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
 */
export type Preferences = {
  technical: boolean; brief_open: boolean; start: 'overview' | 'workspace';
  /** The kinds of example task whose note the manager has read (知道了); theirs fold to a 示例 tag. */
  samples_read: SampleKind[];
};
type SampleKind = 'practice' | 'reference' | 'next_month' | 'legacy';

export const DEFAULT_PREFERENCES: Preferences = { technical: false, brief_open: true, start: 'overview', samples_read: [] };

const FILE = 'preferences.json';
const STARTS = ['overview', 'workspace'] as const;
const SAMPLES: readonly SampleKind[] = ['practice', 'reference', 'next_month', 'legacy'];

/** Only known keys with values of their own type survive; anything else keeps the default. */
function clean(raw: unknown, base: Preferences): Preferences {
  const value = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {};
  return {
    technical: typeof value.technical === 'boolean' ? value.technical : base.technical,
    brief_open: typeof value.brief_open === 'boolean' ? value.brief_open : base.brief_open,
    start: (STARTS as readonly unknown[]).includes(value.start) ? value.start as Preferences['start'] : base.start,
    samples_read: Array.isArray(value.samples_read) && value.samples_read.every((kind) => (SAMPLES as readonly unknown[]).includes(kind))
      ? [...new Set(value.samples_read as SampleKind[])] : base.samples_read,
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
