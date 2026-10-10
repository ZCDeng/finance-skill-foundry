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
  /** Which example this task is (`legacy` is the 6 月 one from before the pack); null for a real task. */
  sample?: 'practice' | 'reference' | 'next_month' | 'legacy' | null;
  /** Made from an older example pack than the one installed. */
  sample_outdated?: boolean;
  /** False while the reference is still being built. */
  sample_ready?: boolean;
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
  | { type: 'export'; key: string; at: string; task: TaskRow; exported: AnalysisExportRow }
  | { type: 'chart'; key: string; at: string; task: TaskRow; chart: ChartRow }
  | { type: 'workbook'; key: string; at: string; task: TaskRow; output: WorkbookOutputRow }
  | { type: 'collection'; key: string; at: string; task: TaskRow; run: CollectionRunRow };

/** One 归档图: a chart saved from a run, with the names of the files that run read. */
export interface ChartRow {
  id: string;
  label: string;
  run_id: string | null;
  created_at: string;
  datasets: string[];
}

/** One 写回 Excel copy: a new workbook made from a snapshot and a reviewed patch. */
export interface WorkbookOutputRow {
  id: string;
  filename: string;
  sha256: string;
  created_at: string;
  /** The snapshot it was written from, by name. */
  dataset: string;
  applied: number;
  kept: number;
}

/** One 收缴率 run, with the 口径 it ran under: confirmed, the default nobody confirmed, or a trial. */
export interface CollectionRunRow {
  id: string;
  created_at: string;
  run_by: string | null;
  as_of: string;
  group_by: string[];
  caliber: { version: number | null; status: 'confirmed' | 'default' | 'trial'; differs: string[] };
  inputs: Record<string, string>;
  figures: Record<string, string | null>;
}

/** One to-do on 总览: a blocking line of a task's month-close status, or a 收费明细 / 口径 waiting on the manager. */
export interface OverviewTodo {
  kind: 'scope' | 'source' | 'structure' | 'controls' | 'exceptions' | 'review' | 'collection' | 'signoff';
  text: string;
  /** Where on the task it is handled: scope, datasets, structure, controls, results, drafts or billing. */
  target?: string;
}

/** A board card 总览 counts in 「本月已为你自动重算 N 张卡」 (foundry/overview.py _dashboard_overview). */
export interface OverviewRecomputed {
  card_id: string;
  title: string;
  at: string;
  changed: boolean;
  change: string;
  state: 'pinned' | 'accepted';
  /** A scenario card (回款情景) is never accepted; it is only looked at. */
  kind?: 'figure' | 'rank' | 'bridge' | 'scenario';
  carried_from: string | null;
}

/** One active task on 总览, with its month-close line as `finance-close-status` gives it. */
export interface OverviewTask {
  task: TaskRow;
  headline?: { state: string; text: string; detail?: string };
  blocks?: { key: string; label: string; state: 'done' | 'attention' | 'blocked' | 'not_started' }[];
  conclusion?: { level: string; text: string };
  todo: OverviewTodo[];
  /** The board's cards last run again on newer files or carried from another task, with what changed. */
  dashboard?: { recomputed: OverviewRecomputed[] };
  /** The example reference task is still being built. */
  building?: boolean;
  /** This task could not be read; the others still are. */
  error?: string;
}

/** What `overview` answers. */
export interface Overview {
  schema_version: 1;
  tasks: OverviewTask[];
  todo_count: number;
}

/** What `library-detail` answers for one draft: its text, its checks, what it rests on and the task's versions. */
export interface LibraryDetail {
  schema_version: 1;
  task_id: string;
  draft: {
    draft_id: string; revision: number; title: string; created_at: string;
    review_status: string | null; publication_status: string | null; parent_id: string | null; body: string;
  };
  checks: { key: string; label: string; status: string }[];
  rests_on: {
    run_id: string; label: string; seq?: number | null; created_at?: string | null; execution_status?: string | null;
    missing?: boolean; datasets: { id: string; name: string; hash: string }[];
  }[];
  requirements: { seq: number | null; scope: Record<string, unknown> } | null;
  versions: { draft_id: string; revision: number; title: string; created_at: string }[];
}

/** The read surface, one entry per screen question. */
export const READS = {
  tasks: 'task-list',
  task: 'task-show',
  deliverables: 'deliverables',
  analysis: 'analysis-deliverables',
  overview: 'overview',
  library: 'library',
  libraryDetail: 'library-detail',
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
 * Which kind goes first when two rows share a second.
 *
 * An export is made after the revision it came from, so within one second it
 * goes above that revision. Between stores there is no real order at all: the
 * old flow writes elsewhere and goes last. Ranking kinds instead of guessing
 * keeps the list the same on every read.
 */
const SAME_SECOND_RANK: Record<GalleryRow['type'], number> = {
  export: 0, draft: 1, workbook: 2, chart: 3, collection: 4, deliverable: 5,
};

/** A row's own sequence inside its kind: the old flow's seq, the draft's seq, the source revision; none for the rest. */
function ordinal(row: GalleryRow): number {
  if (row.type === 'deliverable') return row.row.seq;
  if (row.type === 'draft') return row.draft.seq;
  if (row.type === 'export') return row.exported.revision;
  return 0;
}

/**
 * 成果库's order: newest first, and total.
 *
 * Two old-flow rows compare by time, then seq, so a brief and a workpaper
 * filed in one instant keep their own order; everything else falls through
 * to the kind and then the key, so the order never depends on which task or
 * which store answered first.
 */
export function newestFirst(a: GalleryRow, b: GalleryRow): number {
  if (a.at !== b.at) return a.at < b.at ? 1 : -1;
  if (a.type !== b.type) return SAME_SECOND_RANK[a.type] - SAME_SECOND_RANK[b.type];
  const later = ordinal(b) - ordinal(a);
  if (later !== 0) return later;
  return a.key < b.key ? -1 : a.key > b.key ? 1 : 0;
}

/**
 * 成果库: every version and file the tasks outside the trash produced, as one list.
 *
 * One `library` call reads every task in one process; it used to be two
 * processes per task, which a store with twenty tasks felt. The CLI decides
 * nothing here either: each row carries the state its own store saved.
 */
export async function galleryRows(binding: Omit<Binding, 'task'>, env?: FoundryEnv): Promise<GalleryRow[]> {
  const rows = await runFoundryJson<GalleryRow[]>(binding, READS.library, [], env);
  return [...rows].sort(newestFirst);
}

/** 总览: every active task's month-close line and what is waiting on the manager, in one process. */
export function overviewRows(binding: Omit<Binding, 'task'>, env?: FoundryEnv): Promise<Overview> {
  return runFoundryJson<Overview>(binding, READS.overview, [], env);
}

/** One draft as 成果库's side panel shows it. The renderer names a task and a draft id, nothing else. */
export async function libraryDetail(binding: Binding, draftId: string, env?: FoundryEnv): Promise<LibraryDetail> {
  if (!/^[0-9a-f]{32}$/.test(draftId)) throw new Error(`not a draft id: ${draftId}`);
  return runFoundryJson<LibraryDetail>(binding, READS.libraryDetail, ['--draft', draftId], env);
}

/** Where a 写回 Excel copy was filed, from its id; the CLI checks its bytes against its record. */
export async function workbookOutputPath(binding: Binding, outputId: string, env?: FoundryEnv): Promise<string> {
  if (!/^[0-9a-f]{32}$/.test(outputId)) throw new Error(`not a workbook output id: ${outputId}`);
  const found = await runFoundryJson<{ path: string }>(binding, 'workbook-output-path', ['--output', outputId], env);
  return found.path;
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
