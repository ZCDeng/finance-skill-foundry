import mammoth from 'mammoth';
import { parseHTML } from 'linkedom';
import {
  AlignmentType,
  BorderStyle,
  Document,
  ExternalHyperlink,
  Footer,
  Header,
  HeadingLevel,
  ImageRun,
  LevelFormat,
  Packer,
  PageNumber,
  Paragraph,
  Table,
  TableCell,
  TableLayoutType,
  TableOfContents,
  TableRow,
  TextRun,
  WidthType,
} from 'docx';
import type { ReportDocument, ReportFormat, ReportImportResult, ReportNode, ReportSource } from './model.js';
import { createReportDocument, documentFromMarkdown, documentToMarkdown, renderReportHtml, safeHref, safeImageSrc, textContent } from './format.js';
import { reportVisualEvidence } from './visual-evidence.js';

type ImportResources = Record<string, string>;
type ImportContext = { source: ReportSource; resources: ImportResources; warnings: string[] };

export { documentFromMarkdown, documentToMarkdown, renderReportHtml };

const TWIP_PER_MM = 56.6929133858;
const NUMERIC_TEXT = /^[(（]?-?(?:¥|￥|\$)?\s*\d[\d,]*(?:\.\d+)?%?[)）]?$/;
const NOTE_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$/;
// DESIGN.md 财务数字 in Word: figure cells set their Latin characters in the embedded IBM Plex Mono (units such as 万元
// stay in Noto Sans SC), a negative reads in the muted red, and a 合计/总计 or 小计 row is bold. Word embeds one
// Regular face, so bold Plex is drawn by Word itself.
const FIGURE_FONT = 'IBM Plex Mono';
const FIGURE_RUN_FONT = { ascii: FIGURE_FONT, hAnsi: FIGURE_FONT, eastAsia: 'Noto Sans SC', cs: FIGURE_FONT };
const NEGATIVE_COLOR = '94463D';
const NEGATIVE_FIGURE = /^(?:[-−]|[(（](?=[-−]?(?:¥|￥|\$)?\s*\d))/;
const TOTAL_ROW = /^(?:合计|总计|总额|total\b)/i;
const SUBTOTAL_ROW = /^(?:小计|subtotal\b)/i;
// In prose only digits and % take Plex Mono, as in the app (FND Figures); words, commas and points keep Noto Sans SC.
const PROSE_DIGITS = /[0-9%]+/g;

const HEADING_LEVELS = {
  1: HeadingLevel.HEADING_1,
  2: HeadingLevel.HEADING_2,
  3: HeadingLevel.HEADING_3,
  4: HeadingLevel.HEADING_4,
  5: HeadingLevel.HEADING_5,
  6: HeadingLevel.HEADING_6,
} as const;

export async function importReport(data: Buffer, format: ReportFormat, source: ReportSource, resources: ImportResources = {}): Promise<ReportImportResult> {
  switch (format) {
    case 'md': {
      const warnings: string[] = [];
      return withSource(sanitizeImportedImages(documentFromMarkdown(data.toString('utf8')), resources, warnings), source, warnings);
    }
    case 'html':
      return importHtml(data, source, resources);
    case 'docx':
      return importDocx(data, source);
    case 'pdf':
      return importPdf(data, source);
    case 'xlsx':
      return { warnings: ['Excel 文稿导入由 Foundry 工作表接口按 sheet/range 处理；转换层未直接展开工作簿。'], source, sheets: [], needsReview: true };
    case 'pptx':
      return { warnings: ['PPT 文稿导入由 Foundry 读取文字和表格；转换层未直接展开演示文稿。'], source, needsReview: true };
    default:
      return { warnings: [`暂不支持的文稿格式：${String(format)}`], source, needsReview: true };
  }
}

type ExportOptions = { marker?: string; contentMode?: string; projectionHash?: string; draftId?: string; contentHash?: string; publicationStatus?: string; reviewStatus?: string; reproducibilityStatus?: string; sources?: string[]; visualSources?: string[] };

export async function exportDocx(doc: ReportDocument, title: string, fontData?: Uint8Array, options: ExportOptions = {}, figureFontData?: Uint8Array): Promise<Buffer> {
  const metadata = [doc.metadata.company, doc.metadata.period, doc.metadata.currency, doc.metadata.unit].filter(Boolean).join(' / ');
  const content = exportNodes(doc.content, title);
  const managementMode = isManagementMode(options);
  const receipt = docxReceipt({ ...options, visualSources: options.visualSources ?? reportVisualEvidence(doc) });
  const body = nodesToDocx(content, collectNoteIds(content));
  const frontMatter = [
    ...(options.marker ? [new Paragraph({ keepNext: true, spacing: { after: 120 }, children: [new TextRun({ text: options.marker, size: 18, color: '7A4D00', bold: true })] })] : []),
    new Paragraph({ text: title, heading: HeadingLevel.TITLE, spacing: { after: metadata ? 120 : 180 } }),
    ...(metadata ? [new Paragraph({ keepNext: true, spacing: { after: 180 }, children: [new TextRun({ text: metadata, size: 20, color: '696760' })] })] : []),
  ];
  const children = managementMode
    ? [...frontMatter, ...body, ...receipt]
    : [...frontMatter, ...receipt, new TableOfContents('目录', { hyperlink: true, headingStyleRange: '1-2' }), ...body];
  const headerText = [
    options.marker,
    title,
    options.contentMode,
    options.projectionHash?.slice(0, 12),
  ].filter(Boolean).join(' · ');
  const document = new Document({
    creator: 'FA Foundry',
    title,
    fonts: fontData || figureFontData ? [
      ...(fontData ? [{ name: 'Noto Sans SC', data: Buffer.from(fontData) }] : []),
      ...(figureFontData ? [{ name: FIGURE_FONT, data: Buffer.from(figureFontData) }] : []),
    ] : undefined,
    styles: {
      paragraphStyles: [
        { id: 'Normal', name: 'Normal', run: { font: 'Noto Sans SC', size: 22 }, paragraph: { spacing: { line: 360, after: 160 } } },
        { id: 'Title', name: 'Title', basedOn: 'Normal', next: 'Normal', run: { size: 32, bold: true }, paragraph: { spacing: { after: 300 }, keepNext: true } },
        { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { size: 28, bold: true }, paragraph: { spacing: { before: 360, after: 160 }, keepNext: true, outlineLevel: 0 } },
        { id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { size: 24, bold: true }, paragraph: { spacing: { before: 300, after: 140 }, keepNext: true, outlineLevel: 1 } },
        { id: 'Heading3', name: 'Heading 3', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { size: 22, bold: true }, paragraph: { spacing: { before: 240, after: 120 }, keepNext: true, outlineLevel: 2 } },
      ],
    },
    numbering: {
      config: [{
        reference: 'foundry-numbering',
        levels: [{ level: 0, format: LevelFormat.DECIMAL, text: '%1.', alignment: AlignmentType.LEFT }],
      }],
    },
    sections: [{
      properties: {
        page: {
          size: { width: 11906, height: 16838 },
          margin: {
            top: mm(20),
            right: mm(20),
            bottom: mm(20),
            left: mm(20),
            header: mm(10),
            footer: mm(10),
          },
          pageNumbers: { start: 1 },
        },
      },
      headers: { default: new Header({ children: [new Paragraph({ children: [new TextRun({ text: headerText || title, size: 18 })] })] }) },
      footers: {
        default: new Footer({
          children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ children: [PageNumber.CURRENT] })] })],
        }),
      },
      children,
    }],
  });
  return Packer.toBuffer(document);
}

