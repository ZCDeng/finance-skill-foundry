/**
 * 看板快照: the manager's accepted cards as one A4 landscape page, printed to PDF or drawn as a PNG for a slide.
 *
 * The renderer sends what the board shows as data (texts, figures, bars, steps), never markup. This file checks
 * that shape, escapes every text and draws the bars itself in paper colours: the board's own look, fixed for print as
 * visuals.ts fixes a report's charts. Before anything is filed the server holds the same data to the board
 * (foundry/dashboard_snapshot.py): accepted cards only, every figure the cell its run holds.
 *
 * Nothing here touches Electron or the file system: the board reads the same limits and types, and
 * dashboard-print.ts prints the page.
 */
export type SnapshotFormat = 'pdf' | 'pptx' | 'xlsx';
export const SNAPSHOT_FORMATS: readonly SnapshotFormat[] = ['pdf', 'pptx', 'xlsx'];

/** A figure as the board shows it: accounting form, and whether it is below zero. */
export type SnapshotText = { text: string; negative: boolean };
/** The screening light a collection-health figure carries (CollectionHealthView's levels). */
export type SnapshotLevel = 'red' | 'orange' | 'yellow' | 'green' | 'unknown';
export type SnapshotNamed = { card_id: string; title: string };

export interface SnapshotFigure {
  card_id: string; title: string; subject: string; part: string;
  value: SnapshotText; level: SnapshotLevel | null; level_label: string;
  beside: { label: string; text: string }[];
  note: string; source: number;
  /** The run's own cell behind the figure, for the server to hold it to. */
  cell: { column: string; value: string };
}
export interface SnapshotRank {
  card_id: string; kind: 'rank'; title: string; unit: string; note: string; source: number;
  items: { label: string; value: number; shown: SnapshotText; note: string }[];
  reference: { value: number; label: string } | null;
}
export interface SnapshotBridge {
  card_id: string; kind: 'bridge'; title: string; unit: string; note: string; source: number;
  steps: { label: string; kind: 'total' | 'delta'; value: number; shown: SnapshotText }[];
}
export interface DashboardSnapshot {
  version: 1;
  board_id: string;
  task: string;
  period: string;
  figures: SnapshotFigure[];
  charts: (SnapshotRank | SnapshotBridge)[];
  /** One per card on the page: where its figure came from. */
  sources: { n: number; card_id: string; title: string; run: string; lines: string[] }[];
  /** One per run the page reads, keyed A, B, … */
  runs: { key: string; run_id: string; label: string; computed: string; files: string[] }[];
  /** Accepted cards the page has no room for; a workbook snapshot has them all. */
  beyond: SnapshotNamed[];
  /** Cards on the board that no snapshot shows: waiting for the manager, and 回款情景 what-ifs. */
  left_out: { pinned: SnapshotNamed[]; scenario: SnapshotNamed[] };
  /** The 署名 it was exported under (设置 › 使用者); absent when nobody was chosen. A name, not a permission. */
  signed_by?: string;
}

/** One page holds two rows of six figures; three charts beside more than six figures, else six. */
export const PAGE_FIGURES = 12;
export function pageCharts(figures: number): number { return figures <= 6 ? 6 : 3; }

const CONTROL = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/;
const ID = /^[0-9a-f]{32}$/;
const MAX_CARDS = 40;

