// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { Bridge } from '../src/bridge.js';
import { PreferencesProvider } from '../src/components/Preferences.js';
import { ControlsPanel } from '../src/views/analysis/ControlsPanel.js';
import type { ControlList, ControlRow } from '../src/views/analysis/controls.js';

afterEach(() => { cleanup(); delete (globalThis as { foundry?: Partial<Bridge> }).foundry; });

const side = (range: string, value: string) => ({ dataset_id: 'd1', source_hash: 'h', sheet: '08·AR', range, scale: '1', value });
const control = { kind: 'subtotal' as const, label: '坏账分项', left: side('D25:D30', ''), right: side('D31', ''), tolerance: '0' };
const broken: ControlRow = {
  id: 'c1', state: 'confirmed', control,
  result: { status: 'break', difference: '11655', left: side('D25:D30', '33780'), right: side('D31', '22125') },
  issue: { state: 'open', blocking: true },
};
const listOf = (rows: ControlRow[], requireReview = false): ControlList => ({
  controls: rows, settings: { require_second_review: requireReview },
  summary: { controls: rows.length, confirmed: rows.length, pass: 0, break: 1, stale: 0, error: 0, blocking: rows.filter((row) => row.issue?.blocking).length },
});
const mount = (handler: (command: string, spec: unknown) => unknown) => {
  const financeCall = vi.fn(async (_task: string, command: string, spec?: unknown) => ({ ok: true, value: handler(command, spec) }));
  (globalThis as { foundry?: Partial<Bridge> }).foundry = { financeCall: financeCall as unknown as Bridge['financeCall'] };
  return financeCall;
};

it('shows where each side was read and that the difference holds the close', async () => {
  mount(() => listOf([broken]));
  render(<ControlsPanel taskId="t" />);
  expect(await screen.findByText(/08·AR!D25:D30 合计 33,780；08·AR!D31 合计 22,125；差额 11,655/)).toBeTruthy();
  expect(screen.getByText('待处理')).toBeTruthy();
  expect(screen.getByText(/挡住月结 1 项/)).toBeTruthy();
});

it('will not save an acceptance without a reason, and sends the reason when given', async () => {
  const calls = mount((command) => command === 'finance-controls-list' ? listOf([broken]) : {});
  render(<ControlsPanel taskId="t" />);
  fireEvent.click(await screen.findByLabelText('接受差异并说明'));
  const save = screen.getByRole('button', { name: '保存处置' }) as HTMLButtonElement;
  expect(save.disabled).toBe(true);
  fireEvent.change(screen.getByLabelText('说明'), { target: { value: '总计与总账一致' } });
  expect(save.disabled).toBe(false);
  fireEvent.click(save);
  await waitFor(() => expect(calls).toHaveBeenCalledWith('t', 'finance-control-disposition-save', { control_id: 'c1', decision: 'waived', reason: '总计与总账一致' }));
});

