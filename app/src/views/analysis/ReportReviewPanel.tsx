import { useState, type ReactNode } from 'react';
import { CircleCheck, CircleHelp, ListChecks, Scale, TriangleAlert } from 'lucide-react';
import { bridge, type Answer } from '../../bridge.js';
import { Button } from '../../components/ui/button.js';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../components/ui/tabs.js';
import { HelpLink } from '../guide/GuideHub.js';
import { WorkbookBrowser } from './WorkbookBrowser.js';
import { errorText, unwrap } from './shared.js';

export type ReportReviewStatus = 'match' | 'match_rounded' | 'match_scaled' | 'mismatch' | 'needs_review';
export interface ReportReviewCandidate {
  kind?: 'workbook' | 'table' | 'fact' | string;
  dataset_id?: string; source_hash?: string; sheet?: string; range?: string;
  row?: number; column?: string; fact_id?: string; run_id?: string;
  label?: string; value?: string; unit?: string | null; display?: string;
}
export interface ReportReviewLocation {
  source_id?: string; page?: string; section?: string; kind?: string;
  table_index?: number; row?: number; column?: number; sheet?: string; range?: string;
}
export interface ReportReviewItem {
  id: string; text?: string; value?: string; unit?: string | null; location?: ReportReviewLocation; excerpt?: string;
  status?: ReportReviewStatus | string; candidates?: ReportReviewCandidate[]; note?: string; amount_like?: boolean;
  compared_value?: string; difference?: string;
}
export interface ReportReview {
  id?: string;
  summary?: Partial<Record<ReportReviewStatus | 'total' | 'needs_review_not_amount', number>> & { status?: string; truncated?: boolean };
  items?: ReportReviewItem[];
  notes?: string[];
  closing_note?: string;
}
/** Where the panel can open a PDF page: the parent loads the archived bytes and draws the page. */
export interface ReportReviewPdf {
  load(sourceId: string): Promise<string | undefined>;
  render(dataUrl: string, page: number): ReactNode;
}

const CLOSING_NOTE = '复核只比对数字，不判断表述是否恰当，也不代表报告可以对外发送。';
const TABS = [
  { id: 'mismatch', label: '不一致', statuses: ['mismatch'], Icon: TriangleAlert },
  { id: 'scaled', label: '疑似单位换算', statuses: ['match_scaled'], Icon: Scale },
  { id: 'review', label: '需人工核对', statuses: ['needs_review'], Icon: CircleHelp },
  { id: 'match', label: '一致', statuses: ['match', 'match_rounded'], Icon: CircleCheck },
] as const;
type TabId = typeof TABS[number]['id'];
const STATUS_WORDS: Record<string, string> = {
  match: '一致', match_rounded: '四舍五入后一致', match_scaled: '疑似单位换算', mismatch: '不一致', needs_review: '需人工核对',
};
const KIND_WORDS: Record<string, string> = { workbook: '套表', table: '资料表', fact: '计算结果' };

/** Thousands separators on an exact decimal string; the digits never pass through Number. */
export function groupedNumber(value: string): string {
  const match = /^([+-]?)(\d+)(\.\d+)?$/.exec(value.trim());
  if (!match) return value;
  return `${match[1]}${match[2].replace(/\B(?=(\d{3})+(?!\d))/g, ',')}${match[3] ?? ''}`;
}
function amountWords(value: string | undefined, unit: string | null | undefined): string {
  if (value == null) return '';
  const text = groupedNumber(value);
  if (!unit) return text;
  return unit === '%' ? `${text}%` : `${text} ${unit}`;
}
/** 「第 3 页」「表 2 第 4 行第 3 列」 or the section the number sits in. */
export function reviewPlace(location: ReportReviewLocation | undefined): string {
  if (!location) return '正文';
  const parts: string[] = [];
  if (location.page) parts.push(`第 ${location.page} 页`);
  if (location.kind === 'table_cell' && location.table_index) parts.push(`表 ${location.table_index} 第 ${location.row} 行第 ${location.column} 列`);
  else if (location.kind === 'note') parts.push('附注');
  else if (location.section && !location.page) parts.push(`「${location.section.split(' / ').pop()}」一节`);
  return parts.join(' ') || '正文';
}
function candidateWhere(candidate: ReportReviewCandidate): string {
  const kind = KIND_WORDS[candidate.kind ?? ''] ?? '来源';
  if (candidate.sheet && candidate.range) return `${kind} ${candidate.sheet}!${candidate.range}`;
  if (candidate.row != null && candidate.column) return `${kind} 第 ${candidate.row} 行 ${candidate.column} 列`;
  return kind;
}
/** 「套表 利润表!B12 = 1,234.56 万元」, with the source line's name when it has one. */
export function candidateWords(candidate: ReportReviewCandidate): string {
  const label = candidate.label ? `「${candidate.label}」` : '';
  return `${candidateWhere(candidate)}${label ? ` ${label}` : ''} = ${amountWords(candidate.value, candidate.unit) || '—'}`;
}
type SourceRange = { dataset_id: string; sheet: string; range: string };
function sourceRange(candidate: ReportReviewCandidate | undefined): SourceRange | null {
  if (!candidate?.dataset_id || !candidate.sheet || !candidate.range) return null;
  return { dataset_id: candidate.dataset_id, sheet: candidate.sheet, range: candidate.range };
}
function pageNumber(page: string | undefined): number | undefined {
  // A page is a place in the file, not an amount: a whole number is enough here.
  return page && /^\d{1,5}$/.test(page) ? Number.parseInt(page, 10) : undefined;
}

