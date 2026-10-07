import type { ReportDocument, ReportMark, ReportNode } from './model.js';
import { renderReportVisualSvg, reportVisualMarkdown } from './visuals.js';
import { reportVisualEvidence } from './visual-evidence.js';

const EMPTY_METADATA = { ledger: '', organization: '', company: '', period: '', currency: '', unit: '' };
const NUMERIC_TEXT = /^[(（]?-?(?:¥|￥|\$)?\s*\d[\d,]*(?:\.\d+)?%?[)）]?$/;
// A rendered table cell that reads as a number: a signed figure with well-formed thousands groups, then a unit and a
// short note in brackets, as in 「325,644.00 万元」「−3.30 个百分点」「117814.5625 万元（估算）」. Brackets must pair
// and 「1,2,3」 is text. Only the HTML table markup reads it; the editor's alignment (parseTable) and the DOCX export
// keep NUMERIC_TEXT.
const NUMERIC_CELL = /^[(（]?[-+−]?(?:¥|￥|\$)?\s*(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?[%％]?[)）]?(?:\s*(?:个百分点|百万元|万元|亿元|千元|元|平方米|㎡|天|倍|户|人|笔|万|亿|[%％]))?(?:\s*[（(][^（）()]{1,8}[)）])?$/;
// A cell that stands in for a number (a dash, 不适用, a note that a ratio is not given): it takes no part in deciding a
// column's alignment and sits where that column's numbers sit.
const NOTE_CELL = /^(?:[-—–－]+|不适用|不可比|不计算|无|暂无|无数据|暂无数据|数据缺失|缺数|未提供|未披露|待补充|n\/?a|.{0,8}不作比率)$/i;
// A bare year (2026) labels a row or column; it is not a figure to align with the numbers.
const BARE_YEAR = /^(?:19|20)\d{2}$/;
// A figure written below zero, by sign or by accounting parentheses. The author's text stays as written; the cell is
// only marked so it reads in the muted negative red (DESIGN.md 财务数字).
const NEGATIVE_FIGURE = /^(?:[-−]|[(（](?=[-−]?(?:¥|￥|\$)?\s*\d))/;
// A row named 合计/总计 is a total and 小计 a subtotal: Bold and SemiBold, the table's two weights above Regular.
const TOTAL_ROW = /^(?:合计|总计|总额|total\b)/i;
const SUBTOTAL_ROW = /^(?:小计|subtotal\b)/i;
const NOTE_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$/;
const NOTE_REF_PATTERN = /\[\^([A-Za-z0-9][A-Za-z0-9_.:-]{0,63})\]/g;

type FigureFont = { weight: number; url: string };
type RenderOptions = { fontDataUrl?: string; figureFonts?: FigureFont[]; print?: boolean; marker?: string; contentMode?: string; projectionHash?: string; draftId?: string; contentHash?: string; publicationStatus?: string; reviewStatus?: string; reproducibilityStatus?: string; sources?: string[]; visualSources?: string[] };

const blockTypes = new Set([
  'paragraph',
  'heading',
  'bulletList',
  'orderedList',
  'blockquote',
  'codeBlock',
  'horizontalRule',
  'table',
  'image',
  'reportVisual',
  'reportNote',
  'reportPageBreak',
]);

export function createReportDocument(content: ReportNode[] = []): ReportDocument {
  return { schema_version: 1, template_version: 'annual-v1', metadata: { ...EMPTY_METADATA }, content };
}

export const DOCUMENT_METADATA_LABELS = { ledger: '账套', organization: '组织', company: '企业', period: '期间', currency: '币种', unit: '单位' } as const;
export const TABLE_METADATA_LABELS = { caption: '表题', period: '期间', currency: '币种', unit: '单位' } as const;

export function documentFromMarkdown(body: string): ReportDocument {
  const lines = body.replace(/\r\n?/g, '\n').split('\n');
  const content: ReportNode[] = [];
  const metadata = { ...EMPTY_METADATA };
  let i = 0;
  const firstContentIndex = lines.findIndex((line) => line.trim());
  if (firstContentIndex >= 0) {
    const parsedMetadata = parseProjectionLine(lines[firstContentIndex], DOCUMENT_METADATA_LABELS);
    if (parsedMetadata) {
      const clean = (value?: string) => !value || value === '未声明' ? '' : value;
      metadata.ledger = clean(parsedMetadata.ledger);
      metadata.organization = clean(parsedMetadata.organization);
      metadata.company = clean(parsedMetadata.company);
      metadata.period = clean(parsedMetadata.period);
      metadata.currency = clean(parsedMetadata.currency);
      metadata.unit = clean(parsedMetadata.unit);
      i = firstContentIndex + 1;
    }
  }
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i += 1;
      continue;
    }
    const note = line.match(/^\[\^([^\]]+)\]:\s*(.*)$/);
    if (note) {
      content.push({ type: 'reportNote', attrs: { id: note[1] }, content: [{ type: 'paragraph', content: parseInline(note[2]) }] });
      i += 1;
      continue;
    }
    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      content.push({ type: 'heading', attrs: { level: heading[1].length }, content: parseInline(heading[2]) });
      i += 1;
      continue;
    }
    if (/^---+$/.test(line.trim())) {
      content.push({ type: 'horizontalRule' });
      i += 1;
      continue;
    }
    if (/^```/.test(line)) {
      const code: string[] = [];
      i += 1;
      while (i < lines.length && !/^```/.test(lines[i])) {
        code.push(lines[i]);
        i += 1;
      }
      content.push({ type: 'codeBlock', content: [{ type: 'text', text: code.join('\n') }] });
      i += i < lines.length ? 1 : 0;
      continue;
    }
    const tableProjection = parseProjectionLine(line, TABLE_METADATA_LABELS);
    if (tableProjection && isTableStart(lines, nextNonEmptyIndex(lines, i + 1))) {
      i = nextNonEmptyIndex(lines, i + 1);
      const tableLines: string[] = [];
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) {
        tableLines.push(lines[i]);
        i += 1;
      }
      content.push(parseTable(tableLines, tableProjection as Record<string, string>));
      continue;
    }
    if (isTableStart(lines, i)) {
      const tableLines: string[] = [];
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) {
        tableLines.push(lines[i]);
        i += 1;
      }
      content.push(parseTable(tableLines));
      continue;
    }
    const list = line.match(/^(\s*)([-*+]|\d+[.)])\s+(.+)$/);
    if (list) {
      const parsed = parseListBlock(lines, i, list[1].length, /\d+[.)]/.test(list[2]));
      content.push(parsed.node);
      i = parsed.next;
      continue;
    }
    const image = line.match(/^!\[([^\]]*)\]\(([^)\s]+)(?:\s+"([^"]+)")?\)$/);
    if (image) {
      content.push({ type: 'image', attrs: { alt: image[1], src: image[2], title: image[3] ?? '' } });
      i += 1;
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,6})\s+/.test(lines[i]) && !isTableStart(lines, i) && !/^\[\^([^\]]+)\]:/.test(lines[i])) {
      if (/^(\s*)([-*+]|\d+[.)])\s+/.test(lines[i]) || /^```/.test(lines[i]) || /^---+$/.test(lines[i].trim())) break;
      para.push(lines[i]);
      i += 1;
    }
    content.push({ type: 'paragraph', content: parseInline(para.join('\n')) });
  }
  const doc = createReportDocument(content);
  doc.metadata = metadata;
  return doc;
}

export function documentToMarkdown(doc: ReportDocument): string {
  const metadata = documentMetadataMarkdown(doc);
  const contentBlocks = normalizeBlocks(doc.content).map(nodeToMarkdown).filter(Boolean);
  const blocks = [metadata && contentBlocks[0]?.trim() !== metadata ? metadata : '', ...contentBlocks].filter(Boolean);
  const rendered = blocks.join('\n\n').trim();
  return rendered ? `${rendered}\n` : '';
}

export function renderReportHtml(doc: ReportDocument, title: string, options: RenderOptions = {}): string {
  const css = reportCss(options);
  const noteIds = collectNoteIds(doc.content);
  const blocks = exportBlocks(doc.content, title);
  const managementMode = isManagementMode(options);
  const receipt = renderReceipt({ ...options, visualSources: reportVisualEvidence(doc) });
  const toc = managementMode ? '' : blocks
    .filter((node) => node.type === 'heading' && Number(node.attrs?.level ?? 1) <= 2)
    .map((node, index) => {
      const level = Math.max(1, Math.min(6, Number(node.attrs?.level ?? 1)));
      const text = textContent(node);
      return `<li class="toc-level-${level}"><a href="#section-${index + 1}">${escapeHtml(text)}</a></li>`;
    })
    .join('');
  let sectionIndex = 0;
  const body = blocks.map((node) => {
    if (node.type === 'heading') {
      sectionIndex += 1;
      return nodeToHtml(node, sectionIndex, noteIds);
    }
    return nodeToHtml(node, sectionIndex, noteIds);
  }).join('\n');
  return `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; font-src data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeHtml(title)}</title>
