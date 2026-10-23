import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const ANALYSIS = readFileSync(fileURLToPath(new URL('../src/views/analysis.css', import.meta.url)), 'utf8');

/** The declarations of every plain rule naming exactly this selector, as name → value. */
function declarations(selector: string): Record<string, string> {
  const flat = ANALYSIS.replace(/\/\*[\s\S]*?\*\//g, '');
  const found: Record<string, string> = {};
  for (const [, selectors, body] of flat.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    if (!selectors.split(',').map((name) => name.trim().replace(/\s+/g, ' ')).includes(selector)) continue;
    for (const part of body.split(';')) {
      const colon = part.indexOf(':');
      if (colon >= 0) found[part.slice(0, colon).trim()] = part.slice(colon + 1).trim();
    }
  }
  if (!Object.keys(found).length) throw new Error(`no rule for ${selector}`);
  return found;
}

describe('the result page layout (DESIGN.md 结果区)', () => {
  it('uses the compact data-card radius with 16px inside, cards stacked as a column', () => {
    expect(declarations('.analysis-kpi-card')).toMatchObject({
      'border-radius': 'var(--fnd-radius-mark)', padding: '16px', display: 'flex', 'flex-direction': 'column',
    });
  });

  it('sets each KPI figure right-aligned in tabular numbers, label on the left', () => {
    expect(declarations('.analysis-kpi-list dd')).toMatchObject({ 'text-align': 'right', 'font-variant-numeric': 'tabular-nums' });
    expect(declarations('.analysis-kpi-list > div')).toMatchObject({ display: 'flex', 'justify-content': 'space-between' });
  });

  it('draws figures in IBM Plex Mono and the digits of result sentences in its figures-only face', () => {
    for (const selector of ['.analysis-number', '.analysis-kpi-card strong', '.analysis-kpi-list dd', '.analysis-report-review-number']) {
      expect(declarations(selector), selector).toMatchObject({ 'font-family': 'var(--fnd-font-figure)', 'font-variant-numeric': 'tabular-nums' });
    }
    for (const selector of ['.analysis-headline', '.analysis-kpi-card', '.analysis-tieout-result', '.analysis-report-review-candidate']) {
      expect(declarations(selector), selector).toMatchObject({ 'font-family': 'var(--fnd-font-prose)' });
    }
    // The KPI value is a subtotal-weight figure, not the browser's bold for <strong>: three weights per table.
    expect(declarations('.analysis-kpi-card strong')['font-weight']).toBe('var(--fnd-weight-strong)');
  });

  it('goes to two KPI columns at 900px of result width and one at 480px', () => {
    expect(ANALYSIS).toMatch(/\.analysis-result \{[^}]*container: analysis-result \/ inline-size;/);
    expect(ANALYSIS).toMatch(/@container analysis-result \(max-width: 900px\) \{ \.analysis-kpi-grid \{ grid-template-columns: repeat\(2, minmax\(0, 1fr\)\); \} \}/);
    expect(ANALYSIS).toMatch(/@container analysis-result \(max-width: 480px\) \{ \.analysis-kpi-grid \{ grid-template-columns: minmax\(0, 1fr\); \} \}/);
  });

  it('stacks the date and states, and leaves the screen-reader heading undrawn', () => {
    expect(declarations('.analysis-result-head')).toMatchObject({ display: 'flex', 'flex-direction': 'column' });
    // The heading is sr-only in the markup; no page rule may draw it back.
    expect(ANALYSIS).not.toMatch(/\.analysis-result-head h3/);
    expect(declarations('.analysis-kpi-title')).toMatchObject({ '-webkit-line-clamp': '2', overflow: 'hidden' });
  });

  it('keeps each KPI meta part whole and drops the fixed title height', () => {
    expect(declarations('.analysis-kpi-meta > span')).toMatchObject({ 'white-space': 'nowrap' });
    expect(declarations('.analysis-kpi-title')).not.toHaveProperty('min-height');
  });

  it('writes the version notes as plain secondary text, no box', () => {
    const note = declarations('.analysis-version-note');
    expect(note).toMatchObject({ color: 'var(--fnd-muted)', 'font-size': 'var(--fnd-size-label)', border: '0' });
    expect(note).not.toHaveProperty('border-radius');
  });

  it('no longer places a message outside the result article', () => {
    expect(ANALYSIS).not.toContain('.analysis-result-area > .analysis-message');
  });
});
