import type { BrowserWindow } from 'electron';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const page = vi.hoisted(() => ({
  attached: false,
  origin: '',
  events: [] as string[],
  storage: new Map<string, Map<string, string>>(),
}));
vi.mock('../electron/harness/pane.js', () => ({
  Pane: class {
    attached() { return page.attached; }
    skin() {}
    focus() {}
    async attach(_window: BrowserWindow, origin: string) {
      page.attached = true;
      page.origin = origin;
    }
    async load(origin: string) {
      page.events.push(`load:${origin}`);
      page.origin = origin;
    }
    async run(script: string) {
      page.events.push(`${script.includes('?.snapshot()') ? 'snapshot' : script.includes('Object.entries') ? 'restore' : 'handoff'}:${page.origin}`);
      let storage = page.storage.get(page.origin);
      if (!storage) { storage = new Map(); page.storage.set(page.origin, storage); }
      // Browser storage belongs to the document origin, including after the
      // runtime process exits while its old document remains in the pane.
      const localStorage = {
        getItem: (key: string) => storage.get(key) ?? null,
        setItem: (key: string, value: string) => storage.set(key, value),
      };
      return new Function('window', `return ${script}`)({__foundryEmbedded: {
        version: 1,
        snapshot: () => ({drafts: Object.fromEntries([...storage].filter(([key]) => key.startsWith('dsh.conversation.chat.')).map(([key, value]) => [key.slice('dsh.conversation.chat.'.length), JSON.parse(value)])), receipts: {}}),
        dispatch: (request: {sessionId: string; draft?: string}) => {
          localStorage.setItem('dsh.sessions.current', JSON.stringify({sessionId: request.sessionId}));
          if (request.draft !== undefined) localStorage.setItem('dsh.conversation.chat.' + request.sessionId, JSON.stringify({selection: null, view: null, inspect: null, draft: request.draft}));
          return {sessionId: request.sessionId, submitted: false};
        }
      }, localStorage: {
        getItem: (key: string) => storage.get(key) ?? null,
        setItem: (key: string, value: string) => storage.set(key, value),
      } });
    }
  },
}));
import { HarnessHost } from '../electron/harness/host.js';
import { SESSION_SELECTION_KEY, chatStoreKey } from '../electron/harness/handoff.js';

const oldOrigin = 'http://127.0.0.1:41000';
const nextOrigin = 'http://127.0.0.1:42000';
function fixture() {
  const host = new HarnessHost({ entry: '/unused', home: '/unused', varRoot: '/unused', foundryBin: '/unused' });
  const start = vi.spyOn(host, 'start').mockResolvedValue(oldOrigin);
  return { host, start };
}
beforeEach(() => {
  page.attached = false; page.origin = ''; page.events.length = 0; page.storage.clear();
});

describe('harness conversation recovery', () => {
  it('selects and seeds a session without reloading when the runtime origin is unchanged', async () => {
    const { host } = fixture();
    await host.attach({} as BrowserWindow);
    await host.show('session-a', '比较本月利润');
    expect(page.events).toEqual([`handoff:${oldOrigin}`]);
    expect(JSON.parse(page.storage.get(oldOrigin)!.get(SESSION_SELECTION_KEY)!)).toEqual({ sessionId: 'session-a' });
    expect(JSON.parse(page.storage.get(oldOrigin)!.get(chatStoreKey('session-a'))!)).toEqual({ selection: null, view: null, inspect: null, draft: '比较本月利润' });
  });

  it('loads the restarted runtime origin before writing that origin\'s session and draft', async () => {
    const { host, start } = fixture();
    await host.attach({} as BrowserWindow);
    start.mockResolvedValue(nextOrigin);
    await host.show('session-b', '继续分析回款');
    expect(page.events).toEqual([`snapshot:${oldOrigin}`, `load:${nextOrigin}`, `restore:${nextOrigin}`, `load:${nextOrigin}`, `handoff:${nextOrigin}`]);
    expect(page.storage.get(oldOrigin)?.get(SESSION_SELECTION_KEY)).toBeUndefined();
    expect(JSON.parse(page.storage.get(nextOrigin)!.get(SESSION_SELECTION_KEY)!)).toEqual({ sessionId: 'session-b' });
    expect(JSON.parse(page.storage.get(nextOrigin)!.get(chatStoreKey('session-b'))!)).toEqual({ selection: null, view: null, inspect: null, draft: '继续分析回款' });

    page.events.length = 0;
    await host.show('session-c', '');
    expect(page.events).toEqual([`handoff:${nextOrigin}`]);
    expect(JSON.parse(page.storage.get(nextOrigin)!.get(SESSION_SELECTION_KEY)!)).toEqual({ sessionId: 'session-c' });
  });


  it('migrates unsent per-session drafts when the runtime port changes, and passive resume keeps them', async () => {
    const {host, start} = fixture();
    await host.attach({} as BrowserWindow);
    await host.show('session-a', '未发送的问题');
    start.mockResolvedValue(nextOrigin);
    page.events.length = 0;
    await host.show('session-a');
    expect(page.events).toEqual([`snapshot:${oldOrigin}`, `load:${nextOrigin}`, `restore:${nextOrigin}`, `load:${nextOrigin}`, `handoff:${nextOrigin}`]);
    expect(JSON.parse(page.storage.get(nextOrigin)!.get(chatStoreKey('session-a'))!).draft).toBe('未发送的问题');
  });

  it('refuses handoff before the pane is attached', async () => {
    const { host } = fixture();
    await expect(host.show('session-a', '问题')).rejects.toThrow('对话窗口尚未连接');
    expect(page.events).toEqual([]);
    expect(page.storage.size).toBe(0);
  });
});
