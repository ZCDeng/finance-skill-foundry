import { useEffect, useMemo, useState } from 'react';
import type { AnalysisRun, ScriptConclusion } from '../../bridge.js';
import { Button } from '../../components/ui/button.js';
import { businessRows, cardNotes, columnSemantics, displayColumns, formatBusinessCell, formatBusinessValue, longRowColumns, otherLongRows, periodOptions, rowBasisLabel, rowPeriod, type DisplayColumn } from './businessResults.js';
import { assumptionSummary, Table } from './presentation.js';

/** How many sentences stand above the cards before the rest fold away. */
const shownConclusions = 3;

type Kpi = { title: string; period: string; unit: string; basis: string; estimated: boolean; estimatedBudget: string; actualLabel: string; budgetLabel: string; actual: string; budget: string; difference: string; rate: string; notes: string[] };

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
    period: row.period == null || row.period === '' ? '未声明期间' : String(row.period),
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
    rate: valueFor(row, columns, ['attainment_rate', 'attainment_pct', 'achievement_pct', 'completion_pct', 'attainment', 'attainment_ratio', 'budget_attainment', 'budget_attainment_rate', 'budget_completion', 'budget_completion_rate', 'completion_rate', 'completion', 'achievement_rate', 'achievement', 'actual_budget_rate', 'actual_budget_ratio', 'actual_to_budget', 'ratio']),
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

function ConclusionLine({ conclusion }: { conclusion: ScriptConclusion }) {
  return <div className="analysis-headline-line">
    <p className="analysis-headline-text">{conclusion.text}</p>
    <p className="analysis-note">依据：{conclusion.basis}</p>
  </div>;
}

export function BusinessResultView({ run, onSources }: { run: AnalysisRun; onSources?(): void }) {
  const periods = useMemo(() => periodOptions(run), [run]);
  const [period, setPeriod] = useState(periods[0] ?? '');
  useEffect(() => {
    setPeriod((current) => (current && periods.includes(current) ? current : periods[0] ?? ''));
  }, [run.id, periods]);
  const columns = useMemo(() => displayColumns(run), [run]);
  const sourceRows = useMemo(() => businessRows(run), [run]);
  const filteredRows = useMemo(() => (period ? sourceRows.filter((row) => String(rowPeriod(row) ?? '') === period) : sourceRows), [period, sourceRows]);
  const rows = useMemo(() => filteredRows.map((row) => {
    const output: Record<string, string> = {};
    for (const column of columns) {
      output[column.label] = column.name === '__basis' ? rowBasisLabel(row) : formatBusinessCell(row[column.name], column, row);
    }
    return output;
  }), [columns, filteredRows]);
  const kpis = useMemo(() => kpiRows(filteredRows).map((row) => kpiFor(row, columns)), [columns, filteredRows]);
  const conclusions = useMemo(() => periodConclusions(run, period), [run, period]);
  const otherRows = useMemo(() => otherLongRows(run), [run]);
  const otherColumns = useMemo(() => longRowColumns(run, otherRows), [run, otherRows]);
  // A row without a period belongs to every period tab rather than to none.
  const others = useMemo(() => otherRows.filter((row) => { const value = rowPeriod(row); return !period || value == null || value === '' || String(value) === period; }).map((row) => {
    const output: Record<string, string> = {};
    for (const column of otherColumns) output[column.label] = formatBusinessCell(row[column.name], column, row);
    return output;
  }), [otherColumns, otherRows, period]);
  return <section className="analysis-business-result" aria-label="业务结果">
    {periods.length > 1 ? <div className="analysis-period-tabs" role="tablist" aria-label="结果期间">
      {periods.map((item) => <Button key={item} variant={item === period ? 'default' : 'outline'} type="button" role="tab" aria-selected={item === period}
        onClick={() => setPeriod(item)}>{item}</Button>)}
    </div> : null}
    {/* The backend's own sentences, shown as written: the frontend does no arithmetic on them. */}
    {conclusions.length ? <section className="analysis-headline" aria-label="脚本结论">
      {conclusions.slice(0, shownConclusions).map((conclusion, index) => <ConclusionLine key={index} conclusion={conclusion} />)}
      {conclusions.length > shownConclusions ? <details className="analysis-details"><summary>其余 {conclusions.length - shownConclusions} 句结论</summary>
        {conclusions.slice(shownConclusions).map((conclusion, index) => <ConclusionLine key={index} conclusion={conclusion} />)}
      </details> : null}
    </section> : null}
    {kpis.length ? <div className="analysis-kpi-grid" aria-label="关键指标">
      {kpis.map((kpi, index) => <article key={`${kpi.title}:${kpi.period}:${index}`} className="analysis-kpi-card">
        <span>{kpi.title}</span>
        <strong aria-label={`${kpi.title}实际`}>{kpi.actual}</strong>
        {kpi.actualLabel ? <small className="analysis-kpi-source">{kpi.actualLabel}</small> : null}
        <small>{kpi.period} · {kpi.unit} · 依据：{kpi.basis}</small>
        <dl aria-label={`${kpi.title}指标明细`}>
          <div><dt>{kpi.estimated ? '预算（估算）' : '预算'}</dt><dd>{kpi.budget}</dd></div>
          {kpi.estimatedBudget ? <div><dt>预算（估算）</dt><dd>{kpi.estimatedBudget}</dd></div> : null}
          <div><dt>差异</dt><dd>{kpi.difference}</dd></div>
          <div><dt>达成率</dt><dd>{kpi.rate}</dd></div>
        </dl>
        {kpi.budgetLabel ? <small className="analysis-kpi-source">预算：{kpi.budgetLabel}</small> : null}
        {kpi.notes.length ? <small className="analysis-kpi-notes">{kpi.notes.join(' · ')}</small> : null}
      </article>)}
    </div> : null}
    {/* The run's own caveats stand next to the numbers they qualify, whatever words they use. */}
    {kpis.length > 0 && Boolean(run.assumptions?.length) && <p className="analysis-note" aria-label="本次计算的假设">本次计算的假设：{assumptionSummary(run.assumptions)}</p>}
    <div className="analysis-business-table">
      {rows.length > 0 || !others.length ? <Table key={`${run.id}:${period || 'all'}`} columns={columns.map((column) => ({ name: column.label, type: column.semantics === 'text' ? 'VARCHAR' : 'DECIMAL' }))}
        rows={rows} caption="业务结果" /> : null}
      {others.length > 0 && <Table key={`${run.id}:${period || 'all'}:others`} columns={otherColumns.map((column) => ({ name: column.label, type: column.semantics === 'text' ? 'VARCHAR' : 'DECIMAL' }))}
        rows={others} caption="其他结果" />}
    </div>
    <div className="analysis-actions">
      {onSources ? <Button variant="outline" type="button" onClick={onSources}>查看来源与口径</Button> : null}
      <details className="analysis-details"><summary>原始字段 · {run.result?.columns.length ?? 0} 列</summary>
        <Table key={`${run.id}:raw-business`} columns={run.result?.columns ?? []} rows={run.result?.rows ?? []} caption="原始计算结果" />
      </details>
    </div>
  </section>;
}