it('asks who confirms a difference sent out for confirmation', async () => {
  mount((command) => command === 'finance-controls-list' ? listOf([broken]) : {});
  render(<ControlsPanel taskId="t" />);
  fireEvent.click(await screen.findByLabelText('待外部确认'));
  fireEvent.change(screen.getByLabelText('说明'), { target: { value: '请确认计提比例' } });
  expect((screen.getByRole('button', { name: '保存处置' }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.change(screen.getByLabelText('由谁确认'), { target: { value: '账套编制方' } });
  expect((screen.getByRole('button', { name: '保存处置' }) as HTMLButtonElement).disabled).toBe(false);
});

it('offers differences first among suggestions and confirms only the ticked ones', async () => {
  const pass = { control: { ...control, label: '欠费余额' }, preview: { status: 'pass' as const } };
  const brk = { control, preview: { status: 'break' as const, difference: '11655' } };
  const calls = mount((command) => command === 'finance-controls-propose' ? { suggestions: [pass, brk] } : command === 'finance-controls-list' ? listOf([]) : {});
  render(<ControlsPanel taskId="t" />);
  fireEvent.click(await screen.findByRole('button', { name: /找建议控制/ }));
  const group = (await screen.findByText('建议的控制（勾选要确认的）')).closest('fieldset')!;
  const boxes = Array.from(group.querySelectorAll('[role=checkbox]'));
  // The break is listed first and ticked; the passing one is not.
  expect(boxes[0].getAttribute('aria-checked')).toBe('true');
  expect(boxes[1].getAttribute('aria-checked')).toBe('false');
  fireEvent.click(screen.getByRole('button', { name: /确认选中的 1 条/ }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith('t', 'finance-controls-save', { controls: [control], origin: 'suggested', confirm: true }));
});

it('copies the confirmation sheet for the person who compiled the books', async () => {
  const writeText = vi.fn(async () => undefined);
  Object.assign(navigator, { clipboard: { writeText } });
  mount((command) => command === 'finance-control-confirmation-sheet' ? { count: 1, markdown: '# 勾稽差异确认', tsv: '序号' } : listOf([broken]));
  render(<ControlsPanel taskId="t" />);
  fireEvent.click(await screen.findByRole('button', { name: /复制确认单/ }));
  await waitFor(() => expect(writeText).toHaveBeenCalledWith('# 勾稽差异确认'));
  expect(await screen.findByText(/已复制确认单（1 项）/)).toBeTruthy();
});

it('asks for a reviewer when an accepted difference waits on a second person', async () => {
  const waiting: ControlRow = { ...broken, issue: { state: 'awaiting_review', blocking: true, disposition: { id: 'p1', decision: 'waived', reason: '已知', decided_by_name: '张会计' } } };
  const calls = mount((command) => command === 'finance-controls-list' ? listOf([waiting], true) : {});
  render(<ControlsPanel taskId="t" />);
  fireEvent.change(await screen.findByLabelText('复核人'), { target: { value: '李经理' } });
  fireEvent.click(screen.getByRole('button', { name: '复核通过' }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith('t', 'finance-control-disposition-review', { id: 'p1', reviewer: '李经理' }));
  expect(screen.queryByRole('button', { name: '保存处置' })).toBeNull();
});

it('offers only correction for a range that cannot be read', async () => {
  const unreadable: ControlRow = { ...broken, result: { status: 'error', reason: '08·AR!D25:D30 里有 1 个文字单元格，不能当作空白跳过' }, issue: { state: 'open', blocking: true } };
  mount(() => listOf([unreadable]));
  render(<ControlsPanel taskId="t" />);
  expect(await screen.findByLabelText('修正资料后重新导入')).toBeTruthy();
  expect(screen.queryByLabelText('接受差异并说明')).toBeNull();
});

it('lets an accepted difference be changed, and a stale control be retired with a reason', async () => {
  const waived: ControlRow = { ...broken, issue: { state: 'waived', blocking: false, disposition: { id: 'p1', decision: 'waived', reason: '已知' } } };
  const stale: ControlRow = { ...broken, id: 'c2', result: { status: 'stale', reason: '资料已有更新的版本' }, issue: { state: 'stale', blocking: true } };
  const calls = mount((command) => command === 'finance-controls-list' ? listOf([waived, stale]) : {});
  render(<ControlsPanel taskId="t" />);
  fireEvent.click(await screen.findByRole('button', { name: '改处置' }));
  expect(screen.getByLabelText('待外部确认')).toBeTruthy();
  const retire = screen.getByRole('button', { name: '停用这条控制' }) as HTMLButtonElement;
  expect(retire.disabled).toBe(true);
  fireEvent.change(screen.getByLabelText('停用原因'), { target: { value: '已换用修正后的资料' } });
  fireEvent.click(retire);
  await waitFor(() => expect(calls).toHaveBeenCalledWith('t', 'finance-controls-retire', { id: 'c2', reason: '已换用修正后的资料' }));
});

it('asks for the name of whoever accepts when a second review is required', async () => {
  mount(() => listOf([broken], true));
  render(<ControlsPanel taskId="t" />);
  fireEvent.click(await screen.findByLabelText('接受差异并说明'));
  fireEvent.change(screen.getByLabelText('说明'), { target: { value: '已知' } });
  const save = screen.getByRole('button', { name: '保存处置' }) as HTMLButtonElement;
  expect(save.disabled).toBe(true);
  fireEvent.change(screen.getByLabelText('你的姓名'), { target: { value: '张会计' } });
  expect(save.disabled).toBe(false);
});

it('lets the manager compare two places across workbooks, preview the gap, then confirm it', async () => {
  const sources = [
    { dataset_id: 'ledger', source_hash: 'h1', name: '合同台账.xlsx', sheets: ['11·物业服务合同台账'] },
    { dataset_id: 'close', source_hash: 'h2', name: '月结套表.xlsx', sheets: ['08·AR收缴率与欠费'] },
  ];
  const calls = mount((command, spec) => {
    if (command === 'finance-controls-list') return listOf([]);
    if (command === 'finance-controls-sources') return { sources };
    if (command === 'finance-controls-preview') {
      const drafted = (spec as { control: { left: object; right: object } }).control;
      return { control: drafted, preview: { status: 'break', difference: '-2793.2794',
        left: { ...drafted.left, value: '245726.6057' }, right: { ...drafted.right, value: '248519.8851' } } };
    }
    return {};
  });
  render(<ControlsPanel taskId="t" />);
  fireEvent.click(await screen.findByRole('button', { name: '添加两处取数对比' }));
  const check = await screen.findByRole('button', { name: '加总两处，看差额' }) as HTMLButtonElement;
  expect(check.disabled).toBe(true);
  fireEvent.change(await screen.findByLabelText('第一处工作簿'), { target: { value: 'ledger' } });
  fireEvent.change(screen.getByLabelText('第一处工作表'), { target: { value: '11·物业服务合同台账' } });
  fireEvent.change(screen.getByLabelText('第一处单元格'), { target: { value: 't605' } });
  fireEvent.change(screen.getByLabelText('第二处工作簿'), { target: { value: 'close' } });
  fireEvent.change(screen.getByLabelText('第二处工作表'), { target: { value: '08·AR收缴率与欠费' } });
  fireEvent.change(screen.getByLabelText('第二处单元格'), { target: { value: 'C11' } });
  expect(check.disabled).toBe(false);
  fireEvent.click(check);
  expect(await screen.findByText('差额 -2,793.2794 万元')).toBeTruthy();
  const control = {
    kind: 'tie_out', tolerance: '0', unit: '万元', label: '11·物业服务合同台账!T605 对 08·AR收缴率与欠费!C11',
    left: { dataset_id: 'ledger', source_hash: 'h1', sheet: '11·物业服务合同台账', range: 'T605', scale: '1' },
    right: { dataset_id: 'close', source_hash: 'h2', sheet: '08·AR收缴率与欠费', range: 'C11', scale: '1' },
  };
  expect(calls).toHaveBeenCalledWith('t', 'finance-controls-preview', { control });
  expect(calls.mock.calls.some(([, command]) => command === 'finance-controls-save')).toBe(false);
  fireEvent.click(screen.getByRole('button', { name: '确认并保存这条对比' }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith('t', 'finance-controls-save', { controls: [control], origin: 'declared', confirm: true }));
  await waitFor(() => expect(screen.queryByRole('button', { name: '确认并保存这条对比' })).toBeNull());
});

it('scales the side in the larger unit to the smaller one, never by a coefficient', async () => {
  const calls = mount((command, spec) => command === 'finance-controls-sources'
    ? { sources: [{ dataset_id: 'a', source_hash: 'h', name: 'a.xlsx', sheets: ['S'] }] }
    : command === 'finance-controls-preview' ? { control: (spec as { control: unknown }).control, preview: { status: 'pass', difference: '0' } } : listOf([]));
  render(<ControlsPanel taskId="t" />);
  fireEvent.click(await screen.findByRole('button', { name: '添加两处取数对比' }));
  for (const [title, unit, cell] of [['第一处', '万元', 'B2'], ['第二处', '元', 'C9']]) {
    fireEvent.change(await screen.findByLabelText(`${title}工作簿`), { target: { value: 'a' } });
    fireEvent.change(screen.getByLabelText(`${title}工作表`), { target: { value: 'S' } });
    fireEvent.change(screen.getByLabelText(`${title}单元格`), { target: { value: cell } });
    fireEvent.change(screen.getByLabelText(`${title}单位`), { target: { value: unit } });
  }
  fireEvent.click(screen.getByRole('button', { name: '加总两处，看差额' }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith('t', 'finance-controls-preview', { control: expect.objectContaining({
    unit: '元', left: expect.objectContaining({ scale: '10000' }), right: expect.objectContaining({ scale: '1' }) }) }));
});

it('reads a full-width range, refuses to keep a comparison it could not read, and reports a failed run after a save', async () => {
  let status = 'stale';
  let runFails = false;
  const calls = mount((command, spec) => {
    if (command === 'finance-controls-sources') return { sources: [{ dataset_id: 'a', source_hash: 'h', name: 'a.xlsx', sheets: ['S'] }] };
    if (command === 'finance-controls-preview') return { control: (spec as { control: unknown }).control, preview: { status, difference: '5', reason: '资料已有更新的版本' } };
    if (command === 'finance-controls-run' && runFails) throw new Error('run failed');
    return listOf([]);
  });
  render(<ControlsPanel taskId="t" />);
  fireEvent.click(await screen.findByRole('button', { name: '添加两处取数对比' }));
  for (const [title, cell] of [['第一处', 'ｂ5：b6'], ['第二处', 'C9']]) {
    fireEvent.change(await screen.findByLabelText(`${title}工作簿`), { target: { value: 'a' } });
    fireEvent.change(screen.getByLabelText(`${title}工作表`), { target: { value: 'S' } });
    fireEvent.change(screen.getByLabelText(`${title}单元格`), { target: { value: cell } });
  }
  fireEvent.click(screen.getByRole('button', { name: '加总两处，看差额' }));
  expect(await screen.findByText('这两处读不出可比较的合计，改选单元格后再加总。')).toBeTruthy();
  expect(screen.queryByRole('button', { name: '确认并保存这条对比' })).toBeNull();
  expect(calls).toHaveBeenCalledWith('t', 'finance-controls-preview', { control: expect.objectContaining({ left: expect.objectContaining({ range: 'B5:B6' }) }) });
  status = 'break'; runFails = true;
  fireEvent.change(screen.getByLabelText('第二处单元格'), { target: { value: 'C10' } });
  fireEvent.click(screen.getByRole('button', { name: '加总两处，看差额' }));
  fireEvent.click(await screen.findByRole('button', { name: '确认并保存这条对比' }));
  expect(await screen.findByText(/运行没有完成，请点「重新运行」/)).toBeTruthy();
  expect(screen.queryByRole('button', { name: '确认并保存这条对比' })).toBeNull();
});

it('offers the assistant suggestion as a suggestion and adopts it only when the manager says so', async () => {
  const suggested: ControlRow = { ...broken, finding: { set_by_manager: false, suggested_type: 'source_conflict', suggested_type_label: '来源矛盾', suggested_note: '台账与月结实收对不上' } };
  const calls = mount((command) => command === 'finance-controls-list' ? listOf([suggested]) : {});
  render(<ControlsPanel taskId="t" />);
  expect(await screen.findByText('助手建议：来源矛盾（台账与月结实收对不上）')).toBeTruthy();
  // A suggestion is not the type: nothing in the row header says so yet.
  expect(document.querySelector('[data-slot="badge"]')).toBeNull();
  expect(calls.mock.calls.some(([, command]) => command === 'finance-control-finding-save')).toBe(false);
  fireEvent.click(screen.getByRole('button', { name: '采用建议' }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith('t', 'finance-control-finding-save', { control_id: 'c1', finding_type: 'source_conflict', note: '台账与月结实收对不上' }));
});

it('lets the manager choose one of the five types, shows the decided one, and never asks for it before a disposition', async () => {
  const typed: ControlRow = { ...broken, finding: { set_by_manager: true, type: 'not_updated', type_label: '未更新' } };
  const calls = mount((command) => command === 'finance-controls-list' ? listOf([typed]) : {});
  render(<ControlsPanel taskId="t" />);
  await screen.findByText(/差额 11,655/);
  expect(document.querySelector('[data-slot="badge"]')?.textContent).toBe('问题类型：未更新');
  const save = screen.getByRole('button', { name: '保存问题类型' }) as HTMLButtonElement;
  expect(save.disabled).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: '问题类型' }));
  expect(screen.getAllByRole('option').map((option) => option.textContent)).toEqual([
    expect.stringMatching(/^公式或控制缺陷/), expect.stringMatching(/^来源矛盾/), expect.stringMatching(/^无依据假设/),
    expect.stringMatching(/^未更新/), expect.stringMatching(/^口径不同.*要列调节而不是改数/),
  ]);
  fireEvent.click(screen.getByRole('option', { name: /^口径不同/ }));
  fireEvent.change(screen.getByLabelText('类型说明（可选）'), { target: { value: '台账含税，月结不含税' } });
  fireEvent.click(save);
  await waitFor(() => expect(calls).toHaveBeenCalledWith('t', 'finance-control-finding-save', { control_id: 'c1', finding_type: 'basis_difference', note: '台账含税，月结不含税' }));
  // The disposition does not wait on a type.
  fireEvent.click(screen.getByLabelText('接受差异并说明'));
  fireEvent.change(screen.getByLabelText('说明'), { target: { value: '已知口径差' } });
  fireEvent.click(screen.getByRole('button', { name: '保存处置' }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith('t', 'finance-control-disposition-save', { control_id: 'c1', decision: 'waived', reason: '已知口径差' }));
});

it('says a type decided about another difference no longer applies', async () => {
  mount(() => listOf([{ ...broken, finding: { set_by_manager: false, outdated: true } }]));
  render(<ControlsPanel taskId="t" />);
  expect(await screen.findByText('之前定的问题类型针对的是另一笔差额，已不适用。')).toBeTruthy();
  expect(document.querySelector('[data-slot="badge"]')).toBeNull();
});

it('lets the manager turn down a suggestion and keep the type she decided', async () => {
  const both: ControlRow = { ...broken, finding: {
    set_by_manager: true, type: 'formula_control', type_label: '公式或控制缺陷', note: '合计公式漏了 D9',
    suggested_type: 'basis_difference', suggested_type_label: '口径不同', suggested_note: '台账含税',
  } };
  const calls = mount((command) => command === 'finance-controls-list' ? listOf([both]) : {});
  render(<ControlsPanel taskId="t" />);
  expect(await screen.findByText('助手建议：口径不同（台账含税）')).toBeTruthy();
  // Nothing in her own fields changed, so the only way to answer the suggestion is to say she keeps hers.
  expect((screen.getByRole('button', { name: '保存问题类型' }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: '保留我的类型' }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith('t', 'finance-control-finding-save', { control_id: 'c1', finding_type: 'formula_control', note: '合计公式漏了 D9' }));
});

it('offers keeping a type only when the manager has decided one', async () => {
  mount(() => listOf([{ ...broken, finding: { set_by_manager: false, suggested_type: 'not_updated', suggested_type_label: '未更新' } }]));
  render(<ControlsPanel taskId="t" />);
  expect(await screen.findByRole('button', { name: '采用建议' })).toBeTruthy();
  expect(screen.queryByRole('button', { name: '保留我的类型' })).toBeNull();
});

it('turns second review on from a labelled switch', async () => {
  const calls = mount((command) => command === 'finance-controls-list' ? listOf([broken]) : {});
  render(<ControlsPanel taskId="t" />);
  const toggle = await screen.findByRole('switch', { name: '接受差异后需要第二人复核' });
  expect(toggle.getAttribute('aria-checked')).toBe('false');
  fireEvent.click(screen.getByText('接受差异后需要第二人复核'));
  await waitFor(() => expect(calls).toHaveBeenCalledWith('t', 'finance-control-settings-save', { require_second_review: true }));
});

it('signs a disposition and offers the review with the current person\'s 署名, never as the reviewer of their own acceptance', async () => {
  const people = [{ id: 'p1', name: '张三', role: 'manager' as const, signature: '财务部 张三' }];
  const calls = mount((command) => command === 'finance-controls-list' ? listOf([broken]) : {});
  const foundry = (globalThis as { foundry?: Partial<Bridge> }).foundry!;
  Object.assign(foundry, {
    preferencesGet: vi.fn(async () => ({ ok: true, value: { technical: false, brief_open: true, start: 'overview', samples_read: [], skipped_steps: {}, people, current_person: 'p1' } })),
    preferencesSet: vi.fn(),
  });
  const { unmount } = render(<PreferencesProvider><ControlsPanel taskId="t" /></PreferencesProvider>);
  fireEvent.click(await screen.findByLabelText('接受差异并说明'));
  fireEvent.change(screen.getByLabelText('说明'), { target: { value: '已知' } });
  // Filled in, and still the manager's to change.
  await waitFor(() => expect((screen.getByLabelText('你的姓名') as HTMLInputElement).value).toBe('财务部 张三'));
  fireEvent.click(screen.getByRole('button', { name: '保存处置' }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith('t', 'finance-control-disposition-save', { control_id: 'c1', decision: 'waived', reason: '已知', decided_by_name: '财务部 张三' }));
  unmount();

  const waiting = (by: string): ControlRow => ({ ...broken, issue: { state: 'awaiting_review', blocking: true, disposition: { id: 'd1', decision: 'waived', reason: '已知', decided_by_name: by } } });
  mount((command) => command === 'finance-controls-list' ? listOf([waiting('张会计')], true) : {});
  Object.assign((globalThis as { foundry?: Partial<Bridge> }).foundry!, { preferencesGet: foundry.preferencesGet, preferencesSet: vi.fn() });
  const second = render(<PreferencesProvider><ControlsPanel taskId="t" /></PreferencesProvider>);
  expect(await screen.findByText(/处置人 张会计/)).toBeTruthy();
  await waitFor(() => expect((screen.getByLabelText('复核人') as HTMLInputElement).value).toBe('财务部 张三'));
  second.unmount();

  mount((command) => command === 'finance-controls-list' ? listOf([waiting('财务部 张三')], true) : {});
  Object.assign((globalThis as { foundry?: Partial<Bridge> }).foundry!, { preferencesGet: foundry.preferencesGet, preferencesSet: vi.fn() });
  render(<PreferencesProvider><ControlsPanel taskId="t" /></PreferencesProvider>);
  expect(await screen.findByText(/处置人 财务部 张三/)).toBeTruthy();
  await waitFor(() => expect(foundry.preferencesGet).toHaveBeenCalledTimes(3));
  await act(async () => {});
  expect((screen.getByLabelText('复核人') as HTMLInputElement).value).toBe('');
});
