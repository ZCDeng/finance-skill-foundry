// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { FileReadinessFacts, FileReadinessStates, ReadinessPanel } from '../src/views/analysis/ReadinessPanel.js';

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
    expect(screen.getByText(/02·GL科目余额表范围没声明齐：缺币种/)).toBeTruthy();

    // Each file's own scope now sits on its row in the file list, not in a second table here.
    expect(screen.queryByRole('table')).toBeNull();
  });

  it('puts what is missing on the file\'s row and the rest of what it read beside its content', () => {
    const { container, unmount } = render(<FileReadinessStates row={report.datasets[1] as never} />);
    expect(container.textContent).toBe('还缺期间、币种');
    unmount();
    // A file that is fine adds nothing to its row.
    const fine = render(<FileReadinessStates row={{ ...report.datasets[0], missing_fields: [], freshness: { state: 'current', reasons: [] } } as never} />);
    expect(fine.container.textContent).toBe('');
    fine.unmount();
    render(<FileReadinessFacts row={report.datasets[0] as never} />);
    const facts = screen.getByLabelText('这份资料读到的范围');
    expect(facts.textContent).toContain('期间 2026 年 8 月');
    expect(facts.textContent).toContain('单位 元');
    expect(facts.textContent).toContain('合计校验');
    // The worded period never breaks across lines; the line breaks at 「 · 」.
    expect(Array.from(facts.querySelectorAll('.fnd-period')).map((span) => span.textContent)).toEqual(['2026 年 8 月', '2026 年 8 月']);
  });

  it('sits on the page as a section with a rule under it, not as a clickable card', async () => {
    mount(report);
    render(<ReadinessPanel taskId="t" />);
    const heading = await screen.findByText('这批资料能算什么');
    const section = heading.closest('section')!;
    expect(section.className).toBe('analysis-readiness');
    expect(section.classList.contains('fnd-card')).toBe(false);
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
