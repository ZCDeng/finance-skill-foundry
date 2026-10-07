// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import type { DatasetSnapshot, WorkbookHealth } from '../src/bridge.js';
import { MaterialsFileList, fileMeta, materialsAnchor } from '../src/views/analysis/MaterialsFileList.js';

const taskId = 'a'.repeat(32);
const workbook: DatasetSnapshot = {
  id: 'b'.repeat(32), task_id: taskId, schema_version: 1, created_at: '2026-10-01T00:00:00Z',
  name: '月结套表', kind: 'workbook', source_hash: 'c'.repeat(64), source_name: '月结.xlsx', source_file: 'source.xlsx',
  metadata: { period: '2026-08', unit: '万元', currency: 'CNY' }, transformation: { sheet_count: 3 },
};
const csv: DatasetSnapshot = { ...workbook, id: 'd'.repeat(32), name: '回款明细', kind: 'table', source_name: 'rows.csv', source_file: 'source.csv',
  metadata: {}, transformation: undefined, row_count: 12 };
// A table the manager's confirmation cut out of the workbook: it carries the original bytes but answers through its upload.
const derived: DatasetSnapshot = { ...workbook, id: 'e'.repeat(32), name: '02·GL科目余额表', kind: 'table', transformation: undefined, row_count: 40,
  metadata: { derived_from: workbook.id, sheet: '02·GL科目余额表' } };
const health: WorkbookHealth = {
  schema_version: 1, status: 'checked', checked_formula_cells: 120, truncated: false, sheet_count: 3, issue_count: 2,
  issues: [
    { code: 'formula_without_cache', severity: 'info', count: 4, sheets: ['汇总'], samples: [] },
    { code: 'hardcoded_number', severity: 'warning', count: 2, sheets: ['汇总'], samples: [] },
  ],
};
const clean: WorkbookHealth = { schema_version: 1, status: 'checked', checked_formula_cells: 3, truncated: false, sheet_count: 1, issue_count: 0, issues: [] };

const column = (letter: string, display: string, role: string, pair: string | null = null) => ({ letter, header: display, display, role, pair, direction: null });
const sheet = (overrides: Record<string, unknown> = {}) => ({
  sheet: '02·GL科目余额表', decision: 'table', reason: null, header_row: 4, title_rows: [1, 2],
  columns: [column('A', '科目代码', 'account_code'), column('C', '类别', 'category'), column('G', '本期发生额借方', 'debit', 'amount_1'), column('H', '本期发生额贷方', 'credit', 'amount_1')],
  amount_pairs: [{ id: 'amount_1', label: '本期发生额', debit: 'G', credit: 'H', primary: true, direction: { kind: 'by_category', column: 'C' } }],
  excluded_rows: [], fill_down_columns: [], scope_hints: { period: '2026-08', currency: '', unit: '元' },
  preview: [{ row: 4, is_header: true, cells: [{ letter: 'A', text: '科目代码' }] }], confidence: 0.9, blocked_reason: null, ...overrides,
});
const proposal = (datasetId: string, state: string, sheets = [sheet()]) => ({ id: `p-${datasetId}`, dataset_id: datasetId, revision: 1, structure_state: state, sheets, template_matches: [] });

type Answers = { proposals?: unknown[]; confirmations?: unknown[]; health?: (spec: Record<string, unknown>) => unknown };
function mount(answers: Answers = {}) {
  const financeCall = vi.fn(async (_task: string, command: string, spec: Record<string, unknown>) => {
    if (command === 'structure-proposal-list') return { ok: true, value: { proposals: answers.proposals ?? [] } };
    if (command === 'structure-confirmation-list') return { ok: true, value: { confirmations: answers.confirmations ?? [] } };
    if (command === 'workbook-health' && answers.health) return answers.health(spec);
    return { ok: true, value: {} };
  });
  (globalThis as { foundry?: unknown }).foundry = { financeCall };
  return financeCall;
}
const calls = (financeCall: ReturnType<typeof mount>, command: string) => financeCall.mock.calls.filter((call) => call[1] === command);

function List(props: Partial<Parameters<typeof MaterialsFileList>[0]> & { datasets: DatasetSnapshot[] }) {
  return <MaterialsFileList taskId={taskId} busy={false} preview={null} onPreview={() => {}} onClosePreview={() => {}} onRefresh={() => {}} {...props} />;
}
const rowOf = (name: string) => screen.getByText(name, { selector: '.fnd-title' }).closest('li') as HTMLElement;

