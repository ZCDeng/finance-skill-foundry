// @vitest-environment jsdom
import { act, cleanup, render, screen } from '@testing-library/react';
import { getConfig } from '@testing-library/dom';
import { afterEach, expect, it, vi } from 'vitest';

vi.mock('pdfjs-dist', () => ({ GlobalWorkerOptions: { workerSrc: '' }, getDocument: vi.fn() }));
import { Analysis } from '../src/views/Analysis.js';
import type { AnalysisState, Answer, Bridge, DatasetSnapshot, TaskRow } from '../src/bridge.js';

const task: TaskRow = { id: 'a'.repeat(32), title: '范围初始化', period: null, skill_id: null, created_at: '2026-09-05T00:00:00Z', windows: 0 };
const object = { task_id: task.id, schema_version: 1, created_at: task.created_at };
const source: DatasetSnapshot = { ...object, id: 'b'.repeat(32), name: '实际资料', kind: 'table', source_hash: 'c'.repeat(64), source_name: 'actual.csv',
  metadata: { currency: 'CNY', unit: '元' }, schema: [{ name: 'profit', type: 'DECIMAL(38,2)' }], row_count: 1 };
const state: AnalysisState = { task_id: task.id, datasets: [source], analyses: [], runs: [], drafts: [], methods: [] };
const context = { ...object, id: '4'.repeat(32), name: '已保存范围', bindings: { actual: source.id },
  scopes: { actual: { period: '2026-08', currency: 'CNY', unit: '元', scenario: 'actual' } } };
const success = <T,>(value: T): Answer<T> => ({ ok: true, value });
const props = { task, tasks: [task], onPick: vi.fn(), onNew: vi.fn(), onChat: vi.fn() };
const rerunName = '按已保存范围重算损益表';

function install(readContexts: () => Promise<typeof context[]>) {
  const financeCall = vi.fn(async (_taskId: string, command: string) => {
    if (command === 'list-finance-context') return success({ task_id: task.id, datasets: [source], contexts: await readContexts(),
      account_maps: [], scenarios: [], metric_definitions: [], capabilities: ['metrics'] });
    if (command === 'finance-adjustment-list') return success({ adjustments: [] });
    return success({});
  });
  (globalThis as unknown as { foundry: Partial<Bridge> }).foundry = {
    analysisState: async () => success(state), financeCall,
  };
  return financeCall;
}

afterEach(() => { cleanup(); delete (globalThis as unknown as { foundry?: Bridge }).foundry; sessionStorage.clear(); vi.clearAllMocks(); });

it('commits resolved bootstrap work before starting the default button lookup', async () => {
  const timeout = getConfig().asyncUtilTimeout;
  expect(timeout).toBe(1000);
  let returned = false;
  install(async () => {
    // Controlled main-thread scheduling: an already-resolved mock can still queue
    // its React commit behind a query timeout. No API delay or retry is introduced.
    const until = performance.now() + timeout + 100;
    while (performance.now() < until) { /* Deliberately keep this JS turn busy. */ }
    returned = true;
    return [context];
  });
  await act(async () => { render(<Analysis {...props} embedded section="results" />); });
  expect(await screen.findByRole('button', { name: rerunName })).toBeTruthy();
  expect(returned).toBe(true);
  expect(screen.getByRole('region', { name: '范围与计算' })).toBeTruthy();
  expect(getConfig().asyncUtilTimeout).toBe(timeout);
});

it('keeps an unresolved context absent until that exact read settles', async () => {
  let release!: (contexts: typeof context[]) => void;
  const pending = new Promise<typeof context[]>((resolve) => { release = resolve; });
  const calls = install(() => pending);
  await act(async () => { render(<Analysis {...props} embedded section="results" />); });
  expect(calls.mock.calls.some(([, command]) => command === 'list-finance-context')).toBe(true);
  expect(screen.queryByRole('button', { name: rerunName })).toBeNull();
  await act(async () => { release([context]); });
  expect(screen.getByRole('button', { name: rerunName })).toBeTruthy();
});

it('does not invent a saved-scope action when the completed read has no context', async () => {
  install(async () => []);
  await act(async () => { render(<Analysis {...props} embedded section="results" />); });
  expect(screen.getByRole('region', { name: '范围与计算' })).toBeTruthy();
  expect(screen.queryByRole('button', { name: rerunName })).toBeNull();
});
