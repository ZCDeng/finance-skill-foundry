import type { ReportDocument, ReportMark, ReportNode } from './model.js';

const EMPTY_METADATA = { company: '', period: '', currency: '', unit: '' };
const NUMERIC_TEXT = /^[(（]?-?(?:¥|￥|\$)?\s*\d[\d,]*(?:\.\d+)?%?[)）]?$/;

type RenderOptions = { fontDataUrl?: string; print?: boolean };

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
  'reportNote',
  'reportPageBreak',
]);

export function createReportDocument(content: ReportNode[] = []): ReportDocument {
  return { schema_version: 1, template_version: 'annual-v1', metadata: { ...EMPTY_METADATA }, content };
}

const DOCUMENT_METADATA_LABELS = { company: '企业', period: '期间', currency: '币种', unit: '单位' } as const;
const TABLE_METADATA_LABELS = { caption: '表题', period: '期间', currency: '币种', unit: '单位' } as const;

export function documentFromMarkdown(body: string): ReportDocument {
  const lines = body.replace(/\r\n?/g, '\n').split('\n');
  const content: ReportNode[] = [];
  const metadata = { ...EMPTY_METADATA };
  let i = 0;
  const firstContentIndex = lines.findIndex((line) => line.trim());
  if (firstContentIndex >= 0) {
    const parsedMetadata = parseProjectionLine(lines[firstContentIndex], DOCUMENT_METADATA_LABELS);
    if (parsedMetadata) {
      metadata.company = parsedMetadata.company ?? '';
      metadata.period = parsedMetadata.period ?? '';
      metadata.currency = parsedMetadata.currency ?? '';
      metadata.unit = parsedMetadata.unit ?? '';
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
  const toc = normalizeBlocks(doc.content)
    .filter((node) => node.type === 'heading' && Number(node.attrs?.level ?? 1) <= 2)
    .map((node, index) => {
      const level = Math.max(1, Math.min(6, Number(node.attrs?.level ?? 1)));
      const text = textContent(node);
      return `<li class="toc-level-${level}"><a href="#section-${index + 1}">${escapeHtml(text)}</a></li>`;
    })
    .join('');
  let sectionIndex = 0;
  const body = normalizeBlocks(doc.content).map((node) => {
    if (node.type === 'heading') {
      sectionIndex += 1;
      return nodeToHtml(node, sectionIndex);
    }
    return nodeToHtml(node, sectionIndex);
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
<main class="report-shell${options.print ? ' is-print' : ''}">
<header class="report-cover">
<p class="report-kicker">${escapeHtml(metadataLine(doc))}</p>
<h1>${escapeHtml(title)}</h1>
</header>
${toc ? `<nav class="report-toc" aria-label="目录"><h2>目录</h2><ol>${toc}</ol></nav>` : ''}
<article class="report-body">
${body}
</article>
</main>
</body>
</html>`;
}

function documentMetadataMarkdown(doc: ReportDocument): string {
  return projectionLine(doc.metadata ?? EMPTY_METADATA, DOCUMENT_METADATA_LABELS);
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


function parseProjectionLine<T extends Record<string, string>>(line: string, labels: T): Partial<Record<keyof T, string>> | undefined {
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

function isTableStart(lines: string[], index: number): boolean {
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

function nodeToHtml(node: ReportNode, sectionIndex: number): string {
  const attrs = sourceAttrs(node);
  switch (node.type) {
    case 'heading': {
      const level = Math.max(1, Math.min(6, Number(node.attrs?.level ?? 1)));
      return `<h${level} id="section-${sectionIndex}"${attrs}>${inlineToHtml(node.content ?? [])}</h${level}>`;
    }
    case 'paragraph':
      return `<p${attrs}>${inlineToHtml(node.content ?? [])}</p>`;
    case 'blockquote':
      return `<blockquote${attrs}>${inlineToHtml(flatInline(node.content ?? []))}</blockquote>`;
    case 'codeBlock':
      return `<pre${attrs}><code>${escapeHtml(textContent(node))}</code></pre>`;
    case 'horizontalRule':
      return '<hr>';
    case 'bulletList':
    case 'orderedList': {
      const tag = node.type === 'orderedList' ? 'ol' : 'ul';
      return `<${tag}${attrs}>${(node.content ?? []).map((item) => `<li>${(item.content ?? []).map((child) => nodeToHtml(child, sectionIndex)).join('')}</li>`).join('')}</${tag}>`;
    }
    case 'table':
      return tableToHtml(node, attrs);
    case 'image':
      return imageToHtml(node, attrs);
    case 'reportNote':
      return `<aside class="report-note"${attrs}><sup>${escapeHtml(String(node.attrs?.id ?? ''))}</sup>${(node.content ?? []).map((child) => nodeToHtml(child, sectionIndex)).join('')}</aside>`;
    case 'reportPageBreak':
      return '<div class="report-page-break" aria-hidden="true"></div>';
    default:
      return inlineToHtml(node.content ?? []);
  }
}

function inlineToHtml(nodes: ReportNode[]): string {
  return nodes.map((node) => {
    if (node.type === 'text') {
      let html = escapeHtml(node.text ?? '');
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
    return inlineToHtml(node.content ?? []);
  }).join('');
}

function tableToHtml(table: ReportNode, attrs: string): string {
  const rows = (table.content ?? []).filter((row) => row.type === 'tableRow');
  const rowGroups = splitWideRows(rows);
  if (rowGroups.length > 1) {
    return `<div class="wide-table-group"${attrs}>${rowGroups.map((group, index) => tableRowsToHtml(table, group, index > 0)).join('')}</div>`;
  }
  return tableRowsToHtml(table, rows, false, attrs);
}

function tableRowsToHtml(table: ReportNode, rows: ReportNode[], continuation: boolean, attrs = ''): string {
  const captionText = attrText(table.attrs?.caption, 300);
  const caption = captionText ? `<caption>${escapeHtml(captionText)}</caption>` : '';
  const unit = [table.attrs?.period, table.attrs?.currency, table.attrs?.unit].map((value) => attrText(value, 120)).filter(Boolean).join(' / ');
  const renderedRows = rows.map((row, rowIndex) => {
    const cells = (row.content ?? []).map((cell) => {
      const tag = cell.type === 'tableHeader' || rowIndex === 0 ? 'th' : 'td';
      const textAlign = cell.attrs?.textAlign === 'right' || NUMERIC_TEXT.test(textContent(cell).trim()) ? 'right' : 'left';
      const colspan = numberAttr('colspan', cell.attrs?.colspan);
      const rowspan = numberAttr('rowspan', cell.attrs?.rowspan);
      return `<${tag} class="${textAlign === 'right' ? 'num' : 'text'}"${colspan}${rowspan}>${(cell.content ?? []).map((child) => nodeToHtml(child, 0)).join('')}</${tag}>`;
    }).join('');
    return `<tr>${cells}</tr>`;
  });
  const head = renderedRows.length > 0 ? `<thead>${renderedRows[0]}</thead>` : '';
  const body = renderedRows.length > 1 ? `<tbody>${renderedRows.slice(1).join('')}</tbody>` : '<tbody></tbody>';
  const marker = continuation ? '<p class="table-meta">续表</p>' : '';
  return `<figure class="financial-table"${attrs}>${marker}${unit ? `<p class="table-meta">${escapeHtml(unit)}</p>` : ''}<table>${caption}${head}${body}</table></figure>`;
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
    const span = Math.max(1, Math.min(20, Number(cell.attrs?.colspan ?? 1) || 1));
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
  return value.replace(/([\\`*[\]()])/g, '\\$1');
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

function reportCss(options: RenderOptions): string {
  const fontFace = options.fontDataUrl ? `@font-face{font-family:"Noto Sans SC";src:url("${options.fontDataUrl}") format("woff2");font-weight:100 900;font-display:block;}` : '';
  return `${fontFace}
:root{color-scheme:light dark;--report-bg:#f7f7f5;--report-paper:#fff;--report-ink:#1b1b18;--report-muted:#696760;--report-line:#d9d4c7;--report-accent:#b78a38;--report-font:"Noto Sans SC","PingFang SC","Microsoft YaHei",sans-serif}
@media (prefers-color-scheme:dark){:root{--report-bg:#111;--report-paper:#181817;--report-ink:#efeee8;--report-muted:#a8a49b;--report-line:#36332e;--report-accent:#d1a85a}}
@page{size:A4;margin:20mm}
*{box-sizing:border-box}
body{margin:0;background:var(--report-bg);color:var(--report-ink);font-family:var(--report-font);font-size:16px;line-height:28px;letter-spacing:0}
.report-shell{max-width:calc(42em + 48px);margin:0 auto;padding:32px 24px 56px}
.report-cover,.report-toc,.report-body{max-width:42em;margin:0 auto}
.report-cover{padding:12px 0 28px;border-bottom:1px solid var(--report-line)}
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
.report-image img{max-width:100%;height:auto;display:block}
.report-note{padding-top:10px;border-top:1px solid var(--report-line);color:var(--report-muted);font-size:14px;line-height:24px}
.report-page-break{break-after:page;height:0}
.report-shell.is-print{width:210mm;min-height:297mm;max-width:none;margin:24px auto;padding:20mm;background:#fff;color:#111;box-shadow:0 20px 60px rgba(0,0,0,.16)}
.report-shell.is-print .report-cover,.report-shell.is-print .report-toc,.report-shell.is-print .report-body{max-width:none}
.report-shell.is-print table{font-size:9pt;line-height:1.4}
.report-shell.is-print th,.report-shell.is-print td{padding:5pt 6pt}
.report-shell.is-print .report-note{font-size:9pt;line-height:1.45}
@media print{body{background:#fff;color:#111;font-size:11pt;line-height:1.65}.report-shell{max-width:none;padding:0}.report-cover,.report-toc,.report-body{max-width:none}.report-cover{break-after:avoid}.report-toc{break-after:page}table{font-size:9pt;line-height:1.4}thead{display:table-header-group}tfoot{display:table-footer-group}th,td{padding:5pt 6pt}.report-note{font-size:9pt;line-height:1.45}.report-shell.is-print{width:auto;min-height:0;max-width:none;margin:0;padding:0;background:#fff;box-shadow:none}}`;
}