function isManagementMode(options: ExportOptions): boolean {
  return options.contentMode === 'management';
}

function docxReceipt(options: ExportOptions): Paragraph[] {
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
  const paragraphs = rows.map(([label, value]) => new Paragraph({ spacing: { after: 40 }, children: [new TextRun({ text: `${label}：`, bold: true, size: 18, color: '696760' }), new TextRun({ text: value, size: 18, color: '696760' })] }));
  if (sources.length) {
    paragraphs.push(new Paragraph({ spacing: { before: 60, after: 40 }, children: [new TextRun({ text: '授权来源：' + sources.join('；'), size: 18, color: '696760' })] }));
  }
  for (const source of options.visualSources ?? []) {
    paragraphs.push(new Paragraph({ spacing: { before: 60, after: 40 }, children: [new TextRun({ text: '图表依据：' + source, size: 18, color: '696760' })] }));
  }
  if (paragraphs.length) paragraphs.push(new Paragraph({ spacing: { after: 240 } }));
  return paragraphs;
}

function exportNodes(content: ReportNode[], title: string): ReportNode[] {
  const first = content[0];
  if (first?.type === 'heading' && Number(first.attrs?.level ?? 1) === 1 && normalizeTitle(textContent(first)) === normalizeTitle(title)) {
    return content.slice(1);
  }
  return content;
}

function normalizeTitle(value: string): string {
  return value.replace(/\s+/g, '').toLocaleLowerCase();
}

async function importDocx(data: Buffer, source: ReportSource): Promise<ReportImportResult> {
  const result = await mammoth.convertToHtml(
    { buffer: data },
    {
      convertImage: mammoth.images.imgElement(async (image) => {
        const imageBuffer = await image.read('base64');
        const src = `data:${image.contentType};base64,${imageBuffer}`;
        return { src: safeImageSrc(src) ? src : '' };
      }),
      styleMap: [
        "p[style-name='Title'] => h1:fresh",
        "p[style-name='Heading 1'] => h1:fresh",
        "p[style-name='Heading 2'] => h2:fresh",
        "p[style-name='Heading 3'] => h3:fresh",
      ],
    },
  );
  const warnings = [
    ...result.messages.map((message) => `${message.type}: ${message.message}`),
    'Word 导入采用语义转换；复杂版面、页眉页脚、文本框和分页位置可能损失，需复核。',
  ];
  const imported = htmlToDocument(result.value, source, {}, warnings);
  return { ...withSource(imported, source, warnings), needsReview: warnings.length > 0 };
}