/** Ask Foundry to check the numbers of a saved draft or of a document still in the import preview. */
export async function requestReportReview(taskId: string, spec: { draft_id: string } | { document: unknown }): Promise<ReportReview> {
  const api = bridge();
  if (!api?.financeCall) throw new Error('此版本暂不支持复核报告数字。');
  return unwrap(await api.financeCall(taskId, 'report-review', spec as Record<string, unknown>) as Answer<ReportReview>);
}

export function ReportReviewPanel({ taskId, review, pdf }: { taskId: string; review: ReportReview; pdf?: ReportReviewPdf }) {
  const items = Array.isArray(review.items) ? review.items : [];
  const groups = TABS.map((tab) => ({ ...tab, items: items.filter((item) => (tab.statuses as readonly string[]).includes(String(item.status))) }));
  const [tab, setTab] = useState<TabId>(() => groups.find((group) => group.items.length)?.id ?? 'mismatch');
  const [source, setSource] = useState<SourceRange | null>(null);
  const [page, setPage] = useState<{ dataUrl: string; page: number } | null>(null);
  const [pageError, setPageError] = useState('');
  const summary = review.summary ?? {};
  const total = summary.total ?? items.length;
  const attention = (summary.mismatch ?? 0) + (summary.match_scaled ?? 0) + (summary.needs_review ?? 0);
  const openPage = async (item: ReportReviewItem) => {
    const number = pageNumber(item.location?.page);
    if (!pdf || !item.location?.source_id || !number) return;
    setPageError('');
    try {
      const dataUrl = await pdf.load(item.location.source_id);
      if (dataUrl) setPage({ dataUrl, page: number });
      else setPageError('原文件不是 PDF 或未归档，无法打开原页。');
    } catch (failure) { setPageError(errorText(failure)); }
  };
  return <section className="analysis-report-review" aria-label="报告数字复核结果">
    <div className="analysis-section-heading"><h4><ListChecks size={16} aria-hidden />数字复核结果</h4>
      <HelpLink article="report-review" label="复核外部报告数字" /></div>
    <p className={`analysis-report-review-headline${attention ? ' analysis-report-review-headline--attention' : ''}`} role="status">
      {attention ? <TriangleAlert size={16} aria-hidden /> : <CircleCheck size={16} aria-hidden />}
      {total === 0 ? '文稿里没有找到可比对的数字。'
        : attention ? `共 ${total} 个数字，${attention} 个需要你核对。`
          : `共 ${total} 个数字，都在当前资料或计算结果中找到了一致的数值。`}
    </p>
    <ul className="analysis-report-review-summary" aria-label="复核结果统计">
      {groups.map(({ id, label, Icon, items: rows }) => <li key={id}
        className={`analysis-report-review-count${id !== 'match' && rows.length ? ' analysis-report-review-count--attention' : ''}`}>
        <Icon size={14} aria-hidden /><span>{label}</span><strong>{rows.length}</strong></li>)}
    </ul>
    {(summary.match_rounded ?? 0) > 0 && <p className="analysis-note">「一致」里有 {summary.match_rounded} 个是按文稿显示的小数位四舍五入后一致。</p>}
    {(summary.needs_review_not_amount ?? 0) > 0 && <p className="analysis-note">需人工核对里有 {summary.needs_review_not_amount} 个看起来不是金额或比例（如人数、编号），排在最后。</p>}
    {items.length > 0 && <Tabs value={tab} onValueChange={(value) => setTab(value as TabId)}>
      <TabsList className="analysis-report-review-tabs" aria-label="按复核结果查看">
        {groups.map(({ id, label, items: rows }) => <TabsTrigger key={id} value={id}>{label}<span>{rows.length}</span></TabsTrigger>)}
      </TabsList>
      {groups.map(({ id, label, items: rows }) => <TabsContent key={id} value={id}>
        {rows.length === 0 ? <p className="analysis-note">没有「{label}」的数字。</p>
          : <ol className="analysis-report-review-items">{rows.map((item) => {
            const best = item.candidates?.[0];
            const range = sourceRange(best);
            const canOpenPage = Boolean(pdf && item.location?.source_id && pageNumber(item.location?.page));
            return <li key={item.id} className={`analysis-report-review-item analysis-report-review-item--${item.status}`}>
              <div className="analysis-report-review-item-head">
                <strong className="analysis-report-review-number">{item.text}</strong>
                <span className="analysis-report-review-status">{STATUS_WORDS[String(item.status)] ?? '需人工核对'}</span>
                <span className="analysis-note">{reviewPlace(item.location)}</span>
              </div>
              {item.excerpt && <blockquote className="analysis-report-review-excerpt">{item.excerpt}</blockquote>}
              {best && <p className="analysis-report-review-candidate">{item.status === 'mismatch' ? '来源：' : item.status === 'needs_review' ? '最接近的来源：' : '对应来源：'}{candidateWords(best)}</p>}
              {item.status === 'mismatch' && item.difference != null && <p className="analysis-report-review-difference">
                按文稿单位折算来源为 {amountWords(item.compared_value, item.unit)}，相差 {amountWords(item.difference, item.unit)}</p>}
              {item.note && <p className="analysis-note">{item.note}</p>}
              {(item.candidates?.length ?? 0) > 1 && <details className="analysis-details"><summary>其他候选来源 · {item.candidates!.length - 1} 个</summary>
                <ul>{item.candidates!.slice(1).map((candidate, index) => <li key={index}>{candidateWords(candidate)}</li>)}</ul></details>}
              {(range || canOpenPage) && <div className="analysis-actions">
                {range && <Button variant="outline" type="button" onClick={() => setSource(range)}>查看源区域 {range.sheet}!{range.range}</Button>}
                {canOpenPage && <Button variant="outline" type="button" onClick={() => void openPage(item)}>查看原文第 {item.location!.page} 页</Button>}
              </div>}
            </li>;
          })}</ol>}
      </TabsContent>)}
    </Tabs>}
    {source && <section aria-label="复核来源区域"><div className="analysis-section-heading"><h4>{source.sheet}!{source.range}</h4>
      <Button variant="ghost" type="button" onClick={() => setSource(null)}>关闭源区域</Button></div>
      <WorkbookBrowser key={JSON.stringify(source)} taskId={taskId} datasetId={source.dataset_id} initialSheet={source.sheet} initialRange={source.range} showSheetPicker={false} />
    </section>}
    {pageError && <p role="alert" className="analysis-message analysis-message--error">{pageError}</p>}
    {page && pdf && <section aria-label="复核原文页面"><div className="analysis-section-heading"><h4>原文第 {page.page} 页</h4>
      <Button variant="ghost" type="button" onClick={() => setPage(null)}>关闭原页</Button></div>
      {pdf.render(page.dataUrl, page.page)}
    </section>}
    {(review.notes ?? []).map((note) => <p key={note} className="analysis-note">{note}</p>)}
    <p className="analysis-report-review-closing">{review.closing_note || CLOSING_NOTE}</p>
  </section>;
}

