// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { FieldShell } from '../src/components/FinancialControls.js';
import { Checkbox } from '../src/components/ui/checkbox.js';
import { NativeSelect } from '../src/components/ui/native-select.js';

afterEach(cleanup);

describe('shadcn primitives on FA tokens', () => {
  it('keeps the select native so the platform draws its menu', () => {
    const onChange = vi.fn();
    render(<NativeSelect aria-label="用途" value="input" onChange={(event) => onChange(event.target.value)}>
      <option value="input">读取输入</option><option value="output">写回输出</option>
    </NativeSelect>);
    const select = screen.getByRole('combobox', { name: '用途' });
    expect(select.tagName).toBe('SELECT');
    expect(select.classList.contains('fnd-field')).toBe(true);
    expect(select.closest('[data-slot="native-select-wrapper"]')?.querySelector('svg[aria-hidden]')).toBeTruthy();
    fireEvent.change(select, { target: { value: 'output' } });
    expect(onChange).toHaveBeenCalledWith('output');
  });

  it('toggles a checkbox from the text of the label around it', () => {
    const onCheckedChange = vi.fn();
    render(<label><Checkbox checked={false} onCheckedChange={onCheckedChange} />纳入</label>);
    fireEvent.click(screen.getByText('纳入'));
    expect(onCheckedChange).toHaveBeenCalledWith(true);
    expect(screen.getByRole('checkbox', { name: '纳入' })).toBeTruthy();
  });

  it('lays a field out with shadcn slots and marks the invalid state', () => {
    render(<FieldShell label="期间" htmlFor="p" error="格式应为 YYYY-MM"><input id="p" aria-invalid /></FieldShell>);
    const field = screen.getByText('格式应为 YYYY-MM').closest('[data-slot="field"]');
    expect(field?.getAttribute('data-invalid')).toBe('true');
    expect(field?.querySelector('[data-slot="field-label"]')?.textContent).toBe('期间');
    expect(screen.getByText('格式应为 YYYY-MM').getAttribute('data-slot')).toBe('field-error');
    expect(screen.getByText('格式应为 YYYY-MM').id).toBe('p-description');
  });
});
