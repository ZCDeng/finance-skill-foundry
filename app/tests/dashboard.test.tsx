// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AnalysisRun, Bridge } from '../src/bridge.js';
import { DashboardView, useDashboard } from '../src/views/analysis/Dashboard.js';
import { cardSignature, DashboardPinContext, figureDraft, matchingRows, splitDisplay, type CardDraft, type Dashboard, type DashboardCard } from '../src/views/analysis/dashboard.js';
import { newerRun, TEMPLATES } from '../src/views/analysis/dashboardTemplates.js';
import { scenarioAt, scenarioBase } from '../src/views/analysis/dashboardScenario.js';
import { ASK_EVENT, ASK_PROMPTS } from '../src/views/guide/ask.js';
import { BusinessResultView } from '../src/views/analysis/BusinessResultView.js';
import type { FigureSourceContext } from '../src/views/analysis/figureSource.js';
import fixture from './fixtures/collection-health-run.json';

// A collection_health run on a property group's dashboard and ten city companies of its 11·城市公司明细表.
const health = fixture as unknown as AnalysisRun;

const template = (id: string) => TEMPLATES.find((row) => row.id === id)!;

const varianceRow = (metric: string, actual: string, baseline: string, contribution: string) => ({
  organization: '华东', period: '2026-08', unit: '万元', metric, actual, baseline, amount_change: contribution, profit_impact: contribution,
  contribution, ratio: '0', comparison_status: 'complete',
});
const variance: AnalysisRun = {
  id: 'e'.repeat(32), task_id: 't'.repeat(32), schema_version: 1, created_at: '2026-10-08T00:00:00Z', analysis_id: 'b'.repeat(32),
  execution_status: 'succeeded', reproducibility_status: 'reproducible', review_status: 'unreviewed', publication_status: 'draft', input_hashes: {}, engine: 'finance',
  result: {
    method: 'revenue_minus_cost_minus_expense', comparison: { actual_scenario: 'actual', baseline_scenario: 'budget' },
    columns: Object.keys(varianceRow('revenue', '1', '1', '1')).map((name) => ({ name, type: 'VARCHAR' })),
    rows: [varianceRow('revenue', '120', '100', '20'), varianceRow('cost', '70', '60', '-10'), varianceRow('expense', '20', '15', '-5'), varianceRow('profit', '30', '25', '5')],
    row_count: 4, truncated: false,
  } as AnalysisRun['result'],
};

function mount(handler: (command: string, spec: Record<string, unknown>) => unknown) {
  const financeCall = vi.fn(async (_task: string, command: string, spec?: Record<string, unknown>) => {
    try {
      return { ok: true, value: handler(command, spec ?? {}) };
    } catch (failure) {
      return { ok: false, message: (failure as Error).message };
    }
  });
  (globalThis as { foundry?: Partial<Bridge> }).foundry = { financeCall: financeCall as unknown as Bridge['financeCall'] };
  return financeCall;
}

/** A backend stand-in that keeps the board as the real one does: ids for new cards, a version per save. */
function boardBackend(initial: DashboardCard[] = []) {
  let version = 0;
  let board: Dashboard | null = initial.length ? { id: 'v0', parent_id: null, created_at: '2026-10-10T00:00:00Z', cards: initial } : null;
  const financeCall = mount((command, spec) => {
    if (command === 'dashboard-read') return { dashboard: board };
    if (command === 'dashboard-save') {
      if ((spec.parent_id ?? null) !== (board?.id ?? null)) throw new Error('the dashboard changed since it was read; read it again');
      version += 1;
      const cards = (spec.cards as (Omit<DashboardCard, 'id' | 'template' | 'note' | 'proposed_by' | 'accepted'> & Partial<DashboardCard>)[]).map((card, index) => ({
        template: null, note: null, proposed_by: 'manager' as const, ...card, id: card.id ?? `card-${version}-${index}`,
        accepted: card.state === 'accepted' ? card.accepted ?? { run_id: card.run_id, at: '2026-10-10T09:00:00Z' } : null,
      }));
      board = { id: `v${version}`, parent_id: board?.id ?? null, created_at: '2026-10-10T00:00:00Z', cards };
      return board;
    }
    throw new Error(`unexpected ${command}`);
  });
  return { financeCall, board: () => board };
}

