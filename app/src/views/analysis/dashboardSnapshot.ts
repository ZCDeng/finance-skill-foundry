/**
 * 看板快照: what the board shows of its accepted cards, as the data the desktop prints (electron/reports/
 * dashboard-snapshot.ts) and the backend holds to the board before filing it (foundry/dashboard_snapshot.py).
 *
 * Every figure, bar and step is read from the run the card reads, through the same views the board draws, so a page
 * and the board never differ. Only accepted cards go in; 待认可 cards and 回款情景 what-ifs are named as left out.
 */
import type { AnalysisRevision, AnalysisRun } from '../../bridge.js';
import { accountingFigure } from '../../lib/figures.js';
import {
  PAGE_FIGURES, pageCharts, type DashboardSnapshot, type SnapshotBridge, type SnapshotFigure, type SnapshotFormat, type SnapshotNamed,
  type SnapshotRank, type SnapshotText,
} from '../../../electron/reports/dashboard-snapshot.js';
import { profitBridges } from './RunPanel.js';
import { matchingRows, type Dashboard, type DashboardCard } from './dashboardModel.js';
import { figureView, rankItems, sameMatch } from './dashboardViews.js';
import { figureSource, runFiles, type FigureSourceContext } from './figureSourceInfo.js';

/** A card the manager accepted on the run it reads now: the only kind a snapshot shows (dashboard_snapshot.accepted). */
export function acceptedCard(card: DashboardCard): boolean {
  return card.state === 'accepted' && card.kind !== 'scenario' && card.accepted?.run_id === card.run_id;
}

const shown = (text: string): SnapshotText => { const figure = accountingFigure(text); return { text: figure.text, negative: figure.negative }; };
const cut = (text: string, max: number) => (Array.from(text).length > max ? `${Array.from(text).slice(0, max - 1).join('')}…` : text);
const named = (card: DashboardCard): SnapshotNamed => ({ card_id: card.id, title: card.title });
const KEYS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';

export type SnapshotTask = { title: string; period: string };

/**
 * The snapshot of ``board`` for one format. A page (PDF, PPT) holds at most two rows of figures and the charts that fit
 * beside them; the accepted cards past that are named on it, and an Excel snapshot holds every one. Throws, in words a
 * manager reads, when an accepted card no longer draws on its run.
 */
