import type { AnalysisDraft, AnalysisRevision, AnalysisRun } from '../../bridge.js';

export type RunPresentationRole = 'business' | 'activity' | 'failure';

export type BusinessResultSelection = {
  primary?: AnalysisRun;
  reason: 'draft_reference' | 'latest_business' | 'latest_success' | 'latest_failure' | 'none';
  businessRuns: AnalysisRun[];
  activityRuns: AnalysisRun[];
  failedRuns: AnalysisRun[];
};

export type FieldSemantics = 'amount' | 'ratio' | 'ratio_pct' | 'ratio_delta' | 'text';
export type RowBasisKind = 'source' | 'direct' | 'calculation' | 'estimate' | 'judgment' | 'unknown';

export type DisplayColumn = { name: string; type?: string; label: string; semantics: FieldSemantics };
type CanonicalMeasure = 'actual' | 'budget' | 'estimated_budget' | 'variance' | 'rate' | 'rate_pct';
type ParsedWideColumn = { name: string; metric?: string; measure: CanonicalMeasure; period: string; order: number };

const explicitBusinessRoles = new Set(['business', 'business_result', 'calculation', 'analysis_result']);
const explicitActivityRoles = new Set(['probe', 'preanalysis', 'draft_support', 'audit_check', 'read', 'inspection', 'activity', 'technical', 'trace', 'debug', 'empty']);
const successStatuses = new Set(['succeeded', 'success']);
const hiddenFields = new Set(['source_rows', 'excluded_source_rows', 'detail_rows']);
const amountFieldLabels: Record<string, string> = {
  actual: '实际',
  budget: '预算',
  baseline: '基准',
  same_period_budget: '同期预算',
  variance: '差异',
  difference: '差异',
  amount_change: '科目增减',
  profit_impact: '利润影响',
  contribution: '差异贡献',
};
const ratioFieldLabels: Record<string, string> = {
  attainment: '达成率',
  attainment_rate: '达成率',
  attainment_ratio: '达成率',
  budget_attainment: '达成率',
  budget_attainment_rate: '达成率',
  budget_completion: '预算完成率',
  budget_completion_rate: '预算完成率',
  completion: '完成率',
  completion_rate: '完成率',
  completion_ratio: '完成率',
  achievement: '达成率',
  achievement_rate: '达成率',
  achievement_ratio: '达成率',
  actual_budget_rate: '实际/预算',
  actual_budget_ratio: '实际/预算',
  actual_to_budget: '实际/预算',
  ratio: '差异率',
  rate: '比例',
  ratio_delta: '比例变化',
  attainment_delta: '达成率变化',
};
const ratioPctFieldLabels: Record<string, string> = {
  attainment_pct: '达成率',
};
const ratioDeltaFieldLabels: Record<string, string> = {
  ratio_delta: '比例变化',
  attainment_delta: '达成率变化',
};
const moneyUnitSegments = new Set(['万元', '元', '亿元', '千元', '百万元']);
const moneyTokens = new Set(['amount', 'revenue', 'cost', 'expense', 'profit', 'cash', 'budget', 'actual', 'variance', 'sales', 'income']);
const textFieldLabels: Record<string, string> = {
  metric: '指标',
  metric_key: '指标',
  business_key: '业务键',
  result_key: '结果键',
  period: '期间',
  granularity: '粒度',
  organization: '组织',
  organization_id: '组织',
  scenario: '情景',
  source: '来源',
  source_note: '来源说明',
  '来源': '来源',
  '口径与来源': '来源',
  '估算方法': '估算方法',
  '区域': '区域',
  '指标': '指标',
  '单位': '单位',
  note: '说明',
  basis: '依据',
  row_basis: '依据',
  validation_basis: '依据',
};
const metricLabels: Record<string, string> = {
  revenue: '收入',
  operating_profit: '营业利润',
  profit: '利润',
  gross_profit: '毛利',
  period_expense: '期间费用',
  credit_impairment_loss: '信用减值损失',
  asset_impairment_loss: '资产减值损失',
  impairment_loss_total: '减值损失合计',
  other_income_and_gains_4items: '其他损益四项',
  operating_profit_excl_other: '剔除其他损益经营利润',
  operating_profit_excluding_other: '剔除其他损益经营利润',
  operating_profit_excl_other_gains: '剔除其他损益经营利润',
  other_gains: '其他收益',
  expense: '费用',
  cost: '成本',
  '营业收入': '营业收入',
  '收入': '收入',
  '经营利润': '经营利润',
  '营业利润': '营业利润',
};
const basisLabels: Record<RowBasisKind, string> = {
  source: '来源',
  direct: '直接取数',
  calculation: '计算',
  estimate: '估算',
  judgment: '专业判断',
  unknown: '未知',
};
const sourceBasisValues = new Set(['source', 'source_fact', 'source_refresh_batch', 'external', 'external_reference', '来源']);
const directBasisValues = new Set(['direct', 'direct_source', 'raw_source', 'actual_source', '直接取数']);
const calculationBasisValues = new Set(['calculation', 'computed', 'formula', 'derived', 'saved_draft_version', '计算']);
const estimateBasisValues = new Set(['estimate', 'estimated', 'estimation', 'user_assumption', 'assumption', '估算']);
const judgmentBasisValues = new Set(['judgment', 'professional_judgment', 'manager_judgment', '专业判断']);
const basisFields = ['basis', 'row_basis', 'validation_basis', 'source_basis', 'value_basis', 'evidence_basis'];

