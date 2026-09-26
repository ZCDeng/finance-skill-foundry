import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { ArrowUp, ChevronDown, FilePlus2, FileSpreadsheet, MessageSquare, Play, RefreshCw } from 'lucide-react';
import { bridge, shortSha, when, type Answer, type AnalysisDraft, type AnalysisMethod,
  type AnalysisRevision, type AnalysisRun, type AnalysisState, type DatasetSnapshot, type FinanceContext,
  type FinanceContextState, type FinanceDrilldown, type FinanceSourceBatch,
  type TaskRow } from '../bridge.js';
import './analysis.css';
import { Table, RunStatus, STATUS, textValue } from './analysis/presentation.js';
import { RunPanel } from './analysis/RunPanel.js';
import { runPresentationRole } from './analysis/businessResults.js';
import { AnalysisScopeCard } from './analysis/AnalysisScopeCard.js';
import { ClaimBindingRepair } from './analysis/ClaimBindingRepair.js';
import { WorkbookOverview } from './analysis/WorkbookOverview.js';
import { RevisionDiff } from './analysis/RevisionDiff.js';
import { WaitOrb } from '../components/WaitOrb.js';
import { dimensionGaps, EvidenceDimensionList, EvidenceQuality, type EvidenceDimensions, type EvidenceIssue } from './analysis/EvidenceQuality.js';
import { ParameterField } from './analysis/ParameterField.js';
import { PdfComparison, ReportEditor, type ReportDraftDocument } from './analysis/ReportEditor.js';
import { documentFromMarkdown, documentToMarkdown } from '../../electron/reports/format.js';
import { AccountMapEditor } from './analysis/AccountMapEditor.js';
import { ReadinessPanel } from './analysis/ReadinessPanel.js';
import { RequirementsPanel } from './analysis/RequirementsPanel.js';
import { StructurePendingStrip, StructureProposalCard, type StructureProposal } from './analysis/StructureProposalCard.js';
import { readCopy, removeCopy, writeCopy } from './analysis/workingCopy.js';
import { AccountingPeriodInput, DateInput, DecimalInput, FieldShell, MultiSelect, PeriodRangeInput, SearchableSelect, TextField, type SelectOption } from '../components/FinancialControls.js';
import { Button } from '../components/ui/button.js';
import { Input } from '../components/ui/input.js';
import { Textarea } from '../components/ui/textarea.js';
import { Tabs, TabsList, TabsTrigger } from '../components/ui/tabs.js';

type Tab = 'datasets' | 'results' | 'drafts' | 'methods';
type AnalysisEdit = Pick<AnalysisRevision, 'parameters' | 'assumptions' | 'bindings'> & { sql: string };
type MaterialityDenominator = 'baseline_abs' | 'actual_abs' | 'max_abs';
type MaterialityNegativePolicy = 'absolute' | 'signed';
type MaterialityEdit = { absolute: string; relative: string; denominator: MaterialityDenominator; negativePolicy: MaterialityNegativePolicy };
type DraftEdit = { title: string; body: string; limitations: string; review: string; document?: ReportDraftDocument; materiality?: MaterialityEdit; recovery?: FinanceCompletionRecovery | null };
type ReportMode = 'read' | 'edit' | 'print';
interface ExplanationFact {
  id: string; run_id: string; row?: number; column?: string; value?: unknown; display_value?: unknown; label?: string; unit?: string; scope?: Record<string, unknown>; semantics?: Record<string, unknown>;
}
interface ExplanationQuality {
  status?: string; issues?: EvidenceIssue[]; coverage?: unknown; citations?: unknown[];
  status_dimensions?: EvidenceDimensions;
  readability?: { status: 'clear' | 'suggestions'; issues: { code: string; message: string; position?: number }[] };
  checks?: Partial<Record<'numbers' | 'coverage' | 'provenance', { status?: string }>>;
  requirements?: { scope_changed?: boolean; items?: { id: string; label: string; status: string; provenance_status: string }[] };
}
interface ExplanationPreparation { facts?: ExplanationFact[]; required_fact_ids?: string[]; diagnostics?: unknown[]; business_contexts?: FinanceBackground[] }
interface FinanceBackground {
  id?: string; label?: string; text?: string; paragraph?: string; basis?: string; scope?: Record<string, unknown>; effective_from?: string; effective_to?: string; dataset_id?: string; created_at?: string;
}
interface FinanceCompletionRecovery {
  operation_id: string; status: string; revision?: number; title?: string; body?: string; limitations?: string[] | string; run_ids?: string[]; fact_ids?: string[];
  claims?: unknown[]; materiality?: Record<string, unknown>; requirements_id?: string | null; parent_id?: string | null; updated_at?: string;
  evidence_recipes?: Record<string, unknown>[]; consistency_rules?: Record<string, unknown>[]; consistency_sources?: Record<string, unknown>[] | Record<string, unknown>;
  attempt_status?: string | null; validation_error?: { code?: string; message?: string; details?: unknown[] } | null;
}
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
function appendixMarkdownVariants(appendix?: string): string[] {
  const cleanAppendix = appendix?.trim();
  if (!cleanAppendix) return [];
  const canonicalAppendix = documentToMarkdown(documentFromMarkdown(cleanAppendix)).trim();
  return Array.from(new Set([cleanAppendix, canonicalAppendix]));
}
function readableDraftParts(body: string, appendix?: string): { body: string; appendix?: string } {
  const variants = appendixMarkdownVariants(appendix);
  if (!variants.length) return { body };
  const trimmedBody = body.trimEnd();
  const matchedAppendix = variants.find((candidate) => trimmedBody.endsWith(candidate));
  if (!matchedAppendix) return { body };
  return { body: trimmedBody.slice(0, trimmedBody.length - matchedAppendix.length).trimEnd(), appendix: variants[0] };
}
const metricLabel = (value: unknown): string => {
  if (value && typeof value === 'object' && 'name' in value && 'expression' in value
    && typeof value.name === 'string' && typeof value.expression === 'string') {
    return `${value.name}：${value.expression}`;
  }
  return textValue(value);
};
const itemLabel = (value: unknown, index: number) => typeof value === 'object' && value !== null
  ? String((value as Record<string, unknown>).label ?? (value as Record<string, unknown>).name ?? `第 ${index + 1} 项`)
  : `第 ${index + 1} 项`;
const itemValue = (value: unknown) => typeof value === 'object' && value !== null
  ? textValue((value as Record<string, unknown>).value ?? (value as Record<string, unknown>).description ?? value)
  : value == null ? '' : String(value);
function editItem(value: unknown, next: string): unknown {
  if (typeof value !== 'object' || value === null) return next;
  const record = value as Record<string, unknown>;
  return { ...record, ['value' in record ? 'value' : 'description']: next };
}
function unwrap<T>(answer: Answer<T>): T {
  if (!answer.ok) throw new Error(answer.message);
  return answer.value;
}

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
  // it started keeps going. Keyed by task so another task never shows it.
  const [financeRunning, setFinanceRunning] = useState<{ taskId: string; label: string } | null>(null);
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
      openRequest={scopeRequest} running={financeRunning?.taskId === task.id ? financeRunning.label : ''}
      onRunning={(label, active) => setFinanceRunning((current) => active ? { taskId: task.id, label }
        : current?.taskId === task.id && current.label === label ? null : current)}
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
function DatasetPreview({ source, content }: { source: DatasetSnapshot; content: Record<string, unknown> }) {
  const columns = Array.isArray(content.columns) ? content.columns.map((column: unknown) => typeof column === 'string'
    ? { name: column } : column as { name: string; type?: string }) : source.schema ?? [];
  const rows = Array.isArray(content.rows) ? content.rows as Record<string, unknown>[] : [];
  const workbook = content.workbook as { sheets?: { name: string; rows: number; columns: number }[] } | undefined;
  return <article className="analysis-source-preview"><h3>{source.name}</h3>
    <details className="analysis-details"><summary>资料标识</summary><p className="analysis-note">资料版本：{source.id} · 原始摘要：{source.source_hash ?? source.sha256}</p></details>
    {source.kind === 'workbook' && <>
      <p className="analysis-note">已保留完整工作簿及所有工作表。请与助手确定分析范围，封面和标题不会被当作数据表头。</p>
      {Array.isArray(workbook?.sheets) && <Table caption="工作表目录"
        columns={[{ name: '工作表' }, { name: '已用行' }, { name: '已用列' }]}
        rows={workbook.sheets.map((sheet) => ({ 工作表: sheet.name, 已用行: sheet.rows, 已用列: sheet.columns }))} />}
    </>}
    {columns.length > 0 && <Table columns={columns} rows={rows} caption="资料预览" />}
    {typeof content.text === 'string' && <><pre className="analysis-source-text">{content.text.slice(0, 30000)}</pre>
      {content.text.length > 30000 && <p className="analysis-note">当前显示前 30,000 个字符，助手可以继续读取全文。</p>}</>}
    {Boolean(content.truncated) && <p className="analysis-note">当前仅显示部分内容。</p>}
    <details className="analysis-details"><summary>来源与资料口径</summary><p>原始文件：{source.source_name ?? source.name}</p>{Object.entries(source.metadata ?? {}).map(([key, value]) =>
      <p key={key}>{key}：{textValue(value)}</p>)}
      {columns.length > 0 && <p>字段：{columns.map((column) => `${column.name}${column.type ? ` (${column.type})` : ''}`).join('、')}</p>}
    </details></article>;
}

const scopeFields = [
  ['ledger', '账簿'], ['organization', '组织'], ['period', '期间'],
  ['currency', '币种'], ['unit', '单位'], ['scenario', '情景'],
] as const;
const fileDatasets = (datasets: DatasetSnapshot[]) => datasets.filter((source) =>
  String(source.source_name ?? source.filename ?? '').toLowerCase().endsWith('.xlsx')
  || source.metadata?.source_file === 'source.xlsx');
const datasetSize = (source: DatasetSnapshot): string => source.kind === 'workbook'
  ? typeof source.transformation?.sheet_count === 'number' ? `${source.transformation.sheet_count} 张工作表` : ''
  : source.row_count == null ? '' : `${source.row_count} 行`;
const datasetOptions = (datasets: DatasetSnapshot[]): SelectOption[] => datasets.map((source) => ({
  value: source.id,
  label: source.name,
  meta: [source.source_name ?? source.kind, datasetSize(source), shortSha(source.id)].filter(Boolean).join(' · '),
}));
const runOptions = (runs: AnalysisRun[]): SelectOption[] => runs.filter((row) => row.execution_status === 'succeeded').map((row) => ({
  value: row.id,
  label: when(row.created_at),
  meta: shortSha(row.id),
}));
const contextOptions = (finance: FinanceContextState | null): SelectOption[] => finance?.contexts.map((context) => ({
  value: context.id,
  label: context.name,
  meta: Object.entries(context.scopes ?? {}).map(([alias, item]) => `${alias} ${scopeSummary(item)}`).join('；') || shortSha(context.id),
})) ?? [];
const accountMapOptions = (finance: FinanceContextState | null): SelectOption[] => finance?.account_maps.map((item) => ({
  value: String(item.id ?? ''),
  label: textValue(item.name ?? '管理科目映射'),
  meta: shortSha(String(item.id ?? '')),
})).filter((item) => item.value) ?? [];
const aliasOptions = (aliases: string[], context?: FinanceContext): SelectOption[] => aliases.map((alias) => ({
  value: alias,
  label: alias,
  meta: shortSha(context?.bindings[alias] ?? ''),
}));

function scopeSummary(scope: Record<string, unknown> = {}): string {
  return scopeFields.map(([key, label]) => scope[key] ? `${label} ${textValue(scope[key])}` : '').filter(Boolean).join(' · ') || '未限定';
}

function SourceRefreshPanel({ taskId, busy, onRefresh }: { taskId: string; busy: boolean; onRefresh(): Promise<void> }) {
  const [batches, setBatches] = useState<FinanceSourceBatch[]>([]);
  const [scope, setScope] = useState({
    source_id: 'erp-export', tenant_id: 'default', ledger_id: '', organization_id: '', period: '',
    currency: 'CNY', cutoff_at: '', calendar: '', mode: 'snapshot',
  });
  const [product, setProduct] = useState('file');
  const [version, setVersion] = useState('export');
  const [name, setName] = useState('');
  const [policy, setPolicy] = useState<'snapshot_only' | 'business_key'>('snapshot_only');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const load = useCallback(async () => {
    const api = bridge(); if (!api?.financeCall) return;
    const answer = unwrap(await api.financeCall(taskId, 'finance-source-list') as Answer<{ batches: FinanceSourceBatch[] }>);
    setBatches(answer.batches ?? []);
  }, [taskId]);
  useEffect(() => { void load().catch(() => {}); }, [load]);
  async function refreshSource() {
    if (refreshing) return;
    setRefreshing(true);
    try {
      const api = bridge(); if (!api?.financeSourceRefresh) throw new Error('此版本暂不支持刷新财务来源文件。');
      setError(''); setMessage('');
      const cleanScope = Object.fromEntries(Object.entries(scope).filter(([, value]) => value.trim())) as Record<string, string>;
      const result = unwrap(await api.financeSourceRefresh(taskId, {
        product, version, name: name.trim() || undefined, file_identity_policy: policy, scope: cleanScope,
      }));
      if (result.cancelled) { setMessage('已取消刷新。'); return; }
      await onRefresh(); await load();
      const usable = typeof result.effective_dataset_id === 'string' ? result.effective_dataset_id : result.dataset_id;
      const datasetId = typeof usable === 'string' ? shortSha(usable) : '';
      setMessage(typeof result.dataset_id === 'string'
        ? `已发布新来源快照 ${datasetId}。历史结果仍按原快照保留。`
        : '文件内容与已发布快照一致，已保留原结果引用。');
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setRefreshing(false);
    }
  }
  const ready = scope.source_id.trim() && scope.tenant_id.trim() && scope.ledger_id.trim()
    && scope.organization_id.trim() && scope.period.trim() && scope.currency.trim() && scope.cutoff_at.trim();
  return <details className="analysis-source-refresh" aria-label="刷新财务来源">
    <summary><span><span className="analysis-source-refresh-title">更新 ERP 来源</span>
      <span className="analysis-note">已有来源导出变化时，生成新的资料版本；旧运行仍引用旧快照。</span></span>
      <ChevronDown size={16} aria-hidden /></summary>
    <fieldset className="analysis-fieldset" disabled={busy || refreshing}><div className="analysis-edit-grid">
      <TextField label="来源编号" value={scope.source_id} onChange={(value) => setScope({ ...scope, source_id: value })} />
      <TextField label="租户/账套" value={scope.tenant_id} onChange={(value) => setScope({ ...scope, tenant_id: value })} />
      <TextField label="账簿" value={scope.ledger_id} onChange={(value) => setScope({ ...scope, ledger_id: value })} />
      <TextField label="组织" value={scope.organization_id} onChange={(value) => setScope({ ...scope, organization_id: value })} />
      <AccountingPeriodInput label="期间" value={scope.period} onChange={(value) => setScope({ ...scope, period: value })} />
      <TextField label="截止时间" value={scope.cutoff_at} placeholder="2026-08-31T23:59:59+08:00" onChange={(value) => setScope({ ...scope, cutoff_at: value })} />
      <TextField label="币种" value={scope.currency} onChange={(value) => setScope({ ...scope, currency: value })} />
      <TextField label="来源产品" value={product} onChange={setProduct} />
    </div>
    <details className="analysis-details"><summary>高级：来源身份与刷新方式</summary><div className="analysis-edit-grid">
      <TextField label="版本" value={version} onChange={setVersion} />
      <TextField label="资料名称" value={name} onChange={setName} />
      <TextField label="日历" value={scope.calendar} onChange={(value) => setScope({ ...scope, calendar: value })} />
      <TextField label="刷新模式" value={scope.mode} onChange={(value) => setScope({ ...scope, mode: value })} />
      <FieldShell label="文件身份策略"><select aria-label="文件身份策略" className="fnd-field" value={policy} onChange={(event) => setPolicy(event.target.value as typeof policy)}>
        <option value="snapshot_only">按文件快照</option><option value="business_key">按业务键识别</option></select></FieldShell>
    </div></details></fieldset>
    <div className="analysis-actions"><Button variant="outline" type="button" disabled={busy || refreshing || !ready} onClick={() => void refreshSource()}>
      <RefreshCw size={14} aria-hidden />选择文件并刷新</Button>
      {refreshing && <span role="status" className="analysis-note"><WaitOrb state="working" />正在选择文件并刷新来源…</span>}</div>
    {batches.length > 0 && <details className="analysis-details"><summary>来源刷新批次 · {batches.length} 个</summary>
      <div className="analysis-history-list">{[...batches].reverse().slice(0, 8).map((batch) => <div key={batch.id} className="analysis-history-row analysis-history-row--static">
        <span>{batch.source_name ?? batch.product ?? '来源文件'}</span><span>{batch.publication_status ?? 'recorded'} · {batch.row_count ?? 0} 行</span>
        <time>{when(batch.created_at)}</time><span>{batch.dataset_id ? `新快照 ${shortSha(batch.dataset_id)}` : batch.effective_dataset_id ? `沿用 ${shortSha(batch.effective_dataset_id)}` : batch.prior_snapshot_id ? `沿用 ${shortSha(batch.prior_snapshot_id)}` : shortSha(batch.id)}</span>
      </div>)}</div></details>}
    {message && <p role="status" className="analysis-message">{message}</p>}
    {error && <p role="alert" className="analysis-message analysis-message--error">{error}</p>}
  </details>;
}

