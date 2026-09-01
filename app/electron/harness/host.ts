import { spawn, type ChildProcess } from 'node:child_process';

import type { BrowserWindow } from 'electron';

import {
  type Intent,
  LineBuffer,
  PRESET_BY_INTENT,
  defaultPresetPatch,
  STARTUP_TIMEOUT_MS,
  harnessArgs,
  harnessEnv,
  harnessUrlFrom,
  rpcBody,
  rpcUrl,
  rpcValue,
} from './boot.js';
import { followupDraft, handoffScript } from './handoff.js';
import { noticePatch, readNotice } from './notice.js';
import { Pane } from './pane.js';
import { HARNESS_SKIN } from './skin.js';

export interface HostOptions {
  /** The runtime entry, `<install>/node_modules/@deepseek-ai/dsh/lib/bin.js`. */
  entry: string;
  /** The staged runtime's root, for reading what it ships. */
  root?: string;
  /** This app's own harness home. Never the operator's, so a profile edit here is ours. */
  home: string;
  varRoot: string;
  foundryBin: string;
  /** Passed through to the child, so a model calling `launch-formulator` finds it. */
  formulatorBin?: string;
  /** Switches a bundled companion is not allowed to run without. See `resources.ts`. */
  companionEnv?: Record<string, string>;
}

export interface OpenedSession {
  sessionId: string;
  preset: string;
}

/**
 * The runtime as a child process, and its page as a view in this window.
 *
 * What this app owns is the origin the page is pinned to, the directories the
 * runtime may touch, and the rectangle the view occupies. It does not own the
 * page: the conversation, the model picker and the session list are upstream's,
 * which is the point of packing the runtime rather than reimplementing it.
 */
export class HarnessHost {
  private child: ChildProcess | null = null;
  private readonly pane = new Pane();
  private base: string | null = null;
  private starting: Promise<string> | null = null;

  constructor(private readonly opts: HostOptions) {}

  /** The loopback origin, once the banner has named it. */
  origin(): string | null {
    return this.base;
  }

  /** Spawn once; every later caller waits on the same start. */
  start(): Promise<string> {
    if (this.base) return Promise.resolve(this.base);
    if (this.starting) return this.starting;
    this.starting = new Promise<string>((resolve, reject) => {
      const child = spawn(process.execPath, harnessArgs(this.opts.entry), {
        env: harnessEnv(process.env, {
          home: this.opts.home,
          varRoot: this.opts.varRoot,
          foundryBin: this.opts.foundryBin,
          formulatorBin: this.opts.formulatorBin,
          companionEnv: this.opts.companionEnv,
        }) as NodeJS.ProcessEnv,
        stdio: ['ignore', 'pipe', 'pipe'],
      });
      this.child = child;
      const lines = new LineBuffer();
      const timer = setTimeout(() => {
        reject(new Error(`the harness printed no URL in ${STARTUP_TIMEOUT_MS}ms`));
      }, STARTUP_TIMEOUT_MS);
      const settle = (chunk: Buffer) => {
        for (const line of lines.push(chunk.toString('utf8'))) {
          const found = harnessUrlFrom(line);
          if (found) {
            clearTimeout(timer);
            this.base = found;
            resolve(found);
          }
        }
      };
      child.stdout?.on('data', settle);
      child.stderr?.on('data', (chunk: Buffer) => process.stderr.write(chunk));
      child.on('exit', (code) => {
        clearTimeout(timer);
        this.child = null;
        this.base = null;
        this.starting = null;
        reject(new Error(`the harness exited with ${code}`));
      });
    });
    return this.starting;
  }

  /** One RPC against the running runtime. */
  private async rpc(method: string, payload: Record<string, unknown>): Promise<unknown> {
    const origin = await this.start();
    const response = await fetch(rpcUrl(origin, method), {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: rpcBody(method, payload),
    });
    if (!response.ok) throw new Error(`${method} answered ${response.status}`);
    return rpcValue(method, await response.json());
  }

  /**
   * Open a conversation on the preset the button chose.
   *
   * The preset is not a suggestion the operator can drift off: `session.create`
   * takes it, records it on the session's creation header, and the runtime
   * composes that agent from it. A follow-up opened here is offered
   * `query-locked` and nothing else.
   *
   * The conversation is also given somewhere to stand, which is the other half
   * of the same fence: a preset says which tools exist, `cwd` says how far the
   * ones that take a path can reach.
   */
  async open(
    intent: Intent,
    cwd: string,
    seed?: { windowId: string; briefSha?: string | null },
  ): Promise<OpenedSession> {
    const preset = PRESET_BY_INTENT[intent];
    // `cwd` is not a convenience. Every tool that takes a path resolves it
    // against the session's own directory, and a session created without one
    // stands in the host's -- measured as `/` on a Finder launch. See
    // `workspace.ts`.
    const created = (await this.rpc('session.create', { agentPreset: preset, cwd })) as {
      sessionId?: string;
    } | null;
    const sessionId = created?.sessionId;
    if (!sessionId) throw new Error('session.create returned no session id');
    const draft = intent === 'followup' && seed ? followupDraft(seed) : '';
    await this.show(sessionId, draft);
    return { sessionId, preset };
  }

  /** Point the view at the new session and reload so the page reads the cell. */
  private async show(sessionId: string, draft: string): Promise<void> {
    const origin = await this.start();
    if (!this.pane.attached()) return;
    await this.pane.run(handoffScript(sessionId, draft));
    await this.pane.load(origin);
  }

  /**
   * Answer the runtime's developer-preview dialog before anyone sees it.
   *
   * Best effort, and deliberately so: the fallback is that an operator reads a
   * notice meant for Harness developers and presses Continue, which costs a
   * click. Failing the whole start over it would cost the workbench.
   */
  async dismissDeveloperNotice(): Promise<boolean> {
    if (!this.opts.root) return false;
    const notice = readNotice(this.opts.root);
    if (!notice) return false;
    try {
      await this.rpc('settings.update', noticePatch(notice));
      return true;
    } catch {
      return false;
    }
  }

  /**
   * Point the runtime's own default at this product's period preset.
   *
   * Best effort, like the notice: the fallback is a picker that opens on
   * `standard`, which is a label an operator can change and not a fence they
   * can cross -- the page cannot create a session on any preset at all.
   */
  async makePeriodTheDefault(): Promise<boolean> {
    try {
      await this.rpc('settings.update', defaultPresetPatch());
      return true;
    } catch {
      return false;
    }
  }

  /** Put the page in the window. Called once, after the first start. */
  async attach(window: BrowserWindow): Promise<void> {
    // Before the load, so the first paint already carries it.
    this.pane.skin(HARNESS_SKIN);
    await this.pane.attach(window, await this.start());
  }

  /** Show or hide the page by giving it a rectangle or none. */
  place(window: BrowserWindow, visible: boolean): void {
    this.pane.place(window, visible);
  }

  stop(): void {
    this.child?.kill();
    this.child = null;
    this.base = null;
    this.starting = null;
  }
}
