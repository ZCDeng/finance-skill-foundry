// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AnalysisRun, Bridge } from '../src/bridge.js';
import { DashboardView, useDashboard } from '../src/views/analysis/Dashboard.js';
import type { Dashboard, DashboardCard } from '../src/views/analysis/dashboardModel.js';
import { buildSnapshot } from '../src/views/analysis/dashboardSnapshot.js';
import { rankItems } from '../src/views/analysis/dashboardViews.js';
import { profitBridges } from '../src/views/analysis/RunPanel.js';
import type { FigureSourceContext } from '../src/views/analysis/figureSourceInfo.js';
import { errorText } from '../src/views/analysis/shared.js';
import { normalizeSnapshot, snapshotFileName, snapshotHtml } from '../electron/reports/dashboard-snapshot.js';
import fixture from './fixtures/collection-health-run.json';
import { press } from './press.js';

// A collection_health run on a property group's dashboard and ten city companies of its 11·城市公司明细表.
const health = { ...(fixture as unknown as AnalysisRun), bindings: { kpi: 'd'.repeat(32) }, input_hashes: { kpi: 'a1b2c3d4e5f6a7b8' } } as AnalysisRun;
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

let next = 0;
const id = () => (next += 1).toString(16).padStart(32, '0');
const accepted = (run: AnalysisRun) => ({ state: 'accepted' as const, accepted: { run_id: run.id, at: '2026-10-10T09:00:00Z' } });
const figure = (key: string, overrides: Partial<DashboardCard> = {}): DashboardCard => ({
  id: id(), kind: 'figure', title: key, state: 'pinned', run_id: health.id, template: 'collection', note: null, proposed_by: 'manager', accepted: null,
  select: { match: { entity: '集团', metric_key: key, scenario: '本期' }, column: 'value' }, ...overrides,
});
const rank = (overrides: Partial<DashboardCard> = {}): DashboardCard => ({
  id: id(), kind: 'rank', title: '各主体距生死线（从低到高）', state: 'pinned', run_id: health.id, template: 'collection', note: null, proposed_by: 'manager', accepted: null,
  select: { match: { metric_key: 'collection_gap', scenario: '本期', entity_origin: 'table' }, label: 'entity', column: 'value', order: 'asc', limit: 10,
    reference: { value: '0', label: '生死线' } }, ...overrides,
});
const scenario = (): DashboardCard => ({
  id: id(), kind: 'scenario', title: '回款情景：收缴率变了会怎样', state: 'pinned', run_id: health.id, template: 'collection', note: null, proposed_by: 'manager', accepted: null,
  select: { match: { entity: '集团', scenario: '本期' } },
});
const board = (cards: DashboardCard[]): Dashboard => ({ id: 'f'.repeat(32), parent_id: null, created_at: '2026-10-10T00:00:00Z', cards });
const contextOf = (run: AnalysisRun): FigureSourceContext => ({
  run, datasets: [{ id: 'd'.repeat(32), name: '01·核心指标看板' } as never],
  analysis: { question: '回款健康分析' } as never, superseded: new Set(),
});
const task = { title: '华宸物业 8 月月结', period: '2026 年 8 月' };

afterEach(() => { cleanup(); delete (globalThis as { foundry?: unknown }).foundry; });

