// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { StructurePendingStrip, StructureProposalCard, type StructureProposal } from '../src/views/analysis/StructureProposalCard.js';
import { WorkbookBrowser } from '../src/views/analysis/WorkbookBrowser.js';
import { acrossElements } from './text-match.js';

const financeCall = vi.fn();
beforeEach(() => {
  financeCall.mockReset().mockResolvedValue({ ok: true, value: {} });
  (globalThis as { foundry?: unknown }).foundry = { financeCall };
});
afterEach(() => cleanup());

function column(letter: string, display: string, role: string, pair: string | null = null) {
  return { letter, header: display, display, role, pair, direction: null };
}

function ledger(overrides: Partial<StructureProposal['sheets'][number]> = {}) {
  return {
    sheet: '02·GL科目余额表',
    decision: 'table' as const,
    reason: null,
    header_row: 4,
    title_rows: [1, 2],
    columns: [
      column('A', '科目代码', 'account_code'),
      column('C', '类别', 'category'),
      column('G', '本期发生额借方', 'debit', 'amount_1'),
      column('H', '本期发生额贷方', 'credit', 'amount_1'),
    ],
    amount_pairs: [{
      id: 'amount_1', label: '本期发生额', debit: 'G', credit: 'H', primary: true,
      direction: { kind: 'by_category', column: 'C' },
    }],
    excluded_rows: [{ row: 5, text: '资产类科目', reason: 'section' }],
    fill_down_columns: [],
    scope_hints: { period: '2026-08', currency: '', unit: '元' },
    preview: [
      { row: 3, is_header: false, cells: [{ letter: 'A', text: '科目余额表' }] },
      { row: 4, is_header: true, cells: [{ letter: 'A', text: '科目代码' }, { letter: 'C', text: '类别' }] },
      { row: 5, is_header: false, cells: [{ letter: 'A', text: '资产类科目' }] },
    ],
    confidence: 0.9,
    blocked_reason: null,
    ...overrides,
  };
}

function proposal(sheets: StructureProposal['sheets'], state = 'pending_confirmation'): StructureProposal {
  return { id: 'p1', dataset_id: 'shell-1', revision: 1, structure_state: state, sheets, template_matches: [] };
}

