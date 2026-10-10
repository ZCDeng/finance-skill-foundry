/**
 * 看板快照, printed: the page dashboard-snapshot.ts lays out, in a private offline window, as one PDF page or a PNG
 * drawn at twice its size for the slide.
 */
import { BrowserWindow } from 'electron';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import * as path from 'node:path';
import { randomUUID } from 'node:crypto';
import { pathToFileURL } from 'node:url';

/** A4 landscape at 96 CSS pixels to the inch. */
const PAGE = { width: 1123, height: 794 };


/**
 * The page in a private, offline window: printed to one PDF page, or drawn at twice its size as a PNG. A page whose
 * content runs past the sheet is scaled down to fit it rather than spilling onto a second one.
 */
export async function renderSnapshot(html: string, as: 'pdf' | 'png', signal: AbortSignal): Promise<Buffer> {
  if (signal.aborted) throw new Error('已取消导出。');
  const scratch = await mkdtemp(path.join(tmpdir(), 'fa-dashboard-'));
  const entry = pathToFileURL(path.join(scratch, 'page.html')).href;
  await writeFile(path.join(scratch, 'page.html'), html, { mode: 0o600 });
  const window = new BrowserWindow({ show: false, width: PAGE.width, height: PAGE.height, useContentSize: true, webPreferences: {
    // A hidden window paints nothing to capture; an offscreen one does.
    sandbox: true, contextIsolation: true, nodeIntegration: false, partition: `dashboard-snapshot-${randomUUID()}`, offscreen: as === 'png',
  } });
  const session = window.webContents.session;
  session.setPermissionRequestHandler((_web, _permission, callback) => callback(false));
  session.webRequest.onBeforeRequest({ urls: ['http://*/*', 'https://*/*', 'file://*/*'] }, (details, callback) => callback({ cancel: details.url !== entry }));
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  window.webContents.on('will-navigate', (event) => event.preventDefault());
  const cancel = () => { if (!window.isDestroyed()) window.destroy(); };
  signal.addEventListener('abort', cancel, { once: true });
  const devtools = window.webContents.debugger;
  try {
    await window.loadURL(entry);
    // The page is laid out on an A4 viewport whatever the screen, and a PNG is drawn at twice that.
    devtools.attach('1.3');
    await devtools.sendCommand('Emulation.setDeviceMetricsOverride', { width: PAGE.width, height: PAGE.height, deviceScaleFactor: as === 'png' ? 2 : 1, mobile: false });
    await window.webContents.executeJavaScript(`(async () => {
      await document.fonts.ready;
      if (!document.fonts.check('11px "Noto Sans SC"', '经营看板')) throw new Error('中文字体未加载');
      // Fit the page to the sheet: widen it as it shrinks so the scaled page still spans the sheet.
      const page = document.querySelector('.page');
      const width = ${PAGE.width}, height = ${PAGE.height};
      let fit = 1;
      for (let step = 0; step < 6; step += 1) {
        page.style.width = (width / fit) + 'px';
        const tall = page.scrollHeight;
        if (tall * fit <= height) break;
        fit = Math.max(0.5, Math.min(fit * 0.98, height / tall));
      }
      page.style.transform = fit < 1 ? 'scale(' + fit + ')' : '';
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    })()`);
    if (signal.aborted) throw new Error('已取消导出。');
    if (as === 'pdf') {
      return await window.webContents.printToPDF({ landscape: true, pageSize: 'A4', printBackground: true, preferCSSPageSize: true,
        margins: { top: 0, bottom: 0, left: 0, right: 0 }, pageRanges: '1' });
    }
    const shot = await devtools.sendCommand('Page.captureScreenshot', {
      format: 'png', clip: { x: 0, y: 0, width: PAGE.width, height: PAGE.height, scale: 1 }, captureBeyondViewport: false,
    }) as { data?: unknown };
    const png = typeof shot.data === 'string' ? Buffer.from(shot.data, 'base64') : Buffer.alloc(0);
    if (!png.length) throw new Error('没能画出这一页。');
    return png;
  } finally {
    signal.removeEventListener('abort', cancel);
    if (devtools.isAttached()) devtools.detach();
    if (!window.isDestroyed()) window.destroy();
    await session.clearStorageData();
    await rm(scratch, { recursive: true, force: true });
  }
}

