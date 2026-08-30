import { execFile } from 'node:child_process';
import { lstatSync, mkdirSync, readFileSync, rmSync, statSync, symlinkSync } from 'node:fs';
import * as path from 'node:path';

/**
 * Putting this product's pieces where the runtime can find them, on every start.
 *
 * Both steps are idempotent and both are repeated rather than done once at
 * install time. A preset is read from its file each time a generation starts, so
 * an edit in the checkout has to be carried over deliberately; and a profile
 * whose link was broken by a moved checkout is a profile that boots with no
 * period tools and says nothing about it.
 */

function run(bin: string, args: string[], env: NodeJS.ProcessEnv): Promise<string> {
  return new Promise((resolve, reject) => {
    execFile(bin, args, { env, encoding: 'utf8', timeout: 300_000 }, (error, stdout, stderr) => {
      if (error) return reject(new Error((stderr || stdout || error.message).trim()));
      return resolve(stdout);
    });
  });
}

/**
 * Install the period tools into the harness's `web` profile.
 *
 * One command and deliberately not two: `add` writes the package into the
 * profile's dependencies and appends it to `dsh.profile.bundles`, and the
 * package carries its own `dsh.bundle.patch`, so the insert row arrives from
 * there. Passing that same file as `--patch` composes the row twice.
 */
export async function installPlugin(opts: {
  entry: string;
  home: string;
  pluginDir: string;
}): Promise<void> {
  await run(
    process.execPath,
    [opts.entry, 'plugin', '--profile', 'web', 'add', opts.pluginDir],
    { ...process.env, DSH_HOME: opts.home, ELECTRON_RUN_AS_NODE: '1' },
  );
  ensureLinked({ ...opts, installRoot: path.dirname(path.dirname(path.dirname(path.dirname(opts.entry)))) });
}

/**
 * Put the package where the loader will actually find it.
 *
 * `dsh plugin add` does two things: it writes the profile's manifest, and it has
 * pnpm materialise a link in `node_modules`. Under `ELECTRON_RUN_AS_NODE` only
 * the first happens. Measured: the profile came back with the package in its
 * `dependencies` and in `dsh.profile.bundles`, `pnpm-lock.yaml` and
 * `.package-map.json` both written, and no `node_modules/<name>` at all -- so
 * the row composed, the loader tried to import it, and the boot died with
 * `Cannot find package`. The same command from a plain `node` creates the link.
 *
 * So the manifest half stays with the supported command and the link is made
 * here, where it does not depend on a package manager running correctly inside
 * an Electron that is pretending to be Node. It is also worth doing on every
 * start for its own sake: a moved checkout leaves a link pointing at nothing,
 * and a dangling link fails exactly the same way.
 *
 * A symlink rather than a copy, matching what `add` does for a local path: an
 * edit in the checkout is then live in the profile, which is what a developer
 * expects. A packaged build has no checkout to point at and will want the copy.
 *
 * Two roots, and the second one is the awkward one. Under `ELECTRON_RUN_AS_NODE`
 * the loader does not find the package from the profile at all -- measured, with
 * the profile link present and pnpm's own install complete, the boot still died
 * with `Cannot find package`, while the identical home under a plain `node`
 * booted fine. The specifier is imported from
 * `<install>/node_modules/@deepseek-ai/cordis-plugin-loader`, so
 * `<install>/node_modules/<name>` is on that importer's own lookup path and a
 * link there works under both runtimes.
 *
 * Writing into a pinned install tree is impolite and a re-pin wipes it, which is
 * why it is re-made on every start rather than treated as installed. The profile
 * link stays too: it is what a plain-node run of the same home resolves, and
 * dropping it would make this app's home only bootable by this app.
 */
export function ensureLinked(opts: {
  home: string;
  pluginDir: string;
  installRoot: string;
  profile?: string;
}): string[] {
  const name = JSON.parse(readFileSync(path.join(opts.pluginDir, 'package.json'), 'utf8')).name as string;
  const roots = [
    path.join(opts.home, 'profiles', opts.profile ?? 'web', 'node_modules'),
    path.join(opts.installRoot, 'node_modules'),
  ];
  return roots.map((root) => {
    const target = path.join(root, name);
    mkdirSync(root, { recursive: true });
    if (linkIsGood(target, opts.pluginDir)) return target;
    rmSync(target, { recursive: true, force: true });
    symlinkSync(opts.pluginDir, target, 'dir');
    return target;
  });
}

/** Whether something already at `target` resolves to the directory we want. */
function linkIsGood(target: string, pluginDir: string): boolean {
  try {
    lstatSync(target);
  } catch {
    return false;
  }
  try {
    // Resolves the link; a dangling one throws here and gets replaced.
    return statSync(target).isDirectory() && statSync(target).ino === statSync(pluginDir).ino;
  } catch {
    return false;
  }
}

/**
 * Install the `period` and `f3` agent presets.
 *
 * Through the CLI rather than by copying here: `foundry` owns where a preset
 * comes from and what a valid one looks like, and a second copier in this
 * process would be a second thing to keep in step.
 */
export async function installPresets(opts: { foundryBin: string; home: string; varRoot: string }): Promise<void> {
  await run(opts.foundryBin, ['--var', opts.varRoot, 'install-presets', '--dsh-home', opts.home], process.env);
}

/** The runtime entry inside an install root. */
export function entryPath(installRoot: string): string {
  return path.join(installRoot, 'node_modules', '@deepseek-ai', 'dsh', 'lib', 'bin.js');
}
