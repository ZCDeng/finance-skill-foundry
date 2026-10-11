import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { ArrowUp, FilePlus2, MessageSquare, RefreshCw } from 'lucide-react';
import { bridge, timeWait, when, type Answer, type AnalysisDraft, type AnalysisRevision, type AnalysisRun, type AnalysisState, type DatasetSnapshot, type FinanceDrilldown,
  type TaskRow } from '../bridge.js';
import './analysis.css';
import { STATUS, assumptionSummary, textValue } from './analysis/presentation.js';
import { RunPanel } from './analysis/RunPanel.js';
import { isBudgetAlias, isSuccessfulRun, runPresentationRole } from './analysis/businessResults.js';
import { ScopePanel } from './analysis/ScopePanel.js';
import { useAnalysisScope } from './analysis/scope.js';
import { WorkbookOverview } from './analysis/WorkbookOverview.js';
import { ReadinessPanel, useReadiness } from './analysis/ReadinessPanel.js';
import { MonthCloseControlCenter, type CloseTarget } from './analysis/MonthCloseControlCenter.js';
import { AskLink, HelpLink } from './guide/GuideHub.js';
import { readCopy, removeCopy, writeCopy } from './analysis/workingCopy.js';
import { SearchableSelect } from '../components/FinancialControls.js';
import { Button } from '../components/ui/button.js';
import { Textarea } from '../components/ui/textarea.js';
import { DatasetPreview } from './analysis/DatasetPreview.js';
import { DashboardView, useDashboard, type BoardTour } from './analysis/Dashboard.js';
import { MonthBrief } from './analysis/MonthBrief.js';
import { formatPeriod } from '../lib/period.js';
import { DashboardPinContext } from './analysis/dashboardModel.js';
import { MaterialsFileList, materialsAnchor } from './analysis/MaterialsFileList.js';
import { SourceRefreshPanel } from './analysis/SourceRefreshPanel.js';
import { BillingPanel } from './analysis/BillingPanel.js';
import { WorkbookPanel } from './analysis/WorkbookPanel.js';
import { RollforwardPanel } from './analysis/RollforwardPanel.js';
import { FinanceWorkbench, type FinanceOutcome, type ScopeRequest } from './analysis/FinanceWorkbench.js';
import { FinanceChartPanel } from './analysis/FinanceChartPanel.js';
import { SettingsGroup, SettingsPanel, useSettingsPanel } from './analysis/SettingsPanel.js';
import { AnalysisEditor, type AnalysisEdit } from './analysis/AnalysisEditor.js';
import { DraftEditor, type DraftEdit } from './analysis/DraftEditor.js';
import { Methods } from './analysis/Methods.js';
import { unwrap, errorText } from './analysis/shared.js';
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from '../components/ui/empty.js';
import { DisclosureSummary } from '../components/Disclosure.js';
import { Technical, usePreferences } from '../components/Preferences.js';
import { Loading, SkeletonCards, SkeletonRows } from '../components/Loading.js';
import { ReportNav, StepIntro, StepNav, StepNext } from './analysis/StepNav.js';
import { isOperationsAnalysis, isReportView, isSkippable, nextStep, sectionOf, stepOf, stepStates, type AnalysisSection, type ReportView, type SkippableStep } from './analysis/steps.js';
import { isCollectionHealthRun } from './analysis/CollectionHealthView.js';

type Selection = { analysis?: string; draft?: string };
export type { AnalysisSection } from './analysis/steps.js';
export type AnalysisChatOptions = { submit?: boolean; requestId?: string; targetTaskId?: string };
type Props = {
  task: TaskRow | null;
  tasks: TaskRow[];
  active?: boolean;
  embedded?: boolean;
  section?: AnalysisSection;
  onSectionChange?(section: AnalysisSection): void;
  onPick(id: string): void;
  onNew(question: string): void | Promise<string | void>;
  onChat(question?: string, draftId?: string, options?: AnalysisChatOptions): void | Promise<void>;
  onLocatorPreview?(preview: import('../bridge.js').LocatorPreviewSpec): void;
  /** 成果库 asks for one draft version of a task; a new count is a new request. */
  draftRequest?: { count: number; taskId: string; draftId: string };
  /** Go to where a line of 本月三句话 is handled, as a 总览 to-do goes there: the step, then the block on it. */
  onOpenTarget?(target: string): void;
  /** 60 秒看看它能做什么 is walking this task's board. */
  tour?: BoardTour;
  /** This task's month-close blocks as 总览 last read them: the first three steps' states come from these. */
  progress?: import('../bridge.js').OverviewTask;
};
/** Each place's own 使用指南 article, opened from the 「?」 beside 刷新. */
const PAGE_ARTICLES: Partial<Record<AnalysisSection, [article: string, label: string]>> = {
  materials: ['page-datasets', '「资料」这一步有什么'], scope: ['scope', '分析范围与期间'], close: ['page-close', '「勾稽」这一步有什么'],
  results: ['page-results', '「财务分析」这一步有什么'], operations: ['collection-health', '回款与现金：生死线、应收天数和风险雷达'],
  dashboard: ['page-dashboard', '看板：经营看板、一页纸与汇报模式'], drafts: ['page-drafts', '「文稿」有什么'], workbook: ['excel-writeback', '写回 Excel：预览后生成新工作簿'],
};
const EXAMPLES = ['本月利润为什么没有达到预算？', '哪些客户需要优先跟进回款？', '回款晚两周，现金余额会怎样？'];

