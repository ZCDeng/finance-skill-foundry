import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { ArrowRight, Check, Pin, RefreshCw, X } from 'lucide-react';
import { bridge, when, type Answer, type AnalysisRevision, type AnalysisRun, type DatasetSnapshot } from '../../bridge.js';
import { Button } from '../../components/ui/button.js';
import { DisclosureSummary } from '../../components/Disclosure.js';
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from '../../components/ui/empty.js';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '../../components/ui/alert-dialog.js';
import { RankBars, type RankItem } from '../../components/charts/RankBars.js';
import { Waterfall } from '../../components/charts/Waterfall.js';
import { groupDigits } from '../../lib/figures.js';
import { AskLink } from '../guide/GuideHub.js';
import { FigureSource } from './FigureSource.js';
import { figureSource, runIsStale, type FigureSourceContext } from './figureSource.js';
import { isCollectionHealthRun, LevelMark, type HealthRow } from './CollectionHealthView.js';
import { kpiFor } from './BusinessResultView.js';
import { profitBridges } from './RunPanel.js';
import { columnSemantics, displayColumns, formatBusinessCell, businessColumnLabel } from './businessResults.js';
import { cardSignature, matchingRows, splitDisplay, type CardDraft, type Dashboard, type DashboardCard, type PinBoard } from './dashboard.js';
import { newerRun, TEMPLATES, type Template } from './dashboardTemplates.js';
import { errorText, unwrap } from './shared.js';
import './Dashboard.css';

type Edit = (cards: DashboardCard[]) => (DashboardCard | CardDraft)[];

/**
 * The task's board as last saved, and the one way to change it: an edit of the cards as they stand. A save made over
 * a board someone else (the assistant) changed since it was read is read again and the edit made once more.
 */
export function useDashboard(taskId: string | undefined) {
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [loaded, setLoaded] = useState(false);
  const current = useRef<Dashboard | null>(null);
  const task = useRef(taskId);
  task.current = taskId;
  const load = useCallback(async () => {
    const api = bridge();
    if (!taskId || !api?.financeCall) return null;
    const read = unwrap(await api.financeCall(taskId, 'dashboard-read', {}) as Answer<{ dashboard: Dashboard | null }>);
    if (task.current !== taskId) return null;
    current.current = read.dashboard;
    setDashboard(read.dashboard);
    setLoaded(true);
    return read.dashboard;
  }, [taskId]);
  useEffect(() => {
    current.current = null;
    setDashboard(null);
    setLoaded(false);
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
      if (task.current === taskId) {
        current.current = next;
        setDashboard(next);
      }
      return next;
    }
  }, [load, taskId]);
  const pin = useCallback<PinBoard['pin']>(async (draft) => {
    const shown = await load();
    if (shown?.cards.some((card) => cardSignature(card) === cardSignature(draft))) return '看板上已经有这张卡。';
    await change((cards) => [...cards, draft]);
    return '已钉到看板，等你在「看板」页认可。';
  }, [change, load]);
  return useMemo(() => ({ dashboard, loaded, load, change, pin }), [dashboard, loaded, load, change, pin]);
}

export type DashboardState = ReturnType<typeof useDashboard>;

const STATE_WORDS: Record<DashboardCard['state'], string> = { explore: '助手提议', pinned: '待认可', accepted: '已认可' };

/** What a figure card shows of its row. */
type FigureView = { subject: string; value: string; part: string; beside: [string, string][]; level: HealthRow['level']; levelLabel: string | null; row: Record<string, unknown>; facts: [string, string][] };

function figureView(card: DashboardCard, run: AnalysisRun): FigureView | null {
  const rows = run.result?.rows ?? [];
  const found = matchingRows(rows, card.select.match);
  const column = card.select.column ?? '';
  if (found.length !== 1 || !(column in found[0])) return null;
  const row = found[0];
  if (isCollectionHealthRun(run)) {
    const health = row as unknown as HealthRow;
    // The same measure's other lines: 上年同期 or 年初, and the change.
    const beside = (rows as unknown as HealthRow[]).filter((item) => item !== health && item.entity === health.entity && item.metric_key === health.metric_key)
      .map((item): [string, string] => [item.scenario, item.display_value]);
    return {
      subject: health.entity, value: health.display_value, part: health.scenario, beside, level: health.level, levelLabel: health.level_label, row,
      facts: [['主体', health.entity], ['单位', health.unit ?? ''], ['说明', health.note]],
    };
  }
  const kpi = kpiFor(row, displayColumns(run));
  const value = column === 'actual' ? kpi.actual
    : formatBusinessCell(row[column], { name: column, label: businessColumnLabel(column), semantics: columnSemantics(column) }, row);
  const beside: [string, string][] = column === 'actual'
    ? [[kpi.estimated ? '预算（估算）' : '预算', kpi.budget], ['差异', kpi.difference], [kpi.rateLabel, kpi.rate]].filter(([, text]) => text && text !== '—') as [string, string][]
    : [];
  return {
    subject: [kpi.periodLabel, kpi.unit].join(' · '), value, part: column === 'actual' ? '实际' : businessColumnLabel(column), beside, level: null, levelLabel: null, row,
    facts: [['期间', kpi.periodLabel], ['单位', kpi.unit], ['依据', kpi.basis]],
  };
}