<style>${css}</style>
</head>
<body>
<main class="report-shell${options.print ? ' is-print' : ''}"${options.contentMode ? ` data-report-content-mode="${escapeAttribute(options.contentMode)}"` : ''}${options.projectionHash ? ` data-report-projection-hash="${escapeAttribute(options.projectionHash)}"` : ''}>
<header class="report-cover">
${options.marker ? `<p class="report-review-marker">${escapeHtml(options.marker)}</p>` : ''}
<p class="report-kicker">${escapeHtml(metadataLine(doc))}</p>
<h1>${escapeHtml(title)}</h1>
${managementMode ? '' : receipt}
</header>
${toc ? `<nav class="report-toc" aria-label="目录"><h2>目录</h2><ol>${toc}</ol></nav>` : ''}
<article class="report-body">
${body}
</article>
${managementMode ? receipt : ''}
</main>
</body>
</html>`;
}


function isManagementMode(options: RenderOptions): boolean {
  return options.contentMode === 'management';
}

function renderReceipt(options: RenderOptions): string {
  const rows = [
    ['文稿标记', options.marker],
    ['草稿版本', options.draftId],
    ['导出模式', options.contentMode],
    ['投影 SHA-256', options.projectionHash],
    ['内容 SHA-256', options.contentHash],
    ['发布状态', options.publicationStatus],
    ['复核状态', options.reviewStatus],
    ['可复现状态', options.reproducibilityStatus],
  ].filter((row): row is [string, string] => Boolean(row[1]));
  const sources = (options.sources ?? []).filter(Boolean).slice(0, 12);
  const visuals = options.visualSources ?? [];
  if (!rows.length && !sources.length && !visuals.length) return '';
  const items = rows.map(([label, value]) => `<li><strong>${escapeHtml(label)}：</strong>${escapeHtml(value)}</li>`).join('');
  const sourceItems = sources.length ? `<li><strong>授权来源：</strong><ul>${sources.map((source) => `<li>${escapeHtml(source)}</li>`).join('')}</ul></li>` : '';
  const visualItems = visuals.length ? `<li><strong>图表依据：</strong><ul>${visuals.map((source) => `<li>${escapeHtml(source)}</li>`).join('')}</ul></li>` : '';
  return `<section class="report-receipt" aria-label="导出身份"><ul>${items}${sourceItems}${visualItems}</ul></section>`;
}

function exportBlocks(content: ReportNode[], title: string): ReportNode[] {
  const blocks = normalizeBlocks(content);
  const first = blocks[0];
  if (first?.type === 'heading' && Number(first.attrs?.level ?? 1) === 1 && normalizeTitle(textContent(first)) === normalizeTitle(title)) {
    return blocks.slice(1);
  }
  return blocks;
}

function normalizeTitle(value: string): string {
  return value.replace(/\s+/g, '').toLocaleLowerCase();
}

function documentMetadataMarkdown(doc: ReportDocument): string {
  const metadata = { ...EMPTY_METADATA, ...(doc.metadata ?? {}) };
  const hasAny = Object.values(metadata).some((value) => Boolean(attrText(value, 300)));
  if (!hasAny && !doc.template_id) return '';
  const declared = new Set(['ledger', 'organization', 'period', 'currency', 'unit']);
  return Object.entries(DOCUMENT_METADATA_LABELS)
    .map(([key, label]) => {
      const value = attrText(metadata[key as keyof typeof metadata], 300);
      if (value) return `${label}：${value}`;
      if (declared.has(key)) return `${label}：未声明`;
      return '';
    })
    .filter(Boolean)
    .join('；');
}

function tableMetadataMarkdown(tableOrAttrs: ReportNode | ReportNode['attrs']): string {
  const attrs = (tableOrAttrs && 'type' in tableOrAttrs ? tableOrAttrs.attrs : tableOrAttrs) ?? {};
  const values: Record<string, unknown> = { ...attrs };
  return projectionLine(values, TABLE_METADATA_LABELS);
}

function projectionLine(values: Record<string, unknown>, labels: Record<string, string>): string {
  const parts = Object.entries(labels)
    .map(([key, label]) => [label, attrText(values[key], 300)] as const)
    .filter(([, value]) => value)
    .map(([label, value]) => `${label}：${value}`);
  return parts.join('；');
}


export function parseProjectionLine<T extends Record<string, string>>(line: string, labels: T): Partial<Record<keyof T, string>> | undefined {
  const reverse = new Map(Object.entries(labels).map(([key, label]) => [label, key as keyof T]));
  const parsed: Partial<Record<keyof T, string>> = {};
  const text = line.trim();
  if (!text) return undefined;
  for (const part of text.split('；')) {
    const index = part.indexOf('：');
    if (index <= 0) return undefined;
    const label = part.slice(0, index).trim();
    const key = reverse.get(label);
    if (!key) return undefined;
    parsed[key] = part.slice(index + 1).trim();
  }
  return Object.keys(parsed).length > 0 ? parsed : undefined;
}

function nextNonEmptyIndex(lines: string[], index: number): number {
  let next = index;
  while (next < lines.length && !lines[next].trim()) next += 1;
  return next;
}

function parseInline(text: string): ReportNode[] {
  const out: ReportNode[] = [];
  let rest = text;
  const pattern = /(!?\[([^\]]*)\]\(([^)\s]+)(?:\s+"([^"]+)")?\)|\*\*([^*]+)\*\*|`([^`]+)`)/;
  while (rest) {
    const match = rest.match(pattern);
    if (!match || match.index === undefined) {
      out.push(textNode(unescapeMarkdown(rest)));
      break;
    }
    if (match.index > 0) out.push(textNode(unescapeMarkdown(rest.slice(0, match.index))));
    if (match[1]?.startsWith('![')) {
      out.push({ type: 'image', attrs: { alt: match[2], src: match[3], title: match[4] ?? '' } });
    } else if (match[3]) {
      out.push({ type: 'text', text: match[2], marks: safeHref(match[3]) ? [{ type: 'link', attrs: { href: match[3] } }] : undefined });
    } else if (match[5]) {
      out.push({ type: 'text', text: match[5], marks: [{ type: 'bold' }] });
    } else if (match[6]) {
      out.push({ type: 'text', text: match[6], marks: [{ type: 'code' }] });
    }
    rest = rest.slice(match.index + match[0].length);
  }
  return mergeTextNodes(out);
}

