// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { RunPanel } from '../src/views/analysis/RunPanel.js';
import type { AnalysisRevision, AnalysisRun, DatasetSnapshot, FinanceDrilldown } from '../src/bridge.js';

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

    const raw = screen.getByText('原始结果字段 · 6 列').closest('details') as HTMLDetailsElement;
    expect(raw.open).toBe(false);
    fireEvent.click(screen.getByText('原始结果字段 · 6 列'));
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
    expect(screen.getByText('指标“最早订单”有 1 条来源金额缺失，最小值结果已排除这些缺失来源，请复核口径。')).toBeTruthy();
    expect(screen.getByText('指标“客户数”有 2 条来源金额缺失，去重计数结果已排除这些缺失来源，请复核口径。')).toBeTruthy();
    const raw = screen.getByText('原始诊断细节 · 3 项').closest('details') as HTMLDetailsElement;
    expect(raw.open).toBe(false);
    fireEvent.click(screen.getByText('原始诊断细节 · 3 项'));
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
