import { describe, expect, it } from 'vitest';

import { diffCounts, lineDiff } from '../src/lib/textDiff.js';

describe('lineDiff', () => {
  it('keeps the common lines and marks what was taken out and put in', () => {
    const lines = lineDiff('标题\n\n毛利率 31%\n费用率下降', '标题\n\n毛利率 32%\n费用率下降\n新增一段')!;
    expect(lines.map((line) => `${line.kind}:${line.text}`)).toEqual([
      'same:标题', 'same:', 'removed:毛利率 31%', 'added:毛利率 32%', 'same:费用率下降', 'added:新增一段',
    ]);
    expect(diffCounts(lines)).toEqual({ added: 2, removed: 1 });
  });

  it('leaves blank lines out of the counts and answers null past the limit', () => {
    expect(diffCounts(lineDiff('a', 'a\n\n')!)).toEqual({ added: 0, removed: 0 });
    expect(lineDiff('a\nb\nc', 'a', 2)).toBeNull();
  });
});