function textNode(text: string): ReportNode {
  return { type: 'text', text };
}

function mergeTextNodes(nodes: ReportNode[]): ReportNode[] {
  const merged: ReportNode[] = [];
  for (const node of nodes) {
    const last = merged[merged.length - 1];
    if (node.type === 'text' && last?.type === 'text' && sameMarks(last.marks, node.marks)) {
      last.text = `${last.text ?? ''}${node.text ?? ''}`;
    } else {
      merged.push(node);
    }
  }
  return merged;
}

function sameMarks(a?: ReportMark[], b?: ReportMark[]): boolean {
  return JSON.stringify(a ?? []) === JSON.stringify(b ?? []);
}

export function isTableStart(lines: string[], index: number): boolean {
  return /^\s*\|.*\|\s*$/.test(lines[index] ?? '') && /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(lines[index + 1] ?? '');
}

function parseTable(lines: string[], attrs: Record<string, string> = {}): ReportNode {
  const rows = lines.filter((_, index) => index !== 1).map((line, rowIndex) => {
    const cells = splitRow(line).map((cell) => ({
      type: rowIndex === 0 ? 'tableHeader' : 'tableCell',
      attrs: { textAlign: NUMERIC_TEXT.test(cell.trim()) ? 'right' : 'left' },
      content: [{ type: 'paragraph', content: parseInline(cell.trim()) }],
    }));
    return { type: 'tableRow', content: cells };
  });
  return { type: 'table', attrs, content: rows };
}

