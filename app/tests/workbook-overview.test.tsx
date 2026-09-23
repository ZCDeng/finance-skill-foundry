// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { DatasetSnapshot } from '../src/bridge.js';
import { WorkbookOverview } from '../src/views/analysis/WorkbookOverview.js';

const taskId = 'a'.repeat(32);
const budget: DatasetSnapshot = {
  id: 'b'.repeat(32), task_id: taskId, schema_version: 1, created_at: '2026-09-23T00:00:00Z',
  name: '年度预算', kind: 'workbook', source_hash: 'c'.repeat(64), source_name: '年度预算.xlsx', metadata: {},
};
const close: DatasetSnapshot = { ...budget, id: 'd'.repeat(32), name: '月结', source_name: '月结.xlsx' };

afterEach(() => {
  cleanup();
  delete (globalThis as { foundry?: unknown }).foundry;
});

it('jumps from the workbook overview to an exact sheet and bounded range in two actions', async () => {
  const financeCall = vi.fn(async (_task: string, _command: string, spec: { sheet: string; range?: string }) => ({
    ok: true,
    value: {
      dataset_id: budget.id, source_hash: budget.source_hash, source_name: budget.source_name,
      sheet: spec.sheet, range: spec.range ?? 'A1:L40',
      bounds: { min_row: 36, min_col: 2, max_row: 39, max_col: 9 }, cells: [], warnings: [],
    },
  }));
  (globalThis as { foundry?: unknown }).foundry = {
    financeCall,
    analysisReadDataset: vi.fn(async (_task: string, datasetId: string) => ({ ok: true, value: {
      workbook: { sheets: datasetId === budget.id
        ? [{ name: '00·封面', rows: 20, columns: 7 }, { name: '01·年度预算总表', rows: 52, columns: 17 }]
        : [{ name: '01·应收账款', rows: 50, columns: 9 }] },
    } })),
  };

  render(<WorkbookOverview taskId={taskId} datasets={[budget, close]} />);
  await screen.findByText('工作簿总览 · 2 本 · 3 张工作表');
  fireEvent.change(screen.getByLabelText('快速定位工作表及区域'), { target: { value: '01·年度预算总表!B36:I39' } });
  fireEvent.click(screen.getByRole('button', { name: '定位区域' }));
  await waitFor(() => expect(financeCall).toHaveBeenLastCalledWith(taskId, 'workbook-range-preview', {
    dataset_id: budget.id, sheet: '01·年度预算总表', range: 'B36:I39',
  }));
  expect(screen.getByRole('region', { name: '工作簿区域预览 01·年度预算总表 B36:I39' })).toBeTruthy();
});

it('requires a workbook prefix when two sources contain the same sheet name', async () => {
  const financeCall = vi.fn(async (_task: string, _command: string, spec: { dataset_id: string; sheet: string; range?: string }) => ({
    ok: true,
    value: {
      dataset_id: spec.dataset_id, source_hash: budget.source_hash, source_name: budget.source_name,
      sheet: spec.sheet, range: spec.range ?? 'A1:L40',
      bounds: { min_row: 1, min_col: 1, max_row: 1, max_col: 1 }, cells: [], warnings: [],
    },
  }));
  (globalThis as { foundry?: unknown }).foundry = {
    financeCall,
    analysisReadDataset: vi.fn(async () => ({ ok: true, value: {
      workbook: { sheets: [{ name: '01·年度预算总表', rows: 52, columns: 17 }] },
    } })),
  };

  render(<WorkbookOverview taskId={taskId} datasets={[budget, close]} />);
  await screen.findByText('工作簿总览 · 2 本 · 2 张工作表');
  await waitFor(() => expect(financeCall).toHaveBeenCalled());
  const initialCalls = financeCall.mock.calls.length;
  fireEvent.change(screen.getByLabelText('快速定位工作表及区域'), { target: { value: '01·年度预算总表!B36:I39' } });
  fireEvent.click(screen.getByRole('button', { name: '定位区域' }));
  expect(screen.getByRole('alert').textContent).toContain('多个工作簿有同名工作表');
  expect(financeCall).toHaveBeenCalledTimes(initialCalls);

  fireEvent.change(screen.getByLabelText('快速定位工作表及区域'), { target: { value: '月结.xlsx/01·年度预算总表!B36:I39' } });
  fireEvent.click(screen.getByRole('button', { name: '定位区域' }));
  await waitFor(() => expect(financeCall).toHaveBeenLastCalledWith(taskId, 'workbook-range-preview', {
    dataset_id: close.id, sheet: '01·年度预算总表', range: 'B36:I39',
  }));
});
