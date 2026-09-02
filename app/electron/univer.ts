import { type ChildProcess, spawn } from 'node:child_process';
import { existsSync, mkdirSync, rmSync } from 'node:fs';
import * as path from 'node:path';
import type { BrowserWindow } from 'electron';

import { FoundryFailure } from './foundry.js';
import { LineBuffer } from './harness/boot.js';
import { Pane } from './harness/pane.js';

/**
 * A read-only look at one archived workbook, in the Univer viewer.
 *
 * The Univer bundle ships a collaboration gateway and a viewer that talks to
 * it. Neither is a file renderer: the viewer opens a *unit* inside a `.univer`
 * container the gateway serves, over HTTP plus a WebSocket. So a preview is
 * four things -- a gateway process, a container holding a copy of the
 * workbook, the one-shot worker that turns xlsx bytes into that copy, and a
 * page pointed at the result -- and this class owns all four so that nothing
 * else has to.
 *
 * What the operator accepted, and what this enforces (KTD20):
 *
 *   1. `UNIVER_ALLOWED_ROOT` is the task's own artifacts directory. Read from
 *      the bytes of `gateway.cjs`: the gateway binds loopback only, has no
 *      authentication, reflects any `Origin` in its CORS headers, and the
 *      root is the one check its `UniverfileManager` makes before opening or
 *      creating a container. With it set, the most any page on the machine
 *      can reach through this gateway is the scratch containers under the
 *      deliverables the operator is already looking at.
 *   2. The gateway runs only while a preview is open. `close()` kills it and
 *      removes the container. The window of exposure is the minutes a
 *      workbook is on screen, not the life of the app.
 *   3. No model is involved. This process talks to the gateway itself; the
 *      thirteen `univer_*` tools stay denied on the close seat (KTD12) and
 *      this path never registers a tool at all.
 *
 * "Read-only" is a property of the archive, not of the page. The viewer's
 * trunk page can be typed into; what it types into is a container derived
 * from the archived bytes, made fresh on every open and deleted on close.
 * The filed `.xlsx` is never opened by the gateway at all -- the worker reads
 * it once and hands over a snapshot.
 *
 * Every wire shape here is read from the bundle's own bytes, not guessed:
 * the worker protocol from `adapters/unit-content/worker.ts`, the routes
 * from `gateway-app/transport/http.ts`, the container key and viewer URL
 * from `adapters/gateway/file-api.ts` and `provider/gateway-univer-service.ts`.
 * The plugin's own path to the same result is `univer_import`, which does
 * exactly this sequence through a draft worktree; this repeats it without
 * the model in the loop.
 *
 * Spawned with Electron's own binary as Node, the same way the harness is.
 * Whether the gateway's native bindings (libsql, the formula engine, the
 * Office exchange) load under that ABI is measured on the first open and
 * nowhere else; a load failure surfaces as the gateway or the worker exiting
 * before it says anything useful, which is reported as itself rather than
 * as a timeout.
 */

/** What the gateway prints once it is listening. Read from `gateway-entry.ts`. */
const READY = /\[dsh-univer-gateway\] listening on (http:\/\/127\.0\.0\.1:\d+)/;

/** `GATEWAY_PORT_IN_USE_EXIT_CODE` in the gateway's own protocol module. */
const PORT_IN_USE = 98;

/**
 * The bundle's documented default, tried upward on a collision.
 *
 * The plugin's own gateway starts at the same number, so an authoring session
 * that has one running is the likeliest collision, and the structured exit
 * code is what tells the two apart from a gateway that could not load.
 */
const FIRST_PORT = 9080;
const PORT_TRIES = 8;

const STARTUP_TIMEOUT_MS = 15_000;
/** The plugin's own `unitContentOperationTimeoutMs` default. */
const IMPORT_TIMEOUT_MS = 120_000;
const REQUEST_TIMEOUT_MS = 10_000;
/** The plugin's own `gatewayMutationTimeoutMs` default. */
const MUTATION_TIMEOUT_MS = 60_000;

/** `UniverType.UNIVER_SHEET` on the wire. */
const SHEET = 2;

/**
 * What the child processes inherit, and nothing else.
 *
 * The same five names the plugin's own launcher forwards to the same
 * programs (`processes/gateway/launcher.ts`). A third-party server gets the
 * environment its author chose for it; it does not get this process's.
 */
const INHERITED = ['HOME', 'LANG', 'LC_ALL', 'PATH', 'TMPDIR'] as const;

export interface PreviewSpec {
  task: string;
  sha256: string;
  origin: string;
}

