// @vitest-environment jsdom
import { useState } from 'react';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Answer, Bridge, Overview as OverviewData, TaskRow } from '../src/bridge.js';
import { Overview } from '../src/views/Overview.js';
import { App } from '../src/App.js';
import { PreferencesProvider } from '../src/components/Preferences.js';

vi.mock('../src/views/Analysis.js', () => ({
  Analysis: ({ task, tour }: { task: TaskRow | null; tour?: { onEnd(): void } }) => {
    const [shown] = useState(task?.title ?? '');
    return <><p>{task ? `本地成果：${task.title}` : `从问题开始${shown}`}</p>{tour ? <button type="button" onClick={tour.onEnd}>看完了</button> : null}</>;
  },
}));

const task = (id: string, title: string, period: string, extra: Partial<TaskRow> = {}): TaskRow =>
  ({ id: id.repeat(32), title, period, skill_id: null, created_at: '2026-10-01T00:00:00Z', windows: 0, ...extra });
const august = task('a', '华东 8 月月结', '2026-08');
const july = task('b', '华东 7 月月结', '2026-07');
const blocks = (states: string[]) => ['范围', '来源', '结构', '控制', '异常', '复核'].map((label, index) =>
  ({ key: ['scope', 'source', 'structure', 'controls', 'exceptions', 'review'][index], label, state: states[index] as 'done' }));
const data: OverviewData = {
  schema_version: 1,
  todo_count: 3,
  tasks: [
    { task: august, headline: { state: 'not_ready', text: '尚未准备：还有 2 项待处理' },
      blocks: blocks(['blocked', 'done', 'blocked', 'done', 'done', 'not_started']),
      conclusion: { level: 'not_assessable', text: '无法判断' },
      todo: [{ kind: 'scope', text: '期间未确认', target: 'scope' }, { kind: 'structure', text: '月结.xlsx 的表结构等你确认', target: 'structure' }] },
    { task: july, headline: { state: 'needs_review', text: '需要复核：计算完成，但有 1 项来源冲突' },
      blocks: blocks(['done', 'done', 'done', 'done', 'blocked', 'done']),
      conclusion: { level: 'usable_with_caveats', text: '带保留可用' },
      todo: [{ kind: 'exceptions', text: '应收滚动：待外部确认，差额 1200', target: 'controls' }] },
  ],
};
const noop = () => undefined;
const props = { data, loading: false, error: '', fresh: false, recent: [], onRefresh: noop, onOpen: vi.fn(), onOpenClose: vi.fn(),
  onNewQuestion: vi.fn(), onChecklist: vi.fn(), onGuide: vi.fn(), onLibrary: vi.fn() };

afterEach(() => { cleanup(); vi.clearAllMocks(); delete (globalThis as unknown as { foundry?: Bridge }).foundry; });

