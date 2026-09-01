import { ArrowLeft, FileText } from 'lucide-react';

import { Reader } from '../components/Reader.js';
import { type DeliverableRow, type TaskRow, bytes, shortSha, when } from '../bridge.js';

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
  onBack,
}: {
  rows: { task: TaskRow; row: DeliverableRow }[];
  open: OpenDeliverable | null;
  onOpen(task: TaskRow, row: DeliverableRow): void;
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
        {open.text === null ? (
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
                  <FileText size={13} strokeWidth={1.5} aria-hidden />
                  {when(row.at)}
                </button>
              </td>
              <td>{task.title}</td>
              <td>{KIND_LABEL[row.kind]}</td>
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
