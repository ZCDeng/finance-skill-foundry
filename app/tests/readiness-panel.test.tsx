// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { ReadinessPanel } from '../src/views/analysis/ReadinessPanel.js';

afterEach(() => cleanup());

const report = {
  proposed_scope: { ledger: '', organization: '', period: '', currency: '', unit: '' },
  datasets: [
    {
      dataset_id: 'a'.repeat(32),
      name: '02·GL科目余额表',
      scope: { ledger: '', organization: '', period: '2026-08', currency: '', unit: '元' },
      missing_fields: ['currency'],
      can_run: ['control_totals'],
      blocked: [{ capability: 'management_pnl', missing_fields: ['currency'], reason: 'missing_scope' }],
    },
    {
      dataset_id: 'b'.repeat(32),
      name: '年度预算台账',
      scope: { ledger: '', organization: '', period: '', currency: '', unit: '万元' },
      missing_fields: ['period', 'currency'],
      can_run: [],
      blocked: [{ capability: 'management_pnl', missing_fields: ['period', 'currency'], reason: 'missing_scope' }],
    },
  ],
  can_run: ['control_totals'],
  blocked: [
    { capability: 'management_pnl', missing_fields: ['currency'], reason: 'missing_scope', dataset_id: 'a'.repeat(32) },
  ],
  file_identity_policy: 'snapshot_only',
  diagnostics: [],
  erp_connected: false,
};

function mount(value: unknown) {
  const financeCall = vi.fn(async () => ({ ok: true, value }));
  (globalThis as { foundry?: unknown }).foundry = { financeCall };
  return financeCall;
}

describe('readiness panel', () => {
  it('names which file is missing what instead of blaming the task', async () => {
    mount(report);
    render(<ReadinessPanel taskId="t" />);
    await screen.findByText('这批资料能算什么');

    // The capability the batch can run, and the one it cannot, with the file.
    expect(screen.getAllByText('合计校验').length).toBeGreaterThan(0);
    expect(screen.getByText(/02·GL科目余额表口径没声明齐：缺币种/)).toBeTruthy();

    // Each file's own scope, including the unit that only the title declared.
    const budget = screen.getByRole('row', { name: /年度预算台账/ });
    expect(budget.textContent).toContain('单位 万元');
    expect(budget.textContent).toContain('期间、币种');
    const ledger = screen.getByRole('row', { name: /02·GL科目余额表/ });
    expect(ledger.textContent).toContain('期间 2026-08');
  });

  it('says the numbers came from these files and nothing else', async () => {
    mount(report);
    render(<ReadinessPanel taskId="t" />);
    expect(await screen.findByText(/未接外部账套/)).toBeTruthy();
  });

  it('survives a report that answers with fewer fields than this build knows', async () => {
    mount({ can_run: [], file_identity_policy: 'snapshot_only' });
    render(<ReadinessPanel taskId="t" />);
    await screen.findByText('这批资料能算什么');
    expect(screen.getByText('还没有已授权的资料。')).toBeTruthy();
  });

  it('stays out of the way when this build cannot answer the call', async () => {
    (globalThis as { foundry?: unknown }).foundry = {};
    const { container } = render(<ReadinessPanel taskId="t" />);
    await waitFor(() => expect(container.textContent).toBe(''));
  });
});
