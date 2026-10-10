import { readdirSync, readFileSync, statSync } from 'node:fs';
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

/** The four grounds text and marks are drawn on: the canvas, a card, the strong fill and the selection fill. */
function grounds(table: Record<string, string>): string[] {
  return ['--fnd-bg', '--fnd-surface', '--fnd-surface-strong', '--fnd-selection-surface'].map((name) => table[name]);
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

  it('draws figures in IBM Plex Mono and leaves Chinese to the interface face', () => {
    const values = block(TOKENS, ':root');
    const fallback = values['--fnd-font-sans'];
    expect(values['--fnd-font-figure']).toBe(`'IBM Plex Mono', ${fallback}`);
    expect(values['--fnd-font-prose']).toBe(`'FND Figures', ${fallback}`);
  });

  it('marks a negative figure in a muted dark red that is not the warning colour', () => {
    // Deng's rule 3: a soft dark red beside the sign or parentheses, never a saturated pure red.
    const saturation = (hex: string) => {
      const [r, g, b] = [0, 2, 4].map((at) => parseInt(hex.slice(1 + at, 3 + at), 16) / 255);
      const max = Math.max(r, g, b), min = Math.min(r, g, b), lightness = (max + min) / 2;
      return max === min ? 0 : (max - min) / (1 - Math.abs(2 * lightness - 1));
    };
    for (const table of [block(TOKENS, ':root'), block(TOKENS, ":root[data-theme='dark']")]) {
      expect(table['--fnd-negative']).not.toBe(table['--fnd-warning']);
      expect(saturation(table['--fnd-negative'])).toBeLessThan(saturation(table['--fnd-warning']));
      expect(saturation(table['--fnd-negative'])).toBeLessThan(0.5);
      expect(hue(table['--fnd-negative'])).toBeLessThan(20);
    }
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
      ['light', light, grounds(light)],
      ['dark', dark, grounds(dark)],
    ];
    for (const [theme, table, grounds] of cases) {
      for (const token of ['--fnd-ink', '--fnd-muted', '--fnd-mark-outside', '--fnd-mark-absent', '--fnd-negative']) {
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
    for (const ground of [light['--fnd-surface'], light['--fnd-surface-strong']]) {
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
      ['light', light, grounds(light)],
      ['dark', dark, grounds(dark)],
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
    for (const table of [light, dark]) {
      for (const ground of grounds(table)) {
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

  it('draws a selected chip with an ink edge on the selection surface, not the primary fill or the gold', async () => {
    const { buttonVariants } = await import('../src/components/ui/button.js');
    const { cn } = await import('../src/lib/utils.js');
    // As Button renders it: cn() lets the chip radius and label size replace the control ones.
    const classes = cn(buttonVariants({ variant: 'outline', size: 'chip' })).split(' ');
    expect(classes).toContain('rounded-[var(--fnd-radius-pill)]');
    expect(classes).not.toContain('rounded-[var(--fnd-radius-control)]');
    expect(classes).toContain('text-[length:var(--fnd-size-label)]');
    expect(classes).toContain('h-7');
    for (const state of ['aria-selected', 'aria-pressed']) {
      expect(classes).toContain(`${state}:border-[var(--fnd-ink)]`);
      expect(classes).toContain(`${state}:bg-[var(--fnd-selection-surface)]`);
    }
    expect(classes.some((name) => /bg-primary|--fnd-selected|--fnd-gold/.test(name))).toBe(false);
  });

  it('keeps a selected chip selected under the pointer: each outline hover is outranked by the same chain behind aria-*', async () => {
    const { buttonVariants } = await import('../src/components/ui/button.js');
    const outline = buttonVariants({ variant: 'outline' }).split(' ');
    const chip = buttonVariants({ variant: 'outline', size: 'chip' }).split(' ');
    // An outline hover such as enabled:hover:not-focus-visible:border-[…] compiles to .x:enabled:hover:not(:focus-visible);
    // the bare aria-selected:border-[…] is .x[aria-selected=true] and loses to it. The override has to carry the
    // whole chain plus the attribute, for the same property, and paint the selected colours.
    const hovers = outline.filter((name) => name.split(':').includes('hover'));
    expect(hovers.length).toBeGreaterThan(0);
    for (const state of ['aria-selected', 'aria-pressed']) {
      for (const hover of hovers) {
        const chain = hover.slice(0, hover.lastIndexOf(':'));
        const property = hover.slice(hover.lastIndexOf(':') + 1).replace(/\[.*$/, '');
        const override = chip.find((name) => name.startsWith(`${state}:${chain}:${property}`));
        expect(override, `${state} over ${hover}`).toBeDefined();
        expect(override).toMatch(/var\(--fnd-(ink|selection-surface)\)/);
      }
    }
  });

  it('stands the chip focus ring off the edge so the ink edge still shows while focused', async () => {
    const { buttonVariants } = await import('../src/components/ui/button.js');
    expect(buttonVariants({ variant: 'outline', size: 'chip' }).split(' ')).toContain('focus-visible:outline-offset-1');
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
 * `.fnd-head__tab` is also the back button on 成果库 and 任务 and the
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

  it('draws the title-bar tabs as words, without a pill, at the strong weight', () => {
    expect(declarations(COMPONENTS, '.fnd-head .fnd-head__tab')).toMatchObject({
      'border-radius': '0',
      'font-weight': 'var(--fnd-weight-strong)',
      position: 'relative',
    });
    expect(declarations(COMPONENTS, ".fnd-head .fnd-head__tab:active:not(:disabled):not([aria-current='page'])").background).toBe('transparent');
  });

  it('marks the current tab with gold text and a 2px gold underline, which a hover grows from the middle', () => {
    expect(declarations(COMPONENTS, CURRENT)).toMatchObject({
      color: 'var(--fnd-selected)',
      background: 'transparent',
    });
    // The underline is the mark that does not depend on colour. Drawn by a
    // positioned pseudo-element, so the tab and the header keep their height.
    expect(declarations(COMPONENTS, '.fnd-head .fnd-head__tab::after')).toMatchObject({
      position: 'absolute',
      height: '2px',
      background: 'var(--fnd-selected)',
      transform: 'scaleX(0)',
      transition: 'transform var(--fnd-transition)',
    });
    expect(declarations(COMPONENTS, `${CURRENT}::after`).transform).toBe('scaleX(1)');
    expect(declarations(COMPONENTS, '.fnd-head .fnd-head__tab:hover:not(:disabled)::after').transform).toBe('scaleX(1)');
  });

  it('keeps the tabs on the window centre line: two equal sides around them', () => {
    expect(declarations(COMPONENTS, '.fnd-head')).toMatchObject({
      display: 'grid',
      'grid-template-columns': 'minmax(0, 1fr) auto minmax(0, 1fr)',
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

  it('steps technical folds down to the label size in the secondary text colour, same left edge', () => {
    expect(declarations(COMPONENTS, `${SUMMARY}[data-tone='quiet']`)).toMatchObject({
      color: 'var(--fnd-muted)',
      'font-size': 'var(--fnd-size-label)',
      'line-height': '18px',
    });
    expect(declarations(COMPONENTS, `${SUMMARY}[data-tone='quiet']`)).not.toHaveProperty('padding-left');
    expect(declarations(COMPONENTS, `${SUMMARY}[data-tone='quiet'] > ${ICON}`)).toMatchObject({ width: '14px', height: '14px' });
  });

  it('hangs the chevron in the gutter so the words start on the content edge', () => {
    expect(declarations(COMPONENTS, SUMMARY)).toMatchObject({
      'margin-inline-start': '-24px',
      'max-width': 'calc(100% + 24px)',
      padding: '5px 8px 5px 24px',
    });
    // The 16px box sits at -20..-4 from the content edge, inside the 20px gutter of the narrowest pane.
    expect(declarations(COMPONENTS, ICON).left).toBe('4px');
    expect(declarations(COMPONENTS, `${SUMMARY}[data-tone='quiet'] > ${ICON}`).left).toBe('6px');
    // In the taskbar the fold is a control in a row, so it keeps the chevron inside.
    expect(declarations(COMPONENTS, `.fnd-taskbar__technical ${SUMMARY}`)['margin-inline-start']).toBe('0');
    // In a bordered card with a narrower gutter the chevron stays inside rather than crossing the border.
    const flat = COMPONENTS.replace(/\/\*[\s\S]*?\*\//g, '');
    const inset = [...flat.matchAll(/([^{}]+)\{([^{}]*)\}/g)].find(([, selector]) => selector.includes('.analysis-structure-sheet') && selector.trim().endsWith(SUMMARY));
    expect(inset?.[2]).toMatch(/margin-inline-start:\s*0/);
  });

  it('turns the chevron a quarter when open, on the shared transition', () => {
    expect(declarations(COMPONENTS, `details[open] > ${SUMMARY} > ${ICON}`).transform).toBe('rotate(90deg)');
    expect(declarations(COMPONENTS, ICON).transition).toBe('transform var(--fnd-transition)');
    // Reduced motion zeroes the shared duration, so the turn is instant there.
    expect(TOKENS).toMatch(/@media \(prefers-reduced-motion: reduce\) \{\s*:root \{ --fnd-duration: 0ms; \}/);
  });

  it('grows and shrinks the opened content on the shared transition, as the Accordion does', () => {
    const FOLD = 'details:has(> .fnd-disclosure-summary)';
    expect(declarations(COMPONENTS, FOLD)['interpolate-size']).toBe('allow-keywords');
    expect(declarations(COMPONENTS, `${FOLD}::details-content`)).toMatchObject({
      'block-size': '0',
      overflow: 'clip',
      transition: 'block-size var(--fnd-transition), content-visibility var(--fnd-transition) allow-discrete',
    });
    expect(declarations(COMPONENTS, `details[open]:has(> .fnd-disclosure-summary)::details-content`)['block-size']).toBe('auto');
  });

  it('steps every nested fold 24px in and rules its content under the chevron', () => {
    const FOLD = 'details:has(> .fnd-disclosure-summary)';
    expect(declarations(COMPONENTS, `${FOLD} ${FOLD}`)['margin-inline-start']).toBe('24px');
    expect(() => declarations(COMPONENTS, `${FOLD} ${FOLD} ${FOLD}`)).toThrow(/no rule/);
    // -12px puts the 1px rule under the chevron's centre; 11px more brings the content back to the words.
    expect(declarations(COMPONENTS, `${FOLD} ${FOLD}::details-content`)).toMatchObject({
      'margin-inline-start': '-12px',
      'padding-inline-start': '11px',
      'border-inline-start': '1px solid var(--fnd-line)',
    });
    expect(declarations(COMPONENTS, `${FOLD} + ${FOLD}`)['border-top']).toBe('1px solid var(--fnd-line)');
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

describe('the 资料 page, settings panel and task drawer controls', () => {
  const read = (rel: string) => readFileSync(fileURLToPath(new URL(rel, import.meta.url)), 'utf8');
  const ANALYSIS = read('../src/views/analysis.css');
  const WORKSPACE = read('../src/components/workspace.css');
  const CONTROLS = read('../src/components/financial-controls.css');
  const light = block(TOKENS, ':root');
  const dark = block(TOKENS, ":root[data-theme='dark']");

  it('lets the 范围与计算 fold scroll with the page, with no scroll area of its own', () => {
    expect(ANALYSIS).not.toContain('analysis-finance-setup-dialog');
    const body = declarations(ANALYSIS, '.analysis-finance-setup-body');
    expect(body).not.toHaveProperty('overflow');
    expect(body).not.toHaveProperty('overscroll-behavior');
    expect(ANALYSIS).not.toContain('analysis-finance-setup-scroll');
    // The column around the panes clips rather than hides, so scrollIntoView inside a pane cannot slide it.
    expect(declarations(read('../src/components/components.css'), ".fnd-shell[data-screen='analysis'] .fnd-column").overflow).toBe('clip');
    // The results pane keeps a 24px gutter, room for the fold's hanging chevron.
    expect(declarations(WORKSPACE, '.workspace-results').padding.split(' ')[1]).toBe('24px');
  });

  it('draws the task drawer\'s status segments as ordinary 36px, 14px controls', () => {
    expect(declarations(WORKSPACE, '.workspace-lifecycle button')).toMatchObject({
      'min-height': 'var(--fnd-button-height)', 'font-size': 'var(--fnd-size-body)', 'line-height': '22px',
    });
    expect(light['--fnd-button-height']).toBe('36px');
    expect(light['--fnd-size-body']).toBe('14px');
  });

  it('leaves the period shortcuts to the chip button, with no pressed colours of their own', () => {
    expect(declarations(CONTROLS, '.fnd-period-shortcuts')).toMatchObject({ display: 'flex', 'flex-wrap': 'wrap', gap: '6px' });
    expect(CONTROLS).not.toContain('.fnd-period-shortcuts .fnd-control-icon');
  });

  it('keeps a pressed chip\'s ink edge at 3:1 or better on the surfaces it sits on, in both themes', () => {
    for (const [theme, table] of [['light', light], ['dark', dark]] as const) {
      for (const ground of ['--fnd-surface', '--fnd-bg', '--fnd-selection-surface']) {
        const ratio = contrast(table['--fnd-ink'], over(table[ground], table['--fnd-surface']));
        expect(ratio, `${theme} ink edge on ${ground} is ${ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(3);
      }
    }
  });

  it('renders a chip without the control radius or the body size', async () => {
    const { buttonVariants } = await import('../src/components/ui/button.js');
    const { cn } = await import('../src/lib/utils.js');
    const classes = cn(buttonVariants({ variant: 'outline', size: 'chip' })).split(' ');
    expect(classes).not.toContain('rounded-[var(--fnd-radius-control)]');
    expect(classes).not.toContain('text-[length:var(--fnd-size-body)]');
    expect(classes).toContain('aria-pressed:border-[var(--fnd-ink)]');
  });

  it('keeps the 资料 state words neutral and gives the file meta the 12px label size', () => {
    expect(declarations(ANALYSIS, '.analysis-file-state').color).toBe('var(--fnd-ink)');
    expect(declarations(ANALYSIS, '.analysis-file-status-label').color).toBe('var(--fnd-muted)');
    expect(declarations(ANALYSIS, '.analysis-source-meta')['font-size']).toBe('var(--fnd-size-label)');
    // The old formula-health rule that only re-zeroed a margin nobody sets any more is gone.
    expect(ANALYSIS).not.toContain('.analysis-formula-health [data-slot="button"]');
  });
});

describe('the shape, type and spacing scales', () => {
  /** Every app stylesheet outside the token, font and bridge files, comments removed. */
  const sheets = (() => {
    const root = fileURLToPath(new URL('../src', import.meta.url));
    const found: [string, string][] = [];
    const walk = (dir: string) => {
      for (const name of readdirSync(dir)) {
        const full = `${dir}/${name}`;
        if (statSync(full).isDirectory()) walk(full);
        else if (name.endsWith('.css') && !full.includes('/styles/')) {
          found.push([full.slice(root.length + 1), readFileSync(full, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '')]);
        }
      }
    };
    walk(root);
    return found;
  })();
  const values = (property: RegExp) =>
    sheets.flatMap(([file, css]) => [...css.matchAll(property)].map((match) => [file, match[0]] as const));

  it('rounds corners only with the four radius tokens, or a 1–2px tick', () => {
    expect(sheets.length).toBeGreaterThanOrEqual(7);
    for (const [file, rule] of values(/border-radius:\s*[^;}]+/g)) {
      expect(rule, file).toMatch(/border-radius:\s*(var\(--fnd-radius-(mark|control|container|pill)(,[^)]*)?\)|0|[12]px|50%|inherit)\s*$/);
    }
  });

  it('sizes text only with the type tokens, apart from the brand wordmark and relative code', () => {
    for (const [file, rule] of values(/font-size:\s*[^;}]+/g)) {
      expect(rule, file).toMatch(/font-size:\s*(var\(--fnd-(size-[a-z0-9]+|doc-[a-z]+)(,[^)]*)?\)|inherit|1em|0\.9em|22px)\s*$/);
    }
    expect(values(/font-size:\s*22px/g).map(([file]) => file)).toEqual(['components/components.css']);
  });

  it('keeps every gap and padding on the 4px grid, with 2px and 6px for tight icon pairs', () => {
    // Two measured exceptions: 5px around a 22px summary line makes the 32px compact row, and
    // 11px plus the 1px fold rule is the 12px step; 31px clears the combobox search icon.
    const allowed = new Set([0, 1, 2, 5, 6, 11, 31]);
    for (const [file, rule] of values(/\b(?:row-|column-)?(?:gap|padding(?:-[a-z-]+)?):\s*[^;}]+/g)) {
      for (const [, px] of rule.matchAll(/\b(\d+)px/g)) {
        const n = Number(px);
        expect(n % 4 === 0 || allowed.has(n), `${file}: ${rule}`).toBe(true);
      }
    }
  });
});
