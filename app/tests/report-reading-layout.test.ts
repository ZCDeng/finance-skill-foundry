import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const css = readFileSync(fileURLToPath(new URL('../src/views/analysis/report.css', import.meta.url)), 'utf8');
const rules = (selector: RegExp) => css.split('\n').filter((line) => selector.test(line.split('{')[0] ?? ''));

describe('reading view tables and outline', () => {
  it('aligns cells by their num/text mark, not by column position', () => {
    expect(css).not.toMatch(/:not\(:first-child\)[^{]*\{[^}]*text-align:\s*right/);
    expect(css).toContain('.report-reading :is(td, th).num { text-align: right; }');
  });

  it('keeps numbers whole and lets a wide table scroll', () => {
    expect(css).toContain('.report-reading :is(td, th) { overflow-wrap: break-word; }');
    const nowrap = rules(/\S/).filter((line) => /white-space:\s*nowrap/.test(line) && line.includes('.report-reading'));
    expect(nowrap).toEqual(['.report-reading td.num, .report-reading td.num p { white-space: nowrap; overflow-wrap: normal; }']);
    expect(css).toMatch(/\.report-reading \.financial-table \{[^}]*overflow-x: auto;/);
  });

  it('centres one 56rem text column while the outline is folded', () => {
    expect(css).toMatch(/\.report-shell:not\(\[data-outline-expanded='true'\]\) \{ grid-template-columns: minmax\(0, 1fr\); max-width: 56rem; \}/);
    expect(css).toMatch(/\.report-shell \{[^}]*max-width: calc\(200px \+ 32px \+ 56rem\);/);
  });
});
