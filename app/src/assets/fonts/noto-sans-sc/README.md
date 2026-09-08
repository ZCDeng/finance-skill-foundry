# Noto Sans SC — FA Foundry offline font

## Editable Word reports

`NotoSansSC-report.ttf` is the full 400-weight static instance of the same
approved WOFF2, used only for DOCX embedding. It retains every glyph and the
original license/name tables; OS/2 `fsType=0` permits editable embedding.
`report-font.json` records its source and output SHA-256. Regenerate offline
with `python3 app/scripts/build-report-font.py` (fontTools 4.63.0). The packaged
app includes this TTF and OFL beside the runtime. The DOCX writer embeds it using
OOXML font relationships; reader support for embedded fonts varies. The UI
continues to use the full variable WOFF2 and real weights.

The interface and embedded conversation use **Noto Sans SC**, the Simplified
Chinese regional font. Asap Sharp remains available separately for branding.
Nothing in this font delivery depends on a system installation or a local font
server.

## Official source and license

- Repository: [google/fonts](https://github.com/google/fonts/tree/5e35378e6bda803962ee6fd257e444a7d459660d/ofl/notosanssc)
- Pinned commit: `5e35378e6bda803962ee6fd257e444a7d459660d`
- Source: [`NotoSansSC[wght].ttf`](https://github.com/google/fonts/blob/5e35378e6bda803962ee6fd257e444a7d459660d/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf)
- Official [METADATA.pb](https://github.com/google/fonts/blob/5e35378e6bda803962ee6fd257e444a7d459660d/ofl/notosanssc/METADATA.pb) identifies `Hans`, `zh_Hans`, and the `wght` axis from 100 to 900. An unchanged copy is included here.
- License: [SIL Open Font License 1.1](OFL.txt), including Adobe's copyright
  notice and reserved name `Source`. The OFL travels with this resource and is
  also embedded in a preserved `/*! ... */` comment in `styles/fonts.css`, so
  the compiled renderer stylesheet carries it when Vite copies only referenced
  assets. The WOFF2 retains the font's original name and license metadata.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| Official source TTF | 17,772,300 | `a3041811a78c361b1de50f953c805e0244951c21c5bd412f7232ef0d899af0da` |
| Bundled `NotoSansSC-variable.woff2` | 8,490,924 | `97a715fad95d3cacf4838b1ffedb123d2f1bf0f6bbd726c73e147dcaf317869f` |
| `OFL.txt` | 4,388 | `1c05c68c34f9708415aada51f17e1b0092d2cea709bf4a94cd38114f9e73d7d9` |

`manifest.json` records these hashes, conversion version, measured coverage,
weight samples and numeric advances.

## Loading contract

Use the same single WOFF2 in the renderer and native conversation:

```css
@font-face {
  font-family: 'Noto Sans SC';
  src: url('NotoSansSC-variable.woff2') format('woff2');
  font-style: normal;
  font-weight: 100 900;
  font-display: swap;
}
```

The renderer's actual relative URL is in `app/src/styles/fonts.css`. The native
conversation can embed the bytes of this file through its existing font-loading
path. Do not add `local()` ahead of the bundled file: that would bypass the
verified version and regional glyphs. Use `font-synthesis: none` in the interface
and 400, 500, 600 or 700 for the real variable weights. No glyph subsetting,
weight-axis restriction or outline editing was performed during conversion.

## Measurements

- 30,890 Unicode codepoints and 31,036 glyphs; all glyphs in the official SC
  regional font are retained.
- Real `wght` axis: 100–900. The source's default instance is 100; the CSS face
  range supports the interface's explicit/default CSS weight 400 correctly.
- The Chinese glyph `财` has distinct measured outline hashes at 400, 500, 600
  and 700. The hashes and numeric advance measurements are in `manifest.json`.
- All 394 non-ASCII codepoints used in the renderer's TypeScript source when
  introduced are present. The test rechecks the current source on each run.
- Digits `0`–`9` have the same advance **within each weight**, as measured from
  the actual variable glyph set. The font does not expose a `tnum` GSUB feature;
  its default digit widths are already equal. Amounts may use this family and
  `font-variant-numeric: tabular-nums`; the equal widths do not depend on that
  feature. Keep rows at the same weight and align amounts to the right.

## Rebuild and verify

Use an existing Python environment with `fontTools` and Brotli. The script never
installs dependencies and is not required at application runtime.

```sh
python3 app/scripts/build-noto-font.py
python3 app/scripts/build-noto-font.py --check
node app/node_modules/vitest/vitest.mjs run --root app tests/fonts.test.ts
```

The rebuild downloads only the pinned official font, OFL and metadata, verifies
all source hashes, and converts with `fontTools 4.63.0` and unchanged timestamps.
`--source-dir /path/to/already-downloaded-files` reuses verified local sources.
`--check` performs no network requests: it checks file hashes, glyph coverage,
axes, outline differences and the actual digit advances at all four UI weights.

The WOFF2 uses Brotli compression with no optional table transformations. This
preserves raw SFNT tables and allows the Vitest suite to examine the actual
`name`, `cmap`, `fvar`, `gvar`, `hhea` and `hmtx` data using Node's built-in Brotli
decoder. The tests therefore need no font parsing package or Python dependency.
