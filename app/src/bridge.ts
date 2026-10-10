/**
 * What the preload exposes, as the renderer sees it.
 *
 * Absent outside Electron, which is what makes the views testable and what the
 * dev server shows before main is up. Every method answers with the same
 * `{ok}` envelope: a foundry refusal is a state a screen renders, not a throw.
 */
export type Answer<T> =
  | { ok: true; value: T }
  | { ok: false; refused: boolean; message: string };

export interface TaskRow {
  id: string;
  title: string;
  period: string | null;
  skill_id: string | null;
  created_at: string;
  lifecycle_status?: TaskLifecycleStatus;
  archived_at?: string;
  trashed_at?: string;
  restored_at?: string;
  windows: number;
  /** Which example this task is (`legacy` is the 6 月 one from before the pack); null for a real task. */
  sample?: SampleKind | null;
  /** Made from an older example pack than the one installed. */
  sample_outdated?: boolean;
  /** False while the reference is still being built. */
  sample_ready?: boolean;
}

export type SampleKind = 'practice' | 'reference' | 'next_month' | 'legacy';

/** 收费明细 (foundry/billing_detail.py): a 应收明细, 实收明细 or 房产主数据 table, in DuckDB. */
export type BillingKind = 'receivable' | 'receipt' | 'property';
export type BillingCommand = 'detail-list' | 'detail-confirm' | 'collection-caliber' | 'collection-caliber-confirm'
  | 'collection-run' | 'collection-run-read' | 'collection-run-list' | 'collection-state' | 'collection-drill';
export interface BillingMapping { mapping: Record<string, string>; by: string; at: string }
export interface BillingDetail {
  id: string; kind: BillingKind; name: string; created_at: string; added_by?: string;
  files: { name: string; rows?: number; encoding: string; bytes: number }[];
  columns: string[]; row_count: number;
  proposal: BillingMapping | null; confirmation: BillingMapping | null;
  /** The standard fields, with the name the guide uses. */
  fields: { field: string; label: string; required: boolean }[];
  /** Requirements the chosen columns do not meet yet, by label (应收净额/应收原额). */
  missing: string[];
}
export interface CollectionCaliberParams {
  year_start_month: number; total_method: 'bounded' | 'all_receipts';
  related_owners: string[]; exclude_related: boolean; excluded_fee_items: string[];
}
export interface CollectionCaliberVersion {
  version: number; params: CollectionCaliberParams; note: string;
  status: 'proposed' | 'confirmed' | 'superseded'; by: string; at: string; confirmed_at?: string;
}
export interface CollectionCaliber {
  defaults: CollectionCaliberParams; confirmed: CollectionCaliberVersion | null; proposed: CollectionCaliberVersion | null;
  effective: CollectionCaliberParams; versions: CollectionCaliberVersion[];
}
/** Rates are decimals as text (0.8212), amounts are yuan as text; null where the base is zero. */
export interface CollectionFigures {
  receivable: string; collected: string; collection_rate_current: string | null;
  month_receivable: string; month_collected: string; collection_rate_month: string | null;
  arrears_opening: string; arrears_collected: string; arrears_recovery_rate: string | null;
  collection_rate_total: string | null; outstanding: string; advance_balance: string;
  waiver: string; waiver_rate: string | null; households: number; households_settled: number; household_rate: string | null;
  properties_billed: number;
  reported?: Record<string, { reported: string; computed: string | null; difference_points: string | null }>;
}
export interface CollectionIssue { code: string; rows: number; amount: string; lines: string[] }
export interface CollectionRunCaliber { version: number | null; status: 'confirmed' | 'default' | 'trial'; differs: string[] }
export interface CollectionRun {
  id: string; created_at: string; run_by?: string;
  params: CollectionCaliberParams & { as_of: string; group_by: string[]; reported: Record<string, string> };
  caliber: CollectionRunCaliber;
  inputs: Partial<Record<BillingKind, { id: string; name: string }>>;
  result: {
    window: { year_start: string; as_of: string; as_of_period: string };
    figures: CollectionFigures;
    related?: { owners: string[]; only: CollectionFigures; excluded: CollectionFigures };
    groups?: { key: Record<string, string | null>; figures: CollectionFigures }[];
    quality: CollectionIssue[];
    labels?: CollectionIssue[];
  };
}
/** 往下拆 (foundry/billing_drill.py): the rates a drill takes apart, and one level of it. */
export type DrillFigure = 'collection_rate_current' | 'collection_rate_month' | 'arrears_recovery_rate' | 'collection_rate_total';
export interface DrillSums { base: string; done: string; outstanding: string; rate: string | null }
export interface DrillRow extends DrillSums {
  /** The name the next level is opened by; null is the bills with that column empty. */
  value: string | null; label: string;
  /** Households with something owed toward the rate, on a level above the bills. */
  properties?: number;
  /** A bill: what it is, where its 账期 falls and the export lines it was read from. */
  fee_item?: string | null; period?: string; place?: 'current' | 'arrears'; lines?: string[]; line_count?: number; receipts?: string[]; receipt_count?: number;
}
export interface DrillLevel {
  run_id: string; figure: DrillFigure; label: string; base_label: string; done_label: string; as_of: string; caliber: CollectionRunCaliber;
  levels: { key: string; label: string }[];
  path: (DrillSums & { level: string; value: string | null; label: string })[];
  level: { key: string; label: string };
  /** The whole, against the figure the run filed. */
  run_check: { base: string; done: string; ties: boolean };
  whole: DrillSums & { label: string };
  total: DrillSums;
  /** Whether this level's rows add up to the row it was opened from, and by how much they miss it. */
  ties: boolean; gap: { base: string; done: string };
  row_count: number; rows: DrillRow[];
}
export interface CollectionRunSummary {
  id: string; created_at: string; run_by?: string; as_of: string; group_by: string[]; caliber: CollectionRunCaliber;
  inputs: Partial<Record<BillingKind, string>>;
  figures: Pick<CollectionFigures, 'collection_rate_current' | 'arrears_recovery_rate' | 'collection_rate_total'>;
}

