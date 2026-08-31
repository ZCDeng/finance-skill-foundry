import { contextBridge, ipcRenderer } from 'electron';

/**
 * The bridge.
 *
 * One method per channel and nothing more. The channel names are written out
 * here rather than imported from `ipc/contract.js`: a sandboxed preload can only
 * require `electron` and a few built-ins, and a relative require throws
 * `module not found` while the bridge silently never appears. A test reads this
 * file and compares the literals against CHANNELS, so a renamed channel fails
 * the suite instead of failing at runtime in a packaged build.
 */
const api = {
  tasks: () => ipcRenderer.invoke('foundry:tasks'),
  task: (id: string) => ipcRenderer.invoke('foundry:task', id),
  gallery: () => ipcRenderer.invoke('foundry:gallery'),
  deliverableText: (task: string, sha: string) =>
    ipcRenderer.invoke('foundry:deliverable-text', task, sha),
  taskNew: (title: string, period: string) =>
    ipcRenderer.invoke('foundry:task-new', title, period),
  harnessStatus: () => ipcRenderer.invoke('harness:status'),
  harnessOpen: (intent: string, task: string, seed?: unknown) =>
    ipcRenderer.invoke('harness:open', intent, task, seed),
  formulatorLaunch: () => ipcRenderer.invoke('formulator:launch'),
  formulatorStop: () => ipcRenderer.invoke('formulator:stop'),
  formulatorStatus: () => ipcRenderer.invoke('formulator:status'),
  paneVisible: (screen: string) => ipcRenderer.invoke('pane:visible', screen),
  /**
   * The one channel main pushes on. Returns its own unsubscribe, because a
   * renderer that re-subscribed on every effect run would stack listeners and
   * report one refusal several times.
   */
  onHarnessRefused: (cb: (reason: string) => void) => {
    const relay = (_event: unknown, reason: string) => cb(reason);
    ipcRenderer.on('harness:refused', relay);
    return () => {
      ipcRenderer.off('harness:refused', relay);
    };
  },
};

export type PreloadAPI = typeof api;

contextBridge.exposeInMainWorld('foundry', api);
