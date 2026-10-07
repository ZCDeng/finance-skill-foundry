/**
 * Static report figures shared by the editor and offline exports.
 * Layout principles: diagram-design (Cathryn Lavery, MIT) and huashu-report
 * (alchaincyf, MIT). See docs/plans/2026-09-28-report-visuals.md for provenance.
 * This renderer never accepts SVG, HTML, URLs, or executable chart options.
 */
export type ReportVisualJson = null | string | number | boolean | ReportVisualJson[] | { [key: string]: ReportVisualJson };
export interface ReportVisualColumn { name: string; type?: string; [key: string]: ReportVisualJson | undefined }
interface VisualBase { version: 1; title: string; takeaway: string }
export interface ReportDataVisual extends VisualBase {
  kind: 'bar' | 'line';
  chart_id: string;
  category: string;
  value_columns: string[];
  unit: string;
  series: { columns: ReportVisualColumn[]; rows: Record<string, ReportVisualJson>[] };
  run_id: string;
  snapshot_hash: string;
  source_label: string;
  estimate_notice?: '本图含估算值，经理确认前不作为批复预算。';
}
export interface ReportFlowVisual extends VisualBase {
  kind: 'flow';
  steps: { label: string; detail: string; connector: string }[];
  source_label: string;
}
export type ReportVisual = ReportDataVisual | ReportFlowVisual;

const PAPER = '#ffffff';
const INK = '#252525';
const MUTED = '#626262';
const RULE = '#dedbd4';
const COLORS = ['#8a6729', '#426786', '#626262'];
// The muted negative red of DESIGN.md 财务数字 (--fnd-negative, light): a value below zero, never a series colour.
const NEGATIVE = '#94463d';
// Standalone figures (axis ticks, value labels, row numbers) are set whole in IBM Plex Mono; the chart's own text takes
// only digits and % from it ('FND Figures'), as result sentences do. Both families are the app's and the export's.
const FIGURE_FONT = "'IBM Plex Mono', 'Noto Sans SC', 'PingFang SC', sans-serif";
const PROSE_FONT = "'FND Figures', 'Noto Sans SC', 'PingFang SC', sans-serif";
const WIDTH = 960;
const PAD = 40;
const CONTENT = WIDTH - PAD * 2;
const DECIMAL = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/;
const CONTROL = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/;

function object(raw: unknown, label: string): Record<string, unknown> {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw) || ![Object.prototype, null].includes(Object.getPrototypeOf(raw))) {
    throw new Error(`${label}必须是对象`);
  }
  return raw as Record<string, unknown>;
}

function textField(raw: unknown, label: string, max: number, required = false): string {
  if (raw === undefined && !required) return '';
  if (typeof raw !== 'string' || CONTROL.test(raw)) throw new Error(`${label}必须是有效文本`);
  if ((required && !raw.trim()) || Array.from(raw).length > max) throw new Error(`${label}${required ? '不能为空，且' : ''}最多 ${max} 字`);
  return raw;
}

function finiteJson(raw: unknown, depth = 0, budget = { left: 524288 }): ReportVisualJson {
  if (depth > 12 || --budget.left < 0) throw new Error('图表快照过大或嵌套过深');
  if (raw === null || typeof raw === 'boolean') return raw;
  if (typeof raw === 'number' && Number.isFinite(raw)) return raw;
  if (typeof raw === 'string' && !CONTROL.test(raw)) {
    budget.left -= raw.length;
    if (raw.length > 16384 || budget.left < 0) throw new Error('图表快照文本过长');
    return raw;
  }
  if (Array.isArray(raw)) return raw.map((item) => finiteJson(item, depth + 1, budget));
  if (raw && typeof raw === 'object') {
    const source = object(raw, '图表快照');
    return Object.fromEntries(Object.entries(source).map(([key, value]) => {
      if (key.length > 1000 || CONTROL.test(key) || ['__proto__', 'prototype', 'constructor'].includes(key)) throw new Error('图表快照含不允许的字段');
      budget.left -= key.length;
      return [key, finiteJson(value, depth + 1, budget)];
    }));
  }
  throw new Error('图表快照只能包含有限 JSON 数据');
}

