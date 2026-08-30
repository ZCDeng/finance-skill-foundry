import { app, BrowserWindow, session } from 'electron';
import * as path from 'node:path';

import { applyCsp } from './csp.js';
import { HarnessHost } from './harness/host.js';
import { entryPath, installPlugin, installPresets } from './harness/wiring.js';
import { registerIpc } from './ipc/register.js';

const isDev = !app.isPackaged;

/**
 * Where the store is.
 *
 * `FOUNDRY_VAR` is the same variable the harness bundle reads, so one machine
 * runs one store whether the operator came through this window or through a
 * conversation. Absent, the app still opens and every screen shows the refusal
 * the CLI gives, which is more useful than a window that will not start.
 */
function varRoot(): string {
  return process.env.FOUNDRY_VAR ?? path.join(app.getPath('userData'), 'var');
}

/**
 * Where the packed runtime is.
 *
 * Not bundled yet: U10 embeds a harness the operator already has, named by
 * `FOUNDRY_DSH_INSTALL`. Packing it is the next unit's problem, and pretending
 * otherwise would mean shipping an app whose workbench never starts.
 */
function harnessInstall(): string | null {
  return process.env.FOUNDRY_DSH_INSTALL ?? null;
}

function foundryBin(): string {
  return process.env.FOUNDRY_BIN ?? 'foundry';
}

/** The bundle this app installs into the harness profile. */
function pluginDir(): string {
  return process.env.FOUNDRY_PLUGIN_DIR ?? path.join(__dirname, '..', '..', 'dsh-plugin');
}

let mainWindow: BrowserWindow | null = null;
let harness: HarnessHost | null = null;
/** Whether the workbench is the screen on top. The renderer is the only source. */
let workbenchVisible = false;

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 1080,
    minHeight: 720,
    // Kept empty. The product names itself in its own header; repeating it in
    // the title bar spends the one strip of system chrome on a word already on
    // screen. Electron otherwise mirrors the document title into the window, so
    // the event has to be refused too.
    title: '',
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
    },
  });

  mainWindow.on('page-title-updated', (event) => event.preventDefault());
  mainWindow.once('ready-to-show', () => mainWindow?.show());
  // The embedded page is a native view in window coordinates, so it does not
  // follow a resize on its own.
  mainWindow.on('resize', () => {
    const window = mainWindow;
    if (window && harness) harness.place(window, workbenchVisible);
  });

  if (isDev) {
    void mainWindow.loadURL('http://localhost:5273');
  } else {
    void mainWindow.loadFile(path.join(__dirname, '..', 'dist-vite', 'index.html'));
  }
}

void app.whenReady().then(() => {
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    callback({ responseHeaders: applyCsp(details.responseHeaders ?? {}, isDev) });
  });
  const install = harnessInstall();
  if (install) {
    const home = path.join(app.getPath('userData'), 'harness');
    const host = new HarnessHost({
      entry: entryPath(install),
      home,
      varRoot: varRoot(),
      foundryBin: foundryBin(),
    });
    harness = host;
    registerIpc(
      { varRoot: varRoot() },
      { host, window: () => mainWindow, remember: (visible) => { workbenchVisible = visible; } },
    );
    // Wiring first, then the view. The order is load-bearing: the runtime reads
    // its profile once at boot, so a plugin installed after the child has
    // started is a plugin that composition does not have. Attaching is what
    // starts the child, so it waits.
    void (async () => {
      try {
        await installPlugin({ entry: entryPath(install), home, pluginDir: pluginDir() });
        await installPresets({ foundryBin: foundryBin(), home, varRoot: varRoot() });
        const window = mainWindow;
        if (window) await host.attach(window);
      } catch (error) {
        console.error('[harness] wiring failed:', error instanceof Error ? error.message : error);
      }
    })();
  } else {
    registerIpc({ varRoot: varRoot() });
  }
  createWindow();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  harness?.stop();
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', () => harness?.stop());
