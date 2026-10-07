import { Fragment, useEffect, useMemo, useState, type ReactNode } from 'react';
import { ChevronDown } from 'lucide-react';
import type { AnalysisRun, ScriptConclusion } from '../../bridge.js';
import { Button } from '../../components/ui/button.js';
import { Popover, PopoverContent, PopoverTrigger } from '../../components/ui/popover.js';
import { businessColumnLabel, businessRows, cardNotes, columnSemantics, displayColumns, formatBusinessCell, formatBusinessValue, formatDisplayRows, groupingColumn, labelCollisions, longRowColumns, otherLongRows, periodOptions, rowBasisLabel, rowPeriod, sourceFields, type DisplayColumn } from './businessResults.js';
import { assumptionSummary, Table, textValue } from './presentation.js';
import { DisclosureSummary } from '../../components/Disclosure.js';
import { TechnicalInfo, type TechnicalRow } from './TechnicalInfo.js';
import { formatPeriod } from '../../lib/period.js';

/** How many sentences stand above the cards before the rest fold away. */
const shownConclusions = 3;

/** A source in 其他结果 longer than this shows its first reference and a count, and opens to the rest. */
const inlineSourceChars = 24;

// Vite sets DEV; narrowed here so the app's tsconfig need not carry Vite's client types.
const devBuild = (import.meta as ImportMeta & { env?: { DEV?: boolean } }).env?.DEV === true;

type Kpi = { title: string; period: string; periodLabel: string; unit: string; basis: string; estimated: boolean; estimatedBudget: string; actualLabel: string; budgetLabel: string; actual: string; budget: string; difference: string; rate: string; rateLabel: string; notes: string[] };

/** Attainment fields in the order a card reads them; the first with a value fills the card's last line. */
const rateFields = ['attainment_rate', 'attainment_pct', 'achievement_pct', 'completion_pct', 'attainment', 'attainment_ratio', 'budget_attainment', 'budget_attainment_rate', 'budget_completion', 'budget_completion_rate', 'completion_rate', 'completion', 'achievement_rate', 'achievement', 'actual_budget_rate', 'actual_budget_ratio', 'actual_to_budget', 'ratio'];

/**
 * The rate field a card names: the one whose value it shows, or, when none has a value, the first the row carries,
 * so a ratio row without a figure still reads 差异率 —.
 */
function rateField(row: Record<string, unknown>): string | undefined {
  return rateFields.find((field) => field in row && row[field] != null && row[field] !== '') ?? rateFields.find((field) => field in row);
}

/** The rate line's label in the words of its field: ratio reads 差异率. Without one it stays 达成率. */
function rateLabel(field: string | undefined): string {
  if (!field) return '达成率';
  const label = businessColumnLabel(field);
  return label === field ? '达成率' : label;
}

/**
 * Each period tab in words. Two stored values that read alike (2026-08 and
 * 2026-08:2026-08) keep their stored values, so the tabs stay apart.
 */
function periodLabels(periods: string[]): Map<string, string> {
  const words = periods.map((item) => formatPeriod(item));
  return new Map(periods.map((item, index) => [item, words.indexOf(words[index]) !== words.lastIndexOf(words[index]) ? item : words[index]]));
}

function valueFor(row: Record<string, unknown>, columns: DisplayColumn[], names: string[], fallback = '—'): string {
  for (const name of names) {
    if (!(name in row)) continue;
    const value = row[name];
    if (value == null || value === '') continue;
    const column = columns.find((item) => item.name === name);
    const displayColumn = column ?? { name, label: name, semantics: columnSemantics(name, typeof value === 'number' ? 'DOUBLE' : undefined) };
    return formatBusinessCell(value, displayColumn, row);
  }
  return fallback;
}

function metricTitle(row: Record<string, unknown>): string {
  const metric = row.metric ?? row.metric_key ?? row.business_key ?? row.result_key ?? row.item ?? row.name ?? row['指标'];
  const title = metric == null || metric === '' ? '结果' : formatBusinessValue(metric, 'text');
  const region = row.region ?? row.organization ?? row['区域'];
  return region == null || region === '' ? title : `${title} · ${region}`;
}

