import type { ReportDocument, ReportMark, ReportNode } from './model.js';

export interface ReportParagraphReflowResult {
  document: ReportDocument;
  changedParagraphs: number;
  addedParagraphs: number;
}

const LONG_PARAGRAPH_THRESHOLD = 160;
const SENTENCE_BOUNDARIES = new Set(['。', '！', '？', '；', ';']);
const NOTE_REF_AFTER_BOUNDARY = /^(?:[ \t]*\[\^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\])+(?:[ \t]*)/;
const OPEN_TO_CLOSE: Record<string, string> = {
  '(': ')',
  '（': '）',
  '[': ']',
  '【': '】',
  '《': '》',
  '「': '」',
  '『': '』',
  '“': '”',
  '‘': '’',
};
const CLOSE_CHARS = new Set(Object.values(OPEN_TO_CLOSE));

export function reflowReportParagraphs(document: ReportDocument): ReportParagraphReflowResult {
  const cloned = cloneDocument(document);
  const content: ReportNode[] = [];
  let changedParagraphs = 0;
  let addedParagraphs = 0;
  let inCalculationAppendix = false;

  for (const node of cloned.content) {
    if (node.type === 'heading' && /计算依据/.test(textContent(node))) {
      inCalculationAppendix = true;
      content.push(node);
      continue;
    }
    if (inCalculationAppendix || node.type !== 'paragraph') {
      content.push(node);
      continue;
    }
    const split = splitParagraph(node);
    if (split.length <= 1) {
      content.push(node);
      continue;
    }
    changedParagraphs += 1;
    addedParagraphs += split.length - 1;
    content.push(...split);
  }

  return { document: { ...cloned, content }, changedParagraphs, addedParagraphs };
}

function splitParagraph(paragraph: ReportNode): ReportNode[] {
  const fragments = flattenTextFragments(paragraph);
  if (!fragments) return [paragraph];
  const fullText = fragments.map((fragment) => fragment.text).join('');
  if (!fullText.includes('\n') && fullText.length <= LONG_PARAGRAPH_THRESHOLD) return [paragraph];

  const cuts = safeCutPoints(fullText);
  if (cuts.length === 0) return [paragraph];

  const segments: Array<{ start: number; end: number }> = [];
  let start = 0;
  for (const cut of cuts) {
    if (cut.end > start && fullText.slice(start, cut.end).trim()) segments.push({ start, end: cut.end });
    start = cut.nextStart;
  }
  if (start < fullText.length && fullText.slice(start).trim()) segments.push({ start, end: fullText.length });
  if (segments.length <= 1) return [paragraph];

  return segments.map((segment) => ({
    ...paragraph,
    content: sliceFragments(fragments, segment.start, segment.end),
  }));
}

function flattenTextFragments(paragraph: ReportNode): Array<{ start: number; end: number; text: string; node: ReportNode }> | null {
  const fragments: Array<{ start: number; end: number; text: string; node: ReportNode }> = [];
  let offset = 0;
  for (const child of paragraph.content ?? []) {
    if (child.type !== 'text') return null;
    if ((child.marks ?? []).some(isProtectedMark)) return null;
    const text = child.text ?? '';
    fragments.push({ start: offset, end: offset + text.length, text, node: child });
    offset += text.length;
  }
  return fragments.length > 0 ? fragments : null;
}

function isProtectedMark(mark: ReportMark): boolean {
  return mark.type === 'code' || mark.type === 'link';
}

function safeCutPoints(text: string): Array<{ end: number; nextStart: number }> {
  const cuts: Array<{ end: number; nextStart: number }> = [];
  const stack: string[] = [];
  let inAsciiDoubleQuote = false;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (char === '"') {
      inAsciiDoubleQuote = !inAsciiDoubleQuote;
      continue;
    }
    if (!inAsciiDoubleQuote && OPEN_TO_CLOSE[char]) stack.push(OPEN_TO_CLOSE[char]);

    if (char === '\n') {
      if (stack.length === 0 && !inAsciiDoubleQuote) cuts.push({ end: index, nextStart: index + 1 });
    } else if (SENTENCE_BOUNDARIES.has(char) && stack.length === 0 && !inAsciiDoubleQuote) {
      const end = extendPastTrailingNoteRefs(text, index + 1);
      cuts.push({ end, nextStart: end });
    }

    if (!inAsciiDoubleQuote && CLOSE_CHARS.has(char) && stack[stack.length - 1] === char) stack.pop();
  }
  return cuts;
}

function extendPastTrailingNoteRefs(text: string, start: number): number {
  const match = text.slice(start).match(NOTE_REF_AFTER_BOUNDARY);
  return match ? start + match[0].length : start;
}

function sliceFragments(fragments: Array<{ start: number; end: number; text: string; node: ReportNode }>, start: number, end: number): ReportNode[] {
  const nodes: ReportNode[] = [];
  for (const fragment of fragments) {
    const sliceStart = Math.max(start, fragment.start);
    const sliceEnd = Math.min(end, fragment.end);
    if (sliceEnd <= sliceStart) continue;
    nodes.push({
      ...fragment.node,
      text: fragment.text.slice(sliceStart - fragment.start, sliceEnd - fragment.start),
    });
  }
  return mergeAdjacentText(nodes);
}

function mergeAdjacentText(nodes: ReportNode[]): ReportNode[] {
  const merged: ReportNode[] = [];
  for (const node of nodes) {
    const last = merged[merged.length - 1];
    if (last?.type === 'text' && node.type === 'text' && sameAttrs(last.attrs, node.attrs) && sameMarks(last.marks, node.marks)) {
      last.text = `${last.text ?? ''}${node.text ?? ''}`;
    } else {
      merged.push(node);
    }
  }
  return merged;
}

function textContent(node: ReportNode): string {
  if (node.type === 'text') return node.text ?? '';
  return (node.content ?? []).map(textContent).join('');
}

function sameMarks(a?: ReportMark[], b?: ReportMark[]): boolean {
  return JSON.stringify(a ?? []) === JSON.stringify(b ?? []);
}

function sameAttrs(a?: Record<string, unknown>, b?: Record<string, unknown>): boolean {
  return JSON.stringify(a ?? {}) === JSON.stringify(b ?? {});
}

function cloneDocument(document: ReportDocument): ReportDocument {
  return JSON.parse(JSON.stringify(document)) as ReportDocument;
}
