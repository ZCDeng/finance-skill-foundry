// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Answer, Bridge, TaskDetail, TaskRow } from '../src/bridge.js';
import { App } from '../src/App.js';
import { press } from './press.js';

// Keep task selection, history, document reading and the data strip real.
vi.mock('../src/views/Analysis.js', () => ({ Analysis: () => null }));

const task = (key: string, title: string): TaskRow => ({
  id: key.repeat(32), title, period: null, skill_id: null,
  created_at: '2026-09-06T00:00:00Z', windows: 1,
});
const a = task('a', '华东利润');
const b = task('b', '西南回款');
const detail = (row: TaskRow): TaskDetail => ({
  task: row,
  windows: [{ window_id: row.id, reason: 'initial', at: row.created_at, state: 'locked', inputs: [] }],
  sessions: [],
  deliverables: [{ seq: 1, kind: 'brief', window_id: row.id,
    sha256: (row.id === a.id ? '1' : '2').repeat(64), bytes: 10,
    cause: '分析结论', session_id: null, at: row.created_at }],
});
const ok = <T,>(value: T): Answer<T> => ({ ok: true, value });
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}
function mount(overrides: Partial<Bridge> = {}) {
  const api = {
    // The last task is restored initially, so start with A selected.
    tasks: vi.fn(async () => ok([b, a])),
    task: vi.fn(async (id: string) => ok(detail(id === a.id ? a : b))),
    gallery: vi.fn(async () => ok([])),
    harnessStatus: vi.fn(async () => ok({ wiring: { state: 'ready' as const }, consequence: null, origin: 'http://localhost:1' })),
    harnessOpen: vi.fn<NonNullable<Bridge['harnessOpen']>>(async (_intent, id) => ok({ sessionId: `session-${id}`, preset: 'analysis' })),
    paneVisible: vi.fn(async (value: string) => ok({ screen: value })),
    deliverableOpen: vi.fn(async () => ok({ opened: 'archived.xlsx' })),
    ...overrides,
  } satisfies Partial<Bridge>;
  (globalThis as unknown as { foundry: Partial<Bridge> }).foundry = api;
  render(<App />);
  return api;
}
async function openTool(name: '任务记录与旧版流程' | '数据台') {
  press(await screen.findByRole('button', { name: '任务工具' }));
  fireEvent.click(await screen.findByRole('menuitem', { name }));
}
async function selectTask(row: TaskRow) {
  fireEvent.click(screen.getByRole('button', { name: '工作区' }));
  fireEvent.click(await screen.findByRole('button', { name: '展开任务列表' }));
  fireEvent.click(await screen.findByRole('button', { name: row.title }));
}
async function openInitialHistory() {
  await screen.findByRole('heading', { name: a.title });
  await openTool('任务记录与旧版流程');
}
async function openBHistory() {
  await selectTask(b);
  await openTool('任务记录与旧版流程');
  await screen.findByRole('heading', { name: b.title });
}
afterEach(() => {
  cleanup();
  delete (globalThis as unknown as { foundry?: Bridge }).foundry;
  vi.clearAllMocks();
});

