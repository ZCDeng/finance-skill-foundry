/**
 * A task's 看板 (foundry/dashboards.py): cards pinned from calculated results. A card holds no figure of its own; it
 * names one run and which of its rows it shows, so the board draws numbers the run already holds and opens them to
 * the same source as the result page.
 */
import { createContext } from 'react';
import type { AnalysisRun } from '../../bridge.js';

export type CardKind = 'figure' | 'rank' | 'bridge';
/** explore: the assistant proposed it, not on the board yet; pinned: waits for the manager; accepted: the manager's. */
export type CardState = 'explore' | 'pinned' | 'accepted';
export type TemplateId = 'operating' | 'collection' | 'city';

export type CardSelect = {
  /** Every named column holds this text in the rows the card reads. */
  match: Record<string, string>;
  /** figure: the cell's column; rank: the figure ranked. */
  column?: string;
  /** rank: the column that names each bar. */
  label?: string;
  order?: 'asc' | 'desc';
  limit?: number;
  reference?: { value: string; label: string };
};

export type DashboardCard = {
  id: string;
  kind: CardKind;
  title: string;
  state: CardState;
  run_id: string;
  select: CardSelect;
  template: TemplateId | null;
  note: string | null;
  proposed_by: 'manager' | 'assistant';
  /** Set by the backend when the manager accepts, on the run the card showed then. */
  accepted: { run_id: string; at: string } | null;
};

/** A card before it is saved: the backend gives it an id and records who pinned it. */
export type CardDraft = Pick<DashboardCard, 'kind' | 'title' | 'state' | 'run_id' | 'select'> & { template?: TemplateId | null };

export type Dashboard = { id: string; parent_id: string | null; created_at: string; cards: DashboardCard[] };

/** Pins a draft to the task's board and says how it went, in a sentence for the manager. */
export type PinBoard = { pin(draft: CardDraft): Promise<string> };

/** Present where a result page can pin to its task's board; absent, nothing offers 钉到看板. */
export const DashboardPinContext = createContext<PinBoard | null>(null);

const cell = (row: Record<string, unknown>, column: string) => row[column] == null ? '' : String(row[column]).trim();

/** The rows whose every named column holds the named text, as the backend matches them. */
export function matchingRows(rows: Record<string, unknown>[], match: Record<string, string>): Record<string, unknown>[] {
  return rows.filter((row) => Object.entries(match).every(([column, text]) => cell(row, column) === text.trim()));
}

function sorted(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sorted);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value as Record<string, unknown>).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)).map(([key, item]) => [key, sorted(item)]));
  }
  return value;
}

/** What a card shows, for telling two cards apart: the same run, kind and rows read alike. */
export function cardSignature(card: Pick<DashboardCard, 'kind' | 'run_id' | 'select'>): string {
  return JSON.stringify([card.kind, card.run_id, sorted(card.select)]);
}

/** The columns that say which row a figure is: what it measures, for whom, when and on which side. */
const identityColumns = ['metric_key', 'metric', 'business_key', 'result_key', 'item', 'name', '指标', 'entity', 'organization', 'region', '区域',
  'period', '期间', 'scenario', 'unit'];

const scalar = (value: unknown) => (typeof value === 'string' && value.trim() !== '') || (typeof value === 'number' && Number.isFinite(value));
const figureLike = (value: unknown) => typeof value === 'number' || (typeof value === 'string' && /^[-+]?[\d,]*\.?\d+%?$/.test(value.trim()));

/**
 * A figure card on one row of a run: the row named by the columns that identify it, or, when those name several
 * rows, by every text column it holds. A row no match tells apart from the rest cannot be pinned on its own.
 */
export function figureDraft(run: AnalysisRun, row: Record<string, unknown>, column: string, title: string): CardDraft | null {
  const rows = run.result?.rows ?? [];
  const named = (columns: string[]) => Object.fromEntries(columns.filter((name) => scalar(row[name])).map((name) => [name, String(row[name]).trim()]));
  let match = named(identityColumns);
  if (matchingRows(rows, match).length !== 1) {
    match = named(Object.keys(row).filter((name) => typeof row[name] === 'string' && !figureLike(row[name]) && String(row[name]).length <= 200));
  }
  if (!Object.keys(match).length || matchingRows(rows, match).length !== 1 || !(column in row)) return null;
  return { kind: 'figure', title: title.slice(0, 60), state: 'pinned', run_id: run.id, select: { match, column } };
}

/** A figure a run wrote with its unit (+3.10 个百分点, 82.12%, 123 天) as the figure and the unit apart. */
export function splitDisplay(text: string): { figure: string; unit: string } {
  const found = /^\s*([+-]?[\d,]*\.?\d+)\s*(.*)$/.exec(text);
  if (!found) return { figure: text, unit: '' };
  return { figure: found[1].replace(/^\+/, ''), unit: found[2].trim() };
}
