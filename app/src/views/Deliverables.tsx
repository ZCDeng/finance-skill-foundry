import { Fragment, useMemo, useState } from 'react';
import { ArrowLeft, BarChart3, Eye, FilePen, FileSpreadsheet, FileText, ExternalLink, LayoutDashboard, Percent, Search } from 'lucide-react';

import { DisclosureSummary } from '../components/Disclosure.js';
import { NativeSelect } from '../components/ui/native-select.js';
import { LibraryPanel, type LibraryPanelActions, type LibrarySelection } from './LibraryPanel.js';

import { Reader } from '../components/Reader.js';
import { Button } from '../components/ui/button.js';
import { Input } from '../components/ui/input.js';
import { formatPeriod } from '../lib/period.js';
import {
  type AnalysisDraftRow,
  type AnalysisExportRow,
  type ChartRow,
  type CollectionRunRow,
  type DashboardSnapshotRow,
  type DeliverableRow,
  type ExportFormat,
  type GalleryRow,
  type TaskRow,
  type WorkbookOutputRow,
  SNAPSHOT_FORMAT_WORDS,
  bytes,
  isWorkbook,
  when,
} from '../bridge.js';
import { draftStateText } from './analysis/presentation.js';
import { TechnicalInfo } from './analysis/TechnicalInfo.js';
import { Empty, EmptyDescription, EmptyTitle } from '../components/ui/empty.js';
import { Loading, SkeletonRows } from '../components/Loading.js';

const KIND_LABEL: Record<DeliverableRow['kind'], string> = {
  brief: '结论稿',
  workpaper: '底稿',
  export: '导出件',
};

/** The names the 文稿 export menu gives each format. */
const FORMAT_LABEL: Record<ExportFormat, string> = {
  md: 'Markdown', xlsx: 'Excel', docx: 'Word', pdf: 'PDF', html: 'HTML',
};

const MODE_LABEL: Record<string, string> = { management: '管理版', audit: '审计版' };

/** The 文稿 export menu's order (ReportEditor), so a row's chips read the way the menu does. */
const FORMAT_ORDER: ExportFormat[] = ['docx', 'pdf', 'html', 'md', 'xlsx'];
/** Export rows in a revision's cell: 管理版, 审计版, then anything else (no mode, or one this build does not name). */
type ModeRow = 'management' | 'audit' | 'other';
const MODE_ORDER: ModeRow[] = ['management', 'audit', 'other'];
const ROW_LABEL: Record<ModeRow, string> = { management: '管理版', audit: '审计版', other: '其他' };
const modeRow = (mode: string | null): ModeRow => mode === 'management' || mode === 'audit' ? mode : 'other';

/** `when` to the second, for two exports of one format filed in the same minute. */
function whenToSecond(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  return `${when(iso)}:${String(at.getSeconds()).padStart(2, '0')}`;
}

/**
 * The visible tag that tells the exports of one format in one row apart. The newest keeps the bare format
 * name; each older one adds its time, to the second when two share a minute, and its place (第 N 份,
 * counted from the oldest) when two share a second too.
 */
function exportStamps(files: AnalysisExportRow[]): Map<string, string> {
  const stamps = new Map<string, string>();
  for (const format of FORMAT_ORDER) {
    const same = files.filter((row) => row.format === format);
    const older = same.slice(1);
    const clash = (stamp: (iso: string) => string, row: AnalysisExportRow) =>
      older.some((other) => other !== row && stamp(other.created_at) === stamp(row.created_at));
    older.forEach((row, index) => {
      const stamp = !clash(when, row) ? when(row.created_at)
        : !clash(whenToSecond, row) ? whenToSecond(row.created_at)
          : `第 ${same.length - 1 - index} 份`;
      stamps.set(row.export_id, stamp);
    });
  }
  return stamps;
}

/**
 * One 文稿 revision and every file exported from it. `state` is the revision's own review and publication
 * state: the draft's when the chain's newest draft is this revision, else the newest export's, which reads
 * the same record.
 */
