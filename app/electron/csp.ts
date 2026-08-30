/**
 * Content Security Policy.
 *
 * Injected on every response rather than written into index.html, so a renderer
 * cannot end up without one because a document loaded by a path that skipped the
 * meta tag.
 *
 * `default-src 'none'` and then only what this app actually serves. There is no
 * `img-src` beyond `'self'` because nothing here renders a bitmap: a foundry
 * deliverable is markdown. `font-src 'self'` is required rather than optional --
 * the two bundled faces would otherwise fall through to the `'none'` default and
 * be blocked in the packaged app only, where no dev server is serving a laxer
 * policy to hide it.
 *
 * `base-uri` and `form-action` do not inherit from `default-src`, so leaving
 * them out would leave both open despite the default.
 */
export const CSP_DIRECTIVES = [
  "default-src 'none'",
  "img-src 'self'",
  "font-src 'self'",
  "style-src 'self'",
  "script-src 'self'",
  "base-uri 'none'",
  "form-action 'none'",
] as const;

export const CSP_HEADER_VALUE = CSP_DIRECTIVES.join('; ');

/**
 * What the dev server needs, and only it.
 *
 * Vite injects the react-refresh preamble as an inline module and talks to its
 * HMR server over a websocket, and it serves every stylesheet as a JS module
 * that appends a `<style>` element -- so under the packaged policy a dev window
 * renders its structure with no styling at all, which reads like an unfinished
 * product rather than like a blocked stylesheet. All three additions describe
 * the dev server; the packaged app loads from file:// and never sees them.
 */
export const DEV_CSP_DIRECTIVES = CSP_DIRECTIVES.map((directive) => {
  if (directive.startsWith('script-src')) return `${directive} 'unsafe-inline'`;
  if (directive.startsWith('style-src')) return `${directive} 'unsafe-inline'`;
  if (directive.startsWith('default-src')) return `${directive}; connect-src 'self' ws://localhost:5273`;
  return directive;
});

export const DEV_CSP_HEADER_VALUE = DEV_CSP_DIRECTIVES.join('; ');

export const CSP_HEADER_NAME = 'Content-Security-Policy';

export type IncomingHeaders = Record<string, string | string[] | undefined>;
export type HeaderBag = Record<string, string | string[]>;

/**
 * The response headers with the policy applied.
 *
 * Any policy already present is replaced rather than merged: two CSP headers
 * intersect, which sounds safe but makes the effective policy depend on what
 * some other layer happened to send.
 */
export function applyCsp(responseHeaders: IncomingHeaders = {}, isDev = false): HeaderBag {
  const cleaned: HeaderBag = {};
  for (const [name, value] of Object.entries(responseHeaders)) {
    if (value === undefined) continue;
    if (name.toLowerCase() !== CSP_HEADER_NAME.toLowerCase()) cleaned[name] = value;
  }
  cleaned[CSP_HEADER_NAME] = [isDev ? DEV_CSP_HEADER_VALUE : CSP_HEADER_VALUE];
  return cleaned;
}
