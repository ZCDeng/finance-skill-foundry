import { app, BrowserWindow, session } from 'electron';
import { existsSync } from 'node:fs';
import * as path from 'node:path';

import { applyCsp, ownDocument } from './csp.js';
import { FormulatorHost } from './formulator.js';
import { HarnessHost } from './harness/host.js';
import {
  HARNESS_ENTRY,
  entryPath,
  harnessRoot,
  formulatorBin as packedFormulatorBin,
  foundryBin as packedFoundryBin,
  pluginDir,
  stagedBundleDir,
  type Layout,
} from './harness/resources.js';
import { type Wiring, type WiringStep, installPlugin, installPresets } from './harness/wiring.js';
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
 * Tell the kit where the Formulator this app carries is.
 *
 * Set on this process rather than passed per call: `launch-formulator` reads it
 * through the kit's own resolver, and every path that reaches the CLI -- the
 * data screen, a wiring step, a future one -- then agrees about which binary is
 * meant. An operator's own `FOUNDRY_FORMULATOR_BIN` still wins; a build with no
 * staged Formulator sets nothing and the kit falls back to PATH, which is what
 * keeps a checkout working before `npm run formulator` has ever been run.
 */
function nameFormulator(here: Layout): void {
  if (process.env.FOUNDRY_FORMULATOR_BIN) return;
  const packed = packedFormulatorBin(here);
  if (existsSync(packed)) process.env.FOUNDRY_FORMULATOR_BIN = packed;
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

/**
 * Tell this process where the `foundry` it carries is.
 *
 * The same shape as `nameFormulator`, and for the same reason: the binary was
 * being resolved at three call sites and handed to two of them. The harness
 * child got it through `boot.ts` and `install-presets` got it as an argument,
 * while the store binding this window reads through got a `varRoot` and nothing
 * else -- so `runFoundry` fell through to its last resort and exec'd a bare
 * `foundry` off PATH. On a packaged machine there is no such program, and every
 * screen in the window rendered `spawn foundry ENOENT`: no task list, therefore
 * no task, therefore no session, therefore a harness view that was attached and
 * running and never once given a rectangle.
 *
 * Naming it on the process rather than threading it through `Binding` keeps the
 * resolution in one place and means a call site added later cannot forget it.
 */
function nameFoundry(here: Layout): void {
  if (process.env.FOUNDRY_BIN) return;
  const packed = packedFoundryBin(here);
  if (existsSync(packed)) process.env.FOUNDRY_BIN = packed;
}

/** The bundle's package name, which is also its directory inside a node_modules. */
const BUNDLE_NAME = 'finance-skill-foundry-dsh';

/**
 * How the wiring went, for the screen rather than the console.
 *
 * It used to be a `console.error` and nothing else, so a run that could not
 * install the period tools opened a window that looked fine and then failed
 * somewhere unrelated -- the harness's own dialog reporting that it could not
 * save an acknowledgement, which names nothing that is wrong.
 */
let wiring: Wiring = { state: 'pending' };

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
    // Only this app's own documents. The harness page and Formulator are served
    // by child processes over loopback and carry their own headers; rewriting
    // theirs left both with `default-src 'none'` and neither could boot.
    if (!ownDocument(details.url, isDev)) return callback({});
    callback({ responseHeaders: applyCsp(details.responseHeaders ?? {}, isDev) });
  });
  const here = layout();
  nameFoundry(here);
  nameFormulator(here);
  const override = process.env.FOUNDRY_DSH_INSTALL;
  const entry = override ? path.join(override, HARNESS_ENTRY) : entryPath(here);
  const bundle = override
    ? path.join(override, 'node_modules', BUNDLE_NAME)
    : stagedBundleDir(here, BUNDLE_NAME);
  if (existsSync(entry)) {
    const home = path.join(app.getPath('userData'), 'harness');
    const host = new HarnessHost({
      entry,
      root: override ?? harnessRoot(here),
      home,
      varRoot: varRoot(),
      foundryBin: foundryBin(here),
      // `nameFormulator` has already run, so this is the packed one unless the
      // operator named their own.
      formulatorBin: process.env.FOUNDRY_FORMULATOR_BIN,
    });
    harness = host;
    const pane = new FormulatorHost();
    formulator = pane;
    registerIpc(
      { varRoot: varRoot() },
      {
        host,
        formulator: pane,
        wiring: () => wiring,
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
      // Named per step, because which one stopped decides what is missing: the
      // period tools, the fence presets, or the page itself.
      let step: WiringStep = 'plugin';
      try {
        await installPlugin({
          entry,
          home,
          pluginDir: pluginDir(here),
          stagedBundle: bundle,
        });
        step = 'presets';
        await installPresets({ foundryBin: foundryBin(here), home, varRoot: varRoot() });
        step = 'attach';
        // Before the page is loaded. A write that lands after the first paint is
        // a dialog the operator has already read.
        await host.dismissDeveloperNotice();
        const window = mainWindow;
        if (window) await host.attach(window);
        wiring = { state: 'ready' };
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        wiring = { state: 'failed', step, message };
        // Kept as well as surfaced: the screen gets one sentence, and a
        // stack-carrying message still belongs where it can be read in full.
        console.error(`[harness] wiring failed at ${step}:`, message);
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