const card = (overrides: Partial<DashboardCard>): DashboardCard => ({
  id: 'c1', kind: 'figure', title: '距生死线（本年账单收缴率）', state: 'pinned', run_id: health.id, template: 'collection', note: null, proposed_by: 'manager', accepted: null,
  select: { match: { entity: '集团', metric_key: 'collection_gap', scenario: '本期' }, column: 'value' },
  ...overrides,
});

afterEach(() => { cleanup(); delete (globalThis as { foundry?: unknown }).foundry; });

describe('the ready boards', () => {
  it('lays 回款健康 over the group\'s figures and ranks the detail table worst first', () => {
    const cards = template('collection').cards([health]);
    expect(cards.filter((row) => row.kind === 'figure').map((row) => row.title)).toEqual(['距生死线（本年账单收缴率）', '距生死线（综合收缴率，含清欠）', '生死线收缴率']);
    const rank = cards.find((row) => row.kind === 'rank')!;
    expect(rank.select).toMatchObject({ match: { metric_key: 'collection_gap', scenario: '本期', entity_origin: 'table' }, order: 'asc', reference: { value: '0', label: '生死线' } });
  });

  it('ranks 城市公司 only on measures at least two units carry, and shares the 距生死线 ranking with 回款健康', () => {
    const city = template('city').cards([health]);
    expect(city.map((row) => row.title)).toEqual(['风险雷达得分（从高到低）', '各主体距生死线（从低到高）', '减值占毛利（从高到低）']);
    const shared = template('collection').cards([health]).find((row) => row.kind === 'rank')!;
    expect(city.map(cardSignature)).toContain(cardSignature(shared));
  });

  it('draws 月度经营\'s profit bridge from a variance result and waits for a calculation when there is none', () => {
    const operating = template('operating').cards([variance]);
    expect(operating).toEqual([expect.objectContaining({ kind: 'bridge', run_id: variance.id, select: { match: {} } })]);
    expect(template('operating').cards([])).toEqual([]);
  });
});

describe('a figure pinned from a result', () => {
  const rows = [
    { metric_key: 'revenue', period: '2026-08', organization: '华东', actual: '120', budget: '100' },
    { metric_key: 'revenue', period: '2026-08', organization: '华南', actual: '80', budget: '90' },
  ];
  const run = { ...variance, id: 'r'.repeat(32), engine: 'sql', result: { columns: [], rows, row_count: 2, truncated: false } } as AnalysisRun;

  it('names its row by what the row measures, for whom and when', () => {
    const draft = figureDraft(run, rows[1], 'actual', '收入 · 华南')!;
    expect(draft.select).toEqual({ match: { metric_key: 'revenue', organization: '华南', period: '2026-08' }, column: 'actual' });
    expect(matchingRows(rows, draft.select.match)).toEqual([rows[1]]);
  });

  it('is refused when nothing tells its row from the others', () => {
    const twins = { ...run, result: { ...run.result!, rows: [rows[0], { ...rows[0] }] } } as AnalysisRun;
    expect(figureDraft(twins, rows[0], 'actual', '收入')).toBeNull();
  });

  it('splits a figure from the unit its run wrote beside it', () => {
    expect(splitDisplay('-3.22 个百分点')).toEqual({ figure: '-3.22', unit: '个百分点' });
    expect(splitDisplay('+1,234.50 万元')).toEqual({ figure: '1,234.50', unit: '万元' });
  });

  it('offers 钉到看板 from a KPI card\'s source and pins the KPI there', async () => {
    const pin = vi.fn(async (_draft: CardDraft) => '已钉到看板，等你在「看板」页认可。');
    const source: FigureSourceContext = { run, datasets: [], superseded: new Set() };
    render(<DashboardPinContext.Provider value={{ pin }}><BusinessResultView run={run} source={source} /></DashboardPinContext.Provider>);
    const cards = screen.getByLabelText('关键指标');
    fireEvent.click(within(cards).getAllByRole('button', { name: /实际 .*查看来源/ })[0]);
    fireEvent.click(await screen.findByRole('button', { name: /钉到看板/ }));
    await waitFor(() => expect(pin).toHaveBeenCalledTimes(1));
    expect(pin.mock.calls[0][0]).toMatchObject({ kind: 'figure', state: 'pinned', run_id: run.id, select: { column: 'actual' } });
    expect(await screen.findByText('已钉到看板，等你在「看板」页认可。')).toBeTruthy();
  });
});

