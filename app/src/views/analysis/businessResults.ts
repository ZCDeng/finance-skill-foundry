import type { AnalysisDraft, AnalysisRevision, AnalysisRun, PairMeasure, RowDeclaration, RowDeclarations } from '../../bridge.js';
import { formatPeriod } from '../../lib/period.js';

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
  // Wide P&L results name their columns by metric.
  revenue: '收入',
  cost: '成本',
  expense: '费用',
  profit: '利润',
  gross_profit: '毛利',
  operating_profit: '营业利润',
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
  value: '数值',
  metric_label: '指标说明',
  currency: '币种',
  unit: '单位',
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

/**
 * A label table's own entry for a key. The tables are plain objects, so a bare lookup of a script's own text
 * (「constructor」, 「toString」) would return what every object inherits rather than nothing.
 */
function ownLabel(table: Record<string, string>, key: string): string | undefined {
  return Object.hasOwn(table, key) ? table[key] : undefined;
}

/** A metric code's Chinese name (result_semantics.py RESULT_METRIC_LABELS), or undefined for any other text. */
function metricLabel(key: unknown): string | undefined {
  return ownLabel(metricLabels, String(key));
}

export function businessColumnLabel(name: string): string {
  const key = name.toLowerCase();
  return ownLabel(amountFieldLabels, key) ?? ownLabel(ratioFieldLabels, key) ?? ownLabel(ratioPctFieldLabels, key) ?? ownLabel(textFieldLabels, key) ?? name;
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
  if (semantics === 'ratio_delta') return `${decimalToFixed(value, 2, 100)} 个百分点`;
  if (semantics === 'amount') return decimalToFixed(value, 2);
  if (typeof value === 'object') return JSON.stringify(value);
  const metric = metricLabel(value) ?? String(value);
  return metric;
}

/**
 * One value as every part of the result area shows it, by its declared unit alone (KTD9): a fraction reads ×100
 * as a percentage, a percent as written with %, a 百分点 difference as written with 个百分点, an unmarked value as
 * written and said to be so. Without a table unit it keeps the semantics it was given.
 */
function formatUnitValue(value: unknown, kind: UnitKind | null | undefined, semantics: FieldSemantics = 'amount'): string {
  if (kind === 'points') return value == null || value === '' ? '—' : `${decimalToFixed(value, 2)} 个百分点`;
  if (kind === 'decimal') return formatBusinessValue(value, 'ratio');
  if (kind === 'percent') return formatBusinessValue(value, 'ratio_pct');
  if (kind === 'unmarked') return value == null || value === '' ? '—' : `${typeof value === 'object' ? JSON.stringify(value) : String(value)}（未标单位）`;
  return formatBusinessValue(value, kind === 'amount' ? 'amount' : semantics);
}

export function formatBusinessCell(value: unknown, column: DisplayColumn, row: Record<string, unknown>): string {
  // A row shown as it is keeps its estimate visible even when its label does not say so.
  // In a declared run the declaration says it, grain_basis included; its own words still count (KTD3).
  if (column.name === 'metric_label' && typeof value === 'string' && value && (row[declaredEstimateField] === true || declaresEstimate(row)) && !mentionsEstimate(value)) return `${value}（估算）`;
  // A period reads in words (2026 年 1–8 月); the stored value still filters the tabs and goes to the assistant.
  if (column.name.toLowerCase() === 'period' || column.name === '期间') return value == null || value === '' ? '—' : formatPeriod(value);
  // A long-form value column mixes amounts and ratios; the row's own unit says which, as its declaration read it.
  if (column.name === 'value') return formatUnitValue(value, rowUnitKind(row), column.semantics);
  // A ratio or percent row's value already reads 3.30%, so its unit says % rather than 比率 or pct, and a 百分点 row's
  // 个百分点. A row without a value, or with an amount or unmarked unit, keeps its unit as written.
  const unitName = column.name.toLowerCase();
  if ((unitName === 'unit' || unitName === '单位') && nonEmpty(row.value)) {
    const kind = rowUnitKind(row);
    if (kind === 'decimal' || kind === 'percent') return '%';
    if (kind === 'points') return '个百分点';
  }
  return formatBusinessValue(value, column.semantics);
}

/** How a long-form row's value reads: its declared unit kind in a declared run, else its own unit. */
function rowUnitKind(row: Record<string, unknown>): UnitKind | null {
  return declaredUnitField in row ? row[declaredUnitField] as UnitKind | null : unitKind(unitColumn(row));
}

function sourceColumn(row: Record<string, unknown>): unknown {
  return row.source ?? row.source_note ?? row['来源'] ?? row['口径与来源'];
}

// The row's unit as the backend reads it (result_semantics.py _unit, finance_explanations.py _row_unit): the first of
// unit, 单位 that is neither null nor empty, so 「unit: ''」 beside 「单位: '百分点'」 reads 百分点 everywhere.
function unitColumn(row: Record<string, unknown>): unknown {
  return ['unit', '单位'].map((field) => row[field]).find((value) => value != null && value !== '');
}

