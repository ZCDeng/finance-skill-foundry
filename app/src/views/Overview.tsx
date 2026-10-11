import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { ArrowRight, BookOpen, ChartNoAxesCombined, ClipboardList, FlaskConical, FolderOpen, MessageSquarePlus, RefreshCw, Repeat, Sparkles } from 'lucide-react';

import { bridge, SNAPSHOT_FORMAT_WORDS, type AnalysisRun, type AnalysisState, type GalleryRow, type Overview as OverviewData, type OverviewTask, type TaskRow, when } from '../bridge.js';
import { Button } from '../components/ui/button.js';
import { NativeSelect } from '../components/ui/native-select.js';
import { DisclosureSummary } from '../components/Disclosure.js';
import { Loading, SkeletonRows } from '../components/Loading.js';
import { formatPeriod } from '../lib/period.js';
import { isWhatIf } from './analysis/dashboardModel.js';
import { usePreferences } from '../components/Preferences.js';
import { STEP_ICONS } from './analysis/StepNav.js';
import { useDashboard } from './analysis/Dashboard.js';
import { MonthBrief } from './analysis/MonthBrief.js';
import { STEPS, STEP_WORDS, overviewStepStates, resultStep, type Step, type StepState } from './analysis/steps.js';
import { errorText } from './analysis/glossary.js';
import { unwrap } from './analysis/shared.js';
import { Cockpit, currentRow, TaskName } from './cockpit/Cockpit.js';
import { KeyFigures } from './cockpit/KeyFigures.js';
import { TryCards } from './cockpit/TryCards.js';
import './overview.css';

/** Where a to-do, a line of 本月三句话 or 试一下 is handled, as the workspace names its places. */
export type OverviewTarget = 'scope' | 'datasets' | 'structure' | 'billing' | 'controls' | 'close' | 'results' | 'operations' | 'drafts'
  | 'rollforward' | 'dashboard';

/** What one 成果库 row is, in a line. */
export function galleryLine(row: GalleryRow): string {
  switch (row.type) {
    case 'draft': return `${row.draft.title || '文稿'} · 修订 ${row.draft.revision}`;
    case 'export': return `${row.exported.title || '文稿'} · 修订 ${row.exported.revision} · ${row.exported.format.toUpperCase()}`;
    case 'chart': return row.chart.label || '归档图';
    case 'workbook': return `写回 Excel · ${row.output.dataset}`;
    case 'collection': return `收缴率计算 · 截至 ${row.run.as_of}`;
    case 'dashboard': return `看板快照 · ${SNAPSHOT_FORMAT_WORDS[row.snapshot.format]}`;
    default: return `旧版流程 · 第 ${row.row.seq} 版`;
  }
}

export interface OverviewProps {
  data: OverviewData | null;
  loading: boolean;
  error: string;
  /** No task anywhere, archived and trashed ones included: the start block is then the whole page. */
  fresh: boolean;
  /** The newest 成果库 rows, newest first. */
  recent: GalleryRow[];
  onRefresh(): void;
  onOpen(task: TaskRow, target: OverviewTarget): void;
  /** Opens a task on one of its six steps. */
  onOpenStep(task: TaskRow, step: Step): void;
  /** Opens a task on the step that holds a run's result, that run selected. */
  onOpenResult(task: TaskRow, run: AnalysisRun, step: 'results' | 'operations'): void;
  onNewQuestion(): void;
  /** 做一次经营分析: a new task, opened on 经营分析. Absent where tasks cannot be made. */
  onOperations?(): void;
  onSample?(): void;
  onChecklist(): void;
  onGuide(): void;
  onLibrary(): void;
  /** 60 秒看看它能做什么, while it has been neither seen through nor closed. */
  firstLook?: FirstLookOffer;
}

/** The first look's offer on 总览: start it over the sample's 参考结果 board, or say no once and for all. */
export interface FirstLookOffer {
  /** The 参考结果 is being built: the first time takes most of a minute. */
  busy: boolean;
  error?: string;
  onStart(): void;
  onDismiss(): void;
}

