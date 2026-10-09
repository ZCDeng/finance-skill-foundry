// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { BillingDetail, Bridge, CollectionCaliber, CollectionRun } from '../src/bridge.js';
import { BillingPanel, caliberLines, percent, percentToRate } from '../src/views/analysis/BillingPanel.js';

afterEach(() => { cleanup(); delete (globalThis as { foundry?: Partial<Bridge> }).foundry; });

const at = '2026-10-09T08:00:00Z';
const fields = (kind: BillingDetail['kind']) => ({
  receivable: [{ field: 'bill_id', label: '应收单号', required: true }, { field: 'property_id', label: '房产编号', required: true },
    { field: 'period', label: '账期', required: true }, { field: 'amount_net', label: '应收净额', required: true }],
  receipt: [{ field: 'date', label: '收款日期', required: true }, { field: 'bill_id', label: '应收单号', required: true },
    { field: 'amount', label: '收款金额', required: true }],
  property: [{ field: 'property_id', label: '房产编号', required: true }, { field: 'nature', label: '房产性质', required: false }],
})[kind];
const table = (kind: BillingDetail['kind'], id: string, confirmed: boolean): BillingDetail => {
  const columns = fields(kind).map((field) => field.label);
  const mapping = Object.fromEntries(fields(kind).map((field) => [field.field, field.label]));
  return {
    id: id.repeat(32), kind, name: `海口 ${kind}`, created_at: at, files: [{ name: `${kind}.csv`, rows: 10, encoding: 'gb18030', bytes: 100 }],
    columns, row_count: 410902, proposal: { mapping, by: 'system', at }, confirmation: confirmed ? { mapping, by: 'manager', at } : null,
    fields: fields(kind), missing: [],
  };
};
const defaults = { year_start_month: 1, total_method: 'bounded' as const, related_owners: ['地产'], exclude_related: false, excluded_fee_items: [] };
const variant = { ...defaults, total_method: 'all_receipts' as const, excluded_fee_items: ['商业租金代收'] };
const figures = (current: string, total: string) => ({
  receivable: '1000.00', collected: '821.20', collection_rate_current: current, month_receivable: '100.00', month_collected: '80.00',
  collection_rate_month: '0.8000', arrears_opening: '200.00', arrears_collected: '73.12', arrears_recovery_rate: '0.3656',
  collection_rate_total: total, outstanding: '305.68', advance_balance: '12.00', waiver: '12.60', waiver_rate: '0.0126',
  households: 100, households_settled: 80, household_rate: '0.8000', properties_billed: 100,
});
const run = (id: string, status: 'confirmed' | 'default' | 'trial'): CollectionRun => ({
  id: id.repeat(32), created_at: at, run_by: 'manager',
  params: { ...defaults, as_of: '2026-08-31', group_by: ['nature'], reported: { collection_rate_current: '0.8376' } },
  caliber: { version: status === 'confirmed' ? 1 : null, status, differs: status === 'trial' ? ['total_method'] : [] },
  inputs: { receivable: { id: '1'.repeat(32), name: '海口 应收明细' } },
  result: {
    window: { year_start: '2026-01', as_of: '2026-08-31', as_of_period: '2026-08' },
    figures: { ...figures('0.8212', '0.7316'), reported: { collection_rate_current: { reported: '0.8376', computed: '0.8212', difference_points: '-1.64' } } },
    related: { owners: ['地产'], only: figures('0.1000', '0.1000'), excluded: figures('0.8500', '0.7885') },
    groups: [{ key: { nature: '住宅' }, figures: figures('0.8359', '0.7600') }],
    quality: [{ code: 'void_bills', rows: 260, amount: '0.00', lines: ['应收明细_2026.csv 第 12 行'] }],
    labels: [{ code: 'advance_labelled_current', rows: 36, amount: '448473.72', lines: ['实收明细.csv 第 8 行'] }],
  },
});

