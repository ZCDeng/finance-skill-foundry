import { mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import * as path from 'node:path';

/**
 * The window's appearance: follow the operating system, or hold light or dark.
 *
 * Main applies it as `nativeTheme.themeSource`, which is what every page in the
 * window reads as `prefers-color-scheme`: the shell, the native conversation and
 * Formulator change together, and no page needs a `data-theme` of its own. The
 * choice is one word in a file in this app's own folder, read before the first
 * window opens so a dark choice never starts on a white page.
 */
export const APPEARANCES = ['system', 'light', 'dark'] as const;
export type Appearance = (typeof APPEARANCES)[number];

const FILE = 'appearance.json';

/** What the renderer sent, or a refusal: only the three words travel. */
export function appearanceOf(value: unknown): Appearance {
  if ((APPEARANCES as readonly unknown[]).includes(value)) return value as Appearance;
  throw new Error(`unknown appearance: ${String(value).slice(0, 20)}`);
}

/** The saved choice. Missing, unreadable or unknown is the default, 跟随系统. */
export function readAppearance(folder: string): Appearance {
  try {
    const saved = (JSON.parse(readFileSync(path.join(folder, FILE), 'utf8')) as { appearance?: unknown }).appearance;
    return (APPEARANCES as readonly unknown[]).includes(saved) ? saved as Appearance : 'system';
  } catch {
    return 'system';
  }
}

/** Written beside and renamed over, so a crash mid-write leaves the old choice and not half a file. */
export function writeAppearance(folder: string, value: Appearance): void {
  mkdirSync(folder, { recursive: true });
  const target = path.join(folder, FILE);
  const pending = `${target}.${process.pid}.tmp`;
  writeFileSync(pending, `${JSON.stringify({ appearance: value })}\n`);
  renameSync(pending, target);
}
