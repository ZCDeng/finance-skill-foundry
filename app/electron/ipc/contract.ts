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
  tasks: 'foundry:tasks',
  task: 'foundry:task',
  gallery: 'foundry:gallery',
  deliverableText: 'foundry:deliverable-text',
  deliverableOpen: 'foundry:deliverable-open',
  exportWorkbook: 'foundry:export-workbook',
  /** The one channel that changes the store. See `writes.ts`. */
  taskNew: 'foundry:task-new',
  harnessStatus: 'harness:status',
  harnessOpen: 'harness:open',
  formulatorLaunch: 'formulator:launch',
  formulatorStop: 'formulator:stop',
  formulatorStatus: 'formulator:status',
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