describe('a snapshot of the board', () => {
  it('takes the accepted cards as the board shows them and names the rest as left out', () => {
    const gap = figure('collection_gap', accepted(health));
    const line = figure('break_even_collection', { ...accepted(health), note: '示例预置的认可，不是经理的认可。' });
    const margin = figure('gross_margin');
    // Accepted on an older run: it waits for the manager again.
    const moved = figure('expense_ratio', { state: 'accepted', accepted: { run_id: 'c'.repeat(32), at: '2026-10-09T00:00:00Z' } });
    const ranking = rank(accepted(health));
    const whatIf = scenario();
    const proposal = figure('collection_gap_total', { state: 'explore', proposed_by: 'assistant' });
    const snapshot = buildSnapshot({ board: board([gap, margin, ranking, whatIf, line, moved, proposal]), runs: [health], contextOf, task, format: 'pdf' });

    expect(snapshot.figures.map((item) => item.card_id)).toEqual([gap.id, line.id]);
    const [shown] = snapshot.figures;
    expect(shown).toMatchObject({ subject: '集团', part: '本期', value: { text: '-3.22 个百分点', negative: true }, level: 'red', source: 1,
      cell: { column: 'value', value: '-3.22412814607362800' } });
    expect(snapshot.figures[1].note).toBe('示例预置的认可，不是经理的认可。');
    // The bars are the board's own, worst first, each figure in accounting form.
    const chart = snapshot.charts[0];
    if (chart.kind !== 'rank') throw new Error('a rank');
    expect(chart.items.map((item) => [item.label, item.value])).toEqual(rankItems(ranking, health).items.map((item) => [item.label, item.value]));
    expect(chart.items[0]).toMatchObject({ label: '兰州城市公司', shown: { text: '(6.94)', negative: true } });
    expect(chart).toMatchObject({ unit: '个百分点', reference: { value: 0, label: '生死线' }, source: 3 });

    expect(snapshot.sources.map((item) => [item.n, item.card_id, item.run])).toEqual([[1, gap.id, 'A'], [2, line.id, 'A'], [3, ranking.id, 'A']]);
    expect(snapshot.sources[0].lines.some((text) => text.startsWith('公式：'))).toBe(true);
    expect(snapshot.sources[2].lines.slice(0, 2)).toEqual(['排序：从低到高，取前 10 名', '参考线：生死线 0']);
    expect(snapshot.runs).toEqual([{ key: 'A', run_id: health.id, label: '回款健康分析', computed: expect.stringContaining('计算'), files: ['01·核心指标看板（摘要 a1b2c3d4e5f6）'] }]);
    expect(snapshot.left_out).toEqual({ pinned: [{ card_id: margin.id, title: 'gross_margin' }, { card_id: moved.id, title: 'expense_ratio' }],
      scenario: [{ card_id: whatIf.id, title: whatIf.title }] });
    expect(snapshot.beyond).toEqual([]);
    // The page main prints is laid out from exactly this.
    expect(normalizeSnapshot(JSON.parse(JSON.stringify(snapshot)), true)).toEqual(snapshot);
    const html = snapshotHtml(snapshot, { sans: 'data:font/woff2;base64,AA==', figures: [] }, '2026-10-10 18:20');
    expect(html).toContain('没有放进这一页：待认可 2 张（「gross_margin」「expense_ratio」）；情景 1 张（情景不是实际数，不进快照）。');
    expect(snapshotFileName(snapshot, 'pdf')).toBe('经营看板_华宸物业8月月结_2026年8月.pdf');
  });

  it('prints the 署名 it was exported under, and nothing when nobody is chosen', () => {
    const gap = { ...figure('collection_gap'), state: 'accepted' as const };
    gap.accepted = { run_id: gap.run_id, at: '2026-10-10T10:00:00Z', by: '财务部 张三' };
    const signed = buildSnapshot({ board: board([gap]), runs: [health], contextOf, task, format: 'pdf', signer: ' 财务部 张三 ' });
    expect(signed.signed_by).toBe('财务部 张三');
    expect(normalizeSnapshot(JSON.parse(JSON.stringify(signed)), true)).toEqual(signed);
    expect(snapshotHtml(signed, { sans: 'data:font/woff2;base64,AA==', figures: [] }, '2026-10-10 18:20')).toContain('导出于 2026-10-10 18:20 · 导出人 财务部 张三 · 看板版本');
    const unsigned = buildSnapshot({ board: board([gap]), runs: [health], contextOf, task, format: 'pdf' });
    expect('signed_by' in unsigned).toBe(false);
    expect(snapshotHtml(unsigned, { sans: 'data:font/woff2;base64,AA==', figures: [] }, '2026-10-10 18:20')).not.toContain('导出人');
    expect(() => normalizeSnapshot({ ...JSON.parse(JSON.stringify(signed)), signed_by: '张'.repeat(81) }, true)).toThrow();
  });

  it('draws a profit bridge as its run holds it', () => {
    const bridge: DashboardCard = { id: id(), kind: 'bridge', title: '利润桥 · 华东', run_id: variance.id, template: 'operating', note: null, proposed_by: 'manager',
      select: { match: profitBridges(variance)[0].match }, ...accepted(variance) };
    const snapshot = buildSnapshot({ board: board([bridge]), runs: [variance], contextOf, task, format: 'pptx' });
    const [chart] = snapshot.charts;
    if (chart.kind !== 'bridge') throw new Error('a bridge');
    expect(chart.steps.map((step) => [step.kind, step.value, step.shown.text])).toEqual([
      ['total', 25, '25'], ['delta', 20, '20'], ['delta', -10, '(10)'], ['delta', -5, '(5)'], ['total', 30, '30']]);
    expect(snapshot.sources[0].lines[0]).toBe('利润桥：对照利润，加上收入、成本、费用各自的贡献，到实际利润');
  });

  it('holds what a page holds and names the rest; a workbook holds every accepted card', () => {
    const figures = Array.from({ length: 14 }, () => figure('collection_gap', accepted(health)));
    const charts = Array.from({ length: 4 }, () => rank(accepted(health)));
    const cards = [...figures, ...charts];
    const page = buildSnapshot({ board: board(cards), runs: [health], contextOf, task, format: 'pdf' });
    expect([page.figures.length, page.charts.length]).toEqual([12, 3]);
    expect(page.beyond.map((item) => item.card_id)).toEqual([figures[12].id, figures[13].id, charts[3].id]);
    expect(() => normalizeSnapshot(JSON.parse(JSON.stringify(page)), true)).not.toThrow();
    const few = buildSnapshot({ board: board([...figures.slice(0, 6), ...charts]), runs: [health], contextOf, task, format: 'pptx' });
    expect([few.figures.length, few.charts.length, few.beyond.length]).toEqual([6, 4, 0]);
    const book = buildSnapshot({ board: board(cards), runs: [health], contextOf, task, format: 'xlsx' });
    expect([book.figures.length, book.charts.length, book.beyond.length]).toEqual([14, 4, 0]);
  });

  it('refuses a board with nothing accepted, or a card whose run is gone', () => {
    expect(() => buildSnapshot({ board: board([figure('collection_gap'), scenario()]), runs: [health], contextOf, task, format: 'pdf' }))
      .toThrow('看板上还没有认可的卡，先认可要导出的卡。');
    const gone = figure('collection_gap', { ...accepted(health), run_id: '9'.repeat(32), accepted: { run_id: '9'.repeat(32), at: '2026-10-10T09:00:00Z' } });
    expect(() => buildSnapshot({ board: board([gone]), runs: [health], contextOf, task, format: 'pdf' }))
      .toThrow('「collection_gap」读的计算结果已经不在这个任务里了，先移除这张卡再导出。');
  });

  it('says the backend\'s refusals in words a manager reads', () => {
    const said = (message: string) => errorText(new Error(message)).split('（系统提示：')[0];
    expect(said('「collection_gap」 is not the figure its run holds; export again')).toBe('看板刚在别处更新过，或卡读的结果变了，请刷新后再导出一次。');
    expect(said('only the manager can export the dashboard')).toBe('看板只能由你导出。');
    expect(said('dashboard snapshot integrity check failed; its bytes differ from its record')).toBe('这份看板快照的文件和存档时不一致，或已经不在了。回到看板重新导出一份。');
  });
});

