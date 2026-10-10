/**
 * What each kind of 看板 card shows of the run it reads: the board draws these, and a 看板快照 carries the same
 * (dashboardSnapshot.ts), so a page and the board never differ on a figure.
 */
import type { AnalysisRun } from '../../bridge.js';
import type { RankItem } from '../../components/charts/RankBars.js';
import { groupDigits } from '../../lib/figures.js';
import { isCollectionHealthRun, type HealthRow } from './CollectionHealthView.js';
import { kpiFor } from './BusinessResultView.js';
import { profitBridges } from './RunPanel.js';
import { columnSemantics, displayColumns, formatBusinessCell, businessColumnLabel } from './businessResults.js';
import { matchingRows, splitDisplay, type DashboardCard } from './dashboard.js';
import { scenarioBase } from './dashboardScenario.js';

/** What a figure card shows of its row. */
export type FigureView = { subject: string; value: string; part: string; beside: [string, string][]; level: HealthRow['level']; levelLabel: string | null; row: Record<string, unknown>; facts: [string, string][] };

export function figureView(card: DashboardCard, run: AnalysisRun): FigureView | null {
  const rows = run.result?.rows ?? [];
  const found = matchingRows(rows, card.select.match);
  const column = card.select.column ?? '';
  if (found.length !== 1 || !(column in found[0])) return null;
  const row = found[0];
  if (isCollectionHealthRun(run)) {
    const health = row as unknown as HealthRow;
    // The same measure's other lines: 上年同期 or 年初, and the change.
    const beside = (rows as unknown as HealthRow[]).filter((item) => item !== health && item.entity === health.entity && item.metric_key === health.metric_key)
      .map((item): [string, string] => [item.scenario, item.display_value]);
    return {
      subject: health.entity, value: health.display_value, part: health.scenario, beside, level: health.level, levelLabel: health.level_label, row,
      facts: [['主体', health.entity], ['单位', health.unit ?? ''], ['说明', health.note]],
    };
  }
  const kpi = kpiFor(row, displayColumns(run));
  const value = column === 'actual' ? kpi.actual
    : formatBusinessCell(row[column], { name: column, label: businessColumnLabel(column), semantics: columnSemantics(column) }, row);
  const beside: [string, string][] = column === 'actual'
    ? [[kpi.estimated ? '预算（估算）' : '预算', kpi.budget], ['差异', kpi.difference], [kpi.rateLabel, kpi.rate]].filter(([, text]) => text && text !== '—') as [string, string][]
    : [];
  return {
    subject: [kpi.periodLabel, kpi.unit].join(' · '), value, part: column === 'actual' ? '实际' : businessColumnLabel(column), beside, level: null, levelLabel: null, row,
    facts: [['期间', kpi.periodLabel], ['单位', kpi.unit], ['依据', kpi.basis]],
  };
}

/** The bars of a rank card, worst first as the card orders them, at most its limit. */
export function rankItems(card: DashboardCard, run: AnalysisRun): { items: RankItem[]; unit: string } {
  const { column = '', label = '', order = 'desc', limit = 10 } = card.select;
  const health = isCollectionHealthRun(run);
  const rows = matchingRows(run.result?.rows ?? [], card.select.match)
    .filter((row) => row[label] != null && row[label] !== '' && row[column] !== '' && row[column] != null && Number.isFinite(Number(row[column])));
  rows.sort((a, b) => (order === 'asc' ? 1 : -1) * (Number(a[column]) - Number(b[column])));
  let unit = '';
  const items = rows.slice(0, limit).map((row) => {
    // A collection run writes each figure with its unit; the bar takes the figure, the caption the unit.
    const written = health && typeof row.display_value === 'string' ? splitDisplay(row.display_value) : { figure: groupDigits(String(row[column]).trim()), unit: typeof row.unit === 'string' ? row.unit : '' };
    unit ||= written.unit;
    return { label: String(row[label]), value: Number(row[column]), text: written.figure, note: typeof row.level_label === 'string' && row.level_label ? row.level_label : undefined };
  });
  return { items, unit };
}

export function sameMatch(left: Record<string, string>, right: Record<string, string>): boolean {
  const keys = Object.keys(left);
  return keys.length === Object.keys(right).length && keys.every((key) => right[key] === left[key]);
}

/** Whether a card still draws on another run: the rows it names are there, as the backend will check. */
export function drawsOn(card: DashboardCard, run: AnalysisRun): boolean {
  if (card.kind === 'figure') return figureView(card, run) !== null;
  if (card.kind === 'rank') return rankItems(card, run).items.length >= 2;
  if (card.kind === 'scenario') return scenarioBase(run, card.select.match) !== null;
  return profitBridges(run).some((bridge) => sameMatch(bridge.match, card.select.match));
}
