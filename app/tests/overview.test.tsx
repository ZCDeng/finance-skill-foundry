// @vitest-environment jsdom
import { useState } from 'react';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AnalysisRun, AnalysisState, Answer, Bridge, Overview as OverviewData, Preferences, TaskRow } from '../src/bridge.js';
import fixture from './fixtures/collection-health-run.json';
import { Overview } from '../src/views/Overview.js';
import { App } from '../src/App.js';
import { PreferencesProvider } from '../src/components/Preferences.js';

vi.mock('../src/views/Analysis.js', () => ({
  Analysis: ({ task, tour, section }: { task: TaskRow | null; tour?: { onEnd(): void }; section?: string }) => {
    const [shown] = useState(task?.title ?? '');
    return <><p>{task ? `本地成果：${task.title}` : `从问题开始${shown}`}</p>{task && section ? <p>{`在这一步：${section}`}</p> : null}
      {tour ? <button type="button" onClick={tour.onEnd}>看完了</button> : null}</>;
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
const props = { data, loading: false, error: '', fresh: false, recent: [], onRefresh: noop, onOpen: vi.fn(), onOpenStep: vi.fn(),
  onNewQuestion: vi.fn(), onChecklist: vi.fn(), onGuide: vi.fn(), onLibrary: vi.fn() };

afterEach(() => { cleanup(); vi.clearAllMocks(); sessionStorage.clear(); delete (globalThis as unknown as { foundry?: Bridge }).foundry; });

describe('总览', () => {
  const mainCard = () => screen.getByText('当前任务').closest('section')!;

  it('opens on the task worked on last: its six steps with a line each, and a button to the step that waits', () => {
    const work = { runs: [], cards: [], drafts: 0, datasets: 2 };
    const rows = [{ ...data.tasks[0], work, active_at: '2026-10-02T09:00:00Z' }, { ...data.tasks[1], work, active_at: '2026-10-05T09:00:00Z' }];
    render(<Overview {...props} data={{ ...data, tasks: rows }} />);
    const card = mainCard();
    expect(within(card).getByRole('heading', { level: 2 }).textContent).toBe('华东 7 月月结 · 2026 年 7 月');
    expect(within(card).getByText('账：带保留可用')).toBeTruthy();
    // Each step says its state and what it holds, in words as well as colour.
    expect(within(card).getByRole('button', { name: /^1 资料（月结），已完成：2 份资料，表结构都已确认$/ })).toBeTruthy();
    expect(within(card).getByRole('button', { name: /^3 勾稽（月结），待处理/ })).toBeTruthy();
    fireEvent.click(within(card).getByRole('button', { name: /^5 经营分析/ }));
    expect(props.onOpenStep).toHaveBeenLastCalledWith(july, 'operations');
    // 继续 goes to the first step that waits, and says why.
    fireEvent.click(within(card).getByRole('button', { name: '继续：第 3 步 勾稽' }));
    expect(props.onOpenStep).toHaveBeenLastCalledWith(july, 'close');
    expect(within(card).getByText('应收滚动：待外部确认，差额 1200', { selector: '.fnd-cockpit__next span' })).toBeTruthy();
  });

  it('lists only the current task\'s to-dos, each with its step, three before the rest fold', () => {
    const todo = [...data.tasks[0].todo, { kind: 'controls' as const, text: '还没有确认的勾稽控制', target: 'controls' },
      { kind: 'review' as const, text: '还没有文稿', target: 'drafts' }];
    render(<Overview {...props} data={{ ...data, tasks: [{ ...data.tasks[0], todo }, data.tasks[1]] }} />);
    const card = mainCard();
    expect(within(card).getByRole('heading', { name: '等你处理（4）' })).toBeTruthy();
    expect(within(card).queryByText('应收滚动：待外部确认，差额 1200')).toBeNull();
    const shown = card.querySelector('.fnd-cockpit__todos > ul')!;
    expect(Array.from(shown.querySelectorAll('.fnd-overview__tag')).map((node) => node.textContent)).toEqual(['2 范围', '1 资料', '3 勾稽']);
    expect(within(card).getByText('其余 1 条')).toBeTruthy();
    fireEvent.click(within(card).getByRole('button', { name: '去处理：期间未确认' }));
    expect(props.onOpen).toHaveBeenCalledWith(august, 'scope');
  });

  it('switches the main card from its pills or another task\'s row, and keeps the choice while away', () => {
    const { unmount } = render(<Overview {...props} />);
    expect(within(mainCard()).getByRole('heading', { level: 2 }).textContent).toContain('华东 8 月月结');
    const switcher = screen.getByRole('group', { name: '切换任务' });
    expect(within(switcher).getByRole('button', { name: '华东 8 月月结' }).getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(within(switcher).getByRole('button', { name: '华东 7 月月结' }));
    expect(within(mainCard()).getByRole('heading', { level: 2 }).textContent).toContain('华东 7 月月结');
    // The other task is a row under 其他进行中的任务, its six steps small; a row makes it the main card.
    const others = screen.getByRole('heading', { name: '其他进行中的任务（1）' }).closest('section')!;
    fireEvent.click(within(others).getByRole('button', { name: /^华东 8 月月结/ }));
    expect(within(mainCard()).getByRole('heading', { level: 2 }).textContent).toContain('华东 8 月月结');
    fireEvent.click(within(screen.getByRole('group', { name: '切换任务' })).getByRole('button', { name: '华东 7 月月结' }));
    unmount();
    render(<Overview {...props} />);
    expect(within(mainCard()).getByRole('heading', { level: 2 }).textContent).toContain('华东 7 月月结');
  });

  it('shows another task\'s six steps in words as well as colour', () => {
    const work = { runs: [], cards: [], drafts: 0, datasets: 2 };
    render(<Overview {...props} data={{ ...data, tasks: data.tasks.map((row) => ({ ...row, work })) }} />);
    const others = screen.getByRole('heading', { name: '其他进行中的任务（1）' }).closest('section')!;
    const row = within(others).getByRole('button', { name: /^华东 7 月月结/ });
    expect(within(row).getByRole('img').getAttribute('aria-label'))
      .toBe('1 资料已完成，2 范围已完成，3 勾稽待处理，4 财务分析未开始，5 经营分析未开始，6 汇报未开始');
    expect(row.textContent).toContain('需要复核：计算完成，但有 1 项来源冲突');
  });

  it('places 财务分析, 经营分析 and 汇报 by the same rules as the task\'s steps', () => {
    const run = (extra: Record<string, unknown>) => ({ execution_status: 'succeeded', engine: 'finance', role: '', columns: ['actual'], rows: true, outputs: false, ...extra });
    const work = { runs: [run({ label: '管理损益', analysis_id: 'm' }), run({ scenario_kind: 'collection_health', label: '回款健康', analysis_id: 'h' }), run({ rows: false })],
      cards: [{ state: 'pinned', kind: 'figure' }, { state: 'pinned', kind: 'scenario' }], drafts: 1, datasets: 1 };
    render(<Overview {...props} data={{ ...data, tasks: [{ ...data.tasks[1], work, health: { run_id: 'h', levels: { red: 1, green: 4 } } }] }} />);
    const names = within(mainCard()).getAllByRole('button', { name: /^\d / }).map((button) => button.getAttribute('aria-label'));
    // A pinned card waits on 认可; a what-if card never does.
    expect(names).toEqual([
      '1 资料（月结），已完成：1 份资料，表结构都已确认', expect.stringMatching(/^2 范围（月结），已完成/), expect.stringMatching(/^3 勾稽（月结），待处理/),
      '4 财务分析（财务分析），已完成：已算：管理损益', '5 经营分析（经营分析），已完成：回款健康：风险雷达 1 个红色',
      '6 汇报（汇报），待处理：看板 2 张卡，1 张待认可；文稿 1 版',
    ]);
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

  it('with no task at all, three ways in are the page: a minute\'s look, the example, and one\'s own files', () => {
    const offer = { busy: false, onStart: vi.fn(), onDismiss: vi.fn() };
    const onSample = vi.fn();
    render(<Overview {...props} data={{ schema_version: 1, tasks: [], todo_count: 0 }} fresh onSample={onSample} firstLook={offer} />);
    expect(screen.getByRole('heading', { name: '从这里开始' })).toBeTruthy();
    expect(screen.getAllByRole('heading', { level: 3 }).map((node) => node.textContent)).toEqual(['60 秒看看它能做什么', '用示例练一遍', '带上自己的资料开始']);
    expect(screen.queryByText('当前任务')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '开始看' }));
    expect(offer.onStart).toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '用示例练习' }));
    expect(onSample).toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '问一个新问题' }));
    expect(props.onNewQuestion).toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '第一次使用' }));
    expect(props.onGuide).toHaveBeenCalled();
  });

  it('says nothing holds the close when nothing does', () => {
    render(<Overview {...props} data={{ ...data, todo_count: 0, tasks: data.tasks.map((row) => ({ ...row, todo: [] })) }} />);
    expect(within(mainCard()).getByText('没有挡住月结的事项。')).toBeTruthy();
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

describe('总览 reads the current task\'s own results', () => {
  const ok = <T,>(value: T): Answer<T> => ({ ok: true, value });
  const run = { ...(fixture as unknown as AnalysisRun), task_id: august.id };
  const figure = (id: string, title: string, entity: string, state: 'accepted' | 'pinned' | 'explore') => ({ id, kind: 'figure', title, state, run_id: run.id,
    template: 'collection', note: null, proposed_by: 'manager', accepted: state === 'accepted' ? { run_id: run.id, at: '2026-10-10T09:00:00Z' } : null,
    select: { match: { entity, metric_key: 'collection_gap', scenario: '本期' }, column: 'value' } });
  function mountReads(cards: object[] | null, preferences: Partial<Preferences> = {}) {
    let saved: Preferences = { technical: false, brief_open: true, start: 'overview', samples_read: [], skipped_steps: {}, people: [], current_person: '', tried: [], tips_open: true, ...preferences };
    const preferencesSet = vi.fn(async (patch: Partial<Preferences>) => ok(saved = { ...saved, ...patch }));
    const state = { task_id: august.id, datasets: [{ id: 'd'.repeat(32), name: '套表' }], analyses: [], runs: [run], drafts: [], methods: [] };
    (globalThis as unknown as { foundry: Partial<Bridge> }).foundry = {
      analysisState: vi.fn(async () => ok(state as unknown as AnalysisState)),
      financeCall: vi.fn(async (_task: string, command: string) => command === 'dashboard-read'
        ? ok({ dashboard: cards ? { id: 'v1', parent_id: null, created_at: '2026-10-10T00:00:00Z', cards } : null })
        : command === 'month-brief' ? ok({ schema_version: 1, signature: 's', worded: null, lines: [{ key: 'risk', label: '风险', text: '大连风险最高。', parts: [{ text: '大连风险最高。' }] }] })
          : ok({})) as unknown as Bridge['financeCall'],
      preferencesGet: vi.fn(async () => ok(saved)),
      preferencesSet,
    };
    render(<PreferencesProvider><Overview {...props} /></PreferencesProvider>);
    return preferencesSet;
  }

  it('shows the board\'s accepted figures first, then the pinned, four at most, each opening to its source', async () => {
    mountReads([figure('c1', '大连距生死线', '大连城市公司', 'pinned'), figure('c2', '集团距生死线', '集团', 'accepted'),
      figure('c3', '提议的卡', '集团', 'explore'), { ...figure('c4', '回款情景', '集团', 'pinned'), kind: 'scenario' }]);
    const section = (await screen.findByRole('heading', { name: '关键数字' })).closest('section')!;
    const tiles = within(section).getAllByRole('listitem');
    expect(tiles.map((tile) => tile.querySelector('.fnd-cockpit__figure-title')!.textContent)).toEqual(['集团距生死线', '大连距生死线']);
    expect(within(tiles[0]).getByText('-3.22 个百分点')).toBeTruthy();
    expect(within(tiles[1]).getByText('待认可')).toBeTruthy();
    expect(within(tiles[0]).getByRole('button', { name: /查看来源/ })).toBeTruthy();
    // 本月三句话 is the task's own, read for this task.
    expect(await screen.findByText('大连风险最高。')).toBeTruthy();
  });

  it('with nothing on the board, says where the figures come from and opens the board', async () => {
    mountReads(null);
    const section = (await screen.findByRole('heading', { name: '关键数字' })).closest('section')!;
    expect(within(section).getByText(/到第 6 步看板钉几张卡/)).toBeTruthy();
    fireEvent.click(within(section).getByRole('button', { name: '打开看板' }));
    expect(props.onOpen).toHaveBeenCalledWith(august, 'dashboard');
  });

  it('offers three features not used yet, none a real task\'s records or the preferences show, and keeps it folded', async () => {
    const preferencesSet = mountReads(null, { tried: ['source'] });
    const tries = (await screen.findByText('还没试过')).closest('details')!;
    expect(Array.from(tries.querySelectorAll('.fnd-cockpit__try-title')).map((node) => node.textContent)).toEqual(['回款情景', '倒推到目标', '收缴率下钻到账单']);
    fireEvent.click(within(tries).getByRole('button', { name: '试一下：回款情景' }));
    expect(props.onOpen).toHaveBeenCalledWith(august, 'operations');
    tries.open = false;
    fireEvent(tries, new Event('toggle'));
    await waitFor(() => expect(preferencesSet).toHaveBeenCalledWith({ tips_open: false }));
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

  it('opens on 总览, the main card\'s to-dos counted in its heading and not on the tab, and 去处理 lands on that task', async () => {
    mount();
    await screen.findByRole('heading', { name: '等你处理（2）' });
    expect(screen.getByRole('button', { name: '总览' }).getAttribute('aria-current')).toBe('page');
    fireEvent.click(screen.getByRole('button', { name: '去处理：期间未确认' }));
    await screen.findByText('本地成果：华东 8 月月结');
    expect(screen.getByRole('button', { name: '工作区' }).getAttribute('aria-current')).toBe('page');
  });

  it('做一次经营分析 makes a task and opens it on 经营分析, since 月结 is not the only use', async () => {
    const api = mount();
    const made = task('d', '经营分析', '');
    const rows = [july, august];
    Object.assign(api, {
      tasks: vi.fn(async () => ok(rows)),
      task: vi.fn(async (id: string) => ok({ task: [...rows].find((row) => row.id === id)!, windows: [], deliverables: [], sessions: [] })),
      taskNew: vi.fn(async (title: string) => { rows.push({ ...made, title }); return ok({ id: made.id }); }),
    });
    fireEvent.click(await screen.findByRole('button', { name: '做一次经营分析' }));
    await waitFor(() => expect((api as unknown as { taskNew: ReturnType<typeof vi.fn> }).taskNew).toHaveBeenCalledWith('经营分析', ''));
    await screen.findByText('本地成果：经营分析');
    expect(screen.getByText('在这一步：operations')).toBeTruthy();
  });

  it('reads 总览 again on coming back to it, not on a timer', async () => {
    const api = mount();
    await screen.findByRole('heading', { name: '等你处理（2）' });
    const before = api.overview.mock.calls.length;
    fireEvent.click(screen.getByRole('button', { name: '成果库' }));
    fireEvent.click(screen.getByRole('button', { name: /^总览/ }));
    await waitFor(() => expect(api.overview.mock.calls.length).toBeGreaterThan(before));
  });

  it('reads 总览 again when a task changes in the workspace, so its to-dos follow', async () => {
    const api = mount();
    await screen.findByRole('heading', { name: '等你处理（2）' });
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
    await screen.findByRole('heading', { name: '等你处理（2）' });
    expect(screen.queryByRole('heading', { name: '60 秒看看它能做什么' })).toBeNull();
    unmount();
    render(<App />);
    await screen.findByRole('heading', { name: '等你处理（2）' });
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
    const preferences = { technical: false, brief_open: true, start: 'workspace' as const, samples_read: [], skipped_steps: {}, people: [], current_person: '', tried: [], tips_open: true };
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
    await screen.findByRole('heading', { name: '等你处理（2）' });
  });

  it('leaves the 总览 tab out of a build that cannot read it', async () => {
    const { Shell } = await import('../src/components/Shell.js');
    render(<Shell screen="analysis" onScreen={() => {}} overview={false}><p>x</p></Shell>);
    expect(screen.queryByRole('button', { name: /^总览/ })).toBeNull();
    expect(screen.getByRole('button', { name: '工作区' })).toBeTruthy();
  });
});
