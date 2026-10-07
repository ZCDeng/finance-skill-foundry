import { createHash } from 'node:crypto';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { brotliDecompressSync } from 'node:zlib';
import { describe, expect, it } from 'vitest';

const APP = fileURLToPath(new URL('../', import.meta.url));
const STYLES = resolve(APP, 'src/styles');
const ASSETS = resolve(APP, 'src/assets/fonts');
const FONT = resolve(ASSETS, 'noto-sans-sc/NotoSansSC-variable.woff2');
const CSS = readFileSync(resolve(STYLES, 'fonts.css'), 'utf8');
const FACES = [...CSS.matchAll(/@font-face\s*\{([^}]*)\}/g)].map(([, body]) => ({
  body,
  family: /font-family:\s*'([^']+)'/.exec(body)?.[1],
  weight: /font-weight:\s*([^;]+);/.exec(body)?.[1]?.trim(),
  url: /url\('([^']+)'\)/.exec(body)?.[1],
}));
const KNOWN_TAGS = ['cmap', 'head', 'hhea', 'hmtx', 'maxp', 'name', 'OS/2', 'post', 'cvt ', 'fpgm', 'glyf', 'loca', 'prep', 'CFF ', 'VORG', 'EBDT', 'EBLC', 'gasp', 'hdmx', 'kern', 'LTSH', 'PCLT', 'VDMX', 'vhea', 'vmtx', 'BASE', 'GDEF', 'GPOS', 'GSUB', 'EBSC', 'JSTF', 'MATH', 'CBDT', 'CBLC', 'COLR', 'CPAL', 'SVG ', 'sbix', 'acnt', 'avar', 'bdat', 'bloc', 'bsln', 'cvar', 'fdsc', 'feat', 'fmtx', 'fvar', 'gvar', 'hsty', 'just', 'lcar', 'mort', 'morx', 'opbd', 'prop', 'trak', 'Zapf', 'Silf', 'Glat', 'Gloc', 'Feat', 'Sill'];
const cachedTables = new Map<string, Map<string, Buffer>>();

/** The vendored WOFF2 retains raw SFNT tables, so Node can verify the font
 * directly with its built-in Brotli decoder and no font/package dependency. */
