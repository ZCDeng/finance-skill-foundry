import type { Session } from 'electron';

/**
 * What the embedded page may not do.
 *
 * The runtime's own page carries a New Session button, a fork action and a
 * preset picker. All three produce a conversation this product cannot account
 * for: a session made in the page is never registered against a task, so the
 * period tools it can still reach resolve their task from whatever window
 * happens to be current -- which is some other task's, or the last one anybody
 * touched. The strip above the page said so, and saying so is not the same as
 * stopping it.
 *
 * Blocked at the request rather than in the page's markup. Hiding a button is
 * cosmetic: the same call is one keyboard shortcut, one command palette entry
 * or one upstream redesign away, and a fence that depends on a selector is a
 * fence that opens quietly the next time the runtime is bumped. Every one of
 * these is a `POST /api/<method>` on the loopback origin this app started
 * (`dsh-host-apiproxy`, `postJson('/api/' + method)`), so the origin plus the
 * path is the whole surface.
 *
 * This app's own calls are not affected, and that is structural rather than
 * lucky: `webRequest` observes Chromium's network stack for one session, and
 * `HarnessHost.rpc` runs on the main process's `fetch`, which is Node's. The
 * page and this app reach the same server down two different stacks, and only
 * one of them passes through here.
 */

/** The three calls that would produce a session this product cannot account for. */
export const FENCED_METHODS = ['session.create', 'session.fork', 'agentPreset.select'] as const;

export type FencedMethod = (typeof FENCED_METHODS)[number];

/**
 * What to say, per call, where the operator is looking.
 *
 * Written for someone who just pressed something and watched nothing happen.
 * Each one names the way in that does the same job, because refusing without
 * naming the alternative is how a fence reads as a broken button.
 */
export const FENCE_REASON: Record<FencedMethod, string> = {
  'session.create': '请在分析页选择或新建任务，再点「继续分析」。资料和对话会一起保存在这个任务里。',
  'session.fork': '请在当前对话中提出拆分调查或继续追问；助手会创建关联到当前任务的子任务。',
  'agentPreset.select': '当前对话已关联到任务。新的分析能力请从分析页进入；旧版期间流程仍可在上方选择。',
};

/** The RPC method a URL names, if it is one this app fences on that origin. */
export function fencedMethod(url: string, origin: string | null): FencedMethod | null {
  if (!origin) return null;
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return null;
  }
  if (parsed.origin !== origin) return null;
  const method = parsed.pathname.startsWith('/api/') ? parsed.pathname.slice(5) : '';
  return (FENCED_METHODS as readonly string[]).includes(method) ? (method as FencedMethod) : null;
}

export interface FenceOptions {
  /** Read at request time: the harness has no origin until its banner names one. */
  origin(): string | null;
  /** Told what was refused, so the window can say it rather than the page. */
  onRefused(method: FencedMethod): void;
}

/**
 * Install the fence on one session.
 *
 * Every http(s) request in the session is offered to `fencedMethod`, which is a
 * string comparison against a live origin. `file://` never reaches here, and
 * Formulator's own loopback origin is a different one, so both fall through on
 * the origin check before anything else is looked at.
 */
export function installFence(session: Session, options: FenceOptions): void {
  session.webRequest.onBeforeRequest({ urls: ['*://*/*'] }, (details, callback) => {
    const method = fencedMethod(details.url, options.origin());
    if (!method) return callback({});
    options.onRefused(method);
    callback({ cancel: true });
  });
}
