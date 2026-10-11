import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { ArrowRight, Check, Download, LayoutDashboard, Pin, Presentation, RefreshCw, X } from 'lucide-react';
import { bridge, when, type Answer, type AnalysisRevision, type AnalysisRun, type DatasetSnapshot } from '../../bridge.js';
import { useSigner } from '../../components/Preferences.js';
import { Button } from '../../components/ui/button.js';
import { DisclosureSummary } from '../../components/Disclosure.js';
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from '../../components/ui/empty.js';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from '../../components/ui/dropdown-menu.js';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '../../components/ui/alert-dialog.js';
import { RankBars } from '../../components/charts/RankBars.js';
import { Waterfall } from '../../components/charts/Waterfall.js';
import { formatPeriod } from '../../lib/period.js';
import { AskLink } from '../guide/GuideHub.js';
import { BoardPresentation } from './BoardPresentation.js';
import { ScenarioCard } from './ScenarioCard.js';
import { scenarioBase } from './dashboardScenario.js';
import { GoalCard, SensitivityCard } from './WhatIfCards.js';
import { whatIfView, type GoalView, type SensitivityView } from './dashboardWhatIf.js';
import { FigureSource } from './FigureSource.js';
import { figureSource, runIsStale, type FigureSourceContext } from './figureSourceInfo.js';
import { LevelMark } from './CollectionHealthView.js';
import { profitBridges } from './RunPanel.js';
import { cardSignature, isWhatIf, type CardDraft, type CarryOffer, type Dashboard, type DashboardCard, type PinBoard } from './dashboardModel.js';
import { newerRun, TEMPLATES, type Template } from './dashboardTemplates.js';
import { drawsOn, figureView, rankItems, sameMatch } from './dashboardViews.js';
import { acceptedCard, buildSnapshot, type SnapshotTask } from './dashboardSnapshot.js';
import type { SnapshotFormat } from '../../../electron/reports/dashboard-snapshot.js';
import { errorText, unwrap } from './shared.js';
import './Dashboard.css';
import { SectionIcon } from '../../components/SectionIcon.js';

type Edit = (cards: DashboardCard[]) => (DashboardCard | CardDraft)[];

/** What the last recompute or carry did, said once at the top of the board. */
export type BoardNews = { cards: number; changed: number; failed: { title: string; reason: string }[]; carriedFrom?: string; error?: string };

type Recompute = { dashboard: Dashboard | null; recomputed: string[]; failed: { card_id: string; title: string; reason: string }[] };
type Carry = { dashboard: Dashboard | null; carried: string[]; failed: { card_id: string; title: string; reason: string }[] };

const changedAmong = (board: Dashboard | null, ids: string[]) => (board?.cards ?? []).filter((card) => ids.includes(card.id) && card.recomputed?.changed).length;

/**
 * The task's board as last saved, and the one way to change it: an edit of the cards as they stand. A save made over
 * a board someone else (the assistant) changed since it was read is read again and the edit made once more.
 *
 * When the files a card read have newer versions, the read says so and the board is recomputed on them at once
 * (``canRecompute``: the manager's own task, not archived): same calculation, newest files, each card back to 待认可.
 * ``onRecomputed`` then reads the task again, so the new runs are there to draw.
 */