function metricKey(row: Record<string, unknown>): string {
  return String(row.metric_key ?? row.business_key ?? row.result_key ?? row.metric ?? row.item ?? row.name ?? row['指标'] ?? '').toLowerCase();
}

function kpiPriority(row: Record<string, unknown>): number {
  const key = metricKey(row);
  if (key === 'revenue' || key === '收入' || key === '营业收入') return 0;
  if (key === 'operating_profit' || key === '营业利润' || key === 'profit' || key === '利润') return 1;
  if (key.includes('经营利润') && (key.includes('剔除') || key.includes('excl'))) return 2;
  return 10;
}

/**
 * Up to four cards, one per metric before any metric repeats: the first row of
 * each metric (usually the group total) says more than four regions of revenue.
 */
function kpiRows(rows: Record<string, unknown>[]): Record<string, unknown>[] {
  const ranked = rows
    .filter((row) => row.actual != null && row.actual !== '')
    .map((row, index) => ({ row, index, priority: kpiPriority(row) }))
    .sort((left, right) => left.priority - right.priority || left.index - right.index);
  const seen = new Set<string>();
  const first = ranked.filter((item) => !seen.has(metricKey(item.row)) && Boolean(seen.add(metricKey(item.row))));
  const rest = ranked.filter((item) => !first.includes(item));
  return [...first, ...rest].slice(0, 4).map((item) => item.row);
}

function kpiFor(row: Record<string, unknown>, columns: DisplayColumn[]): Kpi {
  return {
    title: metricTitle(row),
    period: row.period == null || row.period === '' ? '' : String(row.period),
    periodLabel: row.period == null || row.period === '' ? '未声明期间' : formatPeriod(row.period),
    unit: row.unit == null || row.unit === '' ? '未声明单位' : String(row.unit),
    basis: rowBasisLabel(row),
    // Only when the budget shown is itself the estimate; an approved budget beside an estimate stays 预算.
    estimated: row.same_period_budget_estimated === true,
    estimatedBudget: valueFor(row, columns, ['estimated_same_period_budget'], ''),
    // The source's own words for each side: they carry the 口径 and how a budget was made.
    actualLabel: typeof row.actual_label === 'string' ? row.actual_label : '',
    budgetLabel: typeof row.budget_label === 'string' ? row.budget_label : '',
    actual: valueFor(row, columns, ['actual']),
    budget: valueFor(row, columns, ['budget', 'baseline', 'same_period_budget']),
    difference: valueFor(row, columns, ['variance', 'difference', 'amount_change', 'profit_impact', 'contribution']),
    rate: valueFor(row, columns, rateFields),
    rateLabel: rateLabel(rateField(row)),
    notes: cardNotes(row),
  };
}

/** The sentences the backend concluded for this period's pairs; a pair without a period belongs to every tab. */
function periodConclusions(run: AnalysisRun, period: string): ScriptConclusion[] {
  const pairs = run.row_declarations?.pairs ?? [];
  return pairs
    .filter((pair) => !period || pair.period == null || pair.period === '' || String(pair.period) === period)
    .flatMap((pair) => (pair.conclusion ? [pair.conclusion] : []));
}

/**
 * One 其他结果 source: as written when short, else its first reference and how many there are, opening to the list.
 * The main table's sources are not split this way: there one source line can carry several figures' labels.
 */
function SourceRefs({ text, metric }: { text: unknown; metric: string }) {
  const full = textValue(text);
  if (text == null || text === '' || full === '—' || Array.from(full).length <= inlineSourceChars) return <>{full}</>;
  const parts = Array.from(new Set(full.split(/[；;]\s*/).map((part) => part.trim()).filter(Boolean)));
  return <Popover>
    <PopoverTrigger asChild>
      <button type="button" className="fnd-linkish analysis-source-refs" title={full}>
        <span className="analysis-source-refs__first">{parts[0] ?? full}</span>
        {parts.length > 1 ? <span className="analysis-source-refs__count">等 {parts.length} 条</span> : null}
        <ChevronDown size={14} strokeWidth={1.5} aria-hidden="true" />
      </button>
    </PopoverTrigger>
    <PopoverContent className="analysis-source-refs__panel" aria-label={`${metric}的来源单元格引用`}>
      <ol>{parts.map((part) => <li key={part}>{part}</li>)}</ol>
    </PopoverContent>
  </Popover>;
}