export function isSuccessfulRun(run: AnalysisRun): boolean {
  return successStatuses.has(run.execution_status);
}

function explicitRole(run: AnalysisRun): string {
  const row = run as AnalysisRun & { result_role?: unknown; run_role?: unknown; activity_role?: unknown };
  const result = run.result as (NonNullable<AnalysisRun['result']> & { role?: unknown; result_role?: unknown }) | undefined;
  return String(row.result_role ?? row.run_role ?? row.activity_role ?? result?.result_role ?? result?.role ?? '').toLowerCase();
}

function hasRows(run: AnalysisRun): boolean {
  return Boolean(run.result && run.result.rows.length > 0);
}

export function runPresentationRole(run: AnalysisRun): RunPresentationRole {
  if (!isSuccessfulRun(run)) return 'failure';
  const role = explicitRole(run);
  if (explicitBusinessRoles.has(role)) return 'business';
  if (explicitActivityRoles.has(role)) return 'activity';
  if (run.engine === 'finance' || run.engine === 'structured_aggregate') return hasRows(run) ? 'business' : 'activity';
  const names = new Set(run.result?.columns.map((column) => column.name.toLowerCase()) ?? []);
  const declaredBusinessFields = ['actual', 'same_period_budget', 'budget', 'baseline', 'variance', 'attainment_rate', 'attainment', 'budget_attainment', 'completion_rate', 'metric_key', 'period'];
  if (hasRows(run) && declaredBusinessFields.some((name) => names.has(name))) return 'business';
  if (hasRows(run) && (run.outputs?.length || run.output_hash)) return 'business';
  return 'activity';
}

function newest<T extends { created_at: string }>(items: T[]): T | undefined {
  return [...items].sort((left, right) => left.created_at.localeCompare(right.created_at)).at(-1);
}

