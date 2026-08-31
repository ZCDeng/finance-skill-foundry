import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import {
  HARNESS_ENTRY,
  entryPath,
  formulatorBin,
  foundryBin,
  harnessRoot,
  pluginDir,
  stagedBundleDir,
} from '../electron/harness/resources.js';

const read = (rel: string) => readFileSync(fileURLToPath(new URL(rel, import.meta.url)), 'utf8');
const KIT = JSON.parse(read('../../dsh-plugin/package.json'));
const BUILDER = read('../electron-builder.yml');

const PACKED = { packaged: true, appPath: '/A/Foundry.app/Contents/Resources/app.asar', resourcesPath: '/A/Foundry.app/Contents/Resources' };
const DEV = { packaged: false, appPath: '/repo/app', resourcesPath: '/unused' };

describe('where the runtime is', () => {
  it('rides beside the asar when packed, and in extra/ when not', () => {
    // Never inside the archive: it resolves its own modules from real
    // directories, which is why upstream sets `asar: false` for its own build.
    expect(harnessRoot(PACKED)).toBe('/A/Foundry.app/Contents/Resources/dsh');
    expect(harnessRoot(DEV)).toBe('/repo/app/extra/dsh');
    expect(entryPath(PACKED)).not.toContain('.asar');
  });

  it('builds the entry the kit declares', () => {
    // One pin, one entry. `dsh-plugin/package.json` is where the kit says which
    // harness it runs on, and this is the app agreeing with it rather than
    // restating it.
    expect(HARNESS_ENTRY.split('/').join('/')).toBe(KIT.dsh.foundry.harness.entry);
  });

  it('hands the period bundle over as a directory, never a path inside an archive', () => {
    // Installing it means giving the path to a package manager and to a symlink.
    // Neither can be a path inside an asar.
    expect(pluginDir(PACKED)).toBe('/A/Foundry.app/Contents/Resources/dsh-plugin');
    expect(pluginDir(PACKED)).not.toContain('.asar');
    // Normalised by `join`: one level up from the app is the kit's own copy.
    expect(pluginDir(DEV)).toBe('/repo/dsh-plugin');
  });

  it('looks for the staged copy inside the runtime tree', () => {
    // The one the loader actually resolves under Electron-as-Node.
    expect(stagedBundleDir(PACKED, 'finance-skill-foundry-dsh')).toBe(
      '/A/Foundry.app/Contents/Resources/dsh/node_modules/finance-skill-foundry-dsh',
    );
  });
});

describe('where the frozen CLI is', () => {
  it('rides beside the asar, like the runtime', () => {
    // It is an interpreter and a native extension. Both need real files.
    expect(foundryBin(PACKED)).toBe('/A/Foundry.app/Contents/Resources/foundry/foundry');
    expect(foundryBin(PACKED)).not.toContain('.asar');
    expect(foundryBin(DEV)).toBe('/repo/app/extra/foundry/foundry');
  });

  it('is preferred over PATH but not over an explicit override', () => {
    // `FOUNDRY_BIN` is the operator saying which one to use, which is the
    // everyday case for pointing a dev run at a checkout's virtualenv. Worth
    // knowing it shadows the bundled binary rather than being ignored.
    const main = read('../electron/main.ts');
    const order = main.slice(main.indexOf('function foundryBin('));
    expect(order.indexOf('process.env.FOUNDRY_BIN')).toBeLessThan(order.indexOf('packedFoundryBin'));
    expect(order.indexOf('packedFoundryBin')).toBeLessThan(order.indexOf("'foundry'"));
  });

  it('names it on this process, so the window itself can reach the store', () => {
    /*
     * The binary was resolved correctly and handed to two of its three callers.
     * The harness child got it through `boot.ts`, `install-presets` got it as an
     * argument, and the store binding this window reads through got a `varRoot`
     * and nothing else -- so `runFoundry` fell through to its last resort and
     * exec'd a bare `foundry` off PATH, which a packaged machine does not have.
     * Every screen in the window rendered `spawn foundry ENOENT`.
     *
     * `toBeGreaterThan(-1)` before the ordering, not after. `indexOf` returns -1
     * for a call that is not there, and -1 is less than every real index: without
     * these two lines, deleting the call is what makes the ordering assertion
     * pass, and the test would be most confident exactly when the bug was back.
     */
    const main = read('../electron/main.ts');
    const call = main.indexOf('nameFoundry(here)');
    const wire = main.indexOf('registerIpc(');
    expect(call, 'main.ts never calls nameFoundry').toBeGreaterThan(-1);
    expect(wire, 'main.ts never calls registerIpc').toBeGreaterThan(-1);
    expect(call, 'the binary must be named before the store binding is built').toBeLessThan(wire);
    expect(main.slice(main.indexOf('function nameFoundry('))).toContain('process.env.FOUNDRY_BIN =');
  });
});

