import type { FinanceDrilldown } from '../../bridge.js';
import { TechnicalInfo } from './TechnicalInfo.js';
import { STATUS, Table, textValue } from './presentation.js';
import { WaitOrb } from '../../components/WaitOrb.js';
import { dimensionGaps, dimensionStates, EvidenceDimensionList, EvidenceQuality, type EvidenceDimensions, type EvidenceIssue } from './EvidenceQuality.js';
import { PdfComparison } from './ReportEditor.js';
import { Button } from '../../components/ui/button.js';
import { metricLabel, scopeSummary } from './shared.js';
import { HelpLink } from '../guide/GuideHub.js';

export interface ExplanationFact {
  id: string; run_id: string; row?: number; column?: string; value?: unknown; display_value?: unknown; label?: string; unit?: string; scope?: Record<string, unknown>; semantics?: Record<string, unknown>;
}
export interface ExplanationQuality {
  status?: string; issues?: EvidenceIssue[]; coverage?: unknown; citations?: unknown[];
  status_dimensions?: EvidenceDimensions;
  readability?: { status: 'clear' | 'suggestions'; issues: { code: string; message: string; position?: number }[] };
  checks?: Partial<Record<'numbers' | 'coverage' | 'provenance', { status?: string }>>;
  requirements?: { scope_changed?: boolean; items?: { id: string; label: string; status: string; provenance_status: string }[] };
}

function qualityLabel(state: 'idle' | 'checking' | 'passed' | 'issues' | 'stale' | 'unavailable'): string {
  return ({ idle: '尚未检查', checking: '检查中', passed: '检查通过', issues: '需要复核', stale: '待重检', unavailable: '暂不可检查' } as Record<typeof state, string>)[state];
}

function coverageSummary(coverage: unknown): string {
  if (!coverage || typeof coverage !== 'object') return '';
  const value = coverage as Record<string, unknown>;
  const required = value.required ?? value.required_facts ?? value.total;
  const cited = value.cited ?? value.cited_facts ?? value.matched;
  if (required != null && cited != null) return `覆盖 ${textValue(cited)}/${textValue(required)} 条关键事实`;
  return '';
}

function factLabel(fact: ExplanationFact): string {
  const value = textValue(fact.display_value ?? fact.value);
  const label = String(fact.label ?? '').split(' / ').map((part) => STATUS[part] ?? metricLabel(part)).join(' / ');
  return [label, value, fact.unit && !value.includes(fact.unit) ? fact.unit : ''].filter(Boolean).join(' · ') || fact.id;
}

const qualityChecks = [['numbers', '数字与口径'], ['coverage', '问题覆盖'], ['provenance', '来源追溯']] as const;
function checkStateText(result: string | undefined): string {
  if (result === 'pass') return '已核对';
  if (result === 'pass_with_accepted_estimates') return '已核对（含已接受的估算）';
  return result === 'needs_attention' ? '仍有缺口' : '尚未核对';
}

