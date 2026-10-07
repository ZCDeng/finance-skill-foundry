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

/** An 8-digit fill laid over its ground, as the 6-digit colour a reader sees. */
function over(fill: string, ground: string): string {
  const f = fill.replace('#', '');
  const g = ground.replace('#', '');
  const alpha = f.length === 8 ? parseInt(f.slice(6, 8), 16) / 255 : 1;
  let out = '#';
  for (const at of [0, 2, 4]) {
    const mixed = Math.round(parseInt(f.slice(at, at + 2), 16) * alpha + parseInt(g.slice(at, at + 2), 16) * (1 - alpha));
    out += mixed.toString(16).padStart(2, '0');
  }
  return out;
}

/** HSL hue in degrees, for telling two colour families apart. */
function hue(hex: string): number {
  const h = hex.replace('#', '');
  const [r, g, b] = [0, 2, 4].map((at) => parseInt(h.slice(at, at + 2), 16) / 255);
  const max = Math.max(r, g, b);
  const d = max - Math.min(r, g, b);
  if (d === 0) return 0;
  const raw = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return (raw * 60 + 360) % 360;
}

function hueDistance(a: string, b: string): number {
  const d = Math.abs(hue(a) - hue(b));
  return Math.min(d, 360 - d);
}

/** Every plain declaration a selector receives in a flat stylesheet, later rules winning. */
function declarations(css: string, selector: string): Record<string, string> {
  const flat = css.replace(/\/\*[\s\S]*?\*\//g, '');
  const found: Record<string, string> = {};
  for (const [, selectors, body] of flat.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const names = selectors.split(',').map((name) => name.trim().replace(/\s+/g, ' '));
    if (!names.includes(selector)) continue;
    for (const part of body.split(';')) {
      const colon = part.indexOf(':');
      if (colon < 0) continue;
      found[part.slice(0, colon).trim()] = part.slice(colon + 1).trim();
    }
  }
  if (!Object.keys(found).length) throw new Error(`no rule for ${selector}`);
  return found;
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

  it('keeps restrained keyboard focus distinguishable on every workspace surface', () => {
    for (const table of [light, dark]) {
      for (const ground of ['--fnd-bg', '--fnd-surface', '--fnd-surface-strong', '--fnd-selection-surface']) {
        expect(contrast(table['--fnd-focus'], table[ground]), `${ground} focus contrast`).toBeGreaterThanOrEqual(3);
      }
      expect(table['--fnd-line-hover']).not.toBe(table['--fnd-focus']);
    }
  });

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

describe('shadcn aliases', () => {
  const bridge = readFileSync(fileURLToPath(new URL('../src/styles/shadcn-bridge.css', import.meta.url)), 'utf8');

  it('only aliases FA tokens, with no second palette', () => {
    const root = block(bridge, ':root');
    for (const [name, value] of Object.entries(root)) {
      expect(value, name).toMatch(/^var\(--fnd-/);
    }
    expect(bridge).not.toMatch(/(^|\n)\.dark\s*\{/);
    expect(bridge).not.toContain('oklch(');
  });

  it('points destructive at the warning colour, not the gold', () => {
    expect(block(bridge, ':root')['--destructive']).toBe('var(--fnd-warning)');
  });
});

/*
 * Gold used to answer for two things at once: the product's own location
 * (brand, current place, selection, focus, the off-brief mark) and "this went
 * wrong". A delete button in gold read as the selected thing. Warnings now
 * have their own triplet, and gold is left to the first job.
 */
describe('the warning colour', () => {
  const read = (rel: string) => readFileSync(fileURLToPath(new URL(rel, import.meta.url)), 'utf8');
  const light = block(TOKENS, ':root');
  const media = block(TOKENS, '@media (prefers-color-scheme: dark)');
  const dark = block(TOKENS, ":root[data-theme='dark']");
  const TRIPLET = ['--fnd-warning', '--fnd-warning-line', '--fnd-warning-fill'] as const;
  const GOLD = {
    '--fnd-warning': '--fnd-mark-outside',
    '--fnd-warning-line': '--fnd-mark-outside-line',
    '--fnd-warning-fill': '--fnd-mark-outside-fill',
  } as const;

  it('is a full triplet in light and in both dark answers, the same in both dark answers', () => {
    for (const name of TRIPLET) {
      expect(light, `light ${name}`).toHaveProperty(name);
      expect(media, `media ${name}`).toHaveProperty(name);
      expect(dark, `stamped ${name}`).toHaveProperty(name);
      expect(media[name], name).toBe(dark[name]);
    }
  });

  it('is its own colour family, apart from every gold', () => {
    for (const [theme, table] of [
      ['light', light],
      ['dark', dark],
    ] as const) {
      for (const name of TRIPLET) {
        expect(table[name].toLowerCase(), `${theme} ${name}`).not.toBe(table[GOLD[name]].toLowerCase());
      }
      for (const gold of ['--fnd-mark-outside', '--fnd-mark-outside-line', '--fnd-focus', '--fnd-selected']) {
        const distance = hueDistance(table['--fnd-warning'], table[gold]);
        expect(distance, `${theme} --fnd-warning is ${distance.toFixed(0)} degrees from ${gold}`).toBeGreaterThanOrEqual(25);
      }
    }
  });

  it('clears 4.5:1 as text on every light and dark surface, and on its own fill', () => {
    const cases: [string, Record<string, string>, string[]][] = [
      ['light', light, ['#ffffff', '#f7f7f7', light['--fnd-selection-surface']]],
      ['dark', dark, ['#1f1f1f', '#161616', dark['--fnd-bg']]],
    ];
    for (const [theme, table, grounds] of cases) {
      for (const ground of grounds) {
        const bare = contrast(table['--fnd-warning'], ground);
        expect(bare, `${theme} --fnd-warning on ${ground} is ${bare.toFixed(2)}:1`).toBeGreaterThanOrEqual(4.5);
        // A destructive menu item and badge put the text on the fill.
        const filled = over(table['--fnd-warning-fill'], ground);
        const onFill = contrast(table['--fnd-warning'], filled);
        expect(onFill, `${theme} --fnd-warning on its fill over ${ground} is ${onFill.toFixed(2)}:1`).toBeGreaterThanOrEqual(4.5);
      }
    }
  });

  it('clears 3:1 for the warning edge', () => {
    for (const [table, grounds] of [
      [light, ['#ffffff', '#f7f7f7']],
      [dark, ['#1f1f1f', '#161616']],
    ] as const) {
      for (const ground of grounds) {
        expect(contrast(table['--fnd-warning-line'], ground)).toBeGreaterThanOrEqual(3);
      }
    }
  });

  it('keeps the design record in step with the token table', () => {
    const front = /^---\n([\s\S]*?)\n---/.exec(read('../../DESIGN.md'))?.[1] ?? '';
    const colour = (key: string) => new RegExp(`\\b${key}: '(#[0-9a-f]+)'`).exec(front)?.[1];
    for (const name of TRIPLET) {
      const key = name.slice(2);
      expect(colour(key), key).toMatch(/^#/);
      expect(colour(key), key).toBe(light[name]);
      expect(colour(`${key}-dark`), `${key}-dark`).toBe(dark[name]);
    }
  });
});

describe('where the warning colour is drawn', () => {
  const read = (rel: string) => readFileSync(fileURLToPath(new URL(rel, import.meta.url)), 'utf8');
  const COMPONENTS = read('../src/components/components.css');
  const CONTROLS = read('../src/components/financial-controls.css');
  const ANALYSIS = read('../src/views/analysis.css');

  it('gives the destructive button a warning edge, warning text and a warning hover fill', async () => {
    const { buttonVariants } = await import('../src/components/ui/button.js');
    const classes = buttonVariants({ variant: 'destructive' });
    expect(classes).toContain('border-[var(--fnd-warning-line)]');
    expect(classes).toContain('text-[var(--fnd-warning)]');
    expect(classes).toContain('enabled:hover:bg-[var(--fnd-warning-fill)]');
    expect(classes).not.toContain('mark-outside');
  });

  it('gives the destructive badge the warning edge, fill and text', async () => {
    const { badgeVariants } = await import('../src/components/ui/badge.js');
    const classes = badgeVariants({ variant: 'destructive' });
    expect(classes).toContain('border-[var(--fnd-warning-line)]');
    expect(classes).toContain('bg-[var(--fnd-warning-fill)]');
    expect(classes).toContain('text-[var(--fnd-warning)]');
    expect(classes).not.toContain('mark-outside');
  });

  it('gives the destructive menu item warning text and a warning focus fill', () => {
    const menu = read('../src/components/ui/dropdown-menu.tsx');
    expect(menu).toContain('data-[variant=destructive]:text-[var(--fnd-warning)]');
    expect(menu).toContain('data-[variant=destructive]:focus:bg-[var(--fnd-warning-fill)]');
    expect(menu).not.toContain('mark-outside');
  });

  it('draws error messages in the warning colour, edge included', () => {
    expect(declarations(ANALYSIS, '.analysis-message--error')).toMatchObject({
      'border-color': 'var(--fnd-warning-line)',
      color: 'var(--fnd-warning)',
    });
    expect(declarations(CONTROLS, '.fnd-control__error').color).toBe('var(--fnd-warning)');
    expect(declarations(CONTROLS, ".fnd-combobox__state[data-state='error']").color).toBe('var(--fnd-warning)');
    expect(declarations(CONTROLS, '.fnd-combobox__repair').color).toBe('var(--fnd-warning)');
    expect(declarations(COMPONENTS, '.fnd-refusal')).toMatchObject({
      border: '1px solid var(--fnd-warning)',
      background: 'var(--fnd-warning-fill)',
    });
  });

  it('edges an aria-invalid field in the warning line', () => {
    expect(declarations(COMPONENTS, ".fnd-field[aria-invalid='true']")['border-color']).toBe('var(--fnd-warning-line)');
    for (const selector of [
      ".fnd-control[data-invalid='true'] .fnd-field",
      ".fnd-control[data-invalid='true'] .fnd-combobox__button",
      ".fnd-combobox__button[aria-invalid='true']",
    ]) {
      expect(declarations(CONTROLS, selector)['border-color'], selector).toBe('var(--fnd-warning-line)');
    }
  });

  it('leaves the historical marks in their own colours', () => {
    expect(declarations(COMPONENTS, ".fnd-chip[data-coloured='yes'][data-mark='outside']")).toMatchObject({
      color: 'var(--fnd-mark-outside)',
      'border-color': 'var(--fnd-mark-outside-line)',
      background: 'var(--fnd-mark-outside-fill)',
    });
    expect(declarations(COMPONENTS, ".fnd-chip[data-coloured='yes'][data-mark='external']")).toMatchObject({
      color: 'var(--fnd-mark-external)',
      'border-color': 'var(--fnd-mark-external)',
    });
  });

  it('leaves the gold mark tokens to the off-brief chip alone', () => {
    const users: string[] = [];
    for (const [file, css] of [
      ['components.css', COMPONENTS],
      ['financial-controls.css', CONTROLS],
      ['analysis.css', ANALYSIS],
      ['shadcn-bridge.css', read('../src/styles/shadcn-bridge.css')],
    ] as const) {
      const flat = css.replace(/\/\*[\s\S]*?\*\//g, '');
      for (const [, selectors, body] of flat.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
        if (body.includes('--fnd-mark-outside')) users.push(`${file} ${selectors.trim().replace(/\s+/g, ' ')}`);
      }
    }
    expect(users).toEqual(["components.css .fnd-chip[data-coloured='yes'][data-mark='outside']"]);
  });
});

/*
 * R14, KTD13. The title bar says where the reader is, so it carries the gold:
 * the wordmark, the current tab and a hover. Its buttons stay neutral at rest.
 * `.fnd-head__tab` is also the back button on 交付物 and 任务 and the
 * Formulator start and stop button, so every gold title-bar rule is written
 * under `.fnd-head` and those reuses keep their own colours.
 */
describe('the title bar gold', () => {
  const COMPONENTS = readFileSync(fileURLToPath(new URL('../src/components/components.css', import.meta.url)), 'utf8');
  const light = block(TOKENS, ':root');
  const media = block(TOKENS, '@media (prefers-color-scheme: dark)');
  const dark = block(TOKENS, ":root[data-theme='dark']");
  const CURRENT = ".fnd-head .fnd-head__tab[aria-current='page']";
  const HOVER = ".fnd-head .fnd-head__tab:hover:not(:disabled):not([aria-current='page'])";

  /** Every rule in the sheet as [one selector, its body], comments removed. */
  function rules(css: string): [string, string][] {
    const flat = css.replace(/\/\*[\s\S]*?\*\//g, '');
    const found: [string, string][] = [];
    for (const [, selectors, body] of flat.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      for (const name of selectors.split(',')) found.push([name.trim().replace(/\s+/g, ' '), body]);
    }
    return found;
  }

  it('writes the wordmark in the selection gold', () => {
    expect(declarations(COMPONENTS, '.fnd-head__mark').color).toBe('var(--fnd-selected)');
  });

  it('leaves a tab at rest in the secondary text colour and turns it gold on hover', () => {
    expect(declarations(COMPONENTS, '.fnd-head__tab')).toMatchObject({
      color: 'var(--fnd-muted)',
      background: 'transparent',
    });
    expect(declarations(COMPONENTS, HOVER)).toMatchObject({
      color: 'var(--fnd-selected)',
      background: 'transparent',
    });
  });

  it('marks the current tab with gold text, the selection surface and a 1px gold underline', () => {
    expect(declarations(COMPONENTS, CURRENT)).toMatchObject({
      color: 'var(--fnd-selected)',
      background: 'var(--fnd-selection-surface)',
      position: 'relative',
    });
    // The underline is the mark that does not depend on colour. Drawn by a
    // positioned pseudo-element, so the tab and the header keep their height.
    expect(declarations(COMPONENTS, `${CURRENT}::after`)).toMatchObject({
      position: 'absolute',
      bottom: '0',
      height: '1px',
      background: 'var(--fnd-selected)',
    });
  });

  it('keeps the keyboard focus ring a mark of its own, apart from the gold text', () => {
    for (const selector of ['.fnd-head .fnd-head__tab:focus-visible', '.fnd-head__help:focus-visible']) {
      const rule = declarations(COMPONENTS, selector);
      expect(rule, selector).toMatchObject({ outline: '1px solid var(--fnd-focus)', 'outline-offset': '-1px' });
      expect(rule, selector).not.toHaveProperty('color');
      expect(rule, selector).not.toHaveProperty('background');
    }
    // `--fnd-focus` draws rings only; the gold text is always `--fnd-selected`.
    for (const [selector, body] of rules(COMPONENTS)) {
      if (!selector.startsWith('.fnd-head')) continue;
      if (body.includes('--fnd-focus')) expect(selector, selector).toContain(':focus-visible');
      if (selector.includes(':focus-visible')) expect(body, selector).not.toContain('--fnd-selected');
    }
  });

  it('keeps every gold title-bar rule inside .fnd-head, so the reused tab keeps its colours', () => {
    for (const [selector, body] of rules(COMPONENTS)) {
      if (!selector.includes('.fnd-head__tab') || !body.includes('--fnd-selected')) continue;
      expect(selector, selector).toMatch(/^\.fnd-head \.fnd-head__tab/);
    }
    // What the back buttons and the Formulator button draw with, unchanged.
    expect(declarations(COMPONENTS, '.fnd-head__tab:hover')).toMatchObject({
      color: 'var(--fnd-ink)',
      background: 'var(--fnd-surface-strong)',
    });
    expect(declarations(COMPONENTS, ".fnd-head__tab:active:not([aria-current='page'])").background).toBe(
      'var(--fnd-selection-surface)',
    );
  });

  it('clears 4.5:1 for the gold text on the title bar and on the selection surface', () => {
    expect(declarations(COMPONENTS, '.fnd-head').background).toBe('var(--fnd-surface)');
    for (const [theme, table] of [
      ['light', light],
      ['dark (system)', media],
      ['dark (stamped)', dark],
    ] as const) {
      for (const ground of ['--fnd-surface', '--fnd-selection-surface']) {
        const ratio = contrast(table['--fnd-selected'], table[ground]);
        expect(
          ratio,
          `${theme} --fnd-selected ${table['--fnd-selected']} on ${ground} ${table[ground]} is ${ratio.toFixed(4)}:1`,
        ).toBeGreaterThanOrEqual(4.5);
      }
    }
  });
});

/*
 * DESIGN.md 折叠段落. One summary line for every in-place disclosure: body
 * text, a neutral hover, a chevron that turns a quarter, the shared focus ring.
 */
describe('the disclosure summary', () => {
  const COMPONENTS = readFileSync(fileURLToPath(new URL('../src/components/components.css', import.meta.url)), 'utf8');
  const BASE = readFileSync(fileURLToPath(new URL('../src/styles/base.css', import.meta.url)), 'utf8');
  const SUMMARY = '.fnd-disclosure-summary';
  const ICON = '.fnd-disclosure-summary__icon';

  it('reads as body text with a neutral hover and no gold, warning or fixed colour', () => {
    expect(declarations(COMPONENTS, SUMMARY)).toMatchObject({
      color: 'var(--fnd-ink)',
      'font-size': 'var(--fnd-size-body)',
      'font-weight': '400',
      'list-style': 'none',
    });
    expect(declarations(COMPONENTS, `${SUMMARY}:hover`).background).toBe('var(--fnd-selection-surface)');
    const flat = COMPONENTS.replace(/\/\*[\s\S]*?\*\//g, '');
    const bodies = [...flat.matchAll(/([^{}]+)\{([^{}]*)\}/g)].filter(([, selectors]) => selectors.includes(SUMMARY));
    expect(bodies.length).toBeGreaterThan(0);
    for (const [, selectors, body] of bodies) {
      expect(body, selectors.trim()).not.toMatch(/--fnd-selected|--fnd-warning|#[0-9a-f]{3,8}\b/i);
    }
  });

  it('turns the chevron a quarter when open, on the shared transition', () => {
    expect(declarations(COMPONENTS, `details[open] > ${SUMMARY} > ${ICON}`).transform).toBe('rotate(90deg)');
    expect(declarations(COMPONENTS, ICON).transition).toBe('transform var(--fnd-transition)');
    // Reduced motion zeroes the shared duration, so the turn is instant there.
    expect(TOKENS).toMatch(/@media \(prefers-reduced-motion: reduce\) \{\s*:root \{ --fnd-duration: 0ms; \}/);
  });

  it('takes the 1px focus ring from base, which now names summary', () => {
    const flat = BASE.replace(/\/\*[\s\S]*?\*\//g, '');
    const rule = [...flat.matchAll(/([^{}]+)\{([^{}]*)\}/g)].find(
      ([, selector]) => selector.trim().startsWith(':where(') && selector.trim().endsWith(':focus-visible'),
    );
    expect(rule, 'base :focus-visible rule').toBeDefined();
    const elements = /:where\(([^)]*)\)/.exec(rule![1])![1].split(',').map((name) => name.trim());
    expect(elements).toContain('summary');
    expect(rule![2].replace(/\s+/g, ' ')).toContain('outline: 1px solid var(--fnd-focus);');
  });
});
