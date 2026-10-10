import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import * as path from 'node:path';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ handlers: new Map<string, (...args: any[]) => Promise<any>>() }));
vi.mock('electron', () => ({
  ipcMain: { handle: (name: string, handler: any) => mocks.handlers.set(name, handler) },
  shell: {}, dialog: {},
}));
import { readFirstLook, writeFirstLook } from '../electron/firstLook.js';
import { registerIpc } from '../electron/ipc/register.js';
import { CHANNELS } from '../electron/ipc/contract.js';

const folder = () => mkdtempSync(path.join(tmpdir(), 'first-look-'));
const invoke = (name: string) => mocks.handlers.get(name)!({});

beforeEach(() => mocks.handlers.clear());

describe('60 秒看看它能做什么, once', () => {
  it('is offered until it is seen through or closed, and a broken file offers it again', () => {
    const dir = folder();
    expect(readFirstLook(dir)).toBe(false);
    writeFirstLook(dir);
    expect(readFirstLook(dir)).toBe(true);
    expect(JSON.parse(readFileSync(path.join(dir, 'first-look.json'), 'utf8'))).toEqual({ done: true });
    writeFileSync(path.join(dir, 'first-look.json'), '{not json');
    expect(readFirstLook(dir)).toBe(false);
    writeFileSync(path.join(dir, 'first-look.json'), JSON.stringify({ done: 'yes' }));
    expect(readFirstLook(dir)).toBe(false);
  });

  it('keeps its flag in the app\'s own folder, and answers rather than hangs in a build without one', async () => {
    const dir = folder();
    registerIpc({ varRoot: '/store' }, undefined, { folder: () => dir, apply: vi.fn() });
    expect(await invoke(CHANNELS.firstLookGet)).toEqual({ ok: true, value: { done: false } });
    expect(await invoke(CHANNELS.firstLookDone)).toEqual({ ok: true, value: { done: true } });
    expect(await invoke(CHANNELS.firstLookGet)).toEqual({ ok: true, value: { done: true } });
    mocks.handlers.clear();
    registerIpc({ varRoot: '/store' });
    expect((await invoke(CHANNELS.firstLookGet)).ok).toBe(false);
  });
});