/** The task chosen on 总览 this session, kept while the manager goes to the workspace and back. */
const CHOSEN = 'fnd:overview-task';
function readChosen(): string | null {
  try { return sessionStorage.getItem(CHOSEN); } catch { return null; }
}
function keepChosen(taskId: string) {
  try { sessionStorage.setItem(CHOSEN, taskId); } catch { /* the choice then lasts while the page is open */ }
}

/** A task's six states as its own screen shows them, the steps the period does without marked so. */
function statesOf(row: OverviewTask, skipped: readonly Step[] = []): Record<Step, StepState> | null {
  const read = overviewStepStates(row);
  return read ? { ...read, ...Object.fromEntries(skipped.map((step) => [step, 'skipped' as const])) } : null;
}

/**
 * 总览: this month's cockpit. One task at a time, the one worked on last unless another is chosen: its six steps large
 * with a line each, the step to go on with, its to-dos, 本月三句话 and the figures its board holds; then the features
 * not tried yet, the other tasks in a row each, and the newest outputs.
 *
 * Reads nothing a task's own pages do not: the states are steps.ts's, a to-do is one of the month close's blocking
 * items (or a 收费明细 column or 口径 waiting on the manager), a figure is the board's card. Nothing adds figures across
 * tasks: two tasks' periods, organisations and 口径 differ, and a total of them would be a number no workbook holds.
 */
export function Overview({ data, loading, error, fresh, recent, onRefresh, onOpen, onOpenStep, onOpenResult, onNewQuestion, onOperations, onSample, onChecklist, onGuide, onLibrary, firstLook }: OverviewProps) {
  const rows = data?.tasks ?? [];
  // No active task is not the same as none at all: everything may be archived. Only the second is a first run.
  const empty = data !== null && rows.length === 0 && fresh;
  const idle = data !== null && rows.length === 0 && !fresh;
  const { preferences } = usePreferences();
  const [chosen, setChosen] = useState<string | null>(readChosen);
  const top = useRef<HTMLDivElement>(null);
  const current = currentRow(rows, chosen);
  const others = rows.filter((row) => row !== current);
  const pick = (taskId: string) => {
    setChosen(taskId);
    keepChosen(taskId);
    top.current?.scrollIntoView?.({ block: 'start' });
  };
  return (
    <div className="fnd-overview" ref={top}>
      <div className="fnd-overview__head">
        <div>
          <h1 className="fnd-overview__title">总览</h1>
          <p className="fnd-muted">这个月的账做到哪了，数怎么样，下一步点哪里。</p>
        </div>
        <Button variant="outline" type="button" disabled={loading} onClick={onRefresh}>
          <RefreshCw size={14} strokeWidth={1.5} aria-hidden />刷新
        </Button>
      </div>
      {error ? <p role="alert" className="analysis-message analysis-message--error">{error}</p> : null}
      {empty ? <FirstRun firstLook={firstLook} onNewQuestion={onNewQuestion} onOperations={onOperations} onSample={onSample} onChecklist={onChecklist} onGuide={onGuide} /> : <>
        {firstLook ? <FirstLook offer={firstLook} /> : null}
        <Recomputed rows={rows} onOpen={onOpen} />
        {data === null && loading ? <Loading label="正在读取各任务的月结状态…"><SkeletonRows rows={4} /></Loading> : null}
        {current ? <CurrentTask key={current.task.id} row={current} rows={rows} data={data} states={statesOf(current, preferences.skipped_steps[current.task.id])}
          onPick={pick} onOpen={onOpen} onOpenStep={onOpenStep} onOpenResult={onOpenResult} /> : null}
        {others.length || recent.length ? <div className="fnd-overview__grid">
          {others.length ? <Others rows={others} onPick={pick} /> : null}
          {recent.length ? <Recent rows={recent} onLibrary={onLibrary} /> : null}
        </div> : null}
        <Start idle={idle} tasks={rows.map((row) => row.task)} onOpen={onOpen} onNewQuestion={onNewQuestion} onOperations={onOperations} onSample={onSample} onChecklist={onChecklist} />
      </>}
    </div>
  );
}

