// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import type { DatasetSnapshot, WorkbookHealth } from '../src/bridge.js';
import { FormulaHealthPanel } from '../src/views/analysis/FormulaHealthPanel.js';

const taskId = 'a'.repeat(32);
const base: DatasetSnapshot = {
  id: 'b'.repeat(32), task_id: taskId, schema_version: 1, created_at: '2026-10-01T00:00:00Z',
  name: '月结套表', kind: 'workbook', source_hash: 'c'.repeat(64), source_name: '月结.xlsx', source_file: 'source.xlsx', metadata: {},
};
const health: WorkbookHealth = {
  schema_version: 1, status: 'checked', checked_formula_cells: 120, truncated: false, sheet_count: 3, issue_count: 2,
  issues: [
    { code: 'formula_without_cache', severity: 'info', count: 4, sheets: ['汇总'],
      samples: [{ sheet: '汇总', cell: 'B3', range: 'A1:E8', formula: '=1+1' }] },
    { code: 'hardcoded_number', severity: 'warning', count: 2, sheets: ['汇总'], samples: [
      { sheet: '汇总', cell: 'B12', range: 'A8:E17', formula: '=B5*1.13', detail: '1.13' },
      { sheet: '汇总', cell: 'B13', range: 'A9:E18', formula: '=SUM(B2:B9)+2793.28', detail: '2793.28' },
    ] },
  ],
};
const clean: WorkbookHealth = { schema_version: 1, status: 'checked', checked_formula_cells: 3, truncated: false, sheet_count: 1, issue_count: 0, issues: [] };

afterEach(() => {
  cleanup();
  delete (globalThis as { foundry?: unknown }).foundry;
});

function mount(handler: (command: string, spec: Record<string, unknown>) => unknown = () => ({})) {
  const financeCall = vi.fn(async (_task: string, command: string, spec: Record<string, unknown>) => ({ ok: true, value: handler(command, spec) }));
  (globalThis as { foundry?: unknown }).foundry = { financeCall };
  return financeCall;
}

it('renders nothing when no workbook has a hint', () => {
  mount();
  const csv: DatasetSnapshot = { ...base, id: 'd'.repeat(32), name: '明细', kind: 'table', source_name: 'rows.csv', source_file: 'source.csv' };
  // A derived table carries the original bytes but answers through its original upload.
  const derived: DatasetSnapshot = { ...base, id: 'e'.repeat(32), kind: 'table', metadata: { derived_from: base.id } };
  // Older CLIs may hand back a health record with fields missing.
  const sparse: DatasetSnapshot = { ...base, id: 'f'.repeat(32), workbook_health: { schema_version: 1, status: 'checked' } };
  const { container } = render(<FormulaHealthPanel taskId={taskId}
    datasets={[{ ...base, workbook_health: clean }, csv, derived, sparse, { ...base, id: '1'.repeat(32), source_file: undefined }]} />);
  expect(container.innerHTML).toBe('');
});

it('lists each kind of hint with its words, count and sample cells, warnings first', () => {
  mount();
  render(<FormulaHealthPanel taskId={taskId} datasets={[{ ...base, workbook_health: health }]} />);
  const summary = screen.getByText('公式体检 · 月结套表 · 2 类提示');
  const book = summary.closest('details')!;
  expect(book.open).toBe(false);
  const items = within(book).getAllByRole('listitem').filter((item) => item.classList.contains('analysis-formula-health-item'));
  expect(items.map((item) => item.querySelector('.analysis-formula-health-head')?.textContent)).toEqual([
    '需留意公式里写死了数字2 处',
    '提示公式没有保存计算结果4 处',
  ]);
  expect(items[0].className).toContain('analysis-formula-health-item--warning');
  expect(within(items[0]).getByText('常见于手工调整或临时假设，建议改为引用输入单元格并注明来源。')).toBeTruthy();
  expect(within(items[0]).getByText('=B5*1.13')).toBeTruthy();
  expect(within(items[0]).getByText('写死的数字：1.13')).toBeTruthy();
  expect(within(items[1]).getByText(/在 Excel 中打开并保存后，才能当作数据表读取/)).toBeTruthy();
  expect(within(book).getByText(/这些是提示，不影响导入和计算；是否需要修改由你判断。/)).toBeTruthy();
  expect(within(book).getByRole('button', { name: '使用指南：工作簿公式体检' })).toBeTruthy();
  // Hints never take a button away from the manager.
  for (const button of within(book).getAllByRole('button')) expect((button as HTMLButtonElement).disabled).toBe(false);
});

it('opens the original cell and its surroundings from 查看', async () => {
  const financeCall = mount((command, spec) => command === 'workbook-range-preview' ? {
    dataset_id: base.id, source_hash: base.source_hash, source_name: base.source_name, sheet: spec.sheet, range: spec.range,
    bounds: { min_row: 8, min_col: 1, max_row: 17, max_col: 5 }, cells: [], warnings: [],
  } : {});
  render(<FormulaHealthPanel taskId={taskId} datasets={[{ ...base, workbook_health: health }]} />);
  fireEvent.click(screen.getByRole('button', { name: '查看 汇总!B12' }));
  await waitFor(() => expect(financeCall).toHaveBeenCalledWith(taskId, 'workbook-range-preview', {
    dataset_id: base.id, sheet: '汇总', range: 'A8:E17',
  }));
  expect(screen.getByText('正在查看 汇总!B12 及周围区域。')).toBeTruthy();
  expect(await screen.findByRole('region', { name: '工作簿区域预览 汇总 A8:E17' })).toBeTruthy();
});

