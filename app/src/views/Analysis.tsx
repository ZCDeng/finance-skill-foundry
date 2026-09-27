import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowUp, FilePlus2, MessageSquare, RefreshCw } from 'lucide-react';
import { bridge, shortSha, when, type Answer, type AnalysisDraft, type AnalysisState, type DatasetSnapshot, type FinanceDrilldown,
  type TaskRow } from '../bridge.js';
import './analysis.css';
import { STATUS, textValue } from './analysis/presentation.js';
import { RunPanel } from './analysis/RunPanel.js';
import { runPresentationRole } from './analysis/businessResults.js';
import { AnalysisScopeCard } from './analysis/AnalysisScopeCard.js';
import { WorkbookOverview } from './analysis/WorkbookOverview.js';
import { ReadinessPanel } from './analysis/ReadinessPanel.js';
import { readCopy, removeCopy, writeCopy } from './analysis/workingCopy.js';
import { SearchableSelect } from '../components/FinancialControls.js';
import { Button } from '../components/ui/button.js';
import { Textarea } from '../components/ui/textarea.js';
import { Tabs, TabsList, TabsTrigger } from '../components/ui/tabs.js';
import { DatasetPreview } from './analysis/DatasetPreview.js';
import { StructurePanel } from './analysis/StructurePanel.js';
import { SourceRefreshPanel } from './analysis/SourceRefreshPanel.js';
import { WorkbookPanel } from './analysis/WorkbookPanel.js';
import { FinanceWorkbench, type FinanceOutcome, type ScopeRequest } from './analysis/FinanceWorkbench.js';
import { AnalysisEditor, type AnalysisEdit } from './analysis/AnalysisEditor.js';
import { DraftEditor, type DraftEdit } from './analysis/DraftEditor.js';
import { Methods } from './analysis/Methods.js';
import { datasetSize, structureLabel, unwrap } from './analysis/shared.js';

type Tab = 'datasets' | 'results' | 'drafts' | 'methods';
type Selection = { analysis?: string; draft?: string };
export type AnalysisSection = 'materials' | 'results' | 'drafts' | 'methods';
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
};
const TABS: [Tab, string][] = [['datasets', '资料'], ['results', '分析结果'], ['drafts', '文稿'], ['methods', '方法']];
const EXAMPLES = ['本月利润为什么没有达到预算？', '哪些客户需要优先跟进回款？', '回款晚两周，现金余额会怎样？'];

