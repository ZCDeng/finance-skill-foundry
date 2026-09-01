import { mkdirSync } from 'node:fs';
import * as path from 'node:path';

/**
 * Where a conversation is allowed to stand.
 *
 * Every tool in the runtime that takes a path resolves it against the session's
 * own working directory, and a session created without one falls through to the
 * host's: `dsh-host-apiproxy` reads `workspace?.path ?? payload.cwd ??
 * defaults.cwd`, and `defaults.cwd` is `process.cwd()`. This app spawned the
 * runtime without a `cwd` and was itself launched from the Finder, so the
 * measured answer was `/` -- the root of the disk, for every session, on every
 * preset. An authoring session carries the stock editor and shell; those were
 * standing at the root of the machine.
 *
 * So the app names it. One directory per task, created before the session that
 * will stand in it, under this app's own `userData` and nowhere near the
 * operator's documents.
 *
 * It is deliberately NOT the window directory. A window holds `inputs/` -- the
 * archived copies of the books, the very files the period fence exists to stop
 * a model reading around. Handing a session the window would be handing it the
 * ledger with the lock still on the door.
 */

/** The directory every session on one task stands in. */
export function taskWorkspace(userData: string, taskId: string): string {
  return path.join(userData, 'workspace', taskId);
}

/**
 * The same path, made real.
 *
 * The runtime resolves the cwd through `realpath` before it will use it, and
 * the office plugins resolve every tool path against the result, so a directory
 * that does not exist yet is a session whose path tools all refuse. Created
 * here rather than at task creation because a task made by the CLI never passes
 * through this process.
 */
export function ensureTaskWorkspace(userData: string, taskId: string): string {
  const dir = taskWorkspace(userData, taskId);
  mkdirSync(dir, { recursive: true });
  return dir;
}