type RevisionLine = {
  kind: 'revision'; key: string; at: string; draftId: string; revision: number; title: string;
  draft: AnalysisDraftRow | null; state: { publication_status: string; review_status: string }; exports: AnalysisExportRow[];
};
type OldLine = { kind: 'old'; key: string; at: string; row: DeliverableRow };
type ChartLine = { kind: 'chart'; key: string; at: string; chart: ChartRow };
type WorkbookLine = { kind: 'workbook'; key: string; at: string; output: WorkbookOutputRow };
type CollectionLine = { kind: 'collection'; key: string; at: string; run: CollectionRunRow };
type DashboardLine = { kind: 'dashboard'; key: string; at: string; snapshot: DashboardSnapshotRow };
type Line = RevisionLine | OldLine | ChartLine | WorkbookLine | CollectionLine | DashboardLine;
type TaskGroup = { task: TaskRow; lines: Line[] };

/**
 * 成果库 rows by task, then by revision. Groups, lines and each line's exports keep the order they first
 * appear in `rows`, which reads.ts already sorted newest first. Two tasks with one name stay two groups.
 */
function groupByTask(rows: GalleryRow[]): TaskGroup[] {
  const groups = new Map<string, TaskGroup>();
  const revisions = new Map<string, RevisionLine>();
  for (const entry of rows) {
    let group = groups.get(entry.task.id);
    if (!group) {
      group = { task: entry.task, lines: [] };
      groups.set(entry.task.id, group);
    }
    if (entry.type === 'deliverable') {
      group.lines.push({ kind: 'old', key: entry.key, at: entry.at, row: entry.row });
      continue;
    }
    if (entry.type === 'chart') {
      group.lines.push({ kind: 'chart', key: entry.key, at: entry.at, chart: entry.chart });
      continue;
    }
    if (entry.type === 'workbook') {
      group.lines.push({ kind: 'workbook', key: entry.key, at: entry.at, output: entry.output });
      continue;
    }
    if (entry.type === 'collection') {
      group.lines.push({ kind: 'collection', key: entry.key, at: entry.at, run: entry.run });
      continue;
    }
    if (entry.type === 'dashboard') {
      group.lines.push({ kind: 'dashboard', key: entry.key, at: entry.at, snapshot: entry.snapshot });
      continue;
    }
    const source = entry.type === 'draft' ? entry.draft : entry.exported;
    const id = `${entry.task.id}:${source.draft_id}`;
    let line = revisions.get(id);
    if (!line) {
      line = {
        kind: 'revision', key: `revision:${id}`, at: entry.at, draftId: source.draft_id, revision: source.revision,
        title: source.title, draft: null, state: source, exports: [],
      };
      revisions.set(id, line);
      group.lines.push(line);
    }
    if (entry.at > line.at) line.at = entry.at;
    if (entry.type === 'draft') {
      line.draft = entry.draft;
      line.state = entry.draft;
      line.revision = entry.draft.revision;
      line.title = entry.draft.title;
    } else {
      line.exports.push(entry.exported);
    }
  }
  return [...groups.values()];
}
export interface OpenDeliverable {
  task: TaskRow;
  row: DeliverableRow;
  /** `null` while the store is still being read. */
  text: string | null;
}

/**
 * Every result this machine has produced, grouped by task: each 文稿 revision
 * with the files exported from it, the 归档图, the 写回 Excel copies and the
 * 收缴率 runs, newest first; the old flow's versions fold at the bottom.
 * Choosing a row opens a side panel with what it is and where it came from.
 *
 * The list is an index, not the thing. It used to be only the index -- time,
 * task, kind, cause, size, digest, and no way to see what any of it said --
 * which is a log with better column headings. A deliverable is a document; the
 * screen that lists them has to open them, or the versions it is so careful to
 * keep are versions of nothing anyone can read.
 *
 * A task's name and period head its group once. Inside it a revision is one
 * row: its source draft, its state written once, and its exports as chips in
 * two rows, 管理版 and 审计版. An old-flow version keeps its own row with its
 * `cause` after the version name: a file name says a document changed;
 * `query-locked:followup-3` says which question changed it.
 *
 * 状态 shows only the review and publication state a draft already carries;
 * the old flow never had one, so its rows show a dash rather than a guess.
 */