/**
 * One task's analysis state, read again whenever 总览 is; the last answer stays up while the next is read. A read
 * that fails takes it down and says so: 本月三句话 and 关键数字 would otherwise stand beside a refreshed main card.
 */
function useTaskView(taskId: string, again: unknown): { view: AnalysisState | null; problem: string } {
  const [view, setView] = useState<AnalysisState | null>(null);
  const [problem, setProblem] = useState('');
  useEffect(() => {
    const api = bridge();
    if (!api?.analysisState) return;
    let live = true;
    const fail = (text: string) => { if (live) { setView(null); setProblem(text); } };
    void api.analysisState(taskId).then(unwrap).then((value) => {
      if (live) { setView(value); setProblem(''); }
    }, (failure: unknown) => fail(errorText(failure)));
    return () => { live = false; };
  }, [taskId, again]);
  return { view, problem };
}

/** The main card and what reads the task's own results under it: 本月三句话, 关键数字 and 还没试过. */
function CurrentTask({ row, rows, data, states, onPick, onOpen, onOpenStep, onOpenResult }: {
  row: OverviewTask; rows: OverviewTask[]; data: OverviewData | null; states: Record<Step, StepState> | null;
  onPick(taskId: string): void; onOpen(task: TaskRow, target: OverviewTarget): void; onOpenStep(task: TaskRow, step: Step): void;
  onOpenResult(task: TaskRow, run: AnalysisRun, step: 'results' | 'operations'): void;
}) {
  const id = useId();
  const { task } = row;
  const { view, problem } = useTaskView(task.id, data);
  const board = useDashboard(task.id);
  // 总览 read again (刷新, a change in the workspace): the board is read again with it, not only on the first look.
  const seen = useRef(data);
  useEffect(() => {
    if (seen.current === data) return;
    seen.current = data;
    void board.load().catch(() => undefined);
  }, [data, board.load]);
  const open = (target: string) => onOpen(task, target as OverviewTarget);
  const reads = Boolean(bridge()?.financeCall && bridge()?.analysisState);
  return <>
    <Cockpit row={row} rows={rows} states={states} onPick={onPick} onOpen={(_, target) => open(target)} onOpenStep={onOpenStep} />
    {problem ? <p role="alert" className="analysis-message analysis-message--error">本月三句话和关键数字没有读到：{problem}</p> : null}
    {view && view.datasets.length > 0 && bridge()?.financeCall ? <MonthBrief taskId={task.id} board={board.dashboard}
      refreshKey={`${view.datasets.length}:${view.runs.length}:${view.drafts.length}:${board.dashboard?.id ?? ''}`}
      runs={view.runs} analyses={view.analyses} datasets={view.datasets} superseded={view.superseded_datasets ?? []}
      onOpen={open} onOpenResult={(run) => onOpenResult(task, run, resultStep(run, view.analyses, view.runs))} /> : null}
    {reads && board.loaded && view ? <Section id={`${id}-figures`} title="关键数字" className="fnd-overview__card"
      note="这个任务看板上经理认可或钉住的数，点数字看来源；不跨任务相加。">
      <KeyFigures board={board.dashboard} view={view} onBoard={() => open('dashboard')} />
    </Section> : null}
    <TryCards rows={rows} taskTitle={task.title} onTry={open} />
  </>;
}

/**
 * The first screen with no task at all: three ways to begin, largest first, then what to have ready. The first look
 * shows why in a minute; the example walks the whole way; the manager's own files start a real task.
 */