function WorkbookPanel({ taskId, datasets, runs, busy, contextId }: { taskId: string; datasets: DatasetSnapshot[]; runs: AnalysisRun[]; busy: boolean; contextId?: string }) {
  const xlsx = fileDatasets(datasets);
  const [datasetId, setDatasetId] = useState(xlsx[0]?.id ?? '');
  const [inspection, setInspection] = useState<Record<string, unknown> | null>(null);
  const [inspecting, setInspecting] = useState(false);
  const [inspectionError, setInspectionError] = useState('');
  const [bindingId, setBindingId] = useState('');
  const [sourceKind, setSourceKind] = useState<'table' | 'named_range' | 'range'>('table');
  const [sourceName, setSourceName] = useState('');
  const [sheet, setSheet] = useState('');
  const [range, setRange] = useState('');
  const [role, setRole] = useState<'input' | 'output'>('input');
  const [fields, setFields] = useState('[{"name":"amount","policy":"amount"}]');
  const [writes, setWrites] = useState('[{"row":1,"field":"amount","value":"0.00"}]');
  const [runId, setRunId] = useState('');
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const [resolutions, setResolutions] = useState<Record<string, 'keep' | 'apply'>>({});
  const [readResult, setReadResult] = useState<Record<string, unknown> | null>(null);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  // What the panel is doing, in words; every action below waits on the foundry.
  const [running, setRunning] = useState('');
  const locked = busy || Boolean(running);
  const track = (label: string, work: () => Promise<void>) => {
    if (running) return;
    setRunning(label);
    void work().finally(() => setRunning(''));
  };
  const workbookRequest = useRef(0);
  const workbookPreviewMounted = useRef(false);
  const workbookDatasetMounted = useRef(false);
  useEffect(() => { setDatasetId((value) => value || xlsx[0]?.id || ''); }, [xlsx]);
  useEffect(() => {
    if (!workbookPreviewMounted.current) { workbookPreviewMounted.current = true; return; }
    workbookRequest.current += 1; setPreview(null); setResolutions({});
  }, [datasetId, bindingId, writes, runId]);
  useEffect(() => {
    if (!workbookDatasetMounted.current) { workbookDatasetMounted.current = true; return; }
    workbookRequest.current += 1; setInspection(null); setInspectionError(''); setReadResult(null);
  }, [datasetId]);
  if (!xlsx.length) return null;
  const sourceSpec = () => sourceKind === 'range' ? { kind: 'range', sheet, range } : { kind: sourceKind, name: sourceName };
  async function call(command: 'workbook-inspect' | 'workbook-bind' | 'workbook-read' | 'workbook-preview' | 'workbook-apply' | 'analysis-circle-select', spec: Record<string, unknown>) {
    const api = bridge(); if (!api?.financeCall) throw new Error('此版本暂不支持 Excel 协作。');
    return unwrap(await api.financeCall(taskId, command, spec));
  }
  async function inspect() {
    const request = ++workbookRequest.current;
    try {
      setError(''); setInspectionError(''); setMessage(''); setInspecting(true);
      const result = await call('workbook-inspect', { dataset_id: datasetId });
      if (request !== workbookRequest.current) return;
      setInspection(result); setMessage('已读取工作簿结构。');
    } catch (failure) {
      if (request === workbookRequest.current) {
        const text = failure instanceof Error ? failure.message : String(failure);
        setInspectionError(text);
        setError(text);
      }
    } finally {
      if (request === workbookRequest.current) setInspecting(false);
    }
  }
  async function bind() {
    const request = ++workbookRequest.current;
    try {
      setError(''); setMessage('');
      const parsed = JSON.parse(fields);
      if (!Array.isArray(parsed)) throw new Error('字段 JSON 需要是数组。');
      const result = await call('workbook-bind', { dataset_id: datasetId, source: sourceSpec(), fields: parsed, role, writable: role === 'output', header: true });
      if (request !== workbookRequest.current) return;
      setBindingId(String(result.id ?? '')); setPreview(null); setResolutions({}); setMessage('已保存 Excel 区域绑定。');
    } catch (failure) { if (request === workbookRequest.current) setError(failure instanceof Error ? failure.message : String(failure)); }
  }
  async function circleSelect() {
    try {
      setError(''); setMessage('');
      if (!contextId) throw new Error('请先保存财务口径。');
      await call('analysis-circle-select', { kind: 'workbook', binding_id: bindingId, range: range || sourceName || 'A:A', instruction: '改成开票口径', context_id: contextId });
      setMessage('已按圈选生成开票口径修订。');
    } catch (failure) { setError(failure instanceof Error ? failure.message : String(failure)); }
  }
  async function read() {
    const request = ++workbookRequest.current;
    try {
      setError(''); setMessage('');
      const result = await call('workbook-read', { binding_id: bindingId, dataset_id: datasetId });
      if (request !== workbookRequest.current) return;
      setReadResult(result); setMessage('已读取绑定区域。');
    } catch (failure) { if (request === workbookRequest.current) setError(failure instanceof Error ? failure.message : String(failure)); }
  }
  async function previewPatch() {
    const request = ++workbookRequest.current;
    try {
      setError(''); setMessage('');
      const parsed = JSON.parse(writes);
      if (!Array.isArray(parsed)) throw new Error('写入 JSON 需要是数组。');
      const result = await call('workbook-preview', { binding_id: bindingId, dataset_id: datasetId, writes: parsed, ...(runId ? { run_id: runId } : {}) });
      if (request !== workbookRequest.current) return;
      const patch = result.patch as Record<string, unknown> | undefined;
      const nextCells = Array.isArray(patch?.cells) ? patch.cells as Record<string, unknown>[] : [];
      setResolutions(Object.fromEntries(nextCells
        .filter((cell) => cell.conflict === true && cell.cell)
        .map((cell) => [String(cell.cell), 'keep'])));
      setPreview(result); setMessage('已生成写回预览。冲突单元格需要选择保留或应用后再生成文件。');
    } catch (failure) { if (request === workbookRequest.current) setError(failure instanceof Error ? failure.message : String(failure)); }
  }
  async function applyPatch() {
    try {
      setError(''); setMessage('');
      if (!preview?.patch_id) throw new Error('请先生成写回预览。');
      const result = await call('workbook-apply', { patch_id: preview.patch_id, resolutions });
      setMessage(`已生成协作工作簿：${textValue(result.artifact_path ?? result.path ?? result.id)}`);
    } catch (failure) { setError(failure instanceof Error ? failure.message : String(failure)); }
  }
  const sheetNames = Array.isArray(inspection?.sheet_names) ? inspection.sheet_names.map(String) : [];
  const tables = Array.isArray(inspection?.tables) ? inspection.tables.map(String) : [];
  const names = Array.isArray(inspection?.named_ranges) ? inspection.named_ranges.map(String) : [];
  const previewPatchValue = preview?.patch as Record<string, unknown> | undefined;
  const cells = Array.isArray(previewPatchValue?.cells) ? previewPatchValue.cells as Record<string, unknown>[] : [];
  const conflictCells = cells.filter((cell) => cell.conflict === true && cell.cell);
  return <section className="analysis-workbook-panel" aria-label="Excel 协作">
    <div className="analysis-section-heading"><div><h3>Excel 协作</h3><p className="analysis-note">在任务快照上检查表格、绑定区域，预览写回，再生成新的工作簿文件。</p></div></div>
    <fieldset className="analysis-fieldset" disabled={locked}><div className="analysis-edit-grid">
      <SearchableSelect label="工作簿资料" value={datasetId} options={datasetOptions(xlsx)} onChange={setDatasetId} placeholder="搜索工作簿名或快照" />
      <TextField label="绑定编号" value={bindingId} onChange={setBindingId} placeholder="读取、预览或应用已有绑定" />
      <FieldShell label="区域类型"><select aria-label="区域类型" className="fnd-field" value={sourceKind} onChange={(event) => setSourceKind(event.target.value as typeof sourceKind)}>
        <option value="table">表格</option><option value="named_range">命名区域</option><option value="range">工作表范围</option></select></FieldShell>
      {sourceKind === 'range' ? <><SearchableSelect label="工作表" value={sheet} options={sheetNames.map((name) => ({ value: name, label: name }))}
          onChange={setSheet} placeholder={sheetNames.length ? '搜索工作表' : '先检查结构'} allowEmptyLabel="暂不选择"
          loading={inspecting} loadError={inspectionError} unconfigured={!inspection && !inspectionError && !inspecting}
          unconfiguredLabel="请先点击“检查结构”，读取工作表后再选择。" />
        <TextField label="范围" value={range} placeholder="A1:D20" onChange={setRange} /></>
        : <TextField label={sourceKind === 'table' ? '表格名称' : '命名区域'} value={sourceName} onChange={setSourceName} />}
      <FieldShell label="用途"><select aria-label="用途" className="fnd-field" value={role} onChange={(event) => setRole(event.target.value as typeof role)}>
        <option value="input">读取输入</option><option value="output">写回输出</option></select></FieldShell>
      <SearchableSelect label="校验运行（可选）" value={runId} options={runOptions(runs)} onChange={setRunId}
        placeholder="搜索运行时间或编号" allowEmptyLabel="经理直接写入" />
    </div>
    <details className="analysis-details"><summary>高级：字段与写入 JSON</summary><div className="analysis-edit-grid">
      <label>字段数组<Textarea className="analysis-code" rows={4} value={fields} onChange={(event) => setFields(event.target.value)} /></label>
      <label>写入数组<Textarea className="analysis-code" rows={4} value={writes} onChange={(event) => setWrites(event.target.value)} /></label>
    </div></details></fieldset>
    <p className="analysis-note">绑定基准由绑定记录保存；读取和写回预览使用当前选择的目标快照 {shortSha(datasetId)}。</p>
    <div className="analysis-actions">
      <Button variant="outline" type="button" disabled={locked || !datasetId} onClick={() => track('正在检查工作簿结构…', inspect)}><FileSpreadsheet size={14} aria-hidden />检查结构</Button>
      <Button variant="outline" type="button" disabled={locked || !datasetId || (sourceKind === 'range' ? !sheet || !range : !sourceName)} onClick={() => track('正在保存绑定…', bind)}>保存绑定</Button>
      <Button variant="outline" type="button" disabled={locked || !bindingId || !contextId} onClick={() => track('正在按圈选生成开票口径修订…', circleSelect)}>改成开票口径</Button>
      <Button variant="outline" type="button" disabled={locked || !bindingId} onClick={() => track('正在读取绑定区域…', read)}>读取区域</Button>
      <Button variant="outline" type="button" disabled={locked || !bindingId} onClick={() => track('正在生成写回预览…', previewPatch)}>预览写回</Button>
      <Button type="button" disabled={locked || !preview?.patch_id} onClick={() => track('正在生成工作簿…', applyPatch)}>生成工作簿</Button>
      {running && <span role="status" className="analysis-note"><WaitOrb state="working" />{running}</span>}
    </div>
    {inspection && <details className="analysis-details" open><summary>工作簿结构</summary>
      <p>工作表：{sheetNames.join('、') || '未读取'}</p><p>表格：{tables.join('、') || '无'}</p><p>命名区域：{names.join('、') || '无'}</p>
      {Array.isArray(inspection.unsupported_features) && inspection.unsupported_features.length > 0 && <p>需生成独立结果工作簿：{inspection.unsupported_features.map(textValue).join('、')}</p>}
    </details>}
    {readResult && Array.isArray(readResult.rows) && <Table columns={Object.keys(readResult.rows[0] ?? {}).map((name) => ({ name, type: 'VARCHAR' }))} rows={readResult.rows as Record<string, unknown>[]} caption="绑定区域读取结果" />}
    {cells.length > 0 && <Table columns={[{ name: '单元格', type: 'VARCHAR' }, { name: '字段', type: 'VARCHAR' }, { name: '原值', type: 'VARCHAR' }, { name: '新值', type: 'VARCHAR' }, { name: '冲突', type: 'VARCHAR' }]}
      rows={cells.map((cell) => ({ 单元格: cell.cell, 字段: cell.field, 原值: cell.old_value, 新值: cell.new_value, 冲突: cell.conflict === true ? '是' : '否' }))} caption="写回预览" />}
    {conflictCells.length > 0 && <div className="analysis-workbook-conflicts" aria-label="写回冲突处理">
      <strong>冲突处理</strong>
      {conflictCells.map((cell) => {
        const cellId = String(cell.cell);
        return <label key={cellId}>{cellId} · 原值 {textValue(cell.old_value)} → 新值 {textValue(cell.new_value)}
          <select className="fnd-field" value={resolutions[cellId] ?? 'keep'} onChange={(event) => setResolutions((value) => ({ ...value, [cellId]: event.target.value as 'keep' | 'apply' }))}>
            <option value="keep">保留原单元格</option><option value="apply">应用新结果</option>
          </select></label>;
      })}
    </div>}
    {message && <p role="status" className="analysis-message">{message}</p>}
    {error && <p role="alert" className="analysis-message analysis-message--error">{error}</p>}
  </section>;
}

function bridgeScenarioLabels(context?: FinanceContext): { actual: string; baseline: string } {
  const scopes = context?.scopes ?? {};
  const actualScope = scopes.actual;
  const budgetScope = scopes.budget;
  if (!actualScope || !budgetScope) {
    throw new Error('预算桥需要已保存口径包含明确的 actual 与 budget 情景别名。请用实际资料和预算资料重新保存口径后再运行。');
  }
  return {
    actual: textValue(actualScope.scenario ?? 'actual'),
    baseline: textValue(budgetScope.scenario ?? 'budget'),
  };
}

const bridgeDimensions = ['organization', 'period'];

const agingStatusOptions: SelectOption[] = [
  { value: 'active', label: '正常应收', meta: '正常、未逾期、open' },
  { value: 'overdue', label: '逾期应收', meta: '逾期、overdue' },
  { value: 'disputed', label: '争议应收', meta: '争议、disputed' },
  { value: 'collection_hold', label: '暂停催收', meta: '暂停催收、hold' },
  { value: 'written_off', label: '已核销', meta: '核销、writeoff' },
];
const agingStatusMapping = {
  active: ['正常', '未逾期', 'open', 'active'],
  overdue: ['逾期', 'overdue'],
  disputed: ['争议', 'disputed'],
  collection_hold: ['暂停催收', 'hold', 'collection_hold'],
  written_off: ['核销', '已核销', 'written_off'],
};

