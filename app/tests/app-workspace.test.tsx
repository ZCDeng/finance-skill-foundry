// @vitest-environment jsdom
import { useState } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Answer, Bridge, GalleryRow, TaskRow } from '../src/bridge.js';
import { App } from '../src/App.js';
import { press } from './press.js';

vi.mock('../src/views/Analysis.js', () => ({
  Analysis: ({ task, onNew, onChat }: { task: TaskRow | null;
    onNew(text: string): Promise<string>; onChat(text?: string, draft?: string, options?: { submit: boolean; requestId: string; targetTaskId: string }): Promise<void> }) => { const [error, setError] = useState(''); return <div><span role="status">{error}</span>
      <p>{task ? `本地成果：${task.title}` : '从问题开始'}</p>
      <button onClick={() => void (async () => {
        const text = '请把这份完整的问题及资料一起分析';
        const target = await onNew(text);
        await onChat(text, undefined, { submit: true, requestId: 'first-user-action', targetTaskId: target });
      })().catch((error) => setError(error.message))}>发送第一条问题</button>
    </div>; },
}));

const task = (id: string, title: string): TaskRow => ({ id, title, period: null, skill_id: null, created_at: '', windows: 0 });
const a = task('a'.repeat(32), '华东利润');
const b = task('b'.repeat(32), '西南回款');
const galleryRow: GalleryRow = { type: 'deliverable', key: 'b:1', at: '', task: b,
  row: { seq: 1, kind: 'brief', window_id: 'w'.repeat(32), sha256: '1'.repeat(64), bytes: 10,
    cause: 'emit-brief', session_id: null, at: '' } };
const ok = <T,>(value: T): Answer<T> => ({ ok: true, value });
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}
function mount(overrides: Partial<Bridge> = {}) {
  const api = {
    tasks: vi.fn(async () => ok([a, b])),
    task: vi.fn(async (id: string) => ok({ task: id === a.id ? a : b, windows: [], deliverables: [], sessions: [] })),
    gallery: vi.fn(async () => ok([])),
    harnessStatus: vi.fn(async () => ok({ wiring: { state: 'ready' as const }, consequence: null, origin: 'http://localhost:1' })),
    harnessOpen: vi.fn<NonNullable<Bridge['harnessOpen']>>(async (_intent, id, seed) => ok({ sessionId: `session-${id}`, preset: 'analysis', submitted: seed?.submit === true })),
    paneVisible: vi.fn(async (value: string) => ok({ screen: value })),
    ...overrides,
  } satisfies Partial<Bridge>;
  (globalThis as unknown as { foundry: Partial<Bridge> }).foundry = api;
  render(<App />);
  return api;
}
afterEach(() => { cleanup(); delete (globalThis as unknown as { foundry?: Bridge }).foundry; vi.clearAllMocks(); });

