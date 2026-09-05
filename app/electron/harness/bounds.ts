/**
 * Where the embedded harness sits inside the window.
 *
 * The runtime's page is a native view positioned in window coordinates, not an
 * element in this app's document, so it does not move when the document
 * scrolls. Everything above it therefore has to be a fixed strip whose height
 * this file owns, and the renderer's CSS has to agree: `components.css` carries
 * the same two numbers, and `bounds.test.ts` pins them together.
 */

/** The app header. Mirrors `--fnd-header-height`. */
export const HEADER_HEIGHT = 56;

/**
 * The task bar under it.
 *
 * The one strip that says which task a conversation writes to. It is not
 * optional chrome: a session whose binding is invisible is a session an operator
 * can type into without knowing what it will change.
 */
export const TASK_BAR_HEIGHT = 44;

/** A rectangle with no area, for when the workbench is not the screen on top. */
export const HIDDEN = { x: 0, y: 0, width: 0, height: 0 } as const;

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface HarnessLayout extends Rect { revision: number }

/** Renderer CSS coordinates are converted once using the sender's actual zoom. */
export class PaneGeometry {
  private requested: Rect | null = null;
  private revision = -1;
  private zoom = 1;

  accept(value: unknown, zoom: number): boolean {
    if (!value || typeof value !== 'object') throw new Error('invalid harness layout');
    const rect = value as HarnessLayout;
    for (const key of ['x', 'y', 'width', 'height', 'revision'] as const) {
      if (typeof rect[key] !== 'number' || !Number.isFinite(rect[key]) || rect[key] < 0 || rect[key] > Number.MAX_SAFE_INTEGER) {
        throw new Error(`invalid harness layout ${key}`);
      }
    }
    if (!Number.isSafeInteger(rect.revision) || !Number.isFinite(zoom) || zoom <= 0 || zoom > 10) throw new Error('invalid harness layout revision or zoom');
    if (rect.revision <= this.revision) return false;
    this.revision = rect.revision;
    this.zoom = zoom;
    this.requested = { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
    return true;
  }

  bounds(content: { width: number; height: number }): Rect {
    if (!this.requested) return viewBounds(content);
    const raw = this.requested;
    const x = Math.min(content.width, Math.round(raw.x * this.zoom));
    const y = Math.min(content.height, Math.max(Math.round(HEADER_HEIGHT * this.zoom), Math.round(raw.y * this.zoom)));
    const right = Math.min(content.width, Math.round((raw.x + raw.width) * this.zoom));
    const bottom = Math.min(content.height, Math.round((raw.y + raw.height) * this.zoom));
    return { x, y, width: Math.max(0, right - x), height: Math.max(0, bottom - y) };
  }
}

/**
 * The rectangle the harness gets, given the window's content size.
 *
 * Clamped at zero rather than allowed to go negative: a window dragged shorter
 * than its own chrome would otherwise hand the view an inverted rectangle, which
 * Electron accepts and draws as a view covering the strip that was meant to stay
 * visible.
 */
export function viewBounds(content: { width: number; height: number }): Rect {
  const top = HEADER_HEIGHT + TASK_BAR_HEIGHT;
  return {
    x: 0,
    y: top,
    width: Math.max(0, Math.round(content.width)),
    height: Math.max(0, Math.round(content.height - top)),
  };
}
