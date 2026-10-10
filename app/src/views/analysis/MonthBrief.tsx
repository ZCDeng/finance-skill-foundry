import { useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  bridge, when, type AnalysisRevision, type AnalysisRun, type Answer, type BriefLine, type BriefPart, type DatasetSnapshot, type MonthBrief as Brief,
} from '../../bridge.js';
import { Button } from '../../components/ui/button.js';
import { DisclosureSummary } from '../../components/Disclosure.js';
import { Figure } from '../../components/Figure.js';
import { formatPeriod } from '../../lib/period.js';
import { AskLink } from '../guide/GuideHub.js';
import type { Dashboard, DashboardCard } from './dashboardModel.js';
import { figureView } from './dashboardViews.js';
import { FigureSource } from './FigureSource.js';
import { figureSource, runFiles, type FigureSourceContext, type FigureSourceInfo } from './figureSourceInfo.js';
import { errorText } from './shared.js';

/**
 * 本月三句话 (foundry/month_brief.py): what moved most on the board, the biggest risk on the 风险雷达 and what waits on
 * the manager, at the top of the task. A rule picks every figure from results the task already holds; each opens to its
 * source as it does on the board. The assistant may have reworded a line: the figures and links are the rule's, word
 * for word, and the rule's own line is a click away.
 */
export function MonthBrief({ taskId, refreshKey, board, runs, analyses, datasets, superseded, readOnly = false, onOpen, onOpenResult }: {
  taskId: string;
  /** Read again when this changes: the files, runs, drafts or board the lines are picked from. */
  refreshKey: string;
  board: Dashboard | null;
  runs: AnalysisRun[];
  analyses: AnalysisRevision[];
  datasets: DatasetSnapshot[];
  superseded: string[];
  /** An archived task: the lines read as they stand, and nothing offers to ask the assistant. */
  readOnly?: boolean;
  /** A place in the task: close, controls, dashboard, scope, datasets, structure, billing, results or drafts. */
  onOpen(target: string): void;
  onOpenResult(run: AnalysisRun): void;
}) {
  const [brief, setBrief] = useState<Brief | null>(null);
  const [error, setError] = useState('');
  const [original, setOriginal] = useState(false);
  // A new task starts blank: no line of the last one stays up while this one is read.
  useEffect(() => { setBrief(null); setOriginal(false); }, [taskId]);
  useEffect(() => {
    let live = true;
    const api = bridge();
    if (!api?.financeCall) return;
    void (async () => {
      const answer = await api.financeCall!(taskId, 'month-brief') as Answer<Brief>;
      if (!live) return;
      // An answer without lines (a service from before the brief) shows nothing rather than half a block.
      if (answer.ok) { setBrief(Array.isArray(answer.value?.lines) ? answer.value : null); setError(''); } else setError(answer.message);
    })().catch((failure: unknown) => { if (live) setError(errorText(failure)); });
    return () => { live = false; };
  }, [taskId, refreshKey]);
  const replaced = useMemo(() => new Set(superseded), [superseded]);
  // A quiet note in its place: the brief only gathers what the pages below already say, and they carry their own alerts.
  if (!brief) return error ? <p className="analysis-note">{`本月三句话暂时读不出：${error}`}</p> : null;
  const contextOf = (run: AnalysisRun): FigureSourceContext => ({ run, analysis: analyses.find((row) => row.id === run.analysis_id), datasets, superseded: replaced });
  const sources: Sources = { cards: board?.cards ?? [], runs, contextOf, onOpen, onOpenResult };
  const worded = brief.worded && !original ? brief.worded.lines : {};
  return <details className="analysis-details analysis-brief" open>
    <DisclosureSummary>本月三句话</DisclosureSummary>
    <ol className="analysis-brief__lines">
      {brief.lines.map((line) => <li key={line.key} data-failed={line.failed ? '' : undefined}>
        <span className="analysis-brief__label">{line.label}</span>
        <p>{partsOf(line, worded[line.key]).map((part, index) => <BriefWords key={index} part={part} sources={sources} />)}
          {line.ask && !readOnly ? <> <AskLink ask={line.ask} label="让助手做回款健康分析" /></> : null}</p>
      </li>)}
    </ol>
    <p className="analysis-note analysis-brief__foot">
      {brief.worded ? <>{original ? '这是规则写的原句。' : `措辞由${brief.worded.by === 'assistant' ? '助手' : '你'}改过，数和能点开的部分没改。`}
        <Button variant="link" size="sm" type="button" onClick={() => setOriginal((value) => !value)}>{original ? '看改过的措辞' : '看原句'}</Button></>
        : '数字按规则从看板、风险雷达和月结待办里挑，点开看来源。'}
      {readOnly ? null : <AskLink ask="month-brief" label="让助手改措辞" />}
    </p>
  </details>;
}

/**
 * The line in the words shown: the rule's parts, or the assistant's wording cut at each figure and link the rule
 * named. The service refuses a wording that drops one; were one missing all the same, the rule's line is shown.
 */