// Where a row names its organization, in order; organization_id is an identifier, not a name, and is read nowhere.
const regionFields = ['organization', 'region', '区域'];

function regionColumn(row: Record<string, unknown>): unknown {
  const field = regionFields.find((name) => row[name] != null);
  return field ? row[field] : undefined;
}

/** The column a table of long-form rows groups by: the organization, by the same fields regionColumn reads. */
export function groupingColumn(columns: DisplayColumn[]): DisplayColumn | undefined {
  for (const field of regionFields) {
    const column = columns.find((item) => item.name.toLowerCase() === field);
    if (column) return column;
  }
  return undefined;
}

function rowMetric(row: Record<string, unknown>): unknown {
  return row.metric ?? row.metric_key ?? row.business_key ?? row.result_key ?? row.item ?? row.name ?? row['指标'];
}

export function rowPeriod(row: Record<string, unknown>): unknown {
  return row.period ?? row['期间'];
}

function preferredMetricLabel(value: unknown): string {
  if (value == null || value === '') return '结果';
  return metricLabel(value) ?? String(value);
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

// A scenario that names its own period: actual_1_8 (months 1–8), budget_2026_08.
// Anything else after the word (actual_py_1_8, budget_bud_fy, variance_bud_le)
// is a different comparison and is left unpaired. A bare year (actual_2026) is
// left unpaired too: it cannot tell year-to-date from the full year.
const scenarioWithPeriod = /^(actual|budget|variance)_(\d{1,2}_\d{1,2}|\d{4}_\d{2})$/;
// The unit table (KTD9, result_semantics.py FRACTION_UNITS / PERCENT_UNITS / UNMARKED_UNITS / POINT_UNITS). 比率 and
// ratio hold a fraction (0.945 = 94.5%); %, pct and 百分比 a percent; 「-」 says no unit was marked; 百分点 a
// difference of two percentages as written (3.3 = 3.3 个百分点, never ×100). Only the unit converts a value; a name
// never does.
const fractionUnits = new Set(['比率', 'ratio']);
const ratioUnits = new Set([...fractionUnits, '%', 'pct', '百分比']);
const unmarkedUnits = new Set(['-']);
const pointUnits = new Set(['百分点']);

/** How a row's unit reads its value (result_semantics.py unit_kind); null for an amount unit or none. */
type UnitKind = 'amount' | 'decimal' | 'percent' | 'unmarked' | 'points';
function unitKind(unit: unknown): UnitKind | null {
  const text = String(unit ?? '').trim().toLowerCase();
  if (pointUnits.has(text)) return 'points';
  if (fractionUnits.has(text)) return 'decimal';
  if (ratioUnits.has(text)) return 'percent';
  if (unmarkedUnits.has(text)) return 'unmarked';
  return null;
}

function longScenarioMeasure(row: Record<string, unknown>): { measure: CanonicalMeasure; suffix: string; span?: string } | null {
  const scenario = String(row.scenario ?? row['情景'] ?? '').trim().toLowerCase();
  if (!scenario) return null;
  // A ytd or month ending is a period class: a year-to-date actual never pairs with a monthly budget.
  const span = scenario.endsWith('_ytd') ? 'ytd' : scenario.endsWith('_month') ? 'month' : '';
  if (['actual', 'actual_ytd', 'actual_month', 'actual_period'].includes(scenario)) return { measure: 'actual', suffix: '', span };
  if (['budget', 'budget_ytd', 'budget_month', 'same_period_budget', 'baseline'].includes(scenario)) return { measure: 'budget', suffix: '', span };
  if (['estimated_budget', 'estimated_budget_ytd', 'estimated_budget_month'].includes(scenario)) return { measure: 'estimated_budget', suffix: '', span };
  // variance_favorable is signed by effect on profit, not actual minus budget; it stays unpaired.
  if (['variance', 'budget_variance', 'difference', 'amount_change', 'profit_impact', 'contribution'].includes(scenario)) return { measure: 'variance', suffix: '' };
  if (['achievement_ratio', 'attainment_rate', 'attainment_ratio', 'completion_rate', 'actual_budget_ratio', 'actual_to_budget', 'ratio'].includes(scenario)) return { measure: 'rate', suffix: '' };
  if (['achievement_pct', 'attainment_pct', 'completion_pct'].includes(scenario)) return { measure: 'rate_pct', suffix: '' };
  const match = scenarioWithPeriod.exec(scenario);
  return match ? { measure: match[1] as CanonicalMeasure, suffix: match[2] } : null;
}

/**
 * Which comparison a long-form row fills, and for which metric. A variance or
 * 达成率 may be its own metric named for its base (revenue_variance with a
 * variance scenario; revenue_achievement_ratio in 比率, whose scenario word is
 * unreliable, so only its period suffix counts). Both signals must agree.
 */
function longScenarioEntry(row: Record<string, unknown>): { measure: CanonicalMeasure; suffix: string; span?: string; metric: string; unmarked?: boolean } | null {
  const scenario = longScenarioMeasure(row);
  if (!scenario) return null;
  const metric = String(rowMetric(row) ?? '');
  const kind = unitKind(unitColumn(row));
  // A difference of two percentages fills no comparison, as result_semantics.py _comparison reads it.
  if (kind === 'points') return null;
  // 「-」 states no unit: such a 达成率 is kept out of its comparison (unmarked), and an amount in it fills none.
  const unmarked = kind === 'unmarked';
  const ratioUnit = kind === 'decimal' || kind === 'percent';
  const percentUnit = kind === 'percent';
  const rate = /^(.+)_(?:achievement|attainment)_ratio$/.exec(metric);
  if (rate && (ratioUnit || unmarked)) return { measure: percentUnit ? 'rate_pct' : 'rate', suffix: scenario.suffix, metric: rate[1], unmarked };
  // The unit, not the scenario word, says whether a 达成率 is a fraction or already a percentage:
  // achievement_pct in 比率 is a fraction, achievement_ratio in % is already a percentage.
  if (isRatioMeasure(scenario.measure) && (ratioUnit || unmarked)) return { ...scenario, measure: percentUnit ? 'rate_pct' : 'rate', metric, unmarked };
  if (isRatioMeasure(scenario.measure)) return { ...scenario, metric };
  // An amount comparison in a ratio unit (or none marked) would sit beside amounts as if it were one.
  if (ratioUnit || unmarked) return null;
  const variance = /^(.+)_variance$/.exec(metric);
  if (variance && scenario.measure === 'variance') return { ...scenario, metric: variance[1] };
  // Other metrics named for a base (revenue_budget_bud_fy, profit_actual_py) are their own figures.
  return { ...scenario, metric };
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

function longScenarioBaseKey(row: Record<string, unknown>, metric: string, suffix: string): string {
  return [metric, rowPeriod(row), regionColumn(row), suffix].map((value) => String(value ?? '')).join('|');
}

type LongScenarioGroup = {
  /** Whether the figure shown as 同期预算 is itself an estimate. */
  budgetEstimated?: boolean;
  /** Whether this comparison's 达成率 row was left out for an unmarked unit. */
  unitUnmarked?: boolean;
  order: number;
  metric: string;
  region?: unknown;
  period?: unknown;
  unit?: unknown;
  basis: string;
  values: Partial<Record<CanonicalMeasure, unknown>>;
  /** Each figure's own Chinese label, as the source wrote it. */
  labels: Partial<Record<CanonicalMeasure, string>>;
  sources: string[];
};

/**
 * Whether a row declares itself an estimate, by any of the signals this file
 * already honours: an estimate basis, a filled 估算方法, or 估算 in its label,
 * note or source. Errs toward saying so.
 */
function declaresEstimate(row: Record<string, unknown>): boolean {
  if (rowBasisKind(row) === 'estimate') return true;
  const method = String(row['估算方法'] ?? '').trim();
  if (method && !noMethod.has(method.toLowerCase())) return true;
  if (typeof row.scenario === 'string' && /estimat/i.test(row.scenario)) return true;
  return [row.metric_label, row.note, row['说明'], row.source, row.source_note, row['来源'], row['口径与来源']]
    .some((value) => typeof value === 'string' && mentionsEstimate(value));
}

const noMethod = new Set(['无', '否', '-', '—', 'n/a', 'na', '不适用', 'none', 'null']);
// The words an estimate goes by in these files, and the negations that cancel one
// (非估算, 不含估算调整). An unknown wording errs toward 估算.
const estimateWords = /估算|推算|预估|估计|测算|estimat/gi;
const negations = ['非', '不含', '不是', '并非', '无', '未'];
export function mentionsEstimate(text: string): boolean {
  for (const match of text.matchAll(estimateWords)) {
    const before = text.slice(Math.max(0, match.index - 2), match.index);
    if (!negations.some((word) => before.endsWith(word))) return true;
  }
  return false;
}

/** Whether a long-form row is an estimate by its own declaration, for tables that show it as it is. */
export function isEstimateRow(row: Record<string, unknown>): boolean {
  return declaresEstimate(row);
}

function isScriptRun(run: AnalysisRun): boolean {
  return run.engine === 'python' || run.engine === 'shell';
}

function isLongFormat(run: AnalysisRun): boolean {
  const names = new Set(run.result?.columns.map((column) => column.name.toLowerCase()) ?? []);
  return names.has('scenario') && names.has('value') && (names.has('metric_key') || names.has('metric') || names.has('指标'));
}

type LongPairing = { business: Record<string, unknown>[]; used: Set<number> };

/** The run's declaration when it can pair: a declaration the backend paired (every one it serves today). */
function pairedDeclarations(run: AnalysisRun): RowDeclarations | null {
  const declarations = run.row_declarations;
  return declarations && Array.isArray(declarations.pairs) && Array.isArray(declarations.rows) ? declarations : null;
}

/**
 * The comparison rows a long-form table pairs into, and which source rows they used. A declared run pairs
 * strictly as its declaration does (R1); only a run saved without one is inferred here (R2), so declared and
 * inferred rows never meet in one card.
 */
function longScenarioPairing(run: AnalysisRun): LongPairing | null {
  if (pairings.has(run)) return pairings.get(run) ?? null;
  let pairing: LongPairing | null = null;
  if (isLongFormat(run)) {
    const declarations = pairedDeclarations(run);
    pairing = declarations ? declaredPairing(run, declarations) : inferredPairing(run);
  }
  pairings.set(run, pairing);
  return pairing;
}
// The cards, 其他结果 and the period tabs all read one run's pairing. A state read replaces run objects rather than
// editing them, so the pairing is kept per run object.
const pairings = new WeakMap<AnalysisRun, LongPairing | null>();

function nonEmpty(value: unknown): boolean {
  return value != null && value !== '';
}

/**
 * Cards from the backend's pairs. Every figure is the declared row's own value (a Decimal string, present even
 * past the stored preview); whether it is an estimate is the declaration's union (KTD3); a 达成率 reads by its
 * declared unit. The preview row adds only its source and note, when the preview holds it.
 */
function declaredPairing(run: AnalysisRun, declarations: RowDeclarations): LongPairing {
  const entries = new Map(declarations.rows.map((entry) => [entry.row, entry]));
  const preview = run.result?.rows ?? [];
  const olderRequirements = readsOlderRequirements(declarations);
  // A 达成率 the backend left out for an unmarked unit, by the comparison it would have filled.
  const comparisonKey = (metric: unknown, organization: unknown, periodKey: unknown) => [metric, organization, periodKey].map((part) => String(part ?? '')).join('|');
  const unmarked = new Set(declarations.rows.filter((entry) => entry.role === 'ratio' && entry.unit_kind === 'unmarked')
    .map((entry) => comparisonKey(entry.metric, entry.organization, entry.period_key)));
  const groups = (declarations.pairs ?? []).flatMap((pair) => {
    const members = (Object.entries(pair.members) as [PairMeasure, number][]).filter(([, index]) => entries.has(index)).sort((left, right) => left[1] - right[1]);
    const byMeasure = new Map<PairMeasure, RowDeclaration>(members.map(([measure, index]) => [measure, entries.get(index)!]));
    const entry = (measure: PairMeasure): RowDeclaration | undefined => byMeasure.get(measure);
    const value = (measure: PairMeasure): unknown => entry(measure)?.value ?? undefined;
    const label = (measure: PairMeasure): string | undefined => entry(measure)?.scope_label ?? undefined;
    if (!nonEmpty(value('actual'))) return [];
    // The budget shown is picked by value: an approved row with none leaves the estimate beside it as the budget.
    const approved = nonEmpty(value('budget'));
    const estimated = new Set<PairMeasure>([...(pair.estimate?.measures ?? []),
      ...members.filter(([measure, index]) => measure === 'estimated_budget' || entries.get(index)?.estimate).map(([measure]) => measure)]);
    const rate = (['rate', 'rate_pct'] as const).find((measure) => entry(measure));
    const rateKind = rate ? entry(rate)!.unit_kind : null;
    const rateField = rateKind === 'decimal' || (rateKind !== 'percent' && rate === 'rate') ? 'attainment_rate' : 'attainment_pct';
    const sources = members.map(([measure, index]) => {
      const row = preview[index];
      const detail = [label(measure) ?? row?.metric_label, row && sourceColumn(row), row && (row.note ?? row['说明'])].filter(nonEmpty).join('；');
      return detail ? `${scenarioDetailLabel(measure)}：${detail}` : '';
    }).filter(Boolean);
    return [{
      order: members[0][1],
      used: members.map(([, index]) => index),
      row: {
        metric: preferredMetricLabel(pair.metric),
        ...(nonEmpty(pair.organization) ? { region: pair.organization } : {}),
        period: pair.period,
        actual: value('actual'),
        same_period_budget: approved ? value('budget') : value('estimated_budget'),
        // Only when the budget shown is itself the estimate; an approved budget beside an estimate stays 预算.
        same_period_budget_estimated: approved ? estimated.has('budget') : nonEmpty(value('estimated_budget')),
        ...(label('actual') ? { actual_label: label('actual') } : {}),
        ...(label('budget') ?? label('estimated_budget') ? { budget_label: label('budget') ?? label('estimated_budget') } : {}),
        ...(approved && nonEmpty(value('estimated_budget')) ? { estimated_same_period_budget: value('estimated_budget') } : {}),
        variance: value('variance'),
        attainment_rate: rate && rateField === 'attainment_rate' ? value(rate) : undefined,
        ...(rate && rateField === 'attainment_pct' ? { attainment_pct: value(rate) } : {}),
        unit: pair.unit ?? undefined,
        basis: estimated.size ? basisLabels.estimate : basisLabels.calculation,
        source: Array.from(new Set(sources)).join('；'),
        // A pair the backend knows only from its scenarios is inferred there too.
        ...(pair.declared === false ? { inferred: true } : {}),
        ...(olderRequirements ? { requirements_outdated: true } : {}),
        ...(unmarked.has(comparisonKey(pair.metric, pair.organization, pair.period_key)) ? { unit_unmarked: true } : {}),
      },
    }];
  }).sort((left, right) => left.order - right.order);
  return { business: groups.map((group) => group.row), used: new Set(groups.flatMap((group) => group.used)) };
}

/**
 * Whether the declaration was read against an older requirements version than the task's current one (R4).
 * Versions compare by their verified semantic fingerprints, so a resave that changes nothing they mean (a renamed
 * item) says nothing; when either fingerprint could not be verified, a different version errs toward saying so.
 * A run pinned to no requirements has no older version to name.
 */
function readsOlderRequirements(declarations: RowDeclarations): boolean {
  const current = declarations.current_requirements;
  const pinned = declarations.requirements_id;
  if (!pinned || !current?.id || current.id === pinned) return false;
  const before = declarations.requirements_fingerprint;
  return !(before && current.fingerprint && before === current.fingerprint);
}

/** Today's inference, kept for script runs saved before declarations existed (and for SQL long forms). */
function inferredPairing(run: AnalysisRun): LongPairing | null {
  const buckets = new Map<string, { metric: string; rows: { order: number; row: Record<string, unknown>; measure: CanonicalMeasure }[]; units: Set<string>; currencies: Set<string>; spans: Set<string> }>();
  // The comparisons whose 达成率 row was left out for an unmarked unit (KTD9).
  const unmarked = new Set<string>();
  for (const [order, row] of (run.result?.rows ?? []).entries()) {
    const entry = longScenarioEntry(row);
    if (!entry) continue;
    const { measure } = entry;
    const key = longScenarioBaseKey(row, entry.metric, entry.suffix);
    if (entry.unmarked) { unmarked.add(key); continue; }
    const bucket = buckets.get(key) ?? { metric: entry.metric, rows: [], units: new Set<string>(), currencies: new Set<string>(), spans: new Set<string>() };
    bucket.rows.push({ order, row, measure });
    if (entry.span) bucket.spans.add(entry.span);
    if (!isRatioMeasure(measure)) {
      const unit = amountUnit(row);
      const currency = amountCurrency(row);
      if (unit) bucket.units.add(unit);
      if (currency) bucket.currencies.add(currency);
    }
    buckets.set(key, bucket);
  }

  const output: (LongScenarioGroup & { used: number[] })[] = [];
  for (const [key, bucket] of buckets) {
    if (bucket.units.size > 1 || bucket.currencies.size > 1) return null;
    // A year-to-date figure beside a monthly one (actual_ytd, budget_month): not one comparison.
    if (bucket.spans.size > 1) continue;
    const group: LongScenarioGroup & { used: number[] } = {
      unitUnmarked: unmarked.has(key),
      used: bucket.rows.map((item) => item.order),
      order: Math.min(...bucket.rows.map((item) => item.order)),
      metric: preferredMetricLabel(bucket.metric),
      region: regionColumn(bucket.rows[0].row),
      period: rowPeriod(bucket.rows[0].row),
      unit: [...bucket.units][0] || undefined,
      basis: basisLabels.calculation,
      values: {},
      labels: {},
      sources: [],
    };
    const seen = new Set<CanonicalMeasure>();
    const estimated = new Set<CanonicalMeasure>();
    let duplicate = false;
    for (const { row, measure } of bucket.rows.sort((left, right) => left.order - right.order)) {
      // Two rows for one comparison: this group cannot be read, but the others can.
      if (seen.has(measure)) { duplicate = true; break; }
      seen.add(measure);
      group.values[measure] = row.value ?? row['值'];
      if (typeof row.metric_label === 'string' && row.metric_label.trim()) group.labels[measure] = row.metric_label.trim();
      // Every figure in a group with an estimate is read against it, so the group's
      // basis says 估算; which budget is itself the estimate is kept per figure.
      if (measure === 'estimated_budget' || declaresEstimate(row)) {
        group.basis = basisLabels.estimate;
        estimated.add(measure);
      }
      // The row's own label goes with its source: it carries the 口径 (报告口径, 剔除其他收益类)
      // and how a figure was made (推算, 估算) that the paired columns cannot show.
      const source = sourceColumn(row);
      const note = row.note ?? row['说明'];
      const detail = [row.metric_label, source, note].filter((value) => value != null && value !== '').join('；');
      if (detail) group.sources.push(`${scenarioDetailLabel(measure)}：${detail}`);
    }
    if (duplicate) continue;
    group.budgetEstimated = group.values.budget != null ? estimated.has('budget') : group.values.estimated_budget != null;
    output.push(group);
  }

  const paired = output
    .sort((left, right) => left.order - right.order)
    .filter((group) => group.values.actual != null && (
      group.values.budget != null
      || group.values.estimated_budget != null
      || group.values.variance != null
      || group.values.rate != null
      || group.values.rate_pct != null
    ));
  const business = paired
    .map((group) => ({
      metric: group.metric,
      ...(group.region != null && group.region !== '' ? { region: group.region } : {}),
      period: group.period,
      actual: group.values.actual,
      same_period_budget: group.values.budget ?? group.values.estimated_budget,
      same_period_budget_estimated: group.budgetEstimated === true,
      ...(group.labels.actual ? { actual_label: group.labels.actual } : {}),
      ...(group.labels.budget ?? group.labels.estimated_budget ? { budget_label: group.labels.budget ?? group.labels.estimated_budget } : {}),
      ...(group.values.budget != null && group.values.estimated_budget != null ? { estimated_same_period_budget: group.values.estimated_budget } : {}),
      variance: group.values.variance,
      attainment_rate: group.values.rate,
      ...(group.values.rate_pct != null ? { attainment_pct: group.values.rate_pct } : {}),
      unit: group.unit,
      basis: group.basis,
      source: Array.from(new Set(group.sources)).join('；'),
      // Only a script's long form is paired by guesswork worth saying so; SQL, finance-engine and structured
      // results state their own structure (R2).
      ...(isScriptRun(run) ? { inferred: true } : {}),
      ...(group.unitUnmarked ? { unit_unmarked: true } : {}),
    }));
  return { business, used: new Set(paired.flatMap((group) => group.used)) };
}

/** The notes one card carries under its figures, in their fixed order; an estimate stays on the figure's own label. */
export function cardNotes(row: Record<string, unknown>): string[] {
  return [
    row.inferred === true ? '推断' : '',
    row.requirements_outdated === true ? '依据旧版需求' : '',
    row.unit_unmarked === true ? '未标单位' : '',
  ].filter(Boolean);
}

// Fields a declared run's preview rows carry for display only, never shown as columns.
const declaredUnitField = '__unit_kind';
const declaredEstimateField = '__estimate';

/**
 * A long-form run's preview rows as the tables show them: in a declared run each carries its declared unit
 * kind, so a 比率 row whose unit the table cannot read shows 未标单位 as the backend promised, and its
 * declared estimate. A run without a declaration gets its own rows back.
 */
function shownLongRows(run: AnalysisRun): Record<string, unknown>[] {
  const rows = run.result?.rows ?? [];
  const declarations = run.row_declarations;
  if (!declarations?.rows?.length || !isLongFormat(run)) return rows;
  const entries = new Map(declarations.rows.map((entry) => [entry.row, entry]));
  return rows.map((row, index) => {
    const entry = entries.get(index);
    return entry ? { ...row, [declaredUnitField]: entry.unit_kind, ...(entry.estimate ? { [declaredEstimateField]: true } : {}) } : row;
  });
}

function safeLongScenarioRows(run: AnalysisRun): Record<string, unknown>[] | null {
  const pairing = longScenarioPairing(run);
  return pairing?.business.length ? pairing.business : null;
}

/**
 * The long-form rows that did not pair into a comparison: receivables, full-year
 * budgets, ratios of their own. They stay on screen in their own table rather
 * than only in the raw fields. Empty when the table did not pair at all, since
 * the main table then shows every row.
 */
export function otherLongRows(run: AnalysisRun): Record<string, unknown>[] {
  const pairing = longScenarioPairing(run);
  if (!pairing?.business.length) return [];
  return shownLongRows(run).filter((_, index) => !pairing.used.has(index));
}

// The key columns a long form names its metric by (isLongFormat accepts any one of them).
const longKeyFields = ['metric_key', 'metric', '指标'];
const renminbi = new Set(['CNY', '人民币']);

/**
 * Columns for long-form rows shown as they are. When every row has a Chinese label it leads and the key columns go:
 * the key stays in 技术信息's raw table and on hover over the name, and formatDisplayRows adds it to a name two rows
 * share. The scenario goes too once label and key tell rows apart (this year and last year under one key keep it).
 * A currency column that only ever says 人民币 goes; any other currency, or more than one, stays.
 */
export function longRowColumns(run: AnalysisRun, rows: Record<string, unknown>[] = run.result?.rows ?? []): DisplayColumn[] {
  const columns = (run.result?.columns ?? []).filter((column) => !hiddenFields.has(column.name));
  const names = new Set(columns.map((column) => column.name.toLowerCase()));
  const distinct = (parts: (row: Record<string, unknown>) => unknown[]) => new Set(rows.map((row) => JSON.stringify(parts(row)))).size === rows.length;
  const labelled = names.has('metric_label') && rows.every((row) => typeof row.metric_label === 'string' && row.metric_label.trim() !== '');
  const hideScenario = labelled && distinct((row) => [row.metric_label, rowMetric(row), regionColumn(row), rowPeriod(row)]);
  // The key columns go only when every one of them says what rowMetric reads. A metric_key beside a different metric
  // would otherwise vanish while the collision check, which reads rowMetric alone, could not tell its rows apart.
  const keyColumns = columns.filter((column) => longKeyFields.includes(column.name.toLowerCase()));
  const keysAgree = keyColumns.every((column) => rows.every((row) => !nonEmpty(row[column.name]) || String(row[column.name]) === String(rowMetric(row) ?? '')));
  const hideKeys = labelled && keysAgree;
  const currencies = new Set(rows.map(currencyColumn).filter(nonEmpty).map((value) => String(value).trim().toUpperCase()));
  const hideCurrency = currencies.size === 1 && renminbi.has([...currencies][0]);
  const labelIndex = columns.findIndex((column) => column.name.toLowerCase() === 'metric_label');
  if (labelled && labelIndex >= 0) {
    const [label] = columns.splice(labelIndex, 1);
    columns.unshift(label);
  }
  return uniqueColumns(columns.flatMap((column): DisplayColumn[] => {
    const key = column.name.toLowerCase();
    if (hideScenario && key === 'scenario') return [];
    if (hideKeys && longKeyFields.includes(key)) return [];
    if (labelled && longKeyFields.includes(key)) return [{ name: column.name, type: 'VARCHAR', label: keyColumns.length > 1 ? `指标键（${column.name}）` : '指标键', semantics: 'text' }];
    if (hideCurrency && (key === 'currency' || key === '币种')) return [];
    if (key === 'metric_label' && labelled) return [{ name: column.name, type: 'VARCHAR', label: '指标', semantics: 'text' }];
    return [{ name: column.name, type: column.type, label: businessColumnLabel(column.name), semantics: key === 'value' ? 'amount' : columnSemantics(column.name, column.type) }];
  }));
}

function hasLongScenarioBusinessShape(run: AnalysisRun): boolean {
  return safeLongScenarioRows(run) !== null;
}

function longScenarioRows(run: AnalysisRun): Record<string, unknown>[] {
  return safeLongScenarioRows(run) ?? shownLongRows(run);
}

function hasBusinessTableShape(run: AnalysisRun): boolean {
  return hasWideBusinessShape(run) || hasLongScenarioBusinessShape(run);
}

export function businessRows(run: AnalysisRun): Record<string, unknown>[] {
  if (run.result?.rows.some((row) => 'actual' in row || 'same_period_budget' in row || 'attainment_rate' in row)) return run.result.rows;
  if (hasLongScenarioBusinessShape(run)) return longScenarioRows(run);
  if (!hasWideBusinessShape(run)) return shownLongRows(run);
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
        same_period_budget_estimated: !('budget' in group.values) && 'estimated_budget' in group.values,
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
  const base = isLongFormat(run) ? longRowColumns(run) : (run.result?.columns ?? [])
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

/**
 * Rows of one organization and period whose names read alike but whose metric keys differ: on screen, without the
 * key columns, nothing tells them apart. This is the contract the backend's label_ambiguous check (C') must keep,
 * field for field, and app/tests/fixtures/label-collisions.json is the sample both sides assert:
 * - Rows: long-form rows in no pair (其他结果 when the run pairs, every row of the main table when it does not).
 *   Paired rows carry no metric_label and never take part.
 * - Organization: the first of organization, region, 区域 that is not null, as a string ('' counts as a value);
 *   '' when all are null. organization_id is not read.
 * - Period: the stored period, else 期间, as written and not formatted; '' when null.
 * - Label: rows whose metric_label is not a string with text after trim take no part. The trimmed label reads as
 *   the table shows it: with 「（估算）」 after it when the row is an estimate (declared so, or by declaresEstimate's
 *   own signals) and the label does not already say so; otherwise a label that is a metricLabels key reads as its
 *   Chinese name. Labels compare after a final trim.
 * - Key: the first of METRIC_FIELDS (rowMetric's order) that is not null, as a string; the row's own key, never
 *   the base metric a pair reads it as (revenue_variance stays revenue_variance).
 * - A group with two or more distinct keys is a collision; one key under one name (this year and last year of one
 *   metric) is told apart by its scenario and is not. Groups and their keys keep first-appearance order.
 * - The backend warns by the estimates of the run's own declaration (its rows and pinned requirements version). An
 *   estimate the task's latest requirements add at read time marks the row here (__estimate) but does not recompute
 *   label_ambiguous, so the two sides can differ by a group then.
 */
export type LabelCollision = { organization: string; period: string; label: string; keys: string[]; rows: Record<string, unknown>[] };

const labelDisplayColumn: DisplayColumn = { name: 'metric_label', type: 'VARCHAR', label: '指标', semantics: 'text' };

export function labelCollisions(rows: Record<string, unknown>[]): LabelCollision[] {
  const groups = new Map<string, LabelCollision>();
  for (const row of rows) {
    if (typeof row.metric_label !== 'string' || !row.metric_label.trim()) continue;
    const organization = String(regionColumn(row) ?? '');
    const period = String(rowPeriod(row) ?? '');
    const label = formatBusinessCell(row.metric_label.trim(), labelDisplayColumn, row).trim();
    const id = JSON.stringify([organization, period, label]);
    const group = groups.get(id) ?? { organization, period, label, keys: [], rows: [] };
    const key = String(rowMetric(row) ?? '');
    if (!group.keys.includes(key)) group.keys.push(key);
    group.rows.push(row);
    groups.set(id, group);
  }
  return [...groups.values()].filter((group) => group.keys.length >= 2);
}

/** What a shared name gets after it: each key's Chinese name when every key has a distinct one, else the keys. */
function collisionSuffixes(collision: LabelCollision): Map<string, string> {
  const chinese = collision.keys.map(metricLabel);
  const useChinese = chinese.every(Boolean) && new Set(chinese).size === chinese.length;
  return new Map(collision.keys.map((key, index) => [key, (useChinese && chinese[index]) || key]));
}

/**
 * Rows as a result table shows them, keyed by column label. Where the key columns are not shown, a name that two
 * rows of one organization and period share gets what tells them apart after it. Each row also carries fields no
 * column shows: __metricKey for the hover over its name, and __group, its organization as stored.
 */
export function formatDisplayRows(rows: Record<string, unknown>[], columns: DisplayColumn[]): Record<string, string>[] {
  const names = new Set(columns.map((column) => column.name.toLowerCase()));
  const labelColumn = columns.find((column) => column.name.toLowerCase() === 'metric_label');
  const suffixes = new Map<Record<string, unknown>, string>();
  if (labelColumn && !longKeyFields.some((field) => names.has(field))) {
    for (const collision of labelCollisions(rows)) {
      const byKey = collisionSuffixes(collision);
      for (const row of collision.rows) suffixes.set(row, byKey.get(String(rowMetric(row) ?? '')) ?? '');
    }
  }
  return rows.map((row) => {
    const output: Record<string, string> = {};
    for (const column of columns) {
      output[column.label] = column.name === '__basis' ? rowBasisLabel(row) : formatBusinessCell(row[column.name], column, row);
    }
    const suffix = suffixes.get(row);
    if (labelColumn && suffix) output[labelColumn.label] = `${output[labelColumn.label]}（${suffix}）`;
    output.__metricKey = String(rowMetric(row) ?? '');
    // The organization as stored, for grouping: a formatted cell would turn a missing one into 「—」.
    output.__group = String(regionColumn(row) ?? '');
    return output;
  });
}

export function displayRows(run: AnalysisRun): Record<string, string>[] {
  return formatDisplayRows(businessRows(run), displayColumns(run));
}

export function periodOptions(run: AnalysisRun): string[] {
  return Array.from(new Set([...businessRows(run), ...otherLongRows(run)].map(rowPeriod).filter((value) => value != null && value !== '').map(String)));
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

/** comparedRows counts current rows lined up with a previous row by identity; resultRows is the larger result's row count. */
export type RevisionValueComparison = {
  changes: RevisionValueChange[];
  comparedRows: number;
  resultRows: number;
};

export function compareBusinessRuns(current: AnalysisRun, previous?: AnalysisRun): RevisionValueComparison {
  if (!previous?.result || !current.result) return { changes: [], comparedRows: 0, resultRows: 0 };
  const previousByIdentity = new Map(previous.result.rows.map((row) => [rowIdentity(row), row]));
  const fieldTypes = new Map([...previous.result.columns, ...current.result.columns].map((column) => [column.name, column.type]));
  const fields = new Set([...current.result.columns, ...previous.result.columns]
    .map((column) => column.name)
    .filter((name) => columnSemantics(name, fieldTypes.get(name)) !== 'text'));
  const changes: RevisionValueChange[] = [];
  let comparedRows = 0;
  for (const row of current.result.rows) {
    const identity = rowIdentity(row);
    if (!identity || !previousByIdentity.has(identity)) continue;
    comparedRows += 1;
    const before = previousByIdentity.get(identity)!;
    for (const field of fields) {
      const semantics = columnSemantics(field, fieldTypes.get(field));
      const oldValue = formatBusinessValue(before[field], semantics);
      const newValue = formatBusinessValue(row[field], semantics);
      if (oldValue !== newValue) {
        changes.push({ identity, label: metricLabel(row.metric ?? row.metric_key ?? identity) ?? String(row.metric ?? identity), field: businessColumnLabel(field), before: oldValue, after: newValue });
      }
    }
  }
  const resultRows = Math.max(current.result.rows.length, previous.result.rows.length, current.result.row_count ?? 0, previous.result.row_count ?? 0);
  return { changes, comparedRows, resultRows };
}
