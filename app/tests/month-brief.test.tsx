// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AnalysisRun, BriefLine, Bridge, MonthBrief as Brief } from '../src/bridge.js';
import { MonthBrief, partsOf } from '../src/views/analysis/MonthBrief.js';
import type { Dashboard, DashboardCard } from '../src/views/analysis/dashboardModel.js';
import { ASK_EVENT, ASK_PROMPTS } from '../src/views/guide/ask.js';
import { TASK_CHANGED_EVENT } from '../src/views/guide/QuickStartChecklist.js';
import fixture from './fixtures/collection-health-run.json';

// A collection_health run on a property group's dashboard and ten city companies of its 11·城市公司明细表.
const health = fixture as unknown as AnalysisRun;

afterEach(() => { cleanup(); delete (globalThis as { foundry?: unknown }).foundry; });

const gap: DashboardCard = {
  id: 'c1', kind: 'figure', title: '集团距生死线', state: 'pinned', run_id: health.id, template: 'collection', note: null, proposed_by: 'manager', accepted: null,
  select: { match: { entity: '集团', metric_key: 'collection_gap', scenario: '本期' }, column: 'value' },
  recomputed: {
    at: '2026-10-10T09:00:00Z', from_run_id: 'f'.repeat(32), was_accepted: true, months: ['2026-08', '2026-09'],
    before: { value: '-2.10', display: '-2.10 个百分点', level: 'red', unit: '百分点' },
    after: { value: '-3.22', display: '-3.22 个百分点', level: 'red', unit: '百分点' },
    changed: true, change: '-1.12 个百分点', adjusted: [], manual: [], carried_from: { task_id: 't'.repeat(32), title: '华宸物业 8 月月结' },
  },
};
const board: Dashboard = { id: 'v1', parent_id: null, created_at: '2026-10-10T09:00:00Z', cards: [gap] };

const lines: BriefLine[] = [
  { key: 'change', label: '变化', parts: [
    { text: '「集团距生死线」从 ' }, { text: '-2.10 个百分点', ref: { kind: 'card_before', card_id: 'c1' } }, { text: ' 变为 ' },
    { text: '-3.22 个百分点', ref: { kind: 'card', card_id: 'c1' } }, { text: '，变动 ' }, { text: '-1.12 个百分点', ref: { kind: 'card_change', card_id: 'c1' } },
    { text: '。' }], text: '「集团距生死线」从 -2.10 个百分点 变为 -3.22 个百分点，变动 -1.12 个百分点。' },
  { key: 'risk', label: '风险', parts: [
    { text: '兰州城市公司风险雷达 ' },
    { text: '3 分', ref: { kind: 'row', run_id: health.id, column: 'value', metric: '兰州城市公司风险雷达',
      match: { entity: '兰州城市公司', metric_key: 'risk_score', scenario: '本期', entity_origin: 'table' } } },
    { text: '（黄）。另有 ' }, { text: '3 个主体', ref: { kind: 'result', run_id: health.id } }, { text: '是黄色。' }],
  text: '兰州城市公司风险雷达 3 分（黄）。另有 3 个主体是黄色。' },
  { key: 'waiting', label: '等你拍板', parts: [
    { text: '2 件事', ref: { kind: 'open', target: 'close' } }, { text: '等你处理，先看：' },
    { text: '应收滚动：待外部确认，差额 1200', ref: { kind: 'open', target: 'controls' } }, { text: '。' }],
  text: '2 件事等你处理，先看：应收滚动：待外部确认，差额 1200。' },
];
const brief = (worded: Brief['worded'] = null): Brief => ({ schema_version: 1, lines, signature: 's'.repeat(64), worded });

function mount(answer: Brief) {
  const financeCall = vi.fn(async () => ({ ok: true as const, value: answer }));
  (globalThis as { foundry?: Partial<Bridge> }).foundry = { financeCall: financeCall as unknown as Bridge['financeCall'] };
  const onOpen = vi.fn();
  const onOpenResult = vi.fn();
  render(<MonthBrief taskId="t1" refreshKey="1" board={board} runs={[health]} analyses={[]} datasets={[]} superseded={[]}
    onOpen={onOpen} onOpenResult={onOpenResult} />);
  return { financeCall, onOpen, onOpenResult };
}