type FinanceAdjustment = {
  id: string;
  label?: string;
  include_in_management_pnl?: boolean;
  note?: string;
  amount?: string;
  profit_impact?: string;
  parent_id?: string | null;
  /** The newer row that replaced this one. A superseded row, pending or confirmed, is history, not a choice. */
  superseded_by?: string | null;
};

const STRUCTURE_LABELS: Record<string, string> = {
  pending_confirmation: '待确认表结构',
  pending_acknowledgement: '待经理追认',
  no_table: '没有可用的表',
  withdrawn: '已撤回',
};

function structureLabel(source: DatasetSnapshot): string {
  const state = (source as { structure_state?: string }).structure_state ?? '';
  return STRUCTURE_LABELS[state] ?? '';
}

/**
 * Every file in this task that is waiting on the manager: one waiting for her to
 * say what its tables are, one somebody else confirmed on her behalf, one a
 * remembered structure was applied to.
 */
function StructurePanel({ taskId, datasets, busy, onRefresh }: {
  taskId: string; datasets: DatasetSnapshot[]; busy: boolean; onRefresh(): Promise<void> | void;
}) {
  const [proposals, setProposals] = useState<StructureProposal[]>([]);
  const [pending, setPending] = useState<{ id: string; dataset_id: string; source: string; state: string; parent_id: string | null }[]>([]);
  const [error, setError] = useState('');
  const load = useCallback(async () => {
    const api = bridge(); if (!api?.financeCall) return;
    const listed = unwrap(await api.financeCall(taskId, 'structure-proposal-list', {}) as Answer<{ proposals?: StructureProposal[] }>);
    setProposals(listed.proposals ?? []);
    const settled = unwrap(await api.financeCall(taskId, 'structure-confirmation-list', {}) as Answer<{ confirmations?: typeof pending }>);
    const rows = settled.confirmations ?? [];
    const superseded = new Set(rows.map((row) => row.parent_id).filter(Boolean) as string[]);
    setPending(rows.filter((row) => row.state === 'pending_acknowledgement' && !superseded.has(row.id)));
  }, [taskId]);
  useEffect(() => { void load().catch((failure) => setError(failure instanceof Error ? failure.message : String(failure))); }, [load, datasets]);

  const named = (id: string) => datasets.find((item) => item.id === id)?.name ?? id;
  const settle = async () => { await load(); await onRefresh(); };
  const waiting = proposals.filter((item) => item.structure_state === 'pending_confirmation' || item.structure_state === 'no_table');
  if (!waiting.length && !pending.length && !error) return null;
  return (
    <div className="analysis-structure-panel">
      {error && <p role="alert" className="analysis-structure-error">{error}</p>}
      {/* A to-do line per file; the confirmation form is long and opens on demand. */}
      {waiting.map((proposal) => (
        <details key={proposal.id} className="analysis-details analysis-structure-todo">
          <summary>待确认表结构 · {named(proposal.dataset_id)}{proposal.structure_state === 'no_table' ? ' · 没有识别出数据表' : ` · ${proposal.sheets.length} 张工作表`}</summary>
          <StructureProposalCard taskId={taskId} datasetName={named(proposal.dataset_id)}
            proposal={proposal} busy={busy} onSettled={settle} />
        </details>
      ))}
      {pending.map((confirmation) => (
        <StructurePendingStrip key={confirmation.id} taskId={taskId} datasetName={named(confirmation.dataset_id)}
          confirmation={confirmation} busy={busy} onSettled={settle} />
      ))}
    </div>
  );
}

function FinanceAdjustmentPanel({ taskId, contextId, busy, onRefresh }: {
  taskId: string; contextId: string; busy: boolean; onRefresh(): Promise<void> | void;
}) {
  const [rows, setRows] = useState<FinanceAdjustment[]>([]);
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [pendingId, setPendingId] = useState('');
  const [rerunning, setRerunning] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const load = useCallback(async () => {
    const api = bridge(); if (!api?.financeCall || !contextId) return;
    const listed = unwrap(await api.financeCall(taskId, 'finance-adjustment-list', { context_id: contextId }) as Answer<{ adjustments?: FinanceAdjustment[] }>);
    const next = listed.adjustments ?? [];
    setRows(next);
    setSelected((current) => {
      const nextSelected: Record<string, boolean> = {};
      for (const row of next.filter((item) => item.include_in_management_pnl)) {
        nextSelected[row.id] = current[row.id] !== false;
      }
      return nextSelected;
    });
  }, [taskId, contextId]);
  useEffect(() => { void load().catch((failure) => setError(failure instanceof Error ? failure.message : String(failure))); }, [load]);
  const current = rows.filter((row) => !row.superseded_by);
  const confirmed = current.filter((row) => row.include_in_management_pnl);
  const pending = current.filter((row) => !row.include_in_management_pnl && !confirmed.some((item) => item.parent_id === row.id));
  const locked = busy || Boolean(pendingId) || rerunning;
  async function confirm(id: string) {
    const api = bridge(); if (!api?.financeCall) return;
    setPendingId(id); setError(''); setMessage('');
    try {
      unwrap(await api.financeCall(taskId, 'finance-adjustment-confirm', { id }));
      setMessage('已确认纳入考核。');
      await load();
      await onRefresh();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setPendingId('');
    }
  }
  async function rerun() {
    const api = bridge(); if (!api?.financeCall) return;
    setRerunning(true); setError(''); setMessage('');
    const ids = confirmed.filter((row) => selected[row.id] !== false).map((row) => row.id);
    try {
      unwrap(await api.financeCall(taskId, 'run-metric', { context_id: contextId, metric: { kind: 'management_pnl' }, adjustment_ids: ids }));
      setMessage(ids.length ? '已按勾选调整重算考核利润。' : '已无调整重跑账面利润。');
      await onRefresh();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setRerunning(false);
    }
  }
  if (!contextId) return null;
  return <aside className="analysis-adjustment-panel" aria-label="考核调整"><details className="analysis-details">
    <summary><div className="analysis-section-heading"><h3>考核调整</h3><span className="analysis-note">{pending.length ? `${pending.length} 条待确认 · ` : ''}确认后才会进入下一次管理损益。</span></div></summary>
    {pending.length ? <ul className="analysis-history-list">{pending.map((row) => <li key={row.id} className="analysis-history-row analysis-history-row--static">
      <span>{row.label || '调整'} · 待确认</span>
      <Button type="button" disabled={locked} onClick={() => void confirm(row.id)}>{pendingId === row.id ? '确认中…' : '确认纳入'}</Button>
    </li>)}</ul> : <p className="analysis-note">没有待确认的调整。</p>}
    {confirmed.length ? <div className="analysis-fieldset analysis-adjustment-rerun" aria-label="重算">
      <p className="analysis-note">重算</p>
      {confirmed.map((row) => <label key={row.id}><input type="checkbox" checked={selected[row.id] !== false}
        onChange={(event) => setSelected((value) => ({ ...value, [row.id]: event.target.checked }))} />{row.label || row.id}</label>)}
      <Button type="button" disabled={locked} onClick={() => void rerun()}>{rerunning ? <><WaitOrb state="solving" />重算中…</> : '重算'}</Button>
    </div> : null}
  </details>
    {/* Outside the fold: a failed list must not read as "nothing to confirm". */}
    {message && <p role="status" className="analysis-message">{message}</p>}
    {error && <p role="alert" className="analysis-message analysis-message--error">{error}</p>}
  </aside>;
}


type FinanceChart = {
  id: string;
  label?: string;
  run_id?: string;
  content_hash?: string;
  series?: { columns?: unknown[]; rows?: Record<string, unknown>[] };
};

