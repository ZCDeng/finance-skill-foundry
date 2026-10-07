// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ReportVisualComposer } from '../src/views/analysis/ReportVisualComposer.js';
import type { AnalysisRun } from '../src/bridge.js';

const task = 'a'.repeat(32);
const chartId = 'b'.repeat(32);
const runId = 'c'.repeat(32);
const ok = (value: unknown) => ({ ok: true, value });
const chart = { id: chartId, label: '已核算经营结果', run_id: runId, snapshot_hash: 'd'.repeat(64), series: { columns: [{ name: '项目', type: 'VARCHAR' }, { name: '金额', type: 'DECIMAL' }, { name: '预算', type: 'DECIMAL' }], rows: [{ 项目: '甲', 金额: '-3.50', 预算: '2.00' }, { 项目: '乙', 金额: '0', 预算: null }] } };
const runs = [{ id: runId, created_at: '2026-09-28T03:00:00Z', execution_status: 'succeeded' }] as AnalysisRun[];

afterEach(() => { cleanup(); delete (globalThis as unknown as { foundry?: unknown }).foundry; });
function api(call: (task: string, command: string, args: Record<string, unknown>) => Promise<unknown>) {
  (globalThis as unknown as { foundry: unknown }).foundry = { financeCall: vi.fn(call) };
}
function mount(props: Partial<React.ComponentProps<typeof ReportVisualComposer>> = {}) {
  const onApply = vi.fn(); const onCancel = vi.fn();
  const view = render(<ReportVisualComposer taskId={task} runs={[]} onApply={onApply} onCancel={onCancel} {...props} />);
  return { ...view, onApply, onCancel };
}