function numberValue(raw: unknown, label: string): number | null {
  if (raw === null) return null;
  const value = raw;
  if (!((typeof value === 'string' && DECIMAL.test(value)) || typeof value === 'number')) throw new Error(`${label}必须是十进制数或 null（缺失）`);
  const number = Number(value);
  const coefficient = String(value).split(/[eE]/)[0];
  if (!Number.isFinite(number) || (number === 0 && /[1-9]/.test(coefficient))) throw new Error(`${label}超出可绘制的有限数值范围`);
  return number;
}

function categoryValue(raw: unknown): string {
  if (typeof raw !== 'string' && !(typeof raw === 'number' && Number.isFinite(raw))) throw new Error('类别必须是非空文本或有限数值');
  const value = String(raw);
  if (!value.trim()) throw new Error('类别不能为空');
  return value;
}

/** Validation is structural; authoritative snapshot binding remains server-owned. */
export function normalizeReportVisual(raw: unknown): ReportVisual {
  const source = object(raw, '文稿图表');
  if (source.version !== 1) throw new Error('不支持的文稿图表版本');
  const common: VisualBase = {
    version: 1,
    title: textField(source.title, '图题', 160, true),
    takeaway: textField(source.takeaway, '图表结论', 300),
  };
  if (source.kind === 'flow') {
    if (!Array.isArray(source.steps) || source.steps.length < 2 || source.steps.length > 6) throw new Error('解释流程必须包含 2–6 个步骤');
    const steps = source.steps.map((item, index) => {
      const step = object(item, `步骤 ${index + 1}`);
      return {
        label: textField(step.label, '步骤名称', 60, true),
        detail: textField(step.detail, '步骤说明', 140),
        connector: textField(step.connector, '步骤关系', 40),
      };
    });
    if (steps[steps.length - 1].connector) throw new Error('最后一个步骤不能有后续关系');
    const flow: ReportFlowVisual = { ...common, kind: 'flow', steps, source_label: textField(source.source_label, '来源', 200) || '作者分析' };
    assertVisualDensity(flow);
    return flow;
  }
  if (source.kind !== 'bar' && source.kind !== 'line') throw new Error('图型仅支持比较条形图、趋势折线图和解释流程图');
  const category = textField(source.category, '类别列', 200, true);
  if (!Array.isArray(source.value_columns) || source.value_columns.length < 1 || source.value_columns.length > 3) throw new Error('请选择 1–3 个数值列');
  const value_columns = source.value_columns.map((column) => textField(column, '数值列', 200, true));
  if (new Set(value_columns).size !== value_columns.length || value_columns.includes(category)) throw new Error('类别列与数值列不能重复');
  const data = object(source.series, '冻结数据');
  const limit = source.kind === 'bar' ? 12 : 24;
  if (!Array.isArray(data.rows) || !data.rows.length || data.rows.length > limit) throw new Error(`${source.kind === 'bar' ? '条形图' : '折线图'}需有 1–${limit} 行，请先汇总或拆分数据`);
  if (source.kind === 'bar' && data.rows.length * value_columns.length > 12) throw new Error('条形图最多展示 12 个数据位置，请拆分图表');
  if (!Array.isArray(data.columns) || !data.columns.length || data.columns.length > 256) throw new Error('冻结数据需要 1–256 个字段定义');
  const budget = { left: 524288 };
  const columns = data.columns.map((rawColumn) => {
    const column = object(rawColumn, '字段定义');
    const copied = finiteJson(column, 2, budget) as Record<string, ReportVisualJson>;
    const name = textField(column.name, '字段名称', 200, true);
    if (column.type !== undefined && typeof column.type !== 'string') throw new Error('字段类型必须为文本');
    return { ...copied, name } as ReportVisualColumn;
  });
  const names = columns.map((column) => column.name);
  if (new Set(names).size !== names.length) throw new Error('冻结数据包含重复字段');
  if (![category, ...value_columns].every((name) => names.includes(name))) throw new Error('所选字段不在冻结数据中');
  const rows = data.rows.map((row) => finiteJson(object(row, '数据行'), 2, budget) as Record<string, ReportVisualJson>);
  const encoded = JSON.stringify({ columns, rows });
  // UTF-8 byte count without a DOM/Node dependency (the module runs in both).
  let bytes = 0;
  for (const char of encoded) { const cp = char.codePointAt(0)!; bytes += cp < 0x80 ? 1 : cp < 0x800 ? 2 : cp < 0x10000 ? 3 : 4; }
  if (bytes > 524288) throw new Error('图表快照超过 512 KiB');
  const categories = rows.map((row) => categoryValue(row[category]).trim());
  if (new Set(categories).size !== categories.length) throw new Error('类别必须唯一，请先汇总或换用其他类别列');
  for (const column of value_columns) {
    const values = rows.map((row) => numberValue(row[column], `数值列“${column}”`));
    if (values.every((value) => value === null)) throw new Error(`数值列“${column}”全部缺失，无法绘图`);
  }
  const snapshot_hash = textField(source.snapshot_hash, '快照标识', 64, true);
  if (!/^[a-f0-9]{64}$/i.test(snapshot_hash)) throw new Error('快照标识必须是有效的 SHA-256');
  const chart_id = textField(source.chart_id, '归档图标识', 32, true);
  const run_id = textField(source.run_id, '计算标识', 32, true);
  if (!/^[a-f0-9]{32}$/.test(chart_id)) throw new Error('归档图标识必须是 32 位小写十六进制');
  if (!/^[a-f0-9]{32}$/.test(run_id)) throw new Error('计算标识必须是 32 位小写十六进制');
  const estimateNotice = '本图含估算值，经理确认前不作为批复预算。' as const;
  if (source.estimate_notice !== undefined && source.estimate_notice !== estimateNotice) throw new Error('估算提示必须使用标准文案');
  const visual: ReportDataVisual = {
    ...common, kind: source.kind, category, value_columns, series: { columns, rows }, snapshot_hash,
    chart_id, run_id,
    unit: textField(source.unit, '单位', 40, true),
    source_label: textField(source.source_label, '来源', 200, true),
    ...(source.estimate_notice ? { estimate_notice: estimateNotice } : {}),
  };
  assertVisualDensity(visual);
  return visual;
}