function mount({ details, caliber, runs = [] as CollectionRun[], extra = {} as Partial<Bridge> }: {
  details: BillingDetail[]; caliber: CollectionCaliber; runs?: CollectionRun[]; extra?: Partial<Bridge>;
}) {
  const billingCall = vi.fn(async (_task: string, command: string, spec?: Record<string, unknown>) => {
    const value = command === 'collection-state' ? {
      details, caliber,
      runs: runs.map((row) => ({ id: row.id, created_at: row.created_at, as_of: row.params.as_of, group_by: row.params.group_by, caliber: row.caliber, inputs: {}, figures: {} })),
    }
      : command === 'collection-run-read' ? runs.find((row) => row.id === spec?.run)
      : command === 'collection-run' ? (runs.push(run('9', 'confirmed')), runs.at(-1))
      : {};
    return { ok: true as const, value };
  });
  (globalThis as { foundry?: Partial<Bridge> }).foundry = { billingCall: billingCall as unknown as Bridge['billingCall'], ...extra };
  return billingCall;
}

it('writes rates as percentages and takes a typed percentage without floating point', () => {
  expect(percent('0.8375607752862742')).toBe('83.76%');
  expect(percent(null)).toBe('—');
  expect(percentToRate('83.76')).toBe('0.8376');
  expect(percentToRate('5')).toBe('0.05');
  expect(percentToRate('100%')).toBe('1.00');
  expect(percentToRate('八十')).toBeNull();
  expect(caliberLines(variant)).toContain('不算物业费的收费项目：商业租金代收');
});

