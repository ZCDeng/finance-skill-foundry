import { mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import * as path from 'node:path';

/**
 * 设置: the few choices the manager makes for the app as a whole, beside the appearance in this app's own folder.
 *
 * technical: whether ids, digests, scripts, raw JSON and engine diagnostics show in the workspace. Off by default:
 * a manager never needs them to read a result, and the assistant reads them through its own tools either way.
 * brief_open: whether 本月三句话 opens expanded at the top of a task.
 * start: which screen the app opens on.
 * samples_read: example-task notes already read.
 * skipped_steps: the steps a task marks 本期不做, by task.
 * people, current_person: who uses this computer, and who is signing now (使用者).
 */
export type Preferences = {
  technical: boolean; brief_open: boolean; start: 'overview' | 'workspace';
  /** The kinds of example task whose note the manager has read (知道了); theirs fold to a 示例 tag. */
  samples_read: SampleKind[];
  /**
   * Per task, the steps this period does without (本期不做): a task with no month close, or no report. A task is
   * one period, so the mark is the period's. Only the steps after 范围 can be left out; a task without a mark has no entry.
   */
  skipped_steps: Record<string, SkippableStep[]>;
  /**
   * 使用者: the people who use the app on this computer, each with the name a record is signed with. Switching needs
   * no password: this is who signed, not who may. Disposing of a difference, reviewing it, accepting a board card
   * and exporting the one-page board fill in the current person's 署名, which can still be changed there.
   */
  people: Person[];
  /** The person signing now, by id; '' or an id no longer in the list is nobody, and every name is typed. */
  current_person: string;
};
export type Person = { id: string; name: string; role: PersonRole; signature: string };
/** 经理, 财务分析, 复核人: what the person does, shown beside the name. It grants nothing. */
export type PersonRole = 'manager' | 'analyst' | 'reviewer';
type SampleKind = 'practice' | 'reference' | 'next_month' | 'legacy';
export type SkippableStep = 'close' | 'results' | 'operations' | 'report';

export const DEFAULT_PREFERENCES: Preferences = {
  technical: false, brief_open: true, start: 'overview', samples_read: [], skipped_steps: {}, people: [], current_person: '',
};

const FILE = 'preferences.json';
const STARTS = ['overview', 'workspace'] as const;
const SAMPLES: readonly SampleKind[] = ['practice', 'reference', 'next_month', 'legacy'];
export const SKIPPABLE_STEPS: readonly SkippableStep[] = ['close', 'results', 'operations', 'report'];
const TASK_ID = /^[A-Za-z0-9_-]{1,64}$/;
const ROLES: readonly PersonRole[] = ['manager', 'analyst', 'reviewer'];
export const MAX_PEOPLE = 20;
/** A name as a record keeps it: the backend takes up to 80 characters for whoever accepted or reviewed a difference. */
const NAME = /^[^\u0000-\u001f\u007f]{1,80}$/;

/** A map of task to marked steps, each list without repeats and never empty; anything else is not one. */
function skippedOf(value: unknown): Record<string, SkippableStep[]> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const entries = Object.entries(value as Record<string, unknown>);
  const valid = entries.every(([task, steps]) => TASK_ID.test(task) && Array.isArray(steps) && steps.length > 0
    && steps.every((step) => (SKIPPABLE_STEPS as readonly unknown[]).includes(step)) && new Set(steps).size === steps.length);
  return valid ? Object.fromEntries(entries) as Record<string, SkippableStep[]> : null;
}

/** The list of people, each id once, each name and 署名 trimmed and on one line; anything else is not one. */
function peopleOf(value: unknown): Person[] | null {
  if (!Array.isArray(value) || value.length > MAX_PEOPLE) return null;
  const valid = value.every((row) => row && typeof row === 'object' && !Array.isArray(row)
    && Object.keys(row).length === 4 && typeof row.id === 'string' && TASK_ID.test(row.id)
    && typeof row.name === 'string' && NAME.test(row.name) && row.name === row.name.trim()
    && typeof row.signature === 'string' && NAME.test(row.signature) && row.signature === row.signature.trim()
    && (ROLES as readonly unknown[]).includes(row.role));
  return valid && new Set(value.map((row) => row.id)).size === value.length
    ? value.map((row) => ({ ...row }) as Person) : null;
}

/** Only known keys with values of their own type survive; anything else keeps the default. */
function clean(raw: unknown, base: Preferences): Preferences {
  const value = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {};
  return {
    technical: typeof value.technical === 'boolean' ? value.technical : base.technical,
    brief_open: typeof value.brief_open === 'boolean' ? value.brief_open : base.brief_open,
    start: (STARTS as readonly unknown[]).includes(value.start) ? value.start as Preferences['start'] : base.start,
    samples_read: Array.isArray(value.samples_read) && value.samples_read.every((kind) => (SAMPLES as readonly unknown[]).includes(kind))
      ? [...new Set(value.samples_read as SampleKind[])] : base.samples_read,
    skipped_steps: skippedOf(value.skipped_steps) ?? base.skipped_steps,
    people: peopleOf(value.people) ?? base.people,
    current_person: value.current_person === '' || (typeof value.current_person === 'string' && TASK_ID.test(value.current_person))
      ? value.current_person : base.current_person,
  };
}

/** The saved choices. Missing, unreadable or unknown values are the defaults. */
export function readPreferences(folder: string): Preferences {
  try {
    return clean(JSON.parse(readFileSync(path.join(folder, FILE), 'utf8')), DEFAULT_PREFERENCES);
  } catch {
    return { ...DEFAULT_PREFERENCES };
  }
}

/** What the renderer sent: a patch of known keys. Anything else is refused rather than dropped. */
export function preferencesPatchOf(raw: unknown): Partial<Preferences> {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('preferences must be an object');
  const patch = raw as Record<string, unknown>;
  for (const key of Object.keys(patch)) {
    if (!(key in DEFAULT_PREFERENCES)) throw new Error(`unknown preference: ${key.slice(0, 20)}`);
  }
  const next = clean(patch, DEFAULT_PREFERENCES);
  for (const key of Object.keys(patch) as (keyof Preferences)[]) {
    if (JSON.stringify(next[key]) !== JSON.stringify(patch[key])) throw new Error(`bad value for ${key}`);
  }
  return Object.fromEntries(Object.keys(patch).map((key) => [key, next[key as keyof Preferences]])) as Partial<Preferences>;
}

/** The patch over what is saved, written beside and renamed over, so a crash mid-write leaves the old file. */
export function writePreferences(folder: string, patch: Partial<Preferences>): Preferences {
  const next = { ...readPreferences(folder), ...patch };
  mkdirSync(folder, { recursive: true });
  const target = path.join(folder, FILE);
  const pending = `${target}.${process.pid}.tmp`;
  writeFileSync(pending, `${JSON.stringify(next)}\n`);
  renameSync(pending, target);
  return next;
}
