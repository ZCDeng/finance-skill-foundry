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
    expect(nowrap).toEqual(['.report-reading td.num:not(.note), .report-reading td.num:not(.note) p { white-space: nowrap; overflow-wrap: normal; }']);
    expect(css).toContain('.report-reading :is(td, th).text { min-width: 4em; }');
    expect(css).toContain('.report-reading :is(td, th):first-child { word-break: keep-all; }');
    expect(css).toMatch(/\.report-reading \.financial-table \{[^}]*overflow-x: auto;/);
  });

  it('keeps one 56rem text column and opens the outline beside it only when both fit', () => {
    expect(css).toMatch(/\.report-shell \{[^}]*grid-template-columns: minmax\(0, 1fr\);[^}]*max-width: 56rem;/);
    // The toolbar grid does not change with the outline.
    expect(css).toMatch(/\.report-toolbar \{[^}]*grid-template-columns: minmax\(0, 1fr\);/);
    expect(css).not.toMatch(/data-outline-expanded[^{]*> \.report-toolbar/);
    // A drawer by default, out of the grid flow; a 200px column only from 896px + 232px of workspace.
    expect(css).toMatch(/\.report-outline \{ position: absolute;/);
    expect(css).toMatch(/@container report-workspace \(min-width: 1128px\) \{\n  \.report-shell\[data-outline-expanded='true'\] \{ grid-template-columns: 200px minmax\(0, 1fr\); max-width: calc\(200px \+ 32px \+ 56rem\); \}/);
  });
});