export function selectBusinessResult(analysis: AnalysisRevision, runs: AnalysisRun[], drafts: AnalysisDraft[] = []): BusinessResultSelection {
  const byAnalysis = runs.filter((run) => run.analysis_id === analysis.id);
  const businessRuns = byAnalysis.filter((run) => runPresentationRole(run) === 'business');
  const activityRuns = byAnalysis.filter((run) => runPresentationRole(run) === 'activity');
  const failedRuns = byAnalysis.filter((run) => runPresentationRole(run) === 'failure');
  const latestDraftRunIds = [...drafts].reverse().flatMap((draft) => draft.run_ids ?? []);
  const draftReferenced = latestDraftRunIds.map((id) => businessRuns.find((run) => run.id === id)).find(Boolean);
  if (draftReferenced) return { primary: draftReferenced, reason: 'draft_reference', businessRuns, activityRuns, failedRuns };
  const latestBusiness = newest(businessRuns);
  if (latestBusiness) return { primary: latestBusiness, reason: 'latest_business', businessRuns, activityRuns, failedRuns };
  const latestSuccess = newest(byAnalysis.filter(isSuccessfulRun));
  if (latestSuccess) return { primary: latestSuccess, reason: 'latest_success', businessRuns, activityRuns, failedRuns };
  const latestFailure = newest(failedRuns);
  return { primary: latestFailure, reason: latestFailure ? 'latest_failure' : 'none', businessRuns, activityRuns, failedRuns };
}

function hasMoneyUnitSegment(key: string): boolean {
  return key.split(/[_\-\s/]+/).some((segment) => moneyUnitSegments.has(segment));
}

// Same rule as the backend: 汇率_影响_万元 / revenue_last_30_days name money, so a 率 driver in the name is not a ratio.
function namesMoney(key: string): boolean {
  return hasMoneyUnitSegment(key) || key.split(/[^a-z0-9]+/).some((token) => moneyTokens.has(token));
}

function isKnownRatioField(key: string): boolean {
  if (key in ratioFieldLabels || key in ratioPctFieldLabels || /达成率|完成率|比例|率$/.test(key)) return true;
  return /毛利率|收缴率|率_/.test(key) && !namesMoney(key);
}

export function columnSemantics(name: string, type?: string): FieldSemantics {
  const key = name.toLowerCase();
  if (key in ratioDeltaFieldLabels || key.endsWith('_pp') || key.endsWith('_point_delta')) return 'ratio_delta';
  if (key in ratioPctFieldLabels || key.endsWith('_pct')) return 'ratio_pct';
  if (isKnownRatioField(key)) return 'ratio';
  if (key in amountFieldLabels || /amount|budget|actual|variance|difference|cost|expense|profit|revenue|income|cash/i.test(key) || /实际|预算|差异|成本|费用|利润|收入|金额|损失/.test(key) || hasMoneyUnitSegment(key)) return 'amount';
  if (/^(DECIMAL|NUMERIC|HUGEINT|UHUGEINT|UBIGINT|BIGINT|UINTEGER|INTEGER|USMALLINT|SMALLINT|UTINYINT|TINYINT|FLOAT|DOUBLE|REAL|INT\d*)\b/i.test(type ?? '')) return 'amount';
  return 'text';
}

export function businessColumnLabel(name: string): string {
  const key = name.toLowerCase();
  return amountFieldLabels[key] ?? ratioFieldLabels[key] ?? ratioPctFieldLabels[key] ?? textFieldLabels[key] ?? name;
}

function decimalParts(value: unknown): { negative: boolean; digits: string; scale: number } | null {
  if (value == null || value === '') return null;
  const text = String(value).trim().replace(/,/g, '');
  const match = /^([+-])?(\d+)(?:\.(\d+))?$/.exec(text);
  if (!match) return null;
  const [, sign, integer, fraction = ''] = match;
  const digits = `${integer}${fraction}`.replace(/^0+(?=\d)/, '') || '0';
  return { negative: sign === '-', digits, scale: fraction.length };
}

