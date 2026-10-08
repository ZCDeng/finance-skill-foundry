import { Fragment, useMemo, useState } from 'react';
import { ArrowLeft, Eye, FilePen, FileSpreadsheet, FileText, ExternalLink, Search } from 'lucide-react';

import { Reader } from '../components/Reader.js';
import { Button } from '../components/ui/button.js';
import { Input } from '../components/ui/input.js';
import { formatPeriod } from '../lib/period.js';
import {
  type AnalysisDraftRow,
  type AnalysisExportRow,
  type DeliverableRow,
  type ExportFormat,
  type GalleryRow,
  type TaskRow,
  bytes,
  isWorkbook,
  when,
} from '../bridge.js';
import { draftStateText } from './analysis/presentation.js';
import { TechnicalInfo } from './analysis/TechnicalInfo.js';
import { Empty, EmptyDescription } from '../components/ui/empty.js';
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
type Line = RevisionLine | OldLine;
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
 * Every version this machine has produced, grouped by task: the old flow's
 * versions, each 文稿 revision with the files exported from it, newest first.
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
}) {
  // Kept here, above the open version, so going back to the list finds the search as it was left.
  const [query, setQuery] = useState('');
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
    <DeliverablesList rows={rows} query={query} onQuery={setQuery} onOpen={onOpen} onOpenDraft={onOpenDraft} onOpenExport={onOpenExport} />
  );
}

/**
 * The list, its own component so its grouping is a hook of its own: Deliverables
 * returns early while a version is open. The search text is Deliverables', so it
 * outlives a visit to one version.
 */
function DeliverablesList({
  rows,
  query,
  onQuery,
  onOpen,
  onOpenDraft,
  onOpenExport,
}: {
  rows: GalleryRow[];
  query: string;
  onQuery(query: string): void;
  onOpen(task: TaskRow, row: DeliverableRow): void;
  onOpenDraft?(task: TaskRow, draft: AnalysisDraftRow): void;
  onOpenExport?(task: TaskRow, exported: AnalysisExportRow): void;
}) {
  const groups = useMemo(() => groupByTask(rows), [rows]);
  const needle = query.trim();
  const shown = needle
    ? groups.filter((group) => group.task.title.toLowerCase().includes(needle.toLowerCase()))
    : groups;
  const nothing = `没有名称包含「${needle}」的任务`;

  if (rows.length === 0) {
    return (
      <div className="fnd-stack">
        <h1 className="fnd-library__title">成果库</h1>
        <Empty><EmptyDescription>还没有产出物。出一次稿就会有第一版。</EmptyDescription></Empty>
      </div>
    );
  }

  return (
    <div className="fnd-stack">
      <div className="fnd-library__head">
        <h1 className="fnd-library__title">成果库</h1>
        <label className="fnd-library__search">
          <Search size={14} strokeWidth={1.5} aria-hidden />
          <Input type="search" aria-label="按任务名搜索" placeholder="按任务名搜索" value={query}
            onChange={(event) => onQuery(event.target.value)} />
        </label>
      </div>
      {/* Present from the start so a change is announced, not inserted with its words. */}
      <span className="sr-only" role="status">
        {needle ? shown.length ? `找到 ${shown.length} 个任务` : nothing : ''}
      </span>
      {shown.length === 0 ? (
        <p className="fnd-muted">{nothing}</p>
      ) : (
        <div className="fnd-tablewrap" tabIndex={0} role="region" aria-label="成果库">
          <table className="fnd-table">
            <caption className="sr-only">按任务分组的文稿版本与导出件</caption>
            <thead>
              <tr>
                <th scope="col">来源文稿</th>
                <th scope="col">状态</th>
                <th scope="col">导出件</th>
                <th scope="col">最近更新</th>
              </tr>
            </thead>
            {shown.map(({ task, lines }) => (
              <tbody key={task.id}>
                <tr>
                  <th scope="rowgroup" colSpan={4}>
                    <span>{task.title}</span>
                    {task.period ? <span className="fnd-muted"> · <span className="fnd-period">{formatPeriod(task.period)}</span></span> : null}
                  </th>
                </tr>
                {lines.map((line) => line.kind === 'revision' ? (
                  <RevisionRow key={line.key} task={task} line={line} onOpenDraft={onOpenDraft} onOpenExport={onOpenExport} />
                ) : (
                  <tr key={line.key} className="fnd-table__open">
                    <td>
                      {/*
                        * The button's name starts with what it shows and carries the
                        * task, so a screen reader is told which version it is about
                        * to open rather than hearing "打开" seven times.
                        */}
                      <button
                        type="button"
                        className="fnd-linkish"
                        onClick={() => onOpen(task, line.row)}
                      >
                        {isWorkbook(line.row) ? (
                          <FileSpreadsheet size={13} strokeWidth={1.5} aria-hidden />
                        ) : (
                          <FileText size={13} strokeWidth={1.5} aria-hidden />
                        )}
                        {`${isWorkbook(line.row) ? '表格' : KIND_LABEL[line.row.kind]} 第 ${line.row.seq} 版`}
                        <span className="sr-only">{`（打开 ${task.title} 的${KIND_LABEL[line.row.kind]} 第 ${line.row.seq} 版）`}</span>
                      </button>
                      <span className="fnd-muted"><span aria-hidden> · </span><span>{line.row.cause}</span></span>
                    </td>
                    {/* The old flow has no review or publication record; nothing is invented for it. */}
                    <td>—</td>
                    <td>—</td>
                    <td className="fnd-library__when">{when(line.at)}</td>
                  </tr>
                ))}
              </tbody>
            ))}
          </table>
        </div>
      )}
    </div>
  );
}

/**
 * One 文稿 revision: its source draft, its state once, and its exports as chips by version kind. Every
 * button's name starts with what it shows; the task, the revision and the file's own time follow for a
 * screen reader only.
 */
function RevisionRow({ task, line, onOpenDraft, onOpenExport }: {
  task: TaskRow;
  line: RevisionLine;
  onOpenDraft?(task: TaskRow, draft: AnalysisDraftRow): void;
  onOpenExport?(task: TaskRow, exported: AnalysisExportRow): void;
}) {
  const { draft } = line;
  const name = `${line.title} · 修订 ${line.revision}`;
  const marker = line.exports.find((row) => row.review_marker)?.review_marker ?? '';
  const byMode = MODE_ORDER
    .map((mode) => ({
      mode,
      files: line.exports
        .filter((row) => modeRow(row.content_mode) === mode)
        .sort((a, b) => FORMAT_ORDER.indexOf(a.format) - FORMAT_ORDER.indexOf(b.format)),
    }))
    .filter(({ files }) => files.length);
  return (
    <tr>
      <td>
        {draft ? (
          <button
            type="button"
            className="fnd-linkish"
            onClick={() => onOpenDraft?.(task, draft)}
            disabled={!onOpenDraft}
          >
            <FilePen size={13} strokeWidth={1.5} aria-hidden />
            {name}
            <span className="sr-only">{`（${task.title} 的文稿 修订 ${line.revision}，${when(draft.created_at)}）`}</span>
          </button>
        ) : name}
      </td>
      <td className="fnd-library__state">{draftStateText(line.state)}</td>
      <td>
        {byMode.length ? (
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
        ) : '—'}
        {marker ? <p className="fnd-library__marker">导出件带「{marker}」标记</p> : null}
      </td>
      <td className="fnd-library__when">{when(line.at)}</td>
    </tr>
  );
}
