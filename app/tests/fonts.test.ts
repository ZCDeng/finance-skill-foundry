import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const STYLES = fileURLToPath(new URL('../src/styles/', import.meta.url));
const FONTS_CSS = readFileSync(resolve(STYLES, 'fonts.css'), 'utf8');
const TOKENS_CSS = readFileSync(resolve(STYLES, 'tokens.css'), 'utf8');
const ASSETS = fileURLToPath(new URL('../src/assets/fonts/', import.meta.url));

const LATIN = 'Asap Sharp';
const CJK = 'LXGW WenKai Mono TC';

interface Face {
  family: string;
  weight: string;
  url: string;
  ranges: number[][];
}

/** Every `@font-face` in the bundled stylesheet, as family, url and ranges. */
function faces(): Face[] {
  const out: Face[] = [];
  for (const [, body] of FONTS_CSS.matchAll(/@font-face\s*\{([^}]*)\}/g)) {
    const family = /font-family:\s*'([^']+)'/.exec(body)?.[1];
    const url = /url\('([^']+)'\)/.exec(body)?.[1];
    const weight = /font-weight:\s*([^;]+);/.exec(body)?.[1]?.trim();
    if (!family || !url || !weight) continue;
    const declared = /unicode-range:\s*([^;]+);/.exec(body)?.[1] ?? '';
    const ranges: number[][] = [];
    for (const part of declared.split(',')) {
      const text = part.trim().replace(/^U\+/i, '');
      if (!text) continue;
      const [lo, hi] = text.split('-');
      ranges.push([parseInt(lo, 16), parseInt(hi ?? lo, 16)]);
    }
    out.push({ family, weight, url, ranges });
  }
  return out;
}

const FACES = faces();

describe('the bundled faces', () => {
  it('ships both families, sliced the way the foundry serves them', () => {
    const counts = new Map<string, number>();
    for (const face of FACES) counts.set(face.family, (counts.get(face.family) ?? 0) + 1);
    expect([...counts.keys()].sort()).toEqual([LATIN, CJK].sort());
    // Three Latin subsets carrying the whole 400-700 axis between them, and
    // 115 CJK slices per weight in two cuts. A number that moved means the
    // table was regenerated, and the coverage check below is the one that says
    // whether that was safe.
    expect(counts.get(LATIN)).toBe(3);
    expect(counts.get(CJK)).toBe(230);
  });

  /*
   * The bold is why this table doubled, and it is the half that is easy to
   * ship broken: Asap Sharp carries its own bold on a variable axis, so Latin
   * looks right whether or not the Chinese 700 was ever staged. A missing
   * Chinese cut shows up only in Chinese, only in bold, and only as a slightly
   * lighter word than the one beside it.
   */
  it('carries a real bold in both scripts, not a synthesised one', () => {
    const latin = FACES.filter((f) => f.family === LATIN).map((f) => f.weight);
    expect(new Set(latin)).toEqual(new Set(['400 700']));
    const cjk = new Set(FACES.filter((f) => f.family === CJK).map((f) => f.weight));
    expect(cjk).toEqual(new Set(['400', '700']));
  });

  /*
   * The failure this catches is silent and total: a rule whose url names a file
   * that is not there renders nothing for that range, and the browser falls
   * through to a system face without saying so. It was a real mistake on the
   * way in -- a naming collision in the download dropped eight slices, and
   * nothing in the running app would have reported it.
   */
  it('has a file behind every url it declares', () => {
    const missing = FACES.filter(
      (face) => !existsSync(resolve(STYLES, face.url)),
    ).map((face) => face.url);
    expect(missing).toEqual([]);
  });

  it('carries the licence beside each family', () => {
    // Both are OFL 1.1, which asks that the licence travel with the files.
    for (const dir of ['asap-sharp', 'lxgw-wenkai-mono-tc']) {
      const licence = resolve(ASSETS, dir, 'OFL.txt');
      expect(existsSync(licence), `${dir}/OFL.txt`).toBe(true);
      expect(readFileSync(licence, 'utf8')).toContain('SIL OPEN FONT LICENSE');
    }
  });

  it('leaves nothing in the font directories that no rule names', () => {
    // A face dropped from the table but left on disk is dead weight inside the
    // bundle, and one that is still on disk under an old name reads like it is
    // still in use.
    const named = new Set(FACES.map((face) => resolve(STYLES, face.url)));
    for (const dir of ['asap-sharp', 'lxgw-wenkai-mono-tc']) {
      for (const file of readdirSync(resolve(ASSETS, dir))) {
        if (!file.endsWith('.woff2')) continue;
        expect(named.has(resolve(ASSETS, dir, file)), `${dir}/${file} is not in fonts.css`).toBe(
          true,
        );
      }
    }
  });
});

