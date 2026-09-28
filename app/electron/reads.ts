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
  lifecycle_status?: 'active' | 'archived' | 'trashed';
  archived_at?: string;
  trashed_at?: string;
  restored_at?: string;
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
  role: 'author' | 'period' | 'followup' | 'analysis';
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

/** The newest version of one draft revision chain, with the state saved on that version. */
export interface AnalysisDraftRow {
  draft_id: string;
  /** The 修订 N the 文稿 tab shows: position among all of the task's drafts. */
  revision: number;
  /** How many versions the chain holds. */
  versions: number;
  title: string;
  created_at: string;
  seq: number;
  review_status: string;
  publication_status: string;
}

export type ExportFormat = 'md' | 'xlsx' | 'docx' | 'pdf' | 'html';

/** One filed export, with the state of the revision it was exported from. */
export interface AnalysisExportRow {
  export_id: string;
  draft_id: string;
  revision: number;
  title: string;
  format: ExportFormat;
  content_mode: 'management' | 'audit' | null;
  sha256: string;
  created_at: string;
  review_status: string;
  publication_status: string;
  /** 「分析草稿·待复核」 unless the source revision is accepted and archived; empty otherwise. */
  review_marker: string;
}

/** What `analysis-deliverables` answers for one task. */
export interface AnalysisDeliverables {
  task_id: string;
  drafts: AnalysisDraftRow[];
  exports: AnalysisExportRow[];
}

/**
 * One row of 成果库. `key` is the kind and that kind's own id: a draft's seq and
 * an old-flow version's seq count in different stores, so neither is a key.
 */
export type GalleryRow =
  | { type: 'deliverable'; key: string; at: string; task: TaskRow; row: DeliverableRow }
  | { type: 'draft'; key: string; at: string; task: TaskRow; draft: AnalysisDraftRow }
  | { type: 'export'; key: string; at: string; task: TaskRow; exported: AnalysisExportRow };

/** The read surface, one entry per screen question. */
export const READS = {
  tasks: 'task-list',
  task: 'task-show',
  deliverables: 'deliverables',
  analysis: 'analysis-deliverables',
} as const;

export type ReadName = keyof typeof READS;
export type TaskLifecycleFilter = 'active' | 'archived' | 'trashed' | 'all';

export function listTasks(binding: Binding, env?: FoundryEnv, lifecycle: TaskLifecycleFilter = 'active'): Promise<TaskRow[]> {
  return runFoundryJson<TaskRow[]>(binding, READS.tasks, lifecycle === 'active' ? [] : ['--lifecycle', lifecycle], env);
}

export function showTask(binding: Binding, env?: FoundryEnv): Promise<TaskDetail> {
  return runFoundryJson<TaskDetail>(binding, READS.task, [], env);
}

export function listDeliverables(binding: Binding, env?: FoundryEnv): Promise<DeliverableRow[]> {
  return runFoundryJson<DeliverableRow[]>(binding, READS.deliverables, [], env);
}

export function listAnalysisDeliverables(binding: Binding, env?: FoundryEnv): Promise<AnalysisDeliverables> {
  return runFoundryJson<AnalysisDeliverables>(binding, READS.analysis, [], env);
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
  known?: TaskRow[],
): Promise<{ task: TaskRow; row: DeliverableRow }[]> {
  const tasks = known ?? await listTasks(binding, env);
  const answers = await perTask(tasks, (task) => listDeliverables({ ...binding, task: task.id }, env));
  const gathered = tasks.flatMap((task, index) => answers[index].map((row) => ({ task, row })));
  // Newest first, and `seq` breaks the ties rather than leaving them to input
  // order. Timestamps are second-resolution and `emit-brief` files the brief and
  // the workpaper in the same instant, so a tie is the normal case, not an edge:
  // sorting on `at` alone leaves those two ascending inside a descending list.
  return gathered.sort((a, b) => {
    if (a.row.at !== b.row.at) return a.row.at < b.row.at ? 1 : -1;
    return b.row.seq - a.row.seq;
  });
}

/** How many per-task CLI reads 成果库 runs at once; each is its own foundry process. */
const TASK_READS_AT_ONCE = 4;

/**
 * One read per task, a few at a time, answered in task order. They start in
 * task order too, and the first failure stops new ones from starting.
 */
async function perTask<T>(tasks: TaskRow[], read: (task: TaskRow) => Promise<T>): Promise<T[]> {
  const answers: T[] = new Array(tasks.length);
  let next = 0;
  let failed = false;
  const worker = async () => {
    while (!failed && next < tasks.length) {
      const index = next++;
      try {
        answers[index] = await read(tasks[index]);
      } catch (error) {
        failed = true;
        throw error;
      }
    }
  };
  await Promise.all(Array.from({ length: Math.min(TASK_READS_AT_ONCE, tasks.length) }, worker));
  return answers;
}

/**
 * Which kind goes first when two rows share a second.
 *
 * An export is made after the revision it came from, so within one second it
 * goes above that revision. Between stores there is no real order at all: the
 * old flow writes elsewhere and goes last. Ranking kinds instead of guessing
 * keeps the list the same on every read.
 */
