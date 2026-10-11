// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Answer, Bridge } from '../src/bridge.js';
import { FileReadinessFacts, ReadinessPanel } from '../src/views/analysis/ReadinessPanel.js';
import { RequirementsPanel, type AnalysisRequirementsRecord } from '../src/views/analysis/RequirementsPanel.js';
import { StructureProposalCard, type StructureProposal } from '../src/views/analysis/StructureProposalCard.js';
import { WorkbookBrowser } from '../src/views/analysis/WorkbookBrowser.js';

const financeCall = vi.fn<NonNullable<Bridge['financeCall']>>();
const taskId = 'task-section-7';

const ok = <T,>(value: T): Answer<T> => ({ ok: true, value });

beforeEach(() => {
  financeCall.mockReset().mockResolvedValue(ok({}));
  (globalThis as unknown as { foundry: Partial<Bridge> }).foundry = { financeCall };
});

afterEach(() => {
  cleanup();
  delete (globalThis as unknown as { foundry?: Partial<Bridge> }).foundry;
});

function proposal(): StructureProposal {
  const columns = [
    { letter: 'A', header: '组织', display: '组织', role: 'organization', pair: null, direction: null },
    { letter: 'B', header: '收入', display: '收入', role: 'amount', pair: null, direction: null, numeric: true },
  ];
  const preview = [
    { row: 2, is_header: true, cells: [{ letter: 'A', text: '组织' }, { letter: 'B', text: '收入' }] },
    { row: 3, is_header: false, cells: [{ letter: 'A', text: '华东' }, { letter: 'B', text: '120' }] },
  ];
  return {
    id: 'proposal-1',
    dataset_id: 'dataset-1',
    revision: 3,
    structure_state: 'pending_confirmation',
    template_matches: [],
    sheets: [{
      sheet: '04·合并利润表',
      decision: 'table',
      reason: null,
      blocked_reason: null,
      header_row: 2,
      title_rows: [1],
      start_row: 2,
      end_row: 10,
      start_column: 'A',
      end_column: 'B',
      columns,
      amount_pairs: [],
      excluded_rows: [],
      fill_down_columns: [],
      scope_hints: { period: '2026-08', currency: 'CNY', unit: '万元', scenario: 'actual_ytd' },
      preview,
      confidence: 0.92,
      selected_block_id: 'internal-block-a',
      table_blocks: [
        { id: 'internal-block-a', header_row: 2, start_row: 2, end_row: 10, start_column: 'A', end_column: 'B', columns, amount_pairs: [], excluded_rows: [], fill_down_columns: [], preview, confidence: 0.92 },
        { id: 'internal-block-b', header_row: 5, start_row: 5, end_row: 20, start_column: 'C', end_column: 'F', columns, amount_pairs: [], excluded_rows: [], fill_down_columns: [], preview, confidence: 0.88 },
      ],
    }],
  };
}

