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
    expect(within(board).getByText('计算成功')).toBeTruthy();
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
  it('labels a requirement estimate and opens both its source range and its factor ranges', () => {
    const issue = {
      code: 'requirement_estimated', severity: 'warning', message: '服务端说明',
      business_key: { metric: 'revenue', organization: '华东区域', period: '2026-01:2026-08', scenario: 'budget_1_8' },
      location: {
        reference: { dataset_id: 'budget', source_hash: 'hash', sheet: '05·区域预算分解', range: 'C5' },
        factor: {
          left: { dataset_id: 'budget', source_hash: 'hash', sheet: '01·年度预算总表', range: 'B12:I12' },
          right: { dataset_id: 'budget', source_hash: 'hash', sheet: '01·年度预算总表', range: 'N12' },
        },
      },
    };
    render(<EvidenceQuality taskId="task" issues={[issue]} />);
    expect(screen.getByText(/估算：来源区域 × 系数区域推算，非源表直接数；经理确认前不计为已回答/, { selector: 'summary' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '查看源区域 05·区域预算分解!C5' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '查看源区域 01·年度预算总表!B12:I12' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '查看源区域 01·年度预算总表!N12' }));
    expect(screen.getByRole('region', { name: '源区域预览' }).textContent).toBe('budget/01·年度预算总表/N12');
  });
  it('shows the manager a plain scope-change note, not the assistant repin instruction', () => {
    const issue = { code: 'requirements_changed', severity: 'warning', message: '分析范围已更新，请按当前要求复核文稿：文稿按要求版本 a 撰写，当前版本为 b。修订文稿时同时传 parent_id 和 requirements_id=b；只传 parent_id 的修订沿用旧版本，本提示不会消失。' };
    render(<EvidenceQuality taskId="task" issues={[issue]} />);
    expect(screen.getByText(/^分析范围已更新，请按当前要求复核文稿。 · 1 条原始问题$/, { selector: 'summary' })).toBeTruthy();
    expect(screen.queryByText(/requirements_id/, { selector: 'summary' })).toBeNull();
  });
  it('does not show prior pass status after an edit', () => {
    render(<EvidenceQuality taskId="task" stale dimensions={{ source_validation: { status: 'pass' }, professional_review: { status: 'reviewed' } }} issues={[]} />);
    expect(screen.queryByText('源数据核验通过')).toBeNull();
    expect(screen.getAllByText('改稿后待复核')).toHaveLength(4);
  });
});
