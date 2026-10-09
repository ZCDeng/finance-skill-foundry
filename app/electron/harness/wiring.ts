import { execFile } from 'node:child_process';
import {
  existsSync,
  lstatSync,
  mkdirSync,
  readFileSync,
  renameSync,
  rmSync,
  statSync,
  symlinkSync,
  writeFileSync,
} from 'node:fs';
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
 * Which wiring step a run is on, and what it would mean if it stopped there.
 *
 * The steps fail in different ways and the operator cannot tell them apart from
 * the symptom. A dangling plugin link makes the runtime's whole tree fail to
 * load, and what reaches the screen is the harness's own settings dialog saying
 * an acknowledgement could not be saved -- which names nothing that is actually
 * wrong. So the step is carried out to the surface rather than logged.
 */
export type WiringStep = 'plugin' | 'presets' | 'attach';

export type Wiring =
  | { state: 'pending' }
  | { state: 'ready' }
  | { state: 'failed'; step: WiringStep; message: string };

/** What a stopped step costs, in the operator's terms rather than the code's. */
export const WIRING_CONSEQUENCE: Record<WiringStep, string> = {
  plugin: '分析工具未能加载，暂时无法在对话中读取资料或计算。',
  presets: '分析助手配置未能加载，请查看下方错误后重试。',
  attach: '对话服务未能启动；已保存的资料和分析仍可在工作台查看。',
};

/**
 * Install the period tools into the harness's `web` profile.
 *
 * Not through `dsh plugin add`, and that is a decision the first clean-machine
 * run forced. That command shells out to pnpm, and a machine without one gets
 * `pnpm not found on PATH — install pnpm to manage profile plugins`. Every
 * earlier run here passed only because the developer's own environment had
 * corepack in it; under `env -i` the whole wiring step fails and the workbench
 * never starts.
 *
 * What the command does is two things, and neither needs a package manager: add
 * a name to the profile's manifest, and put the package where the loader can
 * find it. The second was already being done by hand -- pnpm does not
 * materialise the link under `ELECTRON_RUN_AS_NODE` either -- so this takes the
 * first half too and stops depending on a tool this app does not ship.
 */
export async function installPlugin(opts: {
  entry: string;
  home: string;
  pluginDir: string;
  /** The staged runtime's own copy of the bundle. Must already exist. */
  stagedBundle: string;
  /** The staged runtime's root, for finding the companions npm put there. */
  harnessRoot: string;
}): Promise<void> {
  await materialiseProfile(opts.entry, opts.home);
  addToProfileManifest(opts);
  ensureProfileLink(opts);
  assertStagedBundle(opts.stagedBundle, opts.pluginDir);
  installCompanions(opts);
}

/**
 * Name the staged companions in the profile too.
 *
 * A companion is a third-party bundle this product ships rather than asks the
 * operator to add, and the runtime will not load one it has not been told
 * about. The same two keys as the period bundle, for the same two reasons.
 *
 * The directory is the one `npm install` already made inside the staged
 * runtime, not a copy: it carries native bindings and 150MB of vendor output,
 * and a second copy under the profile would be that again for no gain.
 *
 * A companion the kit declares but the tree does not hold is a refusal rather
 * than a silent skip. `scripts/fetch-harness.mjs --check` says the same thing
 * before a build; this is the claim at run time, where a stale checkout is the
 * likely cause and the message can say so.
 */
export function installCompanions(opts: {
  home: string;
  pluginDir: string;
  harnessRoot: string;
  profile?: string;
}): string[] {
  const kit = JSON.parse(readFileSync(path.join(opts.pluginDir, 'package.json'), 'utf8')) as {
    dsh?: { foundry?: { companions?: Record<string, { package?: string; add?: string }> } };
  };
  const installed: string[] = [];
  for (const companion of Object.values(kit.dsh?.foundry?.companions ?? {})) {
    if (!companion.package || !String(companion.add ?? '').startsWith('staged')) continue;
    const dir = path.join(opts.harnessRoot, 'node_modules', companion.package);
    if (!existsSync(path.join(dir, 'package.json'))) {
      throw new Error(`companion ${companion.package} is not staged at ${dir}; run \`npm run harness\` in app/`);
    }
    addToProfileManifest({ home: opts.home, pluginDir: dir, profile: opts.profile });
    ensureProfileLink({ home: opts.home, pluginDir: dir, profile: opts.profile });
    installed.push(companion.package);
  }
  return installed;
}