/** The bars of a rank card, worst first as the card orders them, at most its limit. */
function rankItems(card: DashboardCard, run: AnalysisRun): { items: RankItem[]; unit: string } {
  const { column = '', label = '', order = 'desc', limit = 10 } = card.select;
  const health = isCollectionHealthRun(run);
  const rows = matchingRows(run.result?.rows ?? [], card.select.match)
    .filter((row) => row[label] != null && row[label] !== '' && row[column] !== '' && row[column] != null && Number.isFinite(Number(row[column])));
  rows.sort((a, b) => (order === 'asc' ? 1 : -1) * (Number(a[column]) - Number(b[column])));
  let unit = '';
  const items = rows.slice(0, limit).map((row) => {
    // A collection run writes each figure with its unit; the bar takes the figure, the caption the unit.
    const written = health && typeof row.display_value === 'string' ? splitDisplay(row.display_value) : { figure: groupDigits(String(row[column]).trim()), unit: typeof row.unit === 'string' ? row.unit : '' };
    unit ||= written.unit;
    return { label: String(row[label]), value: Number(row[column]), text: written.figure, note: typeof row.level_label === 'string' && row.level_label ? row.level_label : undefined };
  });
  return { items, unit };
}

function sameMatch(left: Record<string, string>, right: Record<string, string>): boolean {
  const keys = Object.keys(left);
  return keys.length === Object.keys(right).length && keys.every((key) => right[key] === left[key]);
}

/** Whether a card still draws on another run: the rows it names are there, as the backend will check. */
function drawsOn(card: DashboardCard, run: AnalysisRun): boolean {
  if (card.kind === 'figure') return figureView(card, run) !== null;
  if (card.kind === 'rank') return rankItems(card, run).items.length >= 2;
  return profitBridges(run).some((bridge) => sameMatch(bridge.match, card.select.match));
}

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
};