function escapeXml(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&apos;');
}

/** Expand exponents with string arithmetic; never round Decimal labels via Number. */
function exactValue(value: ReportVisualJson | undefined): string {
  if (value === null || value === undefined) return '缺失';
  const raw = String(value).trim();
  const match = /^([+-]?)(\d*\.?\d*)[eE]([+-]?\d+)$/.exec(raw);
  if (!match) return raw;
  const [, sign, coefficient, exponent] = match;
  const digits = coefficient.replace('.', '');
  if (!/[1-9]/.test(digits)) return `${sign === '-' ? '-' : ''}0`;
  const point = (coefficient.includes('.') ? coefficient.indexOf('.') : coefficient.length) + Number(exponent);
  const expanded = point <= 0 ? `0.${'0'.repeat(-point)}${digits}` : point >= digits.length ? `${digits}${'0'.repeat(point - digits.length)}` : `${digits.slice(0, point)}.${digits.slice(point)}`;
  return sign + expanded;
}

/** An exact value as a label: every digit kept, thousands grouped (−1234567.5 → -1,234,567.5). */
function exactFigure(value: ReportVisualJson | undefined): string {
  const exact = exactValue(value);
  return /^[+-]?\d+(?:\.\d+)?$/.test(exact) ? groupThousands(exact) : exact;
}

function glyphWidth(char: string, size: number): number {
  return size * (/\s/u.test(char) ? 0.34 : /[\u0000-\u00ff]/u.test(char) ? 0.62 : 1.02);
}

function wrap(value: string, width: number, size: number): string[] {
  const lines: string[] = [];
  for (const paragraph of value.split(/\r?\n/)) {
    let line = ''; let used = 0;
    for (const char of Array.from(paragraph)) {
      const charWidth = glyphWidth(char, size);
      if (used + charWidth > width && line) { lines.push(line); line = ''; used = 0; }
      line += char; used += charWidth;
    }
    lines.push(line);
  }
  return lines;
}