export function Deliverables({
  rows,
  open,
  onOpen,
  onOpenDraft,
  onOpenExport,
  onOpenWorkbook,
  onPreview,
  previewing,
  onExport,
  busy,
  onBack,
  onDetail,
  onFile,
  onOpenTask,
  onSample,
}: {
  rows: GalleryRow[];
  open: OpenDeliverable | null;
  onOpen(task: TaskRow, row: DeliverableRow): void;
  /** Go to that task's 文稿 tab with this version selected. */
  onOpenDraft?(task: TaskRow, draft: AnalysisDraftRow): void;
  /** Hand the filed export to the default program. */
  onOpenExport?(task: TaskRow, exported: AnalysisExportRow): void;
  onOpenWorkbook(): void;
  /** Look at the open workbook in this window. Absent in a build with no viewer. */
  onPreview?(task: TaskRow, row: DeliverableRow): void;
  /** The digest whose preview is being put up, if any. */
  previewing?: string | null;
  /** Render the open document's window as a workbook, and open that. */
  onExport(task: TaskRow, windowId: string): void;
  /** The window currently being written, if any. */
  busy: string | null;
  onBack(): void;
  onDetail?: LibraryPanelActions['onDetail'];
  onFile?: LibraryPanelActions['onFile'];
  onOpenTask?: LibraryPanelActions['onOpenTask'];
  /** Make the practice task, for an empty library. */
  onSample?(): void;
}) {
  // Kept here, above the open version, so going back to the list finds the search, filters and selection as left.
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [selected, setSelected] = useState<string | null>(null);
  if (open) {
    return (
      <div className="fnd-stack" style={{ gap: 20 }}>
        <div>
          <button type="button" className="fnd-head__tab" onClick={onBack}>
            <ArrowLeft size={13} strokeWidth={1.5} aria-hidden />
            {' 返回成果库'}
          </button>
        </div>
        {/*
          * Which version this is, above the version itself. A brief read
          * without its cause and its digest is a document an operator cannot
          * place -- and placing it is the reason every version is kept.
          */}
        <dl className="fnd-doc__meta fnd-doc__stamp">
          <div className="fnd-doc__pair">
            <dt>任务</dt>
            <dd>{open.task.title}</dd>
          </div>
          <div className="fnd-doc__pair">
            <dt>类型</dt>
            <dd>{KIND_LABEL[open.row.kind]}</dd>
          </div>
          <div className="fnd-doc__pair">
            <dt>期间</dt>
            <dd>{open.task.period ? <span className="fnd-period">{formatPeriod(open.task.period)}</span> : '未设期间'}</dd>
          </div>
          <div className="fnd-doc__pair">
            <dt>成因</dt>
            <dd>{open.row.cause}</dd>
          </div>
          <div className="fnd-doc__pair">
            <dt>时间</dt>
            <dd>{when(open.row.at)}</dd>
          </div>
        </dl>
        {/* Session, size and digest place a version for whoever audits the store; they fold. */}
        <TechnicalInfo rows={[
          ['会话', open.row.session_id ?? '无会话'],
          ['大小', bytes(open.row.bytes)],
          ['摘要', open.row.sha256],
        ]} />
        {/*
          * The export lives here because this is the screen named 成果库 and
          * this is where an operator looking for one arrives. It was only on
          * the task screen before, below the input archive, which is where it
          * went unfound.
          */}
        {isWorkbook(open.row) ? null : (
          <div>
            <Button variant="outline"
              type="button"
              onClick={() => onExport(open.task, open.row.window_id)}
              disabled={busy === open.row.window_id}>
              <FileSpreadsheet size={13} strokeWidth={1.5} aria-hidden />
              {busy === open.row.window_id ? ' 正在导出…' : ' 导出 Excel'}
            </Button>
          </div>
        )}
        {/*
          * A workbook is looked at or handed over, not rendered by this app.
          * The look is the Univer viewer over a scratch copy, for the question
          * "what is in this version" without leaving the window; the handoff
          * is for sorting and pivoting, which belongs in the software the
          * operator already uses. Both are here because this is the screen an
          * operator looking for either one arrives at -- and it used to offer
          * only the handoff, which read as "there is no viewer".
          */}
        {isWorkbook(open.row) ? (
          <div className="fnd-stack" style={{ gap: 10 }}>
            <p className="fnd-muted">
              这一版是 Excel 工作簿，共四页：本期、结论、底稿、外部引用。
            </p>
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
              {onPreview ? (
                <Button variant="outline"
                  type="button"
                  onClick={() => onPreview(open.task, open.row)}
                  disabled={previewing === open.row.sha256}>
                  <Eye size={14} strokeWidth={1.5} aria-hidden />
                  {previewing === open.row.sha256 ? ' 正在装进预览…' : ' 在这里预览'}
                </Button>
              ) : null}
              <Button variant="outline" type="button" onClick={onOpenWorkbook}>
                <FileSpreadsheet size={14} strokeWidth={1.5} aria-hidden />
                {' 在表格软件里打开'}
                <ExternalLink size={12} strokeWidth={1.5} aria-hidden />
              </Button>
            </div>
          </div>
        ) : open.text === null ? (
          <Loading label="正在读取这一版…"><SkeletonRows rows={5} meta={false} /></Loading>
        ) : (
          <Reader source={open.text} />
        )}
      </div>
    );
  }

  return (
    <DeliverablesList rows={rows} filters={filters} onFilters={setFilters} selected={selected} onSelect={setSelected}
      onOpen={onOpen} onOpenExport={onOpenExport} onSample={onSample}
      actions={{ onDetail, onFile, onOpenTask, onOpenDraft }} />
  );
}


