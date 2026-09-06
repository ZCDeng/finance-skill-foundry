import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  handlers: new Map<string, (...args: any[]) => Promise<any>>(),
  run: vi.fn(), openPath: vi.fn(), chooser: vi.fn(), workspace: vi.fn(),
}));
vi.mock('electron', () => ({
  ipcMain: { handle: (name: string, handler: any) => mocks.handlers.set(name, handler) },
  shell: { openPath: mocks.openPath }, dialog: { showOpenDialog: mocks.chooser },
}));
vi.mock('../electron/foundry.js', async (original) => ({
  ...await original<typeof import('../electron/foundry.js')>(), runFoundry: mocks.run,
}));
vi.mock('../electron/harness/workspace.js', () => ({ ensureTaskWorkspace: mocks.workspace }));
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
    expect(mocks.run).toHaveBeenCalledWith({ varRoot: '/store', task }, 'dataset-add', [
      '--path', '/chosen/actual.csv', '--name', 'actual.csv',
    ]);
    mocks.chooser.mockResolvedValue({ canceled: true, filePaths: ['/chosen/actual.csv'] });
    expect(await invoke(CHANNELS.analysisAddFiles, task)).toEqual({ ok: true, value: [] });
    expect(mocks.run).toHaveBeenCalledTimes(1);
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
    expect(mocks.run).toHaveBeenCalledWith({ varRoot: '/store', task, session: 'session-a' }, 'record-session', [
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
    expect(mocks.run).toHaveBeenCalledWith({ varRoot: '/store', task, session: 'root' }, 'analysis-refresh');
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

  it('exports the domain resolved file and keeps an opener error recoverable', async () => {
    registerIpc({ varRoot: '/store' });
    mocks.run.mockResolvedValue(JSON.stringify({ path: '/store/artifact.xlsx', sha256: 'hash' }));
    mocks.openPath.mockResolvedValue('No application can open this file');
    const result = await invoke(CHANNELS.analysisExport, task, 'draft-a', 'xlsx');
    expect(result.ok).toBe(true);
    expect(result.value.open_error).toBeTruthy();
    expect(mocks.openPath).toHaveBeenCalledWith('/store/artifact.xlsx');
    expect((await invoke(CHANNELS.analysisExport, task, '../escape', 'xlsx')).ok).toBe(false);
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
    await invoke(CHANNELS.financeCall, task, 'prepare-explanation', { run_ids: ['run-a'] });
    await invoke(CHANNELS.financeCall, task, 'validate-explanation', { draft_id: 'draft-a' });
    await invoke(CHANNELS.financeCall, task, 'finance-background-save', { text: '销售提前确认', basis: 'professional_judgment', scope: { ledger: '总账' }, effective_from: '2026-08' });
    await invoke(CHANNELS.financeCall, task, 'finance-background-list', { scope: { ledger: '总账' }, as_of: '2026-08' });
    expect(mocks.run.mock.calls.map((call) => call[1])).toEqual([
      'list-finance-context',
      'finance-source-list',
      'finance-context-save',
      'finance-scenario-save',
      'explain-variance',
      'workbook-preview',
      'drilldown-fact',
      'prepare-explanation',
      'validate-explanation',
      'finance-background-save',
      'finance-background-list',
    ]);
    expect(mocks.run.mock.calls[0][2]).toEqual([]);
    expect(mocks.run.mock.calls[1][2]).toEqual([]);
    expect(mocks.run.mock.calls[2][2]).toEqual(['--spec', expect.stringContaining('\"bindings\"')]);
    const varianceSpec = JSON.parse(mocks.run.mock.calls[4][2][1]);
    expect(varianceSpec.dimensions).toEqual(['organization', 'period']);
    expect(varianceSpec.dimensions).not.toContain('management_account');
    expect((await invoke(CHANNELS.financeCall, task, 'dataset-add', { path: '/tmp/secret.csv' })).ok).toBe(false);
    expect((await invoke(CHANNELS.financeCall, task, 'list-finance-context', { unexpected: true })).ok).toBe(false);
    const backgroundListSpec = JSON.parse(mocks.run.mock.calls[10][2][1]);
    expect(backgroundListSpec.scope).toEqual({ ledger: '总账' });
    expect((await invoke(CHANNELS.financeCall, task, 'run-metric', ['not an object'])).ok).toBe(false);
    expect(mocks.run).toHaveBeenCalledTimes(11);
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
    expect(mocks.run).toHaveBeenCalledWith({ varRoot: '/store', task }, 'finance-source-refresh', ['--spec', expect.any(String)]);
    expect(encoded).toContain('/chosen/gl.csv');
    expect(encoded).not.toContain('/renderer/secret.csv');
    mocks.chooser.mockResolvedValue({ canceled: true, filePaths: ['/chosen/gl.csv'] });
    expect(await invoke(CHANNELS.financeSourceRefresh, task, { scope: {} })).toEqual({ ok: true, value: { cancelled: true } });
    expect(mocks.run).toHaveBeenCalledTimes(1);
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
    expect(mocks.run).toHaveBeenCalledWith({varRoot:'/store',task},'task-rename',['--title','月度利润复盘']);
    expect((await invoke(CHANNELS.taskRename,task,'bad\nname')).ok).toBe(false);
    expect(mocks.run).toHaveBeenCalledOnce();
  });
});
