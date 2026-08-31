import { useCallback, useEffect, useState } from 'react';

import './styles/base.css';

import { Shell, type Screen } from './components/Shell.js';
import {
  type Answer,
  type DeliverableRow,
  type Intent,
  type LaunchSpec,
  type TaskDetail as Detail,
  type HarnessStatus,
  type TaskRow,
  bridge,
} from './bridge.js';
import { Deliverables } from './views/Deliverables.js';
import { TaskDetail } from './views/TaskDetail.js';
import { Tasks } from './views/Tasks.js';
import { DataBar, Formulator } from './views/Formulator.js';
import { TaskBar, Workbench, WiringTrouble, type OpenSession } from './views/Workbench.js';

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
  const [creating, setCreating] = useState(false);
  const [status, setStatus] = useState<HarnessStatus | null>(null);
  const [formulator, setFormulator] = useState<LaunchSpec | null>(null);
  const [busyData, setBusyData] = useState(false);
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
    // The workbench has no page until a session is open; the data screen has none
    // until Formulator is running. Naming the screen and letting main decide
    // keeps the two rectangles from ever both being real.
    const shown =
      (screen === 'workbench' && session !== null) || (screen === 'formulator' && formulator !== null)
        ? screen
        : '';
    void api?.paneVisible?.(shown);
  }, [api, screen, session, formulator]);

  /*
   * Polled while the workbench is open rather than read once: the wiring runs
   * after the window is already up, so a screen that asked once would report
   * `pending` forever and a failure that arrived a second later would never be
   * drawn. It stops on its own as soon as the answer is not `pending`.
   */
  useEffect(() => {
    if (!api?.harnessStatus || screen !== 'workbench') return;
    let live = true;
    const ask = () => {
      void api.harnessStatus?.().then((a) =>
        take(a, (value) => {
          if (!live) return;
          setStatus(value);
          if (value.wiring.state === 'pending') window.setTimeout(ask, 1000);
        }),
      );
    };
    ask();
    return () => {
      live = false;
    };
  }, [api, screen, take]);

  useEffect(() => {
    if (!api?.formulatorStatus || screen !== 'formulator') return;
    void api.formulatorStatus().then((a) => take(a, (value) => setFormulator(value.running)));
  }, [api, screen, take]);

  const launchFormulator = useCallback(() => {
    if (!api?.formulatorLaunch) return;
    setBusyData(true);
    void api
      .formulatorLaunch()
      .then((a) => take(a, setFormulator))
      .finally(() => setBusyData(false));
  }, [api, take]);

  const stopFormulator = useCallback(() => {
    if (!api?.formulatorStop) return;
    setBusyData(true);
    void api
      .formulatorStop()
      .then((a) => take(a, () => setFormulator(null)))
      .finally(() => setBusyData(false));
  }, [api, take]);

  /*
   * Create a task, then open it.
   *
   * Opening it is not a convenience. An operator who just named a period wants
   * to start working in it, and the alternative is a list that grew by one row
   * they now have to find. The list is refreshed either way, because the row has
   * to exist for the workbench's task bar to have a name to draw.
   */
  const createTask = useCallback(
    (title: string, period: string) => {
      if (!api) return;
      setCreating(true);
      void api
        .taskNew(title, period)
        .then((a) =>
          take(a, ({ id }) => {
            void api.tasks().then((rows) => take(rows, setTasks));
            setOpen(id);
          }),
        )
        .finally(() => setCreating(false));
    },
    [api, take],
  );

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
        .then((a) =>
          take(a, (value) => {
            setSession({ ...value, intent });
            // A period session creates a window on the way in, and the task bar
            // above is drawn from `detail`. Without this it keeps saying the
            // task has no window while the operator is typing into the one the
            // button just opened.
            void api.task(open).then((fresh) => take(fresh, setDetail));
          }),
        )
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
        ) : screen === 'formulator' ? (
          <DataBar
            task={current}
            detail={detail}
            running={formulator}
            busy={busyData}
            onLaunch={launchFormulator}
            onStop={stopFormulator}
          />
        ) : undefined
      }
    >
      {problem ? <Refusal message={problem} /> : null}
      {/*
        * Above the buttons, not beside them. A session opened on a half-wired
        * app runs on the wrong preset or with no period tools at all, and the
        * operator should read why before pressing anything.
        */}
      {screen === 'workbench' ? <WiringTrouble status={status} /> : null}
      {screen === 'workbench' ? (
        open === null ? (
          <Tasks tasks={tasks} busy={creating} onOpen={setOpen} onCreate={createTask} />
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
      {screen === 'tasks' && open === null ? (
        <Tasks tasks={tasks} busy={creating} onOpen={setOpen} onCreate={createTask} />
      ) : null}
      {screen === 'tasks' && open !== null && detail ? (
        <TaskDetail detail={detail} onBack={() => setOpen(null)} onRead={read} reading={reading} />
      ) : null}
      {screen === 'formulator' ? <Formulator running={formulator} /> : null}
      {screen === 'deliverables' ? <Deliverables rows={gallery} /> : null}
    </Shell>
  );
}