function FirstRun({ firstLook, onNewQuestion, onOperations, onSample, onChecklist, onGuide }: {
  firstLook?: FirstLookOffer; onNewQuestion(): void; onOperations?(): void; onSample?(): void; onChecklist(): void; onGuide(): void;
}) {
  const id = useId();
  return <section className="fnd-overview__first" aria-labelledby={`${id}-first`}>
    <h2 id={`${id}-first`} className="fnd-overview__h">从这里开始</h2>
    <p className="fnd-muted fnd-overview__note">还没有任务。先花一分钟看看它能做什么，或者用示例练一遍，也可以直接带上自己的资料。</p>
    <ul className="fnd-overview__ways">
      {firstLook ? <li className="fnd-overview__way" data-segment="report">
        <Sparkles className="fnd-overview__way-icon" strokeWidth={1.75} aria-hidden />
        <h3 className="fnd-overview__way-title">60 秒看看它能做什么</h3>
        <p className="fnd-muted">打开示例的参考结果看板，看三处：点一个数看来源，拖一下收缴率，导出一页纸。</p>
        <div className="fnd-overview__actions">
          <Button type="button" disabled={firstLook.busy} aria-busy={firstLook.busy || undefined} onClick={firstLook.onStart}>
            {firstLook.busy ? '正在准备参考结果…' : '开始看'}</Button>
          <Button type="button" variant="ghost" disabled={firstLook.busy} onClick={firstLook.onDismiss}>不用了</Button>
        </div>
        {firstLook.busy ? <p className="fnd-muted fnd-overview__note">第一次要生成参考结果，大约一分钟。</p> : null}
        {firstLook.error ? <p role="alert" className="analysis-message analysis-message--error">{firstLook.error}</p> : null}
      </li> : null}
      {onSample ? <li className="fnd-overview__way" data-segment="close">
        <FlaskConical className="fnd-overview__way-icon" strokeWidth={1.75} aria-hidden />
        <h3 className="fnd-overview__way-title">用示例练一遍</h3>
        <p className="fnd-muted">华宸物业 8 月的资料已经备好，跟着指南走完月结、财务分析、经营分析和汇报。</p>
        <div className="fnd-overview__actions"><Button type="button" variant={firstLook ? 'outline' : 'default'} onClick={onSample}>用示例练习</Button></div>
      </li> : null}
      <li className="fnd-overview__way" data-segment="finance">
        <FolderOpen className="fnd-overview__way-icon" strokeWidth={1.75} aria-hidden />
        <h3 className="fnd-overview__way-title">带上自己的资料开始</h3>
        <p className="fnd-muted">用一句话写清要弄明白的事，再把这个月的 Excel 加进来。</p>
        <div className="fnd-overview__actions">
          <Button type="button" variant={firstLook || onSample ? 'outline' : 'default'} onClick={onNewQuestion}>
            <MessageSquarePlus size={15} strokeWidth={1.5} aria-hidden />问一个新问题</Button>
          {onOperations ? <Button type="button" variant="ghost" onClick={onOperations}>
            <ChartNoAxesCombined size={15} strokeWidth={1.5} aria-hidden />做一次经营分析</Button> : null}
        </div>
      </li>
    </ul>
    <div className="fnd-overview__actions">
      <Button type="button" variant="ghost" onClick={onChecklist}><ClipboardList size={15} strokeWidth={1.5} aria-hidden />资料准备清单</Button>
      <Button type="button" variant="ghost" onClick={onGuide}><BookOpen size={15} strokeWidth={1.5} aria-hidden />第一次使用</Button>
    </div>
  </section>;
}

/**
 * 60 秒看看它能做什么: the sample's 参考结果 board with three things pointed out on it, for the first minute. The
 * 跟着做 steps are for learning it properly; this is the minute that shows why.
 */
function FirstLook({ offer }: { offer: FirstLookOffer }) {
  const id = useId();
  return <Section id={`${id}-first-look`} title="60 秒看看它能做什么" className="fnd-overview__first-look"
    note="打开示例的参考结果看板，看三处：点一个数看来源，拖一下收缴率，导出一页纸。">
    <div className="fnd-overview__actions">
      <Button type="button" disabled={offer.busy} aria-busy={offer.busy || undefined} onClick={offer.onStart}>
        <Sparkles size={15} strokeWidth={1.5} aria-hidden />{offer.busy ? '正在准备参考结果…' : '开始看'}
      </Button>
      <Button type="button" variant="ghost" disabled={offer.busy} onClick={offer.onDismiss}>不用了</Button>
      {offer.busy ? <span className="fnd-muted fnd-overview__note">第一次要生成参考结果，大约一分钟。</span> : null}
    </div>
    {offer.error ? <p role="alert" className="analysis-message analysis-message--error">{offer.error}</p> : null}
  </Section>;
}