/** All figures are rendered as received. In particular, Decimal strings never pass through Number. */
export function Analysis({ task, tasks, active: visible = true, embedded = false, section, onSectionChange, onPick, onNew, onChat, onLocatorPreview }: Props) {
  const [state, setState] = useState<AnalysisState | null>(null);
  const [tab, setTab] = useState<Tab>('datasets');
  const [question, setQuestionState] = useState(() => readCopy<string>(`${task?.id ?? 'new'}:question`) ?? '');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [dataset, setDataset] = useState<{ source: DatasetSnapshot; content: Record<string, unknown> } | null>(null);
  const [selectedAnalysis, setSelectedAnalysis] = useState<string | null>(null);
  const [selectedDraft, setSelectedDraft] = useState<string | null>(null);
  const [scopeRequest, setScopeRequest] = useState<ScopeRequest>({ count: 0 });
  // Held here, not in the workbench: it unmounts when the tab changes, and a run
  // it started keeps going. One entry per task, so a run in another task neither
  // shows here nor unlocks this one.
  const [financeRunning, setFinanceRunning] = useState<Record<string, string>>({});
  // How the last one ended, kept here and per task for the same reasons.
  const [financeOutcome, setFinanceOutcome] = useState<Record<string, FinanceOutcome>>({});
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
  const chooseTab = useCallback((next: Tab) => {
    setTab(next);
    onSectionChange?.(next === 'datasets' ? 'materials' : next);
  }, [onSectionChange]);
  useEffect(() => { if (section) setTab(section === 'materials' ? 'datasets' : section); }, [section]);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  const refresh = useCallback(async (taskId: string) => {
    // A completed operation may belong to a task the manager has left. It must
    // not invalidate an in-flight read for the newly selected task.
    if (currentTask.current !== taskId) return;
    const request = ++readVersion.current;
    const api = bridge();
    if (!api?.analysisState) throw new Error('此版本未连接分析服务。资料与成果尚未读取。');
    const value = unwrap(await api.analysisState(taskId));
    if (active.current && currentTask.current === taskId && request === readVersion.current) setState(value);
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
    setTab(section ? section === 'materials' ? 'datasets' : section : 'datasets');
    if (!task) return;
    const taskId = task.id;
    setLoading(true);
    void refresh(taskId).catch((failure: unknown) => {
      if (active.current && currentTask.current === taskId) setError(String(failure instanceof Error ? failure.message : failure));
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
    void refresh(taskId).catch((failure: unknown) => {
      if (active.current && currentTask.current === taskId) setError(failure instanceof Error ? failure.message : String(failure));
    }).finally(() => { if (active.current && currentTask.current === taskId) setLoading(false); });
  }, [visible, task?.id, refresh]);
  useEffect(() => {
    if (!visible || !task) return;
    const taskId = task.id;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      if (!operation.current && document.visibilityState !== 'hidden') {
        try { await refresh(taskId); }
        catch { /* Keep the last readable results. Explicit refresh reports actionable failures. */ }
      }
      if (!cancelled) timer = setTimeout(() => void poll(), 5000);
    };
    timer = setTimeout(() => void poll(), 5000);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [visible, task?.id, refresh]);

  async function perform(work: (taskId: string) => Promise<void>) {
    if (!task || operation.current) return;
    const taskId = task.id;
    operation.current = true; setBusy(true); setError(''); setNotice('');
    try { await work(taskId); }
    catch (failure) {
      if (active.current && currentTask.current === taskId) setError(failure instanceof Error ? failure.message : String(failure));
    } finally { operation.current = false; if (active.current) setBusy(false); }
  }
  async function addFiles(taskId: string) {
    const api = bridge();
    if (!api?.analysisAddFiles) throw new Error('此版本暂不支持添加分析资料。');
    const added = unwrap(await api.analysisAddFiles(taskId));
    await refresh(taskId);
    if (currentTask.current === taskId) {
      chooseTab('datasets');
      if (added.length) setNotice(`已加入 ${added.length} 份资料。可以继续提问。`);
    }
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
      if (currentTask.current === pending.taskId) setError(failure instanceof Error ? failure.message : String(failure));
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
    catch (failure) { pendingStart.current = null; setError(failure instanceof Error ? failure.message : String(failure)); }
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
    catch (failure) { if (active.current) setError(failure instanceof Error ? failure.message : String(failure)); }
    finally { operation.current = false; if (active.current) setBusy(false); }
  }
  const view = state?.task_id === task?.id ? state : null;
  const referencedRuns = view?.drafts.at(-1)?.run_ids ?? [];
  const lastSuccessful = view && (referencedRuns.map((id) => view.runs.find((run) => run.id === id && runPresentationRole(run) === 'business')).find(Boolean)
    ?? [...view.runs].reverse().find((row) => runPresentationRole(row) === 'business')
    ?? [...view.runs].reverse().find((row) => row.execution_status === 'succeeded' || row.execution_status === 'success'));
  const analysis = view?.analyses.find((row) => row.id === selectedAnalysis)
    ?? view?.analyses.find((row) => row.id === lastSuccessful?.analysis_id) ?? view?.analyses.at(-1);
  const draft = view?.drafts.find((row) => row.id === selectedDraft) ?? view?.drafts.at(-1);
  selectionNow.current = { analysis: analysis?.id, draft: draft?.id };
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
  const financeWorkbench = task && view && view.datasets.length > 0
    ? <FinanceWorkbench key={`${task.id}:finance`} taskId={task.id} datasets={view.datasets} runs={view.runs} busy={busy}
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
      onRefresh={() => refresh(task.id)} />
    : null;
  const counts: Record<Tab, number> = { datasets: view?.datasets.length ?? 0, results: view?.runs.filter((run) => runPresentationRole(run) === 'business').length ?? 0,
    drafts: view?.drafts.length ?? 0, methods: view?.methods.length ?? 0 };
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
        <p className="analysis-note">{task ? '补充资料、调整口径，继续推进这项分析。' : '带上手头资料，比较数字，形成你的判断。'}</p></div>
      {tasks.length > 0 && <div className="analysis-task-controls"><SearchableSelect label="切换任务" ariaLabel="切换分析任务"
        value={task?.id ?? ''} disabled={busy} options={tasks.map((row) => ({ value: row.id, label: row.title, meta: when(row.created_at) }))}
        onChange={onPick} placeholder="搜索任务" />{task && <Button variant="outline" type="button" disabled={busy} onClick={() => onPick('')}>新建分析任务</Button>}</div>}
    </header>}
    {(!embedded || !task || question) && <form className="analysis-composer" onSubmit={(event) => {
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
      <Tabs value={tab} onValueChange={(value) => chooseTab(value as Tab)} activationMode="manual">
      <div className="analysis-tabbar"><TabsList variant="line" className="analysis-tabs" aria-label="任务工作区">
        {TABS.filter(([id]) => !embedded || id !== 'methods').map(([id, title], index, tabs) => (
          <TabsTrigger key={id} id={`analysis-tab-${id}`} value={id} onClick={() => chooseTab(id)}
            onKeyDown={(event) => {
              if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
              event.preventDefault();
              const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1
                : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
              chooseTab(tabs[next][0]); document.getElementById(`analysis-tab-${tabs[next][0]}`)?.focus();
            }}>{title}<span>{counts[id]}</span></TabsTrigger>
        ))}
      </TabsList><Button variant="outline" type="button" disabled={busy || loading} onClick={() => void perform(refresh)}>
        <RefreshCw size={13} aria-hidden />刷新</Button></div></Tabs>
      <section role="tabpanel" id={`analysis-panel-${tab}`} aria-labelledby={embedded && tab === 'methods' ? undefined : `analysis-tab-${tab}`}
        aria-label={embedded && tab === 'methods' ? '方法库' : undefined} className="analysis-content">
        {loading && <p role="status" className="analysis-note">正在读取任务资料与成果…</p>}
        {view && tab === 'datasets' && <>
          {embedded && <div className="analysis-section-heading"><h3>任务资料</h3>{view.datasets.length > 0
            ? <Button variant="outline" type="button" disabled={busy} onClick={() => void perform(addFiles)}><FilePlus2 size={15} aria-hidden />添加资料</Button> : null}</div>}
          {!view.datasets.length && <Empty title="把手头的资料加进来" body="添加文件，或先和助手说口径。"
            onAddFiles={embedded ? () => void perform(addFiles) : undefined}
            onChat={() => void chat(question.trim() || undefined)} />}
          {/* What these files can answer and what still waits on the manager, then the files, then the settings. */}
          <ReadinessPanel taskId={task.id} refreshKey={view.datasets} />
          <StructurePanel taskId={task.id} datasets={view.datasets} busy={busy} onRefresh={() => refresh(task.id)} />
          <div className="analysis-source-list">{view.datasets.map((source) => <button key={source.id} className="fnd-card"
            type="button" onClick={() => void perform(async (taskId) => {
              const api = bridge(); if (!api?.analysisReadDataset) throw new Error('此版本暂不支持资料预览。');
              const content = unwrap(await api.analysisReadDataset(taskId, source.id));
              if (currentTask.current === taskId) setDataset({ source, content });
            })} disabled={busy}>
            <span className="fnd-title">{source.name}</span><span className="analysis-source-meta">
              {{ table: '数据表', background: '背景资料', workbook: 'Excel 工作簿' }[source.kind] ?? source.kind}{datasetSize(source) ? ` · ${datasetSize(source)}` : ''} · {when(source.created_at)}{structureLabel(source) ? ` · ${structureLabel(source)}` : ''}</span>
            <span className="analysis-note">{['period', 'unit', 'currency'].filter((key) => source.metadata?.[key] != null)
              .map((key) => textValue(source.metadata[key])).join(' · ') || '查看内容与来源'}</span>
          </button>)}</div>
          {dataset && <DatasetPreview source={dataset.source} content={dataset.content} />}
          {bridge()?.financeCall && view.datasets.length > 0 && <AnalysisScopeCard taskId={task.id} question={task.title} datasets={view.datasets}
            disabled={busy} onSaved={() => void refresh(task.id)} />}
          <WorkbookOverview taskId={task.id} datasets={view.datasets} />
          <SourceRefreshPanel taskId={task.id} busy={busy} onRefresh={() => refresh(task.id)} />
          <details className="analysis-details"><summary>写回 Excel</summary>
            <WorkbookPanel taskId={task.id} datasets={view.datasets} runs={view.runs} busy={busy} contextId={[...view.runs].reverse().find((run) => run.finance_context_id)?.finance_context_id} />
          </details>
        </>}
        {view && tab === 'results' && <>
          {!analysis && financeWorkbench}
          {selectedAnalysis && view.analyses.at(-1)?.id !== selectedAnalysis && <p className="analysis-note">当前正在查看选定版本。可在分析版本中查看其他结果，工作副本会保留。</p>}
          {!analysis ? <Empty title="从资料到可检查的结果" body="提出比较口径后，结果和依据会出现在这里。"
            onChat={() => void chat(question.trim() || undefined)} /> : <>
            <div className="analysis-select-label"><SearchableSelect label="分析版本" value={analysis.id}
              triggerText={`第 ${view.analyses.findIndex((row) => row.id === analysis.id) + 1} 版（共 ${view.analyses.length} 版）· ${when(analysis.created_at)}`}
              options={[...view.analyses].reverse().map((row) => ({ value: row.id, label: row.question, meta: `第 ${view.analyses.indexOf(row) + 1} 版 · ${when(row.created_at)} · ${shortSha(row.id)}` }))}
              onChange={setSelectedAnalysis} placeholder="搜索问题、时间或版本号" /></div>
            <RunPanel key={task.id} analysis={analysis} analyses={view.analyses} runs={view.runs} drafts={view.drafts} datasets={view.datasets} busy={busy}
              onPick={setSelectedAnalysis} onChat={(prompt) => void chat(prompt)}
              onAdjustScope={financeWorkbench ? (run) => setScopeRequest((value) => ({ count: value.count + 1, contextId: run.finance_context_id ?? undefined })) : undefined}
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
              }} />
            {dataset && <section aria-label="依据资料预览"><div className="analysis-section-heading"><h3>依据资料</h3>
              <Button variant="outline" type="button" onClick={() => setDataset(null)}>关闭资料预览</Button></div>
              <DatasetPreview source={dataset.source} content={dataset.content} /></section>}
            {analysis.sql ? <AnalysisEditor key={`${task.id}:${analysis.id}`} analysis={analysis} datasets={view.datasets} busy={busy}
              edit={analysisEdits.current.get(analysisKey) ?? readCopy<AnalysisEdit>(analysisKey)} onEdit={rememberAnalysis}
              onChat={(spec) => void perform(async (taskId) => {
                let id = analysis.id;
                if (spec) {
                  const api = bridge(); if (!api?.analysisSave) throw new Error('此版本暂不支持保存分析。');
                  const next = unwrap(await api.analysisSave(taskId, spec)); id = next.id;
                  analysisEdits.current.delete(analysisKey); removeCopy(analysisKey);
                  await refresh(taskId); if (currentTask.current === taskId && selectionNow.current.analysis === analysis.id) setSelectedAnalysis(id);
                }
                await handoff(`请调整分析「${analysis.question}」的口径或假设。先读取分析版本 ${id}，保留之前结果。`, undefined, { targetTaskId: taskId });
              })} onSave={(spec) => void perform(async (taskId) => {
                const api = bridge(); if (!api?.analysisSave || !api.analysisRun) throw new Error('此版本暂不支持保存并运行分析。');
                const next = unwrap(await api.analysisSave(taskId, spec));
                analysisEdits.current.delete(analysisKey); removeCopy(analysisKey);
                if (currentTask.current === taskId && selectionNow.current.analysis === analysis.id) setSelectedAnalysis(next.id);
                // Save and run are distinct records; refresh the saved definition even if execution fails.
                try { unwrap(await api.analysisRun(taskId, next.id)); } finally { await refresh(taskId); }
              })} onRun={() => void perform(async (taskId) => {
                const api = bridge(); if (!api?.analysisRun) throw new Error('此版本暂不支持计算。');
                try { unwrap(await api.analysisRun(taskId, analysis.id)); } finally { await refresh(taskId); }
              })} /> : <div className="analysis-definition"><h3>{analysis.question}</h3>
                <p className="analysis-note">{analysis.engine === 'structured_aggregate' ? '这项分析按已保存的筛选、分组和汇总规则计算，来源与剔除记录可在结果中查看。' : '这项分析使用脚本计算。输入资料、代码和实际输出保留在运行记录中。'}</p>
                {analysis.assumptions.length > 0 && <p>假设：{analysis.assumptions.map(textValue).join('；')}</p>}
                <details className="analysis-details"><summary>{analysis.engine === 'structured_aggregate' ? '高级：查看汇总规则' : '高级：查看计算脚本'}</summary><pre className="analysis-source-text">{analysis.engine === 'structured_aggregate' ? JSON.stringify(analysis.aggregate_plan, null, 2) : analysis.code}</pre></details>
                <Button variant="outline" type="button" disabled={busy} onClick={() => void chat(`请读取${analysis.engine === 'structured_aggregate' ? '结构化汇总' : '脚本'}分析版本 ${analysis.id}，继续调整或重跑，保存新的运行记录。`)}>调整或重跑此分析</Button>
              </div>}

          </>}
          {analysis && financeWorkbench}
        </>}
        {view && tab === 'drafts' && <>
          <DraftEditor key={draftKey} taskId={task.id} draft={draft} drafts={view.drafts} busy={busy} runs={view.runs} datasets={view.datasets}
            onAppliedDraft={(next) => void perform(async (taskId) => { await refresh(taskId); if (next.id) setSelectedDraft(next.id); })}
            onLocatorPreview={onLocatorPreview}
            versionPicker={view.drafts.length > 0 ? <SearchableSelect label="文稿版本" compact value={draft?.id ?? ''}
              triggerText={draft ? `修订 ${view.drafts.findIndex((row) => row.id === draft.id) + 1}${draft.id === view.drafts.at(-1)?.id ? ' · 最新' : ''}` : '选择文稿'}
              options={[...view.drafts].reverse().map((row) => ({
                value: row.id ?? '', label: `修订 ${view.drafts.findIndex((item) => item.id === row.id) + 1} · ${row.title}`,
                meta: `${STATUS[row.publication_status] ?? row.publication_status} · ${when(row.created_at)} · ${row.id ? shortSha(row.id) : '未保存'}`,
              }))} onChange={setSelectedDraft} placeholder="搜索标题、状态或版本号" /> : undefined}
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
        </>}
        {view && tab === 'methods' && <Methods state={view} busy={busy} onApply={(methodId, bindings, parameters) => void perform(async (taskId) => {
            const api = bridge(); if (!api?.analysisMethodApply) throw new Error('此版本暂不支持复用方法。');
            const next = unwrap(await api.analysisMethodApply(taskId, methodId, bindings, parameters)); await refresh(taskId);
            if (currentTask.current === taskId) { setSelectedAnalysis(next.id); chooseTab('results'); setNotice('已生成分析版本，可以调整口径后运行。'); }
          })} />}
      </section>
    </>}
  </div>;
}

function Empty({ title, body, onAddFiles, onChat }: { title: string; body: string; onAddFiles?(): void; onChat(): void }) {
  return <div className="analysis-empty"><h3>{title}</h3><p>{body}</p><div className="analysis-actions">
    {onAddFiles ? <Button type="button" onClick={onAddFiles}><FilePlus2 size={14} aria-hidden />添加资料</Button> : null}
    <Button variant="outline" type="button" onClick={onChat}>
      <MessageSquare size={14} aria-hidden />与助手讨论</Button>
  </div></div>;
}

function sourceFormatLabel(format: 'docx' | 'pdf' | 'html' | 'md' | 'xlsx'): string {
  return ({ docx: 'Word', pdf: 'PDF', html: 'HTML', md: '文稿', xlsx: '工作簿' } as Record<typeof format, string>)[format];
}