export type TaskLifecycleStatus = 'active' | 'archived' | 'trashed';
export type TaskLifecycleFilter = TaskLifecycleStatus | 'all';

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
  state: string;
  inputs: InputRow[];
}

export interface SessionRow {
  session_id: string;
  role: 'author' | 'period' | 'followup' | 'analysis';
  opened_at: string;
  leader_verbatim?: string;
}

export interface DeliverableRow {
  seq: number;
  kind: 'brief' | 'workpaper' | 'export';
  window_id: string;
  sha256: string;
  bytes: number;
  /**
   * The archived file's extension. Absent on rows written before workbooks
   * existed, which are all markdown -- so read it through `isWorkbook` rather
   * than comparing it directly.
   */
  ext?: string;
  cause: string;
  session_id: string | null;
  at: string;
}

/** Whether this version is a spreadsheet rather than a document to read here. */
export function isWorkbook(row: DeliverableRow): boolean {
  return (row.ext ?? '.md') === '.xlsx';
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

/**
 * One source record of 成果库: an old-flow version, the newest draft of a
 * revision chain, or a filed export. `key` is the kind and that kind's own id.
 * The list groups them by task and folds each revision's draft and exports into one row.
 */
export type GalleryRow =
  | { type: 'deliverable'; key: string; at: string; task: TaskRow; row: DeliverableRow }
  | { type: 'draft'; key: string; at: string; task: TaskRow; draft: AnalysisDraftRow }
  | { type: 'export'; key: string; at: string; task: TaskRow; exported: AnalysisExportRow }
  | { type: 'chart'; key: string; at: string; task: TaskRow; chart: ChartRow }
  | { type: 'workbook'; key: string; at: string; task: TaskRow; output: WorkbookOutputRow }
  | { type: 'collection'; key: string; at: string; task: TaskRow; run: CollectionRunRow }
  | { type: 'dashboard'; key: string; at: string; task: TaskRow; snapshot: DashboardSnapshotRow };

/** One 看板快照 (electron/reads.ts): the accepted cards it shows, and the ones it left out and why. */
export interface DashboardSnapshotRow {
  id: string;
  format: 'pdf' | 'pptx' | 'xlsx';
  filename: string;
  sha256: string;
  created_at: string;
  title: string;
  cards: string[];
  beyond: string[];
  left_out: { pinned: string[]; scenario: string[] };
}

/** A 看板快照's format as 成果库 and 总览 name it. */
export const SNAPSHOT_FORMAT_WORDS: Record<DashboardSnapshotRow['format'], string> = { pdf: 'PDF 一页纸', pptx: 'PPT 一页', xlsx: 'Excel' };

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
  /** A what-if card (回款情景, 倒推, 敏感性表) is never accepted; it is only looked at. */
  kind?: 'figure' | 'rank' | 'bridge' | 'scenario' | 'goal' | 'sensitivity';
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

/**
 * Where a figure in 本月三句话 came from (foundry/month_brief.py), or the place its words open: a board card as it
 * shows now, before its recompute or the change between; a row of a run; a run's result page; a place in the task.
 */
export type BriefRef =
  | { kind: 'card' | 'card_before' | 'card_change'; card_id: string }
  | { kind: 'row'; run_id: string; match: Record<string, string>; column: string; metric: string }
  | { kind: 'result'; run_id: string }
  | { kind: 'open'; target: string };

/** A run of words in a line; one with a `ref` is a figure or a link, and a rewording keeps it as written. */
export interface BriefPart { text: string; ref?: BriefRef }

export interface BriefLine {
  key: 'change' | 'risk' | 'waiting';
  label: string;
  parts: BriefPart[];
  text: string;
  /** No 风险雷达 yet: the line offers the question that makes one. */
  ask?: 'collection-health';
  /** The line could not be read; the others still are. */
  failed?: boolean;
}

/** What `month-brief` answers: the rule's three lines, and the assistant's wording of them while their figures stand. */
export interface MonthBrief {
  schema_version: 1;
  lines: BriefLine[];
  signature: string;
  worded: { lines: Partial<Record<BriefLine['key'], string>>; by: 'manager' | 'assistant'; created_at: string } | null;
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


/** A file 成果库 can hand to the default program: a filed export by digest and format, a 写回 Excel copy or a 看板快照 by id. */
export type LibraryFile = { kind: 'export'; sha: string; format: ExportFormat } | { kind: 'workbook'; id: string } | { kind: 'dashboard'; id: string };

export type Intent = 'author' | 'period' | 'followup' | 'analysis';

/**
 * How the app's own wiring went, and what a stopped step costs.
 *
 * `consequence` is written for the person looking at the window. The step names
 * are the code's; what an operator needs is which capability is missing.
 */
export type Wiring =
  | { state: 'pending' }
  | { state: 'ready' }
  | { state: 'failed'; step: 'plugin' | 'presets' | 'attach'; message: string };

export interface HarnessStatus {
  wiring: Wiring;
  consequence: string | null;
  origin: string | null;
}

export interface Bridge {
  reportImport?(task: string, options?: import('../electron/reports/model').ReportImportOptions): Promise<Answer<import('../electron/reports/model').ReportImportResult>>;
  reportSource?(task: string, sourceId: string): Promise<Answer<{ source: import('../electron/reports/model').ReportSource; data_base64: string }>>;
  reportPreview?(task: string, document: import('../electron/reports/model').ReportDocument, title: string): Promise<Answer<{ html: string }>>;
  reportCancel?(task: string): Promise<Answer<{ cancelled: boolean; finishing?: boolean }>>;
  onReportProgress?(cb: (progress: { task: string; phase: string }) => void): () => void;
  analysisOpenOutput?(task: string, runId: string, output: string): Promise<Answer<Record<string, unknown>>>;
  analysisState?(task: string): Promise<Answer<AnalysisState>>;
  analysisAddFiles?(task: string): Promise<Answer<DatasetSnapshot[]>>;
  reportTemplatePublish?(task: string): Promise<Answer<{ template_id: string; label: string; kind: string } | { cancelled: true }>>;
  analysisReadDataset?(task: string, id: string): Promise<Answer<Record<string, unknown>>>;
  analysisSave?(task: string, spec: Record<string, unknown>): Promise<Answer<AnalysisRevision>>;
  analysisRun?(task: string, id: string): Promise<Answer<AnalysisRun>>;
  analysisDraft?(task: string, spec: Record<string, unknown>): Promise<Answer<AnalysisDraft>>;
  analysisExport?(task: string, id: string, format: import('../electron/reports/model').ReportExportFormat, mode?: 'management' | 'audit'): Promise<Answer<Record<string, unknown>>>;
  analysisMethodSave?(task: string, id: string, name: string): Promise<Answer<AnalysisMethod>>;
  analysisMethodApply?(task: string, id: string, bindings: Record<string, string>, parameters?: unknown[] | Record<string, unknown>): Promise<Answer<AnalysisRevision>>;
  financeCall?(task: string, command: FinanceCommand, spec?: Record<string, unknown>): Promise<Answer<Record<string, unknown>>>;
  sourceLocatorOpen?(task: string, spec: { fact_id: string } | { run_id: string; row: number; column?: string }): Promise<Answer<SourceLocatorResult>>;
  financeSourceRefresh?(task: string, spec: Record<string, unknown>): Promise<Answer<Record<string, unknown>>>;
  /**
   * Save a roll-forward copy where the manager picks in the save dialog. The
   * renderer names the run; main picks the place and answers with the file name only.
   */
  rollforwardExport?(task: string, runId: string, name?: string): Promise<Answer<{ cancelled?: boolean; exported?: boolean; filename?: string }>>;
  /** 看板快照: the board's accepted cards as one page or a workbook, saved where the manager picks and filed in 成果库. */
  dashboardExport?(task: string, format: import('../electron/reports/dashboard-snapshot').SnapshotFormat,
    snapshot: import('../electron/reports/dashboard-snapshot').DashboardSnapshot): Promise<Answer<{ cancelled: true } | { exported: true; format: string; path: string; snapshot_id: string }>>;
  /** Write-only: hands one user wait to the local timing log. Absent in a build without it. */
  timingLog?(entry: WaitEntry): Promise<Answer<{ written: true }>>;
  /** The window's appearance (跟随系统 / 浅色 / 深色). Absent in a build without it; the header then shows no switch. */
  appearanceGet?(): Promise<Answer<{ appearance: Appearance }>>;
  appearanceSet?(appearance: Appearance): Promise<Answer<{ appearance: Appearance }>>;
  tasks(lifecycle?: TaskLifecycleFilter): Promise<Answer<TaskRow[]>>;
  task(id: string): Promise<Answer<TaskDetail>>;
  /** 成果库: old-flow versions, the newest draft of each revision chain and every filed export, newest first. */
  gallery(): Promise<Answer<GalleryRow[]>>;
  /** 总览: every active task's month-close line and its to-dos. Absent in a build without it. */
  overview?(): Promise<Answer<Overview>>;
  /** 成果库's side panel for one draft. */
  libraryDetail?(task: string, draft: string): Promise<Answer<LibraryDetail>>;
  /** Open a filed export or a 写回 Excel copy, or show it in Finder. */
  libraryFile?(task: string, file: LibraryFile, action: 'open' | 'reveal'): Promise<Answer<{ opened?: string; shown?: string }>>;
  /**
   * Hand one filed analysis export to the default program. The renderer names
   * the task, the digest and the format; main resolves the file through the CLI.
   */
  analysisExportOpen?(task: string, sha: string, format: ExportFormat): Promise<Answer<{ opened: string }>>;
  deliverableText(task: string, sha: string): Promise<Answer<string>>;
  /**
   * Hand one archived version to whatever this machine opens it with.
   *
   * Only for the kinds this app does not render. A workbook belongs in the
   * spreadsheet software the operator already has, which is the whole reason
   * it is written as a workbook.
   */
  deliverableOpen(task: string, sha: string, ext: string): Promise<Answer<{ opened: string }>>;
  /** Render one window as a workbook and file it as a version. */
  exportWorkbook(
    task: string,
    window: string,
  ): Promise<Answer<{ sha256: string; seq: number; ext: string }>>;
  /** The one call that changes the store. Always present; the reads are useless without it. */
  taskRename?(task: string, title: string): Promise<Answer<{task_id: string; title: string}>>;
  taskArchive?(task: string): Promise<Answer<{task_id: string; lifecycle_status: TaskLifecycleStatus}>>;
  taskTrash?(task: string): Promise<Answer<{task_id: string; lifecycle_status: TaskLifecycleStatus}>>;
  taskRestore?(task: string): Promise<Answer<{task_id: string; lifecycle_status: TaskLifecycleStatus}>>;
  /** Delete one trashed task for good. */
  taskPurge?(task: string): Promise<Answer<{task_ids: string[]; lifecycle_status: 'purged'}>>;
  /** 已归档: move the confirmed ones to the trash. 回收站: delete the confirmed ones for good. */
  taskEmpty?(lifecycle: 'archived' | 'trashed', ids: string[]): Promise<Answer<{task_ids: string[]; lifecycle_status: 'trashed' | 'purged'}>>;
  taskNew(title: string, period: string): Promise<Answer<{ id: string }>>;
  /** The synthetic practice task, created once and reused. */
  taskSample?(): Promise<Answer<{ id: string; created: boolean }>>;
  /** The reference task: reused once built, or (`rebuild`) trashed and built again. Takes most of a minute. */
  taskSampleReference?(rebuild?: boolean): Promise<Answer<{ id: string; created: boolean }>>;
  /** The September practice task, made once and reused. */
  taskSampleNext?(): Promise<Answer<{ id: string; created: boolean }>>;
  /** Every practice task to the trash; real tasks are never touched. */
  taskSampleRemove?(): Promise<Answer<{ trashed: string[] }>>;
  /** The 补充数据模板 into a new folder inside one the manager picks, then that folder opened. */
  templatesExport?(): Promise<Answer<{ folder: string } | { cancelled: true }>>;
  /** 收费明细: the example's three detail tables into a practice task; columns left for the manager to confirm. */
  taskSampleBilling?(task: string): Promise<Answer<{ task_id: string; details: Partial<Record<BillingKind, { id: string; name: string; rows: number; confirmed: boolean }>> }>>;
  /** 收费明细: CSV files the manager picks (several only when they are one table split up), as one detail table. */
  billingAdd?(task: string, kind: BillingKind): Promise<Answer<BillingDetail | { cancelled: true }>>;
  billingCall?(task: string, command: BillingCommand, spec?: Record<string, unknown>): Promise<Answer<unknown>>;
  /** 往下拆: one level, every row, as Excel where the manager picks. */
  billingDrillExport?(task: string, spec: { run: string; figure: DrillFigure; path: (string | null)[]; name: string }): Promise<Answer<{ cancelled: true } | { exported: true; rows: number }>>;
  /** Absent when this build has no harness install to embed. */
  harnessStatus?(): Promise<Answer<HarnessStatus>>;
  harnessOpen?(
    intent: Intent,
    task: string,
    seed?: { windowId?: string; briefSha?: string | null; verbatim?: string; draftId?: string; submit?: boolean; requestId?: string },
  ): Promise<Answer<{ sessionId: string; preset: string; submitted?: boolean; blockedReason?: string }>>;
  harnessLayout?(layout: {x: number; y: number; width: number; height: number; revision: number}): Promise<Answer<{accepted: boolean}>>;
  paneVisible?(screen: string): Promise<Answer<{ screen: string }>>;
  /**
   * Main pushes here when the fence cancelled a call the embedded page made.
   *
   * The only channel that travels that way, and the only one that does not
   * answer with `Answer<T>`: nothing asked for it. Returns its unsubscribe.
   */
  onHarnessRefused?(cb: (reason: string) => void): () => void;
  onHarnessExited?(cb: () => void): () => void;
  /** 打开结果 or 钉到看板 on a card in the assistant's answer, checked by the host before it is passed on. */
  onHarnessCardAction?(cb: (action: HarnessCardAction) => void): () => void;
  /** Absent when this build has no harness to embed Formulator beside. */
  formulatorLaunch?(): Promise<Answer<LaunchSpec>>;
  formulatorStop?(): Promise<Answer<{ stopped: boolean }>>;
  formulatorStatus?(): Promise<Answer<{ running: LaunchSpec | null }>>;
  /**
   * A read-only look at one archived workbook, in the Univer viewer.
   *
   * Absent when this build carries no Univer bundle. Main starts the gateway
   * for as long as the preview is open and takes it down on close; the
   * renderer never sees a path, only the task and the digest it already has.
   */
  previewOpen?(task: string, sha: string, ext: string): Promise<Answer<PreviewSpec>>;
  previewClose?(): Promise<Answer<{ stopped: boolean }>>;
  previewStatus?(): Promise<Answer<{ running: PreviewSpec | null }>>;
}

/** What a preview reports back once the viewer is up. */
export interface PreviewSpec {
  /** The task the workbook belongs to, and the digest that names the version. */
  task: string;
  sha256: string;
  /** The viewer origin, so the strip can say where it is looking. */
  origin: string;
  excel_range?: string;
}

/**
 * What a locator preview names once Univer is up: the task and the digest,
 * and the cell the operator asked about. No origin: the renderer reads that
 * from `previewStatus`, the same way every other preview does.
 */
export type LocatorPreviewSpec = Omit<PreviewSpec, 'origin'>;

/**
 * What `sourceLocatorOpen` answers. Path-free by construction on the main
 * side, and origin-free by type here: nothing in it says where a server is.
 */
export interface SourceLocatorResult extends Partial<LocatorPreviewSpec> {
  status: 'ok' | 'locator_unavailable' | 'locator_forbidden' | string;
  locator?: Record<string, unknown>;
  preview?: { available?: boolean; handle?: string };
  viewer?: 'univer' | 'pdf' | 'snapshot';
}

/** What `launch-formulator` reports back. */
export interface LaunchSpec {
  url: string;
  home: string;
  /** Present only when the kit could not confirm the served process is this window's. */
  identity?: string;
}

export function bridge(): Bridge | null {
  return (globalThis as { foundry?: Bridge }).foundry ?? null;
}

/** A click on a card in the assistant's answer that the window acts on (electron/harness/cardAction.ts). */
export type HarnessCardAction = import('../electron/harness/cardAction').CardAction;
export type WaitKind = import('../electron/ipc/contract').WaitKind;
export type WaitOutcome = import('../electron/ipc/contract').WaitOutcome;
/** One user wait as the timing log takes it: what, how it ended, and two durations. */
export type WaitEntry = import('../electron/timing').WaitEntry;
export type Appearance = import('../electron/appearance').Appearance;

/**
 * Times one user wait: from the call, made on the click, to the end of `work`,
 * the page read back after it included. `work` says how it ended through
 * `note`, with the run record whose engine time it carries; otherwise it is
 * ok when `work` returns and an error when it throws. The log is best effort:
 * a build without it, or a write that fails, changes nothing on screen.
 */
export async function timeWait<T>(kind: WaitKind, work: (note: (outcome: WaitOutcome, run?: unknown) => void) => Promise<T>): Promise<T> {
  const started = performance.now();
  let outcome: WaitOutcome | undefined;
  let run: unknown;
  try {
    return await work((ended, record) => { outcome = ended; run = record; });
  } catch (failure) {
    outcome ??= 'error';
    throw failure;
  } finally {
    const seconds = (run as { duration_seconds?: unknown } | undefined)?.duration_seconds;
    const entry: WaitEntry = {
      kind, outcome: outcome ?? 'ok', waitMs: Math.round(performance.now() - started),
      engineMs: typeof seconds === 'number' && Number.isFinite(seconds) ? Math.round(seconds * 1000) : null,
    };
    const api = bridge();
    if (api?.timingLog) void Promise.resolve().then(() => api.timingLog!(entry)).catch(() => {});
  }
}

/** Short forms for a screen: a digest is an identity, not a number to read. */
export const shortSha = (sha: string) => sha.slice(0, 12);

export function bytes(count: number | null): string {
  if (count === null) return '';
  if (count < 1024) return `${count} B`;
  return `${(count / 1024).toFixed(1)} KB`;
}

/** `2026-08-30T14:22:07Z` reads better as a local wall clock on a timeline. */
export function when(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())} ${pad(at.getHours())}:${pad(at.getMinutes())}`;
}

export interface AnalysisObject {
  id: string;
  task_id: string;
  schema_version: string | number;
  created_at: string;
}
export interface DatasetSnapshot extends AnalysisObject {
  name: string;
  kind: string;
  source_hash: string;
  data_hash?: string;
  source_name: string;
  sha256?: string;
  metadata: Record<string, unknown>;
  schema?: { name: string; type: string }[];
  row_count?: number;
  transformation?: { sheet_count?: number; [key: string]: unknown };
  filename?: string;
  /** "source.xlsx" for an uploaded workbook; the archived file's own name inside the snapshot. */
  source_file?: string;
  /** 公式体检, read when the workbook was added. Absent on snapshots filed before it existed. */
  workbook_health?: WorkbookHealth;
}
/** One sample of a formula health hint: a sheet, and for a cell its address and a bounded range around it. */
export interface WorkbookHealthSample {
  sheet: string;
  cell?: string;
  range?: string;
  formula?: string;
  detail?: string;
}
export interface WorkbookHealthIssue {
  code: string;
  severity: 'warning' | 'info' | string;
  /** Occurrences: cells, sheets or links, by code. */
  count: number;
  sheets?: string[];
  samples?: WorkbookHealthSample[];
  /** external_links only: the linked files' names, never their paths. */
  targets?: string[];
}
/** Hints only: nothing here blocks an import or a calculation. */
export interface WorkbookHealth {
  schema_version: number;
  status: 'checked' | 'unavailable' | string;
  checked_formula_cells?: number;
  truncated?: boolean;
  sheet_count?: number;
  /** How many kinds of hint (codes) have at least one occurrence. */
  issue_count?: number;
  issues?: WorkbookHealthIssue[];
  reason?: string;
}
export type AnalysisScalar = string | number | boolean | null;
export interface AnalysisParameterMetadata {
  key: string;
  label: string;
  type: 'string' | 'decimal' | 'integer' | 'boolean' | 'date';
  role: 'business' | 'formula_constant';
  unit?: string;
  description?: string;
  constraints?: {min?: string | number; max?: string | number; choices?: AnalysisScalar[]; nullable?: boolean};
  default?: AnalysisScalar;
}
export interface AnalysisRevision extends AnalysisObject {
  parameter_metadata?: AnalysisParameterMetadata[];
  question: string;
  sql: string | null;
  engine?: 'sql' | 'python' | 'shell' | 'finance' | 'structured_aggregate';
  aggregate_plan?: Record<string, unknown>;
  code?: string;
  /** Finance-engine versions: which calculation (metric, variance, scenario) and the spec it ran. */
  operation?: 'metric' | 'variance' | 'scenario';
  finance_spec?: Record<string, unknown>;
  bindings: Record<string, string>;
  parameters: unknown[] | Record<string, unknown>;
  timeout_seconds?: number;
  max_rows?: number;
  missing_inputs?: string[];
  conversion_rules?: unknown;
  assumptions: unknown[];
  grain: unknown[];
  relationships: unknown[];
  metrics: unknown[];
  parent_id?: string | null;
}
export interface AnalysisRun extends AnalysisObject {
  analysis_id: string;
  bindings?: Record<string, string>;
  parameters?: unknown[] | Record<string, unknown>;
  parameter_metadata?: AnalysisParameterMetadata[];
  assumptions?: unknown[];
  execution_status: string;
  reproducibility_status: string;
  review_status: string;
  publication_status: string;
  input_hashes: Record<string, string>;
  output_hash?: string;
  error?: string | null;
  engine?: string;
  /** Engine seconds, beside the result so output_hash does not move with it. Absent on older and SQL runs. */
  duration_seconds?: number | null;
  code?: string;
  stdout?: string;
  stderr?: string;
  outputs?: {path: string; sha256: string; artifact_path: string; size: number}[];
  finance_context_id?: string;
  finance_scope?: Record<string, Record<string, unknown>>;
  completeness?: string;
  diagnostics?: unknown[];
  result?: {
    columns: { name: string; type: string }[];
    rows: Record<string, unknown>[];
    row_count: number;
    truncated: boolean;
    diagnostics?: unknown[];
    control_totals?: unknown[];
    movement_checks?: unknown[];
    detail_rows?: Record<string, unknown>[];
    excluded_detail_rows?: Record<string, unknown>[];
    provenance?: { mode?: string; status?: string; plan_hash?: string; data_hash?: string; source_hash?: string } & Record<string, unknown>;
  };
  /** Script runs saved with declarations only; a run without one is paired by inference. */
  row_declarations?: RowDeclarations;
  /** Caveat sentences stored with the run record; the result area does not show them. */
  warnings?: unknown[];
}
/** Why a row is an estimate: its grain declared in requirements, its own basis columns, or its wording. */
export type RowEstimateSource =
  | { source: 'declared'; requirements_id: string; item_id: string }
  | { source: 'row'; field: string }
  | { source: 'text'; field: string };
export interface RowDeclaration {
  /** Zero-based index in the full result file (it may lie past the stored result preview). */
  row: number;
  /** The row's own fields the requirement matcher reads (metric_key, metric, organization, period, scenario …). */
  fields: Record<string, unknown>;
  role: 'actual' | 'budget' | 'variance' | 'ratio' | null;
  /** The base metric a role compares (revenue for revenue_variance); the row's own metric without a role. */
  metric: unknown;
  organization: unknown;
  period: unknown;
  /** `${period}|${scenario period suffix}`: rows of one comparison share it; null without a role. */
  period_key: string | null;
  /** ytd or month when the scenario names that period class. */
  span: 'ytd' | 'month' | null;
  unit: string | null;
  unit_kind: 'amount' | 'decimal' | 'percent' | 'unmarked' | 'points' | null;
  /** The row's value as written (a Decimal string), for rows with a role. */
  value: unknown;
  scope_label: string | null;
  estimate: boolean;
  estimate_sources: RowEstimateSource[];
}
export interface RowDeclarations {
  rules_version: string;
  /** The requirements version the run is pinned to, and that record's own fingerprint. */
  requirements_id: string | null;
  requirements_fingerprint: string | null;
  /** Set only when read: the latest requirements whose estimates were merged in. */
  latest_requirements_id?: string;
  complete: boolean;
  incomplete_reason: 'result_file_unavailable' | 'requirements_unavailable' | 'too_many_rows' | null;
  row_count: number;
  rows: RowDeclaration[];
  /** Rows that break the result-row contract; the run still succeeded. Absent on declarations stored before them. */
  warnings?: ResultContractWarning[];
  /** The comparisons the rows pair into, each with the backend's sentence when fully declared. Absent before rules 3.x. */
  pairs?: DeclaredPair[];
  /** Set only when read: the task's current requirements version and its verified fingerprint. */
  current_requirements?: { id: string; fingerprint: string | null };
}
/** The measures a declared pair names its member rows by (result_semantics.LONG_SCENARIO_MEASURES). */
export type PairMeasure = 'actual' | 'budget' | 'estimated_budget' | 'variance' | 'rate' | 'rate_pct';
/** The backend's sentence for one fully declared pair: its own words, never verified, never a draft's fact. */
export interface ScriptConclusion {
  text: string;
  basis: string;
  verified: false;
  /** The figures the sentence states, as Decimal strings; ratio_percent only when it states a 达成率. */
  values: Partial<Record<'actual' | 'budget' | 'variance' | 'ratio_percent', string>>;
  variance_from: 'row' | 'computed';
}
/** One comparison the backend paired from the declared rows; members are row indexes in the declaration. */
export interface DeclaredPair {
  metric: string;
  organization: unknown;
  period: unknown;
  period_key: string;
  span: 'ytd' | 'month' | null;
  unit: string | null;
  members: Partial<Record<PairMeasure, number>>;
  /** Whether the vocabulary names the pair's metric; a pair known only from its scenarios is inferred and gets no sentence. */
  declared: boolean;
  estimate: { estimated: boolean; measures: PairMeasure[] };
  conclusion: ScriptConclusion | null;
}
/** One kind of result-row contract break, in the backend's diagnostic shape with a Chinese message. */
export interface ResultContractWarning {
  severity: 'warning';
  code: 'unit_unmarked' | 'scenario_undeclared' | 'metric_undeclared' | 'estimate_basis_missing' | 'variance_mismatch' | 'label_ambiguous';
  message: string;
  /** Zero-based rows of the full result file, at most 20; row_count counts every row it concerns. */
  rows: number[];
  row_count: number;
  /** The scenario or metric names it concerns, the comparisons a variance_mismatch names, or the shared names a
   * label_ambiguous names. */
  names?: string[];
}
export interface AnalysisDraft extends AnalysisObject {
  document?: import('../electron/reports/model').ReportDocument;
  title: string;
  body: string;
  evidence_appendix?: string;
  evidence_appendix_meta?: Record<string, unknown>;
  run_ids: string[];
  claims: unknown[];
  fact_ids?: string[];
  evidence_recipes?: Record<string, unknown>[];
  consistency_rules?: Record<string, unknown>[];
  consistency_sources?: Record<string, unknown>[] | Record<string, unknown>;
  requirements_id?: string | null;
  materiality?: Record<string, unknown>;
  quality?: Record<string, unknown>;
  revision_comparison?: {
    summary?: { status?: string; issue_count?: number; compared_business_keys?: number };
    issues?: { code?: string; severity?: string; message?: string; business_key?: string; column?: string;
      old_value?: string | number; new_value?: string | number; old_run_id?: string; new_run_id?: string; old_basis?: unknown; new_basis?: unknown }[];
  };
  parent_id?: string | null;
  publication_status: string;
  review_status: string;
  limitations: string[];
}
export interface AnalysisMethod extends AnalysisObject {
  name: string;
  sql: string;
  parameters?: unknown[] | Record<string, unknown>;
  parameter_metadata?: AnalysisParameterMetadata[];
  parameter_policy_version?: 1;
  parameter_contract?: {parameter: string; type: string; source: string; source_parameter?: string | null; role?: 'business' | 'formula_constant' | 'unclassified'; default?: AnalysisScalar; default_strategy?: string; metadata?: AnalysisParameterMetadata}[];
  input_contracts?: Record<string, {schema: {name: string; type: string}[]}>;
  inputs?: string[];
  bindings?: Record<string, string>;
}
export interface AnalysisState {
  task_id: string;
  datasets: DatasetSnapshot[];
  /** Snapshots a newer file or a published source refresh has replaced; a run that read one waits to be recalculated. */
  superseded_datasets?: string[];
  analyses: AnalysisRevision[];
  runs: AnalysisRun[];
  drafts: AnalysisDraft[];
  methods: AnalysisMethod[];
}

export type FinanceCommand =
  | 'list-finance-context'
  | 'finance-source-list'
  | 'finance-readiness'
  | 'finance-context-save'
  | 'finance-map-save'
  | 'finance-metric-save'
  | 'finance-scenario-save'
  | 'finance-scenario-run'
  | 'run-metric'
  | 'explain-variance'
  | 'drilldown-fact'
  | 'save-explanation-draft'
  | 'analysis-requirements-save'
  | 'analysis-requirements-list'
  | 'finance-completion-recoveries'
  | 'finance-completion-recover'
  | 'workbook-range-preview'
  | 'workbook-health'
  | 'prepare-explanation'
  | 'validate-explanation'
  | 'finance-background-save'
  | 'finance-background-list'
  | 'finance-adjustment-save'
  | 'finance-adjustment-list'
  | 'finance-adjustment-confirm'
  | 'finance-controls-propose'
  | 'finance-controls-sources'
  | 'finance-controls-preview'
  | 'finance-controls-save'
  | 'finance-controls-confirm'
  | 'finance-controls-retire'
  | 'finance-controls-run'
  | 'finance-controls-list'
  | 'finance-close-status'
  | 'month-brief'
  | 'finance-control-settings-save'
  | 'finance-control-disposition-save'
  | 'finance-control-disposition-review'
  | 'finance-control-finding-save'
  | 'finance-control-confirmation-sheet'
  | 'report-review'
  | 'report-template-list'
  | 'report-template-apply'
  | 'chart-deliverable-save'
  | 'chart-deliverable-list'
  | 'chart-deliverable-open'
  | 'dashboard-read'
  | 'dashboard-save'
  | 'dashboard-recompute'
  | 'dashboard-carry'
  | 'analysis-circle-select'
  | 'structure-proposal-list'
  | 'structure-proposal-confirm'
  | 'structure-confirmation-list'
  | 'structure-acknowledge'
  | 'structure-reject'
  | 'structure-withdraw'
  | 'structure-template-list'
  | 'structure-template-disable'
  | 'workbook-inspect'
  | 'workbook-bind'
  | 'workbook-read'
  | 'workbook-preview'
  | 'workbook-apply'
  | 'workbook-rollforward-preview'
  | 'workbook-rollforward-apply'
  | 'workbook-rollforward-templates'
  | 'workbook-rollforward-template-save';

export interface FinanceContextState {
  task_id: string;
  datasets: DatasetSnapshot[];
  contexts: FinanceContext[];
  account_maps: Record<string, unknown>[];
  scenarios: Record<string, unknown>[];
  metric_definitions: Record<string, unknown>[];
  capabilities: string[];
}

/** What one file can answer for on its own, and what it is still missing. */
/** Where a file's agreed period was read; the manager sees this beside the candidate. */
export interface ReadinessScopeSource {
  origin?: 'title' | 'column' | 'confirmed';
  sheet?: string;
  text?: string;
  sheet_count?: number;
}

export interface ReadinessDataset {
  dataset_id: string;
  name: string;
  scope: { ledger: string; organization: string; period: string; currency: string; unit: string };
  scope_sources?: { period?: ReadinessScopeSource };
  /** A period the file's own name carries; offered, never filled in. */
  name_scope?: { period?: string; text?: string };
  missing_fields: string[];
  can_run: string[];
  blocked: { capability: string; missing_fields: string[]; reason: string }[];
  /** The period freshness compares: the file's own (column, title), else the period its source refresh was for. */
  period?: string;
  /** The as-of date the file declares (confirmed title 基准日, or a source refresh cutoff); null when it declares none. */
  as_of?: string | null;
  as_of_source?: 'title' | 'source_refresh' | null;
  period_kind?: 'month' | 'annual' | 'as_of' | null;
  /** Whether the file speaks for the task period. Compared only with declared dates, never the clock. */
  freshness?: ReadinessFreshness;
}

export interface ReadinessFreshness {
  state?: 'current' | 'source_stale' | 'period_mismatch' | 'unknown' | string;
  reasons?: { code: string; text?: string }[];
}

export interface ReadinessReport {
  proposed_scope: { ledger: string; organization: string; period: string; currency: string; unit: string };
  datasets: ReadinessDataset[];
  can_run: string[];
  blocked: { capability: string; missing_fields: string[]; reason: string; dataset_id?: string }[];
  file_identity_policy: string;
  diagnostics: { severity: string; code: string; message: string }[];
  erp_connected: boolean;
}

export interface FinanceSourceBatch {
  id: string;
  created_at: string;
  source_name?: string;
  product?: string;
  version?: string;
  dataset_id?: string | null;
  effective_dataset_id?: string | null;
  prior_snapshot_id?: string | null;
  row_count?: number;
  publication_status?: string;
  duplicate_of?: string | null;
  change_counts?: Record<string, unknown>;
  scope?: Record<string, unknown>;
}

export interface FinanceContext extends AnalysisObject {
  name: string;
  bindings: Record<string, string>;
  scopes: Record<string, Record<string, unknown>>;
  policies?: Record<string, Record<string, unknown>>;
  source_hashes?: Record<string, string>;
  account_map_id?: string | null;
  diagnostics?: unknown[];
}

export interface FinanceDrilldown {
  run_id: string;
  row: number;
  column?: string | null;
  rows: { source: Record<string, unknown>; source_hash: string; data: Record<string, unknown>; voucher_detail_available: boolean }[];
  total: number;
  offset: number;
  has_more: boolean;
  message: string;
}