function splitRow(line: string): string[] {
  const trimmed = line.trim().replace(/^\|/, '').replace(/\|$/, '');
  const cells: string[] = [];
  let current = '';
  let escaped = false;
  for (const char of trimmed) {
    if (escaped) {
      current += char;
      escaped = false;
    } else if (char === '\\') {
      escaped = true;
    } else if (char === '|') {
      cells.push(current.trim());
      current = '';
    } else {
      current += char;
    }
  }
  cells.push(current.trim());
  return cells;
}

function nodeToMarkdown(node: ReportNode): string {
  switch (node.type) {
    case 'heading':
      return `${'#'.repeat(Math.max(1, Math.min(6, Number(node.attrs?.level ?? 1))))} ${inlineToMarkdown(node.content ?? [])}`;
    case 'paragraph':
      return inlineToMarkdown(node.content ?? []);
    case 'blockquote':
      return inlineToMarkdown(node.content ?? []).split('\n').map((line) => `> ${line}`).join('\n');
    case 'codeBlock':
      return `\`\`\`\n${textContent(node)}\n\`\`\``;
    case 'horizontalRule':
      return '---';
    case 'bulletList':
    case 'orderedList':
      return (node.content ?? []).map((item, index) => `${node.type === 'orderedList' ? `${index + 1}.` : '-'} ${itemText(item)}`).join('\n');
    case 'table':
      return tableToMarkdown(node);
    case 'image':
      return imageToMarkdown(node);
    case 'reportVisual':
      return reportVisualMarkdown(node.attrs?.visual);
    case 'reportNote':
      return `[^${String(node.attrs?.id ?? '')}]: ${inlineToMarkdown(flatInline(node.content ?? []))}`;
    case 'reportPageBreak':
      return '<div class="report-page-break"></div>';
    default:
      return inlineToMarkdown(node.content ?? []);
  }
}

function itemText(item: ReportNode): string {
  return (item.content ?? []).map((child) => {
    const rendered = child.type === 'paragraph' ? inlineToMarkdown(child.content ?? []) : nodeToMarkdown(child).trimEnd();
    return child.type === 'paragraph' ? rendered : rendered.split('\n').map((line) => `  ${line}`).join('\n');
  }).join('\n');
}

function tableToMarkdown(table: ReportNode): string {
  const rows = (table.content ?? []).filter((row) => row.type === 'tableRow').map(expandRowCells);
  if (rows.length === 0) return '';
  const columns = Math.max(1, ...(rows.map((row) => row.length)));
  const body = rows.map((row) => {
    const padded = [...row, ...Array.from({ length: columns - row.length }, () => ({ type: 'tableCell', content: [{ type: 'paragraph', content: [{ type: 'text', text: '' }] }] } as ReportNode))];
    return `| ${padded.map((cell) => tableCellMarkdown(inlineToMarkdown(flatInline(cell.content ?? [])))).join(' | ')} |`;
  });
  body.splice(1, 0, `| ${Array.from({ length: columns }, () => '---').join(' | ')} |`);
  return [tableMetadataMarkdown(table), body.join('\n')].filter(Boolean).join('\n\n');
}

function imageToMarkdown(node: ReportNode): string {
  const attrs = node.attrs ?? {};
  const title = attrs.title ? ` "${String(attrs.title)}"` : '';
  return `![${String(attrs.alt ?? '')}](${String(attrs.src ?? '')}${title})`;
}

function inlineToMarkdown(nodes: ReportNode[]): string {
  return nodes.map((node) => {
    if (node.type === 'text') {
      let text = escapeMarkdownText(node.text ?? '');
      for (const mark of node.marks ?? []) {
        if (mark.type === 'bold') text = `**${text}**`;
        if (mark.type === 'code') text = `\`${text}\``;
        if (mark.type === 'link' && safeHref(String(mark.attrs?.href ?? ''))) text = `[${text}](${String(mark.attrs?.href)})`;
      }
      return text;
    }
    if (node.type === 'hardBreak') return '\n';
    if (node.type === 'image') return imageToMarkdown(node);
    return inlineToMarkdown(node.content ?? []);
  }).join('');
}

function flatInline(nodes: ReportNode[]): ReportNode[] {
  return nodes.flatMap((node) => node.type === 'paragraph' ? (node.content ?? []) : [node]);
}

function nodeToHtml(node: ReportNode, sectionIndex: number, noteIds: Set<string> = new Set()): string {
  const attrs = sourceAttrs(node);
  switch (node.type) {
    case 'heading': {
      const level = Math.max(1, Math.min(6, Number(node.attrs?.level ?? 1)));
      return `<h${level} id="section-${sectionIndex}"${attrs}>${inlineToHtml(node.content ?? [], noteIds)}</h${level}>`;
    }
    case 'paragraph':
      return `<p${attrs}>${inlineToHtml(node.content ?? [], noteIds)}</p>`;
    case 'blockquote':
      return `<blockquote${attrs}>${inlineToHtml(flatInline(node.content ?? []), noteIds)}</blockquote>`;
    case 'codeBlock':
      return `<pre${attrs}><code>${escapeHtml(textContent(node))}</code></pre>`;
    case 'horizontalRule':
      return '<hr>';
    case 'bulletList':
    case 'orderedList': {
      const tag = node.type === 'orderedList' ? 'ol' : 'ul';
      return `<${tag}${attrs}>${(node.content ?? []).map((item) => `<li>${(item.content ?? []).map((child) => nodeToHtml(child, sectionIndex, noteIds)).join('')}</li>`).join('')}</${tag}>`;
    }
    case 'table':
      return tableToHtml(node, attrs, noteIds);
    case 'image':
      return imageToHtml(node, attrs);
    case 'reportVisual': {
      const fallback = documentFromMarkdown(reportVisualMarkdown(node.attrs?.visual));
      const data = fallback.content.map((child) => nodeToHtml(child, sectionIndex, noteIds)).join('');
      return `<figure class="report-visual"${attrs}>${renderReportVisualSvg(node.attrs?.visual)}<details class="report-visual-data"><summary>查看图表数据与说明</summary>${data}</details></figure>`;
    }
    case 'reportNote':
      return reportNoteToHtml(node, attrs, sectionIndex, noteIds);
    case 'reportPageBreak':
      return '<div class="report-page-break" aria-hidden="true"></div>';
    default:
      return inlineToHtml(node.content ?? [], noteIds);
  }
}