export interface UniverLayout {
  /** `<staged runtime>/node_modules/dsh-univer-office`. */
  bundleDir: string;
}

/** Where the bundle keeps the three artifacts a preview needs. */
export function gatewayEntry(layout: UniverLayout): string {
  return path.join(layout.bundleDir, 'artifacts', 'gateway.cjs');
}

export function viewerRoot(layout: UniverLayout): string {
  return path.join(layout.bundleDir, 'artifacts', 'viewer');
}

export function workerEntry(layout: UniverLayout): string {
  return path.join(layout.bundleDir, 'artifacts', 'unit-content-worker.mjs');
}

/**
 * Where the gateway and the worker resolve `libsql` and the two native
 * bindings from: the `node_modules` the bundle itself sits in. The plugin
 * sets the same thing for the same reason, in `launcher.ts`.
 */
export function nodePath(layout: UniverLayout): string {
  return path.dirname(layout.bundleDir);
}

/** Whether this build carries the bundle at all. */
export function univerStaged(layout: UniverLayout): boolean {
  return (
    existsSync(gatewayEntry(layout)) &&
    existsSync(workerEntry(layout)) &&
    existsSync(path.join(viewerRoot(layout), 'index.html'))
  );
}

function inherited(parent: NodeJS.ProcessEnv): NodeJS.ProcessEnv {
  const out: NodeJS.ProcessEnv = {};
  for (const name of INHERITED) {
    const value = parent[name];
    if (value !== undefined) out[name] = value;
  }
  return out;
}

function withNodePath(parent: NodeJS.ProcessEnv, own: string): string {
  return [own, parent.NODE_PATH].filter((v): v is string => v !== undefined && v.length > 0).join(path.delimiter);
}

/**
 * The environment the gateway child gets: the five inherited names, the
 * three its entry point reads, and where its natives are.
 */
export function gatewayEnv(
  parent: NodeJS.ProcessEnv,
  own: { port: number; viewerRoot: string; allowedRoot: string; nodePath: string },
): NodeJS.ProcessEnv {
  const out = inherited(parent);
  out.UNIVER_COLLAB_GATEWAY_PORT = String(own.port);
  out.UNIVER_VIEW_ASSETS_ROOT = own.viewerRoot;
  out.UNIVER_ALLOWED_ROOT = own.allowedRoot;
  out.NODE_PATH = withNodePath(parent, own.nodePath);
  // The bundle's telemetry switch is honoured at every entry point.
  out.DO_NOT_TRACK = '1';
  out.ELECTRON_RUN_AS_NODE = '1';
  return out;
}

/** The environment the one-shot worker gets. It reads no `UNIVER_*` name. */
export function workerEnv(parent: NodeJS.ProcessEnv, own: { nodePath: string }): NodeJS.ProcessEnv {
  const out = inherited(parent);
  out.NODE_PATH = withNodePath(parent, own.nodePath);
  out.DO_NOT_TRACK = '1';
  out.ELECTRON_RUN_AS_NODE = '1';
  return out;
}

/** The gateway's name for a container: `base64url` of its absolute path. */
export function fileKey(file: string): string {
  return Buffer.from(file, 'utf8').toString('base64url');
}

/**
 * Where the scratch container for one digest lives.
 *
 * Strictly inside the fence -- the gateway refuses a container *at* the
 * allowed root as well as one outside it -- and named by the digest, so two
 * previews of the same version cannot disagree about which file they mean.
 */
export function containerPath(allowedRoot: string, sha256: string): string {
  return path.join(allowedRoot, 'preview', `${sha256}.univer`);
}

/**
 * The viewer page for a container's trunk, view only, in this app's language.
 *
 * Four switches, all the viewer's own, read from its bundle and measured on
 * the packaged app:
 *
 *   - `mode=embedded` is the layout the plugin's own cards use: no file
 *     sidebar (which showed the container's base64 key as its name) and no
 *     header. The strip above the pane already says which workbook this is.
 *   - `editable=false` is honoured only in that mode -- the URL reader
 *     returns `null` for it in standalone mode, and a trunk unit then loads
 *     editable. Measured: 39 of 42 toolbar controls disabled with it, 27 of
 *     43 without. Without it the trunk page can be typed into -- harmless to
 *     the archive, since what it edits is the scratch container, but a
 *     workbook that says 只读 on its strip should not offer a cell to type in.
 *   - `scope=trunk` names what the embedded layout shows.
 *   - `lang=zh-CN` overrides the viewer's fallback to `navigator.language`,
 *     which inside this app resolved to English.
 */
