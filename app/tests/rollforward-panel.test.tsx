// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { AnalysisRun, Bridge, DatasetSnapshot } from '../src/bridge.js';
import { RollforwardPanel, splitAddress } from '../src/views/analysis/RollforwardPanel.js';

afterEach(() => { cleanup(); delete (globalThis as { foundry?: Partial<Bridge> }).foundry; });

const at = '2026-10-01T08:00:00Z';
const august = { id: 'a'.repeat(32), task_id: 't', schema_version: 1, created_at: at, name: '八月套表', kind: 'workbook', source_hash: 'h1', source_name: '八月套表.xlsx', metadata: {} } as DatasetSnapshot;
const balances = { id: 'b'.repeat(32), task_id: 't', schema_version: 1, created_at: at, name: '九月余额', kind: 'workbook', source_hash: 'h2', source_name: '九月余额.xlsx', metadata: {} } as DatasetSnapshot;
const ledger = { id: 'c'.repeat(32), task_id: 't', schema_version: 1, created_at: at, name: '明细', kind: 'table', source_hash: 'h3', source_name: '明细.csv', metadata: {} } as DatasetSnapshot;
const run = {
  id: 'd'.repeat(32), task_id: 't', schema_version: 1, created_at: at, analysis_id: 'e'.repeat(32), execution_status: 'succeeded',
  reproducibility_status: 'unverified', review_status: 'unreviewed', publication_status: 'draft', input_hashes: {},
  result: { columns: [{ name: 'org', type: 'VARCHAR' }, { name: 'amount', type: 'DECIMAL(38,2)' }], rows: [{ org: '华东', amount: '100.25' }], row_count: 1, truncated: false },
} as AnalysisRun;

const mount = (handler: (command: string, spec: Record<string, unknown>) => unknown, extra: Partial<Bridge> = {}) => {
  const financeCall = vi.fn(async (_task: string, command: string, spec?: Record<string, unknown>) => ({ ok: true, value: handler(command, spec ?? {}) }));
  (globalThis as { foundry?: Partial<Bridge> }).foundry = { financeCall: financeCall as unknown as Bridge['financeCall'], ...extra };
  return financeCall;
};
function choose(label: string, option: RegExp | string) {
  fireEvent.click(screen.getByRole('button', { name: label }));
  fireEvent.click(screen.getByRole('option', { name: option }));
}
const type = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
const commands = (financeCall: ReturnType<typeof mount>) => financeCall.mock.calls.map((call) => call[1]);

it('reads a typed address the way the manager writes it', () => {
  expect(splitAddress('利润表!b5')).toEqual({ sheet: '利润表', cell: 'B5' });
  expect(splitAddress('利润表！$B$5')).toEqual({ sheet: '利润表', cell: 'B5' });
  expect(splitAddress("'Q3 P&L'!C7")).toEqual({ sheet: 'Q3 P&L', cell: 'C7' });
  expect(splitAddress('B5')).toEqual({ sheet: '', cell: 'B5' });
});