function importHtml(data: Buffer, source: ReportSource, resources: ImportResources = {}): ReportImportResult {
  const html = data.toString('utf8');
  const warnings = collectHtmlWarnings(html);
  const doc = htmlToDocument(html, source, resources, warnings);
  return { ...withSource(doc, source, warnings), needsReview: warnings.length > 0 };
}

async function importPdf(data: Buffer, source: ReportSource): Promise<ReportImportResult> {
  const pdfjs = await importPdfjs();
  const loadingTask = pdfjs.getDocument({ data: new Uint8Array(data), disableWorker: true, useSystemFonts: true, isEvalSupported: false });
  const pdf = await loadingTask.promise;
  try {
    const content: ReportNode[] = [];
    const warnings: string[] = ['PDF 导入按可选择文字抽取；复杂表格、扫描页和跨栏顺序需复核。'];
    for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
      const page = await pdf.getPage(pageNumber);
      const text = await page.getTextContent({ includeMarkedContent: false });
      const lines = pdfItemsToLines(text.items as Array<{ str?: string; transform?: number[] }>);
      if (lines.length === 0) {
        warnings.push(`第 ${pageNumber} 页未识别到可选择文字，可能需要 OCR 重试。`);
        continue;
      }
      for (const line of lines) {
        content.push({
          type: 'paragraph',
          attrs: { source_id: source.id, page: pageNumber },
          content: [{ type: 'text', text: line }],
        });
      }
    }
    const doc = createReportDocument(content);
    doc.sources = [source];
    return { document: doc, title: titleFromDocument(doc) || source.name, warnings, source, needsReview: true };
  } finally {
    if (typeof pdf.destroy === 'function') await pdf.destroy();
    else if (typeof loadingTask.destroy === 'function') await loadingTask.destroy();
  }
}

function htmlToDocument(html: string, source: ReportSource, resources: ImportResources = {}, warnings: string[] = []): ReportDocument {
  const { document } = parseHTML(html);
  const root = document.querySelector('body') ?? document;
  const context: ImportContext = { source, resources, warnings };
  const content = childrenToNodes(root, context).filter(Boolean) as ReportNode[];
  const doc = createReportDocument(content);
  doc.sources = [source];
  return doc;
}


function sanitizeImportedImages(document: ReportDocument, resources: ImportResources, warnings: string[]): ReportDocument {
  return {
    ...document,
    content: filterImages(document.content, resources, warnings),
  };
}

function filterImages(nodes: ReportNode[] = [], resources: ImportResources, warnings: string[]): ReportNode[] {
  const filtered: ReportNode[] = [];
  for (const node of nodes) {
    if (node.type === 'image') {
      const src = resolveImageSrc(String(node.attrs?.src ?? ''), { source: { id: '', name: '', sha256: '', format: 'md' }, resources, warnings });
      if (src) filtered.push({ ...node, attrs: { ...(node.attrs ?? {}), src } });
      continue;
    }
    filtered.push({ ...node, content: node.content ? filterImages(node.content, resources, warnings) : node.content });
  }
  return filtered;
}

function resolveImageSrc(src: string, context: ImportContext): string {
  const trimmed = src.trim();
  if (!trimmed) return '';
  if (safeImageSrc(trimmed)) return trimmed;
  const mapped = context.resources[trimmed];
  if (mapped && safeImageSrc(mapped)) return mapped;
  if (mapped && !safeImageSrc(mapped)) {
    context.warnings.push(`图片资源 ${shortResourceName(trimmed)} 不是受支持的 PNG/JPEG data URL，已跳过。`);
    return '';
  }
  context.warnings.push(`图片资源 ${shortResourceName(trimmed)} 未随导入提供，已跳过。`);
  return '';
}

function shortResourceName(value: string): string {
  return value.length > 120 ? `${value.slice(0, 117)}...` : value;
}