export function viewerUrl(origin: string, file: string): string {
  return `${origin}/?file=${encodeURIComponent(fileKey(file))}&mode=embedded&scope=trunk&editable=false&lang=zh-CN`;
}

/**
 * The viewer's own appearance switch, read from its bundle.
 *
 * One localStorage key on the viewer's origin, holding `light` or `dark`,
 * default `light`, and no `system`: the viewer never consults
 * `prefers-color-scheme`, which is why `nativeTheme` alone left it white
 * inside a dark window while the harness page went dark beside it.
 */
export const APPEARANCE_KEY = 'univer-collab-client-appearance';

/**
 * A path the gateway answers with a plain-text 404: a document on the
 * viewer's origin that costs no bundle, which is where the key is written
 * before the viewer is loaded. Any non-API path would do; this one says why.
 */
export const APPEARANCE_SEED_PATH = 'appearance';

/** The script that writes the switch. Idempotent; a refused storage is a light viewer, not a failure. */
export function seedAppearance(value: 'light' | 'dark'): string {
  return `(() => { try { localStorage.setItem(${JSON.stringify(APPEARANCE_KEY)}, ${JSON.stringify(value)}); } catch {} })()`;
}

/** Everything sqlite may have left beside a container. */
function removeContainer(file: string): void {
  for (const suffix of ['', '-wal', '-shm', '-journal']) {
    rmSync(`${file}${suffix}`, { force: true });
  }
}

/**
 * What the gateway answers, once its two ways of saying no are one.
 *
 * Read from `transport/http.ts`: a route can answer 4xx with `{error}`, or
 * 200 with `{error: {code: 0, message}}`, or 200 with `{ok: false}`. All
 * three are a refusal with a sentence in it, and the sentence is the part
 * an operator can act on.
 */
