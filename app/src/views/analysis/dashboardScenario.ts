/**
 * The 回款情景 card's arithmetic (foundry/dashboards.py, kind ``scenario``): one entity's 本期 lines of a
 * collection-health run, and what follows when the manager moves its collection rate by hand. The lines are the run's;
 * every figure the card works out from them is a what-if, which is why such a card is never accepted.
 */
import type { AnalysisRun } from '../../bridge.js';
import { isCollectionHealthRun, type HealthRow } from './CollectionHealthView.js';
import { matchingRows } from './dashboard.js';

export type ScenarioBase = {
  entity: string;
  margin: HealthRow;
  expense: HealthRow;
  breakEven: HealthRow;
  gap: HealthRow;
  /** 近12个月营业收入, when the run has it: the year the cash lines are counted over. */
  revenue: HealthRow | null;
  /** The collection rate the run's gap was taken at, in percent: 生死线收缴率 + 距生死线. */
  current: number;
  /** Cash received includes output VAT; revenue does not (params.vat_factor). */
  vat: number;
  /** Fewer points than this over the line reads 贴近生死线 (params.gap_yellow_below, in points). */
  yellowBelow: number;
};

const finite = (text: unknown) => typeof text === 'string' && text.trim() !== '' && Number.isFinite(Number(text));

/** The lines a scenario card reads, or null when the run cannot carry one (the backend refuses the same). */
export function scenarioBase(run: AnalysisRun, match: Record<string, string>): ScenarioBase | null {
  if (!isCollectionHealthRun(run)) return null;
  const rows = matchingRows(run.result?.rows ?? [], match) as unknown as HealthRow[];
  if (new Set(rows.map((row) => row.entity)).size !== 1) return null;
  const line = (key: string) => {
    const found = rows.filter((row) => row.metric_key === key);
    return found.length === 1 && finite(found[0].value) ? found[0] : null;
  };
  const margin = line('gross_margin');
  const expense = line('expense_ratio');
  const breakEven = line('break_even_collection');
  const gap = line('collection_gap');
  if (!margin || !expense || !breakEven || !gap || breakEven.unit !== '%' || gap.unit !== '百分点') return null;
  const params = (run.result as { params?: Record<string, string> } | undefined)?.params ?? {};
  const param = (key: string, fallback: number) => (finite(params[key]) ? Number(params[key]) : fallback);
  return {
    entity: gap.entity, margin, expense, breakEven, gap, revenue: line('ttm_revenue'),
    current: Number(breakEven.value) + Number(gap.value),
    vat: param('vat_factor', 1.06),
    yellowBelow: param('gap_yellow_below', 0.03) * 100,
  };
}

export type ScenarioAt = {
  /** The collection rate moved to, in percent. */
  rate: number;
  /** Points over (or under) the break-even collection rate: also the cash operating margin, per 100 collected. */
  gap: number;
  level: 'red' | 'yellow' | 'green';
  /** A year's cash operating profit at that rate: the gap on the last twelve months' revenue. */
  profit: number | null;
  /** How much more (or less) a year brings in than at the run's own rate, VAT included. */
  collected: number | null;
};

/** What follows at collection rate ``rate``, with the run's own lines held as they are. */
export function scenarioAt(base: ScenarioBase, rate: number): ScenarioAt {
  const gap = rate - Number(base.breakEven.value);
  const revenue = base.revenue ? Number(base.revenue.value) : null;
  return {
    rate,
    gap,
    level: gap < 0 ? 'red' : gap < base.yellowBelow ? 'yellow' : 'green',
    profit: revenue === null ? null : (gap / 100) * revenue,
    collected: revenue === null ? null : ((rate - base.current) / 100) * revenue * base.vat,
  };
}