export function ExplanationQualityPanel({ taskId, quality, state, facts, citedFactIds, factDetails, locatorNotice, locatorPdf, busy, onRecheck, onOpenFact, onOpenLocator }: {
  taskId: string; quality: ExplanationQuality | null; state: 'idle' | 'checking' | 'passed' | 'issues' | 'stale' | 'unavailable'; facts: ExplanationFact[]; citedFactIds: string[];
  factDetails: Record<string, FinanceDrilldown>; locatorNotice: Record<string, string>; locatorPdf: { factId: string; dataUrl: string; page?: number } | null; busy: boolean; onRecheck(): void; onOpenFact(fact: ExplanationFact): void; onOpenLocator(fact: ExplanationFact): void;
}) {
  const coverage = coverageSummary(quality?.coverage);
  const stale = state === 'stale';
  // One line of what is still open. The seven statuses stay separate records and
  // stay listed below; this only names the ones a manager still has to act on.
  const checkGaps = stale ? [] : qualityChecks.flatMap(([key, label]) => {
    const result = quality?.checks?.[key]?.status;
    return !quality?.checks || result === 'pass' || result === 'pass_with_accepted_estimates' ? [] : [`${label}${checkStateText(result)}`];
  });
  const gaps = [...checkGaps, ...dimensionGaps(quality?.status_dimensions, stale)];
  const accepted = qualityChecks.filter(([key]) => quality?.checks?.[key]?.status === 'pass_with_accepted_estimates').map(([, label]) => label);
  const itemCount = (quality?.checks ? qualityChecks.length : 0) + 4;
  return <section className="analysis-quality" aria-label="文稿质量检查">
    <div className="analysis-section-heading"><div><h4>文稿质量检查 <HelpLink article="statuses" label="状态互不替代" /></h4><p className="analysis-note">{state === 'checking' && <WaitOrb state="searching" />}{qualityLabel(state)}{coverage ? ` · ${coverage}` : ''}{citedFactIds.length ? ` · 已引用 ${citedFactIds.length} 条事实` : ''}</p></div>
      <Button variant="outline" type="button" disabled={busy || state === 'checking'} onClick={onRecheck}>重检当前正文</Button></div>
    {/* Never one merged "all passed": with nothing open, the four verification states are named one by one. */}
    {quality && <p className="analysis-quality-summary" aria-label="待处理核对">{gaps.length ? `待处理：${gaps.join(' · ')}` : dimensionStates(quality?.status_dimensions).join(' · ')}</p>}
    {quality && accepted.length > 0 && <p className="analysis-note">{accepted.join('、')}已核对，其中含经理已接受的估算。</p>}
    <p className="analysis-note">计算成功和引用值一致分别记录；源数据核验只覆盖已声明的核验区域。专业判断仍需复核。</p>
    <details className="analysis-details"><summary>核对明细 · {itemCount} 项</summary>
      {quality?.checks && <dl className="analysis-check-summary" aria-label="分项核对状态">
        {qualityChecks.map(([key, label]) => {
          const result = quality.checks?.[key]?.status;
          return <div key={key}><dt>{label}</dt><dd>{stale ? '改稿后待复核' : checkStateText(result)}</dd></div>;
        })}
      </dl>}
      <EvidenceDimensionList dimensions={quality?.status_dimensions} stale={stale} caveat={false} />
    </details>
    {quality?.requirements?.scope_changed && <p role="status">本次分析范围已更新，这份文稿仍使用旧范围。</p>}
    {quality?.readability?.issues.length && state !== 'stale' ? <section className="analysis-details" aria-label="正文阅读建议">
      <h4>正文阅读建议</h4>
      <p className="analysis-note">可用“整理段落”预览分段，再将比较数据、完整公式和来源附注分别组织。</p>
      <ul>{quality.readability.issues.map((issue, index) => <li key={`${issue.code}-${issue.position ?? index}`}>{issue.message}</li>)}</ul>
    </section> : null}
    <EvidenceQuality key={taskId} taskId={taskId} dimensions={quality?.status_dimensions} issues={quality?.issues ?? []} stale={stale} showDimensions={false} />
    {!(quality?.issues?.length) && <p className="analysis-note">{state === 'passed' ? '当前文稿数字、单位和引用未发现问题。' : '检查只提示风险，不会阻止你保存经理判断。'}</p>}
    {facts.length > 0 && <details className="analysis-details"><summary>可引用事实 · {facts.length} 条</summary>
      <div className="analysis-fact-list">{facts.map((fact) => <article key={fact.id} className="analysis-fact-card" aria-label={`事实 ${fact.id}`}>
        <p><strong>{factLabel(fact)}</strong>{citedFactIds.includes(fact.id) ? <span className="analysis-note"> · 已引用</span> : null}</p>
        <p className="analysis-note">计算结果第 {Number(fact.row ?? 0) + 1} 行{fact.column ? ` · ${fact.column}` : ''}{fact.scope ? ` · ${scopeSummary(fact.scope)}` : ''}</p>
        <Button variant="outline" type="button" disabled={busy} onClick={() => onOpenLocator(fact)}>打开原文定位</Button>
        {fact.row != null && <Button variant="outline" type="button" disabled={busy} onClick={() => onOpenFact(fact)}>下钻此事实来源</Button>}
        {locatorNotice[fact.id] ? <p className="analysis-note" role="status">{locatorNotice[fact.id]}</p> : null}
        {locatorPdf?.factId === fact.id ? <PdfComparison dataUrl={locatorPdf.dataUrl} page={locatorPdf.page} /> : null}
        {factDetails[fact.id] && <FactDrilldown detail={factDetails[fact.id]} />}
      </article>)}</div></details>}
    {Boolean(quality?.coverage) && <details className="analysis-details"><summary>高级：检查覆盖明细</summary><pre className="analysis-source-text">{JSON.stringify(quality?.coverage, null, 2)}</pre></details>}
  </section>;
}

function FactDrilldown({ detail }: { detail: FinanceDrilldown }) {
  const columns = Array.from(new Set(detail.rows.flatMap((row) => Object.keys(row.data ?? {})))).map((name) => ({ name, type: 'VARCHAR' }));
  return <div className="analysis-drilldown-result"><p className="analysis-note">来源：{detail.message} · {detail.total} 行{detail.has_more ? ' · 仍有更多' : ''}</p>
    {columns.length > 0 && <Table columns={columns} rows={detail.rows.map((row) => row.data)} caption="事实来源行" />}
    {detail.rows.map((row, index) => <details className="analysis-details" key={index}><summary>来源 {index + 1} · {textValue(row.source)}</summary>
      <p>凭证明细：{row.voucher_detail_available ? '可用' : '不可用'}</p>
      <pre className="analysis-source-text">{JSON.stringify(row.data, null, 2)}</pre>
      <TechnicalInfo rows={[['来源摘要', row.source_hash]]} /></details>)}
  </div>;
}