type KindFilter = 'all' | 'documents' | 'chart' | 'dashboard' | 'workbook' | 'collection';
type StatusFilter = 'all' | 'unreviewed' | 'reviewed' | 'accepted';
type ModeFilter = 'all' | 'management' | 'audit';
type Filters = { query: string; period: string; kind: KindFilter; status: StatusFilter; mode: ModeFilter };
const NO_FILTERS: Filters = { query: '', period: '', kind: 'all', status: 'all', mode: 'all' };

const KIND_FILTERS: [KindFilter, string][] = [
  ['all', '全部类型'], ['documents', '文稿与导出件'], ['chart', '归档图'], ['dashboard', '看板快照'], ['workbook', '写回 Excel'], ['collection', '收缴率计算'],
];
const STATUS_FILTERS: [StatusFilter, string][] = [['all', '全部状态'], ['unreviewed', '待复核'], ['reviewed', '已阅'], ['accepted', '经理认可']];
const MODE_FILTERS: [ModeFilter, string][] = [['all', '全部版本'], ['management', '管理版'], ['audit', '审计版']];
const CALIBER_SHORT: Record<CollectionRunRow['caliber']['status'], string> = { confirmed: '已确认口径', default: '默认口径', trial: '试算' };

/** A line passes the type, status and version filters. Status and version are a 文稿's; anything else drops out under them. */
function passes(line: Line, filters: Filters): boolean {
  if (line.kind === 'old') return false;
  if (filters.kind !== 'all' && (filters.kind === 'documents' ? line.kind !== 'revision' : line.kind !== filters.kind)) return false;
  if (filters.status !== 'all' || filters.mode !== 'all') {
    if (line.kind !== 'revision') return false;
    // The revision's own review state, in the words the 文稿 toolbar uses: 未阅 is 待复核 here, 已阅 and 经理认可 are their own.
    if (filters.status !== 'all' && line.state.review_status !== filters.status) return false;
    if (filters.mode !== 'all' && !line.exports.some((row) => row.content_mode === filters.mode)) return false;
  }
  return true;
}

