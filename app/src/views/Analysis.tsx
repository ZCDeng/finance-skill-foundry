import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowUp, FilePlus2, MessageSquare, RefreshCw } from 'lucide-react';
import { bridge, shortSha, when, type Answer, type AnalysisDraft, type AnalysisMethod,
  type AnalysisRevision, type AnalysisRun, type AnalysisState, type DatasetSnapshot,
  type TaskRow } from '../bridge.js';
import './analysis.css';
import { Table, RunStatus, STATUS, textValue } from './analysis/presentation.js';
import { RunPanel } from './analysis/RunPanel.js';
import { ParameterField } from './analysis/ParameterField.js';
import { DraftBody } from './analysis/DraftBody.js';
import { readCopy, removeCopy, writeCopy } from './analysis/workingCopy.js';

type Tab = 'datasets' | 'results' | 'drafts' | 'methods';
type AnalysisEdit = Pick<AnalysisRevision, 'parameters' | 'assumptions' | 'bindings'> & { sql: string };
type DraftEdit = { title: string; body: string; limitations: string; review: string };
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
};
const TABS: [Tab, string][] = [['datasets', '资料'], ['results', '分析结果'], ['drafts', '文稿'], ['methods', '方法']];
const EXAMPLES = ['本月利润为什么没有达到预算？', '哪些客户需要优先跟进回款？', '回款晚两周，现金余额会怎样？'];
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
export function Analysis({ task, tasks, active: visible = true, embedded = false, section, onSectionChange, onPick, onNew, onChat }: Props) {
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
  const lastSuccessful = view && [...view.runs].reverse().find((row) => row.execution_status === 'succeeded' || row.execution_status === 'success');
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
  const counts: Record<Tab, number> = { datasets: view?.datasets.length ?? 0, results: view?.analyses.length ?? 0,
    drafts: view?.drafts.length ?? 0, methods: view?.methods.length ?? 0 };
  async function saveDraft(taskId: string, spec: Record<string, unknown>): Promise<AnalysisDraft> {
    const api = bridge(); if (!api?.analysisDraft) throw new Error('此版本暂不支持保存文稿。');
    const next = unwrap(await api.analysisDraft(taskId, spec));
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
      {tasks.length > 0 && <div className="analysis-task-controls"><label className="analysis-task-picker">切换任务<select className="fnd-field"
        aria-label="切换分析任务" value={task?.id ?? ''} onChange={(event) => onPick(event.target.value)} disabled={busy}>
        <option value="" disabled>选择任务</option>{tasks.map((row) => <option key={row.id} value={row.id}>{row.title}</option>)}
      </select></label>{task && <button type="button" className="fnd-button" disabled={busy} onClick={() => onPick('')}>新建分析任务</button>}</div>}
    </header>}
    {(!embedded || !task || question) && <form className="analysis-composer" onSubmit={(event) => {
      event.preventDefault(); if ((!task && !question.trim()) || busy) return;
      if (task) void chat(question.trim() || undefined); else void create();
    }}>
      <label htmlFor="analysis-question" className="analysis-question-label">{task ? '接下来想了解什么？' : '你想分析什么？'}</label>
      <textarea id="analysis-question" value={question} onChange={(event) => setQuestion(event.target.value)}
        placeholder="例如：华东本月收入达标，利润为什么没有达标？" rows={2} maxLength={6000} />
      <div className="analysis-composer-actions">
        <button type="button" className="fnd-button" disabled={busy} onClick={() => {
          if (task) void perform(addFiles); else void create(true);
        }}><FilePlus2 size={15} aria-hidden />添加资料</button>
        <span className="analysis-formats">CSV · XLSX · JSON · Markdown · TXT</span>
        <button type="submit" className="fnd-go" disabled={busy || (!task && !question.trim())}>
          {busy ? '正在处理…' : task ? '继续分析' : '开始分析'}<ArrowUp size={15} aria-hidden /></button>
      </div>
    </form>}
    {!task && <div className="analysis-examples" aria-label="分析示例">{EXAMPLES.map((example) =>
      <button className="fnd-button" type="button" key={example} onClick={() => setQuestion(example)}>{example}</button>)}</div>}
    {error && <p role="alert" className="analysis-message analysis-message--error">{error}</p>}
    {notice && <p role="status" className="analysis-message">{notice}</p>}
    {task && <>
      <div className="analysis-tabbar"><div className="analysis-tabs" role="tablist" aria-label="任务工作区">
        {TABS.filter(([id]) => !embedded || id !== 'methods').map(([id, title], index, tabs) => <button key={id} id={`analysis-tab-${id}`} type="button" role="tab"
          aria-selected={tab === id} aria-controls={`analysis-panel-${id}`} tabIndex={tab === id ? 0 : -1}
          className="analysis-tab" onClick={() => chooseTab(id)} onKeyDown={(event) => {
            if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
            event.preventDefault();
            const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1
              : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
            chooseTab(tabs[next][0]); document.getElementById(`analysis-tab-${tabs[next][0]}`)?.focus();
          }}>{title}<span>{counts[id]}</span></button>)}
      </div><button type="button" className="fnd-button" disabled={busy || loading} onClick={() => void perform(refresh)}>
        <RefreshCw size={13} aria-hidden />刷新</button></div>
      <section role="tabpanel" id={`analysis-panel-${tab}`} aria-labelledby={embedded && tab === 'methods' ? undefined : `analysis-tab-${tab}`}
        aria-label={embedded && tab === 'methods' ? '方法库' : undefined} className="analysis-content">
        {loading && <p role="status" className="analysis-note">正在读取任务资料与成果…</p>}
        {view && tab === 'datasets' && <>
          {embedded && <div className="analysis-section-heading"><h3>任务资料</h3><button type="button" className="fnd-button" disabled={busy} onClick={() => void perform(addFiles)}><FilePlus2 size={15} aria-hidden />添加资料</button></div>}
          {!view.datasets.length && <Empty title="把手头的资料加进来" body="无需先准备科目表。也可以先与助手讨论分析口径和所需资料。"
            onChat={() => void chat(question.trim() || undefined)} />}
          <div className="analysis-source-list">{view.datasets.map((source) => <button key={source.id} className="fnd-card"
            type="button" onClick={() => void perform(async (taskId) => {
              const api = bridge(); if (!api?.analysisReadDataset) throw new Error('此版本暂不支持资料预览。');
              const content = unwrap(await api.analysisReadDataset(taskId, source.id));
              if (currentTask.current === taskId) setDataset({ source, content });
            })} disabled={busy}>
            <span className="fnd-title">{source.name}</span><span className="analysis-source-meta">
              {{ table: '数据表', background: '背景资料' }[source.kind] ?? source.kind}{source.row_count != null ? ` · ${source.row_count} 行` : ''} · {when(source.created_at)}</span>
            <span className="analysis-note">{['period', 'unit', 'currency'].filter((key) => source.metadata?.[key] != null)
              .map((key) => textValue(source.metadata[key])).join(' · ') || '查看内容与来源'}</span>
          </button>)}</div>
          {dataset && <DatasetPreview source={dataset.source} content={dataset.content} />}
        </>}
        {view && tab === 'results' && <>
          {selectedAnalysis && view.analyses.at(-1)?.id !== selectedAnalysis && <p className="analysis-note">当前正在查看选定版本。可在分析版本中查看其他结果，工作副本会保留。</p>}
          {!analysis ? <Empty title="从资料到可检查的结果" body="告诉助手你想比较什么、按什么口径看。计算完成后，在这里查看结果与依据。"
            onChat={() => void chat(question.trim() || undefined)} /> : <>
            <label className="analysis-select-label">分析版本<select className="fnd-field" value={analysis.id}
              onChange={(event) => setSelectedAnalysis(event.target.value)}>
              {[...view.analyses].reverse().map((row) => <option key={row.id} value={row.id}>{row.question} · {when(row.created_at)} · {shortSha(row.id)}</option>)}
            </select></label>
            <RunPanel key={task.id} analysis={analysis} analyses={view.analyses} runs={view.runs} datasets={view.datasets} busy={busy}
              onPick={setSelectedAnalysis} onChat={(prompt) => void chat(prompt)}
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
              })} />
            {dataset && <section aria-label="依据资料预览"><div className="analysis-section-heading"><h3>依据资料</h3>
              <button type="button" className="fnd-button" onClick={() => setDataset(null)}>关闭资料预览</button></div>
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
                <p className="analysis-note">这项分析使用脚本计算。输入资料、代码和实际输出保留在运行记录中。</p>
                {analysis.assumptions.length > 0 && <p>假设：{analysis.assumptions.map(textValue).join('；')}</p>}
                <details className="analysis-details"><summary>高级：查看计算脚本</summary><pre className="analysis-source-text">{analysis.code}</pre></details>
                <button type="button" className="fnd-button" disabled={busy} onClick={() => void chat(`请读取脚本分析版本 ${analysis.id}，继续调整或重跑，保存新的运行记录。`)}>调整或重跑此分析</button>
              </div>}

          </>}
        </>}
        {view && tab === 'drafts' && <>
          {view.drafts.length > 0 && <label className="analysis-select-label">文稿版本<select className="fnd-field" value={draft?.id ?? ''}
            onChange={(event) => setSelectedDraft(event.target.value)}>{[...view.drafts].reverse().map((row) =>
            <option key={row.id} value={row.id}>{row.title} · {STATUS[row.publication_status] ?? row.publication_status} · {when(row.created_at)} · {shortSha(row.id)}</option>)}</select></label>}
          <DraftEditor key={draftKey} draft={draft} busy={busy} runs={view.runs} onChat={(spec) => void perform(async (taskId) => {
              const id = spec ? (await saveDraft(taskId, spec)).id : draft?.id;
              await handoff(undefined, id, spec ? { targetTaskId: taskId } : undefined);
            })}
            edit={draftEdits.current.get(draftKey) ?? readCopy<DraftEdit>(draftKey)} onEdit={rememberDraft}
            onSave={(spec) => void perform(async (taskId) => {
              await saveDraft(taskId, spec);
              if (currentTask.current === taskId) setNotice('已保存为新的文稿版本。');
            })} onExport={(format, spec) => void perform(async (taskId) => {
              const api = bridge(); if (!api?.analysisExport) throw new Error('此版本暂不支持导出文稿。');
              const id = spec ? (await saveDraft(taskId, spec)).id : draft?.id;
              if (!id) throw new Error('请先写下文稿内容。');
              const result = unwrap(await api.analysisExport(taskId, id, format));
              if (currentTask.current === taskId) setNotice(result.cancelled ? '已取消导出。' : `已导出${format === 'md' ? '文稿' : '工作簿'}${result.path ? `：${textValue(result.path)}` : '。'}`);
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

function Empty({ title, body, onChat }: { title: string; body: string; onChat(): void }) {
  return <div className="analysis-empty"><h3>{title}</h3><p>{body}</p><button type="button" className="fnd-button" onClick={onChat}>
    <MessageSquare size={14} aria-hidden />与助手讨论</button></div>;
}
function DatasetPreview({ source, content }: { source: DatasetSnapshot; content: Record<string, unknown> }) {
  const columns = Array.isArray(content.columns) ? content.columns.map((column: unknown) => typeof column === 'string'
    ? { name: column } : column as { name: string; type?: string }) : source.schema ?? [];
  const rows = Array.isArray(content.rows) ? content.rows as Record<string, unknown>[] : [];
  return <article className="analysis-source-preview"><h3>{source.name}</h3>
    <p className="analysis-note">资料版本：{source.id} · 原始摘要：{source.source_hash ?? source.sha256}</p>
    {columns.length > 0 && <Table columns={columns} rows={rows} caption="资料预览" />}
    {typeof content.text === 'string' && <><pre className="analysis-source-text">{content.text.slice(0, 30000)}</pre>
      {content.text.length > 30000 && <p className="analysis-note">当前显示前 30,000 个字符，助手可以继续读取全文。</p>}</>}
    {Boolean(content.truncated) && <p className="analysis-note">当前仅显示部分内容。</p>}
    <details className="analysis-details"><summary>来源与资料口径</summary><p>原始文件：{source.source_name ?? source.name}</p>{Object.entries(source.metadata ?? {}).map(([key, value]) =>
      <p key={key}>{key}：{textValue(value)}</p>)}
      {columns.length > 0 && <p>字段：{columns.map((column) => `${column.name}${column.type ? ` (${column.type})` : ''}`).join('、')}</p>}
    </details></article>;
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
      <fieldset disabled={busy} className="analysis-fieldset"><div className="analysis-edit-grid">{Object.entries(bindings).map(([alias, id]) => <label key={alias}>资料 · {alias}
        <select className="fnd-field" value={id} onChange={(event) => setBindings({ ...bindings, [alias]: event.target.value })}>
          {datasets.map((source) => <option key={source.id} value={source.id}>{source.name} · {shortSha(source.id)}</option>)}</select></label>)}
        {Object.entries(parameters).filter(([key]) => metadataFor(key)?.role === 'business').map(([key, value]) =>
          <ParameterField key={key} metadata={metadataFor(key)!} value={value} onChange={(next) => updateParameter(key, value, next)} />)}
        {assumptions.map((value, index) => <label key={`assumption-${index}`}>假设 · {itemLabel(value, index)}
          <input className="fnd-field" value={itemValue(value)} onChange={(event) => setAssumptions(assumptions.map((item, at) => at === index ? editItem(item, event.target.value) : item))} /></label>)}
      </div>
      <details className="analysis-details"><summary>高级参数与公式常量</summary>
        <p className="analysis-note">未标注业务含义的参数按计算定义中的名称或顺序展示。</p>
        <div className="analysis-edit-grid">{Object.entries(parameters).filter(([key]) => metadataFor(key)?.role !== 'business').map(([key, value], index) => <label key={key}>参数 · {Array.isArray(parameters) ? itemLabel(value, index) : key}
          <input className="fnd-field" value={itemValue(value)} onChange={(event) => updateParameter(key, value, event.target.value)} /></label>)}</div>
      </details>
      {Array.isArray(parameters) && <button type="button" className="fnd-button" onClick={() => setParameters([...parameters, ''])}>添加计算参数</button>}
      </fieldset>
      <p className="analysis-note">修改后保存并重跑会创建新版本，之前的结果仍可查看。</p>
      <p className="analysis-note">参数会传入计算，假设说明用于记录依据；改变计算口径可请助手更新表达式。</p>
      <button type="button" className="fnd-button" disabled={busy} onClick={() => onChat(changed ? spec() : undefined)}>与助手调整口径</button>
    </section>
    <details className="analysis-details"><summary>高级：查看或编辑计算 SQL</summary>
      <textarea className="analysis-code" aria-label="计算 SQL" rows={7} value={sql} disabled={busy} onChange={(event) => setSql(event.target.value)} /></details>
    <div className="analysis-actions"><button type="button" className="fnd-go" disabled={busy || !sql.trim()} onClick={() => onSave(spec())}>保存新版并重跑</button><button type="button" className="fnd-button" disabled={busy} onClick={onRun}>重跑当前已保存版本</button></div>
    </details>
  </div>;
}
function DraftEditor({ draft, busy, runs, edit, onEdit, onSave, onExport, onChat }: {
  draft?: AnalysisDraft; busy: boolean; runs: AnalysisRun[]; onSave(spec: Record<string, unknown>): void;
  edit?: DraftEdit; onEdit(edit: DraftEdit): void;
  onExport(format: 'md' | 'xlsx', spec?: Record<string, unknown>): void; onChat(spec?: Record<string, unknown>): void;
}) {
  const [title, setTitle] = useState(edit?.title ?? draft?.title ?? '经营分析');
  const [body, setBody] = useState(edit?.body ?? draft?.body ?? '');
  const [limitations, setLimitations] = useState(edit?.limitations ?? draft?.limitations.join('\n') ?? '');
  const [review, setReview] = useState(edit?.review ?? draft?.review_status ?? 'unreviewed');
  const [editing, setEditing] = useState(!draft || Boolean(edit && (edit.body !== draft.body || edit.title !== draft.title
    || edit.limitations !== draft.limitations.join('\n') || edit.review !== draft.review_status)));
  const exportMenu = useRef<HTMLDetailsElement>(null);
  useEffect(() => { onEdit({ title, body, limitations, review }); }, [title, body, limitations, review, onEdit]);
  const changed = !draft || title !== draft.title || body !== draft.body || limitations !== draft.limitations.join('\n') || review !== draft.review_status;
  function spec(publication: 'draft' | 'archived') {
    return { title: title.trim(), body, run_ids: draft?.run_ids ?? [], claims: draft?.claims ?? [],
      ...(draft ? { parent_id: draft.id } : {}), publication_status: publication, review_status: review,
      limitations: limitations.split('\n').map((line) => line.trim()).filter(Boolean) };
  }
  return <div className="analysis-draft">
    <div className="analysis-section-heading"><h3>{draft ? '文稿' : '写下判断与建议'}</h3>
      {draft && <span className="analysis-note">{STATUS[draft.publication_status] ?? draft.publication_status} · {STATUS[draft.review_status] ?? draft.review_status}</span>}
      <div className="analysis-actions"><button type="button" className="fnd-button" aria-pressed={editing} onClick={() => setEditing(!editing)}>{editing ? '阅读文稿' : '编辑文稿'}</button>
      <button type="button" className="fnd-button" disabled={busy || Boolean(draft && changed && (!title.trim() || !body.trim()))} onClick={() => onChat(changed && body.trim() ? spec('draft') : undefined)}>{draft ? '围绕此稿继续分析' : '请助手整理文稿'}</button></div></div>
    {editing ? <fieldset className="analysis-fieldset analysis-draft-fields" disabled={busy}>
    <label>文稿标题<input aria-label="文稿标题" className="fnd-field" value={title} onChange={(event) => setTitle(event.target.value)} /></label>
    <label>文稿正文<textarea aria-label="文稿正文" rows={14} value={body} placeholder="写下你的判断，或请助手根据分析结果整理初稿。"
      onChange={(event) => { setBody(event.target.value); setReview('unreviewed'); }} /></label>
    <div className="analysis-edit-grid"><label>局限与待确认事项（每行一项）<textarea aria-label="局限与待确认事项（每行一项）" rows={3} value={limitations}
      onChange={(event) => setLimitations(event.target.value)} /></label><label>我的审阅状态<select aria-label="我的审阅状态" className="fnd-field" value={review}
      onChange={(event) => setReview(event.target.value)}><option value="unreviewed">未阅</option><option value="reviewed">已阅</option><option value="accepted">认可</option></select></label></div>
    </fieldset> : <article className="analysis-draft-reading" aria-label="文稿阅读"><h2>{title}</h2><DraftBody body={body} />
      {limitations.trim() && <section><h3>局限与待确认事项</h3><ul>{limitations.split('\n').filter(Boolean).map((line, index) => <li key={index}>{line}</li>)}</ul></section>}</article>}
    {draft && <details className="analysis-details"><summary>引用的计算与依据 · {draft.run_ids.length} 次运行</summary>
      {draft.run_ids.length === 0 && <p>这份文稿尚未引用计算记录。</p>}
      {draft.run_ids.map((id) => { const run = runs.find((item) => item.id === id); return <div key={id}>
        <p>{id}</p>{run ? <RunStatus run={run} /> : <p>此运行记录暂不可读取。</p>}</div>; })}
      {draft.claims.map((claim, index) => <p key={index}>{textValue(claim)}</p>)}</details>}
    <div className="analysis-actions">{changed && <button type="button" className="fnd-go" disabled={busy || !title.trim() || !body.trim()} onClick={() => onSave(spec('draft'))}>保存文稿新版</button>}
      <button type="button" className="fnd-button" disabled={busy || !title.trim() || !body.trim()} onClick={() => onSave(spec('archived'))}>选定并归档此版</button>
      <details ref={exportMenu} className="analysis-export" onKeyDown={(event) => { if (event.key === 'Escape') {
        event.preventDefault(); if (exportMenu.current) { exportMenu.current.open = false; exportMenu.current.querySelector('summary')?.focus(); }
      } }}><summary>导出</summary><div className="analysis-export-options">
        <button type="button" className="fnd-button" disabled={busy || !title.trim() || !body.trim()} onClick={() => {
          if (exportMenu.current) exportMenu.current.open = false; onExport('md', changed ? spec('draft') : undefined);
        }}>导出文稿<span>Markdown</span></button>
        <button type="button" className="fnd-button" disabled={busy || !title.trim() || !body.trim()} onClick={() => {
          if (exportMenu.current) exportMenu.current.open = false; onExport('xlsx', changed ? spec('draft') : undefined);
        }}>导出工作簿<span>Excel</span></button></div></details></div>
    {changed && <p className="analysis-note">交给助手或导出时，会先保存当前内容为新版本。</p>}
  </div>;
}
function Methods({ state, busy, onApply }: {
  state: AnalysisState; busy: boolean;
  onApply(methodId: string, bindings: Record<string, string>, parameters: unknown[] | Record<string, unknown>): void;
}) {
  return <div className="fnd-stack"><h3>方法库</h3>
    <p className="analysis-note">选择已保存的分析方式，填写本次资料与业务参数。有效的分析方式可以在结果中保存。</p>
    {state.methods.length === 0 && <p className="analysis-note">还没有保存的方法。先完成一次分析，再决定是否复用。</p>}
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
    {aliases.map((alias) => <label key={alias}>选择 {alias} 资料<select aria-label={`选择 ${alias} 资料`} className="fnd-field" value={bindings[alias] ?? ''}
      onChange={(event) => setBindings({ ...bindings, [alias]: event.target.value })}>
      <option value="">请选择本次资料</option>{datasets.map((source) => <option key={source.id} value={source.id}>{source.name} · {shortSha(source.id)}</option>)}</select>
      {method.input_contracts?.[alias]?.schema?.length ? <span className="analysis-note">所需字段：{method.input_contracts[alias].schema.map((column) => column.name).join('、')}</span> : null}</label>)}
    </div>
    <div className="analysis-edit-grid">{parameters.map((parameter, index) => {
      const metadata = metadataAt(index);
      return !formula(index) && metadata?.role === 'business' ? <ParameterField key={index} metadata={metadata} value={parameter.value} onChange={(value) => update(index, value)} /> : null;
    })}</div>
    <details className="analysis-details"><summary>高级参数与公式定义</summary><p className="analysis-note">未提供业务含义的参数按计算定义顺序填写。上次的业务数值不会自动带入。</p>
      {parameters.map((parameter, index) => formula(index) || metadataAt(index)?.role === 'business' ? null : <div className="analysis-edit-grid" key={index}>
        <label>参数 {index + 1} 的值{contract[index] ? ` · ${typeLabel[contract[index].type] ?? contract[index].type}` : ''}<input className="fnd-field" value={parameter.value == null ? '' : String(parameter.value)} onChange={(event) => update(index, event.target.value)} /></label>
        {contract.length === 0 && <><label>参数 {index + 1} 的名称（可选）<input className="fnd-field" value={parameter.name} onChange={(event) => setParameters(parameters.map((item, at) => at === index ? { ...item, name: event.target.value } : item))} /></label>
          <button type="button" className="fnd-button" onClick={() => setParameters(parameters.filter((_, at) => at !== index))}>移除参数 {index + 1}</button></>}
      </div>)}
      {contract.length === 0 && <button type="button" className="fnd-button" onClick={() => setParameters([...parameters, { name: '', value: '' }])}>添加方法参数</button>}
      {invalidNames && <p className="analysis-note">具名参数需每项名称完整且不重复。</p>}
      {contract.filter((_, index) => formula(index)).map((entry) => <p key={entry.parameter}>公式常量 {entry.parameter}：{textValue(entry.default)}</p>)}
      <pre className="analysis-source-text">{method.sql}</pre></details>
    </fieldset>
    <button type="button" className="fnd-button" disabled={busy || missingValues || invalidNames || aliases.some((alias) => !bindings[alias])}
      onClick={() => onApply(method.id, bindings, contract.some((_, index) => formula(index))
        ? Object.fromEntries(contract.map((entry, index) => [entry.parameter, parameters[index]?.value]))
        : named ? Object.fromEntries(parameters.map((parameter) => [parameter.name.trim(), parameter.value])) : parameters.map((parameter) => parameter.value))}>用这些资料创建分析</button></article>;
}
