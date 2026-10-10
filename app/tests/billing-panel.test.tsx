// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { BillingCommand, BillingDetail, Bridge, CollectionCaliber, CollectionRun, DrillLevel } from '../src/bridge.js';
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

it('opens on the run a card in the conversation asked for, not the newest, and lets go of the request once shown', async () => {
  const older = run('2', 'confirmed');
  const newest = { ...run('3', 'trial'), created_at: '2026-10-10T08:00:00Z' };
  const billingCall = mount({ details: [table('receivable', 'a', true)], caliber: { defaults, confirmed: null, proposed: null, effective: defaults, versions: [] },
    runs: [older, newest] });
  const onShown = vi.fn();
  const scroll = vi.fn();
  const before = HTMLElement.prototype.scrollIntoView;
  HTMLElement.prototype.scrollIntoView = scroll;
  render(<BillingPanel taskId="t" show={{ id: older.id, count: 1 }} onShown={onShown} />);
  await waitFor(() => expect(onShown).toHaveBeenCalledOnce());
  const reads = billingCall.mock.calls.filter(([, command]) => command === 'collection-run-read').map(([, , spec]) => spec?.run);
  expect(new Set(reads)).toEqual(new Set([older.id]));
  expect(scroll).toHaveBeenCalledWith({ block: 'start' });
  HTMLElement.prototype.scrollIntoView = before;
});

const sums = (base: string, done: string, outstanding: string, rate: string | null) => ({ base, done, outstanding, rate });
function drillLevel(path: (string | null)[], ties = true): DrillLevel {
  const levels = [{ key: 'city', label: '城市公司' }, { key: 'project', label: '项目' }, { key: 'property_id', label: '房产' }, { key: 'bill', label: '账单' }];
  const whole = { label: '全部', ...sums('1000.00', '821.20', '178.80', '0.8212') };
  const common = { run_id: '8'.repeat(32), figure: 'collection_rate_current' as const, label: '当期收缴率', base_label: '本年应收', done_label: '当期已收',
    as_of: '2026-08-31', caliber: { version: 1, status: 'confirmed' as const, differs: [] }, levels, whole,
    run_check: { base: '1000.00', done: '821.20', ties: true }, gap: ties ? { base: '0.00', done: '0.00' } : { base: '-10.00', done: '0.00' } };
  if (!path.length) {
    return { ...common, path: [], level: levels[0], total: sums('1000.00', '821.20', '178.80', '0.8212'), ties, row_count: 2, rows: [
      { value: '海口城市公司', label: '海口城市公司', properties: 90, ...sums('990.00', '818.20', '171.80', '0.8265') },
      { value: null, label: '（空）', properties: 1, ...sums('10.00', '3.00', '7.00', '0.3000') }] };
  }
  return { ...common, path: [{ level: 'city', value: '海口城市公司', label: '海口城市公司', ...sums('990.00', '818.20', '171.80', '0.8265') }],
    level: levels[1], total: sums('990.00', '818.20', '171.80', '0.8265'), ties, row_count: 250,
    rows: [{ value: '南洋城', label: '南洋城', properties: 40, ...sums('500.00', '350.00', '150.00', '0.7000') }] };
}

