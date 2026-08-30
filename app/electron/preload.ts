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
};

export type PreloadAPI = typeof api;

contextBridge.exposeInMainWorld('foundry', api);
