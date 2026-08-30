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