function inlineToHtml(nodes: ReportNode[], noteIds: Set<string> = new Set()): string {
  return nodes.map((node) => {
    if (node.type === 'text') {
      let html = textToHtml(node, noteIds);
      for (const mark of node.marks ?? []) {
        if (mark.type === 'bold') html = `<strong>${html}</strong>`;
        if (mark.type === 'italic') html = `<em>${html}</em>`;
        if (mark.type === 'strike') html = `<s>${html}</s>`;
        if (mark.type === 'underline') html = `<u>${html}</u>`;
        if (mark.type === 'code') html = `<code>${html}</code>`;
        if (mark.type === 'link' && safeHref(String(mark.attrs?.href ?? ''))) {
          html = `<a href="${escapeAttribute(String(mark.attrs?.href))}" rel="noreferrer noopener">${html}</a>`;
        }
      }
      return html;
    }
    if (node.type === 'hardBreak') return '<br>';
    if (node.type === 'image') return imageToHtml(node, '');
    return inlineToHtml(node.content ?? [], noteIds);
  }).join('');
}

function reportNoteToHtml(node: ReportNode, attrs: string, sectionIndex: number, noteIds: Set<string>): string {
  const id = safeNoteId(node.attrs?.id);
  const noteAttrs = `${attrs}${id ? ` id="note-${escapeAttribute(id)}" data-note-id="${escapeAttribute(id)}"` : ''}`;
  const label = id || attrText(node.attrs?.id, 64);
  return `<aside class="report-note"${noteAttrs}><sup>${escapeHtml(label)}</sup>${(node.content ?? []).map((child) => nodeToHtml(child, sectionIndex, noteIds)).join('')}</aside>`;
}

function textToHtml(node: ReportNode, noteIds: Set<string>): string {
  const text = node.text ?? '';
  const marks = node.marks ?? [];
  if (marks.some((mark) => mark.type === 'code' || mark.type === 'link')) return escapeHtml(text);
  return escapeHtmlWithNoteRefs(text, noteIds);
}

function escapeHtmlWithNoteRefs(text: string, noteIds: Set<string>): string {
  let rendered = '';
  let lastIndex = 0;
  NOTE_REF_PATTERN.lastIndex = 0;
  for (const match of text.matchAll(NOTE_REF_PATTERN)) {
    const index = match.index ?? 0;
    const id = safeNoteId(match[1]);
    if (!id || !noteIds.has(id)) continue;
    rendered += escapeHtml(text.slice(lastIndex, index));
    const safeId = escapeAttribute(id);
    rendered += `<sup class="report-note-ref" data-report-note-ref="${safeId}"><a href="#note-${safeId}" aria-label="查看附注 ${safeId}">[${escapeHtml(id)}]</a></sup>`;
    lastIndex = index + match[0].length;
  }
  rendered += escapeHtml(text.slice(lastIndex));
  return rendered;
}

function collectNoteIds(nodes: ReportNode[] = []): Set<string> {
  const ids = new Set<string>();
  const visit = (node: ReportNode) => {
    if (node.type === 'reportNote') {
      const id = safeNoteId(node.attrs?.id);
      if (id) ids.add(id);
      return;
    }
    for (const child of node.content ?? []) visit(child);
  };
  for (const node of nodes) visit(node);
  return ids;
}

function safeNoteId(value: unknown): string {
  const text = attrText(value, 64).trim();
  return NOTE_ID_PATTERN.test(text) ? text : '';
}

function tableToHtml(table: ReportNode, attrs: string, noteIds: Set<string>): string {
  const rows = (table.content ?? []).filter((row) => row.type === 'tableRow');
  const rowGroups = splitWideRows(rows);
  if (rowGroups.length > 1) {
    return `<div class="wide-table-group"${attrs}>${rowGroups.map((group, index) => tableRowsToHtml(table, group, index > 0, noteIds)).join('')}</div>`;
  }
  return tableRowsToHtml(table, rows, false, noteIds, attrs);
}

