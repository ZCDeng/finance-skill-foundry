import { useState } from 'react';
import {
  GraduationCap,
  Loader,
  MessagesSquare,
  PlayCircle,
  TriangleAlert,
} from 'lucide-react';

import { APP_NAME } from '../components/Shell.js';
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

/** The value the picker uses for its one entry that is not a task. */
const NEW_TASK = '__new__';

/**
 * The strip that says where a conversation writes, and opens one.
 *
 * Not optional chrome, and not only a label any more. The harness page below is
 * upstream's and says nothing about this product's store, so this line is the
 * whole of what an operator has to tell them which task a session will change
 * and to change it. Everything here has to be reachable in one strip because
 * the page below is a native view: a panel drawn in the document under it would
 * be covered, and the only menu that draws over it is the one a native `select`
 * opens.
 */
export function TaskBar({
  tasks,
  task,
  detail,
  session,
  busy,
  onPick,
  onNew,
  onOpen,
}: {
  tasks: TaskRow[];
  task: TaskRow | null;
  detail: TaskDetail | null;
  session: OpenSession | null;
  busy: boolean;
  onPick(id: string): void;
  onNew(): void;
  onOpen(intent: Intent): void;
}) {
  const windows = detail?.windows ?? [];
  const newest = windows[windows.length - 1];
  const round = session
    ? (detail?.sessions ?? []).filter((row) => row.role === session.intent).length
    : 0;
  return (
    <div className="fnd-taskbar">
      <select
        className="fnd-picker"
        aria-label="任务"
        value={task?.id ?? ''}
        disabled={busy}
        onChange={(event) => {
          const next = event.target.value;
          if (next === NEW_TASK) onNew();
          else if (next) onPick(next);
        }}
      >
        {task ? null : (
          <option value="" disabled>
            还没有选任务
          </option>
        )}
        {tasks.map((row) => (
          <option key={row.id} value={row.id}>
            {row.period ? `${row.title} · ${row.period}` : row.title}
          </option>
        ))}
        <option value={NEW_TASK}>＋ 新建任务…</option>
      </select>

      {task ? (
        <>
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
        </>
      ) : null}

      <span className="fnd-taskbar__sep">/</span>
      {/*
       * What this conversation is, said the same way whether the app opened it
       * or nobody did. The second half is not a nag: a session started inside
       * the page below runs on whatever preset that page defaults to, and the
       * period tools it can reach resolve their task from the current window
       * rather than from the row named to the left of this sentence.
       */}
      <span className="fnd-muted">
        {session
          ? `本会话 ${ROLE_LABEL[session.intent]} · 第 ${round} 轮 · ${session.preset}`
          : '会话不是从这里开的 · 期间工具会落到当前窗口'}
      </span>

      <span className="fnd-taskbar__spacer" />
      {INTENTS.map(({ id, label, Icon }) => (
        <button
          key={id}
          type="button"
          className="fnd-start"
          data-current={session?.intent === id ? 'yes' : undefined}
          disabled={!task || busy}
          title={INTENTS.find((row) => row.id === id)?.hint}
          onClick={() => onOpen(id)}
        >
          <Icon size={13} strokeWidth={1.5} aria-hidden />
          {label}
        </button>
      ))}
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
      <p className="fnd-muted" style={{ marginTop: 8 }}>
        任务、交付物和数据台不受影响, 还能用。
      </p>
    </div>
  );
}

/**
 * The seconds before the packed runtime answers.
 *
 * The harness page is a native view that covers this whole area, so on a good
 * day none of this is ever seen. It exists because the runtime takes a few
 * seconds to compose its plugin tree on a cold start, and a window that draws
 * nothing for those seconds reads as an app that did not launch.
 */
export function Booting() {
  return (
    <div className="fnd-booting">
      <Loader size={20} strokeWidth={1.25} className="fnd-spin" aria-hidden />
      <p className="fnd-muted">{APP_NAME} 正在启动</p>
    </div>
  );
}

/**
 * What this window is, for someone opening it for the first time.
 *
 * Shown when the store has no task, which is the one moment it is certainly
 * true that nobody here has done this before, and reachable afterwards from the
 * header. It carries the one form that gets a cold install moving: naming a
 * period and opening a session on it in a single press, because the alternative
 * -- name a task on one screen, find it on another, then choose a way in --
 * is three screens of guessing before anything happens.
 */
export function Guide({
  busy,
  canStart,
  onStart,
  onDismiss,
}: {
  busy: boolean;
  /** False when this build has no harness to open a session in. */
  canStart: boolean;
  onStart(title: string, period: string): void;
  onDismiss(): void;
}) {
  const [title, setTitle] = useState('');
  const [period, setPeriod] = useState('');
  const ready = title.trim().length > 0 && canStart && !busy;
  return (
    <div className="fnd-guide">
      <p className="fnd-eyebrow">这是什么</p>
      <h3 className="fnd-guide__lede">
        一个把结账期间当成任务来管的工作台。上面是对话, 下面这三条是进去的路。
      </h3>

      <ol className="fnd-guide__steps">
        {INTENTS.map(({ id, label, hint, Icon }) => (
          <li key={id} className="fnd-guide__step">
            <Icon size={15} strokeWidth={1.5} aria-hidden />
            <span className="fnd-title">{label}</span>
            <span className="fnd-muted">{hint}</span>
          </li>
        ))}
      </ol>

      <p className="fnd-muted fnd-guide__note">
        会话开在哪个任务上, 顶上那条一直写着。任务、每一版交付物和它们的来路, 在「任务」和「交付物」两屏。
      </p>

      <form
        className="fnd-new"
        onSubmit={(event) => {
          event.preventDefault();
          if (!ready) return;
          onStart(title.trim(), period.trim());
        }}
      >
        <input
          className="fnd-field"
          value={title}
          maxLength={120}
          placeholder="任务名, 比如 华东区 8 月回款"
          aria-label="任务名"
          onChange={(event) => setTitle(event.target.value)}
        />
        <input
          className="fnd-field fnd-field--short"
          value={period}
          maxLength={32}
          placeholder="期间 2026-08"
          aria-label="期间"
          onChange={(event) => setPeriod(event.target.value)}
        />
        <button type="submit" className="fnd-go" disabled={!ready}>
          <PlayCircle size={14} strokeWidth={1.5} aria-hidden />
          建任务并开始本期
        </button>
      </form>

      <button type="button" className="fnd-quiet" onClick={onDismiss}>
        先看看再说
      </button>
    </div>
  );
}
