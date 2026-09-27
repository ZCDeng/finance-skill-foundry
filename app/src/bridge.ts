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
  windows: number;
}

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
  analysisExport?(task: string, id: string, format: import('../electron/reports/model').ReportFormat, mode?: 'management' | 'audit'): Promise<Answer<Record<string, unknown>>>;
  analysisMethodSave?(task: string, id: string, name: string): Promise<Answer<AnalysisMethod>>;
  analysisMethodApply?(task: string, id: string, bindings: Record<string, string>, parameters?: unknown[] | Record<string, unknown>): Promise<Answer<AnalysisRevision>>;
  financeCall?(task: string, command: FinanceCommand, spec?: Record<string, unknown>): Promise<Answer<Record<string, unknown>>>;
  sourceLocatorOpen?(task: string, spec: { fact_id: string } | { run_id: string; row: number; column?: string }): Promise<Answer<SourceLocatorResult>>;
  financeSourceRefresh?(task: string, spec: Record<string, unknown>): Promise<Answer<Record<string, unknown>>>;
  tasks(): Promise<Answer<TaskRow[]>>;
  task(id: string): Promise<Answer<TaskDetail>>;
  gallery(): Promise<Answer<{ task: TaskRow; row: DeliverableRow }[]>>;
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
  taskNew(title: string, period: string): Promise<Answer<{ id: string }>>;
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
  unit_kind: 'amount' | 'decimal' | 'percent' | 'unmarked' | null;
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
  | 'prepare-explanation'
  | 'validate-explanation'
  | 'finance-background-save'
  | 'finance-background-list'
  | 'finance-adjustment-save'
  | 'finance-adjustment-list'
  | 'finance-adjustment-confirm'
  | 'report-template-list'
  | 'report-template-apply'
  | 'chart-deliverable-save'
  | 'chart-deliverable-list'
  | 'chart-deliverable-open'
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
  | 'workbook-apply';

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
export interface ReadinessDataset {
  dataset_id: string;
  name: string;
  scope: { ledger: string; organization: string; period: string; currency: string; unit: string };
  missing_fields: string[];
  can_run: string[];
  blocked: { capability: string; missing_fields: string[]; reason: string }[];
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
