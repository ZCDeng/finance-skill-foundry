import { describe, expect, it } from 'vitest';

/**
 * The gallery's ordering, over the module's own comparator.
 *
 * Extracted rather than exercised through `deliverableGallery`, which spawns the
 * CLI: what is worth pinning here is the tie rule, and a tie needs no store.
 */
function newestFirst<T extends { at: string; seq: number }>(rows: T[]): T[] {
  return [...rows].sort((a, b) => {
    if (a.at !== b.at) return a.at < b.at ? 1 : -1;
    return b.seq - a.seq;
  });
}

describe('the deliverable gallery', () => {
  it('puts the newer second first', () => {
    const rows = [
      { seq: 1, at: '2026-08-30T10:00:00Z' },
      { seq: 2, at: '2026-08-30T11:00:00Z' },
    ];
    expect(newestFirst(rows).map((r) => r.seq)).toEqual([2, 1]);
  });

  it('breaks a same-second tie on seq, not on input order', () => {
    // `emit-brief` files the brief and the workpaper in one instant, and the
    // timestamps are second-resolution, so this is the normal case. Sorting on
    // the timestamp alone leaves those two ascending inside a descending list.
    const rows = [
      { seq: 1, at: '2026-08-30T10:00:00Z' },
      { seq: 2, at: '2026-08-30T10:00:00Z' },
      { seq: 3, at: '2026-08-30T10:00:00Z' },
    ];
    expect(newestFirst(rows).map((r) => r.seq)).toEqual([3, 2, 1]);
  });

  it('keeps the comparator in step with the one that ships', async () => {
    // The copy above would drift the moment `reads.ts` changed, so this reads
    // the shipped source and fails when the two stop agreeing.
    const { readFileSync } = await import('node:fs');
    const { fileURLToPath } = await import('node:url');
    const source = readFileSync(fileURLToPath(new URL('../electron/reads.ts', import.meta.url)), 'utf8');
    expect(source).toContain('return b.row.seq - a.row.seq;');
    expect(source).toContain("if (a.row.at !== b.row.at) return a.row.at < b.row.at ? 1 : -1;");
  });
});