function object(raw: unknown, label: string): Record<string, unknown> {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw) || ![Object.prototype, null].includes(Object.getPrototypeOf(raw))) {
    throw new Error(`看板快照的${label}必须是对象`);
  }
  return raw as Record<string, unknown>;
}
function list(raw: unknown, label: string, max: number): unknown[] {
  if (!Array.isArray(raw) || raw.length > max) throw new Error(`看板快照的${label}最多 ${max} 项`);
  return raw;
}
function text(raw: unknown, label: string, max = 200, required = false): string {
  if (typeof raw !== 'string' || CONTROL.test(raw) || Array.from(raw).length > max || (required && !raw.trim())) {
    throw new Error(`看板快照的${label}必须是 ${max} 字以内的文本`);
  }
  return raw;
}
function finite(raw: unknown, label: string): number {
  if (typeof raw !== 'number' || !Number.isFinite(raw)) throw new Error(`看板快照的${label}必须是有限数字`);
  return raw;
}
function id(raw: unknown, label: string): string {
  if (typeof raw !== 'string' || !ID.test(raw)) throw new Error(`看板快照的${label}无效`);
  return raw;
}
function shown(raw: unknown, label: string): SnapshotText {
  const value = object(raw, label);
  if (typeof value.negative !== 'boolean') throw new Error(`看板快照的${label}要说明正负`);
  return { text: text(value.text, label), negative: value.negative };
}
function named(raw: unknown, label: string): SnapshotNamed[] {
  return list(raw, label, MAX_CARDS).map((item) => {
    const row = object(item, label);
    return { card_id: id(row.card_id, label), title: text(row.title, label) };
  });
}

/** The snapshot's shape, every text bounded. ``page``: it is laid out as one page, so it holds what a page holds. */
export function normalizeSnapshot(raw: unknown, page: boolean): DashboardSnapshot {
  const model = object(raw, '内容');
  if (model.version !== 1) throw new Error('看板快照的版本无效');
  const figures = list(model.figures, '数字', MAX_CARDS).map((raw): SnapshotFigure => {
    const item = object(raw, '数字');
    const cell = object(item.cell, '取数单元格');
    if (item.level !== null && !['red', 'orange', 'yellow', 'green', 'unknown'].includes(String(item.level))) throw new Error('看板快照的级别无效');
    return {
      card_id: id(item.card_id, '卡片'), title: text(item.title, '卡片标题', 200, true), subject: text(item.subject, '主体'), part: text(item.part, '取数'),
      value: shown(item.value, '数字'), level: item.level as SnapshotLevel | null, level_label: text(item.level_label, '级别说明'),
      beside: list(item.beside, '旁注', 6).map((pair) => { const row = object(pair, '旁注'); return { label: text(row.label, '旁注'), text: text(row.text, '旁注') }; }),
      note: text(item.note, '卡片说明'), source: finite(item.source, '来源编号'),
      // A run's decimals can run long; the cell goes as the run holds it.
      cell: { column: text(cell.column, '取数列', 200, true), value: text(cell.value, '取数值', 1000, true) },
    };
  });
  const charts = list(model.charts, '图', MAX_CARDS).map((raw): SnapshotRank | SnapshotBridge => {
    const item = object(raw, '图');
    const common = { card_id: id(item.card_id, '卡片'), title: text(item.title, '图标题', 200, true), unit: text(item.unit, '单位'),
      note: text(item.note, '卡片说明'), source: finite(item.source, '来源编号') };
    if (item.kind === 'rank') {
      const reference = item.reference === null ? null : object(item.reference, '参考线');
      return { ...common, kind: 'rank',
        items: list(item.items, '排名', 50).map((bar) => { const row = object(bar, '排名');
          return { label: text(row.label, '排名名称', 200, true), value: finite(row.value, '排名数值'), shown: shown(row.shown, '排名数字'), note: text(row.note, '排名说明') }; }),
        reference: reference && { value: finite(reference.value, '参考线'), label: text(reference.label, '参考线') } };
    }
    if (item.kind === 'bridge') {
      return { ...common, kind: 'bridge',
        steps: list(item.steps, '利润桥', 8).map((step) => { const row = object(step, '利润桥');
          if (row.kind !== 'total' && row.kind !== 'delta') throw new Error('看板快照的利润桥步骤无效');
          return { label: text(row.label, '利润桥步骤', 200, true), kind: row.kind, value: finite(row.value, '利润桥数值'), shown: shown(row.shown, '利润桥数字') }; }) };
    }
    throw new Error('看板快照的图只有排名和利润桥');
  });
  const left = object(model.left_out, '没放进来的卡');
  const snapshot: DashboardSnapshot = {
    version: 1, board_id: id(model.board_id, '看板版本'), task: text(model.task, '任务'), period: text(model.period, '期间'),
    figures, charts,
    sources: list(model.sources, '来源', MAX_CARDS).map((raw) => { const row = object(raw, '来源');
      return { n: finite(row.n, '来源编号'), card_id: id(row.card_id, '卡片'), title: text(row.title, '来源'), run: text(row.run, '计算', 8, true),
        lines: list(row.lines, '来源', 12).map((line) => text(line, '来源', 600)) }; }),
    runs: list(model.runs, '计算', MAX_CARDS).map((raw) => { const row = object(raw, '计算');
      return { key: text(row.key, '计算', 8, true), run_id: id(row.run_id, '计算编号'), label: text(row.label, '计算'), computed: text(row.computed, '计算'),
        files: list(row.files, '资料', 20).map((name) => text(name, '资料', 600)) }; }),
    beyond: named(model.beyond, '放不下的卡'),
    left_out: { pinned: named(left.pinned, '待认可的卡'), scenario: named(left.scenario, '情景卡') },
    ...(model.signed_by ? { signed_by: text(model.signed_by, '导出人', 80, true) } : {}),
  };
  if (page && (figures.length > PAGE_FIGURES || charts.length > pageCharts(figures.length))) throw new Error('一页纸放不下这么多卡。');
  if (!figures.length && !charts.length) throw new Error('看板上还没有认可的卡。');
  return snapshot;
}