describe('structure confirmation card', () => {
  it('names a presentation page someone else adopted in the pending strip', () => {
    render(<StructurePendingStrip taskId="t" datasetName="月结套表" busy={false} onSettled={vi.fn()}
      confirmation={{ id: 'c1', dataset_id: 'shell-1', source: 'assistant', state: 'pending_acknowledgement', parent_id: null,
        sheets: [{ sheet: '01·核心指标看板', decision: 'table', reason: 'adopted_presentation_sheet' },
          { sheet: '02·GL科目余额表', decision: 'table', reason: null }] }} />);
    expect(screen.getByText(/01·核心指标看板 原本是看板或封面页/)).toBeTruthy();
    expect(screen.queryByText(/02·GL科目余额表 原本/)).toBeNull();
  });

  it('lets the manager adopt a set-aside KPI board and sends it as a table', async () => {
    const board = ledger({
      sheet: '01·核心指标看板', decision: 'excluded', reason: 'presentation_sheet',
      blocked_reason: 'presentation_sheet', adoptable: true,
      columns: [column('A', '指标', 'unknown'), column('C', '本年累计', 'unknown')], amount_pairs: [], excluded_rows: [],
    });
    const cover = ledger({ sheet: '00·封面', decision: 'excluded', reason: 'presentation_sheet',
      blocked_reason: 'presentation_sheet', columns: [], amount_pairs: [], excluded_rows: [] });
    const onSettled = vi.fn();
    render(<StructureProposalCard taskId="t" datasetName="月结套表" proposal={proposal([board, cover], 'no_table')}
      busy={false} onSettled={onSettled} />);
    // Only the board, which has a table on it, offers the choice.
    expect(screen.getAllByRole('button', { name: /当作数据表/ })).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: /当作数据表/ }));
    fireEvent.click(screen.getByRole('button', { name: /确认表结构/ }));
    await waitFor(() => expect(onSettled).toHaveBeenCalled());
    const [, command, spec] = financeCall.mock.calls[0];
    expect(command).toBe('structure-proposal-confirm');
    expect(spec.sheets.map((sheet: { sheet: string; decision: string; blocked_reason: string | null }) =>
      [sheet.sheet, sheet.decision, sheet.blocked_reason])).toEqual([['01·核心指标看板', 'table', null]]);
  });

  it('shows the rows around the proposed header so the number is not a guess', () => {
    render(<StructureProposalCard taskId="t" datasetName="月结套表" proposal={proposal([ledger()])}
      busy={false} onSettled={vi.fn()} />);
    expect((screen.getByLabelText('表头行') as HTMLInputElement).value).toBe('4');
    expect(screen.getByText('科目余额表')).toBeTruthy();
    expect(screen.getByText('资产类科目')).toBeTruthy();
  });

  it('sends the corrected header row and the sheet the manager kept', async () => {
    const onSettled = vi.fn();
    render(<StructureProposalCard taskId="t" datasetName="月结套表" proposal={proposal([ledger()])}
      busy={false} onSettled={onSettled} />);
    fireEvent.change(screen.getByLabelText('表头行'), { target: { value: '6' } });
    fireEvent.click(screen.getByRole('button', { name: /确认表结构/ }));
    await waitFor(() => expect(onSettled).toHaveBeenCalled());
    const [, command, spec] = financeCall.mock.calls[0];
    expect(command).toBe('structure-proposal-confirm');
    expect(spec.dataset_id).toBe('shell-1');
    expect(spec.revision).toBe(1);
    expect(spec.sheets).toHaveLength(1);
    expect(spec.sheets[0].header_row).toBe(6);
  });

  it('says it is working while the confirmed structure is applied', async () => {
    let settle: (value: unknown) => void = () => {};
    financeCall.mockReturnValueOnce(new Promise((resolve) => { settle = resolve; }));
    const onSettled = vi.fn();
    render(<StructureProposalCard taskId="t" datasetName="月结套表" proposal={proposal([ledger()])}
      busy={false} onSettled={onSettled} />);
    fireEvent.click(screen.getByRole('button', { name: /确认表结构/ }));
    expect((await screen.findByRole('status')).textContent).toBe('正在按确认的结构整理数据…');
    settle({ ok: true, value: {} });
    await waitFor(() => expect(onSettled).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByText('正在按确认的结构整理数据…')).toBeNull());
  });

  // The page reads the task back every 5 seconds and hands the card an equal proposal as a new object.
  it('keeps the manager\'s unconfirmed changes when the same proposal arrives again, and starts over on a new revision', () => {
    const first = proposal([ledger()]);
    const { rerender } = render(<StructureProposalCard taskId="t" datasetName="月结套表" proposal={first} busy={false} onSettled={vi.fn()} />);
    fireEvent.click(screen.getByRole('checkbox', { name: '采用 02·GL科目余额表' }));
    fireEvent.change(screen.getByLabelText('表头行'), { target: { value: '6' } });
    expect(screen.getByRole('checkbox', { name: '采用 02·GL科目余额表' }).getAttribute('aria-checked')).toBe('false');

    rerender(<StructureProposalCard taskId="t" datasetName="月结套表" proposal={proposal([ledger()])} busy={false} onSettled={vi.fn()} />);
    expect(screen.getByRole('checkbox', { name: '采用 02·GL科目余额表' }).getAttribute('aria-checked')).toBe('false');
    expect((screen.getByLabelText('表头行') as HTMLInputElement).value).toBe('6');

    rerender(<StructureProposalCard taskId="t" datasetName="月结套表" proposal={{ ...proposal([ledger()]), revision: 2 }} busy={false} onSettled={vi.fn()} />);
    expect(screen.getByRole('checkbox', { name: '采用 02·GL科目余额表' }).getAttribute('aria-checked')).toBe('true');
    expect((screen.getByLabelText('表头行') as HTMLInputElement).value).toBe('4');
  });

  it('will not confirm while a kept sheet has no debit or credit side', () => {
    const undecided = ledger({
      sheet: '余额表',
      amount_pairs: [{
        id: 'amount_1', label: '借贷', debit: 'G', credit: 'H', primary: true,
        direction: { kind: 'undecided' },
      }],
    });
    render(<StructureProposalCard taskId="t" datasetName="余额表" proposal={proposal([undecided])}
      busy={false} onSettled={vi.fn()} />);
    expect((screen.getByRole('button', { name: /确认表结构/ }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('借贷 哪一侧是金额（主）'), { target: { value: 'fixed:credit' } });
    expect((screen.getByRole('button', { name: /确认表结构/ }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('lets one undecided sheet be set aside without blocking the others', () => {
    const undecided = ledger({
      sheet: '余额表',
      amount_pairs: [{
        id: 'amount_1', label: '借贷', debit: 'G', credit: 'H', primary: true,
        direction: { kind: 'undecided' },
      }],
    });
    render(<StructureProposalCard taskId="t" datasetName="月结套表" proposal={proposal([ledger(), undecided])}
      busy={false} onSettled={vi.fn()} />);
    const confirm = screen.getByRole('button', { name: /确认表结构/ }) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
    fireEvent.click(screen.getByLabelText('采用 余额表'));
    expect(confirm.disabled).toBe(false);
  });

  it('reports a refusal in the card and keeps the sheet on screen', async () => {
    financeCall.mockResolvedValue({ ok: false, refused: true, message: '当前会话无权确认' });
    render(<StructureProposalCard taskId="t" datasetName="月结套表" proposal={proposal([ledger()])}
      busy={false} onSettled={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /确认表结构/ }));
    expect((await screen.findByRole('alert')).textContent).toContain('当前会话无权确认');
    expect(screen.getByLabelText('表头行')).toBeTruthy();
  });

  it('explains a file with nothing tabular in it instead of offering a confirmation', () => {
    const covers = proposal([
      ledger({ sheet: '00·封面与编制说明', decision: 'excluded', reason: 'presentation_sheet', blocked_reason: 'presentation_sheet', columns: [], amount_pairs: [], preview: [] }),
      ledger({ sheet: '13·行业对标与假设', decision: 'excluded', reason: 'presentation_sheet', blocked_reason: 'presentation_sheet', columns: [], amount_pairs: [], preview: [] }),
    ], 'no_table');
    render(<StructureProposalCard taskId="t" datasetName="只有封面" proposal={covers} busy={false} onSettled={vi.fn()} />);
    expect(screen.queryByRole('button', { name: /确认表结构/ })).toBeNull();
    expect(screen.getAllByText('封面、看板或对标页')).toHaveLength(2);
  });

  it('shows a blocked table in no-table state so the manager can repair and confirm it', async () => {
    const onSettled = vi.fn();
    const pack = proposal([
      ledger({
        sheet: '坏表头',
        decision: 'table',
        reason: 'no_header',
        blocked_reason: 'unreadable_columns',
        header_row: 2,
        start_row: 2,
        end_row: 4,
        start_column: 'A',
        end_column: 'B',
        amount_pairs: [],
        columns: [
          { letter: 'A', header: '项目', display: '项目', role: 'unknown', pair: null, direction: null, include: true, stable_name: 'col_A_项目' },
          { letter: 'B', header: '金额', display: '金额', role: 'unknown', pair: null, direction: null, include: true, stable_name: 'col_B_金额', numeric: true },
        ],
        numeric_coverage: {
          numeric_columns_total: 1,
          numeric_columns_included: 1,
          numeric_columns_excluded: 0,
          retained_cell_coverage: 1,
          metadata_only: false,
        },
      }),
    ], 'no_table');
    render(<StructureProposalCard taskId="t" datasetName="待修复套表" proposal={pack}
      busy={false} onSettled={onSettled} />);

    expect(screen.getByLabelText('采用 坏表头')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('坏表头 B 列含义'), { target: { value: 'amount' } });
    fireEvent.click(screen.getByRole('button', { name: /确认表结构/ }));
    await waitFor(() => expect(onSettled).toHaveBeenCalled());
    const sent = financeCall.mock.calls[0][2].sheets[0];
    expect(sent.sheet).toBe('坏表头');
    expect(sent.blocked_reason).toBeNull();
    expect(sent.reason).toBeNull();
    expect(sent.columns.find((column: { letter: string }) => column.letter === 'B').role).toBe('amount');
  });

  it('lets a wide table with unknown headers be repaired and confirmed', async () => {
    const onSettled = vi.fn();
    const pack = proposal([
      ledger(),
      ledger({
        sheet: '10·区域经营损益表',
        blocked_reason: null,
        amount_pairs: [],
        numeric_coverage: {
          numeric_columns_total: 2,
          numeric_columns_included: 2,
          numeric_columns_excluded: 0,
          retained_cell_coverage: 1,
          metadata_only: false,
        },
        columns: [
          { letter: 'A', header: '区　域', display: '区域', role: 'unknown', pair: null, direction: null, include: true, stable_name: 'col_A_区域' },
          { letter: 'B', header: '营业收入', display: '营业收入', role: 'unknown', pair: null, direction: null, include: true, numeric: true, stable_name: 'col_B_营业收入' },
          { letter: 'C', header: '期间费用', display: '期间费用', role: 'unknown', pair: null, direction: null, include: true, numeric: true, stable_name: 'col_C_期间费用' },
        ],
      }),
    ]);
    render(<StructureProposalCard taskId="t" datasetName="月结套表" proposal={pack}
      busy={false} onSettled={onSettled} />);
    expect(screen.getByLabelText('采用 10·区域经营损益表')).toBeTruthy();
    expect(screen.getByText(/数值列覆盖：纳入 2\/2/)).toBeTruthy();
    fireEvent.click(screen.getByLabelText('10·区域经营损益表 C 列纳入'));
    fireEvent.change(screen.getByLabelText('10·区域经营损益表 C 列排除原因'), { target: { value: '本次不分析费用' } });
    fireEvent.click(screen.getByRole('button', { name: /确认表结构/ }));
    await waitFor(() => expect(onSettled).toHaveBeenCalled());
    const sent = financeCall.mock.calls[0][2].sheets.find((sheet: { sheet: string }) => sheet.sheet === '10·区域经营损益表');
    expect(sent.columns.find((column: { letter: string }) => column.letter === 'C')).toMatchObject({
      include: false,
      exclusion_reason: '本次不分析费用',
    });
  });

  it('drops a row from the not-counted list when the manager puts it back', async () => {
    const onSettled = vi.fn();
    render(<StructureProposalCard taskId="t" datasetName="月结套表" proposal={proposal([ledger()])}
      busy={false} onSettled={onSettled} />);
    fireEvent.click(screen.getByLabelText('第 5 行不计入'));
    fireEvent.click(screen.getByRole('button', { name: /确认表结构/ }));
    await waitFor(() => expect(onSettled).toHaveBeenCalled());
    expect(financeCall.mock.calls[0][2].sheets[0].excluded_rows).toEqual([]);
  });
});

describe('pending acknowledgement strip', () => {
  const confirmation = { id: 'c1', dataset_id: 'shell-1', source: 'assistant', state: 'pending_acknowledgement', parent_id: null };

  it('acknowledges an assistant confirmation', async () => {
    const onSettled = vi.fn();
    render(<StructurePendingStrip taskId="t" datasetName="月结套表" confirmation={confirmation}
      busy={false} onSettled={onSettled} />);
    fireEvent.click(screen.getByRole('button', { name: /追认/ }));
    await waitFor(() => expect(onSettled).toHaveBeenCalled());
    expect(financeCall.mock.calls[0][1]).toBe('structure-acknowledge');
  });

  it('rejects an assistant confirmation and withdraws a template application', async () => {
    const { unmount } = render(<StructurePendingStrip taskId="t" datasetName="月结套表" confirmation={confirmation}
      busy={false} onSettled={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /拒绝/ }));
    await waitFor(() => expect(financeCall.mock.calls[0][1]).toBe('structure-reject'));
    unmount();
    financeCall.mockClear();
    financeCall.mockResolvedValue({ ok: true, value: {} });
    render(<StructurePendingStrip taskId="t" datasetName="九月套表"
      confirmation={{ ...confirmation, source: 'template' }} busy={false} onSettled={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /撤销套用/ }));
    await waitFor(() => expect(financeCall.mock.calls[0][1]).toBe('structure-withdraw'));
  });
});

describe('workbook browser', () => {
  function preview(sheet: string, range: string, display = '910') {
    return {
      ok: true,
      value: {
        dataset_id: 'shell-1',
        source_hash: 'hash',
        source_name: '月结.xlsx',
        sheet,
        range,
        header_context: [
          { address: 'A1', text: '2026 年度预算总表（BUD-2026）' },
          { address: 'A2', text: '单位：万元；12 个月分解' },
        ],
        bounds: { min_row: 36, min_col: 2, max_row: 37, max_col: 3 },
        cells: [
          { address: 'B36', row: 36, column: 2, column_letter: 'B', kind: 'number', display, exact: display === '8.20' ? '8.199999999999999' : display, formula: null, cached_value_available: false, cached_value: null, number_format: display === '8.20' ? '#,##0.00;[Red]-#,##0.00' : 'General', merged: false },
          { address: 'C36', row: 36, column: 3, column_letter: 'C', kind: 'formula', display: '', exact: null, formula: '=B36*2', cached_value_available: false, cached_value: null, number_format: 'General', merged: false },
        ],
        warnings: [],
      },
    };
  }

  it('auto-loads a bounded task workbook range and renders formula and exact-value status', async () => {
    financeCall.mockResolvedValue(preview('04·合并利润表', 'B36:C37', '8.20'));
    render(<WorkbookBrowser taskId="t" datasetId="shell-1" initialSheet="04·合并利润表" initialRange="B36:C37" />);
    await waitFor(() => expect(financeCall).toHaveBeenCalledWith('t', 'workbook-range-preview', {
      dataset_id: 'shell-1',
      sheet: '04·合并利润表',
      range: 'B36:C37',
    }));
    expect(await screen.findByText('8.20')).toBeTruthy();
    expect(screen.getByRole('region', { name: /04·合并利润表 B36:C37/ })).toBeTruthy();
    expect(screen.getByRole('table', { name: /04·合并利润表 B36:C37/ })).toBeTruthy();
    expect(screen.getByRole('columnheader', { name: 'B' })).toBeTruthy();
    expect(screen.getByText('8.20').closest('td')?.getAttribute('title')).toContain('原始值：8.199999999999999');
    expect(screen.getByText(/=B36\*2/)).toBeTruthy();
    expect(screen.getByText(/无缓存值/)).toBeTruthy();
    expect(screen.getByText(/A1：2026 年度预算总表（BUD-2026）/)).toBeTruthy();
    expect(screen.getByText(/A2：单位：万元；12 个月分解/)).toBeTruthy();
    expect(screen.queryByText('精确值')).toBeNull();
  });

  it('searches sheets and submits a range with Enter', async () => {
    financeCall.mockResolvedValue(preview('01·看板', 'A1:L40'));
    render(<WorkbookBrowser
      taskId="t"
      datasetId="shell-1"
      initialSheet="01·看板"
      sheets={['01·看板', '04·合并利润表']}
      sheetContext={{ '04·合并利润表': { period: '2026-08', unit: '元', granularity: '月度' } }}
    />);
    await waitFor(() => expect(financeCall).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText('搜索工作表'), { target: { value: '利润' } });
    financeCall.mockResolvedValue(preview('04·合并利润表', 'A1:L40'));
    fireEvent.change(screen.getByLabelText('工作表'), { target: { value: '04·合并利润表' } });
    await waitFor(() => expect(financeCall).toHaveBeenLastCalledWith('t', 'workbook-range-preview', {
      dataset_id: 'shell-1',
      sheet: '04·合并利润表',
    }));
    expect(screen.getByText(acrossElements(/期间 2026 年 8 月/))).toBeTruthy();

    financeCall.mockResolvedValue(preview('04·合并利润表', 'B36:I39'));
    fireEvent.change(screen.getByLabelText('区域'), { target: { value: 'B36:I39' } });
    fireEvent.keyDown(screen.getByLabelText('区域'), { key: 'Enter' });
    await waitFor(() => expect(financeCall).toHaveBeenLastCalledWith('t', 'workbook-range-preview', {
      dataset_id: 'shell-1',
      sheet: '04·合并利润表',
      range: 'B36:I39',
    }));
  });

  it('can hide the local sheet picker when an overview owns workbook navigation', async () => {
    financeCall.mockResolvedValue(preview('04·合并利润表', 'A1:L40'));
    render(<WorkbookBrowser
      taskId="t"
      datasetId="shell-1"
      initialSheet="04·合并利润表"
      sheets={['01·看板', '04·合并利润表']}
      showSheetPicker={false}
    />);
    expect(screen.queryByLabelText('搜索工作表')).toBeNull();
    expect(screen.queryByLabelText('工作表')).toBeNull();
    expect(screen.getByText('工作表 04·合并利润表')).toBeTruthy();
    await waitFor(() => expect(financeCall).toHaveBeenCalledWith('t', 'workbook-range-preview', {
      dataset_id: 'shell-1',
      sheet: '04·合并利润表',
    }));
  });

  it('keeps stale workbook preview responses from replacing the active dataset', async () => {
    let resolveFirst: (answer: unknown) => void = () => undefined;
    financeCall.mockReturnValueOnce(new Promise((resolve) => {
      resolveFirst = resolve;
    }));
    financeCall.mockResolvedValueOnce(preview('04·合并利润表', 'A1:L40', '222'));
    const { rerender } = render(<WorkbookBrowser taskId="t" datasetId="shell-1" initialSheet="04·合并利润表" />);
    await waitFor(() => expect(financeCall).toHaveBeenCalledTimes(1));
    rerender(<WorkbookBrowser taskId="t" datasetId="shell-2" initialSheet="04·合并利润表" />);
    await waitFor(() => expect(screen.getByText('222')).toBeTruthy());
    resolveFirst(preview('04·合并利润表', 'A1:L40', '111'));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByText('111')).toBeNull();
  });
});