describe('本月三句话', () => {
  it('draws the three lines with every figure opening to its source and every link to its place', async () => {
    const { financeCall, onOpen, onOpenResult } = mount(brief());
    const list = await screen.findByRole('list');
    expect(financeCall).toHaveBeenCalledWith('t1', 'month-brief');
    expect(within(list).getAllByRole('listitem').map((item) => item.textContent)).toEqual([
      expect.stringMatching(/^变化「集团距生死线」从/), expect.stringMatching(/^风险兰州城市公司风险雷达/), expect.stringMatching(/^等你拍板2 件事等你处理/)]);
    // The risk figure opens the row it was read from, as the board's figures do.
    fireEvent.click(screen.getByRole('button', { name: /兰州城市公司风险雷达.*3 分，查看来源/ }));
    const source = await screen.findByRole('dialog', { name: '兰州城市公司风险雷达本期的来源' });
    expect(within(source).getByText('兰州城市公司')).toBeTruthy();
    fireEvent.keyDown(source, { key: 'Escape' });
    fireEvent.click(screen.getByRole('button', { name: '2 件事，到「勾稽」处理' }));
    fireEvent.click(screen.getByRole('button', { name: '应收滚动：待外部确认，差额 1200，到「勾稽」的勾稽控制' }));
    expect(onOpen.mock.calls).toEqual([['close'], ['controls']]);
    fireEvent.click(screen.getByRole('button', { name: '3 个主体，打开这次计算的结果' }));
    expect(onOpenResult).toHaveBeenCalledWith(health);
  });

  it('opens the card as it shows now, as it showed before it was run again, and the change between', async () => {
    mount(brief());
    await screen.findByRole('list');
    fireEvent.click(screen.getByRole('button', { name: /集团距生死线重算前 -2.10 个百分点，查看来源/ }));
    let source = await screen.findByRole('dialog', { name: '集团距生死线重算前的来源' });
    expect(within(source).getByText('「华宸物业 8 月月结」的看板')).toBeTruthy();
    expect(within(source).getByText('2026 年 8 月 → 2026 年 9 月')).toBeTruthy();
    fireEvent.keyDown(source, { key: 'Escape' });
    fireEvent.click(screen.getByRole('button', { name: /集团距生死线较重算前 -1.12 个百分点，查看来源/ }));
    source = await screen.findByRole('dialog', { name: '集团距生死线较重算前的来源' });
    expect(within(source).getAllByRole('definition').slice(0, 2).map((row) => row.textContent)).toEqual(['-2.10 个百分点', '-3.22 个百分点']);
    fireEvent.keyDown(source, { key: 'Escape' });
    expect(screen.getByRole('button', { name: /集团距生死线本期 -3.22 个百分点，查看来源/ })).toBeTruthy();
  });

  it('shows the assistant\'s wording with the same links, and the rule\'s own line a click away', async () => {
    const worded = '先处理「应收滚动：待外部确认，差额 1200」，一共 2 件事等你拍板。';
    const { onOpen } = mount(brief({ lines: { waiting: worded }, by: 'assistant', created_at: '2026-10-10T09:00:00Z' }));
    const item = (await screen.findAllByRole('listitem'))[2];
    expect(item.textContent).toBe(`等你拍板${worded}`);
    fireEvent.click(within(item).getByRole('button', { name: '2 件事，到「勾稽」处理' }));
    expect(onOpen).toHaveBeenCalledWith('close');
    expect(screen.getByText(/措辞由助手改过，数和能点开的部分没改。/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '看原句' }));
    expect(screen.getAllByRole('listitem')[2].textContent).toBe(`等你拍板${lines[2].text}`);
    const asked = vi.fn();
    window.addEventListener(ASK_EVENT, asked);
    fireEvent.click(screen.getByRole('button', { name: '让助手改措辞' }));
    window.removeEventListener(ASK_EVENT, asked);
    expect((asked.mock.calls[0][0] as CustomEvent).detail).toBe(ASK_PROMPTS['month-brief']);
  });

  it('reads the lines again when the task says it changed, as when the assistant has just reworded one', async () => {
    const worded = '先处理「应收滚动：待外部确认，差额 1200」，一共 2 件事等你拍板。';
    const { financeCall } = mount(brief());
    expect((await screen.findAllByRole('listitem'))[2].textContent).toBe(`等你拍板${lines[2].text}`);
    financeCall.mockResolvedValue({ ok: true, value: brief({ lines: { waiting: worded }, by: 'assistant', created_at: '2026-10-10T09:05:00Z' }) });
    await act(async () => { window.dispatchEvent(new Event(TASK_CHANGED_EVENT)); });
    expect(financeCall).toHaveBeenCalledTimes(2);
    expect(screen.getAllByRole('listitem')[2].textContent).toBe(`等你拍板${worded}`);
  });

  it('falls back to the rule\'s line when a wording lost a figure, and says when it cannot be read', async () => {
    expect(partsOf(lines[2], '有两件事等你处理。')).toBe(lines[2].parts);
    expect(partsOf(lines[1], '兰州最高，3 分；另外 3 个主体也是黄色。').map((part) => part.text))
      .toEqual(['兰州最高，', '3 分', '；另外 ', '3 个主体', '也是黄色。']);
    (globalThis as { foundry?: Partial<Bridge> }).foundry = {
      financeCall: vi.fn(async () => ({ ok: false as const, message: 'no task' })) as unknown as Bridge['financeCall'],
    };
    render(<MonthBrief taskId="t1" refreshKey="1" board={null} runs={[]} analyses={[]} datasets={[]} superseded={[]} onOpen={vi.fn()} onOpenResult={vi.fn()} />);
    expect(await screen.findByText('本月三句话暂时读不出：no task')).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
  });
});
