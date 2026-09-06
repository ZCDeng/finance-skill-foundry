// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Answer, Bridge } from '../src/bridge.js';
import { RequirementsPanel, type AnalysisRequirementsRecord } from '../src/views/analysis/RequirementsPanel.js';

const taskId = 'a'.repeat(32);
const otherTaskId = 'b'.repeat(32);
const contextId = 'c'.repeat(32);
const current: AnalysisRequirementsRecord = {
  id: 'r-current-001',
  question: '解释本期利润差异并下钻利润',
  context_id: contextId,
  scope: { ledger: 'L1', organization: '华东', period: '2026-10', currency: 'CNY', unit: '万元' },
  bindings: { actual: 'actual-dataset', budget: 'budget-dataset' },
  items: [
    { id: 'profit', metric: 'profit', label: '利润', dimensions: { metric: 'profit' }, requires_drilldown: true },
    { id: 'expense', metric: 'expense', label: '费用', dimensions: { metric: 'expense' }, requires_drilldown: false },
  ],
  parent_id: null,
};

const ok = <T,>(value: T): Answer<T> => ({ ok: true, value });

function mountBridge(overrides: Partial<Bridge> = {}) {
  const api = {
    financeCall: vi.fn<NonNullable<Bridge['financeCall']>>(async () => ok({ requirements: [current], current })),
    ...overrides,
  } satisfies Partial<Bridge>;
  (globalThis as unknown as { foundry: Partial<Bridge> }).foundry = api;
  return api;
}

afterEach(() => {
  cleanup();
  delete (globalThis as unknown as { foundry?: Bridge }).foundry;
  vi.clearAllMocks();
});