/** Tells the developer, never the manager, that a script wrote one name for two metrics. */
function warnCollisions(rows: Record<string, unknown>[]) {
  for (const collision of labelCollisions(rows)) {
    console.warn(`结果行重名：组织「${collision.organization || '未声明组织'}」期间「${collision.period || '未声明期间'}」的指标名「${collision.label}」对应 ${collision.keys.length} 个指标键（${collision.keys.join('、')}），页面已在名字后补键区分；请在 metric_label 写出对象。`);
  }
}

function ConclusionLine({ conclusion }: { conclusion: ScriptConclusion }) {
  return <div className="analysis-headline-line">
    <p className="analysis-headline-text">{conclusion.text}</p>
    <p className="analysis-note">依据：{conclusion.basis}</p>
  </div>;
}

export function BusinessResultView({ run, onSources, actions, technicalRows, diagnostics = [] }: {
  run: AnalysisRun; onSources?(): void;
  /** The run's next steps (整理成文稿 first). They follow the cards, or the tables when there are no cards. */
  actions?: ReactNode;
  /** Identifiers shown above the raw fields in 技术信息, such as the version's question. */
  technicalRows?: TechnicalRow[];
  /** The engine's own diagnostics, kept in the one 技术信息 fold with the raw fields. */
  diagnostics?: unknown[];
}) {
  const periods = useMemo(() => periodOptions(run), [run]);
  const tabLabels = useMemo(() => periodLabels(periods), [periods]);
  const [period, setPeriod] = useState(periods[0] ?? '');
  useEffect(() => {
    setPeriod((current) => (current && periods.includes(current) ? current : periods[0] ?? ''));
  }, [run.id, periods]);
  const columns = useMemo(() => displayColumns(run), [run]);
  const sourceRows = useMemo(() => businessRows(run), [run]);
  const filteredRows = useMemo(() => (period ? sourceRows.filter((row) => String(rowPeriod(row) ?? '') === period) : sourceRows), [period, sourceRows]);
  const rows = useMemo(() => formatDisplayRows(filteredRows, columns), [columns, filteredRows]);
  const kpis = useMemo(() => kpiRows(filteredRows).map((row) => kpiFor(row, columns)), [columns, filteredRows]);
  const conclusions = useMemo(() => periodConclusions(run, period), [run, period]);
  const otherRows = useMemo(() => otherLongRows(run), [run]);
  const otherColumns = useMemo(() => longRowColumns(run, otherRows), [run, otherRows]);
  // A row without a period belongs to every period tab rather than to none.
  const visibleOthers = useMemo(() => otherRows.filter((row) => { const value = rowPeriod(row); return !period || value == null || value === '' || String(value) === period; }), [otherRows, period]);
  const others = useMemo(() => formatDisplayRows(visibleOthers, otherColumns), [otherColumns, visibleOthers]);
  // 其他结果 groups by organization: its name heads each group once instead of filling a column.
  const otherGroup = useMemo(() => groupingColumn(otherColumns), [otherColumns]);
  useEffect(() => {
    if (!devBuild) return;
    warnCollisions(sourceRows);
    warnCollisions(otherRows);
  }, [sourceRows, otherRows]);
  const tableColumn = (column: DisplayColumn, sources = false) => {
    const metricLabel = column.name.toLowerCase() === 'metric_label';
    const source = sources && sourceFields.includes(column.name.toLowerCase());
    const metricColumn = otherColumns.find((item) => item.name.toLowerCase() === 'metric_label') ?? otherColumns[0];
    return {
      name: column.label,
      type: column.semantics === 'text' ? 'VARCHAR' : 'DECIMAL',
      ...(metricLabel ? { render: (value: unknown, row: Record<string, unknown>) => <span title={row.__metricKey ? `指标键 ${String(row.__metricKey)}` : undefined}>{textValue(value)}</span> } : {}),
      ...(source ? { render: (value: unknown, row: Record<string, unknown>) => <SourceRefs text={value} metric={metricColumn ? textValue(row[metricColumn.label]) : ''} /> } : {}),
    };
  };
  return <section className="analysis-business-result" aria-label="业务结果">
    {periods.length > 1 ? <div className="analysis-period-tabs" role="tablist" aria-label="结果期间">
      {periods.map((item) => <Button key={item} variant="outline" size="chip" type="button" role="tab" aria-selected={item === period}
        onClick={() => setPeriod(item)}>{tabLabels.get(item) ?? item}</Button>)}
    </div> : null}
    {/* The backend's own sentences, shown as written: the frontend does no arithmetic on them. */}
    {conclusions.length ? <section className="analysis-headline" aria-label="脚本结论">
      {conclusions.slice(0, shownConclusions).map((conclusion, index) => <ConclusionLine key={index} conclusion={conclusion} />)}
      {conclusions.length > shownConclusions ? <details className="analysis-details"><DisclosureSummary>其余 {conclusions.length - shownConclusions} 句结论</DisclosureSummary>
        {conclusions.slice(shownConclusions).map((conclusion, index) => <ConclusionLine key={index} conclusion={conclusion} />)}
      </details> : null}
    </section> : null}
    {kpis.length ? <div className="analysis-kpi-grid" aria-label="关键指标">
      {kpis.map((kpi, index) => <article key={`${kpi.title}:${kpi.period}:${index}`} className="analysis-kpi-card">
        <span className="analysis-kpi-title" title={kpi.title}>{kpi.title}</span>
        <strong aria-label={`${kpi.title}实际`}>{kpi.actual}</strong>
        {kpi.actualLabel ? <small className="analysis-kpi-source">{kpi.actualLabel}</small> : null}
        {/* Each part stays whole; the line breaks only at a separator. */}
        <small className="analysis-kpi-meta">{[kpi.periodLabel, kpi.unit, `依据：${kpi.basis}`].map((part, partIndex) => <Fragment key={partIndex}>{partIndex ? ' · ' : ''}<span>{part}</span></Fragment>)}
          {kpi.notes.map((note) => <Fragment key={note}>{' · '}<span className="analysis-kpi-note">{note}</span></Fragment>)}</small>
        <dl className="analysis-kpi-list" aria-label={`${kpi.title}指标明细`}>
          <div><dt>{kpi.estimated ? '预算（估算）' : '预算'}</dt><dd>{kpi.budget}</dd></div>
          {kpi.estimatedBudget ? <div><dt>预算（估算）</dt><dd>{kpi.estimatedBudget}</dd></div> : null}
          <div><dt>差异</dt><dd>{kpi.difference}</dd></div>
          <div><dt>{kpi.rateLabel}</dt><dd>{kpi.rate}</dd></div>
        </dl>
        {kpi.budgetLabel ? <small className="analysis-kpi-source">预算：{kpi.budgetLabel}</small> : null}
      </article>)}
    </div> : null}
    {kpis.length > 0 && actions}
    {/* The run's own caveats stand next to the numbers they qualify, whatever words they use. */}
    {kpis.length > 0 && Boolean(run.assumptions?.length) && <p className="analysis-note" aria-label="本次计算的假设">本次计算的假设：{assumptionSummary(run.assumptions)}</p>}
    <div className="analysis-business-table">
      {rows.length > 0 || !others.length ? <Table key={`${run.id}:${period || 'all'}`} columns={columns.map((column) => tableColumn(column))}
        rows={rows} caption="业务结果" scrollHint /> : null}
      {others.length > 0 && <Table key={`${run.id}:${period || 'all'}:others`} columns={otherColumns.filter((column) => column !== otherGroup).map((column) => tableColumn(column, true))}
        rows={others} caption="其他结果" groupBy={otherGroup?.label} groupFallback="未声明组织" scrollHint />}
    </div>
    {kpis.length === 0 && actions}
    {onSources ? <div className="analysis-actions"><Button variant="outline" type="button" onClick={onSources}>查看来源与范围</Button></div> : null}
    <TechnicalInfo rows={technicalRows}>
      <p className="analysis-note">原始字段 · {run.result?.columns.length ?? 0} 列</p>
      <Table key={`${run.id}:raw-business`} columns={run.result?.columns ?? []} rows={run.result?.rows ?? []} caption="原始计算结果" />
      {diagnostics.length > 0 && <><h4>原始诊断细节 · {diagnostics.length} 项</h4>
        {diagnostics.map((item, index) => <p key={index}>{textValue(item)}</p>)}</>}
    </TechnicalInfo>
  </section>;
}
