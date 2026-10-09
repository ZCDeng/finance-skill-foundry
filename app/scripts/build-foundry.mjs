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
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { foundrySourceHash, stampedHash } from './source-hash.mjs';

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
 * tree it carries in `--add-data` -- and copies it inside the bundle. That is not
 * a hypothetical drift: two agent presets grew a `preset.yml` naming what they
 * are, both suites were green, and the packaged app still installed presets with
 * no display text at all -- because the frozen CLI carried the resources tree
 * from an earlier freeze and `--check` only asked whether the binary existed.
 */
const sourceHash = () => foundrySourceHash(KIT, fileURLToPath(import.meta.url));

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
  collectionSelfTest(join(scratch, 'collection'));
  rmSync(scratch, { recursive: true, force: true });
}

/**
 * 收费明细 through to a collection run, on the frozen binary.
 *
 * `probe` never reaches DuckDB's detail tables or the collection engine, and
 * 0.10.0 shipped a run that hashed its own `.py` file -- which the bundle does
 * not carry, only bytecode. Every 收缴率 failed in the packaged app while every
 * test passed in a checkout. The rows are the hand-worked ones in
 * tests/test_billing_detail.py, cut down: 当期 100 of 300 应收. The 应收 file is
 * GBK, as 收费系统 exports usually are.
 */
function collectionSelfTest(scratch) {
  const env = { HOME: process.env.HOME ?? '', PATH: '/usr/bin:/bin' };
  const files = join(scratch, 'files');
  const vars = join(scratch, 'var');
  mkdirSync(files, { recursive: true });
  const write = (name, lines, encoding = 'UTF-8') => {
    const path = join(files, name);
    const text = lines.join('\r\n') + '\r\n';
    // GBK is what a Chinese-locale Excel saves as CSV. The bundle decodes it in
    // Python's own codecs, so this proves they were frozen in, not that DuckDB can.
    writeFileSync(path, encoding === 'UTF-8' ? text : execFileSync('/usr/bin/iconv', ['-f', 'UTF-8', '-t', encoding], { input: text }));
    return path;
  };
  const receivables = write('应收.csv', [
    '应收单号,房产编号,收费项目,账期,应收原额,减免额,应收净额,单据状态',
    'B1,P1,住宅物业服务费,2026-01,100,0,100,正常',
    'B2,P2,住宅物业服务费,2026-02,200,0,200,正常',
  ], 'GBK');
  const receipts = write('实收.csv', [
    '收款单号,收款日期,应收单号,收款金额,收款方式,款项性质',
    'R1,2026-01-15,B1,100,微信,当期',
  ]);
  const run = (args) =>
    execFileSync(BIN, ['--var', vars, ...args], { encoding: 'utf8', env, stdio: ['ignore', 'pipe', 'inherit'] }).trim();
  const task = run(['task-new', '--title', 'self-test']);
  const as = ['--task', task, '--actor', 'manager'];
  const ids = {};
  for (const [kind, name, path] of [['receivable', '应收', receivables], ['receipt', '实收', receipts]]) {
    const added = JSON.parse(run([...as, 'detail-add', '--kind', kind, '--name', name, '--path', path]));
    const encoding = added.files?.[0]?.encoding;
    if (kind === 'receivable' && encoding !== 'gb18030') {
      throw new Error(`self-test: the GBK 应收 file was read as ${JSON.stringify(encoding)}, expected "gb18030"`);
    }
    ids[kind] = added.id;
    run([...as, 'detail-confirm', '--detail', ids[kind]]);
  }
  const result = JSON.parse(run([...as, 'collection-run', '--spec', JSON.stringify({ ...ids, as_of: '2026-08-31' })]));
  const rate = result.result.figures.collection_rate_current;
  if (rate !== '0.3333') {
    throw new Error(`self-test: collection run gave 当期收缴率 ${JSON.stringify(rate)}, expected "0.3333"`);
  }
  console.log(`self-test: collection run ok (当期收缴率 ${rate})`);
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
    const stamped = stampedHash(STAMP);
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

console.log('self-test: the kit\'s own fixture period …');
selfTest();

// Stamped only once the self-test passed: `--check` trusts the stamp, so a
// bundle that failed its self-test must not leave one behind.
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

const problems = check();
if (problems.length) {
  for (const problem of problems) console.error(`foundry: ${problem}`);
  process.exit(1);
}
console.log(`foundry frozen: ${version.name} ${version.version}`);
