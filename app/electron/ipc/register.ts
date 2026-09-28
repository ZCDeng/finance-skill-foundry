import { type BrowserWindow, type OpenDialogOptions, ipcMain, shell, dialog } from 'electron';

import type { Binding } from '../foundry.js';
import { FoundryFailure, FoundryRefusal, REFUSED, runFoundry } from '../foundry.js';
import type { FormulatorHost } from '../formulator.js';
import { ROLE_BY_INTENT, type Intent } from '../harness/boot.js';
import { ensureTaskWorkspace } from '../harness/workspace.js';
import { WIRING_CONSEQUENCE, type Wiring } from '../harness/wiring.js';
import type { HarnessHost } from '../harness/host.js';
import { followupDraft } from '../harness/handoff.js';
import {
  analysisExportPath,
  deliverablePath,
  galleryRows,
  listTasks,
  readDeliverable,
  showTask,
  sourceLocatorPreviewFile,
} from '../reads.js';
import { LocatorError, ScratchFences, locatorArgs, locatorHighlight, pathFreePayload, previewFence, taskRoot } from '../source-locator.js';
import type { UniverPreviewHost } from '../univer.js';
import { changeTaskLifecycle, newTask } from '../writes.js';
import { CHANNELS, type WaitKind } from './contract.js';
import { appendWait, waitEntry } from '../timing.js';
import * as path from 'node:path';
import type { ReportHost } from '../reports/host.js';
import { withDraftSpec } from '../reports/input.js';

/**
 * What a handler hands back.
 *
 * A refusal is not an exception here. `foundry` exits 3 for a domain refusal --
 * "no task", "workpaper not written" -- and those are states a screen renders,
 * not crashes. Throwing across the IPC boundary would reach the renderer as a
 * mangled `Error invoking remote method` string with the actual sentence buried
 * in it, so the two are separated on this side and the shape is the same either
 * way.
 */
export type Answer<T> =
  | { ok: true; value: T }
  | { ok: false; refused: boolean; message: string };

async function answer<T>(work: () => Promise<T>): Promise<Answer<T>> {
  try {
    return { ok: true, value: await work() };
  } catch (error) {
    if (error instanceof FoundryRefusal) return { ok: false, refused: true, message: error.message };
    if (error instanceof FoundryFailure) return { ok: false, refused: false, message: error.message };
    return { ok: false, refused: false, message: error instanceof Error ? error.message : String(error) };
  }
}

const LOCATOR_CODES = new Set(['locator_forbidden', 'locator_unavailable', 'preview_unavailable', 'locator_error']);

/** A task id as it comes off the wire. 32 hex, or the call does not run. */
function taskId(value: unknown): string {
  const text = String(value ?? '');
  if (!/^[0-9a-f]{32}$/.test(text)) throw new FoundryFailure(`not a task id: ${text}`, null);
  return text;
}

/** Only an explicitly supported intent may open a conversation. */
function intentOf(value: unknown): Intent {
  const text = String(value ?? '');
  if (text === 'author' || text === 'period' || text === 'followup' || text === 'analysis') return text;
  throw new FoundryFailure(`not an intent: ${text}`, null);
}

/**
 * A line an operator typed, as it comes off the wire.
 *
 * Trimmed, bounded, and refused if it carries a control character. Not a
 * quoting defence -- these reach `execFile` as an argument array, so a quote or
 * a semicolon is one more character in a title. It is a defence against a
 * newline or a NUL landing in a stored title and then in every screen and every
 * log line that ever prints it back.
 *
 * Exported only so the refusals have a test. Nothing outside this file calls it.
 */
export function lineOf(value: unknown, what: string, max: number): string {
  const text = String(value ?? '').trim();
  if (!text) throw new FoundryFailure(`${what} is empty`, null);
  if (text.length > max) throw new FoundryFailure(`${what} is longer than ${max} characters`, null);
  // eslint-disable-next-line no-control-regex
  if (/[\u0000-\u001f\u007f]/.test(text)) throw new FoundryFailure(`${what} has a control character`, null);
  return text;
}

