/**
 * 倒推 and 敏感性: what a goal or sensitivity card (foundry/dashboards.py) says of one entity's 本期 lines of a
 * collection-health run. The conversation draws the same cards on the server (foundry/what_if.py); both are held to
 * tests/fixtures/what-if-cases.json, so a run reads the same on the board and under the assistant's answer.
 *
 * Every figure here past the run's own lines is a what-if, which is why such a card is never accepted.
 */
import type { AnalysisRun } from '../../bridge.js';
import { decimalToFixed } from '../../lib/figures.js';
import { isCollectionHealthRun, type HealthRow, type SensitivityGrid } from './CollectionHealthView.js';
import { matchingRows, type CardSelect } from './dashboardModel.js';

export const WHAT_IF_FLAG = '情景，不是实际数';
/** The rows and columns of a sensitivity grid a card shows, around where the entity stands. */
const WINDOW = 5;
const MANUAL_BUDGET = /含手填数：[^；]*全年收入预算/;

/** A line of the run, with what it read: the budget's inputs ride on its rows. */
export type WhatIfRow = HealthRow & { inputs?: Record<string, string> };

/** Number(text) for a finite figure the run wrote; null for anything else. */
const numberOf = (value: unknown) => (typeof value === 'string' && value.trim() !== '' && Number.isFinite(Number(value)) ? Number(value) : null);
const fixed = (value: number, places: number) => decimalToFixed(value.toFixed(8), places);
const signed = (value: number, places: number) => `${value > 0 ? '+' : ''}${fixed(value, places)}`;
const withUnit = (text: string, unit: string) => (unit ? `${text} ${unit}` : text);

/** The entity's 本期 lines by metric key, each with a figure. */
export function linesOf(rows: WhatIfRow[], entity: string): Map<string, WhatIfRow> {
  const out = new Map<string, WhatIfRow>();
  for (const row of rows) {
    if (row.entity === entity && row.scenario === '本期' && numberOf(row.value) !== null && !out.has(row.metric_key)) out.set(row.metric_key, row);
  }
  return out;
}

export type GoalView = {
  goal: 'collection' | 'budget';
  subject: string;
  /** The answer's words and figure: 一年还要多收 19,276 万元, 剩余 4 个月每月要做到 43,589.00 万元. */
  part: string;
  value: string;
  beside: [string, string][];
  caption: string;
  /** The run's own lines the card works from, each opening to its source. */
  basis: WhatIfRow[];
};

/** What reaching ``target`` (or the line itself) takes from the collection rate the run was taken at. */
export function goalCollection(lines: Map<string, WhatIfRow>, entity: string, target: string | undefined, params: Record<string, string>): GoalView {
  const breakEven = lines.get('break_even_collection')!;
  const gap = lines.get('collection_gap')!;
  const line = Number(breakEven.value);
  const current = line + Number(gap.value);
  const goal = target ? Number(target.slice(0, -1)) : line;
  const points = goal - current;
  const at = goal - line;
  const revenueRow = lines.get('ttm_revenue') ?? null;
  const revenue = revenueRow ? numberOf(revenueRow.value) : null;
  const vat = numberOf(params.vat_factor) ?? 1.06;
  const unit = revenueRow?.unit ?? '';
  const money = revenue === null ? null : (points / 100) * revenue * vat;
  // A rate that reads as the goal to the hundredth has reached it: neither short of it nor past it.
  const met = fixed(Math.abs(points), 2) === '0.00';
  const part = met ? (target ? '已达到目标' : '正好在生死线上')
    : money !== null ? (points > 0 ? '一年还要多收' : '一年已比目标多收') : (points > 0 ? '收缴率还要提高' : '收缴率已高出目标');
  const value = met ? `${fixed(goal, 2)}%` : money !== null ? withUnit(fixed(Math.abs(money), 0), unit) : `${fixed(Math.abs(points), 2)} 个百分点`;
  // Without a target the goal is the line itself, which the card shows among the run's lines.
  const beside: [string, string][] = target ? [['目标收缴率', `${fixed(goal, 2)}%`]] : [];
  beside.push(['这次计算的收缴率', `${fixed(current, 2)}%`]);
  if (money !== null && !met) beside.push([points > 0 ? '还差' : '已高出', `${fixed(Math.abs(points), 2)} 个百分点`]);
  if (target) beside.push(['到目标时距生死线', `${signed(at, 2)} 个百分点`]);
  const caption = (target ? '以上几项读自这次计算，只有目标收缴率是假设。' : '以上几项读自这次计算，目标就是生死线收缴率。') + (money !== null
    ? `一年回款差 = 收缴率差 × 近 12 个月营业收入 × ${vat}（回款含增值税），是估算。` : '这次计算没有近 12 个月营业收入，算不出金额。');
  return {
    goal: 'collection', subject: `${entity} · ${target ? `收缴率到 ${fixed(goal, 2)}%` : '收缴率回到生死线'}`, part, value, beside, caption,
    basis: [breakEven, gap, ...(revenueRow ? [revenueRow] : [])],
  };
}