/** Search reads the task's name, its period (as written and as shown) and each line's own title. */
function lineText(line: Line): string {
  return line.kind === 'revision' ? line.title : line.kind === 'chart' ? line.chart.label
    : line.kind === 'workbook' ? `${line.output.filename} ${line.output.dataset}` : line.kind === 'collection' ? `收缴率 ${line.run.as_of}`
      : line.kind === 'dashboard' ? `看板快照 经营看板 ${SNAPSHOT_FORMAT_WORDS[line.snapshot.format]} ${line.snapshot.cards.join(' ')}` : line.row.cause;
}
function taskText(task: TaskRow): string {
  return [task.title, task.period ?? '', task.period ? formatPeriod(task.period) : ''].join(' ');
}

/** What the side panel shows for a line; the old flow opens in its own view instead. */
function selectionOf(task: TaskRow, line: Line): LibrarySelection | null {
  if (line.kind === 'revision') {
    return { kind: 'revision', task, draftId: line.draftId, revision: line.revision, title: line.title, draft: line.draft, state: line.state, exports: line.exports };
  }
  if (line.kind === 'chart') return { kind: 'chart', task, chart: line.chart };
  if (line.kind === 'workbook') return { kind: 'workbook', task, output: line.output };
  if (line.kind === 'collection') return { kind: 'collection', task, run: line.run };
  if (line.kind === 'dashboard') return { kind: 'dashboard', task, snapshot: line.snapshot };
  return null;
}

/**
 * The list, its own component so its grouping is a hook of its own: Deliverables returns early while an
 * old-flow version is open. Filters and the selection are Deliverables', so they outlive that visit.
 *
 * In each task the newest 文稿 revision is the 当前版; earlier ones fold under 「更早的 N 版」, because the
 * question a CFO brings here is "which one is current", and the history is for the one asking after it.
 */
