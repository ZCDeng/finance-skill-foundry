import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  handlers: new Map<string, (...args: any[]) => Promise<any>>(),
  run: vi.fn(), openPath: vi.fn(), chooser: vi.fn(), saver: vi.fn(), workspace: vi.fn(), reportExport: vi.fn(), render: vi.fn(),
}));
vi.mock('electron', () => ({
  ipcMain: { handle: (name: string, handler: any) => mocks.handlers.set(name, handler) },
  shell: { openPath: mocks.openPath }, dialog: { showOpenDialog: mocks.chooser, showSaveDialog: mocks.saver },
}));
vi.mock('../electron/foundry.js', async (original) => ({
  ...await original<typeof import('../electron/foundry.js')>(), runFoundry: mocks.run,
  // The reads parse JSON through their own helper; route it through the same fake exec.
  runFoundryJson: async (...args: unknown[]) => JSON.parse(await mocks.run(...args)),
}));
vi.mock('../electron/harness/workspace.js', () => ({ ensureTaskWorkspace: mocks.workspace }));
vi.mock('../electron/reports/host.js', () => ({ ReportHost: class { export = mocks.reportExport; },
  fontData: async () => 'data:font/woff2;base64,AA==', figureFontData: async () => [] }));
vi.mock('../electron/reports/dashboard-print.js', () => ({ renderSnapshot: mocks.render }));
import { registerIpc } from '../electron/ipc/register.js';
import { CHANNELS } from '../electron/ipc/contract.js';

const task = 'a'.repeat(32), second = 'b'.repeat(32);
const invoke = (name: string, ...args: unknown[]) => mocks.handlers.get(name)!({}, ...args);
beforeEach(() => {
  mocks.handlers.clear(); vi.clearAllMocks();
  mocks.workspace.mockReturnValue('/workspace/task-a');
  mocks.run.mockResolvedValue('{}'); mocks.openPath.mockResolvedValue('');
});

