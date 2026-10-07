// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { Figure } from '../src/components/Figure.js';
import { accountingFigure, decimalToFixed, formatAmount, hasParenthesizedNegative, isFigureText } from '../src/lib/figures.js';
import { formatRawFigure } from '../src/views/analysis/businessResults.js';
import { Table } from '../src/views/analysis/presentation.js';

afterEach(cleanup);

describe('how a figure is written (DESIGN.md 财务数字)', () => {
  it('groups thousands at a fixed number of places, rounding the exact decimal half away from zero', () => {
    expect(decimalToFixed('1250000', 2)).toBe('1,250,000.00');
    expect(decimalToFixed('-18843.0552', 2)).toBe('-18,843.06');
    expect(decimalToFixed('0.945', 2, 100)).toBe('94.50');
    expect(decimalToFixed('-0.004', 2)).toBe('0.00');
    expect(formatAmount('8072.5449')).toBe('8,072.54');
    expect(formatAmount(undefined)).toBe('—');
    expect(formatAmount('待核对')).toBe('待核对');
  });

  it('writes a bare negative in accounting parentheses and keeps the minus on a figure with a unit word', () => {
    expect(accountingFigure('-18,843.06')).toEqual({ text: '(18,843.06)', negative: true, bare: false });
    expect(accountingFigure('-3.30%')).toEqual({ text: '(3.30%)', negative: true, bare: false });
    expect(accountingFigure('-¥1,000.00')).toEqual({ text: '(¥1,000.00)', negative: true, bare: false });
    expect(accountingFigure('-0.65 个百分点')).toEqual({ text: '-0.65 个百分点', negative: true, bare: false });
    expect(accountingFigure('-1,234.00 万元')).toEqual({ text: '-1,234.00 万元', negative: true, bare: false });
    expect(accountingFigure('(1,000.00)')).toEqual({ text: '(1,000.00)', negative: true, bare: false });
    expect(accountingFigure('344,487.06')).toEqual({ text: '344,487.06', negative: false, bare: true });
    expect(accountingFigure('94.53%')).toEqual({ text: '94.53%', negative: false, bare: true });
    expect(accountingFigure('0.945（未标单位）')).toMatchObject({ negative: false, bare: false });
  });

  it('leaves words, dashes and periods alone', () => {
    for (const text of ['—', '收入', '2026 年 1–8 月', 'A12', '1.2.3']) {
      expect(accountingFigure(text)).toEqual({ text, negative: false, bare: false });
    }
    expect(isFigureText('325,644.00 万元（估算）')).toBe(true);
    expect(isFigureText('12.5 倍')).toBe(true);
    expect(hasParenthesizedNegative(['1.00', '-2.00'])).toBe(true);
    expect(hasParenthesizedNegative(['1.00', '-2.00 万元'])).toBe(false);
  });

  it('draws a negative in the negative red and hangs a bare figure only when asked', () => {
    const { container } = render(<><Figure text="-6.85%" /><Figure text="61.68%" hang /><Figure text="61.68%" /></>);
    const [negative, hung, plain] = [...container.querySelectorAll('span')];
    expect(negative.className).toBe('fnd-figure fnd-figure--negative');
    expect(negative.textContent).toBe('(6.85%)');
    expect(hung.className).toBe('fnd-figure fnd-figure--hang');
    expect(plain.className).toBe('fnd-figure');
  });
});

describe('raw engine values in the 原样 tables (decision 6B)', () => {
  it('formats amounts at two places and ratios by their column, as the business table does', () => {
    expect(formatRawFigure('1234.5', 'actual')).toBe('1,234.50');
    expect(formatRawFigure(1234.5, '金额')).toBe('1,234.50');
    expect(formatRawFigure('1234', 'actual')).toBe('1,234.00');
    expect(formatRawFigure('0.945', 'attainment_rate')).toBe('94.50%');
    expect(formatRawFigure('-0.006532', 'ratio_delta')).toBe('-0.65 个百分点');
  });

  it('groups any other number without rounding a place away, padded to its column', () => {
    expect(formatRawFigure('0.0035', 'weight')).toBe('0.0035');
    expect(formatRawFigure('12345', 'count')).toBe('12,345');
    expect(formatRawFigure('1250000', 'value', 1)).toBe('1,250,000.0');
    // Padding stops at four places; a longer value in the column keeps all of its own.
    expect(formatRawFigure('1', 'value', 5)).toBe('1.0000');
    expect(formatRawFigure('0.12345', 'value', 5)).toBe('0.12345');
    expect(formatRawFigure('0.123456789012345678901234567890', 'value', 30)).toBe('0.123456789012345678901234567890');
  });

  it('keeps periods, codes, positions, exact companions and non-decimals as written', () => {
    expect(formatRawFigure('202608', 'period')).toBeNull();
    expect(formatRawFigure('1001', 'account_code')).toBeNull();
    expect(formatRawFigure('6001', '科目编码')).toBeNull();
    expect(formatRawFigure('12', 'row_number')).toBeNull();
    expect(formatRawFigure('0.9389990001', 'attainment_rate_exact')).toBeNull();
    expect(formatRawFigure('1e-7', 'actual')).toBeNull();
    expect(formatRawFigure(true, 'actual')).toBeNull();
    expect(formatRawFigure('—', 'actual')).toBeNull();
  });
});

describe('a result table', () => {
  it('right-aligns figure columns by content, parenthesizes negatives and keeps the raw value at hand', () => {
    render(<Table caption="计算结果" columns={[{ name: 'item', type: 'VARCHAR' }, { name: 'value', type: 'VARCHAR' }, { name: 'rate', type: 'VARCHAR' }]}
      rows={[
        { item: '物业服务', value: '1250000', rate: '12.50%' },
        { item: '停车收入', value: '-6487.60', rate: '-3.30%' },
        { item: '小计', value: '1243512.40', rate: '—' },
        { item: '合计', value: '1243512.40', rate: '—' },
      ]} />);
    const table = screen.getByRole('table', { name: '计算结果' });
    const [head, ...rows] = within(table).getAllByRole('row');
    expect([...head.querySelectorAll('th')].map((cell) => cell.className)).toEqual(['', 'analysis-number', 'analysis-number']);
    const negative = within(rows[1]).getByRole('cell', { name: '(6,487.60)' });
    expect(negative.className).toBe('analysis-number');
    expect(negative.title).toBe('-6487.60');
    expect(negative.querySelector('.fnd-figure--negative')).toBeTruthy();
    expect(within(rows[1]).getByRole('cell', { name: '(3.30%)' })).toBeTruthy();
    // Beside a parenthesized negative, a bare figure ends one place in.
    expect(within(rows[0]).getByRole('cell', { name: '1,250,000.00' }).querySelector('.fnd-figure--hang')).toBeTruthy();
    expect(within(rows[0]).getByRole('cell', { name: '物业服务' }).className).toBe('');
    expect(rows.map((row) => row.className)).toEqual(['', '', 'analysis-row--subtotal', 'analysis-row--total']);
  });

  it('leaves a text column that only sometimes holds digits as text, left-aligned', () => {
    render(<Table caption="明细" columns={[{ name: 'note', type: 'VARCHAR' }]} rows={[{ note: '1200' }, { note: '待补' }]} />);
    const cell = screen.getByRole('cell', { name: '1200' });
    expect(cell.className).toBe('');
    expect(cell.title).toBe('');
  });
});
