/**
 * Every change this window may make, as the CLI call that makes it.
 *
 * The sibling of `reads.ts`, kept apart from it because that file's contract is
 * "one entry per screen question" and a mutation is not a question. Same rule
 * underneath: `foundry/` is the sole mutator (KTD2), so this process names a
 * subcommand and arguments and never touches the catalog.
 *
 * The list is deliberately one line long. A window that can create the first
 * task is a window an operator can start from; a window that can also import,
 * lock and emit would be a second front end to a store whose ordering rules
 * live in the CLI. Those stay where a session drives them.
 */

import { type Binding, type FoundryEnv, runFoundry } from './foundry.js';

/** The write surface. Exported so a test can assert nothing else is reachable. */
export const WRITES = {
  taskNew: 'task-new',
  taskArchive: 'task-archive',
  taskTrash: 'task-trash',
  taskRestore: 'task-restore',
} as const;

export type WriteName = keyof typeof WRITES;

export interface NewTask {
  title: string;
  /** The period this task closes, e.g. `2026-08`. Empty means the CLI's own default. */
  period?: string;
}

/**
 * Create a task and hand back its id.
 *
 * `task-new` prints the id and nothing else, so the trim is the parse. A blank
 * line back means the CLI succeeded and wrote nothing, which is a contract break
 * rather than a task with an empty id -- the screen would then ask for a detail
 * view of `''` and get a validation failure naming the wrong thing.
 */
export async function newTask(
  binding: Omit<Binding, 'task' | 'session'>,
  spec: NewTask,
  env?: FoundryEnv,
): Promise<{ id: string }> {
  const rest = ['--title', spec.title, ...(spec.period ? ['--period', spec.period] : [])];
  const id = (await runFoundry(binding, WRITES.taskNew, rest, env)).trim();
  if (!/^[0-9a-f]{32}$/.test(id)) throw new Error(`task-new did not print a task id: ${id.slice(0, 200)}`);
  return { id };
}

export async function changeTaskLifecycle(
  binding: Binding,
  command: 'task-archive' | 'task-trash' | 'task-restore',
  env?: FoundryEnv,
): Promise<{ task_id: string; lifecycle_status: 'active' | 'archived' | 'trashed' }> {
  return JSON.parse(await runFoundry(binding, command, [], env)) as {
    task_id: string;
    lifecycle_status: 'active' | 'archived' | 'trashed';
  };
}
