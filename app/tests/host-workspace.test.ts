import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const pane = vi.hoisted(() => ({ run: vi.fn(), load: vi.fn() }));
vi.mock('../electron/harness/pane.js', () => ({
  Pane: class {
    attached() { return true; }
    async run(script: string) {
      if (script.includes('?.snapshot()')) return {};
      pane.run(script);
      return {sessionId: JSON.parse(script.match(/dispatch\((.*)\);/)![1]).sessionId, submitted: false};
    }
    focus() {}
    async load(origin: string) { pane.load(origin); }
  },
}));
import { HarnessHost } from '../electron/harness/host.js';

const cwd = '/task-workspaces/finance';
const workspaceId = 'workspace-finance';
const workspace = { workspaceId, path: cwd, title: 'finance', sessionIds: [], createdAt: '2026-09-06', updatedAt: '2026-09-06' };
const response = (value: unknown): { ok: boolean; json(): Promise<unknown> } => ({
  ok: true, json: async () => ({ result: { ok: true, value } }),
});
type Request = { method: string; payload: Record<string, unknown> };
function fixture(options: { title?: string; renameFailures?: string[] } = {}) {
  const requests: Request[] = [];
  let title = options.title ?? workspace.title;
  const renameFailures = [...(options.renameFailures ?? [])];
  const fetch = vi.fn(async (_url: string, options: RequestInit) => {
    const request = JSON.parse(String(options.body)) as Request;
    requests.push({ method: request.method, payload: request.payload });
    // These are the staged host-apiproxy schemas: workspace.create nests its
    // WorkspaceView, and session.create accepts workspaceId OR cwd, not both.
    if (request.method === 'workspace.create') return response({ workspace: { ...workspace, title }, created: false });
    if (request.method === 'workspace.rename') {
      const code = renameFailures.shift();
      if (code) return { ok: true, json: async () => ({ result: { ok: false, error: { code, message: 'rename refused' } } }) };
      title = String(request.payload.title);
      return response({ workspace: { ...workspace, title } });
    }
    if (request.method === 'session.create') {
      if (request.payload.workspaceId !== workspaceId || 'cwd' in request.payload) {
        throw new Error('session.create needs the registered workspaceId without cwd');
      }
      return response({ sessionId: request.payload.sessionId ?? 'session-new', agentPreset: 'analysis' });
    }
    throw new Error(`unexpected method: ${request.method}`);
  });
  vi.stubGlobal('fetch', fetch);
  const host = new HarnessHost({ entry: '/unused', home: '/unused', varRoot: '/unused', foundryBin: '/unused' });
  vi.spyOn(host, 'start').mockResolvedValue('http://127.0.0.1:41000');
  return { host, requests, fetch };
}
beforeEach(() => { pane.run.mockReset(); pane.load.mockReset(); });
afterEach(() => { vi.unstubAllGlobals(); });

