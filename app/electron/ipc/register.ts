import { type BrowserWindow, ipcMain } from 'electron';

import type { Binding } from '../foundry.js';
import { FoundryFailure, FoundryRefusal, runFoundry } from '../foundry.js';
import type { FormulatorHost } from '../formulator.js';
import { ROLE_BY_INTENT, type Intent } from '../harness/boot.js';
import { ensureTaskWorkspace } from '../harness/workspace.js';
import { WIRING_CONSEQUENCE, type Wiring } from '../harness/wiring.js';
import type { HarnessHost } from '../harness/host.js';
import { deliverableGallery, listTasks, readDeliverable, showTask } from '../reads.js';
import { newTask } from '../writes.js';
import { CHANNELS } from './contract.js';

/**
 * What a handler hands back.
 *
 * A refusal is not an exception here. `foundry` exits 3 for a domain refusal --
 * "no task", "workpaper not written" -- and those are states a screen renders,
 * not crashes. Throwing across the IPC boundary would reach the renderer as a
 * mangled `Error invoking remote method` string with the actual sentence buried
 * in it, so the two are separated on this side and the shape is the same either
 * way.
 */
export type Answer<T> =
  | { ok: true; value: T }
  | { ok: false; refused: boolean; message: string };

async function answer<T>(work: () => Promise<T>): Promise<Answer<T>> {
  try {
    return { ok: true, value: await work() };
  } catch (error) {
    if (error instanceof FoundryRefusal) return { ok: false, refused: true, message: error.message };
    if (error instanceof FoundryFailure) return { ok: false, refused: false, message: error.message };
    return { ok: false, refused: false, message: error instanceof Error ? error.message : String(error) };
  }
}

/** A task id as it comes off the wire. 32 hex, or the call does not run. */
function taskId(value: unknown): string {
  const text = String(value ?? '');
  if (!/^[0-9a-f]{32}$/.test(text)) throw new FoundryFailure(`not a task id: ${text}`, null);
  return text;
}

/** An intent as it comes off the wire. One of three, or the call does not run. */
function intentOf(value: unknown): Intent {
  const text = String(value ?? '');
  if (text === 'author' || text === 'period' || text === 'followup') return text;
  throw new FoundryFailure(`not an intent: ${text}`, null);
}

/**
 * A line an operator typed, as it comes off the wire.
 *
 * Trimmed, bounded, and refused if it carries a control character. Not a
 * quoting defence -- these reach `execFile` as an argument array, so a quote or
 * a semicolon is one more character in a title. It is a defence against a
 * newline or a NUL landing in a stored title and then in every screen and every
 * log line that ever prints it back.
 *
 * Exported only so the refusals have a test. Nothing outside this file calls it.
 */
export function lineOf(value: unknown, what: string, max: number): string {
  const text = String(value ?? '').trim();
  if (!text) throw new FoundryFailure(`${what} is empty`, null);
  if (text.length > max) throw new FoundryFailure(`${what} is longer than ${max} characters`, null);
  // eslint-disable-next-line no-control-regex
  if (/[\u0000-\u001f\u007f]/.test(text)) throw new FoundryFailure(`${what} has a control character`, null);
  return text;
}