export function useDashboard(taskId: string | undefined, { canRecompute = false, onRecomputed }: { canRecompute?: boolean; onRecomputed?(): void } = {}) {
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [news, setNews] = useState<BoardNews | null>(null);
  const current = useRef<Dashboard | null>(null);
  const task = useRef(taskId);
  task.current = taskId;
  const allowed = useRef(canRecompute);
  allowed.current = canRecompute;
  const after = useRef(onRecomputed);
  after.current = onRecomputed;
  const recomputing = useRef(false);
  const show = useCallback((next: Dashboard | null) => {
    current.current = next;
    setDashboard(next);
  }, []);
  const recompute = useCallback(async (base: Dashboard) => {
    const api = bridge();
    if (!taskId || !api?.financeCall || recomputing.current) return;
    recomputing.current = true;
    try {
      const answer = await api.financeCall(taskId, 'dashboard-recompute', { parent_id: base.id }) as Answer<Recompute>;
      if (task.current !== taskId) return;
      if (!answer.ok) {
        // Another save came first: the next read tries again.
        if (!/changed since it was read/.test(answer.message)) setNews({ cards: 0, changed: 0, failed: [], error: errorText(new Error(answer.message)) });
        return;
      }
      const out = answer.value;
      if (out.dashboard) show(out.dashboard);
      if (out.recomputed.length || out.failed.length) {
        setNews({ cards: out.recomputed.length, changed: changedAmong(out.dashboard, out.recomputed), failed: out.failed });
      }
      if (out.recomputed.length) after.current?.();
    } finally {
      recomputing.current = false;
    }
  }, [show, taskId]);
  const load = useCallback(async () => {
    const api = bridge();
    if (!taskId || !api?.financeCall) return null;
    const read = unwrap(await api.financeCall(taskId, 'dashboard-read', {}) as Answer<{ dashboard: Dashboard | null; recompute?: { ready: number } }>);
    if (task.current !== taskId) return null;
    show(read.dashboard);
    setLoaded(true);
    if (read.dashboard && (read.recompute?.ready ?? 0) > 0 && allowed.current) void recompute(read.dashboard).catch(() => undefined);
    return read.dashboard;
  }, [recompute, show, taskId]);
  useEffect(() => {
    current.current = null;
    setDashboard(null);
    setLoaded(false);
    setNews(null);
    void load().catch(() => setLoaded(true));
  }, [load]);
  const change = useCallback(async (edit: Edit) => {
    const api = bridge();
    if (!taskId || !api?.financeCall) throw new Error('此版本暂不支持看板。');
    for (let attempt = 0; ; attempt += 1) {
      const base = current.current;
      const answer = await api.financeCall(taskId, 'dashboard-save', { parent_id: base?.id ?? null, cards: edit(base?.cards ?? []) }) as Answer<Dashboard>;
      if (!answer.ok && attempt === 0 && /changed since it was read/.test(answer.message)) {
        await load();
        continue;
      }
      const next = unwrap(answer);
      if (task.current === taskId) show(next);
      return next;
    }
  }, [load, show, taskId]);
  const pin = useCallback<PinBoard['pin']>(async (draft) => {
    const shown = await load();
    if (shown?.cards.some((card) => cardSignature(card) === cardSignature(draft))) return '看板上已经有这张卡。';
    await change((cards) => [...cards, draft]);
    return '已钉到看板，等你在「看板」页认可。';
  }, [change, load]);
  /** Other tasks' boards that could come here, newest period first. */
  const offers = useCallback(async () => {
    const api = bridge();
    if (!taskId || !api?.financeCall) return [];
    return unwrap(await api.financeCall(taskId, 'dashboard-carry', {}) as Answer<{ offers: CarryOffer[] }>).offers;
  }, [taskId]);
  const carry = useCallback(async (offer: CarryOffer) => {
    const api = bridge();
    if (!taskId || !api?.financeCall) throw new Error('此版本暂不支持看板。');
    const out = unwrap(await api.financeCall(taskId, 'dashboard-carry', { from_task_id: offer.task_id }) as Answer<Carry>);
    if (task.current !== taskId) return;
    if (out.dashboard) show(out.dashboard);
    setNews({ cards: out.carried.length, changed: changedAmong(out.dashboard, out.carried), failed: out.failed, carriedFrom: offer.title });
    if (out.carried.length) after.current?.();
  }, [show, taskId]);
  const dismiss = useCallback(() => setNews(null), []);
  return useMemo(() => ({ dashboard, loaded, load, change, pin, news, dismiss, offers, carry }),
    [dashboard, loaded, load, change, pin, news, dismiss, offers, carry]);
}

export type DashboardState = ReturnType<typeof useDashboard>;

const STATE_WORDS: Record<DashboardCard['state'], string> = { explore: '助手提议', pinned: '待认可', accepted: '已认可' };
/** A what-if on the board (情景、倒推、敏感性) is never waiting to be accepted. */
const stateWord = (card: DashboardCard) => (isWhatIf(card.kind) && card.state !== 'explore' ? '情景' : STATE_WORDS[card.state]);

/** A template's cards not on the board yet. */
function freshCards(template: Template, runs: AnalysisRun[], cards: DashboardCard[]): CardDraft[] {
  const shown = new Set(cards.map(cardSignature));
  return template.cards(runs).filter((draft) => !shown.has(cardSignature(draft)));
}

type CardActions = {
  readOnly: boolean;
  busy: boolean;
  act(label: string, edit: Edit): void;
  onOpenResult?(run: AnalysisRun): void;
  /** The current person's 署名 (设置 › 使用者), sent with an acceptance; '' when nobody is chosen. */
  signer: string;
};

/** 导出一页纸: what each format is for, as the menu says it. */
export const EXPORTS: [SnapshotFormat, string, string][] = [
  ['pdf', 'PDF', '一页 A4 横版'], ['pptx', 'PPT', '一页幻灯片'], ['xlsx', 'Excel', '数字和来源'],
];

/** 60 秒看看它能做什么 on this board: three hints, and what to do when the manager has seen them or closed them. */
export type BoardTour = { onEnd(): void };

