import { execFile } from 'node:child_process';
import { existsSync, lstatSync, mkdirSync, readFileSync, rmSync, statSync, symlinkSync } from 'node:fs';
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
  /** The staged runtime's own copy of the bundle. Must already exist. */
  stagedBundle: string;
}): Promise<void> {
  await run(
    process.execPath,
    [opts.entry, 'plugin', '--profile', 'web', 'add', opts.pluginDir],
    { ...process.env, DSH_HOME: opts.home, ELECTRON_RUN_AS_NODE: '1' },
  );
  ensureProfileLink(opts);
  assertStagedBundle(opts.stagedBundle, opts.pluginDir);
}

/**
 * Put the package where the profile's own resolver will find it.
 *
 * `dsh plugin add` does two things: it writes the profile's manifest, and it has
 * pnpm materialise a link in `node_modules`. Under `ELECTRON_RUN_AS_NODE` only
 * the first happens. Measured: the profile came back with the package in its
 * `dependencies` and in `dsh.profile.bundles`, `pnpm-lock.yaml` and
 * `.package-map.json` both written, and no `node_modules/<name>` at all. The
 * same command from a plain `node` creates the link.
 *
 * So the manifest half stays with the supported command and the link is made
 * here, where it does not depend on a package manager running correctly inside
 * an Electron that is pretending to be Node. Worth doing on every start for its
 * own sake too: a moved checkout leaves a link pointing at nothing, and a
 * dangling link fails exactly the same way as a missing one.
 *
 * This is the profile under `userData`, which is always this app's to write.
 */
export function ensureProfileLink(opts: {
  home: string;
  pluginDir: string;
  profile?: string;
}): string {
  const name = JSON.parse(readFileSync(path.join(opts.pluginDir, 'package.json'), 'utf8')).name as string;
  const root = path.join(opts.home, 'profiles', opts.profile ?? 'web', 'node_modules');
  const target = path.join(root, name);
  mkdirSync(root, { recursive: true });
  if (resolvesTo(target, opts.pluginDir)) return target;
  rmSync(target, { recursive: true, force: true });
  symlinkSync(opts.pluginDir, target, 'dir');
  return target;
}

/**
 * The copy inside the staged runtime, which has to be there already.
 *
 * Under `ELECTRON_RUN_AS_NODE` the loader does not resolve the package from the
 * profile at all: with the profile link present and pnpm's install complete, the
 * boot still died with `Cannot find package`, while the identical home under a
 * plain `node` booted. The specifier is imported from the install tree's own
 * copy of the loader, so `<install>/node_modules/<name>` is on that importer's
 * lookup path.
 *
 * Staged at fetch time rather than written here, because in a packed app that
 * path is inside the application bundle -- not this process's to write, and a
 * write there breaks a signature. `scripts/fetch-harness.mjs --check` refuses to
 * package without it; this is the same claim at run time, where the message can
 * name what to do.
 */
export function assertStagedBundle(stagedBundle: string, pluginDir: string): void {
  const manifest = path.join(stagedBundle, 'package.json');
  if (!existsSync(manifest)) {
    throw new Error(
      `the period bundle is not staged at ${stagedBundle}; run \`npm run harness\` in app/`,
    );
  }
  const staged = JSON.parse(readFileSync(manifest, 'utf8')).name as string;
  const wanted = JSON.parse(readFileSync(path.join(pluginDir, 'package.json'), 'utf8')).name as string;
  if (staged !== wanted) {
    throw new Error(`${stagedBundle} holds ${staged}, not ${wanted}`);
  }
}

/** Whether something at `target` already resolves to the directory we want. */
function resolvesTo(target: string, pluginDir: string): boolean {
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
 *
 * This is the one wiring step that still needs the Python side on the machine.
 * A packed app carries the runtime and the bundle; it does not yet carry
 * `foundry` itself, so `FOUNDRY_BIN` has to name one. That is a real gap and it
 * is named here rather than papered over.
 */
export async function installPresets(opts: {
  foundryBin: string;
  home: string;
  varRoot: string;
}): Promise<void> {
  await run(opts.foundryBin, ['--var', opts.varRoot, 'install-presets', '--dsh-home', opts.home], process.env);
}
