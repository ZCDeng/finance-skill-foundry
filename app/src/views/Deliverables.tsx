import { ArrowLeft, Eye, FileOutput, FilePen, FileSpreadsheet, FileText, ExternalLink } from 'lucide-react';

import { Reader } from '../components/Reader.js';
import { Button } from '../components/ui/button.js';
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


/**
 * An export's state is its source revision's. Unless that revision is accepted
 * and archived, the file carries the review stamp, so the list says so first.
 */
function ExportState({ exported }: { exported: AnalysisExportRow }) {
  if (!exported.review_marker) return <>{draftStateText(exported)}</>;
  return (
    <>
      {exported.review_marker}
      <span className="fnd-muted">（{draftStateText(exported)}）</span>
    </>
  );
}

export interface OpenDeliverable {
  task: TaskRow;
  row: DeliverableRow;
  /** `null` while the store is still being read. */
  text: string | null;
}

/**
 * Every version this machine has produced, newest first, across all tasks: the
 * old flow's versions, the newest draft of each revision chain, and every filed
 * export.
 *
 * The list is an index, not the thing. It used to be only the index -- time,
 * task, kind, cause, size, digest, and no way to see what any of it said --
 * which is a log with better column headings. A deliverable is a document; the
 * screen that lists them has to open them, or the versions it is so careful to
 * keep are versions of nothing anyone can read.
 *
 * `cause` is still the column that earns the screen. A file name says a
 * document changed; `query-locked:followup-3` says which question changed it.
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
  if (open) {
    return (
      <div className="fnd-stack" style={{ gap: 20 }}>
        <div>
          <button type="button" className="fnd-head__tab" onClick={onBack}>
            <ArrowLeft size={13} strokeWidth={1.5} aria-hidden />
            {' 交付物'}
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
            <dd>{open.task.period ?? '未设期间'}</dd>
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
          * The export lives here because this is the screen named 交付物 and
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
          <p className="fnd-muted">正在读取这一版…</p>
        ) : (
          <Reader source={open.text} />
        )}
      </div>
    );
  }

  if (rows.length === 0) {
    return <p className="fnd-empty">还没有产出物。出一次稿就会有第一版。</p>;
  }

  return (
    <div className="fnd-tablewrap">
      <table className="fnd-table">
        <thead>
          <tr>
            <th>时间</th>
            <th>任务</th>
            <th>期间</th>
            <th>类型</th>
            <th>状态</th>
            <th>成因</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((entry) => {
            const { task } = entry;
            if (entry.type === 'draft') {
              const { draft } = entry;
              return (
                <tr key={entry.key} className="fnd-table__open">
                  <td>
                    <button
                      type="button"
                      className="fnd-linkish"
                      onClick={() => onOpenDraft?.(task, draft)}
                      disabled={!onOpenDraft}
                      aria-label={`打开 ${task.title} 的文稿 修订 ${draft.revision}`}
                    >
                      <FilePen size={13} strokeWidth={1.5} aria-hidden />
                      {when(entry.at)}
                    </button>
                  </td>
                  <td>{task.title}</td>
                  <td>{task.period ?? '—'}</td>
                  <td>分析文稿</td>
                  <td>{draftStateText(draft)}</td>
                  <td>{`${draft.title} · 修订 ${draft.revision}`}</td>
                </tr>
              );
            }
            if (entry.type === 'export') {
              const { exported } = entry;
              const kind = `${FORMAT_LABEL[exported.format]} 导出件`;
              const mode = exported.content_mode ? ` · ${MODE_LABEL[exported.content_mode] ?? exported.content_mode}` : '';
              return (
                <tr key={entry.key} className="fnd-table__open">
                  <td>
                    <button
                      type="button"
                      className="fnd-linkish"
                      onClick={() => onOpenExport?.(task, exported)}
                      disabled={!onOpenExport}
                      aria-label={`用默认程序打开 ${task.title} 的${kind}（修订 ${exported.revision}）`}
                    >
                      {exported.format === 'xlsx' ? (
                        <FileSpreadsheet size={13} strokeWidth={1.5} aria-hidden />
                      ) : (
                        <FileOutput size={13} strokeWidth={1.5} aria-hidden />
                      )}
                      {when(entry.at)}
                    </button>
                  </td>
                  <td>{task.title}</td>
                  <td>{task.period ?? '—'}</td>
                  <td>{kind}</td>
                  <td><ExportState exported={exported} /></td>
                  <td>{`${exported.title} · 修订 ${exported.revision}${mode}`}</td>
                </tr>
              );
            }
            const { row } = entry;
            return (
              <tr key={entry.key} className="fnd-table__open">
                <td>
                  {/*
                    * The button carries the whole row's name, so a pointer has
                    * the row to aim at and a screen reader is told which version
                    * it is about to open rather than hearing "打开" seven times.
                    */}
                  <button
                    type="button"
                    className="fnd-linkish"
                    onClick={() => onOpen(task, row)}
                    aria-label={`打开 ${task.title} 的${KIND_LABEL[row.kind]} 第 ${row.seq} 版`}
                  >
                    {isWorkbook(row) ? (
                      <FileSpreadsheet size={13} strokeWidth={1.5} aria-hidden />
                    ) : (
                      <FileText size={13} strokeWidth={1.5} aria-hidden />
                    )}
                    {when(row.at)}
                  </button>
                </td>
                <td>{task.title}</td>
                <td>{task.period ?? '—'}</td>
                <td>{isWorkbook(row) ? '表格' : KIND_LABEL[row.kind]}</td>
                {/* The old flow has no review or publication record; nothing is invented for it. */}
                <td>—</td>
                <td>{row.cause}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
