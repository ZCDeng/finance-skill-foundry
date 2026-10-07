// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { RunPanel } from '../src/views/analysis/RunPanel.js';
import type { AnalysisDraft, AnalysisRevision, AnalysisRun, DatasetSnapshot, FinanceDrilldown, ResultContractWarning } from '../src/bridge.js';

const taskId = 'a'.repeat(32);
const analysis: AnalysisRevision = { id: 'b'.repeat(32), task_id: taskId, schema_version: 1, created_at: '2026-09-07T00:00:00Z',
  question: '结构化经营汇总', sql: null, engine: 'python', bindings: {}, parameters: [], assumptions: [], grain: [], relationships: [], metrics: [] };
const dataset: DatasetSnapshot = { id: 'c'.repeat(32), task_id: taskId, schema_version: 1, created_at: '2026-09-07T00:00:00Z',
  name: '本月台账', kind: 'table', source_hash: 'd'.repeat(64), source_name: 'ledger.csv', metadata: {}, row_count: 2 };
const baseRun: AnalysisRun = { id: 'e'.repeat(32), task_id: taskId, schema_version: 1, created_at: '2026-09-07T00:00:00Z', analysis_id: analysis.id,
  execution_status: 'succeeded', reproducibility_status: 'reproducible', review_status: 'unreviewed', publication_status: 'draft', input_hashes: {} };
const noop = vi.fn();
const props = { analysis, analyses: [analysis], datasets: [dataset], busy: false, onPick: noop, onChat: noop, onOpen: noop, onSource: noop, onSaveMethod: noop };

function structuredRun(overrides: Partial<AnalysisRun> = {}): AnalysisRun {
  return { ...baseRun, engine: 'structured_aggregate', result: {
    columns: [
      { name: 'metric', type: 'VARCHAR' }, { name: 'amount', type: 'DECIMAL' }, { name: 'result_key', type: 'VARCHAR' },
      { name: 'source_rows', type: 'JSON' }, { name: 'excluded_source_rows', type: 'JSON' }, { name: 'provenance_status', type: 'VARCHAR' },
    ],
    rows: [{ metric: '收入', amount: '120', result_key: 'total:revenue', source_rows: [{ dataset_id: dataset.id, row_index: 1 }], provenance_status: 'verified' }],
    detail_rows: [{ customer: '客户甲', amount: '120', source_rows: [{ dataset_id: dataset.id, row_index: 1 }] }],
    excluded_detail_rows: [{ customer: '客户乙', amount: '5', excluded_source_rows: [{ dataset_id: dataset.id, row_index: 2 }], exclusion_reason: 'status_not_included' }],
    row_count: 1,
    truncated: false,
    provenance: { mode: 'executor_verified_source_map', status: 'verified', plan_hash: 'p1', data_hash: 'd1', source_hash: 's1' },
  }, ...overrides };
}

function scriptResultRun(overrides: Partial<AnalysisRun> = {}): AnalysisRun {
  return { ...baseRun, engine: 'python', result: {
    columns: [
      { name: 'metric', type: 'VARCHAR' }, { name: 'label', type: 'VARCHAR' }, { name: 'value', type: 'DECIMAL' },
      { name: 'unit', type: 'VARCHAR' }, { name: 'wb', type: 'VARCHAR' }, { name: 'sheet', type: 'VARCHAR' },
      { name: 'cell', type: 'VARCHAR' }, { name: 'note', type: 'VARCHAR' }, { name: 'check', type: 'VARCHAR' },
    ],
    rows: [
      { metric: 'gross_margin_rate', label: '综合毛利率', value: '0.123456789012345678901234567890', unit: '%', wb: 'actual.xlsx', sheet: '利润表', cell: 'G12', note: 'displayvalue: 12.35%', check: 'ok' },
      { metric: 'adjustment', label: '调整项', value: null, unit: '元', wb: 'actual.xlsx', sheet: '调整', cell: 'B2', note: '未填', check: 'review' },
    ],
    row_count: 2,
    truncated: true,
  }, ...overrides };
}

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  const promise = new Promise<T>((resolvePromise) => { resolve = resolvePromise; });
  return { promise, resolve };
}

afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe('RunPanel structured aggregate results', () => {
  it('translates persisted calculation errors and omits identifiers in both result and comparison views', () => {
    const error = `dataset ${dataset.id} integrity check failed: ${'f'.repeat(64)}`;
    const failed = { ...baseRun, id: '0'.repeat(32), execution_status: 'failed', error } as AnalysisRun;
    render(<RunPanel {...props} runs={[failed]} />);
    const alert = screen.getByRole('alert');
    expect(alert.textContent).toContain('资料内容与登记时不一致');
    expect(alert.textContent).toContain('系统提示：');
    expect(alert.textContent).not.toContain(dataset.id);
    expect(alert.textContent).not.toContain('f'.repeat(64));
    cleanup();

    render(<RunPanel {...props} runs={[failed, structuredRun()]} />);
    fireEvent.click(screen.getByRole('button', { name: '比较版本' }));
    fireEvent.change(screen.getByLabelText('对照结果'), { target: { value: failed.id } });
    const comparison = screen.getByRole('region', { name: '版本比较' });
    const comparisonError = within(comparison).getByText(/资料内容与登记时不一致/);
    expect(comparisonError.textContent).not.toContain(dataset.id);
    expect(comparisonError.textContent).not.toContain('f'.repeat(64));
  });

  it('distinguishes calculations saved at the same timestamp by their stored order', () => {
    const first = structuredRun();
    const second = structuredRun({ id: '1'.repeat(32) });
    render(<RunPanel {...props} runs={[first, second]} />);
    const history = screen.getByText(/^计算历史/).closest('details')!;
    const rows = Array.from(history.querySelectorAll('.analysis-history-row'));
    expect(rows[0].textContent).toContain('第 2 次计算');
    expect(rows[1].textContent).toContain('第 1 次计算');
  });

  it('renders a manager-readable structured result with traceable sources and raw technical fields collapsed', async () => {
    render(<RunPanel {...props} runs={[structuredRun()]} onDrilldown={vi.fn(async () => ({ run_id: baseRun.id, row: 0, rows: [], total: 0, offset: 0, has_more: false, message: '无来源' }))} />);
    await screen.findByText('来源可追溯：执行器已核对来源映射；这不代表业务判断已经通过。');
    const main = screen.getByRole('region', { name: '结构化汇总结果' });
    expect(within(main).getByRole('columnheader', { name: 'metric' })).toBeTruthy();
    expect(within(main).getByRole('columnheader', { name: 'amount' })).toBeTruthy();
    expect(within(main).queryByRole('columnheader', { name: 'result_key' })).toBeNull();
    expect(within(main).queryByRole('columnheader', { name: 'source_rows' })).toBeNull();
    expect(within(main).queryByRole('columnheader', { name: 'excluded_source_rows' })).toBeNull();
    expect(within(main).queryByRole('columnheader', { name: 'provenance_status' })).toBeNull();

    fireEvent.click(screen.getByText('来源明细 · 1 行'));
    expect(within(screen.getByRole('region', { name: '来源明细' })).getByRole('cell', { name: '客户甲' })).toBeTruthy();
    fireEvent.click(screen.getByText('剔除明细 · 1 行'));
    expect(within(screen.getByRole('region', { name: '剔除明细' })).getByRole('cell', { name: '客户乙' })).toBeTruthy();

    const raw = screen.getByText('技术信息').closest('details') as HTMLDetailsElement;
    expect(raw.open).toBe(false);
    fireEvent.click(screen.getByText('技术信息'));
    expect(raw.querySelectorAll('details')).toHaveLength(0);
    expect(within(screen.getByRole('region', { name: '原始计算结果' })).getByRole('columnheader', { name: 'result_key' })).toBeTruthy();
  });

  it('explains missing structured aggregate measure values in Chinese and keeps raw diagnostics collapsed', async () => {
    render(<RunPanel {...props} runs={[structuredRun({ result: {
      ...structuredRun().result!, rows: [{ metric: '收入', amount: null, source_rows: [{ dataset_id: dataset.id, row_index: 1 }] }], diagnostics: [
        { code: 'aggregate_missing_measure_values', metric: '收入', aggregation: 'sum', missing_count: 3, source_row_count: 8, message: 'amount is missing' },
        { code: 'aggregate_missing_measure_values', metric: '最早订单', aggregation: 'min', missing_count: 1 },
        { code: 'aggregate_missing_measure_values', metric: '客户数', aggregation: 'count_distinct', missing_count: 2 },
      ],
    } })]} />);
    expect(await screen.findByText('指标“收入”有 3 条来源金额缺失，汇总未完成。')).toBeTruthy();
    expect(screen.getByText('指标“最早订单”有 1 条来源金额缺失，最小值结果已排除这些缺失来源，请复核结果。')).toBeTruthy();
    expect(screen.getByText('指标“客户数”有 2 条来源金额缺失，去重计数结果已排除这些缺失来源，请复核结果。')).toBeTruthy();
    const raw = screen.getByText('技术信息').closest('details') as HTMLDetailsElement;
    expect(raw.open).toBe(false);
    fireEvent.click(screen.getByText('技术信息'));
    expect(within(raw).getByText('原始结果字段 · 6 列')).toBeTruthy();
    expect(raw.querySelectorAll('details')).toHaveLength(0);
    expect(screen.getByText(/amount is missing/)).toBeTruthy();
  });

  it('passes the selected structured detail section to source drilldown', async () => {
    const onDrilldown = vi.fn(async (): Promise<FinanceDrilldown> => ({ run_id: baseRun.id, row: 0, rows: [
      { source: { dataset_id: dataset.id, source_row: 2 }, source_hash: dataset.source_hash, data: { customer: '客户乙' }, voucher_detail_available: true },
    ], total: 1, offset: 0, has_more: false, message: '剔除来源' }));
    render(<RunPanel {...props} runs={[structuredRun()]} onDrilldown={onDrilldown} />);
    await screen.findByLabelText('结果行来源');
    fireEvent.change(screen.getByLabelText('结果行来源'), { target: { value: 'excluded_detail_rows:0' } });
    await waitFor(() => expect((screen.getByLabelText('结果行来源') as HTMLSelectElement).value).toBe('excluded_detail_rows:0'));
    fireEvent.click(screen.getByRole('button', { name: '查看来源行' }));
    await waitFor(() => expect(onDrilldown).toHaveBeenCalledWith(expect.objectContaining({ id: baseRun.id }), 0, undefined, 'excluded_detail_rows'));
    expect(await screen.findByText(/剔除来源/)).toBeTruthy();
  });

  it('drops stale structured drilldown responses when the selected run changes', async () => {
    const first = structuredRun({ id: '1'.repeat(32), created_at: '2026-09-07T00:00:00Z' });
    const second = structuredRun({ id: '2'.repeat(32), created_at: '2026-09-07T01:00:00Z', result: {
      ...structuredRun().result!, rows: [{ metric: '成本', amount: '70', source_rows: [{ dataset_id: dataset.id, row_index: 3 }] }], detail_rows: [], excluded_detail_rows: [] } });
    const gate = deferred<FinanceDrilldown>();
    const onDrilldown = vi.fn(() => gate.promise);
    const { rerender } = render(<RunPanel {...props} runs={[first]} onDrilldown={onDrilldown} />);
    await screen.findByText('第 1 行 · 收入');
    fireEvent.change(screen.getByLabelText('结果行来源'), { target: { value: 'rows:0' } });
    fireEvent.click(screen.getByRole('button', { name: '查看来源行' }));
    await waitFor(() => expect(onDrilldown).toHaveBeenCalledTimes(1));
    rerender(<RunPanel {...props} runs={[first, second]} onDrilldown={onDrilldown} />);
    await screen.findByText('第 1 行 · 成本');
    await act(async () => gate.resolve({ run_id: first.id, row: 0, rows: [], total: 1, offset: 0, has_more: false, message: '旧运行来源' }));
    expect(screen.queryByText(/旧运行来源/)).toBeNull();
    expect((screen.getByLabelText('结果行来源') as HTMLSelectElement).value).toBe('');
  });

  it('does not label ordinary SQL results as source verified', async () => {
    const sqlRun: AnalysisRun = { ...baseRun, engine: 'sql', result: {
      columns: [{ name: 'metric', type: 'VARCHAR' }, { name: 'amount', type: 'DECIMAL' }],
      rows: [{ metric: '收入', amount: '120' }], row_count: 1, truncated: false,
      provenance: { mode: 'executor_verified_source_map', status: 'verified', plan_hash: 'p1', data_hash: 'd1', source_hash: 's1' },
    } };
    render(<RunPanel {...props} runs={[sqlRun]} />);
    await screen.findByRole('region', { name: '计算结果' });
    expect(screen.queryByText(/来源可追溯/)).toBeNull();
    expect(screen.queryByLabelText('结果行来源')).toBeNull();
  });

  it('summarizes exact script result fields first and keeps all original columns in full details', async () => {
    render(<RunPanel {...props} runs={[scriptResultRun()]} />);
    const summary = await screen.findByRole('region', { name: '计算结果' });
    expect(within(summary).getByRole('columnheader', { name: '项目' })).toBeTruthy();
    expect(within(summary).getByRole('columnheader', { name: '数值' })).toBeTruthy();
    expect(within(summary).getByRole('columnheader', { name: '单位' })).toBeTruthy();
    expect(within(summary).queryByRole('columnheader', { name: 'metric' })).toBeNull();
    expect(within(summary).queryByRole('columnheader', { name: 'wb' })).toBeNull();
    expect(within(summary).getByRole('cell', { name: '0.123456789012345678901234567890' }).className).toContain('analysis-number');
    expect(within(summary).getByRole('cell', { name: '—' })).toBeTruthy();
    expect(screen.getByText('2 行 · 当前为截断预览')).toBeTruthy();

    const full = screen.getByText('完整明细 · 9 列').closest('details') as HTMLDetailsElement;
    expect(full.open).toBe(false);
    fireEvent.click(screen.getByText('完整明细 · 9 列'));
    const details = screen.getByRole('region', { name: '完整明细' });
    expect(within(details).getByRole('columnheader', { name: 'metric' })).toBeTruthy();
    expect(within(details).getByRole('columnheader', { name: 'check' })).toBeTruthy();
    expect(within(details).getAllByRole('cell', { name: 'actual.xlsx' })).toHaveLength(2);
    expect(within(details).getByRole('cell', { name: 'displayvalue: 12.35%' })).toBeTruthy();
  });

  it('keeps SQL and missing-field runs on the full table fallback', async () => {
    const sqlRun = scriptResultRun({ engine: 'sql' });
    const missingField = scriptResultRun({ id: 'f'.repeat(32), engine: 'python', result: {
      ...scriptResultRun().result!,
      columns: [{ name: 'label', type: 'VARCHAR' }, { name: 'value', type: 'DECIMAL' }],
      rows: [{ label: '综合毛利率', value: '0.12' }],
      row_count: 1,
      truncated: false,
    } });

    const { rerender } = render(<RunPanel {...props} runs={[sqlRun]} />);
    let table = await screen.findByRole('region', { name: '计算结果' });
    expect(within(table).getByRole('columnheader', { name: 'metric' })).toBeTruthy();
    expect(within(table).getByRole('columnheader', { name: 'label' })).toBeTruthy();
    expect(within(table).queryByRole('columnheader', { name: '项目' })).toBeNull();
    expect(screen.queryByText(/完整明细/)).toBeNull();

    rerender(<RunPanel {...props} runs={[missingField]} />);
    table = await screen.findByRole('region', { name: '计算结果' });
    expect(within(table).getByRole('columnheader', { name: 'label' })).toBeTruthy();
    expect(within(table).getByRole('columnheader', { name: 'value' })).toBeTruthy();
    expect(within(table).queryByRole('columnheader', { name: '项目' })).toBeNull();
    expect(screen.queryByText(/完整明细/)).toBeNull();
  });

  it('keeps multi-value and unknown script result columns on the full table fallback', async () => {
    const multiValue = scriptResultRun({ id: '1'.repeat(32), result: {
      ...scriptResultRun().result!,
      columns: [
        { name: 'label', type: 'VARCHAR' }, { name: 'value', type: 'DECIMAL' }, { name: 'unit', type: 'VARCHAR' },
        { name: 'v2', type: 'DECIMAL' }, { name: 'v3', type: 'DECIMAL' },
      ],
      rows: [{ label: '欠费/坏账/净额', value: '100.00', unit: '元', v2: '30.00', v3: '70.00' }],
      row_count: 1,
      truncated: false,
    } });
    const unknown = scriptResultRun({ id: '2'.repeat(32), result: {
      ...scriptResultRun().result!,
      columns: [
        { name: 'label', type: 'VARCHAR' }, { name: 'value', type: 'DECIMAL' }, { name: 'unit', type: 'VARCHAR' },
        { name: 'scenario_value', type: 'DECIMAL' },
      ],
      rows: [{ label: '敏感性结果', value: '100.00', unit: '元', scenario_value: '88.00' }],
      row_count: 1,
      truncated: false,
    } });

    const { rerender } = render(<RunPanel {...props} runs={[multiValue]} />);
    let table = await screen.findByRole('region', { name: '计算结果' });
    expect(within(table).getByRole('columnheader', { name: 'label' })).toBeTruthy();
    expect(within(table).getByRole('columnheader', { name: 'v2' })).toBeTruthy();
    expect(within(table).getByRole('columnheader', { name: 'v3' })).toBeTruthy();
    expect(within(table).getByRole('cell', { name: '30.00' })).toBeTruthy();
    expect(within(table).getByRole('cell', { name: '70.00' })).toBeTruthy();
    expect(within(table).queryByRole('columnheader', { name: '项目' })).toBeNull();
    expect(screen.queryByText(/完整明细/)).toBeNull();

    rerender(<RunPanel {...props} runs={[unknown]} />);
    table = await screen.findByRole('region', { name: '计算结果' });
    expect(within(table).getByRole('columnheader', { name: 'scenario_value' })).toBeTruthy();
    expect(within(table).getByRole('cell', { name: '88.00' })).toBeTruthy();
    expect(within(table).queryByRole('columnheader', { name: '项目' })).toBeNull();
    expect(screen.queryByText(/完整明细/)).toBeNull();
  });
});