describe('analysis IPC task and session binding', () => {
  it('passes a task-validated revision reference separately from the visible question', async () => {
    const host = { open: vi.fn(), show: vi.fn().mockResolvedValue({}) };
    mocks.run.mockImplementation(async (_binding, command) => command === 'task-show'
      ? JSON.stringify({ sessions: [{ role: 'analysis', session_id: 'root' }] })
      : command === 'analysis-state' ? JSON.stringify({ drafts: [{ id: 'draft-one' }, { id: 'draft-two' }] }) : '{}');
    registerIpc({ varRoot: '/store' }, { host, userData: () => '/user' } as any);
    expect((await invoke(CHANNELS.harnessOpen, 'analysis', task, { draftId: 'draft-two', verbatim: '修正预算' })).ok).toBe(true);
    expect(host.show).toHaveBeenCalledWith('root', '修正预算', '/workspace/task-a', undefined,
      { draftReference: { draftId: 'draft-two', revision: 2 } });
    expect((await invoke(CHANNELS.harnessOpen, 'analysis', task, { draftId: 'foreign-draft', verbatim: '继续' })).ok).toBe(false);
    expect(host.show).toHaveBeenCalledTimes(1);
  });
  it('refuses to open the native analysis conversation for inactive tasks', async () => {
    const host = { open: vi.fn(), show: vi.fn() };
    mocks.run.mockImplementation(async (_binding, command) => command === 'task-show'
      ? JSON.stringify({ task: { title: '旧任务', lifecycle_status: 'archived' }, sessions: [] }) : '{}');
    registerIpc({ varRoot: '/store' }, { host, userData: () => '/user' } as any);
    const result = await invoke(CHANNELS.harnessOpen, 'analysis', task);
    expect(result).toEqual({ ok: false, refused: true, message: '归档或回收站任务只能查看已有成果，恢复后才能继续对话。' });
    expect(host.open).not.toHaveBeenCalled();
    expect(host.show).not.toHaveBeenCalled();
  });

  it('passes explicit audit mode and rejects unsupported export modes before exporting', async () => {
    registerIpc({ varRoot: '/store' });
    mocks.reportExport.mockResolvedValue({ path: '/export/audit.pdf' });
    expect((await invoke(CHANNELS.analysisExport, task, 'draft-1', 'pdf', 'audit')).ok).toBe(true);
    expect(mocks.reportExport).toHaveBeenCalledWith(task, 'draft-1', 'pdf', 'audit');
    expect((await invoke(CHANNELS.analysisExport, task, 'draft-1', 'pdf', 'all-files')).ok).toBe(false);
    expect(mocks.reportExport).toHaveBeenCalledTimes(1);
  });

  it('routes bounded workbook preview, the on-demand formula health check and explicit recovery through manager task authority', async () => {
    registerIpc({ varRoot: '/store' });
    for (const [name, spec] of [
      ['workbook-range-preview', { dataset_id: 'source', sheet: '预算', range: 'B36:I39' }],
      ['workbook-health', { dataset_id: 'source' }],
      ['finance-completion-recover', { operation_id: 'operation', revision: 'revision', draft: { title: '纠正稿' } }],
    ] as const) {
      expect((await invoke(CHANNELS.financeCall, task, name, spec)).ok).toBe(true);
      expect(mocks.run).toHaveBeenCalledWith({ varRoot: '/store', task, actor: 'manager' }, name, ['--spec', JSON.stringify(spec)]);
    }
  });

  it('routes successive task calls explicitly and rejects invalid ids before executing', async () => {
    registerIpc({ varRoot: '/store' });
    await invoke(CHANNELS.analysisState, task);
    await invoke(CHANNELS.analysisState, second);
    await invoke(CHANNELS.analysisState, task);
    expect(mocks.run.mock.calls.map(([binding]) => binding.task)).toEqual([task, second, task]);
    expect((await invoke(CHANNELS.analysisRun, '../b', 'run')).ok).toBe(false);
    expect(mocks.run).toHaveBeenCalledTimes(3);
  });

  it('imports only paths selected through the native dialog, with no renderer supplied path', async () => {
    registerIpc({ varRoot: '/store' });
    mocks.chooser.mockResolvedValue({ canceled: false, filePaths: ['/chosen/actual.csv'] });
    await invoke(CHANNELS.analysisAddFiles, task, '/unselected/secret.csv');
    expect(mocks.run).toHaveBeenCalledWith({ varRoot: '/store', task, actor: 'manager' }, 'dataset-add', [
      '--path', '/chosen/actual.csv', '--name', 'actual.csv',
    ]);
    mocks.chooser.mockResolvedValue({ canceled: true, filePaths: ['/chosen/actual.csv'] });
    expect(await invoke(CHANNELS.analysisAddFiles, task)).toEqual({ ok: true, value: [] });
    expect(mocks.run.mock.calls.map((call) => call[1])).toEqual(['dataset-add', 'task-show']);
  });

  it('refreshes the existing root analysis session after native material import', async () => {
    registerIpc({ varRoot: '/store' });
    mocks.chooser.mockResolvedValue({ canceled: false, filePaths: ['/chosen/月结.xlsx', '/chosen/预算.xlsx'] });
    mocks.run.mockImplementation(async (_binding, command) => command === 'task-show'
      ? JSON.stringify({ sessions: [
          { role: 'analysis', session_id: 'older' },
          { role: 'analysis', session_id: 'root' },
          { role: 'analysis', session_id: 'child', parent_session_id: 'root' },
        ] })
      : JSON.stringify({ id: `${command}-ok` }));
    const result = await invoke(CHANNELS.analysisAddFiles, task);
    expect(result.ok).toBe(true);
    expect(mocks.run.mock.calls.map((call) => call[1])).toEqual([
      'dataset-add',
      'dataset-add',
      'task-show',
      'analysis-refresh',
    ]);
    expect(mocks.run).toHaveBeenCalledWith({ varRoot: '/store', task, session: 'root', actor: 'manager' }, 'analysis-refresh');
  });

  it('syncs successful native imports before returning a later file failure', async () => {
    registerIpc({ varRoot: '/store' });
    mocks.chooser.mockResolvedValue({ canceled: false, filePaths: ['/chosen/月结.xlsx', '/chosen/broken.xlsx'] });
    mocks.run.mockImplementation(async (_binding, command, args) => {
      if (command === 'dataset-add' && args?.includes('/chosen/broken.xlsx')) throw new Error('column names must be nonempty and unique');
      if (command === 'task-show') return JSON.stringify({ sessions: [{ role: 'analysis', session_id: 'root' }] });
      return JSON.stringify({ id: 'first-dataset' });
    });
    const result = await invoke(CHANNELS.analysisAddFiles, task);
    expect(result).toEqual({ ok: false, refused: false, message: 'column names must be nonempty and unique' });
    expect(mocks.run.mock.calls.map((call) => call[1])).toEqual([
      'dataset-add',
      'dataset-add',
      'task-show',
      'analysis-refresh',
    ]);
    expect(mocks.run).toHaveBeenCalledWith({ varRoot: '/store', task, session: 'root', actor: 'manager' }, 'analysis-refresh');
  });

  it('stamps every call it makes as the manager, so a confirmation is not left pending', async () => {
    registerIpc({ varRoot: '/store' });
    await invoke(CHANNELS.financeCall, task, 'structure-proposal-confirm', { dataset_id: 'snapshot-1' });
    const [binding, command] = mocks.run.mock.calls[0];
    expect(command).toBe('structure-proposal-confirm');
    expect(binding.actor).toBe('manager');
  });

  it('lets the card reach the structure commands and still refuses an unknown one', async () => {
    registerIpc({ varRoot: '/store' });
    for (const command of [
      'structure-proposal-list',
      'structure-proposal-confirm',
      'structure-acknowledge',
      'structure-reject',
      'structure-withdraw',
      'structure-template-list',
      'structure-template-disable',
    ]) {
      expect((await invoke(CHANNELS.financeCall, task, command, { id: 'x' })).ok).toBe(true);
    }
    const refused = await invoke(CHANNELS.financeCall, task, 'structure-delete-everything', {});
    expect(refused).toEqual({ ok: false, refused: false, message: 'unsupported finance command' });
  });

  it('lets the controls panel save a 问题类型 as the manager', async () => {
    registerIpc({ varRoot: '/store' });
    const spec = { control_id: 'c'.repeat(32), finding_type: 'source_conflict', note: '台账与月结实收对不上' };
    expect((await invoke(CHANNELS.financeCall, task, 'finance-control-finding-save', spec)).ok).toBe(true);
    expect(mocks.run).toHaveBeenCalledWith({ varRoot: '/store', task, actor: 'manager' }, 'finance-control-finding-save', ['--spec', JSON.stringify(spec)]);
  });

  it('reaches the conversation after a confirmation so it can bind the new table', async () => {
    registerIpc({ varRoot: '/store' });
    mocks.run.mockImplementation(async (_binding, command) => command === 'task-show'
      ? JSON.stringify({ sessions: [{ role: 'analysis', session_id: 'root' }] })
      : JSON.stringify({ id: 'confirmation-1' }));
    await invoke(CHANNELS.financeCall, task, 'structure-proposal-confirm', { dataset_id: 'snapshot-1' });
    expect(mocks.run.mock.calls.map((call) => call[1])).toEqual([
      'structure-proposal-confirm',
      'task-show',
      'analysis-refresh',
    ]);
  });

  it('routes the roll-forward as the manager and lets the conversation see the new copy', async () => {
    registerIpc({ varRoot: '/store' });
    mocks.run.mockImplementation(async (_binding, command) => command === 'task-show'
      ? JSON.stringify({ sessions: [{ role: 'analysis', session_id: 'root' }] })
      : JSON.stringify({ plan_id: 'plan-1' }));
    for (const [name, spec] of [
      ['workbook-rollforward-preview', { dataset_id: 'august', source_hash: 'hash', period: '2026-09', mappings: [] }],
      ['workbook-rollforward-templates', { dataset_id: 'august' }],
      ['workbook-rollforward-template-save', { plan_id: 'plan-1', name: '月度套表' }],
    ] as const) {
      expect((await invoke(CHANNELS.financeCall, task, name, spec)).ok).toBe(true);
      expect(mocks.run).toHaveBeenLastCalledWith({ varRoot: '/store', task, actor: 'manager' }, name, ['--spec', JSON.stringify(spec)]);
    }
    // Only the apply files a snapshot, so only the apply refreshes the conversation.
    expect(mocks.run.mock.calls.map((call) => call[1])).not.toContain('analysis-refresh');
    mocks.run.mockClear();
    expect((await invoke(CHANNELS.financeCall, task, 'workbook-rollforward-apply', { plan_id: 'plan-1' })).ok).toBe(true);
    expect(mocks.run.mock.calls.map((call) => call[1])).toEqual(['workbook-rollforward-apply', 'task-show', 'analysis-refresh']);
    expect(mocks.run.mock.calls[0][0]).toEqual({ varRoot: '/store', task, actor: 'manager' });
  });

  it('exports a roll-forward copy only where the save dialog says, and never names the path back', async () => {
    registerIpc({ varRoot: '/store' });
    const run = 'c'.repeat(32);
    mocks.saver.mockResolvedValue({ canceled: false, filePath: '/chosen/八月套表（2026-09 滚动）.xlsx' });
    mocks.run.mockResolvedValue(JSON.stringify({ filename: '八月套表（2026-09 滚动）.xlsx', sha256: 'f'.repeat(64) }));
    expect(await invoke(CHANNELS.rollforwardExport, task, run, '八月套表（2026-09 滚动）')).toEqual({
      ok: true, value: { exported: true, filename: '八月套表（2026-09 滚动）.xlsx' },
    });
    expect(mocks.saver.mock.calls[0][0].defaultPath).toBe('八月套表（2026-09 滚动）.xlsx');
    expect(mocks.run).toHaveBeenCalledWith({ varRoot: '/store', task, actor: 'manager' }, 'workbook-rollforward-export',
      ['--spec', JSON.stringify({ run_id: run, destination: '/chosen/八月套表（2026-09 滚动）.xlsx' })]);
    // A suggested name cannot steer the folder.
    await invoke(CHANNELS.rollforwardExport, task, run, '../../etc/x');
    expect(mocks.saver.mock.calls[1][0].defaultPath).toBe('.._.._etc_x.xlsx');
    // The copy's own name already ends in .xlsx: the suggestion is that name, not one with .xlsx twice.
    await invoke(CHANNELS.rollforwardExport, task, run, '八月套表（2026-09 滚动）.xlsx');
    expect(mocks.saver.mock.calls[2][0].defaultPath).toBe('八月套表（2026-09 滚动）.xlsx');
    mocks.run.mockClear();
    mocks.saver.mockResolvedValue({ canceled: true, filePath: '' });
    expect(await invoke(CHANNELS.rollforwardExport, task, run)).toEqual({ ok: true, value: { cancelled: true } });
    expect((await invoke(CHANNELS.rollforwardExport, task, '../run')).ok).toBe(false);
    expect(mocks.run).not.toHaveBeenCalled();
    // The renderer cannot name a destination through the generic channel.
    expect(await invoke(CHANNELS.financeCall, task, 'workbook-rollforward-export', { run_id: run, destination: '/etc/passwd.xlsx' }))
      .toEqual({ ok: false, refused: false, message: 'unsupported finance command' });
    expect(mocks.run).not.toHaveBeenCalled();
  });

  it('answers a repeat upload instead of filing it, and leaves the conversation alone', async () => {
    registerIpc({ varRoot: '/store' });
    mocks.chooser.mockResolvedValue({ canceled: false, filePaths: ['/chosen/月结.xlsx'] });
    mocks.run.mockImplementation(async (_binding, command) => command === 'task-show'
      ? JSON.stringify({ sessions: [{ role: 'analysis', session_id: 'root' }] })
      : JSON.stringify({ id: 'existing', duplicate_of: 'existing', name: '月结' }));
    const result = await invoke(CHANNELS.analysisAddFiles, task);
    expect(result.ok).toBe(true);
    expect(result.value[0].duplicate_of).toBe('existing');
    // Nothing new was filed, so nothing widens.
    expect(mocks.run.mock.calls.map((call) => call[1])).toEqual(['dataset-add']);
  });

  it('files nothing when the picker returns without a file', async () => {
    registerIpc({ varRoot: '/store' });
    mocks.chooser.mockResolvedValue({ canceled: false, filePaths: [] });
    expect(await invoke(CHANNELS.analysisAddFiles, task)).toEqual({ ok: true, value: [] });
    expect(mocks.run).not.toHaveBeenCalled();
  });

  it('publishes a company template from the native picker and never dataset-add', async () => {
    registerIpc({ varRoot: '/store' });
    mocks.chooser.mockResolvedValue({ canceled: false, filePaths: ['/chosen/company.docx'] });
    await invoke(CHANNELS.reportTemplatePublish, task, '/unselected/secret.pptx');
    expect(JSON.parse(String(mocks.run.mock.calls[0][2][1])).path).toBe('/chosen/company.docx');
    expect(mocks.run.mock.calls.map((call) => call[1])).toEqual(['report-template-publish']);
    expect(mocks.run.mock.calls.map((call) => call[1])).not.toContain('dataset-add');
    mocks.chooser.mockResolvedValue({ canceled: true, filePaths: ['/chosen/company.docx'] });
    expect(await invoke(CHANNELS.reportTemplatePublish, task)).toEqual({ ok: true, value: { cancelled: true } });
  });

  it('registers a conversation before exposing it and does not create a legacy window', async () => {
    const events: string[] = [];
    const host = {
      open: vi.fn(async () => { events.push('create'); return { sessionId: 'session-a' }; }),
      show: vi.fn(async () => { events.push('show'); }),
    };
    mocks.run.mockImplementation(async (_binding, command) => {
      events.push(command);
      return command === 'task-show' ? JSON.stringify({ task: { title: '华东利润分析' } }) : '{}';
    });
    registerIpc({ varRoot: '/store' }, { host, userData: () => '/user' } as any);
    const result = await invoke(CHANNELS.harnessOpen, 'analysis', task, { verbatim: '利润为什么下降？' });
    expect(result.ok).toBe(true);
    expect(events).toEqual(['task-show', 'create', 'record-session', 'show']);
    expect(host.open).toHaveBeenCalledWith('analysis', '/workspace/task-a', undefined, true);
    expect(mocks.run).toHaveBeenCalledWith({ varRoot: '/store', task, session: 'session-a', actor: 'manager' }, 'record-session', [
      '--role', 'analysis', '--workspace', '/workspace/task-a', '--verbatim', '利润为什么下降？',
    ]);
    expect(host.show).toHaveBeenCalledWith('session-a', '利润为什么下降？', '/workspace/task-a', '华东利润分析');
  });

  it('waits for plugin and pane readiness before creating a session during cold start', async () => {
    let release!: () => void;
    const ready = new Promise<void>((resolve) => { release = resolve; });
    const host = { open: vi.fn().mockResolvedValue({ sessionId: 'cold' }), show: vi.fn() };
    mocks.run.mockImplementation(async (_binding, command) => command === 'task-show'
      ? JSON.stringify({ task: { title: '首项经营分析' } }) : '{}');
    registerIpc({ varRoot: '/store' }, { host, userData: () => '/user', ready: () => ready } as any);
    const result = invoke(CHANNELS.harnessOpen, 'analysis', task, { verbatim: '第一问' });
    await Promise.resolve();
    expect(host.open).not.toHaveBeenCalled();
    expect(mocks.run).not.toHaveBeenCalled();
    release();
    expect((await result).ok).toBe(true);
    expect(host.show).toHaveBeenCalledWith('cold', '第一问', '/workspace/task-a', '首项经营分析');
  });

  it('does not show an unregistered conversation when registration fails', async () => {
    const host = { open: vi.fn().mockResolvedValue({ sessionId: 'unregistered' }), show: vi.fn() };
    mocks.run.mockImplementation(async (_binding, command) => {
      if (command === 'task-show') return '{}';
      throw new Error('registration failed');
    });
    registerIpc({ varRoot: '/store' }, { host, userData: () => '/user' } as any);
    expect((await invoke(CHANNELS.harnessOpen, 'analysis', task)).ok).toBe(false);
    expect(host.show).not.toHaveBeenCalled();
  });

  it('resumes the task root conversation and refreshes its data without losing messages', async () => {
    const host = { open: vi.fn(), show: vi.fn() };
    mocks.run.mockImplementation(async (_binding, command) => command === 'task-show'
      ? JSON.stringify({ task: { title: '预算差异分析' }, sessions: [
          { role: 'analysis', session_id: 'root' },
          { role: 'analysis', session_id: 'child', parent_session_id: 'root' },
        ] }) : '{}');
    registerIpc({ varRoot: '/store' }, { host, userData: () => '/user' } as any);
    const result = await invoke(CHANNELS.harnessOpen, 'analysis', task, { verbatim: '补了预算，再分析' });
    expect(result.value.sessionId).toBe('root');
    expect(host.open).not.toHaveBeenCalled();
    expect(mocks.run).toHaveBeenCalledWith({ varRoot: '/store', task, session: 'root', actor: 'manager' }, 'analysis-refresh');
    expect(host.show).toHaveBeenCalledWith('root', '补了预算，再分析', '/workspace/task-a', '预算差异分析');
  });

  it('keeps legacy session opening free of an extra task title lookup', async () => {
    const host = { open: vi.fn().mockResolvedValue({ sessionId: 'legacy' }), show: vi.fn() };
    registerIpc({ varRoot: '/store' }, { host, userData: () => '/user' } as any);
    const result = await invoke(CHANNELS.harnessOpen, 'author', task);
    expect(result.ok).toBe(true);
    expect(mocks.run.mock.calls.map((call) => call[1])).toEqual(['record-session']);
    expect(host.show).toHaveBeenCalledWith('legacy', '', '/workspace/task-a');
  });

  it('routes all document formats to the task-bound native export host', async () => {
    registerIpc({ varRoot: '/store' });
    mocks.reportExport.mockResolvedValue({ path: '/chosen/report.xlsx', sha256: 'hash' });
    for (const format of ['md', 'xlsx', 'docx', 'pdf', 'html']) {
      const result = await invoke(CHANNELS.analysisExport, task, 'draft-a', format);
      expect(result.ok).toBe(true);
      expect(mocks.reportExport).toHaveBeenLastCalledWith(task, 'draft-a', format, 'management');
    }
    expect((await invoke(CHANNELS.analysisExport, task, 'draft-a', 'exe')).ok).toBe(false);
    // A deck can be imported but never written.
    expect((await invoke(CHANNELS.analysisExport, task, 'draft-a', 'pptx')).ok).toBe(false);
    expect((await invoke(CHANNELS.analysisExport, task, '../escape', 'xlsx')).ok).toBe(false);
    expect(mocks.reportExport).toHaveBeenCalledTimes(5);
    expect(mocks.openPath).not.toHaveBeenCalled();
  });

  it('opens a filed export in the default program from a digest and a format, never a renderer path', async () => {
    registerIpc({ varRoot: '/store' });
    const filed = '/store/tasks/a/analysis/exports/registered/draft-management.pdf';
    mocks.run.mockResolvedValue(JSON.stringify({ path: filed }));
    const sha = 'f'.repeat(64);
    expect(await invoke(CHANNELS.analysisExportOpen, task, sha, 'pdf')).toEqual({ ok: true, value: { opened: filed } });
    expect(mocks.run).toHaveBeenCalledWith({ varRoot: '/store', task, actor: 'manager' }, 'analysis-export-path',
      ['--sha', sha, '--format', 'pdf'], undefined);
    expect(mocks.openPath).toHaveBeenCalledWith(filed);
    // A path, a padded format, an unknown format or a foreign task id never reach argv or the opener.
    for (const [who, digest, format] of [
      [task, '/Users/someone/secret.pdf', 'pdf'], [task, sha, '../x.pdf'], [task, sha, 'exe'], [task, sha, '.pdf'], ['../b', sha, 'pdf'],
    ]) {
      expect((await invoke(CHANNELS.analysisExportOpen, who, digest, format)).ok).toBe(false);
    }
    expect(mocks.run).toHaveBeenCalledTimes(1);
    expect(mocks.openPath).toHaveBeenCalledTimes(1);
  });

  it('says so when the default program cannot open the file', async () => {
    registerIpc({ varRoot: '/store' });
    mocks.run.mockResolvedValue(JSON.stringify({ path: '/store/x.docx' }));
    mocks.openPath.mockResolvedValue('No application knows how to open this file');
    const result = await invoke(CHANNELS.analysisExportOpen, task, 'c'.repeat(64), 'docx');
    expect(result.ok).toBe(false);
    expect(result.message).toContain('No application knows how to open this file');
  });

  it('answers 成果库 with the old flow, the newest drafts and the filed exports in one list, from one read', async () => {
    registerIpc({ varRoot: '/store' });
    const at = '2026-09-27T03:00:00Z';
    const row = { id: task, title: '八月', period: '2026-08', skill_id: null, created_at: at, windows: 1 };
    mocks.run.mockImplementation(async (_binding, command) => command === 'library'
      ? JSON.stringify([
        { type: 'deliverable', key: `deliverable:${task}:1`, at, task: row,
          row: { seq: 1, kind: 'brief', window_id: task, sha256: '1'.repeat(64), bytes: 1, cause: 'emit-brief', session_id: null, at } },
        { type: 'draft', key: `draft:${'2'.repeat(32)}`, at, task: row, draft: { draft_id: '2'.repeat(32), revision: 2, versions: 2,
          title: '八月', created_at: at, seq: 2, review_status: 'unreviewed', publication_status: 'draft' } },
      ])
      : '[]');
    const result = await invoke(CHANNELS.gallery);
    expect(result.ok).toBe(true);
    expect(result.value.map((entry: { key: string }) => entry.key)).toEqual([`draft:${'2'.repeat(32)}`, `deliverable:${task}:1`]);
    expect(mocks.run.mock.calls.map((call) => call[1])).toEqual(['library']);
  });

  it('answers 总览 from one read and 成果库 detail only for a draft id', async () => {
    registerIpc({ varRoot: '/store' });
    mocks.run.mockResolvedValue(JSON.stringify({ schema_version: 1, tasks: [], todo_count: 0 }));
    expect((await invoke(CHANNELS.overview)).value).toEqual({ schema_version: 1, tasks: [], todo_count: 0 });
    expect(mocks.run).toHaveBeenLastCalledWith(expect.objectContaining({ varRoot: '/store' }), 'overview', [], undefined);
    const refused = await invoke(CHANNELS.libraryDetail, task, '../x');
    expect(refused.ok).toBe(false);
    mocks.run.mockResolvedValue(JSON.stringify({ schema_version: 1 }));
    await invoke(CHANNELS.libraryDetail, task, '3'.repeat(32));
    expect(mocks.run).toHaveBeenLastCalledWith(expect.objectContaining({ varRoot: '/store', task }), 'library-detail', ['--draft', '3'.repeat(32)], undefined);
  });

  it('opens or shows a 成果库 file only by digest and format or by output id', async () => {
    registerIpc({ varRoot: '/store' });
    mocks.run.mockResolvedValue(JSON.stringify({ path: '/store/x.xlsx' }));
    mocks.openPath.mockResolvedValue('');
    const opened = await invoke(CHANNELS.libraryFile, task, { kind: 'workbook', id: '4'.repeat(32) }, 'open');
    expect(opened.value).toEqual({ opened: '/store/x.xlsx' });
    expect(mocks.run).toHaveBeenLastCalledWith(expect.objectContaining({ varRoot: '/store', task }), 'workbook-output-path', ['--output', '4'.repeat(32)], undefined);
    expect((await invoke(CHANNELS.libraryFile, task, { kind: 'workbook', id: '/etc/passwd' }, 'open')).ok).toBe(false);
    expect((await invoke(CHANNELS.libraryFile, task, { kind: 'path', id: '4'.repeat(32) }, 'open')).ok).toBe(false);
    expect((await invoke(CHANNELS.libraryFile, task, { kind: 'export', sha: 'c'.repeat(64), format: 'docx' }, 'delete')).ok).toBe(false);
  });

  it('prints a 看板 page in main, files it, and copies the filed bytes only where the save dialog says', async () => {
    const { mkdtemp, readFile, writeFile } = await import('node:fs/promises');
    const { tmpdir } = await import('node:os');
    const { join } = await import('node:path');
    const dir = await mkdtemp(join(tmpdir(), 'fa-dashboard-ipc-'));
    const filed = join(dir, 'filed.pdf');
    await writeFile(filed, '%PDF-1.7 filed');
    registerIpc({ varRoot: '/store' });
    const card = '1'.repeat(32), run = '2'.repeat(32);
    const model = {
      version: 1, board_id: '3'.repeat(32), task: '华宸物业 8 月月结', period: '2026 年 8 月',
      figures: [{ card_id: card, title: '距生死线', subject: '集团', part: '本期', value: { text: '-3.22 个百分点', negative: true }, level: 'red', level_label: '红',
        beside: [], note: '', source: 1, cell: { column: 'value', value: '-3.224' } }],
      charts: [], sources: [{ n: 1, card_id: card, title: '距生死线', run: 'A', lines: ['公式：收缴率 − 生死线'] }],
      runs: [{ key: 'A', run_id: run, label: '回款健康', computed: '10-10 计算', files: [] }], beyond: [], left_out: { pinned: [], scenario: [] },
    };
    let sent: Record<string, unknown> = {};
    mocks.run.mockImplementation(async (_binding, command, args: string[]) => {
      if (command === 'dashboard-snapshot') sent = JSON.parse(args[1]);
      return JSON.stringify({ snapshot: { id: '5'.repeat(32) }, path: filed });
    });
    mocks.render.mockResolvedValue(Buffer.from('%PDF-1.7 page'));
    mocks.saver.mockResolvedValue({ canceled: false, filePath: join(dir, '经营看板.pdf') });
    expect(await invoke(CHANNELS.dashboardExport, task, 'pdf', model)).toEqual({
      ok: true, value: { exported: true, format: 'pdf', path: join(dir, '经营看板.pdf'), snapshot_id: '5'.repeat(32) } });
    expect(mocks.saver.mock.calls[0][0].defaultPath).toBe('经营看板_华宸物业8月月结_2026年8月.pdf');
    expect(mocks.render).toHaveBeenCalledWith(expect.stringContaining('-3.22 个百分点'), 'pdf', expect.anything());
    expect(mocks.run.mock.calls[0][0]).toEqual({ varRoot: '/store', task, actor: 'manager' });
    expect(sent).toMatchObject({ format: 'pdf', model: { board_id: '3'.repeat(32) }, file: expect.stringMatching(/page\.pdf$/) });
    expect(await readFile(join(dir, '经营看板.pdf'), 'utf8')).toBe('%PDF-1.7 filed');

    // Excel is written by the backend; nothing is printed.
    mocks.render.mockClear();
    mocks.saver.mockResolvedValue({ canceled: false, filePath: join(dir, '经营看板.xlsx') });
    expect((await invoke(CHANNELS.dashboardExport, task, 'xlsx', model)).ok).toBe(true);
    expect(mocks.render).not.toHaveBeenCalled();
    expect(sent).not.toHaveProperty('file');

    mocks.run.mockClear();
    mocks.saver.mockResolvedValue({ canceled: false, filePath: join(dir, '经营看板.txt') });
    expect(await invoke(CHANNELS.dashboardExport, task, 'pptx', model)).toMatchObject({ ok: false, message: '文件名要以 .pptx 结尾。' });
    mocks.saver.mockResolvedValue({ canceled: true, filePath: '' });
    expect(await invoke(CHANNELS.dashboardExport, task, 'pdf', model)).toEqual({ ok: true, value: { cancelled: true } });
    expect((await invoke(CHANNELS.dashboardExport, task, 'docx', model)).ok).toBe(false);
    // A page holds twelve figures; the shape is refused before any dialog.
    mocks.saver.mockClear();
    const crowded = { ...model, figures: Array.from({ length: 13 }, () => model.figures[0]) };
    expect(await invoke(CHANNELS.dashboardExport, task, 'pdf', crowded)).toMatchObject({ ok: false, message: '一页纸放不下这么多卡。' });
    expect(await invoke(CHANNELS.dashboardExport, task, 'pdf', { ...model, figures: [{ ...model.figures[0], title: '<b>' + 'x'.repeat(300) }] })).toMatchObject({ ok: false });
    expect(mocks.saver).not.toHaveBeenCalled();
    expect(mocks.run).not.toHaveBeenCalled();

    // 成果库 opens a filed snapshot by its id only.
    mocks.run.mockResolvedValue(JSON.stringify({ path: filed }));
    expect((await invoke(CHANNELS.libraryFile, task, { kind: 'dashboard', id: '5'.repeat(32) }, 'open')).value).toEqual({ opened: filed });
    expect(mocks.run).toHaveBeenLastCalledWith(expect.objectContaining({ varRoot: '/store', task }), 'dashboard-snapshot-path', ['--snapshot', '5'.repeat(32)], undefined);
    expect((await invoke(CHANNELS.libraryFile, task, { kind: 'dashboard', id: '../x' }, 'open')).ok).toBe(false);
  });

  it('allows only bounded finance business commands through one IPC call', async () => {
    registerIpc({ varRoot: '/store' });
    await invoke(CHANNELS.financeCall, task, 'list-finance-context');
    await invoke(CHANNELS.financeCall, task, 'finance-source-list');
    await invoke(CHANNELS.financeCall, task, 'finance-context-save', {
      name: '八月经营口径',
      bindings: { actual: 'b'.repeat(32) },
      scopes: { actual: { ledger: '总账', period: '2026-08', currency: 'CNY', unit: '元', scenario: 'actual' } },
    });
    await invoke(CHANNELS.financeCall, task, 'finance-scenario-save', {
      context_id: 'ctx-a',
      kind: 'receivables_aging',
      inputs: { as_of: '2026-08-31', invoices_alias: 'actual' },
      label: '基准账龄',
    });
    await invoke(CHANNELS.financeCall, task, 'explain-variance', {
      context_id: 'ctx-a',
      actual_scenario: 'actual',
      baseline_scenario: 'budget',
      dimensions: ['organization', 'period'],
    });
    await invoke(CHANNELS.financeCall, task, 'workbook-preview', {
      binding_id: 'binding-a',
      writes: [{ row: 1, field: 'amount', value: '10.00' }],
    });
    await invoke(CHANNELS.financeCall, task, 'drilldown-fact', { run_id: 'run-a', row: 0, limit: 100 });
    await invoke(CHANNELS.financeCall, task, 'finance-completion-recoveries');
    await invoke(CHANNELS.financeCall, task, 'prepare-explanation', { run_ids: ['run-a'] });
    await invoke(CHANNELS.financeCall, task, 'validate-explanation', { draft_id: 'draft-a' });
    await invoke(CHANNELS.financeCall, task, 'finance-background-save', { text: '销售提前确认', basis: 'professional_judgment', scope: { ledger: '总账' }, effective_from: '2026-08' });
    await invoke(CHANNELS.financeCall, task, 'finance-background-list', { scope: { ledger: '总账' }, as_of: '2026-08' });
    await invoke(CHANNELS.financeCall, task, 'finance-adjustment-save', { context_id: 'ctx-a', label: '总部费用调整', amount: '5', profit_impact: '5' });
    await invoke(CHANNELS.financeCall, task, 'finance-adjustment-list', { context_id: 'ctx-a' });
    await invoke(CHANNELS.financeCall, task, 'finance-adjustment-confirm', { id: 'adj-a' });
    await invoke(CHANNELS.financeCall, task, 'chart-deliverable-save', { run_id: 'run-a' });
    await invoke(CHANNELS.financeCall, task, 'chart-deliverable-list', { run_id: 'run-a' });
    await invoke(CHANNELS.financeCall, task, 'chart-deliverable-open', { id: 'chart-a' });
    await invoke(CHANNELS.financeCall, task, 'analysis-circle-select', { kind: 'draft_table', draft_id: 'draft-a', range: 'A:A' });
    expect(mocks.run.mock.calls.map((call) => call[1])).toEqual([
      'list-finance-context',
      'finance-source-list',
      'finance-context-save',
      'finance-scenario-save',
      'explain-variance',
      'workbook-preview',
      'drilldown-fact',
      'finance-completion-recoveries',
      'prepare-explanation',
      'validate-explanation',
      'finance-background-save',
      'finance-background-list',
      'finance-adjustment-save',
      'finance-adjustment-list',
      'finance-adjustment-confirm',
      'chart-deliverable-save',
      'chart-deliverable-list',
      'chart-deliverable-open',
      'analysis-circle-select',
    ]);
    expect(mocks.run.mock.calls[0][2]).toEqual([]);
    expect(mocks.run.mock.calls[1][2]).toEqual([]);
    expect(mocks.run.mock.calls[7][2]).toEqual([]);
    expect(mocks.run.mock.calls[2][2]).toEqual(['--spec', expect.stringContaining('\"bindings\"')]);
    const varianceSpec = JSON.parse(mocks.run.mock.calls[4][2][1]);
    expect(varianceSpec.dimensions).toEqual(['organization', 'period']);
    expect(varianceSpec.dimensions).not.toContain('management_account');
    expect((await invoke(CHANNELS.financeCall, task, 'dataset-add', { path: '/tmp/secret.csv' })).ok).toBe(false);
    expect((await invoke(CHANNELS.financeCall, task, 'list-finance-context', { unexpected: true })).ok).toBe(false);
    const backgroundListSpec = JSON.parse(mocks.run.mock.calls[11][2][1]);
    expect(backgroundListSpec.scope).toEqual({ ledger: '总账' });
    expect((await invoke(CHANNELS.financeCall, task, 'run-metric', ['not an object'])).ok).toBe(false);
    expect(mocks.run).toHaveBeenCalledTimes(19);
  });

  it('sends report-review through the draft spec transport, as a private file once it is large', async () => {
    registerIpc({ varRoot: '/store' });
    const { readFile } = await import('node:fs/promises');
    let filed = '';
    mocks.run.mockImplementation(async (_binding: unknown, _command: string, args: string[]) => {
      if (args[0] === '--spec-file') filed = await readFile(args[1], 'utf8');
      return JSON.stringify({ summary: { status: 'pass' } });
    });
    const small = { draft_id: 'd'.repeat(32) };
    expect((await invoke(CHANNELS.financeCall, task, 'report-review', small)).ok).toBe(true);
    expect(mocks.run).toHaveBeenLastCalledWith({ varRoot: '/store', task, actor: 'manager' }, 'report-review',
      ['--spec', JSON.stringify(small)]);
    const document = { content: [{ type: 'paragraph', content: [{ type: 'text', text: '营业收入 1,234.56 万元。'.repeat(4000) }] }] };
    expect((await invoke(CHANNELS.financeCall, task, 'report-review', { document })).ok).toBe(true);
    const [, command, args] = mocks.run.mock.calls.at(-1)!;
    expect(command).toBe('report-review');
    expect(args).toEqual(['--spec-file', expect.stringContaining('draft.json')]);
    expect(JSON.parse(filed)).toEqual({ document });
    expect((await invoke(CHANNELS.financeCall, task, 'report-review', ['not an object'])).ok).toBe(false);
    expect(mocks.run).toHaveBeenCalledTimes(2);
  });

  it('does not reach open-source-locator through the generic finance channel', async () => {
    registerIpc({ varRoot: '/store' });
    const result = await invoke(CHANNELS.financeCall, task, 'open-source-locator', { fact_id: 'fact-a' });
    expect(result).toEqual({ ok: false, refused: false, message: 'unsupported finance command' });
    expect(mocks.run).not.toHaveBeenCalled();
  });

  it('treats a template picker that returned no file as cancelled', async () => {
    registerIpc({ varRoot: '/store' });
    mocks.chooser.mockResolvedValue({ canceled: false, filePaths: [] });
    expect(await invoke(CHANNELS.reportTemplatePublish, task)).toEqual({ ok: true, value: { cancelled: true } });
    expect(mocks.run).not.toHaveBeenCalled();
  });

  it('refreshes finance source files only from the native file picker', async () => {
    registerIpc({ varRoot: '/store' });
    mocks.chooser.mockResolvedValue({ canceled: false, filePaths: ['/chosen/gl.csv'] });
    await invoke(CHANNELS.financeSourceRefresh, task, {
      path: '/renderer/secret.csv',
      scope: { source_id: 'erp', tenant_id: 'demo', ledger_id: 'gl', organization_id: 'east', period: '2026-08', currency: 'CNY', cutoff_at: '2026-08-31' },
      product: 'kingdee',
    });
    const encoded = mocks.run.mock.calls[0][2][1];
    expect(mocks.run).toHaveBeenCalledWith({ varRoot: '/store', task, actor: 'manager' }, 'finance-source-refresh', ['--spec', expect.any(String)]);
    expect(encoded).toContain('/chosen/gl.csv');
    expect(encoded).not.toContain('/renderer/secret.csv');
    mocks.chooser.mockResolvedValue({ canceled: true, filePaths: ['/chosen/gl.csv'] });
    expect(await invoke(CHANNELS.financeSourceRefresh, task, { scope: {} })).toEqual({ ok: true, value: { cancelled: true } });
    expect(mocks.run).toHaveBeenCalledTimes(1);
  });

  it('builds the 收费明细 flags itself from a fixed list of commands, as the manager, with room for millions of rows', async () => {
    registerIpc({ varRoot: '/store' });
    const as = { varRoot: '/store', task, actor: 'manager' };
    const detail = 'c'.repeat(32);
    await invoke(CHANNELS.billingCall, task, 'detail-list');
    expect(mocks.run).toHaveBeenLastCalledWith(as, 'detail-list', [], { timeoutMs: undefined });
    await invoke(CHANNELS.billingCall, task, 'detail-confirm', { detail, mapping: { bill_id: '应收单号' } });
    expect(mocks.run).toHaveBeenLastCalledWith(as, 'detail-confirm', ['--detail', detail, '--mapping', '{"bill_id":"应收单号"}'], { timeoutMs: undefined });
    await invoke(CHANNELS.billingCall, task, 'collection-caliber-confirm', { version: 2 });
    expect(mocks.run).toHaveBeenLastCalledWith(as, 'collection-caliber-confirm', ['--version', '2'], { timeoutMs: undefined });
    await invoke(CHANNELS.billingCall, task, 'collection-run', { as_of: '2026-08-31' });
    expect(mocks.run).toHaveBeenLastCalledWith(as, 'collection-run', ['--spec', '{"as_of":"2026-08-31"}'], { timeoutMs: 30 * 60_000 });
    const calls = mocks.run.mock.calls.length;
    expect((await invoke(CHANNELS.billingCall, task, 'detail-add', {})).ok).toBe(false);
    expect((await invoke(CHANNELS.billingCall, task, 'collection-caliber-propose', {})).ok).toBe(false);
    expect((await invoke(CHANNELS.billingCall, task, 'detail-confirm', { detail: '../x' })).ok).toBe(false);
    expect((await invoke(CHANNELS.billingCall, task, 'toString')).ok).toBe(false);
    expect(mocks.run).toHaveBeenCalledTimes(calls);
  });

  it('reads the 收费明细 of an archived task but adds, confirms and runs nothing there', async () => {
    registerIpc({ varRoot: '/store' });
    mocks.run.mockImplementation(async (_binding, command) => command === 'task-show'
      ? JSON.stringify({ task: { lifecycle_status: 'archived' } }) : '{}');
    expect((await invoke(CHANNELS.billingCall, task, 'collection-state')).ok).toBe(true);
    for (const [command, spec] of [['detail-confirm', { detail: 'c'.repeat(32) }], ['collection-caliber-confirm', { version: 1 }], ['collection-run', { as_of: '2026-08-31' }]] as const) {
      expect(await invoke(CHANNELS.billingCall, task, command, spec)).toMatchObject({ ok: false, refused: true });
    }
    expect((await invoke(CHANNELS.billingAdd, task, 'receipt')).ok).toBe(false);
    expect((await invoke(CHANNELS.taskSampleBilling, task)).ok).toBe(false);
    expect(mocks.chooser).not.toHaveBeenCalled();
    expect(mocks.run.mock.calls.map((call) => call[1]).filter((name) => name !== 'task-show')).toEqual(['collection-state']);
  });

  it('adds a detail table only from files the native picker returned, named after them', async () => {
    registerIpc({ varRoot: '/store' });
    mocks.chooser.mockResolvedValue({ canceled: false, filePaths: ['/chosen/应收_2025.csv', '/chosen/应收_2026.csv'] });
    expect((await invoke(CHANNELS.billingAdd, task, 'receivable')).ok).toBe(true);
    expect(mocks.chooser.mock.calls[0][0].properties).toContain('multiSelections');
    expect(mocks.run).toHaveBeenCalledWith({ varRoot: '/store', task, actor: 'manager' }, 'detail-add',
      ['--kind', 'receivable', '--name', '应收_2025 等 2 个文件', '--path', '/chosen/应收_2025.csv', '--path', '/chosen/应收_2026.csv'], { timeoutMs: 30 * 60_000 });
    expect((await invoke(CHANNELS.billingAdd, task, 'ledger')).ok).toBe(false);
    mocks.chooser.mockResolvedValue({ canceled: true, filePaths: [] });
    expect(await invoke(CHANNELS.billingAdd, task, 'receipt')).toEqual({ ok: true, value: { cancelled: true } });
    expect(mocks.run.mock.calls.filter((call) => call[1] === 'detail-add')).toHaveLength(1);
    await invoke(CHANNELS.taskSampleBilling, task);
    expect(mocks.run).toHaveBeenLastCalledWith({ varRoot: '/store', task, actor: 'manager' }, 'task-sample-billing', [], { timeoutMs: 30 * 60_000 });
  });
});

