// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AnalysisDraft, Answer, Bridge } from '../src/bridge.js';
vi.mock('../src/views/analysis/ReportEditor.js', () => ({
  ReportEditor: () => <div>文稿正文</div>,
  PdfComparison: ({ page }: { page?: number }) => <div>PDF 原页 {page}</div>,
}));
import { DraftEditor } from '../src/views/analysis/DraftEditor.js';
import { ReportReviewPanel, candidateWords, gapWords, groupedNumber, reviewPlace, type ReportReview } from '../src/views/analysis/ReportReviewPanel.js';

const taskId = 'a'.repeat(32);
const dataset = 'd'.repeat(32);
const pdfSource = 'e'.repeat(32);
const review: ReportReview = {
  id: 'r'.repeat(32),
  summary: { status: 'needs_attention', total: 5, match: 1, match_rounded: 1, match_scaled: 1, mismatch: 1, needs_review: 1, needs_review_not_amount: 0 },
  items: [
    { id: 'n1', text: '820 万元', value: '820', unit: '万元', status: 'mismatch', excerpt: '营业成本本月实际 820 万元。',
      location: { source_id: pdfSource, source_format: 'pdf', page: '3', section: '第 3 页', kind: 'paragraph' },
      candidates: [{ kind: 'workbook', dataset_id: dataset, sheet: '利润表', range: 'B5', label: '营业成本 · 本月实际', value: '800', unit: '万元' }],
      compared_value: '800', compared_basis: 'same', difference: '20' },
    { id: 'n2', text: '1,234.56', value: '1234.56', unit: '万元', status: 'match_scaled',
      location: { kind: 'table_cell', table_index: 2, row: 4, column: 3, section: '明细' }, excerpt: '1,234.56',
      candidates: [{ kind: 'workbook', dataset_id: dataset, sheet: '明细', range: 'B12', label: '一店 · 收入', value: '12345600', unit: '元' }],
      note: '与来源相差 10000 倍，疑似单位换算（如元与万元），请核对单位。' },
    { id: 'n3', text: '77 万元', value: '77', unit: '万元', status: 'needs_review', location: { kind: 'paragraph', section: '八月经营分析' },
      excerpt: '其他 77 万元。', candidates: [], note: '没有在当前资料和计算结果中找到这个数字。' },
    { id: 'n4', text: '1,234.57 万元', value: '1234.57', unit: '万元', status: 'match_rounded', location: { kind: 'paragraph', section: '八月经营分析' },
      excerpt: '本月营业收入 1,234.57 万元', candidates: [{ kind: 'workbook', dataset_id: dataset, sheet: '利润表', range: 'B4', label: '营业收入 · 本月实际', value: '1234.5678', unit: '万元' }],
      note: '按文稿显示的 2 位小数四舍五入后一致。' },
    { id: 'n5', text: '120 万元', value: '120', unit: '万元', status: 'match', location: { kind: 'paragraph' }, excerpt: '收入实际 120 万元',
      candidates: [{ kind: 'fact', label: '收入 · 实际 2026-09', value: '120', unit: '万元' }] },
  ],
  notes: ['1 份已被新版本取代的资料没有参与比对。'],
  closing_note: '复核只比对数字，不判断表述是否恰当，也不代表报告可以对外发送。',
};

afterEach(() => { cleanup(); delete (globalThis as unknown as { foundry?: Partial<Bridge> }).foundry; });

describe('report review words', () => {
  it('groups exact decimal strings without going through Number', () => {
    expect(groupedNumber('12345678901234567890.123')).toBe('12,345,678,901,234,567,890.123');
    expect(groupedNumber('-1234.5')).toBe('-1,234.5');
    expect(groupedNumber('0.352')).toBe('0.352');
    expect(groupedNumber('not a number')).toBe('not a number');
  });
  it('names the place in the report and the source cell', () => {
    expect(reviewPlace({ page: '3', kind: 'paragraph' })).toBe('第 3 页');
    expect(reviewPlace({ kind: 'table_cell', table_index: 2, row: 4, column: 3 })).toBe('表 2 第 4 行第 3 列');
    expect(reviewPlace({ kind: 'paragraph', section: '一、经营 / 收入' })).toBe('「收入」一节');
    expect(reviewPlace(undefined)).toBe('正文');
    expect(candidateWords({ kind: 'workbook', sheet: '利润表', range: 'B12', value: '1234.56', unit: '万元' })).toBe('套表 利润表!B12 = 1,234.56 万元');
    expect(candidateWords({ kind: 'workbook', sheet: '利润表', range: 'B7', label: '毛利率', value: '35.2', unit: '%' })).toBe('套表 利润表!B7 「毛利率」 = 35.2%');
  });
  it('says which side is larger, and gives a gap between percentages in percentage points', () => {
    expect(gapWords('20', '万元')).toBe('文稿比来源多 20 万元');
    expect(gapWords('-1385', '万元')).toBe('文稿比来源少 1,385 万元');
    expect(gapWords('5', '%')).toBe('文稿比来源高 5 个百分点');
    expect(gapWords('-0.05', '%')).toBe('文稿比来源低 0.05 个百分点');
    expect(gapWords('12', null)).toBe('文稿比来源多 12');
  });
});