export function registerIpc(
  binding: Omit<Binding, 'task' | 'session'>,
  panes?: {
    host: HarnessHost;
    formulator: FormulatorHost;
    /** The read-only workbook look. Refuses by name in a build with no Univer bundle. */
    preview: UniverPreviewHost;
    /** How the wiring went. Read, never awaited: a failed run has no harness to wait on. */
    wiring: () => Wiring;
    /** Shared startup gate: sessions wait for plugin, presets and pane attachment. */
    ready?: () => Promise<void>;
    window: () => BrowserWindow | null;
    /** Told on every change, so a resize can put the views back where they were. */
    remember: (screen: string) => void;
    /** This app's own state root; a session's workspace is made under it. */
    userData: () => string;
  },
): { shutdown(): void } {
  /**
   * The locator scratch directories this process fenced Univer to, by task.
   * Removed on preview close, on the next locator open for the same task, and
   * at quit through `shutdown`; never a directory the renderer named.
   */
  const scratch = new ScratchFences();
  const shutdown = () => scratch.discardAll();
  // Everything this process does is the manager acting in her own window, so the
  // stamp is set once here rather than at each call site.
  binding = { ...binding, actor: 'manager' };
  /**
   * Files the manager asked to keep a second copy of, by path. Set by the
   * renderer's answer to the duplicate prompt and cleared once used, so a later
   * add of the same file asks again.
   */
  const allowDuplicates = new Set<string>();
  /**
   * How long the last file dialog of each kind stayed open, in milliseconds.
   *
   * The renderer times a wait from the click, and the dialog opens inside the
   * handler it is waiting on; the time spent picking a file is the manager's,
   * not the app's. It comes off that wait when the wait is logged, once. One
   * entry per kind is enough: the screen runs one import or refresh at a time,
   * and each new dialog replaces the last.
   */
  const dialogOpen = new Map<WaitKind, number>();
  const chooseFiles = async (kind: WaitKind, options: OpenDialogOptions) => {
    const opened = performance.now();
    try {
      return await dialog.showOpenDialog(options);
    } finally {
      dialogOpen.set(kind, performance.now() - opened);
    }
  };
  const taskLifecycle = (raw: unknown) => {
    const value = String(raw ?? 'active');
    if (!['active', 'archived', 'trashed', 'all'].includes(value)) throw new Error(`unknown task lifecycle: ${value}`);
    return value as 'active' | 'archived' | 'trashed' | 'all';
  };
  ipcMain.handle(CHANNELS.tasks, (_event, lifecycle: unknown) => answer(() => listTasks(binding, undefined, taskLifecycle(lifecycle))));

  ipcMain.handle(CHANNELS.task, (_event, task: unknown) =>
    answer(() => showTask({ ...binding, task: taskId(task) })),
  );

  ipcMain.handle(CHANNELS.gallery, () => answer(() => galleryRows(binding)));

  ipcMain.handle(CHANNELS.deliverableText, (_event, task: unknown, sha: unknown) =>
    answer(() => readDeliverable({ ...binding, task: taskId(task) }, String(sha ?? ''))),
  );

  /**
   * Open an archived workbook in whatever this machine uses for spreadsheets.
   *
   * `shell.openPath` is the delivery. The point of writing the close as xlsx
   * was that a finance manager reads it in the software they already sort and
   * pivot in. The in-window look (`previewOpen`, below) answers a different
   * question, "what is in this version", on a scratch copy; it is not a
   * second Excel, and this handoff is not a stopgap for it.
   *
   * The path never crosses the boundary. The renderer passes a digest, the CLI
   * resolves it under this task's own artifacts, and the operator's opener gets
   * a file this store filed.
   */
  ipcMain.handle(
    CHANNELS.deliverableOpen,
    (_event, task: unknown, sha: unknown, ext: unknown) =>
      answer(async () => {
        const path = await deliverablePath(
          { ...binding, task: taskId(task) },
          String(sha ?? ''),
          String(ext ?? ''),
        );
        const trouble = await shell.openPath(path);
        if (trouble) throw new Error(`打不开 ${path}: ${trouble}`);
        return { opened: path };
      }),
  );

  /**
   * Open one filed analysis export in the default program, from 成果库.
   *
   * The same handoff as `deliverableOpen`, for the analysis store's exports:
   * the renderer passes a digest and a format, `analysisExportPath` checks both
   * before argv, and the CLI names the file only if this task filed those bytes
   * under that format and they still match their receipt.
   */
  ipcMain.handle(
    CHANNELS.analysisExportOpen,
    (_event, task: unknown, sha: unknown, format: unknown) =>
      answer(async () => {
        const file = await analysisExportPath(
          { ...binding, task: taskId(task) },
          String(sha ?? ''),
          String(format ?? ''),
        );
        const trouble = await shell.openPath(file);
        if (trouble) throw new Error(`打不开 ${file}: ${trouble}`);
        return { opened: file };
      }),
  );

  /**
   * Write one window as a workbook and file it as a version.
   *
   * A write, and it is here rather than in a session tool on purpose. The
   * close seat has no reason to own this: rendering a locked window computes
   * nothing, so a model calling it would only be doing what the operator can
   * ask for the moment they want the file. Keeping it on a button also keeps
   * `export:xlsx` an operator's cause in the timeline rather than a model's.
   */
  ipcMain.handle(CHANNELS.exportWorkbook, (_event, task: unknown, window: unknown) =>
    answer(async () => {
      const id = String(window ?? '');
      if (id && !/^[0-9a-f]{32}$/.test(id)) throw new Error(`not a window id: ${id}`);
      const out = await runFoundry(
        { ...binding, task: taskId(task) },
        'export',
        ['--format', 'xlsx', ...(id ? ['--window', id] : [])],
      );
      return JSON.parse(out.trim()) as { sha256: string; seq: number; ext: string };
    }),
  );

  /**
   * Create a task.
   *
   * Registered beside the reads rather than behind `panes`, because a build with
   * no harness staged still has a store and an operator who needs somewhere to
   * put a period. It is also the only channel here that changes anything, which
   * is why it is the only one whose arguments are free text.
   */
  ipcMain.handle(CHANNELS.taskNew, (_event, title: unknown, period: unknown) =>
    answer(() =>
      newTask(binding, {
        title: lineOf(title, 'title', 120),
        period: String(period ?? '').trim() ? lineOf(period, 'period', 32) : undefined,
      }),
    ),
  );

  ipcMain.handle(CHANNELS.taskRename, (_event, task: unknown, title: unknown) => answer(async () =>
    JSON.parse(await runFoundry({...binding, task: taskId(task)}, 'task-rename', ['--title', lineOf(title, 'title', 120)])),
  ));

  ipcMain.handle(CHANNELS.taskArchive, (_event, task: unknown) => answer(() =>
    changeTaskLifecycle({ ...binding, task: taskId(task) }, 'task-archive'),
  ));
  ipcMain.handle(CHANNELS.taskTrash, (_event, task: unknown) => answer(() =>
    changeTaskLifecycle({ ...binding, task: taskId(task) }, 'task-trash'),
  ));
  ipcMain.handle(CHANNELS.taskRestore, (_event, task: unknown) => answer(() =>
    changeTaskLifecycle({ ...binding, task: taskId(task) }, 'task-restore'),
  ));

  // Every analysis operation goes through the same domain CLI as legacy work.
  const analysisCall = async (rawTask: unknown, command: string, args: string[] = []) =>
    JSON.parse(await runFoundry({ ...binding, task: taskId(rawTask) }, command, args));
  /** Commands that make a new snapshot the root session should be able to see. */
  const widensTheSession = new Set(['structure-proposal-confirm', 'structure-reject', 'structure-withdraw']);
  let reportHost: Promise<ReportHost> | undefined;
  const reports = () => reportHost ??= import('../reports/host.js').then(({ ReportHost }) => new ReportHost(binding,
    (task, phase) => panes?.window()?.webContents.send(CHANNELS.reportProgress, { task, phase })));
  ipcMain.handle(CHANNELS.reportImport, (_event, task: unknown, options?: unknown) => answer(async () =>
    (await reports()).import(taskId(task), options as import('../reports/model.js').ReportImportOptions)));
  ipcMain.handle(CHANNELS.reportSource, (_event, task: unknown, source: unknown) => answer(async () =>
    (await reports()).source(taskId(task), source)));
  ipcMain.handle(CHANNELS.reportPreview, (_event, task: unknown, document: unknown, title: unknown) => answer(async () =>
    (await reports()).preview(taskId(task), document, title)));
  ipcMain.handle(CHANNELS.reportCancel, (_event, task: unknown) => answer(async () =>
    (await reports()).cancel(taskId(task))));
  const draftCall = async (rawTask: unknown, command: string, spec: unknown) => {
    const task = taskId(rawTask);
    return withDraftSpec(spec, (args) => analysisCall(task, command, args));
  };
  const rootAnalysisContext = async (task: string): Promise<{ sessionId?: string; title?: string }> => {
    const known = await analysisCall(task, 'task-show');
    const lifecycle = String(known.task?.lifecycle_status ?? 'active');
    if (lifecycle !== 'active') throw new FoundryRefusal('归档或回收站任务只能查看已有成果，恢复后才能继续对话。', REFUSED);
    const previous = [...(known.sessions ?? [])].reverse().find(
      (row: { role: string; session_id?: string; parent_session_id?: string }) => row.role === 'analysis' && !row.parent_session_id,
    );
    return {
      sessionId: typeof previous?.session_id === 'string' ? previous.session_id : undefined,
      title: typeof known.task?.title === 'string' ? known.task.title : undefined,
    };
  };
  const refreshRootAnalysisSession = async (task: string): Promise<void> => {
    const previous = await rootAnalysisContext(task);
    if (previous.sessionId) await runFoundry({ ...binding, task, session: previous.sessionId }, 'analysis-refresh');
  };
  const objectJson = (value: unknown): string => {
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('expected an object');
    const text = JSON.stringify(value);
    if (text.length > 1_000_000) throw new Error('analysis definition is too large');
    return text;
  };
  const objectId = (value: unknown): string => {
    const id = String(value ?? '');
    if (!/^[a-zA-Z0-9_-]{1,128}$/.test(id)) throw new Error('invalid analysis object id');
    return id;
  };
  const financeCommands = new Set([
    'list-finance-context',
    'finance-source-list',
    'finance-readiness',
    'finance-context-save',
    'finance-map-save',
    'finance-metric-save',
    'finance-scenario-save',
    'finance-scenario-run',
    'run-metric',
    'explain-variance',
    'drilldown-fact',
    'save-explanation-draft',
    'analysis-requirements-save',
    'analysis-requirements-list',
    'finance-completion-recoveries',
    'finance-completion-recover',
    'workbook-range-preview',
    'prepare-explanation',
    'validate-explanation',
    'finance-background-save',
    'finance-background-list',
    'finance-adjustment-save',
    'finance-adjustment-list',
    'finance-adjustment-confirm',
    'report-template-list',
    'report-template-apply',
    'chart-deliverable-save',
    'chart-deliverable-list',
    'chart-deliverable-open',
    'analysis-circle-select',
    'structure-proposal-list',
    'structure-proposal-confirm',
    'structure-confirmation-list',
    'structure-acknowledge',
    'structure-reject',
    'structure-withdraw',
    'structure-template-list',
    'structure-template-disable',
    'workbook-inspect',
    'workbook-bind',
    'workbook-read',
    'workbook-preview',
    'workbook-apply',
  ]);
  const financeListCommands = new Set(['list-finance-context', 'finance-source-list', 'finance-readiness', 'finance-completion-recoveries']);
  ipcMain.handle(CHANNELS.financeCall, (_e, task: unknown, command: unknown, spec: unknown = undefined) =>
    answer(() => {
      const name = String(command ?? '');
      if (!financeCommands.has(name)) throw new Error('unsupported finance command');
      if (financeListCommands.has(name)) {
        if (spec !== undefined && spec !== null) throw new Error('finance command does not take a spec');
        return analysisCall(task, name);
      }
      if (name === 'save-explanation-draft') return draftCall(task, name, spec);
      return analysisCall(task, name, ['--spec', objectJson(spec)]).then(async (result) => {
        // A confirmed structure makes a table the conversation should be able to
        // reach, the same way adding a file does.
        if (widensTheSession.has(name)) await refreshRootAnalysisSession(taskId(task));
        return result;
      });
    }));
  ipcMain.handle(CHANNELS.financeSourceRefresh, (_e, rawTask: unknown, rawSpec: unknown) =>
    answer(async () => {
      if (!rawSpec || typeof rawSpec !== 'object' || Array.isArray(rawSpec)) throw new Error('expected a source refresh object');
      const selected = await chooseFiles('source.refresh', {
        title: '刷新财务来源文件',
        properties: ['openFile'],
        filters: [{ name: '财务来源文件', extensions: ['csv', 'xlsx', 'json'] }],
      });
      if (selected.canceled || selected.filePaths.length === 0) return { cancelled: true };
      return analysisCall(rawTask, 'finance-source-refresh', [
        '--spec',
        objectJson({ ...(rawSpec as Record<string, unknown>), path: selected.filePaths[0] }),
      ]);
    }));
  ipcMain.handle(CHANNELS.analysisOpenOutput, (_e, task: unknown, run: unknown, output: unknown) =>
    answer(async () => {
      const result = await analysisCall(task, 'analysis-output', ['--run', objectId(run), '--output', lineOf(output, 'output name', 1000)]);
      const trouble = await shell.openPath(result.path);
      if (trouble) throw new Error(trouble);
      return result;
    }));
  ipcMain.handle(CHANNELS.analysisState, (_e, task: unknown) =>
    answer(() => analysisCall(task, 'analysis-state')));
  ipcMain.handle(CHANNELS.analysisReadDataset, (_e, task: unknown, id: unknown) =>
    answer(() => analysisCall(task, 'dataset-read', ['--dataset', objectId(id)])));
  ipcMain.handle(CHANNELS.analysisSave, (_e, task: unknown, spec: unknown) =>
    answer(() => analysisCall(task, 'analysis-save', ['--spec', objectJson(spec)])));
  ipcMain.handle(CHANNELS.analysisRun, (_e, task: unknown, id: unknown) =>
    answer(() => analysisCall(task, 'analysis-run', ['--analysis', objectId(id)])));
  ipcMain.handle(CHANNELS.analysisDraft, (_e, task: unknown, spec: unknown) =>
    answer(() => draftCall(task, 'analysis-draft', spec)));
  ipcMain.handle(CHANNELS.analysisMethodSave, (_e, task: unknown, id: unknown, name: unknown) =>
    answer(() => analysisCall(task, 'analysis-method-save', [
      '--analysis', objectId(id), '--name', lineOf(name, 'method name', 120),
    ])));
  ipcMain.handle(CHANNELS.analysisMethodApply, (_e, task: unknown, id: unknown, bindings: unknown, parameters: unknown = []) =>
    answer(() => {
      if (!parameters || typeof parameters !== 'object') throw new Error('method parameters must be an array or object');
      const encoded = JSON.stringify(parameters);
      if (encoded.length > 100_000) throw new Error('method parameters are too large');
      return analysisCall(task, 'analysis-method-apply', [
        '--method', objectId(id), '--bindings', objectJson(bindings), '--parameters', encoded,
      ]);
    }));
  ipcMain.handle(CHANNELS.analysisExport, (_e, task: unknown, id: unknown, rawFormat: unknown, rawMode: unknown = 'management') =>
    answer(async () => {
      const taskKey = taskId(task), draft = objectId(id);
      if (!['md', 'xlsx', 'docx', 'pdf', 'html'].includes(String(rawFormat))) throw new Error('unsupported export format');
      if (rawMode !== 'management' && rawMode !== 'audit') throw new Error('unsupported export mode');
      return (await reports()).export(taskKey, draft, rawFormat, rawMode);
    }));
  ipcMain.handle(CHANNELS.analysisAddFiles, (_e, rawTask: unknown) =>
    answer(async () => {
      const task = taskId(rawTask);
      const selected = await chooseFiles('materials.import', {
        title: '加入分析资料', properties: ['openFile', 'multiSelections'],
        filters: [{ name: '表格与背景资料', extensions: ['csv', 'xlsx', 'json', 'md', 'txt'] }],
      });
      if (selected.canceled || selected.filePaths.length === 0) return [];
      const rows = [];
      let failure: unknown;
      for (const file of selected.filePaths) {
        try {
          const args = ['--path', file, '--name', path.basename(file)];
          // Re-adding the same bytes is answered, not filed: the caller is told
          // which copy the task already holds and can ask for a second one.
          if (allowDuplicates.has(file)) args.push('--allow-duplicate');
          rows.push(await analysisCall(task, 'dataset-add', args));
        } catch (error) {
          failure = error;
          break;
        }
      }
      allowDuplicates.clear();
      if (rows.some((row) => !(row as { duplicate_of?: string }).duplicate_of)) {
        await refreshRootAnalysisSession(task);
      }
      if (failure) throw failure;
      return rows;
    }));
  ipcMain.handle(CHANNELS.reportTemplatePublish, (_e, rawTask: unknown) =>
    answer(async () => {
      const task = taskId(rawTask);
      const selected = await dialog.showOpenDialog({
        title: '发布公司模板', properties: ['openFile'],
        filters: [{ name: 'Word 或 Excel', extensions: ['docx', 'xlsx'] }],
      });
      if (selected.canceled || selected.filePaths.length === 0) return { cancelled: true };
      const file = selected.filePaths[0];
      return analysisCall(task, 'report-template-publish', ['--spec', objectJson({ path: file, name: path.basename(file), label: path.parse(file).name })]);
    }));

  /**
   * One line per user wait, appended to the local timing log in this app's own
   * folder (see `timing.ts`). Write-only: nothing reads it back over IPC, and it
   * never touches the task store. The dialog time of that kind comes off here.
   */
  ipcMain.handle(CHANNELS.timingLog, (_e, raw: unknown) =>
    answer(async () => {
      const entry = waitEntry(raw);
      const folder = panes?.userData();
      if (!folder) throw new Error('no local folder for the timing log');
      const picking = dialogOpen.get(entry.kind) ?? 0;
      dialogOpen.delete(entry.kind);
      await appendWait(folder, entry, picking);
      return { written: true };
    }));

  if (!panes) return { shutdown };
  const harness = panes;

  /**
   * What the workbench needs to know before it draws anything.
   *
   * Deliberately does not start the harness. The old version awaited
   * `host.start()`, which meant the one call a screen would make to find out
   * whether the wiring failed either hung on a start that was never going to
   * happen or reported the timeout instead of the reason.
   */
  ipcMain.handle(CHANNELS.harnessStatus, () =>
    answer(async () => {
      const state = harness.wiring();
      return {
        wiring: state,
        consequence: state.state === 'failed' ? WIRING_CONSEQUENCE[state.step] : null,
        origin: harness.host.origin(),
      };
    }),
  );

  /**
   * Open a conversation, bound before it exists.
   *
   * The order is the point. A period session gets a window created against this
   * task first, so the window carries the back-pointer before the model can call
   * anything -- the CLI then resolves the task from the window rather than from
   * an ambient value, which is what lets one harness process serve every task.
   * The session is registered on the task with the role its button chose, and
   * the leader's own wording is written here rather than inferred later from
   * whatever a model passed to `query-locked`.
   */
  // The action id belongs to one explicit user submission. Store its promise
  // before work starts, so concurrent IPC retries cannot create another root.
  const inputActions = new Map<string, {fingerprint: string; result: Promise<unknown>}>();
  let openQueue: Promise<unknown> = Promise.resolve();
  const serializeOpen = (seed: unknown, intent: unknown, task: unknown, operation: () => Promise<unknown>) => {
    const action = seed as {submit?: boolean; requestId?: unknown} | undefined;
    const key = action?.requestId;
    if (action?.submit && (typeof key !== 'string' || !key || key.length > 200)) return answer(async () => { throw new Error('提交问题需要有效的操作编号。'); });
    if (key !== undefined && (typeof key !== 'string' || !key || key.length > 200)) return answer(async () => { throw new Error('invalid action id'); });
    const fingerprint = JSON.stringify([intent, task, seed]);
    const previous = typeof key === 'string' ? inputActions.get(key) : undefined;
    if (previous) return previous.fingerprint === fingerprint ? previous.result : answer(async () => { throw new Error('操作编号已用于其他内容。'); });
    const result = openQueue.then(operation);
    openQueue = result.catch(() => {});
    if (typeof key === 'string') {
      inputActions.set(key, {fingerprint, result});
      result.then((reply) => {
        const outcome = reply as Answer<{submitted?: boolean}>;
        if (!outcome.ok || !outcome.value.submitted) inputActions.delete(key);
      }, () => inputActions.delete(key));
    }
    return result;
  };
  ipcMain.handle(
    CHANNELS.harnessOpen,
    (_event, rawIntent: unknown, rawTask: unknown, rawSeed: unknown) =>
      serializeOpen(rawSeed, rawIntent, rawTask, () => answer(async () => {
        const intent = intentOf(rawIntent);
        const task = taskId(rawTask);
        await harness.ready?.();
        const seed = (rawSeed ?? {}) as { windowId?: string; briefSha?: string; verbatim?: string; draftId?: string; submit?: boolean; requestId?: string };
        if (seed.verbatim !== undefined && (typeof seed.verbatim !== 'string' || seed.verbatim.length > 100000 || seed.verbatim.includes('\0'))) throw new Error('invalid question');
        if (seed.submit && (intent !== 'analysis' || !seed.verbatim?.trim())) throw new Error('只有明确的分析问题可以直接提交。');
        let draftReference: { draftId: string; revision: number } | undefined;
        if (seed.draftId !== undefined) {
          if (intent !== 'analysis') throw new Error('只有分析任务可以引用文稿。');
          const draftId = objectId(seed.draftId);
          const state = await analysisCall(task, 'analysis-state');
          const drafts = Array.isArray(state.drafts) ? state.drafts : [];
          const index = drafts.findIndex((draft: { id?: string }) => draft.id === draftId);
          if (index < 0) throw new Error('所选文稿不属于当前任务或已不可读取。');
          draftReference = { draftId, revision: index + 1 };
        }
        const action = seed.submit || draftReference ? {
          ...(seed.submit ? {submit: true, requestId: seed.requestId} : {}),
          ...(draftReference ? {draftReference} : {}),
        } : undefined;
        const workspace = ensureTaskWorkspace(harness.userData(), task);
        let workspaceTitle: string | undefined;
        if (intent === 'analysis') {
          const previous = await rootAnalysisContext(task);
          workspaceTitle = previous.title;
          if (previous.sessionId) {
            // Refresh only this root conversation; an active run keeps its fixed inputs.
            await runFoundry({ ...binding, task, session: previous.sessionId }, 'analysis-refresh');
            const draft = seed.verbatim ?? '';
            const reply = action
              ? await harness.host.show(previous.sessionId, draft || undefined, workspace, workspaceTitle, action)
              : await harness.host.show(previous.sessionId, draft || undefined, workspace, workspaceTitle);
            return { ...reply, sessionId: previous.sessionId, preset: 'analysis' };
          }
        }
        let windowId = seed.windowId;
        if (intent === 'period') {
          windowId = (await runFoundry({ ...binding, task }, 'create')).trim();
        }
        if (windowId && !/^[0-9a-f]{32}$/.test(windowId)) throw new Error('invalid window id');
        const opened = await harness.host.open(intent, workspace, undefined, true);
        // Register before the page exposes the conversation to user input.
        await runFoundry({ ...binding, task, session: opened.sessionId }, 'record-session', [
          '--role', ROLE_BY_INTENT[intent], '--workspace', workspace,
          ...(windowId ? ['--window', windowId] : []),
          ...(seed.verbatim ? ['--verbatim', seed.verbatim] : []),
        ]);
        const draft = intent === 'analysis'
          ? seed.verbatim ?? ''
          : intent === 'followup' && windowId
            ? followupDraft({ windowId, briefSha: seed.briefSha })
            : '';
        const reply = intent === 'analysis'
          ? action
            ? await harness.host.show(opened.sessionId, draft || undefined, workspace, workspaceTitle, action)
            : await harness.host.show(opened.sessionId, draft || undefined, workspace, workspaceTitle)
          : await harness.host.show(opened.sessionId, draft, workspace);
        return {...opened, ...reply};
      })),
  );

  /**
   * Launch Formulator on the current window.
   *
   * No task argument: the lease is a window's, and `launch-formulator` takes the
   * current one. Binding it to a task here would let a screen ask for a reader
   * on a window that is not the one the operator is looking at.
   */
  ipcMain.handle(CHANNELS.formulatorLaunch, () =>
    answer(async () => {
      const window = panes.window();
      if (!window) throw new FoundryFailure('no window to show Formulator in', null);
      return panes.formulator.launch(binding, window);
    }),
  );

  ipcMain.handle(CHANNELS.formulatorStop, () =>
    answer(async () => {
      const window = panes.window();
      if (window) await panes.formulator.stop(binding, window);
      return { stopped: true };
    }),
  );

  ipcMain.handle(CHANNELS.formulatorStatus, () =>
    answer(async () => ({ running: panes.formulator.running() })),
  );

  /**
   * Open an authorized source cell on digest scratch.
   *
   * Not preview:open and not deliverable-path. The renderer names a fact or a
   * run cell; the path never crosses the boundary, and Univer is fenced to
   * artifacts/preview/<source_hash>/ rather than the analysis tree.
   *
   * A failure reaches the renderer as one of four fixed codes and nothing
   * else: the CLI's stderr names files, and this channel is the one the
   * renderer may call with a fact it has not been shown.
   */
  ipcMain.handle(
    CHANNELS.sourceLocatorOpen,
    async (_event, task: unknown, spec: unknown) => {
      const outcome = await answer(async () => {
        const window = panes?.window();
        if (!window || !panes?.preview) throw new LocatorError('preview_unavailable');
        let id: string;
        let args: ReturnType<typeof locatorArgs>;
        try {
          id = taskId(task);
          args = locatorArgs(spec);
        } catch {
          throw new LocatorError('locator_error');
        }
        // Whatever this task had on screen before is stale the moment a new
        // cell is asked for; the copy goes before the CLI writes the next one.
        scratch.discard(id);
        let payload: Record<string, unknown>;
        try {
          payload = pathFreePayload(await analysisCall(id, 'open-source-locator', ['--spec', JSON.stringify(args)]));
        } catch (error) {
          if (error instanceof FoundryRefusal) throw new LocatorError('locator_forbidden');
          throw new LocatorError('locator_unavailable');
        }
        if (String(payload.status ?? '') !== 'ok') return payload;
        const locator = (payload.locator ?? {}) as Record<string, unknown>;
        const preview = (payload.preview ?? {}) as Record<string, unknown>;
        const available = Boolean(preview.available ?? locator.preview_available);
        const kind = String(locator.kind ?? '');
        if (!available) return payload;
        if (kind === 'pdf') return { ...payload, viewer: 'pdf' };
        if (kind !== 'xlsx' && kind !== 'csv') return { ...payload, viewer: 'snapshot' };
        let fence: ReturnType<typeof previewFence>;
        try {
          const file = await sourceLocatorPreviewFile({ ...binding, task: id }, args as Record<string, unknown>);
          fence = previewFence(file, String(locator.source_hash ?? ''), taskRoot(binding.varRoot, id));
        } catch (error) {
          if (error instanceof FoundryRefusal) throw new LocatorError('locator_forbidden');
          throw new LocatorError('preview_unavailable');
        }
        scratch.fence(id, fence.allowedRoot);
        let opened: { task: string; sha256: string };
        try {
          opened = await panes.preview.open(window, {
            task: id,
            sha256: String(locator.source_hash ?? ''),
            file: fence.file,
            allowedRoot: fence.allowedRoot,
            label: String(locator.excel_range || locator.sheet || '授权预览'),
            highlight: locatorHighlight(locator),
          });
        } catch {
          scratch.discard(id);
          throw new LocatorError('preview_unavailable');
        }
        return {
          ...payload,
          viewer: 'univer',
          task: opened.task,
          sha256: opened.sha256,
        };
      });
      if (outcome.ok) return outcome;
      // Only a code crosses here. `answer` already turned a `LocatorError`
      // into its own name; anything else was thrown past the mapping above.
      const code = LOCATOR_CODES.has(outcome.message) ? outcome.message : 'locator_error';
      return { ok: false, refused: code === 'locator_forbidden', message: code };
    },
  );

  /**
   * Open one archived workbook read-only in the Univer viewer.
   *
   * The renderer names a task and a digest, exactly as it does to read a brief.
   * The path comes back from the CLI, never from the wire, and the gateway is
   * fenced to that path's own directory -- the task's artifacts -- for as long
   * as the preview is up. That directory is chosen here and not by the host so
   * the rule is next to the only call that can widen it.
   */
  ipcMain.handle(
    CHANNELS.previewOpen,
    (_event, task: unknown, sha: unknown, ext: unknown) =>
      answer(async () => {
        const window = panes.window();
        if (!window) throw new FoundryFailure('no window to show the preview in', null);
        const id = taskId(task);
        const digest = String(sha ?? '');
        const [file, detail] = await Promise.all([
          deliverablePath({ ...binding, task: id }, digest, String(ext ?? '')),
          showTask({ ...binding, task: id }),
        ]);
        return panes.preview.open(window, {
          task: id,
          sha256: digest,
          file,
          allowedRoot: path.dirname(file),
          // The tab the operator reads: the task and the version, not the
          // sixty-four hex characters the worker would name it after.
          label: `${detail.task.title} · ${digest.slice(0, 12)}`,
        });
      }),
  );

  ipcMain.handle(CHANNELS.previewClose, () =>
    answer(async () => {
      const window = panes.window();
      if (window) panes.preview.close(window);
      // The gateway is down; the scratch copy it was fenced to goes with it.
      scratch.discardAll();
      return { stopped: true };
    }),
  );

  ipcMain.handle(CHANNELS.previewStatus, () =>
    answer(async () => ({ running: panes.preview.running() })),
  );

  /**
   * Which screen is on top.
   *
   * Both embedded pages are native views in window coordinates, so React
   * unmounting a component does not hide either of them. This is the one place
   * that decides which rectangle is real, and it places both so a switch cannot
   * leave two stacked.
   */
  ipcMain.handle(CHANNELS.harnessLayout, (event, value: unknown) => answer(async () => {
    const window = panes.window();
    if (!window || event.sender !== window.webContents) throw new Error('invalid layout sender');
    return {accepted: panes.host.layout(window, value, event.sender.getZoomFactor())};
  }));

  ipcMain.handle(CHANNELS.paneVisible, (_event, screen: unknown) =>
    answer(async () => {
      const name = String(screen ?? '');
      panes.remember(name);
      const window = panes.window();
      if (window) {
        panes.host.place(window, name === 'workbench');
        panes.formulator.place(window, name === 'formulator');
        panes.preview.place(window, name === 'preview');
      }
      return { screen: name };
    }),
  );
  return { shutdown };
}