const SAME_SECOND_RANK: Record<GalleryRow['type'], number> = { export: 0, draft: 1, deliverable: 2 };

/** A row's own sequence inside its kind: the old flow's seq, the draft's seq, the source revision. */
function ordinal(row: GalleryRow): number {
  return row.type === 'deliverable' ? row.row.seq : row.type === 'draft' ? row.draft.seq : row.exported.revision;
}

/**
 * 成果库's order: newest first, and total.
 *
 * Two old-flow rows compare exactly as `deliverableGallery` does -- time, then
 * seq -- and everything else falls through to the kind and then the key, so
 * the order never depends on which task or which store answered first.
 */
export function newestFirst(a: GalleryRow, b: GalleryRow): number {
  if (a.at !== b.at) return a.at < b.at ? 1 : -1;
  if (a.type !== b.type) return SAME_SECOND_RANK[a.type] - SAME_SECOND_RANK[b.type];
  const later = ordinal(b) - ordinal(a);
  if (later !== 0) return later;
  return a.key < b.key ? -1 : a.key > b.key ? 1 : 0;
}

/**
 * 成果库: the old flow's versions, the newest draft of each revision chain, and
 * every filed export, as one list.
 *
 * Composed here for the same reason as `deliverableGallery`: each store already
 * answers its half. The analysis half is its own read because drafts and
 * exports live in the analysis store, and it carries their review and
 * publication state as the store saved it; nothing here decides a status.
 */
export async function galleryRows(binding: Omit<Binding, 'task'>, env?: FoundryEnv): Promise<GalleryRow[]> {
  const tasks = (await listTasks(binding, env, 'all')).filter((task) => (task.lifecycle_status ?? 'active') !== 'trashed');
  const rows: GalleryRow[] = (await deliverableGallery(binding, env, tasks)).map(({ task, row }) => ({
    type: 'deliverable', key: `deliverable:${task.id}:${row.seq}`, at: row.at, task, row,
  }));
  const answers = await perTask(tasks, (task) => listAnalysisDeliverables({ ...binding, task: task.id }, env));
  for (const [index, task] of tasks.entries()) {
    const { drafts, exports } = answers[index];
    for (const draft of drafts) {
      rows.push({ type: 'draft', key: `draft:${draft.draft_id}`, at: draft.created_at, task, draft });
    }
    for (const exported of exports) {
      rows.push({ type: 'export', key: `export:${exported.export_id}`, at: exported.created_at, task, exported });
    }
  }
  return rows.sort(newestFirst);
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

/**
 * Where a version was filed, for the one kind this app does not render itself.
 *
 * A workbook opens in the operator's own spreadsheet software, which means
 * something has to name a file. It is still the CLI that names it, and still
 * from a digest: a renderer string reaches an archived version of this task or
 * it reaches nothing.
 *
 * The extension is checked here rather than passed through. `--ext` reaches
 * argv, and a renderer that could put anything in it could ask for a
 * neighbouring file that happened to share a digest stem.
 */
export async function deliverablePath(
  binding: Binding,
  sha256: string,
  ext: string,
  env?: FoundryEnv,
): Promise<string> {
  if (!/^[0-9a-f]{64}$/.test(sha256)) throw new Error(`not a sha256: ${sha256}`);
  if (!ARCHIVED_EXTS.has(ext)) throw new Error(`not an archived extension: ${ext}`);
  const found = await runFoundry(binding, 'deliverable-path', ['--sha', sha256, '--ext', ext], env);
  return found.trim();
}

/**
 * Where this task filed one analysis export, for the operator's own software.
 *
 * The same rule as `deliverablePath`: the renderer passes a digest and a format
 * from a fixed list, both checked here before they reach argv, and the CLI
 * answers with a file only if this task filed those bytes under that format
 * and they still match their receipt.
 */
export async function analysisExportPath(
  binding: Binding,
  sha256: string,
  format: string,
  env?: FoundryEnv,
): Promise<string> {
  if (!/^[0-9a-f]{64}$/.test(sha256)) throw new Error(`not a sha256: ${sha256}`);
  if (!EXPORT_FORMATS.has(format)) throw new Error(`not an export format: ${format}`);
  const found = await runFoundryJson<{ path: string }>(
    binding, 'analysis-export-path', ['--sha', sha256, '--format', format], env,
  );
  return found.path;
}

export async function sourceLocatorPreviewFile(
  binding: Binding,
  spec: Record<string, unknown>,
  env?: FoundryEnv,
): Promise<string> {
  const found = await runFoundry(binding, 'source-locator-preview-file', ['--spec', JSON.stringify(spec)], env);
  return found.trim();
}

/** Every extension the store files a deliverable under. */
const ARCHIVED_EXTS = new Set(['.md', '.xlsx']);

/** Every format the analysis store files an export under. */
const EXPORT_FORMATS = new Set<string>(['md', 'xlsx', 'docx', 'pdf', 'html'] satisfies ExportFormat[]);
