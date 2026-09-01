/**
 * Starting the pinned harness.
 *
 * The contract is upstream's own: run the runtime entry under Electron as Node
 * and read the loopback URL it prints on stdout. Copying that rather than
 * inventing a handshake means an upstream change to the startup banner shows up
 * here as a timeout instead of as a subtly wrong origin.
 *
 * Everything in this file is pure so the parsing and the environment scrub can
 * be tested without spawning anything.
 */

/** Upstream prints this once its plugin tree has settled, not before. */
const READY = /(?:^|\s)dsh web:\s+(http:\/\/[^\s]+)/;

export const STARTUP_TIMEOUT_MS = 90_000;

/**
 * The URL from a banner line, if the line carries one this app will load.
 *
 * Only loopback, only http, and a port must be present. A banner naming
 * anything else is a runtime this app did not start.
 */
export function harnessUrlFrom(line: string): string | null {
  const match = READY.exec(line);
  if (!match) return null;
  try {
    const url = new URL(match[1]);
    if (url.protocol !== 'http:') return null;
    if (url.hostname !== '127.0.0.1' && url.hostname !== 'localhost') return null;
    if (url.port === '' || url.username !== '' || url.password !== '') return null;
    return url.origin;
  } catch {
    return null;
  }
}

/** Splits child output into lines without losing a trailing fragment. */
export class LineBuffer {
  private pending = '';

  push(chunk: string): string[] {
    const parts = `${this.pending}${chunk}`.split(/\r?\n/);
    this.pending = parts.pop() ?? '';
    return parts;
  }

  flush(): string[] {
    if (this.pending === '') return [];
    const line = this.pending;
    this.pending = '';
    return [line];
  }
}

/** Names that look like they carry a live credential. */
const SECRET_NAME = /(^|_)(API_?KEY|TOKEN|SECRET|PASSWORD|CREDENTIALS?)($|_)/i;

/**
 * The environment the child gets.
 *
 * Scrubbing here is not belt and braces. The child is the process that talks to
 * model providers, and it must not be handed a key its operator never gave it:
 * provider credentials reach the harness through its own settings, which is
 * where an operator can see and remove them.
 *
 * `DSH_*` is dropped for a different reason. Those select profiles, homes and
 * tool modes, and an ambient one would silently change which composition boots
 * — including which agent preset is the default, which is this product's fence.
 *
 * Three `FOUNDRY_*` are put back deliberately. `FOUNDRY_VAR` and `FOUNDRY_BIN`
 * are how the bundle finds the store. `FOUNDRY_FORMULATOR_BIN` is how the CLI
 * finds the Formulator this app carries, and it has to travel: the data screen
 * reaches `launch-formulator` from main, which has it, but a model calling that
 * same tool inside a session reaches it through this child -- and a packaged app
 * whose model was told `Data Formulator binary is not installed` would be
 * telling the truth about the only environment that mattered.
 *
 * `FOUNDRY_TASK` is NOT set, and that is a decision rather than an
 * omission — one harness process serves every session and every task, so a
 * process-wide task would bind them all to whichever one happened to be open.
 * The CLI's resolution chain covers it: a period step falls through to the
 * current window's own back-pointer, and a follow-up to the brief window's.
 *
 * `companionEnv` is last, and it wins over the inherited environment on
 * purpose. It carries the switches a third-party bundle is not allowed to ship
 * without — today `DO_NOT_TRACK` for the Univer bundle. An operator who chose
 * that plugin themselves would get to make that call; ours did not choose it,
 * they got it inside a product, so the product makes it for them. Declared in
 * the kit's own manifest so it is one value in one language, not two.
 */
export function harnessEnv(
  parent: NodeJS.ProcessEnv,
  own: {
    home: string;
    varRoot: string;
    foundryBin: string;
    formulatorBin?: string;
    companionEnv?: Record<string, string>;
  },
): NodeJS.ProcessEnv {
  const out: NodeJS.ProcessEnv = {};
  for (const [name, value] of Object.entries(parent)) {
    if (value === undefined) continue;
    if (SECRET_NAME.test(name)) continue;
    if (name.startsWith('DSH_')) continue;
    if (name.startsWith('FOUNDRY_')) continue;
    out[name] = value;
  }
  out.DSH_HOME = own.home;
  out.FOUNDRY_VAR = own.varRoot;
  out.FOUNDRY_BIN = own.foundryBin;
  if (own.formulatorBin) out.FOUNDRY_FORMULATOR_BIN = own.formulatorBin;
  // Upstream spawns its own runtime this way, and Electron's binary is the only
  // Node on a machine that has not installed one.
  out.ELECTRON_RUN_AS_NODE = '1';
  for (const [name, value] of Object.entries(own.companionEnv ?? {})) out[name] = value;
  return out;
}