function decimalToFixed(value: unknown, places: number, multiplier = 1): string {
  const parsed = decimalParts(value);
  if (!parsed) return value == null || value === '' ? '—' : String(value);
  const targetScale = places;
  const current = BigInt(parsed.digits) * BigInt(multiplier);
  const scaleDiff = parsed.scale - targetScale;
  let rounded: bigint;
  if (scaleDiff > 0) {
    const divisor = 10n ** BigInt(scaleDiff);
    rounded = current / divisor;
    if (current % divisor >= divisor / 2n) rounded += 1n;
  } else {
    rounded = current * (10n ** BigInt(-scaleDiff));
  }
  const sign = parsed.negative && rounded !== 0n ? '-' : '';
  const raw = rounded.toString().padStart(places + 1, '0');
  const integer = places ? raw.slice(0, -places) : raw;
  const fraction = places ? raw.slice(-places) : '';
  return `${sign}${integer.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}${places ? `.${fraction}` : ''}`;
}

export function formatBusinessValue(value: unknown, semantics: FieldSemantics): string {
  if (value == null || value === '') return '—';
  if (semantics === 'ratio') return `${decimalToFixed(value, 2, 100)}%`;
  if (semantics === 'ratio_pct') return `${decimalToFixed(value, 2)}%`;
  if (semantics === 'ratio_delta') return `${decimalToFixed(value, 2, 100)}个百分点`;
  if (semantics === 'amount') return decimalToFixed(value, 2);
  if (typeof value === 'object') return JSON.stringify(value);
  const metric = metricLabels[String(value)] ?? String(value);
  return metric;
}

export function formatBusinessCell(value: unknown, column: DisplayColumn, row: Record<string, unknown>): string {
  void row;
  return formatBusinessValue(value, column.semantics);
}

function sourceColumn(row: Record<string, unknown>): unknown {
  return row.source ?? row.source_note ?? row['来源'] ?? row['口径与来源'];
}

function unitColumn(row: Record<string, unknown>): unknown {
  return row.unit ?? row['单位'];
}

function regionColumn(row: Record<string, unknown>): unknown {
  return row.organization ?? row.region ?? row['区域'];
}

function rowMetric(row: Record<string, unknown>): unknown {
  return row.metric ?? row.metric_key ?? row.business_key ?? row.result_key ?? row.item ?? row.name ?? row['指标'];
}

function rowPeriod(row: Record<string, unknown>): unknown {
  return row.period ?? row['期间'];
}

function preferredMetricLabel(value: unknown): string {
  if (value == null || value === '') return '结果';
  return metricLabels[String(value)] ?? String(value);
}

function matchMeasure(parts: string[]): { index: number; length: number; measure: CanonicalMeasure } | null {
  const aliases: [CanonicalMeasure, string[]][] = [
    ['estimated_budget', ['同期预算', '估算']],
    ['budget', ['同期预算']],
    ['budget', ['预算']],
    ['actual', ['实际']],
    ['variance', ['差异']],
    ['variance', ['实际减目标']],
    ['rate_pct', ['达成率', 'pct']],
    ['rate_pct', ['完成率', 'pct']],
    ['rate', ['达成率']],
    ['rate', ['完成率']],
  ];
  for (let index = 0; index < parts.length; index += 1) {
    for (const [measure, alias] of aliases) {
      if (alias.every((part, offset) => parts[index + offset] === part)) return { index, length: alias.length, measure };
    }
  }
  return null;
}

function parseWideColumn(name: string, order: number): ParsedWideColumn | null {
  if (!name.includes('_')) return null;
  const parts = name.split('_').filter(Boolean);
  const match = matchMeasure(parts);
  if (!match) return null;
  const metric = parts.slice(0, match.index).join('_');
  const period = parts.slice(match.index + match.length).join('_');
  if (!period && metric) return null;
  return { name, metric: metric || undefined, measure: match.measure, period, order };
}

function wideColumns(run: AnalysisRun): ParsedWideColumn[] {
  return (run.result?.columns ?? [])
    .map((column, order) => parseWideColumn(column.name, order))
    .filter((column): column is ParsedWideColumn => Boolean(column));
}

