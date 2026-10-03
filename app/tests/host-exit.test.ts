import { EventEmitter } from 'node:events';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { beforeEach, describe, expect, it, vi } from 'vitest';

const spawned = vi.hoisted(() => ({ children: [] as Array<EventEmitter & { stdout: EventEmitter; stderr: EventEmitter; kill: () => void }> }));
vi.mock('node:child_process', () => ({
  spawn: () => {
    const child = Object.assign(new EventEmitter(), { stdout: new EventEmitter(), stderr: new EventEmitter(), kill: () => undefined });
    spawned.children.push(child);
    return child;
  },
}));
vi.mock('../electron/harness/pane.js', () => ({ Pane: class { skin() {} attached() { return false; } } }));
import { harnessUrlFrom } from '../electron/harness/boot.js';
import { HarnessHost } from '../electron/harness/host.js';

const banner = 'http://127.0.0.1:41000';
function host(onExit: () => void) {
  const varRoot = mkdtempSync(join(tmpdir(), 'fa-host-exit-'));
  return new HarnessHost({ entry: '/unused', home: '/unused', varRoot, foundryBin: '/unused', onExit });
}
async function running(h: HarnessHost) {
  const started = h.start();
  const child = spawned.children.at(-1)!;
  child.stdout.emit('data', Buffer.from(`${bannerLine()}\n`));
  await started;
  return child;
}
function bannerLine() {
  const line = `dsh web: ${banner}/`;
  if (!harnessUrlFrom(line)) throw new Error('banner format changed; update this fixture from boot.ts');
  return line;
}

beforeEach(() => { spawned.children.length = 0; });

describe('harness runtime exit', () => {
  it('reports a live runtime that exits on its own and forgets its origin', async () => {
    const onExit = vi.fn();
    const h = host(onExit);
    const child = await running(h);
    expect(h.origin()).not.toBeNull();
    child.emit('exit', 1);
    expect(onExit).toHaveBeenCalledTimes(1);
    expect(h.origin()).toBeNull();
  });

  it('stays quiet when the app stops the runtime itself', async () => {
    const onExit = vi.fn();
    const h = host(onExit);
    const child = await running(h);
    h.stop();
    child.emit('exit', 0);
    expect(onExit).not.toHaveBeenCalled();
  });

  it('leaves a start that never came up to the caller that is waiting on it', async () => {
    const onExit = vi.fn();
    const h = host(onExit);
    const started = h.start();
    spawned.children.at(-1)!.emit('exit', 1);
    await expect(started).rejects.toThrow(/exited/);
    expect(onExit).not.toHaveBeenCalled();
  });
});
