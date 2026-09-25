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
    const saved: AnalysisRequirementsRecord = {
      ...current,
      id: 'r-current-002',
      parent_id: current.id,
      question: '解释利润和费用变化',
      items: current.items.map((item) => ({ ...item, periods: [] })),
      removed_item_ids: [],
      support: null,
    };
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

  it('does not seed a hierarchy level it cannot show from the context scope into the first save', async () => {
    // Review round 6: the context scope held drilldown, the panel has no field for it, and every save
    // resent it; the server refuses a newly written level. granularity is a scope field of its own and stays.
    const seeded = { id: contextId, name: '口径', bindings: { actual: 'ds' },
      scopes: { actual: { ledger: 'L1', organization: '华东', period: '2026-08', currency: 'CNY', unit: '万元', drilldown: '城市公司', granularity: '区域' } } };
    const api = mountBridge({
      financeCall: vi.fn<NonNullable<Bridge['financeCall']>>(async (_task, command, spec) => {
        if (command === 'analysis-requirements-list') return ok({ requirements: [], current: null });
        if (command === 'list-finance-context') return ok({ task_id: taskId, datasets: [], contexts: [seeded], account_maps: [], scenarios: [], metric_definitions: [], capabilities: [] });
        if (command === 'analysis-requirements-save') return ok({ id: 'r-ctx-001', question: spec?.question, context_id: contextId, scope: spec?.scope, bindings: spec?.bindings, items: spec?.items, parent_id: null } as Record<string, unknown>);
        return ok({});
      }),
    });
    render(<RequirementsPanel taskId={taskId} contextId={contextId} />);

    expect(await screen.findByText(/CNY/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText('用户问题'), { target: { value: '解释费用' } });
    fireEvent.click(screen.getByRole('button', { name: /添加指标/ }));
    fireEvent.click(screen.getByRole('button', { name: /保存要求新版/ }));

    await waitFor(() => expect(api.financeCall).toHaveBeenCalledWith(taskId, 'analysis-requirements-save', expect.anything()));
    const saveCall = vi.mocked(api.financeCall).mock.calls.find(([, command]) => command === 'analysis-requirements-save');
    expect(saveCall?.[2]?.scope).not.toHaveProperty('drilldown');
    expect(saveCall?.[2]?.scope).toEqual({ ledger: 'L1', organization: '华东', period: '2026-08', currency: 'CNY', unit: '万元', granularity: '区域' });
  });

  it('seeds a context scope key named like a level, which may be a real row column, into the first save', async () => {
    // Review round 9: the seed also dropped level, breakdown, group_by and hierarchy. Only drilldown is a
    // hierarchy level the server refuses; a 职级 column named level filters rows, so dropping it widened the scope.
    const seeded = { id: contextId, name: '口径', bindings: { actual: 'ds' },
      scopes: { actual: { ledger: 'L1', organization: '华东', period: '2026-08', currency: 'CNY', level: 'P7', drill_down: '城市公司' } } };
    const api = mountBridge({
      financeCall: vi.fn<NonNullable<Bridge['financeCall']>>(async (_task, command, spec) => {
        if (command === 'analysis-requirements-list') return ok({ requirements: [], current: null });
        if (command === 'list-finance-context') return ok({ task_id: taskId, datasets: [], contexts: [seeded], account_maps: [], scenarios: [], metric_definitions: [], capabilities: [] });
        if (command === 'analysis-requirements-save') return ok({ id: 'r-ctx-002', question: spec?.question, context_id: contextId, scope: spec?.scope, bindings: spec?.bindings, items: spec?.items, parent_id: null } as Record<string, unknown>);
        return ok({});
      }),
    });
    render(<RequirementsPanel taskId={taskId} contextId={contextId} />);

    expect(await screen.findByText(/CNY/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText('用户问题'), { target: { value: 'P7 人数' } });
    fireEvent.click(screen.getByRole('button', { name: /添加指标/ }));
    fireEvent.click(screen.getByRole('button', { name: /保存要求新版/ }));

    await waitFor(() => expect(api.financeCall).toHaveBeenCalledWith(taskId, 'analysis-requirements-save', expect.anything()));
    const saveCall = vi.mocked(api.financeCall).mock.calls.find(([, command]) => command === 'analysis-requirements-save');
    expect(saveCall?.[2]?.scope).toEqual({ ledger: 'L1', organization: '华东', period: '2026-08', currency: 'CNY', level: 'P7' });
  });

  it('still resends a stored record scope key it does not show, so the server can record the drop', async () => {
    // Opposite direction: only the context seed is cleaned. A stored record's scope round-trips unchanged;
    // the server drops a legacy level carried over from the parent and records it in authoring_warnings.
    const legacy: AnalysisRequirementsRecord = { ...current, scope: { ...current.scope, drilldown: '城市公司' } };
    const api = mountBridge({
      financeCall: vi.fn<NonNullable<Bridge['financeCall']>>(async (_task, command) => command === 'analysis-requirements-save'
        ? ok({ ...legacy, id: 'r-current-009', parent_id: legacy.id } as unknown as Record<string, unknown>)
        : ok({ requirements: [legacy], current: legacy })),
    });
    render(<RequirementsPanel taskId={taskId} />);
    await screen.findByDisplayValue('解释本期利润差异并下钻利润');
    fireEvent.click(screen.getByRole('button', { name: /保存要求新版/ }));

    await waitFor(() => expect(api.financeCall).toHaveBeenCalledWith(taskId, 'analysis-requirements-save', expect.objectContaining({
      parent_id: legacy.id,
      scope: expect.objectContaining({ drilldown: '城市公司' }),
    })));
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

  it('preserves item periods when saving a revised requirements version', async () => {
    const withPeriods: AnalysisRequirementsRecord = {
      ...current,
      items: [
        { ...current.items[0], periods: ['2026-09', '2026-10'] },
        current.items[1],
      ],
    };
    const api = mountBridge({
      financeCall: vi.fn<NonNullable<Bridge['financeCall']>>(async (_task, command, spec) => command === 'analysis-requirements-save'
        ? ok({ ...withPeriods, id: 'r-periods-002', parent_id: withPeriods.id, items: spec?.items } as Record<string, unknown>)
        : ok({ requirements: [withPeriods], current: withPeriods })),
    });
    render(<RequirementsPanel taskId={taskId} />);

    const profit = await screen.findByLabelText('必答指标 1');
    expect(within(profit).getByText('2026-09 ×')).toBeTruthy();
    fireEvent.change(within(profit).getByLabelText('添加期间 1'), { target: { value: '2026-11' } });
    fireEvent.click(within(profit).getByRole('button', { name: '添加期间' }));
    fireEvent.change(within(profit).getByLabelText('添加累计范围 1'), { target: { value: '2026-01:2026-08' } });
    fireEvent.click(within(profit).getByRole('button', { name: '添加累计范围' }));
    expect(screen.getByText(/上方期间与指标适用期间冲突/)).toBeTruthy();
    expect((screen.getByRole('button', { name: /保存要求新版/ }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('期间'), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: /保存要求新版/ }));

    await waitFor(() => expect(api.financeCall).toHaveBeenCalledWith(taskId, 'analysis-requirements-save', expect.objectContaining({
      items: expect.arrayContaining([expect.objectContaining({ id: 'profit', periods: ['2026-09', '2026-10', '2026-11', '2026-01:2026-08'] })]),
    })));
  });

  it('requires an explicit multi-organization set and clears conflicting shared scope before save', async () => {
    const api = mountBridge({
      financeCall: vi.fn<NonNullable<Bridge['financeCall']>>(async (_task, command, spec) => command === 'analysis-requirements-save'
        ? ok({ ...current, id: 'r-organizations-002', parent_id: current.id, scope: spec?.scope, items: spec?.items } as Record<string, unknown>)
        : ok({ requirements: [current], current })),
    });
    render(<RequirementsPanel taskId={taskId} />);

    const profit = await screen.findByLabelText('必答指标 1');
    const organizationInput = within(profit).getByLabelText('添加组织 1');
    fireEvent.change(organizationInput, { target: { value: '集团合并' } });
    fireEvent.click(within(profit).getByRole('button', { name: '添加组织' }));
    fireEvent.change(organizationInput, { target: { value: '华东区域' } });
    fireEvent.click(within(profit).getByRole('button', { name: '添加组织' }));

    expect(within(profit).getByText('集团合并 ×')).toBeTruthy();
    expect(screen.getByText(/上方组织与指标覆盖组织冲突/)).toBeTruthy();
    expect((screen.getByRole('button', { name: /保存要求新版/ }) as HTMLButtonElement).disabled).toBe(true);

    fireEvent.change(screen.getByLabelText('组织'), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: /保存要求新版/ }));

    await waitFor(() => expect(api.financeCall).toHaveBeenCalledWith(taskId, 'analysis-requirements-save', expect.objectContaining({
      scope: expect.not.objectContaining({ organization: '华东' }),
      items: expect.arrayContaining([expect.objectContaining({
        id: 'profit', organizations: ['集团合并', '华东区域'],
      })]),
    })));
  });

  it('preserves and saves each required result scenario for a financial metric', async () => {
    const withScenarios: AnalysisRequirementsRecord = {
      ...current,
      items: [{ ...current.items[0], scenarios: ['actual_ytd'] }, current.items[1]],
    };
    const api = mountBridge({
      financeCall: vi.fn<NonNullable<Bridge['financeCall']>>(async (_task, command, spec) => command === 'analysis-requirements-save'
        ? ok({ ...withScenarios, id: 'r-scenarios-002', parent_id: withScenarios.id, items: spec?.items } as Record<string, unknown>)
        : ok({ requirements: [withScenarios], current: withScenarios })),
    });
    render(<RequirementsPanel taskId={taskId} />);

    const profit = await screen.findByLabelText('必答指标 1');
    expect(within(profit).getByText('actual_ytd ×')).toBeTruthy();
    const input = within(profit).getByLabelText('添加结果情景 1');
    fireEvent.change(input, { target: { value: 'budget_ytd' } });
    fireEvent.click(within(profit).getByRole('button', { name: '添加情景' }));
    fireEvent.change(input, { target: { value: 'achievement_ratio' } });
    fireEvent.click(within(profit).getByRole('button', { name: '添加情景' }));
    fireEvent.click(screen.getByRole('button', { name: /保存要求新版/ }));

    await waitFor(() => expect(api.financeCall).toHaveBeenCalledWith(taskId, 'analysis-requirements-save', expect.objectContaining({
      items: expect.arrayContaining([expect.objectContaining({
        id: 'profit', scenarios: ['actual_ytd', 'budget_ytd', 'achievement_ratio'],
      })]),
    })));
  });

  it('lets a requirement pin the exact result metric key instead of relying on broad profit aliases', async () => {
    const pinned: AnalysisRequirementsRecord = {
      ...current,
      items: [{ ...current.items[0], dimensions: { metric_key: 'operating_profit' } }, current.items[1]],
    };
    const api = mountBridge({
      financeCall: vi.fn<NonNullable<Bridge['financeCall']>>(async (_task, command, spec) => command === 'analysis-requirements-save'
        ? ok({ ...pinned, id: 'r-metric-key-002', parent_id: pinned.id, items: spec?.items } as Record<string, unknown>)
        : ok({ requirements: [pinned], current: pinned })),
    });
    render(<RequirementsPanel taskId={taskId} />);

    const profit = await screen.findByLabelText('必答指标 1');
    const exactKey = within(profit).getByLabelText('精确结果键 1') as HTMLInputElement;
    expect(exactKey.value).toBe('operating_profit');
    fireEvent.change(exactKey, { target: { value: 'gross_profit' } });
    fireEvent.click(screen.getByRole('button', { name: /保存要求新版/ }));

    await waitFor(() => expect(api.financeCall).toHaveBeenCalledWith(taskId, 'analysis-requirements-save', expect.objectContaining({
      items: expect.arrayContaining([expect.objectContaining({
        id: 'profit', dimensions: expect.objectContaining({ metric_key: 'gross_profit' }),
      })]),
    })));
  });

  it('round-trips supported custom requirements without stale choice warnings', async () => {
    const supportedCustom: AnalysisRequirementsRecord = {
      ...current,
      id: 'r-custom-001',
      question: '核对华宸物业月结套表控制关系',
      scope: {
        ledger: 'default',
        organization: '华宸物业',
        period: '2026-01至2026-08（月结）及2026全年（BUD/LE）',
        currency: 'CNY',
        unit: '元（GL与三大报表）/ 万元（分析表，按各工作表注明）',
      },
      items: [
        { id: 'acct-total', metric: 'account_total', label: '科目合计', dimensions: {}, requires_drilldown: false },
        { id: 'variance', metric: 'total_variance', label: '总额差异', dimensions: {}, requires_drilldown: true },
      ],
      support: { items: [
        { requirement_item_id: 'acct-total', status: 'requires_execution', canonical_metric: 'account_total', next_action: '已识别控制合计。', missing_inputs: [] },
        { requirement_item_id: 'variance', status: 'requires_execution', canonical_metric: 'total_variance', next_action: '已识别总额差异。', missing_inputs: [] },
      ] },
    };
    const api = mountBridge({
      financeCall: vi.fn<NonNullable<Bridge['financeCall']>>(async (_task, command, spec) => command === 'analysis-requirements-save'
        ? ok({ ...supportedCustom, id: 'r-custom-002', parent_id: supportedCustom.id, scope: spec?.scope, items: spec?.items } as Record<string, unknown>)
        : ok({ requirements: [supportedCustom], current: supportedCustom })),
    });
    render(<RequirementsPanel taskId={taskId} />);

    expect(await screen.findByDisplayValue('2026-01至2026-08（月结）及2026全年（BUD/LE）')).toBeTruthy();
    expect(screen.getByText(/元（GL与三大报表）\/ 万元（分析表，按各工作表注明）/)).toBeTruthy();
    expect(screen.getByRole('button', { name: '指标 1' }).textContent).toContain('科目合计');
    expect(screen.getByRole('button', { name: '指标 2' }).textContent).toContain('总额差异');
    expect(screen.queryByText(/当前选择已失效/)).toBeNull();
    expect(screen.queryByText(/请输入 YYYY-MM 会计期间/)).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: /保存要求新版/ }));

    await waitFor(() => expect(api.financeCall).toHaveBeenCalledWith(taskId, 'analysis-requirements-save', expect.objectContaining({
      scope: expect.objectContaining({
        period: '2026-01至2026-08（月结）及2026全年（BUD/LE）',
        unit: '元（GL与三大报表）/ 万元（分析表，按各工作表注明）',
      }),
      items: [
        expect.objectContaining({ id: 'acct-total', metric: 'account_total', label: '科目合计' }),
        expect.objectContaining({ id: 'variance', metric: 'total_variance', label: '总额差异' }),
      ],
    })));
  });

  it('keeps saved custom period editable until converted to a monthly period', async () => {
    const supportedCustom: AnalysisRequirementsRecord = {
      ...current,
      id: 'r-custom-period-001',
      scope: {
        ledger: 'default',
        organization: '华宸物业',
        period: '2026-01至2026-08（月结）及2026全年（BUD/LE）',
        currency: 'CNY',
        unit: '万元',
      },
      items: [{ id: 'acct-total', metric: 'account_total', label: '科目合计', dimensions: {}, requires_drilldown: false }],
    };
    const api = mountBridge({
      financeCall: vi.fn<NonNullable<Bridge['financeCall']>>(async (_task, command, spec) => command === 'analysis-requirements-save'
        ? ok({ ...supportedCustom, id: 'r-custom-period-002', parent_id: supportedCustom.id, scope: spec?.scope, items: spec?.items } as Record<string, unknown>)
        : ok({ requirements: [supportedCustom], current: supportedCustom })),
    });
    render(<RequirementsPanel taskId={taskId} />);

    const period = await screen.findByLabelText('期间');
    expect(screen.queryByRole('button', { name: '期间打开年月选择' })).toBeNull();
    fireEvent.change(period, { target: { value: '2026-01至2026-09（月结）及2026全年（BUD/LE）' } });
    expect(screen.queryByText(/请输入 YYYY-MM 会计期间/)).toBeNull();
    fireEvent.change(screen.getByLabelText('期间'), { target: { value: '2026-01至2026-09（月结）及2026全年（BUD/LE，含滚动预测）' } });
    expect(screen.queryByText(/请输入 YYYY-MM 会计期间/)).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: /保存要求新版/ }));
    await waitFor(() => expect(api.financeCall).toHaveBeenCalledWith(taskId, 'analysis-requirements-save', expect.objectContaining({
      scope: expect.objectContaining({ period: '2026-01至2026-09（月结）及2026全年（BUD/LE，含滚动预测）' }),
    })));

    fireEvent.change(screen.getByLabelText('期间'), { target: { value: '2026-08' } });
    expect(screen.getByRole('button', { name: '期间打开年月选择' })).toBeTruthy();
  });

  it('shows requirement support gaps without blocking free editing', async () => {
    const supported = {
      ...current,
      support: { items: [
        {
          requirement_item_id: 'profit',
          status: 'requires_input',
          canonical_metric: 'profit',
          next_action: '请补充预算资料。',
          missing_inputs: [{ dataset_id: 'budget-dataset', alias: '预算表', columns: ['amount', 'period'] }],
        },
        { requirement_item_id: 'expense', status: 'unrecognized', canonical_metric: null, next_action: '暂未识别该能力，可继续自由编辑。', missing_inputs: [] },
      ] },
    } as unknown as AnalysisRequirementsRecord;
    const saved: AnalysisRequirementsRecord = { ...supported, id: 'r-support-002', parent_id: supported.id, question: '继续按经理口径解释' };
    const api = mountBridge({
      financeCall: vi.fn<NonNullable<Bridge['financeCall']>>(async (_task, command) => command === 'analysis-requirements-save'
        ? ok(saved as unknown as Record<string, unknown>)
        : ok({ requirements: [supported], current: supported })),
    });
    render(<RequirementsPanel taskId={taskId} />);

    expect(await screen.findByText(/缺少资料：预算表（字段：amount、period）。请补充预算资料。/)).toBeTruthy();
    expect(screen.getByText(/暂未识别该能力，可继续自由编辑。/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText('用户问题'), { target: { value: '继续按经理口径解释' } });
    fireEvent.click(screen.getByRole('button', { name: /保存要求新版/ }));

    await waitFor(() => expect(api.financeCall).toHaveBeenCalledWith(taskId, 'analysis-requirements-save', expect.objectContaining({
      question: '继续按经理口径解释',
      items: expect.arrayContaining([expect.objectContaining({ id: 'profit' })]),
    })));
  });

  it('marks existing support as pending when the global period changes before saving', async () => {
    const supported = {
      ...current,
      support: { items: [
        {
          requirement_item_id: 'profit',
          status: 'requires_input',
          canonical_metric: 'profit',
          next_action: '请补充预算资料。',
          missing_inputs: [{ dataset_id: 'budget-dataset', alias: '预算表', columns: ['amount'] }],
        },
      ] },
    } as unknown as AnalysisRequirementsRecord;
    mountBridge({
      financeCall: vi.fn<NonNullable<Bridge['financeCall']>>(async () => ok({ requirements: [supported], current: supported })),
    });
    render(<RequirementsPanel taskId={taskId} />);

    const profit = await screen.findByLabelText('必答指标 1');
    expect(within(profit).getByText(/请补充预算资料。/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText('期间'), { target: { value: '2026-11' } });

    expect(within(profit).queryByText(/请补充预算资料。/)).toBeNull();
    expect(within(profit).getByText(/条件已修改，保存后重新检查资料匹配。/)).toBeTruthy();
  });

  it('marks existing support as pending when the metric is changed before saving', async () => {
    const supported = {
      ...current,
      support: { items: [
        {
          requirement_item_id: 'profit',
          status: 'requires_input',
          canonical_metric: 'profit',
          next_action: '请补充预算资料。',
          missing_inputs: [{ dataset_id: 'budget-dataset', alias: '预算表', columns: ['amount'] }],
        },
      ] },
    } as unknown as AnalysisRequirementsRecord;
    mountBridge({
      financeCall: vi.fn<NonNullable<Bridge['financeCall']>>(async () => ok({ requirements: [supported], current: supported })),
    });
    render(<RequirementsPanel taskId={taskId} />);

    const profit = await screen.findByLabelText('必答指标 1');
    expect(within(profit).getByText(/请补充预算资料。/)).toBeTruthy();
    fireEvent.click(within(profit).getByRole('button', { name: '指标 1' }));
    fireEvent.mouseDown(screen.getByRole('option', { name: /收入/ }));

    expect(within(profit).queryByText(/请补充预算资料。/)).toBeNull();
    expect(within(profit).getByText(/条件已修改，保存后重新检查资料匹配。/)).toBeTruthy();
  });

  describe('grain_basis declarations', () => {
    // The assistant declares which grains are estimates or unavailable; a manager save that drops the
    // declaration turns a declared estimate back into a pending grain (estimate_cited_for_source_grain).
    const declared = {
      id: 'r-grain-001', question: '华宸 1-8 月收入', context_id: null,
      scope: { ledger: 'L1', currency: 'CNY', unit: '万元' }, bindings: { budget: 'budget-dataset' },
      items: [{ id: 'revenue_1_8', metric: 'revenue', label: '收入', dimensions: {}, requires_drilldown: false,
        organizations: ['集团合并', '华东区域', '华南区域'], periods: ['2026-01:2026-08'], scenarios: ['budget_1_8'],
        grain_basis: [
          { basis: 'estimate', organizations: ['华东区域'], method: '区域全年预算 × 集团进度' },
          { basis: 'estimate', organizations: ['华南区域'], method: '（营业利润 − 其他收益）÷ 合计', factor_reproducible: false, reason: '系数须先减后除' },
        ] }],
      parent_id: null,
    } as unknown as AnalysisRequirementsRecord;

    function mountDeclared() {
      const financeCall = vi.fn<NonNullable<Bridge['financeCall']>>(async (_task, command, spec) => command === 'analysis-requirements-save'
        ? ok({ ...declared, id: 'r-grain-002', parent_id: declared.id, items: spec?.items } as Record<string, unknown>)
        : ok({ requirements: [declared], current: declared }));
      mountBridge({ financeCall });
      return { financeCall };
    }

    function savedItems(api: ReturnType<typeof mountDeclared>): Array<Record<string, unknown>> {
      const call = api.financeCall.mock.calls.find(([, command]) => command === 'analysis-requirements-save');
      return (call?.[2] as { items: Array<Record<string, unknown>> }).items;
    }

    it('keeps the declarations when the manager saves an unrelated edit', async () => {
      const api = mountDeclared();
      render(<RequirementsPanel taskId={taskId} />);
      expect(await screen.findByDisplayValue('华宸 1-8 月收入')).toBeTruthy();
      fireEvent.change(screen.getByLabelText('用户问题'), { target: { value: '华宸 1-8 月收入（改问法）' } });
      fireEvent.click(screen.getByRole('button', { name: /保存要求新版/ }));

      await waitFor(() => expect(api.financeCall).toHaveBeenCalledWith(taskId, 'analysis-requirements-save', expect.anything()));
      expect(savedItems(api)[0].grain_basis).toEqual(declared.items[0].grain_basis);
    });

    it('drops a declaration whose organization the manager removed instead of widening it', async () => {
      const api = mountDeclared();
      render(<RequirementsPanel taskId={taskId} />);
      const revenue = await screen.findByLabelText('必答指标 1');
      fireEvent.click(within(revenue).getByRole('button', { name: '华南区域 ×' }));
      fireEvent.click(screen.getByRole('button', { name: /保存要求新版/ }));

      await waitFor(() => expect(api.financeCall).toHaveBeenCalledWith(taskId, 'analysis-requirements-save', expect.anything()));
      expect(savedItems(api)[0].organizations).toEqual(['集团合并', '华东区域']);
      expect(savedItems(api)[0].grain_basis).toEqual([declared.items[0].grain_basis?.[0]]);
    });
  });

});
