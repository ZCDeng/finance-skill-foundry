// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { AnalysisRun } from '../src/bridge.js';
import { ClaimBindingRepair } from '../src/views/analysis/ClaimBindingRepair.js';
afterEach(cleanup);
it('repairs only the explicit selected calculation binding and retains other claims and exact values', () => {
  const onChange = vi.fn();
  const untouched = { basis: 'professional_judgment', reason: '待访谈' };
  render(<ClaimBindingRepair disabled={false} claims={[
    { basis: 'calculation', run_id: 'r', row: 0, column: 'actual', value: '88', fact_id: 'stale' }, untouched,
  ]} runs={[{ id: 'r', execution_status: 'succeeded', result: { rows: [{ metric: '收入', actual: '900719925474099.99' }] } } as unknown as AnalysisRun]} onChange={onChange} />);
  fireEvent.click(screen.getByRole('button', { name: '采用引用 1 的结果值' }));
  expect(onChange).toHaveBeenCalledWith([
    { basis: 'calculation', run_id: 'r', row: 0, column: 'actual', value: '900719925474099.99' }, untouched,
  ]);
  expect(screen.queryByText('用户假设')).toBeNull();
});
it('cannot select failed runs or write an arbitrary number', () => {
  render(<ClaimBindingRepair disabled={false} claims={[{ basis: 'calculation', run_id: 'failed', row: 0, column: 'actual', value: '88' }]}
    runs={[{ id: 'failed', execution_status: 'failed', result: { rows: [{ actual: '1' }] } } as unknown as AnalysisRun]} onChange={vi.fn()} />);
  expect((screen.getByRole('button', { name: '采用引用 1 的结果值' }) as HTMLButtonElement).disabled).toBe(true);
});