afterEach(() => {
  cleanup();
  document.body.innerHTML = '';
  delete (globalThis as { foundry?: unknown }).foundry;
});

describe('the 资料 file list', () => {
  it('gives every file one row, named once, with its kind, size, origin, time and declared scope in one line', async () => {
    const financeCall = mount();
    render(<List datasets={[workbook, csv, derived]} />);
    await waitFor(() => expect(calls(financeCall, 'structure-confirmation-list')).toHaveLength(1));
    const list = screen.getByRole('list', { name: '资料文件' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(3);
    expect(screen.getAllByText('月结套表', { selector: '.fnd-title' })).toHaveLength(1);
    const meta = rowOf('月结套表').querySelector('.analysis-source-meta')!.textContent!;
    expect(meta).toMatch(/^Excel 工作簿 · 3 张工作表 · 2026-10-01 \d{2}:\d{2} · 2026 年 8 月 · 万元 · CNY$/);
    expect(meta).not.toContain('2026-08');
    expect(fileMeta(derived, [workbook, csv, derived])).toMatch(/^数据表 · 40 行 · 来自 月结套表 \/ 02·GL科目余额表 · /);
    expect(fileMeta(csv)).toMatch(/^数据表 · 12 行 · 2026-10-01/);
  });

  it('says what each table structure waits on, with one action name per file, and opens the form under its own row', async () => {
    const ledger = { ...workbook, id: '1'.repeat(32), name: '总账' };
    const blank = { ...workbook, id: '2'.repeat(32), name: '封面' };
    const assisted = { ...workbook, id: '3'.repeat(32), name: '助手确认的套表' };
    const settled = { ...workbook, id: '4'.repeat(32), name: '已确认的套表' };
    mount({
      proposals: [proposal(ledger.id, 'pending_confirmation'), proposal(blank.id, 'no_table', [sheet({ decision: 'excluded', blocked_reason: 'no_header' })]),
        proposal(assisted.id, 'pending_acknowledgement'), proposal(settled.id, 'confirmed')],
      confirmations: [{ id: 'c1', dataset_id: assisted.id, source: 'assistant', state: 'pending_acknowledgement', parent_id: null }],
    });
    render(<List datasets={[ledger, blank, assisted, settled, csv]} />);
    const open = await screen.findByRole('button', { name: '去确认表结构：总账' });
    expect(within(rowOf('总账')).getByText('待确认')).toBeTruthy();
    expect(within(rowOf('封面')).getByText('没有识别出数据表')).toBeTruthy();
    expect(screen.getByRole('button', { name: '查看原因：封面' })).toBeTruthy();
    expect(within(rowOf('助手确认的套表')).getByText('待追认')).toBeTruthy();
    expect(screen.getByRole('button', { name: '处理表结构追认：助手确认的套表' })).toBeTruthy();
    expect(within(rowOf('已确认的套表')).getByText('已确认')).toBeTruthy();
    expect(within(rowOf('已确认的套表')).queryByRole('button', { name: /表结构/ })).toBeNull();
    // A CSV has no table structure to confirm.
    expect(within(rowOf('回款明细')).queryByText('表结构')).toBeNull();
    // Every button in the list has a name of its own, and starts with what it shows.
    const names = within(screen.getByRole('list', { name: '资料文件' })).getAllByRole('button').map((button) => button.getAttribute('aria-label') ?? button.textContent);
    expect(new Set(names).size).toBe(names.length);
    for (const button of within(screen.getByRole('list', { name: '资料文件' })).getAllByRole('button')) {
      expect(button.getAttribute('aria-label')!.startsWith(button.textContent!.trim())).toBe(true);
    }

    expect(open.getAttribute('aria-expanded')).toBe('false');
    expect(within(rowOf('总账')).queryByRole('button', { name: /^确认表结构/ })).toBeNull();
    fireEvent.click(open);
    expect(open.getAttribute('aria-expanded')).toBe('true');
    const form = document.getElementById(open.getAttribute('aria-controls')!)!;
    expect(rowOf('总账').contains(form)).toBe(true);
    expect(within(form).getByRole('button', { name: /^确认表结构/ })).toBeTruthy();
    // The inline card is not a clickable card.
    expect(form.querySelector('.fnd-card')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '处理表结构追认：助手确认的套表' }));
    expect(within(rowOf('助手确认的套表')).getByRole('button', { name: '追认' })).toBeTruthy();
  });

  it('keeps a to-do for a file the list does not hold, as a row at the end', async () => {
    const missing = '9'.repeat(32);
    mount({ proposals: [proposal(missing, 'pending_confirmation')] });
    render(<List datasets={[csv]} />);
    expect(await screen.findByRole('button', { name: `去确认表结构：${missing}` })).toBeTruthy();
    const rows = within(screen.getByRole('list', { name: '资料文件' })).getAllByRole('listitem');
    expect(rows).toHaveLength(2);
    expect(rows[1].hasAttribute('data-structure-todo')).toBe(true);
  });

  it('shows each formula health state in words, none of them only in a title', async () => {
    mount();
    const hinted = { ...workbook, id: '5'.repeat(32), name: '有提示的套表', workbook_health: health };
    const tidy = { ...workbook, id: '6'.repeat(32), name: '干净的套表', workbook_health: clean };
    const broken = { ...workbook, id: '7'.repeat(32), name: '旧套表', workbook_health: { schema_version: 1, status: 'unavailable', reason: 'unreadable_workbook' } as WorkbookHealth };
    // Older CLIs may hand back a health record with fields missing.
    const sparse = { ...workbook, id: '8'.repeat(32), name: '稀疏记录', workbook_health: { schema_version: 1, status: 'checked' } as WorkbookHealth };
    const unfiled = { ...workbook, id: '0'.repeat(32), name: '没有原件', source_file: undefined };
    render(<List datasets={[workbook, hinted, tidy, broken, sparse, csv, derived, unfiled]} />);
    expect(within(rowOf('月结套表')).getByText('未做')).toBeTruthy();
    expect(screen.getByRole('button', { name: '体检这本工作簿：月结套表' }).textContent).toBe('体检');
    expect(within(rowOf('有提示的套表')).getByText(/2 类提示/)).toBeTruthy();
    expect(within(rowOf('有提示的套表')).getByText('其中 1 类需留意')).toBeTruthy();
    expect(screen.getByRole('button', { name: '查看公式体检提示：有提示的套表' }).getAttribute('aria-expanded')).toBe('false');
    expect(within(rowOf('干净的套表')).getByText('无提示')).toBeTruthy();
    expect(within(rowOf('稀疏记录')).getByText('无提示')).toBeTruthy();
    const unfinished = within(rowOf('旧套表')).getByText('未能完成（不影响使用）');
    expect(unfinished.closest('[title]')).toBeNull();
    for (const name of ['回款明细', '02·GL科目余额表', '没有原件']) expect(within(rowOf(name)).queryByText('公式体检')).toBeNull();
    // The state words are neutral; only 需留意 is drawn in the warning colour.
    for (const word of document.querySelectorAll('.analysis-file-state')) expect(word.className).not.toMatch(/warning/);
    expect(document.querySelector('.analysis-file-state-warning')!.textContent).toBe('其中 1 类需留意');

    fireEvent.click(screen.getByRole('button', { name: '查看公式体检提示：有提示的套表' }));
    const book = screen.getByRole('group', { name: '公式体检：有提示的套表' });
    expect(rowOf('有提示的套表').contains(book)).toBe(true);
    expect(within(book).getByText(/这些是提示，不影响导入和计算/)).toBeTruthy();
    // The guide link sits once, in the opened hints, not repeated on every row.
    expect(screen.getAllByRole('button', { name: '使用指南：工作簿公式体检' })).toHaveLength(1);
  });

  it('checks an older workbook once, on demand, and opens what it found', async () => {
    const financeCall = mount({ health: () => ({ ok: true, value: { dataset_id: workbook.id, ...health } }) });
    render(<List datasets={[workbook]} />);
    fireEvent.click(screen.getByRole('button', { name: '体检这本工作簿：月结套表' }));
    const book = await screen.findByRole('group', { name: '公式体检：月结套表' });
    expect(calls(financeCall, 'workbook-health')).toEqual([[taskId, 'workbook-health', { dataset_id: workbook.id }]]);
    expect(screen.getByRole('button', { name: '查看公式体检提示：月结套表' }).getAttribute('aria-expanded')).toBe('true');
    expect(rowOf('月结套表').contains(book)).toBe(true);
    expect(screen.queryByRole('button', { name: /体检这本工作簿/ })).toBeNull();
  });

  it('says plainly when an on-demand check finds nothing, and when it is refused', async () => {
    mount({ health: (spec) => spec.dataset_id === workbook.id ? { ok: true, value: { dataset_id: workbook.id, ...clean } }
      : { ok: false, refused: true, message: 'dataset source workbook integrity check failed' } });
    const other = { ...workbook, id: '5'.repeat(32), name: '另一本' };
    render(<List datasets={[workbook, other]} />);
    fireEvent.click(screen.getByRole('button', { name: '体检这本工作簿：月结套表' }));
    expect(await within(rowOf('月结套表')).findByText('无提示')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '体检这本工作簿：另一本' }));
    expect((await screen.findByRole('alert')).textContent).toContain('这份 Excel 与登记时的内容不一致');
  });

  it('drops a check that settles after the manager has moved to another task', async () => {
    let settle: (answer: unknown) => void = () => {};
    const financeCall = vi.fn((_task: string, command: string) => command === 'workbook-health'
      ? new Promise((resolve) => { settle = resolve; }) : Promise.resolve({ ok: true, value: {} }));
    (globalThis as { foundry?: unknown }).foundry = { financeCall };
    const other = 'f'.repeat(32);
    const later: DatasetSnapshot = { ...workbook, id: '5'.repeat(32), task_id: other, name: '下月套表' };
    const { rerender } = render(<List datasets={[workbook]} />);
    fireEvent.click(screen.getByRole('button', { name: '体检这本工作簿：月结套表' }));
    expect(screen.getByText('正在体检…')).toBeTruthy();
    rerender(<MaterialsFileList taskId={other} datasets={[later]} busy={false} preview={null} onPreview={() => {}} onClosePreview={() => {}} onRefresh={() => {}} />);
    const button = screen.getByRole('button', { name: '体检这本工作簿：下月套表' }) as HTMLButtonElement;
    expect(button.disabled).toBe(false);
    settle({ ok: false, refused: true, message: 'dataset source workbook integrity check failed' });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByRole('alert')).toBeNull();
    expect(button.disabled).toBe(false);
  });

  it('opens and closes a file\'s content under its row', async () => {
    mount();
    const onPreview = vi.fn();
    const onClosePreview = vi.fn();
    const { rerender } = render(<List datasets={[workbook, csv]} onPreview={onPreview} onClosePreview={onClosePreview} />);
    const view = screen.getByRole('button', { name: '查看内容：月结套表' });
    expect(view.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(view);
    expect(onPreview).toHaveBeenCalledWith(workbook);
    const content = { workbook: { sheets: [{ name: '00·封面', rows: 12, columns: 8 }] } };
    rerender(<List datasets={[workbook, csv]} onPreview={onPreview} onClosePreview={onClosePreview} preview={{ source: workbook, content }} />);
    expect(view.getAttribute('aria-expanded')).toBe('true');
    const directory = screen.getByRole('table', { name: '工作表目录' });
    expect(rowOf('月结套表').contains(directory)).toBe(true);
    expect(document.getElementById(view.getAttribute('aria-controls')!)!.contains(directory)).toBe(true);
    // The row already names the file; the preview's own heading is for screen readers only.
    expect(screen.getByRole('heading', { name: '月结套表' }).className).toBe('sr-only');
    expect(screen.getByRole('button', { name: '查看内容：回款明细' }).getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(view);
    expect(onClosePreview).toHaveBeenCalled();
    // A file opened from a result that the list does not hold stays below the list.
    const elsewhere = { ...csv, id: '5'.repeat(32), name: '依据快照' };
    rerender(<List datasets={[workbook, csv]} preview={{ source: elsewhere, content: { columns: [], rows: [] } }} />);
    const preview = screen.getByRole('heading', { name: '依据快照' }).closest('article')!;
    expect(screen.getByRole('list', { name: '资料文件' }).contains(preview)).toBe(false);
  });

  it('points the month-close and guide links at the scope card, the first structure to-do or the list', async () => {
    mount({ proposals: [proposal(csv.id, 'confirmed'), proposal(workbook.id, 'pending_confirmation')] });
    render(<><section className="analysis-scope-card" /><List datasets={[csv, workbook]} /></>);
    await screen.findByRole('button', { name: '去确认表结构：月结套表' });
    expect(materialsAnchor('scope')).toBe(document.querySelector('.analysis-scope-card'));
    expect(materialsAnchor('structure')).toBe(rowOf('月结套表'));
    expect(materialsAnchor('datasets')).toBe(screen.getByRole('list', { name: '资料文件' }));
    cleanup();
    mount();
    render(<List datasets={[csv]} />);
    expect(materialsAnchor('structure')).toBe(screen.getByRole('list', { name: '资料文件' }));
    expect(materialsAnchor('scope')).toBeNull();
  });
});
