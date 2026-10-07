import { describe, expect, it } from 'vitest';
import type { AnalysisDraft, AnalysisRevision, AnalysisRun } from '../../bridge.js';
import sharedCollisions from '../../../tests/fixtures/label-collisions.json';
import { businessColumnLabel, businessRows, columnSemantics, compareBusinessRuns, displayColumns, displayRows, formatBusinessCell, formatBusinessValue, formatDisplayRows, isBudgetAlias, labelCollisions, longRowColumns, otherLongRows, rowBasisLabel, runPresentationRole, selectBusinessResult, type DisplayColumn } from './businessResults.js';

const analysis: AnalysisRevision = {
  id: 'analysis-1',
  task_id: 'task-1',
  schema_version: 1,
  created_at: '2026-09-23T00:00:00Z',
  question: '利润差异',
  sql: null,
  engine: 'python',
  bindings: {},
  parameters: {},
  assumptions: [],
  grain: [],
  relationships: [],
  metrics: [],
};

function run(patch: Partial<AnalysisRun>): AnalysisRun {
  return {
    id: patch.id ?? 'run-1',
    task_id: 'task-1',
    analysis_id: 'analysis-1',
    schema_version: 1,
    created_at: patch.created_at ?? '2026-09-23T00:00:00Z',
    execution_status: patch.execution_status ?? 'succeeded',
    reproducibility_status: 'unverified',
    review_status: 'unreviewed',
    publication_status: 'draft',
    input_hashes: {},
    engine: patch.engine ?? 'python',
    result: patch.result,
    error: patch.error,
  };
}

function draft(runIds: string[]): AnalysisDraft {
  return {
    id: 'draft-1',
    task_id: 'task-1',
    schema_version: 1,
    created_at: '2026-09-23T00:04:00Z',
    title: '经营分析',
    body: '',
    run_ids: runIds,
    claims: [],
    publication_status: 'draft',
    review_status: 'unreviewed',
    limitations: [],
  };
}

