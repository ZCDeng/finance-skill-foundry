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
  const PUSHED = new Set(['harnessRefused', 'harnessExited']);

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

  it('keeps the read surface to the views it answers', () => {
    // A screen that wants something not in here needs a new read-only
    // subcommand, not a new way into the files. 总览 and 成果库 each read every
    // task in one process; the detail is one draft of one task.
    expect(Object.values(READS)).toEqual([
      'task-list', 'task-show', 'deliverables', 'analysis-deliverables', 'overview', 'library', 'library-detail',
    ]);
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
 * each revision chain, every filed export, 归档图, 写回 Excel copies and 收缴率
 * runs, in one order with one key space, from one `library` read.
 */
describe('the deliverables union', () => {
  const SECOND = '2026-09-27T03:00:00Z';
  const task = (key: string, title: string): TaskRow => ({
    id: key.repeat(32), title, period: '2026-08', skill_id: null, created_at: SECOND, windows: 1,
  });
  const A = task('a', '八月经营分析');
  const B = task('b', '回款跟进');
  const brief = (owner: TaskRow, seq: number, at = SECOND): GalleryRow => ({
    type: 'deliverable', key: `deliverable:${owner.id}:${seq}`, at, task: owner,
    row: { seq, kind: 'brief', window_id: 'w'.repeat(32), sha256: String(seq).repeat(64), bytes: 10,
      cause: 'emit-brief', session_id: null, at } satisfies DeliverableRow,
  });
  const draft = (at = SECOND): GalleryRow => ({
    type: 'draft', key: `draft:${'2'.repeat(32)}`, at, task: A,
    draft: { draft_id: '2'.repeat(32), revision: 2, versions: 2, title: '八月经营分析', created_at: at, seq: 2,
      review_status: 'accepted', publication_status: 'archived' },
  });
  const exported = (id: string, format: 'pdf' | 'docx'): GalleryRow => ({
    type: 'export', key: `export:${id.repeat(32)}`, at: SECOND, task: A,
    exported: { export_id: id.repeat(32), draft_id: '1'.repeat(32), revision: 1, title: '八月经营分析', format,
      content_mode: 'management', sha256: 'f'.repeat(64), created_at: SECOND,
      review_status: 'unreviewed', publication_status: 'draft', review_marker: '分析草稿·待复核' },
  });
  const chart: GalleryRow = { type: 'chart', key: `chart:${'9'.repeat(32)}`, at: SECOND, task: B,
    chart: { id: '9'.repeat(32), label: '归档图', run_id: null, created_at: SECOND, datasets: ['月结'] } };
  const library = (rows: GalleryRow[]) => mocks.run.mockImplementation(async (_binding, command) => {
    if (command === 'library') return JSON.stringify(rows);
    throw new Error(`unexpected ${command}`);
  });
  const described = (rows: GalleryRow[]) => rows.map((row) => row.key);
  beforeEach(() => { mocks.run.mockReset(); });

  it('orders a same-second brief, draft, export and chart the same way whatever order the store answers in', async () => {
    const rows = [brief(A, 1), brief(B, 1), draft(), exported('e', 'pdf'), exported('d', 'docx'), chart];
    library(rows);
    const first = await galleryRows({ varRoot: '/store' });
    library([...rows].reverse());
    const second = await galleryRows({ varRoot: '/store' });
    expect(described(second)).toEqual(described(first));
    // Keys are the kind and its own id, so a draft's seq 1 and two tasks' brief seq 1 never meet.
    expect(new Set(described(first)).size).toBe(first.length);
    expect(described(first)).toEqual([
      `export:${'d'.repeat(32)}`,
      `export:${'e'.repeat(32)}`,
      `draft:${'2'.repeat(32)}`,
      `chart:${'9'.repeat(32)}`,
      `deliverable:${A.id}:1`,
      `deliverable:${B.id}:1`,
    ]);
    expect(mocks.run.mock.calls.map((call) => call[1])).toEqual(['library', 'library']);
  });

  it('keeps newer rows first and the old flow\'s own seq rule inside a tie', async () => {
    library([brief(A, 1), { ...brief(A, 2) }, brief(A, 3, '2026-09-27T03:00:05Z'), draft('2026-09-27T03:00:02Z')]);
    expect(described(await galleryRows({ varRoot: '/store' }))).toEqual([
      `deliverable:${A.id}:3`, `draft:${'2'.repeat(32)}`, `deliverable:${A.id}:2`, `deliverable:${A.id}:1`,
    ]);
  });

  it('passes a failed read on rather than showing half a library', async () => {
    mocks.run.mockRejectedValue(new Error('store unreadable'));
    await expect(galleryRows({ varRoot: '/store' })).rejects.toThrow(/store unreadable/);
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
