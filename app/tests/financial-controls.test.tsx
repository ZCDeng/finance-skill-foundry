// @vitest-environment jsdom
import { useState } from 'react';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AccountingPeriodInput, DateInput, DecimalInput, MultiSelect, PeriodRangeInput, SearchableSelect } from '../src/components/FinancialControls.js';
import { contextOptions } from '../src/views/analysis/shared.js';
import type { FinanceContextState } from '../src/bridge.js';

afterEach(() => cleanup());

describe('financial web controls', () => {
  it('finds a saved scope by its period as typed, as worded, or without the spaces', () => {
    const finance = { contexts: [
      { id: 'c-aug', name: '华东口径', scopes: { actual: { period: '2026-08', unit: '万元' } } },
      { id: 'c-ytd', name: '集团口径', scopes: { actual: { period: '2026-01:2026-08', unit: '万元' } } },
    ] } as unknown as FinanceContextState;
    render(<SearchableSelect label="已保存的范围" value="" onChange={vi.fn()} options={contextOptions(finance)} placeholder="搜索范围名称或期间" />);
    fireEvent.click(screen.getByRole('button', { name: '已保存的范围' }));
    const search = screen.getByLabelText('已保存的范围搜索');
    const shown = () => screen.queryAllByRole('option').map((option) => option.textContent ?? '');
    fireEvent.change(search, { target: { value: '2026-08' } });
    expect(shown().some((text) => text.includes('华东口径'))).toBe(true);
    expect(shown().some((text) => text.includes('集团口径'))).toBe(true);
    expect(shown().join('')).not.toContain('2026-08');
    fireEvent.change(search, { target: { value: '2026年8月' } });
    expect(shown().map((text) => text.includes('华东口径'))).toEqual([true]);
    fireEvent.change(search, { target: { value: '1-8月' } });
    expect(shown().map((text) => text.includes('集团口径'))).toEqual([true]);
  });

  it('keeps accounting periods as YYYY-MM and supports base-period shortcuts', () => {
    const onChange = vi.fn();
    render(<AccountingPeriodInput label="对比期间" value="" onChange={onChange} shortcutBaseValue="2026-08" shortcutBaseLabel="实际期间" />);

    expect((screen.getByLabelText('对比期间') as HTMLInputElement).closest('.fnd-period-field__input')).toBeTruthy();
    expect(screen.getByRole('button', { name: '对比期间设为实际期间上期' }).closest('.fnd-period-shortcuts')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: '对比期间设为实际期间上期' }));
    expect(onChange).toHaveBeenLastCalledWith('2026-07');

    fireEvent.click(screen.getByRole('button', { name: '对比期间设为实际期间上年同期' }));
    expect(onChange).toHaveBeenLastCalledWith('2025-08');

    fireEvent.change(screen.getByLabelText('对比期间'), { target: { value: '2026-13' } });
    expect(onChange).not.toHaveBeenCalledWith('2026-13');
    expect(screen.getByText('请输入 YYYY-MM 会计期间。')).toBeTruthy();
  });

  it('marks the matching period shortcut as pressed', () => {
    const now = `${new Date().getFullYear()}-${String(new Date().getMonth() + 1).padStart(2, '0')}`;
    render(<AccountingPeriodInput label="期间" value={now} onChange={() => {}} />);
    expect(screen.getByRole('button', { name: '期间设为本期' }).getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByRole('button', { name: '期间设为上期' }).getAttribute('aria-pressed')).toBe('false');
  });

  it('draws the period shortcuts as the shared chip, pressed only through aria-pressed', () => {
    const now = `${new Date().getFullYear()}-${String(new Date().getMonth() + 1).padStart(2, '0')}`;
    render(<AccountingPeriodInput label="期间" value={now} onChange={() => {}} />);
    for (const name of ['期间设为上期', '期间设为上年同期', '期间设为本期']) {
      const chip = screen.getByRole('button', { name });
      expect(chip.getAttribute('data-slot')).toBe('button');
      expect(chip.getAttribute('data-variant')).toBe('outline');
      expect(chip.getAttribute('data-size')).toBe('chip');
      expect(chip.classList.contains('fnd-control-icon')).toBe(false);
    }
    // The pressed and unpressed chips carry the same classes; only the attribute differs.
    expect(screen.getByRole('button', { name: '期间设为本期' }).className).toBe(screen.getByRole('button', { name: '期间设为上期' }).className);
  });

  it('validates calendar dates without converting them to timestamps', () => {
    const onChange = vi.fn();
    render(<DateInput label="截止日期" value="2026-08-31" onChange={onChange} />);

    fireEvent.change(screen.getByLabelText('截止日期'), { target: { value: '2026-02-29' } });
    expect(onChange).not.toHaveBeenCalledWith('2026-02-29');
    expect(screen.getByText('请输入有效日期 YYYY-MM-DD。')).toBeTruthy();

    fireEvent.change(screen.getByLabelText('截止日期'), { target: { value: '2028-02-29' } });
    expect(onChange).toHaveBeenLastCalledWith('2028-02-29');
  });

  it('keeps decimal values as precise strings while formatting only the display text', () => {
    const onChange = vi.fn();
    function ControlledDecimal() {
      const [value, setValue] = useState('900719925474099.99');
      return <DecimalInput label="期初现金" value={value} onChange={(next) => { onChange(next); setValue(next); }} unit="元" />;
    }
    render(<ControlledDecimal />);
    const input = screen.getByLabelText('期初现金') as HTMLInputElement;

    expect(input.value).toBe('900,719,925,474,099.99');
    fireEvent.focus(input);
    expect(input.value).toBe('900719925474099.99');
    fireEvent.change(input, { target: { value: '900,719,925,474,099.98' } });
    expect(onChange).toHaveBeenLastCalledWith('900719925474099.98');
    fireEvent.blur(input);
    expect(input.value).toBe('900,719,925,474,099.98');
  });

  it('opens Chinese month and date pickers without losing string semantics', async () => {
    const onPeriod = vi.fn();
    const onDate = vi.fn();
    render(<><AccountingPeriodInput label="对比期间" value="2026-08" onChange={onPeriod} />
      <DateInput label="账龄日期" value="2026-08-31" onChange={onDate} /></>);

    fireEvent.click(screen.getByRole('button', { name: '对比期间打开年月选择' }));
    fireEvent.click(screen.getByRole('button', { name: '7月' }));
    expect(onPeriod).toHaveBeenLastCalledWith('2026-07');
    await waitFor(() => expect(document.activeElement).toBe(screen.getByLabelText('对比期间')));

    fireEvent.click(screen.getByRole('button', { name: '账龄日期打开日期选择' }));
    const dialog = screen.getByRole('dialog', { name: '账龄日期日期选择' });
    // shadcn Calendar: focus lands on the chosen day; weeks start on Monday.
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole('button', { name: /2026年8月31日/ })));
    // The caption is a year and a month dropdown, so a date a year back is two picks.
    expect((within(dialog).getByRole('combobox', { name: '选择年份' }) as HTMLSelectElement).value).toBe('2026');
    expect((within(dialog).getByRole('combobox', { name: '选择月份' }) as HTMLSelectElement).value).toBe('7');
    expect(Array.from(dialog.querySelectorAll('th')).map((cell) => cell.textContent)).toEqual(['一', '二', '三', '四', '五', '六', '日']);
    fireEvent.click(screen.getByRole('button', { name: /2026年8月15日/ }));
    expect(onDate).toHaveBeenLastCalledWith('2026-08-15');
  });

  it('jumps a year from the caption dropdown and takes today in one press', async () => {
    const onDate = vi.fn();
    render(<DateInput label="账龄日期" value="2026-08-31" onChange={onDate} />);
    fireEvent.click(screen.getByRole('button', { name: '账龄日期打开日期选择' }));
    const dialog = screen.getByRole('dialog', { name: '账龄日期日期选择' });
    fireEvent.change(within(dialog).getByRole('combobox', { name: '选择年份' }), { target: { value: '2025' } });
    fireEvent.click(await within(dialog).findByRole('button', { name: /2025年8月15日/ }));
    expect(onDate).toHaveBeenLastCalledWith('2025-08-15');

    fireEvent.click(screen.getByRole('button', { name: '账龄日期打开日期选择' }));
    fireEvent.click(within(screen.getByRole('dialog', { name: '账龄日期日期选择' })).getByRole('button', { name: '今天' }));
    const today = new Date();
    const pad = (value: number) => String(value).padStart(2, '0');
    expect(onDate).toHaveBeenLastCalledWith(`${today.getFullYear()}-${pad(today.getMonth() + 1)}-${pad(today.getDate())}`);
  });

  it('opens on a stored date older than the default ten-year reach', () => {
    render(<DateInput label="历史日期" value="1998-03-12" onChange={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: '历史日期打开日期选择' }));
    const dialog = screen.getByRole('dialog', { name: '历史日期日期选择' });
    expect((within(dialog).getByRole('combobox', { name: '选择年份' }) as HTMLSelectElement).value).toBe('1998');
    expect(within(dialog).getByRole('button', { name: /1998年3月12日.*已选/ })).toBeTruthy();
  });

  it('validates true ranges without using them for cash cutoff semantics', () => {
    const onPeriods = vi.fn();
    render(<PeriodRangeInput label="适用期间范围" start="2026-10" end="2026-09" onChange={onPeriods} />);

    expect(screen.getByText('开始期间不能晚于结束期间。')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '适用期间范围开始设为上期' }));
    expect(onPeriods).toHaveBeenLastCalledWith({ start: '2026-09', end: '2026-09' });
  });

  it('moves picker focus with keyboard and returns focus on Escape or selection', async () => {
    const onPeriod = vi.fn();
    const onDate = vi.fn();
    render(<><AccountingPeriodInput label="键盘期间" value="2026-08" onChange={onPeriod} />
      <DateInput label="键盘日期" value="2026-08-15" onChange={onDate} /></>);

    const periodInput = screen.getByLabelText('键盘期间');
    fireEvent.click(screen.getByRole('button', { name: '键盘期间打开年月选择' }));
    const periodDialog = screen.getByRole('dialog', { name: '键盘期间年月选择' });
    await waitFor(() => expect(document.activeElement).toBe(periodDialog));
    fireEvent.keyDown(periodDialog, { key: 'ArrowRight' });
    fireEvent.keyDown(periodDialog, { key: 'Enter' });
    expect(onPeriod).toHaveBeenLastCalledWith('2026-09');
    await waitFor(() => expect(document.activeElement).toBe(periodInput));

    const dateInput = screen.getByLabelText('键盘日期');
    fireEvent.click(screen.getByRole('button', { name: '键盘日期打开日期选择' }));
    const day15 = screen.getByRole('button', { name: /2026年8月15日/ });
    await waitFor(() => expect(document.activeElement).toBe(day15));
    fireEvent.keyDown(day15, { key: 'ArrowRight' });
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole('button', { name: /2026年8月16日/ })));
    fireEvent.keyDown(document.activeElement!, { key: 'Escape' });
    expect(onDate).not.toHaveBeenCalledWith('2026-08-16');
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '键盘日期日期选择' })).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(dateInput));

    fireEvent.click(screen.getByRole('button', { name: '键盘日期打开日期选择' }));
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole('button', { name: /2026年8月15日/ })));
    fireEvent.keyDown(document.activeElement!, { key: 'ArrowRight' });
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole('button', { name: /2026年8月16日/ })));
    fireEvent.click(document.activeElement!);
    expect(onDate).toHaveBeenLastCalledWith('2026-08-16');
    await waitFor(() => expect(document.activeElement).toBe(dateInput));
  });

  it('keeps already submitted range endpoints when Escape closes field editing', () => {
    function ControlledRange() {
      const [range, setRange] = useState({ start: '2026-08', end: '2026-09' });
      return <PeriodRangeInput label="适用期间范围" start={range.start} end={range.end} onChange={setRange} />;
    }
    render(<ControlledRange />);
    const start = screen.getByLabelText('适用期间范围开始') as HTMLInputElement;
    const end = screen.getByLabelText('适用期间范围结束') as HTMLInputElement;

    fireEvent.change(start, { target: { value: '2026-07' } });
    fireEvent.change(end, { target: { value: '2026-10' } });
    fireEvent.keyDown(start, { key: 'Escape' });
    fireEvent.keyDown(end, { key: 'Escape' });

    expect(start.value).toBe('2026-07');
    expect(end.value).toBe('2026-10');
  });


  it('prioritizes direct business-label matches before explanatory meta matches', () => {
    const onChange = vi.fn();
    render(<MultiSelect label="应收状态筛选" values={[]} onChange={onChange} options={[
      { value: 'active', label: '正常应收', meta: '正常、未逾期' },
      { value: 'overdue', label: '逾期应收', meta: '逾期、账龄超期' },
      { value: 'disputed', label: '争议应收', meta: '争议、可能逾期' },
    ]} />);

    fireEvent.click(screen.getByRole('button', { name: '应收状态筛选' }));
    const search = screen.getByLabelText('应收状态筛选搜索');
    fireEvent.change(search, { target: { value: '逾期' } });
    fireEvent.keyDown(search, { key: 'Enter' });

    expect(onChange).toHaveBeenLastCalledWith(['overdue']);
  });

  it('supports multi-select filtering, clearing and IME-safe keyboard toggles', () => {
    const onChange = vi.fn();
    render(<MultiSelect label="应收状态筛选" values={['active']} onChange={onChange} options={[
      { value: 'active', label: '正常应收', meta: '正常、未逾期' },
      { value: 'disputed', label: '争议应收', meta: '争议' },
      { value: 'written_off', label: '已核销', meta: '核销' },
    ]} />);

    fireEvent.click(screen.getByRole('button', { name: '应收状态筛选' }));
    expect(screen.getAllByRole('option').map((option) => option.getAttribute('aria-checked'))).toEqual(['true', 'false', 'false']);
    const search = screen.getByLabelText('应收状态筛选搜索');
    fireEvent.change(search, { target: { value: '争议' } });
    fireEvent.compositionStart(search);
    fireEvent.keyDown(search, { key: 'Enter' });
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.compositionEnd(search);
    fireEvent.keyDown(search, { key: 'Enter' });
    expect(onChange).toHaveBeenLastCalledWith(['active', 'disputed']);
    fireEvent.click(screen.getByRole('button', { name: '清空应收状态筛选' }));
    expect(onChange).toHaveBeenLastCalledWith([]);
  });

  it('filters long finance identifiers and protects IME composition before selecting', () => {
    const onChange = vi.fn();
    render(<SearchableSelect label="实际资料" value="" onChange={onChange} options={[
      { value: 'actual-001', label: '八月实际', meta: 'actual.csv · 1,024 行' },
      { value: 'budget-001', label: '八月预算', meta: 'budget.csv · 1,024 行' },
      { value: 'actual-erp', label: '金蝶实际账套', meta: 'ledger: operating' },
    ]} />);

    fireEvent.click(screen.getByRole('button', { name: '实际资料' }));
    const search = screen.getByLabelText('实际资料搜索');
    fireEvent.change(search, { target: { value: 'actual' } });
    expect(screen.getByRole('option', { name: /八月实际/ })).toBeTruthy();
    expect(screen.queryByRole('option', { name: /八月预算/ })).toBeNull();

    fireEvent.compositionStart(search);
    fireEvent.keyDown(search, { key: 'Enter' });
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.compositionEnd(search);
    fireEvent.keyDown(search, { key: 'ArrowDown' });
    fireEvent.keyDown(search, { key: 'Enter' });
    expect(onChange).toHaveBeenLastCalledWith('actual-erp');
  });

  it('keeps compact version summaries searchable by full metadata and restores keyboard focus', async () => {
    const onChange = vi.fn();
    render(<SearchableSelect label="文稿版本" compact triggerText="09-08 22:55" value="v2" onChange={onChange} options={[
      { value: 'v1', label: '经营简报', meta: '草稿 · 2026-09-08 20:00 · old-revision' },
      { value: 'v2', label: '经营简报', meta: '草稿 · 2026-09-08 22:55 · current-revision' },
    ]} />);
    const trigger = screen.getByRole('button', { name: '文稿版本' });
    expect(trigger.textContent).toContain('文稿版本');
    expect(trigger.textContent).toContain('09-08 22:55');
    expect(trigger.textContent).not.toContain('current-revision');
    expect(trigger.title).toContain('current-revision');
    fireEvent.keyDown(trigger, { key: 'ArrowDown' });
    const search = screen.getByLabelText('文稿版本搜索');
    fireEvent.change(search, { target: { value: 'old-revision' } });
    expect(screen.getByRole('option', { name: /2026-09-08 20:00/ })).toBeTruthy();
    fireEvent.keyDown(search, { key: 'Enter' });
    expect(onChange).toHaveBeenCalledWith('v1');
    expect(trigger.getAttribute('aria-expanded')).toBe('false');
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  });

  it('links help and validation copy to the active input for assistive technology', () => {
    render(<DecimalInput label="比例" value="abc" onChange={() => undefined} help="0.1 代表 10%" />);

    const input = screen.getByLabelText('比例');
    const message = screen.getByText('请输入金额数字，空值与 0 会分开保存。');
    expect(input.getAttribute('aria-describedby')).toBe(message.id);
    expect(input.getAttribute('aria-invalid')).toBe('true');
  });

  it('distinguishes search loading, failed setup, unconfigured and no-match states', () => {
    const onChange = vi.fn();
    const { rerender } = render(<SearchableSelect label="工作表" value="" options={[]} onChange={onChange} loading />);

    fireEvent.click(screen.getByRole('button', { name: '工作表' }));
    expect(screen.getByText('正在读取选项…')).toBeTruthy();

    rerender(<SearchableSelect label="工作表" value="" options={[]} onChange={onChange} loadError="文件已移动" />);
    expect(screen.getByRole('alert').textContent).toContain('选项读取失败：文件已移动');

    rerender(<SearchableSelect label="工作表" value="" options={[]} onChange={onChange} unconfigured unconfiguredLabel="请先点击“检查结构”，读取工作表后再选择。" />);
    expect(screen.getByText('请先点击“检查结构”，读取工作表后再选择。')).toBeTruthy();

    rerender(<SearchableSelect label="工作表" value="" options={[{ value: 'Sheet1', label: 'Sheet1' }]} onChange={onChange} />);
    fireEvent.change(screen.getByLabelText('工作表搜索'), { target: { value: '不存在' } });
    expect(screen.getByText('无匹配结果')).toBeTruthy();
  });

  it('keeps stale linked selections visible without replacing them automatically', () => {
    const onSelect = vi.fn();
    const onMulti = vi.fn();
    render(<><SearchableSelect label="已保存口径" value="ctx-old" options={[{ value: 'ctx-new', label: '新口径' }]} onChange={onSelect} />
      <MultiSelect label="应收状态筛选" values={['active', 'legacy']} options={[{ value: 'active', label: '正常应收' }]} onChange={onMulti} /></>);

    expect(screen.getByText('已失效：ctx-old')).toBeTruthy();
    expect(screen.getByText('当前选择已失效：ctx-old。请清空或重新选择。')).toBeTruthy();
    expect(onSelect).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '清空已保存口径' }));
    expect(onSelect).toHaveBeenLastCalledWith('');

    expect(screen.getByText('正常应收、已失效：legacy')).toBeTruthy();
    expect(screen.getByText('部分已选项已失效：legacy。请移除后继续。')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '移除应收状态筛选失效项' }));
    expect(onMulti).toHaveBeenLastCalledWith(['active']);
  });

  it('bounds long lists while search still reaches items after the first eighty', () => {
    const onChange = vi.fn();
    const options = Array.from({ length: 90 }, (_, index) => {
      const id = String(index + 1).padStart(3, '0');
      return { value: `customer-${id}`, label: `客户${id}`, meta: `编码 ${id}` };
    });
    render(<SearchableSelect label="客户" value="" options={options} onChange={onChange} />);

    fireEvent.click(screen.getByRole('button', { name: '客户' }));
    expect(screen.getByText('已显示前 80 项，共 90 项；继续输入名称或编码可访问其余项。')).toBeTruthy();
    expect(screen.queryByRole('option', { name: /客户081/ })).toBeNull();

    fireEvent.change(screen.getByLabelText('客户搜索'), { target: { value: '081' } });
    expect(screen.getByRole('option', { name: /客户081/ })).toBeTruthy();
    fireEvent.keyDown(screen.getByLabelText('客户搜索'), { key: 'Enter' });
    expect(onChange).toHaveBeenLastCalledWith('customer-081');
  });

  it('opens in a body portal placed by the shared popover and restores trigger focus on Escape', async () => {
    const onChange = vi.fn();
    render(<SearchableSelect label="贴边选择" value="" options={[{ value: 'a', label: 'A' }]} onChange={onChange} />);
    const trigger = screen.getByRole('button', { name: '贴边选择' });

    fireEvent.click(trigger);
    const search = screen.getByLabelText('贴边选择搜索');
    await waitFor(() => expect(document.activeElement).toBe(search));
    const popover = document.body.querySelector('.fnd-combobox__popover') as HTMLElement;
    expect(popover.getAttribute('data-slot')).toBe('popover-content');
    expect(popover.closest('.fnd-control')).toBeNull();
    expect(popover.dataset.side).toBeTruthy();
    expect(trigger.getAttribute('aria-controls')).toBe(popover.id);
    fireEvent.keyDown(search, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByLabelText('贴边选择搜索')).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  });

  it('does not submit hidden options while loading or otherwise showing feedback', () => {
    const onChange = vi.fn();
    render(<SearchableSelect label="工作表" value="" options={[{ value: 'Sheet1', label: 'Sheet1' }]} onChange={onChange} loading />);

    fireEvent.click(screen.getByRole('button', { name: '工作表' }));
    const search = screen.getByLabelText('工作表搜索');
    expect(screen.queryByRole('option', { name: /Sheet1/ })).toBeNull();
    expect(search.getAttribute('aria-activedescendant')).toBeNull();
    fireEvent.keyDown(search, { key: 'Enter' });
    expect(onChange).not.toHaveBeenCalled();
  });

  it('keeps keyboard navigation visible with aria-activedescendant and scrollIntoView', async () => {
    const onChange = vi.fn();
    const scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: scrollIntoView });
    render(<SearchableSelect label="客户" value="" options={Array.from({ length: 5 }, (_, index) => ({
      value: `customer-${index + 1}`,
      label: `客户${index + 1}`,
    }))} onChange={onChange} />);

    fireEvent.click(screen.getByRole('button', { name: '客户' }));
    const search = screen.getByLabelText('客户搜索');
    const rows = screen.getAllByRole('option');
    await waitFor(() => expect(search.getAttribute('aria-activedescendant')).toBe(rows[0].id));
    scrollIntoView.mockClear();
    fireEvent.keyDown(search, { key: 'ArrowDown' });
    await waitFor(() => expect(search.getAttribute('aria-activedescendant')).toBe(rows[1].id));
    expect(scrollIntoView).toHaveBeenCalledWith({ block: 'nearest' });
    fireEvent.keyDown(search, { key: 'Enter' });
    expect(onChange).toHaveBeenLastCalledWith('customer-2');
  });


  it('keeps keyboard selection on the first search result when a stale hover target remains under the pointer', async () => {
    const onChange = vi.fn();
    render(<MultiSelect label="应收状态筛选" values={['disputed']} onChange={onChange} options={[
      { value: 'active', label: '正常应收', meta: '正常、未逾期、open' },
      { value: 'overdue', label: '逾期应收', meta: '逾期、overdue' },
      { value: 'disputed', label: '争议应收', meta: '争议、disputed' },
    ]} />);

    fireEvent.click(screen.getByRole('button', { name: '应收状态筛选' }));
    const search = screen.getByLabelText('应收状态筛选搜索');
    fireEvent.change(search, { target: { value: '逾期' } });
    await waitFor(() => expect(screen.getByRole('option', { name: /逾期应收/ }).getAttribute('data-selected')).toBe('true'));
    fireEvent.mouseEnter(screen.getByRole('option', { name: /正常应收/ }));
    fireEvent.keyDown(search, { key: 'Enter' });

    expect(onChange).toHaveBeenLastCalledWith(['disputed', 'overdue']);
  });

  it('lets actual pointer movement take over the active option before Enter', async () => {
    const onChange = vi.fn();
    render(<MultiSelect label="应收状态筛选" values={['disputed']} onChange={onChange} options={[
      { value: 'active', label: '正常应收', meta: '正常、未逾期、open' },
      { value: 'overdue', label: '逾期应收', meta: '逾期、overdue' },
      { value: 'disputed', label: '争议应收', meta: '争议、disputed' },
    ]} />);

    fireEvent.click(screen.getByRole('button', { name: '应收状态筛选' }));
    const search = screen.getByLabelText('应收状态筛选搜索');
    fireEvent.change(search, { target: { value: '逾期' } });
    fireEvent.pointerMove(screen.getByRole('option', { name: /正常应收/ }));
    await waitFor(() => expect(screen.getByRole('option', { name: /正常应收/ }).getAttribute('data-selected')).toBe('true'));
    fireEvent.keyDown(search, { key: 'Enter' });

    expect(onChange).toHaveBeenLastCalledWith(['disputed', 'active']);
  });

});