/** Keep this arithmetic aligned with foundry.report_visuals.visual_height. */
function visualHeight(visual: ReportVisual): number {
  const n = (text: string, width: number, size: number) => wrap(text, width, size).length;
  const kind = visual.kind === 'flow' ? '作者解释流程' : `${visual.kind === 'bar' ? '类别比较' : '趋势变化'} · 单位：${visual.unit}`;
  let y = 50 + n(visual.title, 880, 24) * 36 + n(kind, 880, 14) * 21 + 12;
  if (visual.takeaway) y += n(`作者结论：${visual.takeaway}`, 880, 17) * 25.5 + 24;
  if (visual.kind !== 'flow' && visual.estimate_notice) y += n(visual.estimate_notice, 880, 15) * 22.5 + 24;
  y += 24;
  if (visual.kind === 'flow') {
    y += 8;
    visual.steps.forEach((step, index) => {
      y += 32 + n(step.label, 684, 19) * 28.5 + (step.detail ? 12 + n(step.detail, 684, 16) * 24 : 0);
      if (index < visual.steps.length - 1) y += Math.max(56, n(step.connector || '下一步', 648, 14) * 21 + 24);
    });
    y += 24;
  } else if (visual.kind === 'bar') {
    y += Math.max(36, n(visual.category, 220, 14) * 21 + 12);
    visual.series.rows.forEach((row, index) => {
      const grouped = visual.value_columns.length > 1;
      const header = n(categoryValue(row[visual.category]), 220, 18) * 27 + (grouped ? 8 : 0);
      if (grouped) y += header;
      visual.value_columns.forEach((column) => {
        y += Math.max(44, n(exactFigure(row[column]), 216, 18) * 27 + 12, grouped ? n(column, 220, 16) * 24 + 12 : 12, grouped ? 0 : header + 12);
      });
      y += index === visual.series.rows.length - 1 ? 20 : 28;
    });
  } else {
    const chartTop = y + 24; const chartBottom = chartTop + 288;
    let labelY = chartTop + 12;
    visual.value_columns.forEach((column) => { labelY += Math.max(76, n(`${column} · 末项 ${exactFigure(visual.series.rows[visual.series.rows.length - 1][column])}`, 232, 18) * 27 + 24); });
    y = Math.max(chartBottom + 68, labelY + 12) + 32;
    for (let start = 0; start < visual.series.rows.length; start += 4) {
      y += Math.max(...visual.series.rows.slice(start, start + 4).map((row, offset) => n(`${start + offset + 1}. ${categoryValue(row[visual.category])}`, 204, 16) * 24 + 16));
    }
    y += 8;
  }
  const source = visual.kind === 'flow' ? `来源：${visual.source_label} · 作者解释，不构成计算证据` : `来源：${visual.source_label}`;
  y += 20 + n(source, 880, 16) * 24;
  if (visual.kind !== 'flow') {
    y += n('数值保持原精度；几何位置为近似比例。单位按声明展示，不自动换算。', 880, 14) * 21 + 4;
    if (visual.series.rows.some((row) => visual.value_columns.some((column) => row[column] === null))) y += n('缺失值显示为“缺失”，不补零。', 880, 14) * 21 + 4;
  }
  return Math.ceil((y + 28) / 4) * 4;
}

function assertVisualDensity(visual: ReportVisual): void {
  if (visualHeight(visual) > 1200) throw new Error('图表内容过密，请拆分图表或缩短图题、类别与步骤说明（最大高度 1200 像素）');
}

function label(lines: string[], x: number, y: number, size = 16, color = INK, weight = 400, anchor = 'start', figure = false): string {
  return `<text x="${x}" y="${y}"${figure ? ` font-family="${FIGURE_FONT}"` : ''} font-size="${size}" fill="${color}" font-weight="${weight}" text-anchor="${anchor}">${lines.map((line, index) => `<tspan x="${x}" dy="${index ? size * 1.5 : 0}">${escapeXml(line)}</tspan>`).join('')}</text>`;
}

function point(value: number): string { return String(Math.round(value * 100) / 100); }

function line(x1: number, y1: number, x2: number, y2: number, color = RULE, width = 1): string {
  return `<line x1="${point(x1)}" y1="${point(y1)}" x2="${point(x2)}" y2="${point(y2)}" stroke="${color}" stroke-width="${width}"/>`;
}

function rect(x: number, y: number, width: number, height: number, fill: string, stroke = 'none'): string {
  return `<rect x="${point(x)}" y="${point(y)}" width="${point(width)}" height="${point(height)}" fill="${fill}" stroke="${stroke}"/>`;
}

