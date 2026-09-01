import { ArrowLeft, FileSpreadsheet, FileText, ExternalLink } from 'lucide-react';

import { Reader } from '../components/Reader.js';
import {
  type DeliverableRow,
  type TaskRow,
  bytes,
  isWorkbook,
  shortSha,
  when,
} from '../bridge.js';

const KIND_LABEL: Record<DeliverableRow['kind'], string> = {
  brief: '结论稿',
  workpaper: '底稿',
  export: '导出件',
};

export interface OpenDeliverable {
  task: TaskRow;
  row: DeliverableRow;
  /** `null` while the store is still being read. */
  text: string | null;
}

/**
 * Every version this machine has produced, newest first, across all tasks.
 *
 * The list is an index, not the thing. It used to be only the index -- time,
 * task, kind, cause, size, digest, and no way to see what any of it said --
 * which is a log with better column headings. A deliverable is a document; the
 * screen that lists them has to open them, or the versions it is so careful to
 * keep are versions of nothing anyone can read.
 *
 * `cause` is still the column that earns the screen. A file name says a
 * document changed; `query-locked:followup-3` says which question changed it.
 */
export function Deliverables({
  rows,
  open,
  onOpen,
  onOpenWorkbook,
  onExport,
  busy,
  onBack,
}: {
  rows: { task: TaskRow; row: DeliverableRow }[];
  open: OpenDeliverable | null;
  onOpen(task: TaskRow, row: DeliverableRow): void;
  onOpenWorkbook(): void;
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
            <dt>成因</dt>
            <dd>{open.row.cause}</dd>
          </div>
          <div className="fnd-doc__pair">
            <dt>会话</dt>
            <dd>{open.row.session_id ?? '无会话'}</dd>
          </div>
          <div className="fnd-doc__pair">
            <dt>时间</dt>
            <dd>{when(open.row.at)}</dd>
          </div>
          <div className="fnd-doc__pair">
            <dt>大小</dt>
            <dd>{bytes(open.row.bytes)}</dd>
          </div>
          <div className="fnd-doc__pair">
            <dt>摘要</dt>
            <dd className="fnd-sha" title={open.row.sha256}>
              {shortSha(open.row.sha256)}
            </dd>
          </div>
        </dl>
        {/*
          * The export lives here because this is the screen named 交付物 and
          * this is where an operator looking for one arrives. It was only on
          * the task screen before, below the input archive, which is where it
          * went unfound.
          */}
        {isWorkbook(open.row) ? null : (
          <div>
            <button
              type="button"
              className="fnd-button"
              onClick={() => onExport(open.task, open.row.window_id)}
              disabled={busy === open.row.window_id}
            >
              <FileSpreadsheet size={13} strokeWidth={1.5} aria-hidden />
              {busy === open.row.window_id ? ' 正在从锁库写…' : ' 把这个窗口出成表格'}
            </button>
          </div>
        )}
        {/*
          * A workbook is handed over rather than rendered. It was written as a
          * spreadsheet so it could be sorted and pivoted in the software the
          * operator already uses; drawing it again in this window would be a
          * worse copy of that software.
          */}
        {isWorkbook(open.row) ? (
          <div className="fnd-stack" style={{ gap: 10 }}>
            <p className="fnd-muted">
              这一版是表格。四页：本期（窗口、锁哈希、标签怎么读）、结论、底稿、外部引用。
            </p>
            <div>
              <button type="button" className="fnd-button" onClick={onOpenWorkbook}>
                <FileSpreadsheet size={14} strokeWidth={1.5} aria-hidden />
                {' 在表格软件里打开'}
                <ExternalLink size={12} strokeWidth={1.5} aria-hidden />
              </button>
            </div>
          </div>
        ) : open.text === null ? (
          <p className="fnd-muted">正在从锁库读出这一版…</p>
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
            <th>类型</th>
            <th>成因</th>
            <th>会话</th>
            <th className="fnd-num">大小</th>
            <th>摘要</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ task, row }) => (
            <tr key={`${task.id}-${row.seq}`} className="fnd-table__open">
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
                  aria-label={`打开 ${task.title} 的${KIND_LABEL[row.kind]} ${shortSha(row.sha256)}`}
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
              <td>{isWorkbook(row) ? '表格' : KIND_LABEL[row.kind]}</td>
              <td>{row.cause}</td>
              <td className="fnd-muted">{row.session_id ?? '无会话'}</td>
              <td className="fnd-num">{bytes(row.bytes)}</td>
              <td className="fnd-sha">{shortSha(row.sha256)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
