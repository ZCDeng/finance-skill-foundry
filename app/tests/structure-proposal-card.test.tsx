// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { StructurePendingStrip, StructureProposalCard, type StructureProposal } from '../src/views/analysis/StructureProposalCard.js';

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

  it('shows an unreadable table with the headers it read, and never offers it', () => {
    const pack = proposal([
      ledger(),
      ledger({
        sheet: '10·区域经营损益表',
        blocked_reason: 'unreadable_columns',
        amount_pairs: [],
        columns: [
          { letter: 'A', header: '区　域', display: '区域', role: 'unknown', pair: null, direction: null },
          { letter: 'B', header: '营业收入', display: '营业收入', role: 'unknown', pair: null, direction: null },
          { letter: 'C', header: '期间费用', display: '期间费用', role: 'unknown', pair: null, direction: null },
        ],
      }),
    ]);
    render(<StructureProposalCard taskId="t" datasetName="月结套表" proposal={pack}
      busy={false} onSettled={vi.fn()} />);
    // No checkbox for it, so she cannot tick something that would be refused.
    expect(screen.queryByLabelText('采用 10·区域经营损益表')).toBeNull();
    expect(screen.getByText(/是一张表，但没有一列能识别/)).toBeTruthy();
    expect(screen.getByText(/区域、营业收入、期间费用/)).toBeTruthy();
    // The readable sheet is still offered.
    expect(screen.getByRole('button', { name: /确认表结构/ })).toBeTruthy();
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
