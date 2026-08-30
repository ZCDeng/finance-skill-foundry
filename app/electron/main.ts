import { app, BrowserWindow, session } from 'electron';
import * as path from 'node:path';

import { applyCsp } from './csp.js';
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

let mainWindow: BrowserWindow | null = null;

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
  registerIpc({ varRoot: varRoot() });
  createWindow();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
