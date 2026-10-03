import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const read = (path: string) => readFileSync(fileURLToPath(new URL(path, import.meta.url)), 'utf8');
const TOKENS = read('../src/styles/tokens.css');
const EXPORT = read('../electron/reports/format.ts');

const token = (name: string) => {
  const match = new RegExp(`--${name}:\\s*([^;]+);`).exec(TOKENS);
  if (!match) throw new Error(`no --${name}`);
  return match[1].trim();
};
/** font-size, line-height and font-weight of one heading rule in the exported HTML stylesheet. */
const exported = (selector: string) => {
  const match = new RegExp(`(?:^|\\n)${selector}\\{([^}]*)\\}`).exec(EXPORT);
  if (!match) throw new Error(`no ${selector} in export css`);
  const value = (property: string) => new RegExp(`${property}:([^;]+)`).exec(match[1])?.[1].trim();
  return [value('font-size'), value('line-height'), value('font-weight')];
};

describe('document heading scale', () => {
  // The editor, both reading views and the exported HTML show the same hierarchy (audit P2-10, decision 5A).
  it('matches the exported HTML heading sizes', () => {
    expect(exported('h1')).toEqual([token('fnd-doc-title'), token('fnd-doc-title-leading'), token('fnd-doc-title-weight')]);
    expect(exported('h2')).toEqual([token('fnd-doc-chapter'), token('fnd-doc-chapter-leading'), token('fnd-doc-chapter-weight')]);
    expect(exported('h3')).toEqual([token('fnd-doc-section'), token('fnd-doc-section-leading'), token('fnd-doc-heading-weight')]);
    expect(exported('h4,h5,h6')).toEqual([token('fnd-doc-sub'), token('fnd-doc-sub-leading'), token('fnd-doc-heading-weight')]);
  });

  it('leaves no literal heading size in the in-app document views', () => {
    const css = read('../src/views/analysis/report.css') + read('../src/views/analysis.css');
    const literal = css.split('\n').filter((line) => /\.(report-prosemirror|report-reading|analysis-draft-reading|analysis-draft-body) h[1-6][^{]*\{[^}]*font-size:\s*\d/.test(line));
    expect(literal).toEqual([]);
  });
});
