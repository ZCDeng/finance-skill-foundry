import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import * as path from 'node:path';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ handlers: new Map<string, (...args: any[]) => Promise<any>>(), openPath: vi.fn(async (_folder: string) => '') }));
vi.mock('electron', () => ({
  ipcMain: { handle: (name: string, handler: any) => mocks.handlers.set(name, handler) },
  app: { getVersion: () => '0.13.0' },
  shell: { openPath: mocks.openPath }, dialog: {},
}));
import { DEFAULT_PREFERENCES, preferencesPatchOf, readPreferences, writePreferences } from '../electron/preferences.js';
import { registerIpc } from '../electron/ipc/register.js';
import { CHANNELS } from '../electron/ipc/contract.js';

const folder = () => mkdtempSync(path.join(tmpdir(), 'preferences-'));
const invoke = (name: string, ...args: unknown[]) => mocks.handlers.get(name)!({}, ...args);

beforeEach(() => { mocks.handlers.clear(); mocks.openPath.mockClear(); });

describe('设置, kept beside the appearance', () => {
  it('starts with technical details off, and a missing, broken or foreign file reads as the defaults', () => {
    const dir = folder();
    expect(readPreferences(dir)).toEqual({ technical: false, brief_open: true, start: 'overview', samples_read: [], skipped_steps: {}, people: [], current_person: '' });
    writeFileSync(path.join(dir, 'preferences.json'), '{not json');
    expect(readPreferences(dir)).toEqual(DEFAULT_PREFERENCES);
    writeFileSync(path.join(dir, 'preferences.json'), JSON.stringify({ technical: 'yes', start: 'tasks', samples_read: ['practice', 'other'], extra: 1 }));
    expect(readPreferences(dir)).toEqual(DEFAULT_PREFERENCES);
  });

  it('writes a patch over what is saved and keeps the rest', () => {
    const dir = folder();
    expect(writePreferences(dir, { technical: true })).toEqual({ ...DEFAULT_PREFERENCES, technical: true });
    expect(writePreferences(dir, { start: 'workspace', samples_read: ['practice'] }))
      .toEqual({ technical: true, brief_open: true, start: 'workspace', samples_read: ['practice'], skipped_steps: {}, people: [], current_person: '' });
    expect(JSON.parse(readFileSync(path.join(dir, 'preferences.json'), 'utf8'))).toEqual(readPreferences(dir));
  });

  it('refuses a patch with an unknown key or a value of the wrong kind rather than dropping it', () => {
    expect(preferencesPatchOf({ brief_open: false })).toEqual({ brief_open: false });
    expect(() => preferencesPatchOf({ theme: 'dark' })).toThrow(/unknown preference/);
    expect(() => preferencesPatchOf({ technical: 1 })).toThrow(/bad value for technical/);
    expect(() => preferencesPatchOf({ start: 'tasks' })).toThrow(/bad value for start/);
    expect(() => preferencesPatchOf({ samples_read: ['practice', 'practice'] })).toThrow(/bad value for samples_read/);
    expect(() => preferencesPatchOf([])).toThrow(/must be an object/);
  });

  it('keeps 本期不做 per task, only for the steps after 范围, each list without repeats and never empty', () => {
    const dir = folder();
    const task = 'a'.repeat(32);
    expect(preferencesPatchOf({ skipped_steps: { [task]: ['close', 'report'] } })).toEqual({ skipped_steps: { [task]: ['close', 'report'] } });
    expect(preferencesPatchOf({ skipped_steps: {} })).toEqual({ skipped_steps: {} });
    for (const bad of [{ [task]: ['materials'] }, { [task]: ['scope'] }, { [task]: [] }, { [task]: ['close', 'close'] }, { 'not a task id': ['close'] }, [], 'close']) {
      expect(() => preferencesPatchOf({ skipped_steps: bad })).toThrow(/bad value for skipped_steps/);
    }
    writePreferences(dir, { skipped_steps: { [task]: ['close'] } });
    expect(readPreferences(dir).skipped_steps).toEqual({ [task]: ['close'] });
    writeFileSync(path.join(dir, 'preferences.json'), JSON.stringify({ skipped_steps: { [task]: ['scope'] } }));
    expect(readPreferences(dir).skipped_steps).toEqual({});
  });

  it('keeps the people who use this computer and who is signing now, each name on one line and each id once', () => {
    const dir = folder();
    expect(DEFAULT_PREFERENCES.people).toEqual([]);
    expect(DEFAULT_PREFERENCES.current_person).toBe('');
    const zhang = { id: 'p1', name: '张三', role: 'manager' as const, signature: '财务部 张三' };
    const li = { id: 'p2', name: '李四', role: 'reviewer' as const, signature: '李四' };
    expect(preferencesPatchOf({ people: [zhang, li], current_person: 'p1' })).toEqual({ people: [zhang, li], current_person: 'p1' });
    expect(preferencesPatchOf({ current_person: '' })).toEqual({ current_person: '' });
    for (const bad of [
      [{ ...zhang, role: 'admin' }], [{ ...zhang, name: '' }], [{ ...zhang, name: ' 张三' }], [{ ...zhang, signature: '张\n三' }],
      [{ ...zhang, signature: '张'.repeat(81) }], [zhang, { ...li, id: 'p1' }], [{ ...zhang, password: '1' }], [{ id: 'p1', name: '张三', role: 'manager' }],
      Array.from({ length: 21 }, (_, n) => ({ ...zhang, id: `p${n}` })), {},
    ]) {
      expect(() => preferencesPatchOf({ people: bad })).toThrow(/bad value for people/);
    }
    expect(() => preferencesPatchOf({ current_person: 'not an id' })).toThrow(/bad value for current_person/);
    writePreferences(dir, { people: [zhang], current_person: 'p1' });
    expect(readPreferences(dir)).toMatchObject({ people: [zhang], current_person: 'p1' });
    // A list with one broken entry is not half kept: it reads as nobody, and every name is typed again.
    writeFileSync(path.join(dir, 'preferences.json'), JSON.stringify({ people: [zhang, { ...li, role: 'owner' }], current_person: 'p1' }));
    expect(readPreferences(dir)).toMatchObject({ people: [], current_person: 'p1' });
  });

  it('answers over IPC, says which version this is and where its data lives, and opens that folder', async () => {
    const dir = folder();
    registerIpc({ varRoot: '/store' }, undefined, { folder: () => dir, apply: vi.fn() });
    expect(await invoke(CHANNELS.preferencesGet)).toEqual({ ok: true, value: DEFAULT_PREFERENCES });
    expect(await invoke(CHANNELS.preferencesSet, { technical: true })).toEqual({ ok: true, value: { ...DEFAULT_PREFERENCES, technical: true } });
    expect((await invoke(CHANNELS.preferencesSet, { technical: 'on' })).ok).toBe(false);
    expect(await invoke(CHANNELS.preferencesGet)).toEqual({ ok: true, value: { ...DEFAULT_PREFERENCES, technical: true } });
    expect(await invoke(CHANNELS.appInfo)).toEqual({ ok: true, value: { version: '0.13.0', data_folder: '/store' } });
    expect(await invoke(CHANNELS.appRevealData)).toEqual({ ok: true, value: { revealed: true } });
    expect(mocks.openPath).toHaveBeenCalledWith('/store');
    mocks.openPath.mockResolvedValueOnce('no such folder');
    expect((await invoke(CHANNELS.appRevealData)).ok).toBe(false);
  });

  it('answers rather than hangs in a build without an app folder', async () => {
    registerIpc({ varRoot: '/store' });
    expect((await invoke(CHANNELS.preferencesGet)).ok).toBe(false);
    expect((await invoke(CHANNELS.preferencesSet, { technical: true })).ok).toBe(false);
  });
});
