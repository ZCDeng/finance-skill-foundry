import {
  GraduationCap,
  MessagesSquare,
  PlayCircle,
  TriangleAlert,
} from 'lucide-react';

import { APP_NAME } from '../components/Shell.js';
import { WaitOrb } from '../components/WaitOrb.js';
import type { HarnessStatus, TaskDetail, TaskRow } from '../bridge.js';
import { NativeSelect } from '../components/ui/native-select.js';

export type Intent = 'author' | 'period' | 'followup' | 'analysis';

export interface OpenSession {
  sessionId: string;
  preset: string;
  intent: Intent;
}

/*
 * The three ways in, in the operator's words.
 *
 * The first used to read 授技能, which named neither what an operator does nor
 * what comes out of it -- a finance manager teaching a skill to something is
 * not a sentence about closing a period. What it produces is a method: the
 * store calls them method skills, `method/` holds four of them, and each period
 * runs against one. So the button says 写方法 and the hint says what it is for.
 */
const INTENTS: { id: Intent; label: string; hint: string; Icon: typeof PlayCircle }[] = [
  { id: 'analysis', label: '继续分析', hint: '读取资料、比较、测算与改稿', Icon: PlayCircle },
  {
    id: 'author',
    label: '写方法',
    hint: 'standard · 把这类分析怎么做定下来, 以后每期照着跑',
    Icon: GraduationCap,
  },
  { id: 'period', label: '开始本期', hint: 'period · 开窗 导入 锁 出稿', Icon: PlayCircle },
  { id: 'followup', label: '追问', hint: 'f3 · 只有 query-locked', Icon: MessagesSquare },
];

const ROLE_LABEL: Record<Intent, string> = { analysis: '财务分析', author: '写方法', period: '期间', followup: '追问' };

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
      <NativeSelect
        className="fnd-picker"
        wrapperClassName="fnd-native-select--picker"
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
      </NativeSelect>

      {task && session?.intent !== 'analysis' ? (
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
          ? `${ROLE_LABEL[session.intent]}${session.intent === 'analysis' ? '' : ` · 第 ${round} 轮`}`
          : '选择任务后继续分析'}
      </span>

      <span className="fnd-taskbar__spacer" />
      {INTENTS.filter(({ id }) => id === 'analysis').map(({ id, label, Icon }) => (
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
      <NativeSelect className="fnd-picker" wrapperClassName="fnd-native-select--picker" aria-label="旧版期间流程" value="" disabled={!task || busy}
        onChange={(event) => { if (event.target.value) onOpen(event.target.value as Intent); }}>
        <option value="">旧版期间流程…</option>
        {INTENTS.filter(({ id }) => id !== 'analysis').map(({ id, label }) => <option key={id} value={id}>{label}</option>)}
      </NativeSelect>
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
      <WaitOrb state="connecting" delay={0} />
      <p className="fnd-muted">{APP_NAME} 正在启动</p>
    </div>
  );
}
