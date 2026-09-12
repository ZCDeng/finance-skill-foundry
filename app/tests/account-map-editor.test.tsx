// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { AccountMapEditor } from '../src/views/analysis/AccountMapEditor.js';

afterEach(() => cleanup());

const three = JSON.stringify([
  { account_code: '6001', management_account: 'revenue' },
  { account_code: '6401', management_account: 'cost' },
  { account_code: '6601', management_account: 'expense' },
]);

describe('account map editor', () => {
  it('edits a row without the manager writing JSON', () => {
    const onChange = vi.fn();
    render(<AccountMapEditor value={three} onChange={onChange} />);
    expect((screen.getByLabelText('第 2 行科目代码') as HTMLInputElement).value).toBe('6401');
    fireEvent.change(screen.getByLabelText('第 2 行科目代码'), { target: { value: '6402' } });
    expect(JSON.parse(onChange.mock.calls[0][0])[1]).toEqual({
      account_code: '6402', management_account: 'cost',
    });
  });

  it('offers only the three accounts the engine knows', () => {
    render(<AccountMapEditor value={three} onChange={vi.fn()} />);
    const options = [...(screen.getByLabelText('第 1 行管理科目') as HTMLSelectElement).options]
      .map((option) => option.value);
    expect(options).toEqual(['', 'revenue', 'cost', 'expense']);
  });

  it('adds and removes rows', () => {
    const onChange = vi.fn();
    render(<AccountMapEditor value={three} onChange={onChange} />);
    fireEvent.click(screen.getByRole('button', { name: /加一行/ }));
    expect(JSON.parse(onChange.mock.calls[0][0])).toHaveLength(4);
    onChange.mockClear();
    fireEvent.click(screen.getByRole('button', { name: '删除第 1 行' }));
    const left = JSON.parse(onChange.mock.calls[0][0]);
    expect(left).toHaveLength(2);
    expect(left[0].account_code).toBe('6401');
  });

  it('falls back to the raw text when the mapping is not an array', () => {
    render(<AccountMapEditor value="{oops" onChange={vi.fn()} />);
    expect(screen.getByRole('alert').textContent).toContain('不是合法的 JSON 数组');
    expect(screen.queryByLabelText('第 1 行科目代码')).toBeNull();
  });
});
