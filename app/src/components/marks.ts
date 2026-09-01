/**
 * The claim vocabulary, in the renderer's own words.
 *
 * These six strings are `foundry/tags.py`, and a test reads that file to keep
 * the two in step. They are not translated and not abbreviated: the tag on a
 * brief, the tag in `followup.jsonl` and the chip on this screen are meant to be
 * the same characters, so an operator can match what they see to what was
 * written down.
 */
export const MARKS = {
  claimed: '报表声称',
  recomputed: '我重算',
  agreed: '两者一致',
  outside: '稿外追问',
  absent: 'not-in-this-window',
  external: '外部引用',
} as const;

export type MarkName = keyof typeof MARKS;

/**
 * Which marks carry colour.
 *
 * The first three say where a number came from within this window and differ by
 * their own label. These three say something else -- that an answer is off the
 * brief, that the window could not answer at all, or that the figure is not this
 * window's arithmetic -- and those are the ones an operator scans for.
 *
 * Three treatments, not three colours competing: warm and filled for off-brief,
 * cool and outlined for cited, grey and struck for refused.
 */
export const COLOURED: readonly MarkName[] = ['outside', 'absent', 'external'];

/** The mark a tag string names, or nothing when it is prose. */
export function markOf(tag: string): MarkName | null {
  for (const [name, text] of Object.entries(MARKS) as [MarkName, string][]) {
    if (tag.includes(text)) return name;
  }
  return null;
}

/**
 * Every mark one tag carries, in declaration order rather than tag order.
 *
 * A follow-up is tagged `稿外追问 / 我重算`: two marks in one string, and both
 * matter -- one says the answer is off the brief, the other says the number was
 * computed rather than read. Rendering only the first would drop where the
 * figure came from.
 *
 * Declaration order, not the order they appear in the string, so the same pair
 * always draws the same way. `我重算 / 稿外追问` and `稿外追问 / 我重算` are the
 * same claim, and a row of chips that reordered itself by how a sentence was
 * punctuated would read as a difference that is not there.
 */
export function marksOf(tag: string): MarkName[] {
  return (Object.entries(MARKS) as [MarkName, string][])
    .filter(([, text]) => tag.includes(text))
    .map(([name]) => name);
}
