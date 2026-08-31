import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import {
  FENCED_METHODS,
  FENCE_REASON,
  type FencedMethod,
  fencedMethod,
  installFence,
} from '../electron/harness/fence.js';

const HARNESS = 'http://127.0.0.1:49980';
/** Formulator's own loopback server, which this fence has no business touching. */
const FORMULATOR = 'http://127.0.0.1:5567';

describe('what the embedded page may not do', () => {
  it('names the three calls that would make a session nothing accounts for', () => {
    // `session.create` is the New Session button. `session.fork` is the same
    // outcome under another name -- it answers with a new session id. And
    // `agentPreset.select` re-presets a session that is already open, which is
    // the fence for 追问 (query-locked only) taken off from the side.
    expect([...FENCED_METHODS].sort()).toEqual([
      'agentPreset.select',
      'session.create',
      'session.fork',
    ]);
  });

  it('catches each of them on the harness origin', () => {
    for (const method of FENCED_METHODS) {
      expect(fencedMethod(`${HARNESS}/api/${method}`, HARNESS)).toBe(method);
    }
  });

  /*
   * Everything the runtime does that is not creating a session goes through the
   * same `/api/` path. A fence that took the path alone would stop the page
   * talking at all -- typing, listing, cancelling, reading history.
   */
  it("lets the rest of the page's own traffic through", () => {
    for (const method of [
      'session.prompt',
      'session.list',
      'session.cancel',
      'session.history',
      'session.rename',
      'agentPreset.list',
      'settings.update',
      'events.mux',
    ]) {
      expect(fencedMethod(`${HARNESS}/api/${method}`, HARNESS)).toBeNull();
    }
  });

  it('leaves the other embedded server alone', () => {
    // Formulator is served on its own loopback port. Same shape of URL, and not
    // this fence's business.
    expect(fencedMethod(`${FORMULATOR}/api/session.create`, HARNESS)).toBeNull();
  });

  it('does nothing before the harness has an origin', () => {
    // The banner names the port after the child is up, and requests exist in
    // the window before that. A null origin must not match everything.
    expect(fencedMethod(`${HARNESS}/api/session.create`, null)).toBeNull();
  });

  it('matches the whole path segment, not a prefix of it', () => {
    expect(fencedMethod(`${HARNESS}/api/session.createx`, HARNESS)).toBeNull();
    expect(fencedMethod(`${HARNESS}/api/session.create/extra`, HARNESS)).toBeNull();
    expect(fencedMethod(`${HARNESS}/session.create`, HARNESS)).toBeNull();
  });

  it('refuses to guess at something that is not a URL', () => {
    expect(fencedMethod('not a url', HARNESS)).toBeNull();
    expect(fencedMethod('', HARNESS)).toBeNull();
  });

  it('has a sentence for every call it blocks, naming the way in that works', () => {
    // A refusal that does not say what to press instead reads as a broken
    // button, which is what this replaced.
    for (const method of FENCED_METHODS) {
      const reason = FENCE_REASON[method];
      expect(reason.length).toBeGreaterThan(20);
    }
    expect(FENCE_REASON['session.create']).toContain('开始本期');
    expect(FENCE_REASON['session.fork']).toContain('追问');
    expect(FENCE_REASON['agentPreset.select']).toContain('query-locked');
  });
});

describe('the fence on a session', () => {
  /** Enough of an Electron session to drive the listener the installer registers. */
  function stub() {
    let listener: ((details: { url: string }, cb: (r: { cancel?: boolean }) => void) => void) | null =
      null;
    let filter: { urls: string[] } | null = null;
    const session = {
      webRequest: {
        onBeforeRequest(f: { urls: string[] }, l: typeof listener) {
          filter = f;
          listener = l;
        },
      },
    };
    return {
      session,
      ask(url: string) {
        let answer: { cancel?: boolean } = {};
        listener?.({ url }, (r) => {
          answer = r;
        });
        return answer;
      },
      get filter() {
        return filter;
      },
    };
  }

  it('cancels a fenced call and says which one', () => {
    const s = stub();
    const refused: FencedMethod[] = [];
    installFence(s.session as never, {
      origin: () => HARNESS,
      onRefused: (method) => refused.push(method),
    });
    expect(s.ask(`${HARNESS}/api/session.create`)).toEqual({ cancel: true });
    expect(refused).toEqual(['session.create']);
  });

  it('gets out of the way of everything else, without reporting it', () => {
    const s = stub();
    const refused: FencedMethod[] = [];
    installFence(s.session as never, {
      origin: () => HARNESS,
      onRefused: (method) => refused.push(method),
    });
    expect(s.ask(`${HARNESS}/api/session.prompt`)).toEqual({});
    expect(s.ask(`${FORMULATOR}/api/session.create`)).toEqual({});
    expect(refused).toEqual([]);
  });

  it('asks to see every http request, and decides in the handler', () => {
    // A narrower url filter would be a second place the rule is written, and
    // the one that fails silently: a request the filter never matched is a
    // request `fencedMethod` never gets to refuse.
    const s = stub();
    installFence(s.session as never, { origin: () => HARNESS, onRefused: () => {} });
    expect(s.filter).toEqual({ urls: ['*://*/*'] });
  });

  it('reads the origin at request time, not at install time', () => {
    // The fence is installed before the child has printed its banner, so an
    // origin captured once would be null for the life of the window.
    const s = stub();
    let origin: string | null = null;
    installFence(s.session as never, { origin: () => origin, onRefused: () => {} });
    expect(s.ask(`${HARNESS}/api/session.create`)).toEqual({});
    origin = HARNESS;
    expect(s.ask(`${HARNESS}/api/session.create`)).toEqual({ cancel: true });
  });
});

describe('the calls this fence names', () => {
  /*
   * Coupling to method names upstream owns. A rename there has to become a red
   * test rather than a fence that quietly stops covering the button it was
   * built for.
   */
  it('are still the ones the installed runtime registers', () => {
    const registry = fileURLToPath(
      new URL('../extra/dsh/node_modules/@deepseek-ai/dsh-host-apiproxy/lib/index.js', import.meta.url),
    );
    if (!existsSync(registry)) return;
    const source = readFileSync(registry, 'utf8');
    for (const method of FENCED_METHODS) {
      expect(source).toContain(`"${method}"`);
    }
  });

  it('are reached at the path this fence watches', () => {
    // `postJson('/api/' + method)` is the client's one transport for a unary
    // call. If that ever became a websocket frame, cancelling a request would
    // stop cancelling anything.
    const client = fileURLToPath(
      new URL('../extra/dsh/node_modules/@deepseek-ai/dsh-host-apiproxy/lib/index.js', import.meta.url),
    );
    if (!existsSync(client)) return;
    expect(readFileSync(client, 'utf8')).toContain('/api/${method}');
  });
});