/**
 * Make the runtime write out the profile directory, if this home is new.
 *
 * `--dump-config` is the cheapest command that does it: it composes the tree,
 * prints it, and exits without binding a port. The output is discarded; what is
 * wanted is the directory it leaves behind.
 */
async function materialiseProfile(entry: string, home: string): Promise<void> {
  await run(process.execPath, [entry, '--profile', 'web', '--dump-config'], {
    ...process.env,
    DSH_HOME: home,
    ELECTRON_RUN_AS_NODE: '1',
  });
}

/**
 * Name the bundle in the profile's own manifest.
 *
 * Two keys, both of which the runtime reads: `dependencies`, which is what a
 * package manager would have written, and `dsh.profile.bundles`, which is the
 * ordered list of layers the loader composes. The bundle's own
 * `dsh.bundle.patch` contributes its insert row from there, which is why the
 * row does not have to be written anywhere else -- and why handing that same
 * patch file to `--patch` as well would compose it twice.
 *
 * Idempotent, and it appends rather than replaces: another product's bundle in
 * the same profile is not this app's to remove.
 *
 * Written only when the bytes actually change, and then through a temporary
 * file. Both halves answer the same failure. This runs on every start, so the
 * ordinary case is a file that already says exactly this -- and rewriting it
 * anyway handed a concurrent reader a window in which the manifest was
 * truncated. A runtime that reads it then fails to compose its whole plugin
 * tree, and what reaches the operator is an unstyled upstream page saying
 * `failed to import loader entry`, naming a bundle that is perfectly fine.
 *
 * The single-instance lock in `main.ts` is the other half of that fix. This is
 * the half that also covers an operator editing the file, or a backup tool
 * reading it while this writes.
 */
export function addToProfileManifest(opts: {
  home: string;
  pluginDir: string;
  profile?: string;
}): string {
  const name = JSON.parse(readFileSync(path.join(opts.pluginDir, 'package.json'), 'utf8')).name as string;
  const manifestPath = path.join(opts.home, 'profiles', opts.profile ?? 'web', 'package.json');
  const manifest = JSON.parse(readFileSync(manifestPath, 'utf8')) as {
    dependencies?: Record<string, string>;
    dsh?: { profile?: { bundles?: string[] } };
  };
  manifest.dependencies = { ...manifest.dependencies, [name]: `link:${opts.pluginDir}` };
  const bundles = manifest.dsh?.profile?.bundles ?? [];
  if (!bundles.includes(name)) bundles.push(name);
  manifest.dsh = { ...manifest.dsh, profile: { ...manifest.dsh?.profile, bundles } };
  writeIfChanged(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
  return name;
}

/**
 * Put `text` at `target`, writing only when it differs from what is there.
 *
 * The rename is atomic within one filesystem, so a reader sees the old file or
 * the new one and never half of either. The temporary name carries this pid so
 * two writers cannot collide on it.
 */
export function writeIfChanged(target: string, text: string): boolean {
  try {
    if (readFileSync(target, 'utf8') === text) return false;
  } catch {
    // No file yet, or unreadable. Either way the write below settles it.
  }
  const temp = `${target}.${process.pid}.tmp`;
  try {
    writeFileSync(temp, text);
    renameSync(temp, target);
  } finally {
    rmSync(temp, { force: true });
  }
  return true;
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
 * `foundryBin` is the frozen CLI the packed app carries in `Resources/foundry`;
 * only a checkout run falls back to one on PATH (see `foundryBin` in main.ts).
 */
export async function installPresets(opts: {
  foundryBin: string;
  home: string;
  varRoot: string;
}): Promise<void> {
  await run(opts.foundryBin, ['--var', opts.varRoot, 'install-presets', '--dsh-home', opts.home], process.env);
}
