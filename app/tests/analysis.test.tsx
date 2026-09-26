// @vitest-environment jsdom
import { press } from './press.js';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const pdfjsMock = vi.hoisted(() => ({
  workerOptions: { workerSrc: '' },
  getDocument: vi.fn(() => ({
    promise: Promise.resolve({
      numPages: 1,
      getPage: async () => ({
        getViewport: () => ({ width: 1, height: 1 }),
        render: () => ({ promise: Promise.resolve(), cancel() {} }),
      }),
    }),
  })),
}));
vi.mock('pdfjs-dist', () => ({
  GlobalWorkerOptions: pdfjsMock.workerOptions,
  getDocument: pdfjsMock.getDocument,
}));
import { Analysis } from '../src/views/Analysis.js';
import { DraftBody } from '../src/views/analysis/DraftBody.js';
import { documentFromMarkdown, documentToMarkdown } from '../electron/reports/format.js';
import type { Answer, AnalysisDraft, AnalysisRevision, AnalysisRun, AnalysisState, Bridge, DatasetSnapshot, TaskRow } from '../src/bridge.js';

const task: TaskRow = { id: 'a'.repeat(32), title: '华东经营分析', period: null, skill_id: null, created_at: '2026-09-05T00:00:00Z', windows: 0 };
const object = { task_id: task.id, schema_version: 1, created_at: task.created_at };
const source: DatasetSnapshot = { ...object, id: 'b'.repeat(32), name: '本月实际', kind: 'table', source_hash: 'c'.repeat(64), source_name: 'actual.csv',
  metadata: { currency: 'CNY', unit: '元' }, schema: [{ name: 'profit', type: 'DECIMAL(38,2)' }], row_count: 1 };
const budgetSource: DatasetSnapshot = { ...source, id: '1'.repeat(32), name: '本月预算', source_hash: '1'.repeat(64), source_name: 'budget.csv' };
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
  const edit = screen.queryByRole('tab', { name: '编辑', selected: false });
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
  press(screen.getByRole('button', { name: '导出' }));
  fireEvent.click(screen.getByRole('menuitem', { name: /导出文稿/ }));
}
function openMethods() {
  fireEvent.click(screen.getByRole('tab', { name: /方法/ }));
  for (const summary of screen.queryAllByText('高级参数与公式定义')) {
    if (summary.closest('details')) (summary.closest('details') as HTMLDetailsElement).open = true;
  }
}
async function openSourceRefreshDetails() {
  const heading = await screen.findByText('更新 ERP 来源');
  const details = heading.closest('details') as HTMLDetailsElement | null;
  expect(details).toBeTruthy();
  if (!details!.open) fireEvent.click(heading.closest('summary')!);
  expect(details!.open).toBe(true);
  return details!;
}
function sourceRefreshField(label: string) {
  const details = screen.getByText('更新 ERP 来源').closest('details') as HTMLDetailsElement;
  return within(details).getByLabelText(label);
}
function chooseSearchable(label: string, option: RegExp | string) {
  fireEvent.click(screen.getByRole('button', { name: label }));
  fireEvent.mouseDown(screen.getByRole('option', { name: option }));
}
function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise; reject = rejectPromise;
  });
  return { promise, resolve, reject };
}
const props = { task, tasks: [task], onPick: vi.fn(), onNew: vi.fn(), onChat: vi.fn() };
afterEach(() => { cleanup(); delete (globalThis as unknown as { foundry?: Bridge }).foundry; vi.clearAllMocks(); vi.useRealTimers(); sessionStorage.clear(); });

