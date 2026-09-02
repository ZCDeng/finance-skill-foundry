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
  role: 'author' | 'period' | 'followup';
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

export type Intent = 'author' | 'period' | 'followup';

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
  taskNew(title: string, period: string): Promise<Answer<{ id: string }>>;
  /** Absent when this build has no harness install to embed. */
  harnessStatus?(): Promise<Answer<HarnessStatus>>;
  harnessOpen?(
    intent: Intent,
    task: string,
    seed?: { windowId?: string; briefSha?: string | null; verbatim?: string },
  ): Promise<Answer<{ sessionId: string; preset: string }>>;
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
