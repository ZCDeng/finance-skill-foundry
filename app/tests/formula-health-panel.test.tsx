// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import type { DatasetSnapshot, WorkbookHealth } from '../src/bridge.js';
import { FormulaHealthDetails } from '../src/views/analysis/FormulaHealthPanel.js';

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

// The file row on the 资料 page (materials-file-list.test) says how many hints and opens this under itself.
it('lists each kind of hint with its words, count and sample cells, warnings first', () => {
  mount();
  render(<FormulaHealthDetails taskId={taskId} dataset={base} health={health} />);
  const book = screen.getByRole('group', { name: '公式体检：月结套表' });
  expect(book.closest('details')).toBeNull();
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
  render(<FormulaHealthDetails taskId={taskId} dataset={base} health={health} />);
  fireEvent.click(screen.getByRole('button', { name: '查看 汇总!B12' }));
  await waitFor(() => expect(financeCall).toHaveBeenCalledWith(taskId, 'workbook-range-preview', {
    dataset_id: base.id, sheet: '汇总', range: 'A8:E17',
  }));
  expect(screen.getByText('正在查看 汇总!B12 及周围区域。')).toBeTruthy();
  expect(await screen.findByRole('region', { name: '工作簿区域预览 汇总 A8:E17' })).toBeTruthy();
});

it('names hidden sheets and linked files without offering a cell to open', () => {
  mount();
  const sheets: WorkbookHealth = { ...clean, issue_count: 2, issues: [
    { code: 'external_links', severity: 'warning', count: 1, sheets: [], samples: [], targets: ['2026 预算.xlsx'] },
    { code: 'hidden_sheets', severity: 'info', count: 1, sheets: ['底稿'], samples: [{ sheet: '底稿', detail: 'veryHidden' }] },
  ] };
  render(<FormulaHealthDetails taskId={taskId} dataset={base} health={sheets} />);
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
  render(<FormulaHealthDetails taskId={taskId} dataset={base} health={listed} />);
  expect(screen.getByText('函数：OFFSET、TODAY')).toBeTruthy();
  expect(screen.getByText('写死的数字：2026、9、30')).toBeTruthy();
  expect(screen.getByText(/若是有意返回的 #N\/A（例如让图表留空），可以忽略。/)).toBeTruthy();
});
