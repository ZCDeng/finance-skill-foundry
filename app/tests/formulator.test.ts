import { describe, expect, it, vi } from 'vitest';

// `Pane` reaches for Electron. Nothing here needs a real window: what is worth
// pinning is which CLI calls happen, in what order, and what survives a refusal.
/** How many pages a detach has closed. A view taken out of the window is not a page ended. */
let pagesClosed = 0;

vi.mock('electron', () => ({
  WebContentsView: class {
    webContents = {
      setWindowOpenHandler() {},
      on() {},
      loadURL: async () => {},
      executeJavaScript: async () => {},
      isDestroyed: () => false,
      close() {
        pagesClosed += 1;
      },
    };
    setBounds() {}
  },
}));

const calls: string[][] = [];
let nextStdout = '';
let refuseStop = false;

vi.mock('../electron/foundry.js', async () => {
  const actual = await vi.importActual<typeof import('../electron/foundry.js')>(
    '../electron/foundry.js',
  );
  return {
    ...actual,
    runFoundry: async (_binding: unknown, command: string) => {
      calls.push([command]);
      if (command === 'stop-formulator' && refuseStop) {
        throw new actual.FoundryRefusal('refusing to kill an unconfirmed process', 3);
      }
      return '';
    },
    runFoundryJson: async (_binding: unknown, command: string) => {
      calls.push([command]);
      return JSON.parse(nextStdout);
    },
  };
});

const { FormulatorHost } = await import('../electron/formulator.js');

function fakeWindow() {
  return {
    contentView: { addChildView() {}, removeChildView() {} },
    getContentSize: () => [1280, 860],
  } as never;
}

describe('the Formulator lease', () => {
  it('reports what the kit said, including an unconfirmed identity', () => {
    // The kit launches anyway when it has no `ps` to prove the served process is
    // this window's, and says so on the record rather than becoming unstartable.
    calls.length = 0;
    nextStdout = JSON.stringify({
      url: 'http://127.0.0.1:5567',
      home: '/var/formulator/w1',
      identity: 'unconfirmed: ps is not installed on this host',
    });
    const host = new FormulatorHost();
    return host.launch({ varRoot: '/v' }, fakeWindow()).then((spec) => {
      expect(calls).toEqual([['launch-formulator']]);
      expect(spec.url).toBe('http://127.0.0.1:5567');
      expect(host.running()?.identity).toContain('unconfirmed');
    });
  });

  it('takes the page down even when the stop refused', async () => {
    // A refusal means the kit would not kill what it could not confirm. Leaving
    // a view pointed at a server this app no longer claims is worse than showing
    // nothing, so the page goes either way and the refusal still reaches the
    // caller.
    nextStdout = JSON.stringify({ url: 'http://127.0.0.1:5567', home: '/h' });
    const host = new FormulatorHost();
    const window = fakeWindow();
    await host.launch({ varRoot: '/v' }, window);
    expect(host.running()).not.toBeNull();

    refuseStop = true;
    const before = pagesClosed;
    await expect(host.stop({ varRoot: '/v' }, window)).rejects.toThrow(/unconfirmed/);
    expect(host.running()).toBeNull();
    // Taken out of the window *and* ended. A detached view whose page lives on
    // is a renderer with nothing to talk to, measured on the workbook preview.
    expect(pagesClosed).toBe(before + 1);
    refuseStop = false;
  });

  it('takes no task, because a lease belongs to one window', async () => {
    // `launch-formulator` acts on `var/current`. Passing a task would let a
    // screen ask for a reader on a window the operator is not looking at --
    // after a re-import, the successor rather than the brief's own window.
    const source = await import('node:fs').then((fs) =>
      fs.readFileSync(new URL('../electron/formulator.ts', import.meta.url), 'utf8'),
    );
    expect(source).toContain("'launch-formulator', []");
    expect(source).toContain("'stop-formulator', []");
  });
});