it('lets the manager confirm the columns the system recognised, and asks for the ones still missing', async () => {
  const pending = table('receivable', '1', false);
  const billingCall = mount({ details: [pending], caliber: { defaults, confirmed: null, proposed: null, effective: defaults, versions: [] } });
  render(<BillingPanel taskId="t" period="2026-08" />);
  const card = await screen.findByText('海口 receivable');
  expect(screen.getByText('待确认列')).toBeTruthy();
  expect(screen.getByText('行业通行默认，未确认')).toBeTruthy();
  const details = card.closest('details')!;
  fireEvent.change(within(details).getByLabelText('海口 receivable 账期'), { target: { value: '' } });
  expect(within(details).getByText('还缺：账期。')).toBeTruthy();
  expect((within(details).getByRole('button', { name: '确认这些列' }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.change(within(details).getByLabelText('海口 receivable 账期'), { target: { value: '账期' } });
  fireEvent.click(within(details).getByRole('button', { name: '确认这些列' }));
  await waitFor(() => expect(billingCall).toHaveBeenCalledWith('t', 'detail-confirm', {
    detail: pending.id, mapping: { bill_id: '应收单号', property_id: '房产编号', period: '账期', amount_net: '应收净额' },
  }));
  expect(await screen.findByText('已确认「海口 receivable」的列。')).toBeTruthy();
});

it('shows the assistant’s 口径 proposal with its reason, confirmed only by the manager’s click', async () => {
  const proposed = { version: 2, params: variant, note: '客户习惯用全部实收', status: 'proposed' as const, by: 'assistant', at };
  const billingCall = mount({
    details: [table('receivable', '1', true), table('receipt', '2', true)],
    caliber: { defaults, confirmed: null, proposed, effective: defaults, versions: [proposed] },
  });
  render(<BillingPanel taskId="t" period="2026-08" />);
  const note = await screen.findByRole('note', { name: '助手提议的口径' });
  expect(within(note).getByText('理由：客户习惯用全部实收')).toBeTruthy();
  expect(within(note).getByText('综合收缴率 = 本年全部实收 ÷ 本年应收（预收和清欠都算进分子）')).toBeTruthy();
  expect(billingCall).not.toHaveBeenCalledWith('t', 'collection-caliber-confirm', expect.anything());
  fireEvent.click(within(note).getByRole('button', { name: '确认这个口径' }));
  await waitFor(() => expect(billingCall).toHaveBeenCalledWith('t', 'collection-caliber-confirm', { version: 2 }));
});

it('runs on the confirmed tables with the date and the reported rate, and shows the rates, the gap and the rows to look at', async () => {
  const runs = [run('8', 'trial')];
  const billingCall = mount({
    details: [table('receivable', '1', true), table('receipt', '2', true), table('property', '3', true)],
    caliber: { defaults, confirmed: null, proposed: null, effective: defaults, versions: [] }, runs,
  });
  render(<BillingPanel taskId="t" period="2026-08" />);
  expect(await screen.findByText('试算')).toBeTruthy();
  expect(screen.getByText(/经理确认口径前，这些数只作参考/)).toBeTruthy();
  const result = screen.getByRole('article', { name: '收缴率结果' });
  expect(within(result).getByLabelText('当期收缴率').textContent).toBe('82.12%');
  expect(within(result).getByLabelText('综合收缴率').textContent).toBe('73.16%');
  expect(result.textContent).toContain('套表填报本年收缴率 83.76%，明细算出 82.12%，差 -1.64 个百分点');
  expect(result.textContent).toContain('剔除关联方后 78.85%');
  expect(result.textContent).toContain('作废账单，不计入：260 行');
  expect(result.textContent).toContain('448,473.72');
  expect(result.textContent).toContain('应收明细_2026.csv 第 12 行');
  fireEvent.click(screen.getByRole('button', { name: '计算收缴率' }));
  await waitFor(() => expect(billingCall).toHaveBeenCalledWith('t', 'collection-run', {
    receivable: '1'.repeat(32), receipt: '2'.repeat(32), property: '3'.repeat(32), as_of: '2026-08-31', group_by: ['nature'],
    reported: { collection_rate_current: '0.8376' },
  }));
  expect(await screen.findByText('已确认口径 · 第 1 版')).toBeTruthy();
});

it('offers the example’s 收费明细 in a practice task only, and nothing changes in a task that can only be read', async () => {
  const taskSampleBilling = vi.fn(async () => ({ ok: true as const, value: { task_id: 't', details: {} } }));
  mount({ details: [], caliber: { defaults, confirmed: null, proposed: null, effective: defaults, versions: [] }, extra: { taskSampleBilling } });
  const { rerender } = render(<BillingPanel taskId="t" practice />);
  fireEvent.click(await screen.findByRole('button', { name: '导入示例收费明细' }));
  await waitFor(() => expect(taskSampleBilling).toHaveBeenCalledWith('t'));
  rerender(<BillingPanel taskId="t" />);
  expect(screen.queryByRole('button', { name: '导入示例收费明细' })).toBeNull();
  rerender(<BillingPanel taskId="t" readOnly />);
  expect((screen.getByRole('button', { name: '导入应收明细' }) as HTMLButtonElement).disabled).toBe(true);
});

it('puts a newer assistant proposal in front of the old confirmation, and finds it without a manual refresh', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  try {
    const confirmed = table('receivable', '1', true);
    const details = [confirmed];
    const billingCall = mount({ details, caliber: { defaults, confirmed: null, proposed: null, effective: defaults, versions: [] } });
    render(<BillingPanel taskId="t" period="2026-08" />);
    expect(await screen.findByText('列已确认')).toBeTruthy();
    // The assistant proposes 账期 from another column, later than the confirmation.
    details[0] = { ...confirmed, columns: [...confirmed.columns, '所属账期'],
      proposal: { mapping: { ...confirmed.proposal!.mapping, period: '所属账期' }, by: 'assistant', at: '2026-10-09T09:00:00Z' } };
    await vi.advanceTimersByTimeAsync(8000);
    expect(await screen.findByText('助手提议了新的对应')).toBeTruthy();
    await waitFor(() => expect((screen.getByLabelText('海口 receivable 账期') as HTMLSelectElement).value).toBe('所属账期'));
    fireEvent.click(screen.getByRole('button', { name: '确认这些列' }));
    await waitFor(() => expect(billingCall).toHaveBeenCalledWith('t', 'detail-confirm', expect.objectContaining({
      mapping: expect.objectContaining({ period: '所属账期' }) })));
  } finally {
    vi.useRealTimers();
  }
});
