// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { Bridge } from '../src/bridge.js';
import type { OverviewTask, Preferences } from '../src/bridge.js';
import { PreferencesProvider } from '../src/components/Preferences.js';
import { GuideHub } from '../src/views/guide/GuideHub.js';
import { QuickStartChecklist, stepsFrom } from '../src/views/guide/QuickStartChecklist.js';

afterEach(() => { cleanup(); delete (globalThis as { foundry?: Partial<Bridge> }).foundry; });

type Block = NonNullable<OverviewTask['blocks']>[number];
const block = (key: string, state: Block['state']): Block => ({ key, label: key, state });
const business = { execution_status: 'succeeded', engine: 'finance', role: 'business', columns: ['metric', 'value'], rows: true, outputs: false };
const collection = { ...business, columns: ['城市公司', '收缴率生死线', '距生死线'] };
/** A task as 总览 reads it: its month-close blocks, its 等你处理 and what the later steps read. */
const row = (overrides: Partial<OverviewTask> = {}, states: Partial<Record<string, Block['state']>> = {}): OverviewTask => ({
  task: { id: 't', title: '华东区 8 月', period: '2026-08', created_at: '2026-10-01T00:00:00Z' } as OverviewTask['task'],
  blocks: (['scope', 'source', 'structure', 'controls', 'exceptions', 'review'] as const).map((key) => block(key, states[key] ?? 'done')),
  todo: [],
  work: { runs: [], cards: [], drafts: 0, datasets: 2 },
  ...overrides,
});

it('reads the six steps the way the step row and 总览 read them, not from a tick', () => {
  const steps = stepsFrom(row({ todo: [{ kind: 'scope', text: '期间未确认', target: 'scope' }] }, { scope: 'blocked', controls: 'blocked' }))!;
  expect(steps.map((step) => [step.label, step.state])).toEqual([
    ['资料', 'done'], ['范围', 'todo'], ['勾稽', 'todo'], ['财务分析', 'not_started'], ['经营分析', 'not_started'], ['汇报', 'not_started'],
  ]);
  expect(steps[0].detail).toBe('2 份资料');
  expect(steps[1]).toMatchObject({ detail: '期间未确认', target: 'scope' });
  expect(steps[3].detail).toBe('还没有计算结果');
});

it('places 回款健康 on 经营分析 and a calculation to run again on 财务分析', () => {
  const steps = stepsFrom(row({
    todo: [{ kind: 'review', text: '范围在上次计算之后改过，请重新计算', target: 'results' }, { kind: 'collection', text: '收缴率口径有一版建议（第 2 版）等你确认', target: 'billing' }],
    work: { runs: [business, collection], cards: [], drafts: 1, datasets: 2 },
  }))!;
  expect(steps[3]).toMatchObject({ state: 'todo', detail: '范围在上次计算之后改过，请重新计算', target: 'results' });
  expect(steps[4]).toMatchObject({ state: 'todo', detail: '收缴率口径有一版建议（第 2 版）等你确认', target: 'billing' });
  expect(steps[5].state).toBe('done');
});

it('sends an undecided difference to 勾稽 and a draft to 汇报 · 文稿, and says 本期不做 for a step the period does without', () => {
  const steps = stepsFrom(row({
    todo: [{ kind: 'exceptions', text: '坏账分项：差异待处理', target: 'controls' }, { kind: 'review', text: '还没有文稿', target: 'drafts' }],
    work: { runs: [business], cards: [], drafts: 0, datasets: 2 },
  }, { exceptions: 'blocked' }), ['operations'])!;
  expect(steps[2]).toMatchObject({ state: 'todo', target: 'close', detail: '坏账分项：差异待处理' });
  expect(steps[4]).toMatchObject({ state: 'skipped', detail: '' });
  expect(steps[5]).toMatchObject({ state: 'todo', target: 'drafts', detail: '还没有文稿' });
});

it('offers one action per open step, none on a step done or not done this period, and never a skip', async () => {
  (globalThis as { foundry?: Partial<Bridge> }).foundry = {
    overview: vi.fn(async () => ({ ok: true as const, value: { schema_version: 1 as const, todo_count: 1, tasks: [row({ todo: [{ kind: 'scope', text: '期间未确认', target: 'scope' }] }, { scope: 'blocked' })] } })),
    preferencesGet: vi.fn(async () => ({ ok: true as const, value: { skipped_steps: { t: ['report'] } } as unknown as Preferences })),
    preferencesSet: vi.fn(),
  };
  const onOpen = vi.fn();
  render(<PreferencesProvider><QuickStartChecklist taskId="t" canOpen onOpen={onOpen} /></PreferencesProvider>);
  expect(await screen.findByText('本期不做')).toBeTruthy();
  const actions = screen.getAllByRole('button', { name: '去处理' });
  // 范围, 财务分析, 经营分析; 资料 and 勾稽 are done and 汇报 is 本期不做.
  expect(actions).toHaveLength(3);
  expect(screen.queryByRole('button', { name: /跳过/ })).toBeNull();
  fireEvent.click(actions[0]);
  expect(onOpen).toHaveBeenCalledWith('scope');
});

it('asks for a task before it can show progress, and says so for one 总览 does not list', async () => {
  render(<QuickStartChecklist canOpen={false} onOpen={vi.fn()} />);
  expect(screen.getByText(/打开或新建一个任务后/)).toBeTruthy();
  cleanup();
  (globalThis as { foundry?: Partial<Bridge> }).foundry = { overview: vi.fn(async () => ({ ok: true as const, value: { schema_version: 1 as const, todo_count: 0, tasks: [] } })) };
  render(<QuickStartChecklist taskId="archived" canOpen onOpen={vi.fn()} />);
  expect(await screen.findByText('这个任务不在进行中，恢复后这里才显示六步进度。')).toBeTruthy();
});

it('offers practice on the sample task first, or your own files', async () => {
  const onSample = vi.fn(async () => undefined);
  const onOwnData = vi.fn();
  render(<GuideHub article="first-run" canOpen={false} onOpen={vi.fn()} onClose={vi.fn()} onSample={onSample} onOwnData={onOwnData} />);
  fireEvent.click(screen.getByRole('button', { name: '用示例任务练习（推荐）' }));
  await waitFor(() => expect(onSample).toHaveBeenCalled());
  fireEvent.click(screen.getByRole('button', { name: '使用自己的资料' }));
  expect(onOwnData).toHaveBeenCalled();
});

it('says so when the sample task cannot be made', async () => {
  render(<GuideHub article="first-run" onOpen={vi.fn()} onClose={vi.fn()} onSample={async () => { throw new Error('这个版本还不能创建示例任务。'); }} />);
  fireEvent.click(screen.getByRole('button', { name: '用示例任务练习（推荐）' }));
  expect((await screen.findByRole('alert')).textContent).toBe('这个版本还不能创建示例任务。');
});

it('reads the task again when something changed it', async () => {
  let answer = row({ todo: [{ kind: 'scope', text: '期间未确认', target: 'scope' }] }, { scope: 'blocked' });
  const overview = vi.fn(async () => ({ ok: true as const, value: { schema_version: 1 as const, todo_count: 1, tasks: [answer] } }));
  (globalThis as { foundry?: Partial<Bridge> }).foundry = { overview };
  render(<QuickStartChecklist taskId="t" canOpen onOpen={vi.fn()} />);
  expect(await screen.findByText(/待处理 · 期间未确认/)).toBeTruthy();
  answer = row();
  window.dispatchEvent(new Event('fnd:task-changed'));
  await waitFor(() => expect(screen.queryByText(/期间未确认/)).toBeNull());
});
