/**
 * A task's 看板 (foundry/dashboards.py): cards pinned from calculated results. A card holds no figure of its own; it
 * names one run and which of its rows it shows, so the board draws numbers the run already holds and opens them to
 * the same source as the result page.
 */
import { createContext } from 'react';
import type { AnalysisRun } from '../../bridge.js';

/**
 * scenario: 回款情景, goal: 倒推, sensitivity: 敏感性表 -- what-ifs over one entity's collection-health lines, never
 * accepted.
 */
export type CardKind = 'figure' | 'rank' | 'bridge' | 'scenario' | 'goal' | 'sensitivity';
export const WHAT_IF_KINDS: readonly CardKind[] = ['scenario', 'goal', 'sensitivity'];
/** A what-if card: never accepted, never in the close, a report or a snapshot (foundry/dashboards.py WHAT_IF). */
export const isWhatIf = (kind: string | undefined) => (WHAT_IF_KINDS as readonly string[]).includes(kind ?? '');
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
  /** goal: what it works back to, the collection rate or the full-year revenue budget. */
  goal?: 'collection' | 'budget';
  /** goal collection: the target rate with its % (92%); without one, the 生死线. */
  target?: string;
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
  /** Set by the backend when the manager accepts, on the run the card showed then, with the 署名 it was accepted under. */
  accepted: { run_id: string; at: string; by?: string } | null;
  /** Sent with an acceptance only: the current person's 署名 (设置 › 使用者). The backend keeps it as `accepted.by`. */
  accepted_by?: string;
  /** Set by the backend when the card was last run again on newer files, or carried from another task's board. */
  recomputed?: Recomputed | null;
  /** The last recompute on the card's newer files did not run, and why; tried again when the files change again. */
  recompute_failed?: { at: string; reason: string } | null;
};

/** What a card showed, for saying what changed: a figure's value, a ranking's order, a bridge's steps. */
export type Shown = {
  value?: string | null; display?: string | null; level?: string | null; unit?: string | null;
  labels?: string[]; leaders?: string[]; beyond?: string[] | null;
  profit?: (string | null)[]; steps?: Record<string, string | null>;
};

/** foundry/dashboard_recompute.py moved_card. */
export type Recomputed = {
  at: string;
  from_run_id: string;
  was_accepted: boolean;
  /** [from, to] when the new files were another month's. */
  months: [string, string] | null;
  before: Shown | null;
  after: Shown;
  /** A move worth a look: a level, a sign, a tenth or a point, the leaders of a ranking. */
  changed: boolean;
  change: string;
  /** What moved with the month, e.g. 已过月数 8 → 9. */
  adjusted: string[];
  /** Figures given by hand, carried as they were. */
  manual: string[];
  carried_from: { task_id: string; title: string } | null;
};

/** One calculation that cannot yet be carried, shared by one or more cards. */
export type CarryBlock = { run_id: string; card_ids: string[]; titles: string[]; code: string; reason: string };

/** One board another task holds that could come to this one (dashboard-carry without a task). */
export type CarryOffer = {
  task_id: string; title: string; period: string | null; target_period?: string | null;
  cards: number; ready: number; missing: string[]; blocked?: CarryBlock[];
};

/** Persisted by the backend even if no card could be carried; a read restores the remaining work. */
export type CarryAttempt = {
  from_task_id: string; from_title?: string; target_period: string | null;
  failed: { run_id: string; card_id: string; title: string; code: string; reason: string }[];
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