describe('section 7 manager-facing scope copy', () => {
  it('names structure blocks by area while submitting the selected internal block id', async () => {
    const onSettled = vi.fn();
    render(<StructureProposalCard taskId={taskId} datasetName="月结套表" proposal={proposal()} busy={false} onSettled={onSettled} />);

    const block = screen.getByLabelText('表块') as HTMLSelectElement;
    expect(block.textContent).toContain('区域 1 · A2:B10 · 表头第 2 行');
    expect(block.textContent).toContain('区域 2 · C5:F20 · 表头第 5 行');
    expect(block.textContent).not.toContain('internal-block');
    expect(screen.getByText(/情景 累计实际/)).toBeTruthy();

    fireEvent.change(block, { target: { value: 'internal-block-b' } });
    fireEvent.click(screen.getByRole('button', { name: /确认表结构/ }));

    await waitFor(() => expect(onSettled).toHaveBeenCalled());
    const sent = financeCall.mock.calls[0][2] as { sheets: { selected_block_id?: string }[] };
    expect(sent.sheets[0].selected_block_id).toBe('internal-block-b');
  });

  it('keeps requirement ids in technical information instead of the body label', async () => {
    const requirement: AnalysisRequirementsRecord = {
      id: 'requirements-version-1',
      question: '解释收入达成率',
      scope: { period: '2026-08', organization: '集团合并', unit: '万元', currency: 'CNY' },
      bindings: {},
      parent_id: null,
      items: [{
        id: '0123456789abcdef0123456789abcdef',
        metric: 'revenue',
        label: '收入达成率',
        dimensions: {},
        requires_drilldown: false,
      }],
    };
    financeCall.mockResolvedValue(ok({ requirements: [requirement], current: requirement }));

    render(<RequirementsPanel taskId={taskId} />);

    expect(await screen.findByText('要求 1 · 收入达成率')).toBeTruthy();
    expect(screen.queryByText(/编号 01234567/)).toBeNull();
    expect(screen.getByText('技术信息')).toBeTruthy();
    expect(screen.getByText('0123456789abcdef0123456789abcdef')).toBeTruthy();
  });

  it('uses range and Chinese scenario words in workbook and readiness panels', async () => {
    financeCall.mockImplementation(async (_task, command) => {
      if (command === 'finance-readiness') return ok({
        proposed_scope: { ledger: '', organization: '', period: '', currency: '', unit: '' },
        datasets: [{
          dataset_id: 'dataset-1',
          name: '月结套表',
          scope: { ledger: '', organization: '集团合并', period: '2026-08', currency: 'CNY', unit: '万元', scenario: 'budget_ytd' },
          missing_fields: ['scenario'],
          can_run: [],
          blocked: [],
        }],
        can_run: [],
        blocked: [{ capability: 'management_pnl', reason: 'missing_scope', missing_fields: ['scenario'], dataset_id: 'dataset-1' }],
        file_identity_policy: 'business_key',
        diagnostics: [],
        erp_connected: false,
      } as never);
      return ok({
        dataset_id: 'dataset-1',
        source_hash: 'hash',
        source_name: '月结.xlsx',
        sheet: '04·合并利润表',
        range: 'A1:B2',
        bounds: { min_row: 1, min_col: 1, max_row: 2, max_col: 2 },
        cells: [{ address: 'A1', row: 1, column: 1, column_letter: 'A', kind: 'text', display: '收入', exact: null, formula: null, cached_value_available: false, cached_value: null, number_format: 'General', merged: false }],
        warnings: [],
      });
    });

    render(<>
      <WorkbookBrowser
        taskId={taskId}
        datasetId="dataset-1"
        initialSheet="04·合并利润表"
        sheetContext={{ '04·合并利润表': { period: '2026-08', unit: '万元', currency: 'CNY', scenario: 'actual_ytd' } }}
      />
      <ReadinessPanel taskId={taskId} />
    </>);

    expect(await screen.findByText(/情景 累计实际/)).toBeTruthy();
    expect(await screen.findByText(/每份文件读到的范围和时效在它那一行/)).toBeTruthy();
    expect(screen.getByText(/范围没声明齐/)).toBeTruthy();
    // The file's own scope, opened with its content in the file list.
    render(<FileReadinessFacts row={{ dataset_id: 'dataset-1', name: '月结套表', missing_fields: ['scenario'], can_run: [], blocked: [],
      scope: { ledger: '', organization: '集团合并', period: '2026-08', currency: 'CNY', unit: '万元', scenario: 'budget_ytd' } as never }} />);
    expect(screen.getByText(/情景 累计预算/)).toBeTruthy();
    expect(screen.getByText(/范围没声明齐/)).toBeTruthy();
    expect(screen.queryByText(/读到的口径|口径没声明齐|标题里没读到口径/)).toBeNull();
  });

  it('uses a neutral dataset sequence when readiness has no file name and keeps the full id in technical information', async () => {
    const datasetId = 'abcdef1234567890abcdef1234567890';
    financeCall.mockResolvedValue(ok({
      proposed_scope: { ledger: '', organization: '', period: '', currency: '', unit: '' },
      datasets: [{
        dataset_id: datasetId,
        name: '',
        scope: { ledger: '', organization: '', period: '2026-08', currency: 'CNY', unit: '万元' },
        missing_fields: [],
        can_run: ['management_pnl'],
        blocked: [],
      }],
      can_run: [],
      blocked: [{ capability: 'management_pnl', reason: 'missing_scope', missing_fields: ['scenario'], dataset_id: datasetId }],
      file_identity_policy: 'business_key',
      diagnostics: [],
      erp_connected: false,
    } as never));

    render(<ReadinessPanel taskId={taskId} />);

    expect(await screen.findAllByText(/资料 1/)).toHaveLength(1);
    expect(screen.queryByText(/abcdef12/)).toBeNull();
    // The full id stays in the file's technical information, beside its content.
    render(<FileReadinessFacts row={{ dataset_id: datasetId, name: '', missing_fields: [], can_run: ['management_pnl'], blocked: [],
      scope: { ledger: '', organization: '', period: '2026-08', currency: 'CNY', unit: '万元' } }} />);
    expect(screen.getByText('技术信息')).toBeTruthy();
    expect(screen.getByText(datasetId)).toBeTruthy();
  });
});
