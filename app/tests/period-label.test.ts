import { describe, expect, it } from 'vitest';
import { formatPeriod, formatPeriods } from '../src/lib/period.js';
import { contextOptions, scopeSummary } from '../src/views/analysis/shared.js';
import type { FinanceContextState } from '../src/bridge.js';

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

describe('formatPeriods', () => {
  it('writes each period in words but keeps two that would read alike as stored', () => {
    expect(formatPeriods(['2026-07', '2026-01:2026-08'])).toEqual(['2026 年 7 月', '2026 年 1–8 月']);
    expect(formatPeriods(['2026-08', '2026-08:2026-08', '2026-07'])).toEqual(['2026-08', '2026-08:2026-08', '2026 年 7 月']);
  });
});

describe('scope lines', () => {
  it('words the period in a scope summary and leaves one that is not a period as stored', () => {
    expect(scopeSummary({ organization: '华东', period: '2026-09', unit: '万元' })).toBe('组织 华东 · 期间 2026 年 9 月 · 单位 万元');
    expect(scopeSummary({ period: 'YTD' })).toBe('期间 YTD');
  });

  it('shows a saved scope in words and still finds it by the period as typed', () => {
    const finance = { contexts: [{ id: 'c', name: '华东口径', scopes: { actual: { period: '2026-08', unit: '万元' } } }] } as unknown as FinanceContextState;
    const [option] = contextOptions(finance);
    expect(option.meta).toContain('期间 2026 年 8 月');
    expect(option.meta).not.toContain('2026-08');
    expect(option.keywords).toBe('2026-08');
  });
});