/** This month's, by the computer's calendar: the line counts what the app did for the manager, not a close period. */
function thisMonth(at: string, now: Date): boolean {
  const day = new Date(at);
  return !Number.isNaN(day.getTime()) && day.getFullYear() === now.getFullYear() && day.getMonth() === now.getMonth();
}

/**
 * 「本月已为你自动重算 N 张卡、发现 M 处变化」: board cards run again this month on newer files or carried from last
 * month's task, and how many moved enough to look at. Opens to the cards; nothing shows until there is one.
 */
function Recomputed({ rows, onOpen, now = new Date() }: { rows: OverviewTask[]; onOpen(task: TaskRow, target: OverviewTarget): void; now?: Date }) {
  const cards = rows.flatMap((row) => (row.dashboard?.recomputed ?? []).filter((item) => thisMonth(item.at, now)).map((item) => ({ task: row.task, item })))
    .sort((a, b) => Number(b.item.changed) - Number(a.item.changed) || b.item.at.localeCompare(a.item.at));
  if (!cards.length) return null;
  const changed = cards.filter(({ item }) => item.changed).length;
  return <details className="analysis-details fnd-overview__recomputed">
    <DisclosureSummary>{changed ? `本月已为你自动重算 ${cards.length} 张卡、发现 ${changed} 处变化`
      : `本月已为你自动重算 ${cards.length} 张卡，没有发现明显变化`}</DisclosureSummary>
    <p className="fnd-muted fnd-overview__note">资料有更新或从上月任务带过来时，看板上的卡按原来的算法重算，都等你认可。</p>
    <ul className="fnd-overview__todos">
      {cards.map(({ task, item }) => <li key={`${task.id}:${item.card_id}`}>
        <div className="fnd-overview__todo-text">
          <span className="fnd-overview__todo-task"><TaskName task={task} /></span>
          <span>{`「${item.title}」：${item.change || '已重算'}`}</span>
        </div>
        <Button type="button" size="sm" variant="outline" onClick={() => onOpen(task, 'dashboard')}>
          {item.changed || isWhatIf(item.kind) ? '去看看' : '去认可'}<ArrowRight size={13} strokeWidth={1.5} aria-hidden />
          <span className="sr-only">：{task.title}，{item.title}</span>
        </Button>
      </li>)}
    </ul>
  </details>;
}

function Section({ title, note, id, children, className }: { title: string; note?: ReactNode; id: string; children: ReactNode; className?: string }) {
  return <section className={['fnd-overview__section', className].filter(Boolean).join(' ')} aria-labelledby={id}>
    <h2 id={id} className="fnd-overview__h">{title}</h2>
    {note ? <p className="fnd-muted fnd-overview__note">{note}</p> : null}
    {children}
  </section>;
}

/** The ways to start something new, under the tasks already going. */
function Start({ idle, tasks, onOpen, onNewQuestion, onOperations, onSample, onChecklist }: {
  idle: boolean; tasks: TaskRow[]; onOpen(task: TaskRow, target: OverviewTarget): void; onNewQuestion(): void;
  onOperations?(): void; onSample?(): void; onChecklist(): void;
}) {
  const id = useId();
  // Newest period first: last month's task is nearly always the one to roll forward from.
  const sources = [...tasks]
    .sort((a, b) => (b.period ?? '').localeCompare(a.period ?? '') || b.created_at.localeCompare(a.created_at));
  return <Section id={`${id}-start`} title="开始新的" className="fnd-overview__start"
    note={idle ? '没有进行中的任务。已归档和回收站里的任务在工作区左边的任务列表里。' : undefined}>
    <div className="fnd-overview__actions">
      <Button type="button" variant="outline" onClick={onNewQuestion}>
        <MessageSquarePlus size={15} strokeWidth={1.5} aria-hidden />问一个新问题
      </Button>
      {/* 月结 is not the only use: a task can start at 经营分析. */}
      {onOperations ? <Button type="button" variant="outline" onClick={onOperations}>
        <ChartNoAxesCombined size={15} strokeWidth={1.5} aria-hidden />做一次经营分析
      </Button> : null}
      {sources.length ? <label className="fnd-overview__roll">
        <Repeat size={15} strokeWidth={1.5} aria-hidden />
        <NativeSelect aria-label="用上月套表起草本月：选上月的任务" value="" wrapperClassName="fnd-native-select--picker"
          onChange={(event) => {
            const task = sources.find((row) => row.id === event.target.value);
            if (task) onOpen(task, 'rollforward');
          }}>
          <option value="">用上月套表起草本月…</option>
          {sources.map((task) => <option key={task.id} value={task.id}>
            {task.period ? `${task.title} · ${formatPeriod(task.period)}` : task.title}
          </option>)}
        </NativeSelect>
      </label> : null}
      {onSample ? <Button type="button" variant="outline" onClick={onSample}>
        <FlaskConical size={15} strokeWidth={1.5} aria-hidden />用示例练习
      </Button> : null}
      <Button type="button" variant="outline" onClick={onChecklist}>
        <ClipboardList size={15} strokeWidth={1.5} aria-hidden />资料准备清单
      </Button>
    </div>
  </Section>;
}