function hasWideBusinessShape(run: AnalysisRun): boolean {
  const parsed = wideColumns(run);
  if (!parsed.length) return false;
  const grouped = new Map<string, Set<CanonicalMeasure>>();
  for (const column of parsed) {
    const key = `${column.metric ?? ''}|${column.period}`;
    const measures = grouped.get(key) ?? new Set<CanonicalMeasure>();
    measures.add(column.measure);
    grouped.set(key, measures);
  }
  return [...grouped.values()].some((measures) => measures.has('actual') && (measures.has('budget') || measures.has('variance') || measures.has('rate')));
}

function canonicalBasis(row: Record<string, unknown>): string {
  const explicit = rowBasisLabel(row);
  if (explicit !== basisLabels.unknown) return explicit;
  return row['估算方法'] ? basisLabels.estimate : explicit;
}

function longScenarioMeasure(row: Record<string, unknown>): CanonicalMeasure | null {
  const scenario = String(row.scenario ?? row['情景'] ?? '').trim().toLowerCase();
  if (!scenario) return null;
  if (['actual', 'actual_ytd', 'actual_month', 'actual_period'].includes(scenario)) return 'actual';
  if (['budget', 'budget_ytd', 'budget_month', 'same_period_budget', 'baseline'].includes(scenario)) return 'budget';
  if (['estimated_budget', 'estimated_budget_ytd', 'estimated_budget_month'].includes(scenario)) return 'estimated_budget';
  if (['variance', 'variance_favorable', 'budget_variance', 'difference', 'amount_change', 'profit_impact', 'contribution'].includes(scenario)) return 'variance';
  if (['achievement_ratio', 'attainment_rate', 'attainment_ratio', 'completion_rate', 'actual_budget_ratio', 'actual_to_budget', 'ratio'].includes(scenario)) return 'rate';
  if (['achievement_pct', 'attainment_pct', 'completion_pct'].includes(scenario)) return 'rate_pct';
  return null;
}

function scenarioDetailLabel(measure: CanonicalMeasure): string {
  if (measure === 'actual') return '实际';
  if (measure === 'budget') return '同期预算';
  if (measure === 'estimated_budget') return '同期预算（估算）';
  if (measure === 'variance') return '差异';
  return '达成率';
}

function currencyColumn(row: Record<string, unknown>): unknown {
  return row.currency ?? row['币种'];
}

function isRatioMeasure(measure: CanonicalMeasure): boolean {
  return measure === 'rate' || measure === 'rate_pct';
}

function amountUnit(row: Record<string, unknown>): string {
  const unit = String(unitColumn(row) ?? '').trim();
  return unit === '比率' || unit === '%' ? '' : unit;
}

function amountCurrency(row: Record<string, unknown>): string {
  return String(currencyColumn(row) ?? '').trim();
}

function longScenarioBaseKey(row: Record<string, unknown>): string {
  return [rowMetric(row), rowPeriod(row), regionColumn(row)].map((value) => String(value ?? '')).join('|');
}

type LongScenarioGroup = {
  order: number;
  metric: string;
  region?: unknown;
  period?: unknown;
  unit?: unknown;
  basis: string;
  values: Partial<Record<CanonicalMeasure, unknown>>;
  sources: string[];
};