type TourStep = 'source' | 'scenario' | 'export';
const TOUR: { key: TourStep; title: string; text: string }[] = [
  { key: 'source', title: '点一个数看来源',
    text: '点框出来的那张卡上的数字：它读的是哪份资料、哪一格，用的什么公式，都写在里面。开会时有人问「这个数哪来的」，点开就是答案。' },
  { key: 'scenario', title: '拖一下收缴率',
    text: '在「回款情景」卡上改一改假设的收缴率，距生死线、现金经营利润和一年回款跟着变。它是情景，不是实际数，不进月结和文稿。' },
  { key: 'export', title: '导出一页纸',
    text: '已认可的卡可以导出成一页 PDF 或 PPT，每个数都带来源编号。开会时也可以点「汇报模式」，一张一张讲。' },
];

/** A card accepted now, under the current person's 署名 when one is chosen. The backend stamps when, on which run. */
function accept(card: DashboardCard, signer: string): DashboardCard {
  return { ...card, state: 'accepted', ...(signer ? { accepted_by: signer } : {}) };
}

export function DashboardView({ task, state, runs, analyses, datasets, superseded = [], readOnly, tour, onOpenResult }: {
  /** The task the board is on, as the page names it; without it the board has no export. */
  task?: SnapshotTask & { id: string };
  state: DashboardState;
  runs: AnalysisRun[];
  analyses: AnalysisRevision[];
  datasets: DatasetSnapshot[];
  superseded?: string[];
  readOnly: boolean;
  /** 60 秒看看它能做什么 is walking this board. */
  tour?: BoardTour;
  onOpenResult?(run: AnalysisRun): void;
}) {
  const { dashboard, loaded, load, change, news, dismiss } = state;
  const [tourAt, setTourAt] = useState(0);
  const root = useRef<HTMLDivElement>(null);
  const [busy, setBusy] = useState(false);
  const signer = useSigner();
  const [said, setSaid] = useState('');
  const [error, setError] = useState('');
  const [confirmAll, setConfirmAll] = useState(false);
  const [presenting, setPresenting] = useState(false);
  const replaced = useMemo(() => new Set(superseded), [superseded]);
  const cards = dashboard?.cards ?? [];
  const board = cards.filter((card) => card.state !== 'explore');
  const proposed = cards.filter((card) => card.state === 'explore');
  // A what-if is never accepted, so it never waits for it.
  const waiting = board.filter((card) => card.state === 'pinned' && !isWhatIf(card.kind));
  const scenarios = board.filter((card) => isWhatIf(card.kind)).length;
  const runOf = (card: DashboardCard) => runs.find((run) => run.id === card.run_id);
  const contextOf = (run: AnalysisRun): FigureSourceContext => ({ run, analysis: analyses.find((row) => row.id === run.analysis_id), datasets, superseded: replaced });
  const stale = board.filter((card) => { const run = runOf(card); return run ? runIsStale(contextOf(run)) : false; });
  const movable = board.flatMap((card) => { const next = newerRun(card, runs); return next && drawsOn(card, next) ? [{ card, next }] : []; });

  const act = (label: string, edit: Edit) => {
    setBusy(true); setError(''); setSaid('');
    void change(edit).then(() => setSaid(label), (failure) => setError(errorText(failure))).finally(() => setBusy(false));
  };
  const actions: CardActions = { readOnly, busy, act, onOpenResult, signer };
  const accepted = board.filter(acceptedCard).length;
  // 汇报模式 shows what the one-page export would, then the what-ifs as what-ifs; a card still waiting stays off.
  const laidOut = [...board.filter((card) => card.kind === 'figure'), ...board.filter((card) => card.kind !== 'figure')];
  const shown = [...laidOut.filter((card) => card.state === 'accepted' && !isWhatIf(card.kind)), ...laidOut.filter((card) => isWhatIf(card.kind))];
  const canExport = Boolean(task && bridge()?.dashboardExport);
  // What each hint frames: the first figure that opens to its source, the 回款情景 card, and 导出一页纸 (or 汇报模式
  // where this build cannot export).
  const step = tour ? TOUR[tourAt].key : null;
  const lit = {
    source: board.find((card) => card.kind === 'figure' && runOf(card))?.id,
    scenario: board.find((card) => card.kind === 'scenario' && runOf(card))?.id,
  };
  const spotlit = (card: DashboardCard) => (step === 'source' || step === 'scenario') && lit[step] === card.id;
  useEffect(() => {
    if (step) root.current?.querySelector('[data-spotlight]')?.scrollIntoView?.({ block: 'start', behavior: 'smooth' });
  }, [step, loaded]);
  const exportAs = (format: SnapshotFormat) => {
    const api = bridge();
    if (!task || !api?.dashboardExport || !dashboard) return;
    setBusy(true); setError(''); setSaid('');
    void (async () => {
      // Read once more first: a page is laid out from the board the manager is looking at, never one changed since.
      const latest = await load();
      if (!latest || latest.id !== dashboard.id) {
        setError('看板刚在别处更新过，已重新读取，看过后再导出。');
        return;
      }
      const snapshot = buildSnapshot({ board: latest, runs, contextOf, task, format, signer });
      const out = unwrap(await api.dashboardExport!(task.id, format, snapshot));
      if ('cancelled' in out) return;
      const name = out.path.split(/[\\/]/).pop() ?? out.path;
      setSaid(`已导出「${name}」，成果库里也存了一份（看板快照）。`);
    })().catch((failure) => setError(errorText(failure))).finally(() => setBusy(false));
  };
  const addTemplate = (template: Template) => {
    const drafts = freshCards(template, runs, cards);
    act(`已加上「${template.title}」的 ${drafts.length} 张卡，等你认可。`, (now) => [...now, ...freshCards(template, runs, now)]);
  };
  const acceptAll = () => {
    setConfirmAll(false);
    act(`已认可 ${waiting.length} 张卡。`, (now) => now.map((card) => (card.state === 'pinned' && !isWhatIf(card.kind) ? accept(card, signer) : card)));
  };
  const moveAll = () => {
    const moves = new Map(movable.map(({ card, next }) => [card.id, next.id]));
    act(`已把 ${moves.size} 张卡换成新结果，需要重新认可。`, (now) => now.map((card) => moves.has(card.id)
      ? { ...card, run_id: moves.get(card.id)!, state: card.state === 'accepted' ? 'pinned' : card.state } : card));
  };

  if (!loaded) return <p role="status" className="analysis-note">正在读取看板…</p>;
  const figures = board.filter((card) => card.kind === 'figure');
  const charts = board.filter((card) => card.kind !== 'figure');
  return <div className="dashboard" ref={root}>
    {tour ? <TourHint at={tourAt} onStep={setTourAt} onEnd={tour.onEnd} /> : null}
    <div className="analysis-section-heading"><h3><SectionIcon icon={LayoutDashboard} segment="report" />看板</h3></div>
    <p className="analysis-note">每张卡都读自这个任务已经算好的结果，看过没问题就点「认可」。</p>
    {error && <p role="alert" className="analysis-message analysis-message--error">{error}</p>}
    {said && <p role="status" className="analysis-message">{said}</p>}
    {news ? <NewsLine news={news} onDismiss={dismiss} /> : null}
    {!board.length && !proposed.length ? <>
      {!readOnly ? <CarryOffers state={state} busy={busy} setBusy={setBusy} setError={setError} /> : null}
      <TemplateChooser runs={runs} cards={cards} readOnly={readOnly} busy={busy} onAdd={addTemplate} />
    </> : <>
      <div className="dashboard__summary">
        <p className="dashboard__counts">{`共 ${board.length} 张 · 已认可 ${board.length - waiting.length - scenarios} 张 · 待认可 ${waiting.length} 张${scenarios ? ` · 情景 ${scenarios} 张` : ''}`}
          {stale.length ? <span className="dashboard__stale">{`资料已更新，${stale.length} 张待重算`}</span> : null}</p>
        {(!readOnly || shown.length > 0) && <div className="dashboard__tools">
          <Button type="button" variant="outline" disabled={busy || !shown.length} title={shown.length ? undefined : '先认可要汇报的卡'}
            data-spotlight={step === 'export' && !(!readOnly && canExport) ? '' : undefined}
            onClick={() => setPresenting(true)}><Presentation size={14} strokeWidth={1.5} aria-hidden />汇报模式</Button>
          {!readOnly && waiting.length > 0 && <Button type="button" variant="outline" disabled={busy} onClick={() => setConfirmAll(true)}>
            <Check size={14} strokeWidth={1.5} aria-hidden />{`全部认可（${waiting.length} 张）`}</Button>}
          {!readOnly && movable.length > 0 && <Button type="button" variant="outline" disabled={busy} onClick={moveAll}>
            <RefreshCw size={14} strokeWidth={1.5} aria-hidden />{`换成新结果（${movable.length} 张）`}</Button>}
          {!readOnly && canExport && <ExportMenu accepted={accepted} left={board.length - accepted} busy={busy} onExport={exportAs} spotlight={step === 'export'} />}
        </div>}
      </div>
      {proposed.length > 0 && <section className="dashboard__proposed" aria-labelledby="dashboard-proposed">
        <h4 id="dashboard-proposed" className="dashboard__group-title">助手提议</h4>
        <p className="analysis-note">助手提议的卡还不在看板上，钉住后才放上去。</p>
        {proposed.some((card) => card.kind === 'figure') && <div className="dashboard__figures">{proposed.filter((card) => card.kind === 'figure')
          .map((card) => <BoardCard key={card.id} card={card} run={runOf(card)} contextOf={contextOf} actions={actions} />)}</div>}
        {proposed.some((card) => card.kind !== 'figure') && <div className="dashboard__charts">{proposed.filter((card) => card.kind !== 'figure')
          .map((card) => <BoardCard key={card.id} card={card} run={runOf(card)} contextOf={contextOf} actions={actions} />)}</div>}
      </section>}
      {figures.length > 0 && <section aria-label="关键数字" className="dashboard__figures">
        {figures.map((card) => <BoardCard key={card.id} card={card} run={runOf(card)} contextOf={contextOf} actions={actions} newer={movable.find((item) => item.card.id === card.id)?.next} spotlight={spotlit(card)} />)}
      </section>}
      {charts.length > 0 && <section aria-label="图" className="dashboard__charts">
        {charts.map((card) => <BoardCard key={card.id} card={card} run={runOf(card)} contextOf={contextOf} actions={actions} newer={movable.find((item) => item.card.id === card.id)?.next} spotlight={spotlit(card)} />)}
      </section>}
      {!readOnly && <BoardAsks busy={busy} />}
      {!readOnly && <details className="analysis-details"><DisclosureSummary>从模板添加</DisclosureSummary>
        <TemplateChooser runs={runs} cards={cards} readOnly={readOnly} busy={busy} onAdd={addTemplate} compact />
      </details>}
    </>}
    {presenting && shown.length > 0 ? <BoardPresentation title={task ? [task.title, task.period].filter(Boolean).join(' · ') : '看板'} cards={shown}
      said={presentedSaid(shown, board.length - shown.length)} onClose={() => setPresenting(false)}
      slide={(card) => <BoardCard key={card.id} card={card} run={runOf(card)} contextOf={contextOf} actions={actions} presenting />} /> : null}
    <AlertDialog open={confirmAll} onOpenChange={setConfirmAll}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{`认可这 ${waiting.length} 张卡？`}</AlertDialogTitle>
          <AlertDialogDescription>认可表示你看过这些数，认为可以用。之后结果重算或换了资料，卡片会回到待认可。</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>取消</AlertDialogCancel>
          <AlertDialogAction onClick={acceptAll}>全部认可</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </div>;
}

