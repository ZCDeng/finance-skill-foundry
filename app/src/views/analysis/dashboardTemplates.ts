/**
 * The three ready boards (经营看板 templates). Each lays cards over results the task has already calculated; none
 * calculates anything. A template that finds no result to read says which calculation it waits on.
 */
import type { AnalysisRun } from '../../bridge.js';
import { isCollectionHealthRun, type HealthRow } from './CollectionHealthView.js';
import { isFinanceVarianceRun, profitBridges, rendersBusinessView } from './RunPanel.js';
import { headlineRows, kpiFor } from './BusinessResultView.js';
import { displayColumns, isSuccessfulRun } from './businessResults.js';
import { figureDraft, type CardDraft, type DashboardCard, type TemplateId } from './dashboard.js';
import { scenarioBase } from './dashboardScenario.js';

export type Template = {
  id: TemplateId;
  title: string;
  /** What the board shows, in a line. */
  summary: string;
  /** What to calculate first, when the task has nothing this template reads. */
  needs: string;
  cards(runs: AnalysisRun[]): CardDraft[];
};

/** Which calculation a card reads, so a newer result of the same kind can take its place. */
export type RunFamily = 'health' | 'variance' | 'business';

export function runFamily(run: AnalysisRun): RunFamily | null {
  if (isCollectionHealthRun(run)) return 'health';
  if (isFinanceVarianceRun(run)) return 'variance';
  if (rendersBusinessView(run)) return 'business';
  return null;
}

function latest(runs: AnalysisRun[], family: RunFamily): AnalysisRun | undefined {
  return runs.filter((run) => isSuccessfulRun(run) && runFamily(run) === family).at(-1);
}

const healthRows = (run: AnalysisRun) => (run.result?.rows ?? []) as unknown as HealthRow[];

/** The unit a collection run names on its own (the group), not one read from its detail table. */
function groupEntity(run: AnalysisRun): string | undefined {
  const rows = healthRows(run).filter((row) => row.scenario === '本期');
  const named = rows.find((row) => row.entity_origin !== 'table');
  if (named) return named.entity;
  const entities = new Set(rows.map((row) => row.entity));
  return entities.size === 1 ? [...entities][0] : undefined;
}

function groupFigures(run: AnalysisRun | undefined, keys: string[], template: TemplateId): CardDraft[] {
  if (!run) return [];
  const entity = groupEntity(run);
  if (!entity) return [];
  return keys.flatMap((key) => {
    const row = healthRows(run).find((item) => item.entity === entity && item.metric_key === key && item.scenario === '本期');
    return row ? [{
      kind: 'figure' as const, title: row.metric_label.slice(0, 60), state: 'pinned' as const, run_id: run.id, template,
      select: { match: { entity, metric_key: key, scenario: '本期' }, column: 'value' },
    }] : [];
  });
}

/** One measure across the units of the detail table, worst first. Fewer than two units rank nothing. */
function tableRank(run: AnalysisRun | undefined, key: string, title: string, order: 'asc' | 'desc', template: TemplateId,
  reference?: { value: string; label: string }): CardDraft[] {
  if (!run) return [];
  const rows = healthRows(run).filter((row) => row.metric_key === key && row.scenario === '本期' && row.entity_origin === 'table'
    && Number.isFinite(Number(row.value)) && row.value !== '');
  if (rows.length < 2) return [];
  return [{
    kind: 'rank', title, state: 'pinned', run_id: run.id, template,
    select: { match: { metric_key: key, scenario: '本期', entity_origin: 'table' }, label: 'entity', column: 'value', order, limit: 10,
      ...(reference ? { reference } : {}) },
  }];
}

/** 回款情景 over the group's lines: the collection rate moved by hand, never accepted. */
function groupScenario(run: AnalysisRun | undefined, template: TemplateId): CardDraft[] {
  if (!run) return [];
  const entity = groupEntity(run);
  const match = { entity: entity ?? '', scenario: '本期' };
  if (!entity || !scenarioBase(run, match)) return [];
  return [{ kind: 'scenario', title: '回款情景：收缴率变了会怎样', state: 'pinned', run_id: run.id, template, select: { match } }];
}

const BREAK_EVEN = { value: '0', label: '生死线' };

export const TEMPLATES: Template[] = [
  {
    id: 'operating',
    title: '月度经营',
    summary: '收入和利润对预算、毛利率、费用率、全年预计，和预算到实际的利润桥。',
    needs: '先算一次预算差异、利润达成或回款健康分析。',
    cards(runs) {
      const business = latest(runs, 'business');
      const variance = latest(runs, 'variance');
      const kpis = business ? headlineRows(business).flatMap((row) => {
        const draft = figureDraft(business, row, 'actual', kpiFor(row, displayColumns(business)).title);
        return draft ? [{ ...draft, template: 'operating' as const }] : [];
      }) : [];
      const bridges = variance ? profitBridges(variance).slice(0, 3).map((bridge): CardDraft => ({
        kind: 'bridge', title: (bridge.label ? `利润桥 · ${bridge.label}` : '利润桥').slice(0, 60), state: 'pinned', run_id: variance.id,
        template: 'operating', select: { match: bridge.match },
      })) : [];
      const health = groupFigures(latest(runs, 'health'),
        ['gross_margin', 'expense_ratio', 'ttm_revenue', 'revenue_full_year_seasonal', 'net_profit_full_year_seasonal', 'revenue_le_gap'], 'operating');
      return [...kpis, ...health, ...bridges];
    },
  },
  {
    id: 'collection',
    title: '回款健康',
    summary: '距生死线、应收天数、应收蓄水和现金回收，各主体距生死线的排名，和一张拖收缴率看后果的情景卡。',
    needs: '先算一次回款健康分析。',
    cards(runs) {
      const run = latest(runs, 'health');
      return [
        ...groupFigures(run, ['collection_gap', 'collection_gap_total', 'break_even_collection', 'dso', 'ar_buildup', 'cash_collection_ratio'], 'collection'),
        ...tableRank(run, 'collection_gap', '各主体距生死线（从低到高）', 'asc', 'collection', BREAK_EVEN),
        ...groupScenario(run, 'collection'),
      ];
    },
  },
  {
    id: 'city',
    title: '城市公司',
    summary: '风险雷达、距生死线、应收天数、减值占毛利和人效，按城市公司排名。',
    needs: '先算一次带城市公司明细表的回款健康分析。',
    cards(runs) {
      const run = latest(runs, 'health');
      return [
        ...tableRank(run, 'risk_score', '风险雷达得分（从高到低）', 'desc', 'city'),
        ...tableRank(run, 'collection_gap', '各主体距生死线（从低到高）', 'asc', 'city', BREAK_EVEN),
        ...tableRank(run, 'dso', '应收天数（从长到短）', 'desc', 'city'),
        ...tableRank(run, 'impairment_to_gross_profit', '减值占毛利（从高到低）', 'desc', 'city'),
        ...tableRank(run, 'revenue_per_head', '人均创收（从高到低）', 'desc', 'city'),
      ];
    },
  },
];

/**
 * A newer result of the calculation a template card reads, when there is one. Only template cards move: a card
 * pinned from a result page stays on the result it was pinned from.
 */
export function newerRun(card: DashboardCard, runs: AnalysisRun[]): AnalysisRun | undefined {
  if (!card.template) return undefined;
  const current = runs.find((run) => run.id === card.run_id);
  const family = current ? runFamily(current) : null;
  if (!current || !family) return undefined;
  const next = latest(runs, family);
  return next && next.id !== current.id && next.created_at > current.created_at ? next : undefined;
}