describe('requirements panel', () => {
  it('loads the current requirements and saves a successor without running analysis', async () => {
    const saved: AnalysisRequirementsRecord = { ...current, id: 'r-current-002', parent_id: current.id, question: '解释利润和费用变化' };
    const onChanged = vi.fn();
    const api = mountBridge({
      financeCall: vi.fn<NonNullable<Bridge['financeCall']>>(async (_task, command) => command === 'analysis-requirements-save'
        ? ok(saved as unknown as Record<string, unknown>)
        : ok({ requirements: [current], current })),
    });
    render(<RequirementsPanel taskId={taskId} contextId={contextId} onChanged={onChanged} />);

    expect(await screen.findByDisplayValue('解释本期利润差异并下钻利润')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('用户问题'), { target: { value: '解释利润和费用变化' } });
    fireEvent.change(screen.getByLabelText('组织'), { target: { value: '华南' } });
    fireEvent.click(screen.getByRole('button', { name: /保存要求新版/ }));

    await waitFor(() => expect(api.financeCall).toHaveBeenCalledWith(taskId, 'analysis-requirements-save', expect.objectContaining({
      question: '解释利润和费用变化',
      context_id: contextId,
      parent_id: current.id,
      bindings: current.bindings,
      scope: expect.objectContaining({ organization: '华南', period: '2026-10', currency: 'CNY', unit: '万元' }),
      items: expect.arrayContaining([expect.objectContaining({ id: 'profit', requires_drilldown: true })]),
    })));
    expect(api.financeCall).not.toHaveBeenCalledWith(taskId, 'analysis-run', expect.anything());
    expect(api.financeCall).not.toHaveBeenCalledWith(taskId, 'run-metric', expect.anything());
    expect(onChanged).toHaveBeenCalledWith(expect.objectContaining(saved));
    expect(await screen.findByText(/保存不会自动计算或批准文稿/)).toBeTruthy();
  });

  it('requires a change reason before removing an existing obligation', async () => {
    const saved: AnalysisRequirementsRecord = {
      ...current,
      id: 'r-current-003',
      parent_id: current.id,
      items: [current.items[1]],
      removed_item_ids: ['profit'],
      change_reason: '经理改为只看费用。',
    };
    const api = mountBridge({
      financeCall: vi.fn<NonNullable<Bridge['financeCall']>>(async (_task, command) => command === 'analysis-requirements-save'
        ? ok(saved as unknown as Record<string, unknown>)
        : ok({ requirements: [current], current })),
    });
    render(<RequirementsPanel taskId={taskId} />);
    await screen.findByDisplayValue('解释本期利润差异并下钻利润');

    const profit = screen.getByLabelText('必答指标 1');
    fireEvent.click(within(profit).getByRole('button', { name: /删除要求/ }));
    const save = screen.getByRole('button', { name: /保存要求新版/ });
    expect((save as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText('删要求必须写明变更原因。')).toBeTruthy();

    fireEvent.change(screen.getByLabelText('删除要求的变更原因'), { target: { value: '经理改为只看费用。' } });
    fireEvent.click(save);
    await waitFor(() => expect(api.financeCall).toHaveBeenCalledWith(taskId, 'analysis-requirements-save', expect.objectContaining({
      change_reason: '经理改为只看费用。',
      items: [expect.objectContaining({ id: 'expense' })],
    })));
  });

  it('keeps invalid dimension JSON inline and blocks save', async () => {
    const api = mountBridge();
    render(<RequirementsPanel taskId={taskId} />);
    await screen.findByDisplayValue('解释本期利润差异并下钻利润');

    fireEvent.change(screen.getByLabelText('维度 JSON 1'), { target: { value: '{bad json' } });

    expect(await screen.findByText('维度必须是 JSON object。')).toBeTruthy();
    expect(screen.getByText('请先修正维度 JSON，再保存要求新版。')).toBeTruthy();
    expect((screen.getByRole('button', { name: /保存要求新版/ }) as HTMLButtonElement).disabled).toBe(true);
    expect(api.financeCall).not.toHaveBeenCalledWith(taskId, 'analysis-requirements-save', expect.anything());
  });

  it('shows when an opened draft belongs to an older requirements version', async () => {
    mountBridge();
    render(<RequirementsPanel taskId={taskId} draftRequirementsId="r-old-draft" />);
    expect(await screen.findByText(/范围已变/)).toBeTruthy();
    expect(screen.getByText(/r-current-001/)).toBeTruthy();
    expect(screen.getByText(/r-old-draft/)).toBeTruthy();
  });

  it('does not let a delayed list response from a previous task overwrite the current task', async () => {
    let finish!: (value: Answer<Record<string, unknown>>) => void;
    const other: AnalysisRequirementsRecord = {
      ...current,
      id: 'r-other-001',
      question: '西南回款账龄分析',
      scope: { ledger: 'L2', organization: '西南', period: '2026-11', currency: 'CNY', unit: '万元' },
      items: [{ id: 'open', metric: 'open_amount', label: '应收余额', dimensions: {}, requires_drilldown: true }],
    };
    mountBridge({
      financeCall: vi.fn<NonNullable<Bridge['financeCall']>>((task) => task === taskId
        ? new Promise<Answer<Record<string, unknown>>>((resolve) => { finish = resolve; })
        : Promise.resolve(ok({ requirements: [other], current: other }))),
    });
    const { rerender } = render(<RequirementsPanel taskId={taskId} />);
    rerender(<RequirementsPanel taskId={otherTaskId} />);

    expect(await screen.findByDisplayValue('西南回款账龄分析')).toBeTruthy();
    await act(async () => finish(ok({ requirements: [current], current })));
    expect(screen.queryByDisplayValue('解释本期利润差异并下钻利润')).toBeNull();
    expect(screen.getByDisplayValue('西南回款账龄分析')).toBeTruthy();
  });

  it('loads context scope without guessing currency or unit and omits cleared scope fields on save', async () => {
    const seeded = {
      id: contextId,
      name: '日本子公司口径',
      bindings: { actual: 'jp-actual' },
      scopes: { actual: { ledger: 'JP-GL', organization: '东京', period: '2026-12', currency: 'JPY', unit: '千元' } },
    };
    const saved: AnalysisRequirementsRecord = {
      id: 'r-jp-001',
      question: '分析日本子公司费用',
      context_id: contextId,
      scope: { ledger: 'JP-GL', period: '2026-12', currency: 'JPY', unit: '千元' },
      bindings: { actual: 'jp-actual' },
      items: [{ id: 'req_1', metric: 'expense', label: '费用', dimensions: {}, requires_drilldown: false }],
      parent_id: null,
    };
    const api = mountBridge({
      financeCall: vi.fn<NonNullable<Bridge['financeCall']>>(async (_task, command, spec) => {
        if (command === 'analysis-requirements-list') return ok({ requirements: [], current: null });
        if (command === 'list-finance-context') return ok({ task_id: taskId, datasets: [], contexts: [seeded], account_maps: [], scenarios: [], metric_definitions: [], capabilities: [] });
        if (command === 'analysis-requirements-save') return ok({ ...saved, scope: spec?.scope, question: spec?.question, items: spec?.items } as Record<string, unknown>);
        return ok({});
      }),
    });
    render(<RequirementsPanel taskId={taskId} contextId={contextId} />);

    expect(await screen.findByText(/JPY/)).toBeTruthy();
    expect(screen.getByText(/千元/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText('用户问题'), { target: { value: '分析日本子公司费用' } });
    fireEvent.change(screen.getByLabelText('组织'), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: /添加指标/ }));
    fireEvent.click(screen.getByRole('button', { name: /保存要求新版/ }));

    await waitFor(() => expect(api.financeCall).toHaveBeenCalledWith(taskId, 'analysis-requirements-save', expect.objectContaining({
      context_id: contextId,
      bindings: { actual: 'jp-actual' },
      scope: expect.not.objectContaining({ organization: '' }),
    })));
    const saveCall = vi.mocked(api.financeCall).mock.calls.find(([, command]) => command === 'analysis-requirements-save');
    expect(saveCall?.[2]?.scope).toEqual(expect.objectContaining({ ledger: 'JP-GL', period: '2026-12', currency: 'JPY', unit: '千元' }));
    expect(saveCall?.[2]?.scope).not.toHaveProperty('organization');
  });

  it('passes the edited working scope to the discussion callback', async () => {
    const onDiscuss = vi.fn();
    mountBridge();
    render(<RequirementsPanel taskId={taskId} draftRequirementsId={current.id} onDiscuss={onDiscuss} />);
    await screen.findByDisplayValue('解释本期利润差异并下钻利润');
    fireEvent.change(screen.getByLabelText('期间'), { target: { value: '2026-11' } });
    fireEvent.click(screen.getByRole('button', { name: /与助手讨论范围/ }));

    expect(onDiscuss).toHaveBeenCalledWith(expect.objectContaining({
      question: '解释本期利润差异并下钻利润',
      currentRequirementsId: current.id,
      draftRequirementsId: current.id,
      scope: expect.objectContaining({ period: '2026-11' }),
      items: expect.arrayContaining([expect.objectContaining({ id: 'profit' })]),
    }));
  });
});