function collectHtmlWarnings(html: string): string[] {
  const warnings: string[] = [];
  if (/<script[\s>]/i.test(html)) warnings.push('HTML 导入已移除脚本内容。');
  if (/\son[a-z]+\s*=/i.test(html)) warnings.push('HTML 导入已忽略事件处理属性。');
  if (/(?:src|href)\s*=\s*["'](?:https?:)?\/\//i.test(html)) warnings.push('HTML 导入发现外部链接或资源；不会自动请求外部内容。');
  return warnings;
}

function childrenToNodes(parent: any, context: ImportContext): ReportNode[] {
  const out: ReportNode[] = [];
  for (const child of Array.from(parent.childNodes ?? []) as any[]) {
    const node = elementToNode(child, context);
    if (Array.isArray(node)) out.push(...node);
    else if (node) out.push(node);
  }
  return out;
}

function elementToNode(node: any, context: ImportContext): ReportNode | ReportNode[] | undefined {
  const { source } = context;
  if (node.nodeType === 3) {
    const text = String(node.textContent ?? '').replace(/\s+/g, ' ').trim();
    return text ? { type: 'paragraph', attrs: { source_id: source.id }, content: [{ type: 'text', text }] } : undefined;
  }
  if (node.nodeType !== 1) return undefined;
  const tag = String(node.localName ?? node.tagName ?? '').toLowerCase();
  if (tag === 'script' || tag === 'style' || tag === 'noscript' || tag === 'iframe' || tag === 'object') return undefined;
  if (tag === 'figure' && hasClass(node, 'report-visual')) {
    context.warnings.push('导入的图表已保留为精确数据与说明；如需可编辑图形，请在本任务内重新绑定计算后插入。');
    const data = node.querySelector('.report-visual-data');
    if (!data) return undefined;
    data.querySelector('summary')?.remove();
    return childrenToNodes(data, context);
  }
  if (tag === 'svg') return undefined;
  if (tag === 'figure' && hasClass(node, 'financial-table')) {
    const table = node.querySelector('table');
    return table ? tableFromElement(table, context, tableAttrsFromFigure(node, source)) : undefined;
  }
  if (tag === 'aside' && hasClass(node, 'report-note')) {
    const noteId = noteIdFromReportNote(node) || '1';
    const noteContent = Array.from(node.querySelectorAll('p')) as any[];
    return {
      type: 'reportNote',
      attrs: { source_id: source.id, id: noteId },
      content: noteContent.length > 0
        ? noteContent.map((paragraph) => ({ type: 'paragraph', content: inlineChildren(paragraph, context) }))
        : [{ type: 'paragraph', content: inlineChildren(node, context).filter((child) => textContent(child).trim() !== noteId) }],
    };
  }
  if (/^h[1-6]$/.test(tag)) return blockNode('heading', inlineChildren(node, context), source, { level: Number(tag.slice(1)) });
  if (tag === 'p') {
    const note = noteFromParagraph(node, context);
    return note ?? blockNode('paragraph', inlineChildren(node, context), source);
  }
  if (tag === 'br') return { type: 'hardBreak' };
  if (tag === 'ul' || tag === 'ol') return { type: tag === 'ol' ? 'orderedList' : 'bulletList', attrs: { source_id: source.id }, content: childrenToNodes(node, context).filter((child) => child.type === 'listItem') };
  if (tag === 'li') return { type: 'listItem', attrs: { source_id: source.id }, content: [{ type: 'paragraph', content: inlineChildren(node, context) }] };
  if (tag === 'blockquote') return { type: 'blockquote', attrs: { source_id: source.id }, content: [{ type: 'paragraph', content: inlineChildren(node, context) }] };
  if (tag === 'pre') return { type: 'codeBlock', attrs: { source_id: source.id }, content: [{ type: 'text', text: String(node.textContent ?? '') }] };
  if (tag === 'hr') return { type: 'horizontalRule', attrs: { source_id: source.id } };
  if (tag === 'img') {
    const src = resolveImageSrc(String(node.getAttribute('src') ?? ''), context);
    return src ? { type: 'image', attrs: { source_id: source.id, src, alt: String(node.getAttribute('alt') ?? ''), title: String(node.getAttribute('title') ?? '') } } : undefined;
  }
  if (tag === 'table') return tableFromElement(node, context);
  if (tag === 'sup') {
    const noteRef = noteRefIdFromElement(node);
    return noteRef ? { type: 'text', text: `[^${noteRef}]` } : { type: 'text', text: String(node.textContent ?? '') };
  }
  return childrenToNodes(node, context);
}

function inlineChildren(parent: any, context: ImportContext): ReportNode[] {
  const out: ReportNode[] = [];
  for (const child of Array.from(parent.childNodes ?? []) as any[]) {
    const nodes = inlineNode(child, context);
    if (Array.isArray(nodes)) out.push(...nodes);
    else if (nodes) out.push(nodes);
  }
  return out.length > 0 ? out : [{ type: 'text', text: '' }];
}

function inlineNode(node: any, context: ImportContext): ReportNode | ReportNode[] | undefined {
  if (node.nodeType === 3) return { type: 'text', text: String(node.textContent ?? '') };
  if (node.nodeType !== 1) return undefined;
  const tag = String(node.localName ?? node.tagName ?? '').toLowerCase();
  if (tag === 'script' || tag === 'style' || tag === 'iframe' || tag === 'object') return undefined;
  if (tag === 'br') return { type: 'hardBreak' };
  const noteRef = noteRefIdFromElement(node);
  if (noteRef) return { type: 'text', text: `[^${noteRef}]` };
  if (tag === 'img') {
    const src = resolveImageSrc(String(node.getAttribute('src') ?? ''), context);
    return src ? { type: 'image', attrs: { source_id: context.source.id, src, alt: String(node.getAttribute('alt') ?? '') } } : undefined;
  }
  const children = inlineChildren(node, context);
  const mark = markForElement(tag, node);
  return mark ? children.map((child) => child.type === 'text' ? { ...child, marks: [...(child.marks ?? []), mark] } : child) : children;
}

function markForElement(tag: string, node: any) {
  if (tag === 'strong' || tag === 'b') return { type: 'bold' };
  if (tag === 'em' || tag === 'i') return { type: 'italic' };
  if (tag === 's' || tag === 'strike' || tag === 'del') return { type: 'strike' };
  if (tag === 'u') return { type: 'underline' };
  if (tag === 'code') return { type: 'code' };
  if (tag === 'a') {
    if (noteRefIdFromElement(node)) return undefined;
    const href = String(node.getAttribute('href') ?? '');
    return safeHref(href) ? { type: 'link', attrs: { href } } : undefined;
  }
  return undefined;
}

function noteIdFromReportNote(node: any): string {
  const dataId = safeNoteId(node.getAttribute?.('data-note-id'));
  if (dataId) return dataId;
  const anchorId = String(node.getAttribute?.('id') ?? '');
  if (anchorId.startsWith('note-')) {
    const id = safeNoteId(anchorId.slice(5));
    if (id) return id;
  }
  return safeNoteId(String(node.querySelector?.('sup')?.textContent ?? '').replace(/[\s[\]]/g, ''));
}

function noteRefIdFromElement(node: any): string {
  const dataId = safeNoteId(node.getAttribute?.('data-report-note-ref'));
  if (dataId) return dataId;
  const descendant = node.querySelector?.('[data-report-note-ref]');
  const descendantId = safeNoteId(descendant?.getAttribute?.('data-report-note-ref'));
  if (descendantId) return descendantId;
  const tag = String(node.localName ?? node.tagName ?? '').toLowerCase();
  if (tag !== 'sup') return '';
  const text = String(node.textContent ?? '').trim();
  const match = text.match(/^\[?([A-Za-z0-9][A-Za-z0-9_.:-]{0,63})\]?$/);
  return match ? safeNoteId(match[1]) : '';
}

function safeNoteId(value: unknown): string {
  const text = typeof value === 'string' || typeof value === 'number' ? String(value).trim().slice(0, 64) : '';
  return NOTE_ID_PATTERN.test(text) ? text : '';
}

function tableFromElement(table: any, context: ImportContext, inheritedAttrs: Record<string, unknown> = {}): ReportNode {
  const { source } = context;
  const rows: ReportNode[] = [];
  for (const row of Array.from(table.querySelectorAll('tr')) as any[]) {
    const cells: ReportNode[] = [];
    for (const cell of Array.from(row.children ?? []) as any[]) {
      const tag = String(cell.localName ?? '').toLowerCase();
      if (tag !== 'td' && tag !== 'th') continue;
      const text = String(cell.textContent ?? '').trim();
      cells.push({
        type: tag === 'th' ? 'tableHeader' : 'tableCell',
        attrs: {
          source_id: source.id,
          colspan: numberFromAttr(cell.getAttribute('colspan')),
          rowspan: numberFromAttr(cell.getAttribute('rowspan')),
          textAlign: /text-align\s*:\s*right/i.test(String(cell.getAttribute('style') ?? '')) || NUMERIC_TEXT.test(text) ? 'right' : 'left',
        },
        content: [{ type: 'paragraph', content: inlineChildren(cell, context) }],
      });
    }
    if (cells.length > 0) rows.push({ type: 'tableRow', attrs: { source_id: source.id }, content: cells });
  }
  const caption = String(table.querySelector('caption')?.textContent ?? '').trim();
  return { type: 'table', attrs: { source_id: source.id, ...inheritedAttrs, ...(caption ? { caption } : {}) }, content: rows };
}

function tableAttrsFromFigure(figure: any, source: ReportSource): Record<string, unknown> {
  const attrs: Record<string, unknown> = { source_id: source.id };
  const meta = Array.from(figure.querySelectorAll('.table-meta')) as any[];
  const parts = meta
    .map((node) => String(node.textContent ?? '').trim())
    .filter((text) => text && text !== '续表')
    .flatMap((text) => text.split('/').map((part) => part.trim()).filter(Boolean));
  if (parts[0]) attrs.period = parts[0];
  if (parts[1]) attrs.currency = parts[1];
  if (parts[2]) attrs.unit = parts.slice(2).join(' / ');
  return attrs;
}

function hasClass(node: any, className: string): boolean {
  return String(node.getAttribute?.('class') ?? '').split(/\s+/).includes(className);
}

function hasSemanticNoteRef(node: any): boolean {
  if (safeNoteId(node?.getAttribute?.('data-report-note-ref'))) return true;
  return Boolean(node?.querySelector?.('[data-report-note-ref]'));
}

function noteFromParagraph(node: any, context: ImportContext): ReportNode | undefined {
  const { source } = context;
  const firstElement = Array.from(node.childNodes ?? []).find((child: any) => child.nodeType === 1 || String(child.textContent ?? '').trim());
  if ((firstElement as any)?.nodeType !== 1) return undefined;
  const tag = String((firstElement as any)?.localName ?? (firstElement as any)?.tagName ?? '').toLowerCase();
  if (tag !== 'sup' || hasSemanticNoteRef(firstElement)) return undefined;
  const rawId = safeNoteId(String((firstElement as any).textContent ?? '').replace(/[\s[\]]/g, ''));
  if (!rawId) return undefined;
  let skippedLabel = false;
  const content = inlineChildren(node, context).filter((child) => {
    if (skippedLabel) return true;
    const normalized = textContent(child).replace(/[\s[\]^]/g, '');
    if (normalized === rawId) {
      skippedLabel = true;
      return false;
    }
    return true;
  });
  return { type: 'reportNote', attrs: { source_id: source.id, id: rawId }, content: [{ type: 'paragraph', content: content.length > 0 ? content : [{ type: 'text', text: '' }] }] };
}

function numberFromAttr(value: string | null): number | undefined {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 1 ? parsed : undefined;
}

function blockNode(type: string, content: ReportNode[], source: ReportSource, attrs: Record<string, unknown> = {}): ReportNode {
  return { type, attrs: { ...attrs, source_id: source.id }, content };
}

function withSource(document: ReportDocument, source: ReportSource, warnings: string[]): ReportImportResult {
  const sourced = addSourceToDocument(document, source);
  return { document: sourced, title: titleFromDocument(sourced) || source.name, warnings, source, needsReview: warnings.length > 0 };
}

function addSourceToDocument(document: ReportDocument, source: ReportSource): ReportDocument {
  return {
    ...document,
    sources: [source],
    content: document.content.map((node) => addSourceAttrs(node, source.id)),
  };
}

function addSourceAttrs(node: ReportNode, sourceId: string): ReportNode {
  const attrs = node.type === 'text' ? node.attrs : { ...(node.attrs ?? {}), source_id: node.attrs?.source_id ?? sourceId };
  return { ...node, attrs, content: node.content?.map((child) => addSourceAttrs(child, sourceId)) };
}

function titleFromDocument(doc: ReportDocument): string {
  const heading = doc.content.find((node) => node.type === 'heading');
  return heading ? textContent(heading).trim() : '';
}

function pdfItemsToLines(items: Array<{ str?: string; transform?: number[] }>): string[] {
  const rows = new Map<number, Array<{ x: number; text: string }>>();
  for (const item of items) {
    const text = String(item.str ?? '').trim();
    if (!text) continue;
    const x = item.transform?.[4] ?? 0;
    const y = Math.round((item.transform?.[5] ?? 0) / 3) * 3;
    const row = rows.get(y) ?? [];
    row.push({ x, text });
    rows.set(y, row);
  }
  return Array.from(rows.entries())
    .sort((a, b) => b[0] - a[0])
    .map(([, row]) => row.sort((a, b) => a.x - b.x).map((item) => item.text).join(' ').replace(/\s+/g, ' ').trim())
    .filter(Boolean);
}

async function importPdfjs(): Promise<{ getDocument: (options: Record<string, unknown>) => { promise: Promise<any>; destroy?: () => Promise<void> } }> {
  return import('pdfjs-dist/legacy/build/pdf.mjs');
}

function nodesToDocx(nodes: ReportNode[], noteIds: Set<string>): Array<Paragraph | Table> {
  return nodes.flatMap((node) => nodeToDocx(node, noteIds));
}

function nodeToDocx(node: ReportNode, noteIds: Set<string>): Array<Paragraph | Table> {
  switch (node.type) {
    case 'heading': {
      const level = Math.max(1, Math.min(6, Number(node.attrs?.level ?? 1))) as keyof typeof HEADING_LEVELS;
      return [new Paragraph({ heading: HEADING_LEVELS[level], keepNext: true, children: inlineToDocxRuns(node.content ?? [], {}, noteIds) })];
    }
    case 'paragraph':
      return [new Paragraph({ children: inlineToDocxRuns(node.content ?? [], {}, noteIds) })];
    case 'blockquote':
      return [new Paragraph({ indent: { left: 360 }, border: { left: { style: BorderStyle.SINGLE, size: 6, color: 'B78A38' } }, children: inlineToDocxRuns(flatInline(node.content ?? []), {}, noteIds) })];
    case 'codeBlock':
      return [new Paragraph({ children: [new TextRun({ text: textContent(node), font: 'Menlo', size: 18 })] })];
    case 'horizontalRule':
      return [new Paragraph({ border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: 'D9D4C7' } } })];
    case 'bulletList':
    case 'orderedList':
      return (node.content ?? []).map((item) => new Paragraph({
        bullet: node.type === 'bulletList' ? { level: 0 } : undefined,
        numbering: node.type === 'orderedList' ? { reference: 'foundry-numbering', level: 0 } : undefined,
        children: inlineToDocxRuns(flatInline(item.content ?? []), {}, noteIds),
      }));
    case 'table':
      return tableBlockToDocx(node, noteIds);
    case 'image':
      return imageToDocx(node);
    case 'reportVisual':
      throw new Error('图表尚未完成导出渲染，请通过文稿导出入口生成 Word。');
    case 'reportNote':
      return [new Paragraph({ style: 'Normal', children: [new TextRun({ text: `[${String(node.attrs?.id ?? '')}] `, superScript: true, size: 18 }), ...inlineToDocxRuns(flatInline(node.content ?? []), { size: 18 }, noteIds)] })];
    case 'reportPageBreak':
      return [new Paragraph({ pageBreakBefore: true })];
    default:
      return [];
  }
}