function tableRowsToHtml(table: ReportNode, rows: ReportNode[], continuation: boolean, noteIds: Set<string>, attrs = ''): string {
  const captionText = attrText(table.attrs?.caption, 300);
  const caption = captionText ? `<caption>${escapeHtml(captionText)}</caption>` : '';
  const unit = [table.attrs?.period, table.attrs?.currency, table.attrs?.unit].map((value) => attrText(value, 120)).filter(Boolean).join(' / ');
  const numericColumns = numericTableColumns(rows);
  const columns = cellColumns(rows);
  const renderedRows = rows.map((row, rowIndex) => {
    const cells = (row.content ?? []).map((cell, cellIndex) => {
      const tag = cell.type === 'tableHeader' || rowIndex === 0 ? 'th' : 'td';
      const span = cellSpan(cell);
      const column = columns[rowIndex][cellIndex];
      // The first column names its rows (even when they are years) and is never set as a number. Elsewhere a body
      // cell is judged by what it says; a header, a dash or a short note also follows a column of numbers.
      const first = column === 0;
      const inNumericColumn = span === 1 && numericColumns.has(column);
      const note = !first && rowIndex > 0 && inNumericColumn && !isNumericCell(cell) && NOTE_CELL.test(textContent(cell).trim());
      const numeric = !first && (isNumericCell(cell) || (rowIndex === 0 && inNumericColumn));
      const negative = numeric && tag === 'td' && NEGATIVE_FIGURE.test(textContent(cell).trim());
      const colspan = numberAttr('colspan', cell.attrs?.colspan);
      const rowspan = numberAttr('rowspan', cell.attrs?.rowspan);
      return `<${tag} class="${note ? 'num note' : negative ? 'num neg' : numeric ? 'num' : 'text'}"${first ? ' data-first-column=""' : ''}${colspan}${rowspan}>${(cell.content ?? []).map((child) => nodeToHtml(child, 0, noteIds)).join('')}</${tag}>`;
    }).join('');
    return `<tr${rowIndex > 0 ? rowWeightClass(row) : ''}>${cells}</tr>`;
  });
  const head = renderedRows.length > 0 ? `<thead>${renderedRows[0]}</thead>` : '';
  const body = renderedRows.length > 1 ? `<tbody>${renderedRows.slice(1).join('')}</tbody>` : '<tbody></tbody>';
  const marker = continuation ? '<p class="table-meta">续表</p>' : '';
  // Named by the table; the in-app reading view makes a figure that scrolls a focusable region (ReportReading).
  const label = `${captionText || '财务表格'}${continuation ? '（续表）' : ''}`;
  return `<figure class="financial-table" aria-label="${escapeAttribute(label)}"${attrs}>${marker}${unit ? `<p class="table-meta">${escapeHtml(unit)}</p>` : ''}<table>${caption}${head}${body}</table></figure>`;
}

function cellSpan(cell: ReportNode): number {
  return Math.max(1, Math.min(20, Number(cell.attrs?.colspan ?? 1) || 1));
}

/** Each cell's starting column, counting the columns that row spans from earlier rows still hold. */
function cellColumns(rows: ReportNode[]): number[][] {
  const held: number[] = [];
  return rows.map((row) => {
    let column = 0;
    const starts = (row.content ?? []).map((cell) => {
      while ((held[column] ?? 0) > 0) column += 1;
      const start = column;
      const span = cellSpan(cell);
      const rowspan = Math.max(1, Math.min(200, Number(cell.attrs?.rowspan ?? 1) || 1));
      for (let index = 0; index < span; index += 1) held[start + index] = rowspan;
      column += span;
      return start;
    });
    for (let index = 0; index < held.length; index += 1) if (held[index] > 0) held[index] -= 1;
    return starts;
  });
}

function rowWeightClass(row: ReportNode): string {
  const name = textContent(row.content?.[0] ?? { type: 'text' }).trim();
  if (TOTAL_ROW.test(name)) return ' class="row-total"';
  if (SUBTOTAL_ROW.test(name)) return ' class="row-subtotal"';
  return '';
}

export function isNumericCell(cell: ReportNode): boolean {
  const text = textContent(cell).trim();
  if (BARE_YEAR.test(text)) return false;
  const number = NUMERIC_CELL.test(text) && (text.match(/[(（]/g) ?? []).length === (text.match(/[)）]/g) ?? []).length;
  // parseTable right-aligns whatever NUMERIC_TEXT accepts, so that alignment says nothing NUMERIC_CELL does not.
  if (number || NUMERIC_TEXT.test(text)) return number;
  return cell.attrs?.textAlign === 'right';
}

/**
 * Columns whose body cells are more often numbers than words. A header cell over one of them is set as a number,
 * so 「1 至 8 月实际」 sits over its figures; a table with row spans keeps its headers as written.
 */
function numericTableColumns(rows: ReportNode[]): Set<number> {
  const columns = new Set<number>();
  if (rows.some((row) => (row.content ?? []).some((cell) => Number(cell.attrs?.rowspan ?? 1) > 1))) return columns;
  const counts = new Map<number, { numbers: number; words: number }>();
  for (const row of rows.slice(1)) {
    expandRowCells(row).forEach((cell, index) => {
      const text = textContent(cell).trim();
      if (index === 0) return;
      if (!text || (NOTE_CELL.test(text) && !isNumericCell(cell))) return;
      const count = counts.get(index) ?? { numbers: 0, words: 0 };
      if (isNumericCell(cell)) count.numbers += 1;
      else count.words += 1;
      counts.set(index, count);
    });
  }
  for (const [index, count] of counts) if (count.numbers > count.words) columns.add(index);
  return columns;
}

function splitWideRows(rows: ReportNode[]): ReportNode[][] {
  const expanded = rows.map(expandRowCells);
  const maxColumns = Math.max(0, ...expanded.map((row) => row.length));
  if (maxColumns <= 6) return [rows];
  const groups: ReportNode[][] = [];
  for (let start = 1; start < maxColumns; start += 5) {
    groups.push(rows.map((row, rowIndex) => ({ ...row, content: [expanded[rowIndex][0], ...expanded[rowIndex].slice(start, start + 5)].filter(Boolean) as ReportNode[] })));
  }
  return groups;
}

function expandRowCells(row: ReportNode): ReportNode[] {
  const cells: ReportNode[] = [];
  for (const cell of row.content ?? []) {
    const span = cellSpan(cell);
    const attrs = { ...(cell.attrs ?? {}) };
    delete attrs.colspan;
    delete attrs.rowspan;
    cells.push({ ...cell, attrs });
    for (let index = 1; index < span; index += 1) {
      cells.push({ type: cell.type, attrs: { textAlign: attrs.textAlign ?? 'left' }, content: [{ type: 'paragraph', content: [{ type: 'text', text: '' }] }] });
    }
  }
  return cells;
}