/** One hint of 60 秒看看它能做什么, held at the top of the board while the board scrolls under it. */
function TourHint({ at, onStep, onEnd }: { at: number; onStep(at: number): void; onEnd(): void }) {
  const hint = TOUR[at];
  const last = at === TOUR.length - 1;
  return <aside className="dashboard-tour" aria-label="60 秒看看它能做什么">
    <div className="dashboard-tour__head">
      <p className="dashboard-tour__count">{`${at + 1} / ${TOUR.length}`}</p>
      <Button type="button" size="sm" variant="ghost" aria-label="关掉，不再提示" onClick={onEnd}><X size={14} strokeWidth={1.5} aria-hidden /></Button>
    </div>
    <h4 className="dashboard-tour__title">{hint.title}</h4>
    <p className="dashboard-tour__text">{hint.text}</p>
    <div className="dashboard-tour__actions">
      {at > 0 ? <Button type="button" size="sm" variant="ghost" onClick={() => onStep(at - 1)}>上一步</Button> : null}
      <Button type="button" size="sm" onClick={() => (last ? onEnd() : onStep(at + 1))}>{last ? '看完了' : '下一步'}</Button>
    </div>
  </aside>;
}

/** What 汇报模式 holds, and what it left off. */
function presentedSaid(shown: DashboardCard[], left: number) {
  const scenarios = shown.filter((card) => isWhatIf(card.kind)).length;
  const parts = [`已认可 ${shown.length - scenarios} 张`, scenarios ? `情景 ${scenarios} 张（不是实际数）` : ''].filter(Boolean).join(' · ');
  return left ? `${parts}；另有 ${left} 张待认可，没放进来。` : `${parts}。`;
}