describe('where the frozen Formulator is', () => {
  it('rides beside the asar and is named to the kit, not put on PATH', () => {
    // A frozen bundle is a directory beside an application. The kit's resolver
    // reads `FOUNDRY_FORMULATOR_BIN` first for exactly that reason.
    expect(formulatorBin(PACKED)).toBe('/A/Foundry.app/Contents/Resources/formulator/data_formulator');
    expect(formulatorBin(PACKED)).not.toContain('.asar');
    const main = read('../electron/main.ts');
    expect(main).toContain('FOUNDRY_FORMULATOR_BIN');
  });

  it('leaves an operator override alone', () => {
    const main = read('../electron/main.ts');
    const fn = main.slice(main.indexOf('function nameFormulator('));
    expect(fn.indexOf('process.env.FOUNDRY_FORMULATOR_BIN')).toBeLessThan(fn.indexOf('packedFormulatorBin'));
  });

  it('ships it whole, for the same reason as the CLI', () => {
    const block = BUILDER.slice(BUILDER.indexOf('from: extra/formulator'));
    const own = block.slice(0, block.indexOf('- from:', 1));
    expect(own).toContain('to: formulator');
    expect(own).not.toContain("'!**/*.ts'");
  });
});

describe('what the build config ships', () => {
  it('names node_modules explicitly, because electron-builder skips it quietly', () => {
    // A directory called `node_modules` inside `extraResources` is skipped
    // unless it is asked for by name, and the build still succeeds: `dsh/`
    // arrives holding the pin file and nothing else, and the workbench never
    // starts on a machine with no staged tree to fall back on.
    expect(BUILDER).toContain('from: extra/dsh/node_modules');
    expect(BUILDER).toContain('to: dsh/node_modules');
  });

  it('carries the period bundle as its own resource', () => {
    expect(BUILDER).toContain('from: ../dsh-plugin');
    expect(BUILDER).toContain('to: dsh-plugin');
  });

  it('lets nothing key-shaped into the bundle', () => {
    for (const pattern of ["'!**/.env'", "'!**/.env.*'", "'!**/*_API_KEY*'"]) {
      expect(BUILDER, pattern).toContain(pattern);
    }
  });

  it('ships the frozen CLI whole, with no source-tree filters', () => {
    // A PyInstaller one-dir bundle is an interpreter, a native DuckDB extension
    // and the packaged resources. The `.ts`/`.map` trimming that suits the
    // harness tree would take real files out of this one.
    const block = BUILDER.slice(BUILDER.indexOf('from: extra/foundry'));
    const own = block.slice(0, block.indexOf('- from:', 1));
    expect(own).toContain('to: foundry');
    expect(own).not.toContain("'!**/*.map'");
    expect(own).not.toContain("'!**/*.ts'");
  });

  it('refuses to package without a staged runtime', () => {
    // Packaging without it produces an app whose workbench never starts and says
    // nothing about why, so the check runs first and stops.
    const scripts = JSON.parse(read('../package.json')).scripts;
    expect(scripts.package.startsWith('npm run harness:check')).toBe(true);
    expect(scripts.dist.startsWith('npm run harness:check')).toBe(true);
    // And without the frozen CLI, which fails differently: the window opens and
    // every screen shows a refusal about a binary that is not there.
    expect(scripts.package).toContain('npm run foundry:check');
    expect(scripts.dist).toContain('npm run foundry:check');
    // And without the frozen Formulator, whose absence the data screen would
    // otherwise report as `Data Formulator binary is not installed`.
    expect(scripts.package).toContain('npm run formulator:check');
    expect(scripts.dist).toContain('npm run formulator:check');
    // And the gate, because `check` only asks whether files are present. A
    // bundle that serves pages and registers no locked-catalog connector passes
    // every file check there is.
    expect(scripts.package).toContain('npm run formulator:gate');
    expect(scripts.dist).toContain('npm run formulator:gate');
  });
});

