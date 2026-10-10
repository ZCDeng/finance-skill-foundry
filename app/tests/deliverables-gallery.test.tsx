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
  ChartRow,
  CollectionRunRow,
  DeliverableRow,
  GalleryRow,
  LibraryDetail,
  TaskRow,
  WorkbookOutputRow,
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
const CHART: ChartRow = { id: 'c'.repeat(32), label: '收缴率趋势', run_id: null, created_at: SECOND, datasets: ['收费明细'] };
const WORKBOOK: WorkbookOutputRow = {
  id: 'b'.repeat(32), filename: '8月套表-写回.xlsx', sha256: '9'.repeat(64), created_at: SECOND, dataset: '8 月套表', applied: 12, kept: 3,
};
const COLLECTION: CollectionRunRow = {
  id: 'r'.repeat(32), created_at: SECOND, run_by: 'manager', as_of: '2026-08-31', group_by: [],
  caliber: { version: null, status: 'trial', differs: [] }, inputs: { receivable: '应收明细' },
  figures: { collection_rate_current: '0.8212', arrears_recovery_rate: '0.3656', collection_rate_total: '0.7316' },
};
const LIST = { open: null, onOpenWorkbook: () => {}, busy: null, onBack: () => {} };

afterEach(() => {
  cleanup();
  delete (globalThis as unknown as { foundry?: Bridge }).foundry;
  sessionStorage.clear();
  vi.restoreAllMocks();
});

/** The 状态 cell of the row whose button carries `label`. */
function statusOf(label: RegExp): HTMLElement {
  const header = screen.getAllByRole('columnheader').map((cell) => cell.textContent);
  const row = screen.getByRole('button', { name: label }).closest('tr')!;
  return within(row).getAllByRole('cell')[header.indexOf('状态')];
}
const V2 = /^八月利润说明 · 修订 2/;
const V1 = /^八月利润说明 · 修订 1/;
const groupNames = () => [...document.querySelectorAll("th[scope='rowgroup']")].map((cell) => cell.firstElementChild!.textContent);