function caption(visual: ReportVisual): string {
  const parts = [visual.title];
  if (visual.takeaway) parts.push(`作者结论：${visual.takeaway}`);
  if (visual.kind === 'flow') parts.push(`作者解释流程 · 来源：${visual.source_label}`);
  else {
    if (visual.estimate_notice) parts.push(visual.estimate_notice);
    parts.push(`单位：${visual.unit}（按声明展示，不自动换算）`, `来源：${visual.source_label}`);
  }
  return parts.join('\n');
}

export function reportVisualCaption(raw: unknown): string { return caption(normalizeReportVisual(raw)); }

function scaleFor(visual: ReportDataVisual): { position: (value: number) => number; zero: number; magnitude: number; normalizedAt: (ratio: number) => number } {
  const values = visual.series.rows.flatMap((row) => visual.value_columns.map((column) => numberValue(row[column], column)).filter((value): value is number => value !== null));
  const magnitude = Math.max(...values.map(Math.abs)) || 1;
  // Normalize before subtracting: opposite finite extremes must not overflow.
  const low = Math.min(0, ...values.map((value) => value / magnitude));
  const observedHigh = Math.max(0, ...values.map((value) => value / magnitude));
  const high = observedHigh === low ? low + 1 : observedHigh;
  const span = high - low;
  return { position: (value) => (value / magnitude - low) / span, zero: -low / span, magnitude,
    normalizedAt: (ratio) => ratio === 0 ? low : ratio === 1 ? high : low * (1 - ratio) + high * ratio };
}

/** Axis ticks are approximate scale guides; the attached data retain exact values. */
function axisTick(normalized: number, magnitude: number, scientific: boolean): string {
  if (normalized === 0) return '0';
  // Work on mantissa/exponent separately: even a tick below Number.MIN_VALUE
  // must not be labelled zero, and finite opposite extremes must not overflow.
  const [mantissa, power] = magnitude.toExponential(15).split('e');
  const product = normalized * Number(mantissa);
  const shift = Math.floor(Math.log10(Math.abs(product)));
  let coefficient = product / 10 ** shift;
  let exponent = Number(power) + shift;
  coefficient = Number(coefficient.toPrecision(3));
  if (Math.abs(coefficient) >= 10) { coefficient /= 10; exponent += 1; }
  // Money in 元 runs to hundreds of millions: write it the way a finance table does (418,000,000),
  // up to 15 characters, which is what fits left of the plot. Only beyond that, or for tiny values, use e-notation.
  if (scientific || exponent < -3) return `${coefficient}e${exponent}`;
  return groupThousands(Number(`${coefficient}e${exponent}`).toString());
}

/** 1234567.5 → 1,234,567.5; the digits themselves are left untouched. */
function groupThousands(value: string): string {
  const [whole, fraction] = value.split('.');
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return fraction === undefined ? grouped : `${grouped}.${fraction}`;
}

