import { join } from 'node:path';

/**
 * Where this app's pieces are, packed and unpacked.
 *
 * The runtime never goes inside the asar. It resolves its own modules from real
 * directories, which is why upstream sets `asar: false` for its own build;
 * staging it beside the archive instead lets this app keep asar packing for its
 * own code.
 */

export interface Layout {
  packaged: boolean;
  /** `app.getAppPath()`. In a pack this is the asar; unpacked it is the project. */
  appPath: string;
  /** `process.resourcesPath`. Meaningless unless packaged. */
  resourcesPath: string;
}

/** The staged runtime's root: the directory that owns `node_modules`. */
export function harnessRoot(layout: Layout): string {
  if (layout.packaged) return join(layout.resourcesPath, 'dsh');
  return join(layout.appPath, 'extra', 'dsh');
}

/** The runtime entry, relative to that root. Mirrors `dsh.foundry.harness.entry`. */
export const HARNESS_ENTRY = join('node_modules', '@deepseek-ai', 'dsh', 'lib', 'bin.js');

export function entryPath(layout: Layout): string {
  return join(harnessRoot(layout), HARNESS_ENTRY);
}

/**
 * The period bundle this app installs into the harness profile.
 *
 * Packed it rides beside the asar, because installing it means handing a
 * directory path to a package manager and to a symlink -- neither of which can
 * be a path inside an archive. Unpacked it is the kit's own `dsh-plugin/`, one
 * level up from the app, so an edit in the checkout is what the profile links
 * to.
 */
export function pluginDir(layout: Layout): string {
  if (layout.packaged) return join(layout.resourcesPath, 'dsh-plugin');
  return join(layout.appPath, '..', 'dsh-plugin');
}

/**
 * The frozen `foundry` CLI this app carries.
 *
 * The app shells out to it for every read and for the wiring steps, so a packed
 * build that expected one on the machine only worked where the kit was already
 * installed. `scripts/build-foundry.mjs` freezes it; this is where it lands.
 *
 * `FOUNDRY_BIN` still wins when it is set. That is the operator saying which one
 * to use -- pointing a dev run at a checkout's virtualenv is the everyday case --
 * and it is worth knowing that a stale one in a shell profile shadows the
 * bundled binary rather than being ignored.
 */
export function foundryBin(layout: Layout): string {
  if (layout.packaged) return join(layout.resourcesPath, 'foundry', 'foundry');
  return join(layout.appPath, 'extra', 'foundry', 'foundry');
}

/**
 * The bundle's copy inside the staged runtime, which must already exist.
 *
 * `scripts/fetch-harness.mjs` puts it there and `--check` refuses to package
 * without it. It cannot be made at run time in a packed app: that path is inside
 * the application bundle, which is not this process's to write to, and on a
 * signed build a write there breaks the signature. Unpacked, the same path is in
 * the staged tree and is writable, so the wiring step still repairs it.
 */
export function stagedBundleDir(layout: Layout, bundleName: string): string {
  return join(harnessRoot(layout), 'node_modules', bundleName);
}
