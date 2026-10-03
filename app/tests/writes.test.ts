import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { WRITES } from '../electron/writes.js';
import { lineOf } from '../electron/ipc/register.js';

const read = (rel: string) => readFileSync(fileURLToPath(new URL(rel, import.meta.url)), 'utf8');

vi.mock('../electron/foundry.js', async (original) => ({
  ...(await original<typeof import('../electron/foundry.js')>()),
  runFoundry: vi.fn(),
}));

const { runFoundry } = await import('../electron/foundry.js');
const { changeTaskLifecycle, newTask, sampleTask } = await import('../electron/writes.js');
const called = runFoundry as unknown as ReturnType<typeof vi.fn>;

afterEach(() => called.mockReset());

const ID = 'a'.repeat(32);

describe('creating a task', () => {
  /*
   * The window shipped with ten IPC channels and every one of them was a read.
   * The empty task list told the operator to run `foundry task-new`, a CLI that
   * lives inside the application bundle. So on a machine that had only installed
   * the app there was no way to make the first task -- and with no task there is
   * no session, and with no session the harness view is attached, running, and
   * never given a rectangle. This channel is what makes the window usable from a
   * cold install.
   */
  it('is a mutation the window can make, and the only one', () => {
    expect(Object.values(WRITES)).toEqual(['task-new', 'task-archive', 'task-trash', 'task-restore', 'task-sample']);
  });

  it('passes the title through and leaves an empty period off the argv', async () => {
    called.mockResolvedValue(`${ID}\n`);
    await newTask({ varRoot: '/v' }, { title: '八月回款' });
    expect(called).toHaveBeenCalledWith(
      { varRoot: '/v' },
      'task-new',
      ['--title', '八月回款'],
      undefined,
    );
  });

  it('names the period when there is one', async () => {
    called.mockResolvedValue(ID);
    await newTask({ varRoot: '/v' }, { title: '八月回款', period: '2026-08' });
    expect(called).toHaveBeenCalledWith(
      { varRoot: '/v' },
      'task-new',
      ['--title', '八月回款', '--period', '2026-08'],
      undefined,
    );
  });

  it('hands back the id the CLI printed', async () => {
    called.mockResolvedValue(`${ID}\n`);
    expect(await newTask({ varRoot: '/v' }, { title: 'x' })).toEqual({ id: ID });
  });

  it('changes lifecycle through task-scoped CLI commands', async () => {
    called.mockResolvedValue(JSON.stringify({ task_id: ID, lifecycle_status: 'archived' }));
    await expect(changeTaskLifecycle({ varRoot: '/v', task: ID }, 'task-archive')).resolves.toEqual({ task_id: ID, lifecycle_status: 'archived' });
    expect(called).toHaveBeenCalledWith({ varRoot: '/v', task: ID }, 'task-archive', [], undefined);
  });

  it('refuses stdout that is not an id, rather than returning an empty one', async () => {
    // A blank line back is the CLI succeeding and writing nothing. Passing that
    // on would have the screen ask for a detail view of `''`, and the failure
    // would name the wrong thing.
    called.mockResolvedValue('\n');
    await expect(newTask({ varRoot: '/v' }, { title: 'x' })).rejects.toThrow(
      /did not print a task id/,
    );
  });

  it('goes through the CLI like every read does', () => {
    // KTD2: `foundry/` is the sole mutator. A write from this process that
    // opened the catalog would be the second thing that knows the store layout.
    const source = read('../electron/writes.ts');
    for (const match of source.matchAll(/(?:^|\n)\s*import[^\n]*from\s*'([^']+)'/g)) {
      expect(/^(node:fs|node:fs\/promises|fs|duckdb)$/.test(match[1]), match[1]).toBe(false);
    }
  });
});

describe('what a typed line may contain', () => {
  it('trims, because a trailing space is not part of a name', () => {
    expect(lineOf('  八月回款 ', 'title', 120)).toBe('八月回款');
  });

  it('refuses a blank one', () => {
    expect(() => lineOf('   ', 'title', 120)).toThrow(/title is empty/);
    expect(() => lineOf(undefined, 'title', 120)).toThrow(/title is empty/);
  });

  it('refuses one that is too long', () => {
    expect(() => lineOf('x'.repeat(121), 'title', 120)).toThrow(/longer than 120/);
    expect(lineOf('x'.repeat(120), 'title', 120)).toHaveLength(120);
  });

  it('refuses a control character, which would land in every log line after', () => {
    // Not a quoting defence -- these reach execFile as an argument array, so a
    // quote or a semicolon is one more character in a title. A newline is not:
    // it would split one stored name across two lines of every log and every
    // screen that ever prints it back.
    expect(() => lineOf('a\nb', 'title', 120)).toThrow(/control character/);
    expect(() => lineOf('a\u0000b', 'title', 120)).toThrow(/control character/);
    expect(() => lineOf('a\u001bb', 'title', 120)).toThrow(/control character/);
    expect(() => lineOf('a\u007fb', 'title', 120)).toThrow(/control character/);
    // Punctuation is not a control character and must survive: a title is prose.
    expect(lineOf('a; rm -rf / b', 'title', 120)).toBe('a; rm -rf / b');
  });
});

describe('the practice task', () => {
  it('names no arguments and hands back the id the CLI printed', async () => {
    called.mockResolvedValue(JSON.stringify({ id: ID, created: true }));
    expect(await sampleTask({ varRoot: '/v' })).toEqual({ id: ID, created: true });
    expect(called).toHaveBeenCalledWith({ varRoot: '/v' }, 'task-sample', [], undefined);
  });

  it('refuses an answer without a task id', async () => {
    called.mockResolvedValue(JSON.stringify({ id: '../x' }));
    await expect(sampleTask({ varRoot: '/v' })).rejects.toThrow(/task id/);
  });
});