function renderBars(visual: ReportDataVisual, top: number): { svg: string; bottom: number } {
  const categoryWidth = 220; const chartLeft = 290; const chartRight = 680; const valueX = 704; const valueWidth = 216;
  const scale = scaleFor(visual); const zeroX = chartLeft + scale.zero * (chartRight - chartLeft);
  const categoryHeader = wrap(visual.category, categoryWidth, 14);
  const headerHeight = Math.max(36, categoryHeader.length * 21 + 12);
  const shapes: string[] = []; let y = top + headerHeight;
  shapes.push(label(categoryHeader, PAD, top + 14, 14, MUTED), label(['精确值'], valueX, top + 14, 14, MUTED));
  shapes.push(label(['0'], zeroX, top + 14, 14, MUTED, 400, 'middle', true));
  visual.series.rows.forEach((row, rowIndex) => {
    const categoryLines = wrap(categoryValue(row[visual.category]), categoryWidth, 18);
    const rowTop = y;
    const entries = visual.value_columns.map((column, index) => {
      const valueLines = wrap(exactFigure(row[column]), valueWidth, 18);
      const seriesLines = visual.value_columns.length > 1 ? wrap(column, categoryWidth, 16) : [];
      const height = Math.max(44, valueLines.length * 27 + 12, seriesLines.length * 24 + 12);
      return { column, index, valueLines, seriesLines, height };
    });
    const headerHeight = categoryLines.length * 27 + (entries.length > 1 ? 8 : 0);
    if (entries.length > 1) { shapes.push(label(categoryLines, PAD, y + 20, 18, INK, 600)); y += headerHeight; }
    entries.forEach(({ column, index, valueLines, seriesLines, height }) => {
      const value = numberValue(row[column], column); const middle = y + height / 2;
      if (entries.length === 1) shapes.push(label(categoryLines, PAD, y + 20, 18, INK, 500));
      else shapes.push(label(seriesLines, PAD + 12, y + 20, 16, COLORS[index]));
      if (value !== null) {
        const endpoint = chartLeft + scale.position(value) * (chartRight - chartLeft);
        if (value === 0) shapes.push(line(zeroX, middle - 9, zeroX, middle + 9, COLORS[index], 3));
        else shapes.push(rect(Math.min(zeroX, endpoint), middle - 9, Math.abs(endpoint - zeroX), 18, COLORS[index]));
      }
      shapes.push(label(valueLines, valueX, y + 20, 18, value === null ? MUTED : value < 0 ? NEGATIVE : COLORS[index], 500, 'start', value !== null));
      y += Math.max(height, entries.length === 1 ? headerHeight + 12 : 0);
    });
    shapes.push(line(PAD, y + 8, WIDTH - PAD, y + 8));
    y += rowIndex === visual.series.rows.length - 1 ? 20 : 28;
    if (y <= rowTop) throw new Error('图表布局无效');
  });
  const grid = [0, 0.25, 0.5, 0.75, 1].map((tick) => line(chartLeft + tick * (chartRight - chartLeft), top + headerHeight - 12, chartLeft + tick * (chartRight - chartLeft), y - 12, '#efeeea')).join('');
  return { svg: grid + line(zeroX, top + headerHeight - 12, zeroX, y - 12, '#aaa49a', 1.5) + shapes.join(''), bottom: y };
}

function renderLines(visual: ReportDataVisual, top: number): { svg: string; bottom: number } {
  const chartLeft = 144; const chartRight = 656; const chartTop = top + 24; const chartHeight = 288; const chartBottom = chartTop + chartHeight;
  const scale = scaleFor(visual); const rows = visual.series.rows;
  const x = (index: number) => rows.length === 1 ? (chartLeft + chartRight) / 2 : chartLeft + index * (chartRight - chartLeft) / (rows.length - 1);
  const y = (value: number) => chartBottom - scale.position(value) * chartHeight;
  const ticks = [0, 1 / 3, 2 / 3, 1].filter((tick) => Math.abs(tick - scale.zero) * chartHeight >= 24);
  // One style per axis: past 1e11 the grouped figure no longer fits, so every tick switches together.
  const scientific = scale.magnitude >= 9.995e10; // what rounds to 1.00e11 at three digits
  ticks.push(scale.zero); ticks.sort((a, b) => a - b);
  const shapes = ticks.flatMap((tick) => {
    const tickY = chartBottom - tick * chartHeight;
    const text = tick === scale.zero ? '0' : axisTick(scale.normalizedAt(tick), scale.magnitude, scientific);
    return [line(chartLeft, tickY, chartRight, tickY, '#efeeea'), `<g data-report-axis-tick="true">${label([text], chartLeft - 12, tickY + 5, 14, MUTED, 400, 'end', true)}</g>`];
  });
  shapes.push(line(chartLeft, y(0), chartRight, y(0), '#aaa49a', 1.5));
  let labelY = chartTop + 12;
  visual.value_columns.forEach((column, seriesIndex) => {
    let segment: string[] = []; let last: { x: number; y: number } | null = null;
    const flush = () => { if (segment.length > 1) shapes.push(`<polyline points="${segment.join(' ')}" fill="none" stroke="${COLORS[seriesIndex]}" stroke-width="2.5"${seriesIndex === 1 ? ' stroke-dasharray="7 4"' : seriesIndex === 2 ? ' stroke-dasharray="2 4"' : ''}/>`); segment = []; };
    rows.forEach((row, rowIndex) => {
      const value = numberValue(row[column], column);
      if (value === null) { flush(); return; }
      const px = x(rowIndex); const py = y(value); segment.push(`${point(px)},${point(py)}`); last = { x: px, y: py };
      shapes.push(`<circle cx="${point(px)}" cy="${point(py)}" r="3.5" fill="${seriesIndex === 1 ? PAPER : COLORS[seriesIndex]}" stroke="${COLORS[seriesIndex]}" stroke-width="1.5"/>`);
    });
    flush();
    const value = rows[rows.length - 1][column];
    const lastLabel = wrap(`${column} · 末项 ${exactFigure(value)}`, 232, 18);
    if (last && value !== null) {
      const endpoint = last as { x: number; y: number };
      shapes.push(`<path d="M ${point(endpoint.x)} ${point(endpoint.y)} H 672 V ${point(labelY - 5)} H 680" fill="none" stroke="${COLORS[seriesIndex]}" stroke-width="1"/>`);
    }
    // The series name keeps its colour; a negative last value itself reads in the muted negative red.
    const lastValue = numberValue(value, column);
    const figure = escapeXml(exactFigure(value));
    let lastText = label(lastLabel, 688, labelY, 18, COLORS[seriesIndex], 600);
    if (lastValue !== null && lastValue < 0) {
      const at = lastText.lastIndexOf(`${figure}</tspan>`);
      if (at >= 0) lastText = `${lastText.slice(0, at)}<tspan fill="${NEGATIVE}" font-family="${FIGURE_FONT}">${figure}</tspan>${lastText.slice(at + figure.length)}`;
    }
    shapes.push(lastText);
    labelY += Math.max(76, lastLabel.length * 27 + 24);
  });
  rows.forEach((_row, index) => shapes.push(label([String(index + 1)], x(index), chartBottom + 28, 16, MUTED, 400, 'middle', true)));
  const dataTop = Math.max(chartBottom + 68, labelY + 12);
  shapes.push(label(['按原始行序排列 · 序号对应下方类别 · 缺失值保留断线'], PAD, dataTop, 16, MUTED));
  let categoryY = dataTop + 32;
  for (let start = 0; start < rows.length; start += 4) {
    const group = rows.slice(start, start + 4).map((row, offset) => wrap(`${start + offset + 1}. ${categoryValue(row[visual.category])}`, 204, 16));
    group.forEach((lines, index) => shapes.push(label(lines, PAD + index * 220, categoryY, 16, INK)));
    categoryY += Math.max(...group.map((lines) => lines.length * 24 + 16));
  }
  return { svg: shapes.join(''), bottom: categoryY + 8 };
}

