import { describe, expect, it } from 'vitest';
import type { AnalysisDraft, AnalysisRevision, AnalysisRun } from '../../bridge.js';
import { businessRows, columnSemantics, compareBusinessRuns, displayColumns, displayRows, formatBusinessValue, rowBasisLabel, runPresentationRole, selectBusinessResult } from './businessResults.js';

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
    expect(formatBusinessValue('-0.006532', 'ratio_delta')).toBe('-0.65个百分点');
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
      expect.objectContaining({ metric: '期间费用', region: '集团合并', period: '2026-01:2026-08', actual: '29946.0000', same_period_budget: '31642.0000', variance: '1696.0000', unit: '万元', basis: '计算' }),
    ]);
    expect(displayRows(current).slice(0, 2).map((row) => row['指标'])).toEqual(['毛利', '期间费用']);
    expect(displayColumns(current).map((column) => column.label)).toEqual(['指标', '区域', '期间', '实际', '同期预算', '差异', '达成率', '单位', '依据', '来源']);
    expect(displayRows(current)).toEqual([
      expect.objectContaining({ 指标: '毛利', 区域: '集团合并', 实际: '58,789.50', 同期预算: '64,441.38', 差异: '-5,651.88', 单位: '万元', 依据: '计算' }),
      expect.objectContaining({ 指标: '期间费用', 区域: '集团合并', 实际: '29,946.00', 同期预算: '31,642.00', 差异: '1,696.00', 单位: '万元', 依据: '计算' }),
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
          { metric_key: 'revenue', period: '2026-01:2026-08', organization: '西部区域', scenario: 'attainment_pct', unit: '比率', value: '100.3773' },
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
      expect.objectContaining({ 指标: '收入', 期间: '2026-01:2026-08', 实际: '325,644.00', 同期预算: '344,487.06', 差异: '-18,843.06', 达成率: '94.53%' }),
      expect.objectContaining({ 指标: '营业利润', 期间: '2026-01:2026-08', 实际: '21,086.00', 同期预算: '27,192.38', 差异: '-6,106.38', 达成率: '77.54%' }),
      expect.objectContaining({ 指标: '收入', 期间: '2026-08', 实际: '41,469.63', 同期预算: '44,163.65', 达成率: '93.90%' }),
      expect.objectContaining({ 指标: '营业利润', 期间: '2026-08', 实际: '2,155.63', 同期预算: '3,318.66', 达成率: '64.95%' }),
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
    expect(compareBusinessRuns(current, previous)).toEqual([{
      identity: 'other_gains',
      label: '其他收益',
      field: '同期预算',
      before: '3,063.05',
      after: '3,185.00',
    }]);
  });
});
