// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { EvidenceQuality } from '../src/views/analysis/EvidenceQuality.js';
import type { RequirementItemView } from '../src/views/analysis/requirementGaps.js';
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
  it('merges unanswered requirements by reason and names requirements and organizations once', () => {
    const organizations = ['华东区域', '华南区域', '华北区域', '西南区域', '西北区域', '东北区域'];
    const reason = '系数区域 N12 引用了未缓存的公式';
    const declared = organizations.map((organization) => ({ organization, period: '2026-01:2026-08', scenario: 'budget_1_8', state: 'estimate_factor_not_reproducible', reason }));
    const items: RequirementItemView[] = [
      { id: 'r1', label: '1-8 月营业收入', status: 'missing', provenance_status: 'not_required', organizations, awaiting_manager: ['estimate_factor_not_reproducible'], declared_grains: declared },
      { id: 'r2', label: '1-8 月营业利润', status: 'missing', provenance_status: 'not_required', organizations, awaiting_manager: ['estimate_factor_not_reproducible'], declared_grains: declared },
      { id: 'r3', label: '控制总数', status: 'missing', provenance_status: 'not_required', awaiting_manager: ['structure_pending_confirmation', 'bindings_without_engine_rows'] },
    ];
    const long = (label: string) => `尚未提供“${label}”的计算依据。${'metric_key 与 evidence_recipe 的长说明。'.repeat(40)}`;
    const issues = items.map((item) => ({ code: 'requirement_unanswered', severity: 'warning', message: long(item.label), requirement_item_id: item.id }));
    render(<EvidenceQuality taskId="task" issues={issues} requirements={items} />);
    const summary = screen.getByText(/分析要求还没有可计入的计算依据/, { selector: 'summary' });
    expect(summary.textContent).toBe('分析要求还没有可计入的计算依据 · 3 条原始问题');
    const gaps = summary.closest('details')!.querySelector('.analysis-requirement-gaps') as HTMLElement;
    expect(within(gaps).getAllByText('估算系数无法由归档单元格复算，需要你决定口径')).toHaveLength(1);
    expect(within(gaps).getByText('要求：1-8 月营业收入；1-8 月营业利润')).toBeTruthy();
    expect(within(gaps).getByText(reason)).toBeTruthy();
    const scopes = within(gaps).getByText(/^涉及：/).textContent ?? '';
    for (const organization of organizations) expect(scopes.split(organization)).toHaveLength(2);
    const structure = within(gaps).getByText('工作簿结构待你确认').closest('li') as HTMLElement;
    expect(within(structure).getByText('要求：控制总数')).toBeTruthy();
    expect(within(gaps).getByText('绑定的资料读不出计算行，需要改绑或换依据')).toBeTruthy();
    expect(gaps.textContent).not.toContain('metric_key');
    fireEvent.click(screen.getByText('原始问题 1', { selector: 'summary' }));
    expect(screen.getByText(/"message": "尚未提供“1-8 月营业收入”的计算依据。metric_key/)).toBeTruthy();
  });
  it('writes a grain without an organization as its period and scenario in words', () => {
    const items: RequirementItemView[] = [{ id: 'r1', label: '全年预算', status: 'missing', provenance_status: 'not_required',
      missing_grains: [{ period: '2026-01:2026-08', scenario: 'budget_1_8' }] }];
    render(<EvidenceQuality taskId="task" issues={[{ code: 'requirement_unanswered', severity: 'warning', message: '尚未提供“全年预算”的计算依据。', requirement_item_id: 'r1' }]} requirements={items} />);
    const gaps = document.querySelector('.analysis-requirement-gaps') as HTMLElement;
    expect(within(gaps).getByText('还没有可计入的计算依据')).toBeTruthy();
    expect(within(gaps).getByText('涉及：2026 年 1–8 月 · 预算')).toBeTruthy();
    expect(gaps.textContent).not.toContain('2026-01:2026-08');
    expect(gaps.textContent).not.toContain('budget_1_8');
  });
  it('lists every requirement whose source check is missing, from the message when items are absent', () => {
    const issues = ['营业收入', '营业利润'].map((label, index) => ({ code: 'requested_source_missing', severity: 'warning', message: `尚未完成“${label}”的指定来源核查。`, requirement_item_id: `r${index}` }));
    render(<EvidenceQuality taskId="task" issues={issues} />);
    expect(screen.getByText(/指定来源还没有核查 · 2 条原始问题/, { selector: 'summary' })).toBeTruthy();
    const gaps = document.querySelector('.analysis-requirement-gaps') as HTMLElement;
    expect(within(gaps).getByText('要求：营业收入；营业利润')).toBeTruthy();
  });
});