// --- the page ---------------------------------------------------------------------------------

// Paper colours: the board's light theme (src/styles/tokens.css), fixed so a dark desktop prints the same page.
const INK = '#1c2232';
const MUTED = '#5b6176';
const LINE = '#dfe1e7';
const ZERO = '#a9adbd';
const NEGATIVE = '#94463d';
const REFERENCE = '#c96a5c';
const UP = '#4f7553';
const LEVEL_COLOURS: Record<SnapshotLevel, string> = { red: '#a3372b', orange: '#c96a5c', yellow: '#a35f1f', green: '#4f7553', unknown: '#6b6b6b' };
const FIGURE_FONT = "'IBM Plex Mono', 'Noto Sans SC', sans-serif";
const PROSE_FONT = "'FND Figures', 'Noto Sans SC', sans-serif";

export function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]!);
}
const num = (value: number) => String(Math.round(value * 100) / 100);
const short = (value: string, max: number) => (Array.from(value).length > max ? `${Array.from(value).slice(0, max - 1).join('')}…` : value);

function domain(values: number[]): [number, number] {
  const low = Math.min(0, ...values);
  const high = Math.max(0, ...values);
  if (low === high) return [low, high + 1];
  return [low, high];
}

/** A rank card's bars: worst first as the card orders them, below zero in the negative red, its line dashed. */
export function rankSvg(chart: SnapshotRank, width: number): string {
  const ROW = 20, LABEL = 84, VALUE = 76;
  const rows = chart.items;
  const [low, high] = domain([...rows.map((row) => row.value), ...(chart.reference ? [chart.reference.value] : [])]);
  const x = (value: number) => LABEL + 6 + ((value - low) / (high - low)) * (width - LABEL - VALUE - 12);
  const height = rows.length * ROW + (chart.reference ? 18 : 4);
  const zero = x(0);
  const bars = rows.map((row, index) => {
    const top = index * ROW + 3;
    const left = Math.min(zero, x(row.value));
    return `<text x="${LABEL}" y="${num(top + 11)}" text-anchor="end" font-family="${PROSE_FONT}" font-size="11" fill="${MUTED}">${escapeHtml(short(row.label, 7))}</text>`
      + `<rect x="${num(left)}" y="${num(top)}" width="${num(Math.max(1, Math.abs(x(row.value) - zero)))}" height="${ROW - 7}" fill="${row.value < 0 ? NEGATIVE : INK}" fill-opacity="${row.value < 0 ? 1 : 0.78}"/>`
      + `<text x="${num(width - VALUE + 6)}" y="${num(top + 11)}" font-family="${FIGURE_FONT}" font-size="11" fill="${row.shown.negative ? NEGATIVE : INK}">${escapeHtml(row.shown.text)}</text>`;
  }).join('');
  const reference = chart.reference
    ? `<line x1="${num(x(chart.reference.value))}" x2="${num(x(chart.reference.value))}" y1="0" y2="${rows.length * ROW}" stroke="${REFERENCE}" stroke-width="1.5" stroke-dasharray="5 4"/>`
      + `<text x="${num(x(chart.reference.value))}" y="${rows.length * ROW + 13}" text-anchor="middle" font-family="${PROSE_FONT}" font-size="10" fill="${MUTED}">${escapeHtml(chart.reference.label)}</text>`
    : '';
  return `<svg viewBox="0 0 ${width} ${height}" style="width:100%;max-width:${width}px" role="img" aria-label="${escapeHtml(chart.title)}">`
    + `<line x1="${num(zero)}" x2="${num(zero)}" y1="0" y2="${rows.length * ROW}" stroke="${ZERO}"/>${bars}${reference}</svg>`;
}

