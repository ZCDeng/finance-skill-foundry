import { app, BrowserWindow, session } from 'electron';
import { existsSync } from 'node:fs';
import * as path from 'node:path';

import { applyCsp } from './csp.js';
import { FormulatorHost } from './formulator.js';
import { HarnessHost } from './harness/host.js';
import {
  HARNESS_ENTRY,
  entryPath,
  foundryBin as packedFoundryBin,
  pluginDir,
  stagedBundleDir,
  type Layout,
} from './harness/resources.js';
import { installPlugin, installPresets } from './harness/wiring.js';
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
 * Where this app's own pieces are.
 *
 * `FOUNDRY_DSH_INSTALL` still overrides, for pointing a dev run at a runtime
 * staged somewhere else; without it the staged tree is used, packed or not.
 */
function layout(): Layout {
  return {
    packaged: app.isPackaged,
    appPath: app.getAppPath(),
    resourcesPath: process.resourcesPath,
  };
}

/**
 * Which `foundry` this run uses.
 *
 * An explicit `FOUNDRY_BIN` first, then the one this app carries, then whatever
 * is on PATH. The last is not a fallback anyone should rely on -- it is what
 * keeps a checkout usable before `npm run foundry` has ever been run.
 */
function foundryBin(here: Layout): string {
  if (process.env.FOUNDRY_BIN) return process.env.FOUNDRY_BIN;
  const packed = packedFoundryBin(here);
  return existsSync(packed) ? packed : 'foundry';
}

/** The bundle's package name, which is also its directory inside a node_modules. */
const BUNDLE_NAME = 'finance-skill-foundry-dsh';

let mainWindow: BrowserWindow | null = null;
let harness: HarnessHost | null = null;
let formulator: FormulatorHost | null = null;
/** Which screen is on top. The renderer is the only source. */
let onTop = '';

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
    if (!window) return;
    harness?.place(window, onTop === 'workbench');
    formulator?.place(window, onTop === 'formulator');
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
  const here = layout();
  const override = process.env.FOUNDRY_DSH_INSTALL;
  const entry = override ? path.join(override, HARNESS_ENTRY) : entryPath(here);
  const bundle = override
    ? path.join(override, 'node_modules', BUNDLE_NAME)
    : stagedBundleDir(here, BUNDLE_NAME);
  if (existsSync(entry)) {
    const home = path.join(app.getPath('userData'), 'harness');
    const host = new HarnessHost({
      entry,
      home,
      varRoot: varRoot(),
      foundryBin: foundryBin(here),
    });
    harness = host;
    const pane = new FormulatorHost();
    formulator = pane;
    registerIpc(
      { varRoot: varRoot() },
      {
        host,
        formulator: pane,
        window: () => mainWindow,
        remember: (screen) => {
          onTop = screen;
        },
      },
    );
    // Wiring first, then the view. The order is load-bearing: the runtime reads
    // its profile once at boot, so a plugin installed after the child has
    // started is a plugin that composition does not have. Attaching is what
    // starts the child, so it waits.
    void (async () => {
      try {
        await installPlugin({
          entry,
          home,
          pluginDir: pluginDir(here),
          stagedBundle: bundle,
        });
        await installPresets({ foundryBin: foundryBin(here), home, varRoot: varRoot() });
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

/**
 * Put down what this process started.
 *
 * The harness is a child and dies with a kill. Formulator does not: it is
 * spawned in its own session so a CLI killed mid-startup cannot orphan it, which
 * also means it outlives this app unless it is stopped. A survivor holds the
 * window's lease and the port, and the next launch refuses on the pre-flight --
 * so the operator's next period is broken by the last one's exit.
 */
async function shutDown(): Promise<void> {
  harness?.stop();
  const window = mainWindow;
  if (formulator?.running() && window) {
    try {
      await formulator.stop({ varRoot: varRoot() }, window);
    } catch {
      // Already gone, or the kit would not kill what it could not confirm. Its
      // own refusal has been shown; there is nothing further to do on the way out.
    }
  }
}

app.on('window-all-closed', () => {
  void shutDown().then(() => {
    if (process.platform !== 'darwin') app.quit();
  });
});

app.on('before-quit', () => {
  void shutDown();
});