describe('the board', () => {
  function Board(extra: Partial<Parameters<typeof DashboardView>[0]>) {
    const state = useDashboard('t');
    return <DashboardView state={state} runs={[health, variance]} analyses={[]} datasets={[]} readOnly={false} {...extra} />;
  }
  const view = async (extra: Partial<Parameters<typeof DashboardView>[0]> = {}) => {
    render(<Board {...extra} />);
    await waitFor(() => expect(screen.queryByText('正在读取看板…')).toBeNull());
  };

  it('starts from a template and saves its cards as waiting for the manager', async () => {
    const backend = boardBackend();
    await view();
    expect(screen.getByRole('heading', { name: '还没有看板' })).toBeTruthy();
    const row = screen.getByText('回款健康').closest('li')!;
    fireEvent.click(within(row).getByRole('button', { name: /添加 5 张卡/ }));
    await waitFor(() => expect(backend.board()?.cards).toHaveLength(5));
    expect(backend.board()!.cards.every((row) => row.state === 'pinned')).toBe(true);
    // The 回款情景 card is a what-if: on the board, never waiting to be accepted.
    expect(await screen.findByText('共 5 张 · 已认可 0 张 · 待认可 4 张 · 情景 1 张')).toBeTruthy();
    // A figure card opens its source like the result page does.
    const gap = screen.getByRole('article', { name: '距生死线（本年账单收缴率）' });
    expect(within(gap).getByRole('button', { name: /查看来源/ })).toBeTruthy();
    expect(within(gap).getByText('红')).toBeTruthy();
    expect(screen.getByRole('img', { name: /^各主体距生死线（从低到高）：兰州城市公司 -6.94/ })).toBeTruthy();
  });

  it('lets the manager accept one card, and all of them after a confirmation', async () => {
    const backend = boardBackend([card({}), card({ id: 'c2', kind: 'rank', title: '风险雷达得分（从高到低）', template: 'city',
      select: { match: { metric_key: 'risk_score', scenario: '本期', entity_origin: 'table' }, label: 'entity', column: 'value', order: 'desc', limit: 10 } })]);
    await view();
    fireEvent.click(within(screen.getByRole('article', { name: '距生死线（本年账单收缴率）' })).getByRole('button', { name: '认可' }));
    await waitFor(() => expect(backend.board()?.cards[0].state).toBe('accepted'));
    fireEvent.click(await screen.findByRole('button', { name: '全部认可（1 张）' }));
    fireEvent.click(await screen.findByRole('button', { name: '全部认可' }));
    await waitFor(() => expect(backend.board()?.cards.map((row) => row.state)).toEqual(['accepted', 'accepted']));
  });

  it('shows the assistant\'s proposals apart until the manager pins them', async () => {
    const backend = boardBackend([card({ state: 'explore', proposed_by: 'assistant', note: '集团已经低于生死线' })]);
    await view();
    const proposals = screen.getByRole('region', { name: '助手提议' });
    expect(within(proposals).getByText('集团已经低于生死线')).toBeTruthy();
    fireEvent.click(within(proposals).getByRole('button', { name: /钉住/ }));
    await waitFor(() => expect(backend.board()?.cards[0].state).toBe('pinned'));
  });

  it('marks a card read from a replaced file and offers no change on an archived task', async () => {
    boardBackend([card({ state: 'accepted', accepted: { run_id: health.id, at: '2026-10-10T09:00:00Z' } })]);
    const read = { ...health, bindings: { kpi: 'd'.repeat(32) } } as AnalysisRun;
    await view({ runs: [read], superseded: ['d'.repeat(32)], readOnly: true });
    const gap = screen.getByRole('article', { name: '距生死线（本年账单收缴率）' });
    expect(within(gap).getByText('资料已更新，待重算')).toBeTruthy();
    expect(within(gap).queryByRole('button', { name: /认可|移除/ })).toBeNull();
  });

  it('moves a template card to a newer result of the same calculation and asks for acceptance again', async () => {
    const backend = boardBackend([card({ state: 'accepted', accepted: { run_id: health.id, at: '2026-10-10T09:00:00Z' } })]);
    const newer = { ...health, id: 'n'.repeat(32), created_at: '2026-10-10T08:00:00Z' } as AnalysisRun;
    expect(newerRun(card({}), [health, newer])?.id).toBe(newer.id);
    expect(newerRun(card({ template: null }), [health, newer])).toBeUndefined();
    await view({ runs: [health, newer] });
    fireEvent.click(screen.getByRole('button', { name: '换成新结果（1 张）' }));
    await waitFor(() => expect(backend.board()?.cards[0]).toMatchObject({ run_id: newer.id, state: 'pinned' }));
  });

  it('reads the board again and makes the change once more when it changed since it was read', async () => {
    const backend = boardBackend([card({})]);
    const { result } = renderHook(() => useDashboard('t'));
    await waitFor(() => expect(result.current.loaded).toBe(true));
    // The assistant proposed a card in between: the board on disk moved on.
    const { financeCall } = backend;
    await financeCall('t', 'dashboard-save', { parent_id: 'v0', cards: [card({}), card({ id: undefined, kind: 'rank', title: '风险雷达', template: 'city',
      select: { match: { metric_key: 'risk_score', scenario: '本期', entity_origin: 'table' }, label: 'entity', column: 'value', order: 'desc', limit: 10 } })] });
    await act(async () => { expect(await result.current.pin({ kind: 'bridge', title: '利润桥', state: 'pinned', run_id: variance.id, select: { match: {} } })).toMatch(/已钉到看板/); });
    expect(backend.board()?.cards.map((row) => row.kind)).toEqual(['figure', 'rank', 'bridge']);
  });
});

