import { appendFile } from 'node:fs/promises';
import * as path from 'node:path';

import { WAIT_KINDS, type WaitKind, type WaitOutcome } from './ipc/contract.js';

/**
 * The local wait-timing log: one JSON line per user wait, in this app's own
 * folder, never the task store and never sent anywhere.
 *
 * Its own module for the reason `harness/wiring.ts` is: the IPC layer reaches
 * the store only through the CLI, and this file is not the store.
 */
export const TIMING_LOG = 'wait-timing.jsonl';

export interface WaitEntry { kind: WaitKind; outcome: WaitOutcome; waitMs: number; engineMs: number | null }

function milliseconds(value: unknown): number {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0 || value > 86_400_000) {
    throw new Error('wait times are milliseconds');
  }
  return value;
}

/**
 * One wait as it comes off the wire. A kind on the fixed list, a known outcome
 * and plain numbers, or it is refused; every other field is dropped, so no
 * amount, file name or typed text can reach the line.
 */
export function waitEntry(raw: unknown): WaitEntry {
  const entry = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>;
  const kind = WAIT_KINDS.find((known) => known === entry.kind);
  if (!kind) throw new Error('unknown wait kind');
  const outcome = entry.outcome;
  if (outcome !== 'ok' && outcome !== 'error' && outcome !== 'cancelled') throw new Error('unknown wait outcome');
  return { kind, outcome, waitMs: milliseconds(entry.waitMs), engineMs: entry.engineMs == null ? null : milliseconds(entry.engineMs) };
}

/** Appends one line: when, what, how it ended, the wait less `excludedMs`, and the engine time when known. */
export async function appendWait(folder: string, entry: WaitEntry, excludedMs = 0): Promise<void> {
  const line = JSON.stringify({
    at: new Date().toISOString(),
    kind: entry.kind,
    outcome: entry.outcome,
    wait_ms: Math.round(Math.max(0, entry.waitMs - excludedMs)),
    engine_ms: entry.engineMs === null ? null : Math.round(entry.engineMs),
  });
  await appendFile(path.join(folder, TIMING_LOG), `${line}\n`, { encoding: 'utf8', mode: 0o600 });
}