/**
 * The 复核数字 button and its result. Running it files a review record and changes nothing else:
 * not the document, not the draft's review status.
 */
export function ReportReviewAction({ taskId, spec, label, intro, disabled = false, pdf }: {
  taskId: string;
  spec: { draft_id: string } | { document: unknown } | null;
  label: string;
  intro: string;
  disabled?: boolean;
  pdf?: ReportReviewPdf;
}) {
  // The result belongs to what was reviewed: a re-read import or another draft shows none until run again.
  const subject = spec ? ('draft_id' in spec ? spec.draft_id : spec.document) : null;
  const [reviewed, setReviewed] = useState<{ subject: unknown; review: ReportReview } | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState('');
  const review = reviewed && reviewed.subject === subject ? reviewed.review : null;
  const run = async () => {
    if (!spec) return;
    setRunning(true); setError('');
    try { setReviewed({ subject, review: await requestReportReview(taskId, spec) }); }
    catch (failure) { setReviewed(null); setError(errorText(failure)); }
    finally { setRunning(false); }
  };
  return <div className="analysis-report-review-action">
    <div className="analysis-report-review-intro">
      <p className="analysis-note">{intro}</p>
      <Button variant="outline" type="button" disabled={disabled || running || !spec} onClick={() => void run()}>
        <ListChecks size={14} aria-hidden />{running ? '正在复核…' : review ? '重新复核' : label}</Button>
    </div>
    {error && <p role="alert" className="analysis-message analysis-message--error">{error}</p>}
    {review && <ReportReviewPanel key={review.id ?? 'review'} taskId={taskId} review={review} pdf={pdf} />}
  </div>;
}