it('previews the mapping, writes the copy as the manager and says what it did and did not do', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.assign(navigator, { clipboard: { writeText } });
  const onApplied = vi.fn();
  const rollforwardExport = vi.fn(async () => ({ ok: true as const, value: { exported: true, filename: '八月套表（2026-09 滚动）.xlsx' } }));
  const financeCall = mount((command) => {
    if (command === 'workbook-rollforward-templates') return { templates: [] };
    if (command === 'workbook-rollforward-preview') return {
      plan_id: 'plan-1', period: '2026-09', workbook_supported: true, unsupported_features: [],
      counts: { write: 3, blocked: 0, unchanged: 0 }, title_hints: [{ sheet: '利润表', cell: 'A1', target: '利润表!A1', text: '华东公司利润表 2026年08月', period: '2026-08', mapped: true }],
      rows: [
        { index: 0, target: '利润表!B5', status: 'write', old_value: '1000', new_value: '1234.56', cell_type: 'number', notes: [], source: { kind: 'dataset', name: '九月余额', sheet: '科目余额', range: 'B1:B2' } },
        { index: 1, target: '利润表!A1', status: 'write', old_value: '华东公司利润表 2026年08月', new_value: '华东公司利润表 2026年09月', cell_type: 'text', notes: [], source: { kind: 'value', manager_value: '华东公司利润表 2026年09月', note: '' } },
        { index: 2, target: '利润表!C5', status: 'write', old_value: null, new_value: '100.25', cell_type: 'number', notes: [], source: { kind: 'run', row: 0, column: 'amount' } },
      ],
      change_log: { tsv: 'preview-tsv', markdown: 'preview-md' },
    };
    if (command === 'workbook-rollforward-apply') return {
      run_id: 'plan-1', output_name: '八月套表（2026-09 滚动）', counts: { write: 3, blocked: 0, unchanged: 0 }, formula_cache_cleared: true,
      change_log: { tsv: '单元格\t原值\t新值\t来源\t状态/原因\n', markdown: '# 下月套表变更记录\n' },
    };
    if (command === 'workbook-rollforward-template-save') return { id: 'tpl-1', name: '华东月度套表', mapping_count: 3, mappings: [] };
    return {};
  }, { rollforwardExport });
  render(<RollforwardPanel taskId="t" datasets={[august, balances, ledger]} runs={[run]} busy={false} onApplied={onApplied} />);
  // Nothing is picked or loaded until the manager chooses last month's workbook.
  expect(financeCall).not.toHaveBeenCalled();
  expect((screen.getByRole('button', { name: '预览' }) as HTMLButtonElement).disabled).toBe(true);
  choose('上月套表', /八月套表/);
  await waitFor(() => expect(financeCall).toHaveBeenCalledWith('t', 'workbook-rollforward-templates', { dataset_id: august.id }));
  type('新月份', '2026-09');

  type('第 1 行目标单元格', '利润表!B5');
  choose('第 1 行来源', /^资料区域合计/);
  choose('第 1 行来源资料', /九月余额/);
  // A CSV is not a workbook a cell can be read from.
  fireEvent.click(screen.getByRole('button', { name: '第 1 行来源资料' }));
  expect(screen.queryByRole('option', { name: /明细/ })).toBeNull();
  fireEvent.keyDown(screen.getByRole('listbox'), { key: 'Escape' });
  type('第 1 行区域', '科目余额!b1:b2');

  fireEvent.click(screen.getByRole('button', { name: '添加一行' }));
  type('第 2 行目标单元格', '利润表!A1');
  choose('第 2 行来源', /^手填值/);
  type('第 2 行手填值', '华东公司利润表 2026年09月');

  fireEvent.click(screen.getByRole('button', { name: '添加一行' }));
  type('第 3 行目标单元格', '利润表!C5');
  choose('第 3 行来源', /^计算结果/);
  choose('第 3 行计算结果', /第 1 次计算/);
  choose('第 3 行取哪一列', /^amount/);

  fireEvent.click(screen.getByRole('button', { name: '预览' }));
  await waitFor(() => expect(financeCall).toHaveBeenCalledWith('t', 'workbook-rollforward-preview', {
    dataset_id: august.id, source_hash: 'h1', period: '2026-09',
    mappings: [
      { target: { sheet: '利润表', cell: 'B5' }, source: { kind: 'dataset', dataset_id: balances.id, source_hash: 'h2', sheet: '科目余额', range: 'B1:B2' } },
      { target: { sheet: '利润表', cell: 'A1' }, source: { kind: 'value', value: '华东公司利润表 2026年09月' } },
      { target: { sheet: '利润表', cell: 'C5' }, source: { kind: 'run', run_id: run.id, row: 0, column: 'amount' } },
    ],
  }));
  const table = await screen.findByRole('region', { name: '滚动预览' });
  expect(within(table).getAllByText('将写入')).toHaveLength(3);
  // The title goes in as text, and says so; the amounts do not need to.
  expect(within(table).getAllByText('按文字写入')).toHaveLength(1);
  expect(within(table).getByText('九月余额 · 科目余额!B1:B2（合计）')).toBeTruthy();
  expect(within(table).getByText('计算结果 第 1 行 · amount')).toBeTruthy();
  expect(screen.getByText(/预览完成：将写入 3 格/)).toBeTruthy();
  // The title is mapped, so nothing warns about it.
  expect(screen.queryByText(/还写着别的月份/)).toBeNull();

  fireEvent.click(screen.getByRole('button', { name: '生成下月副本' }));
  await waitFor(() => expect(financeCall).toHaveBeenCalledWith('t', 'workbook-rollforward-apply', { plan_id: 'plan-1' }));
  expect(await screen.findByText('已生成「八月套表（2026-09 滚动）」，在资料列表里。原工作簿未改动；公式会在 Excel 打开时重算：请「导出下月副本」，在 Excel 里打开并保存，再重新添加，本应用才能读到公式结果。')).toBeTruthy();
  expect(onApplied).toHaveBeenCalled();
  expect((screen.getByRole('button', { name: '生成下月副本' }) as HTMLButtonElement).disabled).toBe(true);

  fireEvent.click(screen.getByRole('button', { name: '复制变更记录' }));
  await waitFor(() => expect(writeText).toHaveBeenCalledWith('单元格\t原值\t新值\t来源\t状态/原因\n'));

  // The copy goes where she saves it; the filed one stays as it was made.
  fireEvent.click(screen.getByRole('button', { name: '导出下月副本' }));
  await waitFor(() => expect(rollforwardExport).toHaveBeenCalledWith('t', 'plan-1', '八月套表（2026-09 滚动）'));
  expect(await screen.findByText(/已导出「八月套表（2026-09 滚动）.xlsx」。在 Excel 里打开、检查并保存后，再到资料页重新添加/)).toBeTruthy();

  type('模板名称', '华东月度套表');
  fireEvent.click(screen.getByRole('button', { name: '存为下月模板' }));
  await waitFor(() => expect(financeCall).toHaveBeenCalledWith('t', 'workbook-rollforward-template-save', { plan_id: 'plan-1', name: '华东月度套表' }));
  expect(await screen.findByText(/已存为下月模板「华东月度套表」/)).toBeTruthy();
  expect(commands(financeCall)).toEqual([
    'workbook-rollforward-templates', 'workbook-rollforward-preview', 'workbook-rollforward-apply', 'workbook-rollforward-template-save',
  ]);
});

