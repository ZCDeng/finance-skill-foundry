// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { Bridge } from '../src/bridge.js';
import { MonthCloseControlCenter, type CloseStatus } from '../src/views/analysis/MonthCloseControlCenter.js';

afterEach(() => { cleanup(); delete (globalThis as { foundry?: Partial<Bridge> }).foundry; });

const status: CloseStatus = {
  headline: { state: 'not_ready', text: '尚未准备：还有 1 项必须确认' },
  blocking: ['期间未确认'],
  blocks: [
    { key: 'scope', label: '范围', state: 'blocked', items: [{ text: '期间未确认', blocking: true, target: 'scope' }] },
    { key: 'source', label: '来源', state: 'done', items: [{ text: '月结 · 摘要 e3763c14568d', blocking: false, target: 'datasets' }] },
    { key: 'structure', label: '结构', state: 'done', items: [] },
    { key: 'controls', label: '控制', state: 'blocked', items: [{ text: '还没有确认的勾稽控制', blocking: true, target: 'controls' }] },
    { key: 'exceptions', label: '异常', state: 'done', items: [{ text: '没有未处置的差异', blocking: false }] },
    { key: 'review', label: '复核', state: 'not_started', items: [{ text: '还没有计算结果', blocking: false, target: 'results' }] },
  ],
};
const mount = () => {
  const financeCall = vi.fn(async (_task: string, command: string) => ({ ok: true, value: command === 'finance-close-status'
    ? status : { controls: [], summary: { controls: 0, confirmed: 0, pass: 0, break: 0, stale: 0, error: 0 } } }));
  (globalThis as { foundry?: Partial<Bridge> }).foundry = { financeCall: financeCall as unknown as Bridge['financeCall'] };
  return financeCall;
};

it('leads with the server headline and the next thing to do', async () => {
  mount();
  render(<MonthCloseControlCenter taskId="t" onOpen={vi.fn()} />);
  expect(await screen.findByRole('heading', { name: '尚未准备：还有 1 项必须确认' })).toBeTruthy();
  expect(screen.getByText('下一步：期间未确认')).toBeTruthy();
  expect(screen.getAllByRole('status')[0].textContent).toBe('尚未准备：还有 1 项必须确认');
});

it('says each block state in words, not colour alone', async () => {
  mount();
  render(<MonthCloseControlCenter taskId="t" onOpen={vi.fn()} />);
  expect(await screen.findByRole('listitem', { name: '1 范围：待处理' })).toBeTruthy();
  expect(screen.getByRole('listitem', { name: '2 来源：已就绪' })).toBeTruthy();
  expect(screen.getByRole('listitem', { name: '6 复核：尚未开始' })).toBeTruthy();
});

it('sends the manager to where a blocking item is fixed', async () => {
  mount();
  const onOpen = vi.fn();
  render(<MonthCloseControlCenter taskId="t" onOpen={onOpen} />);
  const scope = await screen.findByRole('listitem', { name: '1 范围：待处理' });
  fireEvent.click(within(scope).getByRole('button', { name: '去处理' }));
  expect(onOpen).toHaveBeenCalledWith('scope');
});

it('keeps the tie-out controls on the same page', async () => {
  mount();
  render(<MonthCloseControlCenter taskId="t" onOpen={vi.fn()} />);
  expect(await screen.findByRole('region', { name: '勾稽控制' })).toBeTruthy();
});
