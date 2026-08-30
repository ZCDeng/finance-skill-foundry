import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import { COLOURED, MARKS, markOf, marksOf } from '../src/components/marks.js';

const TAGS = readFileSync(fileURLToPath(new URL('../../foundry/tags.py', import.meta.url)), 'utf8');

describe('the claim vocabulary', () => {
  it('is the same five strings the store writes', () => {
    // The tag on a brief, the tag in `followup.jsonl` and the chip on screen are
    // meant to be the same characters, so an operator can match what they see to
    // what was written down. Two copies of a vocabulary drift; this is what
    // stops them.
    const declared = new Map<string, string>();
    for (const line of TAGS.split('\n')) {
      const match = /^([A-Z_]+) = "(.+)"$/.exec(line.trim());
      if (match) declared.set(match[1], match[2]);
    }
    expect(declared.size).toBe(5);
    expect(new Set(declared.values())).toEqual(new Set(Object.values(MARKS)));
    expect(MARKS.claimed).toBe(declared.get('CLAIMED'));
    expect(MARKS.recomputed).toBe(declared.get('RECOMPUTED'));
    expect(MARKS.agreed).toBe(declared.get('AGREED'));
    expect(MARKS.outside).toBe(declared.get('OUTSIDE'));
    expect(MARKS.absent).toBe(declared.get('NOT_IN_WINDOW'));
  });

  it('colours the two marks that are not about arithmetic', () => {
    // Five colours would out-shout the numbers they sit beside. The three that
    // say where a figure came from stay ink and differ by their own label.
    expect([...COLOURED].sort()).toEqual(['absent', 'outside']);
  });
});

describe('reading a tag', () => {
  it('finds both marks in a follow-up tag, always in the same order', () => {
    // `稿外追问 / 我重算` carries two, and both matter: one says the answer is off
    // the brief, the other says the number was computed rather than read.
    //
    // The order is `marks.ts`'s, not the sentence's. Both spellings of the same
    // claim have to draw identically, or a row of chips reads as a difference
    // that punctuation invented.
    expect(marksOf('稿外追问 / 我重算')).toEqual(['recomputed', 'outside']);
    expect(marksOf('我重算 / 稿外追问')).toEqual(['recomputed', 'outside']);
  });

  it('finds nothing in prose', () => {
    expect(markOf('本期收入合计')).toBeNull();
    expect(marksOf('本期收入合计')).toEqual([]);
  });

  it('reads a brief fact tag', () => {
    expect(markOf('两者一致')).toBe('agreed');
    expect(marksOf('not-in-this-window')).toEqual(['absent']);
  });
});