describe('report visual composer', () => {
  it('keeps an honest empty state and still permits an author supplied flow', async () => {
    api(async () => ok({ charts: [] }));
    const { onApply } = mount();
    expect(await screen.findByText(/还没有可用的计算结果/)).toBeTruthy();
    expect((screen.getByRole('button', { name: '插入文稿' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('图表类型'), { target: { value: 'flow' } });
    fireEvent.change(screen.getByLabelText('图表标题'), { target: { value: '回款流程' } });
    fireEvent.change(screen.getByLabelText('步骤 1'), { target: { value: '确认应收' } });
    fireEvent.change(screen.getByLabelText('步骤 2'), { target: { value: '回款核销' } });
    fireEvent.change(screen.getByLabelText('关系 1'), { target: { value: '完成对账后' } });
    fireEvent.click(screen.getByRole('button', { name: '插入文稿' }));
    expect(onApply).toHaveBeenCalledWith(expect.objectContaining({ kind: 'flow', title: '回款流程', takeaway: '', source_label: '作者分析', steps: [{ label: '确认应收', detail: '', connector: '完成对账后' }, { label: '回款核销', detail: '', connector: '' }] }));
  });

  it('opens an archived snapshot, requires explicit mapping and unit, and preserves exact values', async () => {
    api(async (_task, command) => ok(command === 'chart-deliverable-list' ? { charts: [chart] } : chart));
    const { onApply } = mount();
    await screen.findByRole('option', { name: /已核算经营结果/ });
    fireEvent.change(screen.getByLabelText('图表数据'), { target: { value: `chart:${chartId}` } });
    await screen.findByLabelText('类别列');
    fireEvent.change(screen.getByLabelText('图表标题'), { target: { value: '经营结果比较' } });
    fireEvent.change(screen.getByLabelText('类别列'), { target: { value: '项目' } });
    fireEvent.click(screen.getByLabelText('数值列 金额'));
    expect((screen.getByRole('button', { name: '插入文稿' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('图表单位'), { target: { value: '万元' } });
    expect(screen.getByLabelText('图表预览').querySelector('svg')).toBeTruthy();
    expect(screen.getByLabelText('图表原始数据').textContent).toContain('-3.50');
    fireEvent.click(screen.getByRole('button', { name: '插入文稿' }));
    expect(onApply).toHaveBeenCalledWith(expect.objectContaining({ chart_id: chartId, series: chart.series, value_columns: ['金额'], unit: '万元', takeaway: '' }));
  });

  it('archives a chosen successful run before reading its immutable chart', async () => {
    const call = vi.fn(async (_task: string, command: string) => ok(command === 'chart-deliverable-list' ? { charts: [] } : chart));
    api(call);
    mount({ runs });
    fireEvent.change(screen.getByLabelText('图表数据'), { target: { value: `run:${runId}` } });
    await screen.findByLabelText('类别列');
    expect(call).toHaveBeenCalledWith(task, 'chart-deliverable-save', expect.objectContaining({ run_id: runId }));
    expect(call).toHaveBeenCalledWith(task, 'chart-deliverable-open', { id: chartId });
  });

  it('uses the server report projection before JSON numbers lose integer precision', async () => {
    const record = {
      ...chart,
      series: { columns: chart.series.columns, rows: [{ 项目: Number('9007199254740993'), 金额: Number('9007199254740995'), 预算: 1 }] },
      report_series: { columns: chart.series.columns, rows: [{ 项目: '9007199254740993', 金额: '9007199254740995', 预算: '1.0' }] },
    };
    api(async (_task, command) => ok(command === 'chart-deliverable-list' ? { charts: [record] } : record));
    const { onApply } = mount();
    await screen.findByRole('option', { name: /已核算经营结果/ });
    fireEvent.change(screen.getByLabelText('图表数据'), { target: { value: `chart:${chartId}` } });
    await screen.findByLabelText('类别列');
    fireEvent.change(screen.getByLabelText('图表标题'), { target: { value: '金额原精度' } });
    fireEvent.change(screen.getByLabelText('类别列'), { target: { value: '项目' } });
    fireEvent.click(screen.getByLabelText('数值列 金额'));
    fireEvent.change(screen.getByLabelText('图表单位'), { target: { value: '万元' } });
    expect(screen.getByLabelText('图表原始数据').textContent).toContain('9007199254740993');
    expect(screen.getByLabelText('图表预览').textContent).toContain('9,007,199,254,740,995');
    fireEvent.click(screen.getByRole('button', { name: '插入文稿' }));
    expect(onApply).toHaveBeenCalledWith(expect.objectContaining({ series: record.report_series }));
  });

  it('does not display a previous task response after a task switch', async () => {
    let resolveOld: (value: unknown) => void = () => {};
    api(async (id, command) => id === task && command === 'chart-deliverable-list' ? new Promise((resolve) => { resolveOld = resolve; }) : ok({ charts: [] }));
    const view = mount();
    view.rerender(<ReportVisualComposer taskId={'e'.repeat(32)} runs={[]} onApply={view.onApply} onCancel={view.onCancel} />);
    await screen.findByText(/还没有可用的计算结果/);
    await act(async () => { resolveOld(ok({ charts: [chart] })); });
    await waitFor(() => expect(screen.queryByRole('option', { name: /已核算经营结果/ })).toBeNull());
  });

  it('ignores an obsolete open request when another source is selected', async () => {
    let resolveOld: (value: unknown) => void = () => {};
    const second = { ...chart, id: 'f'.repeat(32), label: '另一份结果', series: { columns: [{ name: '部门', type: 'VARCHAR' }, { name: '金额', type: 'DECIMAL' }], rows: [{ 部门: '丙', 金额: 9 }] } };
    api(async (_task, command, args) => {
      if (command === 'chart-deliverable-list') return ok({ charts: [chart, second] });
      if (args.id === chartId) return new Promise((resolve) => { resolveOld = resolve; });
      return ok(second);
    });
    mount();
    await screen.findByRole('option', { name: /已核算经营结果/ });
    fireEvent.change(screen.getByLabelText('图表数据'), { target: { value: `chart:${chartId}` } });
    fireEvent.change(screen.getByLabelText('图表数据'), { target: { value: `chart:${second.id}` } });
    await screen.findByRole('option', { name: '部门' });
    await act(async () => { resolveOld(ok(chart)); });
    await waitFor(() => expect(screen.queryByRole('option', { name: '项目' })).toBeNull());
  });

  it('cancels without inserting, and permits editing an existing visual without guessing data', async () => {
    api(async () => ok({ charts: [] }));
    const initial = { version: 1 as const, kind: 'flow' as const, title: '已有流程', takeaway: '', source_label: '作者分析', steps: [{ label: '第一步', detail: '', connector: '然后' }, { label: '第二步', detail: '', connector: '' }] };
    const { onApply, onCancel } = mount({ initial });
    expect((screen.getByLabelText('图表标题') as HTMLInputElement).value).toBe('已有流程');
    fireEvent.click(screen.getByRole('button', { name: '取消图表' }));
    expect(onApply).not.toHaveBeenCalled();
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it('rejects over-dense data without silently displaying a subset', async () => {
    const dense = { ...chart, series: { columns: chart.series.columns, rows: Array.from({ length: 13 }, (_, i) => ({ 项目: `部门 ${i + 1}`, 金额: i, 预算: 10 })) } };
    api(async (_task, command) => ok(command === 'chart-deliverable-list' ? { charts: [dense] } : dense));
    mount();
    await screen.findByRole('option', { name: /已核算经营结果/ });
    fireEvent.change(screen.getByLabelText('图表数据'), { target: { value: `chart:${chartId}` } });
    await screen.findByLabelText('类别列');
    fireEvent.change(screen.getByLabelText('图表标题'), { target: { value: '部门比较' } });
    fireEvent.change(screen.getByLabelText('类别列'), { target: { value: '项目' } });
    fireEvent.click(screen.getByLabelText('数值列 金额'));
    fireEvent.change(screen.getByLabelText('图表单位'), { target: { value: '万元' } });
    expect(screen.getByRole('alert').textContent).toMatch(/1–12 行/);
    expect(screen.getByLabelText('图表预览').querySelector('svg')).toBeNull();
    expect(screen.getByLabelText('图表原始数据').querySelectorAll('tbody tr')).toHaveLength(13);
    expect((screen.getByRole('button', { name: '插入文稿' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('retains an existing frozen chart while editing its title without fetching a new run', async () => {
    const call = vi.fn(async (_task: string, _command: string) => ok({ charts: [] }));
    api(call);
    const initial = { version: 1 as const, kind: 'bar' as const, title: '经营结果', takeaway: '', source_label: chart.label, chart_id: chart.id, run_id: chart.run_id, snapshot_hash: chart.snapshot_hash, series: chart.series, category: '项目', value_columns: ['金额'], unit: '万元' };
    const { onApply } = mount({ initial });
    fireEvent.change(screen.getByLabelText('图表标题'), { target: { value: '复核后的经营结果' } });
    fireEvent.click(screen.getByRole('button', { name: '更新图表' }));
    expect(onApply).toHaveBeenCalledWith({ ...initial, title: '复核后的经营结果' });
    expect(call.mock.calls.every((call) => call[1] === 'chart-deliverable-list')).toBe(true);
  });

  it('shows a source failure without retaining the old preview and allows retry', async () => {
    let failed = true;
    api(async (_task, command) => {
      if (command === 'chart-deliverable-list') return ok({ charts: [chart] });
      if (failed) throw new Error('归档图暂时不可用');
      return ok(chart);
    });
    mount();
    await screen.findByRole('option', { name: /已核算经营结果/ });
    fireEvent.change(screen.getByLabelText('图表数据'), { target: { value: `chart:${chartId}` } });
    expect((await screen.findByRole('alert')).textContent).toContain('归档图暂时不可用');
    expect(screen.queryByLabelText('类别列')).toBeNull();
    failed = false;
    fireEvent.change(screen.getByLabelText('图表数据'), { target: { value: '' } });
    fireEvent.change(screen.getByLabelText('图表数据'), { target: { value: `chart:${chartId}` } });
    expect(await screen.findByLabelText('类别列')).toBeTruthy();
  });
});
