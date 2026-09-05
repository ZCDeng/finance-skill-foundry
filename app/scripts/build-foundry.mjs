#!/usr/bin/env node
/**
 * Freeze the `foundry` CLI into `extra/foundry/`.
 *
 * The app shells out to `foundry` for every read and for the wiring steps, so a
 * packed build that expected one on the machine was a packed build that only
 * worked where the kit was already installed. This freezes it with PyInstaller
 * into a one-dir bundle the app carries.
 *
 * One-dir rather than one-file: a one-file build unpacks itself into a temporary
 * directory on every launch, and this binary is launched dozens of times in a
 * session -- once per screen refresh.
 *
 *   node scripts/build-foundry.mjs           build it
 *   node scripts/build-foundry.mjs --check   verify without building
 */

import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const APP = join(HERE, '..');
const KIT = join(APP, '..');
const STAGE = join(APP, 'extra', 'foundry');
const BUILD = join(APP, 'extra', 'foundry-build');
const BIN = join(STAGE, 'foundry');
const STAMP = join(STAGE, 'BUILT');

/**
 * A fingerprint of everything this freeze embeds.
 *
 * The freeze takes the whole `foundry` package -- its Python and the resources
 * tree it carries in `--add-data` -- and copies it inside the bundle. Nothing
 * afterwards ever looks at the checkout again, so a bundle can be arbitrarily
 * older than the source it was made from and behave perfectly while doing the
 * wrong thing.
 *
 * That is not hypothetical. Two agent presets grew a `preset.yml` naming what
 * they are; the file was written, the packaged mirror was synced, both suites
 * were green, and the packaged app still installed presets with no display text
 * at all -- because the frozen CLI carried the resources tree from an earlier
 * freeze and `--check` only asked whether the binary existed.
 *
 * Path and content, both: a renamed file with identical bytes is a different
 * tree, and `install_presets` walks directories by name.
 */
function sourceHash() {
  const root = join(KIT, 'foundry');
  const hash = createHash('sha256');
  const walk = (dir) => {
    for (const entry of readdirSync(dir, { withFileTypes: true }).sort((a, b) =>
      a.name < b.name ? -1 : 1,
    )) {
      if (entry.name === '__pycache__' || entry.name.endsWith('.pyc')) continue;
      const path = join(dir, entry.name);
      if (entry.isDirectory()) walk(path);
      else {
        hash.update(relative(root, path).split('/').join('/'));
        hash.update(readFileSync(path));
      }
    }
  };
  walk(root);
  hash.update('build-foundry.mjs');
  hash.update(readFileSync(fileURLToPath(import.meta.url)));
  return hash.digest('hex');
}

/** The fingerprint the stamp recorded, or null when it predates them. */
function stampedHash() {
  if (!existsSync(STAMP)) return null;
  const line = readFileSync(STAMP, 'utf8')
    .split('\n')
    .find((row) => row.startsWith('source: '));
  return line ? line.slice(8).trim() : null;
}

/**
 * What the frozen bundle must be able to do before it counts as built.
 *
 * `probe` is the kit's own done-gate: it drives a whole fixture period through
 * the library and refuses on anything the period loop cannot do. Running it here
 * means a bundle that imports but cannot read a workbook, open DuckDB, or find
 * its own packaged fixtures fails at build time rather than in front of an
 * operator.
 */
function selfTest() {
  const scratch = join(BUILD, 'probe-var');
  rmSync(scratch, { recursive: true, force: true });
  execFileSync(BIN, ['--var', scratch, 'probe'], {
    stdio: 'inherit',
    // No inherited PATH to a checkout's virtualenv: the point is that this
    // bundle carries its own interpreter and its own native extensions.
    env: { HOME: process.env.HOME ?? '', PATH: '/usr/bin:/bin' },
  });
  if (process.platform === 'darwin') {
    execFileSync(BIN, ['--_foundry-runner-self-test', join(scratch, 'runner-workspace')], {
      stdio: 'inherit',
      env: { HOME: process.env.HOME ?? '', PATH: '/usr/bin:/bin' },
    });
  }
  rmSync(scratch, { recursive: true, force: true });
}