function safeLongScenarioRows(run: AnalysisRun): Record<string, unknown>[] | null {
  const names = new Set(run.result?.columns.map((column) => column.name.toLowerCase()) ?? []);
  if (!names.has('scenario') || !names.has('value')) return null;
  if (!names.has('metric_key') && !names.has('metric') && !names.has('指标')) return null;

  const buckets = new Map<string, { rows: { order: number; row: Record<string, unknown>; measure: CanonicalMeasure }[]; units: Set<string>; currencies: Set<string> }>();
  for (const [order, row] of (run.result?.rows ?? []).entries()) {
    const measure = longScenarioMeasure(row);
    if (!measure) continue;
    const key = longScenarioBaseKey(row);
    const bucket = buckets.get(key) ?? { rows: [], units: new Set<string>(), currencies: new Set<string>() };
    bucket.rows.push({ order, row, measure });
    if (!isRatioMeasure(measure)) {
      const unit = amountUnit(row);
      const currency = amountCurrency(row);
      if (unit) bucket.units.add(unit);
      if (currency) bucket.currencies.add(currency);
    }
    buckets.set(key, bucket);
  }

  const output: LongScenarioGroup[] = [];
  for (const bucket of buckets.values()) {
    if (bucket.units.size > 1 || bucket.currencies.size > 1) return null;
    const group: LongScenarioGroup = {
      order: Math.min(...bucket.rows.map((item) => item.order)),
      metric: preferredMetricLabel(rowMetric(bucket.rows[0].row)),
      region: regionColumn(bucket.rows[0].row),
      period: rowPeriod(bucket.rows[0].row),
      unit: [...bucket.units][0] || undefined,
      basis: basisLabels.calculation,
      values: {},
      sources: [],
    };
    const seen = new Set<CanonicalMeasure>();
    for (const { row, measure } of bucket.rows.sort((left, right) => left.order - right.order)) {
      if (seen.has(measure)) return null;
      seen.add(measure);
      group.values[measure] = row.value ?? row['值'];
      if (measure === 'estimated_budget') group.basis = basisLabels.estimate;
      const source = sourceColumn(row);
      const note = row.note ?? row['说明'];
      if (source != null && source !== '') {
        const detail = [source, note].filter((value) => value != null && value !== '').join('；');
        group.sources.push(`${scenarioDetailLabel(measure)}：${detail}`);
      }
    }
    output.push(group);
  }

  const business = output
    .sort((left, right) => left.order - right.order)
    .filter((group) => group.values.actual != null && (
      group.values.budget != null
      || group.values.estimated_budget != null
      || group.values.variance != null
      || group.values.rate != null
      || group.values.rate_pct != null
    ))
    .map((group) => ({
      metric: group.metric,
      ...(group.region != null && group.region !== '' ? { region: group.region } : {}),
      period: group.period,
      actual: group.values.actual,
      same_period_budget: group.values.budget ?? group.values.estimated_budget,
      ...(group.values.budget != null && group.values.estimated_budget != null ? { estimated_same_period_budget: group.values.estimated_budget } : {}),
      variance: group.values.variance,
      attainment_rate: group.values.rate,
      ...(group.values.rate_pct != null ? { attainment_pct: group.values.rate_pct } : {}),
      unit: group.unit,
      basis: group.basis,
      source: Array.from(new Set(group.sources)).join('；'),
    }));
  return business.length ? business : null;
}

function hasLongScenarioBusinessShape(run: AnalysisRun): boolean {
  return safeLongScenarioRows(run) !== null;
}

function longScenarioRows(run: AnalysisRun): Record<string, unknown>[] {
  return safeLongScenarioRows(run) ?? run.result?.rows ?? [];
}

function hasBusinessTableShape(run: AnalysisRun): boolean {
  return hasWideBusinessShape(run) || hasLongScenarioBusinessShape(run);
}

