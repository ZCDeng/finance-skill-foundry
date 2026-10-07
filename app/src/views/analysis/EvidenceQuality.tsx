import { useState } from 'react';
import { Button } from '../../components/ui/button.js';
import { WorkbookBrowser } from './WorkbookBrowser.js';
import { DisclosureSummary } from '../../components/Disclosure.js';

export type EvidenceDimension = { status?: string; message?: string; [key: string]: unknown };
export type EvidenceDimensions = Partial<Record<'execution' | 'numeric_citation' | 'source_validation' | 'professional_review', EvidenceDimension>>;
export interface EvidenceIssue {
  code?: string; message?: string; severity?: string; origin?: string; excerpt?: string;
  business_key?: Record<string, unknown> | string; label?: string; location?: unknown;
  assertion_source?: unknown; original_text?: string; [key: string]: unknown;
}
type SourceRange = { dataset_id: string; source_hash?: string; sheet: string; range: string };
const dimensions = [
  ['execution', '计算', '计算成功', '尚未计算'],
  ['numeric_citation', '数字引用', '引用值一致', '尚未检查引用'],
  ['source_validation', '源数据核验', '源数据核验通过', '尚未独立核验'],
  ['professional_review', '专业复核', '已专业复核', '待专业复核'],
] as const;
const messages: Record<string, string> = {
  uncited_number: '正文数字尚未关联计算依据', missing_required_fact: '关键事实尚未引用',
  missing_dataset_citation: '资料来源尚未关联', unknown_fact: '引用已不属于当前计算结果',
  claim_value_mismatch: '引用值与计算结果不一致', revision_numeric_regression: '新修订改变了既有业务数值',
  requirement_estimated: '估算：来源区域 × 系数区域推算，非源表直接数；经理确认前不计为已回答',
  // The server message also tells the assistant which requirements_id a revision must name.
  requirements_changed: '分析范围已更新，请按当前要求复核文稿。',
};
function sources(value: unknown): SourceRange[] {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return [];
  const row = value as Record<string, unknown>;
  if (typeof row.dataset_id === 'string' && typeof row.sheet === 'string' && typeof row.range === 'string') {
    return [{ dataset_id: row.dataset_id, sheet: row.sheet, range: row.range, ...(typeof row.source_hash === 'string' ? { source_hash: row.source_hash } : {}) }];
  }
  return ['left', 'right', 'reference', 'factor'].flatMap((key) => sources(row[key]));
}
function statusText(key: typeof dimensions[number][0], status: string | undefined, success: string, pending: string): string {
  if (['pass', 'passed', 'succeeded', 'verified', 'reviewed', 'approved'].includes(status ?? '')) return success;
  if (['needs_attention', 'mismatch', 'failed', 'error', 'issues', 'rejected'].includes(status ?? '')) return key === 'execution' ? '计算未成功' : '需要复核';
  return pending;
}
/** The four verification dimensions that are not done yet, in words; empty when all four passed. */
export function dimensionGaps(values: EvidenceDimensions | undefined, stale = false): string[] {
  if (stale) return ['改稿后待复核'];
  return dimensions.flatMap(([key, label, success, pending]) => {
    const text = statusText(key, values?.[key]?.status, success, pending);
    if (text === success) return [];
    return [text === '需要复核' ? `${label}需要复核` : text];
  });
}
/** Each of the four verification dimensions in words, one per record. */
export function dimensionStates(values: EvidenceDimensions | undefined): string[] {
  return dimensions.map(([key, , success, pending]) => statusText(key, values?.[key]?.status, success, pending));
}
export function EvidenceDimensionList({ dimensions: values, stale = false, caveat = true }: { dimensions?: EvidenceDimensions; stale?: boolean; caveat?: boolean }) {
  return <>
    <dl className="analysis-check-summary" aria-label="四项独立核验状态">
      {dimensions.map(([key, label, success, pending]) => <div key={key}>
        <dt>{label}</dt><dd>{stale ? '改稿后待复核' : statusText(key, values?.[key]?.status, success, pending)}</dd>
        {values?.[key]?.message && <p className="analysis-note">{values[key]?.message}</p>}
      </div>)}
    </dl>
    {caveat && <p className="analysis-note">计算成功和引用值一致分别记录；源数据核验只覆盖已声明的核验区域。专业判断仍需复核。</p>}
  </>;
}
export function EvidenceQuality({ taskId, dimensions: values, issues, stale = false, showDimensions = true }: {
  taskId: string; dimensions?: EvidenceDimensions; issues: EvidenceIssue[]; stale?: boolean;
  /** False when the caller already lists the dimensions in its own summary. */
  showDimensions?: boolean;
}) {
  const [selected, setSelected] = useState<SourceRange | null>(null);
  const groups = new Map<string, { title: string; message: string; issues: EvidenceIssue[]; sources: Map<string, SourceRange> }>();
  for (const issue of issues) {
    const keyParts = issue.business_key && typeof issue.business_key === 'object' ? Object.entries(issue.business_key).sort(([a], [b]) => a.localeCompare(b)) : [];
    const title = keyParts.map(([, value]) => String(value)).filter(Boolean).join(' · ') || issue.label || '';
    const key = JSON.stringify([issue.code, typeof issue.business_key === 'string' ? issue.business_key : keyParts, issue.origin, issue.severity]);
    const message = issue.origin === 'generated_appendix' && issue.code === 'uncited_number'
      ? '自动附表中的数字与计算依据尚未对应，需要重新核验附表。你的正文可以继续编辑和保存。'
      : messages[issue.code ?? ''] || issue.message || '请核对这条说明的数字和依据';
    const group = groups.get(key) ?? { title, message, issues: [], sources: new Map<string, SourceRange>() };
    group.issues.push(issue);
    for (const source of [...sources(issue.location), ...sources(issue.assertion_source)]) group.sources.set(JSON.stringify(source), source);
    groups.set(key, group);
  }
  return <div className="analysis-evidence-quality">
    {showDimensions && <EvidenceDimensionList dimensions={values} stale={stale} />}
    {[...groups].sort(([, a], [, b]) => priority(a.issues[0]) - priority(b.issues[0])).map(([key, group]) => <details className="analysis-details" key={key}>
      <DisclosureSummary>{group.title ? `${group.title}：` : ''}{group.issues[0].origin === 'claim_binding' ? '引用绑定 · ' : group.issues[0].origin === 'generated_appendix' ? '自动附表 · ' : ''}{group.issues[0].severity === 'error' ? '需修正 · ' : ''}{group.message} · {group.issues.length} 条原始问题</DisclosureSummary>
      <p className="analysis-note">{group.sources.size ? '先核对来源区域，再修正计算或引用并重检。' : '核对当前计算和引用；原始问题保留在下方，便于逐项处理。'}</p>
      {group.issues[0].old_value != null && group.issues[0].new_value != null && <p>原值 {String(group.issues[0].old_value)} → 新值 {String(group.issues[0].new_value)}</p>}
      {[...group.sources].map(([sourceKey, source]) => <Button variant="outline" key={sourceKey} type="button" onClick={() => setSelected(source)}>
        查看源区域 {source.sheet}!{source.range}
      </Button>)}
      {group.issues.map((issue, index) => <details className="analysis-details" key={index}><DisclosureSummary>原始问题 {index + 1}</DisclosureSummary>
        {issue.original_text && <blockquote>{issue.original_text}</blockquote>}
        {issue.excerpt && <p>对应片段：{issue.excerpt}</p>}
        <pre className="analysis-source-text">{JSON.stringify(issue, null, 2)}</pre>
      </details>)}
    </details>)}
    {selected && <section aria-label="问题来源区域"><div className="analysis-section-heading"><h4>{selected.sheet}!{selected.range}</h4>
      <Button variant="ghost" type="button" onClick={() => setSelected(null)}>关闭源区域</Button></div>
      <WorkbookBrowser key={JSON.stringify(selected)} taskId={taskId} datasetId={selected.dataset_id} initialSheet={selected.sheet} initialRange={selected.range} showSheetPicker={false} />
    </section>}
  </div>;
}
function priority(issue: EvidenceIssue): number {
  if (/^(evidence_recipe_|financial_consistency_|revision_numeric_)/.test(issue.code ?? '')) return 0;
  return issue.severity === 'error' ? 1 : 2;
}
