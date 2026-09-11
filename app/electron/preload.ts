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
  reportImport: (task: string, options?: unknown) => ipcRenderer.invoke('report:import', task, options),
  reportSource: (task: string, sourceId: string) => ipcRenderer.invoke('report:source', task, sourceId),
  reportPreview: (task: string, document: unknown, title: string) => ipcRenderer.invoke('report:preview', task, document, title),
  reportCancel: (task: string) => ipcRenderer.invoke('report:cancel', task),
  onReportProgress: (cb: (progress: { task: string; phase: string }) => void) => {
    const relay = (_event: unknown, progress: { task: string; phase: string }) => cb(progress);
    ipcRenderer.on('report:progress', relay);
    return () => { ipcRenderer.off('report:progress', relay); };
  },
  analysisOpenOutput: (task: string, runId: string, output: string) => ipcRenderer.invoke('analysis:open-output', task, runId, output),
  analysisState: (task: string) => ipcRenderer.invoke('analysis:state', task),
  analysisAddFiles: (task: string) => ipcRenderer.invoke('analysis:add-files', task),
  reportTemplatePublish: (task: string) => ipcRenderer.invoke('report-template:publish', task),
  analysisReadDataset: (task: string, id: string) => ipcRenderer.invoke('analysis:read-dataset', task, id),
  analysisSave: (task: string, spec: unknown) => ipcRenderer.invoke('analysis:save', task, spec),
  analysisRun: (task: string, id: string) => ipcRenderer.invoke('analysis:run', task, id),
  analysisDraft: (task: string, spec: unknown) => ipcRenderer.invoke('analysis:draft', task, spec),
  analysisExport: (task: string, id: string, format: string) => ipcRenderer.invoke('analysis:export', task, id, format),
  analysisMethodSave: (task: string, id: string, name: string) => ipcRenderer.invoke('analysis:method-save', task, id, name),
  analysisMethodApply: (task: string, id: string, bindings: unknown, parameters: unknown = []) => ipcRenderer.invoke('analysis:method-apply', task, id, bindings, parameters),
  financeCall: (task: string, command: string, spec?: unknown) => ipcRenderer.invoke('finance:call', task, command, spec),
  financeSourceRefresh: (task: string, spec: unknown) => ipcRenderer.invoke('finance:source-refresh', task, spec),
  tasks: () => ipcRenderer.invoke('foundry:tasks'),
  task: (id: string) => ipcRenderer.invoke('foundry:task', id),
  gallery: () => ipcRenderer.invoke('foundry:gallery'),
  deliverableText: (task: string, sha: string) =>
    ipcRenderer.invoke('foundry:deliverable-text', task, sha),
  deliverableOpen: (task: string, sha: string, ext: string) =>
    ipcRenderer.invoke('foundry:deliverable-open', task, sha, ext),
  exportWorkbook: (task: string, window: string) =>
    ipcRenderer.invoke('foundry:export-workbook', task, window),
  taskRename: (task: string, title: string) => ipcRenderer.invoke('foundry:task-rename', task, title),
  taskNew: (title: string, period: string) =>
    ipcRenderer.invoke('foundry:task-new', title, period),
  harnessStatus: () => ipcRenderer.invoke('harness:status'),
  harnessOpen: (intent: string, task: string, seed?: unknown) =>
    ipcRenderer.invoke('harness:open', intent, task, seed),
  formulatorLaunch: () => ipcRenderer.invoke('formulator:launch'),
  formulatorStop: () => ipcRenderer.invoke('formulator:stop'),
  formulatorStatus: () => ipcRenderer.invoke('formulator:status'),
  sourceLocatorOpen: (task: string, spec: unknown) =>
    ipcRenderer.invoke('source-locator:open', task, spec),
  previewOpen: (task: string, sha: string, ext: string) =>
    ipcRenderer.invoke('preview:open', task, sha, ext),

  previewClose: () => ipcRenderer.invoke('preview:close'),
  previewStatus: () => ipcRenderer.invoke('preview:status'),
  harnessLayout: (layout: unknown) => ipcRenderer.invoke('harness:layout', layout),
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
