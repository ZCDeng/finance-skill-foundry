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
import { Booting, Guide, TaskBar, WiringTrouble, type OpenSession } from './views/Workbench.js';

/**
 * A refusal is a sentence the store wrote. Show it, do not translate it.
 *
 * `onDismiss` is not decoration. On the two embedded screens this sentence is
 * drawn in a column the native page covers, so it is shown *instead* of that
 * page -- and nothing else would ever clear it: the status poll stops once the
 * wiring is ready, so a failed call would leave the harness hidden behind an
 * error with no way back to it.
 */
function Refusal({ message, onDismiss }: { message: string; onDismiss?: () => void }) {
  // `onDismiss` is only passed where this is standing in for a page it displaced,
  // so it is also the signal to draw as a panel rather than as a stripe across
  // the column.
  return (
    <div className={onDismiss ? 'fnd-refusal fnd-refusal--panel' : 'fnd-refusal'}>
      <p>{message}</p>
      {onDismiss ? (
        <button type="button" className="fnd-quiet" style={{ marginTop: 12 }} onClick={onDismiss}>
          知道了
        </button>
      ) : null}
    </div>
  );
}

export function App() {
  const api = bridge();
  /*
   * The workbench is the app. It used to open on 任务, which is a form asking
   * for the name of something an operator has no reason to name until they know
   * what this window does -- and the embedded runtime, which is the answer to
   * that question, was three screens behind it.
   */
  const [screen, setScreen] = useState<Screen>('workbench');
  /** The task every session opened here binds to. Survives a screen change. */
  const [current, setCurrent] = useState<string | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  /** The task being read on 任务. A different question from which one is bound. */
  const [open, setOpen] = useState<string | null>(null);
  const [openDetail, setOpenDetail] = useState<Detail | null>(null);
  const [session, setSession] = useState<OpenSession | null>(null);
  const [opening, setOpening] = useState(false);
  const [creating, setCreating] = useState(false);
  const [status, setStatus] = useState<HarnessStatus | null>(null);
  const [formulator, setFormulator] = useState<LaunchSpec | null>(null);
  const [busyData, setBusyData] = useState(false);
  const [tasks, setTasks] = useState<TaskRow[]>([]);
  /** Until this is true, an empty list is "not asked yet", not "no tasks". */
  const [listed, setListed] = useState(false);
  const [gallery, setGallery] = useState<{ task: TaskRow; row: DeliverableRow }[]>([]);
  const [reading, setReading] = useState<{ sha: string; text: string } | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [asked, setAsked] = useState(false);

  /** Every answer lands here, so one refusal path serves every screen. */
  const take = useCallback(<T,>(answer: Answer<T>, use: (value: T) => void) => {
    if (answer.ok) {
      setProblem(null);
      use(answer.value);
    } else {
      setProblem(answer.message);
    }
  }, []);

  /*
   * The list, for the strip as much as for 任务.
   *
   * The picker in the task bar is on every screen the workbench draws, so this
   * is no longer something only the list screen needs. It also carries the
   * binding: with no task chosen, the newest one is taken, because an operator
   * coming back to this window is almost always coming back to what they were
   * last doing, and a strip that says nothing is a strip they have to act on
   * before the app does anything.
   */
  const refreshTasks = useCallback(() => {
    if (!api) return;
    void api.tasks().then((a) =>
      take(a, (rows) => {
        setTasks(rows);
        setListed(true);
        setCurrent((held) => held ?? rows[rows.length - 1]?.id ?? null);
      }),
    );
  }, [api, take]);

  useEffect(() => {
    refreshTasks();
  }, [refreshTasks]);

  useEffect(() => {
    if (!api || screen !== 'deliverables') return;
    void api.gallery().then((a) => take(a, setGallery));
  }, [api, screen, take]);

  /** The bound task's own record, which is what the strip reads. */
  const refreshDetail = useCallback(
    (id: string | null) => {
      if (!api || id === null) {
        setDetail(null);
        return;
      }
      void api.task(id).then((a) => take(a, setDetail));
    },
    [api, take],
  );

  useEffect(() => {
    refreshDetail(current);
  }, [refreshDetail, current]);

  useEffect(() => {
    if (!api || open === null) {
      setOpenDetail(null);
      return;
    }
    setReading(null);
    void api.task(open).then((a) => take(a, setOpenDetail));
  }, [api, open, take]);

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

  /*
   * What the fence stopped, said in this window rather than in the page.
   *
   * A cancelled request surfaces inside the runtime's own UI as a call that did
   * not arrive, which names nothing an operator can act on. Subscribed once for
   * the life of the window and on every screen: the page keeps running when the
   * operator is on 任务, and a refusal that arrived while they were there would
   * otherwise be lost.
   */
  useEffect(() => {
    if (!api?.onHarnessRefused) return;
    return api.onHarnessRefused((reason) => {
      setScreen('workbench');
      setProblem(reason);
    });
  }, [api]);

  useEffect(() => {
    if (!api?.formulatorStatus || screen !== 'formulator') return;
    void api.formulatorStatus().then((a) => take(a, (value) => setFormulator(value.running)));
  }, [api, screen, take]);

  /*
   * The guide covers the workbench, so it decides whether the page below gets a
   * rectangle at all.
   *
   * Shown on a store with no task, which is the one moment it is certainly true
   * that nobody here has done this before, and otherwise only when the header
   * asks for it. Not remembered anywhere: `file://` has no storage worth
   * relying on, and "has this operator ever made a task" is a better answer to
   * the same question than a flag would be.
   */
  const guide = screen === 'workbench' && (asked || (listed && tasks.length === 0 && !dismissed));
  const ready = status?.wiring.state === 'ready';
  const failed = status?.wiring.state === 'failed';

  /*
   * The harness page is a native view, so it is not hidden by React unmounting
   * anything -- main has to be told to give it a rectangle or take it away. This
   * is the one place that says which screen is on top.
   *
   * It is no longer gated on a session. The runtime's own page is what this
   * product looks like, and holding it back until three clicks had happened is
   * what made a fresh install unreadable. What is still gated is the guide: it
   * is drawn in this app's document, and anything drawn there while the view has
   * a rectangle is behind it.
   */
  useEffect(() => {
    // A refusal takes the rectangle away for the same reason the guide does: it
    // is drawn in this app's document, and the page would be on top of it.
    const blocked = guide || problem !== null;
    const shown =
      screen === 'workbench' && ready && !blocked
        ? 'workbench'
        : screen === 'formulator' && formulator !== null && !blocked
          ? 'formulator'
          : '';
    void api?.paneVisible?.(shown);
  }, [api, screen, ready, guide, problem, formulator]);

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
   * Open a conversation on a task, named rather than inferred.
   *
   * The id is an argument because the one flow that matters most does not have
   * it in state yet: the guide creates a task and opens a period session on it
   * in a single press, and a `current` set a render earlier is not visible to
   * the call that follows.
   */
  const openSession = useCallback(
    (intent: Intent, taskId?: string) => {
      const target = taskId ?? current;
      if (!api?.harnessOpen || !target) return;
      setOpening(true);
      const on = target === current ? detail : null;
      const newest = on?.windows[on.windows.length - 1];
      const latestBrief = [...(on?.deliverables ?? [])]
        .reverse()
        .find((row) => row.kind === 'export' || row.kind === 'brief');
      const seed =
        intent === 'followup' && newest
          ? { windowId: newest.window_id, briefSha: latestBrief?.sha256 ?? null }
          : undefined;
      void api
        .harnessOpen(intent, target, seed)
        .then((a) =>
          take(a, (value) => {
            setSession({ ...value, intent });
            setCurrent(target);
            // A period session creates a window on the way in, and the strip
            // above is drawn from `detail`. Without this it keeps saying the
            // task has no window while the operator is typing into the one the
            // button just opened.
            refreshDetail(target);
            refreshTasks();
          }),
        )
        .finally(() => setOpening(false));
    },
    [api, current, detail, take, refreshDetail, refreshTasks],
  );

  /** Name a task and start working in it, in one press. */
  const startFirst = useCallback(
    (title: string, period: string) => {
      if (!api) return;
      setCreating(true);
      void api
        .taskNew(title, period)
        .then((a) =>
          take(a, ({ id }) => {
            setCurrent(id);
            setAsked(false);
            setDismissed(true);
            refreshTasks();
            openSession('period', id);
          }),
        )
        .finally(() => setCreating(false));
    },
    [api, take, refreshTasks, openSession],
  );

  /** Name a task from 任务, and open it there. The workbench binds to it too. */
  const createTask = useCallback(
    (title: string, period: string) => {
      if (!api) return;
      setCreating(true);
      void api
        .taskNew(title, period)
        .then((a) =>
          take(a, ({ id }) => {
            refreshTasks();
            setCurrent(id);
            setOpen(id);
          }),
        )
        .finally(() => setCreating(false));
    },
    [api, take, refreshTasks],
  );

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

  const bound = tasks.find((row) => row.id === current) ?? null;

  return (
    <Shell
      screen={screen}
      onScreen={setScreen}
      onGuide={screen === 'workbench' ? () => setAsked(true) : undefined}
      strip={
        screen === 'workbench' ? (
          <TaskBar
            tasks={tasks}
            task={bound}
            detail={detail}
            session={session}
            busy={opening || creating}
            onPick={(id) => {
              setCurrent(id);
              // The old session belongs to the task that was bound a moment
              // ago. Keeping it would put another task's round counter above a
              // conversation that never touched it.
              setSession(null);
            }}
            onNew={() => {
              setScreen('tasks');
              setOpen(null);
            }}
            onOpen={openSession}
          />
        ) : screen === 'formulator' ? (
          <DataBar
            task={bound}
            detail={detail}
            running={formulator}
            busy={busyData}
            onLaunch={launchFormulator}
            onStop={stopFormulator}
          />
        ) : undefined
      }
    >
      {problem ? (
        <Refusal message={problem} onDismiss={() => setProblem(null)} />
      ) : null}
      {screen === 'workbench' ? (
        guide ? (
          <Guide
            busy={creating || opening}
            canStart={Boolean(api.harnessOpen)}
            onStart={startFirst}
            onDismiss={() => {
              setAsked(false);
              setDismissed(true);
            }}
          />
        ) : failed ? (
          <WiringTrouble status={status} />
        ) : ready ? null : (
          <Booting />
        )
      ) : null}
      {screen === 'tasks' && open === null ? (
        <Tasks tasks={tasks} busy={creating} onOpen={setOpen} onCreate={createTask} />
      ) : null}
      {screen === 'tasks' && open !== null && openDetail ? (
        <TaskDetail
          detail={openDetail}
          onBack={() => setOpen(null)}
          onRead={read}
          reading={reading}
        />
      ) : null}
      {screen === 'formulator' ? <Formulator running={formulator} /> : null}
      {screen === 'deliverables' ? <Deliverables rows={gallery} /> : null}
    </Shell>
  );
}