function check() {
  const problems = [];
  if (!existsSync(BIN)) problems.push(`no frozen CLI at extra/foundry/foundry`);
  if (!existsSync(join(STAGE, '_internal', 'foundry', 'resources', 'formulator-plugin'))) {
    // PyInstaller's data collector skips `.py` files, and this directory holds
    // nothing else -- so a bundle built without the whole resources tree comes
    // out missing it and every command fails at import, including ones that
    // never touch Formulator.
    problems.push('the packaged resources tree is incomplete (formulator-plugin)');
  }
  if (problems.length === 0) {
    const stamped = stampedHash();
    const current = sourceHash();
    if (stamped === null) {
      problems.push('the frozen CLI carries no source fingerprint (it predates this check)');
    } else if (stamped !== current) {
      problems.push(
        `the frozen CLI is not this checkout: it carries ${stamped.slice(0, 12)}, the source is ${current.slice(0, 12)}`,
      );
    }
  }
  return problems;
}

if (process.argv.includes('--check')) {
  const problems = check();
  if (problems.length === 0) {
    console.log(`foundry frozen: ${readFileSync(STAMP, 'utf8').split('\n')[0]}`);
    process.exit(0);
  }
  for (const problem of problems) console.error(`foundry: ${problem}`);
  console.error('run `npm run foundry` first');
  process.exit(1);
}

mkdirSync(BUILD, { recursive: true });
const venv = join(BUILD, '.venv');
const python = join(venv, 'bin', 'python');

console.log('building a throwaway environment …');
// `--clear`: the build environment is throwaway, and `uv venv` refuses to
// reuse one. Without it a second build fails on the venv it made itself,
// which is a script that works exactly once per checkout.
execFileSync('uv', ['venv', '--clear', '--python', '3.14', venv], { stdio: 'inherit' });
execFileSync('uv', ['pip', 'install', '--python', python, 'pyinstaller', KIT], { stdio: 'inherit' });

/*
 * A shim rather than the installed console script: PyInstaller wants a source
 * file to analyse, and the generated script in `bin/` is a wrapper whose imports
 * it cannot see through.
 */
const entry = join(BUILD, 'entry.py');
writeFileSync(entry, [
  'import sys',
  'from foundry.runner_entry import dispatch',
  'runner_result = dispatch(sys.argv[1:])',
  'if runner_result is not None:',
  '    sys.exit(runner_result)',
  'from foundry.cli import main',
  'sys.exit(main())',
  '',
].join('\n'));

console.log('freezing …');
rmSync(STAGE, { recursive: true, force: true });
execFileSync(
  join(venv, 'bin', 'pyinstaller'),
  [
    '--noconfirm',
    '--clean',
    '--onedir',
    '--name',
    'foundry',
    // The whole tree, verbatim. `--collect-data foundry` drops `.py` files,
    // which is every file in `resources/formulator-plugin`.
    '--add-data',
    `${join(KIT, 'foundry', 'resources')}:foundry/resources`,
    // A native extension: its shared library and its own data have to come too.
    '--collect-all',
    'duckdb',
    '--collect-all',
    'openpyxl',
    '--distpath',
    join(BUILD, 'dist'),
    '--workpath',
    join(BUILD, 'work'),
    '--specpath',
    BUILD,
    entry,
  ],
  { stdio: 'inherit' },
);

mkdirSync(dirname(STAGE), { recursive: true });
execFileSync('cp', ['-R', join(BUILD, 'dist', 'foundry'), STAGE]);

const version = JSON.parse(
  execFileSync(python, ['-c', 'import json,tomllib,pathlib;print(json.dumps(tomllib.loads(pathlib.Path("' + join(KIT, 'pyproject.toml') + '").read_text())["project"]))'], { encoding: 'utf8' }),
);
writeFileSync(
  STAMP,
  [
    `${version.name} ${version.version}`,
    'frozen-by: scripts/build-foundry.mjs (PyInstaller, one-dir)',
    // The tree this bundle embedded. `--check` recomputes it, so a freeze older
    // than the checkout is a refusal rather than a surprise in the packaged app.
    `source: ${sourceHash()}`,
    '',
    'Not in version control. Regenerate with `npm run foundry`.',
    '',
  ].join('\n'),
);

console.log('self-test: the kit\'s own fixture period …');
selfTest();

const problems = check();
if (problems.length) {
  for (const problem of problems) console.error(`foundry: ${problem}`);
  process.exit(1);
}
console.log(`foundry frozen: ${version.name} ${version.version}`);
