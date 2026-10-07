// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { Bridge } from '../src/bridge.js';
import { MonthCloseControlCenter, type CloseStatus } from '../src/views/analysis/MonthCloseControlCenter.js';

afterEach(() => { cleanup(); delete (globalThis as { foundry?: Partial<Bridge> }).foundry; });

const status: CloseStatus = {
  headline: { state: 'not_ready', text: '尚未准备：还有 2 项待处理' },
  blocking: ['期间未确认', '还没有确认的勾稽控制'],
  blocks: [
    { key: 'scope', label: '范围', state: 'blocked', items: [{ text: '期间未确认', blocking: true, target: 'scope' }] },
    { key: 'source', label: '来源', state: 'done', items: [{ text: '月结', hint: '摘要 e3763c14568d', blocking: false, target: 'datasets' }] },
    { key: 'structure', label: '结构', state: 'done', items: [] },
    { key: 'controls', label: '控制', state: 'blocked', items: [{ text: '还没有确认的勾稽控制', blocking: true, target: 'controls' }] },
    { key: 'exceptions', label: '异常', state: 'done', items: [{ text: '没有未处置的差异', blocking: false }] },
    { key: 'review', label: '复核', state: 'not_started', items: [{ text: '还没有计算结果', blocking: false, target: 'results' }] },
  ],
};
const mount = (answer: CloseStatus = status) => {
  const financeCall = vi.fn(async (_task: string, command: string) => ({ ok: true, value: command === 'finance-close-status'
    ? answer : { controls: [], summary: { controls: 0, confirmed: 0, pass: 0, break: 0, stale: 0, error: 0 } } }));
  (globalThis as { foundry?: Partial<Bridge> }).foundry = { financeCall: financeCall as unknown as Bridge['financeCall'] };
  return financeCall;
};

