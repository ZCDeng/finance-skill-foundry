import { ArrowRight } from 'lucide-react';
import type { AnalysisRun, AnalysisState } from '../../bridge.js';
import { Button } from '../../components/ui/button.js';
import { LevelMark } from '../analysis/CollectionHealthView.js';
import { FigureSource } from '../analysis/FigureSource.js';
import { isWhatIf, type Dashboard, type DashboardCard } from '../analysis/dashboardModel.js';
import { figureView } from '../analysis/dashboardViews.js';
import { figureSource, runIsStale, type FigureSourceContext } from '../analysis/figureSourceInfo.js';

/** How many of the board's figures 总览 shows: the few a CFO reads first. */
export const KEY_FIGURES = 4;

/**
 * 关键数字: the figure cards on this task's board that the manager accepted or pinned, accepted first, at most four.
 * Each is the board's own card read from the same run (figureView), and its value opens to the same source. One task,
 * one 口径: nothing here adds figures across tasks, which would be a number no workbook holds.
 */
export function keyFigureCards(board: Dashboard | null): DashboardCard[] {
  const cards = (board?.cards ?? []).filter((card) => card.kind === 'figure' && !isWhatIf(card.kind) && card.state !== 'explore');
  return [...cards.filter((card) => card.state === 'accepted'), ...cards.filter((card) => card.state === 'pinned')].slice(0, KEY_FIGURES);
}

export function KeyFigures({ board, view, onBoard }: { board: Dashboard | null; view: AnalysisState | null; onBoard(): void }) {
  const replaced = new Set(view?.superseded_datasets ?? []);
  const contextOf = (run: AnalysisRun): FigureSourceContext => ({ run, analysis: view?.analyses.find((row) => row.id === run.analysis_id), datasets: view?.datasets ?? [], superseded: replaced });
  const shown = keyFigureCards(board).flatMap((card) => {
    const run = view?.runs.find((row) => row.id === card.run_id);
    const figure = run ? figureView(card, run) : null;
    return run && figure ? [{ card, run, figure }] : [];
  });
  if (!shown.length) {
    return <div className="fnd-cockpit__empty">
      <p className="fnd-muted">到第 6 步看板钉几张卡、认可后，这里就显示这个任务的关键数字。</p>
      <Button type="button" variant="outline" size="sm" onClick={onBoard}>打开看板<ArrowRight size={13} strokeWidth={1.5} aria-hidden /></Button>
    </div>;
  }
  return <ul className="fnd-cockpit__figures">
    {shown.map(({ card, run, figure }) => {
      const info = figureSource(contextOf(run), figure.row, { metric: card.title, part: figure.part, value: figure.value, facts: figure.facts });
      const stale = runIsStale(contextOf(run));
      return <li key={card.id} className="fnd-cockpit__figure" data-state={card.state}>
        <p className="fnd-cockpit__figure-title" title={card.title}>{card.title}</p>
        <p className="fnd-cockpit__figure-value"><FigureSource text={figure.value} info={info} />
          {figure.level ? <LevelMark level={figure.level} label={figure.levelLabel} /> : null}</p>
        <p className="fnd-cockpit__figure-foot">
          <span>{figure.subject}</span>
          <span data-state={card.state}>{card.state === 'accepted' ? '已认可' : '待认可'}</span>
          {stale ? <span className="dashboard__stale">资料已更新，待重算</span> : null}
        </p>
      </li>;
    })}
  </ul>;
}
