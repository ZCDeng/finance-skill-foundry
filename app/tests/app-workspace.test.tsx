// @vitest-environment jsdom
import { useState } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Answer, Bridge, TaskRow } from '../src/bridge.js';
import { App } from '../src/App.js';

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
const ok = <T,>(value: T): Answer<T> => ({ ok: true, value });
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
  it('restores a selected task without manufacturing a user submission', async () => {
    const api = mount();
    await waitFor(() => expect(api.harnessOpen).toHaveBeenCalledOnce());
    expect(api.harnessOpen).toHaveBeenCalledWith('analysis', b.id, { verbatim: undefined, draftId: undefined, submit: undefined, requestId: undefined });
    expect(screen.getByText('本地成果：西南回款')).toBeTruthy();
    expect(screen.queryByRole('button', { name: '对话' })).toBeNull();
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
