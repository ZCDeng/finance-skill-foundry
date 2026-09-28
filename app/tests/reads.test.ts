import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ run: vi.fn() }));
// Only the exec is replaced; the argv, the JSON contract and every check on this side stay real.
vi.mock('../electron/foundry.js', async (original) => {
  const real = await original<typeof import('../electron/foundry.js')>();
  return {
    ...real,
    runFoundry: mocks.run,
    runFoundryJson: async (...args: unknown[]) => JSON.parse(await mocks.run(...args)),
  };
});

import {
  type AnalysisDeliverables,
  type DeliverableRow,
  type GalleryRow,
  type TaskRow,
  READS,
  analysisExportPath,
  galleryRows,
  listTasks,
} from '../electron/reads.js';
import { CHANNELS } from '../electron/ipc/contract.js';

const read = (rel: string) => readFileSync(fileURLToPath(new URL(rel, import.meta.url)), 'utf8');

describe('every data path is a CLI call', () => {
  it('reaches the store only through execFile', () => {
    // KTD2: `foundry/` is the sole mutator, and this app is a caller. A read of
    // `var/` from this process would be a second thing that knows the store
    // layout, and the two would agree until the day they did not.
    // The three that face the store. `harness/wiring.ts` uses `fs` to place a
    // link inside this app's own harness home, which is not the catalog.
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

  /**
   * The one channel main pushes on. Everything else is the renderer asking.
   *
   * Named here rather than inferred, so adding a second push channel has to be
   * a decision someone writes down instead of a handler quietly going missing.
   */
  const PUSHED = new Set(['harnessRefused']);

  it('gives every declared channel a handler', () => {
    // By key rather than by transforming the wire name: `harness:status` and
    // `harnessStatus` do not derive from each other, and a heuristic that
    // happened to work for the first four channels quietly stopped checking
    // anything when a fifth arrived.
    const register = read('../electron/ipc/register.ts');
    for (const key of Object.keys(CHANNELS)) {
      if (PUSHED.has(key)) continue;
      expect(register, key).toContain(`CHANNELS.${key}`);
    }
  });

  it('sends the pushed channel from main, where the fence lives', () => {
    // It has no `ipcMain.handle`, so the check above cannot see it. Without
    // this, a channel declared and never sent would pass the suite.
    const main = read('../electron/main.ts');
    for (const key of PUSHED) {
      expect(main, key).toContain(`CHANNELS.${key}`);
    }
  });

  it('keeps the read surface to the four views it answers', () => {
    // A screen that wants something not in here needs a new read-only
    // subcommand, not a new way into the files. The fourth is 成果库's analysis
    // half: drafts and filed exports live in the analysis store, not in
    // `deliverables`.
    expect(Object.values(READS)).toEqual(['task-list', 'task-show', 'deliverables', 'analysis-deliverables']);
  });

  it('filters task-list through the CLI lifecycle flag', async () => {
    mocks.run.mockResolvedValue('[]');
    await listTasks({ varRoot: '/store' });
    await listTasks({ varRoot: '/store' }, undefined, 'archived');
    expect(mocks.run.mock.calls.map((call) => [call[1], call[2]])).toEqual([
      ['task-list', []],
      ['task-list', ['--lifecycle', 'archived']],
    ]);
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

/*
 * 成果库 as one list (R10, KTD11): the old flow's versions, the newest draft of
 * each revision chain, and every filed export, in one order with one key space.
 */
describe('the deliverables union', () => {
  const SECOND = '2026-09-27T03:00:00Z';
  const task = (key: string, title: string): TaskRow => ({
    id: key.repeat(32), title, period: '2026-08', skill_id: null, created_at: SECOND, windows: 1,
  });
  const A = task('a', '八月经营分析');
  const B = task('b', '回款跟进');
  const brief = (seq: number): DeliverableRow => ({
    seq, kind: 'brief', window_id: 'w'.repeat(32), sha256: String(seq).repeat(64), bytes: 10,
    cause: 'emit-brief', session_id: null, at: SECOND,
  });
  // Draft v1 has seq 1, v2 seq 2; the listing carries only v2, and an export of v1.
  const analysis = (drafts: 'forward' | 'reverse'): AnalysisDeliverables => {
    const exports = [
      { export_id: 'e'.repeat(32), draft_id: '1'.repeat(32), revision: 1, title: '八月经营分析', format: 'pdf' as const,
        content_mode: 'management' as const, sha256: 'f'.repeat(64), created_at: SECOND,
        review_status: 'unreviewed', publication_status: 'draft', review_marker: '分析草稿·待复核' },
      { export_id: 'd'.repeat(32), draft_id: '1'.repeat(32), revision: 1, title: '八月经营分析', format: 'docx' as const,
        content_mode: 'audit' as const, sha256: 'c'.repeat(64), created_at: SECOND,
        review_status: 'unreviewed', publication_status: 'draft', review_marker: '分析草稿·待复核' },
    ];
    return {
      task_id: A.id,
      drafts: [{ draft_id: '2'.repeat(32), revision: 2, versions: 2, title: '八月经营分析', created_at: SECOND, seq: 2,
        review_status: 'accepted', publication_status: 'archived' }],
      exports: drafts === 'forward' ? exports : [...exports].reverse(),
    };
  };
  const store = (order: 'forward' | 'reverse') => mocks.run.mockImplementation(async (binding, command) => {
    if (command === 'task-list') return JSON.stringify(order === 'forward' ? [A, B] : [B, A]);
    // Both tasks' old flow filed seq 1 in the same second, and task A's draft v1 also has seq 1.
    if (command === 'deliverables') return JSON.stringify([brief(1)]);
    if (command === 'analysis-deliverables') {
      return JSON.stringify(binding.task === A.id ? analysis(order) : { task_id: B.id, drafts: [], exports: [] });
    }
    throw new Error(`unexpected ${command}`);
  });
  const described = (rows: GalleryRow[]) => rows.map((row) => row.key);
  beforeEach(() => { mocks.run.mockReset(); });

  it('orders a same-second brief, draft and export the same way whatever order the store answers in', async () => {
    store('forward');
    const first = await galleryRows({ varRoot: '/store' });
    store('reverse');
    const second = await galleryRows({ varRoot: '/store' });
    expect(described(second)).toEqual(described(first));
    // Keys are the kind and its own id, so a draft's seq 1 and two tasks' brief seq 1 never meet.
    expect(new Set(described(first)).size).toBe(first.length);
    expect(described(first)).toEqual([
      `export:${'d'.repeat(32)}`,
      `export:${'e'.repeat(32)}`,
      `draft:${'2'.repeat(32)}`,
      `deliverable:${A.id}:1`,
      `deliverable:${B.id}:1`,
    ]);
  });

  it('lists the draft chain once, at its newest version, with that version\'s own state', async () => {
    store('forward');
    const drafts = (await galleryRows({ varRoot: '/store' })).filter((row) => row.type === 'draft');
    expect(drafts).toHaveLength(1);
    const [only] = drafts;
    if (only.type !== 'draft') throw new Error('not a draft row');
    expect(only.task.id).toBe(A.id);
    expect([only.draft.revision, only.draft.review_status, only.draft.publication_status]).toEqual([2, 'accepted', 'archived']);
  });

  it('keeps archived task results in 成果库 and hides trashed task results', async () => {
    const archived = { ...A, lifecycle_status: 'archived' as const };
    const trashed = { ...B, lifecycle_status: 'trashed' as const };
    mocks.run.mockImplementation(async (binding, command, args) => {
      if (command === 'task-list') {
        expect(args).toEqual(['--lifecycle', 'all']);
        return JSON.stringify([archived, trashed]);
      }
      if (binding.task === trashed.id) throw new Error('trashed task should not be read');
      if (command === 'deliverables') return JSON.stringify([brief(1)]);
      return JSON.stringify({ task_id: archived.id, drafts: [], exports: [] });
    });
    expect(described(await galleryRows({ varRoot: '/store' }))).toEqual([`deliverable:${archived.id}:1`]);
  });

  it('keeps newer rows first and the old flow\'s own seq rule inside a tie', async () => {
    mocks.run.mockImplementation(async (_binding, command) => {
      if (command === 'task-list') return JSON.stringify([A]);
      if (command === 'deliverables') return JSON.stringify([brief(1), { ...brief(2), kind: 'workpaper' }, { ...brief(3), at: '2026-09-27T03:00:05Z' }]);
      return JSON.stringify({ task_id: A.id, drafts: [{ ...analysis('forward').drafts[0], created_at: '2026-09-27T03:00:02Z' }], exports: [] });
    });
    expect(described(await galleryRows({ varRoot: '/store' }))).toEqual([
      `deliverable:${A.id}:3`, `draft:${'2'.repeat(32)}`, `deliverable:${A.id}:2`, `deliverable:${A.id}:1`,
    ]);
  });

  it('reads tasks a few at a time, keeps their order, and stops starting reads after a failure', async () => {
    const tasks = Array.from({ length: 9 }, (_, index) => ({ ...A, id: `${index}`.repeat(32) }));
    let inFlight = 0;
    let most = 0;
    const started: string[] = [];
    mocks.run.mockImplementation(async (binding, command) => {
      if (command === 'task-list') return JSON.stringify(tasks);
      started.push(`${command}:${binding.task}`);
      inFlight += 1;
      most = Math.max(most, inFlight);
      await new Promise((resolve) => setTimeout(resolve, 5));
      inFlight -= 1;
      if (command === 'deliverables') return JSON.stringify([{ ...brief(1), at: `2026-09-27T03:00:0${binding.task[0]}Z` }]);
      return JSON.stringify({ task_id: binding.task, drafts: [], exports: [] });
    });
    const rows = await galleryRows({ varRoot: '/store' });
    expect(most).toBeGreaterThan(1);
    expect(most).toBeLessThanOrEqual(4);
    expect(started.slice(0, 9)).toEqual(tasks.map((task) => `deliverables:${task.id}`));
    expect(described(rows)).toEqual([...tasks].reverse().map((task) => `deliverable:${task.id}:1`));

    started.length = 0;
    mocks.run.mockImplementation(async (binding, command) => {
      if (command === 'task-list') return JSON.stringify(tasks);
      started.push(binding.task);
      if (binding.task === tasks[0].id) throw new Error('store unreadable');
      await new Promise((resolve) => setTimeout(resolve, 5));
      return JSON.stringify([]);
    });
    await expect(galleryRows({ varRoot: '/store' })).rejects.toThrow(/store unreadable/);
    expect(started.length).toBeLessThan(tasks.length);
  });

  it('resolves an export only from a digest and a known format, never from a path', async () => {
    mocks.run.mockResolvedValue(JSON.stringify({ path: '/store/tasks/a/analysis/exports/registered/x.pdf' }));
    const binding = { varRoot: '/store', task: A.id };
    await expect(analysisExportPath(binding, '../../etc/passwd', 'pdf')).rejects.toThrow(/not a sha256/);
    await expect(analysisExportPath(binding, 'f'.repeat(64), '.pdf')).rejects.toThrow(/not an export format/);
    await expect(analysisExportPath(binding, 'f'.repeat(64), 'pdf/../../x')).rejects.toThrow(/not an export format/);
    expect(mocks.run).not.toHaveBeenCalled();
    expect(await analysisExportPath(binding, 'f'.repeat(64), 'pdf')).toBe('/store/tasks/a/analysis/exports/registered/x.pdf');
    expect(mocks.run).toHaveBeenCalledWith(binding, 'analysis-export-path', ['--sha', 'f'.repeat(64), '--format', 'pdf'], undefined);
  });
});
