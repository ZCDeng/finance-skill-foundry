// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('pdfjs-dist', () => ({ GlobalWorkerOptions: { workerSrc: '' }, getDocument: vi.fn() }));

import { App } from '../src/App.js';
import type {
  AnalysisDraft,
  AnalysisDraftRow,
  AnalysisExportRow,
  AnalysisState,
  Answer,
  Bridge,
  DeliverableRow,
  GalleryRow,
  TaskRow,
} from '../src/bridge.js';
import { Deliverables } from '../src/views/Deliverables.js';

/*
 * 成果库 as one list (R10, KTD11): the old flow's versions, the newest draft of
 * each revision chain and every filed export, each with the state it already
 * has and its own way to open.
 */

const SECOND = '2026-09-27T03:00:00Z';
const task = (key: string, title: string): TaskRow => ({
  id: key.repeat(32), title, period: '2026-08', skill_id: null, created_at: SECOND, windows: 1,
});
const A = task('a', '八月经营分析');
const B = task('b', '西南回款');
// Seq 2 on both the old-flow brief and the draft: the old key `${task}-${seq}` would collide.
const brief: DeliverableRow = {
  seq: 2, kind: 'brief', window_id: 'w'.repeat(32), sha256: '1'.repeat(64), bytes: 10,
  cause: 'emit-brief', session_id: null, at: SECOND,
};
const v2: AnalysisDraftRow = {
  draft_id: '2'.repeat(32), revision: 2, versions: 2, title: '八月利润说明', created_at: SECOND, seq: 2,
  review_status: 'accepted', publication_status: 'archived',
};
const pdfOfV1: AnalysisExportRow = {
  export_id: 'e'.repeat(32), draft_id: '1'.repeat(32), revision: 1, title: '八月利润说明', format: 'pdf',
  content_mode: 'management', sha256: 'f'.repeat(64), created_at: SECOND,
  review_status: 'unreviewed', publication_status: 'draft', review_marker: '分析草稿·待复核',
};
const htmlOfV2: AnalysisExportRow = {
  ...pdfOfV1, export_id: 'd'.repeat(32), draft_id: v2.draft_id, revision: 2, format: 'html', sha256: 'c'.repeat(64),
  review_status: 'accepted', publication_status: 'archived', review_marker: '',
};
const ROWS: GalleryRow[] = [
  { type: 'export', key: `export:${pdfOfV1.export_id}`, at: SECOND, task: A, exported: pdfOfV1 },
  { type: 'export', key: `export:${htmlOfV2.export_id}`, at: SECOND, task: A, exported: htmlOfV2 },
  { type: 'draft', key: `draft:${v2.draft_id}`, at: SECOND, task: A, draft: v2 },
  { type: 'deliverable', key: `deliverable:${A.id}:2`, at: SECOND, task: A, row: brief },
];
const LIST = { open: null, onOpenWorkbook: () => {}, busy: null, onBack: () => {} };

afterEach(() => {
  cleanup();
  delete (globalThis as unknown as { foundry?: Bridge }).foundry;
  sessionStorage.clear();
  vi.restoreAllMocks();
});

/** The 状态 cell of the row whose open button carries `label`. */
function statusOf(label: RegExp): HTMLElement {
  const header = screen.getAllByRole('columnheader').map((cell) => cell.textContent);
  const row = screen.getByRole('button', { name: label }).closest('tr')!;
  return within(row).getAllByRole('cell')[header.indexOf('状态')];
}

describe('the 成果库 list', () => {
  it('shows each row the state it already has, and only a dash for the old flow', () => {
    render(<Deliverables rows={ROWS} {...LIST} onOpen={() => {}} onExport={() => {}} />);
    expect(statusOf(/结论稿/).textContent).toBe('—');
    expect(statusOf(/文稿 修订 2/).textContent).toBe('已归档 · 经理认可');
    // v1's own state, and the review stamp because v1 is neither accepted nor archived.
    const ofV1 = statusOf(/PDF 导出件/);
    expect(ofV1.textContent).toContain('分析草稿·待复核');
    expect(ofV1.textContent).toContain('草稿 · 未阅');
    const ofV2 = statusOf(/HTML 导出件/);
    expect(ofV2.textContent).toBe('已归档 · 经理认可');
  });

  it('gives every row its own key even when a draft and an old version share a seq', () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(<Deliverables rows={ROWS} {...LIST} onOpen={() => {}} onExport={() => {}} />);
    expect(error.mock.calls.flat().join(' ')).not.toMatch(/same key/);
    expect(screen.getAllByRole('row')).toHaveLength(ROWS.length + 1);
  });

  it('opens a draft, an export and an old version each its own way', () => {
    const onOpen = vi.fn(), onOpenDraft = vi.fn(), onOpenExport = vi.fn();
    render(<Deliverables rows={ROWS} {...LIST} onOpen={onOpen} onExport={() => {}} onOpenDraft={onOpenDraft} onOpenExport={onOpenExport} />);
    fireEvent.click(screen.getByRole('button', { name: /文稿 修订 2/ }));
    fireEvent.click(screen.getByRole('button', { name: /PDF 导出件/ }));
    fireEvent.click(screen.getByRole('button', { name: /结论稿/ }));
    expect(onOpenDraft).toHaveBeenCalledWith(A, v2);
    expect(onOpenExport).toHaveBeenCalledWith(A, pdfOfV1);
    expect(onOpen).toHaveBeenCalledWith(A, brief);
  });

  it('keeps the old flow\'s reader and Excel export', () => {
    const onExport = vi.fn();
    render(<Deliverables rows={ROWS} {...LIST} open={{ task: A, row: brief, text: '# 本期结论稿' }} onOpen={() => {}} onExport={onExport} />);
    expect(screen.getByText('本期结论稿')).toBeTruthy();
    const technical = screen.getByText('技术信息').closest('details') as HTMLDetailsElement;
    expect(technical.open).toBe(false);
    expect(screen.queryByText('111111111111')).toBeNull();
    fireEvent.click(screen.getByText('技术信息'));
    expect(within(technical).getByText(brief.sha256)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /导出 Excel/ }));
    expect(onExport).toHaveBeenCalledWith(A, brief.window_id);
  });
});

