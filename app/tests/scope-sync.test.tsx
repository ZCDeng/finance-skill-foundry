// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { Answer, Bridge } from '../src/bridge.js';
import { emptyScope, useAnalysisScope, type AnalysisScope } from '../src/views/analysis/scope.js';
import { RequirementsPanel } from '../src/views/analysis/RequirementsPanel.js';

const ok = (value: Record<string, unknown>): Answer<Record<string, unknown>> => ({ ok: true, value });
const first = { id: 'first', question: '华东分析', scope: { organization: '华东' }, bindings: {}, items: [] };
const next = { ...first, id: 'next', scope: { organization: '华南' } };
const deferred = () => {
  let resolve!: (value: Answer<Record<string, unknown>>) => void;
  const promise = new Promise<Answer<Record<string, unknown>>>((done) => { resolve = done; });
  return { resolve, promise };
};
const mount = (financeCall: NonNullable<Bridge['financeCall']>) => {
  (globalThis as { foundry?: Partial<Bridge> }).foundry = { financeCall };
};
const shared = (record = first): AnalysisScope => ({
  current: record, scope: { ...emptyScope(), ...record.scope }, candidates: {}, conflicts: [],
  loading: false, saving: false, message: '', error: '', setField: vi.fn(), setFields: vi.fn(), applyRecord: vi.fn(), save: vi.fn(),
});
afterEach(() => { cleanup(); delete (globalThis as { foundry?: Partial<Bridge> }).foundry; });

it('keeps unsaved fields when a new task refresh still has no saved scope', async () => {
  mount(vi.fn(async () => ok({ current: null })));
  const { result, rerender } = renderHook(({ version }) => useAnalysisScope('task', '问题', [], version), { initialProps: { version: 0 } });
  await waitFor(() => expect(result.current.loading).toBe(false));
  act(() => result.current.setField('organization', '正在填写'));
  rerender({ version: 1 });
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(result.current.scope.organization).toBe('正在填写');
});

it('does not let an older refresh replace a record just saved in another panel', async () => {
  const read = deferred(); let reads = 0;
  mount(vi.fn(async (_task, command) => command === 'analysis-requirements-list'
    ? ++reads === 1 ? ok({ current: first }) : read.promise : ok({})));
  const { result, rerender } = renderHook(({ version }) => useAnalysisScope('task', '问题', [], version), { initialProps: { version: 0 } });
  await waitFor(() => expect(result.current.current?.id).toBe(first.id));
  rerender({ version: 1 });
  act(() => result.current.applyRecord(next));
  await act(async () => read.resolve(ok({ current: first })));
  expect(result.current.current?.id).toBe(next.id);
  expect(result.current.scope.organization).toBe('华南');
});

it('re-reads a scope already on screen in the background, without a loading state', async () => {
  const read = deferred(); let reads = 0;
  mount(vi.fn(async (_task, command) => command === 'analysis-requirements-list'
    ? ++reads === 1 ? ok({ current: first }) : read.promise : ok({})));
  const { result, rerender } = renderHook(({ version }) => useAnalysisScope('task', '问题', [], version), { initialProps: { version: 0 } });
  await waitFor(() => expect(result.current.current?.id).toBe(first.id));
  rerender({ version: 1 });
  expect(result.current.loading).toBe(false);
  await act(async () => read.resolve(ok({ current: next })));
  expect(result.current.loading).toBe(false);
  expect(result.current.scope.organization).toBe('华南');
});

it('keeps pending field edits when another editor reads the same saved version', async () => {
  mount(vi.fn(async () => ok({ current: first })));
  const { result } = renderHook(() => useAnalysisScope('task', '问题', []));
  await waitFor(() => expect(result.current.current?.id).toBe(first.id));
  act(() => result.current.setField('organization', '正在填写'));
  act(() => result.current.applyRecord(first));
  expect(result.current.scope.organization).toBe('正在填写');
});

it('does not publish a requirements save response after switching tasks', async () => {
  const save = deferred(); const oldScope = shared(); const newScope = shared(next); const changed = vi.fn();
  mount(vi.fn(async (task, command) => command === 'analysis-requirements-save'
    ? save.promise : ok({ current: task === 'old-task' ? first : next })));
  const { rerender } = render(<RequirementsPanel taskId="old-task" analysisScope={oldScope} onChanged={changed} />);
  await screen.findByDisplayValue(first.question);
  fireEvent.click(screen.getByRole('button', { name: /保存要求新版/ }));
  rerender(<RequirementsPanel taskId="new-task" analysisScope={newScope} onChanged={changed} />);
  await screen.findByDisplayValue('华南');
  vi.mocked(newScope.applyRecord).mockClear();
  await act(async () => save.resolve(ok({ ...first, id: 'saved-old' })));
  expect(newScope.applyRecord).not.toHaveBeenCalled();
  expect(changed).not.toHaveBeenCalled();
  expect(screen.getByDisplayValue('华南')).toBeTruthy();
});

it('does not publish a requirements list response after its editor unmounts', async () => {
  const read = deferred(); const state = shared();
  mount(vi.fn(async () => read.promise));
  const { unmount } = render(<RequirementsPanel taskId="task" analysisScope={state} />);
  unmount();
  await act(async () => read.resolve(ok({ current: first })));
  expect(state.applyRecord).not.toHaveBeenCalled();
});