/**
 * 导出一页纸: the accepted cards as one A4 page (PDF, or a slide) or a workbook. What is not accepted stays off it,
 * and the page says so.
 */
function ExportMenu({ accepted, left, busy, onExport, spotlight = false }: {
  accepted: number; left: number; busy: boolean; onExport(format: SnapshotFormat): void; spotlight?: boolean;
}) {
  return <DropdownMenu>
    <DropdownMenuTrigger asChild>
      <Button type="button" variant="outline" disabled={busy || !accepted} title={accepted ? undefined : '先认可要导出的卡'} data-spotlight={spotlight ? '' : undefined}>
        <Download size={14} strokeWidth={1.5} aria-hidden />导出一页纸</Button>
    </DropdownMenuTrigger>
    <DropdownMenuContent align="end" collisionPadding={16}>
      <DropdownMenuLabel>{`放进已认可的 ${accepted} 张卡`}</DropdownMenuLabel>
      {left > 0 && <p className="dashboard__export-note">{`另外 ${left} 张待认可或是情景，不放进来，页脚会写明。`}</p>}
      <DropdownMenuSeparator />
      {EXPORTS.map(([format, name, what]) => <DropdownMenuItem key={format} disabled={busy} onSelect={() => onExport(format)}>
        {`${name}（${what}）`}</DropdownMenuItem>)}
    </DropdownMenuContent>
  </DropdownMenu>;
}

