import { useId, type ReactNode } from 'react';
import { ArrowRight, BookOpen, CircleAlert, CircleCheck, CircleDashed, CircleSlash, ClipboardList, FlaskConical, MessageSquarePlus, RefreshCw, Repeat } from 'lucide-react';

import { SNAPSHOT_FORMAT_WORDS, type GalleryRow, type Overview as OverviewData, type OverviewTask, type OverviewTodo, type TaskRow, when } from '../bridge.js';
import { Button } from '../components/ui/button.js';
import { NativeSelect } from '../components/ui/native-select.js';
import { DisclosureSummary } from '../components/Disclosure.js';
import { Loading, SkeletonRows } from '../components/Loading.js';
import { formatPeriod } from '../lib/period.js';
import { isWhatIf } from './analysis/dashboardModel.js';
import './overview.css';

/** Where a to-do is handled, as the workspace names its places. */
export type OverviewTarget = 'scope' | 'datasets' | 'structure' | 'billing' | 'controls' | 'results' | 'drafts' | 'rollforward' | 'dashboard';

/**
 * The groups 等你处理 shows, in the order a manager clears them: what only the manager can sign
 * off first, then what holds the numbers, then what is still missing.
 */
const GROUPS: { kind: OverviewTodo['kind']; title: string; note: string }[] = [
  { kind: 'signoff', title: '等你复核', note: '系统能检查的都已通过，最后一步由你复核文稿。' },
  { kind: 'exceptions', title: '差异待处置', note: '处置只能由你来做，并且要写明理由。' },
  { kind: 'controls', title: '勾稽控制待处理', note: '还没有确认的控制，或读不出、已过期的控制。' },
  { kind: 'structure', title: '表结构待确认', note: '每份 Excel 确认一次表头、明细范围和合计行。' },
  { kind: 'scope', title: '分析范围未确认', note: '期间、组织、单位和币种。' },
  { kind: 'collection', title: '收费明细与口径待确认', note: '列和收缴率口径由你确认，未确认前的结果只作试算。' },
  { kind: 'source', title: '缺少资料', note: '先把这个月的资料加进来。' },
  { kind: 'review', title: '计算与文稿待更新', note: '资料或范围改过以后，要重新计算并按新结果更新文稿。' },
];

const BLOCK_WORDS = { done: '已就绪', attention: '请留意', blocked: '待处理', not_started: '尚未开始' } as const;
const BLOCK_ICONS = { done: CircleCheck, attention: CircleAlert, blocked: CircleSlash, not_started: CircleDashed } as const;

/** A task's name with its period, the way every list in the app writes it. */
function TaskName({ task }: { task: TaskRow }) {
  return <>
    <span className="fnd-overview__task-title">{task.title}</span>
    {task.period ? <span className="fnd-muted"> · <span className="fnd-period">{formatPeriod(task.period)}</span></span> : null}
    {task.sample && !task.title.startsWith('示例') ? <span className="fnd-overview__tag">示例</span> : null}
  </>;
}

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
  onOpenClose(task: TaskRow): void;
  onNewQuestion(): void;
  onSample?(): void;
  onChecklist(): void;
  onGuide(): void;
  onLibrary(): void;
}

/**
 * 总览: every active task at once, and the next thing each one needs.
 *
 * Reads nothing a task's own 月结 page does not: each line is `finance-close-status`'s, and a to-do
 * is one of its blocking items (or a 收费明细 column or 口径 waiting on the manager). Nothing here
 * adds figures across tasks: two tasks' periods, organisations and 口径 differ, and a total of
 * them would be a number no workbook holds.
 */