function FinanceChartPanel({ taskId, runs, busy, onRefresh }: {
  taskId: string; runs: AnalysisRun[]; busy: boolean; onRefresh(): Promise<void> | void;
}) {
  const [charts, setCharts] = useState<FinanceChart[]>([]);
  const [opened, setOpened] = useState<FinanceChart | null>(null);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [pending, setPending] = useState(false);
  const latest = [...runs].reverse().find((row) => row.execution_status === 'succeeded' || row.execution_status === 'success');
  const load = useCallback(async () => {
    const api = bridge(); if (!api?.financeCall) return;
    const listed = unwrap(await api.financeCall(taskId, 'chart-deliverable-list', {}) as Answer<{ charts?: FinanceChart[] }>);
    setCharts(listed.charts ?? []);
  }, [taskId]);
  useEffect(() => { void load().catch((failure) => setError(failure instanceof Error ? failure.message : String(failure))); }, [load]);
  async function archive() {
    const api = bridge(); if (!api?.financeCall || !latest) return;
    setPending(true); setError(''); setMessage('');
    try {
      unwrap(await api.financeCall(taskId, 'chart-deliverable-save', { run_id: latest.id }));
      setMessage('已归档当前结果图。');
      await load();
      await onRefresh();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally { setPending(false); }
  }
  async function open(id: string) {
    const api = bridge(); if (!api?.financeCall) return;
    setPending(true); setError(''); setMessage('');
    try {
      const record = unwrap(await api.financeCall(taskId, 'chart-deliverable-open', { id }) as Answer<FinanceChart>);
      setOpened(record);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally { setPending(false); }
  }
  const rows = opened?.series?.rows ?? [];
  const columns = rows[0] ? Object.keys(rows[0]) : [];
  return <aside className="analysis-chart-panel" aria-label="归档图"><details className="analysis-details">
    <summary><div className="analysis-section-heading"><h3>归档图</h3><span className="analysis-note">{charts.length ? `${charts.length} 张 · ` : ''}归档当前结果，不重新计算。</span></div></summary>
    <Button type="button" disabled={busy || pending || !latest} onClick={() => void archive()}>{pending ? '归档中…' : '归档当前结果图'}</Button>
    {charts.length ? <ul className="analysis-history-list">{charts.map((row) => <li key={row.id} className="analysis-history-row analysis-history-row--static">
      <span>{row.label || row.id}</span>
      <Button type="button" disabled={busy || pending} onClick={() => void open(row.id)}>打开</Button>
    </li>)}</ul> : <p className="analysis-note">还没有归档图。</p>}
    {opened && columns.length ? <table className="analysis-table"><thead><tr>{columns.map((name) => <th key={name}>{name}</th>)}</tr></thead>
      <tbody>{rows.map((row, index) => <tr key={index}>{columns.map((name) => <td key={name}>{textValue(row[name])}</td>)}</tr>)}</tbody></table> : null}
  </details>
    {message && <p role="status" className="analysis-message">{message}</p>}
    {error && <p role="alert" className="analysis-message analysis-message--error">{error}</p>}
  </aside>;
}

type ScopeRequest = { count: number; contextId?: string };

function FinanceWorkbench({ taskId, datasets, runs, busy, openRequest = { count: 0 }, running = '', onRunning, onRefresh }: {
  taskId: string; datasets: DatasetSnapshot[]; runs: AnalysisRun[]; busy: boolean;
  /** Bumped by 调整口径 on a result; each new count opens the settings on that result's scope. */
  openRequest?: ScopeRequest;
  /** What is running right now, in words; owned by the parent so it outlives this component. */
  running?: string; onRunning(label: string, active: boolean): void;
  onRefresh(): Promise<void>;
}) {
  const [finance, setFinance] = useState<FinanceContextState | null>(null);
  const [actual, setActual] = useState(datasets[0]?.id ?? '');
  const [budget, setBudget] = useState('');
  const [scope, setScope] = useState<Record<string, string>>({ ledger: '', organization: '', period: '', currency: 'CNY', unit: '元', scenario: 'actual' });
  const [budgetScope, setBudgetScope] = useState<Record<string, string>>({ scenario: 'budget' });
  const [comparePeriod, setComparePeriod] = useState('');
  const [contextId, setContextId] = useState('');
  const [mapName, setMapName] = useState('管理科目映射');
  const [mapRows, setMapRows] = useState('[{"account_code":"6001","management_account":"revenue"},{"account_code":"6401","management_account":"cost"},{"account_code":"6601","management_account":"expense"}]');
  const [accountMapId, setAccountMapId] = useState('');
  const [scenarioKind, setScenarioKind] = useState<'receivables_aging' | 'cash_13_weeks'>('receivables_aging');
  const [scenarioLabel, setScenarioLabel] = useState('基准情景');
  const [scenarioPrimary, setScenarioPrimary] = useState('actual');
  const [scenarioSecondary, setScenarioSecondary] = useState('');
  const [scenarioAsOf, setScenarioAsOf] = useState('');
  const [scenarioStart, setScenarioStart] = useState('');
  const [scenarioCutoff, setScenarioCutoff] = useState('');
  const [scenarioStatusField, setScenarioStatusField] = useState('invoice_status');
  const [scenarioStatuses, setScenarioStatuses] = useState<string[]>([]);
  const [openingCash, setOpeningCash] = useState('');
  const [delayDays, setDelayDays] = useState('14');
  const [baselineScenarioId, setBaselineScenarioId] = useState('');
  const hasSuccessfulResults = runs.some((row) => row.execution_status === 'succeeded' || row.execution_status === 'success');
  const [setupOpen, setSetupOpen] = useState(!hasSuccessfulResults);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const setup = useRef<HTMLDetailsElement>(null);
  // A remount (tab change, new task) must not replay a request it did not see.
  const seenRequest = useRef(openRequest.count);
  useEffect(() => { setActual((value) => value || datasets[0]?.id || ''); }, [datasets]);
  useEffect(() => { if (hasSuccessfulResults) setSetupOpen(false); }, [hasSuccessfulResults]);
  useEffect(() => {
    if (openRequest.count === seenRequest.current) return;
    seenRequest.current = openRequest.count;
    const context = finance?.contexts.find((item) => item.id === openRequest.contextId);
    if (context) loadContext(context);
    setSetupOpen(true);
    setup.current?.scrollIntoView?.({ block: 'start', behavior: 'smooth' });
    setup.current?.querySelector('summary')?.focus({ preventScroll: true });
  }, [openRequest.count]);
  /** Puts a saved scope back into the form, so the settings show what that result used. */
  function loadContext(context: FinanceContext) {
    const text = (value: unknown) => typeof value === 'string' ? value : '';
    const actualScope = (context.scopes?.actual ?? {}) as Record<string, unknown>;
    const budgetScope = context.scopes?.budget as Record<string, unknown> | undefined;
    setContextId(context.id);
    if (text(context.bindings?.actual)) setActual(text(context.bindings.actual));
    setBudget(text(context.bindings?.budget));
    setScope((current) => ({ ...current, ...Object.fromEntries(scopeFields.map(([key]) => [key, text(actualScope[key])])) }));
    if (budgetScope) {
      setBudgetScope({ scenario: text(budgetScope.scenario) || 'budget' });
      setComparePeriod(text(budgetScope.period) !== text(actualScope.period) ? text(budgetScope.period) : '');
    }
  }
  async function track(label: string, work: () => Promise<void>) {
    if (running) return;
    onRunning(label, true);
    try { await work(); } finally { onRunning(label, false); }
  }
  useEffect(() => {
    let cancelled = false;
    const api = bridge();
    if (!api?.financeCall) return;
    void api.financeCall(taskId, 'list-finance-context').then((answer) => {
      if (!cancelled) {
        const value = unwrap(answer as Answer<FinanceContextState>);
        setFinance(value);
        setContextId((current) => current || value.contexts.at(-1)?.id || '');
      }
    }).catch((failure) => { if (!cancelled) setError(failure instanceof Error ? failure.message : String(failure)); });
    return () => { cancelled = true; };
  }, [taskId]);
  function saveContext(runAfter?: 'pnl' | 'bridge') {
    return track(runAfter === 'pnl' ? '正在保存口径并运行管理口径损益…' : runAfter === 'bridge' ? '正在保存口径并运行预算差异桥…' : '正在保存口径…', async () => { try {
      const api = bridge(); if (!api?.financeCall) throw new Error('此版本暂不支持财务业务口径。');
      setError(''); setMessage('');
      const bindings = { actual, ...(budget ? { budget } : {}) };
      const scopes = { actual: scope, ...(budget ? { budget: { ...scope, ...budgetScope, ...(comparePeriod ? { period: comparePeriod } : {}) } } : {}) };
      const context = unwrap(await api.financeCall(taskId, 'finance-context-save', {
        name: `${scope.period || '本期'}${scope.organization ? ` ${scope.organization}` : ''}经营口径`,
        bindings, scopes, ...(accountMapId ? { account_map_id: accountMapId } : {}),
      }) as Answer<FinanceContext>);
      setContextId(context.id);
      setFinance((value) => value ? {
        ...value,
        contexts: value.contexts.some((item) => item.id === context.id) ? value.contexts : [...value.contexts, context],
      } : value);
      if (runAfter === 'pnl') {
        unwrap(await api.financeCall(taskId, 'run-metric', { context_id: context.id, metric: { kind: 'management_pnl' } }));
        setMessage('已保存口径并运行管理口径损益。');
        setSetupOpen(false);
      } else if (runAfter === 'bridge') {
        const labels = bridgeScenarioLabels(context);
        unwrap(await api.financeCall(taskId, 'explain-variance', {
          context_id: context.id, actual_scenario: labels.actual, baseline_scenario: labels.baseline,
          dimensions: bridgeDimensions,
        }));
        setMessage('已保存口径并运行预算差异桥。');
        setSetupOpen(false);
      } else {
        setMessage('已保存财务分析口径。');
      }
      await onRefresh();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } });
  }
  function saveMap() {
    return track('正在保存映射…', async () => { try {
      const api = bridge(); if (!api?.financeCall) throw new Error('此版本暂不支持管理科目映射。');
      setError(''); setMessage('');
      const parsed = JSON.parse(mapRows);
      if (!Array.isArray(parsed)) throw new Error('映射 JSON 需要是数组。');
      const record = unwrap(await api.financeCall(taskId, 'finance-map-save', { name: mapName, rows: parsed }) as Answer<Record<string, unknown>>);
      setAccountMapId(String(record.id ?? ''));
      setFinance((value) => value ? { ...value, account_maps: [...value.account_maps, record] } : value);
      setMessage('已保存管理科目映射，可用于下一次口径保存。');
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } });
  }
  const runExisting = (kind: 'pnl' | 'bridge') => track(kind === 'pnl' ? '正在运行管理口径损益…' : '正在运行预算差异桥…', async () => {
    try {
      const api = bridge(); if (!api?.financeCall || !contextId) return;
      setError(''); setMessage('');
      if (kind === 'pnl') unwrap(await api.financeCall(taskId, 'run-metric', { context_id: contextId, metric: { kind: 'management_pnl' } }));
      else {
        const labels = bridgeScenarioLabels(selectedContext);
        unwrap(await api.financeCall(taskId, 'explain-variance', {
          context_id: contextId, actual_scenario: labels.actual, baseline_scenario: labels.baseline,
          dimensions: bridgeDimensions,
        }));
      }
      setMessage(kind === 'pnl' ? '已运行管理口径损益。' : '已运行预算差异桥。');
      setSetupOpen(false);
      await onRefresh();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    }
  });
  const selectedContext = finance?.contexts.find((context) => context.id === contextId);
  const aliases = Object.keys(selectedContext?.bindings ?? {});
  useEffect(() => {
    setScenarioPrimary((value) => value || aliases[0] || 'actual');
  }, [aliases.join('|')]);
  useEffect(() => { setBaselineScenarioId(''); }, [contextId, scenarioKind]);
  function runScenario(child = false) {
    return track(child ? '正在运行延迟回款子情景…' : '正在运行基准情景…', async () => { try {
      const api = bridge(); if (!api?.financeCall || !contextId) throw new Error('请先保存或选择财务口径。');
      setError(''); setMessage('');
      const scenarioScope = selectedContext?.scopes?.[scenarioPrimary] ?? scope;
      let scenario: Record<string, unknown>;
      if (child) {
        if (scenarioKind !== 'cash_13_weeks') throw new Error('延迟回款子情景仅适用于 13 周现金测算。');
        if (!baselineScenarioId) throw new Error('请先运行一个 13 周现金基准情景。');
        const parent = finance?.scenarios.find((item) => item.id === baselineScenarioId);
        if (parent && (parent.kind !== 'cash_13_weeks' || parent.context_id !== contextId)) throw new Error('请选择同一财务口径下的 13 周现金基准情景。');
        scenario = unwrap(await api.financeCall(taskId, 'finance-scenario-save', {
          parent_id: baselineScenarioId,
          label: `${scenarioLabel || '情景'} · 延迟 ${delayDays || '0'} 天`,
          changes: { scenario: { delay_receipts_days: Number(delayDays || 0), label: `回款延迟 ${delayDays || 0} 天` } },
        }));
      } else {
        const inputs = scenarioKind === 'receivables_aging'
          ? { as_of: scenarioAsOf || scope.period || scope.cutoff_at, scope: scenarioScope, invoices_alias: scenarioPrimary,
              ...(scenarioSecondary ? { activity_alias: scenarioSecondary } : {}),
              ...(scenarioStatuses.length ? { status_filter: { field: scenarioStatusField || 'status', include: scenarioStatuses, mapping: agingStatusMapping } } : {}) }
          : { opening_cash: openingCash, start_date: scenarioStart, actual_cutoff: scenarioCutoff, scope: scenarioScope,
              receipts_alias: scenarioPrimary, ...(scenarioSecondary ? { payments_alias: scenarioSecondary } : {}), scenario: { delay_receipts_days: 0 } };
        scenario = unwrap(await api.financeCall(taskId, 'finance-scenario-save', {
          context_id: contextId, kind: scenarioKind, label: scenarioLabel || '基准情景', inputs,
        }));
        setBaselineScenarioId(String(scenario.id ?? ''));
      }
      unwrap(await api.financeCall(taskId, 'finance-scenario-run', { scenario_id: String(scenario.id) }));
      setFinance((value) => value && !value.scenarios.some((item) => item.id === scenario.id)
        ? { ...value, scenarios: [...value.scenarios, scenario] } : value);
      setMessage(child ? '已运行延迟回款子情景。' : '已运行基准情景。');
      setSetupOpen(false);
      await onRefresh();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } });
  }
  const locked = busy || Boolean(running);
  const disabled = locked || !actual;
  const moreScope = scopeFields.filter(([key]) => key !== 'period');
  const moreScopeSummary = moreScope.map(([key, label]) => scope[key] ? `${label} ${scope[key]}` : '').filter(Boolean).join(' · ');
  return <><details ref={setup} className="analysis-finance-setup" aria-label="财务分析设置" open={setupOpen}
    onToggle={(event) => setSetupOpen((event.currentTarget as HTMLDetailsElement).open)}>
    <summary><div className="analysis-section-heading"><h3>财务业务口径</h3><span className="analysis-note">用已登记资料建立范围，结果仍保留 SQL 与脚本高级路径。</span></div></summary>
    <fieldset className="analysis-fieldset" disabled={locked}><div className="analysis-edit-grid">
      <SearchableSelect label="实际资料" value={actual} options={datasetOptions(datasets)} onChange={(value) => {
        setActual(value);
        if (budget === value) setBudget('');
      }} placeholder="搜索资料名称、来源或快照" />
      <SearchableSelect label="预算资料（可选）" value={budget} options={datasetOptions(datasets.filter((source) => source.id !== actual))}
        onChange={setBudget} placeholder="搜索预算资料" allowEmptyLabel="暂不选择" />
      {finance?.contexts.length ? <SearchableSelect label="已保存口径" value={contextId} options={contextOptions(finance)}
        onChange={setContextId} placeholder="搜索口径名称或范围" /> : null}
      <AccountingPeriodInput label="期间" value={scope.period ?? ''} onChange={(value) => setScope({ ...scope, period: value })} />
      {budget && <TextField label="预算情景名称" value={budgetScope.scenario ?? ''} onChange={(value) => setBudgetScope({ ...budgetScope, scenario: value })} />}
      {budget && <AccountingPeriodInput label="对比期间" value={comparePeriod} onChange={setComparePeriod}
        shortcutBaseValue={scope.period} shortcutBaseLabel="实际期间"
        help="快捷项基于实际期间；留空时沿用实际期间，填写后预算桥按该期间保存 baseline 范围。" />}
    </div>
    <details className="analysis-details"><summary>更多范围{moreScopeSummary ? ` · ${moreScopeSummary}` : ''}</summary>
      <div className="analysis-edit-grid">{moreScope.map(([key, label]) =>
        <TextField key={key} label={label} value={scope[key] ?? ''} onChange={(value) => setScope({ ...scope, [key]: value })} />)}</div>
    </details></fieldset>
    <div className="analysis-actions">
      <Button variant="outline" type="button" disabled={disabled} onClick={() => void saveContext()}>保存口径</Button>
      <Button type="button" disabled={disabled} onClick={() => void saveContext('pnl')}>保存并运行 P&L</Button>
      <Button variant="outline" type="button" disabled={disabled || !budget} onClick={() => void saveContext('bridge')}>运行预算桥</Button>
      {contextId && <Button variant="outline" type="button" disabled={locked} onClick={() => void runExisting('pnl')}>用已保存口径重跑 P&L</Button>}
      {contextId && <Button variant="outline" type="button" disabled={locked} onClick={() => void runExisting('bridge')}>用已保存口径运行预算桥</Button>}
    </div>
    {contextId && <details className="analysis-details analysis-scenario-panel"><summary>情景测算</summary>
      <fieldset className="analysis-fieldset" disabled={locked}><div className="analysis-edit-grid">
        <FieldShell label="情景类型"><select aria-label="情景类型" className="fnd-field" value={scenarioKind} onChange={(event) => setScenarioKind(event.target.value as typeof scenarioKind)}>
          <option value="receivables_aging">应收账龄</option><option value="cash_13_weeks">13 周现金</option></select></FieldShell>
        <TextField label="情景名称" value={scenarioLabel} onChange={setScenarioLabel} />
        <SearchableSelect label={scenarioKind === 'receivables_aging' ? '应收/发票资料' : '回款资料'} value={scenarioPrimary}
          options={aliasOptions(aliases, selectedContext)} onChange={setScenarioPrimary} placeholder="搜索情景别名或资料编号" />
        <SearchableSelect label={scenarioKind === 'receivables_aging' ? '核销活动（可选）' : '付款资料（可选）'} value={scenarioSecondary}
          options={aliasOptions(aliases.filter((alias) => alias !== scenarioPrimary), selectedContext)}
          onChange={setScenarioSecondary} placeholder="搜索情景别名或资料编号" allowEmptyLabel="暂不选择" />
        {scenarioKind === 'receivables_aging' ? <>
          <DateInput label="账龄日期" value={scenarioAsOf} onChange={setScenarioAsOf} />
          <TextField label="状态字段" value={scenarioStatusField} onChange={setScenarioStatusField} help="账龄计算会按这个列名识别发票状态。" />
          <MultiSelect label="应收状态筛选" values={scenarioStatuses} options={agingStatusOptions} onChange={setScenarioStatuses}
            placeholder="默认纳入全部状态" help="选择后只纳入这些状态；不选则纳入全部应收记录。" />
        </> : <>
          <DecimalInput label="期初现金" value={openingCash} onChange={setOpeningCash} placeholder="5000000.00" unit={scope.unit || '元'} />
          <DateInput label="预测开始日" value={scenarioStart} onChange={setScenarioStart}
            help="写入 start_date；通常晚于实际收支截止日。" />
          <DateInput label="实际收支截止日" value={scenarioCutoff} onChange={setScenarioCutoff}
            help="写入 actual_cutoff；这是历史实际收支边界，不是预测结束日。" />
        </>}
        {scenarioKind === 'cash_13_weeks' && <DecimalInput label="回款延迟天数" value={delayDays} onChange={setDelayDays} unit="天" />}
      </div></fieldset>
      <div className="analysis-actions">
        <Button variant="outline" type="button" disabled={locked || !contextId || !scenarioPrimary || (scenarioKind === 'cash_13_weeks' && (!openingCash || !scenarioStart || !scenarioCutoff))} onClick={() => void runScenario(false)}><Play size={14} aria-hidden />运行基准情景</Button>
        <Button variant="outline" type="button" disabled={locked || scenarioKind !== 'cash_13_weeks' || !baselineScenarioId} onClick={() => void runScenario(true)}>运行延迟回款子情景</Button>
      </div>
      {finance?.scenarios.filter((scenario) => scenario.context_id === contextId && scenario.kind === scenarioKind).length ? <div className="analysis-history-list">{[...finance.scenarios].filter((scenario) => scenario.context_id === contextId && scenario.kind === scenarioKind).reverse().slice(0, 6).map((scenario) => <button type="button" className="analysis-history-row" key={String(scenario.id)} disabled={locked}
        aria-current={scenario.id === baselineScenarioId ? 'true' : undefined} onClick={() => setBaselineScenarioId(String(scenario.id ?? ''))}>
        <span>{textValue(scenario.label ?? scenario.kind)}</span><span>{textValue(scenario.kind)}</span><time>{when(String(scenario.created_at ?? ''))}</time><span>{shortSha(String(scenario.id ?? ''))}</span></button>)}</div> : null}
    </details>}
    {finance?.contexts.length ? <details className="analysis-details"><summary>已保存财务口径 · {finance.contexts.length} 个</summary>
      <div className="analysis-history-list">{[...finance.contexts].reverse().map((context) => <button key={context.id} type="button" className="analysis-history-row" disabled={locked}
        aria-current={context.id === contextId ? 'true' : undefined} onClick={() => setContextId(context.id)}>
        <span>{context.name}</span><span>{Object.entries(context.scopes ?? {}).map(([alias, item]) => `${alias} ${scopeSummary(item)}`).join('；')}</span><span>{shortSha(context.id)}</span></button>)}</div></details> : null}
    <details className="analysis-details"><summary>管理科目映射</summary>
      <p className="analysis-note">损益算不出来，多半是这里没配齐。引擎只认收入、成本、费用三个管理科目，把原表的科目代码归到这三类。</p>
      <div className="analysis-edit-grid"><label>映射名称<Input className="min-w-0 flex-1" value={mapName} disabled={locked} onChange={(event) => setMapName(event.target.value)}  /></label>
        <SearchableSelect label="已保存映射" value={accountMapId} disabled={locked} options={accountMapOptions(finance)} onChange={setAccountMapId}
          placeholder="搜索映射名称或编号" allowEmptyLabel="暂不使用" /></div>
      <AccountMapEditor value={mapRows} disabled={locked} onChange={setMapRows} />
      {accountMapId && <p className="analysis-note">当前口径保存时会使用映射 {shortSha(accountMapId)}。</p>}
      <Button variant="outline" type="button" disabled={locked || !mapRows.trim()} onClick={() => void saveMap()}>保存映射</Button>
    </details>
  </details>
  {/* Outside the settings: a run closes them on success, and the outcome must stay readable. */}
  {running ? <p role="status" className="analysis-message"><WaitOrb state="solving" />{running}</p>
    : message ? <p role="status" className="analysis-message">{message}</p> : null}
  {error && <p role="alert" className="analysis-message analysis-message--error">{error}</p>}
  {contextId ? <FinanceAdjustmentPanel taskId={taskId} contextId={contextId} busy={locked} onRefresh={onRefresh} /> : null}
  {contextId ? <FinanceChartPanel taskId={taskId} runs={runs} busy={locked} onRefresh={onRefresh} /> : null}
  </>;
}
function AnalysisEditor({ analysis, datasets, busy, edit, onEdit, onRun, onSave, onChat }: {
  analysis: AnalysisRevision; datasets: DatasetSnapshot[]; busy: boolean;
  edit?: AnalysisEdit; onEdit(edit: AnalysisEdit): void;
  onRun(): void; onSave(spec: Record<string, unknown>): void; onChat(spec?: Record<string, unknown>): void;
}) {
  const [sql, setSql] = useState(edit?.sql ?? analysis.sql ?? '');
  const [parameters, setParameters] = useState(edit?.parameters ?? analysis.parameters);
  const [assumptions, setAssumptions] = useState(edit?.assumptions ?? analysis.assumptions);
  const [bindings, setBindings] = useState(edit?.bindings ?? analysis.bindings);
  useEffect(() => { onEdit({ sql, parameters, assumptions, bindings }); }, [sql, parameters, assumptions, bindings, onEdit]);
  function updateParameter(key: string, value: unknown, next: string | boolean | null) {
    setParameters(Array.isArray(parameters)
      ? parameters.map((item, index) => String(index) === key ? typeof next === 'string' ? editItem(value, next) : next : item)
      : { ...parameters, [key]: typeof next === 'string' ? editItem(value, next) : next });
  }
  const calculationChanged = sql !== analysis.sql || JSON.stringify(parameters) !== JSON.stringify(analysis.parameters)
    || JSON.stringify(bindings) !== JSON.stringify(analysis.bindings);
  const changed = calculationChanged || JSON.stringify(assumptions) !== JSON.stringify(analysis.assumptions);
  const spec = () => ({
    question: analysis.question, sql, bindings, parameters, assumptions, parent_id: analysis.id,
    grain: analysis.grain, relationships: analysis.relationships, metrics: analysis.metrics,
    ...(analysis.parameter_metadata == null ? {} : { parameter_metadata: analysis.parameter_metadata }),
    ...(analysis.timeout_seconds == null ? {} : { timeout_seconds: analysis.timeout_seconds }),
    ...(analysis.max_rows == null ? {} : { max_rows: analysis.max_rows }),
    ...(analysis.missing_inputs == null ? {} : { missing_inputs: analysis.missing_inputs }),
    ...(analysis.conversion_rules == null ? {} : { conversion_rules: analysis.conversion_rules }),
  });
  const metadataFor = (key: string) => analysis.parameter_metadata?.find((metadata) => metadata.key.toLowerCase()
    === (Array.isArray(parameters) ? String(Number(key) + 1) : key.toLowerCase()));
  return <div className="analysis-definition">
    {calculationChanged && <p className="analysis-message" role="status">计算口径已修改，当前结果尚未更新。保存新版并重跑后查看新结果。</p>}
    {!calculationChanged && changed && <p className="analysis-note" role="status">假设说明已修改；说明文字本身不会改变计算。可以保存并交给助手继续调整。</p>}
    <details className="analysis-details analysis-definition-fold"><summary>口径与计算定义{changed ? ' · 有未提交修改' : ''}</summary>
    <div className="analysis-logic">{analysis.metrics?.length > 0 && <p>指标：{analysis.metrics.map(metricLabel).join('；')}</p>}
      {analysis.grain?.length > 0 && <p>计算粒度：{analysis.grain.map(textValue).join('；')}</p>}
      {analysis.relationships?.length > 0 && <p>资料关联：{analysis.relationships.map(textValue).join('；')}</p>}</div>
    {Boolean(analysis.missing_inputs?.length) && <p className="analysis-message">待补资料：{analysis.missing_inputs?.join('、')}</p>}
    <section className="analysis-details"><h4>参数、假设与资料</h4>
      <fieldset disabled={busy} className="analysis-fieldset"><div className="analysis-edit-grid">{Object.entries(bindings).map(([alias, id]) =>
        <SearchableSelect key={alias} label={`资料 · ${alias}`} value={id} options={datasetOptions(datasets)}
          onChange={(value) => setBindings({ ...bindings, [alias]: value })} placeholder="搜索资料名称、来源或快照" />)}
        {Object.entries(parameters).filter(([key]) => metadataFor(key)?.role === 'business').map(([key, value]) =>
          <ParameterField key={key} metadata={metadataFor(key)!} value={value} onChange={(next) => updateParameter(key, value, next)} />)}
        {assumptions.map((value, index) => <label key={`assumption-${index}`}>假设 · {itemLabel(value, index)}
          <Input className="min-w-0 flex-1" value={itemValue(value)} onChange={(event) => setAssumptions(assumptions.map((item, at) => at === index ? editItem(item, event.target.value) : item))}  /></label>)}
      </div>
      <details className="analysis-details"><summary>高级参数与公式常量</summary>
        <p className="analysis-note">未标注业务含义的参数按计算定义中的名称或顺序展示。</p>
        <div className="analysis-edit-grid">{Object.entries(parameters).filter(([key]) => metadataFor(key)?.role !== 'business').map(([key, value], index) =>
          <TextField key={key} label={`参数 · ${Array.isArray(parameters) ? itemLabel(value, index) : key}`} value={itemValue(value)}
            onChange={(next) => updateParameter(key, value, next)} />)}</div>
      </details>
      {Array.isArray(parameters) && <Button variant="outline" type="button" onClick={() => setParameters([...parameters, ''])}>添加计算参数</Button>}
      </fieldset>
      <p className="analysis-note">修改后保存并重跑会创建新版本，之前的结果仍可查看。</p>
      <p className="analysis-note">参数会传入计算，假设说明用于记录依据；改变计算口径可请助手更新表达式。</p>
      <Button variant="outline" type="button" disabled={busy} onClick={() => onChat(changed ? spec() : undefined)}>与助手调整口径</Button>
    </section>
    <details className="analysis-details"><summary>高级：查看或编辑计算 SQL</summary>
      <Textarea className="analysis-code" aria-label="计算 SQL" rows={7} value={sql} disabled={busy} onChange={(event) => setSql(event.target.value)} /></details>
    <div className="analysis-actions"><Button type="button" disabled={busy || !sql.trim()} onClick={() => onSave(spec())}>保存新版并重跑</Button><Button variant="outline" type="button" disabled={busy} onClick={onRun}>重跑当前已保存版本</Button></div>
    </details>
  </div>;
}
function DraftEditor({ taskId, draft, drafts, busy, runs, datasets, edit, onEdit, onSave, onExport, onChat, onDiscussRequirements, versionPicker, onLocatorPreview, onAppliedDraft }: {
  taskId: string; draft?: AnalysisDraft; drafts: AnalysisDraft[]; busy: boolean; runs: AnalysisRun[]; datasets: DatasetSnapshot[]; onSave(spec: Record<string, unknown>): void;
  edit?: DraftEdit; onEdit(edit: DraftEdit): void;
  onExport(format: 'docx' | 'pdf' | 'html' | 'md' | 'xlsx', spec?: Record<string, unknown>, mode?: 'management' | 'audit'): void | Promise<void>; onChat(spec?: Record<string, unknown>): void;
  onDiscussRequirements(request: Record<string, unknown>): void;
  versionPicker?: ReactNode;
  onLocatorPreview?(preview: import('../bridge.js').LocatorPreviewSpec): void;
  onAppliedDraft?(draft: AnalysisDraft): void;
}) {
  const initialEditUnsaved = Boolean(draft && edit && draftEditDiffers(draft, edit));
  const [title, setTitle] = useState(edit?.title ?? draft?.title ?? '经营分析');
  const [body, setBody] = useState(edit?.body ?? draft?.body ?? '');
  const [document, setDocument] = useState<ReportDraftDocument | undefined>(() => edit?.document ?? richDraftDocument(draft));
  const [limitations, setLimitations] = useState(edit?.limitations ?? draft?.limitations.join('\n') ?? '');
  const [review, setReview] = useState(edit?.review ?? draft?.review_status ?? 'unreviewed');
  const [materiality, setMateriality] = useState<MaterialityEdit>(() => edit?.materiality ?? materialityToEdit(draft?.materiality));
  const [recovery, setRecovery] = useState<FinanceCompletionRecovery | null>(edit?.recovery ?? null);
  const [reportMode, setReportMode] = useState<ReportMode>(() => (!draft || Boolean(edit && (edit.body !== draft.body || edit.title !== draft.title
    || edit.limitations !== draft.limitations.join('\n') || edit.review !== draft.review_status || !sameDocument(edit.document, richDraftDocument(draft)) || !sameMateriality(edit.materiality, draft.materiality) || edit.recovery))) ? 'edit' : 'read');
  const [quality, setQuality] = useState<ExplanationQuality | null>(initialEditUnsaved ? null : (draft?.quality as ExplanationQuality | undefined) ?? null);
  const [qualityState, setQualityState] = useState<'idle' | 'checking' | 'passed' | 'issues' | 'stale' | 'unavailable'>(initialEditUnsaved ? 'stale' : 'idle');
  const [updatedRequirementsId, setUpdatedRequirementsId] = useState<string | null>(null);
  const [recoveries, setRecoveries] = useState<FinanceCompletionRecovery[]>([]);
  const [recoveryError, setRecoveryError] = useState('');
  const [facts, setFacts] = useState<ExplanationFact[]>([]);
  const [factDetails, setFactDetails] = useState<Record<string, FinanceDrilldown>>({});
  const [locatorNotice, setLocatorNotice] = useState<Record<string, string>>({});
  const [locatorPdf, setLocatorPdf] = useState<{ factId: string; dataUrl: string; page?: number } | null>(null);
  const [backgrounds, setBackgrounds] = useState<FinanceBackground[]>([]);
  const [background, setBackground] = useState({ label: '', text: '', basis: 'professional_judgment', effective_from: '', effective_to: '', dataset_id: '', paragraph: '', source: '', retrieved_at: '' });
  const [backgroundScope, setBackgroundScope] = useState<Record<string, string>>({ ledger: '', organization: '', period: '', currency: '', unit: '' });
  const [scopeJson, setScopeJson] = useState('');
  const [backgroundMessage, setBackgroundMessage] = useState('');
  const [toolError, setToolError] = useState('');
  const [requirementsOpen, setRequirementsOpen] = useState(!draft);
  const qualityRequest = useRef(0);
  const factRequest = useRef(0);
  const backgroundRequest = useRef(0);
  const recoveryRequest = useRef(0);
  const draftRuns = runs.filter((run) => draft?.run_ids.includes(run.id));
  const parentDraft = drafts.find((candidate) => candidate.id === draft?.parent_id);
  const previousRun = runs.find((run) => parentDraft?.run_ids.includes(run.id));
  const comparison = draft?.revision_comparison;
  const affectedClaims = (comparison?.issues ?? []).filter((issue) => issue.code === 'revision_numeric_regression').map((issue) => ({
    label: `${issue.column ?? '指标'} · 原值 ${issue.old_value ?? ''} → 新值 ${issue.new_value ?? ''}`,
    message: `${(draft?.claims ?? []).filter((claim) => Boolean(claim && typeof claim === 'object'
      && (claim as Record<string, unknown>).column === issue.column
      && [(issue as { old_run_id?: string }).old_run_id, (issue as { new_run_id?: string }).new_run_id].includes(String((claim as Record<string, unknown>).run_id)))).length} 条计算引用需要按当前版本核对。`,
  }));
  const financeRuns = draftRuns.filter((run) => (run.engine === 'finance' || run.engine === 'structured_aggregate'));
  const primaryFinanceRun = financeRuns[0];
  const defaultScope = firstFinanceScope(primaryFinanceRun);
  const contextId = primaryFinanceRun?.finance_context_id;
  const effectiveRunIds = recovery?.run_ids ?? draft?.run_ids ?? [];
  const effectiveClaims = recovery ? (recovery.claims ?? []) : (draft?.claims ?? []);
  const citedFactIds = explicitFactIds(recovery ? undefined : draft, body, recovery?.fact_ids);
  const boundDatasetIds = Array.from(new Set(draftRuns.flatMap((run) => Object.values(run.bindings ?? {}))));
  const sourceDatasets = datasets.filter((source) => boundDatasetIds.includes(source.id));
  const materialitySpec = materialityToSpec(materiality);
  const materialityChanged = !sameMateriality(materiality, draft?.materiality);
  const materialityError = materiality.relative.trim().startsWith('-') ? '相对阈值不能为负数。0.1 表示 10%。' : '';
  const hasUnsavedQualityInputs = Boolean(draft && ((edit?.body != null && edit.body !== draft.body) || materialityChanged
    || (updatedRequirementsId && updatedRequirementsId !== draft.requirements_id) || recovery));
  const reading = readableDraftParts(body, draft?.evidence_appendix);
  useEffect(() => { onEdit({ title, body, limitations, review, document, materiality, recovery }); }, [title, body, limitations, review, document, materiality, recovery, onEdit]);
  useEffect(() => {
    setTitle(edit?.title ?? draft?.title ?? '经营分析');
    setBody(edit?.body ?? draft?.body ?? '');
    setDocument(edit?.document ?? richDraftDocument(draft));
    setLimitations(edit?.limitations ?? draft?.limitations.join('\n') ?? '');
    setReview(edit?.review ?? draft?.review_status ?? 'unreviewed');
    setMateriality(edit?.materiality ?? materialityToEdit(draft?.materiality));
    setRecovery(edit?.recovery ?? null);
    const restoredUnsaved = Boolean(draft && edit && draftEditDiffers(draft, edit));
    setQuality(restoredUnsaved ? null : (draft?.quality as ExplanationQuality | undefined) ?? null);
    setQualityState(restoredUnsaved ? 'stale' : 'idle');
    setUpdatedRequirementsId(null);
    setRequirementsOpen(!draft);
    setReportMode(!draft || restoredUnsaved ? 'edit' : 'read');
    setFacts([]); setFactDetails({}); setBackgrounds([]); setToolError(''); setBackgroundMessage('');
    setBackgroundScope(scopeToFields(defaultScope)); setScopeJson(JSON.stringify(defaultScope, null, 2));
    qualityRequest.current += 1; factRequest.current += 1; backgroundRequest.current += 1;
  }, [draft?.id]);
  const loadRecoveries = useCallback(async () => {
    const api = bridge(); if (!api?.financeCall) return;
    const request = ++recoveryRequest.current;
    setRecoveryError('');
    try {
      const answer = await api.financeCall(taskId, 'finance-completion-recoveries');
      if (request !== recoveryRequest.current) return;
      const result = unwrap(answer as Answer<{ recoveries?: FinanceCompletionRecovery[] }>);
      setRecoveries((result.recoveries ?? []).filter(isVisibleRecovery));
    } catch (failure) {
      if (request === recoveryRequest.current) {
        setRecoveries([]);
        setRecoveryError(failure instanceof Error ? failure.message : String(failure));
      }
    }
  }, [taskId]);
  useEffect(() => {
    void loadRecoveries();
    return () => { recoveryRequest.current += 1; };
  }, [loadRecoveries]);
  useEffect(() => {
    if (Object.values(backgroundScope).some(Boolean)) return;
    const next = scopeToFields(defaultScope);
    if (Object.values(next).some(Boolean)) { setBackgroundScope(next); setScopeJson(JSON.stringify(defaultScope, null, 2)); }
  }, [primaryFinanceRun?.id]);
  useEffect(() => {
    if (!draft || !draft.run_ids.length) return;
    const api = bridge();
    if (!api?.financeCall) { setQuality(null); setQualityState('unavailable'); return; }
    const request = ++qualityRequest.current;
    const bgRequest = ++backgroundRequest.current;
    if (hasUnsavedQualityInputs) {
      setQuality(null); setQualityState('stale'); setToolError('');
      void loadBackgrounds(bgRequest, defaultScope);
      return () => { qualityRequest.current += 1; factRequest.current += 1; backgroundRequest.current += 1; };
    }
    setQuality(null); setQualityState('checking'); setToolError('');
    void Promise.allSettled([
      api.financeCall(taskId, 'prepare-explanation', { run_ids: draft.run_ids, materiality: materialitySpec }),
      api.financeCall(taskId, 'validate-explanation', edit?.body != null && edit.body !== draft.body || materialityChanged || updatedRequirementsId
        ? { draft_id: draft.id, body, run_ids: draft.run_ids, fact_ids: citedFactIds, claims: draft.claims,
          ...(updatedRequirementsId ? { requirements_id: updatedRequirementsId } : {}), materiality: materialitySpec }
        : { draft_id: draft.id, materiality: materialitySpec }),
    ]).then(([prepared, checked]) => {
      if (request !== qualityRequest.current) return;
      if (prepared.status === 'fulfilled') {
        const value = unwrap(prepared.value as Answer<ExplanationPreparation>);
        setFacts(value.facts ?? []);
        if (value.business_contexts?.length) setBackgrounds(value.business_contexts);
      }
      if (checked.status === 'fulfilled') {
        const value = unwrap(checked.value as Answer<ExplanationQuality>);
        setQuality(value);
        setQualityState(qualityStateFromResult(value));
      } else setQualityState('unavailable');
    }).catch((failure) => { if (request === qualityRequest.current) { setQualityState('unavailable'); setToolError(failure instanceof Error ? failure.message : String(failure)); } });
    void loadBackgrounds(bgRequest, defaultScope);
    return () => { qualityRequest.current += 1; factRequest.current += 1; backgroundRequest.current += 1; };
  }, [draft?.id, taskId]);
  const changed = !draft || title !== draft.title || body !== draft.body || !sameDocument(document, richDraftDocument(draft)) || limitations !== draft.limitations.join('\n') || review !== draft.review_status
    || Boolean(updatedRequirementsId && updatedRequirementsId !== draft.requirements_id) || materialityChanged || Boolean(recovery);
  const canLoadRecovery = !hasMeaningfulUnsavedDraft(draft, { title, body, limitations, review, materiality, recovery }, materialityChanged);
  function spec(publication: 'draft' | 'archived') {
    const parentId = recovery ? recovery.parent_id : draft?.id;
    return { title: title.trim(), body, ...(document ? { document } : richDraftDocument(draft) ? { document: null } : {}), run_ids: effectiveRunIds, claims: effectiveClaims, ...(citedFactIds.length ? { fact_ids: citedFactIds } : {}),
      ...(recovery ? { recovery_ref: { operation_id: recovery.operation_id, revision: recovery.revision },
        evidence_recipes: recovery.evidence_recipes ?? [], consistency_rules: recovery.consistency_rules ?? [], consistency_sources: recovery.consistency_sources ?? [] } : {}),
      ...(parentId ? { parent_id: parentId } : {}),
      ...((updatedRequirementsId ?? recovery?.requirements_id) ? { requirements_id: updatedRequirementsId ?? recovery?.requirements_id } : {}),
      materiality: materialitySpec, publication_status: publication, review_status: review,
      limitations: limitations.split('\n').map((line) => line.trim()).filter(Boolean) };
  }
  async function recheck() {
    if (!draft && !recovery) return;
    const api = bridge(); if (!api?.financeCall) { setQuality(null); setQualityState('unavailable'); return; }
    const request = ++qualityRequest.current;
    try {
      setQuality(null); setQualityState('checking'); setToolError('');
      const prepared = unwrap(await api.financeCall(taskId, 'prepare-explanation', { run_ids: effectiveRunIds, materiality: materialitySpec }) as Answer<ExplanationPreparation>);
      if (request !== qualityRequest.current) return;
      setFacts(prepared.facts ?? []);
      const checked = unwrap(await api.financeCall(taskId, 'validate-explanation', { ...(recovery ? {} : { draft_id: draft!.id }), body, review_status: review, run_ids: effectiveRunIds, fact_ids: explicitFactIds(recovery ? undefined : draft, body, recovery?.fact_ids), claims: effectiveClaims,
        ...(recovery ? { evidence_recipes: recovery.evidence_recipes ?? [], consistency_rules: recovery.consistency_rules ?? [], consistency_sources: recovery.consistency_sources ?? [] } : {}),
        ...((updatedRequirementsId ?? recovery?.requirements_id) ? { requirements_id: updatedRequirementsId ?? recovery?.requirements_id } : {}), materiality: materialitySpec }) as Answer<ExplanationQuality>);
      if (request !== qualityRequest.current) return;
      setQuality(checked); setQualityState(qualityStateFromResult(checked));
    } catch (failure) {
      if (request === qualityRequest.current) { setQuality(null); setQualityState('unavailable'); setToolError(failure instanceof Error ? failure.message : String(failure)); }
    }
  }
  async function openFact(fact: ExplanationFact) {
    const api = bridge(); if (!api?.financeCall || fact.row == null) return;
    const request = ++factRequest.current;
    try {
      setToolError('');
      const result = unwrap(await api.financeCall(taskId, 'drilldown-fact', { run_id: fact.run_id, row: fact.row, ...(fact.column ? { column: fact.column } : {}), offset: 0, limit: 100 }) as Answer<FinanceDrilldown>);
      if (request === factRequest.current) setFactDetails((value) => ({ ...value, [fact.id]: result }));
    } catch (failure) { if (request === factRequest.current) setToolError(failure instanceof Error ? failure.message : String(failure)); }
  }
  async function openLocator(fact: ExplanationFact) {
    const api = bridge();
    const request = ++factRequest.current;
    try {
      setToolError('');
      setLocatorNotice((value) => ({ ...value, [fact.id]: '' }));
      setLocatorPdf(null);
      if (!api?.sourceLocatorOpen) {
        await openFact(fact);
        return;
      }
      const located = unwrap(await api.sourceLocatorOpen(taskId, { fact_id: fact.id }));
      if (request !== factRequest.current) return;
      if (located.status === 'locator_forbidden') {
        setLocatorNotice((value) => ({ ...value, [fact.id]: '无权打开' }));
        return;
      }
      if (located.status === 'locator_unavailable') {
        await openFact(fact);
        return;
      }
      if (located.preview?.available === false) {
        setLocatorNotice((value) => ({ ...value, [fact.id]: '该页未归档' }));
        await openFact(fact);
        return;
      }
      if (located.viewer === 'univer' && located.sha256 && located.task) {
        onLocatorPreview?.({ task: located.task, sha256: located.sha256, excel_range: typeof located.locator?.excel_range === 'string' ? located.locator.excel_range : undefined });
        return;
      }
      if (located.viewer === 'pdf') {
        // A locator names a dataset, not a report source. The archived page
        // is the report source whose bytes hash to the locator's source; a
        // draft that imported no such file has no page to show.
        const sourceHash = typeof located.locator?.source_hash === 'string' ? located.locator.source_hash : '';
        const archived = sourceHash ? document?.sources?.find((item) => item.sha256 === sourceHash) : undefined;
        if (!api.reportSource || !archived) {
          setLocatorNotice((value) => ({ ...value, [fact.id]: '该页未归档' }));
          await openFact(fact);
          return;
        }
        const payload = unwrap(await api.reportSource(taskId, archived.id) as Answer<{ data_base64?: string }>);
        if (!payload.data_base64) {
          setLocatorNotice((value) => ({ ...value, [fact.id]: '该页未归档' }));
          await openFact(fact);
          return;
        }
        const page = typeof located.locator?.page === 'number' && Number.isInteger(located.locator.page) && located.locator.page > 0 ? located.locator.page : undefined;
        setLocatorPdf({ factId: fact.id, dataUrl: `data:application/pdf;base64,${payload.data_base64}`, ...(page ? { page } : {}) });
        return;
      }
      await openFact(fact);
    } catch (failure) { if (request === factRequest.current) setToolError(locatorFailureText(failure)); }
  }
  async function loadBackgrounds(request = ++backgroundRequest.current, scopeOverride?: Record<string, unknown>) {
    const api = bridge(); if (!api?.financeCall) return;
    try {
      const scope = scopeOverride ?? currentBackgroundScope(backgroundScope, scopeJson);
      const result = unwrap(await api.financeCall(taskId, 'finance-background-list', { ...(contextId ? { context_id: contextId } : {}), scope, as_of: scope.period }) as Answer<{ backgrounds?: FinanceBackground[]; business_contexts?: FinanceBackground[]; items?: FinanceBackground[] }>);
      if (request === backgroundRequest.current) setBackgrounds(result.backgrounds ?? result.business_contexts ?? result.items ?? []);
    } catch { /* background list is optional for old backends */ }
  }
  async function saveBackground() {
    const api = bridge(); if (!api?.financeCall) { setToolError('此版本暂不支持财务背景。'); return; }
    const request = ++backgroundRequest.current;
    try {
      setToolError(''); setBackgroundMessage('');
      const scope = currentBackgroundScope(backgroundScope, scopeJson);
      const paragraph = background.paragraph.trim() ? Number(background.paragraph) : undefined;
      if (background.basis === 'source_fact' && (!background.dataset_id || !paragraph)) throw new Error('资料事实需要选择授权资料并填写段落编号。');
      if (background.basis === 'external_reference' && (!background.source.trim() || !background.retrieved_at.trim())) throw new Error('外部依据需要填写来源和查询日期。');
      const saved = unwrap(await api.financeCall(taskId, 'finance-background-save', {
        ...(contextId ? { context_id: contextId } : {}), label: background.label.trim() || undefined, text: background.text.trim(), basis: background.basis,
        scope, effective_from: background.effective_from || scope.period, effective_to: background.effective_to || undefined,
        ...(background.basis === 'source_fact' && background.dataset_id ? { dataset_id: background.dataset_id } : {}),
        ...(background.basis === 'source_fact' && paragraph ? { paragraph } : {}),
        ...(background.basis === 'external_reference' ? { external_reference: externalReferencePayload(background.source.trim(), background.retrieved_at.trim()) } : {}),
      }) as Answer<FinanceBackground>);
      if (request !== backgroundRequest.current) return;
      setBackgroundMessage('已保存财务背景。'); setBackground({ ...background, label: '', text: '', paragraph: '', source: '', retrieved_at: '' });
      setBackgrounds((value) => [saved, ...value.filter((item) => item.id !== saved.id)]);
    } catch (failure) { if (request === backgroundRequest.current) setToolError(failure instanceof Error ? failure.message : String(failure)); }
  }
  function markQualityStale() {
    qualityRequest.current += 1;
    setQuality(null); setQualityState('stale');
  }
  function onBodyChange(value: string) {
    markQualityStale();
    setBody(value); setReview('unreviewed');
  }
  function onDocumentChange(value: ReportDraftDocument | undefined) {
    markQualityStale();
    setDocument(value);
  }
  function onMaterialityChange(next: MaterialityEdit) {
    setMateriality(next);
    markQualityStale();
  }
  function loadRecovery(next: FinanceCompletionRecovery) {
    if (!canLoadRecovery) return;
    setRecovery(next);
    setTitle(next.title?.trim() || title);
    setBody(next.body ?? '');
    setDocument(richRecoveryDocument(next));
    setLimitations(Array.isArray(next.limitations) ? next.limitations.join('\n') : textValue(next.limitations ?? ''));
    if (next.materiality) setMateriality(materialityToEdit(next.materiality));
    setReview('unreviewed');
    setReportMode('edit');
    markQualityStale();
  }
  return <div className="analysis-draft">
    <CompletionRecoveriesPanel recoveries={recoveries} error={recoveryError} disabled={busy || !canLoadRecovery} onRetry={() => void loadRecoveries()} onLoad={loadRecovery} />
    {recoveries.length > 0 && !canLoadRecovery && <p className="analysis-note">当前有未保存输入；保存或放弃当前修改后再载入恢复稿，避免覆盖你的编辑。</p>}
    {recovery && <p role="status" className="analysis-message">已载入未保存恢复稿，尚未检查；保存后才会成为新的文稿版本。</p>}
    {recovery && <ClaimBindingRepair claims={effectiveClaims} runs={runs.filter((run) => effectiveRunIds.includes(run.id))} disabled={busy}
      onChange={(claims) => { setRecovery({ ...recovery, claims }); markQualityStale(); setReview('unreviewed'); }} />}
    <div className="analysis-draft-navigation" data-expanded={bridge()?.financeCall && requirementsOpen ? 'true' : undefined}>
    {versionPicker && <div className="analysis-version-picker">{versionPicker}</div>}
    {bridge()?.financeCall && <details className="analysis-details analysis-requirements" open={requirementsOpen}
      onToggle={(event) => setRequirementsOpen((event.currentTarget as HTMLDetailsElement).open)}>
      <summary>本次分析要求</summary>
      <RequirementsPanel taskId={taskId} contextId={contextId} draftRequirementsId={draft?.requirements_id ?? undefined}
        onChanged={(requirements) => { qualityRequest.current += 1; setUpdatedRequirementsId(requirements.id); setQuality(null); setQualityState('stale'); }}
        onDiscuss={onDiscussRequirements} />
    </details>}
    </div>
    <ReportEditor key={`${draft?.id ?? 'new'}`} taskId={taskId} draftId={draft?.id} contextId={contextId} title={title} body={body} appendix={reading.appendix}
      toolbarLabel={draft ? '文稿' : '写下判断与建议'}
      status={draft ? `${STATUS[draft.publication_status] ?? draft.publication_status} · ${STATUS[draft.review_status] ?? draft.review_status} · 检查：${qualityShortLabel(qualityState)}` : undefined}
      assistantAction={<Button variant="ghost" size="sm" type="button" aria-label={draft ? '围绕此稿继续分析' : '请助手整理文稿'} title={draft ? '围绕此稿继续分析' : '请助手整理文稿'}
        disabled={busy || Boolean(draft && changed && (!title.trim() || !body.trim() || materialityError))}
        onClick={() => onChat(changed && body.trim() ? spec('draft') : undefined)}><MessageSquare size={14} aria-hidden />{draft ? '继续分析' : '请助手整理文稿'}</Button>}
      limitations={limitations} review={review} document={document} busy={busy} initialMode={reportMode} mode={reportMode} onMode={setReportMode} onTitle={setTitle}
      onBody={onBodyChange} onDocument={onDocumentChange} onLimitations={setLimitations} onReview={setReview} onExport={(format, mode) => onExport(format, changed ? spec('draft') : undefined, mode)}
      onAppliedDraft={onAppliedDraft} />
    {draft && parentDraft && draftRuns[0] && <RevisionDiff current={draftRuns[0]} previous={previousRun} comparison={comparison}
      currentRevision={drafts.findIndex((item) => item.id === draft.id) + 1} previousRevision={drafts.findIndex((item) => item.id === parentDraft.id) + 1}
      evidence={{ affected_claims: affectedClaims, unresolved_issues: quality?.issues ?? [] }} />}
    {/* Everything that decides whether this version can go out, after the text it checks. */}
    <section className="analysis-prepublish" aria-label="发布前检查">
    <div className="analysis-section-heading"><h3>发布前检查</h3><p className="analysis-note">质量检查、重要性阈值、引用的计算和经理判断背景。</p></div>
    {(draft || recovery) && <ExplanationQualityPanel taskId={taskId} quality={quality} state={qualityState} facts={facts} citedFactIds={citedFactIds} factDetails={factDetails} locatorNotice={locatorNotice} locatorPdf={locatorPdf} busy={busy} onRecheck={() => void recheck()} onOpenFact={(fact) => void openFact(fact)} onOpenLocator={(fact) => void openLocator(fact)} />}
    <fieldset className="analysis-fieldset analysis-draft-fields" disabled={busy}>
    <MaterialityFields value={materiality} scopeText={materialityScopeSummary(financeRuns)} error={materialityError} disabled={busy} onChange={onMaterialityChange} />
    </fieldset>
    {draft && <details className="analysis-details"><summary>引用的计算与依据 · {draft.run_ids.length} 次运行</summary>
      {draft.run_ids.length === 0 && <p>这份文稿尚未引用计算记录。</p>}
      {draft.run_ids.map((id) => { const run = runs.find((item) => item.id === id); return <div key={id}>
        <p>{id}</p>{run ? <RunStatus run={run} /> : <p>此运行记录暂不可读取。</p>}</div>; })}
      {draft.claims.map((claim, index) => <p key={index}>{textValue(claim)}</p>)}</details>}
    {draft && financeRuns.length > 0 && <FinanceBackgroundPanel background={background} scope={backgroundScope} scopeJson={scopeJson} backgrounds={backgrounds} datasets={sourceDatasets} busy={busy}
      message={backgroundMessage} onBackground={setBackground} onScope={setBackgroundScope} onScopeJson={setScopeJson} onSave={() => void saveBackground()} onList={() => void loadBackgrounds()} />}
    </section>
    <div className="analysis-actions">{changed && <Button type="button" disabled={busy || !title.trim() || !body.trim() || Boolean(materialityError)} onClick={() => onSave(spec('draft'))}>保存文稿新版</Button>}
      <Button variant="outline" type="button" disabled={busy || !title.trim() || !body.trim() || Boolean(materialityError)} onClick={() => onSave(spec('archived'))}>选定并归档此版</Button></div>
    {changed && <p className="analysis-note">交给助手或导出时，会先保存当前内容为新版本。</p>}
    {toolError && <p role="alert" className="analysis-message analysis-message--error">{toolError}</p>}
  </div>;
}


const denominatorOptions: SelectOption[] = [
  { value: 'baseline_abs', label: '按基准金额' },
  { value: 'actual_abs', label: '按实际金额' },
  { value: 'max_abs', label: '按较大金额' },
];
const negativePolicyOptions: SelectOption[] = [
  { value: 'absolute', label: '按绝对值比较' },
  { value: 'signed', label: '保留正负方向' },
];
function validDenominator(value: unknown): MaterialityDenominator {
  return value === 'actual_abs' || value === 'max_abs' ? value : 'baseline_abs';
}

function validNegativePolicy(value: unknown): MaterialityNegativePolicy {
  return value === 'signed' ? 'signed' : 'absolute';
}

function materialityToEdit(value: unknown): MaterialityEdit {
  const source = value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
  const relativeObject = source.relative && typeof source.relative === 'object' && !Array.isArray(source.relative) ? source.relative as Record<string, unknown> : null;
  const relativeValue = relativeObject ? relativeObject.threshold ?? relativeObject.value : source.relative;
  return {
    absolute: String(source.absolute ?? '0'),
    relative: relativeValue == null ? '' : String(relativeValue),
    denominator: validDenominator(relativeObject?.denominator),
    negativePolicy: validNegativePolicy(relativeObject?.negative_policy),
  };
}

function materialityToSpec(value: MaterialityEdit): Record<string, unknown> {
  const absolute = value.absolute.trim() || '0';
  const relative = value.relative.trim();
  return {
    absolute,
    ...(relative ? { relative: { threshold: relative, denominator: value.denominator, negative_policy: value.negativePolicy } } : {}),
  };
}

function sameMateriality(edit: MaterialityEdit | undefined, saved: unknown): boolean {
  return JSON.stringify(materialityToSpec(edit ?? materialityToEdit(undefined))) === JSON.stringify(materialityToSpec(materialityToEdit(saved)));
}


function materialityScopeSummary(runs: AnalysisRun[]): string {
  const groups = Array.from(new Set(runs.flatMap((run) => Object.values(run.finance_scope ?? {}).map((scope) => {
    const currency = scope.currency ? textValue(scope.currency) : '未注明币种';
    const unit = scope.unit ? textValue(scope.unit) : '未注明单位';
    return `${currency}/${unit}`;
  }))));
  if (!groups.length) return '按运行结果的原币原单位判断；当前运行未注明币种或单位。';
  if (groups.length === 1) return `按运行结果原币原单位判断：${groups[0]}。`;
  return `按每组运行结果的原币原单位判断：${groups.join('；')}。`;
}

function MaterialityFields({ value, scopeText, error, disabled, onChange }: { value: MaterialityEdit; scopeText: string; error?: string; disabled?: boolean; onChange(value: MaterialityEdit): void }) {

  const set = (patch: Partial<MaterialityEdit>) => onChange({ ...value, ...patch });
  // Folded by default with the values in its summary; an error opens it, and
  // clearing the error never closes it under the manager's cursor.
  const [open, setOpen] = useState(Boolean(error));
  useEffect(() => { if (error) setOpen(true); }, [error]);
  const summary = [value.absolute && `绝对 ${value.absolute}`, value.relative && `相对 ${value.relative}`].filter(Boolean).join(' · ');
  return <details className="analysis-details" open={open} onToggle={(event) => setOpen((event.currentTarget as HTMLDetailsElement).open)}>
    <summary>重要性阈值{summary ? ` · ${summary}` : ' · 未设置'}</summary>
    <p className="analysis-note">用于准备可引用事实和重检覆盖范围。相对阈值填 0.1 表示 10%。</p>
    <div className="analysis-edit-grid">
      <DecimalInput label="重要性绝对金额" value={value.absolute} onChange={(absolute) => set({ absolute })} placeholder="0"
        disabled={disabled} help="只填阈值，不做单位换算。" />
      <FieldShell label="阈值单位"><p className="analysis-note">{scopeText}</p></FieldShell>
      <DecimalInput label="相对重要性阈值" value={value.relative} onChange={(relative) => set({ relative })} placeholder="0.1" unit="比例"
        disabled={disabled} help={error || '可选；0.1 = 10%，留空则只使用绝对金额。'} />
      <SearchableSelect label="相对分母" value={value.denominator} options={denominatorOptions} onChange={(denominator) => set({ denominator: validDenominator(denominator) })}
        disabled={disabled} />
      <SearchableSelect label="负数比较规则" value={value.negativePolicy} options={negativePolicyOptions} onChange={(negativePolicy) => set({ negativePolicy: validNegativePolicy(negativePolicy) })}
        disabled={disabled} />
    </div>
    {error ? <p role="alert" className="analysis-message analysis-message--error">{error}</p> : null}
  </details>;
}

function firstFinanceScope(run?: AnalysisRun): Record<string, unknown> {
  const scopes = Object.values(run?.finance_scope ?? {});
  return scopes[0] ?? {};
}

function scopeToFields(scope: Record<string, unknown>): Record<string, string> {
  return Object.fromEntries(['ledger', 'organization', 'period', 'currency', 'unit'].map((key) => [key, scope[key] == null ? '' : textValue(scope[key])])) as Record<string, string>;
}

function currentBackgroundScope(fields: Record<string, string>, extraJson: string): Record<string, unknown> {
  const base = Object.fromEntries(Object.entries(fields).filter(([, value]) => value.trim()).map(([key, value]) => [key, value.trim()]));
  return { ...parseObject(extraJson, '高级范围 JSON'), ...base };
}

function parseObject(value: string, label: string): Record<string, unknown> {
  if (!value.trim()) return {};
  const parsed = JSON.parse(value);
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error(`${label} 需要是对象。`);
  return parsed as Record<string, unknown>;
}

function explicitFactIds(draft: AnalysisDraft | undefined, body: string, extraFactIds: string[] = []): string[] {
  const fromDraft = draft?.fact_ids ?? [];
  const fromBody = Array.from(body.matchAll(/\{\{\s*fact:([A-Za-z0-9_.:-]+)\s*\}\}/g), (match) => match[1]);
  return Array.from(new Set([...fromDraft, ...extraFactIds, ...fromBody].filter(Boolean)));
}

function isVisibleRecovery(item: FinanceCompletionRecovery): boolean {
  return ['repair_available', 'timed_out', 'cancelled', 'failed', 'needs_review', 'awaiting_input'].includes(item.status)
    && Boolean(String(item.body ?? item.title ?? '').trim());
}

function recoveryLimitationsText(value: FinanceCompletionRecovery['limitations']): string {
  return Array.isArray(value) ? value.filter(Boolean).join('；') : textValue(value ?? '');
}

function hasMeaningfulUnsavedDraft(draft: AnalysisDraft | undefined, edit: DraftEdit, materialityChanged: boolean): boolean {
  if (draft) {
    return draftEditDiffers(draft, edit) || materialityChanged || Boolean(edit.recovery);
  }
  return Boolean(edit.body.trim() || edit.limitations.trim() || (edit.title.trim() && edit.title.trim() !== '经营分析') || edit.recovery);
}

function draftEditDiffers(draft: AnalysisDraft, edit: DraftEdit): boolean {
  return edit.title !== draft.title || edit.body !== draft.body || edit.limitations !== draft.limitations.join('\n')
    || edit.review !== draft.review_status || !sameDocument(edit.document, richDraftDocument(draft)) || !sameMateriality(edit.materiality, draft.materiality) || Boolean(edit.recovery);
}

function richDraftDocument(draft: AnalysisDraft | undefined): ReportDraftDocument | undefined {
  const value = (draft as (AnalysisDraft & { document?: unknown }) | undefined)?.document;
  return isReportDocument(value) ? value : undefined;
}

function richRecoveryDocument(recovery: FinanceCompletionRecovery): ReportDraftDocument | undefined {
  const value = (recovery as FinanceCompletionRecovery & { document?: unknown }).document;
  return isReportDocument(value) ? value : undefined;
}

function isReportDocument(value: unknown): value is ReportDraftDocument {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value)
    && (value as { schema_version?: unknown }).schema_version === 1
    && (value as { template_version?: unknown }).template_version === 'annual-v1'
    && Array.isArray((value as { content?: unknown }).content));
}

