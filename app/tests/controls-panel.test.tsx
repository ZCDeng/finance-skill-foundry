// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { Bridge } from '../src/bridge.js';
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
  expect(await screen.findByText(/08·AR!D25:D30 合计 33780；08·AR!D31 合计 22125；差额 11655/)).toBeTruthy();
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
  const boxes = Array.from(group.querySelectorAll('input[type=checkbox]'));
  // The break is listed first and ticked; the passing one is not.
  expect((boxes[0] as HTMLInputElement).checked).toBe(true);
  expect((boxes[1] as HTMLInputElement).checked).toBe(false);
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