/** A profit bridge: totals stand on zero, each change floats from where the bridge stands, up in green, down in red. */
export function bridgeSvg(chart: SnapshotBridge, width: number): string {
  const HEIGHT = 170, TOP = 18, BOTTOM = 30;
  let level = 0;
  const bars = chart.steps.map((step) => {
    const from = step.kind === 'total' ? 0 : level;
    const to = step.kind === 'total' ? step.value : level + step.value;
    level = to;
    return { ...step, from, to };
  });
  const [low, high] = domain(bars.flatMap((bar) => [bar.from, bar.to]));
  const y = (value: number) => TOP + (1 - (value - low) / (high - low)) * (HEIGHT - TOP - BOTTOM);
  const slot = width / Math.max(1, bars.length);
  const body = bars.map((bar, index) => {
    const left = index * slot + slot * 0.18;
    const span = slot * 0.64;
    const top = Math.min(y(bar.from), y(bar.to));
    const fill = bar.kind === 'total' ? INK : bar.value < 0 ? NEGATIVE : UP;
    const link = index < bars.length - 1
      ? `<line x1="${num(left + span)}" x2="${num((index + 1) * slot + slot * 0.18)}" y1="${num(y(bar.to))}" y2="${num(y(bar.to))}" stroke="${MUTED}" stroke-dasharray="3 3"/>` : '';
    return `<rect x="${num(left)}" y="${num(top)}" width="${num(span)}" height="${num(Math.max(1, Math.abs(y(bar.to) - y(bar.from))))}" fill="${fill}"/>${link}`
      + `<text x="${num(left + span / 2)}" y="${num(top - 4)}" text-anchor="middle" font-family="${FIGURE_FONT}" font-size="10" fill="${bar.shown.negative ? NEGATIVE : INK}">${escapeHtml(bar.shown.text)}</text>`
      + `<text x="${num(left + span / 2)}" y="${HEIGHT - 12}" text-anchor="middle" font-family="${PROSE_FONT}" font-size="10" fill="${MUTED}">${escapeHtml(short(bar.label, 6))}</text>`;
  }).join('');
  return `<svg viewBox="0 0 ${width} ${HEIGHT}" style="width:100%;max-width:${width}px" role="img" aria-label="${escapeHtml(chart.title)}">`
    + `<line x1="0" x2="${width}" y1="${num(y(0))}" y2="${num(y(0))}" stroke="${ZERO}"/>${body}</svg>`;
}

export type SnapshotFonts = { sans: string; figures: { weight: number; url: string }[] };

const FONT_URL = /^data:font\/woff2;base64,[A-Za-z0-9+/=]+$/;

function faces(fonts: SnapshotFonts): string {
  if (!FONT_URL.test(fonts.sans) || !fonts.figures.every((font) => FONT_URL.test(font.url) && Number.isInteger(font.weight))) {
    throw new Error('看板快照缺少离线字体。');
  }
  return [`@font-face{font-family:"Noto Sans SC";src:url("${fonts.sans}") format("woff2");font-weight:100 900;}`,
    ...fonts.figures.flatMap((font) => [
      `@font-face{font-family:"IBM Plex Mono";src:url("${font.url}") format("woff2");font-weight:${font.weight};unicode-range:U+0020-007E,U+00A0-00FF,U+2030,U+2212;}`,
      `@font-face{font-family:"FND Figures";src:url("${font.url}") format("woff2");font-weight:${font.weight};unicode-range:U+0025,U+0030-0039;}`])].join('');
}