describe('the 成果库 list', () => {
  it('puts a task\'s newest revision first as 当前版 and folds the earlier ones', () => {
    render(<Deliverables rows={ROWS} {...LIST} onOpen={() => {}} onExport={() => {}} />);
    const current = screen.getByRole('button', { name: V2 }).closest('tr')!;
    expect(current.textContent).toContain('当前版');
    expect(statusOf(V2).textContent).toBe('已归档 · 经理认可');
    // v2's draft and its HTML export are one row.
    expect(within(current).getByRole('button', { name: /^HTML 导出件/ })).toBeTruthy();
    expect(screen.queryByRole('button', { name: V1 })).toBeNull();
    const more = screen.getByRole('button', { name: /更早的 1 版/ });
    expect(more.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(more);
    expect(more.getAttribute('aria-expanded')).toBe('true');
    // v1 only has an export; its state is v1's own.
    expect(statusOf(V1).textContent).toBe('草稿 · 未阅');
    expect(screen.getByRole('button', { name: V1 }).closest('tr')!.textContent).not.toContain('当前版');
    const pdf = screen.getByRole('button', { name: /PDF 导出件/ });
    expect(pdf.closest('tr')!.textContent).toContain('导出件带「分析草稿·待复核」标记');
    expect(pdf.textContent).toContain('分析草稿·待复核');
  });

  it('keeps the old flow\'s versions in a fold of their own at the bottom', () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(<Deliverables rows={ROWS} {...LIST} onOpen={() => {}} onExport={() => {}} />);
    expect(error.mock.calls.flat().join(' ')).not.toMatch(/same key/);
    const library = screen.getByRole('region', { name: '成果库' });
    expect(within(library).queryByRole('button', { name: /结论稿/ })).toBeNull();
    const fold = screen.getByText(/旧版流程的版本 · 1/).closest('details')!;
    expect(fold.open).toBe(false);
    const old = within(fold).getByRole('button', { name: /结论稿/ });
    expect(old.textContent!.startsWith('结论稿 第 2 版')).toBe(true);
    expect(old.textContent).toContain(`打开 ${A.title} 的结论稿 第 2 版`);
  });

  it('names each task once, in its group heading, and orders groups by their newest row', () => {
    const LATER = '2026-09-28T03:00:00Z';
    const ofB: AnalysisDraftRow = { ...v2, draft_id: '9'.repeat(32), revision: 1, title: '西南回款说明' };
    const rows: GalleryRow[] = [
      { type: 'draft', key: `draft:${ofB.draft_id}`, at: LATER, task: B, draft: ofB },
      { type: 'draft', key: `draft:${v2.draft_id}`, at: SECOND, task: A, draft: v2 },
      { type: 'export', key: `export:${pdfOfV1.export_id}`, at: SECOND, task: A, exported: pdfOfV1 },
    ];
    render(<Deliverables rows={rows} {...LIST} onOpen={() => {}} onExport={() => {}} />);
    const named = screen.getAllByText(A.title);
    expect(named).toHaveLength(1);
    expect(named[0].closest("th[scope='rowgroup']")).toBeTruthy();
    expect(groupNames()).toEqual([B.title, A.title]);
  });

  it('lists 归档图, 写回 Excel and 收缴率 runs beside the 文稿', () => {
    const rows: GalleryRow[] = [
      { type: 'collection', key: 'collection:r', at: SECOND, task: A, run: COLLECTION },
      { type: 'workbook', key: 'workbook:w', at: SECOND, task: A, output: WORKBOOK },
      { type: 'chart', key: 'chart:c', at: SECOND, task: A, chart: CHART },
      { type: 'draft', key: `draft:${v2.draft_id}`, at: SECOND, task: A, draft: v2 },
    ];
    render(<Deliverables rows={rows} {...LIST} onOpen={() => {}} onExport={() => {}} />);
    expect(statusOf(/^收缴率计算 · 截至 2026-08-31/).textContent).toBe('试算');
    expect(statusOf(/^写回 Excel · 8 月套表/).textContent).toBe('写入 12 格');
    expect(statusOf(/^归档图 · 收缴率趋势/).textContent).toBe('已归档');
    fireEvent.change(screen.getByRole('combobox', { name: '类型' }), { target: { value: 'collection' } });
    expect(screen.queryByRole('button', { name: V2 })).toBeNull();
    expect(screen.getByRole('button', { name: /^收缴率计算/ })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /^归档图/ })).toBeNull();
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
    const row = screen.getByRole('button', { name: V2 }).closest('tr')!;
    expect(within(row).getByText('管理版')).toBeTruthy();
    expect(within(row).getByText('审计版')).toBeTruthy();
    const audit = within(row).getByRole('button', { name: /^PDF 导出件（修订 2 · 审计版 · / });
    expect(audit.getAttribute('data-size')).toBe('chip');
    expect(audit.hasAttribute('aria-pressed')).toBe(false);
    fireEvent.click(audit);
    expect(onOpenExport).toHaveBeenCalledWith(A, auditPdf);
    // The version filter keeps revisions that have an export of that kind.
    fireEvent.change(screen.getByRole('combobox', { name: '导出版本' }), { target: { value: 'audit' } });
    expect(screen.getByRole('button', { name: V2 })).toBeTruthy();
  });

  it('writes the period once, in words, in the group heading', () => {
    const undated = { ...B, period: null };
    const ofB: AnalysisDraftRow = { ...v2, draft_id: '9'.repeat(32), revision: 1, title: '西南回款说明' };
    const rows: GalleryRow[] = [
      { type: 'draft', key: `draft:${v2.draft_id}`, at: SECOND, task: A, draft: v2 },
      { type: 'draft', key: `draft:${ofB.draft_id}`, at: SECOND, task: undated, draft: ofB },
    ];
    render(<Deliverables rows={rows} {...LIST} onOpen={() => {}} onExport={() => {}} />);
    expect(screen.queryByRole('columnheader', { name: '期间' })).toBeNull();
    const [dated, plain] = [...document.querySelectorAll("th[scope='rowgroup']")];
    expect(dated.querySelector('.fnd-muted')!.textContent).toBe(' · 2026 年 8 月');
    expect(plain.querySelector('.fnd-muted')).toBeNull();
    expect(plain.textContent).toBe(B.title);
  });

  it('searches task names, titles and periods, filters by period and status, and says what it found', () => {
    const ofB: AnalysisDraftRow = { ...v2, draft_id: '9'.repeat(32), revision: 1, title: '西南回款说明', review_status: 'unreviewed' };
    const july = { ...B, period: '2026-07' };
    const rows: GalleryRow[] = [...ROWS, { type: 'draft', key: `draft:${ofB.draft_id}`, at: SECOND, task: july, draft: ofB }];
    render(<Deliverables rows={rows} {...LIST} onOpen={() => {}} onExport={() => {}} />);
    const status = screen.getByRole('status');
    expect(status.textContent).toBe('');
    const search = screen.getByRole('searchbox', { name: '搜索任务、标题或期间' });
    fireEvent.change(search, { target: { value: '西南' } });
    expect(groupNames()).toEqual([B.title]);
    expect(status.textContent).toBe('找到 1 个任务');
    fireEvent.change(search, { target: { value: '利润说明' } });
    expect(groupNames()).toEqual([A.title]);
    fireEvent.change(search, { target: { value: '2026 年 7 月' } });
    expect(groupNames()).toEqual([B.title]);
    fireEvent.change(search, { target: { value: '不存在' } });
    expect(screen.queryByRole('table', { name: /按任务分组/ })).toBeNull();
    expect(status.textContent).toBe('没有和「不存在」相符的成果');
    expect(screen.getByText('没有和「不存在」相符的成果', { selector: 'p' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '清除筛选' }));
    expect(groupNames()).toEqual([A.title, B.title]);
    fireEvent.change(screen.getByRole('combobox', { name: '期间' }), { target: { value: '2026-08' } });
    expect(groupNames()).toEqual([A.title]);
    fireEvent.change(screen.getByRole('combobox', { name: '期间' }), { target: { value: '' } });
    fireEvent.change(screen.getByRole('combobox', { name: '文稿状态' }), { target: { value: 'unreviewed' } });
    // A's 当前版 is accepted, so only its earlier revision stays, listed as it is and not called 当前版.
    expect(groupNames()).toEqual([A.title, B.title]);
    expect(screen.queryByRole('button', { name: V2 })).toBeNull();
    expect(screen.getByRole('button', { name: V1 }).closest('tr')!.textContent).not.toContain('当前版');
    // Under a status filter the old flow, which has none, is left out.
    expect(screen.queryByText(/旧版流程的版本/)).toBeNull();
  });

  it('keeps a revision already read (已阅) out of 待复核', () => {
    const read: AnalysisDraftRow = { ...v2, review_status: 'reviewed' };
    render(<Deliverables rows={[{ type: 'draft', key: `draft:${read.draft_id}`, at: SECOND, task: A, draft: read }]} {...LIST} onOpen={() => {}} onExport={() => {}} />);
    fireEvent.change(screen.getByRole('combobox', { name: '文稿状态' }), { target: { value: 'unreviewed' } });
    expect(screen.queryByRole('button', { name: V2 })).toBeNull();
    fireEvent.change(screen.getByRole('combobox', { name: '文稿状态' }), { target: { value: 'reviewed' } });
    expect(screen.getByRole('button', { name: V2 })).toBeTruthy();
  });

  it('with only old-flow versions matching, opens their fold instead of saying nothing matched', () => {
    const rows: GalleryRow[] = [{ type: 'deliverable', key: `deliverable:${A.id}:2`, at: SECOND, task: A, row: brief }];
    render(<Deliverables rows={rows} {...LIST} onOpen={() => {}} onExport={() => {}} />);
    expect(screen.queryByText(/没有符合筛选条件的成果/)).toBeNull();
    expect((screen.getByText(/旧版流程的版本 · 1/).closest('details') as HTMLDetailsElement).open).toBe(true);
    fireEvent.change(screen.getByRole('searchbox', { name: '搜索任务、标题或期间' }), { target: { value: 'emit' } });
    expect(screen.getByRole('status').textContent).toBe('旧版流程里有 1 个相符的版本');
    expect(screen.queryByText(/没有和「emit」相符的成果/)).toBeNull();
  });

  it('titles the screen 成果库 whether or not there is anything in it, and says how to get a first result', () => {
    render(<Deliverables rows={ROWS} {...LIST} onOpen={() => {}} onExport={() => {}} />);
    expect(screen.getByRole('heading', { level: 1, name: '成果库' })).toBeTruthy();
    cleanup();
    const onSample = vi.fn();
    render(<Deliverables rows={[]} {...LIST} onOpen={() => {}} onExport={() => {}} onSample={onSample} />);
    expect(screen.getByRole('heading', { level: 1, name: '成果库' })).toBeTruthy();
    expect(screen.getByText('还没有成果')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '用示例练习' }));
    expect(onSample).toHaveBeenCalled();
  });

  it('heads the columns 成果, 状态, 导出件, 最近更新, each scoped to its column', () => {
    render(<Deliverables rows={ROWS.filter((row) => row.type !== 'deliverable')} {...LIST} onOpen={() => {}} onExport={() => {}} />);
    const headers = screen.getAllByRole('columnheader');
    expect(headers.map((cell) => cell.textContent)).toEqual(['成果', '状态', '导出件', '最近更新']);
    for (const cell of headers) expect(cell.getAttribute('scope')).toBe('col');
  });

  it('writes 最近更新 as plain text, and keeps the table a focusable region', () => {
    render(<Deliverables rows={ROWS} {...LIST} onOpen={() => {}} onExport={() => {}} />);
    const region = screen.getByRole('region', { name: '成果库' });
    const header = within(region).getAllByRole('columnheader').map((cell) => cell.textContent);
    for (const row of region.querySelectorAll('tr.fnd-library__row')) {
      const cell = within(row as HTMLElement).getAllByRole('cell')[header.indexOf('最近更新')];
      expect(cell.textContent).not.toBe('');
      expect(within(cell).queryByRole('button')).toBeNull();
    }
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

  it('starts every button\'s name with what it shows and carries the task and time', () => {
    render(<Deliverables rows={ROWS} {...LIST} onOpen={() => {}} onExport={() => {}} />);
    const draft = screen.getByRole('button', { name: V2 });
    expect(draft.getAttribute('aria-label')).toBeNull();
    expect(draft.textContent).toContain(A.title);
    expect(draft.textContent).toContain(when(v2.created_at));
    fireEvent.click(screen.getByRole('button', { name: /更早的 1 版/ }));
    const pdf = screen.getByRole('button', { name: /PDF 导出件/ });
    expect(pdf.getAttribute('aria-label')).toBeNull();
    expect(pdf.textContent!.startsWith('PDF')).toBe(true);
    expect(pdf.textContent).toContain(when(pdfOfV1.created_at));
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
    const row = screen.getByRole('button', { name: V2 }).closest('tr')!;
    expect(within(row).getAllByText('其他')).toHaveLength(1);
    expect([...row.querySelectorAll('.fnd-library__chips')].map((chips) => chips.children.length)).toEqual([2]);
    expect(row.classList.contains('fnd-table__open')).toBe(false);
  });

  it('keeps the search and the selection when an old version is opened and closed again', () => {
    const props = { rows: ROWS, ...LIST, onOpen: () => {}, onExport: () => {} };
    const { rerender } = render(<Deliverables {...props} />);
    fireEvent.change(screen.getByRole('searchbox', { name: '搜索任务、标题或期间' }), { target: { value: '八月' } });
    fireEvent.click(screen.getByRole('button', { name: V2 }));
    rerender(<Deliverables {...props} open={{ task: A, row: brief, text: '# 本期结论稿' }} />);
    expect(screen.queryByRole('searchbox')).toBeNull();
    rerender(<Deliverables {...props} />);
    expect((screen.getByRole('searchbox', { name: '搜索任务、标题或期间' }) as HTMLInputElement).value).toBe('八月');
    expect(screen.getByRole('complementary', { name: /八月利润说明 · 修订 2/ })).toBeTruthy();
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
    const row = screen.getByRole('button', { name: V2 }).closest('tr')!;
    const chips = within(row).getAllByRole('button').filter((button) => button.getAttribute('data-size') === 'chip');
    const label = { docx: 'Word', pdf: 'PDF', html: 'HTML', md: 'Markdown', xlsx: 'Excel' };
    expect(chips.map((chip) => chip.firstChild!.textContent)).toEqual(EXPORT_MENU_FORMATS.map((format) => label[format]));
  });

  it('opens a revision\'s panel, an export and an old version each its own way', () => {
    const onOpen = vi.fn(), onOpenDraft = vi.fn(), onOpenExport = vi.fn();
    render(<Deliverables rows={ROWS} {...LIST} onOpen={onOpen} onExport={() => {}} onOpenDraft={onOpenDraft} onOpenExport={onOpenExport} />);
    const name = screen.getByRole('button', { name: V2 });
    fireEvent.click(name);
    expect(name.getAttribute('aria-pressed')).toBe('true');
    const panel = screen.getByRole('complementary', { name: /八月利润说明 · 修订 2/ });
    fireEvent.click(within(panel).getByRole('button', { name: /在文稿页打开/ }));
    expect(onOpenDraft).toHaveBeenCalledWith(A, v2);
    fireEvent.click(within(panel).getByRole('button', { name: '关闭详情' }));
    expect(screen.queryByRole('complementary')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /更早的 1 版/ }));
    fireEvent.click(screen.getByRole('button', { name: /PDF 导出件/ }));
    fireEvent.click(screen.getByRole('button', { name: /结论稿/ }));
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
 * The side panel: what a 文稿 revision rests on, its checks, its exports and a comparison with another
 * version; for a 写回 Excel copy and a 收缴率 run, what they are and where to open them.
 */
describe('the 成果库 side panel', () => {
  const v1Draft: AnalysisDraftRow = { ...v2, draft_id: '1'.repeat(32), revision: 1, review_status: 'unreviewed', publication_status: 'draft' };
  const detail = (id: string, body: string): LibraryDetail => ({
    schema_version: 1, task_id: A.id,
    draft: { draft_id: id, revision: id === v2.draft_id ? 2 : 1, title: '八月利润说明', created_at: SECOND,
      review_status: 'accepted', publication_status: 'archived', parent_id: null, body },
    checks: [
      { key: 'execution', label: '计算执行', status: 'pass' },
      { key: 'numeric_citation', label: '数字引用', status: 'fail' },
    ],
    rests_on: [{ run_id: 'r'.repeat(32), label: '八月毛利率', created_at: SECOND, datasets: [{ id: 'd1', name: '利润表.xlsx', hash: 'abcdef012345' }] }],
    requirements: { seq: 1, scope: { period: '2026-08', organization: '华东区' } },
    versions: [
      { draft_id: v1Draft.draft_id, revision: 1, title: '八月利润说明', created_at: SECOND },
      { draft_id: v2.draft_id, revision: 2, title: '八月利润说明', created_at: SECOND },
    ],
  });
  const rows: GalleryRow[] = [
    { type: 'export', key: `export:${htmlOfV2.export_id}`, at: SECOND, task: A, exported: htmlOfV2 },
    { type: 'draft', key: `draft:${v2.draft_id}`, at: SECOND, task: A, draft: v2 },
    { type: 'draft', key: `draft:${v1Draft.draft_id}`, at: SECOND, task: A, draft: v1Draft },
    { type: 'workbook', key: 'workbook:w', at: SECOND, task: A, output: WORKBOOK },
    { type: 'collection', key: 'collection:r', at: SECOND, task: A, run: COLLECTION },
  ];

  it('shows a revision\'s checks, sources and scope, and compares it with another version', async () => {
    const onDetail = vi.fn(async (_task: TaskRow, id: string) => detail(id, id === v2.draft_id
      ? '# 八月利润说明\n\n毛利率 32.1%。\n\n费用率下降。' : '# 八月利润说明\n\n毛利率 31.0%。\n\n费用率下降。'));
    const onFile = vi.fn();
    render(<Deliverables rows={rows} {...LIST} onOpen={() => {}} onExport={() => {}} onDetail={onDetail} onFile={onFile} />);
    fireEvent.click(screen.getByRole('button', { name: V2 }));
    const panel = screen.getByRole('complementary', { name: /修订 2/ });
    expect(onDetail).toHaveBeenCalledWith(A, v2.draft_id);
    const sources = await within(panel).findByRole('region', { name: '来源追溯' });
    expect(sources.textContent).toContain('八月毛利率');
    expect(sources.textContent).toContain('利润表.xlsx');
    expect(sources.textContent).toContain('abcdef012345');
    expect(sources.textContent).toContain('华东区');
    expect(within(panel).getByRole('region', { name: '检查' }).textContent).toContain('数字引用需要处理');
    fireEvent.click(within(panel).getByRole('button', { name: /^打开HTML/ }));
    expect(onFile).toHaveBeenCalledWith(A, { kind: 'export', sha: htmlOfV2.sha256, format: 'html' }, 'open');
    fireEvent.change(within(panel).getByRole('combobox', { name: '和哪一版比较' }), { target: { value: v1Draft.draft_id } });
    await waitFor(() => expect(panel.querySelector('ins')).toBeTruthy());
    expect(panel.querySelector('ins')!.textContent).toContain('毛利率 32.1%。');
    expect(panel.querySelector('del')!.textContent).toContain('毛利率 31.0%。');
    expect(within(panel).getByText(/新增 1 行，删除 1 行/).textContent).toContain('从所选那一版到这一版');
  });

  it('opens a 写回 Excel copy and points a 收缴率 run at its task', () => {
    const onFile = vi.fn(), onOpenTask = vi.fn();
    render(<Deliverables rows={rows} {...LIST} onOpen={() => {}} onExport={() => {}} onFile={onFile} onOpenTask={onOpenTask} />);
    fireEvent.click(screen.getByRole('button', { name: /^写回 Excel/ }));
    let panel = screen.getByRole('complementary');
    expect(panel.textContent).toContain('12 个');
    fireEvent.click(within(panel).getByRole('button', { name: /在访达中显示/ }));
    expect(onFile).toHaveBeenCalledWith(A, { kind: 'workbook', id: WORKBOOK.id }, 'reveal');
    fireEvent.click(screen.getByRole('button', { name: /^收缴率计算/ }));
    panel = screen.getByRole('complementary');
    expect(panel.textContent).toContain('82.12%');
    expect(panel.textContent).toContain('口径还没有经理确认');
    fireEvent.click(within(panel).getByRole('button', { name: '在资料页查看' }));
    expect(onOpenTask).toHaveBeenCalledWith(A, 'billing');
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
    return screen.findByRole('button', { name: new RegExp(`^${B.title}修订稿 · 修订 2`) });
  }
  /** Choose a revision's row, then 在文稿页打开 in its side panel. */
  function openFromPanel(owner: TaskRow) {
    fireEvent.click(screen.getByRole('button', { name: new RegExp(`^${owner.title}修订稿 · 修订 2`) }));
    const panel = screen.getByRole('complementary', { name: /修订 2/ });
    fireEvent.click(within(panel).getByRole('button', { name: /在文稿页打开/ }));
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
    await openLibrary();
    openFromPanel(B);
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
    await screen.findByRole('button', { name: new RegExp(`^${B.title}修订稿 · 修订 2`) });
    openFromPanel(archivedB);
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
    openFromPanel(A);
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
    // A's PDF is of revision 1, folded under its 当前版.
    fireEvent.click(screen.getByRole('button', { name: new RegExp(`更早的 1 版（${A.title}）`) }));
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