it('lists what will not be written, with the reason in words, and offers the stale title for mapping', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.assign(navigator, { clipboard: { writeText } });
  const financeCall = mount((command) => command === 'workbook-rollforward-preview' ? {
    plan_id: 'plan-2', period: '2026-09', workbook_supported: false, unsupported_features: ['charts', 'drawings', 'extensions'],
    counts: { write: 1, blocked: 3, unchanged: 1 },
    title_hints: [{ sheet: '利润表', cell: 'A1', target: '利润表!A1', text: '华东公司利润表 2026年08月', period: '2026-08', mapped: false }],
    rows: [
      { index: 0, target: '利润表!B7', status: 'blocked', reason_code: 'formula_cell', reason: '目标是公式单元格，公式不会被覆盖', old_value: '=B5-B6', new_value: '400', cell_type: 'number', notes: [], source: { kind: 'value', manager_value: '400' } },
      { index: 4, target: '利润表!B8', status: 'blocked', reason_code: 'text_into_number_cell', reason: '目标原来是数字（或设成了数字、日期格式），这个值会按文字写入，Excel 的合计和公式会漏掉它；金额请写成不带千分位、括号和货币符号的数字，例如 -1200.50', old_value: '1000', new_value: '1,200', cell_type: 'text', notes: [], source: { kind: 'value', manager_value: '1,200' } },
      { index: 1, target: '利润表!E6', status: 'blocked', reason_code: 'merged_non_anchor', reason: '目标在合并单元格里，但不是左上角那一格；只能写左上角', old_value: null, new_value: '1', cell_type: 'number', notes: [], source: { kind: 'value', manager_value: '1' } },
      { index: 2, target: '利润表!B5', status: 'write', old_value: '1000', new_value: '123456789012345678.12', cell_type: 'text', notes: ['decimal_written_as_text'], source: { kind: 'value', manager_value: '123456789012345678.12' } },
      { index: 3, target: '利润表!B6', status: 'unchanged', old_value: '600', new_value: '600', cell_type: 'number', notes: [], source: { kind: 'value', manager_value: '600' } },
    ],
    change_log: { tsv: 'checklist-tsv', markdown: 'checklist-md' },
  } : { templates: [] });
  render(<RollforwardPanel taskId="t" datasets={[august, balances]} runs={[]} busy={false} />);
  choose('上月套表', /八月套表/);
  type('新月份', '2026-09');
  type('第 1 行目标单元格', '利润表!B7');
  choose('第 1 行来源', /^手填值/);
  type('第 1 行手填值', '400');
  fireEvent.click(screen.getByRole('button', { name: '预览' }));

  const table = await screen.findByRole('region', { name: '滚动预览' });
  expect(within(table).getAllByText('不写入')).toHaveLength(3);
  expect(within(table).getByText('目标是公式单元格，公式不会被覆盖')).toBeTruthy();
  // Text that would turn an amount cell into text is listed, not written, with what to do instead.
  expect(within(table).getByText(/Excel 的合计和公式会漏掉它；金额请写成不带千分位/)).toBeTruthy();
  // No copy will be made of this workbook, so nothing says 将写入: those cells are hers to fill in.
  expect(within(table).queryByText('将写入')).toBeNull();
  expect(within(table).getByText('需手工填写')).toBeTruthy();
  expect(within(table).getByText(/需手工填写 1/)).toBeTruthy();
  expect(within(table).getByText('目标在合并单元格里，但不是左上角那一格；只能写左上角')).toBeTruthy();
  expect(within(table).getByText('无变化')).toBeTruthy();
  expect(within(table).getByText('位数超出 Excel 能精确保存的范围，按文字写入完整数字')).toBeTruthy();
  // Words and an icon, never colour alone: the blocked badge carries both.
  const badge = within(table).getAllByText('不写入')[0];
  expect(badge.querySelector('svg')).toBeTruthy();
  expect(badge.getAttribute('data-variant')).toBe('destructive');

  expect(screen.getByText(/含有图表、图片、形状或批注、迷你图、部分下拉列表或条件格式等扩展内容，复制后会丢失，所以不会生成副本/)).toBeTruthy();
  expect((screen.getByRole('button', { name: '生成下月副本' }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: '复制清单' }));
  await waitFor(() => expect(writeText).toHaveBeenCalledWith('checklist-tsv'));

  expect(screen.getByText(/利润表!A1「华东公司利润表 2026年08月」/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: '加到映射' }));
  expect((screen.getByLabelText('第 2 行目标单元格') as HTMLInputElement).value).toBe('利润表!A1');
  expect((screen.getByLabelText('第 2 行手填值') as HTMLInputElement).placeholder).toBe('上次：华东公司利润表 2026年08月');
  // The mapping changed, so the old preview no longer speaks for it.
  expect(screen.queryByRole('region', { name: '滚动预览' })).toBeNull();
  expect(commands(financeCall).filter((name) => name === 'workbook-rollforward-apply')).toEqual([]);
});