function tableBlockToDocx(table: ReportNode, noteIds: Set<string>): Array<Paragraph | Table> {
  const lead: Paragraph[] = [];
  if (table.attrs?.caption) {
    lead.push(new Paragraph({ keepNext: true, spacing: { before: 160, after: 80 }, children: [new TextRun({ text: String(table.attrs.caption), bold: true, size: 20 })] }));
  }
  const meta = [table.attrs?.period, table.attrs?.currency, table.attrs?.unit].filter(Boolean).map(String).join(' / ');
  if (meta) lead.push(new Paragraph({ keepNext: true, spacing: { after: 60 }, children: [new TextRun({ text: meta, size: 18, color: '696760' })] }));
  return [...lead, tableToDocx(table, noteIds)];
}

function tableToDocx(table: ReportNode, noteIds: Set<string>): Table {
  const rows = table.content ?? [];
  const splitTables = splitWideTable(rows);
  if (splitTables.length > 1) {
    return new Table({
      width: { size: 100, type: WidthType.PERCENTAGE },
      layout: TableLayoutType.AUTOFIT,
      rows: splitTables.flatMap((group, index) => [
        ...(index === 0 ? [] : [new TableRow({ children: [new TableCell({ columnSpan: Math.max(1, group[0]?.content?.length ?? 1), children: [new Paragraph({ text: '续表', keepNext: true })] })] })]),
        ...group.map((row, rowIndex) => rowToDocx(row, rowIndex === 0, noteIds)),
      ]),
    });
  }
  return new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    layout: TableLayoutType.AUTOFIT,
    rows: rows.map((row, index) => rowToDocx(row, index === 0, noteIds)),
  });
}

