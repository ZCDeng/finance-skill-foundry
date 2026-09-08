import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import {
  CSP_HEADER_NAME,
  CSP_HEADER_VALUE,
  DEV_CSP_HEADER_VALUE,
  DEV_ORIGIN,
  applyCsp,
  ownDocument,
} from '../electron/csp.js';

const read = (rel: string) => readFileSync(fileURLToPath(new URL(rel, import.meta.url)), 'utf8');

const HARNESS = 'http://127.0.0.1:59370/';
const FORMULATOR = 'http://127.0.0.1:5000/';
const OWN = 'file:///A/Foundry.app/Contents/Resources/app.asar/dist-vite/index.html';

describe('whose document the policy is written for', () => {
  /*
   * The policy is installed on `session.defaultSession`, which is every response
   * the application receives -- and two of the three pages in this window are
   * served by child processes this app spawns. Rewriting their headers gave the
   * harness page `default-src 'none'`: no `connect-src` for the calls its UI
   * makes to its own server, no `unsafe-inline` for the boot script that mounts
   * it, no `data:` for the faces it inlines. The document arrived, `#root`
   * stayed empty, and the workbench was a blank rectangle.
   */
  it('claims this app’s own page', () => {
    expect(ownDocument(OWN)).toBe(true);
    expect(ownDocument('file:///anything.html')).toBe(true);
  });

  it('leaves the embedded servers to their own headers', () => {
    expect(ownDocument(HARNESS)).toBe(false);
    expect(ownDocument(FORMULATOR)).toBe(false);
    // Also under a dev run, where this app is itself served over http.
    expect(ownDocument(HARNESS, true)).toBe(false);
    expect(ownDocument(FORMULATOR, true)).toBe(false);
  });

  it('claims the dev server only while the run is a dev run', () => {
    expect(ownDocument(`${DEV_ORIGIN}/index.html`, true)).toBe(true);
    expect(ownDocument(`${DEV_ORIGIN}/index.html`, false)).toBe(false);
  });

  it('is consulted before the policy is applied, not after', () => {
    /*
     * `toBeGreaterThan(-1)` first: `indexOf` gives -1 for a call that is not
     * there, and -1 comes before every real index, so without this the ordering
     * assertion passes most confidently when the guard has been deleted.
     */
    const main = read('../electron/main.ts');
    const guard = main.indexOf('ownDocument(details.url');
    const apply = main.indexOf('applyCsp(details.responseHeaders');
    expect(guard, 'main.ts never consults ownDocument').toBeGreaterThan(-1);
    expect(apply, 'main.ts never applies the policy').toBeGreaterThan(-1);
    expect(guard).toBeLessThan(apply);
  });
});

describe('the policy itself', () => {
  it('replaces a policy already on the response rather than adding a second', () => {
    // Two CSP headers intersect, which sounds safe and makes the effective
    // policy depend on whatever some other layer happened to send.
    const out = applyCsp({ 'content-security-policy': ['default-src *'], 'x-frame-options': ['DENY'] });
    expect(out[CSP_HEADER_NAME]).toEqual([CSP_HEADER_VALUE]);
    expect(Object.keys(out).filter((k) => k.toLowerCase() === 'content-security-policy')).toHaveLength(1);
    expect(out['x-frame-options']).toEqual(['DENY']);
  });

  it('names the two directives that do not inherit from default-src', () => {
    // `base-uri` and `form-action` are not covered by `default-src 'none'`.
    expect(CSP_HEADER_VALUE).toContain("base-uri 'none'");
    expect(CSP_HEADER_VALUE).toContain("form-action 'none'");
  });

  it('serves the bundled faces, which the default would otherwise block', () => {
    expect(CSP_HEADER_VALUE).toContain("font-src 'self'");
  });

  it('opens nothing extra in the packaged policy', () => {
    // The dev additions describe the dev server. A packaged window loads from
    // file:// and must never see them.
    expect(CSP_HEADER_VALUE.split('; ').find((value) => value.startsWith('script-src'))).toBe("script-src 'self'");
    expect(CSP_HEADER_VALUE).toContain("object-src 'none'");
    expect(CSP_HEADER_VALUE).toContain("img-src 'self' data:");
    expect(CSP_HEADER_VALUE).not.toContain('ws://');
    expect(DEV_CSP_HEADER_VALUE).toContain('unsafe-inline');
  });
});
