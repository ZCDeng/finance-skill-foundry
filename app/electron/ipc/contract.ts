/**
 * Every channel the renderer may use, in one list.
 *
 * The renderer names a channel and a task id and nothing else. It never names a
 * path, a window directory or a file, so the widest thing a compromised
 * renderer can ask for is a view of a task that exists.
 */
export const CHANNELS = {
  tasks: 'foundry:tasks',
  task: 'foundry:task',
  gallery: 'foundry:gallery',
  deliverableText: 'foundry:deliverable-text',
  harnessStatus: 'harness:status',
  harnessOpen: 'harness:open',
  workbenchVisible: 'harness:visible',
} as const;

export type Channel = (typeof CHANNELS)[keyof typeof CHANNELS];