/**
 * Argv for the runtime.
 *
 * Port 0: the operating system picks and the banner reports what it picked. A
 * fixed port would collide with whatever else is listening and would make two
 * copies of this app fight.
 */
export function harnessArgs(entry: string): string[] {
  return [
    // The `web` profile composes the client-reload chain, and
    // `cordis-plugin-hmr` refuses to construct without this flag. A plain `node`
    // satisfies it; the Electron binary running as Node does not, and the whole
    // plugin tree then fails to load, so the workbench never starts.
    //
    // The flag rather than a patch, after measuring: `- id: hmr / disabled: true`
    // has no effect on this profile from a `--patch` overlay OR from the
    // profile's own user layer, while `tool-bash` in the same file flips as
    // expected. Something later re-asserts that row. Turning the reload chain
    // off would have been tidier; making the runtime's own requirement true is
    // what actually boots.
    '--expose-internals',
    entry,
    'web',
    '--host',
    '127.0.0.1',
    '--port',
    '0',
    '--no-open',
  ];
}

/** One RPC envelope for the harness HTTP API. */
export function rpcBody(method: string, payload: Record<string, unknown>): string {
  return JSON.stringify({ type: 'client-request', rpcId: `fnd-${method}`, method, payload });
}

/**
 * Where one RPC goes.
 *
 * The method is in the path as well as in the envelope. Posting the envelope to
 * `/api` alone answers `not found` -- a 404 whose body reads like a refusal --
 * which is what the first version of this did. It is spelled out here with a
 * test because the envelope being right is not the same as the call arriving.
 */
export function rpcUrl(origin: string, method: string): string {
  return `${origin}/api/${method}`;
}

/**
 * The value out of one RPC reply, or the refusal it actually carried.
 *
 * A refusal is nested inside `result`, not beside it: the envelope is
 * `{result: {ok: false, error: {code, message}}}`. Reading a top-level `error`
 * finds nothing, so a refused call looks like a success with no value -- and the
 * caller reports "no session id" while the runtime had said, in the message it
 * threw away, which presets exist. That sentence is the useful one.
 */
export function rpcValue(method: string, body: unknown): unknown {
  const reply = body as {
    result?: { ok?: boolean; value?: unknown; error?: { code?: string; message?: string } };
    error?: { message?: string };
  } | null;
  const refusal = reply?.result?.error ?? reply?.error;
  if (refusal) throw new Error(`${method}: ${refusal.message ?? 'refused'}`);
  if (reply?.result?.ok === false) throw new Error(`${method}: refused`);
  return reply?.result?.value;
}

/**
 * Which agent preset each button opens a session on.
 *
 * The button decides, not the model and not the operator's memory. `period` and
 * `f3` are this product's own, installed by `foundry install-presets`; `f3` is
 * narrowed to `query-locked` alone (KTD7).
 *
 * Authoring runs on the stock `standard` preset on purpose. It is the one job
 * here with no locked window to read around: F1 produces a skill, and producing
 * one wants the editor and the shell that `standard` carries. The fence exists
 * for the period loop, and this is not it.
 */
export const PRESET_BY_INTENT = {
  author: 'standard',
  period: 'period',
  followup: 'f3',
} as const;

export type Intent = keyof typeof PRESET_BY_INTENT;

/**
 * The preset the runtime mounts when nobody names one.
 *
 * Upstream's own default is `standard`, which is a full coding agent -- the
 * right answer for the product the runtime ships with and the wrong one here.
 * The picker above the composer is the first thing an operator reads about what
 * kind of work this window does, and this product's answer to that is a closing
 * period, not a shell.
 *
 * It is a display default and not a fence. What a session actually runs on is
 * decided by the button that opened it (`PRESET_BY_INTENT`), and the page
 * cannot open one at all -- `fence.ts` refuses `session.create`. So this moves
 * a label rather than a permission.
 */
export const DEFAULT_PRESET = PRESET_BY_INTENT.period;

/**
 * The `settings.update` payload that names it.
 *
 * `agent-presets` is the runtime's own settings namespace for this, and its
 * schema is one field. The service reads the value per call rather than caching
 * it, so this takes effect on the next session created without disturbing any
 * that are running.
 */
export function defaultPresetPatch(preset: string = DEFAULT_PRESET): Record<string, unknown> {
  return { ns: 'agent-presets', patch: { default: preset } };
}

/** The session role each intent records on the task. Same word the store uses. */
export const ROLE_BY_INTENT = {
  author: 'author',
  period: 'period',
  followup: 'followup',
} as const;