describe('analysis workbench', () => {
  it('shows a complete workbook as sheets instead of an empty flat table', async () => {
    const workbook: DatasetSnapshot = { ...source, name: '月结套表', source_name: '月结.xlsx', kind: 'workbook',
      schema: [], row_count: 0, transformation: { sheet_count: 2 } };
    const analysisReadDataset = vi.fn(async () => success({ ...workbook, workbook: { sheets: [
      { name: '00·封面', rows: 12, columns: 8 }, { name: '04·合并利润表', rows: 40, columns: 7 },
    ] } }));
    mountBridge({ analysisState: async () => success({ ...initial, datasets: [workbook] }), analysisReadDataset });
    render(<Analysis {...props} embedded section="materials" />);
    fireEvent.click(await screen.findByRole('button', { name: /月结套表\s*Excel 工作簿 · 2 张工作表/ }));
    const directory = await screen.findByRole('table', { name: '工作表目录' });
    expect(within(directory).getByText('00·封面')).toBeTruthy();
    expect(within(directory).getByText('04·合并利润表')).toBeTruthy();
    expect(screen.queryByText(/Excel 工作簿 · 0 行/)).toBeNull();
    expect(analysisReadDataset).toHaveBeenCalledWith(task.id, workbook.id);
  });

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
    expect(screen.getByLabelText('脚本计算输出').closest('details')?.open).toBe(false);
    expect(screen.getByText('脚本输出 · 1 行')).toBeTruthy();
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
    await waitFor(() => expect(analysisExport).toHaveBeenCalledWith(task.id, '3'.repeat(32), 'md', 'management'));
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
    chooseSearchable('分析版本', /888888888888/);
    expect((screen.getByLabelText('参数 · 第 1 项') as HTMLInputElement).value).toBe('0.70');
    chooseSearchable('分析版本', /dddddddddddd/);
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
    fireEvent.click(screen.getByRole('button', { name: '文稿版本' }));
    expect(await screen.findByRole('option', { name: /助手新增报告/ })).toBeTruthy();
    fireEvent.keyDown(screen.getByLabelText('文稿版本搜索'), { key: 'Escape' });
    expect((screen.getByLabelText('文稿正文') as HTMLTextAreaElement).value).toBe('返回后还要继续写的判断。');
    openAnalysisEditor();
    expect((screen.getByLabelText('参数 · 第 1 项') as HTMLInputElement).value).toBe('0.92');
    expect(screen.getByRole('button', { name: '分析版本' }).textContent).toContain('华东利润分析');
    fireEvent.click(screen.getByRole('button', { name: '分析版本' }));
    expect(await screen.findByRole('option', { name: /助手新计算的预算差异/ })).toBeTruthy();
    fireEvent.keyDown(screen.getByLabelText('分析版本搜索'), { key: 'Escape' });
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
    chooseSearchable('选择 actual 资料', /本月实际/);
    fireEvent.click(button);
    await waitFor(() => expect(analysisMethodApply).toHaveBeenCalledWith(task.id, method.id, { actual: source.id }, []));
  });

  it('passes this run\'s method parameters as exact strings with explicit names', async () => {
    const method = { ...object, id: '6'.repeat(32), name: '回款情景', sql: 'select profit * $rate from actual', input_contracts: { actual: { schema: source.schema! } } };
    const analysisMethodApply = vi.fn(async () => success(analysis));
    mountBridge({ analysisState: async () => success({ ...initial, methods: [method] }), analysisMethodApply });
    render(<Analysis {...props} />); await screen.findByText('本月实际');
    openMethods();
    chooseSearchable('选择 actual 资料', /本月实际/);
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
    chooseSearchable('选择 actual 资料', /本月实际/);
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
    const resultArea = screen.getByText('900719925474099.99').closest('.analysis-result') as HTMLElement;
    expect(within(resultArea).getAllByRole('table')).toHaveLength(1);
    expect(screen.getByText('900719925474099.99').classList.contains('analysis-number')).toBe(true);
    const definition = screen.getByText(/^口径与计算定义/).closest('details');
    expect(definition?.open).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: '查看失败记录' }));
    expect((await screen.findByRole('alert')).textContent).toBe('缺少成本列');
    // A failed run shows no result table. The account-map editor is a table of
    // its own elsewhere on the page, so this looks where the result would be.
    expect(document.querySelector('.analysis-result table')).toBeNull();
    expect(screen.getByRole('button', { name: '分析版本' }).textContent).toContain('新的成本口径');
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
    chooseSearchable('选择 actual 资料', /本月实际/);
    expect((screen.getByRole('button', { name: '用这些资料创建分析' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('回款比例'), { target: { value: '85.00000000000001' } });
    fireEvent.click(screen.getByRole('button', { name: '用这些资料创建分析' }));
    await waitFor(() => expect(analysisMethodApply).toHaveBeenCalledWith(task.id, method.id, { actual: source.id }, { '1': '85.00000000000001', '2': '100' }));
  });

  it('reads a saved draft by default and preserves edits between reading and editing', async () => {
    mountBridge(); render(<Analysis {...props} embedded section="drafts" />);
    expect(await screen.findByRole('article', { name: '文稿阅读' })).toBeTruthy();
    expect(screen.queryByLabelText('文稿正文')).toBeNull();
    const toolbar = screen.getByRole('group', { name: '文稿工具栏' });
    expect(within(toolbar).getByRole('heading', { name: /^文稿$/ })).toBeTruthy();
    expect(within(toolbar).getByRole('tablist', { name: '文稿模式' })).toBeTruthy();
    expect(within(toolbar).getByRole('button', { name: '围绕此稿继续分析' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /^(编辑文稿|阅读文稿)$/ })).toBeNull();
    fireEvent.click(screen.getByRole('tab', { name: /^编辑$/ }));
    fireEvent.change(screen.getByLabelText('文稿正文'), { target: { value: '经理自己的判断。' } });
    fireEvent.click(screen.getByRole('tab', { name: /^阅读$/ }));
    expect(within(screen.getByRole('article', { name: '文稿阅读' })).getByText('经理自己的判断。')).toBeTruthy();
    fireEvent.click(screen.getByRole('tab', { name: /^编辑$/ }));
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
    expect(screen.getByRole('tab', { name: /文稿/ }).textContent).toContain('2');
    expect(screen.getByRole('button', { name: '文稿版本' }).getAttribute('title')).toContain('经营简报');
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
    chooseSearchable('文稿版本', /另一个文稿版本/);
    expect(screen.getByRole('article', { name: '文稿阅读' }).textContent).toContain(other.body);
    await act(async () => finish(success(next)));
    expect(screen.getByRole('button', { name: '文稿版本' }).getAttribute('title')).toContain('另一个文稿版本');
    expect(screen.getByRole('article', { name: '文稿阅读' }).textContent).toContain(other.body);
    fireEvent.click(screen.getByRole('button', { name: '文稿版本' }));
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

  it('normalizes draft heading depth without reading headings inside code fences or raw HTML', () => {
    const body = '```md\n# 代码里的标题\n```\n\n## 经营结论\n### 主要驱动\n<img src=x onerror="alert(1)">';
    const view = render(<DraftBody body={body} />);
    expect(screen.getByRole('heading', { name: '经营结论' }).tagName).toBe('H3');
    expect(screen.getByRole('heading', { name: '主要驱动' }).tagName).toBe('H4');
    expect(screen.getByText('# 代码里的标题').tagName).toBe('CODE');
    expect(document.querySelector('img, script')).toBeNull();
    expect(screen.getByText('<img src=x onerror="alert(1)">')).toBeTruthy();

    view.rerender(<DraftBody body={'# 一级结论\n## 二级说明'} />);
    expect(screen.getByRole('heading', { name: '一级结论' }).tagName).toBe('H3');
    expect(screen.getByRole('heading', { name: '二级说明' }).tagName).toBe('H4');
  });

  it('folds only the exact stored evidence appendix suffix while preserving the draft body for editing', async () => {
    const appendix = '## 计算依据附录\n| 项目 | 金额 |\n| --- | ---: |\n| 经营利润 | 250 |';
    const body = `# 经营结论\n本月经营利润为 250 万元。\n\n${appendix}`;
    mountBridge({ analysisState: async () => success({ ...initial, drafts: [{ ...draft, body, evidence_appendix: appendix }] }) });
    render(<Analysis {...props} embedded section="drafts" />);
    const reading = await screen.findByRole('article', { name: '文稿阅读' });
    const main = reading.querySelector('.analysis-draft-main') as HTMLElement;
    expect(within(main).getByText('本月经营利润为 250 万元。')).toBeTruthy();
    expect(within(main).queryByRole('heading', { name: '计算依据附录' })).toBeNull();
    const fold = within(reading).getByText('系统生成计算依据附录').closest('details') as HTMLDetailsElement;
    expect(fold).toBeTruthy();
    fold.open = true;
    expect(within(fold).getByRole('heading', { name: '计算依据附录' })).toBeTruthy();
    fireEvent.click(screen.getByRole('tab', { name: /^编辑$/ }));
    expect((screen.getByLabelText('文稿正文') as HTMLTextAreaElement).value).toBe(body);
  });

  it('folds a canonical regenerated evidence appendix suffix', async () => {
    const appendix = '## 计算依据附录\n本月利润来自系统证据。';
    const canonicalAppendix = documentToMarkdown(documentFromMarkdown(appendix)).trim();
    const body = `# 经营结论
本月经营利润为 250 万元。

${canonicalAppendix}`;
    mountBridge({ analysisState: async () => success({ ...initial, drafts: [{ ...draft, body, evidence_appendix: appendix }] }) });
    render(<Analysis {...props} embedded section="drafts" />);
    const reading = await screen.findByRole('article', { name: '文稿阅读' });
    const main = reading.querySelector('.analysis-draft-main') as HTMLElement;
    expect(within(main).getByText('本月经营利润为 250 万元。')).toBeTruthy();
    expect(within(main).queryByRole('heading', { name: '计算依据附录' })).toBeNull();
    const fold = within(reading).getByText('系统生成计算依据附录').closest('details') as HTMLDetailsElement;
    expect(fold).toBeTruthy();
    fold.open = true;
    expect(within(fold).getByRole('heading', { name: '计算依据附录' })).toBeTruthy();
  });

  it('keeps a tampered canonical appendix visible inline', async () => {
    const appendix = '## 计算依据附录\n本月利润来自系统证据。';
    const canonicalAppendix = documentToMarkdown(documentFromMarkdown(appendix)).trim();
    const body = `# 经营结论
本月经营利润为 250 万元。

${canonicalAppendix} 已改写`;
    mountBridge({ analysisState: async () => success({ ...initial, drafts: [{ ...draft, body, evidence_appendix: appendix }] }) });
    render(<Analysis {...props} embedded section="drafts" />);
    const reading = await screen.findByRole('article', { name: '文稿阅读' });
    expect(within(reading).getByRole('heading', { name: '计算依据附录' })).toBeTruthy();
    expect(within(reading).getByText(/本月利润来自系统证据。 已改写/)).toBeTruthy();
    expect(within(reading).queryByText('系统生成计算依据附录')).toBeNull();
  });

  it('keeps a similar appendix marker inline when it is not the exact stored suffix', async () => {
    const appendix = '## 计算依据附录\n| 项目 | 金额 |\n| --- | ---: |\n| 经营利润 | 250 |';
    const body = '# 经营结论\n本月经营利润为 250 万元。\n\n## 计算依据附录\n经理手工改写过的依据。';
    mountBridge({ analysisState: async () => success({ ...initial, drafts: [{ ...draft, body, evidence_appendix: appendix }] }) });
    render(<Analysis {...props} embedded section="drafts" />);
    const reading = await screen.findByRole('article', { name: '文稿阅读' });
    expect(within(reading).getByRole('heading', { name: '计算依据附录' })).toBeTruthy();
    expect(within(reading).getByText('经理手工改写过的依据。')).toBeTruthy();
    expect(within(reading).queryByText('系统生成计算依据附录')).toBeNull();
  });

  it('names populated draft controls explicitly without including their contents', async () => {
    mountBridge(); render(<Analysis {...props} embedded section="drafts" />);
    await screen.findByRole('article', { name: '文稿阅读' });
    fireEvent.click(screen.getByRole('tab', { name: /^编辑$/ }));
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

  it('keeps the user on drafts when a finance run refresh finishes after they leave results', async () => {
    const refreshGate = deferred<Answer<AnalysisState>>();
    const analysisState = vi.fn(async () => analysisState.mock.calls.length === 1 ? success({ ...initial, datasets: [source, budgetSource] }) : refreshGate.promise);
    const financeCall = vi.fn(async (_taskId: string, command: string, spec?: Record<string, unknown>) => {
      if (command === 'list-finance-context') return success({ task_id: task.id, datasets: [source, budgetSource], contexts: [], account_maps: [], scenarios: [], metric_definitions: [], capabilities: ['metrics'] });
      if (command === 'finance-context-save') return success({ ...object, id: '4'.repeat(32), name: spec?.name, bindings: spec?.bindings, scopes: spec?.scopes, diagnostics: [] });
      if (command === 'run-metric') return success({ ...run, engine: 'finance', finance_context_id: '4'.repeat(32) });
      return success({});
    });
    mountBridge({ analysisState, financeCall });
    render(<Analysis {...props} embedded section="results" />);
    await screen.findByText('财务业务口径');
    fireEvent.click(screen.getByRole('button', { name: '保存并运行 P&L' }));
    await waitFor(() => expect(analysisState).toHaveBeenCalledTimes(2));
    fireEvent.click(screen.getByRole('tab', { name: /文稿/ }));
    await screen.findByRole('tabpanel', { name: /文稿/ });
    await act(async () => refreshGate.resolve(success({ ...initial, datasets: [source, budgetSource], runs: [{ ...run, engine: 'finance', finance_context_id: '4'.repeat(32) }] })));
    await waitFor(() => expect(screen.getByRole('tab', { name: /文稿/ }).getAttribute('aria-selected')).toBe('true'));
    expect(screen.getByRole('tab', { name: /分析结果/ }).getAttribute('aria-selected')).toBe('false');
  });

  it('keeps the user on drafts when a source refresh finishes after they leave datasets', async () => {
    const refreshGate = deferred<Answer<AnalysisState>>();
    let firstRead = true;
    const analysisState = vi.fn(async () => {
      if (firstRead) { firstRead = false; return success({ ...initial, task_id: task.id }); }
      return refreshGate.promise;
    });
    const financeSourceRefresh = vi.fn(async () => success({ dataset_id: '6'.repeat(32), effective_dataset_id: '6'.repeat(32) }));
    const financeCall = vi.fn(async (_taskId: string, command: string) => command === 'finance-source-list' ? success({ batches: [] }) : success({}));
    mountBridge({ analysisState, financeSourceRefresh, financeCall });
    render(<Analysis {...props} embedded section="results" />);
    fireEvent.click(await screen.findByRole('tab', { name: /资料/ }));
    await openSourceRefreshDetails();
    fireEvent.change(sourceRefreshField('账簿'), { target: { value: '经营总账' } });
    fireEvent.change(sourceRefreshField('组织'), { target: { value: '华东' } });
    fireEvent.change(sourceRefreshField('期间'), { target: { value: '2026-09' } });
    fireEvent.change(sourceRefreshField('截止时间'), { target: { value: '2026-09-30T23:59:59+08:00' } });
    fireEvent.click(screen.getByRole('button', { name: /选择文件并刷新/ }));
    await waitFor(() => expect(analysisState).toHaveBeenCalledTimes(2));
    fireEvent.click(screen.getByRole('tab', { name: /文稿/ }));
    await screen.findByRole('tabpanel', { name: /文稿/ });
    await act(async () => refreshGate.resolve(success({ ...initial, datasets: [{ ...source, id: '6'.repeat(32), name: '刷新后资料' }] })));
    await waitFor(() => expect(screen.getByRole('tab', { name: /文稿/ }).getAttribute('aria-selected')).toBe('true'));
    expect(screen.getByRole('tab', { name: /资料/ }).getAttribute('aria-selected')).toBe('false');
  });

  it('does not let a delayed source refresh from the previous task replace the current draft', async () => {
    const other = { ...task, id: '8'.repeat(32), title: '西南经营分析' };
    const refreshGate = deferred<Answer<AnalysisState>>();
    let firstRead = true;
    const otherState = { ...initial, task_id: other.id, datasets: [{ ...source, task_id: other.id, name: '西南资料' }],
      drafts: [{ ...draft, task_id: other.id, body: '西南原稿。' }] };
    const analysisState = vi.fn(async (id: string) => {
      if (id === other.id) return success(otherState);
      if (firstRead) { firstRead = false; return success({ ...initial, task_id: task.id }); }
      return refreshGate.promise;
    });
    const financeSourceRefresh = vi.fn(async () => success({ dataset_id: '6'.repeat(32), effective_dataset_id: '6'.repeat(32) }));
    const financeCall = vi.fn(async (_taskId: string, command: string) => command === 'finance-source-list' ? success({ batches: [] }) : success({}));
    mountBridge({ analysisState, financeSourceRefresh, financeCall });
    const { rerender } = render(<Analysis {...props} embedded section="results" tasks={[task, other]} />);
    fireEvent.click(await screen.findByRole('tab', { name: /资料/ }));
    await openSourceRefreshDetails();
    fireEvent.change(sourceRefreshField('账簿'), { target: { value: '经营总账' } });
    fireEvent.change(sourceRefreshField('组织'), { target: { value: '华东' } });
    fireEvent.change(sourceRefreshField('期间'), { target: { value: '2026-09' } });
    fireEvent.change(sourceRefreshField('截止时间'), { target: { value: '2026-09-30T23:59:59+08:00' } });
    fireEvent.click(screen.getByRole('button', { name: /选择文件并刷新/ }));
    await waitFor(() => expect(analysisState).toHaveBeenCalledTimes(2));
    rerender(<Analysis {...props} embedded section="drafts" task={other} tasks={[task, other]} />);
    await screen.findByText('西南原稿。');
    await act(async () => refreshGate.resolve(success({ ...initial, datasets: [{ ...source, id: '6'.repeat(32), name: '刷新后资料' }] })));
    await waitFor(() => expect(screen.getByRole('tab', { name: /文稿/ }).getAttribute('aria-selected')).toBe('true'));
    expect(screen.getByText('西南原稿。')).toBeTruthy();
    expect(screen.queryByText('刷新后资料')).toBeNull();
  });

  it('creates an isolated finance context from registered datasets and runs management P&L', async () => {
    const accountMap = { ...object, id: '9'.repeat(32), name: '标准管理科目映射' };
    const financeCall = vi.fn(async (_taskId: string, command: string, spec?: Record<string, unknown>) => {
      if (command === 'list-finance-context') return success({ task_id: task.id, datasets: [source, budgetSource], contexts: [], account_maps: [accountMap], scenarios: [], metric_definitions: [], capabilities: ['metrics'] });
      if (command === 'finance-context-save') return success({ ...object, id: '4'.repeat(32), name: spec?.name, bindings: spec?.bindings, scopes: spec?.scopes, diagnostics: [] });
      if (command === 'run-metric') return success({ ...run, engine: 'finance', finance_context_id: String(spec?.context_id) });
      return success({});
    });
    mountBridge({ analysisState: async () => success({ ...initial, datasets: [source, budgetSource] }), financeCall });
    render(<Analysis {...props} embedded section="results" />);
    await screen.findByText('财务业务口径');
    chooseSearchable('预算资料（可选）', /本月预算/);
    fireEvent.change(screen.getByLabelText('账簿'), { target: { value: '经营总账' } });
    fireEvent.change(screen.getByLabelText('组织'), { target: { value: '华东' } });
    fireEvent.change(screen.getByLabelText('期间'), { target: { value: '2026-08' } });
    fireEvent.click(screen.getByRole('button', { name: '对比期间设为实际期间上期' }));
    fireEvent.click(screen.getByText('管理科目映射'));
    // The mapping is edited as rows now: one line per account code, with the
    // management account picked rather than typed into a JSON array.
    expect((screen.getByLabelText('第 1 行科目代码') as HTMLInputElement).value).toBe('6001');
    expect((screen.getByLabelText('第 1 行管理科目') as HTMLSelectElement).value).toBe('revenue');
    expect((screen.getByLabelText('第 3 行管理科目') as HTMLSelectElement).value).toBe('expense');
    fireEvent.change(screen.getByLabelText('第 2 行科目代码'), { target: { value: '6402' } });
    expect((screen.getByLabelText('第 2 行科目代码') as HTMLInputElement).value).toBe('6402');
    fireEvent.click(screen.getByRole('button', { name: '已保存映射' }));
    fireEvent.mouseDown(await screen.findByRole('option', { name: /标准管理科目映射/ }));
    await waitFor(() => expect(screen.getByRole('button', { name: '已保存映射' }).textContent).toContain('标准管理科目映射'));
    expect(screen.getByText(/当前口径保存时会使用映射/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '保存并运行 P&L' }));
    await waitFor(() => expect(financeCall).toHaveBeenCalledWith(task.id, 'run-metric', { context_id: '4'.repeat(32), metric: { kind: 'management_pnl' } }));
    expect((screen.getByLabelText('财务分析设置') as HTMLDetailsElement).open).toBe(false);
    fireEvent.click(screen.getByText('财务业务口径'));
    expect((screen.getByLabelText('财务分析设置') as HTMLDetailsElement).open).toBe(true);
    expect(screen.getByText('情景测算').closest('details')?.open).toBe(false);
    expect(financeCall).toHaveBeenCalledWith(task.id, 'finance-context-save', expect.objectContaining({
      bindings: { actual: source.id, budget: budgetSource.id },
      account_map_id: accountMap.id,
      scopes: expect.objectContaining({
        actual: expect.objectContaining({ ledger: '经营总账', organization: '华东', period: '2026-08', scenario: 'actual' }),
        budget: expect.objectContaining({ ledger: '经营总账', organization: '华东', period: '2026-07', scenario: 'budget' }),
      }),
    }));
  });

  it('folds finance setup by default when an ordinary SQL result already succeeded', async () => {
    const sqlRun: AnalysisRun = { ...run, engine: 'sql' };
    mountBridge({ analysisState: async () => success({ ...initial, runs: [sqlRun] }),
      financeCall: async () => success({ task_id: task.id, datasets: [source], contexts: [], account_maps: [], scenarios: [], metric_definitions: [], capabilities: [] }) });
    render(<Analysis {...props} embedded section="results" />);
    await screen.findByText('财务业务口径');
    const setup = screen.getByLabelText('财务分析设置') as HTMLDetailsElement;
    expect(setup.open).toBe(false);
    fireEvent.click(screen.getByText('财务业务口径'));
    expect(setup.open).toBe(true);
  });

  it('puts the result above the finance settings once a result exists, and the settings first before any result', async () => {
    const financeCall = async () => success({ task_id: task.id, datasets: [source], contexts: [], account_maps: [], scenarios: [], metric_definitions: [], capabilities: [] });
    mountBridge({ analysisState: async () => success({ ...initial, runs: [{ ...run, engine: 'sql' }] }), financeCall });
    const { unmount } = render(<Analysis {...props} embedded section="results" />);
    await screen.findByText('财务业务口径');
    const result = document.querySelector('.analysis-result')!;
    expect(result.compareDocumentPosition(screen.getByLabelText('财务分析设置')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    unmount();
    mountBridge({ analysisState: async () => success({ ...initial, analyses: [], runs: [], drafts: [] }), financeCall });
    render(<Analysis {...props} embedded section="results" />);
    await screen.findByText('财务业务口径');
    const empty = screen.getByRole('heading', { name: '从资料到可检查的结果' });
    expect(screen.getByLabelText('财务分析设置').compareDocumentPosition(empty) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect((screen.getByLabelText('财务分析设置') as HTMLDetailsElement).open).toBe(true);
    expect(screen.getByLabelText('组织').closest('details')?.open).toBe(false);
  });

  it('says what is running while a finance run is pending and keeps the outcome readable after the settings fold', async () => {
    const context = { ...object, id: '4'.repeat(32), name: '八月经营口径', bindings: { actual: source.id },
      scopes: { actual: { ledger: '总账', organization: '华东', period: '2026-08', currency: 'CNY', unit: '元', scenario: 'actual' } } };
    const gate = deferred<Answer<Record<string, unknown>>>();
    const financeCall = vi.fn(async (_taskId: string, command: string) => {
      if (command === 'list-finance-context') return success({ task_id: task.id, datasets: [source], contexts: [context], account_maps: [], scenarios: [], metric_definitions: [], capabilities: ['metrics'] });
      if (command === 'run-metric') return gate.promise;
      if (command === 'finance-adjustment-list') return success({ adjustments: [] });
      if (command === 'chart-deliverable-list') return success({ charts: [] });
      return success({});
    });
    mountBridge({ analysisState: async () => success({ ...initial, analyses: [], runs: [], drafts: [] }), financeCall });
    render(<Analysis {...props} embedded section="results" />);
    const rerun = await screen.findByRole('button', { name: '用已保存口径重跑 P&L' });
    fireEvent.click(rerun);
    expect(await screen.findByText('正在运行管理口径损益…')).toBeTruthy();
    expect((rerun as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: '保存并运行 P&L' }) as HTMLButtonElement).disabled).toBe(true);
    // The workbench unmounts with its tab; the run it started does not stop.
    fireEvent.click(screen.getByRole('tab', { name: /^资料/ }));
    fireEvent.click(screen.getByRole('tab', { name: /^分析结果/ }));
    expect(await screen.findByText('正在运行管理口径损益…')).toBeTruthy();
    const again = await screen.findByRole('button', { name: '用已保存口径重跑 P&L' });
    expect((again as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(again);
    await act(async () => gate.resolve(success({ ...run, engine: 'finance', finance_context_id: context.id })));
    await waitFor(() => expect(screen.queryByText('正在运行管理口径损益…')).toBeNull());
    expect((screen.getByRole('button', { name: '用已保存口径重跑 P&L' }) as HTMLButtonElement).disabled).toBe(false);
    expect(financeCall.mock.calls.filter(([, command]) => command === 'run-metric')).toHaveLength(1);
  });

  it('keeps the run outcome readable after the settings fold on success', async () => {
    const context = { ...object, id: '4'.repeat(32), name: '八月经营口径', bindings: { actual: source.id },
      scopes: { actual: { ledger: '总账', organization: '华东', period: '2026-08', currency: 'CNY', unit: '元', scenario: 'actual' } } };
    const gate = deferred<Answer<Record<string, unknown>>>();
    const financeCall = vi.fn(async (_taskId: string, command: string) => {
      if (command === 'list-finance-context') return success({ task_id: task.id, datasets: [source], contexts: [context], account_maps: [], scenarios: [], metric_definitions: [], capabilities: ['metrics'] });
      if (command === 'run-metric') return gate.promise;
      if (command === 'finance-adjustment-list') return success({ adjustments: [] });
      if (command === 'chart-deliverable-list') return success({ charts: [] });
      return success({});
    });
    mountBridge({ analysisState: async () => success({ ...initial, analyses: [], runs: [], drafts: [] }), financeCall });
    render(<Analysis {...props} embedded section="results" />);
    fireEvent.click(await screen.findByRole('button', { name: '用已保存口径重跑 P&L' }));
    await screen.findByText('正在运行管理口径损益…');
    await act(async () => gate.resolve(success({ ...run, engine: 'finance', finance_context_id: context.id })));
    const outcome = await screen.findByText('已运行管理口径损益。');
    const setup = screen.getByLabelText('财务分析设置') as HTMLDetailsElement;
    expect(setup.open).toBe(false);
    expect(setup.contains(outcome)).toBe(false);
    expect(screen.queryByText('正在运行管理口径损益…')).toBeNull();
  });

  it('opens the folded finance settings from 调整口径 on the scope that result used, once', async () => {
    const scope = (period: string) => ({ ledger: '总账', organization: '华东', period, currency: 'CNY', unit: '元', scenario: 'actual' });
    const julyContext = { ...object, id: '5'.repeat(32), name: '七月经营口径', bindings: { actual: source.id }, scopes: { actual: scope('2026-07') } };
    const augustContext = { ...object, id: '6'.repeat(32), name: '八月经营口径', bindings: { actual: source.id }, scopes: { actual: scope('2026-08') } };
    const financeCall = vi.fn(async (_taskId: string, command: string) => {
      if (command === 'list-finance-context') return success({ task_id: task.id, datasets: [source], contexts: [julyContext, augustContext], account_maps: [], scenarios: [], metric_definitions: [], capabilities: ['metrics'] });
      if (command === 'finance-adjustment-list') return success({ adjustments: [] });
      if (command === 'chart-deliverable-list') return success({ charts: [] });
      if (command === 'run-metric') return success({ ...run, engine: 'finance' });
      return success({});
    });
    mountBridge({ analysisState: async () => success({ ...initial, runs: [{ ...run, engine: 'finance', finance_context_id: julyContext.id }] }), financeCall });
    render(<Analysis {...props} embedded section="results" />);
    await screen.findByText('财务业务口径');
    await waitFor(() => expect(financeCall).toHaveBeenCalledWith(task.id, 'list-finance-context'));
    const setup = screen.getByLabelText('财务分析设置') as HTMLDetailsElement;
    expect(setup.open).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: '调整口径' }));
    await waitFor(() => expect(setup.open).toBe(true));
    expect(document.activeElement).toBe(setup.querySelector('summary'));
    expect((screen.getByLabelText('期间') as HTMLInputElement).value).toBe('2026-07');
    fireEvent.click(screen.getByRole('button', { name: '用已保存口径重跑 P&L' }));
    await waitFor(() => expect(financeCall).toHaveBeenCalledWith(task.id, 'run-metric', expect.objectContaining({ context_id: julyContext.id })));
    // A remount with the request already counted must not open the settings again.
    fireEvent.click(screen.getByRole('tab', { name: /^文稿/ }));
    fireEvent.click(screen.getByRole('tab', { name: /^分析结果/ }));
    await screen.findByText('财务业务口径');
    expect((screen.getByLabelText('财务分析设置') as HTMLDetailsElement).open).toBe(false);
  });

  it('keeps a failed adjustment list visible while the panel is folded', async () => {
    const context = { ...object, id: '4'.repeat(32), name: '八月经营口径', bindings: { actual: source.id }, scopes: { actual: { period: '2026-08' } } };
    mountBridge({ analysisState: async () => success({ ...initial, runs: [{ ...run, engine: 'finance' }] }),
      financeCall: async (_taskId: string, command: string) => {
        if (command === 'list-finance-context') return success({ task_id: task.id, datasets: [source], contexts: [context], account_maps: [], scenarios: [], metric_definitions: [], capabilities: ['metrics'] });
        if (command === 'finance-adjustment-list') return { ok: false, message: '调整列表读取失败' } as Answer<never>;
        if (command === 'chart-deliverable-list') return success({ charts: [] });
        return success({});
      } });
    render(<Analysis {...props} embedded section="results" />);
    const panel = await screen.findByRole('complementary', { name: '考核调整' });
    const alert = await within(panel).findByRole('alert');
    expect(alert.textContent).toBe('调整列表读取失败');
    expect(panel.querySelector('details')?.open).toBe(false);
    expect(panel.querySelector('details')?.contains(alert)).toBe(false);
  });

  it('runs a newly saved budget bridge at organization-period grain without account slicing', async () => {
    const financeCall = vi.fn(async (_taskId: string, command: string, spec?: Record<string, unknown>) => {
      if (command === 'list-finance-context') return success({ task_id: task.id, datasets: [source, budgetSource], contexts: [], account_maps: [], scenarios: [], metric_definitions: [], capabilities: ['variance'] });
      if (command === 'finance-context-save') return success({ ...object, id: '4'.repeat(32), name: spec?.name, bindings: spec?.bindings, scopes: spec?.scopes, diagnostics: [] });
      if (command === 'explain-variance') return success({ ...run, engine: 'finance', finance_context_id: String(spec?.context_id) });
      return success({});
    });
    mountBridge({ analysisState: async () => success({ ...initial, datasets: [source, budgetSource] }), financeCall });
    render(<Analysis {...props} embedded section="results" />);
    await screen.findByText('财务业务口径');
    chooseSearchable('预算资料（可选）', /本月预算/);
    fireEvent.change(screen.getByLabelText('组织'), { target: { value: '华东' } });
    fireEvent.change(screen.getByLabelText('期间'), { target: { value: '2026-09' } });
    fireEvent.click(screen.getByRole('button', { name: '运行预算桥' }));
    await waitFor(() => expect(financeCall).toHaveBeenCalledWith(task.id, 'explain-variance', expect.objectContaining({
      context_id: '4'.repeat(32), actual_scenario: 'actual', baseline_scenario: 'budget',
      dimensions: ['organization', 'period'],
    })));
    expect((screen.getByLabelText('财务分析设置') as HTMLDetailsElement).open).toBe(false);
  });

  it('surfaces finance diagnostics, incomplete scope and source-row drilldown errors', async () => {
    const financeRun: AnalysisRun = { ...run, engine: 'finance', finance_context_id: '4'.repeat(32), completeness: 'incomplete',
      finance_scope: { actual: { ledger: '经营总账', organization: '华东', period: '2026-08', currency: 'CNY', unit: '元', scenario: 'actual' } },
      result: { columns: [{ name: 'management_account', type: 'VARCHAR' }, { name: 'profit', type: 'DECIMAL' }],
        rows: [{ management_account: '经营利润', profit: '100.00', source_rows: [{ dataset_id: source.id, row_index: 1 }] }],
        row_count: 1, truncated: false, diagnostics: [{ severity: 'error', code: 'control_total_missing', message: '控制数未提供' }] } };
    const financeCall = vi.fn(async (_taskId: string, command: string) => command === 'list-finance-context'
      ? success({ task_id: task.id, datasets: [source], contexts: [], account_maps: [], scenarios: [], metric_definitions: [], capabilities: ['drilldown'] })
      : ({ ok: false as const, refused: true, message: 'source evidence row is invalid' }));
    mountBridge({ analysisState: async () => success({ ...initial, runs: [financeRun] }), financeCall });
    render(<Analysis {...props} embedded section="results" />);
    await screen.findByText('范围尚未完成：存在需要处理的诊断。');
    fireEvent.click(screen.getByText('诊断 · 1 项'));
    expect(screen.getByText(/control_total_missing/)).toBeTruthy();
    await waitFor(() => expect(Array.from((screen.getByLabelText('结果行来源') as HTMLSelectElement).options).map((option) => option.value)).toContain('0'));
    fireEvent.change(screen.getByLabelText('结果行来源'), { target: { value: '0' } });
    await waitFor(() => expect((screen.getByLabelText('结果行来源') as HTMLSelectElement).value).toBe('0'));
    const drilldown = screen.getByRole('button', { name: '查看来源行' }) as HTMLButtonElement;
    await waitFor(() => expect(drilldown.disabled).toBe(false));
    fireEvent.click(drilldown);
    await waitFor(() => expect(financeCall).toHaveBeenCalledWith(task.id, 'drilldown-fact', { run_id: financeRun.id, row: 0, offset: 0, limit: 100 }));
    expect((await screen.findByRole('alert')).textContent).toBe('source evidence row is invalid');
  });

  it('shows a manager-first finance budget bridge while keeping raw result fields expandable', async () => {
    const bridgeResult = { method: 'revenue_minus_cost_minus_expense', comparison: { actual_scenario: 'actual', baseline_scenario: 'budget' }, columns: [
        { name: 'ledger', type: 'VARCHAR' }, { name: 'organization', type: 'VARCHAR' }, { name: 'currency', type: 'VARCHAR' },
        { name: 'unit', type: 'VARCHAR' }, { name: 'period', type: 'VARCHAR' }, { name: 'metric', type: 'VARCHAR' },
        { name: 'actual', type: 'DECIMAL' }, { name: 'baseline', type: 'DECIMAL' }, { name: 'amount_change', type: 'DECIMAL' },
        { name: 'profit_impact', type: 'DECIMAL' }, { name: 'contribution', type: 'DECIMAL' }, { name: 'ratio', type: 'DECIMAL' },
        { name: 'ratio_status', type: 'VARCHAR' }, { name: 'favorability', type: 'VARCHAR' },
        { name: 'comparison_status', type: 'VARCHAR' },
      ], rows: [
        { ledger: 'L1', organization: '华东', currency: 'CNY', unit: '万元', period: '2026-09', metric: 'revenue', actual: '120', baseline: '100', amount_change: '20', profit_impact: '20', contribution: '20', ratio: '0.2', ratio_status: 'absolute_baseline', favorability: 'favorable', comparison_status: 'complete' },
        { ledger: 'L1', organization: '华东', currency: 'CNY', unit: '万元', period: '2026-09', metric: 'cost', actual: '70', baseline: '60', amount_change: '10', profit_impact: '-10', contribution: '-10', ratio: '0.166666666666666666666666', ratio_status: 'absolute_baseline', favorability: 'unfavorable', comparison_status: 'complete' },
        { ledger: 'L1', organization: '华东', currency: 'CNY', unit: '万元', period: '2026-09', metric: 'expense', actual: '20', baseline: '15', amount_change: '5', profit_impact: '-5', contribution: '-5', ratio: '0.333333333333333333333333', ratio_status: 'absolute_baseline', favorability: 'unfavorable', comparison_status: 'complete' },
        { ledger: 'L1', organization: '华东', currency: 'CNY', unit: '万元', period: '2026-09', metric: 'profit', actual: '30', baseline: '25', amount_change: '5', profit_impact: '5', contribution: '5', ratio: '0.2', ratio_status: 'absolute_baseline', favorability: 'favorable', comparison_status: 'complete', source_rows: [{ dataset_id: source.id, row_index: 1 }] },
      ], row_count: 4, truncated: false } as AnalysisRun['result'] & { method: string };
    const bridgeRun: AnalysisRun = { ...run, engine: 'finance', finance_context_id: '4'.repeat(32), completeness: 'not_reconciled', result: bridgeResult };
    mountBridge({ analysisState: async () => success({ ...initial, runs: [bridgeRun] }),
      financeCall: async () => success({ task_id: task.id, datasets: [source], contexts: [], account_maps: [], scenarios: [], metric_definitions: [], capabilities: ['variance'] }) });
    render(<Analysis {...props} embedded section="results" />);
    const bridge = await screen.findByRole('region', { name: '预算差异桥' });
    expect(within(bridge).getByRole('columnheader', { name: '科目' })).toBeTruthy();
    expect(within(bridge).getByRole('columnheader', { name: '科目增减' })).toBeTruthy();
    expect(within(bridge).getByRole('columnheader', { name: '差异贡献' })).toBeTruthy();
    expect(within(bridge).queryByRole('columnheader', { name: 'amount_change' })).toBeNull();
    expect(within(bridge).queryByRole('columnheader', { name: 'profit_impact' })).toBeNull();
    expect(screen.getByText('范围：账簿 L1 · 组织 华东 · 币种 CNY · 单位 万元 · 期间 2026-09')).toBeTruthy();
    expect(within(bridge).getByRole('cell', { name: '利润' })).toBeTruthy();
    expect(within(bridge).getByRole('cell', { name: '33.33%' })).toBeTruthy();
    const costRow = within(bridge).getAllByRole('row').find((rowElement) => (rowElement.textContent ?? '').includes('成本'));
    expect(costRow?.textContent).toContain('10');
    expect(costRow?.textContent).toContain('-10');
    const raw = screen.getByText('原始结果字段 · 15 列').closest('details') as HTMLDetailsElement;
    expect(raw.open).toBe(false);
    fireEvent.click(screen.getByText('原始结果字段 · 15 列'));
    const rawTable = await screen.findByRole('region', { name: '原始计算结果' });
    expect(within(rawTable).getByRole('columnheader', { name: 'amount_change' })).toBeTruthy();
    expect(within(rawTable).getByRole('columnheader', { name: 'profit_impact' })).toBeTruthy();
  });

  it('keeps varying finance dimensions as columns and preserves row order in the manager bridge view', async () => {
    const bridgeResult = { method: 'revenue_minus_cost_minus_expense', comparison: { actual_scenario: 'actual', baseline_scenario: 'budget' }, columns: [
        { name: 'ledger', type: 'VARCHAR' }, { name: 'organization', type: 'VARCHAR' }, { name: 'currency', type: 'VARCHAR' },
        { name: 'unit', type: 'VARCHAR' }, { name: 'period', type: 'VARCHAR' }, { name: 'metric', type: 'VARCHAR' },
        { name: 'actual', type: 'DECIMAL' }, { name: 'baseline', type: 'DECIMAL' }, { name: 'contribution', type: 'DECIMAL' },
        { name: 'ratio', type: 'DECIMAL' },
      ], rows: [
        { ledger: 'L1', organization: '华东', currency: 'CNY', unit: '万元', period: '2026-09', metric: 'profit', actual: '130', baseline: '100', contribution: '30', ratio: '0.3' },
        { ledger: 'L1', organization: '华南', currency: 'CNY', unit: '万元', period: '2026-10', metric: 'profit', actual: '80', baseline: '100', contribution: '-20', ratio: '-0.2' },
      ], row_count: 2, truncated: false } as AnalysisRun['result'] & { method: string; comparison: { actual_scenario: string; baseline_scenario: string } };
    const bridgeRun: AnalysisRun = { ...run, engine: 'finance', result: bridgeResult };
    mountBridge({ analysisState: async () => success({ ...initial, runs: [bridgeRun] }),
      financeCall: async () => success({ task_id: task.id, datasets: [source], contexts: [], account_maps: [], scenarios: [], metric_definitions: [], capabilities: ['variance'] }) });
    render(<Analysis {...props} embedded section="results" />);
    const bridge = await screen.findByRole('region', { name: '预算差异桥' });
    expect(within(bridge).getByRole('columnheader', { name: '组织' })).toBeTruthy();
    expect(within(bridge).getByRole('columnheader', { name: '期间' })).toBeTruthy();
    expect(screen.getByText('范围：账簿 L1 · 币种 CNY · 单位 万元')).toBeTruthy();
    expect(screen.queryByText(/组织 2 项|期间 2 项/)).toBeNull();
    const rows = within(bridge).getAllByRole('row').map((rowElement) => rowElement.textContent ?? '');
    expect(rows[1]).toContain('华东');
    expect(rows[1]).toContain('2026-09');
    expect(rows[2]).toContain('华南');
    expect(rows[2]).toContain('2026-10');
  });

  it('shows explicit units for very large finance variance ratios', async () => {
    const bridgeResult = { method: 'revenue_minus_cost_minus_expense', comparison: { actual_scenario: 'actual', baseline_scenario: 'budget' }, columns: [
        { name: 'period', type: 'VARCHAR' }, { name: 'metric', type: 'VARCHAR' }, { name: 'actual', type: 'DECIMAL' },
        { name: 'baseline', type: 'DECIMAL' }, { name: 'contribution', type: 'DECIMAL' }, { name: 'ratio', type: 'DECIMAL' },
      ], rows: [{ period: '2026-09', metric: 'profit', actual: '1000000', baseline: '1', contribution: '999999', ratio: '1000000.1234567890123456789' }],
      row_count: 1, truncated: false } as AnalysisRun['result'] & { method: string; comparison: { actual_scenario: string; baseline_scenario: string } };
    const bridgeRun: AnalysisRun = { ...run, engine: 'finance', result: bridgeResult };
    mountBridge({ analysisState: async () => success({ ...initial, runs: [bridgeRun] }),
      financeCall: async () => success({ task_id: task.id, datasets: [source], contexts: [], account_maps: [], scenarios: [], metric_definitions: [], capabilities: ['variance'] }) });
    render(<Analysis {...props} embedded section="results" />);
    const bridge = await screen.findByRole('region', { name: '预算差异桥' });
    expect(within(bridge).getByRole('cell', { name: '1000000.1234567890123456789 倍' })).toBeTruthy();
  });

  it('uses comparison-aware finance bridge copy for non-budget scenarios', async () => {
    const bridgeResult = { method: 'revenue_minus_cost_minus_expense', comparison: { actual_scenario: 'actual_2026', baseline_scenario: 'actual_2025' }, columns: [
        { name: 'period', type: 'VARCHAR' }, { name: 'metric', type: 'VARCHAR' }, { name: 'actual', type: 'DECIMAL' },
        { name: 'baseline', type: 'DECIMAL' }, { name: 'contribution', type: 'DECIMAL' }, { name: 'ratio', type: 'DECIMAL' },
      ], rows: [{ period: '2026-09', metric: 'profit', actual: '120', baseline: '100', contribution: '20', ratio: '0.2' }],
      row_count: 1, truncated: false } as AnalysisRun['result'] & { method: string; comparison: { actual_scenario: string; baseline_scenario: string } };
    const bridgeRun: AnalysisRun = { ...run, engine: 'finance', result: bridgeResult };
    mountBridge({ analysisState: async () => success({ ...initial, runs: [bridgeRun] }),
      financeCall: async () => success({ task_id: task.id, datasets: [source], contexts: [], account_maps: [], scenarios: [], metric_definitions: [], capabilities: ['variance'] }) });
    render(<Analysis {...props} embedded section="results" />);
    expect(await screen.findByRole('region', { name: '对照损益差异桥' })).toBeTruthy();
    expect(screen.queryByRole('region', { name: '预算差异桥' })).toBeNull();
    const bridge = screen.getByRole('region', { name: '对照损益差异桥' });
    expect(within(bridge).getByRole('columnheader', { name: 'actual_2026' })).toBeTruthy();
    expect(within(bridge).getByRole('columnheader', { name: '对照（actual_2025）' })).toBeTruthy();
  });

  it('passes edited materiality to preparation, recheck, and finance draft save', async () => {
    const financeRun: AnalysisRun = { ...run, engine: 'finance', finance_scope: { actual: { currency: 'CNY', unit: '元' } } };
    const financeDraft: AnalysisDraft = { ...draft, run_ids: [financeRun.id], materiality: {
      absolute: '5000', relative: { threshold: '0.2', denominator: 'actual_abs', negative_policy: 'signed' },
    } };
    const financeCall = vi.fn(async (_taskId: string, command: string, spec?: Record<string, unknown>) => {
      if (command === 'prepare-explanation') return success({ facts: [{ id: 'fact-profit', run_id: financeRun.id, row: 0, column: 'profit', label: '利润', display_value: '10000' }] });
      if (command === 'validate-explanation') return success({ status: 'pass', issues: [], coverage: { required: 1, cited: 1 } });
      if (command === 'finance-background-list') return success({ backgrounds: [] });
      if (command === 'save-explanation-draft') return success({ ...financeDraft, ...spec, id: '9'.repeat(32) });
      return success({});
    });
    mountBridge({ analysisState: async () => success({ ...initial, runs: [financeRun], drafts: [financeDraft] }), financeCall });
    render(<Analysis {...props} embedded section="drafts" />);
    expect(await screen.findByText(/检查通过/)).toBeTruthy();
    fireEvent.click(screen.getByRole('tab', { name: /^编辑$/ }));

    fireEvent.change(screen.getByLabelText('重要性绝对金额'), { target: { value: '12000.50' } });
    expect(screen.getByText(/按运行结果原币原单位判断：CNY\/元/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText('相对重要性阈值'), { target: { value: '0.1' } });
    chooseSearchable('相对分母', /按较大金额/);
    chooseSearchable('负数比较规则', /按绝对值比较/);

    expect(screen.getByText(/待重检/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '重检当前正文' }));
    await waitFor(() => expect(financeCall).toHaveBeenCalledWith(task.id, 'prepare-explanation', expect.objectContaining({
      materiality: { absolute: '12000.50', relative: { threshold: '0.1', denominator: 'max_abs', negative_policy: 'absolute' } },
    })));
    await waitFor(() => expect(financeCall).toHaveBeenCalledWith(task.id, 'validate-explanation', expect.objectContaining({
      materiality: { absolute: '12000.50', relative: { threshold: '0.1', denominator: 'max_abs', negative_policy: 'absolute' } },
    })));
    fireEvent.click(screen.getByRole('button', { name: '保存文稿新版' }));
    await waitFor(() => expect(financeCall).toHaveBeenCalledWith(task.id, 'save-explanation-draft', expect.objectContaining({
      materiality: { absolute: '12000.50', relative: { threshold: '0.1', denominator: 'max_abs', negative_policy: 'absolute' } },
    })));
  });

  it('keeps unsaved materiality edits when switching away from the draft tab', async () => {
    const financeRun: AnalysisRun = { ...run, engine: 'finance', finance_scope: { actual: { currency: 'CNY', unit: '元' }, budget: { currency: 'JPY', unit: '千元' } } };
    const financeDraft: AnalysisDraft = { ...draft, run_ids: [financeRun.id], materiality: { absolute: '5000' } };
    const financeCall = vi.fn(async (_taskId: string, command: string) => {
      if (command === 'prepare-explanation') return success({ facts: [] });
      if (command === 'validate-explanation') return success({ status: 'pass', issues: [] });
      if (command === 'finance-background-list') return success({ backgrounds: [] });
      return success({});
    });
    mountBridge({ analysisState: async () => success({ ...initial, runs: [financeRun], drafts: [financeDraft] }), financeCall });
    render(<Analysis {...props} embedded section="drafts" />);
    expect(await screen.findByText(/检查通过/)).toBeTruthy();
    fireEvent.click(screen.getByRole('tab', { name: /^编辑$/ }));
    fireEvent.change(screen.getByLabelText('重要性绝对金额'), { target: { value: '12345' } });
    fireEvent.click(screen.getByRole('tab', { name: /分析结果/ }));
    fireEvent.click(screen.getByRole('tab', { name: /文稿/ }));

    expect((await screen.findByLabelText('重要性绝对金额') as HTMLInputElement).value).toBe('12,345');
    expect(screen.getByText(/CNY\/元；JPY\/千元/)).toBeTruthy();
    expect(screen.getByText(/待重检/)).toBeTruthy();
  });

  it('saves manager edits on finance drafts through the finance draft command', async () => {
    const financeRun = { ...run, engine: 'finance' };
    const financeCall = vi.fn(async (_taskId: string, command: string, spec?: Record<string, unknown>) => command === 'list-finance-context'
      ? success({ task_id: task.id, datasets: [source], contexts: [], account_maps: [], scenarios: [], metric_definitions: [], capabilities: ['drafts'] })
      : success({ ...draft, ...spec, id: '4'.repeat(32), review_status: spec?.review_status ?? 'unreviewed' }));
    mountBridge({ analysisState: async () => success({ ...initial, runs: [financeRun], drafts: [{ ...draft, run_ids: [financeRun.id] }] }), financeCall });
    render(<Analysis {...props} embedded section="drafts" />); await screen.findByText('文稿');
    fireEvent.click(screen.getByRole('tab', { name: /^编辑$/ }));
    fireEvent.change(screen.getByLabelText('文稿正文'), { target: { value: '经理调整后的判断。' } });
    fireEvent.click(screen.getByRole('button', { name: '保存文稿新版' }));
    await waitFor(() => expect(financeCall).toHaveBeenCalledWith(task.id, 'save-explanation-draft', expect.objectContaining({
      parent_id: draft.id, body: '经理调整后的判断。', run_ids: [financeRun.id], review_status: 'unreviewed',
    })));
  });

  it.each([true, false])('loads completion recovery into an editable, recheckable copy (existing draft: %s)', async (hasDraft) => {
    const financeRun = { ...run, id: 'r-recovered', engine: 'finance', result: { ...run.result!, rows: [{ profit: '88' }] } };
    const oldClaims = [{ basis: 'calculation', run_id: run.id, row: 0, column: 'profit', value: '900719925474099.99' }];
    const recoveryClaims = [{ basis: 'calculation', run_id: financeRun.id, row: 0, column: 'profit', value: '88' }];
    const recovery = {
      operation_id: 'op-1',
      status: 'repair_available',
      revision: 2,
      title: '恢复的经营说明',
      body: '恢复正文 {{fact:fact-recovered}}。',
      limitations: ['等待销售确认'],
      run_ids: [financeRun.id],
      fact_ids: ['fact-recovered'],
      claims: [{ ...recoveryClaims[0], value: '99' }],
      materiality: { absolute: '9000' },
      requirements_id: 'req-recovered',
      parent_id: null,
      validation_error: { code: 'claim_value_mismatch', message: 'claim value differs', details: [{ run_id: financeRun.id, row: 0, column: 'profit', expected: '99', actual: '88' }] },
      updated_at: '2026-09-06T10:00:00Z',
    };
    const financeCall = vi.fn(async (_taskId: string, command: string, spec?: Record<string, unknown>) => {
      if (command === 'finance-completion-recoveries') return success({ recoveries: [
        recovery,
        { operation_id: 'op-empty', status: 'failed', body: '' },
        { operation_id: 'op-running', status: 'running', body: '仍在运行' },
      ] });
      if (command === 'prepare-explanation') return success({ facts: [{ id: 'fact-recovered', run_id: financeRun.id, row: 0, column: 'profit', label: '恢复利润', display_value: '88' }] });
      if (command === 'validate-explanation') return success({ status: 'pass', issues: [] });
      if (command === 'finance-background-list') return success({ backgrounds: [] });
      if (command === 'finance-completion-recover') return success({ ...draft, ...(spec?.draft as Record<string, unknown>), id: '9'.repeat(32) });
      return success({});
    });
    mountBridge({ analysisState: async () => success({ ...initial, runs: [run, financeRun], drafts: hasDraft ? [{ ...draft, fact_ids: ['fact-old'], claims: oldClaims, run_ids: [run.id] }] : [] }), financeCall });
    render(<Analysis {...props} embedded section="drafts" />);
    await screen.findByText('可恢复的未保存文稿 · 1 条');
    expect(screen.getByText(/可修复/)).toBeTruthy();
    expect(screen.getByText(/填报 99，结果 88/)).toBeTruthy();
    fireEvent.click(screen.getByText('可恢复的未保存文稿 · 1 条'));
    fireEvent.click(screen.getByRole('button', { name: '载入可编辑副本' }));
    expect((await screen.findByLabelText('文稿正文') as HTMLTextAreaElement).value).toBe('恢复正文 {{fact:fact-recovered}}。');
    expect(screen.getByText(/已载入未保存恢复稿/)).toBeTruthy();
    expect(screen.getByText(/待重检/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '采用引用 1 的结果值' }));
    fireEvent.change(screen.getByLabelText('重要性绝对金额'), { target: { value: '12000' } });
    fireEvent.click(screen.getByRole('button', { name: '重检当前正文' }));
    await waitFor(() => expect(financeCall).toHaveBeenCalledWith(task.id, 'prepare-explanation', expect.objectContaining({
      run_ids: [financeRun.id],
      materiality: { absolute: '12000' },
    })));
    await waitFor(() => expect(financeCall).toHaveBeenCalledWith(task.id, 'validate-explanation', expect.objectContaining({
      body: '恢复正文 {{fact:fact-recovered}}。',
      run_ids: [financeRun.id],
      fact_ids: ['fact-recovered'],
      claims: recoveryClaims,
      materiality: { absolute: '12000' },
    })));
    fireEvent.click(screen.getByRole('button', { name: '保存文稿新版' }));
    await waitFor(() => expect(financeCall).toHaveBeenCalledWith(task.id, 'finance-completion-recover', expect.objectContaining({
      operation_id: 'op-1', revision: 2, draft: expect.objectContaining({
      title: '恢复的经营说明',
      body: '恢复正文 {{fact:fact-recovered}}。',
      run_ids: [financeRun.id],
      fact_ids: ['fact-recovered'],
      claims: recoveryClaims,
      materiality: { absolute: '12000' },
      requirements_id: 'req-recovered',
      review_status: 'unreviewed',
    }) })));
    const recoverySave = financeCall.mock.calls.find(([, command]) => command === 'finance-completion-recover')?.[2]?.draft as Record<string, unknown>;
    expect(recoverySave).not.toHaveProperty('parent_id');
    expect(recoverySave.fact_ids).not.toContain('fact-old');
    expect(recoverySave.claims).not.toEqual(oldClaims);
  });

  it('does not overwrite current unsaved draft input with completion recoveries', async () => {
    const financeRun = { ...run, engine: 'finance' };
    const financeCall = vi.fn(async (_taskId: string, command: string) => {
      if (command === 'finance-completion-recoveries') return success({ recoveries: [{ operation_id: 'op-1', status: 'awaiting_input', title: '恢复稿', body: '恢复正文' }] });
      if (command === 'prepare-explanation') return success({ facts: [] });
      if (command === 'validate-explanation') return success({ status: 'pass', issues: [] });
      if (command === 'finance-background-list') return success({ backgrounds: [] });
      return success({});
    });
    mountBridge({ analysisState: async () => success({ ...initial, runs: [financeRun], drafts: [{ ...draft, run_ids: [financeRun.id] }] }), financeCall });
    render(<Analysis {...props} embedded section="drafts" />);
    await screen.findByText('可恢复的未保存文稿 · 1 条');
    fireEvent.click(screen.getByRole('tab', { name: /^编辑$/ }));
    fireEvent.change(screen.getByLabelText('文稿正文'), { target: { value: '当前经理正在编辑。' } });
    fireEvent.click(screen.getByText('可恢复的未保存文稿 · 1 条'));
    expect((screen.getByRole('button', { name: '载入可编辑副本' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByLabelText('文稿正文') as HTMLTextAreaElement).value).toBe('当前经理正在编辑。');
  });

  it('keeps restored local draft edits stale instead of validating the saved old body on remount', async () => {
    const financeRun = { ...run, engine: 'finance' };
    sessionStorage.setItem(`foundry.analysis.working-copy.v1:${task.id}:draft:${draft.id}`, JSON.stringify({
      title: draft.title,
      body: '本地恢复的未保存正文。',
      limitations: draft.limitations.join('\n'),
      review: draft.review_status,
      materiality: { absolute: '0', denominator: 'baseline_abs', negativePolicy: 'absolute', relative: '' },
    }));
    const financeCall = vi.fn(async (_taskId: string, command: string) => {
      if (command === 'finance-completion-recoveries') return success({ recoveries: [] });
      if (command === 'prepare-explanation') return success({ facts: [] });
      if (command === 'validate-explanation') return success({ status: 'pass', issues: [] });
      if (command === 'finance-background-list') return success({ backgrounds: [] });
      return success({});
    });
    mountBridge({ analysisState: async () => success({ ...initial, runs: [financeRun], drafts: [{ ...draft, run_ids: [financeRun.id] }] }), financeCall });
    render(<Analysis {...props} embedded section="drafts" />);
    expect((await screen.findByLabelText('文稿正文') as HTMLTextAreaElement).value).toBe('本地恢复的未保存正文。');
    expect(screen.getByText(/待重检/)).toBeTruthy();
    expect(screen.queryByText(/检查通过/)).toBeNull();
    expect(financeCall.mock.calls.some(([, command]) => command === 'validate-explanation')).toBe(false);
  });

  it('auto-checks finance drafts, marks edits stale, rechecks current body, and still saves quality warnings', async () => {
    const financeRun: AnalysisRun = { ...run, engine: 'finance', finance_context_id: 'ctx-a',
      finance_scope: { actual: { ledger: '总账', organization: '华东', period: '2026-09', currency: 'CNY', unit: '元' } } };
    const checkedDraft: AnalysisDraft = { ...draft, run_ids: [financeRun.id], quality: { status: 'passed', issues: [] } };
    const financeCall = vi.fn(async (_taskId: string, command: string, spec?: Record<string, unknown>) => {
      if (command === 'prepare-explanation') return success({ facts: [{ id: 'fact-profit', run_id: financeRun.id, row: 0, column: 'profit', label: '经营利润', display_value: '900719925474099.99', unit: '元', scope: { organization: '华东', period: '2026-09' } }], required_fact_ids: ['fact-profit'], business_contexts: [] });
      if (command === 'validate-explanation' && spec?.draft_id && !spec?.body) return success({ status: 'pass', issues: [], coverage: { required: 1, cited: 1 },
        checks: { numbers: { status: 'pass' }, coverage: { status: 'pass' }, provenance: { status: 'not_assessed' } } });
      if (command === 'validate-explanation') return success({ status: 'issues', issues: [{ severity: 'error', code: 'number_mismatch', message: '正文数字与引用事实不一致' }], coverage: { required: 1, cited: 0 } });
      if (command === 'drilldown-fact') return success({ run_id: financeRun.id, row: 0, rows: [
        { source: { dataset_id: source.id, row_index: 1 }, source_hash: source.source_hash, data: { customer: 'A客户', profit: '900719925474099.99' }, voucher_detail_available: true },
      ], total: 2, offset: 0, has_more: false, message: '已定位到利润来源行' });
      if (command === 'finance-background-list') return success({ backgrounds: [] });
      if (command === 'save-explanation-draft') return success({ ...checkedDraft, ...spec, id: '7'.repeat(32) });
      return success({});
    });
    mountBridge({ analysisState: async () => success({ ...initial, runs: [financeRun], drafts: [checkedDraft] }), financeCall });
    render(<Analysis {...props} embedded section="drafts" />);
    expect(await screen.findByText(/检查通过/)).toBeTruthy();
    expect(screen.getByText('数字与口径')).toBeTruthy();
    expect(screen.getByText('来源追溯')).toBeTruthy();
    expect(screen.getByText('尚未核对')).toBeTruthy();
    fireEvent.click(screen.getByText('可引用事实 · 1 条'));
    expect(screen.getByText(/经营利润 · 900719925474099.99 · 元/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '下钻此事实来源' }));
    expect(await screen.findByText(/已定位到利润来源行 · 2 行/)).toBeTruthy();
    expect(await screen.findByRole('region', { name: '事实来源行' })).toBeTruthy();
    expect(screen.getByRole('cell', { name: 'A客户' })).toBeTruthy();
    fireEvent.click(screen.getByRole('tab', { name: /^编辑$/ }));
    fireEvent.change(screen.getByLabelText('文稿正文'), { target: { value: '利润为 1 元，需要复核。' } });
    expect(screen.getByText(/待重检/)).toBeTruthy();
    expect(screen.queryByText(/检查通过/)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '重检当前正文' }));
    expect(await screen.findByText(/正文数字与引用事实不一致/, { selector: 'summary' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '保存文稿新版' }));
    await waitFor(() => expect(financeCall).toHaveBeenCalledWith(task.id, 'save-explanation-draft', expect.objectContaining({
      body: '利润为 1 元，需要复核。', review_status: 'unreviewed',
    })));
    const saveCall = financeCall.mock.calls.find(([, command]) => command === 'save-explanation-draft');
    expect(saveCall?.[2]).not.toHaveProperty('fact_ids');
  });

  it('keeps draft requirements collapsed until the manager expands them', async () => {
    const financeRun: AnalysisRun = { ...run, engine: 'finance', finance_context_id: 'ctx-a' };
    const currentRequirements = {
      id: 'req-current',
      question: '解释收入和利润缺口',
      scope: { organization: '华宸物业', period: '2026-08', currency: 'CNY', unit: '万元' },
      bindings: {},
      items: [{ id: 'req_1', metric: 'profit', label: '利润', dimensions: {}, requires_drilldown: false }],
    };
    const financeCall = vi.fn(async (_taskId: string, command: string) => {
      if (command === 'analysis-requirements-list') return success({ requirements: [currentRequirements], current: currentRequirements });
      if (command === 'finance-completion-recoveries') return success({ recoveries: [] });
      if (command === 'prepare-explanation') return success({ facts: [] });
      if (command === 'validate-explanation') return success({ status: 'pass', issues: [] });
      if (command === 'finance-background-list') return success({ backgrounds: [] });
      return success({});
    });
    mountBridge({ analysisState: async () => success({ ...initial, runs: [financeRun], drafts: [{ ...draft, run_ids: [financeRun.id], requirements_id: 'req-current' }] }), financeCall });
    render(<Analysis {...props} embedded section="drafts" />);
    const summary = await screen.findByText('本次分析要求', { selector: 'summary' });
    const details = summary.closest('details') as HTMLDetailsElement;
    expect(details.open).toBe(false);
    fireEvent.click(summary);
    expect(details.open).toBe(true);
    expect(await screen.findByLabelText('用户问题')).toBeTruthy();
    expect((screen.getByLabelText('用户问题') as HTMLTextAreaElement).value).toBe('解释收入和利润缺口');
  });

  it('names only the open checks in one line and keeps all seven statuses folded below', async () => {
    const financeRun: AnalysisRun = { ...run, engine: 'finance' };
    const financeCall = vi.fn(async (_taskId: string, command: string) => {
      if (command === 'finance-completion-recoveries') return success({ recoveries: [] });
      if (command === 'prepare-explanation') return success({ facts: [] });
      if (command === 'validate-explanation') return success({ status: 'needs_attention', issues: [],
        checks: { numbers: { status: 'pass' }, coverage: { status: 'needs_attention' }, provenance: { status: 'pass' } },
        status_dimensions: { execution: { status: 'pass' }, numeric_citation: { status: 'pass' }, source_validation: { status: 'not_configured' }, professional_review: { status: 'unreviewed' } },
      });
      return success({});
    });
    mountBridge({ analysisState: async () => success({ ...initial, runs: [financeRun], drafts: [{ ...draft, run_ids: [financeRun.id] }] }), financeCall });
    render(<Analysis {...props} embedded section="drafts" />);
    const summary = await screen.findByLabelText('待处理核对');
    expect(summary.textContent).toBe('待处理：问题覆盖仍有缺口 · 尚未独立核验 · 待专业复核');
    const checks = screen.getByLabelText('分项核对状态');
    const dimensions = screen.getByLabelText('四项独立核验状态');
    expect(checks.closest('details')).toBe(dimensions.closest('details'));
    expect(checks.closest('details')?.open).toBe(false);
    expect(within(checks).getByText('仍有缺口')).toBeTruthy();
    expect(within(dimensions).getByText('待专业复核')).toBeTruthy();
    expect(screen.getAllByLabelText('四项独立核验状态')).toHaveLength(1);
  });

  it('shows paragraph advice separately from passed financial checks and clears it after edits', async () => {
    const financeRun: AnalysisRun = { ...run, engine: 'finance' };
    const financeCall = vi.fn(async (_taskId: string, command: string) => {
      if (command === 'finance-completion-recoveries') return success({ recoveries: [] });
      if (command === 'prepare-explanation') return success({ facts: [] });
      if (command === 'validate-explanation') return success({ status: 'pass', issues: [],
        checks: { numbers: { status: 'pass' }, coverage: { status: 'pass' }, provenance: { status: 'pass' } },
        readability: { status: 'suggestions', issues: [{ code: 'dense_paragraph', message: '这一段包含多个主题，建议分段。', position: 12 }] },
      });
      return success({});
    });
    mountBridge({ analysisState: async () => success({ ...initial, runs: [financeRun], drafts: [{ ...draft, run_ids: [financeRun.id] }] }), financeCall });
    render(<Analysis {...props} embedded section="drafts" />);
    const advice = await screen.findByRole('region', { name: '正文阅读建议' });
    expect(within(advice).getByText('这一段包含多个主题，建议分段。')).toBeTruthy();
    expect(screen.getByText('当前文稿数字、单位和引用未发现问题。')).toBeTruthy();
    expect(within(screen.getByLabelText('分项核对状态')).getAllByText('已核对')).toHaveLength(3);
    fireEvent.click(screen.getByRole('tab', { name: /^编辑$/ }));
    fireEvent.change(screen.getByLabelText('文稿正文'), { target: { value: '修改后的短结论。' } });
    expect(screen.queryByRole('region', { name: '正文阅读建议' })).toBeNull();
  });

  it('groups duplicate quality issues while leaving every source detail expandable', async () => {
    const financeRun: AnalysisRun = { ...run, engine: 'finance' };
    const duplicateIssues = Array.from({ length: 120 }, (_, index) => ({
      severity: 'error',
      code: 'unknown_fact',
      origin: 'claim_binding',
      message: '引用已失效',
      excerpt: `正文片段 ${index + 1}`,
    }));
    const financeCall = vi.fn(async (_taskId: string, command: string) => {
      if (command === 'finance-completion-recoveries') return success({ recoveries: [] });
      if (command === 'prepare-explanation') return success({ facts: [] });
      if (command === 'validate-explanation') return success({ status: 'issues', issues: duplicateIssues, coverage: { required: 120, cited: 0 } });
      if (command === 'finance-background-list') return success({ backgrounds: [] });
      return success({});
    });
    mountBridge({ analysisState: async () => success({ ...initial, runs: [financeRun], drafts: [{ ...draft, run_ids: [financeRun.id] }] }), financeCall });
    render(<Analysis {...props} embedded section="drafts" />);
    expect(await screen.findByText(/需要复核/)).toBeTruthy();
    const issueSummary = screen.getByText(/引用已不属于当前计算结果 · 120 条原始问题/, { selector: 'summary' });
    expect(issueSummary.textContent).toContain('引用已不属于当前计算结果');
    const grouped = issueSummary.closest('details') as HTMLDetailsElement;
    expect(grouped.open).toBe(false);
    fireEvent.click(issueSummary);
    expect(grouped.open).toBe(true);
    expect(await screen.findByText('对应片段：正文片段 1')).toBeTruthy();
    expect(screen.getByText('对应片段：正文片段 120')).toBeTruthy();
    const firstRawSummary = screen.getByText('原始问题 1', { selector: 'summary' });
    const firstRaw = firstRawSummary.closest('details') as HTMLDetailsElement;
    fireEvent.click(firstRawSummary);
    expect(firstRaw.open).toBe(true);
    expect(within(firstRaw).getByText(/"message": "引用已失效"/)).toBeTruthy();
    expect(screen.queryByText(/当前文稿数字、单位和引用未发现问题/)).toBeNull();
  });

  it('saves only explicitly cited finance facts and does not promote prepared facts automatically', async () => {
    const financeRun: AnalysisRun = { ...run, engine: 'finance' };
    const financeDraft: AnalysisDraft = { ...draft, run_ids: [financeRun.id], body: '利润引用 {{fact:fact-body}}。', fact_ids: ['fact-draft'] };
    const financeCall = vi.fn(async (_taskId: string, command: string, spec?: Record<string, unknown>) => {
      if (command === 'prepare-explanation') return success({ facts: [
        { id: 'fact-body', run_id: financeRun.id, row: 0, column: 'profit', label: '正文事实', display_value: '90' },
        { id: 'fact-optional', run_id: financeRun.id, row: 1, column: 'profit', label: '可选事实', display_value: '80' },
      ] });
      if (command === 'validate-explanation') return success({ status: 'pass', issues: [] });
      if (command === 'finance-background-list') return success({ backgrounds: [] });
      if (command === 'save-explanation-draft') return success({ ...financeDraft, ...spec, id: '8'.repeat(32) });
      return success({});
    });
    mountBridge({ analysisState: async () => success({ ...initial, runs: [financeRun], drafts: [financeDraft] }), financeCall });
    render(<Analysis {...props} embedded section="drafts" />);
    await screen.findByText(/检查通过/);
    fireEvent.click(screen.getByRole('tab', { name: /^编辑$/ }));
    fireEvent.change(screen.getByLabelText('文稿正文'), { target: { value: '利润引用 {{fact:fact-body}}，并沿用经理口径。' } });
    fireEvent.click(screen.getByRole('button', { name: '保存文稿新版' }));
    await waitFor(() => expect(financeCall).toHaveBeenCalledWith(task.id, 'save-explanation-draft', expect.objectContaining({
      fact_ids: ['fact-draft', 'fact-body'],
    })));
    const saveCall = financeCall.mock.calls.find(([, command]) => command === 'save-explanation-draft');
    expect(saveCall?.[2]).not.toEqual(expect.objectContaining({ fact_ids: expect.arrayContaining(['fact-optional']) }));
  });

  it.each(['finance', 'structured_aggregate'])('distinguishes generated appendix issues and keeps save available for %s', async (engine) => {
    const financeRun: AnalysisRun = { ...run, engine };
    const financeCall = vi.fn(async (_taskId: string, command: string) => {
      if (command === 'prepare-explanation') return success({ facts: [] });
      if (command === 'validate-explanation') return success({ status: 'needs_attention', issues: [
        { code: 'uncited_number', severity: 'error', origin: 'generated_appendix', excerpt: '自动附表金额' },
        { code: 'unknown_fact', severity: 'error', origin: 'claim_binding' },
      ] });
      return success({});
    });
    mountBridge({ analysisState: async () => success({ ...initial, runs: [financeRun] }), financeCall });
    render(<Analysis {...props} embedded section="drafts" />);
    expect(await screen.findByText(/自动附表中的数字与计算依据尚未对应/)).toBeTruthy();
    expect(screen.getByText(/对应片段：自动附表金额/)).toBeTruthy();
    expect(screen.getByText(/引用绑定 · 需修正/)).toBeTruthy();
    fireEvent.click(screen.getByRole('tab', { name: /^编辑$/ }));
    fireEvent.change(screen.getByRole('textbox', { name: '文稿正文' }), { target: { value: '利润有所改善，业务原因待进一步确认。' } });
    expect((screen.getByRole('button', { name: '保存文稿新版' }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('clears saved quality details while automatic validation is pending, then shows the real validation result', async () => {
    const financeRun: AnalysisRun = { ...run, engine: 'finance' };
    const checkedDraft: AnalysisDraft = { ...draft, run_ids: [financeRun.id], quality: { status: 'pass', issues: [],
      checks: { numbers: { status: 'pass' }, coverage: { status: 'pass' }, provenance: { status: 'pass' } } } };
    let resolveCheck!: (value: Answer<Record<string, unknown>>) => void;
    const financeCall = vi.fn(async (_taskId: string, command: string) => {
      if (command === 'finance-completion-recoveries') return success({ recoveries: [] });
      if (command === 'prepare-explanation') return success({ facts: [] });
      if (command === 'validate-explanation') return new Promise<Answer<Record<string, unknown>>>((resolve) => { resolveCheck = resolve; });
      if (command === 'finance-background-list') return success({ backgrounds: [] });
      return success({});
    });
    mountBridge({ analysisState: async () => success({ ...initial, runs: [financeRun], drafts: [checkedDraft] }), financeCall });
    render(<Analysis {...props} embedded section="drafts" />);
    await screen.findByText(/检查中/);
    expect(screen.queryByText('数字与口径')).toBeNull();
    expect(screen.queryAllByText('已核对')).toHaveLength(0);

    await act(async () => resolveCheck(success({ status: 'pass', issues: [], checks: { numbers: { status: 'pass' }, coverage: { status: 'pass' }, provenance: { status: 'pass' } } })));
    expect(await screen.findByText(/检查通过/)).toBeTruthy();
    expect(screen.getByText('数字与口径')).toBeTruthy();
    expect(screen.getAllByText('已核对')).toHaveLength(3);
  });

  it('clears existing quality details during manual recheck and does not restore them after failure', async () => {
    const financeRun: AnalysisRun = { ...run, engine: 'finance' };
    const checkedDraft: AnalysisDraft = { ...draft, run_ids: [financeRun.id], quality: { status: 'pass', issues: [],
      checks: { numbers: { status: 'pass' }, coverage: { status: 'pass' }, provenance: { status: 'pass' } } } };
    let resolveCheck!: (value: Answer<Record<string, unknown>>) => void;
    let validationCalls = 0;
    const financeCall = vi.fn(async (_taskId: string, command: string) => {
      if (command === 'finance-completion-recoveries') return success({ recoveries: [] });
      if (command === 'prepare-explanation') return success({ facts: [] });
      if (command === 'validate-explanation') {
        validationCalls += 1;
        if (validationCalls === 1) return success({ status: 'pass', issues: [], checks: { numbers: { status: 'pass' }, coverage: { status: 'pass' }, provenance: { status: 'pass' } } });
        return new Promise<Answer<Record<string, unknown>>>((resolve) => { resolveCheck = resolve; });
      }
      if (command === 'finance-background-list') return success({ backgrounds: [] });
      return success({});
    });
    mountBridge({ analysisState: async () => success({ ...initial, runs: [financeRun], drafts: [checkedDraft] }), financeCall });
    render(<Analysis {...props} embedded section="drafts" />);
    expect(await screen.findByText(/检查通过/)).toBeTruthy();
    expect(screen.getByText('数字与口径')).toBeTruthy();
    expect(screen.getAllByText('已核对')).toHaveLength(3);

    fireEvent.click(screen.getByRole('button', { name: '重检当前正文' }));
    await screen.findByText(/检查中/);
    expect(screen.queryByText('数字与口径')).toBeNull();
    expect(screen.queryAllByText('已核对')).toHaveLength(0);
    await act(async () => resolveCheck({ ok: false, refused: true, message: '校验服务暂不可用' }));
    expect(await screen.findByText(/暂不可检查/)).toBeTruthy();
    expect(screen.queryByText('数字与口径')).toBeNull();
    expect(screen.queryAllByText('已核对')).toHaveLength(0);
  });

  it('invalidates an in-flight quality check when the draft body changes', async () => {
    const financeRun: AnalysisRun = { ...run, engine: 'finance' };
    let resolveCheck!: (value: Answer<Record<string, unknown>>) => void;
    const financeCall = vi.fn(async (_taskId: string, command: string) => {
      if (command === 'prepare-explanation') return success({ facts: [] });
      if (command === 'validate-explanation') return new Promise<Answer<Record<string, unknown>>>((resolve) => { resolveCheck = resolve; });
      if (command === 'finance-background-list') return success({ backgrounds: [] });
      return success({});
    });
    mountBridge({ analysisState: async () => success({ ...initial, runs: [financeRun], drafts: [{ ...draft, run_ids: [financeRun.id] }] }), financeCall });
    render(<Analysis {...props} embedded section="drafts" />);
    await screen.findByText(/检查中/);
    fireEvent.click(screen.getByRole('tab', { name: /^编辑$/ }));
    fireEvent.change(screen.getByLabelText('文稿正文'), { target: { value: '检查未完成时修改正文。' } });
    expect(screen.getByText(/待重检/)).toBeTruthy();
    await act(async () => resolveCheck(success({ status: 'pass', issues: [] })));
    expect(screen.queryByText(/检查通过/)).toBeNull();
    expect(screen.getByText(/待重检/)).toBeTruthy();
  });

  it('does not show a green quality state for non-pass statuses without issues', async () => {
    const financeRun: AnalysisRun = { ...run, engine: 'finance' };
    const financeCall = vi.fn(async (_taskId: string, command: string) => {
      if (command === 'prepare-explanation') return success({ facts: [] });
      if (command === 'validate-explanation') return success({ status: 'needs_attention', issues: [], coverage: { required: 1, cited: 1 } });
      if (command === 'finance-background-list') return success({ backgrounds: [] });
      return success({});
    });
    mountBridge({ analysisState: async () => success({ ...initial, runs: [financeRun], drafts: [{ ...draft, run_ids: [financeRun.id] }] }), financeCall });
    render(<Analysis {...props} embedded section="drafts" />);
    expect(await screen.findByText(/需要复核/)).toBeTruthy();
    expect(screen.queryByText(/检查通过/)).toBeNull();
  });

  it('ignores stale draft quality responses after switching draft versions', async () => {
    const second = { ...draft, id: '7'.repeat(32), title: '第二版', body: '第二版正文。' };
    let resolveFirst!: (value: Answer<Record<string, unknown>>) => void;
    const financeCall = vi.fn(async (_taskId: string, command: string, spec?: Record<string, unknown>) => {
      if (command === 'prepare-explanation') return success({ facts: [] });
      if (command === 'validate-explanation' && spec?.draft_id === draft.id) return new Promise<Answer<Record<string, unknown>>>((resolve) => { resolveFirst = resolve; });
      if (command === 'validate-explanation') return success({ status: 'issues', issues: [{ severity: 'warning', message: '第二版需要补引用' }] });
      if (command === 'finance-background-list') return success({ backgrounds: [] });
      return success({});
    });
    mountBridge({ analysisState: async () => success({ ...initial, drafts: [draft, second] }), financeCall });
    render(<Analysis {...props} embedded section="drafts" />);
    await screen.findByText('第二版');
    chooseSearchable('文稿版本', /经营简报/);
    await screen.findByText('经营简报');
    await waitFor(() => expect(financeCall).toHaveBeenCalledWith(task.id, 'validate-explanation', expect.objectContaining({ draft_id: draft.id, materiality: { absolute: '0' } })));
    chooseSearchable('文稿版本', /第二版/);
    await screen.findByText(/第二版需要补引用/, { selector: 'summary' });
    await act(async () => resolveFirst(success({ status: 'pass', issues: [] })));
    expect(screen.queryByText(/检查通过/)).toBeNull();
    expect(screen.getByText(/第二版需要补引用/, { selector: 'summary' })).toBeTruthy();
  });

  it('saves finance background with editable scope and lists applicability', async () => {
    const financeRun: AnalysisRun = { ...run, engine: 'finance', finance_context_id: 'ctx-a', bindings: { actual: source.id },
      finance_scope: { actual: { ledger: '总账', organization: '华东', period: '2026-09', currency: 'CNY', unit: '元' } } };
    const financeDraft: AnalysisDraft = { ...draft, run_ids: [financeRun.id] };
    const financeCall = vi.fn(async (_taskId: string, command: string, spec?: Record<string, unknown>) => {
      if (command === 'prepare-explanation') return success({ facts: [] });
      if (command === 'validate-explanation') return success({ status: 'pass', issues: [] });
      if (command === 'finance-background-list') return success({ backgrounds: [{ id: 'bg-old', label: '季节性', text: '春节备货提前', basis: 'professional_judgment', scope: spec?.scope, effective_from: '2026-09' }] });
      if (command === 'finance-background-save') return success({ id: 'bg-new', ...spec });
      return success({});
    });
    mountBridge({ analysisState: async () => success({ ...initial, runs: [financeRun], drafts: [financeDraft] }), financeCall });
    render(<Analysis {...props} embedded section="drafts" />);
    await screen.findByText('财务背景与经理判断');
    fireEvent.click(screen.getByText('财务背景与经理判断'));
    await waitFor(() => expect((screen.getByLabelText('背景组织') as HTMLInputElement).value).toBe('华东'));
    fireEvent.change(screen.getByLabelText('标题'), { target: { value: '销售节奏' } });
    fireEvent.change(screen.getByLabelText('背景正文'), { target: { value: '大客户提前下单，收入确认前置。' } });
    fireEvent.change(screen.getByLabelText('依据类型'), { target: { value: 'source_fact' } });
    chooseSearchable('背景授权资料', /本月实际/);
    fireEvent.change(screen.getByLabelText('背景段落编号'), { target: { value: '1' } });
    fireEvent.change(screen.getByLabelText('适用期间范围开始'), { target: { value: '2026-09' } });
    fireEvent.click(screen.getByRole('button', { name: '保存背景' }));
    await waitFor(() => expect(financeCall).toHaveBeenCalledWith(task.id, 'finance-background-save', expect.objectContaining({
      context_id: 'ctx-a', label: '销售节奏', text: '大客户提前下单，收入确认前置。', basis: 'source_fact',
      scope: expect.objectContaining({ ledger: '总账', organization: '华东', period: '2026-09' }), effective_from: '2026-09',
      dataset_id: source.id, paragraph: 1,
    })));
    expect(screen.getByText('已保存财务背景。')).toBeTruthy();
    expect(screen.getByText('销售节奏')).toBeTruthy();
    expect(screen.getByText(/大客户提前下单/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText('依据类型'), { target: { value: 'external_reference' } });
    expect(screen.getByLabelText('背景外部来源')).toBeTruthy();
    expect(screen.getByLabelText('背景查询日期')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('标题'), { target: { value: '政策依据' } });
    fireEvent.change(screen.getByLabelText('背景正文'), { target: { value: '税费政策引用外部公开说明。' } });
    fireEvent.change(screen.getByLabelText('背景外部来源'), { target: { value: '财政部公开资料' } });
    fireEvent.change(screen.getByLabelText('背景查询日期'), { target: { value: '2026-09-06' } });
    fireEvent.click(screen.getByRole('button', { name: '保存背景' }));
    await waitFor(() => expect(financeCall.mock.calls.some(([, command, spec]) => command === 'finance-background-save'
      && (spec as Record<string, unknown>)?.basis === 'external_reference')).toBe(true));
    const externalSave = financeCall.mock.calls.find(([, command, spec]) => command === 'finance-background-save'
      && (spec as Record<string, unknown>)?.basis === 'external_reference')?.[2] as Record<string, unknown>;
    expect(externalSave.external_reference).toEqual({ title: '财政部公开资料', retrieved_at: '2026-09-06' });
    expect(externalSave).not.toHaveProperty('source');
    expect(externalSave).not.toHaveProperty('retrieved_at');
    expect(externalSave).not.toHaveProperty('dataset_id');
    fireEvent.click(screen.getByRole('button', { name: '刷新适用背景' }));
    await waitFor(() => expect(financeCall).toHaveBeenCalledWith(task.id, 'finance-background-list', expect.objectContaining({ context_id: 'ctx-a' })));
    expect(await screen.findByText('季节性')).toBeTruthy();
    expect(screen.getByText(/账簿 总账 · 组织 华东 · 期间 2026-09/)).toBeTruthy();
  });

  it('confirms a pending management adjustment from the results sidebar without auto-rerunning', async () => {
    const context = { ...object, id: '4'.repeat(32), name: '八月经营口径', bindings: { actual: source.id },
      scopes: { actual: { ledger: '总账', organization: '华东', period: '2026-08', currency: 'CNY', unit: '元', scenario: 'actual' } } };
    const pending = { id: 'adj-pending', label: '总部费用调整', include_in_management_pnl: false, amount: '5', profit_impact: '5' };
    const confirmed = { ...pending, id: 'adj-confirmed', parent_id: pending.id, include_in_management_pnl: true };
    let included = false;
    const confirmGate = deferred<Answer<Record<string, unknown>>>();
    const financeCall = vi.fn(async (_taskId: string, command: string) => {
      if (command === 'list-finance-context') return success({ task_id: task.id, datasets: [source], contexts: [context], account_maps: [], scenarios: [], metric_definitions: [], capabilities: ['metrics'] });
      if (command === 'finance-adjustment-list') return success({ adjustments: included ? [confirmed] : [pending] });
      if (command === 'finance-adjustment-confirm') return confirmGate.promise;
      if (command === 'run-metric') return success({ ...run, engine: 'finance', finance_context_id: context.id });
      return success({});
    });
    mountBridge({ analysisState: async () => success(initial), financeCall });
    render(<Analysis {...props} embedded section="results" />);
    await screen.findByRole('heading', { name: '考核调整' });
    expect(await screen.findByText('总部费用调整 · 待确认')).toBeTruthy();
    expect(screen.getByText(/1 条待确认/).closest('summary')).toBeTruthy();
    expect(screen.getByRole('complementary', { name: '考核调整' }).querySelector('details')?.open).toBe(false);
    fireEvent.click(await screen.findByRole('button', { name: '确认纳入' }));
    await waitFor(() => expect((screen.getByRole('button', { name: '确认中…' }) as HTMLButtonElement).disabled).toBe(true));
    expect(financeCall.mock.calls.some(([, command]) => command === 'run-metric')).toBe(false);
    included = true;
    await act(async () => confirmGate.resolve(success(confirmed)));
    await waitFor(() => expect(screen.getByText('已确认纳入考核。')).toBeTruthy());
    expect(financeCall).toHaveBeenCalledWith(task.id, 'finance-adjustment-confirm', { id: pending.id });
    expect(financeCall.mock.calls.filter(([, command]) => command === 'run-metric')).toEqual([]);
    expect(screen.queryByRole('button', { name: '确认纳入' })).toBeNull();
    const checkbox = await screen.findByRole('checkbox', { name: '总部费用调整' });
    expect((checkbox as HTMLInputElement).checked).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: '重算' }));
    await waitFor(() => expect(financeCall).toHaveBeenCalledWith(task.id, 'run-metric', {
      context_id: context.id, metric: { kind: 'management_pnl' }, adjustment_ids: [confirmed.id],
    }));
    fireEvent.click(checkbox);
    fireEvent.click(screen.getByRole('button', { name: '重算' }));
    await waitFor(() => expect(financeCall).toHaveBeenCalledWith(task.id, 'run-metric', {
      context_id: context.id, metric: { kind: 'management_pnl' }, adjustment_ids: [],
    }));
  });

  it('keeps a pending adjustment unincluded when confirm fails', async () => {
    const context = { ...object, id: '4'.repeat(32), name: '八月经营口径', bindings: { actual: source.id },
      scopes: { actual: { ledger: '总账', period: '2026-08', currency: 'CNY', unit: '元', scenario: 'actual' } } };
    const pending = { id: 'adj-pending', label: '总部费用调整', include_in_management_pnl: false };
    const financeCall = vi.fn(async (_taskId: string, command: string) => {
      if (command === 'list-finance-context') return success({ task_id: task.id, datasets: [source], contexts: [context], account_maps: [], scenarios: [], metric_definitions: [], capabilities: ['metrics'] });
      if (command === 'finance-adjustment-list') return success({ adjustments: [pending] });
      if (command === 'finance-adjustment-confirm') return { ok: false as const, refused: true, message: '当前会话无权确认该调整' };
      return success({});
    });
    mountBridge({ analysisState: async () => success(initial), financeCall });
    render(<Analysis {...props} embedded section="results" />);
    await screen.findByRole('button', { name: '确认纳入' });
    fireEvent.click(screen.getByRole('button', { name: '确认纳入' }));
    expect((await screen.findByRole('alert')).textContent).toContain('当前会话无权确认该调整');
    expect((screen.getByRole('button', { name: '确认纳入' }) as HTMLButtonElement).disabled).toBe(false);
    expect(screen.queryByRole('checkbox', { name: '总部费用调整' })).toBeNull();
    expect(financeCall.mock.calls.some(([, command]) => command === 'run-metric')).toBe(false);
  });

  it('hides a pending parent once a confirmed child exists', async () => {
    const context = { ...object, id: '4'.repeat(32), name: '八月经营口径', bindings: { actual: source.id },
      scopes: { actual: { ledger: '总账', organization: '华东', period: '2026-08', currency: 'CNY', unit: '元', scenario: 'actual' } } };
    const pending = { id: 'adj-pending', label: '总部费用调整', include_in_management_pnl: false };
    const confirmed = { ...pending, id: 'adj-confirmed', parent_id: pending.id, include_in_management_pnl: true };
    const financeCall = vi.fn(async (_taskId: string, command: string) => {
      if (command === 'list-finance-context') return success({ task_id: task.id, datasets: [source], contexts: [context], account_maps: [], scenarios: [], metric_definitions: [], capabilities: ['metrics'] });
      if (command === 'finance-adjustment-list') return success({ adjustments: [pending, confirmed] });
      return success({});
    });
    mountBridge({ analysisState: async () => success(initial), financeCall });
    render(<Analysis {...props} embedded section="results" />);
    await screen.findByRole('heading', { name: '考核调整' });
    expect(await screen.findByRole('checkbox', { name: '总部费用调整' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: '确认纳入' })).toBeNull();
  });

  it('hides superseded rows from both the pending list and the rerun checklist', async () => {
    const context = { ...object, id: '4'.repeat(32), name: '八月经营口径', bindings: { actual: source.id },
      scopes: { actual: { ledger: '总账', organization: '华东', period: '2026-08', currency: 'CNY', unit: '元', scenario: 'actual' } } };
    const replacedPending = { id: 'adj-old-pending', label: '旧的待确认调整', include_in_management_pnl: false, superseded_by: 'adj-a' };
    const confirmedA = { id: 'adj-a', label: '总部费用调整', include_in_management_pnl: true, superseded_by: 'adj-d' };
    const confirmedD = { id: 'adj-d', label: '总部费用调整（修订）', include_in_management_pnl: true, parent_id: 'adj-a' };
    const financeCall = vi.fn(async (_taskId: string, command: string) => {
      if (command === 'list-finance-context') return success({ task_id: task.id, datasets: [source], contexts: [context], account_maps: [], scenarios: [], metric_definitions: [], capabilities: ['metrics'] });
      if (command === 'finance-adjustment-list') return success({ adjustments: [replacedPending, confirmedA, confirmedD] });
      if (command === 'run-metric') return success({ ...run, engine: 'finance', finance_context_id: context.id });
      return success({});
    });
    mountBridge({ analysisState: async () => success(initial), financeCall });
    render(<Analysis {...props} embedded section="results" />);
    await screen.findByRole('heading', { name: '考核调整' });
    expect(await screen.findByRole('checkbox', { name: '总部费用调整（修订）' })).toBeTruthy();
    expect(screen.getAllByRole('checkbox')).toHaveLength(1);
    expect(screen.queryByRole('checkbox', { name: '总部费用调整' })).toBeNull();
    expect(screen.queryByText(/旧的待确认调整/)).toBeNull();
    expect(screen.queryByRole('button', { name: '确认纳入' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '重算' }));
    await waitFor(() => expect(financeCall).toHaveBeenCalledWith(task.id, 'run-metric', {
      context_id: context.id, metric: { kind: 'management_pnl' }, adjustment_ids: [confirmedD.id],
    }));
  });

  it('refreshes finance source files through the native bridge and keeps duplicate batches visible', async () => {
    const financeCall = vi.fn(async (_taskId: string, command: string) => command === 'finance-source-list'
      ? success({ batches: [{ id: '7'.repeat(32), created_at: task.created_at, source_name: '金蝶导出', dataset_id: null, effective_dataset_id: source.id, row_count: 1, publication_status: 'published' }] })
      : success({ task_id: task.id, datasets: [source], contexts: [], account_maps: [], scenarios: [], metric_definitions: [], capabilities: [] }));
    const financeSourceRefresh = vi.fn(async () => success({ dataset_id: '8'.repeat(32), effective_dataset_id: '8'.repeat(32) }));
    mountBridge({ analysisState: async () => success(initial), financeCall, financeSourceRefresh });
    render(<Analysis {...props} embedded section="materials" />);
    await openSourceRefreshDetails();
    fireEvent.change(sourceRefreshField('账簿'), { target: { value: '经营总账' } });
    fireEvent.change(sourceRefreshField('组织'), { target: { value: '华东' } });
    fireEvent.change(sourceRefreshField('期间'), { target: { value: '2026-08' } });
    fireEvent.change(sourceRefreshField('截止时间'), { target: { value: '2026-08-31' } });
    fireEvent.click(screen.getByRole('button', { name: /选择文件并刷新/ }));
    await waitFor(() => expect(financeSourceRefresh).toHaveBeenCalledWith(task.id, expect.objectContaining({
      product: 'file', version: 'export', file_identity_policy: 'snapshot_only',
      scope: expect.objectContaining({ ledger_id: '经营总账', organization_id: '华东', period: '2026-08', currency: 'CNY' }),
    })));
    expect(screen.getByText(/已发布新来源快照/)).toBeTruthy();
    fireEvent.click(screen.getByText(/来源刷新批次/));
    expect(screen.getByText(/沿用/)).toBeTruthy();
  });

  it('keeps ERP source refresh behind an on-demand disclosure in the materials empty state', async () => {
    const emptyState: AnalysisState = { ...initial, datasets: [], analyses: [], runs: [], drafts: [] };
    const financeCall = vi.fn(async (_taskId: string, command: string) => command === 'finance-source-list'
      ? success({ batches: [] })
      : success({ task_id: task.id, datasets: [], contexts: [], account_maps: [], scenarios: [], metric_definitions: [], capabilities: [] }));
    mountBridge({ analysisState: async () => success(emptyState), financeCall });
    render(<Analysis {...props} embedded section="materials" />);
    expect(await screen.findByRole('heading', { name: '把手头的资料加进来' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '添加资料' })).toBeTruthy();
    expect(screen.getByRole('button', { name: /与助手讨论/ })).toBeTruthy();
    const details = screen.getByText('更新 ERP 来源').closest('details') as HTMLDetailsElement | null;
    expect(details).toBeTruthy();
    expect(details!.open).toBe(false);
    expect(within(details!).getByLabelText('账簿').closest('details')).toBe(details);
  });

  it('inspects, binds, previews and applies an Excel collaboration workbook', async () => {
    const workbook = { ...source, id: '7'.repeat(32), source_name: 'plan.xlsx', name: '预算工作簿', metadata: { source_file: 'source.xlsx' } };
    const refreshedWorkbook = { ...workbook, id: '8'.repeat(32), name: '预算工作簿 · 经理刷新' };
    const financeCall = vi.fn(async (_taskId: string, command: string) => {
      if (command === 'finance-source-list') return success({ batches: [] });
      if (command === 'workbook-inspect') return success({ sheet_names: ['Sheet1'], tables: ['OutputTable'], named_ranges: [], unsupported_features: [] });
      if (command === 'workbook-bind') return success({ id: 'bind-1' });
      if (command === 'workbook-read') return success({ rows: [{ amount: '10.00' }], diagnostics: [] });
      if (command === 'workbook-preview') return success({ patch_id: 'patch-1', patch: { cells: [{ cell: 'B2', field: 'amount', old_value: '10.00', new_value: '0.00', conflict: true }] } });
      if (command === 'workbook-apply') return success({ artifact_path: 'finance/workbook_outputs/files/out.xlsx' });
      return success({});
    });
    mountBridge({ analysisState: async () => success({ ...initial, datasets: [source, workbook, refreshedWorkbook] }), financeCall });
    render(<Analysis {...props} embedded section="materials" />);
    await screen.findByText('Excel 协作');
    fireEvent.click(screen.getByRole('button', { name: /检查结构/ }));
    await screen.findByText(/工作表：Sheet1/);
    fireEvent.change(screen.getByLabelText('表格名称'), { target: { value: 'OutputTable' } });
    fireEvent.change(screen.getByLabelText('用途'), { target: { value: 'output' } });
    fireEvent.click(screen.getByRole('button', { name: '保存绑定' }));
    await waitFor(() => expect(financeCall).toHaveBeenCalledWith(task.id, 'workbook-bind', expect.objectContaining({
      source: { kind: 'table', name: 'OutputTable' }, writable: true,
    })));
    chooseSearchable('工作簿资料', /经理刷新/);
    fireEvent.click(screen.getByRole('button', { name: '读取区域' }));
    await screen.findByText('10.00');
    expect(financeCall).toHaveBeenCalledWith(task.id, 'workbook-read', { binding_id: 'bind-1', dataset_id: refreshedWorkbook.id });
    fireEvent.click(screen.getByRole('button', { name: '预览写回' }));
    await screen.findByText('B2');
    expect(financeCall).toHaveBeenCalledWith(task.id, 'workbook-preview', expect.objectContaining({ binding_id: 'bind-1', dataset_id: refreshedWorkbook.id }));
    expect((screen.getByLabelText(/B2 · 原值/) as HTMLSelectElement).value).toBe('keep');
    fireEvent.change(screen.getByLabelText(/B2 · 原值/), { target: { value: 'apply' } });
    fireEvent.click(screen.getByRole('button', { name: '生成工作簿' }));
    await waitFor(() => expect(financeCall).toHaveBeenCalledWith(task.id, 'workbook-apply', { patch_id: 'patch-1', resolutions: { B2: 'apply' } }));
  });

  it('ignores stale Excel writeback previews after the target snapshot changes', async () => {
    const workbook = { ...source, id: '7'.repeat(32), source_name: 'plan.xlsx', name: '预算工作簿', metadata: { source_file: 'source.xlsx' } };
    const refreshedWorkbook = { ...workbook, id: '8'.repeat(32), name: '预算工作簿 · 经理刷新' };
    let resolvePreview!: (value: Answer<Record<string, unknown>>) => void;
    const financeCall = vi.fn(async (_taskId: string, command: string) => {
      if (command === 'finance-source-list') return success({ batches: [] });
      if (command === 'workbook-preview') {
        return new Promise<Answer<Record<string, unknown>>>((resolve) => { resolvePreview = resolve; });
      }
      return success({});
    });
    mountBridge({ analysisState: async () => success({ ...initial, datasets: [source, workbook, refreshedWorkbook] }), financeCall });
    render(<Analysis {...props} embedded section="materials" />);
    await screen.findByText('Excel 协作');
    fireEvent.change(screen.getByLabelText('绑定编号'), { target: { value: 'bind-1' } });
    fireEvent.click(screen.getByRole('button', { name: '预览写回' }));
    chooseSearchable('工作簿资料', /经理刷新/);
    await act(async () => resolvePreview(success({ patch_id: 'old-patch', patch: { cells: [
      { cell: 'Z9', field: 'amount', old_value: '1.00', new_value: '2.00', conflict: true },
    ] } })));
    expect(financeCall).toHaveBeenCalledWith(task.id, 'workbook-preview', expect.objectContaining({ binding_id: 'bind-1', dataset_id: workbook.id }));
    expect(screen.queryByText('Z9')).toBeNull();
    expect((screen.getByRole('button', { name: '生成工作簿' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('uses explicit actual and budget scope aliases for budget bridge reruns even when they are stored out of order', async () => {
    const customContext = { ...object, id: '4'.repeat(32), name: '八月经营口径', bindings: { budget: budgetSource.id, actual: source.id },
      scopes: { budget: { ledger: '经营总账', organization: '华东', period: '2026-08', currency: 'CNY', unit: '元', scenario: 'prior-plan' },
        actual: { ledger: '经营总账', organization: '华东', period: '2026-08', currency: 'CNY', unit: '元', scenario: 'current' } } };
    const financeCall = vi.fn(async (_taskId: string, command: string) => command === 'list-finance-context'
      ? success({ task_id: task.id, datasets: [source, budgetSource], contexts: [customContext], account_maps: [], scenarios: [], metric_definitions: [], capabilities: ['variance'] })
      : success({}));
    mountBridge({ analysisState: async () => success({ ...initial, datasets: [source, budgetSource] }), financeCall });
    render(<Analysis {...props} embedded section="results" />);
    await screen.findByText('八月经营口径');
    fireEvent.click(screen.getByRole('button', { name: '用已保存口径运行预算桥' }));
    await waitFor(() => expect(financeCall).toHaveBeenCalledWith(task.id, 'explain-variance', expect.objectContaining({
      context_id: customContext.id, actual_scenario: 'current', baseline_scenario: 'prior-plan',
      dimensions: ['organization', 'period'],
    })));
  });

  it('rejects ambiguous budget bridge contexts instead of guessing scenario label order', async () => {
    const customContext = { ...object, id: '4'.repeat(32), name: '八月经营口径', bindings: { current: source.id, plan: budgetSource.id },
      scopes: { current: { ledger: '经营总账', organization: '华东', period: '2026-08', currency: 'CNY', unit: '元', scenario: 'current' },
        plan: { ledger: '经营总账', organization: '华东', period: '2026-08', currency: 'CNY', unit: '元', scenario: 'prior-plan' } } };
    const financeCall = vi.fn(async (_taskId: string, command: string) => command === 'list-finance-context'
      ? success({ task_id: task.id, datasets: [source, budgetSource], contexts: [customContext], account_maps: [], scenarios: [], metric_definitions: [], capabilities: ['variance'] })
      : success({}));
    mountBridge({ analysisState: async () => success({ ...initial, datasets: [source, budgetSource] }), financeCall });
    render(<Analysis {...props} embedded section="results" />);
    await screen.findByText('八月经营口径');
    fireEvent.click(screen.getByRole('button', { name: '用已保存口径运行预算桥' }));
    expect((await screen.findByRole('alert')).textContent).toContain('明确的 actual 与 budget 情景别名');
    expect(financeCall).not.toHaveBeenCalledWith(task.id, 'explain-variance', expect.anything());
  });

  it('drops stale source-row drilldown when the selected finance run changes', async () => {
    const firstRun: AnalysisRun = { ...run, id: '5'.repeat(32), engine: 'finance', finance_context_id: 'ctx-a',
      result: { columns: [{ name: 'management_account', type: 'VARCHAR' }], rows: [{ management_account: 'revenue', source_rows: [{ dataset_id: source.id, row_index: 1 }] }], row_count: 1, truncated: false } };
    const secondRun: AnalysisRun = { ...firstRun, id: '6'.repeat(32), created_at: '2026-09-06T00:00:00Z',
      result: { columns: [{ name: 'management_account', type: 'VARCHAR' }], rows: [{ management_account: 'cost', source_rows: [{ dataset_id: source.id, row_index: 2 }] }], row_count: 1, truncated: false } };
    let backend: AnalysisState = { ...initial, runs: [firstRun] };
    let resolveDrilldown!: (value: Answer<Record<string, unknown>>) => void;
    const financeCall = vi.fn(async (_taskId: string, command: string) => {
      if (command === 'list-finance-context') return success({ task_id: task.id, datasets: [source], contexts: [], account_maps: [], scenarios: [], metric_definitions: [], capabilities: ['drilldown'] });
      if (command === 'drilldown-fact') return new Promise<Answer<Record<string, unknown>>>((resolve) => { resolveDrilldown = resolve; });
      return success({});
    });
    mountBridge({ analysisState: vi.fn(async () => success(backend)), financeCall });
    render(<Analysis {...props} embedded section="results" />);
    await screen.findByText('第 1 行 · revenue');
    await waitFor(() => expect(Array.from((screen.getByLabelText('结果行来源') as HTMLSelectElement).options).map((option) => option.value)).toContain('0'));
    fireEvent.change(screen.getByLabelText('结果行来源'), { target: { value: '0' } });
    await waitFor(() => expect((screen.getByLabelText('结果行来源') as HTMLSelectElement).value).toBe('0'));
    fireEvent.click(screen.getByRole('button', { name: '查看来源行' }));
    await waitFor(() => expect(financeCall).toHaveBeenCalledWith(task.id, 'drilldown-fact', { run_id: firstRun.id, row: 0, offset: 0, limit: 100 }));
    backend = { ...initial, runs: [firstRun, secondRun] };
    fireEvent.click(screen.getByRole('button', { name: '刷新' }));
    await screen.findByText('第 1 行 · cost');
    await act(async () => resolveDrilldown(success({ run_id: firstRun.id, row: 0, rows: [], total: 1, offset: 0, has_more: false, message: '旧运行来源' })));
    expect(screen.queryByText(/旧运行来源/)).toBeNull();
    expect((screen.getByLabelText('结果行来源') as HTMLSelectElement).value).toBe('');
  });

  it('passes structured aggregate excluded-detail section through the Analysis drilldown IPC wiring', async () => {
    const structuredRun: AnalysisRun = { ...run, engine: 'structured_aggregate', result: {
      columns: [{ name: 'metric', type: 'VARCHAR' }, { name: 'amount', type: 'DECIMAL' }, { name: 'excluded_source_rows', type: 'JSON' }],
      rows: [{ metric: '收入', amount: '120' }],
      detail_rows: [{ customer: '客户甲', amount: '120', source_rows: [{ dataset_id: source.id, row_index: 1 }] }],
      excluded_detail_rows: [{ customer: '客户乙', amount: '5', excluded_source_rows: [{ dataset_id: source.id, row_index: 2 }] }],
      row_count: 1, truncated: false,
      provenance: { mode: 'executor_verified_source_map', status: 'verified', plan_hash: 'p1', data_hash: 'd1', source_hash: 's1' },
    } };
    const financeCall = vi.fn(async (_taskId: string, command: string) => {
      if (command === 'list-finance-context') return success({ task_id: task.id, datasets: [source], contexts: [], account_maps: [], scenarios: [], metric_definitions: [], capabilities: ['drilldown'] });
      if (command === 'drilldown-fact') return success({ run_id: structuredRun.id, row: 0, rows: [], total: 0, offset: 0, has_more: false, message: '剔除明细来源' });
      return success({});
    });
    mountBridge({ analysisState: async () => success({ ...initial, analyses: [{ ...analysis, engine: 'structured_aggregate', sql: '', aggregate_plan: { group_by: ['region'] } }], runs: [structuredRun] }), financeCall });
    render(<Analysis {...props} embedded section="results" />);
    await screen.findByText('来源可追溯：执行器已核对来源映射；这不代表业务判断已经通过。');
    expect(screen.getByText('高级：查看汇总规则')).toBeTruthy();
    expect(screen.queryByText('高级：查看计算脚本')).toBeNull();
    await waitFor(() => expect(Array.from((screen.getByLabelText('结果行来源') as HTMLSelectElement).options).map((option) => option.value)).toContain('excluded_detail_rows:0'));
    fireEvent.change(screen.getByLabelText('结果行来源'), { target: { value: 'excluded_detail_rows:0' } });
    await waitFor(() => expect((screen.getByLabelText('结果行来源') as HTMLSelectElement).value).toBe('excluded_detail_rows:0'));
    fireEvent.click(screen.getByRole('button', { name: '查看来源行' }));
    await waitFor(() => expect(financeCall).toHaveBeenCalledWith(task.id, 'drilldown-fact', {
      run_id: structuredRun.id, row: 0, section: 'excluded_detail_rows', offset: 0, limit: 100,
    }));
  });

  it('runs baseline and delayed child scenarios from a saved finance context', async () => {
    const context = { ...object, id: '4'.repeat(32), name: '八月经营口径', bindings: { actual: source.id, budget: budgetSource.id },
      scopes: { actual: { ledger: '经营总账', organization: '华东', period: '2026-08', currency: 'CNY', unit: '元', scenario: 'actual' } } };
    const financeCall = vi.fn(async (_taskId: string, command: string, spec?: Record<string, unknown>) => {
      if (command === 'list-finance-context') return success({ task_id: task.id, datasets: [source, budgetSource], contexts: [context], account_maps: [], scenarios: [], metric_definitions: [], capabilities: ['scenarios'] });
      if (command === 'finance-scenario-save') return success({ ...object, id: spec?.parent_id ? '6'.repeat(32) : spec?.kind === 'cash_13_weeks' ? '7'.repeat(32) : '5'.repeat(32), ...spec });
      if (command === 'finance-scenario-run') return success({ ...run, engine: 'finance', finance_context_id: context.id });
      return success({});
    });
    mountBridge({ analysisState: async () => success({ ...initial, datasets: [source, budgetSource] }), financeCall });
    render(<Analysis {...props} embedded section="results" />);
    await screen.findByText('情景测算');
    fireEvent.change(screen.getByLabelText('账龄日期'), { target: { value: '2026-08-31' } });
    fireEvent.click(screen.getByRole('button', { name: '应收状态筛选' }));
    fireEvent.mouseDown(screen.getByRole('option', { name: /争议应收/ }));
    fireEvent.click(screen.getByRole('button', { name: /运行基准情景/ }));
    await waitFor(() => expect(financeCall).toHaveBeenCalledWith(task.id, 'finance-scenario-run', { scenario_id: '5'.repeat(32) }));
    expect(financeCall).toHaveBeenCalledWith(task.id, 'finance-scenario-save', expect.objectContaining({
      context_id: context.id, kind: 'receivables_aging', inputs: expect.objectContaining({ as_of: '2026-08-31', invoices_alias: 'actual',
        status_filter: expect.objectContaining({ field: 'invoice_status', include: ['disputed'] }) }),
    }));
    expect((screen.getByRole('button', { name: '运行延迟回款子情景' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('情景类型'), { target: { value: 'cash_13_weeks' } });
    expect((screen.getByRole('button', { name: '运行延迟回款子情景' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('期初现金'), { target: { value: '5000000.00' } });
    fireEvent.change(screen.getByLabelText('预测开始日'), { target: { value: '2026-09-01' } });
    fireEvent.change(screen.getByLabelText('实际收支截止日'), { target: { value: '2026-08-31' } });
    fireEvent.click(screen.getByRole('button', { name: /运行基准情景/ }));
    await waitFor(() => expect(financeCall).toHaveBeenCalledWith(task.id, 'finance-scenario-save', expect.objectContaining({
      context_id: context.id, kind: 'cash_13_weeks', inputs: expect.objectContaining({ opening_cash: '5000000.00', start_date: '2026-09-01', actual_cutoff: '2026-08-31', scenario: { delay_receipts_days: 0 } }),
    })));
    await waitFor(() => expect((screen.getByRole('button', { name: '运行延迟回款子情景' }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole('button', { name: '运行延迟回款子情景' }));
    await waitFor(() => expect(financeCall).toHaveBeenCalledWith(task.id, 'finance-scenario-save', expect.objectContaining({
      parent_id: '7'.repeat(32), changes: { scenario: expect.objectContaining({ delay_receipts_days: 14 }) },
    })));
  });

  it('opens a cited fact through the dedicated locator channel, not deliverable preview', async () => {
    const financeRun: AnalysisRun = { ...run, engine: 'finance', finance_context_id: 'ctx-a' };
    const checkedDraft: AnalysisDraft = { ...draft, run_ids: [financeRun.id], quality: { status: 'passed', issues: [] } };
    const sourceLocatorOpen = vi.fn(async () => success({
      status: 'ok',
      viewer: 'univer' as const,
      task: task.id,
      sha256: source.source_hash,
      locator: { kind: 'xlsx', excel_range: '费用!D18', preview_available: true },
      preview: { available: true, handle: 'h'.repeat(64) },
    }));
    const onLocatorPreview = vi.fn();
    const financeCall = vi.fn(async (_taskId: string, command: string) => {
      if (command === 'prepare-explanation') return success({ facts: [{ id: 'fact-expense', run_id: financeRun.id, row: 0, column: 'expense', label: '费用', display_value: '20' }] });
      if (command === 'validate-explanation') return success({ status: 'pass', issues: [], coverage: { required: 1, cited: 1 } });
      if (command === 'finance-background-list') return success({ backgrounds: [] });
      return success({});
    });
    mountBridge({ analysisState: async () => success({ ...initial, runs: [financeRun], drafts: [checkedDraft] }), financeCall, sourceLocatorOpen });
    render(<Analysis {...props} embedded section="drafts" onLocatorPreview={onLocatorPreview} />);
    fireEvent.click(await screen.findByText('可引用事实 · 1 条'));
    fireEvent.click(screen.getByRole('button', { name: '打开原文定位' }));
    await waitFor(() => expect(sourceLocatorOpen).toHaveBeenCalledWith(task.id, { fact_id: 'fact-expense' }));
    await waitFor(() => expect(onLocatorPreview).toHaveBeenCalledWith({ task: task.id, sha256: source.source_hash, excel_range: '费用!D18' }));
    const handed = onLocatorPreview.mock.calls[0][0] as Record<string, unknown>;
    expect(handed).not.toHaveProperty('origin');
    expect(handed).not.toHaveProperty('file');
    expect(handed).not.toHaveProperty('allowedRoot');
    expect(financeCall.mock.calls.some(([, command]) => command === 'drilldown-fact')).toBe(false);
  });

  it('shows 无权打开 without navigating when the locator is forbidden', async () => {
    const financeRun: AnalysisRun = { ...run, engine: 'finance', finance_context_id: 'ctx-a' };
    const checkedDraft: AnalysisDraft = { ...draft, run_ids: [financeRun.id], quality: { status: 'passed', issues: [] } };
    const sourceLocatorOpen = vi.fn(async () => success({ status: 'locator_forbidden' }));
    const onLocatorPreview = vi.fn();
    const financeCall = vi.fn(async (_taskId: string, command: string) => {
      if (command === 'prepare-explanation') return success({ facts: [{ id: 'fact-expense', run_id: financeRun.id, row: 0, column: 'expense', label: '费用', display_value: '20' }] });
      if (command === 'validate-explanation') return success({ status: 'pass', issues: [] });
      if (command === 'finance-background-list') return success({ backgrounds: [] });
      if (command === 'drilldown-fact') return success({ run_id: financeRun.id, row: 0, rows: [], total: 0, offset: 0, has_more: false, message: '来源行' });
      return success({});
    });
    mountBridge({ analysisState: async () => success({ ...initial, runs: [financeRun], drafts: [checkedDraft] }), financeCall, sourceLocatorOpen });
    render(<Analysis {...props} embedded section="drafts" onLocatorPreview={onLocatorPreview} />);
    fireEvent.click(await screen.findByText('可引用事实 · 1 条'));
    fireEvent.click(screen.getByRole('button', { name: '打开原文定位' }));
    expect(await screen.findByText('无权打开')).toBeTruthy();
    expect(onLocatorPreview).not.toHaveBeenCalled();
    expect(financeCall.mock.calls.some(([, command]) => command === 'drilldown-fact')).toBe(false);
  });

  it('shows a fixed sentence, never main\'s text, when the locator channel fails', async () => {
    const financeRun: AnalysisRun = { ...run, engine: 'finance', finance_context_id: 'ctx-a' };
    const checkedDraft: AnalysisDraft = { ...draft, run_ids: [financeRun.id], quality: { status: 'passed', issues: [] } };
    const sourceLocatorOpen = vi.fn(async () => ({ ok: false as const, refused: false, message: 'preview_unavailable' }));
    const onLocatorPreview = vi.fn();
    const financeCall = vi.fn(async (_taskId: string, command: string) => {
      if (command === 'prepare-explanation') return success({ facts: [{ id: 'fact-expense', run_id: financeRun.id, row: 0, column: 'expense', label: '费用', display_value: '20' }] });
      if (command === 'validate-explanation') return success({ status: 'pass', issues: [] });
      if (command === 'finance-background-list') return success({ backgrounds: [] });
      return success({});
    });
    mountBridge({ analysisState: async () => success({ ...initial, runs: [financeRun], drafts: [checkedDraft] }), financeCall, sourceLocatorOpen });
    render(<Analysis {...props} embedded section="drafts" onLocatorPreview={onLocatorPreview} />);
    fireEvent.click(await screen.findByText('可引用事实 · 1 条'));
    fireEvent.click(screen.getByRole('button', { name: '打开原文定位' }));
    expect((await screen.findByRole('alert')).textContent).toContain('预览暂不可用');
    expect(onLocatorPreview).not.toHaveBeenCalled();
  });

  it('opens an archived PDF locator through reportSource instead of drilldown, on the cited page', async () => {
    const financeRun: AnalysisRun = { ...run, engine: 'finance', finance_context_id: 'ctx-a' };
    const archived = { id: 'src-pdf', name: '费用明细.pdf', sha256: source.source_hash, format: 'pdf' as const };
    const checkedDraft: AnalysisDraft = { ...draft, run_ids: [financeRun.id], quality: { status: 'passed', issues: [] },
      document: { schema_version: 1, template_version: 'annual-v1', metadata: { company: '华东', period: '2026-08', currency: 'CNY', unit: '元' },
        content: [{ type: 'paragraph', content: [{ type: 'text', text: '利润有所改善。' }] }], sources: [archived] } };
    const sourceLocatorOpen = vi.fn(async () => success({
      status: 'ok',
      viewer: 'pdf' as const,
      // The dataset id is not a report source id; only the hash ties the two together.
      locator: { kind: 'pdf', dataset_id: source.id, source_hash: source.source_hash, page: 2, preview_available: true },
      preview: { available: true, handle: 'h'.repeat(64) },
    }));
    const reportSource = vi.fn(async () => success({ source: archived, data_base64: btoa('%PDF-1.4\n') }));
    const getPage = vi.fn(async () => ({
      getViewport: () => ({ width: 1, height: 1 }),
      render: () => ({ promise: Promise.resolve(), cancel() {} }),
    }));
    pdfjsMock.getDocument.mockImplementationOnce(() => ({ promise: Promise.resolve({ numPages: 3, getPage }) }));
    const financeCall = vi.fn(async (_taskId: string, command: string) => {
      if (command === 'prepare-explanation') return success({ facts: [{ id: 'fact-pdf', run_id: financeRun.id, row: 0, column: 'expense', label: '费用', display_value: '20' }] });
      if (command === 'validate-explanation') return success({ status: 'pass', issues: [] });
      if (command === 'finance-background-list') return success({ backgrounds: [] });
      if (command === 'drilldown-fact') return success({ run_id: financeRun.id, row: 0, rows: [], total: 0, offset: 0, has_more: false });
      return success({});
    });
    mountBridge({ analysisState: async () => success({ ...initial, runs: [financeRun], drafts: [checkedDraft] }), financeCall, sourceLocatorOpen, reportSource });
    render(<Analysis {...props} embedded section="drafts" />);
    fireEvent.click(await screen.findByText('可引用事实 · 1 条'));
    fireEvent.click(screen.getByRole('button', { name: '打开原文定位' }));
    await waitFor(() => expect(reportSource).toHaveBeenCalledWith(task.id, archived.id));
    expect(reportSource).not.toHaveBeenCalledWith(task.id, source.id);
    await waitFor(() => expect(getPage).toHaveBeenCalledWith(2));
    expect(await screen.findByText('2/3')).toBeTruthy();
    expect(financeCall.mock.calls.some(([, command]) => command === 'drilldown-fact')).toBe(false);
  });

  it('says 该页未归档 when no report source carries the locator hash, instead of guessing from the dataset id', async () => {
    const financeRun: AnalysisRun = { ...run, engine: 'finance', finance_context_id: 'ctx-a' };
    const checkedDraft: AnalysisDraft = { ...draft, run_ids: [financeRun.id], quality: { status: 'passed', issues: [] } };
    const sourceLocatorOpen = vi.fn(async () => success({
      status: 'ok',
      viewer: 'pdf' as const,
      locator: { kind: 'pdf', dataset_id: source.id, source_hash: source.source_hash, preview_available: true },
      preview: { available: true, handle: 'h'.repeat(64) },
    }));
    const reportSource = vi.fn(async () => success({ source: { id: source.id, name: 'x.pdf', sha256: source.source_hash, format: 'pdf' as const }, data_base64: btoa('%PDF-1.4\n') }));
    const financeCall = vi.fn(async (_taskId: string, command: string) => {
      if (command === 'prepare-explanation') return success({ facts: [{ id: 'fact-pdf', run_id: financeRun.id, row: 0, column: 'expense', label: '费用', display_value: '20' }] });
      if (command === 'validate-explanation') return success({ status: 'pass', issues: [] });
      if (command === 'finance-background-list') return success({ backgrounds: [] });
      if (command === 'drilldown-fact') return success({ run_id: financeRun.id, row: 0, rows: [], total: 0, offset: 0, has_more: false, message: '已定位到费用来源行' });
      return success({});
    });
    mountBridge({ analysisState: async () => success({ ...initial, runs: [financeRun], drafts: [checkedDraft] }), financeCall, sourceLocatorOpen, reportSource });
    render(<Analysis {...props} embedded section="drafts" />);
    fireEvent.click(await screen.findByText('可引用事实 · 1 条'));
    fireEvent.click(screen.getByRole('button', { name: '打开原文定位' }));
    expect(await screen.findByText('该页未归档')).toBeTruthy();
    expect(reportSource).not.toHaveBeenCalled();
    expect(await screen.findByText(/已定位到费用来源行/)).toBeTruthy();
  });

  it('keeps the snapshot row when a locator is unavailable or the page was not archived', async () => {
    const financeRun: AnalysisRun = { ...run, engine: 'finance', finance_context_id: 'ctx-a' };
    const checkedDraft: AnalysisDraft = { ...draft, run_ids: [financeRun.id], quality: { status: 'passed', issues: [] } };
    const sourceLocatorOpen = vi.fn(async () => success({
      status: 'ok',
      locator: { kind: 'pdf', preview_available: false },
      preview: { available: false, handle: 'h'.repeat(64) },
    }));
    const financeCall = vi.fn(async (_taskId: string, command: string) => {
      if (command === 'prepare-explanation') return success({ facts: [{ id: 'fact-expense', run_id: financeRun.id, row: 0, column: 'expense', label: '费用', display_value: '20' }] });
      if (command === 'validate-explanation') return success({ status: 'pass', issues: [] });
      if (command === 'finance-background-list') return success({ backgrounds: [] });
      if (command === 'drilldown-fact') return success({ run_id: financeRun.id, row: 0, rows: [
        { source: { dataset_id: source.id, row_index: 1 }, source_hash: source.source_hash, data: { expense: '20' }, voucher_detail_available: false },
      ], total: 1, offset: 0, has_more: false, message: '已定位到费用来源行' });
      return success({});
    });
    mountBridge({ analysisState: async () => success({ ...initial, runs: [financeRun], drafts: [checkedDraft] }), financeCall, sourceLocatorOpen });
    render(<Analysis {...props} embedded section="drafts" />);
    fireEvent.click(await screen.findByText('可引用事实 · 1 条'));
    fireEvent.click(screen.getByRole('button', { name: '打开原文定位' }));
    expect(await screen.findByText('该页未归档')).toBeTruthy();
    expect(await screen.findByText(/已定位到费用来源行/)).toBeTruthy();
  });

  it('archives the current result chart and reopens the stored series without rerunning', async () => {
    const context = { ...object, id: '4'.repeat(32), name: '八月经营口径', bindings: { actual: source.id },
      scopes: { actual: { ledger: '总账', period: '2026-08', currency: 'CNY', unit: '元', scenario: 'actual' } } };
    const financeRun: AnalysisRun = { ...run, engine: 'finance', finance_context_id: context.id };
    const listed = { id: 'chart-1', label: '管理口径损益', run_id: financeRun.id, series: { columns: ['profit'], rows: [{ profit: '30' }] } };
    let saved = false;
    const financeCall = vi.fn(async (_taskId: string, command: string) => {
      if (command === 'list-finance-context') return success({ task_id: task.id, datasets: [source], contexts: [context], account_maps: [], scenarios: [], metric_definitions: [], capabilities: ['metrics'] });
      if (command === 'finance-adjustment-list') return success({ adjustments: [] });
      if (command === 'chart-deliverable-list') return success({ charts: saved ? [listed] : [] });
      if (command === 'chart-deliverable-save') { saved = true; return success(listed); }
      if (command === 'chart-deliverable-open') return success(listed);
      if (command === 'run-metric') return success(financeRun);
      return success({});
    });
    mountBridge({ analysisState: async () => success({ ...initial, runs: [financeRun] }), financeCall });
    render(<Analysis {...props} embedded section="results" />);
    await screen.findByRole('heading', { name: '归档图' });
    fireEvent.click(screen.getByRole('button', { name: '归档当前结果图' }));
    await waitFor(() => expect(financeCall).toHaveBeenCalledWith(task.id, 'chart-deliverable-save', { run_id: financeRun.id }));
    expect(await screen.findByText('已归档当前结果图。')).toBeTruthy();
    fireEvent.click(await screen.findByRole('button', { name: '打开' }));
    await waitFor(() => expect(financeCall).toHaveBeenCalledWith(task.id, 'chart-deliverable-open', { id: listed.id }));
    expect(screen.getByText('30')).toBeTruthy();
    expect(financeCall.mock.calls.filter(([, command]) => command === 'run-metric')).toEqual([]);
  });

  it('records a workbook circle-select as an invoice-basis revision', async () => {
    const context = { ...object, id: '4'.repeat(32), name: '八月经营口径', bindings: { actual: source.id } };
    const workbook = { ...source, id: '7'.repeat(32), source_name: 'plan.xlsx', name: '预算工作簿', metadata: { source_file: 'source.xlsx' } };
    const financeRun: AnalysisRun = { ...run, engine: 'finance', finance_context_id: context.id };
    const financeCall = vi.fn(async (_taskId: string, command: string) => {
      if (command === 'workbook-inspect') return success({ sheet_names: ['Sheet1'], tables: ['OutputTable'], named_ranges: [], unsupported_features: [] });
      if (command === 'workbook-bind') return success({ id: 'bind-1' });
      if (command === 'analysis-circle-select') return success({ id: 'req-new', change_reason: '改成开票口径' });
      return success({});
    });
    mountBridge({ analysisState: async () => success({ ...initial, datasets: [source, workbook], runs: [financeRun] }), financeCall });
    render(<Analysis {...props} embedded section="materials" />);
    await screen.findByText('Excel 协作');
    fireEvent.click(screen.getByRole('button', { name: /检查结构/ }));
    await screen.findByText(/工作表：Sheet1/);
    fireEvent.change(screen.getByLabelText('表格名称'), { target: { value: 'OutputTable' } });
    fireEvent.click(screen.getByRole('button', { name: '保存绑定' }));
    await waitFor(() => expect(financeCall).toHaveBeenCalledWith(task.id, 'workbook-bind', expect.objectContaining({
      source: { kind: 'table', name: 'OutputTable' },
    })));
    fireEvent.click(screen.getByRole('button', { name: '改成开票口径' }));
    await waitFor(() => expect(financeCall).toHaveBeenCalledWith(task.id, 'analysis-circle-select', expect.objectContaining({
      kind: 'workbook', binding_id: 'bind-1', instruction: '改成开票口径', context_id: context.id,
    })));
    expect(await screen.findByText('已按圈选生成开票口径修订。')).toBeTruthy();
  });

  it('uses the latest finance context for workbook circle-select', async () => {
    const oldContext = { ...object, id: '3'.repeat(32), name: '旧口径' };
    const context = { ...object, id: '4'.repeat(32), name: '八月经营口径', bindings: { actual: source.id } };
    const workbook = { ...source, id: '7'.repeat(32), source_name: 'plan.xlsx', name: '预算工作簿', metadata: { source_file: 'source.xlsx' } };
    const oldRun: AnalysisRun = { ...run, id: '1'.repeat(32), engine: 'finance', finance_context_id: oldContext.id };
    const financeRun: AnalysisRun = { ...run, engine: 'finance', finance_context_id: context.id };
    const financeCall = vi.fn(async (_taskId: string, command: string) => {
      if (command === 'workbook-inspect') return success({ sheet_names: ['Sheet1'], tables: ['OutputTable'], named_ranges: [], unsupported_features: [] });
      if (command === 'workbook-bind') return success({ id: 'bind-1' });
      if (command === 'analysis-circle-select') return success({ id: 'req-new', change_reason: '改成开票口径' });
      return success({});
    });
    mountBridge({ analysisState: async () => success({ ...initial, datasets: [source, workbook], runs: [oldRun, financeRun] }), financeCall });
    render(<Analysis {...props} embedded section="materials" />);
    await screen.findByText('Excel 协作');
    fireEvent.click(screen.getByRole('button', { name: /检查结构/ }));
    await screen.findByText(/工作表：Sheet1/);
    fireEvent.change(screen.getByLabelText('表格名称'), { target: { value: 'OutputTable' } });
    fireEvent.click(screen.getByRole('button', { name: '保存绑定' }));
    await waitFor(() => expect(financeCall).toHaveBeenCalledWith(task.id, 'workbook-bind', expect.objectContaining({
      source: { kind: 'table', name: 'OutputTable' },
    })));
    fireEvent.click(screen.getByRole('button', { name: '改成开票口径' }));
    await waitFor(() => expect(financeCall).toHaveBeenCalledWith(task.id, 'analysis-circle-select', expect.objectContaining({
      kind: 'workbook', binding_id: 'bind-1', context_id: context.id,
    })));
  });

});
