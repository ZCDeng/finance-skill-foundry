import { type BrowserWindow, WebContentsView } from 'electron';

import { HIDDEN, PaneGeometry, type Rect } from './bounds.js';

/** What a pane's owner hears from, and says to, the page it embeds. */
export interface PaneHooks {
  /** A script to run in the page after every load, once the page's own bundle has run. */
  script?: () => string;
  /** Every console line the page writes. */
  console?: (message: string) => void;
}

/**
 * One embedded page, positioned in window coordinates.
 *
 * Both of this app's embedded surfaces -- the harness and Formulator -- are
 * somebody else's web app served on loopback, shown full-bleed under this app's
 * own strips. A `WebContentsView` is not part of the document, so React
 * unmounting something does not hide it. `place` controls native visibility as
 * well as bounds; a zero-size rectangle alone can retain a painted macOS layer.
 *
 * Pinned to the origin it was opened on. A page that navigated somewhere else
 * would be a page this window is vouching for and did not launch.
 */
export class Pane {
  private view: WebContentsView | null = null;
  private origin: string | null = null;
  private readonly geometry = new PaneGeometry();
  private visible = false;
  private drawn = false;
  private focusWhenShown = false;
  /**
   * A stylesheet re-applied after every load.
   *
   * `insertCSS` is scoped to the document that was current when it ran, so a
   * reload -- which is how a session hand-off takes effect -- drops it. Held
   * here and re-inserted on `did-finish-load` rather than at each call site,
   * because the call site that forgets is the one that leaves the pane looking
   * like a different product.
   */
  private css: string | null = null;

  constructor(private readonly hooks: PaneHooks = {}) {}

  attached(): boolean {
    return this.view !== null;
  }

  /** Draw this stylesheet over the page, now and after every later load. */
  skin(css: string): void {
    this.css = css;
    if (this.view) void this.view.webContents.insertCSS(css);
  }

  /** Put the page in the window, once, and load it. */
  async attach(window: BrowserWindow, origin: string): Promise<void> {
    if (this.view) {
      if (this.origin !== origin) await this.load(origin);
      return;
    }
    const view = new WebContentsView({
      webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true },
    });
    this.view = view;
    this.origin = origin;
    view.setVisible(false);
    window.contentView.addChildView(view);
    view.setBounds(HIDDEN);
    view.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    view.webContents.on('did-finish-load', () => {
      if (this.css) void view.webContents.insertCSS(this.css);
      // Like the stylesheet, a page's globals go with the document a reload replaces.
      const script = this.hooks.script?.();
      if (script) void view.webContents.executeJavaScript(script, true).catch(() => undefined);
    });
    const heard = this.hooks.console;
    if (heard) view.webContents.on('console-message', (event) => heard(event.message));
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
  async run(script: string): Promise<unknown> {
    if (!this.view) return;
    return this.view.webContents.executeJavaScript(script, true);
  }

  layout(window: BrowserWindow, value: unknown, zoom: number): boolean {
    const accepted = this.geometry.accept(value, zoom);
    if (accepted) this.place(window, this.visible);
    return accepted;
  }

  focus(): void {
    if (this.drawn) this.view?.webContents.focus();
    else this.focusWhenShown = true;
  }

  /** Toggle the native layer; bounds alone are not a visibility control. */
  place(window: BrowserWindow, visible: boolean): void {
    this.visible = visible;
    if (!this.view) return;
    const [width, height] = window.getContentSize();
    const rect: Rect = visible ? this.geometry.bounds({ width, height }) : { ...HIDDEN };
    this.drawn = visible && rect.width > 0 && rect.height > 0;
    if (!this.drawn) {
      if (this.view.webContents.isFocused()) window.webContents.focus();
      this.view.setVisible(false);
    }
    this.view.setBounds(rect);
    if (this.drawn) this.view.setVisible(true);
    if (this.drawn && this.focusWhenShown) {
      this.focusWhenShown = false;
      this.view.webContents.focus();
    }
  }

  /**
   * Take it out of the window. The page goes with it.
   *
   * Removing the view does not end the page: the renderer behind it lives on
   * until the object is collected, still pointed at whatever it was showing.
   * For the two panes that detach once at quit that was invisible; for a
   * preview that opens and closes per version it was one renderer process
   * left behind each time, measured as a lingering page target after the
   * gateway it talked to had already exited. So the page is closed here.
   */
  detach(window: BrowserWindow): void {
    if (!this.view) return;
    const view = this.view;
    this.view = null;
    this.origin = null;
    this.visible = false;
    this.drawn = false;
    this.focusWhenShown = false;
    window.contentView.removeChildView(view);
    if (!view.webContents.isDestroyed()) view.webContents.close();
  }
}
