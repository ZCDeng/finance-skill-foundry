# IBM Plex Mono — FA Foundry figure font

Financial figures (table amounts, KPI values, amount inputs, and the digits inside
result sentences) are drawn in **IBM Plex Mono**. Every digit, comma, decimal
point, minus sign, parenthesis, percent sign and space is 600/1000 em wide, so a
right-aligned column of amounts lines up at the last digit with no `tnum` feature.
Chinese text and units keep Noto Sans SC.

## Official source and license

- Publisher package: npm [`@ibm/plex-mono@2.5.0`](https://registry.npmjs.org/@ibm/plex-mono/-/plex-mono-2.5.0.tgz)
  from [IBM/plex](https://github.com/IBM/plex) (font version 2.005). Tarball SHA-256
  `55b5ffcfcd5e9db36ef2070b2b07a573434ca02c6f3be2b921c0b88fff29acad`.
- Three static weights only: Regular 400 (detail rows), SemiBold 600 (subtotals,
  headers, KPI values) and Bold 700 (totals). That is the three-weight table rule.
- License: [SIL Open Font License 1.1](OFL.txt), the package's own `LICENSE.txt`,
  with the Reserved Font Name "Plex". The OFL counts even a format change as a
  Modified Version, and a Modified Version may not use the reserved name. So the
  WOFF2 files are IBM's own, copied byte for byte from
  `package/fonts/complete/woff2/`, and are never converted, subset or renamed. The
  OFL is also embedded in a preserved `/*! ... */` comment in `styles/fonts.css`,
  and it ships beside the app in `fonts/ibm-plex-mono/OFL.txt`.

- Word export: Word embeds TrueType only, and the npm package has none. The
  Regular face `IBMPlexMono-Regular.ttf` comes from IBM's own GitHub release
  archive for the same version (`ibm-plex-mono.zip`, pinned by SHA-256), copied
  byte for byte from `fonts/complete/ttf/`. Its embedding permission (fsType) is 0,
  installable. That archive's WOFF2 files and license are byte-identical to the
  npm ones.

`manifest.json` records each face's SHA-256 and byte count, and the measured equal
advance of every figure character.

## Report exports

The faces also ship as app resources in `fonts/ibm-plex-mono/` (electron-builder
`extraResources`), checked by `scripts/check-packaged-font.cjs` after packing.
HTML and PDF exports embed the three WOFF2 faces as data URLs under the same two
families; Word embeds the Regular TTF; charts rasterized for Word load the WOFF2
faces. See DESIGN.md 文稿和导出里的数字.

## Loading contract

`styles/fonts.css` registers the same three files under two families:

- `IBM Plex Mono` (`--fnd-font-figure`) covers Basic Latin, Latin-1, `‰` and
  `−`. Figure cells use this family, so grouping, sign and parentheses hold the
  column. Chinese units such as 万元 and 个百分点 fall through to Noto Sans SC.
- `FND Figures` (`--fnd-font-prose`) covers only `0`–`9` and `%`. Result
  sentences use this family, so their numbers read in Plex Mono while words,
  commas and points stay in the sentence's own face. The text is never split.

No `local()` is used and nothing loads from Google Fonts at runtime. Vite emits the
files as assets (`assetsInlineLimit: 0`) under the renderer CSP `font-src 'self'`.

## Rebuild and verify

Use an existing Python environment with fontTools and Brotli. The script never
installs dependencies and is not required at application runtime.

```sh
python3 app/scripts/build-figure-font.py --check   # offline, bundled files only
python3 app/scripts/build-figure-font.py           # download the pinned package and copy the faces
```