function sameDocument(left?: ReportDraftDocument, right?: ReportDraftDocument): boolean {
  return JSON.stringify(left ?? null) === JSON.stringify(right ?? null);
}

function sourceFormatLabel(format: 'docx' | 'pdf' | 'html' | 'md' | 'xlsx'): string {
  return ({ docx: 'Word', pdf: 'PDF', html: 'HTML', md: '文稿', xlsx: '工作簿' } as Record<typeof format, string>)[format];
}

function recoveryStatusLabel(status: string): string {
  return ({ repair_available: '可修复', timed_out: '超时', cancelled: '已取消', failed: '失败', needs_review: '待审阅', awaiting_input: '等待输入' } as Record<string, string>)[status] ?? status;
}

function recoveryValidationText(item: FinanceCompletionRecovery): string {
  const error = item.validation_error;
  if (!error) return '';
  const first = Array.isArray(error.details) ? error.details[0] : null;
  if (first && typeof first === 'object') {
    const detail = first as Record<string, unknown>;
    const location = [detail.run_id, detail.row, detail.column].filter((part) => part !== undefined && part !== null && String(part).trim()).join(' / ');
    const values = detail.expected !== undefined || detail.actual !== undefined
      ? `填报 ${textValue(detail.expected ?? '')}，结果 ${textValue(detail.actual ?? '')}`
      : '';
    return [location, values].filter(Boolean).join('：');
  }
  return textValue(error.message ?? '');
}

