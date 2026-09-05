// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Analysis } from '../src/views/Analysis.js';
import type { Answer, AnalysisDraft, AnalysisRevision, AnalysisRun, AnalysisState, Bridge, DatasetSnapshot, TaskRow } from '../src/bridge.js';

const task: TaskRow = { id: 'a'.repeat(32), title: '华东经营分析', period: null, skill_id: null, created_at: '2026-09-05T00:00:00Z', windows: 0 };
const object = { task_id: task.id, schema_version: 1, created_at: task.created_at };
const source: DatasetSnapshot = { ...object, id: 'b'.repeat(32), name: '本月实际', kind: 'table', source_hash: 'c'.repeat(64), source_name: 'actual.csv',
  metadata: { currency: 'CNY', unit: '元' }, schema: [{ name: 'profit', type: 'DECIMAL(38,2)' }], row_count: 1 };
const analysis: AnalysisRevision = { ...object, id: 'd'.repeat(32), question: '华东利润分析', sql: 'select profit * ? as profit from actual',
  bindings: { actual: source.id }, parameters: ['0.85'], assumptions: ['回款率 85%'], grain: ['项目'], relationships: [],
  metrics: [{ name: '经营利润', expression: '收入−成本−费用' }, '利润率'] };
const run: AnalysisRun = { ...object, id: 'e'.repeat(32), analysis_id: analysis.id, execution_status: 'succeeded',
  reproducibility_status: 'reproducible', publication_status: 'draft', review_status: 'unreviewed', input_hashes: { [source.id]: source.source_hash },
  result: { columns: [{ name: 'profit', type: 'DECIMAL(38,2)' }], rows: [{ profit: '900719925474099.99' }], row_count: 1, truncated: false } };
const draft: AnalysisDraft = { ...object, id: 'f'.repeat(32), title: '经营简报', body: '利润有所改善。', run_ids: [run.id],
  claims: [{ basis: 'calculation', run_id: run.id, row: 0, column: 'profit', value: '900719925474099.99' }],
  publication_status: 'archived', review_status: 'accepted', limitations: ['业务原因待访谈确认'] };
const initial: AnalysisState = { task_id: task.id, datasets: [source], analyses: [analysis], runs: [run], drafts: [draft], methods: [] };
const success = <T,>(value: T): Answer<T> => ({ ok: true, value });
function mountBridge(overrides: Partial<Bridge> = {}) {
  const api = { analysisState: vi.fn(async () => success(initial)), ...overrides };
  (globalThis as unknown as { foundry: Partial<Bridge> }).foundry = api;
  return api;
}
function openDraftEditor() {
  fireEvent.click(screen.getByRole('tab', { name: /文稿/ }));
  const edit = screen.queryByRole('button', { name: '编辑文稿' });
  if (edit) fireEvent.click(edit);
}
function openAnalysisEditor() {
  fireEvent.click(screen.getByRole('tab', { name: /分析结果/ }));
  const definition = screen.queryByText(/^口径与计算定义/);
  if (definition?.closest('details')) (definition.closest('details') as HTMLDetailsElement).open = true;
  const adjust = screen.queryByText('调整参数、假设与资料');
  if (adjust?.closest('details')) (adjust.closest('details') as HTMLDetailsElement).open = true;
}
function exportDraft() {
  fireEvent.click(screen.getByText('导出', { selector: 'summary' }));
  fireEvent.click(screen.getByRole('button', { name: /导出文稿/ }));
}
function openMethods() {
  fireEvent.click(screen.getByRole('tab', { name: /方法/ }));
  for (const summary of screen.queryAllByText('高级参数与公式定义')) {
    if (summary.closest('details')) (summary.closest('details') as HTMLDetailsElement).open = true;
  }
}
const props = { task, tasks: [task], onPick: vi.fn(), onNew: vi.fn(), onChat: vi.fn() };
afterEach(() => { cleanup(); delete (globalThis as unknown as { foundry?: Bridge }).foundry; vi.clearAllMocks(); vi.useRealTimers(); sessionStorage.clear(); });