it('fills the mapping from a saved template and waits for this month\'s sources', async () => {
  const financeCall = mount((command) => command === 'workbook-rollforward-templates' ? {
    templates: [{ id: 'tpl-1', name: '华东月度套表', mapping_count: 2, mappings: [
      { target: { sheet: '利润表', cell: 'B5' }, source: { kind: 'dataset', sheet: '科目余额', range: 'B1:B2', hint: '#月余额' } },
      { target: { sheet: '利润表', cell: 'A1' }, source: { kind: 'value', note: '标题', last_value: '华东公司利润表 ####年##月' } },
    ] }],
  } : {});
  render(<RollforwardPanel taskId="t" datasets={[august, balances]} runs={[]} busy={false} />);
  choose('上月套表', /八月套表/);
  await waitFor(() => expect(financeCall).toHaveBeenCalledTimes(1));
  choose('套用模板', /华东月度套表/);
  type('新月份', '2026-10');
  expect((screen.getByLabelText('第 1 行目标单元格') as HTMLInputElement).value).toBe('利润表!B5');
  expect((screen.getByLabelText('第 1 行区域') as HTMLInputElement).value).toBe('科目余额!B1:B2');
  expect(screen.getByText('上次用的是：#月余额')).toBeTruthy();
  expect((screen.getByLabelText('第 2 行手填值') as HTMLInputElement).value).toBe('');
  expect(screen.getByText(/还有 2 行没填完（第 1、2 行）/)).toBeTruthy();
  expect((screen.getByRole('button', { name: '预览' }) as HTMLButtonElement).disabled).toBe(true);
  choose('第 1 行来源资料', /九月余额/);
  type('第 2 行手填值', '华东公司利润表 2026年10月');
  expect((screen.getByRole('button', { name: '预览' }) as HTMLButtonElement).disabled).toBe(false);
});

it('renders nothing when the task has no workbook and tolerates an older engine', async () => {
  mount(() => ({}));
  const { container } = render(<RollforwardPanel taskId="t" datasets={[ledger]} runs={[]} busy={false} />);
  expect(container.innerHTML).toBe('');
  cleanup();
  render(<RollforwardPanel taskId="t" datasets={[august]} runs={[]} busy={false} />);
  choose('上月套表', /八月套表/);
  type('新月份', '2026-09');
  type('第 1 行目标单元格', '利润表!B5');
  choose('第 1 行来源', /^手填值/);
  type('第 1 行手填值', '1');
  fireEvent.click(screen.getByRole('button', { name: '预览' }));
  // An answer without rows or counts draws an empty preview rather than crashing.
  expect(await screen.findByRole('region', { name: '滚动预览' })).toBeTruthy();
  expect((screen.getByRole('button', { name: '生成下月副本' }) as HTMLButtonElement).disabled).toBe(true);
});

it('says in words why a copy was not made or not exported', async () => {
  const { friendlyError } = await import('../src/views/analysis/glossary.js');
  expect(friendlyError('rollforward workbook has parts a copy would lose (charts, extensions); no copy was made')).toMatch(/^这本工作簿含有.*迷你图/);
  expect(friendlyError('rollforward export destination must be an absolute .xlsx path')).toMatch(/^请把文件名保存为 \.xlsx/);
  expect(friendlyError('rollforward export destination cannot be inside the store')).toMatch(/^不能导出到本应用自己的数据文件夹/);
  expect(friendlyError('rollforward copy integrity check failed')).toMatch(/^资料列表里的下月副本和生成时的记录对不上/);
  expect(friendlyError('only the manager can export a roll-forward copy')).toMatch(/^下月副本只能由你/);
});