function renderFlow(visual: ReportFlowVisual, top: number): { svg: string; bottom: number } {
  const shapes: string[] = []; const left = 104; const boxWidth = 748; let y = top + 8;
  visual.steps.forEach((step, index) => {
    const title = wrap(step.label, boxWidth - 64, 19); const detail = step.detail ? wrap(step.detail, boxWidth - 64, 16) : [];
    const height = 32 + title.length * 28.5 + (detail.length ? 12 + detail.length * 24 : 0);
    shapes.push(rect(left, y, boxWidth, height, index === 0 ? '#faf7f0' : PAPER, index === 0 ? COLORS[0] : RULE));
    shapes.push(label([String(index + 1).padStart(2, '0')], 64, y + 37, 17, index === 0 ? COLORS[0] : MUTED, 600, 'middle'));
    shapes.push(label(title, left + 24, y + 32, 19, INK, 600));
    if (detail.length) shapes.push(label(detail, left + 24, y + 32 + title.length * 28.5 + 8, 16, MUTED));
    y += height;
    if (index < visual.steps.length - 1) {
      const relationship = wrap(step.connector || '下一步', 648, 14);
      const gap = Math.max(56, relationship.length * 21 + 24);
      shapes.push(line(128, y, 128, y + gap - 8, MUTED, 1.5));
      shapes.push(`<path d="M 122 ${point(y + gap - 14)} L 128 ${point(y + gap - 8)} L 134 ${point(y + gap - 14)}" fill="none" stroke="${MUTED}" stroke-width="1.5"/>`);
      shapes.push(label(relationship, 152, y + 28, 14, MUTED)); y += gap;
    }
  });
  return { svg: shapes.join(''), bottom: y + 24 };
}

