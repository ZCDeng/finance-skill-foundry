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

it('puts the differences that will hold the close under a 可计算 headline', async () => {
  const financeCall = vi.fn(async (_task: string, command: string) => ({ ok: true, value: command === 'finance-close-status'
    ? { ...status, headline: { state: 'calculable', text: '可计算：范围和结构已确认', detail: '3 项差异仍挡住月结，处理完才能提交复核' } }
    : { controls: [], summary: { controls: 0, confirmed: 0, pass: 0, break: 0, stale: 0, error: 0 } } }));
  (globalThis as { foundry?: Partial<Bridge> }).foundry = { financeCall: financeCall as unknown as Bridge['financeCall'] };
  render(<MonthCloseControlCenter taskId="t" onOpen={vi.fn()} />);
  expect(await screen.findByRole('heading', { name: '可计算：范围和结构已确认' })).toBeTruthy();
  expect(screen.getByText('3 项差异仍挡住月结，处理完才能提交复核')).toBeTruthy();
  expect(screen.getAllByRole('status')[0].textContent).toBe('可计算：范围和结构已确认。3 项差异仍挡住月结，处理完才能提交复核');
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

it('states the 可用结论 under the headline, apart from it, with reasons and each workbook', async () => {
  const reasons = ['坏账分项：差额 11655，来源矛盾，差异待处理', '台账实收：差额 -2793.2794，未定类型，待外部确认', '应收分项：差额 5，口径不同，待重新导入修正后的资料', '预收分项：差额 7，未定类型，差异待处理', '税金：差额 1，未更新，接受差异待第二人复核'];
  const withConclusion: CloseStatus = {
    ...status, headline: { state: 'needs_review', text: '需要复核：计算完成，但有 5 项来源冲突' },
    conclusion: {
      level: 'not_usable', text: '不可用', reasons: reasons.map((text) => ({ text, target: 'controls' })),
      basis: { confirmed: 7, passed: 2, waived: 0, open: 5 },
      workbooks: [
        { dataset_id: 'b1', name: '月结套表.xlsx', level: 'not_usable', text: '不可用', reasons: [{ text: reasons[0] }] },
        { dataset_id: 'b3', name: '银行流水.xlsx', level: 'not_assessable', text: '无法判断', reasons: [{ text: '还没有你确认的勾稽控制读到这本工作簿' }] },
      ],
    },
  };
  const financeCall = vi.fn(async (_task: string, command: string) => ({ ok: true, value: command === 'finance-close-status'
    ? withConclusion : { controls: [], summary: { controls: 0, confirmed: 0, pass: 0, break: 0, stale: 0, error: 0 } } }));
  (globalThis as { foundry?: Partial<Bridge> }).foundry = { financeCall: financeCall as unknown as Bridge['financeCall'] };
  render(<MonthCloseControlCenter taskId="t" onOpen={vi.fn()} />);
  // The headline stays the headline; the conclusion is its own block below it.
  expect(await screen.findByRole('heading', { name: '需要复核：计算完成，但有 5 项来源冲突' })).toBeTruthy();
  const conclusion = screen.getByRole('region', { name: '套表可用结论' });
  expect(within(conclusion).getByRole('heading', { name: '套表可用结论：不可用' })).toBeTruthy();
  expect(within(conclusion).getByText('结论只根据你确认过的控制和处置得出；助手的类型建议不改变结论。')).toBeTruthy();
  expect(within(conclusion).getByText('依据：你确认的 7 条控制，相符 2 条，已接受差异 0 条，仍挡住月结 5 条。')).toBeTruthy();
  const [shown, more, books] = [conclusion.querySelector(':scope > ul')!, ...Array.from(conclusion.querySelectorAll(':scope > details'))];
  expect(Array.from(shown.querySelectorAll('li')).map((item) => item.textContent)).toEqual(reasons.slice(0, 3));
  expect(more.querySelector('summary')!.textContent).toBe('另外 2 条原因');
  expect(Array.from(more.querySelectorAll('li')).map((item) => item.textContent)).toEqual(reasons.slice(3));
  expect(books.querySelector('summary')!.textContent).toBe('按工作簿看');
  expect(within(books as HTMLElement).getByText('银行流水.xlsx').parentElement!.textContent).toBe('银行流水.xlsx：无法判断');
  expect(conclusion.className).toContain('analysis-close-conclusion--not_usable');
  expect(conclusion.textContent).not.toMatch(/完成|通过/);
  // Only the headline is announced as status.
  expect(screen.getAllByRole('status')[0].textContent).toBe('需要复核：计算完成，但有 5 项来源冲突');
});

it('shows no conclusion when an older engine leaves it out, and a bare one without crashing', async () => {
  mount();
  render(<MonthCloseControlCenter taskId="t" onOpen={vi.fn()} />);
  await screen.findByRole('heading', { name: '尚未准备：还有 1 项必须确认' });
  expect(screen.queryByRole('region', { name: '套表可用结论' })).toBeNull();
  cleanup();
  const bare = { ...status, conclusion: { level: 'not_assessable', text: '无法判断' } } as CloseStatus;
  const financeCall = vi.fn(async (_task: string, command: string) => ({ ok: true, value: command === 'finance-close-status'
    ? bare : { controls: [], summary: { controls: 0, confirmed: 0, pass: 0, break: 0, stale: 0, error: 0 } } }));
  (globalThis as { foundry?: Partial<Bridge> }).foundry = { financeCall: financeCall as unknown as Bridge['financeCall'] };
  render(<MonthCloseControlCenter taskId="t" onOpen={vi.fn()} />);
  expect(await screen.findByRole('heading', { name: '套表可用结论：无法判断' })).toBeTruthy();
  expect(screen.queryByText('按工作簿看')).toBeNull();
});
