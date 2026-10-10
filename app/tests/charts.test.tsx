// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { extent, niceTicks, tickText } from '../src/components/charts/scale.js';
import { segments, seriesSummary, Sparkline, type SeriesPoint } from '../src/components/charts/Sparkline.js';
import { bridgeBars, bridgeCloses, Waterfall, type BridgeStep } from '../src/components/charts/Waterfall.js';
import { RankBars } from '../src/components/charts/RankBars.js';
import { archivedBars } from '../src/views/analysis/FinanceChartPanel.js';
import { RunPanel } from '../src/views/analysis/RunPanel.js';
import type { AnalysisRevision, AnalysisRun, DatasetSnapshot } from '../src/bridge.js';

afterEach(cleanup);

const points = (values: (number | null)[]): SeriesPoint[] => values.map((value, index) => ({ label: `${index + 1} 月`, value, text: value == null ? '—' : String(value) }));

const bridge: BridgeStep[] = [
  { label: '预算利润', kind: 'total', value: 25, text: '25' },
  { label: '收入', kind: 'delta', value: 20, text: '20' },
  { label: '成本', kind: 'delta', value: -10, text: '-10' },
  { label: '费用', kind: 'delta', value: -5, text: '-5' },
  { label: '实际利润', kind: 'total', value: 30, text: '30' },
];

describe('chart scales', () => {
  it('holds zero for bars and gives a single value room', () => {
    expect(extent([3, 7], true)).toEqual([0, 7]);
    expect(extent([-2, 5])).toEqual([-2, 5]);
    expect(extent([4])).toEqual([3.6, 4.4]);
    expect(extent([])).toEqual([-1, 1]);
  });

  it('rounds ticks to 1, 2 or 5 steps and writes them grouped', () => {
    expect(niceTicks([0, 37], 4)).toEqual({ domain: [0, 40], ticks: [0, 10, 20, 30, 40] });
    expect(niceTicks([-12, 30], 4).ticks).toEqual([-20, 0, 20, 40]);
    expect(tickText(12000, 5000)).toBe('12,000');
    expect(tickText(-0.25, 0.05)).toBe('-0.25');
  });
});

describe('sparkline', () => {
  it('breaks at a missing value and at a 口径 change', () => {
    expect(segments(points([1, 2, null, 4, 5, 6]), [4]).map((piece) => piece.map((point) => point.index))).toEqual([[0, 1], [3], [4, 5]]);
  });

  it('reads its ends, high and low to a screen reader', () => {
    expect(seriesSummary('收缴率', points([80, 85, 78, 82]))).toBe('收缴率：从1 月 80 到4 月 82，最高2 月 85，最低3 月 78');
    render(<Sparkline title="收缴率" points={points([80, 85])} />);
    expect(screen.getByRole('img', { name: '收缴率：从1 月 80 到2 月 85' })).toBeTruthy();
  });
});

describe('bridge', () => {
  it('floats each change from where the bridge stands', () => {
    expect(bridgeBars(bridge).map(({ from, to }) => [from, to])).toEqual([[0, 25], [25, 45], [45, 35], [35, 30], [0, 30]]);
  });

  it('draws only a bridge whose changes carry the first total to the last', () => {
    expect(bridgeCloses(bridge)).toBe(true);
    expect(bridgeCloses(bridge.map((step) => step.label === '费用' ? { ...step, value: -4 } : step))).toBe(false);
    expect(bridgeCloses(bridge.slice(1))).toBe(false);
  });

  it('labels every bar with its figure, negatives in parentheses', () => {
    render(<Waterfall title="利润桥" steps={bridge} unit="万元" />);
    const chart = screen.getByRole('img', { name: '利润桥：预算利润 25，收入 20，成本 -10，费用 -5，实际利润 30（万元）' });
    expect(within(chart).getByText('(10)').getAttribute('data-negative')).toBe('true');
    expect(screen.getByText('单位：万元')).toBeTruthy();
  });
});

describe('rank bars', () => {
  it('sorts longest first unless told to keep the order', () => {
    const items = [{ label: '三亚', value: -1.4, text: '-1.40' }, { label: '海口', value: 3.1, text: '3.10' }];
    const { unmount } = render(<RankBars title="距生死线" items={items} />);
    expect(screen.getByRole('img').getAttribute('aria-label')).toBe('距生死线：海口 3.10，三亚 -1.40');
    unmount();
    render(<RankBars title="距生死线" items={items} keepOrder />);
    expect(screen.getByRole('img').getAttribute('aria-label')).toBe('距生死线：三亚 -1.40，海口 3.10');
  });
});