describe('ReportReviewPanel', () => {
  it('shows counts in words, opens on the mismatches and lists each number with its place, excerpt and source', () => {
    const financeCall = vi.fn(async (): Promise<Answer<Record<string, unknown>>> => ({ ok: true, value: {} }));
    (globalThis as unknown as { foundry: Partial<Bridge> }).foundry = { financeCall: financeCall as unknown as Bridge['financeCall'] };
    render(<ReportReviewPanel taskId={taskId} review={review} />);
    const panel = screen.getByRole('region', { name: '报告数字复核结果' });
    expect(within(panel).getByRole('status').textContent).toBe('共 5 个数字，3 个需要你核对。');
    const counts = within(panel).getByRole('list', { name: '复核结果统计' });
    expect([...counts.querySelectorAll('li')].map((row) => row.textContent)).toEqual(['不一致1', '疑似单位换算1', '需人工核对1', '一致2']);
    expect(counts.querySelectorAll('svg').length).toBe(4);
    expect(screen.getByText('「一致」里有 1 个是按文稿显示的小数位四舍五入后一致。')).toBeTruthy();

    const tabs = within(panel).getAllByRole('tab').map((tab) => tab.textContent);
    expect(tabs).toEqual(['不一致1', '疑似单位换算1', '需人工核对1', '一致2']);
    const current = within(panel).getByRole('tabpanel');
    expect(within(current).getByText('820 万元')).toBeTruthy();
    expect(within(current).getByText('第 3 页')).toBeTruthy();
    expect(within(current).getByText('营业成本本月实际 820 万元。')).toBeTruthy();
    expect(within(current).getByText('来源：套表 利润表!B5 「营业成本 · 本月实际」 = 800 万元')).toBeTruthy();
    expect(within(current).getByText('文稿比来源多 20 万元')).toBeTruthy();

    fireEvent.mouseDown(within(panel).getByRole('tab', { name: '疑似单位换算1' }), { button: 0 });
    const scaled = within(panel).getByRole('tabpanel');
    expect(within(scaled).getByText('表 2 第 4 行第 3 列')).toBeTruthy();
    expect(within(scaled).getByText('对应来源：套表 明细!B12 「一店 · 收入」 = 12,345,600 元')).toBeTruthy();
    fireEvent.click(within(scaled).getByRole('button', { name: '查看源区域 明细!B12' }));
    const opened = screen.getByRole('region', { name: '复核来源区域' });
    expect(within(opened).getByRole('heading', { name: '明细!B12' })).toBeTruthy();

    fireEvent.mouseDown(within(panel).getByRole('tab', { name: '一致2' }), { button: 0 });
    const matched = within(panel).getByRole('tabpanel');
    expect(within(matched).getByText('四舍五入后一致')).toBeTruthy();
    expect(within(matched).getByText('对应来源：计算结果 「收入 · 实际 2026-09」 = 120 万元')).toBeTruthy();
    expect(screen.getByText('1 份已被新版本取代的资料没有参与比对。')).toBeTruthy();
    expect(screen.getByText('复核只比对数字，不判断表述是否恰当，也不代表报告可以对外发送。')).toBeTruthy();
    expect(screen.getByRole('button', { name: '使用指南：复核外部报告数字' })).toBeTruthy();
  });

  it('words a converted source value, and never shows a cut-off review as all clear', () => {
    render(<ReportReviewPanel taskId={taskId} review={{
      summary: { status: 'needs_attention', total: 3, match: 1, mismatch: 2, truncated: true },
      items: [
        { id: 'n1', text: '35.7%', value: '35.7', unit: '%', status: 'mismatch', compared_value: '35.2', compared_basis: 'ratio', difference: '0.5',
          candidates: [{ kind: 'workbook', sheet: '利润表', range: 'B6', label: '毛利率 · 本月实际', value: '0.352', unit: null }] },
        // A record from before compared_basis: the source was converted into the report's unit.
        { id: 'n2', text: '820 万元', value: '820', unit: '万元', status: 'mismatch', compared_value: '800', difference: '20',
          candidates: [{ kind: 'workbook', sheet: '利润表', range: 'B5', value: '8000000', unit: '元' }] },
      ],
    }} />);
    expect(screen.getByText('来源是比例值，即 35.2%，文稿比来源高 0.5 个百分点')).toBeTruthy();
    expect(screen.getByText('来源折成文稿单位是 800 万元，文稿比来源多 20 万元')).toBeTruthy();
    cleanup();

    render(<ReportReviewPanel taskId={taskId} review={{
      summary: { status: 'needs_attention', total: 1, match: 1, truncated: true },
      items: [{ id: 'n1', text: '9,876.54 万元', value: '9876.54', unit: '万元', status: 'match', candidates: [] }],
      notes: ['文稿里的数字超过 3000 个，只复核了前 3000 个。'],
    }} />);
    const headline = screen.getByRole('status');
    expect(headline.textContent).toBe('复核了前 1 个数字，都找到了一致的数值。文稿里的数字超过复核上限，其余数字没有复核，请人工核对。');
    expect(headline.className).toContain('analysis-report-review-headline--attention');
  });

  it('offers the original page only for a number read from a PDF', () => {
    const load = vi.fn(async () => 'data:application/pdf;base64,JVBE');
    render(<ReportReviewPanel taskId={taskId} pdf={{ load, render: () => null }} review={{
      summary: { status: 'needs_attention', total: 2, needs_review: 2 },
      items: [
        { id: 'n1', text: '500 万元', value: '500', unit: '万元', status: 'needs_review', candidates: [],
          location: { source_id: 'p'.repeat(32), source_format: 'pptx', page: '2', kind: 'paragraph' } },
        // An older record names no format: no page button rather than one that cannot open.
        { id: 'n2', text: '600 万元', value: '600', unit: '万元', status: 'needs_review', candidates: [],
          location: { source_id: pdfSource, page: '4', kind: 'paragraph' } },
      ],
    }} />);
    expect(screen.getByText('第 2 页')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /查看原文第/ })).toBeNull();
  });

  it('opens the cited PDF page through the parent and tolerates a record from an older engine', async () => {
    const load = vi.fn(async (id: string) => id === pdfSource ? 'data:application/pdf;base64,JVBE' : undefined);
    const renderPdf = vi.fn((_url: string, page: number) => <div>PDF 原页 {page}</div>);
    render(<ReportReviewPanel taskId={taskId} review={review} pdf={{ load, render: renderPdf }} />);
    fireEvent.click(screen.getByRole('button', { name: '查看原文第 3 页' }));
    await waitFor(() => expect(screen.getByRole('region', { name: '复核原文页面' })).toBeTruthy());
    expect(load).toHaveBeenCalledWith(pdfSource);
    expect(renderPdf).toHaveBeenCalledWith('data:application/pdf;base64,JVBE', 3);
    cleanup();

    render(<ReportReviewPanel taskId={taskId} review={{}} />);
    expect(screen.getByRole('status').textContent).toBe('文稿里没有找到可比对的数字。');
    expect(screen.queryByRole('tab')).toBeNull();
    expect(screen.getByText('复核只比对数字，不判断表述是否恰当，也不代表报告可以对外发送。')).toBeTruthy();
  });
});