function parseListBlock(lines: string[], start: number, indent: number, ordered: boolean): { node: ReportNode; next: number } {
  const items: ReportNode[] = [];
  let i = start;
  while (i < lines.length) {
    const current = lines[i].match(/^(\s*)([-*+]|\d+[.)])\s+(.+)$/);
    if (!current) break;
    const currentIndent = current[1].length;
    const currentOrdered = /\d+[.)]/.test(current[2]);
    if (currentIndent !== indent || currentOrdered !== ordered) break;
    const itemContent: ReportNode[] = [{ type: 'paragraph', content: parseInline(current[3]) }];
    i += 1;
    while (i < lines.length) {
      const next = lines[i].match(/^(\s*)([-*+]|\d+[.)])\s+(.+)$/);
      if (!next || next[1].length <= indent) break;
      const nested = parseListBlock(lines, i, next[1].length, /\d+[.)]/.test(next[2]));
      itemContent.push(nested.node);
      i = nested.next;
    }
    items.push({ type: 'listItem', content: itemContent });
  }
  return { node: { type: ordered ? 'orderedList' : 'bulletList', content: items }, next: i };
}

function tableCellMarkdown(value: string): string {
  return value.replace(/\n/g, '<br>').replace(/\|/g, '\\|');
}

function escapeMarkdownText(value: string): string {
  let escaped = '';
  let lastIndex = 0;
  NOTE_REF_PATTERN.lastIndex = 0;
  for (const match of value.matchAll(NOTE_REF_PATTERN)) {
    const index = match.index ?? 0;
    escaped += value.slice(lastIndex, index).replace(/([\\`*[\]()])/g, '\\$1');
    escaped += match[0];
    lastIndex = index + match[0].length;
  }
  escaped += value.slice(lastIndex).replace(/([\\`*[\]()])/g, '\\$1');
  return escaped;
}

function unescapeMarkdown(value: string): string {
  return value.replace(/\\([\\`*[\]()|])/g, '$1');
}

function imageToHtml(node: ReportNode, attrs: string): string {
  const src = String(node.attrs?.src ?? '');
  if (!safeImageSrc(src)) return '';
  const title = attrText(node.attrs?.title, 300);
  return `<figure class="report-image"${attrs}><img src="${escapeAttribute(src)}" alt="${escapeAttribute(attrText(node.attrs?.alt, 300))}">${title ? `<figcaption>${escapeHtml(title)}</figcaption>` : ''}</figure>`;
}

function numberAttr(name: 'colspan' | 'rowspan', value: unknown): string {
  const n = Number(value);
  return Number.isFinite(n) && n > 1 ? ` ${name}="${n}"` : '';
}

function sourceAttrs(node: ReportNode): string {
  const attrs = node.attrs ?? {};
  return ['source_id', 'page', 'sheet', 'range'].map((key) => {
    const value = attrText(attrs[key], 300);
    return value ? ` data-${key.replace('_', '-')}="${escapeAttribute(value)}"` : '';
  }).join('');
}

function attrText(value: unknown, maximum: number): string {
  return typeof value === 'string' || typeof value === 'number' ? String(value).slice(0, maximum) : '';
}

function normalizeBlocks(nodes: ReportNode[]): ReportNode[] {
  return nodes.filter((node) => blockTypes.has(node.type) || node.type === 'paragraph');
}

export function textContent(node: ReportNode): string {
  if (node.type === 'text') return node.text ?? '';
  return (node.content ?? []).map(textContent).join('');
}

function metadataLine(doc: ReportDocument): string {
  return [doc.metadata.company, doc.metadata.period, doc.metadata.currency, doc.metadata.unit].filter(Boolean).join(' / ') || '经营分析报告';
}

export function safeHref(href: string): boolean {
  return /^(https?:|mailto:|#|\.\/|\/(?!\/))/.test(href);
}

export function safeImageSrc(src: string): boolean {
  return /^data:image\/(?:png|jpeg|jpg);base64,[a-z0-9+/=\s]+$/i.test(src);
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]!));
}

function escapeAttribute(value: string): string {
  return escapeHtml(value).replace(/\n/g, '&#10;');
}

const FIGURE_LATIN = 'U+0020-007E,U+00A0-00FF,U+2030,U+2212';
const FIGURE_DIGITS = 'U+0025,U+0030-0039';

/**
 * The same IBM Plex Mono faces the app uses (styles/fonts.css), registered twice: whole figure cells take every Latin
 * character from it; prose takes only digits and %, so numbers inside sentences read in Plex Mono (DESIGN.md 财务数字).
 */
function figureFontFaces(fonts: FigureFont[]): string {
  return fonts.filter((font) => /^data:font\/woff2;base64,[A-Za-z0-9+/=]+$/.test(font.url) && Number.isInteger(font.weight))
    .flatMap((font) => [['IBM Plex Mono', FIGURE_LATIN], ['FND Figures', FIGURE_DIGITS]].map(([family, range]) =>
      `@font-face{font-family:"${family}";src:url("${font.url}") format("woff2");font-weight:${font.weight};font-style:normal;font-display:block;unicode-range:${range};}`))
    .join('');
}

function reportCss(options: RenderOptions): string {
  const fontFace = (options.fontDataUrl ? `@font-face{font-family:"Noto Sans SC";src:url("${options.fontDataUrl}") format("woff2");font-weight:100 900;font-display:block;}` : '')
    + figureFontFaces(options.figureFonts ?? []);
  return `${fontFace}
:root{color-scheme:light dark;--report-bg:#f7f7f5;--report-paper:#fff;--report-ink:#1b1b18;--report-muted:#696760;--report-line:#d9d4c7;--report-accent:#b78a38;--report-negative:#94463d;--report-font:"Noto Sans SC","PingFang SC","Microsoft YaHei",sans-serif;--report-prose:"FND Figures",var(--report-font);--report-figure:"IBM Plex Mono",var(--report-font)}
@media (prefers-color-scheme:dark){:root{--report-bg:#111;--report-paper:#181817;--report-ink:#efeee8;--report-muted:#a8a49b;--report-line:#36332e;--report-accent:#d1a85a;--report-negative:#d9a097}}
@page{size:A4;margin:20mm}
*{box-sizing:border-box}
body{margin:0;background:var(--report-bg);color:var(--report-ink);font-family:var(--report-prose);font-size:16px;line-height:28px;letter-spacing:0}
.report-shell{max-width:calc(42em + 48px);margin:0 auto;padding:32px 24px 56px}
.report-cover,.report-toc,.report-body{max-width:42em;margin:0 auto}
.report-cover{padding:12px 0 28px;border-bottom:1px solid var(--report-line)}
.report-review-marker{display:inline-block;margin:0 0 12px;padding:2px 8px;border:1px solid #b78a38;border-radius:4px;background:#fff6d8;color:#7a4d00;font-size:13px;line-height:22px}
.report-receipt{margin:16px 0 0;padding:10px 12px;border:1px solid var(--report-line);border-radius:6px;background:var(--report-paper);color:var(--report-muted);font-size:12px;line-height:20px;overflow-wrap:anywhere}
.report-receipt ul{margin:0;padding-left:18px}.report-receipt li+li{margin-top:2px}.report-receipt strong{color:var(--report-ink)}
.report-kicker,.table-meta,figcaption{margin:0;color:var(--report-muted);font-size:13px;line-height:22px}
h1{margin:8px 0 0;font-size:28px;line-height:40px;font-weight:750;letter-spacing:0}
h2{margin:32px 0 12px;font-size:22px;line-height:32px;font-weight:720;break-after:avoid}
h3{margin:28px 0 10px;font-size:18px;line-height:28px;font-weight:700;break-after:avoid}
h4,h5,h6{margin:24px 0 8px;font-size:16px;line-height:26px;font-weight:700;break-after:avoid}
p,ul,ol,blockquote,pre,figure,.report-note{margin:0 0 18px}
.report-toc{padding:24px 0 8px}
.report-toc h2{margin:0 0 10px;font-size:16px;line-height:24px}
.report-toc ol{margin:0;padding:0;list-style:none}
.report-toc li{margin:0 0 4px;line-height:24px}
.report-toc .toc-level-2{padding-left:16px}.report-toc .toc-level-3{padding-left:32px}
a{color:inherit;text-decoration-color:var(--report-accent);text-underline-offset:3px}
blockquote{padding-left:16px;border-left:2px solid var(--report-accent);color:var(--report-muted)}
pre{padding:12px 14px;background:color-mix(in srgb,var(--report-paper),var(--report-line) 20%);border:1px solid var(--report-line);overflow:auto}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.92em}
.financial-table{break-inside:auto;margin:22px 0 26px}
table{width:100%;border-collapse:collapse;table-layout:auto;font-size:14px;line-height:22px}
caption{text-align:left;font-weight:700;margin-bottom:8px;break-after:avoid}
tr{break-inside:avoid}
th,td{padding:8px 10px;border:0;border-bottom:1px solid var(--report-line);vertical-align:top}
th{font-weight:700;text-align:left;border-top:1px solid var(--report-line);background:color-mix(in srgb,var(--report-paper),var(--report-line) 12%)}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
td.num{font-family:var(--report-figure)}td.num.note{font-family:var(--report-prose)}td.neg{color:var(--report-negative)}
tr.row-subtotal td{font-weight:600}tr.row-total td{font-weight:700;border-top:1.5px solid var(--report-ink)}
.report-image img{max-width:100%;height:auto;display:block}
.report-image,.report-visual{break-inside:avoid;page-break-inside:avoid}
.report-visual>svg{display:block;width:100%;height:auto;background:#fff;border:1px solid var(--report-line);border-radius:6px}
.report-visual-data{margin-top:8px;font-size:13px;line-height:22px;overflow-wrap:anywhere}.report-visual-data summary{cursor:pointer;color:var(--report-muted)}
@media print{.report-visual-data{display:none}.report-visual>svg{max-height:230mm}}
.report-note{padding-top:10px;border-top:1px solid var(--report-line);color:var(--report-muted);font-size:14px;line-height:24px}
.report-note-ref{font-size:.75em;line-height:0;vertical-align:super;margin:0 1px}.report-note-ref a{text-decoration:none;color:var(--report-accent)}
.report-page-break{break-after:page;height:0}
.report-shell.is-print{width:210mm;min-height:297mm;max-width:none;margin:24px auto;padding:20mm;background:#fff;color:#111;box-shadow:0 20px 60px rgba(0,0,0,.16)}
.report-shell.is-print .report-cover,.report-shell.is-print .report-toc,.report-shell.is-print .report-body{max-width:none}
.report-shell.is-print{--report-negative:#94463d}
.report-shell.is-print table{font-size:9pt;line-height:1.4}
.report-shell.is-print th,.report-shell.is-print td{padding:5pt 6pt}
.report-shell.is-print .report-note{font-size:9pt;line-height:1.45}
@media print{:root{--report-negative:#94463d}body{background:#fff;color:#111;font-size:11pt;line-height:1.65}.report-shell{max-width:none;padding:0}.report-cover,.report-toc,.report-body{max-width:none}.report-cover{break-after:avoid}.report-toc{break-after:page}table{font-size:9pt;line-height:1.4}thead{display:table-header-group}tfoot{display:table-footer-group}th,td{padding:5pt 6pt}.report-note{font-size:9pt;line-height:1.45}.report-shell.is-print{width:auto;min-height:0;max-width:none;margin:0;padding:0;background:#fff;box-shadow:none}}`;
}
