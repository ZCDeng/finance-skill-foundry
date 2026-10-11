import type { AnalysisRevision, AnalysisRun, AnalysisState, OverviewTask } from '../../bridge.js';
import { isWhatIf, type Dashboard } from './dashboardModel.js';
import { runPresentationRole } from './businessResults.js';
import { isCollectionHealthRun } from './CollectionHealthView.js';

/**
 * The task's work in six steps, in the order it is done: 月结 makes the figures right (资料, 范围, 勾稽), 财务分析
 * explains them, 经营分析 looks at what happened in the business, 汇报 is what goes to the boss. The order is a
 * suggestion, not a gate: any step opens at any time, and the period gate inside the steps stays as it was.
 */
export type Step = 'materials' | 'scope' | 'close' | 'results' | 'operations' | 'report';
/** 汇报 holds three things: the board, the drafts and the workbook written back to Excel. */
export type ReportView = 'dashboard' | 'drafts' | 'workbook';
/** A place on the task screen: a step, one of 汇报's three, or the method library the sidebar opens. */
export type AnalysisSection = Step | ReportView | 'methods';

export const STEPS: { step: Step; label: string; group: string }[] = [
  { step: 'materials', label: '资料', group: '月结' },
  { step: 'scope', label: '范围', group: '月结' },
  { step: 'close', label: '勾稽', group: '月结' },
  { step: 'results', label: '财务分析', group: '财务分析' },
  { step: 'operations', label: '经营分析', group: '经营分析' },
  { step: 'report', label: '汇报', group: '汇报' },
];
export const REPORT_VIEWS: { view: ReportView; label: string }[] = [
  { view: 'dashboard', label: '看板' }, { view: 'drafts', label: '文稿' }, { view: 'workbook', label: '写回 Excel' },
];

export const isReportView = (place: string): place is ReportView => place === 'dashboard' || place === 'drafts' || place === 'workbook';
export const stepOf = (place: AnalysisSection): Step | 'methods' => (isReportView(place) ? 'report' : place);

/**
 * Where a place named elsewhere is: 总览's to-dos, the guide, 本月三句话 and the month-close page name places in
 * their own words (datasets, structure, controls, billing …), and so did the six tabs before the steps.
 */
export function sectionOf(target: string): AnalysisSection {
  switch (target) {
    case 'scope': return 'scope';
    case 'close': case 'controls': return 'close';
    case 'results': return 'results';
    case 'operations': case 'billing': return 'operations';
    case 'report': case 'dashboard': return 'dashboard';
    case 'drafts': return 'drafts';
    case 'workbook': return 'workbook';
    case 'methods': return 'methods';
    default: return 'materials';
  }
}

/** 回款健康 belongs to 经营分析: a version saved for it, or one whose runs are its. Every other analysis is 财务分析's. */
export function isOperationsAnalysis(analysis: AnalysisRevision, runs: AnalysisRun[]): boolean {
  return analysis.finance_spec?.kind === 'collection_health'
    || runs.some((run) => run.analysis_id === analysis.id && isCollectionHealthRun(run));
}

export type StepState = 'done' | 'todo' | 'attention' | 'not_started';
export const STEP_WORDS: Record<StepState, string> = { done: '已完成', todo: '待处理', attention: '请留意', not_started: '未开始' };

type Block = NonNullable<OverviewTask['blocks']>[number];
const worst = (blocks: (Block | undefined)[]): StepState | null => {
  const states = blocks.filter((block): block is Block => Boolean(block)).map((block) => block.state);
  if (!states.length) return null;
  if (states.includes('blocked')) return 'todo';
  if (states.includes('attention')) return 'attention';
  if (states.every((state) => state === 'not_started')) return 'not_started';
  return 'done';
};

/**
 * Each step's state, read from what the task already says: the month-close blocks 总览 reads for it (来源, 结构,
 * 范围, 控制, 异常) for the first three, the results, drafts and board for the rest. Nothing is ticked by hand.
 */
export function stepStates({ view, progress, board, scopeSaved }: {
  view: AnalysisState | null; progress?: OverviewTask; board?: Dashboard | null; scopeSaved: boolean;
}): Record<Step, StepState> {
  const block = (key: string) => progress?.blocks?.find((item) => item.key === key);
  const files = view?.datasets.length ?? 0;
  const results = view?.runs.filter((run) => runPresentationRole(run) === 'business') ?? [];
  const operations = results.filter((run) => isCollectionHealthRun(run));
  const cards = board?.cards.filter((card) => card.state !== 'explore') ?? [];
  return {
    materials: !files ? 'not_started' : worst([block('source'), block('structure')]) ?? 'done',
    scope: !files ? 'not_started' : worst([block('scope')]) ?? (scopeSaved ? 'done' : 'todo'),
    close: !files ? 'not_started' : worst([block('controls'), block('exceptions')]) ?? 'not_started',
    results: results.length > operations.length ? 'done' : 'not_started',
    operations: operations.length ? 'done' : 'not_started',
    // A what-if card is only looked at, never accepted: it does not wait on the manager.
    report: cards.some((card) => card.state === 'pinned' && !isWhatIf(card.kind)) ? 'todo' : cards.length || view?.drafts.length ? 'done' : 'not_started',
  };
}