it('checks an older workbook on demand and shows the result without storing it', async () => {
  const financeCall = mount((command) => command === 'workbook-health' ? { dataset_id: base.id, source_hash: base.source_hash, ...health } : {});
  render(<FormulaHealthPanel taskId={taskId} datasets={[base]} />);
  expect(screen.getByText('月结套表 · 导入时还没有做公式体检。')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: '体检这本工作簿：月结套表' }));
  await waitFor(() => expect(financeCall).toHaveBeenCalledWith(taskId, 'workbook-health', { dataset_id: base.id }));
  const summary = await screen.findByText('公式体检 · 月结套表 · 2 类提示');
  expect((summary.closest('details') as HTMLDetailsElement).open).toBe(true);
  expect(financeCall.mock.calls.map((call) => call[1])).toEqual(['workbook-health']);
  expect(screen.queryByRole('button', { name: /体检这本工作簿/ })).toBeNull();
});

it('says plainly when an on-demand check finds nothing, and when a check could not finish', async () => {
  mount((command) => command === 'workbook-health' ? { dataset_id: base.id, ...clean } : {});
  const broken: DatasetSnapshot = { ...base, id: '2'.repeat(32), name: '旧套表',
    workbook_health: { schema_version: 1, status: 'unavailable', reason: 'unreadable_workbook' } };
  render(<FormulaHealthPanel taskId={taskId} datasets={[base, broken]} />);
  expect(screen.getByText('旧套表：这本工作簿未能完成公式体检（不影响使用）。')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: '体检这本工作簿：月结套表' }));
  expect(await screen.findByText('月结套表：公式体检没有发现需要提示的地方。')).toBeTruthy();
});

it('shows a refused on-demand check in the manager\'s words', async () => {
  const financeCall = vi.fn(async () => ({ ok: false, refused: true, message: 'dataset source workbook integrity check failed' }));
  (globalThis as { foundry?: unknown }).foundry = { financeCall };
  render(<FormulaHealthPanel taskId={taskId} datasets={[base]} />);
  fireEvent.click(screen.getByRole('button', { name: '体检这本工作簿：月结套表' }));
  expect((await screen.findByRole('alert')).textContent).toContain('这份 Excel 与登记时的内容不一致');
});

it('drops a check that settles after the manager has moved to another task', async () => {
  let settle: (answer: unknown) => void = () => {};
  const financeCall = vi.fn(() => new Promise((resolve) => { settle = resolve; }));
  (globalThis as { foundry?: unknown }).foundry = { financeCall };
  const other = 'd'.repeat(32);
  const later: DatasetSnapshot = { ...base, id: 'e'.repeat(32), task_id: other, name: '下月套表' };
  const { rerender } = render(<FormulaHealthPanel taskId={taskId} datasets={[base]} />);
  fireEvent.click(screen.getByRole('button', { name: '体检这本工作簿：月结套表' }));
  expect(screen.getByText('正在体检…')).toBeTruthy();
  rerender(<FormulaHealthPanel taskId={other} datasets={[later]} />);
  const button = screen.getByRole('button', { name: '体检这本工作簿：下月套表' }) as HTMLButtonElement;
  expect(button.disabled).toBe(false);
  settle({ ok: false, refused: true, message: 'dataset source workbook integrity check failed' });
  await new Promise((resolve) => setTimeout(resolve, 0));
  expect(screen.queryByRole('alert')).toBeNull();
  expect(button.disabled).toBe(false);
  expect(financeCall).toHaveBeenCalledWith(taskId, 'workbook-health', { dataset_id: base.id });
});

it('names hidden sheets and linked files without offering a cell to open', () => {
  mount();
  const sheets: WorkbookHealth = { ...clean, issue_count: 2, issues: [
    { code: 'external_links', severity: 'warning', count: 1, sheets: [], samples: [], targets: ['2026 预算.xlsx'] },
    { code: 'hidden_sheets', severity: 'info', count: 1, sheets: ['底稿'], samples: [{ sheet: '底稿', detail: 'veryHidden' }] },
  ] };
  render(<FormulaHealthPanel taskId={taskId} datasets={[{ ...base, workbook_health: sheets }]} />);
  expect(screen.getByText('链接的文件：2026 预算.xlsx')).toBeTruthy();
  expect(screen.getByText('深度隐藏')).toBeTruthy();
  expect(screen.queryByRole('button', { name: /^查看/ })).toBeNull();
});

it('lists several values in the manager\'s punctuation and explains deliberate #N/A results', () => {
  mount();
  const listed: WorkbookHealth = { ...clean, issue_count: 3, issues: [
    { code: 'volatile_function', severity: 'info', count: 1, sheets: ['汇总'],
      samples: [{ sheet: '汇总', cell: 'B2', range: 'A1:E6', formula: '=OFFSET(A1,0,0)+TODAY()', detail: 'OFFSET, TODAY' }] },
    { code: 'hardcoded_number', severity: 'warning', count: 1, sheets: ['汇总'],
      samples: [{ sheet: '汇总', cell: 'B5', range: 'A1:E9', formula: '=DATE(2026,9,30)', detail: '2026, 9, 30' }] },
    { code: 'cached_error', severity: 'warning', count: 1, sheets: ['汇总'],
      samples: [{ sheet: '汇总', cell: 'B7', range: 'A3:E10', detail: '#N/A' }] },
  ] };
  render(<FormulaHealthPanel taskId={taskId} datasets={[{ ...base, workbook_health: listed }]} />);
  expect(screen.getByText('函数：OFFSET、TODAY')).toBeTruthy();
  expect(screen.getByText('写死的数字：2026、9、30')).toBeTruthy();
  expect(screen.getByText(/若是有意返回的 #N\/A（例如让图表留空），可以忽略。/)).toBeTruthy();
});
