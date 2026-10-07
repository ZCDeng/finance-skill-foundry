// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Table } from '../src/views/analysis/presentation.js';

const columns = [{ name: '指标', type: 'VARCHAR' }, { name: '数值', type: 'DECIMAL' }];

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('result Table', () => {
  it('groups rows stably, pages them by data rows, and marks a group carried onto the next page', () => {
    // 105 rows of two organizations, interleaved: 集团 holds 53, 华东 52.
    const rows = Array.from({ length: 105 }, (_, index) => ({ 组织: index % 2 ? '华东' : '集团', 指标: `m${index}`, 数值: String(index) }));
    render(<Table columns={columns} rows={rows} caption="其他结果" groupBy="组织" groupFallback="未声明组织" />);
    const region = screen.getByRole('region', { name: '其他结果' });
    expect(within(region).getAllByRole('rowheader').map((header) => header.textContent)).toEqual(['集团', '华东']);
    const first = region.querySelectorAll('tbody');
    expect(Array.from(first[0].querySelectorAll('td:first-child')).slice(0, 3).map((cell) => cell.textContent)).toEqual(['m0', 'm2', 'm4']);
    expect(region.querySelectorAll('tbody td:first-child')).toHaveLength(100);
    expect(within(region).getByText('第 1 / 2 页 · 共 105 行')).toBeTruthy();
    fireEvent.click(within(region).getByRole('button', { name: '下一页' }));
    expect(within(region).getAllByRole('rowheader').map((header) => header.textContent)).toEqual(['华东（续）']);
    expect(region.querySelectorAll('tbody td:first-child')).toHaveLength(5);
    expect(within(region).getByText('第 2 / 2 页 · 共 105 行')).toBeTruthy();
  });

  it('heads each group with a rowgroup header spanning every column', () => {
    render(<Table columns={columns} rows={[{ 组织: '集团', 指标: 'a', 数值: '1' }, { 指标: 'b', 数值: '2' }]} caption="其他结果" groupBy="组织" groupFallback="未声明组织" />);
    const headers = screen.getAllByRole('rowheader');
    expect(headers.map((header) => header.textContent)).toEqual(['集团', '未声明组织']);
    for (const header of headers) {
      expect(header.getAttribute('scope')).toBe('rowgroup');
      expect(header.getAttribute('colspan')).toBe(String(columns.length));
    }
    expect(screen.getAllByRole('columnheader').map((header) => header.textContent)).toEqual(['指标', '数值']);
  });

  it('keeps one tbody and no row headers without groupBy', () => {
    const { container } = render(<Table columns={columns} rows={[{ 指标: 'a', 数值: '1' }, { 指标: 'b', 数值: '2' }]} caption="业务结果" />);
    expect(container.querySelectorAll('tbody')).toHaveLength(1);
    expect(screen.queryAllByRole('rowheader')).toHaveLength(0);
  });

  it('hands a column renderer the cell value and its whole row', () => {
    const renderCell = vi.fn((value: unknown, row: Record<string, unknown>) => <b>{`${String(value)}:${String(row.__key)}`}</b>);
    render(<Table columns={[{ name: '指标', type: 'VARCHAR', render: renderCell }]} rows={[{ 指标: '收入', __key: 'revenue' }]} caption="业务结果" />);
    expect(screen.getByRole('cell', { name: '收入:revenue' }).querySelector('b')).toBeTruthy();
    expect(renderCell).toHaveBeenCalledWith('收入', { 指标: '收入', __key: 'revenue' });
    // A field no column names is never a cell.
    expect(screen.queryByRole('cell', { name: 'revenue' })).toBeNull();
  });

  it.each([[800, true], [400, false]])('says more columns sit to the right only when the table is wider than its area (%i)', (scrollWidth, overflowing) => {
    vi.spyOn(HTMLElement.prototype, 'scrollWidth', 'get').mockReturnValue(scrollWidth);
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(400);
    render(<Table columns={columns} rows={[{ 指标: 'a', 数值: '1' }]} caption="业务结果" scrollHint />);
    const region = screen.getByRole('region', { name: '业务结果' });
    const hint = screen.queryByText('右侧还有列，可横向滚动查看');
    expect(hint !== null).toBe(overflowing);
    if (hint) expect(region.getAttribute('aria-describedby')).toBe(hint.id);
    else expect(region.hasAttribute('aria-describedby')).toBe(false);
  });

  it('drops the hint once the table is scrolled to its right end', () => {
    vi.spyOn(HTMLElement.prototype, 'scrollWidth', 'get').mockReturnValue(800);
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(400);
    render(<Table columns={columns} rows={[{ 指标: 'a', 数值: '1' }]} caption="业务结果" scrollHint />);
    const region = screen.getByRole('region', { name: '业务结果' });
    expect(screen.getByText('右侧还有列，可横向滚动查看')).toBeTruthy();
    region.scrollLeft = 400;
    fireEvent.scroll(region);
    expect(screen.queryByText('右侧还有列，可横向滚动查看')).toBeNull();
    expect(region.hasAttribute('aria-describedby')).toBe(false);
  });

  it('never measures without scrollHint', () => {
    vi.spyOn(HTMLElement.prototype, 'scrollWidth', 'get').mockReturnValue(800);
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(400);
    render(<Table columns={columns} rows={[{ 指标: 'a', 数值: '1' }]} caption="业务结果" />);
    expect(screen.queryByText('右侧还有列，可横向滚动查看')).toBeNull();
  });
});
