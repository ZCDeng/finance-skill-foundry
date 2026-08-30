import { type BrowserWindow, WebContentsView } from 'electron';

import { HIDDEN, type Rect, viewBounds } from './bounds.js';

/**
 * One embedded page, positioned in window coordinates.
 *
 * Both of this app's embedded surfaces -- the harness and Formulator -- are
 * somebody else's web app served on loopback, shown full-bleed under this app's
 * own strips. A `WebContentsView` is not part of the document, so React
 * unmounting something does not hide it: it is shown and hidden by being given a
 * rectangle or none, which is what `place` is for.
 *
 * Pinned to the origin it was opened on. A page that navigated somewhere else
 * would be a page this window is vouching for and did not launch.
 */
export class Pane {
  private view: WebContentsView | null = null;
  private origin: string | null = null;

  attached(): boolean {
    return this.view !== null;
  }

  /** Put the page in the window, once, and load it. */
  async attach(window: BrowserWindow, origin: string): Promise<void> {
    if (this.view) {
      await this.load(origin);
      return;
    }
    const view = new WebContentsView({
      webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true },
    });
    this.view = view;
    this.origin = origin;
    window.contentView.addChildView(view);
    view.setBounds(HIDDEN);
    view.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    view.webContents.on('will-navigate', (event, url) => {
      const pinned = this.origin;
      if (!pinned) return;
      if (!url.startsWith(`${pinned}/`) && url !== pinned) event.preventDefault();
    });
    await view.webContents.loadURL(origin);
  }

  /** Point it at a new origin, re-pinning as it goes. */
  async load(origin: string): Promise<void> {
    if (!this.view) return;
    this.origin = origin;
    await this.view.webContents.loadURL(origin);
  }

  /** Run one script in the page before its own bundle does. */
  async run(script: string): Promise<void> {
    if (!this.view) return;
    await this.view.webContents.executeJavaScript(script, true);
  }

  /** Show it by giving it the rectangle under this app's strips, or hide it. */
  place(window: BrowserWindow, visible: boolean): void {
    if (!this.view) return;
    const [width, height] = window.getContentSize();
    const rect: Rect = visible ? viewBounds({ width, height }) : { ...HIDDEN };
    this.view.setBounds(rect);
  }

  /** Take it out of the window. The page goes with it. */
  detach(window: BrowserWindow): void {
    if (!this.view) return;
    window.contentView.removeChildView(this.view);
    this.view = null;
    this.origin = null;
  }
}