/**
 * 其他进行中的任务: a row each, its six steps small as on the task screen, each named in words for readers; a step the
 * task marked 本期不做 says so. Then the close line. A row makes that task the main card.
 */
function Others({ rows, onPick }: { rows: OverviewTask[]; onPick(taskId: string): void }) {
  const id = useId();
  const { preferences } = usePreferences();
  return <Section id={`${id}-others`} className="fnd-overview__progress-section" title={`其他进行中的任务（${rows.length}）`}
    note="点一行换到上面看它；六个图标依次是 1 资料、2 范围、3 勾稽，4 财务分析，5 经营分析，6 汇报。">
    <ul className="fnd-overview__progress">
      {rows.map((row) => {
        const states = statesOf(row, preferences.skipped_steps[row.task.id]);
        return <li key={row.task.id}>
          <button type="button" className="fnd-overview__progress-row" onClick={() => onPick(row.task.id)}>
            <span className="fnd-overview__progress-name"><TaskName task={row.task} /></span>
            {states ? <span className="fnd-overview__dots" role="img"
              aria-label={STEPS.map(({ step, label }, index) => `${index + 1} ${label}${STEP_WORDS[states[step]]}`).join('，')}>
              {STEPS.map(({ step, label, group }, index) => {
                const Icon = STEP_ICONS[states[step]];
                // A hairline between 月结 and each analysis, as on the task screen.
                const opensGroup = index > 0 && STEPS[index - 1].group !== group;
                return <span key={step} className="fnd-overview__step" data-opens-group={opensGroup || undefined}>
                  <Icon className="fnd-overview__dot" data-state={states[step]} size={16} strokeWidth={1.75}
                    aria-hidden><title>{`${index + 1} ${label}：${STEP_WORDS[states[step]]}`}</title></Icon>
                </span>;
              })}
            </span> : null}
            <span className="fnd-overview__headline">
              {row.building ? '参考结果正在生成' : row.error ? `读取失败：${row.error}` : row.headline?.text ?? ''}
              {row.headline?.detail ? <span className="fnd-muted">（{row.headline.detail}）</span> : null}
            </span>
            {row.conclusion ? <span className="fnd-overview__conclusion" data-level={row.conclusion.level}>账：{row.conclusion.text}</span> : null}
          </button>
        </li>;
      })}
    </ul>
  </Section>;
}

function Recent({ rows, onLibrary }: { rows: GalleryRow[]; onLibrary(): void }) {
  const id = useId();
  return <Section id={`${id}-recent`} className="fnd-overview__recent-section" title="最近成果">
    <ul className="fnd-overview__recent">
      {rows.map((row) => <li key={row.key}>
        <span className="fnd-overview__recent-what">{galleryLine(row)}</span>
        <span className="fnd-muted"><TaskName task={row.task} /></span>
        <span className="fnd-muted fnd-overview__when">{when(row.at)}</span>
      </li>)}
    </ul>
    <div><Button type="button" variant="link" className="px-0" onClick={onLibrary}>打开成果库<ArrowRight size={13} strokeWidth={1.5} aria-hidden /></Button></div>
  </Section>;
}