/**
 * 问着加卡: questions for the assistant, put into the conversation unsent. It answers with explore cards under
 * 助手提议, which go on the board only when pinned; a filter changes which rows a card reads, never the 口径.
 */
function BoardAsks({ busy }: { busy: boolean }) {
  return <p className="analysis-note dashboard__asks"><span>让助手加卡：</span>
    <AskLink ask="dashboard-cards" label="提议几张卡" disabled={busy} />
    <AskLink ask="dashboard-by-city" label="按城市公司排一排" disabled={busy} />
    <AskLink ask="collection-scenario" label="加一张回款情景卡" disabled={busy} />
    <AskLink ask="collection-goal" label="倒推还要收多少" disabled={busy} />
    <AskLink ask="collection-sensitivity" label="加一张敏感性表" disabled={busy} />
    <span>只填进对话框，改好再发送。</span></p>;
}

/** What the last recompute or carry did, said once; the cards themselves say what changed. */
function NewsLine({ news, onDismiss }: { news: BoardNews; onDismiss(): void }) {
  const verb = news.carriedFrom ? '带过来' : '重算';
  const head = news.carriedFrom
    ? `已从「${news.carriedFrom}」带过来 ${news.cards} 张卡，按这个任务的资料重算好了`
    : `资料有更新，已按新资料重算 ${news.cards} 张卡`;
  const tail = news.changed ? `，其中 ${news.changed} 张有明显变化` : '，没有明显变化';
  return <div role={news.error ? 'alert' : 'status'} className={`analysis-message dashboard__news${news.error ? ' analysis-message--error' : ''}`}>
    {news.error ? <p>{`没能按新资料重算：${news.error}`}</p> : null}
    {news.cards ? <p>{`${head}${tail}，${news.carriedFrom ? '等你认可' : '等你重新认可'}。`}</p> : null}
    {news.failed.length ? <>
      <p>{`${news.failed.length} 张没能${verb}：`}</p>
      <ul>{news.failed.map((item) => <li key={`${item.title}:${item.reason}`}>{`「${item.title}」：${item.reason}`}</li>)}</ul>
    </> : null}
    <Button type="button" size="sm" variant="ghost" onClick={onDismiss}>知道了</Button>
  </div>;
}

/**
 * 从别的任务带过来: last month's board onto this empty one. Each card's calculation runs on this task's files of the
 * same names, so a board can come over once the month's pack is in and its tables confirmed.
 */
function CarryOffers({ state, busy, setBusy, setError }: {
  state: DashboardState; busy: boolean; setBusy(value: boolean): void; setError(text: string): void;
}) {
  const [offers, setOffers] = useState<CarryOffer[] | null>(null);
  const { offers: list, carry } = state;
  useEffect(() => {
    let live = true;
    void list().then((rows) => { if (live) setOffers(rows); }, () => { if (live) setOffers([]); });
    return () => { live = false; };
  }, [list]);
  if (!offers?.length) return null;
  const bring = (offer: CarryOffer) => {
    setBusy(true); setError('');
    void carry(offer).catch((failure) => setError(errorText(failure))).finally(() => setBusy(false));
  };
  return <section className="dashboard__carry" aria-labelledby="dashboard-carry">
    <h4 id="dashboard-carry" className="dashboard__group-title">从别的任务带过来</h4>
    <p className="analysis-note">按原来的算法，用这个任务里同名的资料重算一遍，卡片都等你认可。</p>
    <ul className="dashboard__templates">
      {offers.map((offer) => <li key={offer.task_id}>
        <div><strong>{offer.period ? `${offer.title} · ${formatPeriod(offer.period)}` : offer.title}</strong>
          <p className="analysis-note">{offer.ready === offer.cards ? `${offer.cards} 张卡，读的资料这里都有。`
            : `${offer.cards} 张卡，其中 ${offer.ready} 张读的资料这里都有。`}</p>
          {offer.missing.length ? <p className="analysis-note">{`还缺：${offer.missing.join('、')}。先加入资料并确认表结构。`}</p> : null}</div>
        <Button type="button" variant="outline" disabled={busy || !offer.ready} onClick={() => bring(offer)}>
          {offer.ready ? `带过来并重算（${offer.ready} 张）` : '带过来'}<ArrowRight size={14} strokeWidth={1.5} aria-hidden /></Button>
      </li>)}
    </ul>
  </section>;
}

