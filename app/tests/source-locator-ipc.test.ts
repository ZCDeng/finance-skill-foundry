import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  handlers: new Map<string, (...args: any[]) => Promise<any>>(),
  run: vi.fn(),
  openPath: vi.fn(),
  chooser: vi.fn(),
  workspace: vi.fn(),
  reportExport: vi.fn(),
  previewOpen: vi.fn(),
}));
vi.mock('electron', () => ({
  ipcMain: { handle: (name: string, handler: any) => mocks.handlers.set(name, handler) },
  shell: { openPath: mocks.openPath },
  dialog: { showOpenDialog: mocks.chooser },
}));
vi.mock('../electron/foundry.js', async (original) => ({
  ...await original<typeof import('../electron/foundry.js')>(),
  runFoundry: mocks.run,
}));
vi.mock('../electron/harness/workspace.js', () => ({ ensureTaskWorkspace: mocks.workspace }));
vi.mock('../electron/reports/host.js', () => ({ ReportHost: class { export = mocks.reportExport; } }));
import { registerIpc } from '../electron/ipc/register.js';
import { CHANNELS } from '../electron/ipc/contract.js';

const task = 'a'.repeat(32);
const hash = 'c'.repeat(64);
const invoke = (name: string, ...args: unknown[]) => mocks.handlers.get(name)!({}, ...args);

beforeEach(() => {
  mocks.handlers.clear();
  vi.clearAllMocks();
  mocks.workspace.mockReturnValue('/workspace/task-a');
  mocks.run.mockResolvedValue('{}');
  mocks.openPath.mockResolvedValue('');
  mocks.previewOpen.mockResolvedValue({ task, sha256: hash, origin: 'http://127.0.0.1:9081' });
});

function panes() {
  return {
    preview: { open: mocks.previewOpen, close: vi.fn(), place: vi.fn(), running: vi.fn() },
    window: () => ({ webContents: {} }),
  } as any;
}

describe('source-locator dedicated IPC', () => {
  it('rejects path arguments before the CLI runs', async () => {
    registerIpc({ varRoot: '/store' }, panes());
    expect((await invoke(CHANNELS.sourceLocatorOpen, task, { path: '/tmp/secret.xlsx' })).ok).toBe(false);
    expect((await invoke(CHANNELS.sourceLocatorOpen, task, { fact_id: 'fact-a', dataset_id: 'ds' })).ok).toBe(false);
    expect(mocks.run).not.toHaveBeenCalled();
    expect(mocks.previewOpen).not.toHaveBeenCalled();
  });

  it('opens Univer on digest scratch and never uses preview:open or analysis as the fence', async () => {
    const scratch = `/store/tasks/${task}/artifacts/preview/${hash}/${hash}.xlsx`;
    mocks.run.mockImplementation(async (_binding, command) => {
      if (command === 'open-source-locator') {
        return JSON.stringify({
          status: 'ok',
          locator: {
            dataset_id: 'b'.repeat(32),
            source_hash: hash,
            kind: 'xlsx',
            sheet: '费用',
            excel_range: '费用!D18',
            source_row: 18,
            preview_available: true,
          },
          preview: { available: true, handle: 'd'.repeat(64) },
        });
      }
      if (command === 'source-locator-preview-file') return scratch;
      if (command === 'deliverable-path') throw new Error('deliverable-path must not run');
      return '{}';
    });
    registerIpc({ varRoot: '/store' }, panes());
    const result = await invoke(CHANNELS.sourceLocatorOpen, task, { fact_id: 'fact-expense' });
    expect(result.ok).toBe(true);
    expect(mocks.run.mock.calls.map((call) => call[1])).toEqual([
      'open-source-locator',
      'source-locator-preview-file',
    ]);
    expect(mocks.previewOpen).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({
        task,
        sha256: hash,
        file: scratch,
        allowedRoot: `/store/tasks/${task}/artifacts/preview/${hash}`,
        label: '费用!D18',
      }),
    );
    const encoded = JSON.stringify(result.value);
    expect(encoded).not.toContain('/store/');
    expect(encoded).not.toContain('file://');
    expect(encoded).not.toContain('analysis/datasets');
    expect(result.value.status).toBe('ok');
    expect(result.value.viewer).toBe('univer');
    expect(result.value.preview.handle).toBe('d'.repeat(64));
    expect(result.value.origin).toBeUndefined();
    expect(JSON.stringify(result.value)).not.toContain('127.0.0.1');
  });

  it('does not open Univer when the locator is unavailable, forbidden, or has no archived page', async () => {
    registerIpc({ varRoot: '/store' }, panes());
    mocks.run.mockResolvedValueOnce(JSON.stringify({ status: 'locator_unavailable' }));
    expect(await invoke(CHANNELS.sourceLocatorOpen, task, { run_id: 'run-a', row: 0, column: 'expense' })).toEqual({
      ok: true,
      value: { status: 'locator_unavailable' },
    });
    mocks.run.mockResolvedValueOnce(JSON.stringify({ status: 'locator_forbidden' }));
    expect((await invoke(CHANNELS.sourceLocatorOpen, task, { fact_id: 'missing' })).value).toEqual({
      status: 'locator_forbidden',
    });
    mocks.run.mockResolvedValueOnce(JSON.stringify({
      status: 'ok',
      locator: { kind: 'pdf', preview_available: false, source_hash: hash },
      preview: { available: false, handle: 'e'.repeat(64) },
    }));
    const missing = await invoke(CHANNELS.sourceLocatorOpen, task, { fact_id: 'fact-pdf' });
    expect(missing.value.status).toBe('ok');
    expect(missing.value.preview.available).toBe(false);
    expect(mocks.previewOpen).not.toHaveBeenCalled();
    expect(mocks.run.mock.calls.some((call) => call[1] === 'deliverable-path')).toBe(false);
    expect(mocks.run.mock.calls.some((call) => call[1] === 'source-locator-preview-file')).toBe(false);
  });

  it('refuses to fence Univer at an analysis dataset path', async () => {
    mocks.run.mockImplementation(async (_binding, command) => {
      if (command === 'open-source-locator') {
        return JSON.stringify({
          status: 'ok',
          locator: { source_hash: hash, kind: 'xlsx', preview_available: true, excel_range: '费用!D18' },
          preview: { available: true, handle: 'd'.repeat(64) },
        });
      }
      return `/store/tasks/${task}/analysis/datasets/ds/source.xlsx`;
    });
    registerIpc({ varRoot: '/store' }, panes());
    const result = await invoke(CHANNELS.sourceLocatorOpen, task, { fact_id: 'fact-expense' });
    expect(result.ok).toBe(false);
    expect(mocks.previewOpen).not.toHaveBeenCalled();
  });
});