/*
 * Through the app, with the real analysis screen: a draft row lands on that
 * task's 文稿 tab with that version selected, even when it is not the task's
 * newest draft and even when the task is the one already open.
 */
describe('opening 成果库 rows in the app', () => {
  const ok = <T,>(value: T): Answer<T> => ({ ok: true, value });
  const draft = (owner: TaskRow, id: string, title: string, parent: string | null = null): AnalysisDraft => ({
    id, task_id: owner.id, schema_version: 1, created_at: SECOND, title, body: `${title}正文。`,
    run_ids: [], claims: [], publication_status: 'draft', review_status: 'unreviewed', limitations: [], parent_id: parent,
  });
  // Per task: chain one is v1 then v2, chain two is a single, newer draft. The list shows v2.
  const stateOf = (owner: TaskRow): AnalysisState => {
    const [first, second, other] = [0, 1, 2].map((n) => String((owner.id === A.id ? 4 : 7) + n).repeat(32));
    return {
      task_id: owner.id, datasets: [], analyses: [], runs: [], methods: [],
      drafts: [
        draft(owner, first, `${owner.title}初稿`),
        draft(owner, second, `${owner.title}修订稿`, first),
        draft(owner, other, `${owner.title}另一份`),
      ],
    };
  };
  const secondOf = (owner: TaskRow): AnalysisDraftRow => {
    const second = stateOf(owner).drafts[1];
    return { draft_id: second.id, revision: 2, versions: 2, title: second.title, created_at: SECOND, seq: 2,
      review_status: 'unreviewed', publication_status: 'draft' };
  };
  const gallery: GalleryRow[] = [
    { type: 'export', key: `export:${pdfOfV1.export_id}`, at: SECOND, task: A, exported: pdfOfV1 },
    { type: 'draft', key: `draft:${secondOf(B).draft_id}`, at: SECOND, task: B, draft: secondOf(B) },
    { type: 'draft', key: `draft:${secondOf(A).draft_id}`, at: SECOND, task: A, draft: secondOf(A) },
    { type: 'deliverable', key: `deliverable:${A.id}:2`, at: SECOND, task: A, row: brief },
  ];
  function mount() {
    const api = {
      // The last task is bound on start, so A is the task already open.
      tasks: vi.fn(async () => ok([B, A])),
      task: vi.fn(async (id: string) => ok({ task: id === A.id ? A : B, windows: [], sessions: [], deliverables: [] })),
      gallery: vi.fn(async () => ok(gallery)),
      analysisState: vi.fn(async (id: string) => ok(stateOf(id === A.id ? A : B))),
      analysisExportOpen: vi.fn(async () => ok({ opened: '/filed/report.pdf' })),
      exportWorkbook: vi.fn(async () => ok({ sha256: '3'.repeat(64), seq: 3, ext: '.xlsx' })),
      deliverableText: vi.fn(async () => ok('# 本期结论稿')),
      deliverableOpen: vi.fn(async () => ok({ opened: 'archived.xlsx' })),
      harnessStatus: vi.fn(async () => ok({ wiring: { state: 'ready' as const }, consequence: null, origin: 'http://localhost:1' })),
      harnessOpen: vi.fn<NonNullable<Bridge['harnessOpen']>>(async (_intent, id) => ok({ sessionId: `session-${id}`, preset: 'analysis' })),
      paneVisible: vi.fn(async (value: string) => ok({ screen: value })),
    } satisfies Partial<Bridge>;
    (globalThis as unknown as { foundry: Partial<Bridge> }).foundry = api;
    render(<App />);
    return api;
  }
  async function openLibrary() {
    fireEvent.click(await screen.findByRole('button', { name: '成果库' }));
    return screen.findByRole('button', { name: new RegExp(`${B.title} 的文稿 修订 2`) });
  }
  async function selectedVersion() {
    const picker = await screen.findByRole('button', { name: '文稿版本' });
    // The trigger reads 修订 N, with · 最新 when N is the task's newest draft.
    await waitFor(() => expect(picker.textContent).toMatch(/修订 \d/));
    return picker;
  }

  it('opens a draft of another task on its 文稿 tab with that version selected', async () => {
    mount();
    await screen.findByRole('heading', { name: A.title });
    fireEvent.click(await openLibrary());
    await screen.findByRole('heading', { name: B.title });
    expect(screen.getByRole('tab', { name: /文稿/ }).getAttribute('aria-selected')).toBe('true');
    const picker = await selectedVersion();
    await waitFor(() => expect(picker.textContent).toMatch(/修订 2$/));
    expect(picker.getAttribute('title')).toContain(secondOf(B).title);
  });

  it('opens an archived task draft from 成果库 in the archived task view without starting chat', async () => {
    const archivedB = { ...B, lifecycle_status: 'archived' as const };
    const archivedGallery: GalleryRow[] = [{ type: 'draft', key: `draft:${secondOf(archivedB).draft_id}`, at: SECOND, task: archivedB, draft: secondOf(archivedB) }];
    const api = {
      tasks: vi.fn(async (view?: string) => ok(view === 'archived' ? [archivedB] : [A])),
      task: vi.fn(async (id: string) => ok({ task: id === A.id ? A : archivedB, windows: [], sessions: [], deliverables: [] })),
      gallery: vi.fn(async () => ok(archivedGallery)),
      analysisState: vi.fn(async (id: string) => ok(stateOf(id === A.id ? A : archivedB))),
      harnessStatus: vi.fn(async () => ok({ wiring: { state: 'ready' as const }, consequence: null, origin: 'http://localhost:1' })),
      harnessOpen: vi.fn<NonNullable<Bridge['harnessOpen']>>(async (_intent, id) => ok({ sessionId: `session-${id}`, preset: 'analysis' })),
      paneVisible: vi.fn(async (value: string) => ok({ screen: value })),
    } satisfies Partial<Bridge>;
    (globalThis as unknown as { foundry: Partial<Bridge> }).foundry = api;
    render(<App />);
    await screen.findByRole('heading', { name: A.title });
    fireEvent.click(await screen.findByRole('button', { name: '成果库' }));
    fireEvent.click(await screen.findByRole('button', { name: new RegExp(`${B.title} 的文稿 修订 2`) }));
    await screen.findByRole('heading', { name: B.title });
    fireEvent.click(screen.getByRole('button', { name: '展开任务列表' }));
    expect(screen.getByRole('button', { name: '已归档' }).getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByText('任务已停用编辑')).toBeTruthy();
    expect(screen.getByRole('button', { name: '恢复任务' })).toBeTruthy();
    expect(api.tasks).toHaveBeenCalledWith('archived');
    expect(api.harnessOpen.mock.calls.map(([, id]) => id)).toEqual([A.id]);
  });

  it('opens a draft of the task already open with that version, not its newest', async () => {
    const api = mount();
    await screen.findByRole('heading', { name: A.title });
    await waitFor(() => expect(api.harnessOpen).toHaveBeenCalledTimes(1));
    await openLibrary();
    fireEvent.click(screen.getByRole('button', { name: new RegExp(`${A.title} 的文稿 修订 2`) }));
    expect(screen.getByRole('tab', { name: /文稿/ }).getAttribute('aria-selected')).toBe('true');
    const picker = await selectedVersion();
    await waitFor(() => expect(picker.textContent).toMatch(/修订 2$/));
    expect(picker.getAttribute('title')).toContain(secondOf(A).title);
    expect(screen.getByRole('heading', { name: A.title })).toBeTruthy();
    // Coming back to the workspace resumes A's own conversation, as any screen switch does; no other task is bound.
    expect(api.harnessOpen.mock.calls.every(([, id]) => id === A.id)).toBe(true);
  });

  it('hands an export to the default program by task, digest and format', async () => {
    const api = mount();
    await screen.findByRole('heading', { name: A.title });
    await openLibrary();
    fireEvent.click(screen.getByRole('button', { name: /PDF 导出件/ }));
    await waitFor(() => expect(api.analysisExportOpen).toHaveBeenCalledWith(A.id, pdfOfV1.sha256, 'pdf'));
  });

  it('still reads an old-flow version and exports it to Excel', async () => {
    const api = mount();
    await screen.findByRole('heading', { name: A.title });
    await openLibrary();
    fireEvent.click(screen.getByRole('button', { name: /结论稿/ }));
    expect(await screen.findByText('本期结论稿')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /导出 Excel/ }));
    await waitFor(() => expect(api.exportWorkbook).toHaveBeenCalledWith(A.id, brief.window_id));
  });
});
