import { useState } from 'react';
import { Reader } from '../components/Reader.js';
import {
  ArrowLeft,
  Eye,
  FileSpreadsheet,
  FileText,
  HardDriveDownload,
  MessageSquareQuote,
} from 'lucide-react';

import {
  type DeliverableRow,
  type TaskDetail as Detail,
  type WindowRow,
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

const ROLE_LABEL: Record<Detail['sessions'][number]['role'], string> = {
  analysis: '财务分析',
  author: '写方法',
  period: '期间',
  followup: '追问',
};

const REASON_LABEL: Record<WindowRow['reason'], string> = {
  initial: '首次导入',
  reimport: '补数据 · 后继窗口',
};

function Inputs({ window: row }: { window: WindowRow }) {
  if (row.inputs.length === 0) {
    return <p className="fnd-muted">这个窗口还没有导入过。</p>;
  }
  return (
    <div className="fnd-tablewrap">
      <table className="fnd-table">
        <thead>
          <tr>
            <th>表</th>
            <th>归档副本</th>
            <th className="fnd-num">大小</th>
            <th>导入时的来源</th>
          </tr>
        </thead>
        <tbody>
          {row.inputs.map((input) => (
            <tr key={input.role}>
              <td>
                {input.role}
                {input.derived_from ? <span className="fnd-muted">{` 由 ${input.derived_from} 推出`}</span> : null}
              </td>
              <td className="fnd-sha">{input.archived}</td>
              <td className="fnd-num">{bytes(input.bytes)}</td>
              {/*
                * The operator's own path, kept for recognition only. Nothing
                * reads it after the import: the window parses and locks against
                * its own copy, so this column can name a file that is long gone
                * and the window still answers for itself.
                */}
              <td className="fnd-muted">{input.origin_path ?? ''}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * One task: its chain of windows, what each was built from, every version it
 * produced, and the conversations that touched it.
 */
export function TaskDetail({
  detail,
  onBack,
  onRead,
  onExport,
  onOpenWorkbook,
  onPreview,
  previewing,
  busy,
  reading,
}: {
  detail: Detail;
  onBack(): void;
  onRead(sha: string): void;
  /** Render this window as a workbook and file it as a version. */
  onExport(windowId: string): void;
  /** Hand an already-filed workbook to the operator's spreadsheet software. */
  onOpenWorkbook(sha: string, ext: string): void;
  /** Look at an already-filed workbook in this window. Absent in a build with no viewer. */
  onPreview?(sha: string, ext: string): void;
  /** The digest whose preview is being put up, if any. */
  previewing?: string | null;
  /** The window id currently being rendered, if any. */
  busy: string | null;
  reading: { sha: string; text: string } | null;
}) {
  const [openWindow, setOpenWindow] = useState<string | null>(detail.windows[0]?.window_id ?? null);
  const versionsFor = (windowId: string) =>
    detail.deliverables.filter((row) => row.window_id === windowId);

  return (
    <div className="fnd-stack" style={{ gap: 28 }}>
      <div>
        <button type="button" className="fnd-head__tab" onClick={onBack}>
          <ArrowLeft size={13} strokeWidth={1.5} aria-hidden />
          {' 任务'}
        </button>
        <h2 className="fnd-lede" style={{ marginTop: 12 }}>
          {detail.task.title}
        </h2>
        <p className="fnd-muted">
          {[detail.task.period, `建于 ${when(detail.task.created_at)}`].filter(Boolean).join(' · ')}
        </p>
      </div>

      <section>
        <p className="fnd-eyebrow">窗口链</p>
        <ol className="fnd-time" style={{ marginTop: 14 }}>
          {detail.windows.map((row) => (
            <li key={row.window_id} className="fnd-time__item">
              <button
                type="button"
                className="fnd-card"
                onClick={() => setOpenWindow(row.window_id === openWindow ? null : row.window_id)}
              >
                <span className="fnd-row">
                  <span className="fnd-title">{REASON_LABEL[row.reason]}</span>
                  <span className="fnd-muted">{row.state}</span>
                  <span className="fnd-muted">{when(row.at)}</span>
                  <span className="fnd-sha">{shortSha(row.window_id)}</span>
                </span>
              </button>
              {openWindow === row.window_id ? (
                <div className="fnd-panel" style={{ marginTop: 10 }}>
                  {/*
                    * First inside the panel, and that placement is the fix for
                    * a measured problem rather than a preference. It used to
                    * sit under 输入归档, which on a real close is twenty-odd
                    * rows each carrying a full source path -- 1344px below the
                    * fold on the task this was found on. An action nobody
                    * scrolls to is an action that does not exist.
                    */}
                  <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                    <button
                      type="button"
                      className="fnd-button"
                      onClick={() => onExport(row.window_id)}
                      disabled={busy === row.window_id}
                    >
                      <FileSpreadsheet size={13} strokeWidth={1.5} aria-hidden />
                      {busy === row.window_id ? ' 正在从锁库写…' : ' 出一份表格'}
                    </button>
                  </div>
                  <p className="fnd-eyebrow" style={{ marginTop: 14 }}>
                    <HardDriveDownload size={12} strokeWidth={1.5} aria-hidden />
                    {' 输入归档'}
                  </p>
                  <div style={{ marginTop: 10 }}>
                    <Inputs window={row} />
                  </div>
                  <p className="fnd-eyebrow" style={{ marginTop: 20 }}>
                    <FileText size={12} strokeWidth={1.5} aria-hidden />
                    {' 交付物版本'}
                  </p>
                  <div className="fnd-tablewrap" style={{ marginTop: 10 }}>
                    <table className="fnd-table">
                      <thead>
                        <tr>
                          <th>#</th>
                          <th>类型</th>
                          <th>成因</th>
                          <th>会话</th>
                          <th>时间</th>
                          <th className="fnd-num">大小</th>
                          <th>摘要</th>
                        </tr>
                      </thead>
                      <tbody>
                        {versionsFor(row.window_id).map((version) => (
                          <tr key={version.seq}>
                            <td className="fnd-num">{version.seq}</td>
                            <td>{isWorkbook(version) ? '表格' : KIND_LABEL[version.kind]}</td>
                            <td>{version.cause}</td>
                            <td className="fnd-muted">{version.session_id ?? '无会话'}</td>
                            <td>{when(version.at)}</td>
                            <td className="fnd-num">{bytes(version.bytes)}</td>
                            <td>
                              <button
                                type="button"
                                className="fnd-head__tab"
                                onClick={() =>
                                  isWorkbook(version)
                                    ? onOpenWorkbook(version.sha256, version.ext ?? '.xlsx')
                                    : onRead(version.sha256)
                                }
                                // Twelve hex characters is an identity, not a
                                // label. The same pattern as the gallery: say
                                // which version, and say where it opens.
                                aria-label={
                                  isWorkbook(version)
                                    ? `在表格软件里打开 ${shortSha(version.sha256)}`
                                    : `打开 ${shortSha(version.sha256)}`
                                }
                              >
                                {shortSha(version.sha256)}
                              </button>
                              {/*
                                * The look, beside the handoff. A workbook row
                                * with one control that leaves the window read
                                * as a workbook this app could not show.
                                */}
                              {isWorkbook(version) && onPreview ? (
                                <button
                                  type="button"
                                  className="fnd-head__tab"
                                  onClick={() => onPreview(version.sha256, version.ext ?? '.xlsx')}
                                  disabled={previewing === version.sha256}
                                  aria-label={`预览 ${shortSha(version.sha256)}`}
                                >
                                  <Eye size={12} strokeWidth={1.5} aria-hidden />
                                  {previewing === version.sha256 ? ' 装进预览…' : ' 预览'}
                                </button>
                              ) : null}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {reading && versionsFor(row.window_id).some((v) => v.sha256 === reading.sha) ? (
                    <Reader source={reading.text} />
                  ) : null}
                </div>
              ) : null}
            </li>
          ))}
        </ol>
      </section>

      <section>
        <p className="fnd-eyebrow">
          <MessageSquareQuote size={12} strokeWidth={1.5} aria-hidden />
          {' 会话'}
        </p>
        {detail.sessions.length === 0 ? (
          <p className="fnd-muted" style={{ marginTop: 10 }}>
            还没有会话记在这个任务上。
          </p>
        ) : (
          <div className="fnd-stack" style={{ marginTop: 12 }}>
            {detail.sessions.map((session) => (
              <div key={session.session_id} className="fnd-panel">
                <span className="fnd-row">
                  <span className="fnd-title">{ROLE_LABEL[session.role]}</span>
                  <span className="fnd-sha">{session.session_id}</span>
                  <span className="fnd-muted">{when(session.opened_at)}</span>
                </span>
                {/*
                  * The leader's own wording, when the operator wrote it down. It
                  * is deliberately not the `text` a model passed to
                  * `query-locked`: a model may paraphrase, and what was asked
                  * and what was computed are two columns.
                  */}
                {session.leader_verbatim ? (
                  <p style={{ marginTop: 8 }}>「{session.leader_verbatim}」</p>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
