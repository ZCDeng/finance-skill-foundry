import { type BrowserWindow, ipcMain } from 'electron';

import type { Binding } from '../foundry.js';
import { FoundryFailure, FoundryRefusal, runFoundry } from '../foundry.js';
import { ROLE_BY_INTENT, type Intent } from '../harness/boot.js';
import type { HarnessHost } from '../harness/host.js';
import { deliverableGallery, listTasks, readDeliverable, showTask } from '../reads.js';
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

export function registerIpc(
  binding: Omit<Binding, 'task' | 'session'>,
  harness?: {
    host: HarnessHost;
    window: () => BrowserWindow | null;
    /** Told on every change, so a resize can put the view back where it was. */
    remember: (visible: boolean) => void;
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

  if (!harness) return;

  ipcMain.handle(CHANNELS.harnessStatus, () =>
    answer(async () => ({ origin: await harness.host.start() })),
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

  ipcMain.handle(CHANNELS.workbenchVisible, (_event, visible: unknown) =>
    answer(async () => {
      const shown = Boolean(visible);
      harness.remember(shown);
      const window = harness.window();
      if (window) harness.host.place(window, shown);
      return { visible: shown };
    }),
  );
}
