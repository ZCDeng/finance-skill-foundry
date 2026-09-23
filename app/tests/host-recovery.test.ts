import { mkdtempSync, readFileSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import type { BrowserWindow } from 'electron';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const page = vi.hoisted(() => ({
  attached: false,
  origin: '',
  events: [] as string[],
  storage: new Map<string, Map<string, string>>(),
  touched: new Set<string>(),
  currentDrafts: new Map<string, {selection: null; view: null; inspect: null; draft: string}>(),
  currentReferences: new Map<string, string>(),
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
        removeItem: (key: string) => storage.delete(key),
      };
      return new Function('window', `return ${script}`)({__foundryEmbedded: {
        version: 1,
        snapshot: () => {
          for (const id of page.touched) {
            const draft = page.currentDrafts.get(id);
            if (draft) storage.set('dsh.conversation.chat.' + id, JSON.stringify(draft));
            const refKey = 'fnd.references.' + id;
            const refs = page.currentReferences.get(id);
            if (refs) storage.set(refKey, refs);
            else storage.delete(refKey);
          }
          return {
            drafts: Object.fromEntries([...storage].filter(([key]) => key.startsWith('dsh.conversation.chat.')).map(([key, value]) => [key.slice('dsh.conversation.chat.'.length), JSON.parse(value)])),
            receipts: Object.fromEntries([...storage].filter(([key]) => key.startsWith('fnd.submitted.'))),
            references: Object.fromEntries([...storage].filter(([key]) => key.startsWith('fnd.references.'))),
          };
        },
        dispatch: (request: {sessionId: string; draft?: string; draftReference?: {draftId: string; revision: number}; submit?: boolean}) => {
          page.touched.add(request.sessionId);
          localStorage.setItem('dsh.sessions.current', JSON.stringify({sessionId: request.sessionId}));
          if (request.draft !== undefined) {
            const prefix = request.draftReference ? `基于修订 ${request.draftReference.revision}` : '';
            const draft = prefix ? `${prefix} ${request.draft}` : request.draft;
            const value = {selection: null, view: null, inspect: null, draft};
            page.currentDrafts.set(request.sessionId, value);
            localStorage.setItem('dsh.conversation.chat.' + request.sessionId, JSON.stringify(value));
            if (request.draftReference) {
              const refs = JSON.stringify({draft, occurrences:[{source:'foundry-draft',ref:JSON.stringify(request.draftReference),offset:0,length:prefix.length,label:prefix,clipboardText:prefix}]});
              page.currentReferences.set(request.sessionId, refs);
              localStorage.setItem('fnd.references.' + request.sessionId, refs);
            }
          } else {
            try {
              const saved = JSON.parse(localStorage.getItem('dsh.conversation.chat.' + request.sessionId) ?? 'null');
              if (saved && typeof saved.draft === 'string') page.currentDrafts.set(request.sessionId, saved);
            } catch {}
            const refs = localStorage.getItem('fnd.references.' + request.sessionId);
            if (refs) page.currentReferences.set(request.sessionId, refs);
          }
          if (request.submit) {
            const value = {selection: null, view: null, inspect: null, draft: ''};
            page.currentDrafts.set(request.sessionId, value);
            page.currentReferences.delete(request.sessionId);
            localStorage.setItem('dsh.conversation.chat.' + request.sessionId, JSON.stringify(value));
            localStorage.removeItem('fnd.references.' + request.sessionId);
            return {sessionId: request.sessionId, submitted: true};
          }
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
function privateVarRoot() { return mkdtempSync(join(tmpdir(), 'fa-host-recovery-')); }
function fixture(varRoot = privateVarRoot()) {
  const host = new HarnessHost({ entry: '/unused', home: '/unused', varRoot, foundryBin: '/unused' });
  const start = vi.spyOn(host, 'start').mockResolvedValue(oldOrigin);
  return { host, start, varRoot };
}
beforeEach(() => {
  vi.useRealTimers();
  page.attached = false; page.origin = ''; page.events.length = 0; page.storage.clear(); page.touched.clear(); page.currentDrafts.clear(); page.currentReferences.clear();
});
afterEach(() => { vi.useRealTimers(); });

describe('harness conversation recovery', () => {
  it('selects and seeds a session without reloading when the runtime origin is unchanged', async () => {
    const { host } = fixture();
    await host.attach({} as BrowserWindow);
    await host.show('session-a', '比较本月利润');
    expect(page.events).toEqual([`handoff:${oldOrigin}`, `snapshot:${oldOrigin}`]);
    expect(JSON.parse(page.storage.get(oldOrigin)!.get(SESSION_SELECTION_KEY)!)).toEqual({ sessionId: 'session-a' });
    expect(JSON.parse(page.storage.get(oldOrigin)!.get(chatStoreKey('session-a'))!)).toEqual({ selection: null, view: null, inspect: null, draft: '比较本月利润' });
  });

  it('loads the restarted runtime origin before writing that origin\'s session and draft', async () => {
    const { host, start } = fixture();
    await host.attach({} as BrowserWindow);
    start.mockResolvedValue(nextOrigin);
    await host.show('session-b', '继续分析回款');
    expect(page.events).toEqual([`snapshot:${oldOrigin}`, `load:${nextOrigin}`, `handoff:${nextOrigin}`, `snapshot:${nextOrigin}`]);
    expect(page.storage.get(oldOrigin)?.get(SESSION_SELECTION_KEY)).toBeUndefined();
    expect(JSON.parse(page.storage.get(nextOrigin)!.get(SESSION_SELECTION_KEY)!)).toEqual({ sessionId: 'session-b' });
    expect(JSON.parse(page.storage.get(nextOrigin)!.get(chatStoreKey('session-b'))!)).toEqual({ selection: null, view: null, inspect: null, draft: '继续分析回款' });

    page.events.length = 0;
    await host.show('session-c', '');
    expect(page.events).toEqual([`handoff:${nextOrigin}`, `snapshot:${nextOrigin}`]);
    expect(JSON.parse(page.storage.get(nextOrigin)!.get(SESSION_SELECTION_KEY)!)).toEqual({ sessionId: 'session-c' });
  });


  it('migrates unsent per-session drafts when the runtime port changes, and passive resume keeps them', async () => {
    const {host, start} = fixture();
    await host.attach({} as BrowserWindow);
    await host.show('session-a', '未发送的问题');
    start.mockResolvedValue(nextOrigin);
    page.events.length = 0;
    await host.show('session-a');
    expect(page.events).toEqual([`snapshot:${oldOrigin}`, `load:${nextOrigin}`, `restore:${nextOrigin}`, `load:${nextOrigin}`, `handoff:${nextOrigin}`, `snapshot:${nextOrigin}`]);
    expect(JSON.parse(page.storage.get(nextOrigin)!.get(chatStoreKey('session-a'))!).draft).toBe('未发送的问题');
  });

  it('migrates structured revision sidecars with the session draft on runtime restart', async () => {
    const {host, start} = fixture();
    await host.attach({} as BrowserWindow);
    page.storage.set(oldOrigin, new Map());
    page.storage.get(oldOrigin)!.set('dsh.conversation.chat.session-a', JSON.stringify({selection:null, view:null, inspect:null, draft:'基于修订 2 继续分析'}));
    page.storage.get(oldOrigin)!.set('fnd.references.session-a', JSON.stringify({draft:'基于修订 2 继续分析', occurrences:[{source:'foundry-draft',ref:'{"draftId":"draft-a","revision":2}',offset:0,length:6,label:'基于修订 2',clipboardText:'基于修订 2'}]}));
    start.mockResolvedValue(nextOrigin);
    await host.show('session-a');
    expect(page.storage.get(nextOrigin)!.get('fnd.references.session-a')).toContain('draft-a');
  });

  it('restores structured revision sidecars after a full app restart with a new runtime port', async () => {
    const first = fixture();
    await first.host.attach({} as BrowserWindow);
    await first.host.show('session-a', '继续分析', undefined, undefined, {draftReference:{draftId:'draft-a',revision:2}});
    expect(page.storage.get(oldOrigin)!.get('fnd.references.session-a')).toContain('draft-a');

    page.attached = false;
    page.origin = '';
    page.events.length = 0;
    const restarted = fixture(first.varRoot);
    restarted.start.mockResolvedValue(nextOrigin);
    await restarted.host.attach({} as BrowserWindow);
    await restarted.host.show('session-a');

    expect(page.events).toEqual([`restore:${nextOrigin}`, `load:${nextOrigin}`, `handoff:${nextOrigin}`, `snapshot:${nextOrigin}`]);
    expect(JSON.parse(page.storage.get(nextOrigin)!.get(chatStoreKey('session-a'))!).draft).toBe('基于修订 2 继续分析');
    expect(page.storage.get(nextOrigin)!.get('fnd.references.session-a')).toContain('draft-a');
  });

  it('persists ordinary edits after handoff and restores the latest draft after restart', async () => {
    vi.useFakeTimers();
    const first = fixture();
    await first.host.attach({} as BrowserWindow);
    await first.host.show('session-a', '继续分析', undefined, undefined, {draftReference:{draftId:'draft-a',revision:2}});
    page.currentDrafts.set('session-a', {selection:null, view:null, inspect:null, draft:'基于修订 2 用户手动改过的新问题'});
    page.currentReferences.set('session-a', JSON.stringify({draft:'基于修订 2 用户手动改过的新问题', occurrences:[{source:'foundry-draft',ref:'{"draftId":"draft-a","revision":2}',offset:0,length:6,label:'基于修订 2',clipboardText:'基于修订 2'}]}));
    await vi.advanceTimersByTimeAsync(1000);
    first.host.stop();
    vi.useRealTimers();

    page.attached = false; page.origin = ''; page.events.length = 0; page.touched.clear(); page.currentDrafts.clear(); page.currentReferences.clear();
    const restarted = fixture(first.varRoot);
    restarted.start.mockResolvedValue(nextOrigin);
    await restarted.host.attach({} as BrowserWindow);
    await restarted.host.show('session-a');

    expect(JSON.parse(page.storage.get(nextOrigin)!.get(chatStoreKey('session-a'))!).draft).toBe('基于修订 2 用户手动改过的新问题');
    expect(page.storage.get(nextOrigin)!.get('fnd.references.session-a')).toContain('draft-a');
    expect((statSync(join(first.varRoot, 'harness-draft-snapshot.json')).mode & 0o777)).toBe(0o600);
  });

  it('persists deleted references and empty drafts so restart does not resurrect stale chips', async () => {
    vi.useFakeTimers();
    const first = fixture();
    await first.host.attach({} as BrowserWindow);
    await first.host.show('session-a', '继续分析', undefined, undefined, {draftReference:{draftId:'draft-a',revision:2}});
    page.currentDrafts.set('session-a', {selection:null, view:null, inspect:null, draft:''});
    page.currentReferences.delete('session-a');
    await vi.advanceTimersByTimeAsync(1000);
    first.host.stop();
    vi.useRealTimers();
    const persisted = JSON.parse(readFileSync(join(first.varRoot, 'harness-draft-snapshot.json'), 'utf8'));
    expect(persisted.drafts['session-a'].draft).toBe('');
    expect(persisted.references['fnd.references.session-a']).toBeUndefined();

    page.attached = false; page.origin = ''; page.events.length = 0; page.touched.clear(); page.currentDrafts.clear(); page.currentReferences.clear();
    const restarted = fixture(first.varRoot);
    restarted.start.mockResolvedValue(nextOrigin);
    await restarted.host.attach({} as BrowserWindow);
    await restarted.host.show('session-a');

    expect(JSON.parse(page.storage.get(nextOrigin)!.get(chatStoreKey('session-a'))!).draft).toBe('');
    expect(page.storage.get(nextOrigin)!.get('fnd.references.session-a')).toBeUndefined();
  });

  it('persists successful native submit clearing so restart does not resend sent text', async () => {
    const first = fixture();
    await first.host.attach({} as BrowserWindow);
    await first.host.show('session-a', '继续分析', undefined, undefined, {draftReference:{draftId:'draft-a',revision:2}});
    await first.host.show('session-a', '基于修订 2 继续分析', undefined, undefined, {submit:true, requestId:'send-1'});
    const persisted = JSON.parse(readFileSync(join(first.varRoot, 'harness-draft-snapshot.json'), 'utf8'));
    expect(persisted.drafts['session-a'].draft).toBe('');
    expect(persisted.references['fnd.references.session-a']).toBeUndefined();

    page.attached = false; page.origin = ''; page.events.length = 0; page.touched.clear(); page.currentDrafts.clear(); page.currentReferences.clear();
    const restarted = fixture(first.varRoot);
    restarted.start.mockResolvedValue(nextOrigin);
    await restarted.host.attach({} as BrowserWindow);
    await restarted.host.show('session-a');

    expect(JSON.parse(page.storage.get(nextOrigin)!.get(chatStoreKey('session-a'))!).draft).toBe('');
    expect(page.storage.get(nextOrigin)!.get('fnd.references.session-a')).toBeUndefined();
  });

  it('keeps restored but unopened session drafts across a second restart', async () => {
    vi.useFakeTimers();
    const first = fixture();
    await first.host.attach({} as BrowserWindow);
    await first.host.show('session-a', '继续 A', undefined, undefined, {draftReference:{draftId:'draft-a',revision:2}});
    await first.host.show('session-b', '继续 B', undefined, undefined, {draftReference:{draftId:'draft-b',revision:3}});

    page.attached = false; page.origin = ''; page.events.length = 0; page.touched.clear(); page.currentDrafts.clear(); page.currentReferences.clear();
    const second = fixture(first.varRoot);
    second.start.mockResolvedValue(nextOrigin);
    await second.host.attach({} as BrowserWindow);
    await second.host.show('session-a');
    await vi.advanceTimersByTimeAsync(1000);
    second.host.stop();
    vi.useRealTimers();
    const persistedAfterAOnly = JSON.parse(readFileSync(join(first.varRoot, 'harness-draft-snapshot.json'), 'utf8'));
    expect(persistedAfterAOnly.drafts['session-b'].draft).toBe('基于修订 3 继续 B');
    expect(persistedAfterAOnly.references['fnd.references.session-b']).toContain('draft-b');

    page.attached = false; page.origin = ''; page.events.length = 0; page.touched.clear(); page.currentDrafts.clear(); page.currentReferences.clear();
    const third = fixture(first.varRoot);
    third.start.mockResolvedValue('http://127.0.0.1:43000');
    await third.host.attach({} as BrowserWindow);
    await third.host.show('session-b');

    expect(JSON.parse(page.storage.get('http://127.0.0.1:43000')!.get(chatStoreKey('session-b'))!).draft).toBe('基于修订 3 继续 B');
    expect(page.storage.get('http://127.0.0.1:43000')!.get('fnd.references.session-b')).toContain('draft-b');
  });

  it('refuses handoff before the pane is attached', async () => {
    const { host } = fixture();
    await expect(host.show('session-a', '问题')).rejects.toThrow('对话窗口尚未连接');
    expect(page.events).toEqual([]);
    expect(page.storage.size).toBe(0);
  });
});