/** What the last recompute said of a card waiting for the manager: where it came from, what it showed, what moved. */
function RecomputedLine({ card }: { card: DashboardCard }) {
  if (card.recompute_failed) {
    return <p className="dashboard-card__recompute" data-failed="">{`没能按新资料重算：${card.recompute_failed.reason}`}</p>;
  }
  const said = card.recomputed;
  if (!said || card.state === 'accepted') return null;
  // Where it came from is said once at the top and on 总览; the card says what it was and how it moved.
  const month = said.months ? `按 ${formatPeriod(said.months[1])}的资料重算` : '按新资料重算';
  const before = card.kind === 'figure' || isWhatIf(card.kind) ? said.before?.display
    : card.kind === 'rank' ? (said.before?.labels ?? []).slice(0, 3).join('、') : '';
  const what = card.kind === 'rank' && before ? `上次前三 ${before}` : before ? `上次 ${before}` : '';
  return <div className="dashboard-card__recompute" data-changed={said.changed ? '' : undefined}>
    <p>{month}{said.changed ? <span className="dashboard-card__changed">有变化</span> : null}</p>
    <p>{[what, said.change].filter(Boolean).join(' · ')}</p>
    {said.adjusted.length ? <p>{said.adjusted.join('；')}</p> : null}
    {said.manual.length ? <p>{`沿用上次手填的数：${said.manual.join('、')}`}</p> : null}
  </div>;
}

/** The three ready boards: each adds the cards it can draw from this task's results, or says what to calculate first. */
function TemplateChooser({ runs, cards, readOnly, busy, onAdd, compact = false }: {
  runs: AnalysisRun[]; cards: DashboardCard[]; readOnly: boolean; busy: boolean; onAdd(template: Template): void; compact?: boolean;
}) {
  const rows = TEMPLATES.map((template) => ({ template, all: template.cards(runs).length, fresh: freshCards(template, runs, cards).length }));
  const list = <ul className="dashboard__templates">
    {rows.map(({ template, all, fresh }) => <li key={template.id}>
      <div><strong>{template.title}</strong><p className="analysis-note">{template.summary}</p>
        {!all ? <p className="analysis-note">{template.needs}</p> : !fresh ? <p className="analysis-note">这套的卡都已经在看板上。</p> : null}</div>
      {!readOnly && <Button type="button" variant="outline" disabled={busy || !fresh} onClick={() => onAdd(template)}>
        {fresh ? `添加 ${fresh} 张卡` : '添加'}<ArrowRight size={14} strokeWidth={1.5} aria-hidden /></Button>}
    </li>)}
  </ul>;
  if (compact) return list;
  const none = rows.every((row) => !row.all);
  return <Empty className="analysis-empty dashboard__empty"><EmptyHeader><EmptyTitle asChild><h3>还没有看板</h3></EmptyTitle>
    <EmptyDescription>选一套模板，用这个任务已经算好的结果搭一块看板。也可以在分析结果里点开 KPI 卡上的数字，选「钉到看板」。</EmptyDescription></EmptyHeader>
    <EmptyContent>{list}
      {none && !readOnly ? <p className="analysis-note analysis-empty-asks"><AskLink ask="collection-health" label="让助手做回款健康分析" disabled={busy} /><span>只填进对话框，改好再发送。</span></p> : null}
    </EmptyContent></Empty>;
}

