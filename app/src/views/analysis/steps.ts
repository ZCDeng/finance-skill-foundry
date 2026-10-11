import type { AnalysisRevision, AnalysisRun, AnalysisState, OverviewTask, OverviewWork } from '../../bridge.js';
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

export type StepState = 'done' | 'todo' | 'attention' | 'not_started' | 'skipped';
export const STEP_WORDS: Record<StepState, string> = { done: '已完成', todo: '待处理', attention: '请留意', not_started: '未开始', skipped: '本期不做' };

/** What each step is for, in one sentence at its top. */
export const STEP_INTROS: Record<Step, string> = {
  materials: '把这个月的资料加进来，确认每份表的结构，看它们能算什么。',
  scope: '确认算哪个月、哪个组织、什么单位和币种，后面每一步都按这个范围算。',
  close: '核对套表的勾稽关系和差异，做到「可提交经理复核」。',
  results: '把财务结果讲清楚：管理损益、预算差异和明细分析。',
  operations: '看经营上发生了什么、风险在哪：回款与现金、收缴率。',
  report: '把认可的关键数字和文稿整理好，拿给老板看。',
};

/** The steps a period can do without (本期不做). 资料 and 范围 are what every other step stands on. */
export type SkippableStep = Extract<Step, 'close' | 'results' | 'operations' | 'report'>;
export const SKIPPABLE: readonly SkippableStep[] = ['close', 'results', 'operations', 'report'];
export const isSkippable = (step: Step): step is SkippableStep => (SKIPPABLE as readonly Step[]).includes(step);

/** The step after this one that the period does, if any. */
export function nextStep(step: Step, skipped: readonly Step[]): Step | null {
  const order = STEPS.map((item) => item.step);
  return order.slice(order.indexOf(step) + 1).find((item) => !skipped.includes(item)) ?? null;
}

/**
 * Whether what this step concludes rests on figures 勾稽 has not checked: 勾稽 is not done, or this period does
 * without it. Only the steps after it are concerned, and only where the task has files to check.
 */
export function unreconciled(step: Step, states: Record<Step, StepState>): boolean {
  return (step === 'results' || step === 'operations' || step === 'report') && states.materials !== 'not_started' && states.close !== 'done';
}

type Block = NonNullable<OverviewTask['blocks']>[number];
const worst = (blocks: (Block | undefined)[]): StepState | null => {
  const states = blocks.filter((block): block is Block => Boolean(block)).map((block) => block.state);
  if (!states.length) return null;
  if (states.includes('blocked')) return 'todo';
  if (states.includes('attention')) return 'attention';
  if (states.every((state) => state === 'not_started')) return 'not_started';
  return 'done';
};

/** What the step rules read of a task: its runs, its board's cards, how many drafts and files. */
type Work = { runs: AnalysisRun[]; cards: { state?: string; kind?: string }[]; drafts: number; files: number };

function statesOf({ runs, cards: all, drafts, files }: Work, progress: OverviewTask | undefined, scopeSaved: boolean): Record<Step, StepState> {
  const block = (key: string) => progress?.blocks?.find((item) => item.key === key);
  const results = runs.filter((run) => runPresentationRole(run) === 'business');
  const operations = results.filter((run) => isCollectionHealthRun(run));
  const cards = all.filter((card) => card.state !== 'explore');
  // What 等你处理 lists for a later step (计算要重算, 收费明细的列, 文稿) waits on someone, whatever was done before it.
  const waits = (step: Step) => progress?.todo.some((item) => item.target && stepOf(sectionOf(item.target)) === step) ?? false;
  return {
    materials: !files ? 'not_started' : worst([block('source'), block('structure')]) ?? 'done',
    scope: !files ? 'not_started' : worst([block('scope')]) ?? (scopeSaved ? 'done' : 'todo'),
    close: !files ? 'not_started' : worst([block('controls'), block('exceptions')]) ?? 'not_started',
    results: waits('results') ? 'todo' : results.length > operations.length ? 'done' : 'not_started',
    operations: waits('operations') ? 'todo' : operations.length ? 'done' : 'not_started',
    // A what-if card is only looked at, never accepted: it does not wait on the manager.
    report: waits('report') || cards.some((card) => card.state === 'pinned' && !isWhatIf(card.kind)) ? 'todo'
      : cards.length || drafts ? 'done' : 'not_started',
  };
}

/**
 * Each step's state, read from what the task already says: the month-close blocks 总览 reads for it (来源, 结构,
 * 范围, 控制, 异常) for the first three, the results, drafts and board for the rest. Nothing is ticked by hand.
 */
export function stepStates({ view, progress, board, scopeSaved }: {
  view: AnalysisState | null; progress?: OverviewTask; board?: Dashboard | null; scopeSaved: boolean;
}): Record<Step, StepState> {
  return statesOf({ runs: view?.runs ?? [], cards: board?.cards ?? [], drafts: view?.drafts.length ?? 0, files: view?.datasets.length ?? 0 },
    progress, scopeSaved);
}

/** A run as overview.py read it, put back in the shape runPresentationRole and isCollectionHealthRun read. */
function runOfDigest(digest: OverviewWork['runs'][number]): AnalysisRun {
  return {
    execution_status: digest.execution_status, engine: digest.engine ?? undefined, result_role: digest.role || undefined,
    output_hash: digest.outputs ? 'outputs' : undefined,
    result: { columns: digest.columns.map((name) => ({ name, type: '' })), rows: digest.rows ? [{}] : [], row_count: digest.rows ? 1 : 0,
      truncated: false, scenario_kind: digest.scenario_kind ?? undefined },
  } as unknown as AnalysisRun;
}

/** 总览's row: the same rules as the task's own steps, on what overview.py read of it. None while it cannot be read. */
export function overviewStepStates(row: OverviewTask): Record<Step, StepState> | null {
  if (!row.work || !row.blocks) return null;
  return statesOf({ runs: row.work.runs.map(runOfDigest), cards: row.work.cards, drafts: row.work.drafts, files: row.work.datasets }, row, false);
}