describe('the fall-through between them', () => {
  /*
   * The mechanism, and it only runs in one order. LXGW WenKai Mono TC carries a
   * Latin of its own, so naming it first would give it every English word in
   * the product and Asap Sharp would never draw. Swapping these two names is a
   * one-character edit that silently changes the whole product's typeface.
   */
  it('names the Latin face before the Chinese one, in both stacks', () => {
    for (const token of ['--fnd-font-sans', '--fnd-font-display']) {
      const stack = new RegExp(`${token}:\\s*([^;]+);`).exec(TOKENS_CSS)?.[1];
      expect(stack, token).toBeTruthy();
      const latin = stack!.indexOf(LATIN);
      const cjk = stack!.indexOf(CJK);
      expect(latin, `${token} does not name ${LATIN}`).toBeGreaterThanOrEqual(0);
      expect(cjk, `${token} does not name ${CJK}`).toBeGreaterThan(latin);
    }
  });

  it('keeps a system Chinese face behind them', () => {
    // Not the plan, the safety net. A stack that ran straight to `sans-serif`
    // would still render, in whatever the platform picked, which is how a
    // bundled Chinese face was once deleted without a single test failing.
    expect(TOKENS_CSS).toContain('PingFang SC');
  });
});

describe('what the Chinese face can actually draw', () => {
  /** Every codepoint one cut of the CJK family declares, across its slices. */
  function covered(weight: string): Set<number> {
    const out = new Set<number>();
    for (const face of FACES) {
      if (face.family !== CJK || face.weight !== weight) continue;
      for (const [lo, hi] of face.ranges) {
        for (let c = lo; c <= hi; c += 1) out.add(c);
      }
    }
    return out;
  }

  /** Every non-ASCII character the renderer's own source puts on screen. */
  function used(): Set<string> {
    const out = new Set<string>();
    const walk = (dir: string) => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const path = resolve(dir, entry.name);
        if (entry.isDirectory()) walk(path);
        else if (/\.tsx?$/.test(entry.name)) {
          for (const ch of readFileSync(path, 'utf8')) {
            if (ch.codePointAt(0)! > 0x2000) out.add(ch);
          }
        }
      }
    };
    walk(resolve(dirname(STYLES)));
    return out;
  }

  /*
   * The one thing worth doubting about this pairing.
   *
   * LXGW WenKai Mono TC is the Traditional Chinese cut of the family and every
   * sentence in this window is Simplified. It does cover them -- 17,730
   * codepoints, and all 197 characters the renderer uses -- but that is a fact
   * about today's strings, not a property of the font. This is what turns the
   * next sentence written with a character it cannot draw into a red test
   * rather than into a tofu box in front of an operator.
   */
  it('covers every character the interface is written in, at every weight', () => {
    for (const weight of ['400', '700']) {
      const table = covered(weight);
      const missing = [...used()].filter((ch) => !table.has(ch.codePointAt(0)!));
      expect(
        missing,
        `not in ${CJK} ${weight}: ${missing
          .map((c) => `${c} U+${c.codePointAt(0)!.toString(16)}`)
          .join(', ')}`,
      ).toEqual([]);
    }
  });

  it('is a wide enough face that this is a real check', () => {
    // A table that had lost its ranges would pass the check above by covering
    // nothing and being asked about nothing. This is the floor under it.
    expect(covered('400').size).toBeGreaterThan(15000);
    expect(covered('700').size).toBeGreaterThan(15000);
    expect(used().size).toBeGreaterThan(100);
  });
});

describe('what the build actually emits', () => {
  /** The built stylesheet, if a build has been run in this checkout. */
  function built(): string | null {
    const dir = fileURLToPath(new URL('../dist-vite/assets/', import.meta.url));
    if (!existsSync(dir)) return null;
    const sheets = readdirSync(dir).filter((name) => name.endsWith('.css'));
    if (sheets.length === 0) return null;
    return sheets.map((name) => readFileSync(resolve(dir, name), 'utf8')).join('\n');
  }

  /*
   * Both failures below only appear in a packaged build. The dev server shows
   * neither, so without this the first sign of either would be an operator
   * looking at the wrong thing.
   */
  it('inlines no face as a data: URI, which the policy would block', () => {
    // `default-src 'none'` with `font-src 'self'` does not cover `data:`.
    // Three of the Chinese slices are under Vite's default 4 KB inline limit,
    // so this was real: they were inlined, and would have drawn tofu for their
    // ranges in the packaged app only. See `assetsInlineLimit` in the config.
    const css = built();
    if (css === null) return;
    expect(css).not.toContain('url(data:font');
    expect(css).not.toContain('url("data:font');
  });

  it('emits the table once, not once per stylesheet that reaches it', () => {
    // `fonts.css` used to be imported from `tokens.css`, which two entry
    // stylesheets import, so every rule landed in the bundle twice.
    const css = built();
    if (css === null) return;
    const rules = [...css.matchAll(/@font-face/g)].length;
    expect(rules).toBe(FACES.length);
  });

  it('ships a file for every slice it names', () => {
    const css = built();
    if (css === null) return;
    const dir = fileURLToPath(new URL('../dist-vite/assets/', import.meta.url));
    const named = [...css.matchAll(/url\(\.\/([^)]+\.woff2)\)/g)].map((m) => m[1]);
    expect(new Set(named).size).toBe(FACES.length);
    for (const file of new Set(named)) {
      expect(existsSync(resolve(dir, file)), file).toBe(true);
    }
  });
});
