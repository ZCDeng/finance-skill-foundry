#!/usr/bin/env node
/**
 * Stage the runtime the FA Foundry harness runs on into `extra/dsh/`.
 *
 * The tree is not in version control: it is ~280MB across tens of thousands of
 * files, and what is reproducible is the version in the pin, not the bytes. Run
 * this once after `npm install`; `npm run package` checks for it and stops
 * rather than building an app whose workbench never starts.
 *
 * The version is read from the kit's own `dsh-plugin/package.json`
 * (`dsh.foundry.harness`) rather than restated here. That file already declares
 * the tool roster, the profiles and the presets; the harness it runs on belongs
 * beside them, and a second copy of the number is a second thing to keep true.
 *
 *   node scripts/fetch-harness.mjs           stage it
 *   node scripts/fetch-harness.mjs --check   verify without touching anything
 */

import { execFileSync } from 'node:child_process';
import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const APP = join(HERE, '..');
const KIT = join(APP, '..');
const PLUGIN_DIR = join(KIT, 'dsh-plugin');
const STAGE = join(APP, 'extra', 'dsh');
const PIN_FILE = join(STAGE, 'PIN');

const kit = JSON.parse(readFileSync(join(PLUGIN_DIR, 'package.json'), 'utf8'));
const harness = kit.dsh.foundry.harness;
const PIN = `${harness.package}@${harness.version}`;

/*
 * Companions that ride in the same tree.
 *
 * A companion is a third-party bundle this product ships rather than asks the
 * operator to add, and it goes into the runtime's own `node_modules` for the
 * same reason the period bundle does: under `ELECTRON_RUN_AS_NODE` the loader
 * resolves a bundle from the install tree, not from the profile.
 *
 * `file-upload` is not here. It carries an `add` command because it is added by
 * hand against a real dsh CLI; only a companion whose `add` says it is staged
 * belongs in this list.
 */
const COMPANIONS = Object.values(kit.dsh.foundry.companions ?? {}).filter((companion) =>
  String(companion.add ?? '').startsWith('staged'),
);
const COMPANION_PINS = COMPANIONS.map((companion) => `${companion.package}@${companion.version}`);

function pinOnDisk() {
  if (!existsSync(PIN_FILE)) return null;
  const line = readFileSync(PIN_FILE, 'utf8').split('\n').find((row) => row.startsWith('pin:'));
  return line ? line.slice(4).trim() : null;
}

function check() {
  const problems = [];
  if (!existsSync(join(STAGE, harness.entry))) {
    problems.push(`no runtime entry at extra/dsh/${harness.entry}`);
  }
  const staged = pinOnDisk();
  if (staged !== PIN) problems.push(`staged pin is ${staged ?? 'absent'}, the kit declares ${PIN}`);
  /*
   * The bundle has to be inside the runtime's own tree, not only in the
   * profile. Measured in U10: under `ELECTRON_RUN_AS_NODE` the loader does not
   * resolve the package from the profile at all, and the specifier is imported
   * from the install tree's own copy of the loader -- so this is the copy that
   * makes the boot work in a packaged app, where nothing may write into the
   * bundle at run time.
   */
  if (!existsSync(join(STAGE, 'node_modules', kit.name, 'package.json'))) {
    problems.push(`the period bundle is not staged at extra/dsh/node_modules/${kit.name}`);
  }
  /*
   * A companion at the wrong version is worse than an absent one: the profile
   * manifest names a version, the loader resolves whatever is on disk, and the
   * mismatch shows up as a tool that is registered but behaves differently.
   */
  for (const companion of COMPANIONS) {
    const manifest = join(STAGE, 'node_modules', companion.package, 'package.json');
    if (!existsSync(manifest)) {
      problems.push(`companion ${companion.package} is not staged at extra/dsh/node_modules`);
      continue;
    }
    const staged = JSON.parse(readFileSync(manifest, 'utf8')).version;
    if (staged !== companion.version) {
      problems.push(`companion ${companion.package} is staged at ${staged}, the kit declares ${companion.version}`);
    }
  }
  return problems;
}

if (process.argv.includes('--check')) {
  const problems = check();
  if (problems.length === 0) {
    console.log(`harness staged: ${PIN}`);
    process.exit(0);
  }
  for (const problem of problems) console.error(`harness: ${problem}`);
  console.error('run `npm run harness` first');
  process.exit(1);
}

mkdirSync(STAGE, { recursive: true });
writeFileSync(
  join(STAGE, 'package.json'),
  `${JSON.stringify({ name: 'foundry-harness-stage', private: true, type: 'module' }, null, 2)}\n`,
);

console.log([`staging ${PIN}`, ...COMPANION_PINS].join(' + ') + ' into extra/dsh …');
/*
 * `--ignore-scripts` because nothing in this tree needs one and a bundle that
 * did would be running third-party code on a build machine. Measured on
 * dsh-univer-office 0.2.12 and its 55 transitive packages: no preinstall,
 * install or postinstall anywhere; the only lifecycle hooks are `prepare`,
 * which npm does not run for a registry tarball.
 */
execFileSync('npm', ['install', PIN, ...COMPANION_PINS, '--no-audit', '--no-fund', '--omit=dev', '--ignore-scripts'], {
  cwd: STAGE,
  stdio: 'inherit',
});

/*
 * A copy rather than a link. A symlink out of the staged tree points at a
 * checkout that a packaged app does not carry, and electron-builder would
 * either follow it into the source directory or ship a dangling name.
 */
const bundleTarget = join(STAGE, 'node_modules', kit.name);
rmSync(bundleTarget, { recursive: true, force: true });
cpSync(PLUGIN_DIR, bundleTarget, {
  recursive: true,
  filter: (src) => !src.endsWith('node_modules') && !src.endsWith('.DS_Store'),
});

writeFileSync(
  PIN_FILE,
  [
    `pin: ${PIN}`,
    `entry: ${harness.entry}`,
    `bundle: node_modules/${kit.name} (copied from ../../dsh-plugin)`,
    ...COMPANION_PINS.map((pin) => `companion: ${pin}`),
    'staged-by: scripts/fetch-harness.mjs',
    '',
    'Not in version control. Regenerate with `npm run harness`.',
    '',
  ].join('\n'),
);

const problems = check();
if (problems.length) {
  for (const problem of problems) console.error(`harness: ${problem}`);
  process.exit(1);
}
console.log(`harness staged: ${PIN}`);