describe('the freezing script', () => {
  it('ships the whole resources tree, not a data collection', () => {
    // PyInstaller's data collector skips `.py` files, and
    // `resources/formulator-plugin` holds nothing else. A bundle built with
    // `--collect-data foundry` comes out missing it, and then every command
    // fails at import -- including ones that never touch Formulator, because
    // `cli.py` resolves that path at module scope.
    // Scoped to the argv the script actually passes: the prose above it names
    // `--collect-data` in order to say why it is not used, and an assertion over
    // the whole file would forbid explaining that.
    const script = read('../scripts/build-foundry.mjs');
    const argv = script.slice(script.indexOf("'--noconfirm'"), script.indexOf('{ stdio:', script.indexOf("'--noconfirm'")));
    expect(argv).toContain("'--add-data'");
    expect(argv).not.toContain("'--collect-data'");
    expect(argv).toContain("'--collect-all'");
    expect(argv).toContain("'duckdb'");
  });

  it('runs the kit\'s own done-gate before calling it built', () => {
    // `probe` drives a whole fixture period through the library. A bundle that
    // imports but cannot read a workbook, open DuckDB or find its own fixtures
    // fails here rather than in front of an operator.
    const script = read('../scripts/build-foundry.mjs');
    expect(script).toContain("'probe'");
    expect(script).toContain("PATH: '/usr/bin:/bin'");
  });
});

describe('the Formulator freeze', () => {
  it('carries the kit, because a frozen app ignores PYTHONPATH', () => {
    // `DF_PLUGIN_DIR` names a loose `.py` that Data Formulator imports by path.
    // A frozen app can do that and still not satisfy the file's own `foundry`
    // imports from outside itself -- which produces a bundle that serves pages
    // and offers no locked-catalog connector, silently.
    const script = read('../scripts/build-formulator.mjs');
    const argv = script.slice(script.indexOf("'--noconfirm'"), script.indexOf('{ stdio:', script.indexOf("'--noconfirm'")));
    expect(argv).toContain("'foundry'");
    expect(argv).toContain("'duckdb'");
    expect(argv).toContain("'openpyxl'");
  });

  it('collects what is reached from strings rather than imported', () => {
    // The thirteen data loaders, litellm's provider configs, and tiktoken's
    // encoding plugin. None is visible to static analysis; each fails in its own
    // way and only one of them is loud.
    const script = read('../scripts/build-formulator.mjs');
    const argv = script.slice(script.indexOf("'--noconfirm'"), script.indexOf('{ stdio:', script.indexOf("'--noconfirm'")));
    expect(argv).toContain("'--collect-submodules',\n    'data_formulator'");
    expect(argv).toContain("'litellm'");
    expect(argv).toContain("'tiktoken_ext'");
  });

  it('puts freeze_support before the import, not after', () => {
    // The sandbox spawns worker processes and macOS re-executes this script in
    // the child. An import at module scope runs again there before
    // `freeze_support()` can say "you are the worker", and the app relaunches
    // itself instead of starting one.
    const script = read('../scripts/build-formulator.mjs');
    const shim = script.slice(script.indexOf('const entry ='), script.indexOf("console.log('freezing"));
    expect(shim.indexOf('freeze_support()')).toBeLessThan(shim.indexOf('from data_formulator.app import'));
  });

  it('has a gate that asks the server, not just the port', () => {
    // A bundle without the kit starts, serves, answers a health check and passes
    // the identity gate, and offers no locked-catalog connector at all.
    const gate = read('../scripts/gate-formulator.mjs');
    expect(gate).toContain('/api/data-loaders');
    expect(gate).toContain('locked_catalog');
    expect(gate).toContain("PATH: '/usr/bin:/bin'");
  });
});

describe('the staging script', () => {
  it('reads the pin rather than restating it', () => {
    const script = read('../scripts/fetch-harness.mjs');
    expect(script).toContain('kit.dsh.foundry.harness');
    expect(script).not.toContain(KIT.dsh.foundry.harness.version);
  });

  it('checks for the copy the loader needs, not only for the runtime', () => {
    // Two things have to be staged. A tree with the runtime and no bundle boots
    // and then dies with `Cannot find package`, which is the failure this whole
    // path exists to prevent.
    const script = read('../scripts/fetch-harness.mjs');
    expect(script).toContain("join(STAGE, harness.entry)");
    expect(script).toContain("join(STAGE, 'node_modules', kit.name, 'package.json')");
  });
});