export function buildSnapshot({ board, runs, contextOf, task, format }: {
  board: Dashboard; runs: AnalysisRun[]; contextOf(run: AnalysisRun): FigureSourceContext; task: SnapshotTask; format: SnapshotFormat;
}): DashboardSnapshot {
  const cards = board.cards.filter((card) => card.state !== 'explore');
  const wanted = cards.filter(acceptedCard);
  if (!wanted.length) throw new Error('看板上还没有认可的卡，先认可要导出的卡。');
  const page = format !== 'xlsx';
  const figureCards = wanted.filter((card) => card.kind === 'figure');
  const chartCards = wanted.filter((card) => card.kind !== 'figure');
  const figuresTaken = page ? figureCards.slice(0, PAGE_FIGURES) : figureCards;
  const chartsTaken = page ? chartCards.slice(0, pageCharts(figuresTaken.length)) : chartCards;
  const beyond = wanted.filter((card) => !figuresTaken.includes(card) && !chartsTaken.includes(card));

  const keys = new Map<string, string>();
  const used: AnalysisRun[] = [];
  const sources: DashboardSnapshot['sources'] = [];
  const runOf = (card: DashboardCard) => {
    const run = runs.find((row) => row.id === card.run_id);
    if (!run) throw new Error(`「${card.title}」读的计算结果已经不在这个任务里了，先移除这张卡再导出。`);
    if (!keys.has(run.id)) { keys.set(run.id, KEYS[keys.size] ?? String(keys.size + 1)); used.push(run); }
    return run;
  };
  const sourceOf = (card: DashboardCard, run: AnalysisRun, row: Record<string, unknown> | undefined, said: { value?: string; part?: string; facts?: [string, string][]; lead?: string[] } = {}) => {
    const n = sources.length + 1;
    const info = row ? figureSource(contextOf(run), row, { metric: card.title, part: said.part ?? '', value: said.value ?? '', facts: said.facts ?? [] }) : null;
    // 依据 says how a business figure was taken; 主体、期间、单位 are on the tile already.
    const lines = [...(said.lead ?? []), ...[...(info?.sources ?? []), ...(info?.facts ?? []).filter(([label]) => label === '依据')]
      .map(([label, text]) => `${label}：${text}`)].map((line) => cut(line, 600)).slice(0, 12);
    sources.push({ n, card_id: card.id, title: card.title, run: keys.get(run.id)!, lines });
    return n;
  };

  const figures = figuresTaken.map((card): SnapshotFigure => {
    const run = runOf(card);
    const view = figureView(card, run);
    const column = card.select.column ?? '';
    const cell = view?.row[column];
    if (!view || cell == null || String(cell).trim() === '') throw new Error(`「${card.title}」在这次结果里找不到它的数，先移除这张卡再导出。`);
    return {
      card_id: card.id, title: card.title, subject: cut(view.subject, 200), part: cut(view.part, 200),
      value: shown(view.value), level: view.level, level_label: view.levelLabel ?? '',
      beside: view.beside.slice(0, 6).map(([label, text]) => ({ label: cut(label, 200), text: cut(text, 200) })),
      note: card.note ?? '', source: sourceOf(card, run, view.row, { value: view.value, part: view.part, facts: view.facts }),
      cell: { column, value: String(cell) },
    };
  });
  const charts = chartsTaken.map((card): SnapshotRank | SnapshotBridge => {
    const run = runOf(card);
    if (card.kind === 'rank') {
      const { items, unit } = rankItems(card, run);
      if (items.length < 2) throw new Error(`「${card.title}」这次结果里能排名的不到两行，先移除这张卡再导出。`);
      const reference = card.select.reference ? { value: Number(card.select.reference.value), label: card.select.reference.label } : null;
      // The rows a ranking reads share one formula; its first row says it.
      const lead = [`排序：${card.select.order === 'asc' ? '从低到高' : '从高到低'}，取前 ${items.length} 名`, ...(reference ? [`参考线：${reference.label} ${card.select.reference!.value}`] : [])];
      return {
        card_id: card.id, kind: 'rank', title: card.title, unit, note: card.note ?? '',
        source: sourceOf(card, run, matchingRows(run.result?.rows ?? [], card.select.match)[0], { lead }),
        // Labels go as the run writes them: the backend holds each bar to its row by name.
        items: items.map((item) => ({ label: item.label, value: item.value, shown: shown(item.text), note: item.note ?? '' })),
        reference,
      };
    }
    const found = profitBridges(run).find((bridge) => sameMatch(bridge.match, card.select.match));
    if (!found) throw new Error(`「${card.title}」这次结果里的利润桥画不出来，先移除这张卡再导出。`);
    return {
      card_id: card.id, kind: 'bridge', title: card.title, unit: found.unit, note: card.note ?? '',
      source: sourceOf(card, run, matchingRows(run.result?.rows ?? [], card.select.match).find((row) => row.metric === 'profit'),
        { lead: ['利润桥：对照利润，加上收入、成本、费用各自的贡献，到实际利润'] }),
      steps: found.steps.map((step) => ({ label: step.label, kind: step.kind, value: step.value, shown: shown(step.text) })),
    };
  });

  return {
    version: 1, board_id: board.id, task: cut(task.title, 200), period: task.period,
    figures, charts, sources,
    runs: used.map((run) => {
      const context = contextOf(run);
      const info = figureSource(context, {}, { metric: '', part: '', value: '' });
      return {
        key: keys.get(run.id)!, run_id: run.id, label: cut(questionOf(context.analysis), 200), computed: cut(info.computed, 200),
        files: runFiles(context).slice(0, 20).map((file) => cut(`${file.name}${file.digest ? `（摘要 ${file.digest}）` : ''}`, 600)),
      };
    }),
    beyond: beyond.map(named),
    left_out: {
      pinned: cards.filter((card) => card.kind !== 'scenario' && !acceptedCard(card)).map(named),
      scenario: cards.filter((card) => card.kind === 'scenario').map(named),
    },
  };
}

function questionOf(analysis?: AnalysisRevision): string {
  return analysis?.question?.trim() ?? '';
}