/** What the full-year revenue budget still needs from each month left, against the months gone. */
export function goalBudget(lines: Map<string, WhatIfRow>, entity: string): GoalView {
  const remainingRow = lines.get('revenue_budget_remaining')!;
  const monthlyRow = lines.get('revenue_budget_monthly')!;
  const inputs = { ...(remainingRow.inputs ?? {}), ...(monthlyRow.inputs ?? {}) };
  const unit = remainingRow.unit ?? '';
  const remaining = Number(remainingRow.value);
  const need = Number(monthlyRow.value);
  const budget = numberOf(inputs.revenue_budget_full);
  const done = numberOf(inputs.revenue);
  const months = numberOf(inputs.months_elapsed);
  const manual = MANUAL_BUDGET.test(remainingRow.note ?? '');
  // Short by what reads as 0.00 is done to the cent: neither a month's target nor an overshoot.
  const short = remaining > 0 && fixed(remaining, 2) !== '0.00';
  const exact = !short && fixed(Math.abs(remaining), 2) === '0.00';
  const part = short ? `剩余 ${months !== null ? 12 - months : '—'} 个月每月要做到` : exact ? '全年收入预算正好完成' : '全年收入预算已完成，超出';
  const value = short ? (monthlyRow.display_value || withUnit(fixed(need, 2), unit))
    : exact ? withUnit(decimalToFixed(inputs.revenue_budget_full, 2), unit) : withUnit(fixed(-remaining, 2), unit);
  const beside: [string, string][] = [
    [manual ? '全年收入预算（手填）' : '全年收入预算', withUnit(decimalToFixed(inputs.revenue_budget_full, 2), unit)],
    ['本年累计', withUnit(decimalToFixed(inputs.revenue, 2), unit)],
  ];
  if (budget !== null && done !== null && budget > 0) beside.push(['已完成', `${fixed((done / budget) * 100, 2)}%`]);
  if (short) beside.push(['还差', remainingRow.display_value || withUnit(fixed(remaining, 2), unit)]);
  const pace = done !== null && months ? done / months : null;
  if (pace !== null) {
    beside.push(['已过月份月均', withUnit(fixed(pace, 2), unit)]);
    if (short && pace > 0) beside.push(['每月要比月均多', `${signed((need / pace - 1) * 100, 1)}%`]);
  }
  const caption = `全年收入预算、本年累计和已过月数读自这次计算${manual ? '，全年收入预算是手填的' : ''}。每月要做到 = 还差 ÷ 剩余月数，是倒推，不是预测。`;
  return { goal: 'budget', subject: `${entity} · 全年收入预算`, part, value, beside, caption, basis: [remainingRow, monthlyRow] };
}

export type SensitivityCell = { text: string; tone: 'loss' | 'edge' | 'gain'; current: boolean };
export type SensitivityView = {
  subject: string; corner: string; columns: string[]; rows: { label: string; cells: SensitivityCell[] }[]; caption: string;
  basis: WhatIfRow[];
};

/** The candidate nearest ``value``, and whether ``value`` lies on the grid (within half a step of its ends). */
function place(value: string | null, candidates: string[]): [number, boolean] {
  const target = numberOf(value);
  const values = candidates.map(Number);
  if (target === null) return [Math.floor(values.length / 2), false];
  let best = 0;
  values.forEach((candidate, index) => { if (Math.abs(candidate - target) < Math.abs(values[best] - target)) best = index; });
  const half = Math.abs(values[1] - values[0]) / 2;
  return [best, Math.min(...values) - half <= target && target <= Math.max(...values) + half];
}

