// @vitest-environment jsdom
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import * as path from 'node:path';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ handlers: new Map<string, (...args: any[]) => Promise<any>>() }));
vi.mock('electron', () => ({
  ipcMain: { handle: (name: string, handler: any) => mocks.handlers.set(name, handler) },
  shell: {}, dialog: {},
}));
import { appearanceOf, readAppearance, writeAppearance } from '../electron/appearance.js';
import { registerIpc } from '../electron/ipc/register.js';
import { CHANNELS } from '../electron/ipc/contract.js';
import { ThemeSwitch } from '../src/components/ThemeSwitch.js';

const folder = () => mkdtempSync(path.join(tmpdir(), 'appearance-'));
const invoke = (name: string, ...args: unknown[]) => mocks.handlers.get(name)!({}, ...args);

afterEach(() => { cleanup(); delete (globalThis as { foundry?: unknown }).foundry; });
beforeEach(() => mocks.handlers.clear());

describe('the saved appearance', () => {
  it('defaults to following the system, and reads back what was written', () => {
    const dir = folder();
    expect(readAppearance(dir)).toBe('system');
    writeAppearance(dir, 'dark');
    expect(readAppearance(dir)).toBe('dark');
    expect(JSON.parse(readFileSync(path.join(dir, 'appearance.json'), 'utf8'))).toEqual({ appearance: 'dark' });
  });

  it('treats a broken or unknown file as the default', () => {
    const dir = folder();
    writeFileSync(path.join(dir, 'appearance.json'), '{not json');
    expect(readAppearance(dir)).toBe('system');
    writeFileSync(path.join(dir, 'appearance.json'), JSON.stringify({ appearance: 'sepia' }));
    expect(readAppearance(dir)).toBe('system');
  });

  it('lets only the three words through', () => {
    expect(appearanceOf('light')).toBe('light');
    expect(() => appearanceOf('sepia')).toThrow();
    expect(() => appearanceOf({ toString: () => 'dark' })).toThrow();
  });
});

describe('the appearance channels', () => {
  it('apply and save a choice, and refuse anything else without applying it', async () => {
    const dir = folder();
    const apply = vi.fn();
    registerIpc({ varRoot: '/store' }, undefined, { folder: () => dir, apply });
    expect(await invoke(CHANNELS.appearanceGet)).toEqual({ ok: true, value: { appearance: 'system' } });
    expect(await invoke(CHANNELS.appearanceSet, 'light')).toEqual({ ok: true, value: { appearance: 'light' } });
    expect(apply).toHaveBeenCalledWith('light');
    expect(readAppearance(dir)).toBe('light');
    expect((await invoke(CHANNELS.appearanceSet, '../../etc')).ok).toBe(false);
    expect(apply).toHaveBeenCalledTimes(1);
    expect(readAppearance(dir)).toBe('light');
  });

  it('answer, rather than hang, in a build that was not given a folder', async () => {
    registerIpc({ varRoot: '/store' });
    expect((await invoke(CHANNELS.appearanceGet)).ok).toBe(false);
  });
});

describe('ThemeSwitch', () => {
  const install = (saved: string) => {
    const api = {
      appearanceGet: vi.fn().mockResolvedValue({ ok: true, value: { appearance: saved } }),
      appearanceSet: vi.fn().mockImplementation(async (appearance: string) => ({ ok: true, value: { appearance } })),
    };
    (globalThis as { foundry?: unknown }).foundry = api;
    return api;
  };

  it('is absent when the build has no appearance channel', () => {
    (globalThis as { foundry?: unknown }).foundry = {};
    const { container } = render(<ThemeSwitch />);
    expect(container.innerHTML).toBe('');
  });

  it('shows the saved choice as the one checked radio with the only tab stop', async () => {
    install('dark');
    render(<ThemeSwitch />);
    await act(async () => {});
    const group = screen.getByRole('radiogroup', { name: '外观' });
    const radios = screen.getAllByRole('radio');
    expect(radios.map((radio) => radio.getAttribute('aria-label'))).toEqual(['跟随系统外观', '浅色', '深色']);
    expect(screen.getByRole('radio', { name: '深色' }).getAttribute('aria-checked')).toBe('true');
    expect(radios.map((radio) => radio.tabIndex)).toEqual([-1, -1, 0]);
    expect(group.style.getPropertyValue('--fnd-theme-index')).toBe('2');
  });

  it('applies a click at once, moves with the arrows, and goes back if main refuses', async () => {
    const api = install('system');
    render(<ThemeSwitch />);
    await act(async () => {});
    await act(async () => { fireEvent.click(screen.getByRole('radio', { name: '浅色' })); });
    expect(api.appearanceSet).toHaveBeenLastCalledWith('light');
    expect(screen.getByRole('radio', { name: '浅色' }).getAttribute('aria-checked')).toBe('true');

    await act(async () => { fireEvent.keyDown(screen.getByRole('radio', { name: '浅色' }), { key: 'ArrowRight' }); });
    expect(api.appearanceSet).toHaveBeenLastCalledWith('dark');
    expect(document.activeElement).toBe(screen.getByRole('radio', { name: '深色' }));

    api.appearanceSet.mockResolvedValueOnce({ ok: false, refused: false, message: 'disk full' });
    await act(async () => { fireEvent.keyDown(screen.getByRole('radio', { name: '深色' }), { key: 'ArrowRight' }); });
    expect(api.appearanceSet).toHaveBeenLastCalledWith('system');
    expect(screen.getByRole('radio', { name: '深色' }).getAttribute('aria-checked')).toBe('true');
  });
});