/** All figures are rendered as received. In particular, Decimal strings never pass through Number. */
export function Analysis({ task, tasks, active: visible = true, embedded = false, section, onSectionChange, onPick, onNew, onChat, onLocatorPreview, draftRequest, onOpenTarget, tour, progress }: Props) {
  const [state, setState] = useState<AnalysisState | null>(null);
  const [place, setPlace] = useState<AnalysisSection>('materials');
  // 汇报 opens on whichever of its three was last open.
  const lastReport = useRef<ReportView>('dashboard');
  const [question, setQuestionState] = useState(() => readCopy<string>(`${task?.id ?? 'new'}:question`) ?? '');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [dataset, setDataset] = useState<{ source: DatasetSnapshot; content: Record<string, unknown> } | null>(null);
  const [selectedAnalysis, setSelectedAnalysis] = useState<string | null>(null);
  const [selectedDraft, setSelectedDraft] = useState<string | null>(null);
  const handledDraftRequest = useRef(0);
  useEffect(() => {
    if (!draftRequest || draftRequest.count === handledDraftRequest.current || draftRequest.taskId !== task?.id) return;
    handledDraftRequest.current = draftRequest.count;
    setSelectedDraft(draftRequest.draftId);
  }, [draftRequest, task?.id]);
  const [scopeRequest, setScopeRequest] = useState<ScopeRequest>({ count: 0 });
  const [scopeRefresh, setScopeRefresh] = useState({ version: 0, quiet: false });
  const [materialsRefresh, setMaterialsRefresh] = useState(0);
  // The collection run a card in the conversation asked to open on the 收费明细 panel.
  const [billingShow, setBillingShow] = useState<{ id: string; count: number } | undefined>(undefined);
  // Bumped when a card in the conversation opens a run: RunPanel reads the kept run only when it mounts.
  const [runOpens, setRunOpens] = useState(0);
  // One scope per task, edited from the 资料 page and the finance settings alike.
  const analysisScope = useAnalysisScope(task?.id, task?.title ?? '', state?.datasets ?? [], scopeRefresh.version, scopeRefresh.quiet);
  // Held here, not in the workbench: it unmounts when the tab changes, and a run
  // it started keeps going. One entry per task, so a run in another task neither
  // shows here nor unlocks this one.
  const [financeRunning, setFinanceRunning] = useState<Record<string, string>>({});
  // How the last one ended, kept here and per task for the same reasons.
  const [financeOutcome, setFinanceOutcome] = useState<Record<string, FinanceOutcome>>({});
  // The task's board, read here so 钉到看板 on the result page and the 看板 tab change the same one. Opening the
  // task recomputes the cards whose files have newer versions; the task is read again to draw the new runs.
  const board = useDashboard(task?.id, {
    canRecompute: Boolean(bridge()?.financeCall) && !(task?.lifecycle_status && task.lifecycle_status !== 'active'),
    onRecomputed: () => { if (task) void refresh(task.id); },
  });
  const currentTask = useRef(task?.id);
  currentTask.current = task?.id;
  const active = useRef(true);
  const previousVisibility = useRef({ visible, taskId: task?.id });
  const operation = useRef(false);
  const readVersion = useRef(0);
  const pendingStart = useRef<{ question: string; withFiles: boolean; requestId: string; taskId?: string; resolved?: boolean } | null>(null);
  const submission = useRef<{ question: string; requestId: string; taskId?: string; submit: boolean } | null>(null);
  const analysisEdits = useRef(new Map<string, AnalysisEdit>());
  const draftEdits = useRef(new Map<string, DraftEdit>());
  const selectionNow = useRef<{ analysis?: string; draft?: string }>({});
  function setQuestion(value: string) {
    writeCopy(`${currentTask.current ?? 'new'}:question`, value);
    setQuestionState(value);
  }
  /** Open a step or a place in one; a name from elsewhere (总览, the guide, a card) is read as sectionOf reads it. */
  const choose = useCallback((target: string) => {
    const next = target === 'report' ? lastReport.current : sectionOf(target);
    if (isReportView(next)) lastReport.current = next;
    setPlace(next);
    onSectionChange?.(next);
  }, [onSectionChange]);
  useEffect(() => {
    if (!section) return;
    const next = sectionOf(section);
    if (isReportView(next)) lastReport.current = next;
    setPlace(next);
  }, [section]);
  const step = stepOf(place);
  // The assistant may have proposed a card since the board was read.
  useEffect(() => { if (place === 'dashboard') void board.load().catch(() => undefined); }, [place, board.load]);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  const refresh = useCallback(async (taskId: string, options?: { scope?: boolean | 'quiet' }) => {
    // A completed operation may belong to a task the manager has left. It must
    // not invalidate an in-flight read for the newly selected task.
    if (currentTask.current !== taskId) return;
    const request = ++readVersion.current;
    const api = bridge();
    if (!api?.analysisState) throw new Error('此版本未连接分析服务。资料与成果尚未读取。');
    const value = unwrap(await api.analysisState(taskId));
    if (active.current && currentTask.current === taskId && request === readVersion.current) {
      setState(value);
      if (options?.scope) setScopeRefresh(({ version }) => ({ version: version + 1, quiet: options.scope === 'quiet' }));
      window.dispatchEvent(new Event('fnd:task-changed'));
    }
  }, []);
  useEffect(() => {
    const selection = readCopy<Selection>(`${task?.id}:selection`);
    setState(null); setDataset(null); setSelectedAnalysis(selection?.analysis ?? null); setSelectedDraft(selection?.draft ?? null);
    setError(''); setNotice('');
    const pending = pendingStart.current;
    if (task && pending?.resolved && (!pending.taskId || pending.taskId === task.id)) {
      pending.taskId = task.id;
      writeCopy(`${task.id}:question`, pending.question);
      removeCopy('new:question');
    }
    setQuestionState(readCopy<string>(`${task?.id ?? 'new'}:question`) ?? '');
    setPlace(section ? sectionOf(section) : 'materials');
    if (!task) return;
    const taskId = task.id;
    setLoading(true);
    void refresh(taskId).catch((failure: unknown) => {
      if (active.current && currentTask.current === taskId) setError(errorText(failure));
    }).finally(() => { if (active.current && currentTask.current === taskId) setLoading(false); });
  }, [task?.id, refresh]);
  useEffect(() => {
    const previous = previousVisibility.current;
    previousVisibility.current = { visible, taskId: task?.id };
    // Task changes have their own initial read. Resuming the same mounted
    // workspace must read work performed by the assistant while it was hidden.
    if (!visible || previous.visible || previous.taskId !== task?.id || !task) return;
    const taskId = task.id;
    setLoading(true);
    void refresh(taskId, { scope: 'quiet' }).catch((failure: unknown) => {
      if (active.current && currentTask.current === taskId) setError(errorText(failure));
    }).finally(() => { if (active.current && currentTask.current === taskId) setLoading(false); });
  }, [visible, task?.id, refresh]);
  useEffect(() => {
    if (!visible || !task) return;
    const taskId = task.id;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      if (!operation.current && document.visibilityState !== 'hidden') {
        try { await refresh(taskId, { scope: 'quiet' }); }
        catch { /* Keep the last readable results. Explicit refresh reports actionable failures. */ }
      }
      if (!cancelled) timer = setTimeout(() => void poll(), 5000);
    };
    timer = setTimeout(() => void poll(), 5000);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [visible, task?.id, refresh]);

  async function perform(work: (taskId: string) => Promise<void>, options?: { rethrow?: boolean }) {
    if (!task || operation.current) return;
    const taskId = task.id;
    operation.current = true; setBusy(true); setError(''); setNotice('');
    try { await work(taskId); }
    catch (failure) {
      if (active.current && currentTask.current === taskId) setError(errorText(failure));
      if (options?.rethrow) throw failure;
    } finally { operation.current = false; if (active.current) setBusy(false); }
  }
  // Timed from the click, but main takes off the minutes the file dialog stood open.
  const addFiles = (taskId: string) => timeWait('materials.import', async (note) => {
    const api = bridge();
    if (!api?.analysisAddFiles) throw new Error('此版本暂不支持添加分析资料。');
    const added = unwrap(await api.analysisAddFiles(taskId));
    await refresh(taskId);
    note(added.length ? 'ok' : 'cancelled');
    if (currentTask.current === taskId) {
      choose('materials');
      if (added.length) setNotice(`已加入 ${added.length} 份资料。可以继续提问。`);
    }
  });
  /** Runs a saved analysis and reads the page back even if the run fails; the wait ends after the read-back. */
  async function runSaved(taskId: string, id: string, note: (outcome: 'ok', run: unknown) => void) {
    const api = bridge(); if (!api?.analysisRun) throw new Error('此版本暂不支持计算。');
    try {
      const run = unwrap(await api.analysisRun(taskId, id));
      if (run.execution_status === 'succeeded' || run.execution_status === 'success') note('ok', run);
      else throw new Error(textValue(run.error ?? '计算失败'));
    } finally { await refresh(taskId); }
  }
  useEffect(() => {
    if (busy || operation.current || !pendingStart.current?.taskId) return;
    const pending = pendingStart.current;
    pendingStart.current = null;
    void finishStart(pending as typeof pending & { taskId: string });
  }, [task?.id, busy]);
  async function handoff(prompt: string | undefined, draftId?: string, options?: AnalysisChatOptions) {
    // Preserve the complete working question until the target harness accepts it.
    if (options) await onChat(prompt, draftId, options); else await onChat(prompt, draftId);
    const target = options?.targetTaskId ?? currentTask.current;
    if (prompt && readCopy<string>(`${target ?? 'new'}:question`)?.trim() === prompt) {
      removeCopy(`${target ?? 'new'}:question`);
      if (currentTask.current === target) setQuestionState((value) => value.trim() === prompt ? '' : value);
    }
    if (options?.requestId && submission.current?.requestId === options.requestId) submission.current = null;
  }
  async function finishStart(pending: { question: string; withFiles: boolean; requestId: string; taskId: string }) {
    operation.current = true; setBusy(true);
    try {
      writeCopy(`${pending.taskId}:question`, pending.question); removeCopy('new:question');
      if (currentTask.current === pending.taskId) setQuestionState(pending.question);
      if (pending.withFiles) await addFiles(pending.taskId);
      if (pending.question) await handoff(pending.question, undefined, {
        submit: !pending.withFiles, requestId: pending.requestId, targetTaskId: pending.taskId,
      });
    } catch (failure) {
      if (currentTask.current === pending.taskId) setError(errorText(failure));
    } finally { operation.current = false; if (active.current) setBusy(false); }
  }
  async function create(withFiles = false) {
    if (operation.current) return;
    operation.current = true; setBusy(true); setError('');
    const prompt = question.trim();
    const requestId = submission.current?.question === prompt ? submission.current.requestId : crypto.randomUUID();
    submission.current = { question: prompt, requestId, submit: !withFiles };
    pendingStart.current = { question: prompt, withFiles, requestId };
    try {
      const id = await onNew(prompt || '新的财务分析');
      if (pendingStart.current) {
        pendingStart.current.resolved = true;
        pendingStart.current.taskId = typeof id === 'string' ? id : currentTask.current;
      }
      if (pendingStart.current?.taskId) submission.current.taskId = pendingStart.current.taskId;
    }
    catch (failure) { pendingStart.current = null; setError(errorText(failure)); }
    finally { operation.current = false; if (active.current) setBusy(false); }
  }
  async function chat(prompt?: string, draftId?: string) {
    if (operation.current) return;
    operation.current = true; setBusy(true); setError('');
    try {
      const retry = submission.current;
      await handoff(prompt, draftId, retry && retry.taskId === task?.id && retry.question === prompt
        ? { submit: retry.submit, requestId: retry.requestId, targetTaskId: retry.taskId } : undefined);
    }
    catch (failure) { if (active.current) setError(errorText(failure)); }
    finally { operation.current = false; if (active.current) setBusy(false); }
  }
  const view = state?.task_id === task?.id ? state : null;
  // A newer file came in (added again, refreshed, next month's tables confirmed): the board may have cards to recompute.
  const replacedKey = (view?.superseded_datasets ?? []).join(',');
  const boardLoad = board.load;
  useEffect(() => { if (replacedKey) void boardLoad().catch(() => undefined); }, [replacedKey, boardLoad]);
  // Read while 资料 is open, as the panel did when it lived alone: the summary and each file's row share it.
  const readiness = useReadiness(task && view && place === 'materials' ? task.id : null, view?.datasets);
  // 回款健康 is 经营分析's: its versions and runs show on step 5, every other analysis on 财务分析.
  const operational = useMemo(() => new Set((view?.analyses ?? []).filter((row) => isOperationsAnalysis(row, view?.runs ?? [])).map((row) => row.id)),
    [view?.analyses, view?.runs]);
  const financeAnalyses = view?.analyses.filter((row) => !operational.has(row.id)) ?? [];
  const operationsAnalyses = view?.analyses.filter((row) => operational.has(row.id)) ?? [];
  const financeRuns = view?.runs.filter((run) => !operational.has(run.analysis_id)) ?? [];
  const referencedRuns = view?.drafts.at(-1)?.run_ids ?? [];
  const lastSuccessful = view && (referencedRuns.map((id) => financeRuns.find((run) => run.id === id && runPresentationRole(run) === 'business')).find(Boolean)
    ?? [...financeRuns].reverse().find((row) => runPresentationRole(row) === 'business')
    ?? [...financeRuns].reverse().find((row) => row.execution_status === 'succeeded' || row.execution_status === 'success'));
  const analysis = financeAnalyses.find((row) => row.id === selectedAnalysis)
    ?? financeAnalyses.find((row) => row.id === lastSuccessful?.analysis_id) ?? financeAnalyses.at(-1);
  const operationsAnalysis = operationsAnalyses.find((row) => row.id === selectedAnalysis) ?? operationsAnalyses.at(-1);
  const draft = view?.drafts.find((row) => row.id === selectedDraft) ?? view?.drafts.at(-1);
  selectionNow.current = { analysis: analysis?.id, draft: draft?.id };
  // Read by the card listener, which is set up once.
  const operationalNow = useRef(operational);
  operationalNow.current = operational;
  /** Opens the result a card, 本月三句话 or the board points at, on the step that holds it. */
  const openResult = (run: AnalysisRun) => {
    if (!task) return;
    writeCopy(`${task.id}:run`, run.id);
    setSelectedAnalysis(run.analysis_id);
    setRunOpens((value) => value + 1);
    choose(operational.has(run.analysis_id) || isCollectionHealthRun(run) ? 'operations' : 'results');
  };
  const analysisKey = `${task?.id}:analysis:${analysis?.id}`;
  const draftKey = `${task?.id}:draft:${draft?.id ?? 'new'}`;
  const rememberAnalysis = useCallback((edit: AnalysisEdit) => {
    analysisEdits.current.set(analysisKey, edit);
    writeCopy(analysisKey, edit);
    if (analysis?.id) {
      setSelectedAnalysis(analysis.id);
      writeCopy(`${task?.id}:selection`, { ...readCopy<Selection>(`${task?.id}:selection`), analysis: analysis.id });
    }
  }, [analysisKey, analysis?.id]);
  const rememberDraft = useCallback((edit: DraftEdit) => {
    draftEdits.current.set(draftKey, edit);
    writeCopy(draftKey, edit);
    if (draft?.id) {
      setSelectedDraft(draft.id);
      writeCopy(`${task?.id}:selection`, { ...readCopy<Selection>(`${task?.id}:selection`), draft: draft.id });
    }
  }, [draftKey, draft?.id]);
  const analysisDefinition = (onSaved?: () => void) => analysis ? (analysis.sql ? <AnalysisEditor key={`${task?.id}:${analysis.id}`} analysis={analysis} datasets={view?.datasets ?? []} busy={busy}
    edit={analysisEdits.current.get(analysisKey) ?? readCopy<AnalysisEdit>(analysisKey)} onEdit={rememberAnalysis}
    onChat={(spec) => void perform(async (taskId) => {
      let id = analysis.id;
      if (spec) {
        const api = bridge(); if (!api?.analysisSave) throw new Error('此版本暂不支持保存分析。');
        const next = unwrap(await api.analysisSave(taskId, spec)); id = next.id;
        analysisEdits.current.delete(analysisKey); removeCopy(analysisKey);
        await refresh(taskId); if (currentTask.current === taskId && selectionNow.current.analysis === analysis.id) setSelectedAnalysis(id);
      }
      await handoff(`请调整分析「${analysis.question}」的范围或假设。先读取分析版本 ${id}，保留之前结果。`, undefined, { targetTaskId: taskId });
    })} onSave={(spec) => perform((taskId) => timeWait('analysis.run', async (note) => {
      const api = bridge(); if (!api?.analysisSave || !api.analysisRun) throw new Error('此版本暂不支持保存并运行分析。');
      const next = unwrap(await api.analysisSave(taskId, spec));
      analysisEdits.current.delete(analysisKey); removeCopy(analysisKey);
      if (currentTask.current === taskId && selectionNow.current.analysis === analysis.id) setSelectedAnalysis(next.id);
      // Save and run are distinct records; refresh the saved definition even if execution fails.
      await runSaved(taskId, next.id, note);
    }), { rethrow: true })} onSaved={onSaved} onRun={() => perform((taskId) => timeWait('analysis.run', (note) => runSaved(taskId, analysis.id, note)), { rethrow: true })} /> : <div className="analysis-definition"><h3>计算定义</h3>
      <p className="analysis-note">{definitionCopy(analysis).note}</p>
      {/* Once this version has run, its assumptions are in the result's 计算依据; before that, only here. */}
      {analysis.assumptions.length > 0 && !view?.runs.some((row) => row.analysis_id === analysis.id && isSuccessfulRun(row))
        && <p className="analysis-note">假设：{assumptionSummary(analysis.assumptions)}</p>}
      <Technical><details className="analysis-details"><DisclosureSummary>{definitionCopy(analysis).detailSummary}</DisclosureSummary><pre className="analysis-source-text fnd-scroll-fade">{definitionCopy(analysis).detail}</pre></details></Technical>
      <div className="analysis-actions"><Button variant="outline" type="button" disabled={busy} onClick={() => void chat(`请读取${definitionCopy(analysis).kind}分析版本 ${analysis.id}，继续调整或重跑，保存新的运行记录。`)}>调整或重跑此分析</Button></div>
    </div>) : null;
  const financeWorkbench = task && view && view.datasets.length > 0
    ? <FinanceWorkbench key={`${task.id}:finance`} taskId={task.id} datasets={view.datasets} runs={view.runs} busy={busy} scope={analysisScope}
      comparesBudget={Boolean(analysis && (analysis.operation === 'variance' || Object.keys(analysis.bindings ?? {}).some(isBudgetAlias)))}
      openRequest={scopeRequest} running={financeRunning[task.id] ?? ''} outcome={financeOutcome[task.id]}
      onRunning={(label, active) => setFinanceRunning((current) => {
        if (active) return { ...current, [task.id]: label };
        if (current[task.id] !== label) return current;
        const { [task.id]: _finished, ...rest } = current;
        return rest;
      })}
      onOutcome={(outcome) => setFinanceOutcome((current) => {
        if (outcome) return { ...current, [task.id]: outcome };
        if (!current[task.id]) return current;
        const { [task.id]: _cleared, ...rest } = current;
        return rest;
      })}
      onRefresh={() => refresh(task.id)} onScope={() => choose('scope')}>{(close) => analysisDefinition(close)}</FinanceWorkbench>
    : null;
  /** The snapshot a result's 依据 opened, under the result. */
  const sourcePreview = dataset ? <section aria-label="依据资料预览"><div className="analysis-section-heading"><h3>依据资料</h3>
    <Button variant="outline" type="button" onClick={() => setDataset(null)}>关闭资料预览</Button></div>
    <DatasetPreview source={dataset.source} content={dataset.content} /></section> : null;
  /** One result with its version picker: 财务分析 shows the finance versions, 经营分析 the 回款健康 ones. */
  const resultOf = (shown: AnalysisRevision, list: AnalysisRevision[], onAdjustScope?: (run: AnalysisRun) => void) => !task || !view ? null :
    <RunPanel key={`${task.id}:${runOpens}`} analysis={shown} analyses={view.analyses} runs={view.runs} drafts={view.drafts} datasets={view.datasets} superseded={view.superseded_datasets} busy={busy}
      question={task.title}
      versionPicker={<SearchableSelect label="分析版本" compact value={shown.id}
        triggerText={`第 ${list.findIndex((row) => row.id === shown.id) + 1} 版（共 ${list.length} 版）· ${when(shown.created_at)}`}
        options={[...list].reverse().map((row) => ({ value: row.id, label: row.question, meta: `第 ${list.indexOf(row) + 1} 版 · ${when(row.created_at)}` }))}
        onChange={setSelectedAnalysis} placeholder="搜索问题或时间" />}
      versionNote={selectedAnalysis === shown.id && list.at(-1)?.id !== shown.id ? '当前正在查看选定版本。可在分析版本中查看其他结果，工作副本会保留。' : undefined}
      onPick={setSelectedAnalysis} onChat={(prompt) => void chat(prompt)}
      onAdjustScope={onAdjustScope}
      onOpen={(run, path) => void perform(async (taskId) => {
        const api = bridge(); if (!api?.analysisOpenOutput) throw new Error('此版本暂不支持打开分析文件。');
        unwrap(await api.analysisOpenOutput(taskId, run.id, path));
        if (currentTask.current === taskId) setNotice(`已打开 ${path}。`);
      })}
      onSource={(source) => void perform(async (taskId) => {
        const api = bridge(); if (!api?.analysisReadDataset) throw new Error('此版本暂不支持资料预览。');
        const content = unwrap(await api.analysisReadDataset(taskId, source.id));
        if (currentTask.current === taskId) setDataset({ source, content });
      })}
      onSaveMethod={(id, name) => void perform(async (taskId) => {
        const api = bridge(); if (!api?.analysisMethodSave) throw new Error('此版本暂不支持保存方法。');
        unwrap(await api.analysisMethodSave(taskId, id, name)); await refresh(taskId);
        if (currentTask.current === taskId) setNotice('已保存方法，可在方法库中复用。');
      })}
      onDrilldown={async (run, row, column, section) => {
        const api = bridge(); if (!api?.financeCall) throw new Error('此版本暂不支持查看财务来源行。');
        return unwrap(await api.financeCall(task.id, 'drilldown-fact', {
          run_id: run.id, row, ...(column ? { column } : {}), ...(section ? { section } : {}), offset: 0, limit: 100,
        }) as Answer<FinanceDrilldown>);
      }} />;
  const reportCounts = { dashboard: board.dashboard?.cards.filter((card) => card.state !== 'explore').length ?? 0, drafts: view?.drafts.length ?? 0 };
  const readOnly = Boolean(task?.lifecycle_status && task.lifecycle_status !== 'active');
  const preferences = usePreferences();
  // 本期不做, kept per task in 设置's file: the step stays open, its state reads 本期不做, 下一步 passes it by.
  const skipped: SkippableStep[] = (task && preferences.preferences.skipped_steps[task.id]) || [];
  const states = { ...stepStates({ view, progress: progress?.task.id === task?.id ? progress : undefined, board: board.dashboard, scopeSaved: Boolean(analysisScope.current) }),
    ...Object.fromEntries(skipped.map((item) => [item, 'skipped' as const])) };
  const skip = (target: SkippableStep, on: boolean) => {
    if (!task) return;
    const { [task.id]: _current, ...others } = preferences.preferences.skipped_steps;
    const marked = on ? [...skipped.filter((item) => item !== target), target] : skipped.filter((item) => item !== target);
    void preferences.set({ skipped_steps: marked.length ? { ...others, [task.id]: marked } : others })
      .catch(() => setError('没能保存「本期不做」，请再试一次。'));
  };
  const canPin = Boolean(bridge()?.financeCall) && !readOnly;
  const pinBoard = useMemo(() => (canPin ? { pin: board.pin } : null), [canPin, board.pin]);
  /*
   * A click on a card in the assistant's answer beside this page (dsh-plugin/client.js), for the task on screen only.
   * 打开结果 opens the run the card read; 钉到看板 is the manager's own pin, through the board's own save, so it lands
   * pinned and waits for 认可 like any other.
   */
  useEffect(() => {
    const api = bridge();
    if (!api?.onHarnessCardAction) return;
    return api.onHarnessCardAction((action) => {
      const taskId = currentTask.current;
      if (!taskId || action.taskId !== taskId) return;
      setError(''); setNotice('');
      if (action.action === 'pin') {
        if (!canPin) { setNotice('这项任务现在只能查看，不能往看板上钉卡。'); return; }
        void board.pin({ ...action.card, state: 'pinned' }).then(
          (said) => { if (currentTask.current === taskId) setNotice(said); },
          (failure: unknown) => { if (currentTask.current === taskId) setError(errorText(failure)); });
        return;
      }
      if (action.kind === 'collection') {
        setBillingShow({ id: action.runId, count: Date.now() });
        choose('operations');
        return;
      }
      writeCopy(`${taskId}:run`, action.runId);
      if (action.analysisId) setSelectedAnalysis(action.analysisId);
      setRunOpens((value) => value + 1);
      choose(action.analysisId && operationalNow.current.has(action.analysisId) ? 'operations' : 'results');
      // The assistant may have calculated it after this page last read the task.
      void refresh(taskId).catch(() => undefined);
    });
  }, [board.pin, canPin, choose, refresh]);
  async function saveDraft(taskId: string, spec: Record<string, unknown>): Promise<AnalysisDraft> {
    const api = bridge();
    const recoveryRef = spec.recovery_ref as { operation_id: string; revision: number } | undefined;
    const { recovery_ref: _recoveryRef, ...draftSpec } = spec;
    const usesFinanceRun = (spec.run_ids as unknown[] | undefined)?.some((id) => view?.runs.some((run) => run.id === id && (run.engine === 'finance' || run.engine === 'structured_aggregate')));
    if (recoveryRef && !api?.financeCall) throw new Error('此版本暂不支持恢复保存。');
    if (!api?.analysisDraft && !((usesFinanceRun || recoveryRef) && api?.financeCall)) throw new Error('此版本暂不支持保存文稿。');
    const next = unwrap((recoveryRef && api?.financeCall
      ? await api.financeCall(taskId, 'finance-completion-recover', { ...recoveryRef, draft: draftSpec })
      : usesFinanceRun && api?.financeCall
        ? await api.financeCall(taskId, 'save-explanation-draft', draftSpec)
        : await api!.analysisDraft!(taskId, draftSpec)) as Answer<AnalysisDraft>);
    draftEdits.current.delete(draftKey); removeCopy(draftKey);
    await refresh(taskId);
    if (currentTask.current === taskId) {
      setState((value) => value && value.task_id === taskId
        ? { ...value, drafts: value.drafts.some((row) => row.id === next.id) ? value.drafts : [...value.drafts, next] } : value);
      if (selectionNow.current.draft === draft?.id) setSelectedDraft(next.id);
    }
    return next;
  }

  return <div className="analysis-workspace">
    {!embedded && <header className="analysis-header">
      <div><h2>{task?.title ?? '从一个问题开始'}</h2>
        <p className="analysis-note">{task ? '补充资料、确认范围，继续推进这项分析。' : '带上手头资料，比较数字，形成你的判断。'}</p></div>
      {tasks.length > 0 && <div className="analysis-task-controls"><SearchableSelect label="切换任务" ariaLabel="切换分析任务"
        value={task?.id ?? ''} disabled={busy} options={tasks.map((row) => ({ value: row.id, label: row.title, meta: when(row.created_at) }))}
        onChange={onPick} placeholder="搜索任务" />{task && <Button variant="outline" type="button" disabled={busy} onClick={() => onPick('')}>新建分析任务</Button>}</div>}
    </header>}
    {(!embedded || !task || question) && <form className="analysis-composer fnd-fold-inset" onSubmit={(event) => {
      event.preventDefault(); if ((!task && !question.trim()) || busy) return;
      if (task) void chat(question.trim() || undefined); else void create();
    }}>
      <label htmlFor="analysis-question" className="analysis-question-label">{task ? '接下来想了解什么？' : '你想分析什么？'}</label>
      <Textarea id="analysis-question" className="analysis-question-input" value={question} onChange={(event) => setQuestion(event.target.value)}
        placeholder="例如：华东本月收入达标，利润为什么没有达标？" rows={2} maxLength={6000} />
      <div className="analysis-composer-actions">
        <Button variant="outline" type="button" disabled={busy} onClick={() => {
          if (task) void perform(addFiles); else void create(true);
        }}><FilePlus2 size={15} aria-hidden />添加资料</Button>
        <span className="analysis-formats">CSV · XLSX · JSON · Markdown · TXT</span>
        <Button type="submit" disabled={busy || (!task && !question.trim())}>
          {busy ? '正在处理…' : task ? '继续分析' : '开始分析'}<ArrowUp size={15} aria-hidden /></Button>
      </div>
    </form>}
    {!task && <div className="analysis-examples" aria-label="分析示例">{EXAMPLES.map((example) =>
      <Button variant="outline" type="button" className="h-auto min-h-8 max-w-full shrink whitespace-normal py-1.5 text-left leading-relaxed" key={example} onClick={() => setQuestion(example)}>{example}</Button>)}</div>}
    {error && <p role="alert" className="analysis-message analysis-message--error">{error}</p>}
    {notice && <p role="status" className="analysis-message">{notice}</p>}
    {task && <>
      {view && view.datasets.length > 0 && bridge()?.financeCall ? <MonthBrief taskId={task.id} board={board.dashboard}
        refreshKey={`${view.datasets.length}:${view.runs.length}:${view.drafts.length}:${board.dashboard?.id ?? ''}:${materialsRefresh}`}
        runs={view.runs} analyses={view.analyses} datasets={view.datasets} superseded={view.superseded_datasets ?? []} readOnly={readOnly}
        onOpen={(target) => onOpenTarget ? onOpenTarget(target) : choose(target)}
        onOpenResult={openResult} /> : null}
      <StepNav step={step} states={states} onStep={choose} tools={<>
        {PAGE_ARTICLES[place] ? <HelpLink article={PAGE_ARTICLES[place]![0]} label={PAGE_ARTICLES[place]![1]} /> : null}
        <Button variant="outline" type="button" disabled={busy || loading} onClick={() => {
          // The 5-second read leaves the structure to-dos alone; an explicit 刷新 reads them again too.
          setMaterialsRefresh((count) => count + 1);
          void perform((taskId) => refresh(taskId, { scope: true }));
        }}>
          <RefreshCw size={13} aria-hidden />刷新</Button></>} />
      <DashboardPinContext.Provider value={pinBoard}>
      <section role="tabpanel" id={`analysis-panel-${step}`} aria-labelledby={step === 'methods' ? undefined : `analysis-tab-${step}`}
        aria-label={step === 'methods' ? '方法库' : undefined} className="analysis-content">
        {view && step !== 'methods' ? <StepIntro step={step} states={states} canSkip={preferences.available && !readOnly}
          onSkip={(on) => { if (isSkippable(step)) skip(step, on); }} onScope={() => choose('scope')} /> : null}
        {step === 'report' && isReportView(place) ? <ReportNav view={place} counts={reportCounts} onView={choose} /> : null}
        {/* The first read draws the shape of the step; a refresh over what is already shown keeps the quiet line. */}
        {loading && (view ? <p role="status" className="analysis-note">正在读取任务资料与成果…</p>
          : <Loading label="正在读取任务资料与成果…">{place === 'results' ? <SkeletonCards /> : <SkeletonRows />}</Loading>)}
        {view && place === 'materials' && <>
          <div className="analysis-section-heading"><span className="fnd-with-help"><h3>任务资料</h3><HelpLink article="data-safety" label="资料快照与原文件" /></span>{embedded && view.datasets.length > 0
            ? <Button variant="outline" type="button" disabled={busy} onClick={() => void perform(addFiles)}><FilePlus2 size={15} aria-hidden />添加资料</Button> : null}</div>
          {!view.datasets.length && <AnalysisEmpty title="把手头的资料加进来" body="添加文件，或先和助手说清范围。"
            onAddFiles={embedded ? () => void perform(addFiles) : undefined}
            onChat={() => void chat(question.trim() || undefined)} />}
          {/* What these files can answer and what still waits on the manager, then the files. */}
          <ReadinessPanel taskId={task.id} readiness={readiness} />
          <MaterialsFileList taskId={task.id} datasets={view.datasets} readiness={readiness.report?.datasets} busy={busy} preview={dataset} refreshKey={materialsRefresh}
            onPreview={(source) => void perform(async (taskId) => {
              const api = bridge(); if (!api?.analysisReadDataset) throw new Error('此版本暂不支持资料预览。');
              const content = unwrap(await api.analysisReadDataset(taskId, source.id));
              if (currentTask.current === taskId) setDataset({ source, content });
            })} onClosePreview={() => setDataset(null)} onRefresh={() => refresh(task.id)} />
          <WorkbookOverview taskId={task.id} datasets={view.datasets} />
          <section className="analysis-more-actions" aria-labelledby="analysis-more-actions">
            <div><h3 id="analysis-more-actions">更多操作</h3><p className="analysis-note">换新导出的来源，或用这个月的数起草下月套表。</p></div>
            <SourceRefreshPanel taskId={task.id} busy={busy} onRefresh={() => refresh(task.id)} />
            <details className="analysis-details analysis-rollforward"><DisclosureSummary>滚动到下月</DisclosureSummary>
              <RollforwardPanel taskId={task.id} datasets={view.datasets} runs={view.runs} busy={busy} onApplied={() => refresh(task.id)} />
            </details>
          </section>
        </>}
        {view && place === 'scope' && (bridge()?.financeCall && view.datasets.length > 0
          ? <ScopePanel scope={analysisScope} datasetCount={view.datasets.length} disabled={busy} onSaved={() => void refresh(task.id)} />
          : <AnalysisEmpty title="先把资料加进来" body="资料里写的期间、组织和单位会列在这里，点一下就能采用。"
            onAddFiles={embedded ? () => void perform(addFiles) : undefined} onChat={() => void chat(question.trim() || undefined)} />)}
        {view && place === 'operations' && <>
          <div className="analysis-section-heading"><div><h3>回款与现金</h3><p className="analysis-note">收缴率、清欠和收费明细这些业务上的事放在这一步。</p></div>
            {view.datasets.length && !readOnly ? <AskLink ask="collection-health" label={operationsAnalysis ? '让助手重算回款健康' : '让助手做回款健康分析'} disabled={busy} /> : null}</div>
          {operationsAnalysis ? resultOf(operationsAnalysis, operationsAnalyses) : null}
          {operationsAnalysis && dataset ? sourcePreview : null}
          {bridge()?.billingCall ? <BillingPanel taskId={task.id} period={task.period} refreshKey={materialsRefresh} show={billingShow} onShown={() => setBillingShow(undefined)}
            practice={task.sample === 'practice' || task.sample === 'next_month'} readOnly={readOnly} /> : null}
        </>}
        {view && place === 'workbook' && <WorkbookPanel taskId={task.id} datasets={view.datasets} runs={view.runs} busy={busy}
          contextId={[...view.runs].reverse().find((run) => run.finance_context_id)?.finance_context_id} />}
        {view && place === 'results' && <>
          {!analysis && financeWorkbench}
          {!analysis ? <AnalysisEmpty title="从资料到可检查的结果" body="选好资料、确认范围并计算后，结果和依据会出现在这里。"
            onChat={() => void chat(question.trim() || undefined)}
            asks={view.datasets.length ? <AskLink ask="readiness" label="让助手做资料体检" disabled={busy} /> : undefined} /> : <>
            {resultOf(analysis, financeAnalyses, financeWorkbench ? (run) => setScopeRequest((value) => ({ count: value.count + 1, contextId: run.finance_context_id ?? undefined })) : undefined)}
            {dataset ? sourcePreview : null}
            {!financeWorkbench && analysis ? <AnalysisSettingsFallback>{(close) => analysisDefinition(close)}</AnalysisSettingsFallback> : null}

          </>}
          {analysis && financeWorkbench}
        </>}
        {view && place === 'dashboard' && <DashboardView task={{ id: task.id, title: task.title, period: formatPeriod(task.period) }} state={board} runs={view.runs} analyses={view.analyses} datasets={view.datasets}
          // The run the card reads, not the version's primary one: RunPanel opens on the run kept here.
          superseded={view.superseded_datasets ?? []} readOnly={readOnly} tour={tour} onOpenResult={openResult} />}
        {view && place === 'close' && <MonthCloseControlCenter taskId={task.id} refreshKey={`${view.datasets.length}:${view.runs.length}:${view.drafts.length}`} busy={busy}
          onOpen={(target: CloseTarget) => {
            choose(target);
            // Bring the block asked for into view: the scope card on 范围, the files on 资料.
            if (target === 'scope' || target === 'structure' || target === 'datasets') {
              requestAnimationFrame(() => materialsAnchor(target)?.scrollIntoView?.({ block: 'start' }));
            }
          }} />}
        {view && place === 'drafts' && <>
          <DraftEditor key={draftKey} taskId={task.id} draft={draft} drafts={view.drafts} busy={busy} runs={view.runs} datasets={view.datasets}
            analysisScope={analysisScope}
            onAppliedDraft={(next) => void perform(async (taskId) => { await refresh(taskId); if (next.id) setSelectedDraft(next.id); })}
            onLocatorPreview={onLocatorPreview}
            versionPicker={view.drafts.length > 0 ? <SearchableSelect label="文稿版本" compact value={draft?.id ?? ''}
              triggerText={draft ? `修订 ${view.drafts.findIndex((row) => row.id === draft.id) + 1}${draft.id === view.drafts.at(-1)?.id ? ' · 最新' : ''}` : '选择文稿'}
              options={[...view.drafts].reverse().map((row) => ({
                value: row.id ?? '', label: `修订 ${view.drafts.findIndex((item) => item.id === row.id) + 1} · ${row.title}`,
                meta: `${STATUS[row.publication_status] ?? row.publication_status} · ${when(row.created_at)}${row.id ? '' : ' · 未保存'}`,
              }))} onChange={setSelectedDraft} placeholder="搜索标题或状态" /> : undefined}
            onChat={(spec) => void perform(async (taskId) => {
              const id = spec ? (await saveDraft(taskId, spec)).id : draft?.id;
              await handoff(undefined, id, spec ? { targetTaskId: taskId } : undefined);
            })}
            onDiscussRequirements={(request) => void handoff(`请围绕以下分析要求继续讨论；未保存的调整仍是讨论草案，请结合当前资料判断可执行性。\n${JSON.stringify(request, null, 2)}`, draft?.id)}
            edit={draftEdits.current.get(draftKey) ?? readCopy<DraftEdit>(draftKey)} onEdit={rememberDraft}
            onSave={(spec) => void perform(async (taskId) => {
              await saveDraft(taskId, spec);
              if (currentTask.current === taskId) setNotice('已保存为新的文稿版本。');
            })} onExport={(format, spec, mode) => perform(async (taskId) => {
              const api = bridge(); if (!api?.analysisExport) throw new Error('此版本暂不支持导出文稿。');
              const id = spec ? (await saveDraft(taskId, spec)).id : draft?.id;
              if (!id) throw new Error('请先写下文稿内容。');
              const result = unwrap(await api.analysisExport(taskId, id, format, mode));
              if (currentTask.current === taskId) setNotice(result.cancelled ? '已取消导出。' : `已导出${format === 'xlsx' ? '工作簿' : sourceFormatLabel(format)}${result.path ? `：${textValue(result.path)}` : '。'}`);
            })} />
          {/* A result kept as a chart goes into a draft, so it is archived here, beside the drafts. */}
          {bridge()?.financeCall && view.runs.some((run) => run.execution_status === 'succeeded' || run.execution_status === 'success')
            ? <FinanceChartPanel taskId={task.id} runs={view.runs} busy={busy || Boolean(financeRunning[task.id])} onRefresh={() => refresh(task.id)} /> : null}
        </>}
        {view && place === 'methods' && <Methods state={view} busy={busy} onApply={(methodId, bindings, parameters) => void perform(async (taskId) => {
            const api = bridge(); if (!api?.analysisMethodApply) throw new Error('此版本暂不支持复用方法。');
            const next = unwrap(await api.analysisMethodApply(taskId, methodId, bindings, parameters)); await refresh(taskId);
            if (currentTask.current === taskId) { setSelectedAnalysis(next.id); choose('results'); setNotice('已生成分析版本，可以调整范围后计算。'); }
          })} />}
        {view && step !== 'methods' && step !== 'report' ? <StepNext next={nextStep(step, skipped)} onStep={choose} /> : null}
      </section>
      </DashboardPinContext.Provider>
    </>}
  </div>;
}