function splitWideTable(rows: ReportNode[]): ReportNode[][] {
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

function rowToDocx(row: ReportNode, header: boolean, noteIds: Set<string>): TableRow {
  const name = textContent(row.content?.[0] ?? { type: 'text' }).trim();
  const total = !header && TOTAL_ROW.test(name);
  const weighted = total || (!header && SUBTOTAL_ROW.test(name));
  return new TableRow({
    tableHeader: header,
    cantSplit: true,
    children: (row.content ?? []).map((cell, index) => {
      const text = textContent(cell).trim();
      const right = cell.attrs?.textAlign === 'right' || NUMERIC_TEXT.test(text);
      const headerCell = header || cell.type === 'tableHeader';
      const figure = right && index > 0 && !headerCell;
      return new TableCell({
        columnSpan: numberOrUndefined(cell.attrs?.colspan),
        rowSpan: numberOrUndefined(cell.attrs?.rowspan),
        margins: { top: 100, bottom: 100, left: 120, right: 120 },
        ...(total ? { borders: { top: { style: BorderStyle.SINGLE, size: 6, color: '1B1B18' } } } : {}),
        children: [new Paragraph({
          alignment: right ? AlignmentType.RIGHT : AlignmentType.LEFT,
          children: inlineToDocxRuns(flatInline(cell.content ?? []), { size: 18, bold: headerCell || weighted,
            ...(figure ? { figure: true, color: NEGATIVE_FIGURE.test(text) ? NEGATIVE_COLOR : undefined } : {}) }, noteIds),
        })],
      });
    }),
  });
}

function imageToDocx(node: ReportNode): Paragraph[] {
  const src = String(node.attrs?.src ?? '');
  if (!safeImageSrc(src)) return [];
  const match = src.match(/^data:image\/(png|jpeg|jpg);base64,(.+)$/i);
  if (!match) return [];
  const data = Buffer.from(match[2], 'base64');
  const type = match[1].toLowerCase() === 'png' ? 'png' : 'jpg';
  const { width, height } = imageDimensions(data, type);
  const scale = Math.min(1, 624 / width, 800 / height);
  const title = String(node.attrs?.title ?? '');
  const alt = String(node.attrs?.alt ?? title);
  return [new Paragraph({
    keepNext: Boolean(title),
    children: [new ImageRun({ data, transformation: { width: Math.max(1, Math.round(width * scale)), height: Math.max(1, Math.round(height * scale)) }, type,
      altText: { name: alt, title, description: alt } })],
  }), ...title.split('\n').filter(Boolean).map((text, index, lines) => new Paragraph({
    keepNext: index < lines.length - 1, spacing: { after: index < lines.length - 1 ? 40 : 180 },
    children: [new TextRun({ text, size: 18, color: '696760' })],
  }))];
}

/** Read only bounded image headers; dimensions never come from editable report attrs. */
function imageDimensions(data: Buffer, type: 'png' | 'jpg'): { width: number; height: number } {
  let width = 0, height = 0;
  if (type === 'png' && data.length >= 24 && data.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))) {
    width = data.readUInt32BE(16); height = data.readUInt32BE(20);
  } else if (type === 'jpg' && data[0] === 0xff && data[1] === 0xd8) {
    let offset = 2;
    while (offset + 4 <= data.length) {
      if (data[offset++] !== 0xff) break;
      while (data[offset] === 0xff) offset += 1;
      const marker = data[offset++];
      if (marker === 0xd9 || marker === 0xda) break;
      if (marker === 0x01 || (marker >= 0xd0 && marker <= 0xd7)) continue;
      if (offset + 2 > data.length) break;
      const size = data.readUInt16BE(offset);
      if (size < 2 || offset + size > data.length) break;
      if ([0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf].includes(marker) && size >= 7) {
        height = data.readUInt16BE(offset + 3); width = data.readUInt16BE(offset + 5); break;
      }
      offset += size;
    }
  }
  if (!(width > 0 && height > 0 && width <= 100_000 && height <= 100_000)) throw new Error('图片尺寸无效，无法导出 Word。');
  return { width, height };
}

