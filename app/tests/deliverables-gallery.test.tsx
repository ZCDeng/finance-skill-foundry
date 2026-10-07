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
import { EXPORT_MENU_FORMATS } from '../src/views/analysis/ReportEditor.js';
import { when } from '../src/bridge.js';

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
  it('writes each revision\'s state once, and only a dash for the old flow', () => {
    render(<Deliverables rows={ROWS} {...LIST} onOpen={() => {}} onExport={() => {}} />);
    expect(statusOf(/结论稿/).textContent).toBe('—');
    // v2's draft and its HTML export are one row, so they share one 状态 cell.
    expect(statusOf(/文稿 修订 2/)).toBe(statusOf(/HTML 导出件/));
    expect(statusOf(/文稿 修订 2/).textContent).toBe('已归档 · 经理认可');
    // v1 only has an export; its state is v1's own, written once.
    expect(statusOf(/PDF 导出件/).textContent).toBe('草稿 · 未阅');
    // The review stamp the file carries stays visible in the row and in the button's name.
    const pdf = screen.getByRole('button', { name: /PDF 导出件/ });
    expect(pdf.closest('tr')!.textContent).toContain('导出件带「分析草稿·待复核」标记');
    expect(pdf.textContent).toContain('分析草稿·待复核');
  });

  it('gives every row its own key even when a draft and an old version share a seq', () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(<Deliverables rows={ROWS} {...LIST} onOpen={() => {}} onExport={() => {}} />);
    expect(error.mock.calls.flat().join(' ')).not.toMatch(/same key/);
    const bodies = document.querySelectorAll('tbody');
    expect(bodies).toHaveLength(1);
    const [head, ...lines] = within(bodies[0] as HTMLElement).getAllByRole('row');
    expect(head.textContent).toContain('八月经营分析');
    // In the order the rows first appear: revision 1 that only has an export, revision 2 with its HTML,
    // and the old-flow brief.
    expect(lines).toHaveLength(3);
    expect(within(lines[0]).getByRole('button', { name: /PDF 导出件/ })).toBeTruthy();
    expect(within(lines[1]).getByRole('button', { name: /文稿 修订 2/ })).toBeTruthy();
    expect(within(lines[1]).getByRole('button', { name: /HTML 导出件/ })).toBeTruthy();
    expect(within(lines[2]).getByRole('button', { name: /结论稿/ })).toBeTruthy();
  });

  it('names each task once, in its group heading, and orders groups by their newest row', () => {
    const LATER = '2026-09-28T03:00:00Z';
    const ofB: AnalysisDraftRow = { ...v2, draft_id: '9'.repeat(32), revision: 1, title: '西南回款说明' };
    const rows: GalleryRow[] = [
      { type: 'draft', key: `draft:${ofB.draft_id}`, at: LATER, task: B, draft: ofB },
      { type: 'draft', key: `draft:${v2.draft_id}`, at: SECOND, task: A, draft: v2 },
      { type: 'export', key: `export:${pdfOfV1.export_id}`, at: SECOND, task: A, exported: pdfOfV1 },
      { type: 'deliverable', key: `deliverable:${B.id}:2`, at: SECOND, task: B, row: brief },
      { type: 'deliverable', key: `deliverable:${A.id}:2`, at: SECOND, task: A, row: brief },
    ];
    render(<Deliverables rows={rows} {...LIST} onOpen={() => {}} onExport={() => {}} />);
    const named = screen.getAllByText(A.title);
    expect(named).toHaveLength(1);
    expect(named[0].closest("th[scope='rowgroup']")).toBeTruthy();
    const groups = [...document.querySelectorAll("th[scope='rowgroup']")].map((cell) => cell.firstElementChild!.textContent);
    expect(groups).toEqual([B.title, A.title]);
  });

  it('lays a revision\'s exports out as chips, 管理版 and 审计版 apart', () => {
    const onOpenExport = vi.fn();
    const docx: AnalysisExportRow = { ...htmlOfV2, export_id: '5'.repeat(32), format: 'docx', sha256: '5'.repeat(64) };
    const pdf: AnalysisExportRow = { ...htmlOfV2, export_id: '6'.repeat(32), format: 'pdf', sha256: '6'.repeat(64) };
    const auditPdf: AnalysisExportRow = { ...pdf, export_id: '7'.repeat(32), content_mode: 'audit', sha256: '7'.repeat(64) };
    const rows: GalleryRow[] = [
      { type: 'export', key: `export:${auditPdf.export_id}`, at: SECOND, task: A, exported: auditPdf },
      { type: 'export', key: `export:${pdf.export_id}`, at: SECOND, task: A, exported: pdf },
      { type: 'export', key: `export:${docx.export_id}`, at: SECOND, task: A, exported: docx },
      { type: 'draft', key: `draft:${v2.draft_id}`, at: SECOND, task: A, draft: v2 },
    ];
    render(<Deliverables rows={rows} {...LIST} onOpen={() => {}} onExport={() => {}} onOpenExport={onOpenExport} />);
    const row = screen.getByRole('button', { name: /文稿 修订 2/ }).closest('tr')!;
    expect(within(row).getByText('管理版')).toBeTruthy();
    expect(within(row).getByText('审计版')).toBeTruthy();
    const audit = within(row).getByRole('button', { name: /^PDF 导出件（修订 2 · 审计版 · / });
    expect(audit.getAttribute('data-size')).toBe('chip');
    expect(audit.hasAttribute('aria-pressed')).toBe(false);
    fireEvent.click(audit);
    expect(onOpenExport).toHaveBeenCalledWith(A, auditPdf);
  });

  it('writes the period once, in words, in the group heading', () => {
    const undated = { ...B, period: null };
    const rows: GalleryRow[] = [
      { type: 'draft', key: `draft:${v2.draft_id}`, at: SECOND, task: A, draft: v2 },
      { type: 'deliverable', key: `deliverable:${B.id}:2`, at: SECOND, task: undated, row: brief },
    ];
    render(<Deliverables rows={rows} {...LIST} onOpen={() => {}} onExport={() => {}} />);
    expect(screen.queryByRole('columnheader', { name: '期间' })).toBeNull();
    const [dated, plain] = [...document.querySelectorAll("th[scope='rowgroup']")];
    expect(dated.querySelector('.fnd-muted')!.textContent).toBe(' · 2026 年 8 月');
    expect(plain.querySelector('.fnd-muted')).toBeNull();
    expect(plain.textContent).toBe(B.title);
  });

  it('searches by task name and says what it found', () => {
    const rows: GalleryRow[] = [
      ...ROWS,
      { type: 'deliverable', key: `deliverable:${B.id}:2`, at: SECOND, task: B, row: brief },
    ];
    render(<Deliverables rows={rows} {...LIST} onOpen={() => {}} onExport={() => {}} />);
    const status = screen.getByRole('status');
    expect(status.textContent).toBe('');
    const search = screen.getByRole('searchbox', { name: '按任务名搜索' });
    fireEvent.change(search, { target: { value: '西南' } });
    const groups = [...document.querySelectorAll("th[scope='rowgroup']")].map((cell) => cell.firstElementChild!.textContent);
    expect(groups).toEqual([B.title]);
    expect(status.textContent).toBe('找到 1 个任务');
    fireEvent.change(search, { target: { value: '不存在' } });
    expect(screen.queryByRole('table')).toBeNull();
    expect(status.textContent).toBe('没有名称包含「不存在」的任务');
    expect(screen.getByText('没有名称包含「不存在」的任务', { selector: 'p' })).toBeTruthy();
  });

  it('titles the screen 成果库 whether or not there is anything in it', () => {
    render(<Deliverables rows={ROWS} {...LIST} onOpen={() => {}} onExport={() => {}} />);
    expect(screen.getByRole('heading', { level: 1, name: '成果库' })).toBeTruthy();
    cleanup();
    render(<Deliverables rows={[]} {...LIST} onOpen={() => {}} onExport={() => {}} />);
    expect(screen.getByRole('heading', { level: 1, name: '成果库' })).toBeTruthy();
    expect(screen.getByText('还没有产出物。出一次稿就会有第一版。')).toBeTruthy();
  });

  it('heads the columns 来源文稿, 状态, 导出件, 最近更新, each scoped to its column', () => {
    render(<Deliverables rows={ROWS} {...LIST} onOpen={() => {}} onExport={() => {}} />);
    const headers = screen.getAllByRole('columnheader');
    expect(headers.map((cell) => cell.textContent)).toEqual(['来源文稿', '状态', '导出件', '最近更新']);
    for (const cell of headers) expect(cell.getAttribute('scope')).toBe('col');
  });

  it('writes 最近更新 as plain text, and keeps the table a focusable region', () => {
    render(<Deliverables rows={ROWS} {...LIST} onOpen={() => {}} onExport={() => {}} />);
    const header = screen.getAllByRole('columnheader').map((cell) => cell.textContent);
    for (const row of [...document.querySelectorAll('tbody tr')].filter((tr) => !tr.querySelector("th[scope='rowgroup']"))) {
      const cell = within(row as HTMLElement).getAllByRole('cell')[header.indexOf('最近更新')];
      expect(cell.textContent).not.toBe('');
      expect(within(cell).queryByRole('button')).toBeNull();
    }
    const region = screen.getByRole('region', { name: '成果库' });
    expect(region.getAttribute('tabindex')).toBe('0');
    expect(region.classList.contains('fnd-tablewrap')).toBe(true);
  });

  it('tells two exports of one format apart by time, leaving the newest bare', () => {
    const EARLIER = '2026-09-26T03:00:00Z';
    const older: AnalysisExportRow = { ...htmlOfV2, export_id: '8'.repeat(32), sha256: '8'.repeat(64), created_at: EARLIER };
    const rows: GalleryRow[] = [
      { type: 'export', key: `export:${htmlOfV2.export_id}`, at: SECOND, task: A, exported: htmlOfV2 },
      { type: 'draft', key: `draft:${v2.draft_id}`, at: SECOND, task: A, draft: v2 },
      { type: 'export', key: `export:${older.export_id}`, at: EARLIER, task: A, exported: older },
    ];
    render(<Deliverables rows={rows} {...LIST} onOpen={() => {}} onExport={() => {}} />);
    const chips = screen.getAllByRole('button', { name: /^HTML/ });
    expect(chips).toHaveLength(2);
    expect(chips[0].firstChild!.textContent).toBe('HTML');
    expect(chips[1].firstChild!.textContent).toBe(`HTML · ${when(EARLIER)}`);
    expect(new Set(chips.map((chip) => chip.textContent)).size).toBe(2);
  });

  it('adds seconds, then a count, when exports of one format share a minute', () => {
    const at = (time: string) => `2026-09-26T03:00:${time}Z`;
    const copy = (n: string, created_at: string): AnalysisExportRow => ({ ...htmlOfV2, export_id: n.repeat(32), sha256: n.repeat(64), created_at });
    const files = [copy('1', at('50')), copy('2', at('30')), copy('3', at('10'))];
    const rows: GalleryRow[] = files.map((exported) => ({ type: 'export', key: `export:${exported.export_id}`, at: exported.created_at, task: A, exported }));
    render(<Deliverables rows={rows} {...LIST} onOpen={() => {}} onExport={() => {}} />);
    const shown = screen.getAllByRole('button', { name: /^HTML/ }).map((chip) => chip.firstChild!.textContent);
    expect(shown).toEqual(['HTML', `HTML · ${when(at('30'))}:30`, `HTML · ${when(at('10'))}:10`]);
    cleanup();
    const twins = [copy('1', at('50')), copy('2', at('10')), copy('3', at('10'))];
    render(<Deliverables rows={twins.map((exported) => ({ type: 'export', key: `export:${exported.export_id}`, at: exported.created_at, task: A, exported }))} {...LIST} onOpen={() => {}} onExport={() => {}} />);
    const counted = screen.getAllByRole('button', { name: /^HTML/ }).map((chip) => chip.firstChild!.textContent);
    expect(counted).toEqual(['HTML', 'HTML · 第 2 份', 'HTML · 第 1 份']);
  });

  it('starts every button\'s name with what it shows and carries the file\'s own time', () => {
    render(<Deliverables rows={ROWS} {...LIST} onOpen={() => {}} onExport={() => {}} />);
    const draft = screen.getByRole('button', { name: /文稿 修订 2/ });
    expect(draft.getAttribute('aria-label')).toBeNull();
    expect(draft.textContent!.startsWith('八月利润说明 · 修订 2')).toBe(true);
    expect(draft.textContent).toContain(when(v2.created_at));
    const pdf = screen.getByRole('button', { name: /PDF 导出件/ });
    expect(pdf.getAttribute('aria-label')).toBeNull();
    expect(pdf.textContent!.startsWith('PDF')).toBe(true);
    expect(pdf.textContent).toContain(when(pdfOfV1.created_at));
    const old = screen.getByRole('button', { name: /结论稿/ });
    expect(old.getAttribute('aria-label')).toBeNull();
    expect(old.textContent!.startsWith('结论稿 第 2 版')).toBe(true);
    expect(old.textContent).toContain(`打开 ${A.title} 的结论稿 第 2 版`);
  });

  it('puts an export with no named version kind in an 其他 row, and leaves revision rows without a hover fill', () => {
    const plain: AnalysisExportRow = { ...htmlOfV2, export_id: '5'.repeat(32), sha256: '5'.repeat(64), content_mode: null };
    const odd = { ...htmlOfV2, export_id: '6'.repeat(32), sha256: '6'.repeat(64), format: 'pdf', content_mode: 'board' } as unknown as AnalysisExportRow;
    const rows: GalleryRow[] = [
      { type: 'export', key: `export:${plain.export_id}`, at: SECOND, task: A, exported: plain },
      { type: 'export', key: `export:${odd.export_id}`, at: SECOND, task: A, exported: odd },
      { type: 'draft', key: `draft:${v2.draft_id}`, at: SECOND, task: A, draft: v2 },
    ];
    render(<Deliverables rows={rows} {...LIST} onOpen={() => {}} onExport={() => {}} />);
    const row = screen.getByRole('button', { name: /文稿 修订 2/ }).closest('tr')!;
    expect(within(row).getAllByText('其他')).toHaveLength(1);
    expect([...row.querySelectorAll('.fnd-library__chips')].map((chips) => chips.children.length)).toEqual([2]);
    expect(row.classList.contains('fnd-table__open')).toBe(false);
  });

  it('keeps the search when a version is opened and closed again', () => {
    const props = { rows: ROWS, ...LIST, onOpen: () => {}, onExport: () => {} };
    const { rerender } = render(<Deliverables {...props} />);
    fireEvent.change(screen.getByRole('searchbox', { name: '按任务名搜索' }), { target: { value: '八月' } });
    rerender(<Deliverables {...props} open={{ task: A, row: brief, text: '# 本期结论稿' }} />);
    expect(screen.queryByRole('searchbox')).toBeNull();
    rerender(<Deliverables {...props} />);
    expect((screen.getByRole('searchbox', { name: '按任务名搜索' }) as HTMLInputElement).value).toBe('八月');
  });

  it('goes back to 成果库 by name and shows the opened version\'s period in words', () => {
    render(<Deliverables rows={ROWS} {...LIST} open={{ task: A, row: brief, text: '# 本期结论稿' }} onOpen={() => {}} onExport={() => {}} />);
    expect(screen.getByRole('button', { name: '返回成果库' })).toBeTruthy();
    expect(screen.getByText('2026 年 8 月')).toBeTruthy();
  });

  it('orders a revision\'s chips the way the 文稿 export menu does', () => {
    const formats: AnalysisExportRow['format'][] = ['xlsx', 'md', 'html', 'pdf', 'docx'];
    const rows: GalleryRow[] = [
      ...formats.map((format, index): GalleryRow => {
        const exported = { ...htmlOfV2, export_id: String(index).repeat(32), format, sha256: String(index).repeat(64) };
        return { type: 'export', key: `export:${exported.export_id}`, at: SECOND, task: A, exported };
      }),
      { type: 'draft', key: `draft:${v2.draft_id}`, at: SECOND, task: A, draft: v2 },
    ];
    render(<Deliverables rows={rows} {...LIST} onOpen={() => {}} onExport={() => {}} />);
    const row = screen.getByRole('button', { name: /文稿 修订 2/ }).closest('tr')!;
    const chips = within(row).getAllByRole('button').filter((button) => button.getAttribute('data-size') === 'chip');
    const label = { docx: 'Word', pdf: 'PDF', html: 'HTML', md: 'Markdown', xlsx: 'Excel' };
    expect(chips.map((chip) => chip.firstChild!.textContent)).toEqual(EXPORT_MENU_FORMATS.map((format) => label[format]));
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
