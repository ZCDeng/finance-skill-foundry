import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';

import { addToProfileManifest, assertStagedBundle, ensureProfileLink } from '../electron/harness/wiring.js';

const made: string[] = [];
afterEach(() => {
  for (const dir of made.splice(0)) rmSync(dir, { recursive: true, force: true });
});

function scratch(): string {
  const dir = mkdtempSync(join(tmpdir(), 'fnd-wiring-'));
  made.push(dir);
  return dir;
}

/** A profile directory shaped the way the runtime writes one. */
function profile(home: string, manifest: Record<string, unknown>): string {
  const dir = join(home, 'profiles', 'web');
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, 'package.json'), `${JSON.stringify(manifest, null, 2)}\n`);
  return join(dir, 'package.json');
}

function bundle(root: string, name = 'finance-skill-foundry-dsh'): string {
  const dir = join(root, 'dsh-plugin');
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, 'package.json'), JSON.stringify({ name, version: '0.1.0' }));
  return dir;
}

describe('naming the bundle in the profile manifest', () => {
  it('writes both keys the runtime reads', () => {
    // What `dsh plugin add` would have written. It is not used: that command
    // shells out to pnpm, and a machine without one gets `pnpm not found on
    // PATH`, which is every clean machine.
    const home = scratch();
    const manifestPath = profile(home, {
      name: 'dsh-profile-web',
      private: true,
      dsh: { profile: { bundles: ['@deepseek-ai/dsh-base', '@deepseek-ai/dsh-web-app'] } },
    });
    const pluginDir = bundle(home);
    addToProfileManifest({ home, pluginDir });

    const written = JSON.parse(readFileSync(manifestPath, 'utf8'));
    expect(written.dependencies['finance-skill-foundry-dsh']).toBe(`link:${pluginDir}`);
    expect(written.dsh.profile.bundles).toEqual([
      '@deepseek-ai/dsh-base',
      '@deepseek-ai/dsh-web-app',
      'finance-skill-foundry-dsh',
    ]);
  });

  it('appends rather than replaces, and repeats without growing', () => {
    // Another product's bundle in the same profile is not this app's to remove,
    // and this runs on every start.
    const home = scratch();
    const manifestPath = profile(home, {
      dsh: { profile: { bundles: ['@deepseek-ai/dsh-base', 'somebody-elses-bundle'] } },
    });
    const pluginDir = bundle(home);
    addToProfileManifest({ home, pluginDir });
    addToProfileManifest({ home, pluginDir });

    const written = JSON.parse(readFileSync(manifestPath, 'utf8'));
    expect(written.dsh.profile.bundles).toEqual([
      '@deepseek-ai/dsh-base',
      'somebody-elses-bundle',
      'finance-skill-foundry-dsh',
    ]);
  });

  it('starts a manifest that has no dsh block yet', () => {
    const home = scratch();
    const manifestPath = profile(home, { name: 'dsh-profile-web' });
    addToProfileManifest({ home, pluginDir: bundle(home) });
    expect(JSON.parse(readFileSync(manifestPath, 'utf8')).dsh.profile.bundles).toEqual([
      'finance-skill-foundry-dsh',
    ]);
  });
});

describe('the profile link', () => {
  it('is made once and left alone afterwards', () => {
    const home = scratch();
    profile(home, {});
    const pluginDir = bundle(home);
    const first = ensureProfileLink({ home, pluginDir });
    expect(readFileSync(join(first, 'package.json'), 'utf8')).toContain('finance-skill-foundry-dsh');
    expect(ensureProfileLink({ home, pluginDir })).toBe(first);
  });

  it('replaces a link left pointing at nothing', () => {
    // A moved checkout. A dangling link fails exactly the same way as a missing
    // one, and this runs on every start for that reason.
    const home = scratch();
    profile(home, {});
    const pluginDir = bundle(home);
    const target = ensureProfileLink({ home, pluginDir });
    rmSync(pluginDir, { recursive: true, force: true });
    bundle(home);
    expect(ensureProfileLink({ home, pluginDir })).toBe(target);
    expect(readFileSync(join(target, 'package.json'), 'utf8')).toContain('finance-skill-foundry-dsh');
  });
});

describe('the copy inside the runtime tree', () => {
  it('refuses by name when the staging step never ran', () => {
    // It cannot be created here: in a packed app that path is inside the
    // application bundle. The message has to say what to run instead.
    const home = scratch();
    expect(() => assertStagedBundle(join(home, 'nope'), bundle(home))).toThrow(/npm run harness/);
  });

  it('refuses when the staged copy is some other package', () => {
    const home = scratch();
    const staged = bundle(join(home, 'staged'), 'something-else');
    expect(() => assertStagedBundle(staged, bundle(home))).toThrow(/something-else/);
  });
});
