#!/usr/bin/env node
/**
 * Prove the frozen Formulator is the one this kit can use.
 *
 * A readiness probe is not enough and this is the whole reason the gate exists:
 * a bundle built without `foundry` starts, serves its frontend, answers a health
 * check and passes the kit's identity gate, and then offers no locked-catalog
 * connector at all. The window is locked, the lease is held, the page is up, and
 * the one thing the operator opened it for is missing -- quietly, because Data
 * Formulator catches a plugin ImportError and files it under disabled loaders.
 *
 * So the gate drives a real locked window and asks the running server which
 * connectors it has.
 *
 *   node scripts/gate-formulator.mjs [--bin <frozen foundry>] [--formulator <frozen df>] [--var <scratch dir>]
 */

import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const APP = join(HERE, '..');
const KIT = join(APP, '..');

function flag(name, fallback) {
  const at = process.argv.indexOf(name);
  return at >= 0 && process.argv[at + 1] ? process.argv[at + 1] : fallback;
}

const FOUNDRY = flag('--bin', join(APP, 'extra', 'foundry', 'foundry'));
const FORMULATOR = flag('--formulator', join(APP, 'extra', 'formulator', 'data_formulator'));
const VAR = flag('--var', join(APP, 'extra', 'formulator-build', 'gate-var'));
const FIXTURES = join(KIT, 'fixtures', 'period-smoke');

for (const [label, path] of [['foundry', FOUNDRY], ['formulator', FORMULATOR]]) {
  if (!existsSync(path)) {
    console.error(`gate: no frozen ${label} at ${path}`);
    process.exit(1);
  }
}

/*
 * A bare environment on purpose. The point of freezing is that neither binary
 * needs an interpreter, a virtualenv or a PATH entry from this machine, and a
 * gate that inherited one would pass on the build box and fail everywhere else.
 */
const BARE = { HOME: process.env.HOME ?? '', PATH: '/usr/bin:/bin', FOUNDRY_FORMULATOR_BIN: FORMULATOR };

const run = (args, extra = {}) =>
  execFileSync(FOUNDRY, ['--var', VAR, ...args], { encoding: 'utf8', env: { ...BARE, ...extra } });

rmSync(VAR, { recursive: true, force: true });
mkdirSync(VAR, { recursive: true });

console.log('locking a fixture window …');
run(['create']);
run([
  'import',
  '--coa', join(FIXTURES, 'coa.xlsx'),
  '--units', join(FIXTURES, 'units.xlsx'),
  '--map', join(FIXTURES, 'map.xlsx'),
  '--named', join(FIXTURES, 'named.json'),
  '--drop-dir', FIXTURES,
]);
run(['lock']);

console.log('launching the frozen Formulator …');
let spec;
try {
  spec = JSON.parse(run(['launch-formulator']));
} catch (error) {
  console.error('gate: launch-formulator refused:', String(error.stderr ?? error.message).trim());
  process.exit(1);
}
console.log(`  ${spec.url}${spec.identity ? ` (${spec.identity})` : ' (identity confirmed)'}`);

let failure = null;
try {
  const response = await fetch(`${spec.url}/api/data-loaders`);
  if (!response.ok) throw new Error(`/api/data-loaders answered ${response.status}`);
  const body = await response.json();
  const types = (body?.data?.loaders ?? []).map((loader) => loader.type);
  console.log(`  connectors: ${types.join(', ')}`);
  if (!types.includes('locked_catalog')) {
    failure =
      'the locked-catalog connector did not register. The bundle can serve pages and still be ' +
      'useless: a frozen app ignores PYTHONPATH, so the plugin\'s own `foundry` imports resolve ' +
      'only from inside it. Rebuild carrying foundry, duckdb and openpyxl.';
  }
} catch (error) {
  failure = `could not ask the server for its connectors: ${error.message}`;
} finally {
  try {
    run(['stop-formulator']);
  } catch (error) {
    console.error('gate: stop-formulator refused:', String(error.stderr ?? error.message).trim());
  }
}

if (failure) {
  console.error(`gate: ${failure}`);
  process.exit(1);
}
rmSync(VAR, { recursive: true, force: true });
console.log('gate: the frozen Formulator serves this kit\'s locked catalog');
