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

/** Top-level statements that open a style rule outside any @layer block. :root token blocks only define custom properties. */
function unlayeredRules(css: string): string[] {
  const text = css.replace(/\/\*[\s\S]*?\*\//g, (comment) => comment.replace(/[^\n]/g, ' '));
  const found: string[] = [];
  let depth = 0;
  let statement = '';
  for (const char of text) {
    if (char === '{') {
      const head = statement.trim();
      if (depth === 0 && !head.startsWith('@') && !head.startsWith(':root')) found.push(head);
      depth += 1;
      statement = '';
    } else if (char === '}') {
      depth -= 1;
      statement = '';
    } else if (char === ';' && depth === 0) {
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

  it('sizes text from the type scale, not fractional rem values', () => {
    const offenders = sheets(SRC).flatMap((path) => (readFileSync(path, 'utf8').match(/font-size:\s*[0-9.]+rem/g) ?? []).map((hit) => `${path.slice(SRC.length + 1)}: ${hit}`));
    expect(offenders).toEqual([]);
  });
});