describe('导出一页纸 on the board', () => {
  function mount(cards: DashboardCard[], dashboardExport?: Bridge['dashboardExport']) {
    let read = 0;
    const financeCall = vi.fn(async (_task: string, command: string) => {
      if (command !== 'dashboard-read') throw new Error(command);
      read += 1;
      // From the third read on, the assistant has changed the board.
      return { ok: true, value: { dashboard: read > 2 ? { ...board(cards), id: '8'.repeat(32) } : board(cards) } };
    });
    (globalThis as { foundry?: Partial<Bridge> }).foundry = { financeCall: financeCall as unknown as Bridge['financeCall'], dashboardExport };
  }
  function Board({ withTask = true }: { withTask?: boolean }) {
    const state = useDashboard('t');
    return <DashboardView state={state} runs={[health]} analyses={[]} datasets={[]} readOnly={false}
      task={withTask ? { id: 't', title: '华宸物业 8 月月结', period: '2026 年 8 月' } : undefined} />;
  }

  it('exports the accepted cards, says where the copy went and that 成果库 keeps one', async () => {
    const dashboardExport = vi.fn(async (_task: string, format: string) => ({ ok: true as const, value: { exported: true as const, format, path: '/Users/me/Desktop/经营看板.pdf', snapshot_id: '1'.repeat(32) } }));
    mount([figure('collection_gap', accepted(health)), scenario()], dashboardExport);
    render(<Board />);
    press(await screen.findByRole('button', { name: '导出一页纸' }));
    expect(screen.getByText('放进已认可的 1 张卡')).toBeTruthy();
    expect(screen.getByText('另外 1 张待认可或是情景，不放进来，页脚会写明。')).toBeTruthy();
    fireEvent.click(screen.getByRole('menuitem', { name: 'PDF（一页 A4 横版）' }));
    expect(await screen.findByText('已导出「经营看板.pdf」，成果库里也存了一份（看板快照）。')).toBeTruthy();
    const [taskId, format, snapshot] = dashboardExport.mock.calls[0] as unknown as [string, string, { board_id: string; figures: unknown[]; task: string }];
    expect([taskId, format, snapshot.board_id, snapshot.figures.length, snapshot.task]).toEqual(['t', 'pdf', 'f'.repeat(32), 1, '华宸物业 8 月月结']);
  });

  it('is not offered before a card is accepted, and refuses a board changed since it was shown', async () => {
    const dashboardExport = vi.fn();
    mount([figure('collection_gap')], dashboardExport as unknown as Bridge['dashboardExport']);
    render(<Board />);
    expect((await screen.findByRole('button', { name: '导出一页纸' }) as HTMLButtonElement).disabled).toBe(true);
    cleanup();

    mount([figure('collection_gap', accepted(health))], dashboardExport as unknown as Bridge['dashboardExport']);
    render(<Board />);
    // The board is read again before the page is laid out; this time it has changed.
    await screen.findByRole('button', { name: '导出一页纸' });
    await waitFor(() => expect(screen.queryByText('正在读取看板…')).toBeNull());
    (globalThis as { foundry?: Partial<Bridge> }).foundry!.financeCall = vi.fn(async () => ({ ok: true, value: { dashboard: { ...board([]), id: '8'.repeat(32) } } })) as never;
    press(screen.getByRole('button', { name: '导出一页纸' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Excel（数字和来源）' }));
    expect(await screen.findByText('看板刚在别处更新过，已重新读取，看过后再导出。')).toBeTruthy();
    expect(dashboardExport).not.toHaveBeenCalled();
  });

  it('leaves the export out where this build cannot do it', async () => {
    mount([figure('collection_gap', accepted(health))]);
    render(<Board />);
    await screen.findByText(/共 1 张/);
    expect(screen.queryByRole('button', { name: '导出一页纸' })).toBeNull();
  });
});
