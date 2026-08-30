import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import { HARNESS_ENTRY, entryPath, harnessRoot, pluginDir, stagedBundleDir } from '../electron/harness/resources.js';

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

  it('refuses to package without a staged runtime', () => {
    // Packaging without it produces an app whose workbench never starts and says
    // nothing about why, so the check runs first and stops.
    const scripts = JSON.parse(read('../package.json')).scripts;
    expect(scripts.package.startsWith('npm run harness:check')).toBe(true);
    expect(scripts.dist.startsWith('npm run harness:check')).toBe(true);
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