function AnalysisSettingsFallback({ children }: { children(close: () => void): ReactNode }) {
  const settings = useSettingsPanel();
  return <SettingsGroup note="自己动手改这次分析的算法：计算定义和高级参数。">
    <SettingsPanel state={settings} label="计算定义与参数">{children(settings.close)}</SettingsPanel>
  </SettingsGroup>;
}

const FINANCE_OPERATION: Record<string, string> = { metric: '损益指标', variance: '差异分析', scenario: '情景测算' };

/** How a saved analysis says what computed it: a script, the saved aggregate rules, or the finance engine. */
function definitionCopy(analysis: AnalysisRevision): { note: string; detailSummary: string; detail: string | undefined; kind: string } {
  if (analysis.engine === 'structured_aggregate') {
    return { note: '这项分析按已保存的筛选、分组和汇总规则计算，来源与剔除记录可在结果中查看。', detailSummary: '高级：查看汇总规则',
      detail: JSON.stringify(analysis.aggregate_plan, null, 2), kind: '结构化汇总' };
  }
  if (analysis.engine === 'finance') {
    const operation = analysis.operation ? FINANCE_OPERATION[analysis.operation] : undefined;
    return { note: `这项分析由财务引擎按已保存的范围计算${operation ? `（${operation}）` : ''}，没有脚本。有来源的结果行可以在「结果行来源」里打开来源行。`,
      detailSummary: '高级：计算定义', detail: JSON.stringify(analysis.finance_spec ?? {}, null, 2), kind: '财务' };
  }
  return { note: '这项分析使用脚本计算。输入资料、代码和实际输出保留在运行记录中。', detailSummary: '高级：查看计算脚本', detail: analysis.code, kind: '脚本' };
}

function AnalysisEmpty({ title, body, onAddFiles, onChat, asks }: { title: string; body: string; onAddFiles?(): void; onChat(): void; asks?: ReactNode }) {
  return <Empty className="analysis-empty"><EmptyHeader><EmptyTitle asChild><h3>{title}</h3></EmptyTitle><EmptyDescription>{body}</EmptyDescription></EmptyHeader>
    <EmptyContent>
      {onAddFiles ? <Button type="button" onClick={onAddFiles}><FilePlus2 size={14} aria-hidden />添加资料</Button> : null}
      <Button variant="outline" type="button" onClick={onChat}>
        <MessageSquare size={14} aria-hidden />与助手讨论</Button>
      {asks ? <p className="analysis-note analysis-empty-asks">{asks}<span>只填进对话框，改好再发送。</span></p> : null}
    </EmptyContent></Empty>;
}

function sourceFormatLabel(format: 'docx' | 'pdf' | 'html' | 'md' | 'xlsx'): string {
  return ({ docx: 'Word', pdf: 'PDF', html: 'HTML', md: '文稿', xlsx: '工作簿' } as Record<typeof format, string>)[format];
}
