/**
 * Every view this app draws, as the CLI call that answers it.
 *
 * The map is the contract: a screen that wants something not in here needs a new
 * read-only subcommand on the CLI, not a file read from this process. `READS` is
 * exported so a test can assert that every registered channel resolves to one of
 * these and nothing else.
 */

import { type Binding, type FoundryEnv, runFoundry, runFoundryJson } from './foundry.js';

/** One row of `task-list`. */
export interface TaskRow {
  id: string;
  title: string;
  period: string | null;
  skill_id: string | null;
  created_at: string;
  windows: number;
}

/** One archived input, derived by the CLI from the window's own manifest. */
export interface InputRow {
  role: string;
  origin_path: string | null;
  archived: string;
  sha256: string;
  bytes: number | null;
  present: boolean;
  derived_from?: string | null;
}

export interface WindowRow {
  window_id: string;
  reason: 'initial' | 'reimport';
  at: string;
  state: 'Open' | 'Imported' | 'Locked' | 'Briefed' | 'FollowUp';
  inputs: InputRow[];
}

export interface SessionRow {
  session_id: string;
  role: 'author' | 'period' | 'followup';
  opened_at: string;
  /** What the leader actually asked, when the operator wrote it down. */
  leader_verbatim?: string;
}

export interface DeliverableRow {
  seq: number;
  kind: 'brief' | 'workpaper' | 'export';
  window_id: string;
  sha256: string;
  bytes: number;
  cause: string;
  session_id: string | null;
  at: string;
}

export interface TaskDetail {
  task: Omit<TaskRow, 'windows'>;
  windows: WindowRow[];
  sessions: SessionRow[];
  deliverables: DeliverableRow[];
}

/** The read surface, one entry per screen question. */
export const READS = {
  tasks: 'task-list',
  task: 'task-show',
  deliverables: 'deliverables',
} as const;

export type ReadName = keyof typeof READS;

export function listTasks(binding: Binding, env?: FoundryEnv): Promise<TaskRow[]> {
  return runFoundryJson<TaskRow[]>(binding, READS.tasks, [], env);
}

export function showTask(binding: Binding, env?: FoundryEnv): Promise<TaskDetail> {
  return runFoundryJson<TaskDetail>(binding, READS.task, [], env);
}

export function listDeliverables(binding: Binding, env?: FoundryEnv): Promise<DeliverableRow[]> {
  return runFoundryJson<DeliverableRow[]>(binding, READS.deliverables, [], env);
}

/**
 * The deliverable gallery, newest first, with the task each version belongs to.
 *
 * Composed here from two calls rather than added to the CLI as a third: the
 * gallery is a presentation question ("what has this machine produced lately"),
 * and the store already answers both halves. A CLI command for it would exist
 * only to save this loop.
 */
export async function deliverableGallery(
  binding: Omit<Binding, 'task'>,
  env?: FoundryEnv,
): Promise<{ task: TaskRow; row: DeliverableRow }[]> {
  const tasks = await listTasks(binding, env);
  const gathered: { task: TaskRow; row: DeliverableRow }[] = [];
  for (const task of tasks) {
    for (const row of await listDeliverables({ ...binding, task: task.id }, env)) {
      gathered.push({ task, row });
    }
  }
  // Newest first, and `seq` breaks the ties rather than leaving them to input
  // order. Timestamps are second-resolution and `emit-brief` files the brief and
  // the workpaper in the same instant, so a tie is the normal case, not an edge:
  // sorting on `at` alone leaves those two ascending inside a descending list.
  return gathered.sort((a, b) => {
    if (a.row.at !== b.row.at) return a.row.at < b.row.at ? 1 : -1;
    return b.row.seq - a.row.seq;
  });
}

/**
 * The bytes of one archived version, for the reader pane.
 *
 * Goes through the CLI like everything else. The app knows a sha256, never a
 * path, so there is no way for a renderer string to name a file on disk.
 */
export function readDeliverable(
  binding: Binding,
  sha256: string,
  env?: FoundryEnv,
): Promise<string> {
  if (!/^[0-9a-f]{64}$/.test(sha256)) throw new Error(`not a sha256: ${sha256}`);
  return runFoundry(binding, 'deliverable-text', ['--sha', sha256], env);
}
