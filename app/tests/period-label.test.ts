import { describe, expect, it } from 'vitest';
import { formatPeriod } from '../src/lib/period.js';

describe('formatPeriod', () => {
  it.each([
    ['2026-08', '2026 年 8 月'],
    ['2026-01', '2026 年 1 月'],
    ['2026', '2026 年'],
    [2026, '2026 年'],
    ['2026-01:2026-08', '2026 年 1–8 月'],
    ['2026-08:2026-08', '2026 年 8 月'],
    ['2025-11:2026-02', '2025 年 11 月–2026 年 2 月'],
  ])('writes %j as %j', (value, expected) => {
    expect(formatPeriod(value)).toBe(expected);
  });

  it.each(['2026-08:2026-01', '2026-13', '2026-00', '2026-01:2026-13', 'YTD', '1_8月', '2026-08-31', '2026 YTD', '2026-8', '2608', '0000', '0000-08', '2026-01:3026-02'])(
    'leaves %j as stored', (value) => {
      expect(formatPeriod(value)).toBe(value);
    });

  it('leaves a number that is not a year as stored', () => {
    expect(formatPeriod(2608)).toBe('2608');
  });

  it('returns nothing for a missing period, leaving the placeholder to the caller', () => {
    expect(formatPeriod(null)).toBe('');
    expect(formatPeriod(undefined)).toBe('');
    expect(formatPeriod('')).toBe('');
  });

  it('uses an en dash between months, not a hyphen', () => {
    expect(formatPeriod('2026-01:2026-08')).toContain('–');
    expect(formatPeriod('2026-01:2026-08')).not.toContain('-');
  });
});
