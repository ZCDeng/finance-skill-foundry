/**
 * The one way this app talks to the store.
 *
 * KTD2: `foundry/` is the sole mutator. This process never opens the DuckDB
 * catalog and never reads a file under `var/` directly. It execs the CLI, which
 * means the store layout is known in exactly one place and a view this app wants
 * is a new read-only subcommand rather than a second reader that can drift.
 *
 * Reading a task's own `task.json` from here would be quicker and would work
 * today. It would also make this file the second thing that knows what a task
 * directory looks like, and the two would agree right up until the day they
 * did not.
 */

import { execFile } from 'node:child_process';

/** foundry exits 3 for a domain refusal and leaves 2 to argparse for a usage error. */
export const REFUSED = 3;

const DEFAULT_TIMEOUT_MS = 120_000;
const MAX_BUFFER = 32 * 1024 * 1024;

export class FoundryRefusal extends Error {
  readonly refused = true;
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = 'FoundryRefusal';
  }
}

export class FoundryFailure extends Error {
  readonly refused = false;
  constructor(message: string, readonly status: number | null) {
    super(message);
    this.name = 'FoundryFailure';
  }
}

/** Where the store is, and which task and conversation a call belongs to. */
export interface Binding {
  varRoot: string;
  /** Passed through when the caller has one; the CLI falls through to the window's own back-pointer. */
  task?: string;
  /** The conversation. U10 supplies it from the harness; nothing here invents one. */
  session?: string;
}

/**
 * Build the argv for one call.
 *
 * `--var`, `--task` and `--session` are parser-level flags, so they go in front
 * of the subcommand: argparse stops accepting them once a subparser has been
 * chosen. Pure and exported so the ordering is a test rather than a comment.
 */
export function foundryArgs(binding: Binding, command: string, rest: readonly string[] = []): string[] {
  if (!binding.varRoot) throw new Error('varRoot is required');
  const argv = ['--var', binding.varRoot];
  if (binding.task) argv.push('--task', binding.task);
  if (binding.session) argv.push('--session', binding.session);
  return [...argv, command, ...rest];
}

export interface FoundryEnv {
  bin?: string;
  timeoutMs?: number;
}

/** Run one call and hand back its stdout, or throw a refusal apart from a failure. */
export function runFoundry(
  binding: Binding,
  command: string,
  rest: readonly string[] = [],
  env: FoundryEnv = {},
): Promise<string> {
  const bin = env.bin ?? process.env.FOUNDRY_BIN ?? 'foundry';
  const argv = foundryArgs(binding, command, rest);
  return new Promise((resolve, reject) => {
    execFile(
      bin,
      argv,
      { timeout: env.timeoutMs ?? DEFAULT_TIMEOUT_MS, maxBuffer: MAX_BUFFER, encoding: 'utf8' },
      (error, stdout, stderr) => {
        if (!error) return resolve(stdout);
        // A refusal is a state the operator acts on ("this window is not
        // locked"); a failure is a bug or a broken install. Branching on the
        // code keeps them separable without string-matching stderr.
        const status = typeof (error as { code?: unknown }).code === 'number'
          ? ((error as { code: number }).code)
          : null;
        const detail = (stderr || stdout || error.message).trim();
        return reject(
          status === REFUSED ? new FoundryRefusal(detail, status) : new FoundryFailure(detail, status),
        );
      },
    );
  });
}

/**
 * Run one call whose stdout is JSON.
 *
 * A read command that printed something else is a contract break, not a value
 * to guess at, so this refuses by name rather than returning undefined.
 */
export async function runFoundryJson<T>(
  binding: Binding,
  command: string,
  rest: readonly string[] = [],
  env: FoundryEnv = {},
): Promise<T> {
  const stdout = await runFoundry(binding, command, rest, env);
  try {
    return JSON.parse(stdout) as T;
  } catch {
    throw new FoundryFailure(`foundry ${command} did not print JSON: ${stdout.slice(0, 400)}`, 0);
  }
}
