import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import { READS } from '../electron/reads.js';
import { CHANNELS } from '../electron/ipc/contract.js';

const read = (rel: string) => readFileSync(fileURLToPath(new URL(rel, import.meta.url)), 'utf8');

describe('every data path is a CLI call', () => {
  it('reaches the store only through execFile', () => {
    // KTD2: `foundry/` is the sole mutator, and this app is a caller. A read of
    // `var/` from this process would be a second thing that knows the store
    // layout, and the two would agree until the day they did not.
    const sources = ['../electron/foundry.ts', '../electron/reads.ts', '../electron/ipc/register.ts'];
    // Imports, not prose: these files talk about DuckDB and about not reading
    // `var/`, and an assertion that matched the word would forbid saying so.
    const imports = /(?:^|\n)\s*(?:import[^\n]*from\s*'([^']+)'|const[^\n]*=\s*require\('([^']+)'\))/g;
    const banned = /^(node:fs|node:fs\/promises|fs|duckdb)$/;
    for (const rel of sources) {
      for (const match of read(rel).matchAll(imports)) {
        const module = match[1] ?? match[2];
        expect(banned.test(module), `${rel} imports ${module}`).toBe(false);
      }
    }
    expect(read('../electron/foundry.ts')).toMatch(/execFile/);
  });

  it('answers every channel from the read surface', () => {
    // A screen that wants something not in READS needs a new read-only
    // subcommand, not a new way into the files.
    const register = read('../electron/ipc/register.ts');
    for (const channel of Object.values(CHANNELS)) {
      expect(register).toContain(channel.split(':')[1].replace(/-([a-z])/g, (_m, c) => c.toUpperCase()));
    }
    expect(Object.values(READS)).toEqual(['task-list', 'task-show', 'deliverables']);
  });

  it('holds the preload literals to the contract', () => {
    // A sandboxed preload cannot require a relative module, so the channel names
    // are written out there. This is what keeps the copy honest: a renamed
    // channel fails here instead of at runtime in a packaged build.
    const preload = read('../electron/preload.ts');
    for (const channel of Object.values(CHANNELS)) {
      expect(preload).toContain(`'${channel}'`);
    }
  });

  it('lets a renderer name a task and a digest, and nothing else', () => {
    // The widest thing a compromised renderer can ask for is a view of a task
    // that exists. Both guards are shape checks on this side of the bridge.
    expect(read('../electron/ipc/register.ts')).toMatch(/\^\[0-9a-f\]\{32\}\$/);
    expect(read('../electron/reads.ts')).toMatch(/\^\[0-9a-f\]\{64\}\$/);
  });
});