describe('business result presentation', () => {
  it('names the budget side by the same words the backend gives the budget role, approved or estimated', () => {
    for (const word of ['budget', 'Budget_YTD', 'same_period_budget', 'baseline', 'estimated_budget_month']) expect(isBudgetAlias(word)).toBe(true);
    for (const word of ['actual', 'budget_variance', 'forecast', 'invoices']) expect(isBudgetAlias(word)).toBe(false);
  });

  it.each(['preanalysis', 'draft_support', 'audit_check'])('keeps explicit %s activity out of business results even with numeric rows', (role) => {
    const activity = { ...run({ result: { columns: [{ name: 'actual', type: 'DECIMAL' }], rows: [{ actual: '100' }], row_count: 1, truncated: false } }), result_role: role };
    expect(runPresentationRole(activity)).toBe('activity');
  });
  it('keeps the latest failed retry from replacing the successful business result', () => {
    const business = run({
      id: 'business',
      created_at: '2026-09-23T00:01:00Z',
      result: { columns: [{ name: 'metric_key', type: 'VARCHAR' }, { name: 'actual', type: 'DECIMAL' }], rows: [{ metric_key: 'revenue', actual: '325644' }], row_count: 1, truncated: false },
    });
    const failed = run({ id: 'failed', created_at: '2026-09-23T00:02:00Z', execution_status: 'failed', error: 'boom' });
    const selected = selectBusinessResult(analysis, [business, failed], []);
    expect(selected.primary?.id).toBe('business');
    expect(selected.businessRuns.map((item) => item.id)).toEqual(['business']);
    expect(selected.failedRuns.map((item) => item.id)).toEqual(['failed']);
  });

  it('prefers the business run referenced by the latest draft over a later probe', () => {
    const business = run({
      id: 'business',
      created_at: '2026-09-23T00:01:00Z',
      result: { columns: [{ name: 'metric_key', type: 'VARCHAR' }, { name: 'variance', type: 'DECIMAL' }], rows: [{ metric_key: 'operating_profit', variance: '-6106.3769' }], row_count: 1, truncated: false },
    });
    const probe = run({
      id: 'probe',
      created_at: '2026-09-23T00:03:00Z',
      result: { columns: [{ name: 'label', type: 'VARCHAR' }, { name: 'value', type: 'VARCHAR' }], rows: [{ label: '读取工作表', value: '30' }], row_count: 1, truncated: false },
    });
    const selected = selectBusinessResult(analysis, [business, probe], [draft(['business'])]);
    expect(runPresentationRole(probe)).toBe('activity');
    expect(selected.reason).toBe('draft_reference');
    expect(selected.primary?.id).toBe('business');
  });

  it('formats amounts, ratios and percentage-point deltas without losing decimal text', () => {
    expect(formatBusinessValue('-18843.0552', 'amount')).toBe('-18,843.06');
    expect(formatBusinessValue('0.945301', 'ratio')).toBe('94.53%');
    expect(formatBusinessValue('-0.006532', 'ratio_delta')).toBe('-0.65 个百分点');
  });

  it('labels a wide P&L result by its metrics in Chinese', () => {
    const labels = displayColumns(run({
      result: {
        columns: ['organization', 'scenario', 'currency', 'unit', 'revenue', 'cost', 'expense', 'profit'].map((name) => ({ name, type: ['revenue', 'cost', 'expense', 'profit'].includes(name) ? 'DECIMAL' : 'VARCHAR' })),
        rows: [{ organization: '华东', scenario: 'actual', currency: 'CNY', unit: '元', revenue: '120', cost: '70', expense: '20', profit: '30' }],
        row_count: 1,
        truncated: false,
      },
    })).map((column) => column.label);
    expect(labels).toEqual(expect.arrayContaining(['组织', '情景', '币种', '单位', '收入', '成本', '费用', '利润']));
    expect(labels).not.toEqual(expect.arrayContaining(['revenue']));
  });

  it('maps declared business fields to Chinese labels and preserves unknown columns', () => {
    const rows = displayRows(run({
      result: {
        columns: [
          { name: 'metric_key', type: 'VARCHAR' },
          { name: 'actual', type: 'DECIMAL' },
          { name: 'attainment_rate', type: 'DOUBLE' },
          { name: 'custom_probe_code', type: 'VARCHAR' },
        ],
        rows: [{ metric_key: 'revenue', actual: '325644', attainment_rate: '0.945301', custom_probe_code: 'x7' }],
        row_count: 1,
        truncated: false,
      },
    }));
    expect(rows[0]).toMatchObject({ 指标: '收入', 实际: '325,644.00', 达成率: '94.53%', custom_probe_code: 'x7' });
  });



  it('keeps unique display labels when backend fields share Chinese names', () => {
    const current = run({
      result: {
        columns: [
          { name: 'metric', type: 'VARCHAR' },
          { name: 'metric_key', type: 'VARCHAR' },
          { name: 'budget', type: 'DECIMAL' },
          { name: 'baseline', type: 'DECIMAL' },
          { name: 'actual', type: 'DECIMAL' },
        ],
        rows: [{ metric: '收入展示名', metric_key: 'revenue', budget: '120', baseline: '100', actual: '90' }],
        row_count: 1,
        truncated: false,
      },
    });

    expect(displayColumns(current).map((column) => column.label)).toEqual(['指标', '指标（metric_key）', '预算', '基准', '实际', '依据']);
    expect(displayRows(current)[0]).toMatchObject({
      指标: '收入展示名',
      '指标（metric_key）': '收入',
      预算: '120.00',
      基准: '100.00',
      实际: '90.00',
      依据: '未知',
    });
  });

  it('recognizes known attainment fields as ratios without treating arbitrary percent columns as ratios', () => {
    expect(columnSemantics('attainment')).toBe('ratio');
    expect(columnSemantics('budget_attainment')).toBe('ratio');
    expect(columnSemantics('completion_rate')).toBe('ratio');
    expect(columnSemantics('营业利润_差异率_同口径', 'DECIMAL(18,6)')).toBe('ratio');
    expect(columnSemantics('营业利润_差异_同口径_万元', 'DECIMAL(38,4)')).toBe('amount');
    expect(columnSemantics('generic_variance_percent', 'DOUBLE')).toBe('amount');
    const rows = displayRows(run({
      result: {
        columns: [{ name: 'metric_key', type: 'VARCHAR' }, { name: 'attainment', type: 'DOUBLE' }],
        rows: [{ metric_key: 'revenue', attainment: '0.938999' }],
        row_count: 1,
        truncated: false,
      },
    }));
    expect(rows[0]).toMatchObject({ 指标: '收入', 达成率: '93.90%' });
  });

  it('lets a money unit or amount word beat a 率 driver or day window in the name', () => {
    for (const name of ['毛利率_影响_万元', '汇率_影响_万元', '利率_影响_万元', 'revenue_last_30_days', 'ar_amount_over_90_days', '应收_逾期_90_天_万元']) {
      expect(columnSemantics(name, 'DECIMAL(38,4)'), name).toBe('amount');
      expect(columnSemantics(name), name).toBe('amount');
    }
    expect(columnSemantics('营业利润_差异率_同口径', 'DECIMAL(18,6)')).toBe('ratio');
    expect(columnSemantics('收缴率_实际', 'DECIMAL(18,6)')).toBe('ratio');
    expect(columnSemantics('毛利率_实际', 'DECIMAL(18,6)')).toBe('ratio');
    const rows = displayRows(run({
      result: {
        columns: [
          { name: '区域', type: 'VARCHAR' },
          { name: '汇率_影响_万元', type: 'DECIMAL(38,4)' },
          { name: '营业利润_差异率_同口径', type: 'DECIMAL(18,6)' },
        ],
        rows: [{ 区域: '华东区域', 汇率_影响_万元: '35.2', 营业利润_差异率_同口径: '-0.106551' }],
        row_count: 1,
        truncated: false,
      },
    }));
    expect(rows[0]).toMatchObject({ 汇率_影响_万元: '35.20', 营业利润_差异率_同口径: '-10.66%' });
  });

  it('keeps explicit pct fields as already-percent values', () => {
    expect(formatBusinessValue('94.53', 'ratio_pct')).toBe('94.53%');
    const rows = displayRows(run({
      result: {
        columns: [{ name: 'metric_key', type: 'VARCHAR' }, { name: 'attainment_pct', type: 'DOUBLE' }],
        rows: [{ metric_key: 'revenue', attainment_pct: '94.53' }],
        row_count: 1,
        truncated: false,
      },
    }));
    expect(rows[0]).toMatchObject({ 指标: '收入', 达成率: '94.53%' });
  });

  it('labels row basis only from explicit known basis values', () => {
    expect(rowBasisLabel({ basis: 'source_fact' })).toBe('来源');
    expect(rowBasisLabel({ row_basis: 'direct_source' })).toBe('直接取数');
    expect(rowBasisLabel({ validation_basis: 'calculation' })).toBe('计算');
    expect(rowBasisLabel({ basis: 'user_assumption' })).toBe('估算');
    expect(rowBasisLabel({ basis: 'professional_judgment' })).toBe('专业判断');
    expect(rowBasisLabel({ basis: 'unmapped_vendor_flag' })).toBe('未知');
  });

  it('normalizes Huachen region Chinese wide rows into metric-period business rows', () => {
    const rows = displayRows(run({
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
        rows: [{
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
        }],
        row_count: 1,
        truncated: false,
      },
    }));
    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatchObject({
      指标: '收入',
      区域: '华东区域',
      期间: '1_8月',
      实际: '109,742.03',
      同期预算: '117,814.57',
      差异: '-8,072.54',
      达成率: '93.15%',
      单位: '万元',
      依据: '估算',
      来源: '实际：mth/10；年度预算：bud/05',
    });
    expect(rows[1]).toMatchObject({ 指标: '经营利润', 实际: '12,451.54', 达成率: '89.34%' });
  });

  it('does not overwrite official budget when estimated budget has the same metric and period', () => {
    const rows = displayRows(run({
      result: {
        columns: [
          { name: '区域', type: 'VARCHAR' },
          { name: '收入_实际_1_8月', type: 'DECIMAL' },
          { name: '收入_同期预算_1_8月', type: 'DECIMAL' },
          { name: '收入_同期预算_估算_1_8月', type: 'DECIMAL' },
          { name: '收入_达成率_1_8月', type: 'DOUBLE' },
          { name: '单位', type: 'VARCHAR' },
        ],
        rows: [{ 区域: '集团', 收入_实际_1_8月: '90', 收入_同期预算_1_8月: '100', 收入_同期预算_估算_1_8月: '110', 收入_达成率_1_8月: '0.9', 单位: '万元' }],
        row_count: 1,
        truncated: false,
      },
    }));
    expect(rows[0]).toMatchObject({ 指标: '收入', 实际: '90.00', 同期预算: '100.00', '同期预算（估算）': '110.00' });
  });

  it('normalizes Huachen group metric rows with wide Chinese period columns', () => {
    const current = run({
      result: {
        columns: [
          { name: '指标', type: 'VARCHAR' },
          { name: '实际_1_8月', type: 'DECIMAL' },
          { name: '同期预算_1_8月', type: 'DECIMAL' },
          { name: '差异_1_8月', type: 'DECIMAL' },
          { name: '达成率_1_8月', type: 'DOUBLE' },
          { name: '实际_8月', type: 'DECIMAL' },
          { name: '同期预算_8月', type: 'DECIMAL' },
          { name: '差异_8月', type: 'DECIMAL' },
          { name: '达成率_8月', type: 'DOUBLE' },
          { name: '单位', type: 'VARCHAR' },
          { name: '口径与来源', type: 'VARCHAR' },
        ],
        rows: [{
          指标: '营业收入',
          实际_1_8月: '325644.0000',
          同期预算_1_8月: '344487.0552',
          差异_1_8月: '-18843.0552',
          达成率_1_8月: '0.945301',
          实际_8月: '41469.6250',
          同期预算_8月: '44163.6526',
          差异_8月: '-2694.0276',
          达成率_8月: '0.938999',
          单位: '万元',
          口径与来源: 'mth/04·合并利润表 B5/C5',
        }],
        row_count: 1,
        truncated: false,
      },
    });
    expect(displayColumns(current).map((column) => column.label)).toEqual(['指标', '期间', '实际', '同期预算', '差异', '达成率', '单位', '依据', '来源']);
    expect(displayRows(current)).toEqual([
      expect.objectContaining({ 指标: '营业收入', 期间: '1_8月', 实际: '325,644.00', 同期预算: '344,487.06', 差异: '-18,843.06', 达成率: '94.53%' }),
      expect.objectContaining({ 指标: '营业收入', 期间: '8月', 实际: '41,469.63', 同期预算: '44,163.65', 差异: '-2,694.03', 达成率: '93.90%' }),
    ]);
  });

  it('pivots real Huachen metric_key scenario rows into business result rows', () => {
    const current = run({
      id: '49bb555c1cca40a8a144b4e51e2413a5',
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
          { metric_key: 'gross_profit', period: '2026-01:2026-08', organization: '集团合并', scenario: 'actual_ytd', unit: '万元', value: '58789.5000', source: 'mth/04·合并利润表 C24（元 ÷ 10000）', note: '毛利实际' },
          { metric_key: 'gross_profit', period: '2026-01:2026-08', organization: '集团合并', scenario: 'budget_ytd', unit: '万元', value: '64441.3769', source: 'bud/01·年度预算总表 B24:I24 合计', note: '毛利同期预算' },
          { metric_key: 'gross_profit', period: '2026-01:2026-08', organization: '集团合并', scenario: 'variance', unit: '万元', value: '-5651.8769', source: '本表计算', note: '毛利缺口（不利）' },
          { metric_key: 'period_expense', period: '2026-01:2026-08', organization: '集团合并', scenario: 'actual_ytd', unit: '万元', value: '29946.0000', source: 'mth/04 C18:C22 合计（元 ÷ 10000）', note: '期间费用实际' },
          { metric_key: 'period_expense', period: '2026-01:2026-08', organization: '集团合并', scenario: 'budget_ytd', unit: '万元', value: '31642.0000', source: 'bud/01 B32:I32 合计', note: '期间费用同期预算' },
          { metric_key: 'period_expense', period: '2026-01:2026-08', organization: '集团合并', scenario: 'variance_favorable', unit: '万元', value: '1696.0000', source: '本表计算', note: '费用低于预算 = 对利润正向贡献' },
          { metric_key: 'operating_profit', period: '2026-01:2026-08', organization: '集团合并', scenario: 'achievement_ratio', unit: '比率', value: '0.775437913263110148', source: '实际 ÷ 同期预算（完整 Decimal，未截断）', note: '达成率' },
        ],
        row_count: 7,
        truncated: false,
      },
    });

    expect(businessRows(current).slice(0, 2)).toEqual([
      expect.objectContaining({ metric: '毛利', region: '集团合并', period: '2026-01:2026-08', actual: '58789.5000', same_period_budget: '64441.3769', variance: '-5651.8769', unit: '万元', basis: '计算' }),
      // variance_favorable is budget minus actual (1696 under budget); as 差异 beside actual-minus-budget rows it
      // would read as an overspend, so it stays unpaired and the card shows no 差异 for this row.
      expect.objectContaining({ metric: '期间费用', region: '集团合并', period: '2026-01:2026-08', actual: '29946.0000', same_period_budget: '31642.0000', variance: undefined, unit: '万元', basis: '计算' }),
    ]);
    expect(otherLongRows(current).map((row) => row.scenario)).toContain('variance_favorable');
    expect(displayRows(current).slice(0, 2).map((row) => row['指标'])).toEqual(['毛利', '期间费用']);
    expect(displayColumns(current).map((column) => column.label)).toEqual(['指标', '区域', '期间', '实际', '同期预算', '差异', '达成率', '单位', '依据', '来源']);
    expect(displayRows(current)).toEqual([
      expect.objectContaining({ 指标: '毛利', 区域: '集团合并', 实际: '58,789.50', 同期预算: '64,441.38', 差异: '-5,651.88', 单位: '万元', 依据: '计算' }),
      expect.objectContaining({ 指标: '期间费用', 区域: '集团合并', 实际: '29,946.00', 同期预算: '31,642.00', 差异: '—', 单位: '万元', 依据: '计算' }),
    ]);
  });


  it('keeps long scenario rows raw when amount units conflict or a measure is duplicated', () => {
    const mixedUnit = run({
      result: {
        columns: [
          { name: 'metric_key', type: 'VARCHAR' }, { name: 'period', type: 'VARCHAR' }, { name: 'organization', type: 'VARCHAR' },
          { name: 'scenario', type: 'VARCHAR' }, { name: 'unit', type: 'VARCHAR' }, { name: 'value', type: 'DECIMAL' },
        ],
        rows: [
          { metric_key: 'revenue', period: '2026-08', organization: '集团合并', scenario: 'actual_month', unit: '万元', value: '41469.6250' },
          { metric_key: 'revenue', period: '2026-08', organization: '集团合并', scenario: 'budget_month', unit: '元', value: '441636526' },
        ],
        row_count: 2,
        truncated: false,
      },
    });
    expect(businessRows(mixedUnit)).toBe(mixedUnit.result?.rows);

    const duplicateMeasure = run({
      result: {
        columns: mixedUnit.result!.columns,
        rows: [
          { metric_key: 'revenue', period: '2026-08', organization: '集团合并', scenario: 'actual_month', unit: '万元', value: '41469.6250' },
          { metric_key: 'revenue', period: '2026-08', organization: '集团合并', scenario: 'actual_month', unit: '万元', value: '41470.0000' },
          { metric_key: 'revenue', period: '2026-08', organization: '集团合并', scenario: 'budget_month', unit: '万元', value: '44163.6526' },
        ],
        row_count: 3,
        truncated: false,
      },
    });
    expect(businessRows(duplicateMeasure)).toBe(duplicateMeasure.result?.rows);
  });

  it('recognizes estimated-only budgets and pct rates in long scenario rows conservatively', () => {
    const estimated = run({
      result: {
        columns: [
          { name: 'metric_key', type: 'VARCHAR' }, { name: 'period', type: 'VARCHAR' }, { name: 'organization', type: 'VARCHAR' },
          { name: 'scenario', type: 'VARCHAR' }, { name: 'unit', type: 'VARCHAR' }, { name: 'value', type: 'DECIMAL' },
        ],
        rows: [
          { metric_key: 'revenue', period: '2026-01:2026-08', organization: '西部区域', scenario: 'actual_ytd', unit: '万元', value: '33541.3320' },
          { metric_key: 'revenue', period: '2026-01:2026-08', organization: '西部区域', scenario: 'estimated_budget_ytd', unit: '万元', value: '33415.2443' },
          // The unit, not the scenario word, says 100.3773 is already a percentage (KTD9).
          { metric_key: 'revenue', period: '2026-01:2026-08', organization: '西部区域', scenario: 'attainment_pct', unit: '%', value: '100.3773' },
        ],
        row_count: 3,
        truncated: false,
      },
    });
    expect(displayColumns(estimated).map((column) => column.label)).toEqual(['指标', '区域', '期间', '实际', '同期预算', '差异', '达成率', '达成率（pct）', '单位', '依据', '来源']);
    expect(displayRows(estimated)[0]).toMatchObject({ 指标: '收入', 区域: '西部区域', 实际: '33,541.33', 同期预算: '33,415.24', '达成率（pct）': '100.38%', 单位: '万元', 依据: '估算' });
  });

  it('separates real Huachen long scenario periods for revenue and operating profit', () => {
    const current = run({
      result: {
        columns: [
          { name: 'metric_key', type: 'VARCHAR' }, { name: 'period', type: 'VARCHAR' }, { name: 'organization', type: 'VARCHAR' },
          { name: 'scenario', type: 'VARCHAR' }, { name: 'unit', type: 'VARCHAR' }, { name: 'value', type: 'DECIMAL' },
        ],
        rows: [
          { metric_key: 'revenue', period: '2026-01:2026-08', organization: '集团合并', scenario: 'actual_ytd', unit: '万元', value: '325644.0000' },
          { metric_key: 'revenue', period: '2026-01:2026-08', organization: '集团合并', scenario: 'budget_ytd', unit: '万元', value: '344487.0552' },
          { metric_key: 'revenue', period: '2026-01:2026-08', organization: '集团合并', scenario: 'variance', unit: '万元', value: '-18843.0552' },
          { metric_key: 'revenue', period: '2026-01:2026-08', organization: '集团合并', scenario: 'achievement_ratio', unit: '比率', value: '0.945301122594983360' },
          { metric_key: 'operating_profit', period: '2026-01:2026-08', organization: '集团合并', scenario: 'actual_ytd', unit: '万元', value: '21086.0000' },
          { metric_key: 'operating_profit', period: '2026-01:2026-08', organization: '集团合并', scenario: 'budget_ytd', unit: '万元', value: '27192.3769' },
          { metric_key: 'operating_profit', period: '2026-01:2026-08', organization: '集团合并', scenario: 'variance', unit: '万元', value: '-6106.3769' },
          { metric_key: 'operating_profit', period: '2026-01:2026-08', organization: '集团合并', scenario: 'achievement_ratio', unit: '比率', value: '0.775437913263110148' },
          { metric_key: 'revenue', period: '2026-08', organization: '集团合并', scenario: 'actual_month', unit: '万元', value: '41469.6250' },
          { metric_key: 'revenue', period: '2026-08', organization: '集团合并', scenario: 'budget_month', unit: '万元', value: '44163.6526' },
          { metric_key: 'revenue', period: '2026-08', organization: '集团合并', scenario: 'achievement_ratio', unit: '比率', value: '0.938998985785881306' },
          { metric_key: 'operating_profit', period: '2026-08', organization: '集团合并', scenario: 'actual_month', unit: '万元', value: '2155.6250' },
          { metric_key: 'operating_profit', period: '2026-08', organization: '集团合并', scenario: 'budget_month', unit: '万元', value: '3318.6566' },
          { metric_key: 'operating_profit', period: '2026-08', organization: '集团合并', scenario: 'achievement_ratio', unit: '比率', value: '0.649547470503576658' },
        ],
        row_count: 14,
        truncated: false,
      },
    });
    expect(displayRows(current)).toEqual([
      expect.objectContaining({ 指标: '收入', 期间: '2026 年 1–8 月', 实际: '325,644.00', 同期预算: '344,487.06', 差异: '-18,843.06', 达成率: '94.53%' }),
      expect.objectContaining({ 指标: '营业利润', 期间: '2026 年 1–8 月', 实际: '21,086.00', 同期预算: '27,192.38', 差异: '-6,106.38', 达成率: '77.54%' }),
      expect.objectContaining({ 指标: '收入', 期间: '2026 年 8 月', 实际: '41,469.63', 同期预算: '44,163.65', 达成率: '93.90%' }),
      expect.objectContaining({ 指标: '营业利润', 期间: '2026 年 8 月', 实际: '2,155.63', 同期预算: '3,318.66', 达成率: '64.95%' }),
    ]);
  });


  it('does not infer percentage semantics from row unit alone', () => {
    const rows = displayRows(run({
      result: {
        columns: [
          { name: 'metric', type: 'VARCHAR' },
          { name: 'period', type: 'VARCHAR' },
          { name: 'actual', type: 'DOUBLE' },
          { name: 'variance', type: 'DOUBLE' },
          { name: 'unit', type: 'VARCHAR' },
        ],
        rows: [
          { metric: '收入', period: '1_8月', actual: '109742.0280', variance: '-8072.5449', unit: '万元' },
          { metric: '毛利率', period: '1_8月', actual: '0.212', variance: '-0.015', unit: '%' },
        ],
        row_count: 2,
        truncated: false,
      },
    }));
    expect(rows[0]).toMatchObject({ 实际: '109,742.03', 差异: '-8,072.54' });
    expect(rows[1]).toMatchObject({ 实际: '0.21', 差异: '-0.02' });
  });

  it('formats a long-form value by its declared unit alone: 比率 as a fraction, % as a percent, - as written', () => {
    const rows = displayRows(run({
      result: {
        columns: ['metric_key', 'organization', 'period', 'scenario', 'value', 'unit'].map((name) => ({ name, type: name === 'value' ? 'DECIMAL' : 'VARCHAR' })),
        rows: [
          { metric_key: 'revenue_achievement_pct', organization: '华东区域', period: '2026-01:2026-08', scenario: 'achievement_pct', value: '0.945', unit: '比率' },
          { metric_key: 'profit_achievement_pct', organization: '华东区域', period: '2026-01:2026-08', scenario: 'achievement_pct', value: '94.5', unit: '%' },
          { metric_key: 'collection_rate', organization: '华东区域', period: '2026-01:2026-08', scenario: 'achievement_ratio', value: '0.945', unit: '-' },
          { metric_key: 'receivable_balance', organization: '华东区域', period: '2026-01:2026-08', scenario: 'actual_1_8', value: '41400', unit: '万元' },
        ],
        row_count: 4,
        truncated: false,
      },
    }));
    expect(rows.map((row) => row['数值'])).toEqual(['94.50%', '94.50%', '0.945（未标单位）', '41,400.00']);
  });

  it('shows a 百分点 row as written in 个百分点 and never pairs it', () => {
    const current = run({
      result: {
        columns: ['metric_key', 'organization', 'period', 'scenario', 'value', 'unit', 'metric_label'].map((name) => ({ name, type: name === 'value' ? 'DECIMAL' : 'VARCHAR' })),
        rows: [
          { metric_key: 'revenue', organization: '华东区域', period: '2026-01:2026-08', scenario: 'actual_1_8', value: '90', unit: '万元', metric_label: '营业收入 1-8 月实际' },
          { metric_key: 'revenue', organization: '华东区域', period: '2026-01:2026-08', scenario: 'budget_1_8', value: '100', unit: '万元', metric_label: '营业收入 1-8 月预算' },
          // A 达成率 written in 百分点 is a difference, not the comparison's 达成率.
          { metric_key: 'revenue_achievement_ratio', organization: '华东区域', period: '2026-01:2026-08', scenario: 'achievement_ratio', value: '3.3', unit: '百分点', metric_label: '营业收入达成率变动' },
          { metric_key: 'collection_rate_gap', organization: '华东区域', period: '2026-01:2026-08', scenario: 'actual_1_8', value: '3.3000', unit: '百分点', metric_label: '收缴率缺口' },
          { metric_key: 'collection_rate_gap_prior', organization: '华东区域', period: '2026-01:2026-08', scenario: 'actual_1_8', value: '', unit: '百分点', metric_label: '上年收缴率缺口' },
        ],
        row_count: 5,
        truncated: false,
      },
    });
    expect(businessRows(current)).toEqual([expect.objectContaining({ metric: '收入', actual: '90', same_period_budget: '100', attainment_rate: undefined })]);
    const others = otherLongRows(current);
    const shown = formatDisplayRows(others, longRowColumns(current, others));
    expect(shown.map((row) => [row['指标'], row['数值'], row['单位']])).toEqual([
      ['营业收入达成率变动', '3.30 个百分点', '个百分点'],
      ['收缴率缺口', '3.30 个百分点', '个百分点'],
      ['上年收缴率缺口', '—', '百分点'],
    ]);
  });

  it.each([
    ['2.345', '2.35 个百分点'],
    ['-0.001', '0.00 个百分点'],
    ['-1234567.125', '-1,234,567.13 个百分点'],
  ])('reads a 百分点 value %s as the backend displays it, %s', (value, shown) => {
    const column: DisplayColumn = { name: 'value', type: 'DECIMAL', label: '数值', semantics: 'amount' };
    expect(formatBusinessCell(value, column, { value, unit: '百分点' })).toBe(shown);
    // An empty unit gives way to 单位, as result_semantics.py and the facts read it.
    expect(formatBusinessCell(value, column, { value, unit: '', 单位: '百分点' })).toBe(shown);
  });

  it('never pairs a row whose unit is - as a budget amount', () => {
    const current = run({
      result: {
        columns: ['metric_key', 'organization', 'period', 'scenario', 'value', 'unit'].map((name) => ({ name, type: name === 'value' ? 'DECIMAL' : 'VARCHAR' })),
        rows: [
          { metric_key: 'revenue', organization: '华东区域', period: '2026-01:2026-08', scenario: 'actual_1_8', value: '90', unit: '万元' },
          { metric_key: 'revenue', organization: '华东区域', period: '2026-01:2026-08', scenario: 'budget_1_8', value: '0.945', unit: '-' },
          { metric_key: 'profit', organization: '华东区域', period: '2026-01:2026-08', scenario: 'actual_1_8', value: '9', unit: '万元' },
          { metric_key: 'profit', organization: '华东区域', period: '2026-01:2026-08', scenario: 'budget_1_8', value: '10', unit: '万元' },
        ],
        row_count: 4,
        truncated: false,
      },
    });
    expect(businessRows(current)).toEqual([expect.objectContaining({ metric: '利润', actual: '9', same_period_budget: '10' })]);
    expect(otherLongRows(current).map((row) => row.unit)).toEqual(['万元', '-']);
  });

  describe('one name for two metrics', () => {
    const ytd = '2026-01:2026-08';
    const row = (metric_key: string, metric_label: string, organization = '集团合并', period: string | null = ytd, extra: Record<string, unknown> = {}) =>
      ({ metric_key, organization, period, scenario: 'budget_bud_fy', value: '0.5', unit: '比率', metric_label, ...extra });
    const longColumns = (names: string[]) => names.map((name) => ({ name, type: name === 'value' ? 'DECIMAL' : 'VARCHAR' }));
    const columnsFor = (rows: Record<string, unknown>[], names = ['metric_key', 'organization', 'period', 'scenario', 'value', 'unit', 'metric_label']) =>
      longRowColumns(run({ result: { columns: longColumns(names), rows, row_count: rows.length, truncated: false } }), rows);

    it('collects only an organization and period whose shared name covers different keys', () => {
      const rows = [
        row('ratio', '1-8 月实际÷全年 BUD'),
        row('revenue_completion_ratio', ' 1-8 月实际÷全年 BUD '),
        // This year and last year under one key: told apart by the scenario.
        row('revenue_prior', '营业收入', '华东区域', ytd, { scenario: 'actual_py_1_8' }),
        row('revenue_prior', '营业收入', '华东区域', ytd, { scenario: 'actual_ly_1_8' }),
        // One name in two organizations, or two periods.
        row('ratio', '收缴率', '集团合并'), row('collection', '收缴率', '华东区域'),
        row('ratio', '回款率', '集团合并', '2026-08'), row('collection', '回款率', '集团合并', '2026'),
      ];
      expect(labelCollisions(rows).map(({ organization, period, label, keys, rows: members }) => ({ organization, period, label, keys, size: members.length })))
        .toEqual([{ organization: '集团合并', period: ytd, label: '1-8 月实际÷全年 BUD', keys: ['ratio', 'revenue_completion_ratio'], size: 2 }]);
    });

    it('adds the key, or its Chinese name, only where no key column is shown', () => {
      const raw = [row('ratio', '1-8 月实际÷全年 BUD'), row('revenue_completion_ratio', '1-8 月实际÷全年 BUD')];
      const shown = formatDisplayRows(raw, columnsFor(raw));
      expect(shown.map((item) => item['指标'])).toEqual(['1-8 月实际÷全年 BUD（ratio）', '1-8 月实际÷全年 BUD（revenue_completion_ratio）']);
      expect(shown.map((item) => item.__metricKey)).toEqual(['ratio', 'revenue_completion_ratio']);
      const chinese = [row('revenue', '1-8 月合计'), row('operating_profit', '1-8 月合计')];
      expect(formatDisplayRows(chinese, columnsFor(chinese)).map((item) => item['指标'])).toEqual(['1-8 月合计（收入）', '1-8 月合计（营业利润）']);
      // With the key column on screen (a row without a label keeps it), the name stays as written.
      const unlabelled = [...raw, row('receivable', '')];
      const columns = columnsFor(unlabelled);
      expect(columns.map((column) => column.label)).toContain('指标');
      expect(formatDisplayRows(unlabelled, columns).map((item) => item['指标说明'])).toEqual(['1-8 月实际÷全年 BUD', '1-8 月实际÷全年 BUD', '—']);
    });

    // The sample the backend label_ambiguous check (C') asserts too: both sides must find these groups in these rows.
    it('finds the shared Huachen sample\'s collisions, the contract with the backend check', () => {
      const sample = run({
        result: { columns: longColumns(sharedCollisions.columns), rows: sharedCollisions.rows, row_count: sharedCollisions.rows.length, truncated: false },
      });
      // The 华东区域 profit actual and budget pair into a card; only the rows left over are compared.
      const others = otherLongRows(sample);
      expect(sharedCollisions.rows.filter((item) => !others.includes(item)).map((item) => [item.metric_key, item.scenario]))
        .toEqual([['profit', 'actual_1_8'], ['profit', 'budget_1_8']]);
      expect(labelCollisions(others).map(({ organization, period, label, keys }) => ({ organization, period, label, keys })))
        .toEqual(sharedCollisions.label_collisions);
    });

    it('reads a label that only an object has by inheritance as written', () => {
      const rows = [row('ratio', 'constructor'), row('revenue_completion_ratio', 'constructor'), row('profit', 'toString'), row('ratio', '__proto__')];
      expect(labelCollisions(rows).map(({ label, keys }) => ({ label, keys }))).toEqual([{ label: 'constructor', keys: ['ratio', 'revenue_completion_ratio'] }]);
      const shown = formatDisplayRows(rows, columnsFor(rows));
      expect(shown.map((item) => item['指标'])).toEqual(['constructor（ratio）', 'constructor（revenue_completion_ratio）', 'toString', '__proto__']);
      expect(formatBusinessValue('toString', 'text')).toBe('toString');
      expect(businessColumnLabel('constructor')).toBe('constructor');
    });

    it('compares names as the table shows them, so an estimate reads alike with a label that already says 估算', () => {
      const raw = [row('profit_budget_est', '营业利润预算', '华东区域', ytd, { basis: 'estimate', unit: '万元' }), row('profit_budget_note', '营业利润预算（估算）', '华东区域', ytd, { unit: '万元' })];
      expect(labelCollisions(raw).map((item) => item.label)).toEqual(['营业利润预算（估算）']);
      expect(formatDisplayRows(raw, columnsFor(raw, ['metric_key', 'organization', 'period', 'scenario', 'value', 'unit', 'metric_label', 'basis'])).map((item) => item['指标']))
        .toEqual(['营业利润预算（估算）（profit_budget_est）', '营业利润预算（估算）（profit_budget_note）']);
    });

    it('keeps the key columns when metric and metric_key disagree, so no row loses what tells it apart', () => {
      const names = ['metric', 'metric_key', 'organization', 'period', 'scenario', 'value', 'unit', 'metric_label'];
      const disagree = [
        { ...row('revenue_ytd', '收入'), metric: 'revenue' },
        { ...row('revenue_month', '收入'), metric: 'revenue' },
      ];
      const columns = columnsFor(disagree, names);
      expect(columns.filter((column) => ['metric', 'metric_key'].includes(column.name)).map((column) => column.label)).toEqual(['指标键（metric）', '指标键（metric_key）']);
      // The key columns are on screen, so the name stays as written.
      expect(formatDisplayRows(disagree, columns).map((item) => item['指标'])).toEqual(['收入', '收入']);
      // Where they agree, they go as one.
      const agree = disagree.map((item) => ({ ...item, metric: item.metric_key }));
      expect(columnsFor(agree, names).map((column) => column.name)).not.toEqual(expect.arrayContaining(['metric']));
      expect(columnsFor(agree, names).map((column) => column.name)).not.toContain('metric_key');
    });

    it('drops a Chinese 指标 key column like metric_key and tells its rows apart the same way', () => {
      const rows = [{ 指标: 'ratio', organization: '集团合并', period: ytd, scenario: 'budget_bud_fy', value: '0.48', unit: '比率', metric_label: '完成率' },
        { 指标: 'revenue_completion_ratio', organization: '集团合并', period: ytd, scenario: 'budget_bud_fy', value: '0.62', unit: '比率', metric_label: '完成率' }];
      const columns = columnsFor(rows, ['指标', 'organization', 'period', 'scenario', 'value', 'unit', 'metric_label']);
      expect(columns.map((column) => column.name)).not.toContain('指标');
      expect(formatDisplayRows(rows, columns).map((item) => item['指标'])).toEqual(['完成率（ratio）', '完成率（revenue_completion_ratio）']);
    });

    it('adds no key where 估算 already tells two names apart, and no 估算 for a key that names one', () => {
      const rows = [row('revenue_estimated_budget', '全年预算', '集团合并', ytd, { scenario: 'estimated_budget_ytd', unit: '万元' }), row('revenue_budget', '全年预算', '集团合并', ytd, { unit: '万元' })];
      // The estimate already reads apart from the approved budget, so neither gets a key.
      expect(formatDisplayRows(rows, columnsFor(rows)).map((item) => item['指标'])).toEqual(['全年预算（估算）', '全年预算']);
      // A key alone does not make a row an estimate.
      const keyOnly = [row('revenue_estimated_budget', '全年预算', '集团合并', ytd, { unit: '万元' }), row('revenue_budget', '全年预算', '集团合并', ytd, { unit: '万元' })];
      expect(formatDisplayRows(keyOnly, columnsFor(keyOnly)).map((item) => item['指标'])).toEqual(['全年预算（revenue_estimated_budget）', '全年预算（revenue_budget）']);
    });
  });

  it.each([
    ['比率', '0.616750', '%'],
    ['pct', '3.3000', '%'],
    ['%', '94.5', '%'],
    ['天', '45', '天'],
    ['万元', '41400', '万元'],
    ['-', '0.9', '-'],
    ['比率', '', '比率'],
    ['百分点', '3.3000', '个百分点'],
    ['百分点', '', '百分点'],
  ])('writes the unit %s of a row valued %j as %s', (unit, value, shown) => {
    const column: DisplayColumn = { name: 'unit', type: 'VARCHAR', label: '单位', semantics: 'text' };
    expect(formatBusinessCell(unit, column, { unit, value })).toBe(shown);
    expect(formatBusinessCell(unit, { ...column, name: '单位' }, { 单位: unit, value })).toBe(shown);
  });

  it('compares revisions by stable business identity rather than row position', () => {
    const previous = run({
      result: {
        columns: [{ name: 'metric_key', type: 'VARCHAR' }, { name: 'same_period_budget', type: 'DECIMAL' }],
        rows: [{ metric_key: 'other_gains', same_period_budget: '3063.0494' }],
        row_count: 1,
        truncated: false,
      },
    });
    const current = run({
      result: {
        columns: [{ name: 'metric_key', type: 'VARCHAR' }, { name: 'same_period_budget', type: 'DECIMAL' }],
        rows: [{ metric_key: 'other_gains', same_period_budget: '3185' }],
        row_count: 1,
        truncated: false,
      },
    });
    expect(compareBusinessRuns(current, previous).changes).toEqual([{
      identity: 'other_gains',
      label: '其他收益',
      field: '同期预算',
      before: '3,063.05',
      after: '3,185.00',
    }]);
  });
});