describe('draft view', () => {
  const common = { task_id: taskId, schema_version: 1, created_at: '2026-10-04T00:00:00Z' };
  const document = {
    schema_version: 1, template_version: 'annual-v1',
    metadata: { company: '', period: '', currency: '', unit: '' },
    sources: [{ id: pdfSource, name: '八月月报.pdf', sha256: 'f'.repeat(64), format: 'pdf' }],
    content: [{ type: 'paragraph', content: [{ type: 'text', text: '营业成本本月实际 820 万元。' }] }],
  };
  const draft = { ...common, id: 'c'.repeat(32), title: '八月月报', body: '营业成本本月实际 820 万元。', run_ids: [], claims: [],
    limitations: [], review_status: 'unreviewed', publication_status: 'draft', document } as unknown as AnalysisDraft;

  it('reviews a saved imported draft by its id and leaves the draft as it was', async () => {
    const financeCall = vi.fn(async (_task: string, command: string): Promise<Answer<Record<string, unknown>>> => ({
      ok: true, value: command === 'report-review' ? review as Record<string, unknown> : {},
    }));
    (globalThis as unknown as { foundry: Partial<Bridge> }).foundry = { financeCall: financeCall as unknown as Bridge['financeCall'] };
    const onSave = vi.fn();
    render(<DraftEditor taskId={taskId} draft={draft} drafts={[draft]} runs={[]} datasets={[]} busy={false}
      onEdit={vi.fn()} onSave={onSave} onExport={vi.fn()} onChat={vi.fn()} onDiscussRequirements={vi.fn()} />);
    const section = screen.getByRole('region', { name: '复核外部报告数字' });
    fireEvent.click(within(section).getByRole('button', { name: '复核外部报告数字' }));
    await waitFor(() => expect(within(section).getByRole('region', { name: '报告数字复核结果' })).toBeTruthy());
    expect(financeCall).toHaveBeenCalledWith(taskId, 'report-review', { draft_id: draft.id });
    expect(onSave).not.toHaveBeenCalled();
    expect(within(section).getByRole('button', { name: '重新复核' })).toBeTruthy();
  });

  it('offers no review for a draft written here without an imported source', () => {
    const written = { ...draft, id: '9'.repeat(32), document: { ...document, sources: [] } } as unknown as AnalysisDraft;
    render(<DraftEditor taskId={taskId} draft={written} drafts={[written]} runs={[]} datasets={[]} busy={false}
      onEdit={vi.fn()} onSave={vi.fn()} onExport={vi.fn()} onChat={vi.fn()} onDiscussRequirements={vi.fn()} />);
    expect(screen.queryByRole('region', { name: '复核外部报告数字' })).toBeNull();
  });
});
