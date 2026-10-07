// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { Bridge } from '../src/bridge.js';
import type { CloseStatus } from '../src/views/analysis/MonthCloseControlCenter.js';
import { GuideHub } from '../src/views/guide/GuideHub.js';
import { QuickStartChecklist, stepsFrom } from '../src/views/guide/QuickStartChecklist.js';

afterEach(() => { cleanup(); delete (globalThis as { foundry?: Partial<Bridge> }).foundry; });

const block = (key: string, state: 'done' | 'blocked' | 'attention' | 'not_started', items: CloseStatus['blocks'][number]['items'] = []) =>
  ({ key, label: key, state, items });
const status = (overrides: Partial<Record<string, CloseStatus['blocks'][number]>> = {}): CloseStatus => ({
  headline: { state: 'not_ready', text: '' }, blocking: [],
  blocks: [
    overrides.scope ?? block('scope', 'blocked', [{ text: '期间未确认', blocking: true, target: 'scope' }]),
    overrides.source ?? block('source', 'done', [{ text: '示例', hint: '摘要 abc', blocking: false, target: 'datasets' }]),
    overrides.structure ?? block('structure', 'done'),
    overrides.controls ?? block('controls', 'blocked', [{ text: '还没有确认的勾稽控制', blocking: true, target: 'controls' }]),
    overrides.exceptions ?? block('exceptions', 'done'),
    overrides.review ?? block('review', 'not_started', [{ text: '还没有计算结果', blocking: false, target: 'results' }]),
  ],
});

it('reads each step from the task, not from a tick', () => {
  const steps = stepsFrom(status());
  expect(steps.map((step) => [step.label, step.state])).toEqual([
    ['添加资料', 'done'], ['确认表结构', 'done'], ['确认分析范围', 'todo'],
    ['运行计算', 'not_started'], ['核对来源与异常', 'todo'], ['保存文稿并复核', 'not_started'],
  ]);
  expect(steps[0].detail).toBe('1 份');
  expect(steps[2].detail).toBe('期间未确认');
});

it('marks the draft step done only when the review block no longer blocks', () => {
  const calculated = stepsFrom(status({ review: block('review', 'blocked', [{ text: '还没有文稿', blocking: true, target: 'drafts' }]) }));
  expect(calculated[3].state).toBe('done');
  expect(calculated[5]).toMatchObject({ state: 'todo', detail: '还没有文稿' });
  expect(stepsFrom(status({ review: block('review', 'done') }))[5].state).toBe('done');
});

it('offers one action per open step and never a skip', async () => {
  (globalThis as { foundry?: Partial<Bridge> }).foundry = { financeCall: vi.fn(async () => ({ ok: true, value: status() })) as unknown as Bridge['financeCall'] };
  const onOpen = vi.fn();
  render(<QuickStartChecklist taskId="t" canOpen onOpen={onOpen} />);
  const actions = await screen.findAllByRole('button', { name: '去处理' });
  expect(actions).toHaveLength(4);
  expect(screen.queryByRole('button', { name: /跳过/ })).toBeNull();
  fireEvent.click(actions[0]);
  expect(onOpen).toHaveBeenCalledWith('scope');
});

it('asks for a task before it can show progress', () => {
  render(<QuickStartChecklist canOpen={false} onOpen={vi.fn()} />);
  expect(screen.getByText(/打开或新建一个任务后/)).toBeTruthy();
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

it('does not call a calculation done once the scope or data changed after it', () => {
  const steps = stepsFrom(status({ review: block('review', 'blocked', [{ text: '范围在上次计算之后改过，请重新计算', blocking: true, target: 'results' }]) }));
  expect(steps[3]).toMatchObject({ state: 'todo', detail: '范围在上次计算之后改过，请重新计算', target: 'results' });
  expect(steps[5].state).toBe('done');
});

it('sends a draft problem to drafts and an undecided difference to the close tab', () => {
  const steps = stepsFrom(status({
    controls: block('controls', 'done'),
    exceptions: block('exceptions', 'blocked', [{ text: '坏账分项：差异待处理', blocking: true, target: 'controls' }]),
    review: block('review', 'blocked', [{ text: '还没有文稿', blocking: true, target: 'drafts' }]),
  }));
  expect(steps[4]).toMatchObject({ state: 'todo', target: 'close' });
  expect(steps[5]).toMatchObject({ state: 'todo', target: 'drafts', detail: '还没有文稿' });
});

it('reads the task again when something changed it', async () => {
  let answer = status();
  const financeCall = vi.fn(async () => ({ ok: true, value: answer }));
  (globalThis as { foundry?: Partial<Bridge> }).foundry = { financeCall: financeCall as unknown as Bridge['financeCall'] };
  render(<QuickStartChecklist taskId="t" canOpen onOpen={vi.fn()} />);
  expect(await screen.findByText(/待处理 · 期间未确认/)).toBeTruthy();
  answer = status({ scope: block('scope', 'done', [{ text: '2026-06 · 人民币', blocking: false, target: 'scope' }]) });
  window.dispatchEvent(new Event('fnd:task-changed'));
  await waitFor(() => expect(screen.queryByText(/期间未确认/)).toBeNull());
});
