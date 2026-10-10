import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ handlers: new Map<string, (...args: any[]) => Promise<any>>() }));
vi.mock('electron', () => ({
  ipcMain: { handle: (name: string, handler: any) => mocks.handlers.set(name, handler) },
  shell: {}, dialog: {},
}));
import { registerIpc } from '../electron/ipc/register.js';
import { CHANNELS } from '../electron/ipc/contract.js';

beforeEach(() => { mocks.handlers.clear(); });

function window(full: boolean) {
  const state = { full };
  return {
    state,
    webContents: {},
    isFullScreen: () => state.full,
    setFullScreen: vi.fn((on: boolean) => { state.full = on; }),
  };
}

describe('汇报模式 and the window full screen', () => {
  it('takes the main window full screen and back, saying whether it already was', async () => {
    const main = window(false);
    registerIpc({ varRoot: '/store' }, { window: () => main } as any);
    const invoke = (sender: unknown, on: unknown) => mocks.handlers.get(CHANNELS.windowFullScreen)!({ sender }, on);
    expect(await invoke(main.webContents, true)).toEqual({ ok: true, value: { was: false } });
    expect(main.state.full).toBe(true);
    expect(await invoke(main.webContents, false)).toEqual({ ok: true, value: { was: true } });
    expect(main.state.full).toBe(false);
    // Only the window's own page may ask, and only on or off.
    expect((await invoke({}, true)).ok).toBe(false);
    expect((await invoke(main.webContents, 'yes')).ok).toBe(false);
    expect(main.setFullScreen).toHaveBeenCalledTimes(2);
  });
});
