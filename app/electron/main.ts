import { app, BrowserWindow, nativeTheme, session } from 'electron';
import { existsSync, mkdirSync, renameSync } from 'node:fs';
import * as path from 'node:path';

import { applyCsp, ownDocument } from './csp.js';
import { FormulatorHost } from './formulator.js';
import { HarnessHost } from './harness/host.js';
import {
  HARNESS_ENTRY,
  companionEnv,
  entryPath,
  availableMethodSkillDir,
  harnessRoot,
  methodSkillDir,
  formulatorBin as packedFormulatorBin,
  foundryBin as packedFoundryBin,
  pluginDir,
  stagedBundleDir,
  type Layout,
} from './harness/resources.js';
import { FENCE_REASON, installFence } from './harness/fence.js';
import { type Wiring, type WiringStep, installPlugin, installPresets } from './harness/wiring.js';
import { CHANNELS } from './ipc/contract.js';
import { registerIpc } from './ipc/register.js';
import { type Appearance, readAppearance } from './appearance.js';
import { UniverPreviewHost } from './univer.js';

const isDev = !app.isPackaged;

/**
 * The name this product had before it was called FA Foundry.
 *
 * Electron derives `userData` from the product name, so the rename moved the
 * directory out from under a store that was already there.
 */
const FORMER_PRODUCT = 'Foundry';

/**
 * Carry an existing operator's state across the rename.
 *
 * Two directories and not the whole `userData`: `var` is the store and
 * `harness` is the runtime's home, which is where an operator's provider
 * credentials live. Everything else under there is Chromium's cache, and
 * Chromium writes some of it before this runs -- so moving the parent would
 * either race that or refuse once it existed, and the store would be the thing
 * left behind.
 *
 * Idempotent, and it never overwrites: a destination that already exists is a
 * newer state than the one being carried, and is left alone. A rename that
 * fails leaves the old copy where it is rather than a half-moved one.
 */
function adoptFormerState(): void {
  const dir = app.getPath('userData');
  const former = path.join(path.dirname(dir), FORMER_PRODUCT);
  if (former === dir || !existsSync(former)) return;
  for (const name of ['var', 'harness']) {
    const from = path.join(former, name);
    const to = path.join(dir, name);
    if (!existsSync(from) || existsSync(to)) continue;
    try {
      mkdirSync(dir, { recursive: true });
      renameSync(from, to);
      console.log(`[state] carried ${name} over from ${FORMER_PRODUCT}`);
    } catch (error) {
      console.error(`[state] left ${name} in ${FORMER_PRODUCT}:`, error);
    }
  }
}

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
 *
 * A packaged app never falls back. A bundle missing its own Formulator is a
 * broken build, and on a developer's Mac the PATH fallback would find some other
 * Formulator and hide that; naming the missing path makes the failure say so.
 */
function nameFormulator(here: Layout): void {
  if (process.env.FOUNDRY_FORMULATOR_BIN) return;
  const packed = packedFormulatorBin(here);
  if (here.packaged || existsSync(packed)) process.env.FOUNDRY_FORMULATOR_BIN = packed;
  if (here.packaged && !existsSync(packed)) console.error(`[foundry] this app carries no Formulator at ${packed}`);
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
 * keeps a checkout usable before `npm run foundry` has ever been run. A packaged
 * app never takes it: see `nameFormulator`.
 */
function foundryBin(here: Layout): string {
  if (process.env.FOUNDRY_BIN) return process.env.FOUNDRY_BIN;
  const packed = packedFoundryBin(here);
  return here.packaged || existsSync(packed) ? packed : 'foundry';
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
  if (here.packaged || existsSync(packed)) process.env.FOUNDRY_BIN = packed;
  if (here.packaged && !existsSync(packed)) console.error(`[foundry] this app carries no foundry at ${packed}`);
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
/** The read-only workbook look, present only when this build carries the Univer bundle. */
let preview: UniverPreviewHost | null = null;
/** What `registerIpc` hands back: the locator scratch it fenced, to be removed on the way out. */
let ipc: { shutdown(): void } | null = null;

/** Where the header's appearance switch lands: one file in this app's folder, and the theme every page reads. */
const appearance = {
  folder: () => app.getPath('userData'),
  apply: (value: Appearance) => { nativeTheme.themeSource = value; },
};

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
    preview?.place(window, onTop === 'preview');
  });

  if (isDev) {
    void mainWindow.loadURL('http://localhost:5273');
  } else {
    void mainWindow.loadFile(path.join(__dirname, '..', 'dist-vite', 'index.html'));
  }
}

/**
 * One instance, because two of them share one profile directory.
 *
 * `installPlugin` rewrites `harness/profiles/web/package.json` on every start,
 * and the harness home is derived from `userData`, which is the same path for
 * every copy of this app. A second launch therefore rewrites that manifest
 * underneath the first one's runtime -- and a reader that catches it mid-write
 * fails to compose the whole plugin tree, which reaches the operator as an
 * unstyled upstream page saying `failed to import loader entry`, naming a
 * bundle that is perfectly fine.
 *
 * The lock is taken before anything is read or written, so the losing process
 * quits without touching the store. The winner is asked to surface itself
 * instead, which is what a second launch was asking for anyway.
 *
 * A different `--user-data-dir` gets its own lock, so a scratch instance still
 * runs beside a real one.
 */
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {
    const [window] = BrowserWindow.getAllWindows();
    if (!window) return;
    if (window.isMinimized()) window.restore();
    window.focus();
  });
}