describe('archived chart', () => {
  it('draws a text column against the actual column, and leaves an undrawable series a table', () => {
    const drawn = archivedBars([{ 城市: '海口', actual: '120.50', budget: '100' }, { 城市: '三亚', actual: '-3', budget: '1' }]);
    expect(drawn?.category).toBe('城市');
    expect(drawn?.value).toBe('actual');
    expect(drawn?.items.map((item) => item.text)).toEqual(['120.50', '-3']);
    expect(archivedBars([{ a: '1', b: '2' }])).toBeNull();
    // A variance series starts with columns every row shares; the bars are named by the one that tells them apart.
    const variance = archivedBars([
      { ledger: 'L1', organization: '海口', unit: '元', metric: 'revenue', actual: '120' },
      { ledger: 'L1', organization: '海口', unit: '元', metric: 'profit', actual: '20' },
    ]);
    expect(variance?.category).toBe('metric');
    expect(variance?.items.map((item) => item.label)).toEqual(['revenue', 'profit']);
    // No single column tells the rows apart: the series stays a table.
    expect(archivedBars([
      { period: '2026-08', metric: 'revenue', actual: '1' }, { period: '2026-08', metric: 'profit', actual: '2' },
      { period: '2026-09', metric: 'revenue', actual: '3' }, { period: '2026-09', metric: 'profit', actual: '4' },
    ])).toBeNull();
    expect(archivedBars(Array.from({ length: 31 }, (_, index) => ({ name: `行${index}`, actual: '1' })))).toBeNull();
  });
});

describe('profit bridge on a variance result', () => {
  const taskId = 'a'.repeat(32);
  const analysis = { id: 'b'.repeat(32), task_id: taskId, schema_version: 1, created_at: '2026-09-07T00:00:00Z', question: '利润差异', sql: null, bindings: {}, parameters: [], assumptions: [], grain: [], relationships: [], metrics: [] } as AnalysisRevision;
  const dataset = { id: 'c'.repeat(32), task_id: taskId, schema_version: 1, created_at: '2026-09-07T00:00:00Z', name: '套表', kind: 'table', source_hash: 'd'.repeat(64), source_name: 'pack.xlsx', metadata: {} } as DatasetSnapshot;
  const row = (metric: string, actual: string, baseline: string, contribution: string, extra: Record<string, unknown> = {}) => ({
    organization: '华东', period: '2026-08', unit: '万元', metric, actual, baseline, amount_change: contribution, profit_impact: contribution, contribution, ratio: '0', comparison_status: 'complete', ...extra,
  });
  const run = (rows: Record<string, unknown>[]): AnalysisRun => ({
    id: 'e'.repeat(32), task_id: taskId, schema_version: 1, created_at: '2026-09-07T00:00:00Z', analysis_id: analysis.id,
    execution_status: 'succeeded', reproducibility_status: 'reproducible', review_status: 'unreviewed', publication_status: 'draft', input_hashes: {}, engine: 'finance',
    result: { method: 'revenue_minus_cost_minus_expense', comparison: { actual_scenario: 'actual', baseline_scenario: 'budget' },
      columns: Object.keys(row('revenue', '1', '1', '1')).map((name) => ({ name, type: 'VARCHAR' })), rows, row_count: rows.length, truncated: false } as AnalysisRun['result'],
  });
  const props = { analysis, analyses: [analysis], datasets: [dataset], busy: false, onPick: vi.fn(), onChat: vi.fn(), onOpen: vi.fn(), onSource: vi.fn(), onSaveMethod: vi.fn() };
  const complete = [row('revenue', '120', '100', '20'), row('cost', '70', '60', '-10'), row('expense', '20', '15', '-5'), row('profit', '30', '25', '5')];

  it('draws 预算利润 through 收入, 成本 and 费用 to 实际利润', () => {
    render(<RunPanel {...props} runs={[run(complete)]} />);
    const bridges = screen.getByRole('region', { name: '利润桥' });
    expect(within(bridges).getByRole('img').getAttribute('aria-label')).toBe('利润桥：预算利润 25，收入 20，成本 -10，费用 -5，实际利润 30（万元）');
  });

  it('draws nothing for a bridge with a 缺项', () => {
    render(<RunPanel {...props} runs={[run(complete.map((item) => item.metric === 'cost' ? { ...item, comparison_status: 'partial' } : item))]} />);
    expect(screen.queryByRole('region', { name: '利润桥' })).toBeNull();
  });
});
