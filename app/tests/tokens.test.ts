import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const TOKENS = readFileSync(fileURLToPath(new URL('../src/styles/tokens.css', import.meta.url)), 'utf8');

/** The declarations inside one selector block, as name → value. */
function block(css: string, selector: string): Record<string, string> {
  const start = css.indexOf(selector);
  if (start < 0) throw new Error(`no ${selector}`);
  const open = css.indexOf('{', start);
  let depth = 0;
  let end = open;
  for (let i = open; i < css.length; i += 1) {
    if (css[i] === '{') depth += 1;
    if (css[i] === '}') {
      depth -= 1;
      if (depth === 0) {
        end = i;
        break;
      }
    }
  }
  const found: Record<string, string> = {};
  for (const line of css.slice(open + 1, end).split('\n')) {
    const match = /^\s*(--[a-z0-9-]+)\s*:\s*([^;]+);/.exec(line);
    if (match) found[match[1]] = match[2].trim();
  }
  return found;
}

/** WCAG 2.x relative luminance, compositing an 8-digit hex over its ground. */
function luminance(hex: string, ground: string): number {
  const parse = (value: string) => {
    const h = value.replace('#', '');
    return {
      r: parseInt(h.slice(0, 2), 16),
      g: parseInt(h.slice(2, 4), 16),
      b: parseInt(h.slice(4, 6), 16),
      a: h.length === 8 ? parseInt(h.slice(6, 8), 16) / 255 : 1,
    };
  };
  const front = parse(hex);
  const back = parse(ground);
  const mix = (f: number, b: number) => f * front.a + b * (1 - front.a);
  const channel = (value: number) => {
    const c = value / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return (
    0.2126 * channel(mix(front.r, back.r)) +
    0.7152 * channel(mix(front.g, back.g)) +
    0.0722 * channel(mix(front.b, back.b))
  );
}

function contrast(hex: string, ground: string): number {
  const a = luminance(hex, ground);
  const b = luminance(ground, ground);
  const [hi, lo] = a > b ? [a, b] : [b, a];
  return (hi + 0.05) / (lo + 0.05);
}

describe('the token table', () => {
  it('keeps operational and brand typography independently named', () => {
    const values = block(TOKENS, ':root');
    expect(values['--fnd-font-sans']).toMatch(/^'Noto Sans SC'/);
    expect(values['--fnd-font-brand']).toMatch(/^'Asap Sharp'/);
    expect(values['--fnd-font-sans']).not.toContain('LXGW');
  });

  it('resolves in all three theme states', () => {
    // The viewer has three, not two: an explicit choice stamps the root, and the
    // default stamps nothing at all. A colour defined only behind a stamp never
    // applies in the un-stamped state, which is how a window ends up drawing one
    // theme's text on the other theme's ground.
    const light = block(TOKENS, ':root');
    const media = block(TOKENS, "@media (prefers-color-scheme: dark)");
    const stamped = block(TOKENS, ":root[data-theme='dark']");
    expect(Object.keys(media).length).toBeGreaterThan(0);
    for (const name of Object.keys(media)) {
      expect(light, `${name} is only defined in the dark media query`).toHaveProperty(name);
      expect(stamped, `${name} has no [data-theme='dark'] answer`).toHaveProperty(name);
    }
    for (const name of Object.keys(stamped)) {
      expect(media, `${name} has no prefers-color-scheme answer`).toHaveProperty(name);
    }
  });
});

describe('the five words are legible in both themes', () => {
  const light = block(TOKENS, ':root');
  const dark = block(TOKENS, ":root[data-theme='dark']");

  it('clears 4.5:1 for every mark that is text', () => {
    const cases: [string, Record<string, string>, string[]][] = [
      ['light', light, ['#ffffff', '#f7f7f7']],
      ['dark', dark, ['#1f1f1f', '#161616']],
    ];
    for (const [theme, table, grounds] of cases) {
      for (const token of ['--fnd-ink', '--fnd-muted', '--fnd-mark-outside', '--fnd-mark-absent']) {
        for (const ground of grounds) {
          const ratio = contrast(table[token], ground);
          expect(ratio, `${theme} ${token} on ${ground} is ${ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(4.5);
        }
      }
    }
  });

  /*
   * A fill takes text, so this pair answers to the text floor rather than to
   * the 3:1 an edge gets. `--fnd-line-hover`'s own light gold was tried for it
   * first and measures 3.70:1 under white -- right for the border it was
   * picked for, under the floor for a label sitting on it.
   */
  it('clears 4.5:1 for the label on the selected destination', () => {
    for (const [theme, table] of [
      ['light', light],
      ['dark', dark],
    ] as const) {
      const ratio = contrast(table['--fnd-on-selected'], table['--fnd-selected']);
      expect(
        ratio,
        `${theme} --fnd-on-selected on --fnd-selected is ${ratio.toFixed(2)}:1`,
      ).toBeGreaterThanOrEqual(4.5);
    }
  });

  it('clears 3:1 for the one mark colour that is only an edge', () => {
    // The border gold measures 3.70:1, under the text floor and over the
    // non-text one. That is exactly why the outside chip's text and its border
    // are two tokens rather than one.
    for (const ground of ['#ffffff', '#f7f7f7']) {
      expect(contrast(light['--fnd-mark-outside-line'], ground)).toBeGreaterThanOrEqual(3);
    }
    expect(contrast(light['--fnd-mark-outside-line'], '#ffffff')).toBeLessThan(4.5);
  });
});