function CompletionRecoveriesPanel({ recoveries, error, disabled, onRetry, onLoad }: {
  recoveries: FinanceCompletionRecovery[]; error?: string; disabled: boolean; onRetry(): void; onLoad(recovery: FinanceCompletionRecovery): void;
}) {
  if (!recoveries.length && !error) return null;
  return <details className="analysis-details analysis-recovery-panel">
    <summary>可恢复的未保存文稿 · {recoveries.length} 条</summary>
    <p className="analysis-note">这些内容来自已终止但尚未落成文稿版本的操作。载入后只是可编辑副本，需要你检查并保存。</p>
    {error && <p role="alert" className="analysis-message analysis-message--error">恢复稿读取失败：{error} <Button variant="outline" type="button" onClick={onRetry}>重试</Button></p>}
    <div className="analysis-history-list">{recoveries.map((item) => <div className="analysis-history-row analysis-history-row--static" key={item.operation_id}>
      <span>{item.title?.trim() || '未命名恢复稿'}</span>
      <span>{recoveryStatusLabel(item.status)}{item.updated_at ? ` · ${when(item.updated_at)}` : ''}{item.revision ? ` · ${item.revision}` : ''}</span>
      <span>{recoveryValidationText(item) || recoveryLimitationsText(item.limitations) || `${item.run_ids?.length ?? 0} 次运行 · ${item.fact_ids?.length ?? 0} 条事实`}</span>
      <Button variant="outline" type="button" disabled={disabled} onClick={() => onLoad(item)}>载入可编辑副本</Button>
    </div>)}</div>
  </details>;
}