async function call(
  origin: string,
  method: 'GET' | 'POST',
  route: string,
  body?: Record<string, unknown>,
  timeoutMs: number = REQUEST_TIMEOUT_MS,
): Promise<Record<string, unknown>> {
  let response: Response;
  try {
    response = await fetch(`${origin}${route}`, {
      method,
      ...(body === undefined
        ? {}
        : { headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }),
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (error) {
    throw new FoundryFailure(
      `the Univer gateway did not answer ${method} ${route}: ${error instanceof Error ? error.message : String(error)}`,
      null,
    );
  }
  let value: unknown;
  try {
    value = await response.json();
  } catch {
    throw new FoundryFailure(`the Univer gateway answered ${method} ${route} with something other than JSON`, null);
  }
  const record = (typeof value === 'object' && value !== null ? value : {}) as Record<string, unknown>;
  const error = record.error as { code?: unknown; message?: unknown } | undefined;
  const refused = !response.ok || record.ok === false || (error !== undefined && error.code === 0);
  if (refused) {
    const message =
      typeof error?.message === 'string' && error.message.length > 0
        ? error.message
        : `HTTP ${response.status}`;
    throw new FoundryFailure(`the Univer gateway refused ${method} ${route}: ${message}`, null);
  }
  return record;
}

export class UniverPreviewHost {
  private readonly pane = new Pane();
  private child: ChildProcess | null = null;
  private origin: string | null = null;
  private spec: PreviewSpec | null = null;
  private container: string | null = null;

  constructor(private readonly layout: UniverLayout) {}

  running(): PreviewSpec | null {
    return this.spec;
  }

  /**
   * Start the gateway with its filesystem fenced to `allowedRoot`.
   *
   * One attempt per port, upward from the bundle's default, and only on the
   * structured "port in use" exit: any other early exit is reported as itself,
   * because the likeliest cause is a native binding that did not load under
   * Electron-as-Node, and a timeout would hide that behind "no banner".
   */
  private async start(allowedRoot: string): Promise<string> {
    if (this.origin) return this.origin;
    if (!univerStaged(this.layout)) {
      throw new FoundryFailure('this build carries no Univer bundle to preview with', null);
    }
    for (let attempt = 0; attempt < PORT_TRIES; attempt += 1) {
      const port = FIRST_PORT + attempt;
      const outcome = await this.spawnOnce(port, allowedRoot);
      if (outcome.kind === 'ready') {
        this.origin = outcome.origin;
        return outcome.origin;
      }
      if (outcome.kind === 'port-in-use') continue;
      throw new FoundryFailure(outcome.message, outcome.status);
    }
    throw new FoundryFailure(
      `no free port for the Univer gateway between ${FIRST_PORT} and ${FIRST_PORT + PORT_TRIES - 1}`,
      null,
    );
  }

  private spawnOnce(
    port: number,
    allowedRoot: string,
  ): Promise<
    | { kind: 'ready'; origin: string }
    | { kind: 'port-in-use' }
    | { kind: 'failed'; message: string; status: number | null }
  > {
    return new Promise((resolve) => {
      const child = spawn(process.execPath, [gatewayEntry(this.layout)], {
        env: gatewayEnv(process.env, {
          port,
          viewerRoot: viewerRoot(this.layout),
          allowedRoot,
          nodePath: nodePath(this.layout),
        }) as NodeJS.ProcessEnv,
        cwd: this.layout.bundleDir,
        stdio: ['ignore', 'pipe', 'pipe'],
      });
      this.child = child;
      const lines = new LineBuffer();
      const errors: string[] = [];
      let settled = false;
      const done = (value: Parameters<typeof resolve>[0]) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        resolve(value);
      };
      const timer = setTimeout(() => {
        child.kill('SIGKILL');
        this.child = null;
        done({
          kind: 'failed',
          message: `the Univer gateway printed no banner in ${STARTUP_TIMEOUT_MS}ms: ${errors.join('').trim() || 'no output'}`,
          status: null,
        });
      }, STARTUP_TIMEOUT_MS);
      child.stdout?.on('data', (chunk: Buffer) => {
        for (const line of lines.push(chunk.toString('utf8'))) {
          const found = READY.exec(line);
          if (found) done({ kind: 'ready', origin: found[1] });
        }
      });
      child.stderr?.on('data', (chunk: Buffer) => {
        errors.push(chunk.toString('utf8'));
      });
      child.on('exit', (code) => {
        if (this.child === child) this.child = null;
        if (code === PORT_IN_USE) return done({ kind: 'port-in-use' });
        done({
          kind: 'failed',
          message: `the Univer gateway exited with ${code}: ${errors.join('').trim() || 'no output'}`,
          status: code,
        });
      });
      child.on('error', (error) => {
        this.child = null;
        done({ kind: 'failed', message: error.message, status: null });
      });
    });
  }

  /**
   * Turn one workbook into a Univer snapshot, in the bundle's own worker.
   *
   * The request and the envelope are the worker's own protocol, read from
   * `adapters/unit-content/worker.ts`: one JSON object on stdin, one on
   * stdout, `{ok: true, result}` or `{ok: false, error: {code, message}}`.
   * An import needs no gateway, which is why it runs before one is started:
   * a workbook the worker cannot read costs no port and no process.
   */
  private importSnapshot(source: string): Promise<Record<string, unknown>> {
    return new Promise((resolve, reject) => {
      const child = spawn(process.execPath, [workerEntry(this.layout)], {
        env: workerEnv(process.env, { nodePath: nodePath(this.layout) }) as NodeJS.ProcessEnv,
        cwd: this.layout.bundleDir,
        stdio: ['pipe', 'pipe', 'pipe'],
      });
      const out: Buffer[] = [];
      const err: Buffer[] = [];
      let timedOut = false;
      const timer = setTimeout(() => {
        timedOut = true;
        child.kill();
      }, IMPORT_TIMEOUT_MS);
      child.stdout.on('data', (chunk: Buffer) => out.push(chunk));
      child.stderr.on('data', (chunk: Buffer) => err.push(chunk));
      child.once('error', (error) => {
        clearTimeout(timer);
        reject(new FoundryFailure(`the Univer worker could not start: ${error.message}`, null));
      });
      child.once('close', (code) => {
        clearTimeout(timer);
        const diagnostic = Buffer.concat(err).toString('utf8').trim().slice(0, 2000);
        if (timedOut) {
          reject(new FoundryFailure(`the Univer worker did not finish the import in ${IMPORT_TIMEOUT_MS}ms`, null));
          return;
        }
        let envelope: { ok?: unknown; result?: unknown; error?: { code?: unknown; message?: unknown } };
        try {
          envelope = JSON.parse(Buffer.concat(out).toString('utf8'));
        } catch {
          reject(
            new FoundryFailure(
              `the Univer worker exited with ${code} and no result: ${diagnostic || 'no output'}`,
              code,
            ),
          );
          return;
        }
        if (envelope.ok === true && typeof envelope.result === 'object' && envelope.result !== null) {
          resolve(envelope.result as Record<string, unknown>);
          return;
        }
        const message =
          typeof envelope.error?.message === 'string' ? envelope.error.message : diagnostic || 'no message';
        const codeName = typeof envelope.error?.code === 'string' ? `${envelope.error.code}: ` : '';
        reject(new FoundryFailure(`the Univer worker refused the workbook: ${codeName}${message}`, code));
      });
      child.stdin.end(JSON.stringify({ operation: 'import', sourcePath: source, unitType: SHEET }));
    });
  }

  /**
   * Show one workbook.
   *
   * `file` is an absolute path the caller has already resolved through the
   * store by digest -- never a path the renderer named. `allowedRoot` must
   * contain it, and it is the directory the gateway is fenced to for the life
   * of this preview.
   *
   * The sequence is the plugin's own `univer_import`, read from
   * `gateway-univer-service.ts`, minus the model: a trunk unit cannot be
   * created with content (the route takes a name and nothing else), so the
   * snapshot goes into a draft worktree and is merged, which is the one
   * write the gateway lets carry a snapshot.
   */
  async open(
    window: BrowserWindow,
    target: {
      task: string;
      sha256: string;
      file: string;
      allowedRoot: string;
      /**
       * What the viewer calls the sheet. The worker names an imported
       * workbook after its source file, which here is sixty-four hex
       * characters; the tab the operator reads should say the task and
       * the version instead. Absent, the digest stands.
       */
      label?: string;
    },
  ): Promise<PreviewSpec> {
    if (!target.file.startsWith(`${target.allowedRoot}${path.sep}`)) {
      throw new FoundryFailure('a preview may only open a file under its own fence', null);
    }
    if (!/^[0-9a-f]{64}$/.test(target.sha256)) {
      throw new FoundryFailure(`not a digest: ${target.sha256}`, null);
    }
    // One at a time. A second open replaces the first, gateway and all, so
    // the fence is always the current task's and never a union of two.
    if (this.spec) this.close(window);

    const snapshot = await this.importSnapshot(target.file);
    const file = containerPath(target.allowedRoot, target.sha256);
    // Fresh every time. A container left from an earlier look could carry
    // whatever was typed into it, and this is a look at the archived bytes.
    removeContainer(file);
    mkdirSync(path.dirname(file), { recursive: true });
    this.container = file;

    try {
      const origin = await this.start(target.allowedRoot);
      const key = fileKey(file);
      await call(origin, 'POST', `/uf/${key}`, {}, MUTATION_TIMEOUT_MS);
      const worktree = await call(
        origin,
        'POST',
        `/uf/${key}/worktrees`,
        { agentId: 'fa-foundry', name: 'preview' },
        MUTATION_TIMEOUT_MS,
      );
      const worktreeId = String(worktree.worktreeId ?? '');
      if (!worktreeId) throw new FoundryFailure('the Univer gateway made a worktree without an id', null);
      const wt = encodeURIComponent(worktreeId);
      const name = target.label ?? `${target.sha256.slice(0, 12)}`;
      // Both the unit's name and the workbook's own: the viewer's tab reads
      // one, its sidebar the other, and a version should be called one thing.
      await call(
        origin,
        'POST',
        `/uf/${key}/worktrees/${wt}/units`,
        { type: SHEET, name, snapshot: { ...snapshot, name } },
        MUTATION_TIMEOUT_MS,
      );
      const merged = await call(origin, 'POST', `/uf/${key}/worktrees/${wt}/merge`, {}, MUTATION_TIMEOUT_MS);
      if (merged.ok !== true) {
        throw new FoundryFailure(
          `the Univer gateway could not merge the imported sheet${merged.conflict === true ? ': conflict' : ''}`,
          null,
        );
      }
      // Dark before the viewer boots. The key is written on the viewer's
      // origin from the gateway's 404 text, then the viewer is loaded; done
      // the other way round the viewer would have to be reloaded, which is a
      // second boot of a 47MB bundle. localStorage is per origin in the
      // default session, so this also holds for every later preview on the
      // same port.
      await this.pane.attach(window, `${origin}/${APPEARANCE_SEED_PATH}`);
      await this.pane.run(seedAppearance('dark'));
      await this.pane.load(viewerUrl(origin, file));
      const spec = { task: target.task, sha256: target.sha256, origin };
      this.spec = spec;
      this.pane.place(window, true);
      return spec;
    } catch (error) {
      this.pane.detach(window);
      this.stopGateway();
      removeContainer(file);
      this.container = null;
      throw error;
    }
  }

  /** Take the page down, kill the gateway, remove the container. Order matters: page first. */
  close(window: BrowserWindow): void {
    this.pane.detach(window);
    this.spec = null;
    this.stopGateway();
    if (this.container) {
      removeContainer(this.container);
      this.container = null;
    }
  }

  place(window: BrowserWindow, visible: boolean): void {
    this.pane.place(window, visible);
  }

  private stopGateway(): void {
    this.child?.kill();
    this.child = null;
    this.origin = null;
  }
}