describe('embedded workspace IPC', () => {
  it('deduplicates concurrent explicit submissions and keeps passive resumes draft-free', async () => {
    const host = {open: vi.fn(), show: vi.fn(async (id) => ({sessionId: id, submitted: true}))};
    mocks.run.mockImplementation(async (_binding, command) => command === 'task-show' ? JSON.stringify({sessions:[{session_id:'existing',role:'analysis'}]}) : '{}');
    registerIpc({varRoot:'/store'}, {host,userData:()=>'/user'} as any);
    const seed = {verbatim:'分析利润',submit:true,requestId:'user-action-1'};
    const [first, second] = await Promise.all([invoke(CHANNELS.harnessOpen,'analysis',task,seed),invoke(CHANNELS.harnessOpen,'analysis',task,seed)]);
    expect(first).toEqual(second);
    expect(host.show).toHaveBeenCalledOnce();
    expect(host.show).toHaveBeenLastCalledWith('existing','分析利润','/workspace/task-a',undefined,{submit:true,requestId:'user-action-1'});
    expect((await invoke(CHANNELS.harnessOpen,'analysis',task,{...seed,verbatim:'不同内容'})).ok).toBe(false);
    await invoke(CHANNELS.harnessOpen,'analysis',task);
    expect(host.show).toHaveBeenLastCalledWith('existing',undefined,'/workspace/task-a',undefined);
  });
  it('takes zoom only from the owning renderer and delegates bounded geometry', async () => {
    const sender = {getZoomFactor:()=>1.25};
    const window = {webContents:sender};
    const host = {layout:vi.fn(()=>true)};
    registerIpc({varRoot:'/store'}, {host,userData:()=>'/user',window:()=>window} as any);
    const geometry = {x:200,y:100,width:420,height:600,revision:2};
    const handler = mocks.handlers.get(CHANNELS.harnessLayout)!;
    expect(await handler({sender},geometry)).toEqual({ok:true,value:{accepted:true}});
    expect(host.layout).toHaveBeenCalledWith(window,geometry,1.25);
    expect((await handler({sender:{getZoomFactor:()=>100}},geometry)).ok).toBe(false);
    expect(host.layout).toHaveBeenCalledOnce();
  });
  it('validates task rename before the domain mutation', async () => {
    registerIpc({varRoot:'/store'});
    await invoke(CHANNELS.taskRename,task,'  月度利润复盘  ');
    expect(mocks.run).toHaveBeenCalledWith({varRoot:'/store',task,actor:'manager'},'task-rename',['--title','月度利润复盘']);
    expect((await invoke(CHANNELS.taskRename,task,'bad\nname')).ok).toBe(false);
    expect(mocks.run).toHaveBeenCalledOnce();
  });

  it('answers task lifecycle changes through explicit task-scoped CLI commands', async () => {
    mocks.run.mockResolvedValue(JSON.stringify({ task_id: task, lifecycle_status: 'archived' }));
    registerIpc({varRoot:'/store'});
    expect(await invoke(CHANNELS.taskArchive, task)).toEqual({ok:true,value:{task_id:task,lifecycle_status:'archived'}});
    expect(mocks.run).toHaveBeenCalledWith({varRoot:'/store',task,actor:'manager'},'task-archive',[],undefined);
    expect((await invoke(CHANNELS.taskTrash, '../bad')).ok).toBe(false);
    expect(mocks.run).toHaveBeenCalledOnce();
  });

  it('purges one trashed task or empties a whole list through the CLI', async () => {
    mocks.run.mockResolvedValue(JSON.stringify({ task_ids: [task], lifecycle_status: 'purged' }));
    registerIpc({varRoot:'/store'});
    expect(await invoke(CHANNELS.taskPurge, task)).toEqual({ok:true,value:{task_ids:[task],lifecycle_status:'purged'}});
    expect(mocks.run).toHaveBeenLastCalledWith({varRoot:'/store',task,actor:'manager'},'task-purge',[],undefined);
    expect(await invoke(CHANNELS.taskEmpty, 'trashed', [task])).toEqual({ok:true,value:{task_ids:[task],lifecycle_status:'purged'}});
    expect(mocks.run).toHaveBeenLastCalledWith({varRoot:'/store',actor:'manager'},'task-empty',['--lifecycle','trashed','--only',task],undefined);
    expect((await invoke(CHANNELS.taskEmpty, 'active', [task])).ok).toBe(false);
    expect((await invoke(CHANNELS.taskEmpty, 'trashed', ['../bad'])).ok).toBe(false);
    expect(await invoke(CHANNELS.taskEmpty, 'trashed', [])).toEqual({ok:true,value:{task_ids:[],lifecycle_status:'purged'}});
    expect((await invoke(CHANNELS.taskPurge, '../bad')).ok).toBe(false);
    expect(mocks.run).toHaveBeenCalledTimes(2);
  });
});

