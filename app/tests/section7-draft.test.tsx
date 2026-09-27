// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { AnalysisDraft, AnalysisRun, Bridge, Answer } from '../src/bridge.js';
vi.mock('../src/views/analysis/ReportEditor.js', () => ({ ReportEditor: () => <div>文稿正文</div> }));
import { CompletionRecoveriesPanel } from '../src/views/analysis/CompletionRecoveriesPanel.js';
import { DraftEditor } from '../src/views/analysis/DraftEditor.js';

const common = { task_id: 'a'.repeat(32), schema_version: 1, created_at: '2026-09-27T00:00:00Z' };
const run: AnalysisRun = { ...common, id: 'b'.repeat(32), analysis_id: 'c'.repeat(32), execution_status: 'succeeded',
  reproducibility_status: 'reproducible', review_status: 'unreviewed', publication_status: 'draft', input_hashes: {} };
const draft: AnalysisDraft = { ...common, id: 'd'.repeat(32), title: '经营分析', body: '说明', run_ids: [run.id, 'e'.repeat(32)],
  claims: [{ basis: 'calculation', run_id: run.id, value: '900719925474099.99' }], limitations: [], review_status: 'unreviewed', publication_status: 'draft' };
afterEach(() => { cleanup(); delete (globalThis as unknown as { foundry?: Partial<Bridge> }).foundry; });
it('shows cited calculations by their reference order and preserves exact provenance only inside technical information', () => {
  const onSave = vi.fn();
  render(<DraftEditor taskId={common.task_id} draft={draft} drafts={[draft]} runs={[run]} datasets={[]} busy={false}
    onEdit={vi.fn()} onSave={onSave} onExport={vi.fn()} onChat={vi.fn()} onDiscussRequirements={vi.fn()} />);
  const summary = screen.getByText('引用的计算与依据 · 2 次计算');
  fireEvent.click(summary);
  const references = summary.closest('details')!;
  expect(within(references).getByText(/^引用计算 1 ·/)).toBeTruthy();
  expect(within(references).getByText('引用计算 2')).toBeTruthy();
  expect(within(references).getByText('此计算记录暂不可读取。')).toBeTruthy();
  const technicalSummary = within(references).getByText('技术信息');
  const technical = technicalSummary.closest('details') as HTMLDetailsElement;
  expect(technical.open).toBe(false);
  const businessCopy = references.cloneNode(true) as HTMLElement;
  businessCopy.querySelector('.analysis-technical')?.remove();
  expect(businessCopy.textContent).not.toContain(run.id);
  fireEvent.click(technicalSummary);
  expect(technical.textContent).toContain(run.id);
  expect(technical.textContent).toContain('e'.repeat(32));
  expect(technical.textContent).toContain('900719925474099.99');
  fireEvent.click(screen.getByRole('button', { name: '选定并归档此版' }));
  expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ run_ids: draft.run_ids, claims: draft.claims }));
});

it('keeps recovery identifiers available without mixing them into the recovery instructions', () => {
  const onLoad = vi.fn();
  const recovery = { operation_id: 'f'.repeat(32), status: 'repair_available', run_ids: [run.id],
    validation_error: { message: 'unknown run', details: [{ run_id: run.id, row: 0, column: '利润', expected: '900719925474099.99', actual: '0' }] } };
  render(<CompletionRecoveriesPanel recoveries={[recovery]} disabled={false} onRetry={vi.fn()} onLoad={onLoad} />);
  fireEvent.click(screen.getByText('可恢复的未保存文稿 · 1 条'));
  const technical = screen.getByText('技术信息').closest('details') as HTMLDetailsElement;
  expect(technical.open).toBe(false);
  expect(screen.getByText(/第 1 行 · 利润/).textContent).toContain('900719925474099.99');
  const businessCopy = document.body.cloneNode(true) as HTMLElement;
  businessCopy.querySelectorAll('.analysis-technical').forEach(node => node.remove());
  expect(businessCopy.textContent).not.toContain(run.id);
  expect(technical.textContent).toContain(recovery.operation_id);
  expect(technical.textContent).toContain(run.id);
  fireEvent.click(screen.getByRole('button', { name: '载入可编辑副本' }));
  expect(onLoad).toHaveBeenCalledWith(recovery);
});

it('shows the loaded recovery references rather than the saved draft references', async () => {
  const recoveredRun = { ...run, id: '9'.repeat(32) };
  const recovery = { operation_id: 'f'.repeat(32), status: 'repair_available', title: '恢复稿', body: '恢复正文',
    run_ids: [recoveredRun.id], claims: [{ basis: 'calculation', run_id: recoveredRun.id, value: '42.01' }], limitations: [] };
  const financeCall: NonNullable<Bridge['financeCall']> = async (_task, command): Promise<Answer<Record<string, unknown>>> => ({
    ok: true,
    value: command === 'finance-completion-recoveries' ? { recoveries: [recovery] } : {},
  });
  (globalThis as unknown as { foundry: Partial<Bridge> }).foundry = { financeCall: vi.fn(financeCall) };
  const onSave = vi.fn();
  render(<DraftEditor taskId={common.task_id} draft={draft} drafts={[draft]} runs={[run, recoveredRun]} datasets={[]} busy={false}
    onEdit={vi.fn()} onSave={onSave} onExport={vi.fn()} onChat={vi.fn()} onDiscussRequirements={vi.fn()} />);
  fireEvent.click(await screen.findByText('可恢复的未保存文稿 · 1 条'));
  fireEvent.click(screen.getByRole('button', { name: '载入可编辑副本' }));
  const references = screen.getByText('引用的计算与依据 · 1 次计算').closest('details')!;
  expect(references.textContent).toContain(recoveredRun.id);
  expect(references.textContent).not.toContain(run.id);
  expect(references.textContent).not.toContain('900719925474099.99');
  expect(references.textContent).toContain('42.01');
  fireEvent.click(screen.getByRole('button', { name: '保存文稿新版' }));
  expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ run_ids: recovery.run_ids, claims: recovery.claims }));
});