export function registerIpc(
  binding: Omit<Binding, 'task' | 'session'>,
  panes?: {
    host: HarnessHost;
    formulator: FormulatorHost;
    /** How the wiring went. Read, never awaited: a failed run has no harness to wait on. */
    wiring: () => Wiring;
    window: () => BrowserWindow | null;
    /** Told on every change, so a resize can put the views back where they were. */
    remember: (screen: string) => void;
    /** This app's own state root; a session's workspace is made under it. */
    userData: () => string;
  },
): void {
  ipcMain.handle(CHANNELS.tasks, () => answer(() => listTasks(binding)));

  ipcMain.handle(CHANNELS.task, (_event, task: unknown) =>
    answer(() => showTask({ ...binding, task: taskId(task) })),
  );

  ipcMain.handle(CHANNELS.gallery, () => answer(() => deliverableGallery(binding)));

  ipcMain.handle(CHANNELS.deliverableText, (_event, task: unknown, sha: unknown) =>
    answer(() => readDeliverable({ ...binding, task: taskId(task) }, String(sha ?? ''))),
  );

  /**
   * Create a task.
   *
   * Registered beside the reads rather than behind `panes`, because a build with
   * no harness staged still has a store and an operator who needs somewhere to
   * put a period. It is also the only channel here that changes anything, which
   * is why it is the only one whose arguments are free text.
   */
  ipcMain.handle(CHANNELS.taskNew, (_event, title: unknown, period: unknown) =>
    answer(() =>
      newTask(binding, {
        title: lineOf(title, 'title', 120),
        period: String(period ?? '').trim() ? lineOf(period, 'period', 32) : undefined,
      }),
    ),
  );

  if (!panes) return;
  const harness = panes;

  /**
   * What the workbench needs to know before it draws anything.
   *
   * Deliberately does not start the harness. The old version awaited
   * `host.start()`, which meant the one call a screen would make to find out
   * whether the wiring failed either hung on a start that was never going to
   * happen or reported the timeout instead of the reason.
   */
  ipcMain.handle(CHANNELS.harnessStatus, () =>
    answer(async () => {
      const state = harness.wiring();
      return {
        wiring: state,
        consequence: state.state === 'failed' ? WIRING_CONSEQUENCE[state.step] : null,
        origin: harness.host.origin(),
      };
    }),
  );

  /**
   * Open a conversation, bound before it exists.
   *
   * The order is the point. A period session gets a window created against this
   * task first, so the window carries the back-pointer before the model can call
   * anything -- the CLI then resolves the task from the window rather than from
   * an ambient value, which is what lets one harness process serve every task.
   * The session is registered on the task with the role its button chose, and
   * the leader's own wording is written here rather than inferred later from
   * whatever a model passed to `query-locked`.
   */
  ipcMain.handle(
    CHANNELS.harnessOpen,
    (_event, rawIntent: unknown, rawTask: unknown, rawSeed: unknown) =>
      answer(async () => {
        const intent = intentOf(rawIntent);
        const task = taskId(rawTask);
        const seed = (rawSeed ?? {}) as { windowId?: string; briefSha?: string; verbatim?: string };

        if (intent === 'period') {
          await runFoundry({ ...binding, task }, 'create');
        }
        const opened = await harness.host.open(
          intent,
          // Made real before the session names it: the runtime resolves a cwd
          // through `realpath` and refuses one that is not there.
          ensureTaskWorkspace(harness.userData(), task),
          intent === 'followup' && seed.windowId
            ? { windowId: seed.windowId, briefSha: seed.briefSha ?? null }
            : undefined,
        );
        await runFoundry({ ...binding, task, session: opened.sessionId }, 'record-session', [
          '--role',
          ROLE_BY_INTENT[intent],
          ...(seed.verbatim ? ['--verbatim', seed.verbatim] : []),
        ]);
        return opened;
      }),
  );

  /**
   * Launch Formulator on the current window.
   *
   * No task argument: the lease is a window's, and `launch-formulator` takes the
   * current one. Binding it to a task here would let a screen ask for a reader
   * on a window that is not the one the operator is looking at.
   */
  ipcMain.handle(CHANNELS.formulatorLaunch, () =>
    answer(async () => {
      const window = panes.window();
      if (!window) throw new FoundryFailure('no window to show Formulator in', null);
      return panes.formulator.launch(binding, window);
    }),
  );

  ipcMain.handle(CHANNELS.formulatorStop, () =>
    answer(async () => {
      const window = panes.window();
      if (window) await panes.formulator.stop(binding, window);
      return { stopped: true };
    }),
  );

  ipcMain.handle(CHANNELS.formulatorStatus, () =>
    answer(async () => ({ running: panes.formulator.running() })),
  );

  /**
   * Which screen is on top.
   *
   * Both embedded pages are native views in window coordinates, so React
   * unmounting a component does not hide either of them. This is the one place
   * that decides which rectangle is real, and it places both so a switch cannot
   * leave two stacked.
   */
  ipcMain.handle(CHANNELS.paneVisible, (_event, screen: unknown) =>
    answer(async () => {
      const name = String(screen ?? '');
      panes.remember(name);
      const window = panes.window();
      if (window) {
        panes.host.place(window, name === 'workbench');
        panes.formulator.place(window, name === 'formulator');
      }
      return { screen: name };
    }),
  );
}