describe('harness task workspace binding', () => {
  it('adopts the task directory before creating the conversation in that workspace', async () => {
    const { host, requests } = fixture();
    await expect(host.open('analysis', cwd, undefined, true)).resolves.toEqual({ sessionId: 'session-new', preset: 'analysis' });
    expect(requests).toEqual([
      { method: 'workspace.create', payload: { path: cwd } },
      { method: 'session.create', payload: { agentPreset: 'analysis', workspaceId } },
    ]);
    expect(pane.run).not.toHaveBeenCalled();
  });

  it('reattaches an existing conversation to its task workspace before showing it', async () => {
    const { host, requests } = fixture();
    pane.run.mockImplementation(() => expect(requests).toEqual([
      { method: 'workspace.create', payload: { path: cwd } },
      { method: 'session.create', payload: { sessionId: 'session-existing', workspaceId } },
    ]));
    await host.show('session-existing', '继续分析利润', cwd);
    expect(pane.run).toHaveBeenCalledOnce();
  });

  it('does not hand off when the attachment returns a different session id', async () => {
    const { host, fetch } = fixture();
    fetch.mockResolvedValueOnce(response({ workspace, created: false }));
    fetch.mockResolvedValueOnce(response({ sessionId: 'different-session' }));
    await expect(host.show('session-existing', '继续分析', cwd)).rejects.toThrow('session id');
    expect(pane.run).not.toHaveBeenCalled();
  });

  it.each([{}, { workspace: { workspaceId: '' } }, { workspace: { workspaceId: 42 } }])(
    'refuses malformed workspace registration before creating a session: %j', async (value) => {
      const { host, fetch } = fixture();
      fetch.mockResolvedValueOnce(response(value));
      await expect(host.open('analysis', cwd, undefined, true)).rejects.toThrow('workspace id');
      expect(fetch).toHaveBeenCalledOnce();
      expect(pane.run).not.toHaveBeenCalled();
    },
  );

  it('surfaces workspace attachment refusal without showing an unusable conversation', async () => {
    const { host, fetch } = fixture();
    fetch.mockResolvedValueOnce(response({ workspace, created: false }));
    fetch.mockResolvedValueOnce({ ok: true, json: async () => ({ result: { ok: false, error: { message: 'workspace attachment refused' } } }) });
    await expect(host.show('session-existing', '继续分析', cwd)).rejects.toThrow('workspace attachment refused');
    expect(pane.run).not.toHaveBeenCalled();
  });

  it('replaces only the default directory title with the task business title', async () => {
    const { host, requests } = fixture();
    await host.show('session-existing', '分析利润', cwd, '  华东月度经营分析  ');
    expect(requests).toEqual([
      { method: 'workspace.create', payload: { path: cwd } },
      { method: 'workspace.rename', payload: { workspaceId, title: '华东月度经营分析' } },
      { method: 'session.create', payload: { sessionId: 'session-existing', workspaceId } },
    ]);
    await host.show('session-existing', '', cwd, '后来修改的任务标题');
    expect(requests.filter((request) => request.method === 'workspace.rename')).toHaveLength(1);
    expect(pane.run).toHaveBeenCalledTimes(2);
  });

  it('preserves an existing custom workspace title', async () => {
    const { host, requests } = fixture({ title: '财务经理自己的名字' });
    await host.show('session-existing', '', cwd, '华东月度经营分析');
    expect(requests.some((request) => request.method === 'workspace.rename')).toBe(false);
    expect(pane.run).toHaveBeenCalledOnce();
  });

  it('adds a stable short identifier only after the API reports a name conflict', async () => {
    const { host, requests } = fixture({ renameFailures: ['workspace-name-conflict'] });
    await host.show('session-existing', '', cwd, '月度分析');
    expect(requests.filter((request) => request.method === 'workspace.rename').map((request) => request.payload)).toEqual([
      { workspaceId, title: '月度分析' },
      { workspaceId, title: `月度分析 · ${workspaceId.slice(-8)}` },
    ]);
    expect(pane.run).toHaveBeenCalledOnce();
  });

  it('continues the correctly bound conversation when both name candidates conflict', async () => {
    const { host, requests } = fixture({ renameFailures: ['workspace-name-conflict', 'workspace-name-conflict'] });
    await host.show('session-existing', '', cwd, '月度分析');
    expect(requests.filter((request) => request.method === 'workspace.rename')).toHaveLength(2);
    expect(requests.at(-1)).toEqual({ method: 'session.create', payload: { sessionId: 'session-existing', workspaceId } });
    expect(pane.run).toHaveBeenCalledOnce();
  });

  it('does not misclassify an unrelated rename failure as a naming conflict', async () => {
    const { host, requests } = fixture({ renameFailures: ['workspace-not-found'] });
    await expect(host.show('session-existing', '', cwd, '月度分析')).rejects.toThrow('rename refused');
    expect(requests.filter((request) => request.method === 'workspace.rename')).toHaveLength(1);
    expect(pane.run).not.toHaveBeenCalled();
  });

  it('does not swallow connection failure while resolving a workspace title', async () => {
    const { host, fetch } = fixture();
    fetch.mockRejectedValueOnce(new Error('connection lost'));
    await expect(host.show('session-existing', '', cwd, '月度分析')).rejects.toThrow('connection lost');
    expect(fetch).toHaveBeenCalledOnce();
    expect(pane.run).not.toHaveBeenCalled();
  });
});