function tables(path = FONT): Map<string, Buffer> {
  const cached = cachedTables.get(path);
  if (cached) return cached;
  const bytes = readFileSync(path);
  expect(bytes.toString('ascii', 0, 4)).toBe('wOF2');
  expect(bytes.readUInt32BE(8)).toBe(bytes.length);
  let cursor = 48;
  const uint128 = () => {
    let value = 0;
    for (let i = 0; i < 5; i++) {
      const byte = bytes[cursor++];
      value = value * 128 + (byte & 127);
      if (!(byte & 128)) return value;
    }
    throw new Error('invalid WOFF2 UIntBase128');
  };
  const directory: { tag: string; size: number }[] = [];
  for (let i = 0; i < bytes.readUInt16BE(12); i++) {
    const flags = bytes[cursor++];
    const index = flags & 63;
    const tag = index === 63 ? bytes.toString('ascii', cursor, cursor += 4) : KNOWN_TAGS[index];
    const outlines = tag === 'glyf' || tag === 'loca';
    // The converted Noto face keeps every table raw; a publisher's WOFF2 (IBM Plex Mono) may transform its outlines,
    // whose bytes these tests never read.
    if (path === FONT) expect(flags >> 6, `${tag} must retain its raw SFNT table`).toBe(outlines ? 3 : 0);
    const transformed = outlines ? flags >> 6 !== 3 : flags >> 6 !== 0;
    const original = uint128();
    directory.push({ tag, size: transformed ? uint128() : original });
  }
  const stream = brotliDecompressSync(bytes.subarray(cursor, cursor + bytes.readUInt32BE(20)));
  expect(stream.length).toBe(directory.reduce((sum, row) => sum + row.size, 0));
  let offset = 0;
  const read = new Map(directory.map(({ tag, size }) => [tag, stream.subarray(offset, offset += size)]));
  cachedTables.set(path, read);
  return read;
}
function table(tag: string, path = FONT) {
  const found = tables(path).get(tag);
  if (!found) throw new Error(`font missing ${tag}`);
  return found;
}
function cmap(path = FONT): Map<number, number> {
  const data = table('cmap', path);
  for (let i = 0; i < data.readUInt16BE(2); i++) {
    const record = 4 + i * 8;
    const platform = data.readUInt16BE(record);
    const encoding = data.readUInt16BE(record + 2);
    const at = data.readUInt32BE(record + 4);
    if (!(platform === 0 || (platform === 3 && encoding === 10)) || data.readUInt16BE(at) !== 12) continue;
    const out = new Map<number, number>();
    for (let group = 0; group < data.readUInt32BE(at + 12); group++) {
      const row = at + 16 + group * 12;
      const first = data.readUInt32BE(row), last = data.readUInt32BE(row + 4), glyph = data.readUInt32BE(row + 8);
      for (let code = first; code <= last; code++) if (glyph + code - first > 0) out.set(code, glyph + code - first);
    }
    return out;
  }
  return bmpCmap(data);
}
/** A BMP-only face (IBM Plex Mono) carries format 4 alone. */
function bmpCmap(data: Buffer): Map<number, number> {
  for (let i = 0; i < data.readUInt16BE(2); i++) {
    const record = 4 + i * 8;
    const at = data.readUInt32BE(record + 4);
    if (!(data.readUInt16BE(record) === 3 && data.readUInt16BE(record + 2) === 1) || data.readUInt16BE(at) !== 4) continue;
    const segments = data.readUInt16BE(at + 6) / 2, ends = at + 14, starts = ends + segments * 2 + 2;
    const deltas = starts + segments * 2, offsets = deltas + segments * 2, out = new Map<number, number>();
    for (let segment = 0; segment < segments; segment++) {
      const end = data.readUInt16BE(ends + segment * 2), start = data.readUInt16BE(starts + segment * 2);
      const delta = data.readInt16BE(deltas + segment * 2), rangeAt = offsets + segment * 2, range = data.readUInt16BE(rangeAt);
      for (let code = start; code <= end && code !== 0xffff; code++) {
        const raw = range ? data.readUInt16BE(rangeAt + range + (code - start) * 2) : code;
        const glyph = raw && (raw + delta) & 0xffff;
        if (glyph) out.set(code, glyph);
      }
    }
    return out;
  }
  throw new Error('font missing a Unicode cmap (format 12 or 4)');
}
function names(path = FONT): Map<number, string[]> {
  const data = table('name', path), storage = data.readUInt16BE(4), out = new Map<number, string[]>();
  for (let i = 0; i < data.readUInt16BE(2); i++) {
    const at = 6 + i * 12;
    if (data.readUInt16BE(at) !== 3) continue;
    const id = data.readUInt16BE(at + 6), size = data.readUInt16BE(at + 8), start = storage + data.readUInt16BE(at + 10);
    const value = Buffer.from(data.subarray(start, start + size)).swap16().toString('utf16le');
    out.set(id, [...(out.get(id) ?? []), value]);
  }
  return out;
}
function manifest() { return JSON.parse(readFileSync(resolve(ASSETS, 'noto-sans-sc/manifest.json'), 'utf8')); }
function reportFontManifest() { return JSON.parse(readFileSync(resolve(ASSETS, 'noto-sans-sc/report-font.json'), 'utf8')); }
function usedCharacters(): Set<number> {
  const used = new Set<number>();
  const walk = (dir: string) => {
    for (const item of readdirSync(dir, { withFileTypes: true })) {
      const path = resolve(dir, item.name);
      if (item.isDirectory()) walk(path);
      else if (/\.tsx?$/.test(item.name)) for (const ch of readFileSync(path, 'utf8')) if (ch.codePointAt(0)! > 0x2000) used.add(ch.codePointAt(0)!);
    }
  };
  walk(resolve(APP, 'src'));
  return used;
}

