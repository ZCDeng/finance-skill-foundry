import { type DeliverableRow, type TaskRow, bytes, shortSha, when } from '../bridge.js';

const KIND_LABEL: Record<DeliverableRow['kind'], string> = {
  brief: '结论稿',
  workpaper: '底稿',
  export: '导出件',
};

/**
 * Every version this machine has produced, newest first, across all tasks.
 *
 * `cause` is the column that earns the screen. A file name says a document
 * changed; `query-locked:followup-3` says which question changed it.
 */
export function Deliverables({ rows }: { rows: { task: TaskRow; row: DeliverableRow }[] }) {
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
            <tr key={`${task.id}-${row.seq}`}>
              <td>{when(row.at)}</td>
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
