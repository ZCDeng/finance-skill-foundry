#!/usr/bin/env node
/**
 * Freeze Data Formulator into `extra/formulator/`.
 *
 * The kit treats Formulator as a leased reader discovered on PATH, which meant a
 * packed app only had a data screen where somebody had already installed it.
 * This freezes it too.
 *
 * The bundle carries `foundry` as well, and that is the part that is not
 * obvious. `DF_PLUGIN_DIR` points at `formulator-plugin/`, a loose `.py` file
 * that Data Formulator imports through `spec_from_file_location`; a frozen app
 * can do that, but it ignores `PYTHONPATH`, so that file's own imports --
 * `foundry.*`, and through them duckdb and openpyxl -- can only ever resolve
 * from inside the bundle. A freeze without them starts, serves, passes a
 * readiness probe, and silently offers no locked-catalog connector at all.
 *
 *   node scripts/build-formulator.mjs           build it
 *   node scripts/build-formulator.mjs --check   verify without building
 */

import { execFileSync, spawn } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { foundrySourceHash, stampedHash } from './source-hash.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const APP = join(HERE, '..');
const KIT = join(APP, '..');
const STAGE = join(APP, 'extra', 'formulator');
const BUILD = join(APP, 'extra', 'formulator-build');
/*
 * Named `data_formulator` on purpose. The kit's identity gate now checks the
 * binary a launch recorded, so the name is no longer load-bearing -- but a
 * process list that says what the process is stays worth having.
 */
const NAME = 'data_formulator';
const BIN = join(STAGE, NAME);
const STAMP = join(STAGE, 'BUILT');
// The `foundry` this bundle carries for its connector, and how it was frozen.
const sourceHash = () => foundrySourceHash(KIT, fileURLToPath(import.meta.url));

function check() {
  const problems = [];
  if (!existsSync(BIN)) problems.push('no frozen Formulator at extra/formulator/data_formulator');
  // The 30MB built frontend. `app.py` resolves it from `__file__`, so it has to
  // land at `_internal/data_formulator/dist` or every request 404s while the
  // log looks clean.
  if (!existsSync(join(STAGE, '_internal', 'data_formulator', 'dist', 'index.html'))) {
    problems.push('the built frontend is missing (_internal/data_formulator/dist/index.html)');
  }
  // Without `foundry` in the bundle the locked-catalog connector cannot import,
  // and the failure is silent.
  if (!existsSync(join(STAGE, '_internal', 'foundry'))) {
    problems.push('the bundle does not carry foundry, so the locked-catalog connector cannot load');
  }
  if (problems.length === 0) {
    // The CLI bundle has the same check. Without one here the two could carry
    // different `foundry`s, and the connector would read a catalog with code
    // older than the code that wrote it.
    const stamped = stampedHash(STAMP);
    const current = sourceHash();
    if (stamped === null) {
      problems.push('the frozen Formulator carries no source fingerprint (it predates this check)');
    } else if (stamped !== current) {
      problems.push(
        `the frozen Formulator is not this checkout: it carries ${stamped.slice(0, 12)}, the source is ${current.slice(0, 12)}`,
      );
    }
  }
  return problems;
}

if (process.argv.includes('--check')) {
  const problems = check();
  if (problems.length === 0) {
    console.log(`formulator frozen: ${readFileSync(STAMP, 'utf8').split('\n')[0]}`);
    process.exit(0);
  }
  for (const problem of problems) console.error(`formulator: ${problem}`);
  console.error('run `npm run formulator` first');
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
execFileSync('uv', ['pip', 'install', '--python', python, 'pyinstaller', 'data-formulator==0.7.0', KIT], {
  stdio: 'inherit',
});

/*
 * `freeze_support()` before anything else, and the import inside the function.
 *
 * Data Formulator runs model-written code in `multiprocessing.Process` workers,
 * and the default start method on macOS is spawn -- which re-executes this
 * script in the child. Anything imported at module scope runs again there,
 * before `freeze_support()` has had a chance to say "you are the worker", and
 * the app relaunches itself instead of starting one.
 */
const entry = join(BUILD, 'df_entry.py');
writeFileSync(
  entry,
  [
    'import multiprocessing',
    '',
    'if __name__ == "__main__":',
    '    multiprocessing.freeze_support()',
    '    from data_formulator.app import run_app',
    '',
    '    run_app()',
    '',
  ].join('\n'),
);

console.log('freezing …');
rmSync(STAGE, { recursive: true, force: true });
execFileSync(
  join(venv, 'bin', 'pyinstaller'),
  [
    '--noconfirm',
    '--clean',
    '--onedir',
    '--name',
    NAME,
    // The app and its 30MB frontend. `collect_data_files` takes `dist/` because
    // it is data; `collect_submodules` takes the thirteen data loaders, which
    // are reached by string module path and are invisible to static analysis.
    '--collect-data',
    'data_formulator',
    '--collect-submodules',
    'data_formulator',
    // The kit, so the locked-catalog connector's own imports resolve.
    '--collect-all',
    'foundry',
    '--collect-all',
    'duckdb',
    '--hidden-import',
    'openpyxl',
    // litellm reads package-relative JSON at import and walks its own source
    // tree for provider configs. Data alone is not enough; the submodules are
    // reached from strings.
    '--collect-all',
    'litellm',
    // tiktoken finds its encodings through a plugin module nothing imports
    // statically. Without it the first token count raises `Unknown encoding
    // cl100k_base. Plugins found: []`.
    '--collect-submodules',
    'tiktoken_ext',
    // Two connectors read package-relative JSON at IMPORT time, and
    // data_formulator imports every loader module while registering them -- so a
    // missing file here is not a disabled connector, it is a process that dies
    // before it binds a port. Measured: without the first of these the frozen
    // app exits during startup with
    // `FileNotFoundError: .../_internal/azure/kusto/data/kcsb.json`.
    '--collect-data',
    'azure.kusto.data',
    '--collect-data',
    'azure.cosmos',
    // pyodbc's extension links a Homebrew dylib that is not part of this
    // bundle, and its hook dlopens it during analysis. The unfrozen app already
    // reports mssql disabled for the same reason, so nothing is lost.
    '--exclude-module',
    'pyodbc',
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

execFileSync('cp', ['-R', join(BUILD, 'dist', NAME), STAGE]);
writeFileSync(
  STAMP,
  [
    'data-formulator 0.7.0 (carries foundry, duckdb, openpyxl)',
    'frozen-by: scripts/build-formulator.mjs (PyInstaller, one-dir)',
    `source: ${sourceHash()}`,
    '',
    'Not in version control. Regenerate with `npm run formulator`.',
    '',
  ].join('\n'),
);

const problems = check();
if (problems.length) {
  for (const problem of problems) console.error(`formulator: ${problem}`);
  process.exit(1);
}
console.log('formulator frozen; run `npm run formulator:gate` to prove the connector loads');
