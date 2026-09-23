// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { EvidenceQuality } from '../src/views/analysis/EvidenceQuality.js';
afterEach(cleanup);

vi.mock('../src/views/analysis/WorkbookBrowser.js', () => ({ WorkbookBrowser: (props: { datasetId: string; initialSheet: string; initialRange: string }) => <div role="region" aria-label="源区域预览">{props.datasetId}/{props.initialSheet}/{props.initialRange}</div> }));

describe('EvidenceQuality', () => {
  it('keeps execution and numeric citation success separate from missing source checks and professional review', () => {
    render(<EvidenceQuality taskId="task" dimensions={{ execution: { status: 'pass' }, numeric_citation: { status: 'pass' }, source_validation: { status: 'not_configured' }, professional_review: { status: 'unreviewed' } }} issues={[]} />);
    const board = screen.getByLabelText('四项独立核验状态');
    expect(within(board).getByText('运行成功')).toBeTruthy();
    expect(within(board).getByText('引用值一致')).toBeTruthy();
    expect(within(board).getByText('尚未独立核验')).toBeTruthy();
    expect(within(board).getByText('待专业复核')).toBeTruthy();
  });
  it('groups repeated business issues without losing originals and opens the exact archived range', () => {
    const issue = { code: 'evidence_recipe_mismatch', severity: 'error', message: '源值与运行引用不一致', business_key: { metric: '其他收益', period: '2026-01..2026-08' }, location: { dataset_id: 'budget', source_hash: 'hash', sheet: '预算01', range: 'B36:I39' } };
    render(<EvidenceQuality taskId="task" issues={[issue, issue]} />);
    expect(screen.getAllByText(/源值与运行引用不一致/, { selector: 'summary' })).toHaveLength(1);
    expect(screen.getByText(/2 条原始问题/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '查看源区域 预算01!B36:I39' }));
    expect(screen.getByRole('region', { name: '源区域预览' }).textContent).toBe('budget/预算01/B36:I39');
  });
  it('does not show prior pass status after an edit', () => {
    render(<EvidenceQuality taskId="task" stale dimensions={{ source_validation: { status: 'pass' }, professional_review: { status: 'reviewed' } }} issues={[]} />);
    expect(screen.queryByText('源数据核验通过')).toBeNull();
    expect(screen.getAllByText('改稿后待复核')).toHaveLength(4);
  });
});
