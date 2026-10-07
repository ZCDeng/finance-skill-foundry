// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ScopePanel } from '../src/views/analysis/ScopePanel.js';
import { useAnalysisScope } from '../src/views/analysis/scope.js';
import { BusinessResultView } from '../src/views/analysis/BusinessResultView.js';
import { RevisionDiff } from '../src/views/analysis/RevisionDiff.js';
import type { AnalysisRun, Bridge, DatasetSnapshot } from '../src/bridge.js';
import huachenDeclared from './fixtures/huachen-row-declarations.json';

const taskId = 't'.repeat(32);
const dataset = { id: 'd'.repeat(32), name: '预算套表', kind: 'table', source_hash: 'h'.repeat(64), source_name: 'budget.xlsx', metadata: {} } as unknown as DatasetSnapshot;

/** The 资料 page's scope card: the task's one scope, held by the hook and edited in the panel. */
function ScopeCard({ task = taskId, question, datasets, onSaved }: { task?: string; question: string; datasets: DatasetSnapshot[]; onSaved?(): void }) {
  const scope = useAnalysisScope(task, question, datasets);
  return <ScopePanel scope={scope} datasetCount={datasets.length} onSaved={onSaved} />;
}

const choose = async (label: string, option: RegExp) => {
  fireEvent.click(screen.getByRole('button', { name: label }));
  fireEvent.click(await screen.findByRole('option', { name: option }));
};

function run(rows: Record<string, unknown>[]): AnalysisRun {
  return {
    id: 'r'.repeat(32),
    task_id: taskId,
    analysis_id: 'a'.repeat(32),
    schema_version: 1,
    created_at: '2026-09-23T00:00:00Z',
    execution_status: 'succeeded',
    reproducibility_status: 'unverified',
    review_status: 'unreviewed',
    publication_status: 'draft',
    input_hashes: {},
    engine: 'python',
    result: {
      columns: [
        { name: 'period', type: 'VARCHAR' },
        { name: 'metric_key', type: 'VARCHAR' },
        { name: 'actual', type: 'DECIMAL' },
        { name: 'attainment_rate', type: 'DOUBLE' },
        { name: 'ratio_delta', type: 'DOUBLE' },
        { name: 'source_note', type: 'VARCHAR' },
      ],
      rows,
      row_count: rows.length,
      truncated: false,
    },
  };
}

const ok = <T,>(value: T) => ({ ok: true as const, value });

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  delete (globalThis as { foundry?: Partial<Bridge> }).foundry;
});

