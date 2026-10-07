import {
  DOCUMENT_METADATA_LABELS,
  TABLE_METADATA_LABELS,
  documentFromMarkdown,
  isTableStart,
  parseProjectionLine,
  textContent,
} from '../../../electron/reports/format.js';

/** Where a reading suggestion sits: the chapter above it, which paragraph of that chapter, and how it begins. */
export type ParagraphLocation = { section?: string; ordinal: number; excerpt: string };

type ParagraphBlock = { start: number; end: number; text: string; section?: string; ordinal: number };

const HEADING = /^(#{1,6})\s+(.+)$/;
const LIST = /^(\s*)([-*+]|\d+[.)])\s+(.+)$/;
const NOTE_DEFINITION = /^\[\^([^\]]+)\]:/;
const IMAGE = /^!\[([^\]]*)\]\(([^)\s]+)(?:\s+"([^"]+)")?\)$/;
const TABLE_LINE = /^\s*\|.*\|\s*$/;

/**
 * The paragraphs of a Markdown body as the reading view renders them (format.ts documentFromMarkdown): the
 * metadata line, table projection lines, headings, tables, lists, notes, code and images are not paragraphs.
 * Offsets count code points, as the server's positions do (Python string indexes).
 */
function paragraphBlocks(body: string): ParagraphBlock[] {
  const chars = Array.from(body);
  const lines: { text: string; start: number; end: number }[] = [];
  let lineStart = 0;
  for (let index = 0; index <= chars.length; index += 1) {
    if (index === chars.length || chars[index] === '\n') {
      lines.push({ text: chars.slice(lineStart, index).join('').replace(/\r$/, ''), start: lineStart, end: index });
      lineStart = index + 1;
    }
  }
  const texts = lines.map((line) => line.text);
  const nextNonEmpty = (from: number) => {
    let next = from;
    while (next < texts.length && !texts[next].trim()) next += 1;
    return next;
  };
  const blocks: ParagraphBlock[] = [];
  let section: string | undefined;
  let ordinal = 0;
  let i = 0;
  const first = texts.findIndex((line) => line.trim());
  if (first >= 0 && parseProjectionLine(texts[first], DOCUMENT_METADATA_LABELS)) i = first + 1;
  while (i < texts.length) {
    const line = texts[i];
    if (!line.trim() || NOTE_DEFINITION.test(line) || /^---+$/.test(line.trim()) || IMAGE.test(line)) {
      i += 1;
      continue;
    }
    const heading = line.match(HEADING);
    if (heading) {
      section = plainText(heading[2]) || heading[2].trim();
      ordinal = 0;
      i += 1;
      continue;
    }
    if (/^```/.test(line)) {
      i += 1;
      while (i < texts.length && !/^```/.test(texts[i])) i += 1;
      i += i < texts.length ? 1 : 0;
      continue;
    }
    const tableAt = parseProjectionLine(line, TABLE_METADATA_LABELS) && isTableStart(texts, nextNonEmpty(i + 1)) ? nextNonEmpty(i + 1)
      : isTableStart(texts, i) ? i : -1;
    if (tableAt >= 0) {
      i = tableAt;
      while (i < texts.length && TABLE_LINE.test(texts[i])) i += 1;
      continue;
    }
    if (LIST.test(line)) {
      while (i < texts.length && LIST.test(texts[i])) i += 1;
      continue;
    }
    const from = i;
    while (i < texts.length && texts[i].trim() && !HEADING.test(texts[i]) && !isTableStart(texts, i) && !NOTE_DEFINITION.test(texts[i])) {
      if (LIST.test(texts[i]) || /^```/.test(texts[i]) || /^---+$/.test(texts[i].trim())) break;
      i += 1;
    }
    const indent = Array.from(lines[from].text).length - Array.from(lines[from].text.trimStart()).length;
    ordinal += 1;
    blocks.push({ start: lines[from].start + indent, end: lines[i - 1].end, text: texts.slice(from, i).join('\n'), section, ordinal });
  }
  return blocks;
}

/** A paragraph's words as the reading view shows them, or '' when it does not render as one paragraph. */
function plainText(markdown: string): string {
  const node = documentFromMarkdown(markdown).content[0];
  if (!node || (node.type !== 'paragraph' && node.type !== 'heading')) return '';
  return textContent(node).replace(/\[\^([^\]]+)\]/g, '[$1]').trim();
}

function blockAt(blocks: ParagraphBlock[], position: number): number {
  return blocks.findIndex((block) => block.start <= position && position < block.end);
}

export function paragraphLocation(body: string, position: number): ParagraphLocation | undefined {
  if (!Number.isInteger(position) || position < 0) return undefined;
  const blocks = paragraphBlocks(body);
  const block = blocks[blockAt(blocks, position)];
  if (!block) return undefined;
  const words = Array.from((plainText(block.text) || block.text.trim()).replace(/\s+/g, ' '));
  let end = Math.min(words.length, 20);
  // Never stop inside a number: run on to its end, so 325644.0000 is not shown as 325644.…
  const inNumber = (char?: string) => Boolean(char && /[\d.,%]/.test(char));
  while (end < words.length && inNumber(words[end - 1]) && inNumber(words[end])) end += 1;
  const excerpt = end < words.length ? `${words.slice(0, end).join('')}…` : words.join('');
  return { ...(block.section ? { section: block.section } : {}), ordinal: block.ordinal, excerpt };
}

const LOCATE_PREFIX = 16;
const compact = (value: string) => Array.from(value.replace(/\s+/g, ''));

/**
 * The reading view's paragraph for a body position: matched by its first words among the container's own
 * paragraphs, the nth such paragraph when earlier ones begin the same way. null when it cannot be found.
 */
export function findReadingParagraph(container: Element, body: string, position: number): HTMLElement | null {
  const blocks = paragraphBlocks(body);
  const index = blockAt(blocks, position);
  if (index < 0) return null;
  const key = (text: string) => compact(plainText(text)).slice(0, LOCATE_PREFIX).join('');
  const prefix = key(blocks[index].text);
  if (!prefix) return null;
  const nth = blocks.slice(0, index).filter((block) => key(block.text) === prefix).length;
  const candidates = Array.from(container.children).filter((element): element is HTMLElement =>
    element.tagName === 'P' && compact(element.textContent ?? '').join('').startsWith(prefix));
  return candidates[nth] ?? null;
}