function DeliverablesList({
  rows, filters, onFilters, selected, onSelect, onOpen, onOpenExport, onSample, actions,
}: {
  rows: GalleryRow[];
  filters: Filters;
  onFilters(filters: Filters): void;
  selected: string | null;
  onSelect(key: string | null): void;
  onOpen(task: TaskRow, row: DeliverableRow): void;
  onOpenExport?(task: TaskRow, exported: AnalysisExportRow): void;
  onSample?(): void;
  actions: LibraryPanelActions;
}) {
  const groups = useMemo(() => groupByTask(rows), [rows]);
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());
  const periods = useMemo(() => [...new Set(groups.map((group) => group.task.period).filter((value): value is string => Boolean(value)))].sort().reverse(), [groups]);
  const needle = filters.query.trim().toLowerCase();
  const set = (patch: Partial<Filters>) => onFilters({ ...filters, ...patch });

  const shown = groups.flatMap(({ task, lines }) => {
    if (filters.period && task.period !== filters.period) return [];
    const taskHit = !needle || taskText(task).toLowerCase().includes(needle);
    const kept = lines.filter((line) => passes(line, filters) && (taskHit || lineText(line).toLowerCase().includes(needle)));
    if (!kept.length) return [];
    // 当前版 is the task's newest revision whatever the filters keep; when they leave it out, the revisions
    // they keep are listed as they are, not folded under a version that is not shown.
    const newest = lines.filter((line): line is RevisionLine => line.kind === 'revision').reduce<RevisionLine | null>(
      (best, line) => best && best.revision >= line.revision ? best : line, null);
    const revisions = kept.filter((line): line is RevisionLine => line.kind === 'revision').sort((a, b) => b.revision - a.revision);
    const others = kept.filter((line) => line.kind !== 'revision');
    const current = revisions[0] && revisions[0] === newest ? revisions[0] : null;
    return [{ task, current, older: current ? revisions.slice(1) : [], loose: current ? [] : revisions, others }];
  });
  const old = groups.flatMap(({ task, lines }) => lines
    .filter((line): line is OldLine => line.kind === 'old')
    .filter(() => !filters.period || task.period === filters.period)
    .filter(() => filters.kind === 'all' || filters.kind === 'documents')
    .filter(() => filters.status === 'all' && filters.mode === 'all')
    .filter((line) => !needle || taskText(task).toLowerCase().includes(needle) || line.row.cause.toLowerCase().includes(needle))
    .map((line) => ({ task, line })));

  const chosen = (() => {
    if (!selected) return null;
    for (const { task, lines } of groups) {
      const line = lines.find((item) => item.key === selected);
      if (line) return selectionOf(task, line);
    }
    return null;
  })();
  const filtered = needle || filters.period || filters.kind !== 'all' || filters.status !== 'all' || filters.mode !== 'all';
  const nothing = needle ? `没有和「${filters.query.trim()}」相符的成果` : '没有符合筛选条件的成果';

  if (rows.length === 0) {
    return (
      <div className="fnd-stack">
        <h1 className="fnd-library__title">成果库</h1>
        <Empty className="fnd-library__empty">
          <EmptyTitle>还没有成果</EmptyTitle>
          <EmptyDescription>
            出一次稿、保存一张归档图、写回一份 Excel 或算一次收缴率，都会存到这里，按任务归在一起，每一版都能追溯到它读的资料。
          </EmptyDescription>
          {onSample ? <Button type="button" variant="outline" onClick={onSample}>用示例练习</Button> : null}
        </Empty>
      </div>
    );
  }

  const row = (task: TaskRow, line: Line, nested = false, current = false) => (
    <LibraryRow key={line.key} task={task} line={line} nested={nested} current={current} selected={selected === line.key}
      onSelect={() => onSelect(selected === line.key ? null : line.key)} onOpenExport={onOpenExport} />
  );

  return (
    <div className="fnd-stack">
      <div className="fnd-library__head">
        <div>
          <h1 className="fnd-library__title">成果库</h1>
          <p className="fnd-muted fnd-library__lead">每个任务的当前版排在最前；选一行，在右边看它的检查、来源和导出件。</p>
        </div>
        <label className="fnd-library__search">
          <Search size={14} strokeWidth={1.5} aria-hidden />
          <Input type="search" aria-label="搜索任务、标题或期间" placeholder="搜索任务、标题或期间" value={filters.query}
            onChange={(event) => set({ query: event.target.value })} />
        </label>
      </div>
      <div className="fnd-library__filters" role="group" aria-label="筛选">
        <NativeSelect aria-label="期间" value={filters.period} onChange={(event) => set({ period: event.target.value })}>
          <option value="">全部期间</option>
          {periods.map((period) => <option key={period} value={period}>{formatPeriod(period)}</option>)}
        </NativeSelect>
        <NativeSelect aria-label="类型" value={filters.kind} onChange={(event) => set({ kind: event.target.value as KindFilter })}>
          {KIND_FILTERS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </NativeSelect>
        <NativeSelect aria-label="文稿状态" value={filters.status} onChange={(event) => set({ status: event.target.value as StatusFilter })}>
          {STATUS_FILTERS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </NativeSelect>
        <NativeSelect aria-label="导出版本" value={filters.mode} onChange={(event) => set({ mode: event.target.value as ModeFilter })}>
          {MODE_FILTERS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </NativeSelect>
        {filtered ? <Button type="button" variant="ghost" size="sm" onClick={() => onFilters(NO_FILTERS)}>清除筛选</Button> : null}
      </div>
      {/* Present from the start so a change is announced, not inserted with its words. */}
      <span className="sr-only" role="status">
        {filtered ? shown.length ? `找到 ${shown.length} 个任务` : old.length ? `旧版流程里有 ${old.length} 个相符的版本` : nothing : ''}
      </span>
      <div className={chosen ? 'fnd-library__layout fnd-library__layout--panel' : 'fnd-library__layout'}>
        <div className="fnd-stack fnd-library__main">
          {shown.length === 0 ? (
            // Only old-flow versions match: they are in their fold below, open so they are not missed.
            old.length ? null : <p className="fnd-muted">{nothing}</p>
          ) : (
            <div className="fnd-tablewrap" tabIndex={0} role="region" aria-label="成果库">
              <table className="fnd-table fnd-library__table">
                <caption className="sr-only">按任务分组的成果：文稿版本与导出件、归档图、写回 Excel 和收缴率计算</caption>
                <thead>
                  <tr>
                    <th scope="col">成果</th>
                    <th scope="col">状态</th>
                    <th scope="col">导出件</th>
                    <th scope="col">最近更新</th>
                  </tr>
                </thead>
                {shown.map(({ task, current, older, loose, others }) => {
                  const open = expanded.has(task.id) || older.some((line) => line.key === selected);
                  return (
                    <tbody key={task.id}>
                      <tr>
                        <th scope="rowgroup" colSpan={4}>
                          <span>{task.title}</span>
                          {task.period ? <span className="fnd-muted"> · <span className="fnd-period">{formatPeriod(task.period)}</span></span> : null}
                          {task.lifecycle_status === 'archived' ? <span className="fnd-library__tag">已归档</span> : null}
                        </th>
                      </tr>
                      {current ? row(task, current, false, true) : null}
                      {loose.map((line) => row(task, line))}
                      {older.length ? (
                        <tr className="fnd-library__older">
                          <td colSpan={4}>
                            <button type="button" className="fnd-linkish" aria-expanded={open}
                              onClick={() => setExpanded((held) => {
                                const next = new Set(held);
                                if (next.has(task.id)) next.delete(task.id); else next.add(task.id);
                                return next;
                              })}>
                              {open ? '收起更早的版本' : `更早的 ${older.length} 版`}
                              <span className="sr-only">{`（${task.title}）`}</span>
                            </button>
                          </td>
                        </tr>
                      ) : null}
                      {open ? older.map((line) => row(task, line, true)) : null}
                      {others.map((line) => row(task, line))}
                    </tbody>
                  );
                })}
              </table>
            </div>
          )}
          {old.length ? (
            <details className="analysis-details fnd-library__old" open={shown.length === 0 || undefined}>
              <DisclosureSummary>旧版流程的版本 · {old.length}</DisclosureSummary>
              <p className="fnd-muted">改版前「出稿」流程留下的结论稿、底稿和表格，只读保存。</p>
              <div className="fnd-tablewrap" tabIndex={0} role="region" aria-label="旧版流程的版本">
                <table className="fnd-table">
                  <thead><tr><th scope="col">任务</th><th scope="col">版本</th><th scope="col">时间</th></tr></thead>
                  <tbody>
                    {old.map(({ task, line }) => (
                      <tr key={line.key} className="fnd-table__open">
                        <td>{task.title}{task.period ? <span className="fnd-muted"> · <span className="fnd-period">{formatPeriod(task.period)}</span></span> : null}</td>
                        <td>
                          {/* The name starts with what it shows and carries the task, so a screen reader hears which version. */}
                          <button type="button" className="fnd-linkish" onClick={() => onOpen(task, line.row)}>
                            {isWorkbook(line.row) ? <FileSpreadsheet size={13} strokeWidth={1.5} aria-hidden /> : <FileText size={13} strokeWidth={1.5} aria-hidden />}
                            {`${isWorkbook(line.row) ? '表格' : KIND_LABEL[line.row.kind]} 第 ${line.row.seq} 版`}
                            <span className="sr-only">{`（打开 ${task.title} 的${KIND_LABEL[line.row.kind]} 第 ${line.row.seq} 版）`}</span>
                          </button>
                          <span className="fnd-muted"><span aria-hidden> · </span><span>{line.row.cause}</span></span>
                        </td>
                        <td className="fnd-library__when">{when(line.at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          ) : null}
        </div>
        {chosen ? <LibraryPanel key={selected} selection={chosen} actions={actions} onClose={() => onSelect(null)} /> : null}
      </div>
    </div>
  );
}

/**
 * One line of the library. Its name is a button that opens the side panel; a 文稿 revision also keeps its
 * exports as chips by version kind, each opening the file. Every button's name starts with what it shows;
 * the task and the time follow for a screen reader only.
 */
function LibraryRow({ task, line, nested, current, selected, onSelect, onOpenExport }: {
  task: TaskRow;
  line: Line;
  nested: boolean;
  current: boolean;
  selected: boolean;
  onSelect(): void;
  onOpenExport?(task: TaskRow, exported: AnalysisExportRow): void;
}) {
  if (line.kind === 'old') return null;
  const [icon, name, state] = line.kind === 'revision'
    ? [<FilePen size={13} strokeWidth={1.5} aria-hidden />, `${line.title} · 修订 ${line.revision}`, draftStateText(line.state)]
    : line.kind === 'chart'
      ? [<BarChart3 size={13} strokeWidth={1.5} aria-hidden />, `归档图 · ${line.chart.label || '未命名'}`, '已归档']
      : line.kind === 'workbook'
        ? [<FileSpreadsheet size={13} strokeWidth={1.5} aria-hidden />, `写回 Excel · ${line.output.dataset}`, `写入 ${line.output.applied} 格`]
        : line.kind === 'dashboard'
          ? [<LayoutDashboard size={13} strokeWidth={1.5} aria-hidden />, `看板快照 · ${SNAPSHOT_FORMAT_WORDS[line.snapshot.format]}`, `${line.snapshot.cards.length} 张已认可的卡`]
          : [<Percent size={13} strokeWidth={1.5} aria-hidden />, `收缴率计算 · 截至 ${line.run.as_of}`, CALIBER_SHORT[line.run.caliber.status]];
  return (
    <tr className={nested ? 'fnd-library__row fnd-library__row--older' : 'fnd-library__row'} data-selected={selected || undefined}>
      <td>
        <button type="button" className="fnd-linkish" aria-pressed={selected} onClick={onSelect}>
          {icon}
          {name}
          <span className="sr-only">{`（${task.title}，${when(line.at)}，查看详情）`}</span>
        </button>
        {current ? <span className="fnd-library__current">当前版</span> : null}
      </td>
      <td className="fnd-library__state">{state}</td>
      <td>{line.kind === 'revision' ? <ExportChips task={task} line={line} onOpenExport={onOpenExport} /> : '—'}</td>
      <td className="fnd-library__when">{when(line.at)}</td>
    </tr>
  );
}

function ExportChips({ task, line, onOpenExport }: {
  task: TaskRow;
  line: RevisionLine;
  onOpenExport?(task: TaskRow, exported: AnalysisExportRow): void;
}) {
  const marker = line.exports.find((row) => row.review_marker)?.review_marker ?? '';
  const byMode = MODE_ORDER
    .map((mode) => ({
      mode,
      files: line.exports
        .filter((row) => modeRow(row.content_mode) === mode)
        .sort((a, b) => FORMAT_ORDER.indexOf(a.format) - FORMAT_ORDER.indexOf(b.format)),
    }))
    .filter(({ files }) => files.length);
  if (!byMode.length) return <>—</>;
  return (
    <>
      <div className="fnd-library__exports">
        {byMode.map(({ mode, files }) => {
          const stamps = exportStamps(files);
          return (
            <Fragment key={mode}>
              <span className="fnd-library__mode">{ROW_LABEL[mode]}</span>
              <div className="fnd-library__chips">
                {files.map((exported) => {
                  const label = FORMAT_LABEL[exported.format];
                  const stamp = stamps.get(exported.export_id);
                  const kind = exported.content_mode ? MODE_LABEL[exported.content_mode] ?? exported.content_mode : '';
                  const detail = [`修订 ${exported.revision}`, kind, when(exported.created_at)].filter(Boolean).join(' · ');
                  const flagged = exported.review_marker ? `，文件带「${exported.review_marker}」标记` : '';
                  return (
                    <Button
                      key={exported.export_id}
                      variant="outline"
                      size="chip"
                      type="button"
                      onClick={() => onOpenExport?.(task, exported)}
                      disabled={!onOpenExport}
                    >
                      {stamp ? `${label} · ${stamp}` : label}
                      {/* The space is its own text node: a name trims the edges of each element's text. */}
                      {' '}
                      <span className="sr-only">{`导出件（${detail}），${task.title}，用默认程序打开${flagged}`}</span>
                    </Button>
                  );
                })}
              </div>
            </Fragment>
          );
        })}
      </div>
      {marker ? <p className="fnd-library__marker">导出件带「{marker}」标记</p> : null}
    </>
  );
}
