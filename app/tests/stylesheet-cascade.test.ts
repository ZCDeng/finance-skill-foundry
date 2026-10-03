import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const SRC = fileURLToPath(new URL('../src', import.meta.url));

function sheets(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sheets(path);
    return name.endsWith('.css') ? [path] : [];
  });
}

/** Conditional group rules can hold style rules of their own; @layer, @font-face, @keyframes and the like cannot leak them. */
const GROUP = /^@(media|supports|container|scope|starting-style|document)\b/;
/** A bare :root (optionally with attribute or :not([…]) conditions) only defines custom properties; `:root .card` is a style rule. */
const TOKENS = /^:root(\[[^\]]*\]|:not\(\[[^\]]*\]\))*$/;

/** Style rules that sit outside any @layer block, including inside top-level @media/@supports/@container. */
function unlayeredRules(css: string): string[] {
  const text = css.replace(/\/\*[\s\S]*?\*\//g, (comment) => comment.replace(/[^\n]/g, ' '));
  const found: string[] = [];
  // Each open block: whether rules directly inside it are unlayered.
  const stack: boolean[] = [];
  let statement = '';
  for (const char of text) {
    if (char === '{') {
      const head = statement.trim().replace(/\s+/g, ' ');
      const exposed = stack.length === 0 || stack[stack.length - 1];
      if (exposed && !head.startsWith('@') && !TOKENS.test(head)) found.push(head);
      stack.push(exposed && GROUP.test(head));
      statement = '';
    } else if (char === '}') {
      stack.pop();
      statement = '';
    } else if (char === ';') {
      statement = '';
    } else {
      statement += char;
    }
  }
  return found;
}

describe('stylesheet cascade', () => {
  // Unlayered rules beat every layer, so they silently override control states and utilities (DESIGN.md 样式级联).
  it.each(sheets(SRC).map((path) => [path.slice(SRC.length + 1), path]))('%s keeps every rule inside a cascade layer', (_name, path) => {
    expect(unlayeredRules(readFileSync(path, 'utf8'))).toEqual([]);
  });

  it('finds rules hidden in top-level conditional blocks and :root descendants', () => {
    const probe = ':root { --a: 1; }\n:root[data-theme="dark"] { --a: 2; }\n:root .y { color: red; }\n@media (min-width: 1px) { .x { color: red; } }\n@supports (display: grid) { @media print { .z { color: red; } } }\n@layer layout { @media print { .ok { color: red; } } }\n@font-face { font-family: x; }';
    expect(unlayeredRules(probe)).toEqual([':root .y', '.x', '.z']);
  });

  it('sizes text from the type scale, not fractional rem values', () => {
    const offenders = sheets(SRC).flatMap((path) => (readFileSync(path, 'utf8').match(/font-size:\s*[0-9.]+rem/g) ?? []).map((hit) => `${path.slice(SRC.length + 1)}: ${hit}`));
    expect(offenders).toEqual([]);
  });
});