function varianceRun(rows: Record<string, unknown>[], extra: Record<string, unknown> = {}): AnalysisRun {
  const columns = ['organization', 'period', 'unit', 'metric', 'actual', 'baseline', 'amount_change', 'profit_impact', 'contribution', 'ratio', 'comparison_status']
    .map((name) => ({ name, type: ['actual', 'baseline', 'amount_change', 'profit_impact', 'contribution', 'ratio'].includes(name) ? 'DECIMAL' : 'VARCHAR' }));
  return { ...baseRun, engine: 'finance', result: { method: 'revenue_minus_cost_minus_expense', comparison: { actual_scenario: 'actual', baseline_scenario: 'budget' },
    columns, rows, row_count: rows.length, truncated: false, ...extra } as AnalysisRun['result'] };
}
const bridgeRow = (metric: string, amountChange: string, extra: Record<string, unknown> = {}) => ({ organization: '华东', period: '2026-08', unit: '万元', metric,
  actual: '1', baseline: '1', amount_change: amountChange, profit_impact: amountChange, contribution: amountChange, ratio: '0', comparison_status: 'complete', ...extra });

describe('RunPanel version without a run', () => {
  it('says the task has other results and opens the newest instead of reading as empty', () => {
    const other: AnalysisRevision = { ...analysis, id: 'f'.repeat(32), question: '另一版分析' };
    const onPick = vi.fn();
    render(<RunPanel {...props} analyses={[analysis, other]} runs={[structuredRun({ analysis_id: other.id })]} onPick={onPick} />);
    expect(screen.getByText('此版本尚未计算。本任务另有 1 个结果。')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '查看最新结果' }));
    expect(onPick).toHaveBeenCalledWith(other.id);
  });

  it('keeps the old hint when the task has no result yet', () => {
    render(<RunPanel {...props} runs={[]} />);
    expect(screen.getByText('此版本尚未计算。确认范围后即可计算。')).toBeTruthy();
    expect(screen.queryByRole('button', { name: '查看最新结果' })).toBeNull();
  });
});

