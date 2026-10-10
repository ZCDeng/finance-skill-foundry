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
  reportImport: 'report:import',
  reportSource: 'report:source',
  reportPreview: 'report:preview',
  reportCancel: 'report:cancel',
  reportProgress: 'report:progress',
  analysisOpenOutput: 'analysis:open-output',
  analysisState: 'analysis:state',
  analysisAddFiles: 'analysis:add-files',
  reportTemplatePublish: 'report-template:publish',
  analysisReadDataset: 'analysis:read-dataset',
  analysisSave: 'analysis:save',
  analysisRun: 'analysis:run',
  analysisDraft: 'analysis:draft',
  analysisExport: 'analysis:export',
  analysisMethodSave: 'analysis:method-save',
  analysisMethodApply: 'analysis:method-apply',
  financeCall: 'finance:call',
  financeSourceRefresh: 'finance:source-refresh',
  /**
   * Save a roll-forward copy (滚动到下月) outside the store, to open in Excel.
   * The renderer names a run; main asks where in a save dialog and the CLI
   * writes the bytes it has just checked. The archived copy is never opened in
   * place, since saving it in Excel would change a hashed snapshot.
   */
  rollforwardExport: 'rollforward:export',
  /**
   * 看板快照: the board's accepted cards as one page (PDF, PPT) or a workbook. The renderer sends what the board
   * shows as data, never markup; main draws the page, asks where to save it, and the CLI holds the data to the
   * board before it files the bytes in 成果库 (foundry/dashboard_snapshot.py).
   */
  dashboardExport: 'dashboard:export',
  /**
   * Write-only: one line per user wait, appended to a file in this app's own
   * folder. Nothing reads it back over IPC, and it never reaches the task store.
   */
  timingLog: 'timing:log',
  /**
   * The window's appearance (跟随系统 / 浅色 / 深色). The renderer names one of
   * three words; main saves it in this app's own folder and applies it to every
   * page at once. See `appearance.ts`.
   */
  appearanceGet: 'appearance:get',
  appearanceSet: 'appearance:set',
  tasks: 'foundry:tasks',
  task: 'foundry:task',
  gallery: 'foundry:gallery',
  /** 总览: every active task's month-close line and its to-dos, in one read. */
  overview: 'foundry:overview',
  /** 成果库's side panel: one draft's text, checks and what it rests on. The renderer names a task and a draft id. */
  libraryDetail: 'foundry:library-detail',
  /**
   * Open a filed export or a 写回 Excel copy in the default program, or show it
   * in Finder. The renderer names a task and the file by digest and format or
   * by output id; main asks the CLI where the task filed it.
   */
  libraryFile: 'foundry:library-file',
  deliverableText: 'foundry:deliverable-text',
  deliverableOpen: 'foundry:deliverable-open',
  /**
   * Hand one filed analysis export (md, xlsx, docx, pdf, html) to the default
   * program. The renderer names a task, a digest and a format; main asks the
   * CLI where this task filed those bytes, as it does for `deliverableOpen`.
   */
  analysisExportOpen: 'analysis:export-open',
  exportWorkbook: 'foundry:export-workbook',
  /** The one channel that changes the store. See `writes.ts`. */
  taskNew: 'foundry:task-new',
  taskRename: 'foundry:task-rename',
  taskArchive: 'foundry:task-archive',
  taskTrash: 'foundry:task-trash',
  taskRestore: 'foundry:task-restore',
  taskPurge: 'foundry:task-purge',
  taskEmpty: 'foundry:task-empty',
  taskSample: 'foundry:task-sample',
  taskSampleReference: 'foundry:task-sample-reference',
  taskSampleNext: 'foundry:task-sample-next',
  taskSampleRemove: 'foundry:task-sample-remove',
  /** Copies the 补充数据模板 into a folder the manager picks; touches no task. */
  templatesExport: 'foundry:templates-export',
  /** 收费明细: the example's three tables into a practice task, confirmed as the example's own. */
  taskSampleBilling: 'foundry:task-sample-billing',
  /** 收费明细: CSV files the manager picks, as one detail table. */
  billingAdd: 'billing:add',
  /** 收费明细: the reads, the manager's confirmations and the collection run, by a fixed list of commands. */
  billingCall: 'billing:call',
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
  /**
   * Open an authorized source cell in digest scratch, not an archived deliverable.
   *
   * The renderer names a fact or a run cell. Main resolves the locator, copies
   * snapshot bytes into artifacts/preview/<source_hash>/, and fences Univer to
   * that directory. This is not preview:open and not deliverable-path.
   */
  sourceLocatorOpen: 'source-locator:open',
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
  /**
   * The runtime behind the conversation exited on its own. The pane keeps the
   * dead page, so without this the window kept a session that answered nothing
   * and offered no way back short of switching tasks.
   */
  harnessExited: 'harness:exited',
  /**
   * 打开结果 or 钉到看板 on a card in the assistant's answer. The page has no channel of its own to this window;
   * the host reads the click off the page's console, checked (`harness/cardAction.ts`), and passes it on.
   */
  harnessCardAction: 'harness:card-action',
} as const;

export type Channel = (typeof CHANNELS)[keyof typeof CHANNELS];

/**
 * What a timed wait was doing. A fixed list: the timing log names one of these
 * and never a task, a file or anything a person typed.
 */
export const WAIT_KINDS = [
  'finance.save', 'finance.pnl', 'finance.bridge', 'finance.scenario',
  'analysis.run', 'materials.import', 'source.refresh', 'billing.import', 'billing.run',
] as const;
export type WaitKind = (typeof WAIT_KINDS)[number];
export type WaitOutcome = 'ok' | 'error' | 'cancelled';