describe('task history response ownership', () => {
  it('ignores old A task responses in both the history and current data strip after selecting B', async () => {
    const currentA = deferred<Answer<TaskDetail>>();
    const historyA = deferred<Answer<TaskDetail>>();
    let readsA = 0;
    const taskRead = vi.fn<Bridge['task']>((id) => id === a.id
      ? (++readsA === 1 ? currentA.promise : historyA.promise)
      : Promise.resolve(ok(detail(b))));
    mount({ task: taskRead });
    await openInitialHistory();
    await waitFor(() => expect(readsA).toBe(2));
    await openBHistory();

    await act(async () => historyA.resolve(ok(detail(a))));
    expect(screen.getByRole('heading', { name: b.title })).toBeTruthy();
    expect(screen.queryByRole('heading', { name: a.title })).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: '工作区' }));
    await openTool('数据台');
    expect(await screen.findByText('bbbbbb · locked')).toBeTruthy();
    await act(async () => currentA.resolve(ok(detail(a))));
    expect(screen.getByText('bbbbbb · locked')).toBeTruthy();
    expect(screen.queryByText('aaaaaa · locked')).toBeNull();
  });

  it('keeps B history mounted when the export started on A finishes', async () => {
    const exported = deferred<Awaited<ReturnType<Bridge['exportWorkbook']>>>();
    const exportWorkbook = vi.fn<Bridge['exportWorkbook']>(() => exported.promise);
    const api = mount({ exportWorkbook });
    await openInitialHistory();
    fireEvent.click(await screen.findByRole('button', { name: '导出 Excel' }));
    expect(exportWorkbook).toHaveBeenCalledWith(a.id, a.id);
    await openBHistory();
    const bHeading = screen.getByRole('heading', { name: b.title });
    const readsBeforeCompletion = vi.mocked(api.task).mock.calls.length;

    await act(async () => exported.resolve(ok({ sha256: '3'.repeat(64), seq: 2, ext: '.xlsx' })));
    expect(api.deliverableOpen).toHaveBeenCalledWith(a.id, '3'.repeat(64), '.xlsx');
    expect(screen.getByRole('heading', { name: b.title })).toBe(bHeading);
    expect(screen.getByRole('button', { name: '导出 Excel' })).toBeTruthy();
    // An obsolete refresh must be rejected before it clears B or starts an A read.
    expect(api.task).toHaveBeenCalledTimes(readsBeforeCompletion);

    fireEvent.click(screen.getByRole('button', { name: '工作区' }));
    await openTool('数据台');
    expect(screen.getByText('bbbbbb · locked')).toBeTruthy();
  });



  it('ignores a workbook preview that returns after selecting another task', async () => {
    const latePreview = deferred<Answer<{ task: string; sha256: string; origin: string }>>();
    const workbookDetail = (row: TaskRow): TaskDetail => ({
      ...detail(row),
      deliverables: detail(row).deliverables.map((item) => ({ ...item, ext: '.xlsx' })),
    });
    const taskRead = vi.fn<Bridge['task']>((id) => Promise.resolve(ok(workbookDetail(id === a.id ? a : b))));
    const previewOpen = vi.fn<NonNullable<Bridge['previewOpen']>>((id) => id === a.id
      ? latePreview.promise
      : Promise.resolve(ok({ task: b.id, sha256: '2'.repeat(64), origin: 'http://127.0.0.1:9002' })));
    const previewClose = vi.fn<NonNullable<Bridge['previewClose']>>(async () => ok({ stopped: true }));
    const api = mount({ task: taskRead, previewOpen, previewClose });
    await openInitialHistory();
    fireEvent.click(await screen.findByRole('button', { name: '预览第 1 版交付物' }));
    await waitFor(() => expect(previewOpen).toHaveBeenCalledWith(a.id, '1'.repeat(64), '.xlsx'));

    await openBHistory();
    await act(async () => latePreview.resolve(ok({ task: a.id, sha256: '1'.repeat(64), origin: 'http://127.0.0.1:9001' })));

    expect(screen.queryByText('表格预览')).toBeNull();
    expect(screen.getByRole('heading', { name: b.title })).toBeTruthy();
    expect(previewClose).toHaveBeenCalledTimes(1);
    expect(vi.mocked(api.paneVisible!).mock.calls.map(([value]) => value)).not.toContain('preview');
  });

  it('can open a later preview after an earlier preview request rejects', async () => {
    const workbookDetail = (row: TaskRow): TaskDetail => ({
      ...detail(row),
      deliverables: detail(row).deliverables.map((item) => ({ ...item, ext: '.xlsx' })),
    });
    const taskRead = vi.fn<Bridge['task']>((id) => Promise.resolve(ok(workbookDetail(id === a.id ? a : b))));
    const previewOpen = vi.fn<NonNullable<Bridge['previewOpen']>>((id) => id === a.id
      ? Promise.reject(new Error('preview gateway failed'))
      : Promise.resolve(ok({ task: b.id, sha256: '2'.repeat(64), origin: 'http://127.0.0.1:9002' })));
    const api = mount({ task: taskRead, previewOpen });
    await openInitialHistory();
    fireEvent.click(await screen.findByRole('button', { name: '预览第 1 版交付物' }));
    expect(await screen.findAllByText('preview gateway failed')).not.toHaveLength(0);

    await openBHistory();
    fireEvent.click(await screen.findByRole('button', { name: '预览第 1 版交付物' }));

    expect(await screen.findByText('表格预览')).toBeTruthy();
    expect(screen.getByRole('heading', { name: '西南回款' })).toBeTruthy();
    expect(screen.queryAllByText('preview gateway failed')).toHaveLength(0);
    expect(previewOpen).toHaveBeenCalledWith(b.id, '2'.repeat(64), '.xlsx');
    expect(vi.mocked(api.paneVisible!).mock.calls.map(([value]) => value)).toContain('preview');
  });

  it('keeps B document visible when the document read started on A arrives late', async () => {
    const textA = deferred<Answer<string>>();
    const deliverableText = vi.fn<Bridge['deliverableText']>((id) => id === a.id
      ? textA.promise : Promise.resolve(ok('西南回款的结论正文')));
    mount({ deliverableText });
    await openInitialHistory();
    fireEvent.click(await screen.findByRole('button', { name: '打开第 1 版交付物' }));
    expect(deliverableText).toHaveBeenCalledWith(a.id, '1'.repeat(64));
    await openBHistory();
    fireEvent.click(screen.getByRole('button', { name: '打开第 1 版交付物' }));
    expect(await screen.findByText('西南回款的结论正文')).toBeTruthy();

    await act(async () => textA.resolve(ok('华东利润的迟到正文')));
    expect(screen.getByText('西南回款的结论正文')).toBeTruthy();
    expect(screen.queryByText('华东利润的迟到正文')).toBeNull();
    expect(screen.getByRole('heading', { name: b.title })).toBeTruthy();
  });
});
