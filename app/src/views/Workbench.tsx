import { GraduationCap, MessagesSquare, PlayCircle, TriangleAlert } from 'lucide-react';

import type { HarnessStatus, TaskDetail, TaskRow } from '../bridge.js';

export type Intent = 'author' | 'period' | 'followup';

export interface OpenSession {
  sessionId: string;
  preset: string;
  intent: Intent;
}

const INTENTS: { id: Intent; label: string; hint: string; Icon: typeof PlayCircle }[] = [
  { id: 'author', label: '授技能', hint: 'standard · 写一个可交接的分析技能', Icon: GraduationCap },
  { id: 'period', label: '开始本期', hint: 'period · 开窗 导入 锁 出稿', Icon: PlayCircle },
  { id: 'followup', label: '追问', hint: 'f3 · 只有 query-locked', Icon: MessagesSquare },
];

const ROLE_LABEL: Record<Intent, string> = { author: '授技能', period: '期间', followup: '追问' };

/**
 * The strip that says where a conversation writes.
 *
 * Not optional chrome. The harness page below is upstream's and says nothing
 * about this product's store, so without this line an operator can type into a
 * session and not know which task it will change. It names the task, the chain
 * of windows, the state of the newest one, and this session's own role and
 * round.
 */
export function TaskBar({
  task,
  detail,
  session,
}: {
  task: TaskRow | null;
  detail: TaskDetail | null;
  session: OpenSession | null;
}) {
  if (!task) {
    return (
      <div className="fnd-taskbar">
        <span className="fnd-muted">先选一个任务, 会话才有地方写。</span>
      </div>
    );
  }
  const windows = detail?.windows ?? [];
  const newest = windows[windows.length - 1];
  const round = session
    ? (detail?.sessions ?? []).filter((row) => row.role === session.intent).length
    : 0;
  return (
    <div className="fnd-taskbar">
      <span className="fnd-taskbar__name">{task.title}</span>
      <span className="fnd-taskbar__sep">/</span>
      <span className="fnd-muted">
        {windows.length === 0
          ? '还没有窗口'
          : windows.map((row) => row.window_id.slice(0, 6)).join(' → ')}
      </span>
      {newest ? (
        <>
          <span className="fnd-taskbar__sep">/</span>
          <span className="fnd-muted">{newest.state}</span>
        </>
      ) : null}
      <span className="fnd-taskbar__sep">/</span>
      <span className="fnd-muted">
        {session ? `本会话 ${ROLE_LABEL[session.intent]} · 第 ${round} 轮` : '没有会话'}
      </span>
    </div>
  );
}

/**
 * What the app could not wire up, said where the operator is looking.
 *
 * The harness reports its own troubles in its own page, and they are the wrong
 * troubles: a period bundle that never installed makes the runtime's plugin tree
 * fail to load, and what surfaces is its settings dialog saying an
 * acknowledgement could not be saved. Nothing in that sentence is about a
 * missing bundle. This one is.
 *
 * The runtime's own message is kept under the consequence rather than replaced
 * by it -- it is the half that says which file, and it is what makes the failure
 * fixable rather than merely legible.
 */
export function WiringTrouble({ status }: { status: HarnessStatus | null }) {
  if (!status || status.wiring.state !== 'failed') return null;
  return (
    <div className="fnd-refusal" style={{ marginBottom: 18 }}>
      <span className="fnd-row">
        <TriangleAlert size={14} strokeWidth={1.5} aria-hidden />
        <span className="fnd-title">工作台没有装好</span>
      </span>
      <p style={{ marginTop: 8 }}>{status.consequence}</p>
      <p className="fnd-muted" style={{ marginTop: 8 }}>
        {status.wiring.message}
      </p>
    </div>
  );
}

/**
 * The three ways in.
 *
 * The button picks the agent preset, and nothing later can widen it: a follow-up
 * opened here is offered `query-locked` alone. The operator is choosing what
 * kind of work this is, not which tools to hand a model.
 */
export function Workbench({
  task,
  detail,
  session,
  busy,
  onOpen,
}: {
  task: TaskRow | null;
  detail: TaskDetail | null;
  session: OpenSession | null;
  busy: boolean;
  onOpen(intent: Intent): void;
}) {
  if (session) {
    // The harness page is a native view over this rectangle. Anything drawn here
    // would sit behind it, so this stays empty on purpose.
    return null;
  }
  return (
    <div className="fnd-stack" style={{ gap: 14, paddingTop: 24 }}>
      <p className="fnd-eyebrow">开一个会话</p>
      {INTENTS.map(({ id, label, hint, Icon }) => (
        <button
          key={id}
          type="button"
          className="fnd-card"
          disabled={!task || busy}
          onClick={() => onOpen(id)}
        >
          <span className="fnd-row">
            <Icon size={15} strokeWidth={1.5} aria-hidden />
            <span className="fnd-title">{label}</span>
            <span className="fnd-muted">{hint}</span>
          </span>
        </button>
      ))}
      {task && detail && detail.windows.length === 0 && session === null ? (
        <p className="fnd-muted">这个任务还没有窗口。「开始本期」会先开一个, 再把会话挂上去。</p>
      ) : null}
    </div>
  );
}
