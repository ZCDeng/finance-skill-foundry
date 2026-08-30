import { ipcMain } from 'electron';

import type { Binding } from '../foundry.js';
import { FoundryFailure, FoundryRefusal } from '../foundry.js';
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

export function registerIpc(binding: Omit<Binding, 'task' | 'session'>): void {
  ipcMain.handle(CHANNELS.tasks, () => answer(() => listTasks(binding)));

  ipcMain.handle(CHANNELS.task, (_event, task: unknown) =>
    answer(() => showTask({ ...binding, task: taskId(task) })),
  );

  ipcMain.handle(CHANNELS.gallery, () => answer(() => deliverableGallery(binding)));

  ipcMain.handle(CHANNELS.deliverableText, (_event, task: unknown, sha: unknown) =>
    answer(() => readDeliverable({ ...binding, task: taskId(task) }, String(sha ?? ''))),
  );
}