type RunDefaults = { size?: number; bold?: boolean; figure?: boolean; color?: string };

function inlineToDocxRuns(nodes: ReportNode[], defaults: RunDefaults = {}, noteIds: Set<string> = new Set()): Array<TextRun | ExternalHyperlink> {
  return nodes.flatMap((node) => {
    if (node.type === 'text') {
      const marks = node.marks ?? [];
      const link = marks.find((mark) => mark.type === 'link' && safeHref(String(mark.attrs?.href ?? '')));
      const runs = textRunsWithNoteRefs(node, defaults, noteIds);
      const run = new TextRun({
        text: node.text ?? '',
        size: defaults.size ?? 22,
        bold: defaults.bold || marks.some((mark) => mark.type === 'bold'),
        italics: marks.some((mark) => mark.type === 'italic'),
        strike: marks.some((mark) => mark.type === 'strike'),
        underline: marks.some((mark) => mark.type === 'underline') ? {} : undefined,
        font: marks.some((mark) => mark.type === 'code') ? 'Menlo' : defaults.figure ? FIGURE_RUN_FONT : 'Noto Sans SC',
        ...(defaults.color ? { color: defaults.color } : {}),
      });
      if (link) return [new ExternalHyperlink({ link: String(link.attrs?.href), children: [run] })];
      if (marks.some((mark) => mark.type === 'code')) return [run];
      return runs;
    }
    if (node.type === 'hardBreak') return [new TextRun({ text: '\n' })];
    if (node.type === 'image') return [];
    return inlineToDocxRuns(node.content ?? [], defaults, noteIds);
  });
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

/** Prose text as runs, its digits and % in IBM Plex Mono; a figure cell's text is one run in the figure font. */
function proseRuns(text: string, base: Record<string, unknown>, defaults: RunDefaults): TextRun[] {
  if (defaults.figure) return [new TextRun({ ...base, text, font: FIGURE_RUN_FONT, ...(defaults.color ? { color: defaults.color } : {}) })];
  const runs: TextRun[] = [];
  let last = 0;
  for (const match of text.matchAll(PROSE_DIGITS)) {
    const index = match.index ?? 0;
    if (index > last) runs.push(new TextRun({ ...base, text: text.slice(last, index) }));
    runs.push(new TextRun({ ...base, text: match[0], font: FIGURE_RUN_FONT }));
    last = index + match[0].length;
  }
  if (last < text.length || runs.length === 0) runs.push(new TextRun({ ...base, text: text.slice(last) }));
  return runs;
}

function textRunsWithNoteRefs(node: ReportNode, defaults: RunDefaults, noteIds: Set<string>): TextRun[] {
  const text = node.text ?? '';
  const marks = node.marks ?? [];
  const runs: TextRun[] = [];
  const base = {
    size: defaults.size ?? 22,
    bold: defaults.bold || marks.some((mark) => mark.type === 'bold'),
    italics: marks.some((mark) => mark.type === 'italic'),
    strike: marks.some((mark) => mark.type === 'strike'),
    underline: marks.some((mark) => mark.type === 'underline') ? {} : undefined,
    font: 'Noto Sans SC',
  };
  let lastIndex = 0;
  const pattern = /\[\^([A-Za-z0-9][A-Za-z0-9_.:-]{0,63})\]/g;
  for (const match of text.matchAll(pattern)) {
    const index = match.index ?? 0;
    const id = safeNoteId(match[1]);
    if (!id || !noteIds.has(id)) continue;
    if (index > lastIndex) runs.push(...proseRuns(text.slice(lastIndex, index), base, defaults));
    runs.push(new TextRun({ ...base, text: `[${id}]`, superScript: true, size: Math.max(16, defaults.size ?? 18) }));
    lastIndex = index + match[0].length;
  }
  if (lastIndex < text.length || runs.length === 0) runs.push(...proseRuns(text.slice(lastIndex), base, defaults));
  return runs;
}

function flatInline(nodes: ReportNode[]): ReportNode[] {
  return nodes.flatMap((node) => node.type === 'paragraph' ? (node.content ?? []) : [node]);
}

function numberOrUndefined(value: unknown): number | undefined {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 1 ? parsed : undefined;
}

function mm(value: number): number {
  return Math.round(value * TWIP_PER_MM);
}