const STYLE = `
@page { size: A4 landscape; margin: 0; }
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; width: 297mm; height: 210mm; overflow: hidden; background: #fff; color: ${INK}; color-scheme: light;
  font-family: ${PROSE_FONT}; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
.page { width: 297mm; padding: 9mm 11mm 8mm; display: flex; flex-direction: column; gap: 3.2mm; transform-origin: 0 0; }
.head { display: flex; justify-content: space-between; align-items: flex-end; gap: 12px; border-bottom: 2px solid ${INK}; padding-bottom: 2.4mm; }
.head h1 { margin: 0; font-size: 20px; font-weight: 700; letter-spacing: 0; }
.head h1 span { font-weight: 400; color: ${MUTED}; font-size: 14px; margin-left: 10px; }
.head p { margin: 0; font-size: 10px; color: ${MUTED}; text-align: right; line-height: 15px; }
.figures { display: grid; gap: 2.4mm; }
.tile { border: 1px solid ${LINE}; border-radius: 6px; padding: 2.4mm 2.8mm; display: grid; gap: 1mm; align-content: start; break-inside: avoid; }
.tile h2, .chart h2 { margin: 0; font-size: 11px; font-weight: 600; line-height: 15px; color: ${INK}; }
.subject { margin: 0; font-size: 10px; color: ${MUTED}; line-height: 14px; }
.value { margin: 0; font-family: ${FIGURE_FONT}; font-size: 19px; font-weight: 600; line-height: 24px; font-variant-numeric: tabular-nums; white-space: nowrap; }
.value[data-negative] { color: ${NEGATIVE}; }
sup { font-family: ${PROSE_FONT}; font-size: 9px; font-weight: 400; color: ${MUTED}; margin-left: 2px; vertical-align: super; }
.level { display: inline-flex; align-items: center; gap: 4px; font-size: 10px; color: ${MUTED}; }
.level i { width: 7px; height: 7px; border-radius: 50%; display: inline-block; }
.beside { margin: 0; font-size: 10px; color: ${MUTED}; line-height: 14px; }
.beside b { font-family: ${FIGURE_FONT}; font-weight: 400; color: ${INK}; }
.note { margin: 0; font-size: 10px; color: ${MUTED}; line-height: 14px; }
.charts { display: grid; gap: 3mm; }
.chart { border: 1px solid ${LINE}; border-radius: 6px; padding: 2.4mm 2.8mm; display: grid; gap: 1.4mm; align-content: start; }
.chart svg { display: block; }
.unit { margin: 0; font-size: 10px; color: ${MUTED}; }
.foot { border-top: 1px solid ${LINE}; padding-top: 2mm; display: grid; gap: 1.2mm; font-size: 9px; line-height: 13px; color: ${MUTED}; }
.foot ol { margin: 0; padding: 0; list-style: none; columns: 2; column-gap: 8mm; }
.foot li { break-inside: avoid; margin-bottom: 0.6mm; }
.foot li b { color: ${INK}; font-weight: 600; }
.foot p { margin: 0; }
`;