export function Overview({ data, loading, error, fresh, recent, onRefresh, onOpen, onOpenClose, onNewQuestion, onSample, onChecklist, onGuide, onLibrary }: OverviewProps) {
  const rows = data?.tasks ?? [];
  // No active task is not the same as none at all: everything may be archived. Only the second is a first run.
  const empty = data !== null && rows.length === 0 && fresh;
  const idle = data !== null && rows.length === 0 && !fresh;
  return (
    <div className="fnd-overview">
      <div className="fnd-overview__head">
        <div>
          <h1 className="fnd-overview__title">总览</h1>
          <p className="fnd-muted">所有进行中的任务走到哪一步，哪些事在等你处理。</p>
        </div>
        <Button variant="outline" type="button" disabled={loading} onClick={onRefresh}>
          <RefreshCw size={14} strokeWidth={1.5} aria-hidden />刷新
        </Button>
      </div>
      {error ? <p role="alert" className="analysis-message analysis-message--error">{error}</p> : null}
      <Recomputed rows={rows} onOpen={onOpen} />
      <Start empty={empty} idle={idle} tasks={rows.map((row) => row.task)} onOpen={onOpen} onNewQuestion={onNewQuestion} onSample={onSample} onChecklist={onChecklist} onGuide={onGuide} />
      {data === null && loading ? <Loading label="正在读取各任务的月结状态…"><SkeletonRows rows={4} /></Loading> : null}
      {rows.length ? <div className="fnd-overview__grid">
        <Todos rows={rows} onOpen={onOpen} />
        <Progress rows={rows} onOpenClose={onOpenClose} />
      </div> : null}
      {recent.length ? <Recent rows={recent} onLibrary={onLibrary} /> : null}
    </div>
  );
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

/** The four ways in. With no task at all this is the whole first screen. */
function Start({ empty, idle, tasks, onOpen, onNewQuestion, onSample, onChecklist, onGuide }: {
  empty: boolean; idle: boolean; tasks: TaskRow[]; onOpen(task: TaskRow, target: OverviewTarget): void; onNewQuestion(): void;
  onSample?(): void; onChecklist(): void; onGuide(): void;
}) {
  const id = useId();
  // Newest period first: last month's task is nearly always the one to roll forward from.
  const sources = [...tasks]
    .sort((a, b) => (b.period ?? '').localeCompare(a.period ?? '') || b.created_at.localeCompare(a.created_at));
  return <Section id={`${id}-start`} title={empty ? '从这里开始' : '开始'} className={empty ? 'fnd-overview__start--first' : 'fnd-overview__start'}
    note={empty ? '还没有任务。可以先用示例练一遍，也可以直接带上自己的资料提问。'
      : idle ? '没有进行中的任务。已归档和回收站里的任务在工作区左边的任务列表里。' : undefined}>
    <div className="fnd-overview__actions">
      <Button type="button" variant={empty ? 'default' : 'outline'} onClick={onNewQuestion}>
        <MessageSquarePlus size={15} strokeWidth={1.5} aria-hidden />问一个新问题
      </Button>
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
      {empty ? <Button type="button" variant="ghost" onClick={onGuide}>
        <BookOpen size={15} strokeWidth={1.5} aria-hidden />第一次使用
      </Button> : null}
    </div>
  </Section>;
}

function Todos({ rows, onOpen }: { rows: OverviewTask[]; onOpen(task: TaskRow, target: OverviewTarget): void }) {
  const id = useId();
  const all = rows.flatMap((row) => row.todo.map((item) => ({ task: row.task, item })));
  const groups = GROUPS.map((group) => ({ ...group, items: all.filter(({ item }) => item.kind === group.kind) }))
    .filter((group) => group.items.length);
  return <Section id={`${id}-todo`} title={all.length ? `等你处理（${all.length}）` : '等你处理'}
    note={all.length ? '每一条都挡着某个任务的月结。点「去处理」直接到要处理的位置。' : undefined}>
    {groups.length === 0 ? <p className="fnd-overview__clear"><CircleCheck size={16} strokeWidth={1.5} aria-hidden />没有挡住月结的事项。</p> : null}
    {groups.map((group) => <details key={group.kind} className="analysis-details fnd-overview__group" open>
      <DisclosureSummary>{group.title} · {group.items.length}</DisclosureSummary>
      <p className="fnd-muted fnd-overview__note">{group.note}</p>
      <ul className="fnd-overview__todos">
        {group.items.map(({ task, item }, index) => <li key={`${task.id}:${index}`}>
          <div className="fnd-overview__todo-text">
            <span className="fnd-overview__todo-task"><TaskName task={task} /></span>
            <span>{item.text}</span>
          </div>
          {item.target ? <Button type="button" size="sm" variant="outline" onClick={() => onOpen(task, item.target as OverviewTarget)}>
            去处理<ArrowRight size={13} strokeWidth={1.5} aria-hidden />
            <span className="sr-only">：{task.title}，{item.text}</span>
          </Button> : null}
        </li>)}
      </ul>
    </details>)}
  </Section>;
}

function Progress({ rows, onOpenClose }: { rows: OverviewTask[]; onOpenClose(task: TaskRow): void }) {
  const id = useId();
  const labels = rows.find((row) => row.blocks)?.blocks?.map((block) => block.label) ?? ['范围', '来源', '结构', '控制', '异常', '复核'];
  return <Section id={`${id}-progress`} className="fnd-overview__progress-section" title={`月结进度（进行中 ${rows.length} 个任务）`} note="六个点依次是范围、来源、结构、控制、异常和复核。">
    <ul className="fnd-overview__progress">
      {rows.map((row) => <li key={row.task.id}>
        <button type="button" className="fnd-overview__progress-row" onClick={() => onOpenClose(row.task)}>
          <span className="fnd-overview__progress-name"><TaskName task={row.task} /></span>
          {row.blocks ? <span className="fnd-overview__dots" role="img"
            aria-label={row.blocks.map((block) => `${block.label}${BLOCK_WORDS[block.state]}`).join('，')}>
            {row.blocks.map((block, index) => {
              const Icon = BLOCK_ICONS[block.state];
              return <Icon key={block.key} className="fnd-overview__dot" data-state={block.state} size={16} strokeWidth={1.75}
                aria-hidden><title>{`${labels[index] ?? block.label}：${BLOCK_WORDS[block.state]}`}</title></Icon>;
            })}
          </span> : null}
          <span className="fnd-overview__headline">
            {row.building ? '参考结果正在生成' : row.error ? `读取失败：${row.error}` : row.headline?.text ?? ''}
            {row.headline?.detail ? <span className="fnd-muted">（{row.headline.detail}）</span> : null}
          </span>
          {row.conclusion ? <span className="fnd-overview__conclusion" data-level={row.conclusion.level}>账：{row.conclusion.text}</span> : null}
        </button>
      </li>)}
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