void app.whenReady().then(() => {
  // The losing process is on its way out; `whenReady` still fires for it.
  if (!app.hasSingleInstanceLock()) return;
  // Every page in the window follows one appearance: the system's unless the
  // manager picked light or dark in the header (appearance.ts).
  nativeTheme.themeSource = readAppearance(app.getPath('userData'));
  // A packed app takes its Dock icon from the bundle. A dev run is Electron's
  // own binary, so it is told which one to show.
  if (isDev) app.dock?.setIcon(path.join(__dirname, '..', 'resources', 'icon.png'));
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    // Only this app's own documents. The harness page and Formulator are served
    // by child processes over loopback and carry their own headers; rewriting
    // theirs left both with `default-src 'none'` and neither could boot.
    if (!ownDocument(details.url, isDev)) return callback({});
    callback({ responseHeaders: applyCsp(details.responseHeaders ?? {}, isDev) });
  });
  adoptFormerState();
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
    const bundledSkillDir = availableMethodSkillDir(here);
    if (!bundledSkillDir) {
      console.warn(`[harness] bundled method skills unavailable at ${methodSkillDir(here)}`);
    }
    const host = new HarnessHost({
      entry,
      root: override ?? harnessRoot(here),
      home,
      varRoot: varRoot(),
      foundryBin: foundryBin(here),
      // `nameFormulator` has already run, so this is the packed one unless the
      // operator named their own.
      formulatorBin: process.env.FOUNDRY_FORMULATOR_BIN,
      bundledSkillDir: bundledSkillDir ?? undefined,
      companionEnv: companionEnv(here),
      onExit: () => {
        console.warn('[harness] runtime exited unexpectedly');
        if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send(CHANNELS.harnessExited);
      },
    });
    harness = host;
    /*
     * The fence goes up before the page is ever loaded.
     *
     * Installed on the default session, which is the one both embedded views
     * use. It is keyed on the harness's own origin, so Formulator's loopback
     * server and this app's own `file://` documents fall through untouched.
     */
    installFence(session.defaultSession, {
      origin: () => host.origin(),
      onRefused: (method) => {
        console.warn(`[fence] refused ${method} from the embedded page`);
        mainWindow?.webContents.send(CHANNELS.harnessRefused, FENCE_REASON[method]);
      },
    });
    const pane = new FormulatorHost();
    formulator = pane;
    // The Univer bundle rides in the staged runtime beside the period bundle,
    // so its artifacts are found the same way. Absent, the host says so on
    // the first open rather than at boot -- a build without it is a build
    // with one fewer button, not a broken one.
    const look = new UniverPreviewHost({
      bundleDir: override
        ? path.join(override, 'node_modules', 'dsh-univer-office')
        : stagedBundleDir(here, 'dsh-univer-office'),
    });
    preview = look;
    ipc = registerIpc(
      { varRoot: varRoot() },
      {
        host,
        formulator: pane,
        preview: look,
        wiring: () => wiring,
        ready: async () => {
          await ready;
          if (wiring.state !== 'ready') throw new Error(wiring.state === 'failed' ? wiring.message : '对话服务尚未就绪');
        },
        window: () => mainWindow,
        remember: (screen) => {
          onTop = screen;
        },
        userData: () => app.getPath('userData'),
      },
      appearance,
    );
    // Wiring first, then the view. The order is load-bearing: the runtime reads
    // its profile once at boot, so a plugin installed after the child has
    // started is a plugin that composition does not have. Attaching is what
    // starts the child, so it waits.
    const ready = (async () => {
      // Named per step, because which one stopped decides what is missing: the
      // period tools, the fence presets, or the page itself.
      let step: WiringStep = 'plugin';
      try {
        await installPlugin({
          entry,
          home,
          pluginDir: pluginDir(here),
          stagedBundle: bundle,
          harnessRoot: override ?? harnessRoot(here),
        });
        step = 'presets';
        await installPresets({ foundryBin: foundryBin(here), home, varRoot: varRoot() });
        step = 'attach';
        // Before the page is loaded. A write that lands after the first paint is
        // a dialog the operator has already read, or a picker that has already
        // drawn the wrong default.
        await host.dismissDeveloperNotice();
        await host.makePeriodTheDefault();
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
    ipc = registerIpc({ varRoot: varRoot() }, undefined, appearance);
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
  // The gateway is a child and dies with a kill, but its page has to go first
  // so a view is never left pointed at a server this process no longer runs.
  if (window) preview?.close(window);
  // The scratch copies a locator preview was fenced to are this process's to
  // remove, and this is the last moment it can.
  ipc?.shutdown();
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
