import { PlayCircle, Square } from 'lucide-react';

import type { LaunchSpec, TaskDetail, TaskRow } from '../bridge.js';
import { Chip } from '../components/Chip.js';

/**
 * The strip over the Formulator page.
 *
 * It says which window's books the reader is attached to, because the lease is a
 * window's, not a task's: `launch-formulator` takes the current one, and after a
 * re-import that is the successor rather than the window a brief came from.
 */
export function DataBar({
  task,
  detail,
  running,
  busy,
  onLaunch,
  onStop,
}: {
  task: TaskRow | null;
  detail: TaskDetail | null;
  running: LaunchSpec | null;
  busy: boolean;
  onLaunch(): void;
  onStop(): void;
}) {
  const newest = detail?.windows[detail.windows.length - 1];
  return (
    <div className="fnd-taskbar">
      {/*
        * The task is context, not a precondition. `launch-formulator` takes the
        * current window, so this screen works with no task open at all -- saying
        * "没有任务" flat would read like a blocker in front of a button that is
        * about to work.
        */}
      <span className="fnd-taskbar__name">{task ? task.title : '当前窗口'}</span>
      <span className="fnd-taskbar__sep">/</span>
      <span className="fnd-muted">
        {newest
          ? `${newest.window_id.slice(0, 6)} · ${newest.state}`
          : '租约跟着 current 走, 不跟任务'}
      </span>
      <span className="fnd-taskbar__sep">/</span>
      {running ? (
        <>
          <span className="fnd-muted">{running.url}</span>
          {/*
            * The kit says so when it could not prove the served process is this
            * window's -- no `ps`, or a pid owned by somebody else. It launched
            * anyway rather than becoming unstartable, and this is where that
            * shows.
            */}
          {running.identity ? <span className="fnd-muted">{running.identity}</span> : null}
          <button type="button" className="fnd-head__tab" disabled={busy} onClick={onStop}>
            <Square size={12} strokeWidth={1.5} aria-hidden />
            {' 停掉'}
          </button>
        </>
      ) : (
        <button type="button" className="fnd-head__tab" disabled={busy} onClick={onLaunch}>
          <PlayCircle size={13} strokeWidth={1.5} aria-hidden />
          {' 起 Data Formulator'}
        </button>
      )}
    </div>
  );
}

/**
 * What the screen shows before the reader is up.
 *
 * Once it is running the page below is a native view over this rectangle, so
 * anything drawn here would sit behind it.
 */
export function Formulator({ running }: { running: LaunchSpec | null }) {
  if (running) return null;
  return (
    <div className="fnd-stack" style={{ gap: 14, paddingTop: 24 }}>
      <h2>数据台</h2>
      <div className="fnd-panel">
        <p>
          Data Formulator 以只读方式挂当前窗口锁后的 catalog, 一个窗口一个租约。它把行拷进自己的
          workspace 之后才作图, 所以从图上读到的数不是稿上的数。
        </p>
        <p style={{ marginTop: 12 }}>
          <span className="fnd-muted">从这里读出来的任何数字, 转述时都算 </span>
          <Chip mark="outside" />
        </p>
        <p className="fnd-muted" style={{ marginTop: 12 }}>
          窗口锁了才起得来。补数据开后继窗口时, 旧窗口的租约会被收回。
        </p>
      </div>
    </div>
  );
}