it('leads with the server headline and the next thing to do', async () => {
  mount();
  render(<MonthCloseControlCenter taskId="t" onOpen={vi.fn()} />);
  expect(await screen.findByRole('heading', { name: '尚未准备：还有 2 项待处理' })).toBeTruthy();
  expect(screen.getByText('下一步：期间未确认')).toBeTruthy();
  expect(screen.getAllByRole('status')[0].textContent).toBe('尚未准备：还有 2 项待处理');
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

/** What a sighted reader sees: the text with the screen-reader-only parts taken out. */
const visible = (element: Element) => {
  const copy = element.cloneNode(true) as Element;
  copy.querySelectorAll('.sr-only').forEach((node) => node.remove());
  return copy.textContent;
};

it('opens only the steps that need work and says the rest in one line each', async () => {
  mount();
  render(<MonthCloseControlCenter taskId="t" onOpen={vi.fn()} />);
  expect(await screen.findByRole('listitem', { name: '1 范围：待处理' })).toBeTruthy();
  expect(screen.getByRole('listitem', { name: '4 控制：待处理' })).toBeTruthy();
  expect(screen.queryByRole('listitem', { name: '2 来源：已就绪' })).toBeNull();
  expect(screen.queryByRole('listitem', { name: '6 复核：尚未开始' })).toBeNull();
  const lines = Array.from(document.querySelectorAll('.analysis-close-settled')).map(visible);
  expect(lines).toEqual(['已就绪：来源、结构、异常', '尚未开始：复核（还没有计算结果）']);
});

it('lets the headline number be counted row by row in the open cards', async () => {
  const qa: CloseStatus = {
    headline: { state: 'not_ready', text: '尚未准备：还有 6 项待处理' },
    blocking: ['期间未确认', '预算 的表结构等你确认', '月结套表 的表结构等你确认', '还没有确认的勾稽控制',
      '文稿早于最新一次计算，请按新结果更新', '文稿数值引用：需要处理'],
    blocks: [
      { key: 'scope', label: '范围', state: 'blocked', items: [{ text: '期间未确认', blocking: true, target: 'scope' }] },
      { key: 'source', label: '来源', state: 'done', items: [{ text: '预算', hint: '摘要 bbfdc3ccd5b1', blocking: false, target: 'datasets' }] },
      { key: 'structure', label: '结构', state: 'blocked', items: [
        { text: '预算 的表结构等你确认', blocking: true, target: 'structure' },
        { text: '月结套表 的表结构等你确认', blocking: true, target: 'structure' }] },
      { key: 'controls', label: '控制', state: 'blocked', items: [{ text: '还没有确认的勾稽控制', blocking: true, target: 'controls' }] },
      { key: 'exceptions', label: '异常', state: 'done', items: [{ text: '没有未处置的差异', blocking: false }] },
      { key: 'review', label: '复核', state: 'blocked', items: [
        { text: '文稿早于最新一次计算，请按新结果更新', blocking: true, target: 'drafts' },
        { text: '文稿数值引用：需要处理', blocking: true, target: 'drafts' },
        { text: '经理尚未复核（提交后由经理完成）', blocking: false, target: 'drafts' }] },
    ],
  };
  mount(qa);
  render(<MonthCloseControlCenter taskId="t" onOpen={vi.fn()} />);
  await screen.findByRole('heading', { name: '尚未准备：还有 6 项待处理' });
  const cards = Array.from(document.querySelectorAll('.analysis-close-block--blocked')) as HTMLElement[];
  const rows = cards.flatMap((card) => Array.from(card.querySelectorAll(':scope > ul > li')).map((row) => row.textContent));
  expect(rows).toEqual(qa.blocking);
  expect(rows).toHaveLength(6);
  // What does not hold the close is said below the list, not counted in it.
  const note = screen.getByText('经理尚未复核（提交后由经理完成）');
  expect(note.closest('ul')).toBeNull();
  for (const card of cards) {
    const [action] = within(card).getAllByRole('button', { name: '去处理' });
    expect(within(card).getAllByRole('button', { name: '去处理' })).toHaveLength(1);
    for (const item of Array.from(card.querySelectorAll('li, p'))) {
      expect(item.compareDocumentPosition(action) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
  }
});

it('keeps the 去处理 of the control card on this page, at the tie-out controls', async () => {
  mount();
  const onOpen = vi.fn();
  const spy = vi.spyOn(HTMLElement.prototype, 'scrollIntoView');
  render(<MonthCloseControlCenter taskId="t" onOpen={onOpen} />);
  const controls = await screen.findByRole('listitem', { name: '4 控制：待处理' });
  fireEvent.click(within(controls).getByRole('button', { name: '去处理' }));
  expect(onOpen).not.toHaveBeenCalled();
  const target = spy.mock.contexts[0] as HTMLElement;
  expect(within(target).getByRole('region', { name: '勾稽控制' })).toBeTruthy();
  expect(document.activeElement).toBe(within(target).getByRole('heading', { name: '勾稽控制' }));
  spy.mockRestore();
});

it('keeps file names for screen readers and the digest only in the tooltip', async () => {
  mount();
  render(<MonthCloseControlCenter taskId="t" onOpen={vi.fn()} />);
  await screen.findByRole('heading', { name: '尚未准备：还有 2 项待处理' });
  const source = screen.getByTitle(/摘要 e3763c14568d/);
  expect(source.textContent).toBe('来源');
  expect(source.getAttribute('title')).toBe('月结 · 摘要 e3763c14568d');
  expect(source.nextElementSibling!.className).toBe('sr-only');
  expect(source.nextElementSibling!.textContent).toBe('（月结）');
  expect(document.querySelector('.analysis-close')!.textContent).not.toContain('摘要');
});

it('shows in plain view what was confirmed, what the manager still has to do and which files were replaced', async () => {
  const settled: CloseStatus = {
    headline: { state: 'ready_for_review', text: '可提交经理复核' }, blocking: [],
    blocks: [
      { key: 'scope', label: '范围', state: 'done', items: [{ text: '2026-01:2026-08 · 华宸物业 · 元 · CNY', blocking: false, target: 'scope' }] },
      { key: 'source', label: '来源', state: 'done', items: [
        { text: '月结', hint: '摘要 e3763c14568d', blocking: false, target: 'datasets' },
        { text: '另有 1 份旧版本已被更新的资料取代，只读保留', blocking: false }] },
      { key: 'structure', label: '结构', state: 'done', items: [{ text: '表头、明细范围和合计行已确认', blocking: false, target: 'structure' }] },
      { key: 'controls', label: '控制', state: 'done', items: [{ text: '已确认 1 条，相符 1 条', blocking: false, target: 'controls' }] },
      { key: 'exceptions', label: '异常', state: 'done', items: [{ text: '没有未处置的差异', blocking: false }] },
      { key: 'review', label: '复核', state: 'done', items: [{ text: '经理尚未复核（提交后由经理完成）', blocking: false, target: 'drafts' }] },
    ],
  };
  mount(settled);
  render(<MonthCloseControlCenter taskId="t" onOpen={vi.fn()} />);
  await screen.findByRole('heading', { name: '可提交经理复核' });
  const [line] = Array.from(document.querySelectorAll('.analysis-close-settled'));
  expect(visible(line)).toBe('已就绪：范围（2026-01:2026-08 · 华宸物业 · 元 · CNY）、来源（另有 1 份旧版本已被更新的资料取代，只读保留）、结构、控制、异常、复核（经理尚未复核（提交后由经理完成））');
  expect(screen.getByTitle('表头、明细范围和合计行已确认').textContent).toBe('结构');
  expect(screen.queryByRole('listitem', { name: /已就绪/ })).toBeNull();
});

it('words the confirmed period from the values the server gives, and shows an older answer as its text', async () => {
  const withScope = (item: Record<string, unknown>): CloseStatus => ({
    headline: { state: 'ready_for_review', text: '可提交经理复核' }, blocking: [],
    blocks: [{ key: 'scope', label: '范围', state: 'done', items: [{ blocking: false, target: 'scope', ...item } as CloseStatus['blocks'][number]['items'][number]] }],
  });
  mount(withScope({ text: '2026-01:2026-08 · 华宸 · 万元 · CNY',
    scope: { period: '2026-01:2026-08', organization: '华宸', unit: '万元', currency: 'CNY' } }));
  const { unmount } = render(<MonthCloseControlCenter taskId="t" onOpen={vi.fn()} />);
  await screen.findByRole('heading', { name: '可提交经理复核' });
  expect(visible(document.querySelector('.analysis-close-settled')!)).toBe('已就绪：范围（2026 年 1–8 月 · 华宸 · 万元 · CNY）');
  unmount();

  mount(withScope({ text: '2026-08 · 万元 · CNY' }));
  render(<MonthCloseControlCenter taskId="t" onOpen={vi.fn()} />);
  await screen.findByRole('heading', { name: '可提交经理复核' });
  expect(visible(document.querySelector('.analysis-close-settled')!)).toBe('已就绪：范围（2026-08 · 万元 · CNY）');
});

it('lists every row of a 请留意 card and gives it no 去处理, and marks a note on a 待处理 card', async () => {
  const noted: CloseStatus = {
    ...status,
    blocks: status.blocks.map((block) => block.key === 'exceptions'
      ? { ...block, state: 'attention', items: [{ text: '坏账分项：已接受差异（已知）', blocking: false, attention: true, target: 'controls' },
        { text: '税金：已接受差异（尾差）', blocking: false, attention: true, target: 'controls' }] }
      : block.key === 'review'
        ? { ...block, state: 'blocked', items: [{ text: '还没有文稿', blocking: true, target: 'drafts' },
          { text: '最近一次计算没有成功', blocking: false, attention: true, target: 'results' }] }
        : block),
  };
  mount(noted);
  render(<MonthCloseControlCenter taskId="t" onOpen={vi.fn()} />);
  const exceptions = await screen.findByRole('listitem', { name: '5 异常：请留意' });
  expect(Array.from(exceptions.querySelectorAll(':scope > ul > li')).map((row) => row.textContent))
    .toEqual(['坏账分项：已接受差异（已知）', '税金：已接受差异（尾差）']);
  expect(within(exceptions).queryByRole('button', { name: '去处理' })).toBeNull();
  const review = screen.getByRole('listitem', { name: '6 复核：待处理' });
  expect(Array.from(review.querySelectorAll(':scope > ul > li')).map((row) => row.textContent)).toEqual(['还没有文稿']);
  expect(within(review).getByText('请留意：最近一次计算没有成功').closest('ul')).toBeNull();
});

it('reads top down: headline, 下一步, open cards, settled lines, conclusion, then the tie-out controls', async () => {
  mount({ ...status, conclusion: { level: 'not_assessable', text: '无法判断', reasons: [{ text: '期间未确认' }] } });
  render(<MonthCloseControlCenter taskId="t" onOpen={vi.fn()} />);
  const conclusion = await screen.findByRole('region', { name: '套表可用结论' });
  const order = [
    screen.getByRole('heading', { name: '尚未准备：还有 2 项待处理' }),
    screen.getByText('下一步：期间未确认'),
    document.querySelector('.analysis-close-blocks')!,
    ...Array.from(document.querySelectorAll('.analysis-close-settled')),
    conclusion,
    screen.getByRole('region', { name: '勾稽控制' }),
  ];
  order.slice(1).forEach((element, index) => {
    expect(order[index].compareDocumentPosition(element) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
  // 无法判断 is not a help mark.
  expect(conclusion.querySelector('.analysis-close-conclusion-head svg')!.classList.contains('lucide-circle-dashed')).toBe(true);
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
  // Five reasons are all in view; only 按工作簿看 folds.
  const shown = conclusion.querySelector(':scope > ul')!;
  expect(Array.from(shown.querySelectorAll('li')).map((item) => item.textContent)).toEqual(reasons);
  const folds = Array.from(conclusion.querySelectorAll(':scope > details'));
  expect(folds).toHaveLength(1);
  const [books] = folds;
  expect(books.querySelector('summary')!.textContent).toBe('按工作簿看');
  expect(within(books as HTMLElement).getByText('银行流水.xlsx').parentElement!.textContent).toBe('银行流水.xlsx：无法判断');
  expect(conclusion.className).toContain('analysis-close-conclusion--not_usable');
  // Only the level word carries the warning colour; the label stays in ink.
  expect(conclusion.querySelector('h4 .analysis-close-conclusion-level')!.textContent).toBe('不可用');
  expect(conclusion.textContent).not.toMatch(/完成|通过/);
  // Only the headline is announced as status.
  expect(screen.getAllByRole('status')[0].textContent).toBe('需要复核：计算完成，但有 5 项来源冲突');
  // The guide sits beside the headline only.
  expect(within(conclusion).queryByRole('button', { name: /^使用指南：/ })).toBeNull();
  expect(screen.getByRole('button', { name: '使用指南：月结怎么走一遍' })).toBeTruthy();
});

it('leads with three of more than five reasons and folds the rest', async () => {
  const reasons = ['一', '二', '三', '四', '五', '六'].map((word) => `原因${word}`);
  mount({ ...status, conclusion: { level: 'not_assessable', text: '无法判断', reasons: reasons.map((text) => ({ text })) } });
  render(<MonthCloseControlCenter taskId="t" onOpen={vi.fn()} />);
  const conclusion = await screen.findByRole('region', { name: '套表可用结论' });
  expect(Array.from(conclusion.querySelectorAll(':scope > ul > li')).map((item) => item.textContent)).toEqual(reasons.slice(0, 3));
  const [more] = Array.from(conclusion.querySelectorAll(':scope > details'));
  expect(more.querySelector('summary')!.textContent).toBe('另外 3 条原因');
  expect(Array.from(more.querySelectorAll('li')).map((item) => item.textContent)).toEqual(reasons.slice(3));
});

it('gives no 依据 line when no control has been confirmed', async () => {
  mount({ ...status, conclusion: { level: 'not_assessable', text: '无法判断', reasons: [{ text: '还没有你确认的勾稽控制' }],
    basis: { confirmed: 0, passed: 0, waived: 0, open: 0 } } });
  render(<MonthCloseControlCenter taskId="t" onOpen={vi.fn()} />);
  const conclusion = await screen.findByRole('region', { name: '套表可用结论' });
  expect(within(conclusion).queryByText(/^依据：/)).toBeNull();
});

it('shows no conclusion when an older engine leaves it out, and a bare one without crashing', async () => {
  mount();
  render(<MonthCloseControlCenter taskId="t" onOpen={vi.fn()} />);
  await screen.findByRole('heading', { name: '尚未准备：还有 2 项待处理' });
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
