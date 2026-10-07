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

/** Every innermost rule as [one selector, its body]; commas inside :where()/:not() stay with their selector. */
function rules(css: string): [string, string][] {
  const flat = css.replace(/\/\*[\s\S]*?\*\//g, '');
  const found: [string, string][] = [];
  for (const [, selectors, body] of flat.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    let depth = 0;
    let current = '';
    for (const char of selectors) {
      if (char === '(') depth += 1;
      if (char === ')') depth -= 1;
      if (char === ',' && depth === 0) {
        found.push([current.trim().replace(/\s+/g, ' '), body]);
        current = '';
      } else current += char;
    }
    found.push([current.trim().replace(/\s+/g, ' '), body]);
  }
  return found;
}

describe('disclosures (DESIGN.md 折叠段落)', () => {
  it('no longer has --fnd-disclosure', () => {
    const compact = fileURLToPath(new URL('../harness-client/compact.css', import.meta.url));
    const holders = [...sheets(SRC), compact].filter((path) => readFileSync(path, 'utf8').includes('--fnd-disclosure'));
    expect(holders).toEqual([]);
  });

  /*
   * Outside components.css (which owns .fnd-disclosure-summary), a rule that names a summary
   * anywhere in its selector, or the shared summary classes, may only space the disclosure.
   * The exceptions are listed by file and selector, each with the reason it may draw.
   */
  const MAY_DRAW: Record<string, string> = {
    'styles/base.css :where(a, button, input, textarea, select, summary, [tabindex]):focus-visible': 'the shared 1px focus ring',
    'views/analysis.css .analysis-source-refresh > summary .analysis-note': 'the description line inside the 更新 ERP 来源 summary',
    'views/analysis.css .analysis-source-refresh:not([open]) > summary .analysis-note::after': 'the 点击展开刷新 suffix (PR E)',
    // The reading view injects exported report HTML (electron/reports/format.ts); its chart-data
    // <summary> is not React, so report.css redraws the quiet disclosure for it.
    'views/analysis/report.css .analysis-draft-main .report-visual-data > summary': 'exported HTML chart-data summary',
    'views/analysis/report.css .analysis-draft-main .report-visual-data > summary:hover': 'exported HTML chart-data summary',
    'views/analysis/report.css .analysis-draft-main .report-visual-data > summary::before': 'exported HTML chart-data summary',
    'views/analysis/report.css .analysis-draft-main .report-visual-data[open] > summary::before': 'exported HTML chart-data summary',
  };

  /** The rule offenders and the exceptions it used, for one sheet's text. */
  function summaryRules(name: string, css: string): { offenders: string[]; excepted: string[] } {
    const offenders: string[] = [];
    const excepted: string[] = [];
    for (const [selector, body] of rules(css)) {
      const touches = /(^|[\s>+~(,])summary(?![\w-])/.test(selector) || selector.includes('.fnd-disclosure-summary');
      if (!touches) continue;
      const key = `${name} ${selector}`;
      if (key in MAY_DRAW) {
        excepted.push(key);
        continue;
      }
      const properties = body.split(';').map((part) => part.split(':')[0].trim()).filter(Boolean);
      const drawn = properties.filter((property) => !property.startsWith('margin'));
      if (drawn.length) offenders.push(`${key} { ${drawn.join(', ')} }`);
    }
    return { offenders, excepted };
  }

  it('lets rules outside components.css only space a summary', () => {
    const offenders: string[] = [];
    const excepted: string[] = [];
    for (const path of sheets(SRC)) {
      const name = path.slice(SRC.length + 1);
      if (name === 'components/components.css') continue;
      const found = summaryRules(name, readFileSync(path, 'utf8'));
      offenders.push(...found.offenders);
      excepted.push(...found.excepted);
    }
    expect(offenders).toEqual([]);
    // Every exception still names a live rule, so the list cannot rot into blanket permission.
    expect(excepted.sort()).toEqual(Object.keys(MAY_DRAW).sort());
  });

  it('catches a summary restyled through a descendant, a class or the icon', () => {
    const probe = [
      '.x details > summary span { color: red; }',
      '.x .fnd-disclosure-summary { font-weight: 600; }',
      '.x .fnd-disclosure-summary__icon { transform: none; }',
      '.x[open] > summary { margin-bottom: 4px; }',
    ].join('\n');
    expect(summaryRules('probe.css', probe).offenders).toEqual([
      'probe.css .x details > summary span { color }',
      'probe.css .x .fnd-disclosure-summary { font-weight }',
      'probe.css .x .fnd-disclosure-summary__icon { transform }',
    ]);
  });
});
