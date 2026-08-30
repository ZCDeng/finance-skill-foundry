import { useCallback, useEffect, useState } from 'react';

import './styles/base.css';

import { Shell, type Screen } from './components/Shell.js';
import {
  type Answer,
  type DeliverableRow,
  type Intent,
  type TaskDetail as Detail,
  type TaskRow,
  bridge,
} from './bridge.js';
import { Deliverables } from './views/Deliverables.js';
import { TaskDetail } from './views/TaskDetail.js';
import { Tasks } from './views/Tasks.js';
import { TaskBar, Workbench, type OpenSession } from './views/Workbench.js';

/** A refusal is a sentence the store wrote. Show it, do not translate it. */
function Refusal({ message }: { message: string }) {
  return <p className="fnd-refusal">{message}</p>;
}

export function App() {
  const api = bridge();
  const [screen, setScreen] = useState<Screen>('tasks');
  const [open, setOpen] = useState<string | null>(null);
  const [session, setSession] = useState<OpenSession | null>(null);
  const [opening, setOpening] = useState(false);
  const [tasks, setTasks] = useState<TaskRow[]>([]);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [gallery, setGallery] = useState<{ task: TaskRow; row: DeliverableRow }[]>([]);
  const [reading, setReading] = useState<{ sha: string; text: string } | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  /** Every answer lands here, so one refusal path serves every screen. */
  const take = useCallback(<T,>(answer: Answer<T>, use: (value: T) => void) => {
    if (answer.ok) {
      setProblem(null);
      use(answer.value);
    } else {
      setProblem(answer.message);
    }
  }, []);

  useEffect(() => {
    if (!api) return;
    if (screen !== 'deliverables' && open === null) void api.tasks().then((a) => take(a, setTasks));
    if (screen === 'deliverables') void api.gallery().then((a) => take(a, setGallery));
  }, [api, screen, open, take]);

  /*
   * The harness page is a native view, so it is not hidden by React unmounting
   * anything -- main has to be told to give it a rectangle or take it away. This
   * is the one place that says which screen is on top.
   */
  useEffect(() => {
    void api?.workbenchVisible?.(screen === 'workbench' && session !== null);
  }, [api, screen, session]);

  const openSession = useCallback(
    (intent: Intent) => {
      if (!api?.harnessOpen || !open) return;
      setOpening(true);
      const newest = detail?.windows[detail.windows.length - 1];
      const latestBrief = [...(detail?.deliverables ?? [])]
        .reverse()
        .find((row) => row.kind === 'export' || row.kind === 'brief');
      const seed =
        intent === 'followup' && newest
          ? { windowId: newest.window_id, briefSha: latestBrief?.sha256 ?? null }
          : undefined;
      void api
        .harnessOpen(intent, open, seed)
        .then((a) => take(a, (value) => setSession({ ...value, intent })))
        .finally(() => setOpening(false));
    },
    [api, open, detail, take],
  );

  useEffect(() => {
    if (!api || open === null) {
      setDetail(null);
      return;
    }
    setReading(null);
    void api.task(open).then((a) => take(a, setDetail));
  }, [api, open, take]);

  const read = useCallback(
    (sha: string) => {
      if (!api || open === null) return;
      void api.deliverableText(open, sha).then((a) => take(a, (text) => setReading({ sha, text })));
    },
    [api, open, take],
  );

  if (!api) {
    return (
      <Shell screen={screen} onScreen={setScreen}>
        <p className="fnd-empty">
          这个窗口没有接到 foundry。它在 Electron 之外跑起来时就是这样, 主进程还没起来。
        </p>
      </Shell>
    );
  }

  const current = tasks.find((row) => row.id === open) ?? null;

  return (
    <Shell
      screen={screen}
      onScreen={(next) => {
        // The workbench needs a task to write to, so it keeps the open one.
        if (next !== 'workbench') setOpen(null);
        setScreen(next);
      }}
      strip={
        screen === 'workbench' ? (
          <TaskBar task={current} detail={detail} session={session} />
        ) : undefined
      }
    >
      {problem ? <Refusal message={problem} /> : null}
      {screen === 'workbench' ? (
        open === null ? (
          <Tasks tasks={tasks} onOpen={setOpen} />
        ) : (
          <Workbench
            task={current}
            detail={detail}
            session={session}
            busy={opening}
            onOpen={openSession}
          />
        )
      ) : null}
      {screen === 'tasks' && open === null ? <Tasks tasks={tasks} onOpen={setOpen} /> : null}
      {screen === 'tasks' && open !== null && detail ? (
        <TaskDetail detail={detail} onBack={() => setOpen(null)} onRead={read} reading={reading} />
      ) : null}
      {screen === 'deliverables' ? <Deliverables rows={gallery} /> : null}
    </Shell>
  );
}
