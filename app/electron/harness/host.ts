import { spawn, type ChildProcess } from 'node:child_process';
import { basename, join } from 'node:path';
import { readFileSync } from 'node:fs';

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
import { followupDraft, residentHandoffScript, snapshotDraftsScript, restoreDraftsScript, type EmbeddedReply } from './handoff.js';
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
  /** Root consumed by dsh-skill-filesystem as this product's bundled skills. */
  bundledSkillDir?: string;
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
  private paneOrigin: string | null = null;
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
          bundledSkillDir: this.opts.bundledSkillDir,
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
    const reply = await response.json();
    try {
      return rpcValue(method, reply);
    } catch (error) {
      const code = (reply as { result?: { error?: { code?: unknown } } } | null)?.result?.error?.code;
      if (error instanceof Error && typeof code === 'string') Object.assign(error, { code });
      throw error;
    }
  }

  /** Adopt the task directory in the runtime's persistent workspace registry. */
  private async ensureWorkspace(cwd: string, title?: string): Promise<string> {
    const registered = await this.rpc('workspace.create', { path: cwd }) as {
      workspace?: { workspaceId?: unknown; title?: unknown };
    } | null;
    const workspaceId = registered?.workspace?.workspaceId;
    if (typeof workspaceId !== 'string' || !workspaceId.trim()) {
      throw new Error('workspace.create returned no workspace id');
    }
    const label = title?.trim();
    if (label && label !== registered?.workspace?.title && registered?.workspace?.title === basename(cwd)) {
      for (const candidate of [label, `${label} · ${workspaceId.slice(-8)}`]) {
        try {
          await this.rpc('workspace.rename', { workspaceId, title: candidate });
          break;
        } catch (error) {
          // A title collision is cosmetic. Other RPC failures still surface;
          // they must not masquerade as a working workspace or connection.
          if (!(error instanceof Error && 'code' in error && error.code === 'workspace-name-conflict')) throw error;
        }
      }
    }
    return workspaceId;
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
    deferShow = false,
  ): Promise<OpenedSession> {
    const preset = PRESET_BY_INTENT[intent];
    // The registered workspace supplies cwd and the client conversation's
    // workspace association. A bare cwd leaves the composer without a workspace.
    const workspaceId = await this.ensureWorkspace(cwd);
    const created = (await this.rpc('session.create', { agentPreset: preset, workspaceId })) as {
      sessionId?: string;
    } | null;
    const sessionId = created?.sessionId;
    if (!sessionId) throw new Error('session.create returned no session id');
    const draft = intent === 'followup' && seed ? followupDraft(seed) : '';
    if (!deferShow) await this.show(sessionId, draft);
    return { sessionId, preset };
  }

  /** Select a resident native session; passive resume preserves its input machine. */
  async show(sessionId: string, draft?: string, cwd?: string, workspaceTitle?: string,
    action?: {submit?: boolean; requestId?: string}): Promise<EmbeddedReply> {
    const origin = await this.start();
    if (!this.pane.attached()) throw new Error('对话窗口尚未连接，请重新打开对话。');
    if (cwd !== undefined) {
      const workspaceId = await this.ensureWorkspace(cwd, workspaceTitle);
      const attached = await this.rpc('session.create', { sessionId, workspaceId }) as {
        sessionId?: unknown;
      } | null;
      if (attached?.sessionId !== sessionId) {
        throw new Error('session.create returned a different session id while restoring the workspace');
      }
    }
    // A restarted runtime gets a new port. Its storage belongs to that new
    // origin, while the pane still holds the previous runtime's document.
    if (this.paneOrigin !== origin) {
      const drafts = await this.pane.run(snapshotDraftsScript) as Record<string, unknown> | undefined;
      await this.pane.load(origin);
      this.paneOrigin = origin;
      if (drafts && Object.keys(drafts).length) {
        await this.pane.run(restoreDraftsScript(drafts));
        // New origins have separate browser stores. Restore before constructing
        // the new conversation stores; same-origin task switches never reload.
        await this.pane.load(origin);
      }
    }
    const reply = await this.pane.run(residentHandoffScript({sessionId, draft, ...action})) as EmbeddedReply | undefined;
    if (reply?.sessionId !== sessionId) throw new Error('对话未能恢复到当前任务，请重试。');
    if (draft !== undefined) this.pane.focus();
    return reply;
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
    let font = '';
    if (this.opts.root) {
      const bytes = readFileSync(join(this.opts.root, 'assets/fonts/NotoSansSC-variable.woff2'));
      font = `@font-face{font-family:'Noto Sans SC';src:url(data:font/woff2;base64,${bytes.toString('base64')}) format('woff2');font-style:normal;font-weight:100 900;font-display:swap;}`;
    }
    this.pane.skin(font + HARNESS_SKIN);
    const origin = await this.start();
    await this.pane.attach(window, origin);
    this.paneOrigin = origin;
  }

  /** Show or hide the page by giving it a rectangle or none. */
  place(window: BrowserWindow, visible: boolean): void {
    this.pane.place(window, visible);
  }

  layout(window: BrowserWindow, value: unknown, zoom: number): boolean {
    return this.pane.layout(window, value, zoom);
  }

  stop(): void {
    this.child?.kill();
    this.child = null;
    this.base = null;
    this.starting = null;
  }
}