export function businessRows(run: AnalysisRun): Record<string, unknown>[] {
  if (run.result?.rows.some((row) => 'actual' in row || 'same_period_budget' in row || 'attainment_rate' in row)) return run.result.rows;
  if (hasLongScenarioBusinessShape(run)) return longScenarioRows(run);
  if (!hasWideBusinessShape(run)) return run.result?.rows ?? [];
  const columns = wideColumns(run);
  const output: Record<string, unknown>[] = [];
  for (const sourceRow of run.result?.rows ?? []) {
    const groups = new Map<string, { metric: string; period: string; order: number; values: Partial<Record<CanonicalMeasure, unknown>> }>();
    for (const column of columns) {
      const metric = preferredMetricLabel(column.metric ?? rowMetric(sourceRow));
      const period = column.period || String(rowPeriod(sourceRow) ?? '');
      const key = `${metric}|${period}`;
      const group = groups.get(key) ?? { metric, period, order: column.order, values: {} };
      group.order = Math.min(group.order, column.order);
      group.values[column.measure] = sourceRow[column.name];
      groups.set(key, group);
    }
    for (const group of [...groups.values()].sort((left, right) => left.order - right.order)) {
      if (group.values.actual == null || (!('budget' in group.values) && !('variance' in group.values) && !('rate' in group.values))) continue;
      output.push({
        metric: group.metric,
        ...(regionColumn(sourceRow) != null && regionColumn(sourceRow) !== '' ? { region: regionColumn(sourceRow) } : {}),
        period: group.period,
        actual: group.values.actual,
        same_period_budget: group.values.budget ?? group.values.estimated_budget,
        ...('budget' in group.values && 'estimated_budget' in group.values ? { estimated_same_period_budget: group.values.estimated_budget } : {}),
        variance: group.values.variance,
        attainment_rate: group.values.rate,
        ...('rate_pct' in group.values ? { attainment_pct: group.values.rate_pct } : {}),
        unit: unitColumn(sourceRow),
        basis: canonicalBasis(sourceRow),
        source: sourceColumn(sourceRow),
      });
    }
  }
  return output;
}

function uniqueColumns(columns: DisplayColumn[]): DisplayColumn[] {
  const seen = new Map<string, number>();
  return columns.map((column) => {
    const count = seen.get(column.label) ?? 0;
    seen.set(column.label, count + 1);
    if (count === 0) return column;
    const fallback = businessColumnLabel(column.name) === column.label ? column.name : `${column.label}${count + 1}`;
    let label = `${column.label}（${fallback}）`;
    while (seen.has(label)) label = `${column.label}（${fallback}-${seen.size}）`;
    seen.set(label, 1);
    return { ...column, label };
  });
}

function hasRowBasis(run: AnalysisRun): boolean {
  const names = new Set(run.result?.columns.map((column) => column.name.toLowerCase()) ?? []);
  if (basisFields.some((field) => names.has(field))) return false;
  if (hasBusinessTableShape(run)) return false;
  return Boolean(run.result?.rows?.length);
}

export function displayColumns(run: AnalysisRun): DisplayColumn[] {
  if (hasBusinessTableShape(run)) {
    const rows = businessRows(run);
    const hasRegion = rows.some((row) => row.region != null && row.region !== '');
    const hasEstimatedBudget = rows.some((row) => row.estimated_same_period_budget != null && row.estimated_same_period_budget !== '');
    const hasPctRate = rows.some((row) => row.attainment_pct != null && row.attainment_pct !== '');
    return [
      { name: 'metric', type: 'VARCHAR', label: '指标', semantics: 'text' },
      ...(hasRegion ? [{ name: 'region', type: 'VARCHAR', label: '区域', semantics: 'text' } satisfies DisplayColumn] : []),
      { name: 'period', type: 'VARCHAR', label: '期间', semantics: 'text' },
      { name: 'actual', type: 'DECIMAL', label: '实际', semantics: 'amount' },
      { name: 'same_period_budget', type: 'DECIMAL', label: '同期预算', semantics: 'amount' },
      ...(hasEstimatedBudget ? [{ name: 'estimated_same_period_budget', type: 'DECIMAL', label: '同期预算（估算）', semantics: 'amount' } satisfies DisplayColumn] : []),
      { name: 'variance', type: 'DECIMAL', label: '差异', semantics: 'amount' },
      { name: 'attainment_rate', type: 'DOUBLE', label: '达成率', semantics: 'ratio' },
      ...(hasPctRate ? [{ name: 'attainment_pct', type: 'DOUBLE', label: '达成率（pct）', semantics: 'ratio_pct' } satisfies DisplayColumn] : []),
      { name: 'unit', type: 'VARCHAR', label: '单位', semantics: 'text' },
      { name: 'basis', type: 'VARCHAR', label: '依据', semantics: 'text' },
      { name: 'source', type: 'VARCHAR', label: '来源', semantics: 'text' },
    ];
  }
  const base = (run.result?.columns ?? [])
    .filter((column) => !hiddenFields.has(column.name))
    .map((column) => ({ name: column.name, type: column.type, label: businessColumnLabel(column.name), semantics: columnSemantics(column.name, column.type) }));
  if (hasRowBasis(run)) base.push({ name: '__basis', type: 'VARCHAR', label: '依据', semantics: 'text' });
  return uniqueColumns(base);
}