export function renderReportVisualSvg(raw: unknown): string {
  const visual = normalizeReportVisual(raw);
  const title = wrap(visual.title, CONTENT, 24);
  const shapes = [label(title, PAD, 50, 24, INK, 600)];
  let y = 50 + title.length * 36;
  const kind = visual.kind === 'flow' ? '作者解释流程' : `${visual.kind === 'bar' ? '类别比较' : '趋势变化'} · 单位：${visual.unit}`;
  const kindLines = wrap(kind, CONTENT, 14); shapes.push(label(kindLines, PAD, y, 14, MUTED)); y += kindLines.length * 21 + 12;
  if (visual.takeaway) {
    const takeaway = wrap(`作者结论：${visual.takeaway}`, CONTENT, 17);
    shapes.push(label(takeaway, PAD, y + 12, 17)); y += takeaway.length * 25.5 + 24;
  }
  if (visual.kind !== 'flow' && visual.estimate_notice) {
    const notice = wrap(visual.estimate_notice, CONTENT, 15);
    shapes.push(label(notice, PAD, y + 8, 15, '#8a6729', 600)); y += notice.length * 22.5 + 24;
  }
  shapes.push(line(PAD, y, WIDTH - PAD, y)); y += 24;
  const chart = visual.kind === 'flow' ? renderFlow(visual, y) : visual.kind === 'bar' ? renderBars(visual, y) : renderLines(visual, y);
  shapes.push(chart.svg); y = chart.bottom + 20;
  const source = visual.kind === 'flow' ? `来源：${visual.source_label} · 作者解释，不构成计算证据` : `来源：${visual.source_label}`;
  const sourceLines = wrap(source, CONTENT, 16); shapes.push(label(sourceLines, PAD, y, 16, MUTED)); y += sourceLines.length * 24;
  if (visual.kind !== 'flow') {
    const notes = ['数值保持原精度；几何位置为近似比例。单位按声明展示，不自动换算。'];
    if (visual.series.rows.some((row) => visual.value_columns.some((column) => row[column] === null))) notes.push('缺失值显示为“缺失”，不补零。');
    notes.forEach((note) => { const lines = wrap(note, CONTENT, 14); shapes.push(label(lines, PAD, y + 4, 14, MUTED)); y += lines.length * 21 + 4; });
  }
  const height = Math.ceil((y + 28) / 4) * 4;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${WIDTH}" height="${height}" viewBox="0 0 ${WIDTH} ${height}" role="img" aria-label="${escapeXml(visual.title)}"><title>${escapeXml(visual.title)}</title><desc>${escapeXml(caption(visual))}</desc>${rect(0, 0, WIDTH, height, PAPER)}<g font-family="${PROSE_FONT}" font-variant-numeric="tabular-nums">${shapes.join('')}</g></svg>`;
}

function escapeHtml(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function escapeMarkdown(value: string): string {
  // Keep note references in step text consistent with report_documents.py.
  return escapeHtml(value).split(/(\[\^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\])/g).map((part) => /^\[\^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\]$/.test(part) ? part : part.replace(/[\\`*\[\]()]/g, '\\$&')).join('');
}

function tableCellMarkdown(value: string): string {
  return escapeMarkdown(value).replace(/\n/g, '<br>').replace(/\|/g, '\\|');
}

export function reportVisualMarkdown(raw: unknown): string {
  const visual = normalizeReportVisual(raw);
  const output = [`### ${escapeMarkdown(visual.title)}`];
  if (visual.takeaway) output.push('', escapeMarkdown(visual.takeaway));
  if (visual.kind === 'flow') {
    output.push('', '解释流程（作者分析，不是计算证据）');
    visual.steps.forEach((step, index) => {
      output.push('', `${index + 1}. ${escapeMarkdown(step.label)}${step.detail ? `：${escapeMarkdown(step.detail)}` : ''}`);
      if (step.connector) output.push(`   → ${escapeMarkdown(step.connector)}`);
    });
  } else {
    if (visual.estimate_notice) output.push('', visual.estimate_notice);
    output.push('', `单位：${escapeMarkdown(visual.unit)}`);
    const header = [visual.category, ...visual.value_columns];
    output.push('', `| ${header.map(tableCellMarkdown).join(' | ')} |`, `| ${header.map(() => '---').join(' | ')} |`);
    visual.series.rows.forEach((row) => output.push(`| ${header.map((column) => tableCellMarkdown(row[column] === null ? '缺失' : String(row[column]))).join(' | ')} |`));
  }
  output.push('', `来源：${escapeMarkdown(visual.source_label)}`);
  return output.join('\n');
}