/** Local time as the board writes it: 2026-10-10 18:20. */
export function stampOf(date: Date): string {
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** The page: what the board shows of its accepted cards, every figure numbered to the line that says where it came from. */
export function snapshotHtml(snapshot: DashboardSnapshot, fonts: SnapshotFonts, exportedAt: string): string {
  const e = escapeHtml;
  const columns = Math.max(4, Math.min(6, snapshot.figures.length));
  const tiles = snapshot.figures.map((figure) => `<section class="tile">
    <h2>${e(figure.title)}</h2>
    ${figure.subject || figure.part ? `<p class="subject">${e([figure.subject, figure.part].filter(Boolean).join(' · '))}</p>` : ''}
    <p class="value"${figure.value.negative ? ' data-negative=""' : ''}>${e(figure.value.text)}<sup>${figure.source}</sup></p>
    ${figure.level ? `<span class="level"><i style="background:${LEVEL_COLOURS[figure.level]}"></i>${e(figure.level_label)}</span>` : ''}
    ${figure.beside.map((pair) => `<p class="beside">${e(pair.label)} <b>${e(pair.text)}</b></p>`).join('')}
    ${figure.note ? `<p class="note">${e(figure.note)}</p>` : ''}
  </section>`).join('');
  // One or two charts take half the page each, three take a third: a chart is never drawn larger than the board draws it.
  const across = snapshot.charts.length >= 3 ? 3 : 2;
  const width = across === 2 ? 480 : 330;
  const charts = snapshot.charts.map((chart) => `<section class="chart">
    <h2>${e(chart.title)}<sup>${chart.source}</sup></h2>
    ${chart.note ? `<p class="note">${e(chart.note)}</p>` : ''}
    ${chart.kind === 'rank' ? rankSvg(chart, width) : bridgeSvg(chart, width)}
    ${chart.unit ? `<p class="unit">单位：${e(chart.unit)}</p>` : ''}
  </section>`).join('');
  const sources = snapshot.sources.map((source) => `<li><b>${source.n}</b> ${e(source.title)}${source.lines.length ? `：${e(source.lines.join('；'))}` : ''}〔${e(source.run)}〕</li>`).join('');
  const calculations = snapshot.runs.map((run) => `<li><b>${e(run.key)}</b> ${e([run.label, run.computed, `计算编号 ${run.run_id.slice(0, 8)}`].filter(Boolean).join(' · '))}${run.files.length ? `；资料：${e(run.files.join('、'))}` : ''}</li>`).join('');
  const left = [
    snapshot.left_out.pinned.length ? `待认可 ${snapshot.left_out.pinned.length} 张（${snapshot.left_out.pinned.map((card) => `「${card.title}」`).join('')}）` : '',
    snapshot.left_out.scenario.length ? `情景 ${snapshot.left_out.scenario.length} 张（情景不是实际数，不进快照）` : '',
    snapshot.beyond.length ? `这一页放不下 ${snapshot.beyond.length} 张（${snapshot.beyond.map((card) => `「${card.title}」`).join('')}，导出 Excel 可以看到全部）` : '',
  ].filter(Boolean);
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; font-src data:; img-src data:">
<title>${e(`经营看板 · ${snapshot.task}${snapshot.period ? ` · ${snapshot.period}` : ''}`)}</title>
<style>${faces(fonts)}${STYLE}.figures{grid-template-columns:repeat(${columns},minmax(0,1fr));}.charts{grid-template-columns:repeat(${across},minmax(0,1fr));}</style></head>
<body><main class="page">
<header class="head"><h1>经营看板<span>${e([snapshot.task, snapshot.period].filter(Boolean).join(' · '))}</span></h1>
<p>只放经理认可的卡 · 每个数的来源见页脚<br>${e(`导出于 ${exportedAt}${snapshot.signed_by ? ` · 导出人 ${snapshot.signed_by}` : ''} · 看板版本 ${snapshot.board_id.slice(0, 8)}`)}</p></header>
${tiles ? `<div class="figures">${tiles}</div>` : ''}
${charts ? `<div class="charts">${charts}</div>` : ''}
<footer class="foot">
<ol>${sources}</ol>
<ol>${calculations}</ol>
${left.length ? `<p>没有放进这一页：${e(left.join('；'))}。</p>` : ''}
</footer>
</main></body></html>`;
}

/** A file name for the save dialog, as the backend names the filed copy: 经营看板_示例_华宸物业8月月结_2026年8月.pdf. */
export function snapshotFileName(snapshot: DashboardSnapshot, format: SnapshotFormat): string {
  const stem = ['经营看板', snapshot.task, snapshot.period].filter(Boolean).map((word) => word.replace(/\s*·\s*/g, '_').replace(/\s+/g, ''))
    .join('_').replace(/[\\/:*?"<>|]+/g, '_');
  return `${Array.from(stem).slice(0, 120).join('')}.${format}`;
}