export function rowBasisKind(row: Record<string, unknown>): RowBasisKind {
  const raw = basisFields.map((field) => row[field]).find((value) => value != null && value !== '');
  const value = String(raw ?? '').trim().toLowerCase();
  if (!value) return 'unknown';
  if (sourceBasisValues.has(value)) return 'source';
  if (directBasisValues.has(value)) return 'direct';
  if (calculationBasisValues.has(value)) return 'calculation';
  if (estimateBasisValues.has(value)) return 'estimate';
  if (judgmentBasisValues.has(value)) return 'judgment';
  return 'unknown';
}

export function rowBasisLabel(row: Record<string, unknown>): string {
  return basisLabels[rowBasisKind(row)];
}

export function displayRows(run: AnalysisRun): Record<string, string>[] {
  const columns = displayColumns(run);
  return businessRows(run).map((row) => {
    const output: Record<string, string> = {};
    for (const column of columns) {
      output[column.label] = column.name === '__basis' ? rowBasisLabel(row) : formatBusinessCell(row[column.name], column, row);
    }
    return output;
  });
}

export function periodOptions(run: AnalysisRun): string[] {
  return Array.from(new Set(businessRows(run).map((row) => row.period).filter((value) => value != null && value !== '').map(String)));
}

function rowIdentity(row: Record<string, unknown>): string {
  const explicit = row.metric_key ?? row.business_key ?? row.result_key;
  const scope = row.scope && typeof row.scope === 'object' ? JSON.stringify(row.scope) : '';
  return String(explicit ?? [row.metric, row.period, row.organization, row.scenario, scope].filter((value) => value != null && value !== '').join('|'));
}

export type RevisionValueChange = {
  identity: string;
  label: string;
  field: string;
  before: string;
  after: string;
};

export function compareBusinessRuns(current: AnalysisRun, previous?: AnalysisRun): RevisionValueChange[] {
  if (!previous?.result || !current.result) return [];
  const previousByIdentity = new Map(previous.result.rows.map((row) => [rowIdentity(row), row]));
  const fieldTypes = new Map([...previous.result.columns, ...current.result.columns].map((column) => [column.name, column.type]));
  const fields = new Set([...current.result.columns, ...previous.result.columns]
    .map((column) => column.name)
    .filter((name) => columnSemantics(name, fieldTypes.get(name)) !== 'text'));
  const changes: RevisionValueChange[] = [];
  for (const row of current.result.rows) {
    const identity = rowIdentity(row);
    if (!identity || !previousByIdentity.has(identity)) continue;
    const before = previousByIdentity.get(identity)!;
    for (const field of fields) {
      const semantics = columnSemantics(field, fieldTypes.get(field));
      const oldValue = formatBusinessValue(before[field], semantics);
      const newValue = formatBusinessValue(row[field], semantics);
      if (oldValue !== newValue) {
        changes.push({ identity, label: metricLabels[String(row.metric ?? row.metric_key ?? identity)] ?? String(row.metric ?? identity), field: businessColumnLabel(field), before: oldValue, after: newValue });
      }
    }
  }
  return changes;
}