export function partsOf(line: BriefLine, worded?: string): BriefPart[] {
  if (!worded || worded === line.text) return line.parts;
  const found: { at: number; part: BriefPart }[] = [];
  for (const part of line.parts) {
    if (!part.ref) continue;
    let at = worded.indexOf(part.text);
    while (at >= 0 && found.some((seen) => at < seen.at + seen.part.text.length && seen.at < at + part.text.length)) {
      at = worded.indexOf(part.text, at + 1);
    }
    if (at < 0) return line.parts;
    found.push({ at, part });
  }
  found.sort((left, right) => left.at - right.at);
  const out: BriefPart[] = [];
  let from = 0;
  for (const { at, part } of found) {
    if (at > from) out.push({ text: worded.slice(from, at) });
    out.push(part);
    from = at + part.text.length;
  }
  if (from < worded.length) out.push({ text: worded.slice(from) });
  return out;
}

type Sources = {
  cards: DashboardCard[];
  runs: AnalysisRun[];
  contextOf(run: AnalysisRun): FigureSourceContext;
  onOpen(target: string): void;
  onOpenResult(run: AnalysisRun): void;
};

function Opens({ children, label, onClick }: { children: ReactNode; label: string; onClick(): void }) {
  // Words in a sentence: they wrap and keep the sentence's size and ink, with the link's underline.
  return <Button variant="link" type="button" aria-label={label} onClick={onClick}
    className="inline whitespace-normal text-left align-baseline text-[length:inherit] leading-[inherit] text-foreground">{children}</Button>;
}

/** One part: words, a figure that opens to its source, or words that open the place they name. */
function BriefWords({ part, sources }: { part: BriefPart; sources: Sources }) {
  const { ref } = part;
  if (!ref) return <>{part.text}</>;
  const { cards, runs, contextOf, onOpen, onOpenResult } = sources;
  if (ref.kind === 'open') {
    return <Opens label={`${part.text}，${OPENS[ref.target] ?? '打开'}`} onClick={() => onOpen(ref.target)}>{part.text}</Opens>;
  }
  if (ref.kind === 'result') {
    const run = runs.find((row) => row.id === ref.run_id);
    return run ? <Opens label={`${part.text}，打开这次计算的结果`} onClick={() => onOpenResult(run)}>{part.text}</Opens> : <>{part.text}</>;
  }
  if (ref.kind === 'row') {
    const run = runs.find((row) => row.id === ref.run_id);
    const view = run ? figureView({ kind: 'figure', select: { match: ref.match, column: ref.column } } as DashboardCard, run) : null;
    if (!run || !view) return <Figure text={part.text} />;
    return <FigureSource text={part.text} info={figureSource(contextOf(run), view.row, { metric: ref.metric, part: view.part, value: view.value, facts: view.facts })} />;
  }
  const card = cards.find((row) => row.id === ref.card_id);
  const run = card ? runs.find((row) => row.id === card.run_id) : undefined;
  const view = card?.kind === 'figure' && run ? figureView(card, run) : null;
  if (!card || !run || !view) {
    return <Opens label={`${part.text}，到看板看这张卡`} onClick={() => onOpen('dashboard')}>{part.text}</Opens>;
  }
  const now = figureSource(contextOf(run), view.row, { metric: card.title, part: view.part, value: view.value, facts: view.facts });
  if (ref.kind === 'card') return <FigureSource text={part.text} info={now} />;
  return <FigureSource text={part.text} info={ref.kind === 'card_before' ? before(card, part.text, runs, contextOf) : moved(card, part.text, now)} />;
}

const OPENS: Record<string, string> = {
  close: '到月结页处理', controls: '到月结页的勾稽控制', dashboard: '到看板', scope: '到资料页的分析范围', datasets: '到资料页',
  structure: '到资料页的表结构', billing: '到资料页的收费明细', results: '到分析结果', drafts: '到文稿', rollforward: '到滚动到下月',
};

/** What the card showed before it was run again: the run it read then, when this task holds it, and where it came from. */
function before(card: DashboardCard, text: string, runs: AnalysisRun[], contextOf: Sources['contextOf']): FigureSourceInfo {
  const said = card.recomputed!;
  const run = runs.find((row) => row.id === said.from_run_id);
  const facts: [string, string][] = [['重算时间', when(said.at)]];
  if (said.months) facts.push(['期间', `${formatPeriod(said.months[0])} → ${formatPeriod(said.months[1])}`]);
  if (said.carried_from) facts.push(['来自', `「${said.carried_from.title}」的看板`]);
  return {
    metric: card.title, part: '重算前', value: text, facts, sources: [],
    files: run ? runFiles(contextOf(run)) : [],
    computed: run ? `${when(run.created_at)} 计算` : '上一次计算，在另一个任务里',
    stale: false, runId: said.from_run_id,
  };
}

/** The change the recompute worked out between the two figures, with both beside it. */
function moved(card: DashboardCard, text: string, now: FigureSourceInfo): FigureSourceInfo {
  const said = card.recomputed!;
  const facts: [string, string][] = [['重算前', said.before?.display ?? '—'], ['现在', said.after?.display ?? '—'], ...now.facts];
  return { ...now, part: '较重算前', value: text, facts };
}