describe('unified application session lifecycle', () => {
  it('removes trashed task results from the cached gallery before its next read finishes', async () => {
    const nextGallery = deferred<Answer<GalleryRow[]>>();
    const gallery = vi.fn().mockResolvedValueOnce(ok([galleryRow])).mockReturnValue(nextGallery.promise);
    mount({ gallery, taskTrash: vi.fn(async () => ok({ task_id: b.id, lifecycle_status: 'trashed' as const })),
      tasks: vi.fn(async (view?: string) => ok(view === 'trashed' ? [{ ...b, lifecycle_status: 'trashed' as const }] : [a, b])),
    });
    await screen.findByText('本地成果：西南回款');
    fireEvent.click(screen.getByRole('button', { name: '成果库' }));
    await screen.findByRole('button', { name: /结论稿/ });
    fireEvent.click(screen.getByRole('button', { name: '工作区' }));
    press(screen.getByRole('button', { name: '任务工具' }));
    fireEvent.click(await screen.findByRole('menuitem', { name: /移入回收站/ }));
    await screen.findByText('已将「西南回款」移入回收站');
    fireEvent.click(screen.getByRole('button', { name: '成果库' }));
    expect(screen.queryByRole('button', { name: /结论稿/ })).toBeNull();
    await act(async () => nextGallery.resolve(ok([])));
  });

  it('archiving the open task lands back on 进行中 with the task put down and a way back', async () => {
    let archived = false;
    const api = mount({
      taskArchive: vi.fn(async () => { archived = true; return ok({ task_id: b.id, lifecycle_status: 'archived' as const }); }),
      taskRestore: vi.fn(async () => { archived = false; return ok({ task_id: b.id, lifecycle_status: 'active' as const }); }),
      tasks: vi.fn(async (view?: string) => ok(view === 'archived' ? (archived ? [{ ...b, lifecycle_status: 'archived' as const }] : [])
        : archived ? [a] : [a, b])),
    });
    await screen.findByText('本地成果：西南回款');
    press(screen.getByRole('button', { name: '任务工具' }));
    fireEvent.click(await screen.findByRole('menuitem', { name: '归档任务' }));
    await screen.findByText('已归档「西南回款」');
    expect(screen.getByText('从问题开始')).toBeTruthy();
    expect(screen.getByRole('button', { name: '进行中' }).getAttribute('aria-pressed')).toBe('true');
    await waitFor(() => expect(screen.queryByRole('button', { name: '西南回款' })).toBeNull());
    expect(screen.getByRole('button', { name: '华东利润' })).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: '撤销' }));
    await waitFor(() => expect(api.taskRestore).toHaveBeenCalledWith(b.id));
    await screen.findByRole('button', { name: '西南回款' });
    expect(screen.queryByText('已归档「西南回款」')).toBeNull();
  });

  it('empties the trash only after a confirmation that names how many tasks go', async () => {
    const trashed = [{ ...a, lifecycle_status: 'trashed' as const }, { ...b, lifecycle_status: 'trashed' as const }];
    let left = trashed;
    const api = mount({
      taskEmpty: vi.fn(async () => { const ids = left.map((row) => row.id); left = []; return ok({ task_ids: ids, lifecycle_status: 'purged' as const }); }),
      tasks: vi.fn(async (view?: string) => ok(view === 'trashed' ? left : [])),
    });
    fireEvent.click(await screen.findByRole('button', { name: '展开任务列表' }));
    fireEvent.click(await screen.findByRole('button', { name: '回收站' }));
    fireEvent.click(await screen.findByRole('button', { name: '清空回收站' }));
    const dialog = await screen.findByRole('alertdialog');
    expect(dialog.textContent).toContain('永久删除回收站里的 2 个任务？');
    expect(dialog.textContent).toContain('不能恢复');
    fireEvent.click(screen.getByRole('button', { name: '取消' }));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    expect(api.taskEmpty).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: '清空回收站' }));
    fireEvent.click(await screen.findByRole('button', { name: '永久删除 2 个任务' }));
    await screen.findByText('已永久删除 2 个任务');
    expect(api.taskEmpty).toHaveBeenCalledWith('trashed');
    await screen.findByText('回收站是空的');
    expect(screen.queryByRole('button', { name: '清空回收站' })).toBeNull();
  });

  it('deletes one trashed task for good from its menu', async () => {
    let left = [{ ...b, lifecycle_status: 'trashed' as const }];
    const api = mount({
      taskPurge: vi.fn(async (id: string) => { left = []; return ok({ task_ids: [id], lifecycle_status: 'purged' as const }); }),
      tasks: vi.fn(async (view?: string) => ok(view === 'trashed' ? left : [])),
    });
    fireEvent.click(await screen.findByRole('button', { name: '展开任务列表' }));
    fireEvent.click(await screen.findByRole('button', { name: '回收站' }));
    fireEvent.click(await screen.findByRole('button', { name: '西南回款' }));
    press(screen.getByRole('button', { name: '任务工具' }));
    fireEvent.click(await screen.findByRole('menuitem', { name: '永久删除' }));
    expect((await screen.findByRole('alertdialog')).textContent).toContain('永久删除「西南回款」？');
    fireEvent.click(screen.getByRole('button', { name: '永久删除' }));
    await screen.findByText('已永久删除「西南回款」');
    expect(api.taskPurge).toHaveBeenCalledWith(b.id);
    expect(screen.getByText('从问题开始')).toBeTruthy();
  });

  it('ignores an older gallery response after a newer read has completed', async () => {
    const oldGallery = deferred<Answer<GalleryRow[]>>();
    const gallery = vi.fn().mockReturnValueOnce(oldGallery.promise).mockResolvedValue(ok([]));
    mount({ gallery });
    await screen.findByText('本地成果：西南回款');
    fireEvent.click(screen.getByRole('button', { name: '成果库' }));
    fireEvent.click(screen.getByRole('button', { name: '工作区' }));
    fireEvent.click(screen.getByRole('button', { name: '成果库' }));
    await waitFor(() => expect(gallery).toHaveBeenCalledTimes(2));
    await act(async () => oldGallery.resolve(ok([galleryRow])));
    expect(screen.queryByRole('button', { name: /结论稿/ })).toBeNull();
  });

  it('restores a selected task without manufacturing a user submission', async () => {
    const api = mount();
    await waitFor(() => expect(api.harnessOpen).toHaveBeenCalledOnce());
    expect(api.harnessOpen).toHaveBeenCalledWith('analysis', b.id, { verbatim: undefined, draftId: undefined, submit: undefined, requestId: undefined });
    expect(screen.getByText('本地成果：西南回款')).toBeTruthy();
    expect(screen.queryByRole('button', { name: '对话' })).toBeNull();
  });

  it('a 「让助手…」 question goes into the open task\'s composer without being sent', async () => {
    const api = mount();
    await waitFor(() => expect(api.harnessOpen).toHaveBeenCalledOnce());
    await act(async () => { window.dispatchEvent(new CustomEvent('fnd:ask', { detail: '做一次回款健康分析' })); });
    await waitFor(() => expect(api.harnessOpen).toHaveBeenCalledTimes(2));
    expect(api.harnessOpen).toHaveBeenLastCalledWith('analysis', b.id, { verbatim: '做一次回款健康分析', draftId: undefined, submit: undefined, requestId: undefined });
  });

  it('serializes task switches and does not let the old response select its task again', async () => {
    let finish!: (value: Answer<{ sessionId: string; preset: string }>) => void;
    const harnessOpen = vi.fn((_intent: string, id: string) => id === b.id
      ? new Promise<Answer<{ sessionId: string; preset: string }>>((resolve) => { finish = resolve; })
      : Promise.resolve(ok({ sessionId: 'session-a', preset: 'analysis' })));
    mount({ harnessOpen });
    await waitFor(() => expect(harnessOpen).toHaveBeenCalledOnce());
    fireEvent.click(screen.getByRole('button', { name: '展开任务列表' }));
    fireEvent.click(screen.getByRole('button', { name: a.title }));
    expect(screen.getByRole('heading', { name: a.title })).toBeTruthy();
    expect(harnessOpen).toHaveBeenCalledTimes(1);
    await act(async () => finish(ok({ sessionId: 'late-b', preset: 'analysis' })));
    await waitFor(() => expect(harnessOpen.mock.calls.filter((call) => call[1] === a.id).length).toBeGreaterThanOrEqual(1));
    expect(harnessOpen.mock.calls[1][1]).toBe(a.id);
    expect(screen.getByRole('heading', { name: a.title })).toBeTruthy();
    expect(screen.getByText('本地成果：华东利润')).toBeTruthy();
  });

  it('keeps inactive tasks read-only and does not open a native conversation', async () => {
    const archived = { ...b, lifecycle_status: 'archived' as const };
    const api = mount({ tasks: vi.fn(async () => ok([a, archived])) });
    expect(await screen.findByText('任务已停用编辑')).toBeTruthy();
    expect(screen.getByText(/恢复任务后打开文稿/)).toBeTruthy();
    expect(screen.queryByText('本地成果：西南回款')).toBeNull();
    expect(api.harnessOpen).not.toHaveBeenCalled();
  });

  it('does not let a slow archive result take selection back from a later pick', async () => {
    let finishArchive!: (value: Answer<{ task_id: string; lifecycle_status: 'archived' }>) => void;
    const api = mount({
      taskArchive: vi.fn(() => new Promise<Answer<{ task_id: string; lifecycle_status: 'archived' }>>((resolve) => { finishArchive = resolve; })),
      tasks: vi.fn(async (view?: string) => ok(view === 'archived' ? [{ ...b, lifecycle_status: 'archived' as const }] : [a, b])),
    });
    await screen.findByText('本地成果：西南回款');
    press(screen.getByRole('button', { name: '任务工具' }));
    fireEvent.click(await screen.findByRole('menuitem', { name: /归档任务/ }));
    fireEvent.keyDown(document, { key: 'Escape' });
    fireEvent.click(screen.getByRole('button', { name: '展开任务列表' }));
    fireEvent.click(screen.getByRole('button', { name: a.title }));
    await act(async () => finishArchive(ok({ task_id: b.id, lifecycle_status: 'archived' })));
    expect(screen.getByRole('heading', { name: a.title })).toBeTruthy();
    await waitFor(() => expect(vi.mocked(api.harnessOpen).mock.calls.at(-1)?.[1]).toBe(a.id));
  });

  it('keeps the newest task list response after switching lifecycle filters', async () => {
    const slowActive = deferred<Answer<TaskRow[]>>();
    const archived = { ...b, lifecycle_status: 'archived' as const };
    const tasks = vi.fn((view?: string) => view === 'archived' ? Promise.resolve(ok([archived])) : slowActive.promise);
    mount({ tasks });
    fireEvent.click(screen.getByRole('button', { name: '展开任务列表' }));
    fireEvent.click(screen.getByRole('button', { name: '已归档' }));
    expect(await screen.findByRole('button', { name: b.title })).toBeTruthy();
    await act(async () => slowActive.resolve(ok([a])));
    expect(screen.getByRole('button', { name: b.title })).toBeTruthy();
    expect(screen.queryByRole('button', { name: a.title })).toBeNull();
  });

  it('keeps a later lifecycle filter when an archive finishes before that list loads', async () => {
    const archive = deferred<Answer<{ task_id: string; lifecycle_status: 'archived' }>>();
    const trash = deferred<Answer<TaskRow[]>>();
    const api = mount({
      taskArchive: vi.fn(() => archive.promise),
      tasks: vi.fn((view?: string) => view === 'trashed' ? trash.promise
        : Promise.resolve(ok(view === 'archived' ? [{ ...b, lifecycle_status: 'archived' as const }] : [a, b]))),
    });
    await screen.findByText('本地成果：西南回款');
    press(screen.getByRole('button', { name: '任务工具' }));
    fireEvent.click(await screen.findByRole('menuitem', { name: /归档任务/ }));
    fireEvent.keyDown(document, { key: 'Escape' });
    fireEvent.click(screen.getByRole('button', { name: '展开任务列表' }));
    fireEvent.click(screen.getByRole('button', { name: '回收站' }));
    await act(async () => archive.resolve(ok({ task_id: b.id, lifecycle_status: 'archived' })));
    expect(screen.getByRole('button', { name: '回收站' }).getAttribute('aria-pressed')).toBe('true');
    expect(vi.mocked(api.tasks).mock.calls.at(-1)?.[0]).toBe('trashed');
    await act(async () => trash.resolve(ok([])));
    expect(screen.queryByRole('button', { name: b.title })).toBeNull();
  });

  it('does not discard a loading bucket when its selected filter is clicked again', async () => {
    const archived = deferred<Answer<TaskRow[]>>();
    mount({ tasks: vi.fn((view?: string) => view === 'archived' ? archived.promise : Promise.resolve(ok([a, b]))) });
    await screen.findByText('本地成果：西南回款');
    fireEvent.click(screen.getByRole('button', { name: '展开任务列表' }));
    fireEvent.click(screen.getByRole('button', { name: '已归档' }));
    fireEvent.click(screen.getByRole('button', { name: '已归档' }));
    await act(async () => archived.resolve(ok([{ ...a, lifecycle_status: 'archived' }])));
    expect(screen.getByRole('button', { name: a.title })).toBeTruthy();
    expect(screen.queryByRole('button', { name: b.title })).toBeNull();
  });

  it('keeps local results available after a recoverable conversation failure', async () => {
    const harnessOpen = vi.fn(async () => ({ ok: false as const, refused: true, message: '模型服务暂不可用' }));
    mount({ harnessOpen });
    expect(await screen.findByText('模型服务暂不可用')).toBeTruthy();
    expect(screen.getByText('本地成果：西南回款')).toBeTruthy();
    harnessOpen.mockResolvedValueOnce(ok({ sessionId: 'recovered', preset: 'analysis' }) as never);
    fireEvent.click(screen.getByRole('button', { name: '重新连接' }));
    await waitFor(() => expect(screen.queryByText('模型服务暂不可用')).toBeNull());
  });

  it('submits the first question exactly once against the returned task identity', async () => {
    let rows: TaskRow[] = [];
    const created = task('c'.repeat(32), '新的分析');
    const api = mount({ tasks: vi.fn(async () => ok(rows)), taskNew: vi.fn(async () => { rows = [created]; return ok({ id: created.id }); }) });
    fireEvent.click(screen.getByRole('button', { name: '发送第一条问题' }));
    await waitFor(() => expect(vi.mocked(api.harnessOpen).mock.calls.some((call) => call[2]?.submit)).toBe(true));
    const submissions = vi.mocked(api.harnessOpen).mock.calls.filter((call) => call[2]?.submit);
    expect(submissions).toHaveLength(1);
    expect(submissions[0]).toEqual(['analysis', created.id, {
      verbatim: '请把这份完整的问题及资料一起分析', draftId: undefined, submit: true, requestId: 'first-user-action',
    }]);
  });
  it('does not steal the selection when task creation finishes after a task switch', async () => {
    let finish!: (value: Answer<{ id: string }>) => void;
    const created = task('c'.repeat(32), '刚创建的任务');
    const api = mount({ taskNew: vi.fn(() => new Promise<Answer<{ id: string }>>((resolve) => { finish = resolve; })) });
    await screen.findByText('本地成果：西南回款');
    fireEvent.click(screen.getByRole('button', { name: '发送第一条问题' }));
    fireEvent.click(screen.getByRole('button', { name: '展开任务列表' }));
    fireEvent.click(screen.getByRole('button', { name: a.title }));
    await act(async () => finish(ok({ id: created.id })));
    await waitFor(() => expect(vi.mocked(api.harnessOpen).mock.calls.some((call) => call[1] === created.id)).toBe(true));
    expect(screen.getByRole('heading', { name: a.title })).toBeTruthy();
    await waitFor(() => expect(vi.mocked(api.harnessOpen).mock.calls.at(-1)?.[1]).toBe(a.id));
  });

  it('returns a blocked submission to the editor while leaving the native conversation connected', async () => {
    const api = mount({ taskNew: vi.fn(async () => ok({ id: b.id })),
      harnessOpen: vi.fn(async () => ok({ sessionId: 'session-b', preset: 'analysis', submitted: false, blockedReason: '请先选择模型' })) });
    await screen.findByText('本地成果：西南回款');
    fireEvent.click(screen.getByRole('button', { name: '发送第一条问题' }));
    expect(await screen.findByText('请先选择模型')).toBeTruthy();
    expect(screen.queryByText('对话暂时中断')).toBeNull();
    expect(vi.mocked(api.harnessOpen).mock.calls.length).toBeGreaterThan(1);
  });

});

describe('first run', () => {
  it('opens the guide at 第一次使用 on a store that has never held a task', async () => {
    mount({ tasks: vi.fn(async () => ok([])) });
    expect(await screen.findByRole('heading', { name: '第一次使用' })).toBeTruthy();
  });

  it('stays closed when the store only holds archived tasks', async () => {
    const tasks = vi.fn(async (view?: string) => ok(view === 'all' ? [{ ...a, lifecycle_status: 'archived' as const }] : []));
    mount({ tasks });
    await waitFor(() => expect(tasks).toHaveBeenCalledWith('all'));
    expect(screen.queryByRole('heading', { name: '第一次使用' })).toBeNull();
  });

  it('stays closed for a store with tasks, whatever view is opened later', async () => {
    mount();
    await screen.findByText('本地成果：西南回款');
    expect(screen.queryByRole('heading', { name: '第一次使用' })).toBeNull();
  });
});
