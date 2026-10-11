import type { OverviewBlockItem, OverviewTask } from '../../bridge.js';
import { formatPeriod } from '../../lib/period.js';
import { isWhatIf } from '../analysis/dashboardModel.js';
import { overviewResults, sectionOf, stepOf, STEPS, type Step, type StepState } from '../analysis/steps.js';

/**
 * The line under each of the six steps on 总览's main card: what the step holds, in the words its own page uses. It
 * reads only what overview.py read of the task (the month-close blocks' rows, the runs, the board, the radar) and
 * decides nothing: whether a step is done is steps.ts's, and what waits on the manager is the to-do list's.
 */
export function stepLines(row: OverviewTask, states: Record<Step, StepState>): Record<Step, string> {
  const items = (key: string): OverviewBlockItem[] => row.blocks?.find((block) => block.key === key)?.items ?? [];
  const files = row.work?.datasets ?? 0;
  // A later step's own to-dos (计算要重算, 收费明细的列, 文稿待更新) are said after its line.
  const waiting = (step: Step, line: string) => {
    const count = row.todo.filter((item) => item.target && stepOf(sectionOf(item.target)) === step).length;
    return count ? `${line}；${count} 件等你处理` : line;
  };
  const lines: Record<Step, string> = {
    materials: materialsLine(files, items('structure')),
    scope: scopeLine(files, items('scope')),
    close: closeLine(files, items('controls'), items('exceptions')),
    results: waiting('results', resultsLine(row)),
    operations: waiting('operations', operationsLine(row)),
    report: waiting('report', reportLine(row)),
  };
  for (const { step } of STEPS) if (states[step] === 'skipped') lines[step] = '本期不做';
  return lines;
}

function materialsLine(files: number, structure: OverviewBlockItem[]): string {
  if (!files) return '还没有资料';
  const pending = structure.filter((item) => item.blocking).length;
  return pending ? `${files} 份资料，${pending} 份表结构等你确认` : `${files} 份资料，表结构都已确认`;
}

function scopeLine(files: number, scope: OverviewBlockItem[]): string {
  const missing = scope.filter((item) => item.blocking).map((item) => item.text.replace(/未确认$/, ''));
  if (missing.length) return files ? `${missing.join('、')}还没确认` : '先加资料，再确认范围';
  const values = scope.find((item) => item.scope)?.scope;
  if (!values) return scope[0]?.text ?? '';
  // The period in words, as every page writes it; the rest as confirmed.
  return Object.entries(values).map(([key, value]) => (key === 'period' ? formatPeriod(value) : value)).filter(Boolean).join(' · ');
}

function closeLine(files: number, controls: OverviewBlockItem[], exceptions: OverviewBlockItem[]): string {
  if (!files) return '先加资料';
  const none = controls.find((item) => item.blocking && item.text === '还没有确认的勾稽控制');
  if (none) return none.text;
  const held = controls.filter((item) => item.blocking).length;
  const differences = exceptions.filter((item) => item.blocking).length;
  const summary = controls.find((item) => !item.blocking)?.text ?? '';
  const open = [held ? `${held} 条控制待处理` : '', differences ? `${differences} 处差异待处置` : ''].filter(Boolean);
  return open.length ? `${summary}；${open.join('，')}` : `${summary}，没有未处置的差异`;
}

/** The questions answered, one per version, newest first: 管理损益、预算差异 等 3 项. */
function named(runs: { analysis_id?: string | null; label?: string }[]): string {
  const labels: string[] = [];
  const seen = new Set<string>();
  for (const run of [...runs].reverse()) {
    const key = run.analysis_id ?? run.label ?? '';
    if (seen.has(key)) continue;
    seen.add(key);
    labels.push(run.label || '计算');
  }
  return labels.length > 2 ? `${labels.slice(0, 2).join('、')} 等 ${labels.length} 项` : labels.join('、');
}

function resultsLine(row: OverviewTask): string {
  const { results } = overviewResults(row);
  return results.length ? `已算：${named(results)}` : '还没有财务分析结果';
}

const LIGHTS: [string, string][] = [['red', '红色'], ['orange', '橙色'], ['yellow', '黄色']];

function operationsLine(row: OverviewTask): string {
  const levels = row.health?.levels;
  if (levels) {
    const total = Object.values(levels).reduce((sum, count) => sum + (count ?? 0), 0);
    const lit = LIGHTS.filter(([level]) => levels[level as keyof typeof levels]).map(([level, word]) => `${levels[level as keyof typeof levels]} 个${word}`);
    if (lit.length) return `回款健康：风险雷达 ${lit.join('、')}`;
    if (total) return `回款健康：风险雷达 ${total} 个主体都是绿色`;
  }
  const { operations } = overviewResults(row);
  return operations.length ? `已做 ${operations.length} 次回款健康` : '还没做回款健康';
}

function reportLine(row: OverviewTask): string {
  const cards = (row.work?.cards ?? []).filter((card) => card.state !== 'explore');
  const waiting = cards.filter((card) => card.state === 'pinned' && !isWhatIf(card.kind)).length;
  const drafts = row.work?.drafts ?? 0;
  const board = cards.length ? `看板 ${cards.length} 张卡${waiting ? `，${waiting} 张待认可` : ''}` : '看板还没有卡';
  return drafts ? `${board}；文稿 ${drafts} 版` : board;
}