describe('总览', () => {
  it('groups what waits on the manager, the differences first, and goes where each is handled', () => {
    render(<Overview {...props} />);
    expect(screen.getByRole('heading', { name: '等你处理（3）' })).toBeTruthy();
    const groups = screen.getAllByText(/ · \d$/).map((node) => node.textContent);
    expect(groups).toEqual(['差异待处置 · 1', '表结构待确认 · 1', '分析范围未确认 · 1']);
    fireEvent.click(screen.getByRole('button', { name: /去处理：华东 7 月月结，应收滚动/ }));
    expect(props.onOpen).toHaveBeenCalledWith(july, 'controls');
  });

  it('shows each task\'s close line and six block states in words as well as colour', () => {
    render(<Overview {...props} />);
    const row = screen.getByRole('button', { name: /^华东 8 月月结/ });
    expect(within(row).getByRole('img').getAttribute('aria-label')).toBe('范围待处理，来源已就绪，结构待处理，控制已就绪，异常已就绪，复核尚未开始');
    expect(row.textContent).toContain('尚未准备：还有 2 项待处理');
    expect(screen.getByText('账：带保留可用')).toBeTruthy();
    fireEvent.click(row);
    expect(props.onOpenClose).toHaveBeenCalledWith(august);
  });

  it('says in one line what the boards were recomputed on this month, and opens a task\'s board', () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date('2026-10-20T10:00:00'));
    try {
      const card = (title: string, at: string, changed: boolean, change: string, carried_from: string | null = null) =>
        ({ card_id: title, title, at, changed, change, state: 'pinned' as const, carried_from });
      const withBoards: OverviewData = { ...data, tasks: [
        { ...data.tasks[0], dashboard: { recomputed: [card('集团距生死线', '2026-10-10T09:00:00Z', false, '+0.28 个百分点', '华东 7 月月结'),
          card('风险雷达', '2026-10-10T09:00:00Z', true, '前三名变了'),
          { ...card('回款情景', '2026-10-10T09:00:00Z', false, '+0.28 个百分点'), kind: 'scenario' as const }] } },
        { ...data.tasks[1], dashboard: { recomputed: [card('收入', '2026-09-28T09:00:00Z', true, '变动 +20.0%')] } },
      ] };
      render(<Overview {...props} data={withBoards} />);
      // September's recompute is last month's news.
      const line = screen.getByText('本月已为你自动重算 3 张卡、发现 1 处变化');
      fireEvent.click(line);
      const listed = line.closest('details')!;
      const rows = within(listed).getAllByRole('listitem').map((row) => row.textContent);
      expect(rows[0]).toContain('「风险雷达」：前三名变了');
      expect(rows[1]).toContain('「集团距生死线」：+0.28 个百分点');
      // A scenario card is never accepted: it is only looked at.
      expect(within(listed).getByRole('button', { name: /去看看：华东 8 月月结，回款情景/ })).toBeTruthy();
      expect(within(listed).getByRole('button', { name: /去认可：华东 8 月月结，集团距生死线/ })).toBeTruthy();
      fireEvent.click(within(listed).getByRole('button', { name: /去看看：华东 8 月月结，风险雷达/ }));
      expect(props.onOpen).toHaveBeenCalledWith(august, 'dashboard');
    } finally {
      vi.useRealTimers();
    }
  });

  it('says nothing about boards when none was recomputed this month', () => {
    render(<Overview {...props} />);
    expect(screen.queryByText(/本月已为你自动重算/)).toBeNull();
  });

  it('drafts this month from a chosen task, newest period offered first', () => {
    render(<Overview {...props} />);
    const picker = screen.getByRole('combobox', { name: /用上月套表起草本月/ }) as HTMLSelectElement;
    expect([...picker.options].map((option) => option.textContent)).toEqual(['用上月套表起草本月…', '华东 8 月月结 · 2026 年 8 月', '华东 7 月月结 · 2026 年 7 月']);
    fireEvent.change(picker, { target: { value: july.id } });
    expect(props.onOpen).toHaveBeenCalledWith(july, 'rollforward');
  });

  it('with no task at all, the ways in are the page', () => {
    render(<Overview {...props} data={{ schema_version: 1, tasks: [], todo_count: 0 }} fresh onSample={vi.fn()} />);
    expect(screen.getByRole('heading', { name: '从这里开始' })).toBeTruthy();
    expect(screen.queryByRole('heading', { name: /等你处理/ })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '第一次使用' }));
    expect(props.onGuide).toHaveBeenCalled();
  });

  it('says nothing holds the close when nothing does', () => {
    render(<Overview {...props} data={{ ...data, todo_count: 0, tasks: data.tasks.map((row) => ({ ...row, todo: [] })) }} />);
    expect(screen.getByText('没有挡住月结的事项。')).toBeTruthy();
  });

  it('offers the first look with a way to say no, and says while the 参考结果 is being built', () => {
    const offer = { busy: false, onStart: vi.fn(), onDismiss: vi.fn() };
    const { rerender } = render(<Overview {...props} firstLook={offer} />);
    fireEvent.click(screen.getByRole('button', { name: '不用了' }));
    expect(offer.onDismiss).toHaveBeenCalled();
    rerender(<Overview {...props} firstLook={{ ...offer, busy: true, error: '参考结果没有生成出来' }} />);
    expect((screen.getByRole('button', { name: '正在准备参考结果…' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText('第一次要生成参考结果，大约一分钟。')).toBeTruthy();
    expect(screen.getByRole('alert').textContent).toBe('参考结果没有生成出来');
    rerender(<Overview {...props} />);
    expect(screen.queryByRole('heading', { name: '60 秒看看它能做什么' })).toBeNull();
  });

  it('with every task archived, says so instead of greeting a first run', () => {
    render(<Overview {...props} data={{ schema_version: 1, tasks: [], todo_count: 0 }} />);
    expect(screen.queryByRole('heading', { name: '从这里开始' })).toBeNull();
    expect(screen.getByText(/没有进行中的任务/)).toBeTruthy();
  });
});

describe('总览 in the app', () => {
  const ok = <T,>(value: T): Answer<T> => ({ ok: true, value });
  function mount() {
    const api = {
      tasks: vi.fn(async () => ok([july, august])),
      task: vi.fn(async (id: string) => ok({ task: id === august.id ? august : july, windows: [], deliverables: [], sessions: [] })),
      gallery: vi.fn(async () => ok([])),
      overview: vi.fn(async () => ok(data)),
      harnessStatus: vi.fn(async () => ok({ wiring: { state: 'ready' as const }, consequence: null, origin: 'http://localhost:1' })),
      harnessOpen: vi.fn(async (_intent: string, id: string) => ok({ sessionId: `session-${id}`, preset: 'analysis' })),
      paneVisible: vi.fn(async (value: string) => ok({ screen: value })),
    } satisfies Partial<Bridge>;
    (globalThis as unknown as { foundry: Partial<Bridge> }).foundry = api;
    render(<App />);
    return api;
  }

  it('opens on 总览, the count in its heading and not on the tab, and 去处理 lands on that task', async () => {
    mount();
    await screen.findByRole('heading', { name: '等你处理（3）' });
    expect(screen.getByRole('button', { name: '总览' }).getAttribute('aria-current')).toBe('page');
    fireEvent.click(screen.getByRole('button', { name: /去处理：华东 8 月月结，期间未确认/ }));
    await screen.findByText('本地成果：华东 8 月月结');
    expect(screen.getByRole('button', { name: '工作区' }).getAttribute('aria-current')).toBe('page');
  });

  it('reads 总览 again on coming back to it, not on a timer', async () => {
    const api = mount();
    await screen.findByRole('heading', { name: '等你处理（3）' });
    const before = api.overview.mock.calls.length;
    fireEvent.click(screen.getByRole('button', { name: '成果库' }));
    fireEvent.click(screen.getByRole('button', { name: /^总览/ }));
    await waitFor(() => expect(api.overview.mock.calls.length).toBeGreaterThan(before));
  });

  it('reads 总览 again when a task changes in the workspace, so its to-dos follow', async () => {
    const api = mount();
    await screen.findByRole('heading', { name: '等你处理（3）' });
    fireEvent.click(screen.getByRole('button', { name: '工作区' }));
    const before = api.overview.mock.calls.length;
    window.dispatchEvent(new Event('fnd:task-changed'));
    await waitFor(() => expect(api.overview.mock.calls.length).toBeGreaterThan(before));
  });

  it('offers 60 秒看看它能做什么 until it is seen through, opening the 参考结果 board with its hints', async () => {
    const reference = task('c', '示例：华宸物业 8 月（参考结果）', '2026-08', { sample: 'reference' });
    let done = false;
    const api = {
      tasks: vi.fn(async () => ok([july, august, reference])),
      task: vi.fn(async (id: string) => ok({ task: [july, august, reference].find((row) => row.id === id)!, windows: [], deliverables: [], sessions: [] })),
      gallery: vi.fn(async () => ok([])),
      overview: vi.fn(async () => ok(data)),
      harnessStatus: vi.fn(async () => ok({ wiring: { state: 'ready' as const }, consequence: null, origin: 'http://localhost:1' })),
      harnessOpen: vi.fn(async (_intent: string, id: string) => ok({ sessionId: `session-${id}`, preset: 'analysis' })),
      paneVisible: vi.fn(async (value: string) => ok({ screen: value })),
      taskSampleReference: vi.fn(async () => ok({ id: reference.id, created: false })),
      firstLookGet: vi.fn(async () => ok({ done })),
      firstLookDone: vi.fn(async () => { done = true; return ok({ done }); }),
    } satisfies Partial<Bridge>;
    (globalThis as unknown as { foundry: Partial<Bridge> }).foundry = api as unknown as Partial<Bridge>;
    const { unmount } = render(<App />);
    const offer = (await screen.findByRole('heading', { name: '60 秒看看它能做什么' })).closest('section')!;
    expect(within(offer).getByText('打开示例的参考结果看板，看三处：点一个数看来源，拖一下收缴率，导出一页纸。')).toBeTruthy();
    fireEvent.click(within(offer).getByRole('button', { name: '开始看' }));
    await screen.findByText('本地成果：示例：华宸物业 8 月（参考结果）');
    expect(api.taskSampleReference).toHaveBeenCalledWith(false);
    expect(screen.getByRole('button', { name: '工作区' }).getAttribute('aria-current')).toBe('page');
    // The hints run on the reference's board only, and seeing them through ends the offer for good.
    fireEvent.click(screen.getByRole('button', { name: '看完了' }));
    await waitFor(() => expect(api.firstLookDone).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole('button', { name: '看完了' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /^总览/ }));
    await screen.findByRole('heading', { name: '等你处理（3）' });
    expect(screen.queryByRole('heading', { name: '60 秒看看它能做什么' })).toBeNull();
    unmount();
    render(<App />);
    await screen.findByRole('heading', { name: '等你处理（3）' });
    expect(screen.queryByRole('heading', { name: '60 秒看看它能做什么' })).toBeNull();
  });

  function mountFirstLook(extra: Partial<Bridge>) {
    const reference = task('c', '示例：华宸物业 8 月（参考结果）', '2026-08', { sample: 'reference' });
    const api = {
      tasks: vi.fn(async () => ok([july, august, reference])),
      task: vi.fn(async (id: string) => ok({ task: [july, august, reference].find((row) => row.id === id)!, windows: [], deliverables: [], sessions: [] })),
      gallery: vi.fn(async () => ok([])),
      overview: vi.fn(async () => ok(data)),
      harnessStatus: vi.fn(async () => ok({ wiring: { state: 'ready' as const }, consequence: null, origin: 'http://localhost:1' })),
      harnessOpen: vi.fn(async (_intent: string, id: string) => ok({ sessionId: `session-${id}`, preset: 'analysis' })),
      paneVisible: vi.fn(async (value: string) => ok({ screen: value })),
      taskSampleReference: vi.fn(async () => ok({ id: reference.id, created: false })),
      firstLookGet: vi.fn(async () => ok({ done: false })),
      firstLookDone: vi.fn(async () => ok({ done: true })),
      ...extra,
    } satisfies Partial<Bridge>;
    (globalThis as unknown as { foundry: Partial<Bridge> }).foundry = api as unknown as Partial<Bridge>;
    render(<App />);
    return { api, reference };
  }

  it('brings the offer back, saying why, when 不用了 could not be written down', async () => {
    mountFirstLook({ firstLookDone: vi.fn(async (): Promise<Answer<{ done: boolean }>> => ({ ok: false, refused: false, message: '磁盘已满' })) });
    const offer = (await screen.findByRole('heading', { name: '60 秒看看它能做什么' })).closest('section')!;
    fireEvent.click(within(offer).getByRole('button', { name: '不用了' }));
    expect((await screen.findByRole('alert')).textContent).toBe('没能记下你已看过，下次打开还会出现：磁盘已满');
    expect(screen.getByRole('heading', { name: '60 秒看看它能做什么' })).toBeTruthy();
  });

  it('stays where the manager went while the 参考结果 was still being built', async () => {
    let finish: (answer: Answer<{ id: string; created: boolean }>) => void = () => undefined;
    const { api, reference } = mountFirstLook({ taskSampleReference: vi.fn(() => new Promise<Answer<{ id: string; created: boolean }>>((resolve) => { finish = resolve; })) });
    const offer = (await screen.findByRole('heading', { name: '60 秒看看它能做什么' })).closest('section')!;
    fireEvent.click(within(offer).getByRole('button', { name: '开始看' }));
    await waitFor(() => expect(api.taskSampleReference).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole('button', { name: '成果库' }));
    finish({ ok: true, value: { id: reference.id, created: true } });
    await waitFor(() => expect(screen.getByRole('button', { name: '成果库' }).getAttribute('aria-current')).toBe('page'));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.getByRole('button', { name: '成果库' }).getAttribute('aria-current')).toBe('page');
    expect(screen.queryByRole('button', { name: '看完了', hidden: true })).toBeNull();
    // The offer still waits on 总览, and the built reference now opens at once.
    fireEvent.click(screen.getByRole('button', { name: /^总览/ }));
    const again = (await screen.findByRole('heading', { name: '60 秒看看它能做什么' })).closest('section')!;
    expect(api.firstLookDone).not.toHaveBeenCalled();
    expect(within(again).getByRole('button', { name: '开始看' })).toBeTruthy();
  });

  it('opens on the workspace when 设置 says so, and ⌘, opens 设置 from there', async () => {
    const preferences = { technical: false, brief_open: true, start: 'workspace' as const, samples_read: [] };
    const api = {
      tasks: vi.fn(async () => ok([july, august])),
      task: vi.fn(async (id: string) => ok({ task: id === august.id ? august : july, windows: [], deliverables: [], sessions: [] })),
      gallery: vi.fn(async () => ok([])),
      overview: vi.fn(async () => ok(data)),
      harnessStatus: vi.fn(async () => ok({ wiring: { state: 'ready' as const }, consequence: null, origin: 'http://localhost:1' })),
      harnessOpen: vi.fn(async (_intent: string, id: string) => ok({ sessionId: `session-${id}`, preset: 'analysis' })),
      paneVisible: vi.fn(async (value: string) => ok({ screen: value })),
      preferencesGet: vi.fn(async () => ok(preferences)),
      preferencesSet: vi.fn(async () => ok(preferences)),
    } satisfies Partial<Bridge>;
    (globalThis as unknown as { foundry: Partial<Bridge> }).foundry = api;
    render(<PreferencesProvider><App /></PreferencesProvider>);
    await waitFor(() => expect(screen.getByRole('button', { name: '工作区' }).getAttribute('aria-current')).toBe('page'));
    fireEvent.keyDown(window, { key: ',', metaKey: true });
    await screen.findByRole('heading', { name: '设置' });
    expect(screen.getByRole('button', { name: '设置' }).getAttribute('aria-current')).toBe('page');
    fireEvent.click(screen.getByRole('button', { name: '总览' }));
    await screen.findByRole('heading', { name: '等你处理（3）' });
  });

  it('leaves the 总览 tab out of a build that cannot read it', async () => {
    const { Shell } = await import('../src/components/Shell.js');
    render(<Shell screen="analysis" onScreen={() => {}} overview={false}><p>x</p></Shell>);
    expect(screen.queryByRole('button', { name: /^总览/ })).toBeNull();
    expect(screen.getByRole('button', { name: '工作区' })).toBeTruthy();
  });
});