function qualityStateFromResult(value: ExplanationQuality): 'passed' | 'issues' | 'unavailable' {
  if (value.status === 'pass') return 'passed';
  if ((value.issues ?? []).length || ['needs_attention', 'issues', 'failed'].includes(String(value.status ?? ''))) return 'issues';
  return 'unavailable';
}

function externalReferencePayload(source: string, retrievedAt: string): Record<string, string> {
  const payload: Record<string, string> = { title: source, retrieved_at: retrievedAt };
  if (/^https?:\/\//i.test(source)) payload.url = source;
  return payload;
}

/** The check state in the document toolbar, one word beside 草稿 · 未阅; the panel below says it in full. */
function qualityShortLabel(state: 'idle' | 'checking' | 'passed' | 'issues' | 'stale' | 'unavailable'): string {
  return ({ idle: '未检查', checking: '进行中', passed: '通过', issues: '待复核', stale: '改稿后未重检', unavailable: '不可用' } as Record<typeof state, string>)[state];
}

function qualityLabel(state: 'idle' | 'checking' | 'passed' | 'issues' | 'stale' | 'unavailable'): string {
  return ({ idle: '尚未检查', checking: '检查中', passed: '检查通过', issues: '需要复核', stale: '待重检', unavailable: '暂不可检查' } as Record<typeof state, string>)[state];
}

function coverageSummary(coverage: unknown): string {
  if (!coverage || typeof coverage !== 'object') return '';
  const value = coverage as Record<string, unknown>;
  const required = value.required ?? value.required_facts ?? value.total;
  const cited = value.cited ?? value.cited_facts ?? value.matched;
  if (required != null && cited != null) return `覆盖 ${textValue(cited)}/${textValue(required)} 条关键事实`;
  return '';
}

function factLabel(fact: ExplanationFact): string {
  const value = textValue(fact.display_value ?? fact.value);
  const label = String(fact.label ?? '').split(' / ').map((part) => STATUS[part] ?? metricLabel(part)).join(' / ');
  return [label, value, fact.unit && !value.includes(fact.unit) ? fact.unit : ''].filter(Boolean).join(' · ') || fact.id;
}

/** Main answers a failed locator open with a code, not a sentence; the sentence is written here. */
const LOCATOR_FAILURES: Record<string, string> = {
  locator_forbidden: '无权打开',
  locator_unavailable: '原文定位暂不可用',
  preview_unavailable: '预览暂不可用',
  locator_error: '原文定位失败',
};

function locatorFailureText(failure: unknown): string {
  const message = failure instanceof Error ? failure.message : String(failure);
  return LOCATOR_FAILURES[message] ?? message;
}

const qualityChecks = [['numbers', '数字与口径'], ['coverage', '问题覆盖'], ['provenance', '来源追溯']] as const;

function ExplanationQualityPanel({ taskId, quality, state, facts, citedFactIds, factDetails, locatorNotice, locatorPdf, busy, onRecheck, onOpenFact, onOpenLocator }: {
  taskId: string; quality: ExplanationQuality | null; state: 'idle' | 'checking' | 'passed' | 'issues' | 'stale' | 'unavailable'; facts: ExplanationFact[]; citedFactIds: string[];
  factDetails: Record<string, FinanceDrilldown>; locatorNotice: Record<string, string>; locatorPdf: { factId: string; dataUrl: string; page?: number } | null; busy: boolean; onRecheck(): void; onOpenFact(fact: ExplanationFact): void; onOpenLocator(fact: ExplanationFact): void;
}) {
  const coverage = coverageSummary(quality?.coverage);
  const stale = state === 'stale';
  // One line of what is still open. The seven statuses stay separate records and
  // stay listed below; this only names the ones a manager still has to act on.
  const checkGaps = stale ? [] : qualityChecks.flatMap(([key, label]) => {
    const result = quality?.checks?.[key]?.status;
    return !quality?.checks || result === 'pass' ? [] : [`${label}${result === 'needs_attention' ? '仍有缺口' : '尚未核对'}`];
  });
  const gaps = [...checkGaps, ...dimensionGaps(quality?.status_dimensions, stale)];
  const itemCount = (quality?.checks ? qualityChecks.length : 0) + 4;
  return <section className="analysis-quality" aria-label="文稿质量检查">
    <div className="analysis-section-heading"><div><h4>文稿质量检查</h4><p className="analysis-note">{state === 'checking' && <WaitOrb state="searching" />}{qualityLabel(state)}{coverage ? ` · ${coverage}` : ''}{citedFactIds.length ? ` · 已引用 ${citedFactIds.length} 条事实` : ''}</p></div>
      <Button variant="outline" type="button" disabled={busy || state === 'checking'} onClick={onRecheck}>重检当前正文</Button></div>
    {quality && <p className="analysis-quality-summary" aria-label="待处理核对">{gaps.length ? `待处理：${gaps.join(' · ')}` : `${itemCount} 项核对均已通过`}</p>}
    <details className="analysis-details"><summary>核对明细 · {itemCount} 项</summary>
      {quality?.checks && <dl className="analysis-check-summary" aria-label="分项核对状态">
        {qualityChecks.map(([key, label]) => {
          const result = quality.checks?.[key]?.status;
          return <div key={key}><dt>{label}</dt><dd>{stale ? '改稿后待复核' : result === 'pass' ? '已核对' : result === 'needs_attention' ? '仍有缺口' : '尚未核对'}</dd></div>;
        })}
      </dl>}
      <EvidenceDimensionList dimensions={quality?.status_dimensions} stale={stale} />
    </details>
    {quality?.requirements?.scope_changed && <p role="status">本次分析范围已更新，这份文稿仍使用旧范围。</p>}
    {quality?.readability?.issues.length && state !== 'stale' ? <section className="analysis-details" aria-label="正文阅读建议">
      <h4>正文阅读建议</h4>
      <p className="analysis-note">可用“整理段落”预览分段，再将比较数据、完整公式和来源附注分别组织。</p>
      <ul>{quality.readability.issues.map((issue, index) => <li key={`${issue.code}-${issue.position ?? index}`}>{issue.message}</li>)}</ul>
    </section> : null}
    <EvidenceQuality key={taskId} taskId={taskId} dimensions={quality?.status_dimensions} issues={quality?.issues ?? []} stale={stale} showDimensions={false} />
    {!(quality?.issues?.length) && <p className="analysis-note">{state === 'passed' ? '当前文稿数字、单位和引用未发现问题。' : '检查只提示风险，不会阻止你保存经理判断。'}</p>}
    {facts.length > 0 && <details className="analysis-details"><summary>可引用事实 · {facts.length} 条</summary>
      <div className="analysis-fact-list">{facts.map((fact) => <article key={fact.id} className="analysis-fact-card" aria-label={`事实 ${fact.id}`}>
        <p><strong>{factLabel(fact)}</strong>{citedFactIds.includes(fact.id) ? <span className="analysis-note"> · 已引用</span> : null}</p>
        <p className="analysis-note">运行 {shortSha(fact.run_id)} · 第 {Number(fact.row ?? 0) + 1} 行{fact.column ? ` · ${fact.column}` : ''}{fact.scope ? ` · ${scopeSummary(fact.scope)}` : ''}</p>
        <Button variant="outline" type="button" disabled={busy} onClick={() => onOpenLocator(fact)}>打开原文定位</Button>
        {fact.row != null && <Button variant="outline" type="button" disabled={busy} onClick={() => onOpenFact(fact)}>下钻此事实来源</Button>}
        {locatorNotice[fact.id] ? <p className="analysis-note" role="status">{locatorNotice[fact.id]}</p> : null}
        {locatorPdf?.factId === fact.id ? <PdfComparison dataUrl={locatorPdf.dataUrl} page={locatorPdf.page} /> : null}
        {factDetails[fact.id] && <FactDrilldown detail={factDetails[fact.id]} />}
      </article>)}</div></details>}
    {Boolean(quality?.coverage) && <details className="analysis-details"><summary>高级：检查覆盖明细</summary><pre className="analysis-source-text">{JSON.stringify(quality?.coverage, null, 2)}</pre></details>}
  </section>;
}

function FactDrilldown({ detail }: { detail: FinanceDrilldown }) {
  const columns = Array.from(new Set(detail.rows.flatMap((row) => Object.keys(row.data ?? {})))).map((name) => ({ name, type: 'VARCHAR' }));
  return <div className="analysis-drilldown-result"><p className="analysis-note">来源：{detail.message} · {detail.total} 行{detail.has_more ? ' · 仍有更多' : ''}</p>
    {columns.length > 0 && <Table columns={columns} rows={detail.rows.map((row) => row.data)} caption="事实来源行" />}
    {detail.rows.map((row, index) => <details className="analysis-details" key={index}><summary>来源 {index + 1} · {textValue(row.source)}</summary>
      <p>来源摘要：{row.source_hash}</p><p>凭证明细：{row.voucher_detail_available ? '可用' : '不可用'}</p>
      <pre className="analysis-source-text">{JSON.stringify(row.data, null, 2)}</pre></details>)}
  </div>;
}

function FinanceBackgroundPanel({ background, scope, scopeJson, backgrounds, datasets, busy, message, onBackground, onScope, onScopeJson, onSave, onList }: {
  background: { label: string; text: string; basis: string; effective_from: string; effective_to: string; dataset_id: string; paragraph: string; source: string; retrieved_at: string };
  scope: Record<string, string>; scopeJson: string; backgrounds: FinanceBackground[]; datasets: DatasetSnapshot[]; busy: boolean; message: string;
  onBackground(next: { label: string; text: string; basis: string; effective_from: string; effective_to: string; dataset_id: string; paragraph: string; source: string; retrieved_at: string }): void;
  onScope(next: Record<string, string>): void; onScopeJson(next: string): void; onSave(): void; onList(): void;
}) {
  return <details className="analysis-details analysis-background-panel"><summary>财务背景与经理判断</summary>
    <p className="analysis-note">保存业务原因、经理判断或资料来源解释。背景按范围和有效期复用，经理可改适用范围。</p>
    <fieldset className="analysis-fieldset" disabled={busy}><div className="analysis-edit-grid">
      <label>标题<Input className="min-w-0 flex-1" value={background.label} onChange={(event) => onBackground({ ...background, label: event.target.value })}  /></label>
      <FieldShell label="依据类型"><select aria-label="依据类型" className="fnd-field" value={background.basis} onChange={(event) => onBackground({ ...background, basis: event.target.value })}>
        <option value="professional_judgment">经理专业判断</option><option value="user_assumption">业务假设</option><option value="source_fact">资料事实</option><option value="external_reference">外部依据</option></select></FieldShell>
      <TextField label="账簿" ariaLabel="背景账簿" value={scope.ledger ?? ''} onChange={(value) => onScope({ ...scope, ledger: value })} />
      <TextField label="组织" ariaLabel="背景组织" value={scope.organization ?? ''} onChange={(value) => onScope({ ...scope, organization: value })} />
      <AccountingPeriodInput label="期间" ariaLabel="背景期间" value={scope.period ?? ''} onChange={(value) => onScope({ ...scope, period: value })} />
      <TextField label="币种" ariaLabel="背景币种" value={scope.currency ?? ''} onChange={(value) => onScope({ ...scope, currency: value })} />
      <TextField label="单位" ariaLabel="背景单位" value={scope.unit ?? ''} onChange={(value) => onScope({ ...scope, unit: value })} />
      <div className="analysis-period-range"><PeriodRangeInput label="适用期间范围" start={background.effective_from} end={background.effective_to}
        onChange={({ start, end }) => onBackground({ ...background, effective_from: start, effective_to: end })}
        help="设置这项背景适用的开始与结束期间；结束期间可留空。" /></div>
      {(background.basis === 'source_fact') && <><SearchableSelect label="授权资料" ariaLabel="背景授权资料" value={background.dataset_id}
        options={datasetOptions(datasets)} onChange={(value) => onBackground({ ...background, dataset_id: value })} placeholder="搜索授权资料" allowEmptyLabel="选择资料" />
        <TextField label="段落编号" ariaLabel="背景段落编号" value={background.paragraph} onChange={(value) => onBackground({ ...background, paragraph: value })} inputMode="numeric" /></>}
      {(background.basis === 'external_reference') && <><TextField label="外部来源" ariaLabel="背景外部来源" value={background.source} onChange={(value) => onBackground({ ...background, source: value })} />
        <DateInput label="查询日期" ariaLabel="背景查询日期" value={background.retrieved_at} onChange={(value) => onBackground({ ...background, retrieved_at: value })} /></>}
    </div><label>背景正文<Textarea className="analysis-code" rows={3} value={background.text} onChange={(event) => onBackground({ ...background, text: event.target.value })} /></label>
    <details className="analysis-details"><summary>高级：补充范围 JSON</summary><Textarea aria-label="补充范围 JSON" className="analysis-code" rows={4} value={scopeJson} onChange={(event) => onScopeJson(event.target.value)} /></details></fieldset>
    <div className="analysis-actions"><Button variant="outline" type="button" disabled={busy || !background.text.trim()} onClick={onSave}>保存背景</Button>
      <Button variant="outline" type="button" disabled={busy} onClick={onList}>刷新适用背景</Button></div>
    {message && <p role="status" className="analysis-message">{message}</p>}
    {backgrounds.length > 0 && <div className="analysis-history-list">{backgrounds.map((item, index) => <div className="analysis-history-row analysis-history-row--static" key={item.id ?? index}>
      <span>{textValue(item.label ?? item.basis ?? '财务背景')}</span><span>{textValue(item.text ?? item.paragraph ?? '')}</span>
      <span>{scopeSummary(item.scope ?? {})}</span><span>{textValue(item.effective_from ?? '未设期间')}{item.effective_to ? ` 至 ${textValue(item.effective_to)}` : ''}</span>
    </div>)}</div>}
  </details>;
}

function Methods({ state, busy, onApply }: {
  state: AnalysisState; busy: boolean;
  onApply(methodId: string, bindings: Record<string, string>, parameters: unknown[] | Record<string, unknown>): void;
}) {
  return <div className="fnd-stack"><h3>方法库</h3>
    <p className="analysis-note">{state.methods.length === 0 ? '完成一次分析后，可把有效做法保存在这里。' : '选用已保存的做法，并填写本次资料与参数。'}</p>
    {state.methods.map((method) => <Method key={`${state.task_id}:${method.id}`} taskId={state.task_id} method={method} datasets={state.datasets} busy={busy} onApply={onApply} />)}
  </div>;
}

function Method({ method, datasets, taskId, busy, onApply }: {
  method: AnalysisMethod; datasets: DatasetSnapshot[]; taskId: string; busy: boolean;
  onApply(id: string, bindings: Record<string, string>, parameters: unknown[] | Record<string, unknown>): void;
}) {
  const copyKey = `${taskId}:method:${method.id}`;
  const cached = readCopy<{ bindings: Record<string, string>; parameters: { name: string; value: unknown }[] }>(copyKey);
  const [bindings, setBindings] = useState<Record<string, string>>(cached?.bindings ?? {});
  const contract = method.parameter_contract ?? [];
  const formula = (index: number) => contract[index]?.role === 'formula_constant' && Object.prototype.hasOwnProperty.call(contract[index], 'default');
  const [parameters, setParameters] = useState<{ name: string; value: unknown }[]>(() => cached?.parameters
    ?? contract.map((entry, index) => ({ name: '', value: formula(index) ? entry.default : '' })));
  useEffect(() => { writeCopy(copyKey, { bindings, parameters }); }, [copyKey, bindings, parameters]);
  const aliases = method.inputs ?? Object.keys(method.input_contracts ?? method.bindings ?? {});
  const typeLabel: Record<string, string> = { VARCHAR: '文本', DECIMAL: '金额', DATE: '日期', TIMESTAMP: '日期与时间', INTEGER: '数值', BIGINT: '数值', DOUBLE: '数值', BOOLEAN: '是或否', caller_supplied: '本次取值' };
  const named = parameters.some((parameter) => parameter.name.trim());
  const invalidNames = named && (parameters.some((parameter) => !parameter.name.trim())
    || new Set(parameters.map((parameter) => parameter.name.trim())).size !== parameters.length);
  const metadataAt = (index: number) => contract[index]?.metadata
    ?? method.parameter_metadata?.find((item) => item.key === contract[index]?.parameter);
  const missingValues = contract.some((_, index) => !formula(index)
    && (parameters[index]?.value === '' || parameters[index]?.value == null) && !metadataAt(index)?.constraints?.nullable);
  const update = (index: number, value: unknown) => setParameters(parameters.map((item, at) => at === index ? { ...item, value } : item));
  return <article className="analysis-method"><h3>{method.name}</h3><fieldset className="analysis-fieldset" disabled={busy}><div className="analysis-edit-grid">
    {aliases.map((alias) => <SearchableSelect key={alias} label={`选择 ${alias} 资料`} value={bindings[alias] ?? ''}
      options={datasetOptions(datasets)} onChange={(value) => setBindings({ ...bindings, [alias]: value })}
      placeholder="搜索本次资料" allowEmptyLabel="请选择本次资料"
      help={method.input_contracts?.[alias]?.schema?.length ? `所需字段：${method.input_contracts[alias].schema.map((column) => column.name).join('、')}` : undefined} />)}
    </div>
    <div className="analysis-edit-grid">{parameters.map((parameter, index) => {
      const metadata = metadataAt(index);
      return !formula(index) && metadata?.role === 'business' ? <ParameterField key={index} metadata={metadata} value={parameter.value} onChange={(value) => update(index, value)} /> : null;
    })}</div>
    <details className="analysis-details"><summary>高级参数与公式定义</summary><p className="analysis-note">未提供业务含义的参数按计算定义顺序填写。上次的业务数值不会自动带入。</p>
      {parameters.map((parameter, index) => formula(index) || metadataAt(index)?.role === 'business' ? null : <div className="analysis-edit-grid" key={index}>
        <TextField label={`参数 ${index + 1} 的值${contract[index] ? ` · ${typeLabel[contract[index].type] ?? contract[index].type}` : ''}`}
          value={parameter.value == null ? '' : String(parameter.value)} onChange={(value) => update(index, value)} />
        {contract.length === 0 && <><TextField label={`参数 ${index + 1} 的名称（可选）`} value={parameter.name}
          onChange={(value) => setParameters(parameters.map((item, at) => at === index ? { ...item, name: value } : item))} />
          <Button variant="outline" type="button" onClick={() => setParameters(parameters.filter((_, at) => at !== index))}>移除参数 {index + 1}</Button></>}
      </div>)}
      {contract.length === 0 && <Button variant="outline" type="button" onClick={() => setParameters([...parameters, { name: '', value: '' }])}>添加方法参数</Button>}
      {invalidNames && <p className="analysis-note">具名参数需每项名称完整且不重复。</p>}
      {contract.filter((_, index) => formula(index)).map((entry) => <p key={entry.parameter}>公式常量 {entry.parameter}：{textValue(entry.default)}</p>)}
      <pre className="analysis-source-text">{method.sql}</pre></details>
    </fieldset>
    <Button variant="outline" type="button" disabled={busy || missingValues || invalidNames || aliases.some((alias) => !bindings[alias])}
      onClick={() => onApply(method.id, bindings, contract.some((_, index) => formula(index))
        ? Object.fromEntries(contract.map((entry, index) => [entry.parameter, parameters[index]?.value]))
        : named ? Object.fromEntries(parameters.map((parameter) => [parameter.name.trim(), parameter.value])) : parameters.map((parameter) => parameter.value))}>用这些资料创建分析</Button></article>;
}