describe('the board on newer files and from last month', () => {
  const newer = { ...health, id: 'n'.repeat(32), created_at: '2026-10-10T08:00:00Z' } as AnalysisRun;
  const recomputed = (changed: boolean) => ({
    at: '2026-10-10T09:00:00Z', from_run_id: health.id, was_accepted: true, months: ['2026-08', '2026-09'] as [string, string],
    before: { value: '-3.22', display: '-3.22 个百分点', level: 'red', unit: '百分点' }, after: { value: '-2.94', display: '-2.94 个百分点', level: 'red', unit: '百分点' },
    changed, change: changed ? '级别 黄 → 红' : '+0.28 个百分点', adjusted: ['已过月数 8 → 9'], manual: [], carried_from: null,
  });
  function Board({ canRecompute = true, onRecomputed }: { canRecompute?: boolean; onRecomputed?(): void }) {
    const state = useDashboard('t', { canRecompute, onRecomputed });
    return <DashboardView state={state} runs={[health, newer]} analyses={[]} datasets={[]} readOnly={false} />;
  }

  it('recomputes the cards whose files are newer as soon as the board is read, and says what moved', async () => {
    let board: Dashboard = { id: 'v0', parent_id: null, created_at: '2026-10-10T00:00:00Z',
      cards: [card({ state: 'accepted', accepted: { run_id: health.id, at: '2026-10-09T09:00:00Z' } })] };
    const financeCall = mount((command, spec) => {
      if (command === 'dashboard-read') return { dashboard: board, recompute: { ready: board.cards[0].run_id === health.id ? 1 : 0 } };
      if (command === 'dashboard-recompute') {
        expect(spec).toEqual({ parent_id: 'v0' });
        board = { ...board, id: 'v1', parent_id: 'v0', cards: [card({ run_id: newer.id, recomputed: recomputed(true) })] };
        return { dashboard: board, recomputed: ['c1'], failed: [] };
      }
      throw new Error(`unexpected ${command}`);
    });
    const onRecomputed = vi.fn();
    render(<Board onRecomputed={onRecomputed} />);
    expect(await screen.findByText('资料有更新，已按新资料重算 1 张卡，其中 1 张有明显变化，等你重新认可。')).toBeTruthy();
    const gap = screen.getByRole('article', { name: '距生死线（本年账单收缴率）' });
    expect(within(gap).getByText('按 2026 年 9 月的资料重算')).toBeTruthy();
    expect(within(gap).getByText('有变化')).toBeTruthy();
    expect(within(gap).getByText('上次 -3.22 个百分点 · 级别 黄 → 红')).toBeTruthy();
    expect(within(gap).getByText('已过月数 8 → 9')).toBeTruthy();
    expect(onRecomputed).toHaveBeenCalledTimes(1);
    expect(financeCall.mock.calls.filter(([, command]) => command === 'dashboard-recompute')).toHaveLength(1);
  });

  it('leaves an archived task\'s board as it was read', async () => {
    const financeCall = mount((command) => {
      if (command === 'dashboard-read') return { dashboard: { id: 'v0', parent_id: null, created_at: '2026-10-10T00:00:00Z', cards: [card({})] }, recompute: { ready: 1 } };
      throw new Error(`unexpected ${command}`);
    });
    render(<Board canRecompute={false} />);
    expect(await screen.findByRole('article', { name: '距生死线（本年账单收缴率）' })).toBeTruthy();
    expect(financeCall.mock.calls.map(([, command]) => command)).not.toContain('dashboard-recompute');
  });

  it('says why a card could not be recomputed', async () => {
    mount((command) => {
      if (command === 'dashboard-read') {
        return { dashboard: { id: 'v0', parent_id: null, created_at: '2026-10-10T00:00:00Z',
          cards: [card({ recompute_failed: { at: '2026-10-10T09:00:00Z', reason: '计算里写着 2026-08，换到 2026-09 会算错，要你重新计算' } })] }, recompute: { ready: 0 } };
      }
      throw new Error(`unexpected ${command}`);
    });
    render(<Board />);
    expect(await screen.findByText('没能按新资料重算：计算里写着 2026-08，换到 2026-09 会算错，要你重新计算')).toBeTruthy();
  });

  it('carries last month\'s board onto an empty one and lists what is still missing elsewhere', async () => {
    let board: Dashboard | null = null;
    const financeCall = mount((command, spec) => {
      if (command === 'dashboard-read') return { dashboard: board, recompute: { ready: 0 } };
      if (command === 'dashboard-carry' && !spec.from_task_id) {
        return { offers: [
          { task_id: 'aug', title: '华宸 8 月月结', period: '2026-08', cards: 3, ready: 3, missing: [] },
          { task_id: 'jul', title: '华宸 7 月月结', period: '2026-07', cards: 2, ready: 0, missing: ['01·核心指标看板'] },
        ] };
      }
      if (command === 'dashboard-carry') {
        expect(spec).toEqual({ from_task_id: 'aug' });
        board = { id: 'v1', parent_id: null, created_at: '2026-10-10T00:00:00Z',
          cards: [card({ run_id: newer.id, recomputed: { ...recomputed(false), carried_from: { task_id: 'aug', title: '华宸 8 月月结' } } })] };
        return { dashboard: board, carried: ['c1'], failed: [{ card_id: 'c2', title: '利润桥', reason: '这个任务里还没有：预算' }] };
      }
      throw new Error(`unexpected ${command}`);
    });
    render(<Board />);
    const offers = await screen.findByRole('region', { name: '从别的任务带过来' });
    const july = within(offers).getByText('华宸 7 月月结 · 2026 年 7 月').closest('li')!;
    expect(within(july).getByText('还缺：01·核心指标看板。先加入资料并确认表结构。')).toBeTruthy();
    expect((within(july).getByRole('button', { name: /带过来/ }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(within(offers).getByRole('button', { name: /带过来并重算（3 张）/ }));
    expect(await screen.findByText('已从「华宸 8 月月结」带过来 1 张卡，按这个任务的资料重算好了，没有明显变化，等你认可。')).toBeTruthy();
    expect(screen.getByText('「利润桥」：这个任务里还没有：预算')).toBeTruthy();
    const gap = screen.getByRole('article', { name: '距生死线（本年账单收缴率）' });
    expect(within(gap).getByText('按 2026 年 9 月的资料重算')).toBeTruthy();
    expect(financeCall.mock.calls.filter(([, command]) => command === 'dashboard-carry')).toHaveLength(2);
  });
});

describe('the 回款情景 card and asking the assistant for cards', () => {
  // The group's lines with the last twelve months' revenue the cash lines are counted over.
  const rows = [...(health.result!.rows as Record<string, unknown>[]), {
    entity: '集团', entity_origin: 'declared', metric_key: 'ttm_revenue', metric_label: '近12个月营业收入', scenario: '本期', value: '10000',
    unit: '万元', display_value: '10,000.00 万元', level: null, level_label: null, estimate: false, formula: '近12个月营业收入', note: '',
  }];
  const run = { ...health, id: 's'.repeat(32), result: { ...health.result!, rows, params: { vat_factor: '1.06', gap_yellow_below: '0.03' } } } as AnalysisRun;
  const match = { entity: '集团', scenario: '本期' };

  it('works out the gap, a year\'s cash operating profit and collections from the run\'s own lines', () => {
    const base = scenarioBase(run, match)!;
    // The rate the run's gap was taken at: 生死线 91.14% less 3.22 points.
    expect(base.current).toBeCloseTo(87.9185, 4);
    const at = scenarioAt(base, 92);
    expect(at.gap).toBeCloseTo(0.8574, 4);
    expect(at.level).toBe('yellow');
    expect(at.profit).toBeCloseTo(85.74, 2);
    expect(at.collected).toBeCloseTo(((92 - base.current) / 100) * 10000 * 1.06, 6);
    expect(scenarioAt(base, base.current).collected).toBeCloseTo(0, 9);
    // One entity's lines or none: the whole table, or a run of another kind, carries no scenario.
    expect(scenarioBase(run, { scenario: '本期' })).toBeNull();
    expect(scenarioBase(variance, {})).toBeNull();
  });

  it('moves the rate by hand, flags itself as a what-if and is never offered for acceptance', async () => {
    const scenario = template('collection').cards([run]).find((row) => row.kind === 'scenario')!;
    expect(scenario.select).toEqual({ match });
    boardBackend([card({ id: 's1', kind: 'scenario', title: scenario.title, run_id: run.id, select: scenario.select })]);
    function Board() {
      const state = useDashboard('t');
      return <DashboardView state={state} runs={[run]} analyses={[]} datasets={[]} readOnly={false} />;
    }
    render(<Board />);
    const article = await screen.findByRole('article', { name: '回款情景：收缴率变了会怎样' });
    expect(within(article).getByText('情景，不是实际数')).toBeTruthy();
    expect(within(article).getByText('情景')).toBeTruthy();
    expect(within(article).queryByRole('button', { name: '认可' })).toBeNull();
    expect(screen.queryByRole('button', { name: /全部认可/ })).toBeNull();
    expect(screen.getByText('共 1 张 · 已认可 0 张 · 待认可 0 张 · 情景 1 张')).toBeTruthy();
    // At the run's own rate the card reads as the run does.
    const rate = within(article).getByRole('textbox', { name: '假设收缴率' }) as HTMLInputElement;
    expect(rate.value).toBe('87.92');
    expect(within(article).getByText('低于生死线')).toBeTruthy();
    fireEvent.focus(rate);
    fireEvent.change(rate, { target: { value: '92' } });
    expect(within(article).getByText('+0.86 个百分点')).toBeTruthy();
    expect(within(article).getByText('贴近生死线')).toBeTruthy();
    expect(within(article).getByText('86 万元')).toBeTruthy();
    expect(within(article).getByText('+433 万元')).toBeTruthy();
    // The run's own lines still open to their source; back at the run's rate, nothing is moved.
    expect(within(article).getAllByRole('button', { name: /查看来源/ }).length).toBeGreaterThanOrEqual(3);
    fireEvent.click(within(article).getByRole('button', { name: '回到这次计算的收缴率' }));
    expect(within(article).getByText('低于生死线')).toBeTruthy();
  });

  it('puts a question for the assistant into the conversation, unsent', async () => {
    boardBackend([card({})]);
    const heard = vi.fn();
    const listen = (event: Event) => heard((event as CustomEvent).detail);
    window.addEventListener(ASK_EVENT, listen);
    function Board() {
      const state = useDashboard('t');
      return <DashboardView state={state} runs={[health]} analyses={[]} datasets={[]} readOnly={false} />;
    }
    render(<Board />);
    fireEvent.click(await screen.findByRole('button', { name: '加一张回款情景卡' }));
    expect(heard).toHaveBeenCalledWith(ASK_PROMPTS['collection-scenario']);
    expect(screen.getByRole('button', { name: '提议几张卡' })).toBeTruthy();
    window.removeEventListener(ASK_EVENT, listen);
  });
});
