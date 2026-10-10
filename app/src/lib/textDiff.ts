/**
 * Two versions of a document, line by line: what stayed, what was taken out, what was put in.
 *
 * A longest-common-subsequence over lines, which is what a reader means by "what changed" in a
 * report: a paragraph is a line in the stored Markdown. Blank lines are kept so the result reads
 * as the document does. Past `limit` lines on either side the table would be too large to hold,
 * so the answer is a plain "too long to compare here" (`null`) rather than a slow page.
 */
export type DiffLine = { kind: 'same' | 'removed' | 'added'; text: string };

export function lineDiff(before: string, after: string, limit = 2000): DiffLine[] | null {
  const a = before.split('\n');
  const b = after.split('\n');
  if (a.length > limit || b.length > limit) return null;
  const rows = a.length + 1;
  const cols = b.length + 1;
  // lengths[i * cols + j]: the longest common run of a[i..] and b[j..].
  const lengths = new Uint32Array(rows * cols);
  for (let i = a.length - 1; i >= 0; i -= 1) {
    for (let j = b.length - 1; j >= 0; j -= 1) {
      lengths[i * cols + j] = a[i] === b[j]
        ? lengths[(i + 1) * cols + j + 1] + 1
        : Math.max(lengths[(i + 1) * cols + j], lengths[i * cols + j + 1]);
    }
  }
  const out: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) { out.push({ kind: 'same', text: a[i] }); i += 1; j += 1; }
    else if (lengths[(i + 1) * cols + j] >= lengths[i * cols + j + 1]) { out.push({ kind: 'removed', text: a[i] }); i += 1; }
    else { out.push({ kind: 'added', text: b[j] }); j += 1; }
  }
  while (i < a.length) { out.push({ kind: 'removed', text: a[i] }); i += 1; }
  while (j < b.length) { out.push({ kind: 'added', text: b[j] }); j += 1; }
  return out;
}

/** How many lines each side changed, blank lines left out: they are layout, not content. */
export function diffCounts(lines: DiffLine[]): { added: number; removed: number } {
  let added = 0;
  let removed = 0;
  for (const line of lines) {
    if (!line.text.trim()) continue;
    if (line.kind === 'added') added += 1;
    else if (line.kind === 'removed') removed += 1;
  }
  return { added, removed };
}