describe('business result components', () => {
  it('saves a new scope version with parent CAS and preserves existing question, items, bindings and extra scope', async () => {
    const current = {
      id: 'current-scope-version',
      question: '已保存的问题',
      scope: { period: '2026 YTD', unit: '万元', scenario: '待经理确认', custom_scope: '保留' },
      bindings: { budget_workbook: 'budget-dataset' },
      context_id: 'ctx-existing',
      items: [{ id: 'req_9', metric: 'revenue', label: '收入', dimensions: { region: '集团' }, requires_drilldown: true }],
    };
    const financeCall = vi.fn(async (_task: string, command: string, spec?: Record<string, unknown>) => {
      if (command === 'analysis-requirements-list') return ok({ current });
      if (command === 'finance-readiness') return ok({});
      expect(command).toBe('analysis-requirements-save');
      expect(spec).toMatchObject({
        question: '已保存的问题',
        parent_id: current.id,
        bindings: current.bindings,
        context_id: 'ctx-existing',
        items: current.items,
        scope: { period: '2026-08', unit: '万元', scenario: '待经理确认', organization: '集团', custom_scope: '保留' },
      });
      expect(spec).not.toHaveProperty('actual');
      expect(spec).not.toHaveProperty('budget');
      return ok({ ...current, id: 'next-scope-version', scope: spec?.scope });
    });
    const onSaved = vi.fn();
    (globalThis as { foundry?: Partial<Bridge> }).foundry = { financeCall };
    render(<ScopeCard question="新的输入框问题" datasets={[dataset]} onSaved={onSaved} />);
    expect(await screen.findByDisplayValue('2026 YTD')).toBeTruthy();
    // A saved value none of the fixed choices list is still shown, marked as the saved value.
    expect(screen.getByRole('button', { name: '分析范围情景' }).textContent).toContain('待经理确认');
    fireEvent.change(screen.getByLabelText('分析范围期间'), { target: { value: '2026-08' } });
    fireEvent.change(screen.getByLabelText('分析范围组织'), { target: { value: '集团' } });
    fireEvent.click(screen.getByRole('button', { name: '保存范围' }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledOnce());
    expect(screen.getByText('已保存分析范围，旧版本仍保留。')).toBeTruthy();
  });

  it('does not infer default period, unit, currency, scenario, bindings or profit requirements for a new task', async () => {
    const financeCall = vi.fn(async (_task: string, command: string, spec?: Record<string, unknown>) => {
      if (command === 'analysis-requirements-list') return ok({ current: null });
      if (command === 'finance-readiness') return ok({});
      expect(spec).toMatchObject({ question: '本次想问的问题', scope: {}, bindings: {}, items: [] });
      return ok({ id: 'blank-scope-version', question: '本次想问的问题', scope: {}, bindings: {}, items: [] });
    });
    (globalThis as { foundry?: Partial<Bridge> }).foundry = { financeCall };
    render(<ScopeCard question="本次想问的问题" datasets={[dataset]} />);
    await waitFor(() => expect(financeCall).toHaveBeenCalledWith(taskId, 'analysis-requirements-list', {}));
    expect((screen.getByLabelText('分析范围期间') as HTMLInputElement).value).toBe('');
    for (const field of ['分析范围单位', '分析范围币种', '分析范围情景']) {
      expect(screen.getByRole('button', { name: field }).textContent).toContain('待确认');
    }
    fireEvent.click(screen.getByRole('button', { name: '保存范围' }));
    await screen.findByText('已保存分析范围，旧版本仍保留。');
    const saves = financeCall.mock.calls.filter(([, command]) => command === 'analysis-requirements-save');
    expect(saves).toHaveLength(1);
    expect(saves[0][2]?.scope).toEqual({});
  });

  it('offers the values the files declare as one click each', async () => {
    const financeCall = vi.fn(async (_task: string, command: string) => {
      if (command === 'analysis-requirements-list') return ok({ current: null });
      if (command === 'finance-readiness') return ok({ proposed_scope: { period: '2026-08', organization: '华东', scenario: 'actual', currency: 'CNY' }, datasets: [] });
      return ok({});
    });
    (globalThis as { foundry?: Partial<Bridge> }).foundry = { financeCall };
    const declared = { ...dataset, metadata: { scope_hints: { unit: '万元', period: '2026-08' } } } as DatasetSnapshot;
    render(<ScopeCard question="八月经营情况" datasets={[declared]} />);
    fireEvent.click(await screen.findByRole('button', { name: '采用资料里的组织 华东' }));
    expect((screen.getByLabelText('分析范围组织') as HTMLInputElement).value).toBe('华东');
    fireEvent.click(screen.getByRole('button', { name: '采用资料里的期间 2026-08' }));
    expect((screen.getByLabelText('分析范围期间') as HTMLInputElement).value).toBe('2026-08');
    expect(screen.getByRole('button', { name: '采用资料里的单位 万元' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '采用资料里的币种 CNY' }).textContent).toContain('CNY');
    expect(screen.getByRole('button', { name: '采用资料里的情景 actual' }).textContent).toContain('实际');
    fireEvent.click(screen.getByRole('button', { name: '分析范围情景' }));
    expect(await screen.findByRole('option', { name: /^实际/ })).toBeTruthy();
    expect(screen.queryByRole('option', { name: /^actual/ })).toBeNull();
    // A value already taken is no longer offered.
    expect(screen.queryByRole('button', { name: '采用资料里的期间 2026-08' })).toBeNull();
    await choose('分析范围单位', /^万元/);
    expect(screen.getByRole('button', { name: '分析范围单位' }).textContent).toContain('万元');
  });

  it('draws the values the files declare as chips and keeps 保存范围 as the card\'s one main action, at the right', async () => {
    const financeCall = vi.fn(async (_task: string, command: string) => {
      if (command === 'analysis-requirements-list') return ok({ current: null });
      if (command === 'finance-readiness') return ok({ proposed_scope: { organization: '华东' }, datasets: [] });
      return ok({});
    });
    (globalThis as { foundry?: Partial<Bridge> }).foundry = { financeCall };
    render(<ScopeCard question="八月经营情况" datasets={[dataset]} />);
    const candidate = await screen.findByRole('button', { name: '采用资料里的组织 华东' });
    expect(candidate.getAttribute('data-size')).toBe('chip');
    const card = screen.getByRole('region', { name: '分析范围' });
    const mains = within(card).getAllByRole('button').filter((button) => button.getAttribute('data-variant') === 'default');
    expect(mains.map((button) => button.textContent)).toEqual(['保存范围']);
    const row = mains[0].parentElement!;
    expect(row.className).toBe('analysis-actions analysis-actions--end');
    expect(row.lastElementChild).toBe(mains[0]);
  });

  it('resolves a legacy shared-period conflict explicitly while preserving item periods and bindings', async () => {
    const items = [{ id: 'monthly_profit', metric: 'operating_profit', periods: ['2026-01', '2026-08'], dimensions: {}, requires_drilldown: true }];
    const current = {
      id: 'legacy-requirements', question: '核对月度利润',
      scope: { period: '2026-01:2026-08', unit: '万元', currency: 'CNY' },
      bindings: { actual: 'actual-dataset' }, items,
    };
    const financeCall = vi.fn(async (_task: string, command: string, spec?: Record<string, unknown>) => {
      if (command === 'analysis-requirements-list') return ok({ current });
      if (command === 'finance-readiness') return ok({});
      expect(command).toBe('analysis-requirements-save');
      expect(spec).toMatchObject({ parent_id: current.id, items, bindings: current.bindings, scope: { unit: '元', currency: 'CNY' } });
      expect(spec?.scope).not.toHaveProperty('period');
      return ok({ ...current, id: 'resolved-requirements', scope: spec?.scope });
    });
    (globalThis as { foundry?: Partial<Bridge> }).foundry = { financeCall };
    render(<ScopeCard question="新问题" datasets={[dataset]} />);
    expect(await screen.findByDisplayValue('2026-01:2026-08')).toBeTruthy();
    await choose('分析范围单位', /^元/);
    expect(screen.getByRole('button', { name: '保存范围' }).hasAttribute('disabled')).toBe(true);
    expect(screen.getByRole('alert').textContent).toContain('逐项期间');
    fireEvent.click(screen.getByRole('button', { name: '清空共同期间，保留逐项期间' }));
    expect((screen.getByLabelText('分析范围期间') as HTMLInputElement).value).toBe('');
    fireEvent.click(screen.getByRole('button', { name: '保存范围' }));
    await screen.findByText('已保存分析范围，旧版本仍保留。');
    expect(financeCall.mock.calls.filter(([, command]) => command === 'analysis-requirements-save')).toHaveLength(1);
  });

  it('sends the scope the server saved on the next save, not a legacy level the server dropped', async () => {
    // A pre-phase-1 record kept drilldown in scope. The first save drops it (hierarchy_scope_dropped); the card
    // kept the copy it loaded at mount and resent it, so every later save was refused.
    const items = [{ id: 'profit', metric: 'profit', label: '利润', dimensions: {}, requires_drilldown: true }];
    const current = {
      id: 'legacy-scope', question: '解释利润',
      scope: { ledger: 'L1', unit: '万元', drilldown: '城市公司' }, bindings: { actual: 'actual-dataset' }, items,
    };
    const saved: Record<string, unknown>[] = [];
    const financeCall = vi.fn(async (_task: string, command: string, spec?: Record<string, unknown>) => {
      if (command === 'analysis-requirements-list') return ok({ current });
      if (command === 'finance-readiness') return ok({});
      saved.push(spec ?? {});
      const scope = Object.fromEntries(Object.entries((spec?.scope ?? {}) as Record<string, unknown>).filter(([key]) => key !== 'drilldown'));
      return ok({ ...current, id: `saved-scope-${saved.length}`, scope, authoring_warnings: [{ code: 'hierarchy_scope_dropped' }] });
    });
    (globalThis as { foundry?: Partial<Bridge> }).foundry = { financeCall };
    render(<ScopeCard question="解释利润" datasets={[dataset]} />);
    await waitFor(() => expect(screen.getByRole('button', { name: '分析范围单位' }).textContent).toContain('万元'));
    fireEvent.change(screen.getByLabelText('分析范围期间'), { target: { value: '2026-08' } });
    fireEvent.click(screen.getByRole('button', { name: '保存范围' }));
    await screen.findByText('已保存分析范围，旧版本仍保留。');
    await choose('分析范围币种', /^人民币/);
    fireEvent.click(screen.getByRole('button', { name: '保存范围' }));
    await waitFor(() => expect(saved).toHaveLength(2));

    expect(saved[0]).toMatchObject({ parent_id: 'legacy-scope', scope: { ledger: 'L1', unit: '万元', period: '2026-08', drilldown: '城市公司' } });
    expect(saved[1]).toMatchObject({ parent_id: 'saved-scope-1', items, scope: { ledger: 'L1', unit: '万元', period: '2026-08', currency: 'CNY' } });
    expect(saved[1].scope).not.toHaveProperty('drilldown');
    // The fields show what was stored.
    expect((screen.getByLabelText('分析范围期间') as HTMLInputElement).value).toBe('2026-08');
    expect(screen.getByRole('button', { name: '分析范围币种' }).textContent).toContain('人民币');
  });

  it('ignores a delayed save response from a previous task after switching tasks', async () => {
    let finishOldSave!: (value: ReturnType<typeof ok<Record<string, unknown>>>) => void;
    const otherTask = 'u'.repeat(32);
    const otherCurrent = {
      id: 'other-scope',
      question: '西南分析',
      scope: { period: '2026-09', organization: '西南', unit: '万元' },
      bindings: {},
      items: [],
    };
    const financeCall = vi.fn(async (task: string, command: string, spec?: Record<string, unknown>) => {
      if (command === 'analysis-requirements-list') {
        return ok({ current: task === otherTask ? otherCurrent : { id: 'old-scope', question: '华东分析', scope: { period: '2026-08' }, bindings: {}, items: [] } });
      }
      if (command === 'finance-readiness') return ok({});
      if (command === 'analysis-requirements-save' && task === taskId) {
        return new Promise<ReturnType<typeof ok<Record<string, unknown>>>>((resolve) => { finishOldSave = resolve; });
      }
      return ok({ id: 'unexpected', question: spec?.question, scope: spec?.scope, bindings: {}, items: [] });
    });
    (globalThis as { foundry?: Partial<Bridge> }).foundry = { financeCall };
    const view = render(<ScopeCard task={taskId} question="华东分析" datasets={[dataset]} />);
    expect(await screen.findByDisplayValue('2026-08')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('分析范围期间'), { target: { value: '2026-10' } });
    fireEvent.click(screen.getByRole('button', { name: '保存范围' }));
    view.rerender(<ScopeCard task={otherTask} question="西南分析" datasets={[dataset]} />);
    expect(await screen.findByDisplayValue('2026-09')).toBeTruthy();

    finishOldSave(ok({ id: 'old-scope-saved', question: '华东分析', scope: { period: '2026-10', organization: '华东' }, bindings: {}, items: [] }));

    await waitFor(() => expect((screen.getByLabelText('分析范围期间') as HTMLInputElement).value).toBe('2026-09'));
    expect((screen.getByLabelText('分析范围组织') as HTMLInputElement).value).toBe('西南');
  });


  it('does not send duplicate saves while a scope save is already in flight', async () => {
    let finishSave!: (value: ReturnType<typeof ok<Record<string, unknown>>>) => void;
    const current = { id: 'scope-double-save', question: '双击保存', scope: { period: '2026-08' }, bindings: {}, items: [] };
    const financeCall = vi.fn(async (_task: string, command: string) => {
      if (command === 'analysis-requirements-list') return ok({ current });
      if (command === 'finance-readiness') return ok({});
      if (command === 'analysis-requirements-save') {
        return new Promise<ReturnType<typeof ok<Record<string, unknown>>>>((resolve) => { finishSave = resolve; });
      }
      return ok({});
    });
    (globalThis as { foundry?: Partial<Bridge> }).foundry = { financeCall };
    render(<ScopeCard question="双击保存" datasets={[dataset]} />);
    expect(await screen.findByDisplayValue('2026-08')).toBeTruthy();

    const save = screen.getByRole('button', { name: '保存范围' });
    fireEvent.click(save);
    fireEvent.click(save);
    expect(financeCall.mock.calls.filter(([, command]) => command === 'analysis-requirements-save')).toHaveLength(1);
    finishSave(ok({ ...current, id: 'scope-double-save-next', scope: { period: '2026-08' } }));
    await screen.findByText('已保存分析范围，旧版本仍保留。');
  });

  it('toggles periods while preserving exact amount, ratio, percentage-point and source detail text', () => {
    const onSources = vi.fn();
    render(<BusinessResultView run={run([
      { period: '2026-08', metric_key: 'revenue', actual: '41469.625', attainment_rate: '0.938999', ratio_delta: '-0.006532', source_note: '04表B5/B33' },
      { period: 'YTD', metric_key: 'revenue', actual: '325644', attainment_rate: '0.945301', ratio_delta: '0.012345', source_note: '预算01 I12' },
    ])} onSources={onSources} />);
    const table = screen.getAllByRole('region', { name: '业务结果' }).at(-1)!;
    expect(within(table).getByRole('cell', { name: '41,469.63' })).toBeTruthy();
    expect(within(table).getByRole('cell', { name: '93.90%' })).toBeTruthy();
    expect(within(table).getByRole('cell', { name: '-0.65 个百分点' })).toBeTruthy();
    expect(within(table).getByRole('cell', { name: '04表B5/B33' })).toBeTruthy();
    fireEvent.click(screen.getByRole('tab', { name: 'YTD' }));
    const updated = screen.getAllByRole('region', { name: '业务结果' }).at(-1)!;
    expect(within(updated).getByRole('cell', { name: '325,644.00' })).toBeTruthy();
    expect(within(updated).getByRole('cell', { name: '94.53%' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '查看来源与范围' }));
    expect(onSources).toHaveBeenCalledOnce();
  });


  it('resets the selected period when the same view receives a different run', () => {
    const first = run([
      { period: '2026-08', metric_key: 'revenue', actual: '10', budget: '12', attainment: '0.8333', basis: 'source_fact' },
      { period: 'YTD', metric_key: 'revenue', actual: '100', budget: '120', attainment: '0.8333', basis: 'source_fact' },
    ]);
    const second: AnalysisRun = {
      ...run([{ period: '2026-09', metric_key: 'profit', actual: '77', budget: '70', attainment: '1.1', basis: 'calculation' }]),
      id: 's'.repeat(32),
    };
    const view = render(<BusinessResultView run={first} />);
    fireEvent.click(screen.getByRole('tab', { name: 'YTD' }));
    expect(screen.getByRole('cell', { name: '100.00' })).toBeTruthy();

    view.rerender(<BusinessResultView run={second} />);

    const table = screen.getAllByRole('region', { name: '业务结果' }).at(-1)!;
    expect(within(table).getByRole('cell', { name: '77.00' })).toBeTruthy();
    expect(within(table).queryByText('没有符合当前范围的行。')).toBeNull();
  });

  it('shows KPI actual, budget, difference, rate, period, unit and explicit row basis', () => {
    render(<BusinessResultView run={run([
      { period: '2026-08', unit: '万元', metric_key: 'operating_profit', actual: '90', budget: '100', variance: '-10', attainment: '0.9', basis: 'professional_judgment' },
    ])} />);
    const card = screen.getByRole('article');
    expect(within(card).getByText('营业利润')).toBeTruthy();
    expect(within(card).getByLabelText('营业利润实际').textContent).toBe('90.00');
    expect(card.querySelector('.analysis-kpi-meta')?.textContent).toBe('2026 年 8 月 · 万元 · 依据：专业判断');
    // Each part stays whole; the line may break only at a separator.
    expect(Array.from(card.querySelectorAll('.analysis-kpi-meta > span')).map((part) => part.textContent)).toEqual(['2026 年 8 月', '万元', '依据：专业判断']);
    expect(within(card).getByText('预算')).toBeTruthy();
    expect(within(card).getByText('100.00')).toBeTruthy();
    expect(within(card).getByText('差异')).toBeTruthy();
    expect(within(card).getByText('-10.00')).toBeTruthy();
    expect(within(card).getByText('达成率')).toBeTruthy();
    expect(within(card).getByText('90.00%')).toBeTruthy();
  });

  it('renders Chinese wide business runs as KPI cards instead of unknown placeholder results', () => {
    const rows = [{
      区域: '华东区域',
      收入_实际_1_8月: '109742.0280',
      收入_同期预算_估算_1_8月: '117814.5729',
      收入_差异_1_8月: '-8072.5449',
      收入_达成率_1_8月: '0.931481',
      经营利润_实际_1_8月: '12451.5443',
      经营利润_同期预算_估算_1_8月: '13936.4958',
      经营利润_差异_1_8月: '-1484.9515',
      经营利润_达成率_1_8月: '0.893449',
      单位: '万元',
      估算方法: '区域无月度预算，同期预算=区域年度预算×集团分期比例',
      来源: '实际：mth/10；年度预算：bud/05',
    }];
    const wide: AnalysisRun = {
      ...run([]),
      result: {
      columns: [
        { name: '区域', type: 'VARCHAR' },
        { name: '收入_实际_1_8月', type: 'DECIMAL' },
        { name: '收入_同期预算_估算_1_8月', type: 'DECIMAL' },
        { name: '收入_差异_1_8月', type: 'DECIMAL' },
        { name: '收入_达成率_1_8月', type: 'DOUBLE' },
        { name: '经营利润_实际_1_8月', type: 'DECIMAL' },
        { name: '经营利润_同期预算_估算_1_8月', type: 'DECIMAL' },
        { name: '经营利润_差异_1_8月', type: 'DECIMAL' },
        { name: '经营利润_达成率_1_8月', type: 'DOUBLE' },
        { name: '单位', type: 'VARCHAR' },
        { name: '估算方法', type: 'VARCHAR' },
        { name: '来源', type: 'VARCHAR' },
      ],
      rows,
      row_count: 1,
      truncated: false,
      },
    };
    render(<BusinessResultView run={wide} />);
    const cards = screen.getAllByRole('article');
    expect(within(cards[0]).getByText('收入 · 华东区域')).toBeTruthy();
    expect(within(cards[0]).getByLabelText('收入 · 华东区域实际').textContent).toBe('109,742.03');
    expect(cards[0].querySelector('.analysis-kpi-meta')?.textContent).toMatch(/^1_8月 · 万元 · 依据：估算/);
    expect(within(cards[0]).getByText('93.15%')).toBeTruthy();
    expect(screen.queryByText('未声明期间')).toBeNull();
    expect(screen.queryByText('未声明单位')).toBeNull();
    const table = screen.getAllByRole('region', { name: '业务结果' }).at(-1)!;
    expect(within(table).getAllByRole('cell', { name: '实际：mth/10；年度预算：bud/05' })).toHaveLength(2);
  });


  it('uses estimated budget and rate pct fields from long-form rows in KPI cards', () => {
    const estimated: AnalysisRun = {
      ...run([]),
      result: {
        columns: [
          { name: 'metric_key', type: 'VARCHAR' },
          { name: 'period', type: 'VARCHAR' },
          { name: 'organization', type: 'VARCHAR' },
          { name: 'scenario', type: 'VARCHAR' },
          { name: 'unit', type: 'VARCHAR' },
          { name: 'value', type: 'DECIMAL' },
          { name: 'source', type: 'VARCHAR' },
          { name: 'note', type: 'VARCHAR' },
        ],
        rows: [
          { metric_key: 'revenue', period: '2026-01:2026-08', organization: '西部区域', scenario: 'actual_ytd', unit: '万元', value: '33541.3320', source: 'mth/12 C5', note: '累计收入实际' },
          { metric_key: 'revenue', period: '2026-01:2026-08', organization: '西部区域', scenario: 'estimated_budget_ytd', unit: '万元', value: '33415.2443', source: '预算按集团比例估算', note: '累计收入估算预算' },
          { metric_key: 'revenue', period: '2026-01:2026-08', organization: '西部区域', scenario: 'attainment_pct', unit: '%', value: '100.3773', source: '实际 ÷ 估算预算', note: '达成率百分数' },
        ],
        row_count: 3,
        truncated: false,
      },
    };

    render(<BusinessResultView run={estimated} />);

    const card = screen.getByRole('article');
    expect(within(card).getByText('收入 · 西部区域')).toBeTruthy();
    expect(within(card).getByLabelText('收入 · 西部区域实际').textContent).toBe('33,541.33');
    expect(within(card).getByText('33,415.24')).toBeTruthy();
    expect(within(card).getByText('100.38%')).toBeTruthy();
    expect(card.querySelector('.analysis-kpi-meta')?.textContent).toBe('2026 年 1–8 月 · 万元 · 依据：估算 · 推断');
  });

  it('keeps unsafe long-form rows in the raw table without rendering blank KPI cards', () => {
    const unsafe: AnalysisRun = {
      ...run([]),
      result: {
        columns: [
          { name: 'metric_key', type: 'VARCHAR' },
          { name: 'period', type: 'VARCHAR' },
          { name: 'organization', type: 'VARCHAR' },
          { name: 'scenario', type: 'VARCHAR' },
          { name: 'unit', type: 'VARCHAR' },
          { name: 'value', type: 'DECIMAL' },
          { name: 'source', type: 'VARCHAR' },
        ],
        rows: [
          { metric_key: 'revenue', period: '2026-08', organization: '集团合并', scenario: 'actual_month', unit: '万元', value: '41469.6250', source: 'mth/04 B5' },
          { metric_key: 'revenue', period: '2026-08', organization: '集团合并', scenario: 'budget_month', unit: '元', value: '441636526', source: 'bud/01 I12' },
        ],
        row_count: 2,
        truncated: false,
      },
    };

    render(<BusinessResultView run={unsafe} />);

    expect(screen.queryByRole('article')).toBeNull();
    const table = screen.getAllByRole('region', { name: '业务结果' }).at(-1)!;
    expect(within(table).getByRole('cell', { name: '41,469.63' })).toBeTruthy();
    expect(within(table).getByRole('cell', { name: '441,636,526.00' })).toBeTruthy();
  });


  it('renders real scenario long-form Huachen rows with revenue and operating profit first in KPI cards', () => {
    const columns = [
      { name: 'metric_key', type: 'VARCHAR' },
      { name: 'period', type: 'VARCHAR' },
      { name: 'organization', type: 'VARCHAR' },
      { name: 'scenario', type: 'VARCHAR' },
      { name: 'unit', type: 'VARCHAR' },
      { name: 'value', type: 'DECIMAL' },
      { name: 'source', type: 'VARCHAR' },
      { name: 'note', type: 'VARCHAR' },
    ];
    const current: AnalysisRun = {
      ...run([]),
      id: '49bb555c1cca40a8a144b4e51e2413a5',
      result: {
        columns,
        rows: [
          { metric_key: 'gross_profit', period: '2026-01:2026-08', organization: '集团合并', scenario: 'actual_ytd', unit: '万元', value: '58789.5000', source: 'mth/04·合并利润表 C24（元 ÷ 10000）', note: '毛利实际' },
          { metric_key: 'gross_profit', period: '2026-01:2026-08', organization: '集团合并', scenario: 'budget_ytd', unit: '万元', value: '64441.3769', source: 'bud/01·年度预算总表 B24:I24 合计', note: '毛利同期预算' },
          { metric_key: 'gross_profit', period: '2026-01:2026-08', organization: '集团合并', scenario: 'variance', unit: '万元', value: '-5651.8769', source: '本表计算', note: '毛利缺口（不利）' },
          { metric_key: 'period_expense', period: '2026-01:2026-08', organization: '集团合并', scenario: 'actual_ytd', unit: '万元', value: '29946.0000', source: 'mth/04 C18:C22 合计（元 ÷ 10000）', note: '期间费用实际' },
          { metric_key: 'period_expense', period: '2026-01:2026-08', organization: '集团合并', scenario: 'budget_ytd', unit: '万元', value: '31642.0000', source: 'bud/01 B32:I32 合计', note: '期间费用同期预算' },
          { metric_key: 'period_expense', period: '2026-01:2026-08', organization: '集团合并', scenario: 'variance_favorable', unit: '万元', value: '1696.0000', source: '本表计算', note: '费用低于预算 = 对利润正向贡献' },
          { metric_key: 'operating_profit', period: '2026-01:2026-08', organization: '集团合并', scenario: 'actual_ytd', unit: '万元', value: '21086.0000', source: 'mth/04 C33（元 ÷ 10000）', note: '营业利润实际' },
          { metric_key: 'operating_profit', period: '2026-01:2026-08', organization: '集团合并', scenario: 'budget_ytd', unit: '万元', value: '27192.3769', source: 'bud/01 B41:I41 合计', note: '营业利润同期预算' },
          { metric_key: 'operating_profit', period: '2026-01:2026-08', organization: '集团合并', scenario: 'variance', unit: '万元', value: '-6106.3769', source: '本表计算', note: '营业利润缺口' },
          { metric_key: 'operating_profit', period: '2026-01:2026-08', organization: '集团合并', scenario: 'achievement_ratio', unit: '比率', value: '0.775437913263110148', source: '实际 ÷ 同期预算（完整 Decimal，未截断）', note: '达成率' },
          { metric_key: 'revenue', period: '2026-01:2026-08', organization: '集团合并', scenario: 'actual_ytd', unit: '万元', value: '325644.0000', source: 'mth/04 C5（元 ÷ 10000）', note: '累计收入实际' },
          { metric_key: 'revenue', period: '2026-01:2026-08', organization: '集团合并', scenario: 'budget_ytd', unit: '万元', value: '344487.0552', source: 'bud/01 B12:I12 合计', note: '累计收入同期预算' },
          { metric_key: 'revenue', period: '2026-01:2026-08', organization: '集团合并', scenario: 'variance', unit: '万元', value: '-18843.0552', source: '本表计算', note: '收入缺口' },
          { metric_key: 'revenue', period: '2026-01:2026-08', organization: '集团合并', scenario: 'achievement_ratio', unit: '比率', value: '0.945301122594983360', source: '实际 ÷ 同期预算（完整 Decimal）', note: '收入达成率' },
          { metric_key: 'revenue', period: '2026-08', organization: '集团合并', scenario: 'actual_month', unit: '万元', value: '41469.6250', source: 'mth/04 B5（本月列，元 ÷ 10000）', note: '8 月单月实际，非累计' },
          { metric_key: 'revenue', period: '2026-08', organization: '集团合并', scenario: 'budget_month', unit: '万元', value: '44163.6526', source: 'bud/01 I12（8 月列）', note: '8 月单月预算，非累计' },
          { metric_key: 'revenue', period: '2026-08', organization: '集团合并', scenario: 'achievement_ratio', unit: '比率', value: '0.938998985785881306', source: '8 月实际 ÷ 8 月预算', note: '8 月收入达成率' },
          { metric_key: 'operating_profit', period: '2026-08', organization: '集团合并', scenario: 'actual_month', unit: '万元', value: '2155.6250', source: 'mth/04 B33（本月列，元 ÷ 10000）', note: '8 月单月实际，非累计' },
          { metric_key: 'operating_profit', period: '2026-08', organization: '集团合并', scenario: 'budget_month', unit: '万元', value: '3318.6566', source: 'bud/01 I41（8 月列）', note: '8 月单月预算，非累计' },
          { metric_key: 'operating_profit', period: '2026-08', organization: '集团合并', scenario: 'achievement_ratio', unit: '比率', value: '0.649547470503576658', source: '8 月实际 ÷ 8 月预算', note: '8 月利润达成率' },
        ],
        row_count: 20,
        truncated: false,
      },
    };

    render(<BusinessResultView run={current} />);

    let cards = screen.getAllByRole('article');
    expect(within(cards[0]).getByText('收入 · 集团合并')).toBeTruthy();
    expect(within(cards[0]).getByLabelText('收入 · 集团合并实际').textContent).toBe('325,644.00');
    expect(within(cards[0]).getByText('344,487.06')).toBeTruthy();
    expect(within(cards[0]).getByText('94.53%')).toBeTruthy();
    expect(within(cards[1]).getByText('营业利润 · 集团合并')).toBeTruthy();
    expect(within(cards[1]).getByLabelText('营业利润 · 集团合并实际').textContent).toBe('21,086.00');
    expect(within(cards[1]).getByText('77.54%')).toBeTruthy();
    const ytdTable = screen.getAllByRole('region', { name: '业务结果' }).at(-1)!;
    expect(within(ytdTable).getAllByRole('cell', { name: '收入' }).length).toBeGreaterThan(0);
    expect(within(ytdTable).getAllByRole('cell', { name: '集团合并' }).length).toBeGreaterThan(0);
    expect(within(ytdTable).getByRole('cell', { name: '325,644.00' })).toBeTruthy();
    expect(within(ytdTable).getByRole('cell', { name: '344,487.06' })).toBeTruthy();
    expect(within(ytdTable).getByRole('cell', { name: '-18,843.06' })).toBeTruthy();
    expect(within(ytdTable).getAllByRole('cell', { name: '万元' }).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole('tab', { name: '2026 年 8 月' }));
    cards = screen.getAllByRole('article');
    expect(within(cards[0]).getByText('收入 · 集团合并')).toBeTruthy();
    expect(within(cards[0]).getByLabelText('收入 · 集团合并实际').textContent).toBe('41,469.63');
    expect(within(cards[0]).getByText('93.90%')).toBeTruthy();
    expect(within(cards[1]).getByText('营业利润 · 集团合并')).toBeTruthy();
    expect(within(cards[1]).getByLabelText('营业利润 · 集团合并实际').textContent).toBe('2,155.63');
    expect(within(cards[1]).getByText('64.95%')).toBeTruthy();
    expect(screen.queryByText('依据：未知')).toBeNull();
  });


  it('pairs period-suffixed scenarios and base-named variance and 达成率 rows, keeping every unpaired row on screen', () => {
    const row = (metric_key: string, scenario: string, organization: string, value: string, unit: string, metric_label: string, period = '2026-01:2026-08') =>
      ({ metric_key, organization, period, scenario, value, currency: 'CNY', unit, metric_label, source: '预算工作簿 09·预算执行分析' });
    const current: AnalysisRun = {
      ...run([]),
      id: '84b65b7dda9b48ee8e1d65e285e22d7a',
      result: {
        columns: ['metric_key', 'organization', 'period', 'scenario', 'value', 'currency', 'unit', 'metric_label', 'source']
          .map((name) => ({ name, type: name === 'value' ? 'DECIMAL(38,10)' : 'VARCHAR' })),
        rows: [
          row('revenue', 'actual_1_8', '集团合并', '325644.0000', '万元', '营业收入 1-8 月实际'),
          row('revenue', 'budget_1_8', '集团合并', '344487.0552', '万元', '营业收入 1-8 月预算'),
          row('revenue_variance', 'variance_1_8', '集团合并', '-18843.0552', '万元', '营业收入差异'),
          row('revenue_achievement_ratio', 'budget_1_8', '集团合并', '0.945301', '比率', '营业收入达成率'),
          row('revenue_completion_ratio', 'budget_1_8', '集团合并', '0.616750', '比率', '1-8 月实际÷全年 BUD'),
          row('profit', 'actual_1_8', '集团合并', '21086.0000', '万元', '营业利润 1-8 月实际（报告口径）'),
          row('profit', 'budget_1_8', '集团合并', '27192.3769', '万元', '营业利润 1-8 月预算'),
          row('profit_variance', 'variance_1_8', '集团合并', '-6106.3769', '万元', '营业利润差异'),
          row('profit_actual_py', 'actual_py_1_8', '集团合并', '27370.4653', '万元', '上年同期营业利润'),
          row('revenue', 'actual_1_8', '华东区域', '109742.0300', '万元', '营业收入 1-8 月实际'),
          row('revenue', 'budget_1_8', '华东区域', '117814.5700', '万元', '营业收入 1-8 月预算（估算：集团进度率×区域全年预算）'),
          row('revenue_variance_ratio', 'variance_1_8', '华东区域', '-0.068519', '比率', '营业收入差异率'),
          row('receivable_balance', 'actual_1_8', '华东区域', '41400.0000', '万元', '应收账款期末余额'),
          row('collection_gap_pct', 'actual_1_8', '华东区域', '3.3000', 'pct', '收缴率缺口'),
          row('revenue_budget_bud_fy', 'budget_bud_fy', '华东区域', '180576.0000', '万元', '区域全年收入预算（源表列示）', '2026'),
          row('revenue', 'actual_2026_08', '集团合并', '41469.6250', '万元', '8 月营业收入实际', '2026-08'),
          row('revenue', 'budget_2026_08', '集团合并', '44163.6526', '万元', '8 月营业收入预算', '2026-08'),
          row('profit_achievement_ratio', 'actual_2026_08', '集团合并', '0.649547', '比率', '8 月单月达成率', '2026-08'),
        ],
        row_count: 18,
        truncated: false,
      },
    };

    render(<BusinessResultView run={current} />);

    const cards = screen.getAllByRole('article');
    expect(cards).toHaveLength(3);
    expect(within(cards[0]).getByText('收入 · 集团合并')).toBeTruthy();
    expect(within(cards[0]).getByLabelText('收入 · 集团合并实际').textContent).toBe('325,644.00');
    expect(within(cards[0]).getByText('344,487.06')).toBeTruthy();
    expect(within(cards[0]).getByText('-18,843.06')).toBeTruthy();
    expect(within(cards[0]).getByText('94.53%')).toBeTruthy();
    expect(within(cards[1]).getByText('利润 · 集团合并')).toBeTruthy();
    expect(within(cards[1]).getByText('-6,106.38')).toBeTruthy();
    expect(cards[0].querySelector('.analysis-kpi-meta')?.textContent).toBe('2026 年 1–8 月 · 万元 · 依据：计算 · 推断');
    expect(within(cards[0]).getByText('预算')).toBeTruthy();
    expect(within(cards[2]).getByText('收入 · 华东区域')).toBeTruthy();
    // The regional budget is an estimate by its own label, so the card says so twice.
    expect(cards[2].querySelector('.analysis-kpi-meta')?.textContent).toBe('2026 年 1–8 月 · 万元 · 依据：估算 · 推断');
    expect(within(cards[2]).getByText('预算（估算）')).toBeTruthy();
    expect(within(cards[2]).getByText('117,814.57')).toBeTruthy();
    const others = screen.getByRole('region', { name: '其他结果' });
    expect(within(others).getByRole('cell', { name: '应收账款期末余额' })).toBeTruthy();
    expect(within(others).getByRole('cell', { name: '41,400.00' })).toBeTruthy();
    expect(within(others).getByRole('cell', { name: '上年同期营业利润' })).toBeTruthy();
    expect(within(others).getByRole('cell', { name: '-6.85%' })).toBeTruthy();
    expect(within(others).getByRole('cell', { name: '61.68%' })).toBeTruthy();
    // pct is a percent by the unit table (KTD9), in 其他结果 as on a card.
    expect(within(others).getByRole('cell', { name: '3.30%' })).toBeTruthy();
    expect(within(others).queryByRole('columnheader', { name: /metric_key|scenario|value/ })).toBeNull();
    // Only 人民币 in the table, keys on hover, and each organization named once as its group's heading.
    const otherHeaders = within(others).getAllByRole('columnheader').map((header) => header.textContent);
    for (const gone of ['币种', '指标键', '组织']) expect(otherHeaders).not.toContain(gone);
    expect(within(others).getAllByRole('rowheader').map((header) => header.textContent)).toEqual(['集团合并', '华东区域']);
    // A ratio or percent row's unit says %; its value is unchanged.
    for (const value of ['61.68%', '3.30%', '-6.85%']) {
      expect(within(within(others).getByRole('cell', { name: value }).closest('tr')!).getByRole('cell', { name: '%' }), value).toBeTruthy();
    }
    expect(within(within(others).getByRole('cell', { name: '41,400.00' }).closest('tr')!).getByRole('cell', { name: '万元' })).toBeTruthy();
    expect(within(others).queryByRole('cell', { name: '营业收入 1-8 月实际' })).toBeNull();
    fireEvent.click(screen.getByRole('tab', { name: '2026 年' }));
    expect(screen.queryByRole('article')).toBeNull();
    expect(screen.queryByRole('table', { name: '业务结果' })).toBeNull();
    expect(screen.getByRole('table', { name: '其他结果' })).toBeTruthy();
    expect(within(screen.getByRole('region', { name: '其他结果' })).getByRole('cell', { name: '区域全年收入预算（源表列示）' })).toBeTruthy();
    fireEvent.click(screen.getByRole('tab', { name: '2026 年 8 月' }));
    const month = screen.getAllByRole('article');
    expect(month).toHaveLength(1);
    expect(within(month[0]).getByLabelText('收入 · 集团合并实际').textContent).toBe('41,469.63');
    // August has a profit 达成率 but no August profit actual to pair it with.
    expect(within(screen.getByRole('region', { name: '其他结果' })).getByRole('cell', { name: '8 月单月达成率' })).toBeTruthy();
  });

  it('shows an unpaired long-form table by its Chinese labels with ratios as percentages', () => {
    const current: AnalysisRun = {
      ...run([]),
      result: {
        columns: ['metric_key', 'organization', 'period', 'scenario', 'value', 'unit', 'metric_label']
          .map((name) => ({ name, type: name === 'value' ? 'DECIMAL(38,10)' : 'VARCHAR' })),
        rows: [
          { metric_key: 'receivable_balance', organization: '华东区域', period: '2026-01:2026-08', scenario: 'actual_1_8', value: '41400.0000', unit: '万元', metric_label: '应收账款期末余额' },
          { metric_key: 'collection_actual', organization: '华东区域', period: '2026-01:2026-08', scenario: 'actual_1_8', value: '0.902000', unit: '比率', metric_label: '收缴率实际' },
        ],
        row_count: 2,
        truncated: false,
      },
    };
    render(<BusinessResultView run={current} />);
    const table = screen.getAllByRole('region', { name: '业务结果' }).at(-1)!;
    expect(within(table).getByRole('columnheader', { name: '指标' })).toBeTruthy();
    expect(within(table).getByRole('columnheader', { name: '数值' })).toBeTruthy();
    expect(within(table).getByRole('cell', { name: '收缴率实际' })).toBeTruthy();
    expect(within(table).getByRole('cell', { name: '90.20%' })).toBeTruthy();
    // The label leads and the key column goes: the key is the name's hover and stays in 技术信息's raw table.
    const headers = within(table).getAllByRole('columnheader').map((header) => header.textContent);
    expect(headers[0]).toBe('指标');
    expect(headers).not.toContain('指标键');
    expect(within(table).queryByRole('cell', { name: 'receivable_balance' })).toBeNull();
    expect(within(table).getByText('收缴率实际').getAttribute('title')).toBe('指标键 collection_actual');
    expect(within(screen.getByRole('region', { name: '原始计算结果' })).getByRole('cell', { name: 'receivable_balance' })).toBeTruthy();
    expect(screen.queryByRole('region', { name: '其他结果' })).toBeNull();
  });

  describe('long-form estimates and edge cases', () => {
    const longRun = (rows: Record<string, unknown>[], extra: string[] = []): AnalysisRun => ({
      ...run([]),
      result: {
        columns: ['metric_key', 'organization', 'period', 'scenario', 'value', 'unit', ...extra].map((name) => ({ name, type: name === 'value' ? 'DECIMAL' : 'VARCHAR' })),
        rows, row_count: rows.length, truncated: false,
      },
    });
    const pair = (budget: Record<string, unknown>, actual: Record<string, unknown> = {}) => [
      { metric_key: 'revenue', organization: '华东区域', period: '2026-01:2026-08', scenario: 'actual_1_8', value: '90', unit: '万元', ...actual },
      { metric_key: 'revenue', organization: '华东区域', period: '2026-01:2026-08', scenario: 'budget_1_8', value: '100', unit: '万元', ...budget },
    ];

    it.each([
      ['a filled 估算方法 without the word', { 估算方法: '区域年度预算×集团分期比例' }, ['估算方法']],
      ['an estimate basis', { basis: 'user_assumption' }, ['basis']],
      ['估算 only in the source', { source: '按集团进度估算' }, ['source']],
    ])('labels a budget estimated by %s', (_, budget, extra) => {
      render(<BusinessResultView run={longRun(pair(budget), extra)} />);
      const card = screen.getByRole('article');
      expect(within(card).getByText('预算（估算）')).toBeTruthy();
      expect(within(card).getByText(/依据：估算/)).toBeTruthy();
    });

    const withEstimate = (note?: string) => [
      { metric_key: 'revenue', organization: '集团合并', period: '2026-08', scenario: 'actual_ytd', value: '90', unit: '万元' },
      { metric_key: 'revenue', organization: '集团合并', period: '2026-08', scenario: 'budget_ytd', value: '100', unit: '万元', ...(note ? { note } : {}) },
      { metric_key: 'revenue', organization: '集团合并', period: '2026-08', scenario: 'estimated_budget_ytd', value: '110', unit: '万元' },
    ];

    it('keeps an approved budget as 预算 and shows the estimated one beside it', () => {
      render(<BusinessResultView run={longRun(withEstimate(), ['note'])} />);
      const card = screen.getByRole('article');
      expect(within(card).getByText('100.00').previousSibling?.textContent).toBe('预算');
      expect(within(card).getByText('110.00').previousSibling?.textContent).toBe('预算（估算）');
    });

    it('still pairs when an approved budget only mentions an estimate in its note, flagging it rather than dropping the table', () => {
      render(<BusinessResultView run={longRun(withEstimate('另列估算预算供参考'), ['note'])} />);
      const card = screen.getByRole('article');
      expect(within(card).getByText('100.00').previousSibling?.textContent).toBe('预算（估算）');
      expect(within(card).getByText('110.00')).toBeTruthy();
    });

    it('does not call an approved budget an estimate when only the actual declares one', () => {
      render(<BusinessResultView run={longRun(pair({}, { note: '实际含估算调整' }), ['note'])} />);
      const card = screen.getByRole('article');
      expect(within(card).getByText('100.00').previousSibling?.textContent).toBe('预算');
      expect(within(card).getByText(/依据：估算/)).toBeTruthy();
    });

    it('leaves only an ambiguous group unpaired, keeping the other cards', () => {
      render(<BusinessResultView run={longRun([
        ...pair({}),
        { metric_key: 'revenue', organization: '华东区域', period: '2026-01:2026-08', scenario: 'variance_1_8', value: '-10', unit: '万元' },
        { metric_key: 'revenue_variance', organization: '华东区域', period: '2026-01:2026-08', scenario: 'variance_1_8', value: '-10.5', unit: '万元' },
        { metric_key: 'profit', organization: '华东区域', period: '2026-01:2026-08', scenario: 'actual_1_8', value: '9', unit: '万元' },
        { metric_key: 'profit', organization: '华东区域', period: '2026-01:2026-08', scenario: 'budget_1_8', value: '10', unit: '万元' },
      ])} />);
      const cards = screen.getAllByRole('article');
      expect(cards).toHaveLength(1);
      expect(within(cards[0]).getByText('利润 · 华东区域')).toBeTruthy();
      expect(within(screen.getByRole('table', { name: '其他结果' })).getByRole('cell', { name: '-10.50' })).toBeTruthy();
    });

    it('keeps the scenario when one label and key cover two rows, adds the key where only the key differs, and shows rows without a period on every tab', () => {
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
      render(<BusinessResultView run={longRun([
        ...pair({}),
        { metric_key: 'revenue_prior', organization: '华东区域', period: '2026-01:2026-08', scenario: 'actual_py_1_8', value: '80', unit: '万元', metric_label: '营业收入' },
        { metric_key: 'revenue_prior', organization: '华东区域', period: '2026-01:2026-08', scenario: 'actual_ly_1_8', value: '85', unit: '万元', metric_label: '营业收入' },
        { metric_key: 'ratio', organization: '华东区域', period: '2026-01:2026-08', scenario: 'budget_bud_fy', value: '0.48', unit: '比率', metric_label: '1-8 月实际÷全年 BUD' },
        { metric_key: 'revenue_completion_ratio', organization: '华东区域', period: '2026-01:2026-08', scenario: 'budget_bud_fy', value: '0.62', unit: '比率', metric_label: '1-8 月实际÷全年 BUD' },
        { metric_key: 'receivable_balance', organization: '华东区域', period: null, scenario: 'actual', value: '41400', unit: '万元', metric_label: '应收账款期末余额' },
        { metric_key: 'revenue', organization: '华东区域', period: '2026-08', scenario: 'actual_2026_08', value: '12', unit: '万元' },
        { metric_key: 'revenue', organization: '华东区域', period: '2026-08', scenario: 'budget_2026_08', value: '13', unit: '万元' },
      ], ['metric_label'])} />);
      const others = screen.getByRole('table', { name: '其他结果' });
      expect(within(others).getByRole('columnheader', { name: '情景' })).toBeTruthy();
      expect(within(others).getByRole('cell', { name: 'actual_py_1_8' })).toBeTruthy();
      expect(within(others).getByRole('cell', { name: '1-8 月实际÷全年 BUD（revenue_completion_ratio）' })).toBeTruthy();
      expect(within(others).getByRole('cell', { name: '1-8 月实际÷全年 BUD（ratio）' })).toBeTruthy();
      expect(within(others).getByRole('cell', { name: '41,400.00' })).toBeTruthy();
      // This year and last year under one key are told apart by their scenario: no warning for them.
      expect(warn.mock.calls.some(([message]) => String(message).includes('营业收入'))).toBe(false);
      warn.mockRestore();
      fireEvent.click(screen.getByRole('tab', { name: '2026 年 8 月' }));
      expect(within(screen.getByRole('table', { name: '其他结果' })).getByRole('cell', { name: '41,400.00' })).toBeTruthy();
    });

    it('tells apart two metrics one organization and period wrote under one name, and warns the developer', () => {
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
      render(<BusinessResultView run={longRun([
        { metric_key: 'ratio', organization: '集团合并', period: '2026-01:2026-08', scenario: 'budget_1_8', value: '0.48', unit: '比率', metric_label: '1-8 月实际÷全年 BUD' },
        { metric_key: 'revenue_completion_ratio', organization: '集团合并', period: '2026-01:2026-08', scenario: 'budget_1_8', value: '0.62', unit: '比率', metric_label: '1-8 月实际÷全年 BUD' },
      ], ['metric_label'])} />);
      const table = screen.getAllByRole('region', { name: '业务结果' }).at(-1)!;
      const rowOf = (name: string) => within(table).getByRole('cell', { name }).closest('tr')!;
      expect(within(rowOf('1-8 月实际÷全年 BUD（ratio）')).getByRole('cell', { name: '48.00%' })).toBeTruthy();
      expect(within(rowOf('1-8 月实际÷全年 BUD（revenue_completion_ratio）')).getByRole('cell', { name: '62.00%' })).toBeTruthy();
      const headers = within(table).getAllByRole('columnheader').map((header) => header.textContent);
      expect(headers[0]).toBe('指标');
      expect(headers).not.toContain('指标键');
      expect(headers).not.toContain('情景');
      const messages = warn.mock.calls.map(([message]) => String(message));
      expect(messages.some((message) => ['集团合并', '2026-01:2026-08', 'ratio', 'revenue_completion_ratio', '请在 metric_label 写出对象'].every((part) => message.includes(part)))).toBe(true);
      warn.mockRestore();
    });

    // A pair keeps 其他结果 on screen; the rows after it are the ones it shows.
    const unpaired = (organization: unknown, metric_key: string, value: string, extra: Record<string, unknown> = {}) =>
      ({ metric_key, organization, period: '2026-01:2026-08', scenario: 'actual_1_8', value, unit: '万元', metric_label: `${metric_key} 余额`, ...extra });
    const othersOf = () => screen.getByRole('region', { name: '其他结果' });

    it('groups 其他结果 by organization in the order each first appears, keeping each group\'s own row order', () => {
      render(<BusinessResultView run={longRun([
        ...pair({ metric_label: '收入预算' }, { metric_label: '收入实际' }),
        unpaired('集团', 'a', '1'), unpaired('华东', 'b', '2'), unpaired('集团', 'c', '3'), unpaired('华南', 'd', '4'),
      ], ['metric_label'])} />);
      const others = othersOf();
      expect(within(others).getAllByRole('rowheader').map((header) => header.textContent)).toEqual(['集团', '华东', '华南']);
      const groups = others.querySelectorAll('tbody');
      expect(groups).toHaveLength(3);
      expect(Array.from(groups[0].querySelectorAll('td:first-child')).map((cell) => cell.textContent)).toEqual(['a 余额', 'c 余额']);
      const heading = within(others).getByRole('rowheader', { name: '集团' });
      expect(heading.getAttribute('scope')).toBe('rowgroup');
      expect(heading.getAttribute('colspan')).toBe(String(within(others).getAllByRole('columnheader').length));
    });

    it('names rows without an organization 未声明组织', () => {
      render(<BusinessResultView run={longRun([
        ...pair({ metric_label: '收入预算' }, { metric_label: '收入实际' }),
        unpaired('华东区域', 'a', '1'), unpaired(null, 'b', '2'), unpaired('', 'c', '3'),
      ], ['metric_label'])} />);
      expect(within(othersOf()).getAllByRole('rowheader').map((header) => header.textContent)).toEqual(['华东区域', '未声明组织']);
    });

    it('groups by the organization as stored, so one written 「—」 is its own group and not 未声明组织', () => {
      render(<BusinessResultView run={longRun([
        ...pair({ metric_label: '收入预算' }, { metric_label: '收入实际' }),
        unpaired('—', 'a', '1'), unpaired(null, 'b', '2'),
      ], ['metric_label'])} />);
      expect(within(othersOf()).getAllByRole('rowheader').map((header) => header.textContent)).toEqual(['—', '未声明组织']);
    });

    it('does not group 其他结果 that names no organization', () => {
      const columns = ['metric_key', 'period', 'scenario', 'value', 'unit', 'metric_label'];
      const rows = [
        { metric_key: 'revenue', period: '2026-08', scenario: 'actual_1_8', value: '90', unit: '万元', metric_label: '收入实际' },
        { metric_key: 'revenue', period: '2026-08', scenario: 'budget_1_8', value: '100', unit: '万元', metric_label: '收入预算' },
        { metric_key: 'receivable', period: '2026-08', scenario: 'actual_1_8', value: '7', unit: '万元', metric_label: '应收余额' },
      ];
      render(<BusinessResultView run={{ ...run([]), result: { columns: columns.map((name) => ({ name, type: name === 'value' ? 'DECIMAL' : 'VARCHAR' })), rows, row_count: rows.length, truncated: false } }} />);
      const others = othersOf();
      expect(within(others).queryAllByRole('rowheader')).toHaveLength(0);
      expect(others.querySelectorAll('tbody')).toHaveLength(1);
    });

    const longSource = '预算工作簿 09·预算执行分析 G5；预算工作簿 09·预算执行分析 G20；mth/04 C33';
    it('folds a long 其他结果 source into its first reference and a count that opens to every reference', async () => {
      render(<BusinessResultView run={longRun([
        ...pair({ metric_label: '收入预算' }, { metric_label: '收入实际' }),
        unpaired('华东区域', 'receivable', '7', { source: longSource }),
        unpaired('华东区域', 'collection', '8', { source: '预算工作簿 09·预算执行分析 G5；预算工作簿 09·预算执行分析 G5；mth/04 C33' }),
      ], ['metric_label', 'source'])} />);
      const others = othersOf();
      const trigger = within(others).getByRole('button', { name: /^预算工作簿 09·预算执行分析 G5\s*等 3 条$/ });
      expect(trigger.classList.contains('fnd-linkish')).toBe(true);
      expect(trigger.getAttribute('title')).toBe(longSource);
      // A reference listed twice counts once.
      expect(within(others).getByRole('button', { name: /等 2 条$/ })).toBeTruthy();
      fireEvent.click(trigger);
      const dialog = await screen.findByRole('dialog', { name: 'receivable 余额的来源单元格引用' });
      expect(within(dialog).getAllByRole('listitem').map((item) => item.textContent)).toEqual(['预算工作簿 09·预算执行分析 G5', '预算工作簿 09·预算执行分析 G20', 'mth/04 C33']);
      fireEvent.keyDown(dialog, { key: 'Escape' });
      await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
      expect(document.activeElement).toBe(trigger);
    });

    it('folds a source at 25 characters but not at 24', () => {
      const at24 = '预算09表G5；mth04表C33合并利润表本月';
      const at25 = `${at24}列`;
      expect([Array.from(at24).length, Array.from(at25).length]).toEqual([24, 25]);
      render(<BusinessResultView run={longRun([
        ...pair({ metric_label: '收入预算' }, { metric_label: '收入实际' }),
        unpaired('华东区域', 'a', '1', { source: at24 }), unpaired('华东区域', 'b', '2', { source: at25 }),
      ], ['metric_label', 'source'])} />);
      const others = othersOf();
      expect(within(others).getByRole('cell', { name: at24 }).querySelector('button')).toBeNull();
      expect(within(others).getAllByRole('button', { name: /等 2 条$/ })).toHaveLength(1);
    });

    it.each(['口径与来源', 'source_note'])('keeps a long %s whole: it explains a figure rather than listing cells', (field) => {
      render(<BusinessResultView run={longRun([
        ...pair({ metric_label: '收入预算' }, { metric_label: '收入实际' }),
        unpaired('华东区域', 'a', '1', { [field]: longSource }),
      ], ['metric_label', field])} />);
      const others = othersOf();
      expect(within(others).queryByRole('button')).toBeNull();
      expect(within(others).getByRole('cell', { name: longSource })).toBeTruthy();
    });

    it('keeps a short 其他结果 source and every main-table source as plain text', () => {
      const current = longRun([
        ...pair({ metric_label: '营业利润 1-8 月预算', source: longSource }, { metric_label: '营业利润 1-8 月实际（剔除其他收益类）' }),
        unpaired('华东区域', 'receivable', '7', { source: '04表B5/B33' }),
      ], ['metric_label', 'source']);
      render(<BusinessResultView run={current} />);
      expect(within(othersOf()).getByRole('cell', { name: '04表B5/B33' })).toBeTruthy();
      const main = screen.getAllByRole('region', { name: '业务结果' }).at(-1)!;
      expect(within(main).queryByRole('button')).toBeNull();
      expect(within(main).getByRole('cell', { name: new RegExp(longSource) })).toBeTruthy();
      expect(within(main).getByRole('cell', { name: /营业利润 1-8 月实际（剔除其他收益类）/ })).toBeTruthy();
    });

    it.each([
      [['HKD'], true],
      [['CNY'], false],
      [['人民币'], false],
      [['CNY', 'HKD'], true],
    ])('shows the currency column for %j: %s', (currencies, shown) => {
      render(<BusinessResultView run={longRun([
        ...pair({ metric_label: '收入预算' }, { metric_label: '收入实际' }),
        ...currencies.map((currency, index) => unpaired('华东区域', `m${index}`, '7', { currency })),
      ], ['metric_label', 'currency'])} />);
      const others = othersOf();
      expect(within(others).queryByRole('columnheader', { name: '币种' }) !== null).toBe(shown);
      if (shown) expect(within(others).getByRole('cell', { name: currencies.at(-1)! })).toBeTruthy();
    });

    it('does not add a key to one name used by two organizations, nor warn', () => {
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
      render(<BusinessResultView run={longRun([
        ...pair({ metric_label: '收入预算' }, { metric_label: '收入实际' }),
        unpaired('集团合并', 'ratio', '0.48', { metric_label: '1-8 月实际÷全年 BUD', unit: '比率' }),
        unpaired('华东区域', 'revenue_completion_ratio', '0.62', { metric_label: '1-8 月实际÷全年 BUD', unit: '比率' }),
      ], ['metric_label'])} />);
      expect(within(othersOf()).getAllByRole('cell', { name: '1-8 月实际÷全年 BUD' })).toHaveLength(2);
      expect(warn).not.toHaveBeenCalled();
      warn.mockRestore();
    });

    it.each([
      ['推算', { metric_label: '营业收入 1-8 月预算（按集团进度率推算）' }],
      ['预估', { metric_label: '1-8 月预估预算' }],
      ['English estimated', { note: 'budget (estimated from group progress)' }],
    ])('labels a budget worded as %s an estimate', (_, budget) => {
      render(<BusinessResultView run={longRun(pair(budget), ['metric_label', 'note'])} />);
      const card = screen.getByRole('article');
      expect(within(card).getByText('预算（估算）')).toBeTruthy();
      expect(within(card).getByText(/依据：估算/)).toBeTruthy();
    });

    it.each([
      ['非估算 in the label', { metric_label: '1-8 月批复预算（非估算）' }, ['metric_label']],
      ['不含估算 in the note', { note: '批复预算，不含估算调整' }, ['note']],
      ['估算方法 无', { 估算方法: '无' }, ['估算方法']],
    ])('keeps an approved budget as 预算 when %s', (_, budget, extra) => {
      render(<BusinessResultView run={longRun(pair(budget), extra)} />);
      const card = screen.getByRole('article');
      expect(within(card).getByText('100.00').previousSibling?.textContent).toBe('预算');
      expect(within(card).getByText(/依据：计算/)).toBeTruthy();
    });

    it('puts the run\'s assumptions and each side\'s own label beside the numbers', () => {
      const current = longRun(pair({ metric_label: '营业利润 1-8 月预算' }, { metric_label: '营业利润 1-8 月实际（剔除其他收益类）' }), ['metric_label']);
      render(<BusinessResultView run={{ ...current, assumptions: ['区域层级的 1-8 月预算为推算值，不是批复预算。'] }} />);
      const card = screen.getByRole('article');
      expect(within(card).getByText('营业利润 1-8 月实际（剔除其他收益类）')).toBeTruthy();
      expect(within(card).getByText('预算：营业利润 1-8 月预算')).toBeTruthy();
      expect(screen.getByLabelText('本次计算的假设').textContent).toBe('本次计算的假设：区域层级的 1-8 月预算为推算值，不是批复预算。');
      expect(within(screen.getByRole('table', { name: '业务结果' })).getByRole('cell', { name: /营业利润 1-8 月实际（剔除其他收益类）/ })).toBeTruthy();
    });

    it('marks an unpaired estimate whose label does not say so', () => {
      render(<BusinessResultView run={longRun([
        ...pair({}),
        { metric_key: 'profit', organization: '华东区域', period: '2026-01:2026-08', scenario: 'estimated_budget_ytd', value: '12', unit: '万元', metric_label: '营业利润预算' },
      ], ['metric_label'])} />);
      expect(within(screen.getByRole('table', { name: '其他结果' })).getByRole('cell', { name: '营业利润预算（估算）' })).toBeTruthy();
    });

    it.each([
      ['a bare year suffix', [
        { metric_key: 'revenue', organization: '集团', period: '2026', scenario: 'actual_2026', value: '325644', unit: '万元' },
        { metric_key: 'revenue', organization: '集团', period: '2026', scenario: 'budget_2026', value: '528000', unit: '万元' }]],
      ['a year-to-date actual beside a monthly budget', [
        { metric_key: 'revenue', organization: '集团', period: '2026-08', scenario: 'actual_ytd', value: '325644', unit: '万元' },
        { metric_key: 'revenue', organization: '集团', period: '2026-08', scenario: 'budget_month', value: '44163', unit: '万元' }]],
    ])('makes no card from %s', (_, rows) => {
      render(<BusinessResultView run={longRun(rows)} />);
      expect(screen.queryByRole('article')).toBeNull();
    });

    it('does not read a favorable-signed variance as actual minus budget', () => {
      const expense = (scenario: string, value: string, metric_key = 'expense') => ({ metric_key, organization: '集团', period: '2026-08', scenario, value, unit: '万元' });
      render(<BusinessResultView run={longRun([expense('actual_ytd', '120'), expense('budget_ytd', '100'), expense('variance_favorable', '-20'), expense('variance_favorable', '-20', 'expense_variance')])} />);
      const card = screen.getByRole('article');
      expect(within(card).queryByText('-20.00')).toBeNull();
      expect(within(screen.getByRole('table', { name: '其他结果' })).getAllByRole('cell', { name: '-20.00' })).toHaveLength(2);
    });

    it('follows a Chinese 期间 column for the other results and the period tabs', () => {
      const current: AnalysisRun = { ...run([]), result: {
        columns: ['metric_key', 'organization', '期间', 'scenario', 'value', 'unit', 'metric_label'].map((name) => ({ name, type: name === 'value' ? 'DECIMAL' : 'VARCHAR' })),
        rows: [
          { metric_key: 'revenue', organization: '集团', 期间: '2026-08', scenario: 'actual_2026_08', value: '90', unit: '万元', metric_label: '8 月收入实际' },
          { metric_key: 'revenue', organization: '集团', 期间: '2026-08', scenario: 'budget_2026_08', value: '100', unit: '万元', metric_label: '8 月收入预算' },
          { metric_key: 'revenue_budget_fy', organization: '集团', 期间: '2026', scenario: 'budget_bud_fy', value: '1200', unit: '万元', metric_label: '全年收入预算' },
        ], row_count: 3, truncated: false } };
      render(<BusinessResultView run={current} />);
      expect(screen.getByRole('tab', { name: '2026 年' })).toBeTruthy();
      expect(screen.queryByRole('table', { name: '其他结果' })).toBeNull();
      fireEvent.click(screen.getByRole('tab', { name: '2026 年' }));
      expect(within(screen.getByRole('table', { name: '其他结果' })).getByRole('cell', { name: '全年收入预算' })).toBeTruthy();
    });

    it('reads a 达成率 given in % as a percentage, not a fraction', () => {
      render(<BusinessResultView run={longRun([
        ...pair({}).map((row) => ({ ...row, scenario: row.scenario === 'actual_1_8' ? 'actual_ytd' : 'budget_ytd' })),
        { metric_key: 'revenue', organization: '华东区域', period: '2026-01:2026-08', scenario: 'achievement_ratio', value: '90', unit: '%' },
      ])} />);
      const card = screen.getByRole('article');
      expect(within(card).getByText('90.00%')).toBeTruthy();
      expect(within(card).queryByText('9,000.00%')).toBeNull();
    });
  });

  it('treats an empty backend no-comparable comparison as authoritative instead of falling back locally', () => {
    const previous = run([{ metric_key: 'revenue', actual: '325644' }]);
    const current = run([{ metric_key: 'revenue', actual: '344487.0552' }]);
    render(<RevisionDiff current={current} previous={previous} currentRevision={4} previousRevision={3}
      comparison={{ summary: { status: 'no_comparable_runs', issue_count: 0, compared_business_keys: 0 }, issues: [] }} />);
    expect(screen.getByText(/无可比计算/)).toBeTruthy();
    expect(screen.getByText('没有找到可以比较的上一次计算；系统不会按行序或字段名猜测对应关系。')).toBeTruthy();
    expect(screen.queryByText(/344,487.06/)).toBeNull();
  });

  it('formats backend revision issue values with the changed column semantics', () => {
    const previous = run([{ metric_key: 'revenue', attainment_rate: '0.945301', ratio_delta: '0.012345' }]);
    const current = run([{ metric_key: 'revenue', attainment_rate: '0.938999', ratio_delta: '-0.006532' }]);
    render(<RevisionDiff current={current} previous={previous} currentRevision={5} previousRevision={4}
      comparison={{ summary: { status: 'needs_attention', issue_count: 2, compared_business_keys: 1 }, issues: [{
        code: 'revision_numeric_regression',
        severity: 'warning',
        business_key: "{'metric': 'revenue'}",
        column: 'attainment_rate',
        old_value: '0.945301',
        new_value: '0.938999',
      }, {
        code: 'revision_numeric_regression',
        severity: 'warning',
        business_key: "{'metric': 'revenue'}",
        column: 'ratio_delta',
        old_value: '0.012345',
        new_value: '-0.006532',
      }] }} />);
    expect(screen.getByText(/修订 4 → 修订 5 · 需要处理 · 2 项问题 · 1 个可比指标/)).toBeTruthy();
    expect(screen.getByText(/94.53% → 93.90%/)).toBeTruthy();
    expect(screen.getByText(/1.23 个百分点 → -0.65 个百分点/)).toBeTruthy();
  });

  it('renders long-form value regressions with the financial scenario and unit', () => {
    const previous = run([{ metric_key: 'revenue', value: '325644.0000' }]);
    const current = run([{ metric_key: 'revenue', value: '344487.0552' }]);
    render(<RevisionDiff current={current} previous={previous} comparison={{
      summary: { status: 'needs_attention', issue_count: 2, compared_business_keys: 2 },
      issues: [{
        code: 'revision_numeric_regression', severity: 'error', column: 'value',
        business_key: "{'metric': 'revenue', 'period': '2026-01:2026-08', 'organization': '集团合并', 'scenario': 'actual_ytd', 'unit': '万元'}",
        old_value: '325644.0000', new_value: '344487.0552',
      }, {
        code: 'revision_numeric_regression', severity: 'error', column: 'value',
        business_key: "{'metric': 'revenue', 'period': '2026-01:2026-08', 'organization': '集团合并', 'scenario': 'achievement_ratio', 'unit': '比率'}",
        old_value: '0.945301', new_value: '0.938999',
      }],
    }} />);
    expect(screen.getByText('收入 · 累计实际')).toBeTruthy();
    expect(screen.getByText('收入 · 达成率')).toBeTruthy();
    expect(screen.getByText(/325,644.00 → 344,487.06/)).toBeTruthy();
    expect(screen.getByText(/94.53% → 93.90%/)).toBeTruthy();
  });

  it('shows changed values when a revised run also changed a source hash', () => {
    const previous = run([{ metric_key: 'revenue', value: '325644.0000' }]);
    const current = run([{ metric_key: 'revenue', value: '344487.0552' }]);
    render(<RevisionDiff current={current} previous={previous} comparison={{
      summary: { status: 'needs_attention', issue_count: 1, compared_business_keys: 1 },
      issues: [{
        code: 'revision_basis_changed', severity: 'warning',
        business_key: "{'metric': 'revenue', 'scenario': 'actual_ytd', 'unit': '万元'}",
        changed_columns: [{ column: 'value', old_value: '325644.0000', new_value: '344487.0552' }],
        changed_hash_aliases: [{ kind: 'source_hashes', alias: 'budget' }],
      }],
    }} />);
    expect(screen.getByText(/325,644.00 → 344,487.06/)).toBeTruthy();
    expect(screen.getByText(/budget/)).toBeTruthy();
  });


  it('renders backend revision comparison, affected claims and unresolved issues before local row comparison', () => {
    const previous = run([{ metric_key: 'revenue', actual: '325644' }]);
    const current = run([{ metric_key: 'revenue', actual: '325644' }]);
    render(<RevisionDiff current={current} previous={previous} currentRevision={3} previousRevision={2}
      comparison={{ summary: { status: 'needs_attention', issue_count: 1, compared_business_keys: 1 }, issues: [{
        code: 'revision_numeric_regression',
        severity: 'error',
        business_key: "{'metric': 'revenue'}",
        column: 'actual',
        old_value: '325644',
        new_value: '344487.0552',
        message: '同一来源和口径下的关键数值发生变化，需要解释或修正。',
      }] }}
      evidence={{
        affected_claims: [{ id: 'claim_1', label: '收入达成率结论', message: '引用了已变化的收入实际数。' }],
        unresolved_issues: [{ code: 'source_gap', severity: 'warning', message: '区域收入假设仍待经理确认。' }],
      }} />);
    expect(screen.getByText(/修订 2 → 修订 3 · 需要处理/)).toBeTruthy();
    expect(screen.getByText('revenue · 实际')).toBeTruthy();
    expect(screen.getByText(/325,644.00 → 344,487.06/)).toBeTruthy();
    fireEvent.click(screen.getByText('受影响结论 · 1 项'));
    expect(screen.getByText(/收入达成率结论：引用了已变化的收入实际数。/)).toBeTruthy();
    fireEvent.click(screen.getByText('未解决问题 · 1 项'));
    expect(screen.getByText('区域收入假设仍待经理确认。')).toBeTruthy();
  });
});

// Without a backend comparison the local diff can only line rows up by business identity. It may say nothing
// changed only when every row of both results was lined up; otherwise it sends the reader to the raw tables.
describe('local revision diff coverage', () => {
  const noChange = '可比较指标没有发现数值变化。';
  const sqlRun = (profits: string[]): AnalysisRun => ({ ...run([]), result: {
    columns: [{ name: '区域', type: 'VARCHAR' }, { name: '经营利润', type: 'DECIMAL(38,2)' }],
    rows: ['华东', '华南', '华北'].map((region, index) => ({ 区域: region, 经营利润: profits[index] })),
    row_count: 3, truncated: false,
  } });

  it('keeps the no-change sentence when every row was lined up and none changed', () => {
    const previous = run([{ metric_key: 'revenue', actual: '325644' }, { metric_key: 'cost', actual: '120000' }]);
    const current = run([{ metric_key: 'revenue', actual: '325644' }, { metric_key: 'cost', actual: '120000' }]);
    render(<RevisionDiff current={current} previous={previous} tablesBelow />);
    expect(screen.getByText(noChange)).toBeTruthy();
    expect(screen.queryByText(/没有可对齐的指标/)).toBeNull();
  });

  it('says no metric could be lined up, not that nothing changed, when rows carry no business identity', () => {
    render(<RevisionDiff current={sqlRun(['240', '120', '55'])} previous={sqlRun(['250', '130', '65'])} tablesBelow />);
    expect(screen.getByText('两次结果没有可对齐的指标，请直接对照下方两张结果表。')).toBeTruthy();
    expect(screen.queryByText(noChange)).toBeNull();
  });

  it('lists the changed values when lined-up rows changed', () => {
    const previous = run([{ metric_key: 'revenue', actual: '325644' }]);
    const current = run([{ metric_key: 'revenue', actual: '344487.0552' }]);
    render(<RevisionDiff current={current} previous={previous} tablesBelow />);
    expect(screen.getByText('325,644.00 → 344,487.06')).toBeTruthy();
    expect(screen.queryByText(noChange)).toBeNull();
    expect(screen.queryByText(/没有可对齐的指标/)).toBeNull();
  });

  it('does not claim no change when only part of the rows lined up, and points nowhere without tables below', () => {
    const previous = run([{ metric_key: 'revenue', actual: '325644' }, { actual: '10' }]);
    const current = run([{ metric_key: 'revenue', actual: '325644' }, { actual: '20' }]);
    render(<RevisionDiff current={current} previous={previous} />);
    expect(screen.getByText('两次结果有部分行没有可对齐的指标，无法据此判断数值是否变化。')).toBeTruthy();
    expect(screen.queryByText(noChange)).toBeNull();
  });
});

// U6: a declared run pairs strictly by its declaration; a script run saved without one keeps the old inference and
// says 推断; every value reads by its declared unit through one formatter, on a card and in 其他结果 alike.
describe('result rows by declaration, inference and unit', () => {
  const ytd = '2026-01:2026-08';
  const columns = ['metric_key', 'organization', 'period', 'scenario', 'value', 'unit', 'metric_label'];
  const longRun = (rows: Record<string, unknown>[], patch: Partial<AnalysisRun> = {}): AnalysisRun => ({
    ...run([]),
    result: { columns: columns.map((name) => ({ name, type: name === 'value' ? 'DECIMAL' : 'VARCHAR' })), rows, row_count: rows.length, truncated: false },
    ...patch,
  });
  const row = (metric_key: string, organization: string, scenario: string, value: string, unit: string, metric_label: string, period = ytd) =>
    ({ metric_key, organization, period, scenario, value, unit, metric_label });

  it.each([{ unit: '比率', value: '0.945' }, { unit: '%', value: '94.5' }])('reads achievement_pct $value in $unit as 94.50% on the card and in 其他结果', ({ unit, value }) => {
    render(<BusinessResultView run={longRun([
      row('revenue', '华东区域', 'actual_ytd', '90', '万元', '收入实际'),
      row('revenue', '华东区域', 'budget_ytd', '100', '万元', '收入预算'),
      row('revenue', '华东区域', 'achievement_pct', value, unit, '收入达成率'),
      // No actual to pair with: this one stays in 其他结果.
      row('revenue', '华南区域', 'achievement_pct', value, unit, '华南收入达成率'),
    ])} />);
    const card = screen.getByRole('article');
    expect(within(card).getByText('94.50%')).toBeTruthy();
    expect(within(screen.getByRole('table', { name: '其他结果' })).getByRole('cell', { name: '94.50%' })).toBeTruthy();
  });

  it('keeps a row whose unit is - out of the amount pairing and shows it as written with 未标单位', () => {
    render(<BusinessResultView run={longRun([
      row('revenue', '华东区域', 'actual_1_8', '90', '万元', '收入实际'),
      row('revenue', '华东区域', 'budget_1_8', '0.945', '-', '收入达成率'),
      row('profit', '华东区域', 'actual_1_8', '9', '万元', '利润实际'),
      row('profit', '华东区域', 'budget_1_8', '10', '万元', '利润预算'),
    ])} />);
    const cards = screen.getAllByRole('article');
    expect(cards).toHaveLength(1);
    expect(within(cards[0]).getByText('利润 · 华东区域')).toBeTruthy();
    const others = screen.getByRole('table', { name: '其他结果' });
    expect(within(others).getByRole('cell', { name: '0.945（未标单位）' })).toBeTruthy();
    expect(screen.queryByText('0.95')).toBeNull();
  });

  // Huachen's long form (runs 84b65b7d / 269d9fd9) in miniature: a group pair and two regional pairs whose budgets
  // were estimated, one saying so in its label (推算) and one saying nothing (declared only in grain_basis).
  const huachenRows = [
    row('revenue', '集团合并', 'actual_1_8', '325644.0000', '万元', '营业收入 1-8 月实际'),
    row('revenue', '集团合并', 'budget_1_8', '344487.0552', '万元', '营业收入 1-8 月预算'),
    row('revenue_variance', '集团合并', 'variance_1_8', '-18843.0552', '万元', '营业收入差异'),
    row('revenue_achievement_ratio', '集团合并', 'budget_1_8', '0.945301', '比率', '营业收入达成率'),
    row('revenue', '华东区域', 'actual_1_8', '109742.0280', '万元', '营业收入 1-8 月实际'),
    row('revenue', '华东区域', 'budget_1_8', '117814.5729', '万元', '营业收入 1-8 月预算（推算：集团进度率×区域全年预算）'),
    row('profit', '华南区域', 'actual_1_8', '5210.1100', '万元', '营业利润 1-8 月实际'),
    row('profit', '华南区域', 'budget_1_8', '6021.3300', '万元', '营业利润 1-8 月预算'),
  ];
  const cardFor = (title: string) => screen.getAllByRole('article').find((card) => within(card).queryByText(title))!;

  it('says 推断 on every card of a script run saved without declarations, and still reads 估算 from its wording', () => {
    render(<BusinessResultView run={longRun(huachenRows)} />);
    const cards = screen.getAllByRole('article');
    expect(cards).toHaveLength(3);
    for (const card of cards) expect(within(card).getByText('推断')).toBeTruthy();
    const east = cardFor('收入 · 华东区域');
    expect(within(east).getByText('预算（估算）')).toBeTruthy();
    expect(within(east).getByText('117,814.57')).toBeTruthy();
    // Without a declaration nothing else knows the southern budget is an estimate: its label says nothing.
    expect(within(cardFor('利润 · 华南区域')).getByText('预算')).toBeTruthy();
  });

  it.each([
    ['a finance engine run', { engine: 'finance' }],
    ['a structured aggregate run', { engine: 'structured_aggregate' }],
    ['a SQL run', { engine: undefined }],
  ])('pairs %s as before and never says 推断', (_, patch) => {
    render(<BusinessResultView run={longRun(huachenRows, patch)} />);
    expect(screen.getAllByRole('article')).toHaveLength(3);
    expect(screen.queryByText(/推断/)).toBeNull();
  });

  // What foundry.result_semantics.declare_rows wrote for Huachen-shaped rows (tests/test_result_semantics.py keeps the
  // file current): 华东's budget is an estimate by its own label, 华南's only by the pinned requirements' grain_basis.
  type Declarations = NonNullable<AnalysisRun['row_declarations']>;
  const declaration = huachenDeclared.row_declarations as unknown as Declarations;
  const declaredRun = (patch: Partial<Declarations> = {}, rows: Record<string, unknown>[] = huachenDeclared.rows): AnalysisRun =>
    longRun(rows, { row_declarations: { ...declaration, ...patch } });

  it('pairs a declared Huachen run by its declaration: both regional budgets read 预算（估算） and no card says 推断', () => {
    render(<BusinessResultView run={declaredRun()} />);
    expect(screen.getAllByRole('article')).toHaveLength(3);
    expect(screen.queryByText(/推断/)).toBeNull();
    for (const title of ['收入 · 华东区域', '利润 · 华南区域']) {
      expect(within(cardFor(title)).getByText('预算（估算）'), title).toBeTruthy();
      expect(within(cardFor(title)).getByText(/依据：估算/), title).toBeTruthy();
    }
    const group = cardFor('收入 · 集团合并');
    expect(within(group).getByText('预算')).toBeTruthy();
    expect(within(group).getByText('-18,843.06')).toBeTruthy();
    expect(within(group).getByText('94.53%')).toBeTruthy();
    // A row in no pair stays in 其他结果.
    expect(within(screen.getByRole('table', { name: '其他结果' })).getByRole('cell', { name: '应收账款期末余额' })).toBeTruthy();
  });

  it('shows 其他结果 of a declared run as declared: a budget estimated by grain_basis says 估算, an unmarked 达成率 says 未标单位', () => {
    // Leave 华南's pair out, as a declaration that could not pair it would: its rows fall to 其他结果.
    render(<BusinessResultView run={declaredRun({ pairs: (declaration as Declarations & { pairs: unknown[] }).pairs.slice(0, 2) } as Partial<Declarations>)} />);
    const others = screen.getByRole('table', { name: '其他结果' });
    // Its label says nothing of an estimate; the pinned requirements do.
    expect(within(others).getByRole('cell', { name: '营业利润 1-8 月预算（估算）' })).toBeTruthy();
    // A 达成率 with no unit at all: no table unit to read, but the backend declared it unmarked, so it is shown as written.
    expect(within(others).getByRole('cell', { name: '0.931481（未标单位）' })).toBeTruthy();
    expect(within(others).queryByRole('cell', { name: '0.93' })).toBeNull();
    expect(within(others).getByRole('cell', { name: '0.865271（未标单位）' })).toBeTruthy();
  });

  // The pinned requirements' fingerprint is ffff…; the task's current version is read with the run (current_requirements).
  const pinned = { id: declaration.requirements_id!, fingerprint: declaration.requirements_fingerprint };
  it.each([
    ['the run read the current version', pinned, false],
    ['a later version changed what the requirements mean', { id: 'b2'.repeat(16), fingerprint: 'e'.repeat(64) }, true],
    ['a later version only renamed items', { id: 'b2'.repeat(16), fingerprint: pinned.fingerprint }, false],
    ['a later version could not be fingerprinted', { id: 'b2'.repeat(16), fingerprint: null }, true],
  ])('notes 依据旧版需求 on each card only when %s', (_, current, noted) => {
    render(<BusinessResultView run={declaredRun({ current_requirements: current } as Partial<Declarations>)} />);
    for (const card of screen.getAllByRole('article')) expect(within(card).queryByText(/依据旧版需求/) !== null).toBe(noted);
  });

  it('puts a card\'s other notes in one line, 推断 · 依据旧版需求 · 未标单位, while the estimate stays on its figure', () => {
    // 华南's pair as the backend returns one whose metric its vocabulary does not name: paired from scenarios alone.
    const pairs = (declaration as Declarations & { pairs: Record<string, unknown>[] }).pairs.map((pair, index) => index === 2 ? { ...pair, declared: false } : pair);
    render(<BusinessResultView run={declaredRun({ pairs, current_requirements: { id: 'b2'.repeat(16), fingerprint: 'e'.repeat(64) } } as Partial<Declarations>)} />);
    // Its 达成率 row was left out for an unmarked unit, so the card's 达成率 stays empty and says why.
    const south = cardFor('利润 · 华南区域');
    expect(Array.from(south.querySelectorAll('.analysis-kpi-note')).map((note) => note.textContent)).toEqual(['推断', '依据旧版需求', '未标单位']);
    expect(within(south).getByText('预算（估算）')).toBeTruthy();
    expect(within(cardFor('收入 · 集团合并')).getByText('依据旧版需求')).toBeTruthy();
  });

  it('says 推断 · 未标单位 on an inferred card whose 达成率 row was left out for an unmarked unit', () => {
    render(<BusinessResultView run={longRun([
      row('revenue', '华东区域', 'actual_1_8', '90', '万元', '收入实际'),
      row('revenue', '华东区域', 'budget_1_8', '100', '万元', '收入预算'),
      row('revenue_achievement_ratio', '华东区域', 'budget_1_8', '0.9', '-', '收入达成率'),
    ])} />);
    const card = screen.getByRole('article');
    expect(Array.from(card.querySelectorAll('.analysis-kpi-note')).map((note) => note.textContent)).toEqual(['推断', '未标单位']);
    expect(within(screen.getByRole('table', { name: '其他结果' })).getByRole('cell', { name: '0.9（未标单位）' })).toBeTruthy();
  });

  it('never pairs a declared actual row with a budget row the declaration does not call one', () => {
    // The declaration gives the second row no role; the old inference would read budget_1_8 as the budget.
    const [actual, budget] = [declaration.rows[6], declaration.rows[7]];
    render(<BusinessResultView run={declaredRun({
      row_count: 2, pairs: [], warnings: [],
      rows: [{ ...actual, row: 0 }, { ...budget, row: 1, role: null, period_key: null, value: null, estimate: false, estimate_sources: [] }],
    } as Partial<Declarations>, huachenDeclared.rows.slice(6, 8))} />);
    expect(screen.queryByRole('article')).toBeNull();
    const table = screen.getAllByRole('region', { name: '业务结果' }).at(-1)!;
    expect(within(table).getByRole('cell', { name: '5,210.11' })).toBeTruthy();
    expect(within(table).getByRole('cell', { name: '6,021.33' })).toBeTruthy();
  });

  it('renders a pair whose rows sit past row 1000 of the result preview from the declaration values', () => {
    const detail = Array.from({ length: 1000 }, (_, index) => row(`line_${index}`, '集团合并', 'actual_py_1_8', `${index}.0000`, '万元', '明细'));
    const detailEntries = detail.map((item, index) => ({ row: index, fields: {}, role: null, metric: item.metric_key, organization: '集团合并', period: ytd,
      period_key: null, span: null, unit: '万元', unit_kind: 'amount', value: null, scope_label: '明细', estimate: false, estimate_sources: [] }));
    const [actual, budget] = [declaration.rows[4], declaration.rows[5]];
    const east = (declaration as Declarations & { pairs: Record<string, unknown>[] }).pairs[1];
    const current = declaredRun({
      row_count: 1500, warnings: [],
      rows: [...detailEntries, { ...actual, row: 1200 }, { ...budget, row: 1201 }],
      pairs: [{ ...east, members: { actual: 1200, budget: 1201 } }],
    } as Partial<Declarations>, detail);
    render(<BusinessResultView run={{ ...current, result: { ...current.result!, row_count: 1500, truncated: true } }} />);
    const card = screen.getByRole('article');
    expect(within(card).getByLabelText('收入 · 华东区域实际').textContent).toBe('109,742.03');
    expect(within(card).getByText('117,814.57')).toBeTruthy();
    expect(within(card).getByText('预算（估算）')).toBeTruthy();
    // The row's own label travels with its declaration.
    expect(within(card).getByText('营业收入 1-8 月实际')).toBeTruthy();
    expect(within(card).queryByText(/推断/)).toBeNull();
  });

  // One declared comparison with an approved budget row beside an estimated one. The backend pairs it even when the
  // approved row has no value, so the budget shown is picked by value, as the inference does for older runs.
  const withEstimatedBudget = (budget: string | null) => {
    const measures = ['actual', 'budget', 'estimated_budget'] as const;
    const scenarios = ['actual_1_8', 'budget_1_8', 'estimated_budget_1_8'];
    const labels = ['营业收入 1-8 月实际', '营业收入 1-8 月预算', '营业收入 1-8 月估算预算'];
    const values = ['1000.0000', budget, '800.0000'];
    const rows = scenarios.map((scenario, index) => ({ ...row('revenue', '西部区域', scenario, '', '万元', labels[index]), value: values[index] }));
    const entries = measures.map((measure, index) => ({ ...declaration.rows[4], row: index, fields: {}, role: measure === 'estimated_budget' ? 'budget' : measure,
      organization: '西部区域', value: values[index], scope_label: labels[index], estimate: measure === 'estimated_budget', estimate_sources: [] }));
    const pair = { ...declaration.pairs![1], organization: '西部区域', members: { actual: 0, budget: 1, estimated_budget: 2 },
      estimate: { estimated: true, measures: ['estimated_budget'] }, conclusion: null };
    return declaredRun({ row_count: 3, warnings: [], rows: entries, pairs: [pair] } as Partial<Declarations>, rows);
  };
  const businessTable = () => {
    const table = screen.getByRole('table', { name: '业务结果' });
    const headers = within(table).getAllByRole('columnheader').map((cell) => cell.textContent);
    const cells = within(table).getAllByRole('cell').map((cell) => cell.textContent);
    return { headers, row: Object.fromEntries(headers.map((header, index) => [header, cells[index]])) };
  };

  it.each([['null', null], ['empty', '']])('reads the estimate as 预算（估算） when the declared approved budget beside it is %s', (_, budget) => {
    render(<BusinessResultView run={withEstimatedBudget(budget)} />);
    const card = screen.getByRole('article');
    expect(within(card).getAllByText('800.00').map((node) => node.previousSibling?.textContent)).toEqual(['预算（估算）']);
    expect(within(card).queryByText('预算')).toBeNull();
    // The table's one budget column holds the estimate its row reads against, 依据 估算, as an estimate-only comparison
    // always has; no 同期预算（估算） column beside it makes that figure read as an approved budget.
    const { headers, row: shown } = businessTable();
    expect(headers).not.toContain('同期预算（估算）');
    expect(shown).toMatchObject({ 实际: '1,000.00', 同期预算: '800.00', 依据: '估算' });
  });

  it('keeps a declared approved budget as 预算 and shows the estimated one beside it', () => {
    render(<BusinessResultView run={withEstimatedBudget('900.0000')} />);
    const card = screen.getByRole('article');
    expect(within(card).getByText('900.00').previousSibling?.textContent).toBe('预算');
    expect(within(card).getByText('800.00').previousSibling?.textContent).toBe('预算（估算）');
    expect(businessTable().row).toMatchObject({ 同期预算: '900.00', '同期预算（估算）': '800.00' });
  });

  it('writes — for a missing rate on an estimated-budget card, with no reason made up beside it', () => {
    render(<BusinessResultView run={withEstimatedBudget(null)} />);
    const last = screen.getByRole('article').querySelector('.analysis-kpi-list')!.lastElementChild as HTMLElement;
    expect(last.querySelector('dt')?.textContent).toBe('达成率');
    expect(last.querySelector('dd')?.textContent).toBe('—');
    expect(screen.getByRole('article').textContent).not.toMatch(/不计|估算预算不/);
  });
});

// The backend's conclusion sentences (R6, KTD7): shown above the KPI cards as they were written, with their 脚本结果
// basis. The frontend does no arithmetic; a run without declared conclusions renders as it did before them.
describe('script conclusion sentences', () => {
  const ytd = '2026-01:2026-08';
  const huachenRow = (metric_key: string, scenario: string, organization: string, value: string, unit: string, metric_label: string, period = ytd) =>
    ({ metric_key, organization, period, scenario, value, currency: 'CNY', unit, metric_label, source: '预算工作簿 09·预算执行分析' });
  const huachen: AnalysisRun = {
    ...run([]),
    id: '84b65b7dda9b48ee8e1d65e285e22d7a',
    result: {
      columns: ['metric_key', 'organization', 'period', 'scenario', 'value', 'currency', 'unit', 'metric_label', 'source']
        .map((name) => ({ name, type: name === 'value' ? 'DECIMAL(38,10)' : 'VARCHAR' })),
      rows: [
        huachenRow('revenue', 'actual_1_8', '集团合并', '325644.0000', '万元', '营业收入 1-8 月实际'),
        huachenRow('revenue', 'budget_1_8', '集团合并', '344487.0552', '万元', '营业收入 1-8 月预算'),
        huachenRow('revenue_variance', 'variance_1_8', '集团合并', '-18843.0552', '万元', '营业收入差异'),
        huachenRow('revenue_achievement_ratio', 'budget_1_8', '集团合并', '0.945301', '比率', '营业收入达成率'),
        huachenRow('profit', 'actual_1_8', '集团合并', '21086.0000', '万元', '营业利润 1-8 月实际（报告口径）'),
        huachenRow('profit', 'budget_1_8', '集团合并', '27192.3769', '万元', '营业利润 1-8 月预算'),
        huachenRow('revenue', 'actual_1_8', '华东区域', '109742.0280', '万元', '营业收入 1-8 月实际'),
        huachenRow('revenue', 'budget_1_8', '华东区域', '117814.5729', '万元', '营业收入 1-8 月预算（估算：集团进度率×区域全年预算）'),
        huachenRow('revenue_variance', 'variance_1_8', '华东区域', '-8072.5449', '万元', '营业收入差异'),
        huachenRow('profit', 'actual_1_8', '华东区域', '12451.5443', '万元', '营业利润 1-8 月实际'),
        huachenRow('profit', 'budget_1_8', '华东区域', '13936.4958', '万元', '营业利润 1-8 月预算（估算）'),
        huachenRow('revenue', 'actual_2026_08', '集团合并', '41469.6250', '万元', '8 月营业收入实际', '2026-08'),
        huachenRow('revenue', 'budget_2026_08', '集团合并', '44163.6526', '万元', '8 月营业收入预算', '2026-08'),
      ],
      row_count: 13,
      truncated: false,
    },
  };
  const sentences = {
    groupRevenue: '1-8 月集团合并收入比预算少 18,843.06 万元（达成 94.53%），实际 325,644.00 万元，预算 344,487.06 万元',
    groupProfit: '1-8 月集团合并利润比预算少 6106.3769 万元，实际 21086.0000 万元，预算 27192.3769 万元',
    eastRevenue: '1-8 月华东区域收入比预算少 8072.5449 万元，实际 109742.0280 万元，预算 117814.5729 万元；华东区域预算为估算',
    eastProfit: '1-8 月华东区域利润比预算少 1484.9515 万元，实际 12451.5443 万元，预算 13936.4958 万元；华东区域预算为估算',
    august: '2026 年 8 月集团合并收入比预算少 2694.0276 万元，实际 41469.6250 万元，预算 44163.6526 万元',
  };
  // A member is an estimate as the backend declares it: by its own label (估算), with or without a sentence.
  const estimatedMeasures = (members: Record<string, number>) =>
    Object.entries(members).filter(([, index]) => String(huachen.result!.rows[index].metric_label).includes('估算')).map(([measure]) => measure);
  const pair = (metric: string, organization: string, period: string, members: Record<string, number>, text: string | null) => ({
    metric, organization, period, period_key: `${period}|${period === ytd ? '1_8' : '2026_08'}`, span: null, unit: '万元', members, declared: true,
    estimate: { estimated: estimatedMeasures(members).length > 0, measures: estimatedMeasures(members) },
    conclusion: text ? { text, basis: '脚本结果', verified: false, values: {}, variance_from: 'row' } : null,
  });
  const pairs = (concluded: boolean) => [
    pair('revenue', '集团合并', ytd, { actual: 0, budget: 1, variance: 2, rate: 3 }, concluded ? sentences.groupRevenue : null),
    pair('profit', '集团合并', ytd, { actual: 4, budget: 5 }, concluded ? sentences.groupProfit : null),
    pair('revenue', '华东区域', ytd, { actual: 6, budget: 7, variance: 8 }, concluded ? sentences.eastRevenue : null),
    pair('profit', '华东区域', ytd, { actual: 9, budget: 10 }, concluded ? sentences.eastProfit : null),
    pair('revenue', '集团合并', '2026-08', { actual: 11, budget: 12 }, concluded ? sentences.august : null),
  ];
  const roles = { actual: 'actual', budget: 'budget', estimated_budget: 'budget', variance: 'variance', rate: 'ratio', rate_pct: 'ratio' } as const;
  // Each member row as the backend declares it: its own value and label, 估算 where the pair says so.
  const declaredRows = (list: ReturnType<typeof pairs>) => list.flatMap((item) => Object.entries(item.members).map(([measure, index]) => {
    const source = huachen.result!.rows[index];
    return { row: index, fields: {}, role: roles[measure as keyof typeof roles], metric: item.metric, organization: item.organization, period: item.period,
      period_key: item.period_key, span: null, unit: source.unit, unit_kind: source.unit === '比率' ? 'decimal' : 'amount', value: source.value,
      scope_label: source.metric_label, estimate: item.estimate.measures.includes(measure), estimate_sources: [] };
  }));
  const declared = (concluded: boolean): AnalysisRun => ({
    ...huachen,
    row_declarations: {
      rules_version: '3.1.1', requirements_id: null, requirements_fingerprint: null, complete: concluded, incomplete_reason: concluded ? null : 'result_file_unavailable',
      row_count: 13, rows: declaredRows(pairs(concluded)), warnings: [], pairs: pairs(concluded),
    } as unknown as NonNullable<AnalysisRun['row_declarations']>,
  });

  it('shows the backend sentences above the KPI cards with their 脚本结果 basis, three first and the rest folded', () => {
    render(<BusinessResultView run={declared(true)} />);

    const conclusions = screen.getByRole('region', { name: '脚本结论' });
    const cards = screen.getByLabelText('关键指标');
    expect(conclusions.compareDocumentPosition(cards) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // Each sentence is the backend's text, character for character.
    for (const text of [sentences.groupRevenue, sentences.groupProfit, sentences.eastRevenue]) {
      expect(within(conclusions).getByText(text).closest('details')).toBeNull();
    }
    const rest = within(conclusions).getByText('其余 1 句结论').closest('details')!;
    expect(within(rest).getByText(sentences.eastProfit)).toBeTruthy();
    expect(within(conclusions).getAllByText('依据：脚本结果')).toHaveLength(4);
    expect(conclusions.textContent).not.toMatch(/已核验|核验通过/);
    // The regional budget's estimate is said in the sentence itself.
    expect(within(conclusions).getByText(sentences.eastRevenue).textContent).toContain('华东区域预算为估算');
    // A sentence belongs to its period tab, as the cards do.
    expect(within(conclusions).queryByText(sentences.august)).toBeNull();
    fireEvent.click(screen.getByRole('tab', { name: '2026 年 8 月' }));
    const august = screen.getByRole('region', { name: '脚本结论' });
    expect(within(august).getByText(sentences.august)).toBeTruthy();
    expect(within(august).queryByText(sentences.groupRevenue)).toBeNull();
    expect(within(august).queryByText(/其余/)).toBeNull();
  });

  it('adds only the sentences to a declared run, and says 推断 only where no declaration paired the rows', () => {
    const inferred = render(<BusinessResultView run={huachen} />).container.innerHTML;
    expect(screen.queryByRole('region', { name: '脚本结论' })).toBeNull();
    expect(screen.queryByText(/脚本结果/)).toBeNull();
    expect(screen.getAllByText('推断')).toHaveLength(4);
    cleanup();

    // An incomplete declaration pairs its rows but concludes nothing: the same cards, without 推断.
    const before = render(<BusinessResultView run={declared(false)} />).container.innerHTML;
    expect(before).toBe(inferred.replaceAll(' · <span class="analysis-kpi-note">推断</span>', ''));
    cleanup();

    // With conclusions, the sentences are the only addition.
    const { container } = render(<BusinessResultView run={declared(true)} />);
    container.querySelector('[aria-label="脚本结论"]')!.remove();
    expect(container.innerHTML).toBe(before);
  });
});

describe('result page reading order', () => {
  it('names the period tabs in words, as chips, and still filters by the stored value', () => {
    render(<BusinessResultView run={run([
      { period: '2026-01:2026-08', metric_key: 'revenue', actual: '800', budget: '900' },
      { period: '2026-08', metric_key: 'revenue', actual: '100', budget: '110' },
    ])} />);
    const tabs = within(screen.getByRole('tablist', { name: '结果期间' })).getAllByRole('tab');
    expect(tabs.map((tab) => tab.textContent)).toEqual(['2026 年 1–8 月', '2026 年 8 月']);
    expect(tabs.every((tab) => tab.getAttribute('data-variant') === 'outline' && tab.getAttribute('data-size') === 'chip')).toBe(true);
    fireEvent.click(screen.getByRole('tab', { name: '2026 年 8 月' }));
    expect(screen.getByRole('tab', { name: '2026 年 8 月' }).getAttribute('aria-selected')).toBe('true');
    const card = screen.getByRole('article');
    expect(within(card).getByLabelText('收入实际').textContent).toBe('100.00');
    expect(card.querySelector('.analysis-kpi-meta')?.textContent).toMatch(/^2026 年 8 月 · /);
    const table = screen.getByRole('table', { name: '业务结果' });
    expect(within(table).getAllByRole('row')).toHaveLength(2);
    expect(within(table).getByRole('cell', { name: '2026 年 8 月' })).toBeTruthy();
    // The raw table under 技术信息 keeps the stored values.
    const raw = screen.getByRole('table', { name: '原始计算结果' });
    expect(within(raw).getByRole('cell', { name: '2026-01:2026-08' })).toBeTruthy();
    expect(within(raw).getByRole('cell', { name: '2026-08' })).toBeTruthy();
  });

  it('keeps the stored values on two tabs that would read alike', () => {
    render(<BusinessResultView run={run([
      { period: '2026-08', metric_key: 'revenue', actual: '100', budget: '110' },
      { period: '2026-08:2026-08', metric_key: 'revenue', actual: '101', budget: '110' },
      { period: '2026', metric_key: 'revenue', actual: '900', budget: '1000' },
    ])} />);
    expect(screen.getAllByRole('tab').map((tab) => tab.textContent)).toEqual(['2026-08', '2026-08:2026-08', '2026 年']);
  });

  it('labels the rate line by the field that filled it: 达成率 when absent, 差异率 for ratio', () => {
    render(<BusinessResultView run={run([{ period: '2026-08', metric_key: 'revenue', actual: '90', budget: '100' }])} />);
    let last = screen.getByRole('article').querySelector('.analysis-kpi-list')!.lastElementChild!;
    expect([last.querySelector('dt')?.textContent, last.querySelector('dd')?.textContent]).toEqual(['达成率', '—']);
    cleanup();
    render(<BusinessResultView run={run([{ period: '2026-08', metric_key: 'revenue', actual: '90', budget: '100', ratio: '-0.1' }])} />);
    last = screen.getByRole('article').querySelector('.analysis-kpi-list')!.lastElementChild!;
    expect(last.querySelector('dt')?.textContent).toBe('差异率');
  });

  it('places the next steps right after the cards, or after the tables when there are none', () => {
    const actions = <div data-testid="next">整理成文稿</div>;
    const withCards = { ...run([{ period: '2026-08', metric_key: 'revenue', actual: '90', budget: '100' }]), assumptions: ['预算按 8 月口径。', '汇率取月末。'] };
    render(<BusinessResultView run={withCards} actions={actions} />);
    const next = screen.getByTestId('next');
    const follows = (a: Element, b: Element) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
    expect(follows(screen.getByLabelText('关键指标'), next)).toBe(true);
    const assumptions = screen.getByLabelText('本次计算的假设');
    expect(follows(next, assumptions)).toBe(true);
    // The run's two sentences joined without 。；.
    expect(assumptions.textContent).toBe('本次计算的假设：预算按 8 月口径；汇率取月末。');
    cleanup();
    render(<BusinessResultView run={run([{ period: '2026-08', metric_key: 'revenue', budget: '100' }])} actions={actions} />);
    expect(screen.queryByLabelText('关键指标')).toBeNull();
    const tables = screen.getAllByRole('table');
    const later = screen.getByTestId('next');
    expect(follows(screen.getByRole('table', { name: '业务结果' }), later)).toBe(true);
    expect(follows(later, screen.getByRole('table', { name: '原始计算结果' }))).toBe(true);
    expect(tables.length).toBeGreaterThan(1);
  });
});