export function DashboardView({ state, runs, analyses, datasets, superseded = [], readOnly, onOpenResult }: {
  state: DashboardState;
  runs: AnalysisRun[];
  analyses: AnalysisRevision[];
  datasets: DatasetSnapshot[];
  superseded?: string[];
  readOnly: boolean;
  onOpenResult?(run: AnalysisRun): void;
}) {
  const { dashboard, loaded, change } = state;
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState('');
  const [error, setError] = useState('');
  const [confirmAll, setConfirmAll] = useState(false);
  const replaced = useMemo(() => new Set(superseded), [superseded]);
  const cards = dashboard?.cards ?? [];
  const board = cards.filter((card) => card.state !== 'explore');
  const proposed = cards.filter((card) => card.state === 'explore');
  const waiting = board.filter((card) => card.state === 'pinned');
  const runOf = (card: DashboardCard) => runs.find((run) => run.id === card.run_id);
  const contextOf = (run: AnalysisRun): FigureSourceContext => ({ run, analysis: analyses.find((row) => row.id === run.analysis_id), datasets, superseded: replaced });
  const stale = board.filter((card) => { const run = runOf(card); return run ? runIsStale(contextOf(run)) : false; });
  const movable = board.flatMap((card) => { const next = newerRun(card, runs); return next && drawsOn(card, next) ? [{ card, next }] : []; });

  const act = (label: string, edit: Edit) => {
    setBusy(true); setError(''); setSaid('');
    void change(edit).then(() => setSaid(label), (failure) => setError(errorText(failure))).finally(() => setBusy(false));
  };
  const actions: CardActions = { readOnly, busy, act, onOpenResult };
  const addTemplate = (template: Template) => {
    const drafts = freshCards(template, runs, cards);
    act(`已加上「${template.title}」的 ${drafts.length} 张卡，等你认可。`, (now) => [...now, ...freshCards(template, runs, now)]);
  };
  const acceptAll = () => {
    setConfirmAll(false);
    act(`已认可 ${waiting.length} 张卡。`, (now) => now.map((card) => (card.state === 'pinned' ? { ...card, state: 'accepted' } : card)));
  };
  const moveAll = () => {
    const moves = new Map(movable.map(({ card, next }) => [card.id, next.id]));
    act(`已把 ${moves.size} 张卡换成新结果，需要重新认可。`, (now) => now.map((card) => moves.has(card.id)
      ? { ...card, run_id: moves.get(card.id)!, state: card.state === 'accepted' ? 'pinned' : card.state } : card));
  };

  if (!loaded) return <p role="status" className="analysis-note">正在读取看板…</p>;
  const figures = board.filter((card) => card.kind === 'figure');
  const charts = board.filter((card) => card.kind !== 'figure');
  return <div className="dashboard">
    <div className="analysis-section-heading"><h3>看板</h3></div>
    <p className="analysis-note">每张卡都读自这个任务已经算好的结果，点数字能看到它从哪来。看过没问题就点「认可」。</p>
    {error && <p role="alert" className="analysis-message analysis-message--error">{error}</p>}
    {said && <p role="status" className="analysis-message">{said}</p>}
    {!board.length && !proposed.length ? <TemplateChooser runs={runs} cards={cards} readOnly={readOnly} busy={busy} onAdd={addTemplate} /> : <>
      <div className="dashboard__summary">
        <p className="dashboard__counts">{`共 ${board.length} 张 · 已认可 ${board.length - waiting.length} 张 · 待认可 ${waiting.length} 张`}
          {stale.length ? <span className="dashboard__stale">{`资料已更新，${stale.length} 张待重算`}</span> : null}</p>
        {!readOnly && <div className="dashboard__tools">
          {waiting.length > 0 && <Button type="button" variant="outline" disabled={busy} onClick={() => setConfirmAll(true)}>
            <Check size={14} strokeWidth={1.5} aria-hidden />{`全部认可（${waiting.length} 张）`}</Button>}
          {movable.length > 0 && <Button type="button" variant="outline" disabled={busy} onClick={moveAll}>
            <RefreshCw size={14} strokeWidth={1.5} aria-hidden />{`换成新结果（${movable.length} 张）`}</Button>}
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
        {figures.map((card) => <BoardCard key={card.id} card={card} run={runOf(card)} contextOf={contextOf} actions={actions} newer={movable.find((item) => item.card.id === card.id)?.next} />)}
      </section>}
      {charts.length > 0 && <section aria-label="图" className="dashboard__charts">
        {charts.map((card) => <BoardCard key={card.id} card={card} run={runOf(card)} contextOf={contextOf} actions={actions} newer={movable.find((item) => item.card.id === card.id)?.next} />)}
      </section>}
      {!readOnly && <details className="analysis-details"><DisclosureSummary>从模板添加</DisclosureSummary>
        <TemplateChooser runs={runs} cards={cards} readOnly={readOnly} busy={busy} onAdd={addTemplate} compact />
      </details>}
    </>}
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

function BoardCard({ card, run, contextOf, actions, newer }: {
  card: DashboardCard; run?: AnalysisRun; contextOf(run: AnalysisRun): FigureSourceContext; actions: CardActions; newer?: AnalysisRun;
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
  } else {
    const found = profitBridges(run).find((bridge) => sameMatch(bridge.match, card.select.match));
    body = found ? <Waterfall title={card.title} steps={found.steps} unit={found.unit || undefined} />
      : <p className="analysis-note">这次结果里这一组的利润桥画不出来，可以移除。</p>;
  }
  const stale = run ? runIsStale(contextOf(run)) : false;
  return <article className={`dashboard-card dashboard-card--${card.kind}`} data-state={card.state} aria-label={card.title}>
    <header className="dashboard-card__head">
      <h4 className="dashboard-card__title" title={card.title}>{card.title}</h4>
      <span className="dashboard-card__state" data-state={card.state}>{STATE_WORDS[card.state]}</span>
    </header>
    {card.note ? <p className="dashboard-card__note">{card.note}</p> : null}
    {body}
    <footer className="dashboard-card__foot">
      {run ? <p className="dashboard-card__basis"><span>{`${when(run.created_at)} 计算`}</span>
        {card.state === 'accepted' && card.accepted ? <span>{`${when(card.accepted.at)} 认可`}</span> : null}
        {stale ? <span className="dashboard__stale">资料已更新，待重算</span> : null}</p> : null}
      <Actions card={card} run={run} actions={actions} newer={newer} />
    </footer>
  </article>;
}

function Actions({ card, run, actions, newer }: { card: DashboardCard; run?: AnalysisRun; actions: CardActions; newer?: AnalysisRun }) {
  const { readOnly, busy, act, onOpenResult } = actions;
  const set = (state: DashboardCard['state'], label: string) => act(label, (now) => now.map((item) => (item.id === card.id ? { ...item, state } : item)));
  const remove = (label: string) => act(label, (now) => now.filter((item) => item.id !== card.id));
  return <div className="dashboard-card__actions">
    {!readOnly && card.state === 'explore' && <>
      <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => set('pinned', `已钉住「${card.title}」，等你认可。`)}><Pin size={14} strokeWidth={1.5} aria-hidden />钉住</Button>
      <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => remove(`已不要「${card.title}」。`)}><X size={14} strokeWidth={1.5} aria-hidden />不要</Button>
    </>}
    {!readOnly && card.state === 'pinned' && run && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => set('accepted', `已认可「${card.title}」。`)}>
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