describe('analysis workbench', () => {
  it('starts from the user question, then opens the created task with that same question', async () => {
    mountBridge();
    let finish!: () => void;
    const onNew = vi.fn(() => new Promise<void>((resolve) => { finish = resolve; }));
    const onChat = vi.fn();
    const { rerender } = render(<Analysis {...props} task={null} tasks={[]} onNew={onNew} onChat={onChat} />);
    expect(screen.queryByLabelText('期间')).toBeNull();
    fireEvent.change(screen.getByLabelText('你想分析什么？'), { target: { value: '  利润为什么没达标？  ' } });
    fireEvent.click(screen.getByRole('button', { name: '开始分析' }));
    expect(onNew).toHaveBeenCalledWith('利润为什么没达标？');
    rerender(<Analysis {...props} onNew={onNew} onChat={onChat} />);
    await act(async () => finish());
    await waitFor(() => expect(onChat).toHaveBeenCalledExactlyOnceWith('利润为什么没达标？', undefined,
      expect.objectContaining({ submit: true, requestId: expect.any(String), targetTaskId: task.id })));
  });

  it('adds first files after creation even when task props arrive before the create promise finishes', async () => {
    const analysisAddFiles = vi.fn(async () => success([source]));
    mountBridge({ analysisAddFiles });
    let finish!: () => void;
    const onNew = vi.fn(() => new Promise<void>((resolve) => { finish = resolve; }));
    const { rerender } = render(<Analysis {...props} task={null} tasks={[]} onNew={onNew} />);
    fireEvent.click(screen.getByRole('button', { name: '添加资料' }));
    rerender(<Analysis {...props} onNew={onNew} />);
    expect(analysisAddFiles).not.toHaveBeenCalled();
    await act(async () => finish());
    await waitFor(() => expect(analysisAddFiles).toHaveBeenCalledExactlyOnceWith(task.id));
    expect(props.onChat).not.toHaveBeenCalled();
    expect(screen.getByRole('status').textContent).toContain('已加入 1 份资料');
  });

  it('shows service failure with no synthetic results', async () => {
    mountBridge({ analysisState: async () => ({ ok: false, refused: true, message: '分析存储不可读取' }) });
    render(<Analysis {...props} />);
    expect((await screen.findByRole('alert')).textContent).toBe('分析存储不可读取');
    expect(screen.queryByText('900719925474099.99')).toBeNull();
  });

  it('ignores a delayed response for the previously selected task', async () => {
    const other = { ...task, id: '1'.repeat(32), title: '西南回款' };
    let finish!: (answer: Answer<AnalysisState>) => void;
    mountBridge({ analysisState: vi.fn((id: string) => id === task.id
      ? new Promise<Answer<AnalysisState>>((resolve) => { finish = resolve; })
      : Promise.resolve(success({ ...initial, task_id: other.id, datasets: [{ ...source, task_id: other.id, name: '西南资料' }] }))) });
    const { rerender } = render(<Analysis {...props} />);
    rerender(<Analysis {...props} task={other} tasks={[task, other]} />);
    await screen.findByText('西南资料');
    await act(async () => finish(success(initial)));
    expect(screen.queryByText('本月实际')).toBeNull();
    expect(screen.getByText('西南资料')).toBeTruthy();
  });

  it('preserves exact Decimal text and separates execution, reproducibility, review and publication', async () => {
    mountBridge(); render(<Analysis {...props} />); await screen.findByText('本月实际');
    openAnalysisEditor();
    expect(screen.getByText('900719925474099.99')).toBeTruthy();
    expect(screen.getByText('指标：经营利润：收入−成本−费用；利润率')).toBeTruthy();
    expect(within(screen.getByLabelText('结果状态')).getByText('运行成功')).toBeTruthy();
    expect(screen.getByText('可复算')).toBeTruthy();
    expect(screen.getByText('未阅')).toBeTruthy();
    const sql = screen.getByLabelText('计算 SQL');
    expect(sql.closest('details')?.open).toBe(false);
  });

  it('reads script analyses without treating them as SQL revisions', async () => {
    const script: AnalysisRevision = { ...analysis, sql: null, engine: 'python', code: 'print("利润 30")' };
    const scriptRun: AnalysisRun = { ...run, engine: 'python', stdout: '利润 30', result: { columns: [], rows: [], row_count: 0, truncated: false },
      reproducibility_status: 'unverified', outputs: [{ path: 'profit.csv', sha256: '9'.repeat(64), artifact_path: 'run_outputs/profit.csv', size: 9 }] };
    mountBridge({ analysisState: async () => success({ ...initial, analyses: [script], runs: [scriptRun] }) });
    render(<Analysis {...props} />); await screen.findByText('本月实际');
    openAnalysisEditor();
    expect(screen.getByLabelText('脚本计算输出').textContent).toBe('利润 30');
    expect(screen.getByText(/profit.csv/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: '保存新版并重跑' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '调整或重跑此分析' }));
    await waitFor(() => expect(props.onChat).toHaveBeenCalledWith(expect.stringContaining(analysis.id), undefined));
  });

  it('opens an archived script output through its task and run, and reports a refused opening', async () => {
    const script: AnalysisRevision = { ...analysis, sql: null, engine: 'python', code: 'print("利润 30")' };
    const scriptRun: AnalysisRun = { ...run, engine: 'python', outputs: [{ path: 'profit.csv', sha256: '9'.repeat(64), artifact_path: 'run_outputs/profit.csv', size: 9 }] };
    const analysisOpenOutput = vi.fn(async () => ({ ok: false as const, refused: true, message: '输出文件摘要不匹配' }));
    mountBridge({ analysisState: async () => success({ ...initial, analyses: [script], runs: [scriptRun] }), analysisOpenOutput });
    render(<Analysis {...props} />); await screen.findByText('本月实际');
    openAnalysisEditor();
    fireEvent.click(screen.getByRole('button', { name: '打开文件 profit.csv' }));
    await waitFor(() => expect(analysisOpenOutput).toHaveBeenCalledWith(task.id, run.id, 'profit.csv'));
    expect((await screen.findByRole('alert')).textContent).toBe('输出文件摘要不匹配');
    expect(screen.queryByText('已打开 profit.csv。')).toBeNull();
  });

  it('saves edits into a successor, runs that successor, and preserves its definition if the run fails', async () => {
    const next = { ...analysis, id: '2'.repeat(32), parameters: ['0.90'], parent_id: analysis.id };
    const analysisSave = vi.fn(async () => success(next));
    const analysisRun = vi.fn(async () => ({ ok: false as const, refused: true, message: '计算超时' }));
    const api = mountBridge({ analysisSave, analysisRun });
    render(<Analysis {...props} />); await screen.findByText('本月实际');
    openAnalysisEditor();
    fireEvent.change(screen.getByLabelText('参数 · 第 1 项'), { target: { value: '0.90' } });
    fireEvent.click(screen.getByRole('button', { name: '保存新版并重跑' }));
    await waitFor(() => expect(analysisRun).toHaveBeenCalledWith(task.id, next.id));
    expect(analysisSave.mock.calls[0]).toEqual([task.id, expect.objectContaining({ parameters: ['0.90'], parent_id: analysis.id, bindings: analysis.bindings })]);
    expect((await screen.findByRole('alert')).textContent).toBe('计算超时');
    expect(api.analysisState).toHaveBeenCalledTimes(2);
  });

  it('retains run references when revising a draft, resets review, and exports only saved text', async () => {
    const analysisDraft = vi.fn(async () => success({ ...draft, id: '3'.repeat(32), body: '这是我的专业判断。', publication_status: 'draft', review_status: 'unreviewed' }));
    const analysisExport = vi.fn(async () => success({ path: '/tmp/report.md' }));
    mountBridge({ analysisDraft, analysisExport });
    render(<Analysis {...props} />); await screen.findByText('本月实际');
    openDraftEditor();
    fireEvent.change(screen.getByLabelText('文稿正文'), { target: { value: '这是我的专业判断。' } });
    expect((screen.getByLabelText('我的审阅状态') as HTMLSelectElement).value).toBe('unreviewed');
    exportDraft();
    await waitFor(() => expect(analysisExport).toHaveBeenCalledWith(task.id, '3'.repeat(32), 'md'));
    await waitFor(() => expect(analysisDraft).toHaveBeenCalledWith(task.id, expect.objectContaining({
      parent_id: draft.id, body: '这是我的专业判断。', run_ids: [run.id], claims: draft.claims, review_status: 'unreviewed', publication_status: 'draft',
    })));
  });

  it('retains unsaved draft and parameter edits while checking results in other tabs and versions', async () => {
    const earlier = { ...analysis, id: '8'.repeat(32), parameters: ['0.70'] };
    mountBridge({ analysisState: async () => success({ ...initial, analyses: [earlier, analysis] }) });
    render(<Analysis {...props} />); await screen.findByText('本月实际');
    openDraftEditor();
    fireEvent.change(screen.getByLabelText('文稿正文'), { target: { value: '尚未保存的经营判断。' } });
    openAnalysisEditor();
    fireEvent.change(screen.getByLabelText('参数 · 第 1 项'), { target: { value: '0.93' } });
    fireEvent.change(screen.getByLabelText('分析版本'), { target: { value: earlier.id } });
    expect((screen.getByLabelText('参数 · 第 1 项') as HTMLInputElement).value).toBe('0.70');
    fireEvent.change(screen.getByLabelText('分析版本'), { target: { value: analysis.id } });
    expect((screen.getByLabelText('参数 · 第 1 项') as HTMLInputElement).value).toBe('0.93');
    openDraftEditor();
    expect((screen.getByLabelText('文稿正文') as HTMLTextAreaElement).value).toBe('尚未保存的经营判断。');
    fireEvent.click(screen.getByRole('tab', { name: /资料/ }));
    openAnalysisEditor();
    expect((screen.getByLabelText('参数 · 第 1 项') as HTMLInputElement).value).toBe('0.93');
  });

  it('scopes unsaved edits to both task and version when switching tasks', async () => {
    const other = { ...task, id: '9'.repeat(32), title: '西南经营分析' };
    mountBridge({ analysisState: async (id) => success(id === task.id ? initial
      : { ...initial, task_id: other.id, datasets: [{ ...source, task_id: other.id }], drafts: [{ ...draft, task_id: other.id, body: '西南原稿。' }] }) });
    const { rerender } = render(<Analysis {...props} tasks={[task, other]} />); await screen.findByText('本月实际');
    openDraftEditor();
    fireEvent.change(screen.getByLabelText('文稿正文'), { target: { value: '仅属于华东的未保存判断。' } });
    rerender(<Analysis {...props} task={other} tasks={[task, other]} />); await screen.findByText('本月实际');
    openDraftEditor();
    expect((screen.getByLabelText('文稿正文') as HTMLTextAreaElement).value).toBe('西南原稿。');
    rerender(<Analysis {...props} tasks={[task, other]} />); await screen.findByText('本月实际');
    openDraftEditor();
    expect((screen.getByLabelText('文稿正文') as HTMLTextAreaElement).value).toBe('仅属于华东的未保存判断。');
  });

  it('refreshes assistant updates on reactivation without replacing the versions being edited', async () => {
    let backend = initial;
    const analysisState = vi.fn(async () => success(backend));
    mountBridge({ analysisState });
    const { rerender } = render(<Analysis {...props} active />); await screen.findByText('本月实际');
    openAnalysisEditor();
    fireEvent.change(screen.getByLabelText('参数 · 第 1 项'), { target: { value: '0.92' } });
    openDraftEditor();
    fireEvent.change(screen.getByLabelText('文稿正文'), { target: { value: '返回后还要继续写的判断。' } });
    rerender(<Analysis {...props} active={false} />);
    backend = { ...initial, datasets: [...initial.datasets, { ...source, id: '6'.repeat(32), name: '助手新加预算' }],
      analyses: [...initial.analyses, { ...analysis, id: '7'.repeat(32), question: '助手新计算的预算差异' }],
      drafts: [...initial.drafts, { ...draft, id: '8'.repeat(32), title: '助手新增报告', body: '新的远端正文。' }] };
    expect(analysisState).toHaveBeenCalledTimes(1);
    rerender(<Analysis {...props} active />);
    await waitFor(() => expect(analysisState).toHaveBeenCalledTimes(2));
    await screen.findByRole('option', { name: /助手新增报告/ });
    expect((screen.getByLabelText('文稿正文') as HTMLTextAreaElement).value).toBe('返回后还要继续写的判断。');
    openAnalysisEditor();
    expect((screen.getByLabelText('参数 · 第 1 项') as HTMLInputElement).value).toBe('0.92');
    expect(screen.getByRole('option', { name: /助手新计算的预算差异/ })).toBeTruthy();
    fireEvent.click(screen.getByRole('tab', { name: /资料/ }));
    expect(screen.getByText('助手新加预算')).toBeTruthy();
    rerender(<Analysis {...props} active />);
    expect(analysisState).toHaveBeenCalledTimes(2);
  });

  it('continues analysis with the selected archived draft id', async () => {
    mountBridge(); render(<Analysis {...props} />); await screen.findByText('本月实际');
    openDraftEditor();
    fireEvent.click(screen.getByRole('button', { name: '围绕此稿继续分析' }));
    await waitFor(() => expect(props.onChat).toHaveBeenCalledWith(undefined, draft.id));
  });

  it('does not turn a rejected export into a success message', async () => {
    mountBridge({ analysisExport: async () => ({ ok: false, refused: true, message: '保存位置不可写' }) });
    render(<Analysis {...props} />); await screen.findByText('本月实际');
    openDraftEditor();
    exportDraft();
    expect((await screen.findByRole('alert')).textContent).toBe('保存位置不可写');
    expect(screen.queryByText(/已导出/)).toBeNull();
  });

  it('shows background content together with the original source hash', async () => {
    const notes = { ...source, id: '4'.repeat(32), kind: 'background', name: '经营说明', source_name: 'notes.md', schema: [], row_count: 0 };
    const analysisReadDataset = vi.fn(async () => success({ ...notes, text: '项目成本增加可能与临时运输有关。' }));
    mountBridge({ analysisState: async () => success({ ...initial, datasets: [notes] }), analysisReadDataset });
    render(<Analysis {...props} />);
    fireEvent.click(await screen.findByRole('button', { name: /经营说明/ }));
    expect(await screen.findByText('项目成本增加可能与临时运输有关。')).toBeTruthy();
    expect(screen.getByText(new RegExp(notes.source_hash))).toBeTruthy();
    expect(analysisReadDataset).toHaveBeenCalledWith(task.id, notes.id);
  });

  it('preserves named parameters, conversion rules and execution limits when making a revision', async () => {
    const named = { ...analysis, parameters: { rate: '0.85' }, conversion_rules: [{ unit: '万元', factor: '10000' }], timeout_seconds: 10, max_rows: 500 };
    const analysisSave = vi.fn(async () => success(named));
    mountBridge({ analysisState: async () => success({ ...initial, analyses: [named] }), analysisSave, analysisRun: async () => success(run) });
    render(<Analysis {...props} />); await screen.findByText('本月实际');
    openAnalysisEditor();
    fireEvent.change(screen.getByLabelText('参数 · rate'), { target: { value: '0.90' } });
    fireEvent.click(screen.getByRole('button', { name: '保存新版并重跑' }));
    await waitFor(() => expect(analysisSave).toHaveBeenCalledWith(task.id, expect.objectContaining({
      parameters: { rate: '0.90' }, conversion_rules: named.conversion_rules, timeout_seconds: 10, max_rows: 500,
    })));
  });

  it('requires explicit datasets for a saved method rather than silently reusing previous data', async () => {
    const method = { ...object, id: '5'.repeat(32), name: '利润比较法', sql: 'select * from actual', input_contracts: { actual: { schema: source.schema! } } };
    const analysisMethodApply = vi.fn(async () => success(analysis));
    mountBridge({ analysisState: async () => success({ ...initial, methods: [method] }), analysisMethodApply });
    render(<Analysis {...props} />); await screen.findByText('本月实际');
    openMethods();
    const button = screen.getByRole('button', { name: '用这些资料创建分析' });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('选择 actual 资料'), { target: { value: source.id } });
    fireEvent.click(button);
    await waitFor(() => expect(analysisMethodApply).toHaveBeenCalledWith(task.id, method.id, { actual: source.id }, []));
  });

  it('passes this run\'s method parameters as exact strings with explicit names', async () => {
    const method = { ...object, id: '6'.repeat(32), name: '回款情景', sql: 'select profit * $rate from actual', input_contracts: { actual: { schema: source.schema! } } };
    const analysisMethodApply = vi.fn(async () => success(analysis));
    mountBridge({ analysisState: async () => success({ ...initial, methods: [method] }), analysisMethodApply });
    render(<Analysis {...props} />); await screen.findByText('本月实际');
    openMethods();
    fireEvent.change(screen.getByLabelText('选择 actual 资料'), { target: { value: source.id } });
    fireEvent.click(screen.getByRole('button', { name: '添加方法参数' }));
    fireEvent.change(screen.getByLabelText('参数 1 的值'), { target: { value: '0.8500000000000001' } });
    fireEvent.change(screen.getByLabelText('参数 1 的名称（可选）'), { target: { value: 'rate' } });
    fireEvent.click(screen.getByRole('button', { name: '用这些资料创建分析' }));
    await waitFor(() => expect(analysisMethodApply).toHaveBeenCalledWith(task.id, method.id, { actual: source.id }, { rate: '0.8500000000000001' }));
  });

  it('builds method parameter fields from the saved contract without exposing old values', async () => {
    const method = { ...object, id: '7'.repeat(32), name: '区域比较', sql: 'select * from actual where region=$1',
      input_contracts: { actual: { schema: source.schema! } }, parameter_contract: [{ parameter: '1', type: 'VARCHAR', source: 'literal' }] };
    const analysisMethodApply = vi.fn(async () => success(analysis));
    mountBridge({ analysisState: async () => success({ ...initial, methods: [method] }), analysisMethodApply });
    render(<Analysis {...props} />); await screen.findByText('本月实际');
    openMethods();
    const input = screen.getByLabelText('参数 1 的值 · 文本') as HTMLInputElement;
    expect(input.value).toBe('');
    expect(screen.queryByRole('button', { name: '添加方法参数' })).toBeNull();
    fireEvent.change(input, { target: { value: '华东' } });
    fireEvent.change(screen.getByLabelText('选择 actual 资料'), { target: { value: source.id } });
    fireEvent.click(screen.getByRole('button', { name: '用这些资料创建分析' }));
    await waitFor(() => expect(analysisMethodApply).toHaveBeenCalledWith(task.id, method.id, { actual: source.id }, ['华东']));
  });

  it('returns to the new analysis start without immediately creating an empty task', async () => {
    mountBridge(); render(<Analysis {...props} />); await screen.findByText('本月实际');
    fireEvent.click(screen.getByRole('button', { name: '新建分析任务' }));
    expect(props.onPick).toHaveBeenCalledWith('');
    expect(props.onNew).not.toHaveBeenCalled();
  });

  it('resumes an existing task without forcing the manager to type another question', async () => {
    mountBridge(); render(<Analysis {...props} />); await screen.findByText('本月实际');
    fireEvent.click(screen.getByRole('button', { name: '继续分析' }));
    await waitFor(() => expect(props.onChat).toHaveBeenCalledWith(undefined, undefined));
  });

  it('keeps the complete initial question after creating a task for a cancelled file selection', async () => {
    mountBridge({ analysisAddFiles: async () => success([]) });
    const prompt = '华东本月利润为什么没达标？'.repeat(20);
    const onChat = vi.fn(async () => { throw new Error('会话暂时不可用'); });
    const { rerender } = render(<Analysis {...props} task={null} tasks={[]} onChat={onChat} />);
    fireEvent.change(screen.getByLabelText('你想分析什么？'), { target: { value: prompt } });
    fireEvent.click(screen.getByRole('button', { name: '添加资料' }));
    rerender(<Analysis {...props} onChat={onChat} />);
    await waitFor(() => expect(onChat).toHaveBeenCalledWith(prompt, undefined, expect.objectContaining({ submit: false, targetTaskId: task.id })));
    expect((screen.getByLabelText('接下来想了解什么？') as HTMLTextAreaElement).value).toBe(prompt);
  });

  it('saves a dirty analysis successor before handing its exact revision to the assistant', async () => {
    const next = { ...analysis, id: '2'.repeat(32), parameters: ['0.93'] };
    const analysisSave = vi.fn(async () => success(next));
    mountBridge({ analysisSave });
    render(<Analysis {...props} />); await screen.findByText('本月实际');
    openAnalysisEditor();
    fireEvent.change(screen.getByLabelText('参数 · 第 1 项'), { target: { value: '0.93' } });
    fireEvent.click(screen.getByRole('button', { name: '与助手调整口径' }));
    await waitFor(() => expect(analysisSave).toHaveBeenCalledWith(task.id, expect.objectContaining({ parameters: ['0.93'], parent_id: analysis.id })));
    expect(props.onChat).toHaveBeenCalledWith(expect.stringContaining(next.id), undefined, expect.objectContaining({ targetTaskId: task.id }));
    expect(analysisSave.mock.invocationCallOrder[0]).toBeLessThan(props.onChat.mock.invocationCallOrder[0]);
  });

  it('saves the current draft body before handing it to the assistant', async () => {
    const next = { ...draft, id: '4'.repeat(32), body: '请核实这段新判断。' };
    const analysisDraft = vi.fn(async () => success(next));
    mountBridge({ analysisDraft });
    render(<Analysis {...props} />); await screen.findByText('本月实际');
    openDraftEditor();
    fireEvent.change(screen.getByLabelText('文稿正文'), { target: { value: next.body } });
    fireEvent.click(screen.getByRole('button', { name: '围绕此稿继续分析' }));
    await waitFor(() => expect(analysisDraft).toHaveBeenCalledWith(task.id, expect.objectContaining({ body: next.body, parent_id: draft.id })));
    expect(props.onChat).toHaveBeenCalledWith(undefined, next.id, expect.objectContaining({ targetTaskId: task.id }));
  });

  it('keeps a dirty draft and blocks export when saving that exact version fails', async () => {
    const analysisExport = vi.fn();
    mountBridge({ analysisDraft: async () => ({ ok: false, refused: true, message: '文稿保存失败' }), analysisExport });
    render(<Analysis {...props} />); await screen.findByText('本月实际');
    openDraftEditor();
    fireEvent.change(screen.getByLabelText('文稿正文'), { target: { value: '不能丢失的修改。' } });
    exportDraft();
    expect((await screen.findByRole('alert')).textContent).toBe('文稿保存失败');
    expect(analysisExport).not.toHaveBeenCalled();
    expect((screen.getByLabelText('文稿正文') as HTMLTextAreaElement).value).toBe('不能丢失的修改。');
  });

  it('restores task-scoped working copies after the workspace is remounted', async () => {
    mountBridge();
    const view = render(<Analysis {...props} />); await screen.findByText('本月实际');
    fireEvent.change(screen.getByLabelText('接下来想了解什么？'), { target: { value: '留待补充资料的问题。' } });
    openDraftEditor();
    fireEvent.change(screen.getByLabelText('文稿正文'), { target: { value: '需要继续推敲的判断。' } });
    view.unmount();
    render(<Analysis {...props} />); await screen.findByText('本月实际');
    expect((screen.getByLabelText('接下来想了解什么？') as HTMLTextAreaElement).value).toBe('留待补充资料的问题。');
    openDraftEditor();
    expect((screen.getByLabelText('文稿正文') as HTMLTextAreaElement).value).toBe('需要继续推敲的判断。');
  });

  it('supports keyboard navigation across the workspace tabs', async () => {
    mountBridge(); render(<Analysis {...props} />); await screen.findByText('本月实际');
    const first = screen.getByRole('tab', { name: /资料/ });
    first.focus(); fireEvent.keyDown(first, { key: 'ArrowRight' });
    expect(screen.getByRole('tab', { name: /分析结果/ }).getAttribute('aria-selected')).toBe('true');
    expect(document.activeElement).toBe(screen.getByRole('tab', { name: /分析结果/ }));
  });

  it('embeds an existing task without another task header or composer and exposes materials import', async () => {
    const onSectionChange = vi.fn();
    const analysisAddFiles = vi.fn(async () => success([]));
    mountBridge({ analysisAddFiles });
    render(<Analysis {...props} embedded section="results" onSectionChange={onSectionChange} />);
    await screen.findByText('900719925474099.99');
    expect(screen.queryByLabelText('接下来想了解什么？')).toBeNull();
    expect(screen.queryByRole('heading', { name: task.title })).toBeNull();
    expect(screen.queryByRole('tab', { name: /方法/ })).toBeNull();
    fireEvent.click(screen.getByRole('tab', { name: /资料/ }));
    expect(onSectionChange).toHaveBeenCalledWith('materials');
    fireEvent.click(screen.getByRole('button', { name: '添加资料' }));
    await waitFor(() => expect(analysisAddFiles).toHaveBeenCalledWith(task.id));
  });

  it('keeps one successful result visible after a later failure, and opens exact history records', async () => {
    const newer = { ...analysis, id: '1'.repeat(32), question: '新的成本口径' };
    const failed = { ...run, id: '2'.repeat(32), analysis_id: newer.id, execution_status: 'failed', error: '缺少成本列', result: undefined };
    mountBridge({ analysisState: async () => success({ ...initial, analyses: [analysis, newer], runs: [run, failed] }) });
    render(<Analysis {...props} embedded section="results" />);
    await screen.findByText('900719925474099.99');
    expect(screen.getAllByRole('table')).toHaveLength(1);
    expect(screen.getByText('900719925474099.99').classList.contains('analysis-number')).toBe(true);
    const definition = screen.getByText(/^口径与计算定义/).closest('details');
    expect(definition?.open).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: '查看失败记录' }));
    expect((await screen.findByRole('alert')).textContent).toBe('缺少成本列');
    expect(screen.queryByRole('table')).toBeNull();
    expect((screen.getByLabelText('分析版本') as HTMLSelectElement).value).toBe(newer.id);
  });

  it('opens a local evidence panel and returns keyboard focus when it is dismissed', async () => {
    const analysisReadDataset = vi.fn(async () => success({ text: '本次依据内容' }));
    mountBridge({ analysisReadDataset }); render(<Analysis {...props} embedded section="results" />);
    await screen.findByText('900719925474099.99');
    const trigger = screen.getByRole('button', { name: '查看本次计算依据' });
    fireEvent.click(trigger);
    const panel = screen.getByRole('dialog', { name: '本次计算依据' });
    expect(panel.closest('.analysis-content')).toBeTruthy();
    expect(panel.getAttribute('aria-modal')).toBe('false');
    expect(document.activeElement).toBe(screen.getByRole('button', { name: '关闭计算依据' }));
    fireEvent.click(within(panel).getByRole('button', { name: '查看 本月实际' }));
    await waitFor(() => expect(analysisReadDataset).toHaveBeenCalledWith(task.id, source.id));
    expect(await screen.findByText('本次依据内容')).toBeTruthy();
    fireEvent.keyDown(panel, { key: 'Escape' });
    expect(screen.queryByRole('dialog', { name: '本次计算依据' })).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it('compares actual saved results without fabricating a derived variance', async () => {
    const earlier = { ...run, id: '9'.repeat(32), result: { ...run.result!, rows: [{ profit: '900719925474000.09' }] } };
    mountBridge({ analysisState: async () => success({ ...initial, runs: [earlier, run] }) });
    render(<Analysis {...props} embedded section="results" />); await screen.findByText('900719925474099.99');
    fireEvent.click(screen.getByRole('button', { name: '比较版本' }));
    fireEvent.change(screen.getByLabelText('对照运行'), { target: { value: earlier.id } });
    const comparison = screen.getByRole('region', { name: '版本比较' });
    expect(within(comparison).getByText('900719925474099.99')).toBeTruthy();
    expect(within(comparison).getByText('900719925474000.09')).toBeTruthy();
    expect(within(comparison).getByText(/未推断业务主键或计算差额/)).toBeTruthy();
  });

  it('uses declared business parameter labels while preserving exact decimal text in a successor', async () => {
    const named: AnalysisRevision = { ...analysis, sql: 'select profit * $Rate from actual', parameters: { rate: '0.85' }, parameter_metadata: [
      { key: 'Rate', label: '回款比例', type: 'decimal', unit: '比例', role: 'business', description: '本次预计能收回的比例', constraints: { min: '0', max: '1' } },
    ] };
    const analysisSave = vi.fn(async () => success(named));
    mountBridge({ analysisState: async () => success({ ...initial, analyses: [named] }), analysisSave, analysisRun: async () => success(run) });
    render(<Analysis {...props} />); await screen.findByText('本月实际'); openAnalysisEditor();
    fireEvent.change(screen.getByLabelText('回款比例（比例）'), { target: { value: '0.8500000000000001' } });
    expect(screen.getByText(/当前结果尚未更新/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '保存新版并重跑' }));
    await waitFor(() => expect(analysisSave).toHaveBeenCalledWith(task.id, expect.objectContaining({ parameters: { rate: '0.8500000000000001' }, parameter_metadata: named.parameter_metadata })));
  });

  it('uses declared formula constants while requiring a new business value for method reuse', async () => {
    const method = { ...object, id: '8'.repeat(32), name: '利润比例法', sql: 'select profit * $1 / $2 from actual', inputs: ['actual'],
      parameter_contract: [
        { parameter: '1', type: 'DECIMAL', source: 'parameter', role: 'business' as const,
          metadata: { key: '1', label: '回款比例', type: 'decimal' as const, role: 'business' as const } },
        { parameter: '2', type: 'INTEGER', source: 'literal', role: 'formula_constant' as const, default: '100' },
      ] };
    const analysisMethodApply = vi.fn(async () => success(analysis));
    mountBridge({ analysisState: async () => success({ ...initial, methods: [method] }), analysisMethodApply });
    render(<Analysis {...props} />); await screen.findByText('本月实际'); openMethods();
    expect((screen.getByLabelText('回款比例') as HTMLInputElement).value).toBe('');
    expect(screen.queryByLabelText(/参数 2 的值/)).toBeNull();
    fireEvent.change(screen.getByLabelText('选择 actual 资料'), { target: { value: source.id } });
    expect((screen.getByRole('button', { name: '用这些资料创建分析' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('回款比例'), { target: { value: '85.00000000000001' } });
    fireEvent.click(screen.getByRole('button', { name: '用这些资料创建分析' }));
    await waitFor(() => expect(analysisMethodApply).toHaveBeenCalledWith(task.id, method.id, { actual: source.id }, { '1': '85.00000000000001', '2': '100' }));
  });

  it('reads a saved draft by default and preserves edits between reading and editing', async () => {
    mountBridge(); render(<Analysis {...props} embedded section="drafts" />);
    expect(await screen.findByRole('article', { name: '文稿阅读' })).toBeTruthy();
    expect(screen.queryByLabelText('文稿正文')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '编辑文稿' }));
    fireEvent.change(screen.getByLabelText('文稿正文'), { target: { value: '经理自己的判断。' } });
    fireEvent.click(screen.getByRole('button', { name: '阅读文稿' }));
    expect(within(screen.getByRole('article', { name: '文稿阅读' })).getByText('经理自己的判断。')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '编辑文稿' }));
    expect((screen.getByLabelText('文稿正文') as HTMLTextAreaElement).value).toBe('经理自己的判断。');
  });

  it('refreshes an active workspace on a bounded cadence without taking editor focus', async () => {
    vi.useFakeTimers();
    let backend = initial;
    const analysisState = vi.fn(async () => success(backend));
    mountBridge({ analysisState });
    const { rerender } = render(<Analysis {...props} active />);
    await act(async () => { await Promise.resolve(); });
    openDraftEditor();
    const input = screen.getByLabelText('文稿正文');
    fireEvent.change(input, { target: { value: '仍在编辑。' } }); input.focus();
    backend = { ...initial, drafts: [...initial.drafts, { ...draft, id: '7'.repeat(32), title: '助手刚完成的报告' }] };
    await act(async () => { await vi.advanceTimersByTimeAsync(4999); });
    expect(analysisState).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(analysisState).toHaveBeenCalledTimes(2);
    expect(screen.getByRole('option', { name: /助手刚完成的报告/ })).toBeTruthy();
    expect((screen.getByLabelText('文稿正文') as HTMLTextAreaElement).value).toBe('仍在编辑。');
    expect(document.activeElement).toBe(input);
    rerender(<Analysis {...props} active={false} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(20000); });
    expect(analysisState).toHaveBeenCalledTimes(2);
  });

  it('targets the returned new task even if the user switches tasks while creation is pending', async () => {
    const other = { ...task, id: '6'.repeat(32), title: '另一个任务' };
    const prompt = '只属于新任务的完整问题。';
    let resolve!: (id: string) => void;
    const onNew = vi.fn(() => new Promise<string>((done) => { resolve = done; }));
    mountBridge({ analysisState: async (id) => success({ ...initial, task_id: id }) });
    const onChat = vi.fn(async () => {});
    const { rerender } = render(<Analysis {...props} task={null} onNew={onNew} onChat={onChat} />);
    fireEvent.change(screen.getByLabelText('你想分析什么？'), { target: { value: prompt } });
    fireEvent.click(screen.getByRole('button', { name: '开始分析' }));
    rerender(<Analysis {...props} task={other} onNew={onNew} onChat={onChat} />);
    await act(async () => resolve(task.id));
    await waitFor(() => expect(onChat).toHaveBeenCalledWith(prompt, undefined, expect.objectContaining({ submit: true, targetTaskId: task.id })));
    expect((screen.getByLabelText('接下来想了解什么？') as HTMLTextAreaElement).value).toBe('');
  });

  it('retains the question until handoff succeeds and reuses the first submission request id on retry', async () => {
    const prompt = '失败后仍要继续的问题。';
    const onChat = vi.fn().mockRejectedValueOnce(new Error('暂时断开')).mockResolvedValueOnce(undefined);
    const onNew = vi.fn(async () => task.id);
    mountBridge();
    const { rerender } = render(<Analysis {...props} task={null} onNew={onNew} onChat={onChat} />);
    fireEvent.change(screen.getByLabelText('你想分析什么？'), { target: { value: prompt } });
    fireEvent.click(screen.getByRole('button', { name: '开始分析' }));
    rerender(<Analysis {...props} onNew={onNew} onChat={onChat} />);
    expect((await screen.findByRole('alert')).textContent).toBe('暂时断开');
    expect((screen.getByLabelText('接下来想了解什么？') as HTMLTextAreaElement).value).toBe(prompt);
    fireEvent.click(screen.getByRole('button', { name: '继续分析' }));
    await waitFor(() => expect(onChat).toHaveBeenCalledTimes(2));
    expect(onChat.mock.calls[1][2]).toEqual(onChat.mock.calls[0][2]);
    expect((screen.getByLabelText('接下来想了解什么？') as HTMLTextAreaElement).value).toBe('');
    expect(onNew).toHaveBeenCalledTimes(1);
  });

  it('does not take the reader back to an older draft when its delayed save completes', async () => {
    const other = { ...draft, id: '6'.repeat(32), title: '另一个文稿版本', body: '用户正在核对这一版。' };
    const next = { ...draft, id: '5'.repeat(32), parent_id: draft.id, body: '刚保存的修改。' };
    let finish!: (answer: Answer<AnalysisDraft>) => void;
    mountBridge({ analysisState: async () => success({ ...initial, drafts: [other, draft] }),
      analysisDraft: () => new Promise((resolve) => { finish = resolve; }) });
    render(<Analysis {...props} />); await screen.findByText('本月实际'); openDraftEditor();
    fireEvent.change(screen.getByLabelText('文稿正文'), { target: { value: next.body } });
    fireEvent.click(screen.getByRole('button', { name: '保存文稿新版' }));
    fireEvent.change(screen.getByLabelText('文稿版本'), { target: { value: other.id } });
    expect(screen.getByRole('article', { name: '文稿阅读' }).textContent).toContain(other.body);
    await act(async () => finish(success(next)));
    expect((screen.getByLabelText('文稿版本') as HTMLSelectElement).value).toBe(other.id);
    expect(screen.getByRole('article', { name: '文稿阅读' }).textContent).toContain(other.body);
    expect(screen.getAllByRole('option', { name: /经营简报/ })).toHaveLength(2);
  });

  it('renders ordinary financial Markdown as safe headings, paragraphs, lists, emphasis, code and tables', async () => {
    const body = '# 经营结论\n本月经营利润为 **250 万元**，计算字段为 `profit`。\n\n- 回款改善\n- 成本下降\n\n1. 核对成本\n2. 跟进回款\n\n| 项目 | 金额 |\n| --- | ---: |\n| 经营利润 | **250** |\n\n<img src=x onerror="alert(1)">';
    mountBridge({ analysisState: async () => success({ ...initial, drafts: [{ ...draft, body }] }) });
    render(<Analysis {...props} embedded section="drafts" />);
    const reading = await screen.findByRole('article', { name: '文稿阅读' });
    expect(within(reading).getByRole('heading', { name: '经营结论' })).toBeTruthy();
    expect(within(reading).getByText('250 万元').tagName).toBe('STRONG');
    expect(within(reading).getByText('profit').tagName).toBe('CODE');
    expect(within(reading).getByText('核对成本').closest('ol')).toBeTruthy();
    expect(within(reading).getByText('回款改善').closest('ul')).toBeTruthy();
    expect(within(reading).getByRole('columnheader', { name: '金额' })).toBeTruthy();
    expect(within(reading).getByRole('cell', { name: '250' }).querySelector('strong')).toBeTruthy();
    expect(reading.querySelector('img, script')).toBeNull();
    expect(within(reading).getByText('<img src=x onerror="alert(1)">')).toBeTruthy();
  });

  it('names populated draft controls explicitly without including their contents', async () => {
    mountBridge(); render(<Analysis {...props} embedded section="drafts" />);
    await screen.findByRole('article', { name: '文稿阅读' });
    fireEvent.click(screen.getByRole('button', { name: '编辑文稿' }));
    for (const name of ['文稿标题', '文稿正文', '局限与待确认事项（每行一项）', '我的审阅状态']) {
      expect(screen.getByLabelText(name, { exact: true }).getAttribute('aria-label')).toBe(name);
    }
    expect(screen.getByRole('textbox', { name: '文稿正文' })).toBeTruthy();
  });

  it('gives the embedded method library a real accessible panel name without a methods tab', async () => {
    mountBridge(); render(<Analysis {...props} embedded section="methods" />);
    await screen.findByRole('heading', { name: '方法库' });
    expect(screen.queryByRole('tab', { name: /方法/ })).toBeNull();
    expect(screen.getByRole('tabpanel', { name: '方法库' })).toBeTruthy();
  });

  it.each([false, true])('resolves alias-keyed hashes to the exact source version (immutable run bindings: %s)', async (runBindings) => {
    const inputHash = '6'.repeat(64);
    const original = { ...source, name: '八月经营数据', data_hash: inputHash, metadata: { currency: 'CNY', unit: '元' } };
    const replacement = { ...original, id: '8'.repeat(32), source_hash: '9'.repeat(64), data_hash: '5'.repeat(64), metadata: { currency: 'CNY', unit: '万元' } };
    const revised = { ...analysis, id: '7'.repeat(32), bindings: { actual: replacement.id } };
    const actualRun = { ...run, ...(runBindings ? { bindings: { actual: original.id } } : {}), input_hashes: { actual: inputHash } };
    const analysisReadDataset = vi.fn(async () => success({ columns: [], rows: [], text: '原始八月明细' }));
    mountBridge({ analysisState: async () => success({ ...initial, datasets: [original, replacement],
      analyses: [runBindings ? { ...analysis, bindings: revised.bindings } : analysis, revised], runs: [actualRun] }), analysisReadDataset });
    render(<Analysis {...props} embedded section="results" />);
    await screen.findByText('900719925474099.99');
    fireEvent.click(screen.getByRole('button', { name: '查看本次计算依据' }));
    const evidence = screen.getByRole('dialog', { name: '本次计算依据' });
    fireEvent.click(within(evidence).getByRole('button', { name: '查看 八月经营数据' }));
    await waitFor(() => expect(analysisReadDataset).toHaveBeenCalledExactlyOnceWith(task.id, original.id));
    expect(within(evidence).getByText(original.id)).toBeTruthy();
    expect(within(evidence).getByText(inputHash)).toBeTruthy();
    expect(within(evidence).queryByText(replacement.id)).toBeNull();
    const preview = await screen.findByRole('region', { name: '依据资料预览' });
    expect(within(preview).getByText('unit：元')).toBeTruthy();
    expect(within(preview).queryByText('unit：万元')).toBeNull();
  });

  it('keeps source identifiers visible but prevents opening a snapshot whose data hash differs from the run', async () => {
    const recordedHash = '6'.repeat(64);
    const currentHash = '7'.repeat(64);
    const analysisReadDataset = vi.fn();
    mountBridge({ analysisReadDataset, analysisState: async () => success({ ...initial,
      datasets: [{ ...source, data_hash: currentHash }], runs: [{ ...run, bindings: analysis.bindings, input_hashes: { actual: recordedHash } }] }) });
    render(<Analysis {...props} embedded section="results" />); await screen.findByText('900719925474099.99');
    fireEvent.click(screen.getByRole('button', { name: '查看本次计算依据' }));
    const panel = screen.getByRole('dialog', { name: '本次计算依据' });
    const open = within(panel).getByRole('button', { name: '查看 本月实际' });
    expect((open as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(open);
    expect(analysisReadDataset).not.toHaveBeenCalled();
    expect(within(panel).getByText(source.id)).toBeTruthy();
    expect(within(panel).getByText(recordedHash)).toBeTruthy();
    expect(within(panel).getByText(/资料摘要与运行记录不一致/)).toBeTruthy();
  });

  it('uses each saved run\'s business labels, exact values, units and structured assumptions in evidence and comparison', async () => {
    const previous: AnalysisRevision = { ...analysis, parameters: { overhead: '20.00' },
      parameter_metadata: [{ key: 'OVERHEAD', label: '历史分摊费用', type: 'decimal', role: 'business', unit: '元' }],
      assumptions: [{ name: '分摊口径', value: '各区域按上月收入分摊' }] };
    const current: AnalysisRevision = { ...analysis, id: '8'.repeat(32), parameters: { overhead: '999.00' },
      parameter_metadata: [{ key: 'overhead', label: '定义中的其他费用', type: 'decimal', role: 'business', unit: '美元' }],
      assumptions: [{ name: '分摊口径', value: '定义中的其他说明' }] };
    const savedRun = { ...run, id: '7'.repeat(32), analysis_id: current.id, parameters: { overhead: '30.00000000000001' },
      parameter_metadata: [{ key: 'Overhead', label: '总部费用分摊', type: 'decimal' as const, role: 'business' as const, unit: '万元' }],
      assumptions: [{ name: '分摊口径', value: '各区域按本月收入分摊' }] };
    mountBridge({ analysisState: async () => success({ ...initial, analyses: [previous, current], runs: [run, savedRun] }) });
    render(<Analysis {...props} embedded section="results" />); await screen.findByText('900719925474099.99');
    fireEvent.click(screen.getByRole('button', { name: '查看本次计算依据' }));
    const evidence = screen.getByRole('dialog', { name: '本次计算依据' });
    expect(within(evidence).getByText('参数：总部费用分摊：30.00000000000001 万元')).toBeTruthy();
    expect(within(evidence).getByText('假设说明：分摊口径：各区域按本月收入分摊')).toBeTruthy();
    expect(within(evidence).queryByText(/999.00|其他费用|美元/)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '关闭计算依据' }));
    fireEvent.click(screen.getByRole('button', { name: '比较版本' }));
    fireEvent.change(screen.getByLabelText('对照运行'), { target: { value: run.id } });
    const comparison = screen.getByRole('region', { name: '版本比较' });
    expect(within(comparison).getByText('参数：总部费用分摊：30.00000000000001 万元')).toBeTruthy();
    expect(within(comparison).getByText('参数：历史分摊费用：20.00 元')).toBeTruthy();
    expect(within(comparison).getByText('假设说明：分摊口径：各区域按上月收入分摊')).toBeTruthy();
    expect(within(comparison).queryByText(/name：|value：|其他费用/)).toBeNull();
  });

  it('keeps original parameter keys when a historical definition has no business metadata', async () => {
    const unknown = { ...analysis, parameters: { overhead: '30.00', legacy_rate: '0.8500000000000001' },
      assumptions: [{ label: '估计依据', description: '经理提供的本次估计' }, { note: '未知结构保持原文' }] };
    mountBridge({ analysisState: async () => success({ ...initial, analyses: [unknown] }) });
    render(<Analysis {...props} embedded section="results" />); await screen.findByText('900719925474099.99');
    fireEvent.click(screen.getByRole('button', { name: '查看本次计算依据' }));
    const evidence = screen.getByRole('dialog', { name: '本次计算依据' });
    expect(within(evidence).getByText('参数：overhead：30.00；legacy_rate：0.8500000000000001')).toBeTruthy();
    expect(within(evidence).getByText('假设说明：估计依据：经理提供的本次估计；note：未知结构保持原文')).toBeTruthy();
    expect(within(evidence).queryByText(/万元|回款比例/)).toBeNull();
  });
});
