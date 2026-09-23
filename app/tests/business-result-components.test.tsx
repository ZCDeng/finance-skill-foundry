// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AnalysisScopeCard } from '../src/views/analysis/AnalysisScopeCard.js';
import { BusinessResultView } from '../src/views/analysis/BusinessResultView.js';
import { RevisionDiff } from '../src/views/analysis/RevisionDiff.js';
import type { AnalysisRun, Bridge } from '../src/bridge.js';

const taskId = 't'.repeat(32);
const dataset = { id: 'd'.repeat(32), name: '预算套表' };

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
      items: [{ id: 'req_9', metric: 'revenue', label: '收入', dimensions: { region: '集团' }, requires_drilldown: true }],
    };
    const financeCall = vi.fn(async (_task: string, command: string, spec?: Record<string, unknown>) => {
      if (command === 'analysis-requirements-list') return ok({ current });
      expect(command).toBe('analysis-requirements-save');
      expect(spec).toMatchObject({
        question: '已保存的问题',
        parent_id: current.id,
        bindings: current.bindings,
        items: current.items,
        scope: { period: '2026-08', unit: '万元', scenario: '待经理确认', organization: '集团', custom_scope: '保留' },
      });
      expect(spec).not.toHaveProperty('actual');
      expect(spec).not.toHaveProperty('budget');
      return ok({ ...current, id: 'next-scope-version', scope: spec?.scope });
    });
    const onSaved = vi.fn();
    (globalThis as { foundry?: Partial<Bridge> }).foundry = { financeCall };
    render(<AnalysisScopeCard taskId={taskId} question="新的输入框问题" datasets={[dataset]} onSaved={onSaved} />);
    expect(await screen.findByDisplayValue('2026 YTD')).toBeTruthy();
    expect(screen.getByDisplayValue('待经理确认')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('期间'), { target: { value: '2026-08' } });
    fireEvent.change(screen.getByLabelText('组织'), { target: { value: '集团' } });
    fireEvent.click(screen.getByRole('button', { name: '保存口径' }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ id: 'next-scope-version' })));
  });

  it('does not infer default period, unit, currency, scenario, bindings or profit requirements for a new task', async () => {
    const financeCall = vi.fn(async (_task: string, command: string, spec?: Record<string, unknown>) => {
      if (command === 'analysis-requirements-list') return ok({ current: null });
      expect(spec).toMatchObject({ question: '本次想问的问题', scope: {}, bindings: {}, items: [] });
      return ok({ id: 'blank-scope-version', question: '本次想问的问题', scope: {}, bindings: {}, items: [] });
    });
    (globalThis as { foundry?: Partial<Bridge> }).foundry = { financeCall };
    render(<AnalysisScopeCard taskId={taskId} question="本次想问的问题" datasets={[dataset]} />);
    await waitFor(() => expect(financeCall).toHaveBeenCalledWith(taskId, 'analysis-requirements-list', {}));
    expect((screen.getByLabelText('期间') as HTMLInputElement).value).toBe('');
    expect((screen.getByLabelText('单位') as HTMLInputElement).value).toBe('');
    expect((screen.getByLabelText('币种') as HTMLInputElement).value).toBe('');
    expect((screen.getByLabelText('情景') as HTMLInputElement).value).toBe('');
    fireEvent.click(screen.getByRole('button', { name: '保存口径' }));
    await screen.findByText('已保存口径版本 blank-scope-。');
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
    expect(within(table).getByRole('cell', { name: '-0.65个百分点' })).toBeTruthy();
    expect(within(table).getByRole('cell', { name: '04表B5/B33' })).toBeTruthy();
    fireEvent.click(screen.getByRole('tab', { name: 'YTD' }));
    const updated = screen.getAllByRole('region', { name: '业务结果' }).at(-1)!;
    expect(within(updated).getByRole('cell', { name: '325,644.00' })).toBeTruthy();
    expect(within(updated).getByRole('cell', { name: '94.53%' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '查看来源与口径' }));
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
    expect(within(table).queryByText('没有符合当前口径的行。')).toBeNull();
  });

  it('shows KPI actual, budget, difference, rate, period, unit and explicit row basis', () => {
    render(<BusinessResultView run={run([
      { period: '2026-08', unit: '万元', metric_key: 'operating_profit', actual: '90', budget: '100', variance: '-10', attainment: '0.9', basis: 'professional_judgment' },
    ])} />);
    const card = screen.getByRole('article');
    expect(within(card).getByText('营业利润')).toBeTruthy();
    expect(within(card).getByLabelText('营业利润实际').textContent).toBe('90.00');
    expect(within(card).getByText('2026-08 · 万元 · 依据：专业判断')).toBeTruthy();
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
    expect(within(cards[0]).getByText('1_8月 · 万元 · 依据：估算')).toBeTruthy();
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
          { metric_key: 'revenue', period: '2026-01:2026-08', organization: '西部区域', scenario: 'attainment_pct', unit: '比率', value: '100.3773', source: '实际 ÷ 估算预算', note: '达成率百分数' },
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
    expect(within(card).getByText('2026-01:2026-08 · 万元 · 依据：估算')).toBeTruthy();
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
    fireEvent.click(screen.getByRole('tab', { name: '2026-08' }));
    cards = screen.getAllByRole('article');
    expect(within(cards[0]).getByText('收入 · 集团合并')).toBeTruthy();
    expect(within(cards[0]).getByLabelText('收入 · 集团合并实际').textContent).toBe('41,469.63');
    expect(within(cards[0]).getByText('93.90%')).toBeTruthy();
    expect(within(cards[1]).getByText('营业利润 · 集团合并')).toBeTruthy();
    expect(within(cards[1]).getByLabelText('营业利润 · 集团合并实际').textContent).toBe('2,155.63');
    expect(within(cards[1]).getByText('64.95%')).toBeTruthy();
    expect(screen.queryByText('依据：未知')).toBeNull();
  });


  it('treats an empty backend no-comparable comparison as authoritative instead of falling back locally', () => {
    const previous = run([{ metric_key: 'revenue', actual: '325644' }]);
    const current = run([{ metric_key: 'revenue', actual: '344487.0552' }]);
    render(<RevisionDiff current={current} previous={previous} currentRevision={4} previousRevision={3}
      comparison={{ summary: { status: 'no_comparable_runs', issue_count: 0, compared_business_keys: 0 }, issues: [] }} />);
    expect(screen.getByText(/无可比运行/)).toBeTruthy();
    expect(screen.getByText('后端没有找到可比较运行；未回退到本地行序或字段猜测。')).toBeTruthy();
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
    expect(screen.getByText(/1.23个百分点 → -0.65个百分点/)).toBeTruthy();
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