describe('RunPanel finance conclusion', () => {
  it('keeps exact variance diagnostics and raw values inside one closed technical disclosure', () => {
    const run = varianceRun([bridgeRow('profit', '-900719925474099.99')], {
      diagnostics: [{ code: 'missing_baseline', source_id: dataset.id }],
    });
    render(<RunPanel {...props} runs={[run]} />);
    const summary = screen.getByText('技术信息');
    const technical = summary.closest('details') as HTMLDetailsElement;
    expect(technical.open).toBe(false);
    expect(screen.getByRole('table', { name: '原始计算结果' }).closest('details')).toBe(technical);
    fireEvent.click(summary);
    expect(technical.open).toBe(true);
    expect(within(technical).getByText(/missing_baseline/).textContent).toContain(dataset.id);
    expect(within(technical).getByRole('table', { name: '原始计算结果' }).textContent).toContain('(900,719,925,474,099.99)');
    expect(screen.queryByText('技术信息 · 诊断 1 项')).toBeNull();
  });

  it('leads with the profit change the backend wrote, the three drivers, and the backend caveat', () => {
    const run = varianceRun([
      bridgeRow('revenue', '50', { amount_change_display: '收入增加 50 万元' }),
      bridgeRow('cost', '208', { amount_change_display: '成本增加 208 万元' }),
      bridgeRow('expense', '-10', { amount_change_display: '费用减少 10 万元' }),
      bridgeRow('profit', '-312.00', { amount_change_display: '利润减少 312.00 万元' }),
    ], { interpretation: '分量表示算术贡献。业务原因需经理判断或独立证据。' });
    render(<RunPanel {...props} runs={[run]} />);
    // The run is named by its order, not by a hash prefix; the id stays on hover and in the history rows.
    const header = screen.getByTitle(run.id);
    expect(header.textContent).toContain('第 1 次计算');
    expect(header.textContent).not.toContain(run.id.slice(0, 12));
    expect(document.body.textContent).not.toContain(run.id.slice(0, 12));
    const conclusion = screen.getByRole('region', { name: '结论' });
    expect(within(conclusion).getByText('实际与预算相比，利润减少 312.00 万元')).toBeTruthy();
    expect(within(conclusion).getByText('收入增加 50 万元 · 成本增加 208 万元 · 费用减少 10 万元')).toBeTruthy();
    expect(within(conclusion).getByText('分量表示算术贡献。业务原因需经理判断或独立证据。')).toBeTruthy();
    const table = screen.getByRole('region', { name: '预算差异桥' });
    expect(conclusion.compareDocumentPosition(table) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('reads the sign of the amount string when the backend wrote no phrase, without rounding it', () => {
    const run = varianceRun([
      bridgeRow('revenue', '0.00'),
      bridgeRow('profit', '-900719925474099.99', { comparison_status: 'assumed_zero' }),
    ]);
    render(<RunPanel {...props} runs={[run]} />);
    const conclusion = screen.getByRole('region', { name: '结论' });
    expect(within(conclusion).getByText('实际与预算相比，利润减少 900,719,925,474,099.99 万元')).toBeTruthy();
    expect(within(conclusion).getByText('收入持平')).toBeTruthy();
    expect(within(conclusion).getByText('这一组有一侧没有数据，已按 0 计入，差异等于另一侧的全额。')).toBeTruthy();
  });

  it('names each compared group and caps the conclusion at three of them', () => {
    const rows = ['华东', '华南', '华北', '西南'].map((organization, index) => bridgeRow('profit', index % 2 ? '-20' : '30', { organization }));
    render(<RunPanel {...props} runs={[varianceRun(rows)]} />);
    const conclusion = screen.getByRole('region', { name: '结论' });
    expect(within(conclusion).getByText('华东：实际与预算相比，利润增加 30 万元')).toBeTruthy();
    expect(within(conclusion).getByText('华南：实际与预算相比，利润减少 20 万元')).toBeTruthy();
    expect(within(conclusion).queryByText(/西南/)).toBeNull();
    expect(within(conclusion).getByText('共 4 组，其余见下表。')).toBeTruthy();
  });

  it('counts every compared group, including ones it could not conclude on', () => {
    const rows = ['华东', '华南', '华北'].map((organization) => bridgeRow('profit', '5', { organization }));
    rows.push(bridgeRow('profit', '', { organization: '西南', amount_change: null, contribution: null, comparison_status: 'incomplete' }));
    render(<RunPanel {...props} runs={[varianceRun(rows)]} />);
    const conclusion = screen.getByRole('region', { name: '结论' });
    expect(within(conclusion).getAllByText(/实际与预算相比/)).toHaveLength(3);
    expect(within(conclusion).getByText('共 4 组，其余见下表。')).toBeTruthy();
  });

  it('takes the unit from the side scopes when the row has none, and says nothing when the sides disagree', () => {
    const scoped = (unit: string, baseline = unit) => ({ unit: undefined, actual_scope: { scenario: 'actual', unit }, baseline_scope: { scenario: 'budget', unit: baseline } });
    const { unmount } = render(<RunPanel {...props} runs={[varianceRun([
      bridgeRow('profit', '-312.00', { ...scoped('万元'), amount_change_display: '利润减少 312.00' }),
    ])]} />);
    expect(within(screen.getByRole('region', { name: '结论' })).getByText('实际与预算相比，利润减少 312.00 万元')).toBeTruthy();
    unmount();
    render(<RunPanel {...props} runs={[varianceRun([bridgeRow('profit', '-312.00', scoped('元', '万元'))])]} />);
    expect(screen.queryByRole('region', { name: '结论' })).toBeNull();
  });

  it('says nothing when empty dimension values fold two groups into one', () => {
    render(<RunPanel {...props} runs={[varianceRun([
      bridgeRow('profit', '30', { organization: '华东' }),
      bridgeRow('profit', '-20', { organization: null }),
    ])]} />);
    expect(screen.queryByRole('region', { name: '结论' })).toBeNull();
  });

  it.each([
    [{ actual_scenario: 'forecast', baseline_scenario: 'budget' }, '预测与预算相比，利润减少 5 万元', '预算差异桥'],
    [{ actual_scenario: 'actual', baseline_scenario: 'budget', actual_filters: { period: '2026-08' }, baseline_filters: { period: '2026-07' } }, '实际（2026 年 8 月）与预算（2026 年 7 月）相比，利润减少 5 万元', '预算差异桥'],
    [{ actual_scenario: 'actual', baseline_scenario: 'actual' }, '实际与对照（实际）相比，利润减少 5 万元', '损益差异桥'],
    [{ actual_scenario: 'actual', baseline_scenario: 'estimated_budget' }, '实际与预算（估算）相比，利润减少 5 万元', '估算预算差异桥'],
  ])('names both sides of the comparison: %j', (comparison, sentence, caption) => {
    render(<RunPanel {...props} runs={[varianceRun([bridgeRow('profit', '-5')], { comparison })]} />);
    expect(within(screen.getByRole('region', { name: '结论' })).getByText(sentence)).toBeTruthy();
    expect(screen.getByRole('region', { name: caption })).toBeTruthy();
  });

  it('marks a line one side never booked as 缺项 and leaves it and the profit out of the conclusion', () => {
    const run = varianceRun([
      bridgeRow('revenue', '20', { amount_change_display: '收入增加 20 万元' }),
      bridgeRow('cost', '70', { amount_change_display: '成本增加 70 万元', comparison_status: 'partial' }),
      bridgeRow('expense', '5', { amount_change_display: '费用增加 5 万元' }),
      bridgeRow('profit', '-55', { amount_change_display: '利润减少 55 万元', comparison_status: 'partial' }),
    ]);
    render(<RunPanel {...props} runs={[run]} />);
    const conclusion = screen.getByRole('region', { name: '结论' });
    expect(within(conclusion).getByText('成本是缺项，只在一侧有来源行，利润差异不完整，见下表。')).toBeTruthy();
    expect(within(conclusion).queryByText(/利润减少/)).toBeNull();
    expect(within(conclusion).queryByText(/成本增加/)).toBeNull();
    expect(within(conclusion).getByText('收入增加 20 万元 · 费用增加 5 万元')).toBeTruthy();
    const table = screen.getByRole('region', { name: '预算差异桥' });
    expect(within(table).getByRole('cell', { name: '成本（缺项）' })).toBeTruthy();
    expect(within(table).getByRole('cell', { name: '利润（缺项）' })).toBeTruthy();
    expect(within(table).getByRole('cell', { name: '收入' })).toBeTruthy();
  });

  it('names the group of a 缺项 line and still concludes on complete groups', () => {
    render(<RunPanel {...props} runs={[varianceRun([
      bridgeRow('profit', '30', { organization: '华东' }),
      bridgeRow('expense', '8', { organization: '华南', comparison_status: 'partial' }),
      bridgeRow('profit', '-8', { organization: '华南', comparison_status: 'partial' }),
    ])]} />);
    const conclusion = screen.getByRole('region', { name: '结论' });
    expect(within(conclusion).getByText('华东：实际与预算相比，利润增加 30 万元')).toBeTruthy();
    expect(within(conclusion).getByText('华南：费用是缺项，只在一侧有来源行，利润差异不完整，见下表。')).toBeTruthy();
  });

  it('reads an old run without a partial status as it was recorded', () => {
    const rows = [bridgeRow('cost', '70'), bridgeRow('profit', '-55')].map(({ comparison_status: _recorded, ...row }) => row);
    const run = varianceRun(rows);
    run.result!.columns = run.result!.columns.filter((column) => column.name !== 'comparison_status');
    render(<RunPanel {...props} runs={[run]} />);
    expect(within(screen.getByRole('region', { name: '结论' })).getByText('实际与预算相比，利润减少 55 万元')).toBeTruthy();
    expect(screen.queryByText(/缺项/)).toBeNull();
    expect(within(screen.getByRole('region', { name: '预算差异桥' })).getByRole('cell', { name: '成本' })).toBeTruthy();
  });

  it('writes no conclusion when there is no profit change to state', () => {
    render(<RunPanel {...props} runs={[varianceRun([bridgeRow('revenue', '50'), bridgeRow('profit', '', { amount_change: null, contribution: null, comparison_status: 'incomplete' })])]} />);
    expect(screen.queryByRole('region', { name: '结论' })).toBeNull();
    render(<RunPanel {...props} runs={[structuredRun()]} />);
    expect(screen.queryByRole('region', { name: '结论' })).toBeNull();
  });

  it('offers 调整范围 on finance results only when the settings can be opened', () => {
    const onAdjustScope = vi.fn();
    const run = varianceRun([bridgeRow('profit', '5')]);
    const { unmount } = render(<RunPanel {...props} runs={[run]} />);
    expect(screen.queryByRole('button', { name: '调整范围' })).toBeNull();
    unmount();
    render(<RunPanel {...props} runs={[run]} onAdjustScope={onAdjustScope} />);
    fireEvent.click(screen.getByRole('button', { name: '调整范围' }));
    expect(onAdjustScope).toHaveBeenCalledTimes(1);
    expect(onAdjustScope).toHaveBeenCalledWith(run);
    cleanup();
    render(<RunPanel {...props} runs={[structuredRun()]} onAdjustScope={onAdjustScope} />);
    expect(screen.queryByRole('button', { name: '调整范围' })).toBeNull();
  });

  it('lists results and failures in the history, keeps intermediate steps under their own fold, and names no identifiers', () => {
    const result = structuredRun();
    const probe: AnalysisRun = { ...baseRun, id: 'f'.repeat(32), created_at: '2026-09-07T00:05:00Z', engine: 'python',
      result: { columns: [{ name: 'note', type: 'VARCHAR' }], rows: [{ note: '探查' }], row_count: 1, truncated: false } };
    const failed: AnalysisRun = { ...baseRun, id: '1'.repeat(32), created_at: '2026-09-07T00:10:00Z', execution_status: 'failed', error: '缺少列' };
    render(<RunPanel {...props} runs={[result, probe, failed]} />);
    const history = screen.getByText(/^计算历史/).closest('details')!;
    expect(history.querySelector('summary')!.textContent).toBe('计算历史 · 结果 1 · 未完成 1');
    const rows = within(history).getAllByRole('button').filter((button) => button.classList.contains('analysis-history-row'));
    // Two rows outside the fold (the result and the failure), one inside 中间步骤.
    const steps = screen.getByText('中间步骤 · 1').closest('details')!;
    expect(rows.filter((row) => !steps.contains(row))).toHaveLength(2);
    expect(within(steps).getAllByRole('button')).toHaveLength(1);
    for (const id of [result.id, probe.id, failed.id]) expect(history.textContent).not.toContain(id.slice(0, 12));
  });

  it('folds dataset and run identifiers under 技术信息 in the evidence panel', () => {
    const run = structuredRun({ input_hashes: { ledger: 'd'.repeat(64) }, bindings: { ledger: dataset.id }, output_hash: '9'.repeat(64) });
    render(<RunPanel {...props} runs={[run]} />);
    fireEvent.click(screen.getByRole('button', { name: '查看本次计算依据' }));
    const evidence = screen.getByRole('dialog', { name: '本次计算依据' });
    expect(within(evidence).getByText('本月台账')).toBeTruthy();
    const folds = within(evidence).getAllByText('技术信息').map((summary) => summary.closest('details') as HTMLDetailsElement);
    expect(folds).toHaveLength(2);
    expect(folds.every((fold) => !fold.open)).toBe(true);
    expect(within(folds[0]).getByText('资料编号').nextElementSibling?.textContent).toBe(dataset.id);
    expect(within(folds[1]).getByText('计算编号').nextElementSibling?.textContent).toBe(run.id);
    expect(within(folds[1]).getByText('结果摘要').nextElementSibling?.textContent).toBe('9'.repeat(64));
    // Nothing outside the folds shows an identifier or digest.
    const outside = evidence.cloneNode(true) as HTMLElement;
    outside.querySelectorAll('.analysis-technical').forEach((fold) => fold.remove());
    expect(outside.textContent).not.toContain(dataset.id);
    expect(outside.textContent).not.toContain(run.id);
    expect(outside.textContent).not.toContain('d'.repeat(64));
  });
});

describe('RunPanel 推断 marks', () => {
  // run_metric management_pnl's own shape (foundry/finance_metrics.py): one row per organization and scenario.
  const managementPnl: AnalysisRun = { ...baseRun, engine: 'finance', result: {
    columns: ['organization', 'scenario', 'currency', 'unit', 'revenue', 'cost', 'expense', 'profit'].map((name) => ({ name, type: ['revenue', 'cost', 'expense', 'profit'].includes(name) ? 'DECIMAL' : 'VARCHAR' })),
    rows: [
      { organization: '华东区域', scenario: 'actual', currency: 'CNY', unit: '万元', revenue: '120', cost: '-70', expense: '-20', profit: '30' },
      { organization: '华东区域', scenario: 'budget', currency: 'CNY', unit: '万元', revenue: '130', cost: '-72', expense: '-21', profit: '37' },
    ],
    row_count: 2, truncated: false,
  } };

  it.each([['a management_pnl run', managementPnl], ['a structured aggregate run', structuredRun()]])('never says 推断 on %s', (_, run) => {
    render(<RunPanel {...props} runs={[run]} />);
    expect(screen.getByRole('table', { name: /业务结果|结构化汇总结果/ })).toBeTruthy();
    expect(screen.queryByText(/推断/)).toBeNull();
  });
});

describe('RunPanel result contract warnings', () => {
  const declarations = (warnings: NonNullable<AnalysisRun['row_declarations']>['warnings']): AnalysisRun['row_declarations'] => ({
    rules_version: '2.1.1', requirements_id: null, requirements_fingerprint: null, complete: true, incomplete_reason: null, row_count: 2, rows: [], warnings,
  });
  const contractWarnings: ResultContractWarning[] = [
    { severity: 'warning', code: 'unit_unmarked', rows: [0], row_count: 1,
      message: '1 行没有标明单位，这些行不参与金额配对，结果区原样显示并注明「未标单位」。' },
    { severity: 'warning', code: 'estimate_basis_missing', rows: [1], row_count: 1,
      message: '1 行的文字写了估算用语，但依据列 basis 没有写 estimate。' },
  ];
  const englishSentence = 'Script outputs are retained with code and inputs; reproducibility has not been verified.';

  it('folds the warnings into one Chinese line above the result table, and shows no English sentence', () => {
    render(<RunPanel {...props} runs={[scriptResultRun({ row_declarations: declarations(contractWarnings), warnings: [englishSentence] })]} />);
    const summary = screen.getByText('结果行有 2 处不合约定');
    const disclosure = summary.closest('details') as HTMLDetailsElement;
    expect(disclosure.open).toBe(false);
    expect(within(disclosure).getByText(contractWarnings[0].message)).toBeTruthy();
    expect(within(disclosure).getByText(contractWarnings[1].message)).toBeTruthy();
    const table = screen.getByRole('region', { name: '计算结果' });
    expect(disclosure.compareDocumentPosition(table) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(document.body.textContent).not.toContain(englishSentence);
    expect(document.body.textContent).not.toMatch(/reproducibility|retained/i);
  });

  it('says nothing when the declaration has no warnings or predates them', () => {
    const { unmount } = render(<RunPanel {...props} runs={[scriptResultRun({ row_declarations: declarations([]) })]} />);
    expect(screen.queryByText(/不合约定/)).toBeNull();
    unmount();
    render(<RunPanel {...props} runs={[scriptResultRun({ row_declarations: declarations(undefined) })]} />);
    expect(screen.queryByText(/不合约定/)).toBeNull();
  });
});

describe('RunPanel result head and next steps', () => {
  // run_metric management_pnl's own shape: a finance business result that is not a variance bridge.
  const pnl = (overrides: Partial<AnalysisRun> = {}): AnalysisRun => ({ ...baseRun, engine: 'finance', result: {
    columns: ['organization', 'scenario', 'unit', 'revenue', 'profit'].map((name) => ({ name, type: ['revenue', 'profit'].includes(name) ? 'DECIMAL' : 'VARCHAR' })),
    rows: [{ organization: '华东区域', scenario: 'actual', unit: '万元', revenue: '120', profit: '30' }],
    row_count: 1, truncated: false,
  }, ...overrides });

  afterEach(() => sessionStorage.clear());

  it('names the result for screen readers by the task and keeps the version question in 技术信息 only', () => {
    render(<RunPanel {...props} question="华东经营分析" runs={[pnl()]} />);
    const heading = screen.getByRole('heading', { level: 3, name: '华东经营分析' });
    // The page header shows the task name; the result heading is there for assistive technology only.
    expect(heading.className).toBe('sr-only');
    const article = heading.closest('article') as HTMLElement;
    const technical = Array.from(article.querySelectorAll('.analysis-technical'));
    expect(technical).toHaveLength(1);
    expect(within(technical[0] as HTMLElement).getByText('版本问题').nextElementSibling?.textContent).toBe(analysis.question);
    // Nowhere visible: neither in a heading nor in the result outside 技术信息.
    expect(screen.queryByRole('heading', { name: analysis.question })).toBeNull();
    const outside = article.cloneNode(true) as HTMLElement;
    outside.querySelectorAll('.analysis-technical, .sr-only').forEach((node) => node.remove());
    expect(outside.textContent).not.toContain(analysis.question);
    cleanup();
    render(<RunPanel {...props} runs={[pnl()]} />);
    expect(screen.getByRole('heading', { level: 3, name: analysis.question }).className).toBe('sr-only');
  });

  it('puts the title, the date line and the four states in one header, in that order', () => {
    render(<RunPanel {...props} question="华东经营分析" runs={[pnl()]} />);
    const head = screen.getByRole('heading', { level: 3, name: '华东经营分析' }).parentElement as HTMLElement;
    expect(head.tagName).toBe('HEADER');
    expect(head.classList.contains('analysis-result-head')).toBe(true);
    const children = Array.from(head.children);
    expect(children.map((child) => child.tagName)).toEqual(['H3', 'P', 'DIV']);
    expect(children[1].textContent).toContain('第 1 次计算');
    expect(children[2].getAttribute('aria-label')).toBe('结果状态');
  });

  it('makes 整理成文稿 the primary action on a business result only', () => {
    render(<RunPanel {...props} runs={[pnl()]} />);
    const primary = screen.getByRole('button', { name: '整理成文稿' });
    expect(primary.getAttribute('data-variant')).toBe('default');
    // Right after the cards, ahead of the 依据 button.
    const actions = primary.parentElement as HTMLElement;
    expect(Array.from(actions.querySelectorAll('button')).map((button) => button.textContent)).toEqual(['整理成文稿', '查看本次计算依据']);
    cleanup();
    const failed = { ...baseRun, id: '0'.repeat(32), execution_status: 'failed', error: '缺少列' } as AnalysisRun;
    render(<RunPanel {...props} runs={[failed]} />);
    expect(screen.getByRole('button', { name: '整理成文稿' }).getAttribute('data-variant')).toBe('outline');
  });

  it('says the result is the draft-cited run only while that run is on screen', () => {
    const cited = pnl({ id: '1'.repeat(32) });
    const later = pnl({ id: '2'.repeat(32), created_at: '2026-09-08T00:00:00Z' });
    const draft = { task_id: taskId, schema_version: 1, created_at: '2026-09-09T00:00:00Z', id: '3'.repeat(32), title: '经营简报', body: '',
      run_ids: [cited.id], claims: [], publication_status: 'draft', review_status: 'unreviewed' } as unknown as AnalysisDraft;
    render(<RunPanel {...props} runs={[cited, later]} drafts={[draft]} />);
    const note = '当前结果是最新文稿引用的那次计算；之后的探查和重试保留在「中间步骤」里。';
    expect(screen.getByText(note).className).toBe('analysis-version-note');
    const history = screen.getByText(/^计算历史/).closest('details') as HTMLElement;
    const rows = within(history).getAllByRole('button').filter((button) => button.classList.contains('analysis-history-row'));
    fireEvent.click(rows.find((row) => row.getAttribute('aria-current') !== 'true')!);
    expect(screen.queryByText(note)).toBeNull();
  });

  it('keeps a finance result and its diagnostics in one 技术信息 fold', () => {
    const run = pnl();
    run.result!.diagnostics = [{ code: 'control_total_missing', message: '控制数未提供' }];
    render(<RunPanel {...props} runs={[run]} />);
    const folds = Array.from(document.querySelectorAll('.analysis-result .analysis-technical'));
    expect(folds).toHaveLength(1);
    expect(folds[0].textContent).toContain('原始诊断细节 · 1 项');
    expect(folds[0].textContent).toContain('control_total_missing');
    expect(screen.queryByText(/技术信息 · 诊断/)).toBeNull();
  });

  it('keeps a finance result without rows and its diagnostics in one 技术信息 fold', () => {
    const empty = pnl();
    empty.result = { ...empty.result!, rows: [], row_count: 0, diagnostics: [{ code: 'control_total_missing', message: '控制数未提供' }] };
    render(<RunPanel {...props} runs={[empty]} />);
    const folds = Array.from(document.querySelectorAll('.analysis-result .analysis-technical'));
    expect(folds).toHaveLength(1);
    expect(folds[0].textContent).toContain('原始诊断细节 · 1 项');
    expect(screen.queryByText(/技术信息 · 诊断/)).toBeNull();
    cleanup();
    const failed = { ...baseRun, engine: 'finance', execution_status: 'failed', error: '缺少列',
      result: { columns: [], rows: [], row_count: 0, truncated: false, diagnostics: [{ code: 'scope_missing' }] } } as AnalysisRun;
    render(<RunPanel {...props} runs={[failed]} />);
    const only = Array.from(document.querySelectorAll('.analysis-result .analysis-technical'));
    expect(only).toHaveLength(1);
    expect(only[0].textContent).toContain('scope_missing');
  });

  it('closes the comparison and the evidence panel when another version is picked', () => {
    const other: AnalysisRevision = { ...analysis, id: '9'.repeat(32), question: '另一版分析' };
    const first = pnl({ id: '1'.repeat(32) });
    const second = pnl({ id: '2'.repeat(32), analysis_id: other.id, created_at: '2026-09-08T00:00:00Z' });
    const view = render(<RunPanel {...props} analyses={[analysis, other]} runs={[first, second]} />);
    fireEvent.click(screen.getByRole('button', { name: '比较版本' }));
    fireEvent.click(screen.getByRole('button', { name: '查看本次计算依据' }));
    expect(screen.getByRole('region', { name: '版本比较' })).toBeTruthy();
    expect(screen.getByRole('dialog', { name: '本次计算依据' })).toBeTruthy();
    view.rerender(<RunPanel {...props} analysis={other} analyses={[analysis, other]} runs={[first, second]} />);
    expect(screen.queryByRole('region', { name: '版本比较' })).toBeNull();
    expect(screen.queryByRole('dialog', { name: '本次计算依据' })).toBeNull();
  });

  it('keeps the stored periods on a bridge whose two sides read alike in words', () => {
    render(<RunPanel {...props} runs={[varianceRun([bridgeRow('profit', '-5')], { comparison: {
      actual_scenario: 'actual', baseline_scenario: 'budget', actual_filters: { period: '2026-08' }, baseline_filters: { period: '2026-08:2026-08' },
    } })]} />);
    expect(screen.getByRole('region', { name: '结论' }).textContent).toContain('实际（2026-08）与预算（2026-08:2026-08）相比');
  });
});