describe('offline font resources', () => {
  it('ships one full Noto Sans SC variable face and keeps Asap for optional branding', () => {
    expect(FACES.filter((face) => face.family === 'Noto Sans SC')).toHaveLength(1);
    expect(FACES.filter((face) => face.family === 'Asap Sharp')).toHaveLength(3);
    const noto = FACES.find((face) => face.family === 'Noto Sans SC')!;
    expect(noto.weight).toBe('100 900');
    expect(noto.body).not.toContain('unicode-range');
    expect(CSS).not.toMatch(/LXGW|localhost|127\.0\.0\.1|@import\s+url|local\(/);
    expect(existsSync(resolve(ASSETS, 'lxgw-wenkai-mono-tc'))).toBe(false);
  });

  it('resolves every face to an offline asset and includes both OFL licenses', () => {
    for (const face of FACES) {
      expect(face.url).toBeTruthy();
      expect(face.url).not.toMatch(/^(?:https?:|data:|\/)/);
      expect(existsSync(resolve(STYLES, face.url!)), face.url).toBe(true);
    }
    for (const family of ['asap-sharp', 'noto-sans-sc', 'ibm-plex-mono']) {
      const license = readFileSync(resolve(ASSETS, family, 'OFL.txt'), 'utf8');
      expect(license).toContain('SIL OPEN FONT LICENSE');
      expect(CSS).toContain(license.split('\n').map((line) => line.trimEnd()).join('\n'));
    }
    const named = new Set(FACES.map((face) => resolve(STYLES, face.url!)));
    const reportFont = reportFontManifest();
    expect(reportFont.source_sha256).toBe(createHash('sha256').update(readFileSync(FONT)).digest('hex'));
    expect(createHash('sha256').update(readFileSync(resolve(ASSETS, 'noto-sans-sc', reportFont.file))).digest('hex')).toBe(reportFont.sha256);
    for (const family of ['asap-sharp', 'noto-sans-sc', 'ibm-plex-mono']) for (const name of readdirSync(resolve(ASSETS, family))) {
      if (/\.(woff2?|ttf|otf)$/.test(name) && name !== reportFont.file) expect(named.has(resolve(ASSETS, family, name)), name).toBe(true);
    }
  });

  it('ties the shipped font and license to the pinned official source', () => {
    const record = manifest();
    expect(record.source.repository).toBe('https://github.com/google/fonts');
    expect(record.source.commit).toMatch(/^[a-f0-9]{40}$/);
    expect(record.source.sha256).toBe('a3041811a78c361b1de50f953c805e0244951c21c5bd412f7232ef0d899af0da');
    expect(createHash('sha256').update(readFileSync(FONT)).digest('hex')).toBe(record.output.sha256);
    expect(createHash('sha256').update(readFileSync(resolve(ASSETS, 'noto-sans-sc/OFL.txt'))).digest('hex')).toBe(record.license.sha256);
    expect(record.coverage.codepoints).toBe(cmap().size);
  });

  it('uses local relative assets without Vite font inlining', () => {
    const config = readFileSync(resolve(APP, 'vite.config.mts'), 'utf8');
    expect(config).toMatch(/assetsInlineLimit:\s*0/);
    expect(FACES.every((face) => face.url?.startsWith('../assets/fonts/'))).toBe(true);
  });
});

describe('actual Simplified Chinese glyphs and variable weights', () => {
  it('contains the SC family, not a TC face carrying a CSS alias', () => {
    expect(names().get(16)).toContain('Noto Sans SC');
    expect(names().get(16)).not.toContain('Noto Sans TC');
    expect(cmap().size).toBeGreaterThan(30000);
  });

  it('covers the interface and financial vocabulary from its real cmap', () => {
    const mapping = cmap(), used = usedCharacters();
    for (const char of '财务经理资产负债利润账簿建账资金应收应付预算现金流货币增值税人民币¥￥€−，。％（）') used.add(char.codePointAt(0)!);
    expect(used.size).toBeGreaterThan(300);
    expect([...used].filter((point) => !mapping.has(point)).map((point) => `U+${point.toString(16)}`)).toEqual([]);
  });

  it('has a real 100–900 weight axis and Chinese glyph variations for all UI weights', () => {
    const fvar = table('fvar'), offset = fvar.readUInt16BE(4), count = fvar.readUInt16BE(8), size = fvar.readUInt16BE(10);
    const axes = Array.from({ length: count }, (_, i) => {
      const at = offset + i * size;
      return { tag: fvar.toString('ascii', at, at + 4), min: fvar.readInt32BE(at + 4) / 65536, max: fvar.readInt32BE(at + 12) / 65536 };
    });
    expect(axes).toContainEqual({ tag: 'wght', min: 100, max: 900 });
    const gvar = table('gvar'), width = gvar.readUInt16BE(14) & 1 ? 4 : 2, mapping = cmap();
    const glyphOffset = (glyph: number) => width === 4 ? gvar.readUInt32BE(20 + glyph * 4) : gvar.readUInt16BE(20 + glyph * 2) * 2;
    for (const char of '财务分析账资') {
      const glyph = mapping.get(char.codePointAt(0)!)!;
      expect(glyphOffset(glyph + 1), char).toBeGreaterThan(glyphOffset(glyph));
    }
    const samples = manifest().weights as Record<string, { outline_sha256: string }>;
    expect(Object.keys(samples)).toEqual(['400', '500', '600', '700']);
    expect(new Set(Object.values(samples).map((sample) => sample.outline_sha256)).size).toBe(4);
  });

  it('has naturally equal-width digits and records measured widths at every UI weight', () => {
    const mapping = cmap(), metrics = table('hmtx'), count = table('hhea').readUInt16BE(34);
    const widths = [...'0123456789'].map((digit) => metrics.readUInt16BE(Math.min(mapping.get(digit.codePointAt(0)!)!, count - 1) * 4));
    expect(new Set(widths).size).toBe(1);
    const measured = manifest();
    expect(measured.numerals.mode).toBe('equal-default-advances');
    expect(measured.numerals.has_tnum_feature).toBe(false);
    for (const sample of Object.values(measured.weights) as { digit_advances: number[] }[]) {
      expect(sample.digit_advances).toHaveLength(10);
      expect(new Set(sample.digit_advances).size).toBe(1);
    }
  });
});

describe('IBM Plex Mono figures', () => {
  const PLEX = resolve(ASSETS, 'ibm-plex-mono');
  const record = () => JSON.parse(readFileSync(resolve(PLEX, 'manifest.json'), 'utf8'));
  const plexFaces = (family: string) => FACES.filter((face) => face.family === family);

  it('registers the three table weights twice: whole figure runs, and digits inside sentences', () => {
    for (const family of ['IBM Plex Mono', 'FND Figures']) {
      expect(plexFaces(family).map((face) => face.weight)).toEqual(['400', '600', '700']);
    }
    for (const face of plexFaces('IBM Plex Mono')) expect(face.body).toContain('unicode-range: U+0020-007E, U+00A0-00FF, U+2030, U+2212;');
    // Only digits and % in prose: commas, points and every Chinese character stay in the sentence's face.
    for (const face of plexFaces('FND Figures')) expect(face.body).toContain('unicode-range: U+0025, U+0030-0039;');
    expect(plexFaces('FND Figures').map((face) => face.url)).toEqual(plexFaces('IBM Plex Mono').map((face) => face.url));
  });

  it("ships the publisher's own WOFF2 files byte for byte, so the reserved name stays on an unmodified font", () => {
    const manifest = record();
    expect(manifest.source.package).toBe('@ibm/plex-mono');
    expect(manifest.source.tarball).toMatch(/^https:\/\/registry\.npmjs\.org\/@ibm\/plex-mono\/-\/plex-mono-\d+\.\d+\.\d+\.tgz$/);
    expect(manifest.source.sha256).toMatch(/^[a-f0-9]{64}$/);
    expect(manifest.build).toEqual({ copied_unmodified: true, subset: false, converted: false });
    expect(manifest.license.reserved_font_name).toBe('Plex');
    expect(createHash('sha256').update(readFileSync(resolve(PLEX, 'OFL.txt'))).digest('hex')).toBe(manifest.license.sha256);
    expect(manifest.faces.map((face: { weight: number }) => face.weight)).toEqual([400, 600, 700]);
    for (const face of manifest.faces as { file: string; sha256: string; weight: number }[]) {
      const path = resolve(PLEX, face.file);
      expect(createHash('sha256').update(readFileSync(path)).digest('hex')).toBe(face.sha256);
      expect(names(path).get(1)?.[0]).toMatch(/^IBM Plex Mono\b/);
      expect(table('OS/2', path).readUInt16BE(4), face.file).toBe(face.weight);
    }
  });

  it('gives every character a figure is written with one width at every weight', () => {
    const characters = record().figure_characters as string;
    expect(characters).toContain('()');
    expect(characters).toContain('\u2212');
    for (const face of record().faces as { file: string }[]) {
      const path = resolve(PLEX, face.file);
      const mapping = cmap(path), metrics = table('hmtx', path), count = table('hhea', path).readUInt16BE(34);
      const widths = [...characters].map((char) => metrics.readUInt16BE(Math.min(mapping.get(char.codePointAt(0)!)!, count - 1) * 4));
      expect(new Set(widths), face.file).toEqual(new Set([600]));
    }
  });
});