function windowOf(index: number, size: number): number[] {
  const start = Math.min(Math.max(index - Math.floor(WINDOW / 2), 0), Math.max(size - WINDOW, 0));
  return Array.from({ length: Math.min(start + WINDOW, size) - start }, (_, offset) => start + offset);
}

/** The part of the entity's grid around where it stands, cells toned as the result page tones them. */
export function sensitivityView(grid: SensitivityGrid, gap: WhatIfRow): SensitivityView {
  const margins = grid.gross_margins, rates = grid.collection_rates;
  const [row, rowOn] = place(grid.current?.gross_margin ?? null, margins);
  const [column, columnOn] = place(grid.current?.collection_rate ?? null, rates);
  const edge = numberOf(grid.edge_below);
  const rows = windowOf(row, margins.length), columns = windowOf(column, rates.length);
  const tone = (cell: string): SensitivityCell['tone'] => (Number(cell) < 0 ? 'loss' : edge !== null && Number(cell) < edge ? 'edge' : 'gain');
  const on = rowOn && columnOn;
  const cropped = rows.length < margins.length || columns.length < rates.length;
  return {
    subject: `${grid.entity} · 期间费用率 ${decimalToFixed(grid.expense_ratio, 2, 100)}%`,
    corner: '毛利率 \\ 收缴率',
    columns: columns.map((index) => `${decimalToFixed(rates[index], 1, 100)}%`),
    rows: rows.map((r) => ({
      label: `${decimalToFixed(margins[r], 0, 100)}%`,
      cells: columns.map((c) => ({ text: decimalToFixed(grid.cells[r][c], 1, 100), tone: tone(grid.cells[r][c]), current: on && r === row && c === column })),
    })),
    caption: `${grid.formula ?? ''}。负数表示每收 100 元要倒贴的现金。${on ? '框出的格最接近现在的位置。' : '现在的位置不在表内。'}${cropped ? '完整的表在结果页。' : ''}`,
    basis: [gap],
  };
}

/** The run's sensitivity grid for ``entity``, when it holds one to draw (foundry/dashboards.py sensitivity_grid). */
export function sensitivityGrid(run: AnalysisRun, entity: string): SensitivityGrid | null {
  const grids = (run.result as { sensitivity?: unknown } | undefined)?.sensitivity;
  const grid = Array.isArray(grids) ? (grids as SensitivityGrid[]).find((item) => item && item.entity === entity) : undefined;
  if (!grid || !Array.isArray(grid.gross_margins) || !Array.isArray(grid.collection_rates) || grid.gross_margins.length < 2 || grid.collection_rates.length < 2) return null;
  if (!Array.isArray(grid.cells) || grid.cells.length !== grid.gross_margins.length || grid.cells.some((cells) => !Array.isArray(cells) || cells.length !== grid.collection_rates.length)) return null;
  return grid;
}

/** A goal or sensitivity card on its run, or null when the run cannot carry it (the backend refuses the same). */
export function whatIfView(kind: 'goal' | 'sensitivity', run: AnalysisRun, select: CardSelect): GoalView | SensitivityView | null {
  if (!isCollectionHealthRun(run)) return null;
  const rows = (run.result?.rows ?? []) as unknown as WhatIfRow[];
  const named = matchingRows(rows as unknown as Record<string, unknown>[], select.match) as unknown as WhatIfRow[];
  if (new Set(named.map((row) => row.entity)).size !== 1 || named.some((row) => row.scenario !== '本期')) return null;
  const entity = named[0].entity;
  const lines = linesOf(rows, entity);
  const has = (...keys: string[]) => keys.every((key) => lines.has(key));
  if (kind === 'sensitivity') {
    const grid = sensitivityGrid(run, entity);
    return grid && has('collection_gap') ? sensitivityView(grid, lines.get('collection_gap')!) : null;
  }
  if (select.goal === 'budget') return has('revenue_budget_remaining', 'revenue_budget_monthly') ? goalBudget(lines, entity) : null;
  if (select.goal !== 'collection' || !has('break_even_collection', 'collection_gap')) return null;
  const params = (run.result as { params?: Record<string, string> } | undefined)?.params ?? {};
  return goalCollection(lines, entity, select.target, params);
}