it('takes a rate apart level by level, says each level adds up, and exports one where the manager picks', async () => {
  const runs = [run('8', 'confirmed')];
  mount({ details: [table('receivable', '1', true), table('receipt', '2', true)],
    caliber: { defaults, confirmed: null, proposed: null, effective: defaults, versions: [] }, runs });
  const foundry = (globalThis as unknown as { foundry: Partial<Bridge> }).foundry;
  const plain = foundry.billingCall!;
  const drill = vi.fn(async (task: string, command: BillingCommand, spec?: Record<string, unknown>) => command === 'collection-drill'
    ? { ok: true as const, value: drillLevel(spec!.path as (string | null)[]) } : plain(task, command, spec));
  const save = vi.fn(async () => ({ ok: true as const, value: { exported: true as const, rows: 250 } }));
  foundry.billingCall = drill as unknown as Bridge['billingCall'];
  foundry.billingDrillExport = save as unknown as Bridge['billingDrillExport'];
  render(<BillingPanel taskId="t" period="2026-08" />);
  fireEvent.click(await screen.findByRole('button', { name: '往下拆当期收缴率' }));
  const section = await screen.findByRole('region', { name: '往下拆：当期收缴率' });
  expect(drill).toHaveBeenLastCalledWith('t', 'collection-drill', { run: '8'.repeat(32), figure: 'collection_rate_current', path: [] });
  await within(section).findByText(/等于这次计算结果的数/);
  expect(within(section).getAllByRole('row').map((row) => row.textContent)).toEqual([
    '城市公司户数本年应收当期已收未收当期收缴率', '海口城市公司90990.00818.20171.8082.65%', '（空）110.003.007.0030.00%']);
  fireEvent.click(within(section).getByRole('button', { name: '拆开「海口城市公司」，看项目' }));
  await within(section).findByText('南洋城');
  expect(drill).toHaveBeenLastCalledWith('t', 'collection-drill', { run: '8'.repeat(32), figure: 'collection_rate_current', path: ['海口城市公司'] });
  expect(within(section).getByText(/等于上一层「海口城市公司」的数/)).toBeTruthy();
  expect(within(section).getByText('共 250 行，按未收从多到少列出前 1 行；全部见导出。点名称往下拆一层。')).toBeTruthy();
  const trail = within(section).getByRole('navigation', { name: '拆到哪一层' });
  expect(within(trail).getByText('海口城市公司').getAttribute('aria-current')).toBe('location');
  fireEvent.click(within(section).getByRole('button', { name: /导出 Excel/ }));
  await waitFor(() => expect(save).toHaveBeenCalledWith('t', { run: '8'.repeat(32), figure: 'collection_rate_current', path: ['海口城市公司'],
    name: '当期收缴率-海口城市公司-项目' }));
  expect(await within(section).findByText('已导出 250 行。')).toBeTruthy();
  fireEvent.click(within(trail).getByRole('button', { name: '全部' }));
  await waitFor(() => expect(drill).toHaveBeenLastCalledWith('t', 'collection-drill', { run: '8'.repeat(32), figure: 'collection_rate_current', path: [] }));
  fireEvent.click(within(section).getByRole('button', { name: /收起/ }));
  expect(screen.queryByRole('region', { name: /往下拆/ })).toBeNull();
});

it('opens the row clicked on the level shown, even while the next level is still on its way', async () => {
  const runs = [run('8', 'confirmed')];
  mount({ details: [table('receivable', '1', true), table('receipt', '2', true)],
    caliber: { defaults, confirmed: null, proposed: null, effective: defaults, versions: [] }, runs });
  const foundry = (globalThis as unknown as { foundry: Partial<Bridge> }).foundry;
  const plain = foundry.billingCall!;
  const waiting: (() => void)[] = [];
  const drill = vi.fn(async (task: string, command: BillingCommand, spec?: Record<string, unknown>) => {
    if (command !== 'collection-drill') return plain(task, command, spec);
    const path = spec!.path as (string | null)[];
    // The city level comes back at once; a city's projects wait until let through.
    if (path.length) await new Promise<void>((resolve) => waiting.push(resolve));
    return { ok: true as const, value: drillLevel(path) };
  });
  const save = vi.fn(async () => ({ ok: true as const, value: { exported: true as const, rows: 2 } }));
  foundry.billingCall = drill as unknown as Bridge['billingCall'];
  foundry.billingDrillExport = save as unknown as Bridge['billingDrillExport'];
  render(<BillingPanel taskId="t" period="2026-08" />);
  fireEvent.click(await screen.findByRole('button', { name: '往下拆当期收缴率' }));
  const section = await screen.findByRole('region', { name: '往下拆：当期收缴率' });
  await within(section).findByText(/等于这次计算结果的数/);
  fireEvent.click(within(section).getByRole('button', { name: '拆开「海口城市公司」，看项目' }));
  // Still on the city level: another city is opened from the top, not as a project of the first, and the export is the cities'.
  fireEvent.click(within(section).getByRole('button', { name: '拆开「（空）」，看项目' }));
  expect(drill).toHaveBeenLastCalledWith('t', 'collection-drill', { run: '8'.repeat(32), figure: 'collection_rate_current', path: [null] });
  fireEvent.click(within(section).getByRole('button', { name: /导出 Excel/ }));
  await waitFor(() => expect(save).toHaveBeenCalledWith('t', { run: '8'.repeat(32), figure: 'collection_rate_current', path: [],
    name: '当期收缴率-城市公司' }));
  waiting.forEach((resolve) => resolve());
});

