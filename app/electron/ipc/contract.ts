/**
 * Every channel the renderer may use, in one list.
 *
 * The renderer names a channel, a task id, and -- on the one channel that
 * creates a task -- a title an operator typed. It never names a path, a window
 * directory or a file, so the widest thing a compromised renderer can ask for is
 * a view of a task that exists, or one more task that is empty.
 *
 * The typed strings are still checked in `register.ts` before they reach an
 * argv. They go to `execFile` with an argument array and never a shell, so the
 * check is about bounds and control characters rather than quoting.
 */
export const CHANNELS = {
  analysisOpenOutput: 'analysis:open-output',
  analysisState: 'analysis:state',
  analysisAddFiles: 'analysis:add-files',
  analysisReadDataset: 'analysis:read-dataset',
  analysisSave: 'analysis:save',
  analysisRun: 'analysis:run',
  analysisDraft: 'analysis:draft',
  analysisExport: 'analysis:export',
  analysisMethodSave: 'analysis:method-save',
  analysisMethodApply: 'analysis:method-apply',
  tasks: 'foundry:tasks',
  task: 'foundry:task',
  gallery: 'foundry:gallery',
  deliverableText: 'foundry:deliverable-text',
  deliverableOpen: 'foundry:deliverable-open',
  exportWorkbook: 'foundry:export-workbook',
  /** The one channel that changes the store. See `writes.ts`. */
  taskNew: 'foundry:task-new',
  taskRename: 'foundry:task-rename',
  harnessStatus: 'harness:status',
  harnessOpen: 'harness:open',
  harnessLayout: 'harness:layout',
  formulatorLaunch: 'formulator:launch',
  formulatorStop: 'formulator:stop',
  formulatorStatus: 'formulator:status',
  /**
   * A read-only look at one archived workbook, in the Univer viewer.
   *
   * The renderer names a task and a digest, as it does for every other
   * deliverable call. Main resolves the file, starts the gateway for as long
   * as the preview is open, and takes it down on close. No model is anywhere
   * near this path and no `univer_*` tool is reachable from it.
   */
  previewOpen: 'preview:open',
  previewClose: 'preview:close',
  previewStatus: 'preview:status',
  /** Which screen is on top. Both embedded panes are placed from it. */
  paneVisible: 'pane:visible',
  /**
   * Main to renderer, and the only channel that travels that way.
   *
   * The fence cancels a request the embedded page made; the page then shows
   * whatever it shows for a call that did not arrive, which says nothing about
   * why. This carries the reason to the window, which is the surface that knows
   * about tasks.
   */
  harnessRefused: 'harness:refused',
} as const;

export type Channel = (typeof CHANNELS)[keyof typeof CHANNELS];