function BoardCard({ card, run, contextOf, actions, newer, presenting = false, spotlight = false }: {
  card: DashboardCard; run?: AnalysisRun; contextOf(run: AnalysisRun): FigureSourceContext; actions: CardActions; newer?: AnalysisRun;
  /** Framed for a hint of 60 秒看看它能做什么. */
  spotlight?: boolean;
  /** A slide of 汇报模式: the card as it reads now, without what a recompute said or anything to change it. */
  presenting?: boolean;
}) {
  let body: ReactNode = null;
  if (!run) body = <p className="analysis-note">这张卡读的计算结果已经不在这个任务里了，可以移除。</p>;
  else if (card.kind === 'figure') {
    const view = figureView(card, run);
    if (!view) body = <p className="analysis-note">这次结果里找不到这一行，可以移除。</p>;
    else {
      const info = figureSource(contextOf(run), view.row, { metric: card.title, part: view.part, value: view.value, facts: view.facts });
      body = <>
        <p className="dashboard-card__subject">{view.subject}</p>
        <p className="dashboard-card__value"><FigureSource text={view.value} info={info} />{view.level ? <LevelMark level={view.level} label={view.levelLabel} /> : null}</p>
        {view.beside.length > 0 && <dl className="dashboard-card__beside">
          {view.beside.map(([label, text]) => <div key={label}><dt>{label}</dt><dd>{text}</dd></div>)}
        </dl>}
      </>;
    }
  } else if (card.kind === 'rank') {
    const { items, unit } = rankItems(card, run);
    const reference = card.select.reference ? { value: Number(card.select.reference.value), label: card.select.reference.label } : undefined;
    body = items.length >= 2 ? <>
      <RankBars title={card.title} items={items} reference={reference} keepOrder />
      {unit ? <p className="fnd-chart__caption">{`单位：${unit}`}</p> : null}
    </> : <p className="analysis-note">这次结果里能排名的不到两行，可以移除。</p>;
  } else if (card.kind === 'scenario') {
    const base = scenarioBase(run, card.select.match);
    body = base ? <ScenarioCard base={base} context={contextOf(run)} />
      : <p className="analysis-note">这次结果里凑不齐这个主体的毛利率、期间费用率和距生死线，可以移除。</p>;
  } else if (card.kind === 'goal') {
    const view = whatIfView('goal', run, card.select) as GoalView | null;
    body = view ? <GoalCard view={view} context={contextOf(run)} />
      : <p className="analysis-note">{card.select.goal === 'budget' ? '这次结果里没有这个主体的全年收入预算和已过月数，可以移除。'
        : '这次结果里凑不齐这个主体的生死线和距生死线，可以移除。'}</p>;
  } else if (card.kind === 'sensitivity') {
    const view = whatIfView('sensitivity', run, card.select) as SensitivityView | null;
    body = view ? <SensitivityCard view={view} context={contextOf(run)} />
      : <p className="analysis-note">这次结果里没有这个主体的敏感性表，可以移除。</p>;
  } else {
    const found = profitBridges(run).find((bridge) => sameMatch(bridge.match, card.select.match));
    body = found ? <Waterfall title={card.title} steps={found.steps} unit={found.unit || undefined} />
      : <p className="analysis-note">这次结果里这一组的利润桥画不出来，可以移除。</p>;
  }
  const stale = run ? runIsStale(contextOf(run)) : false;
  return <article className={`dashboard-card dashboard-card--${card.kind}${presenting ? ' dashboard-present__card' : ''}`} data-state={card.state} data-spotlight={spotlight ? '' : undefined} aria-label={card.title}>
    <header className="dashboard-card__head">
      <h4 className="dashboard-card__title" title={card.title}>{card.title}</h4>
      <span className="dashboard-card__state" data-state={isWhatIf(card.kind) && card.state !== 'explore' ? 'scenario' : card.state}>{stateWord(card)}</span>
    </header>
    {card.note ? <p className="dashboard-card__note">{card.note}</p> : null}
    {body}
    {presenting ? null : <RecomputedLine card={card} />}
    <footer className="dashboard-card__foot">
      {run ? <p className="dashboard-card__basis"><span>{`${when(run.created_at)} 计算`}</span>
        {card.state === 'accepted' && card.accepted ? <span>{`${when(card.accepted.at)} ${card.accepted.by ? `${card.accepted.by} ` : ''}认可`}</span> : null}
        {stale ? <span className="dashboard__stale">资料已更新，待重算</span> : null}</p> : null}
      {presenting ? null : <Actions card={card} run={run} actions={actions} newer={newer} />}
    </footer>
  </article>;
}

function Actions({ card, run, actions, newer }: { card: DashboardCard; run?: AnalysisRun; actions: CardActions; newer?: AnalysisRun }) {
  const { readOnly, busy, act, onOpenResult, signer } = actions;
  const set = (state: DashboardCard['state'], label: string) => act(label, (now) => now.map((item) => (item.id !== card.id ? item
    : state === 'accepted' ? accept(item, signer) : { ...item, state })));
  const remove = (label: string) => act(label, (now) => now.filter((item) => item.id !== card.id));
  return <div className="dashboard-card__actions">
    {!readOnly && card.state === 'explore' && <>
      <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => set('pinned', `已钉住「${card.title}」，等你认可。`)}><Pin size={14} strokeWidth={1.5} aria-hidden />钉住</Button>
      <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => remove(`已不要「${card.title}」。`)}><X size={14} strokeWidth={1.5} aria-hidden />不要</Button>
    </>}
    {!readOnly && card.state === 'pinned' && !isWhatIf(card.kind) && run && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => set('accepted', `已认可「${card.title}」。`)}>
      <Check size={14} strokeWidth={1.5} aria-hidden />认可</Button>}
    {!readOnly && card.state === 'accepted' && <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => set('pinned', `已取消认可「${card.title}」。`)}>取消认可</Button>}
    {!readOnly && newer && <Button type="button" size="sm" variant="ghost" disabled={busy}
      onClick={() => act(`已把「${card.title}」换成 ${when(newer.created_at)} 的结果，需要重新认可。`, (now) => now.map((item) => (item.id === card.id
        ? { ...item, run_id: newer.id, state: item.state === 'accepted' ? 'pinned' : item.state } : item)))}>
      <RefreshCw size={14} strokeWidth={1.5} aria-hidden />换成新结果</Button>}
    {!readOnly && card.state !== 'explore' && <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => remove(`已从看板移除「${card.title}」。`)}>移除</Button>}
    {run && onOpenResult && <Button type="button" size="sm" variant="ghost" onClick={() => onOpenResult(run)}>打开结果<ArrowRight size={14} strokeWidth={1.5} aria-hidden /></Button>}
  </div>;
}