describe('wait timing log', () => {
  const tempRoots: string[] = [];
  afterEach(async () => {
    vi.restoreAllMocks();
    const { rm } = await import('node:fs/promises');
    await Promise.all(tempRoots.splice(0).map((dir) => rm(dir, { recursive: true, force: true })));
  });
  async function userData() {
    const { mkdtemp } = await import('node:fs/promises');
    const { tmpdir } = await import('node:os');
    const dir = await mkdtemp(`${tmpdir()}/fnd-timing-`);
    tempRoots.push(dir);
    return dir;
  }
  async function lines(dir: string) {
    const { readFile } = await import('node:fs/promises');
    return (await readFile(`${dir}/wait-timing.jsonl`, 'utf8')).trim().split('\n');
  }

  it('appends one fixed-shape line per wait under userData, and nothing a person typed or a file held', async () => {
    const dir = await userData();
    registerIpc({ varRoot: '/store' }, { userData: () => dir } as any);
    const sent = { kind: 'finance.pnl', outcome: 'ok', waitMs: 1834.6, engineMs: 412,
      amount: '900719925474099.99', file: '/chosen/预算.xlsx', task, title: '华东经营分析' };
    expect(await invoke(CHANNELS.timingLog, sent)).toEqual({ ok: true, value: { written: true } });
    const [line, ...rest] = await lines(dir);
    expect(rest).toEqual([]);
    const row = JSON.parse(line);
    expect(Object.keys(row).sort()).toEqual(['at', 'engine_ms', 'kind', 'outcome', 'wait_ms']);
    expect(row).toMatchObject({ kind: 'finance.pnl', outcome: 'ok', wait_ms: 1835, engine_ms: 412 });
    expect(Number.isNaN(Date.parse(row.at))).toBe(false);
    for (const secret of ['900719925474099', '预算', 'chosen', task, '华东']) expect(line).not.toContain(secret);
    // A kind or a number is refused rather than written when it could carry anything else.
    expect((await invoke(CHANNELS.timingLog, { ...sent, kind: '华东 900719925474099.99' })).ok).toBe(false);
    expect((await invoke(CHANNELS.timingLog, { ...sent, waitMs: '1834' })).ok).toBe(false);
    expect((await invoke(CHANNELS.timingLog, { ...sent, outcome: '已完成' })).ok).toBe(false);
    expect(await lines(dir)).toHaveLength(1);
    // Never the task store: no foundry call was made.
    expect(mocks.run).not.toHaveBeenCalled();
  });

  it('takes the time the materials dialog was open off the import wait', async () => {
    const dir = await userData();
    let clock = 1_000;
    vi.spyOn(performance, 'now').mockImplementation(() => clock);
    registerIpc({ varRoot: '/store' }, { userData: () => dir } as any);
    mocks.chooser.mockImplementation(async () => { clock += 30_000; return { canceled: false, filePaths: ['/chosen/actual.csv'] }; });
    expect((await invoke(CHANNELS.analysisAddFiles, task)).ok).toBe(true);
    // The renderer timed 31.2 s from its click; 30 s of that was the manager picking a file.
    await invoke(CHANNELS.timingLog, { kind: 'materials.import', outcome: 'ok', waitMs: 31_200 });
    // Used once: a later wait with no dialog of its own keeps all of its time.
    await invoke(CHANNELS.timingLog, { kind: 'materials.import', outcome: 'error', waitMs: 500 });
    expect((await lines(dir)).map((line) => JSON.parse(line).wait_ms)).toEqual([1_200, 500]);
  });

  it('takes the time the source dialog was open off the source refresh wait, cancelled or not', async () => {
    const dir = await userData();
    let clock = 0;
    vi.spyOn(performance, 'now').mockImplementation(() => clock);
    registerIpc({ varRoot: '/store' }, { userData: () => dir } as any);
    mocks.chooser.mockImplementation(async () => { clock += 12_000; return { canceled: true, filePaths: [] }; });
    expect(await invoke(CHANNELS.financeSourceRefresh, task, { product: 'file' })).toEqual({ ok: true, value: { cancelled: true } });
    await invoke(CHANNELS.timingLog, { kind: 'source.refresh', outcome: 'cancelled', waitMs: 12_040 });
    // Another kind's wait is not shortened by this dialog.
    mocks.chooser.mockImplementation(async () => { clock += 9_000; return { canceled: false, filePaths: ['/chosen/erp.csv'] }; });
    await invoke(CHANNELS.financeSourceRefresh, task, { product: 'file' });
    await invoke(CHANNELS.timingLog, { kind: 'finance.pnl', outcome: 'ok', waitMs: 2_000 });
    expect((await lines(dir)).map((line) => JSON.parse(line).wait_ms)).toEqual([40, 2_000]);
  });
});