it('marks a level that does not add up to the row above it', async () => {
  const runs = [run('8', 'confirmed')];
  mount({ details: [table('receivable', '1', true), table('receipt', '2', true)],
    caliber: { defaults, confirmed: null, proposed: null, effective: defaults, versions: [] }, runs });
  const foundry = (globalThis as unknown as { foundry: Partial<Bridge> }).foundry;
  const plain = foundry.billingCall!;
  foundry.billingCall = (async (task: string, command: BillingCommand, spec?: Record<string, unknown>) => command === 'collection-drill'
    ? { ok: true as const, value: drillLevel(['海口城市公司'], false) } : plain(task, command, spec)) as unknown as Bridge['billingCall'];
  render(<BillingPanel taskId="t" period="2026-08" />);
  fireEvent.click(await screen.findByRole('button', { name: '往下拆清欠率' }));
  const section = await screen.findByRole('region', { name: '往下拆：当期收缴率' });
  expect((await within(section).findByText(/和上一层「海口城市公司」的数对不上/)).textContent).toContain('本年应收差 (10.00)');
});

it('offers no drill of a total rate counted over every receipt', async () => {
  const counted = { ...run('8', 'confirmed'), params: { ...run('8', 'confirmed').params, total_method: 'all_receipts' as const } };
  mount({ details: [table('receivable', '1', true), table('receipt', '2', true)],
    caliber: { defaults, confirmed: null, proposed: null, effective: defaults, versions: [] }, runs: [counted] });
  render(<BillingPanel taskId="t" period="2026-08" />);
  expect(await screen.findByRole('button', { name: '往下拆当期收缴率' })).toBeTruthy();
  expect(screen.queryByRole('button', { name: '往下拆综合收缴率' })).toBeNull();
});

it('says so when the whole no longer adds up to what the run filed', async () => {
  mount({ details: [table('receivable', '1', true), table('receipt', '2', true)],
    caliber: { defaults, confirmed: null, proposed: null, effective: defaults, versions: [] }, runs: [run('8', 'confirmed')] });
  const foundry = (globalThis as unknown as { foundry: Partial<Bridge> }).foundry;
  const plain = foundry.billingCall!;
  const level = { ...drillLevel([]), run_check: { base: '1001.00', done: '821.20', ties: false } };
  foundry.billingCall = (async (task: string, command: BillingCommand, spec?: Record<string, unknown>) => command === 'collection-drill'
    ? { ok: true as const, value: level } : plain(task, command, spec)) as unknown as Bridge['billingCall'];
  render(<BillingPanel taskId="t" period="2026-08" />);
  fireEvent.click(await screen.findByRole('button', { name: '往下拆当期收缴率' }));
  const section = await screen.findByRole('region', { name: '往下拆：当期收缴率' });
  expect((await within(section).findByRole('alert')).textContent).toBe(
    '从明细重新加总的本年应收 1,000.00、当期已收 821.20，和这次计算记下的 1,001.00、821.20 不一致。请重新计算后再拆。');
  expect(within(section).queryByText(/等于这次计算结果的数/)).toBeNull();
});
