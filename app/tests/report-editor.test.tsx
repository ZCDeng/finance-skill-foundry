// @vitest-environment jsdom
import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { useState } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest';
import { ReportEditor } from '../src/views/analysis/ReportEditor.js';
import { documentFromMarkdown, documentToMarkdown } from '../electron/reports/format.js';
import type { Answer } from '../src/bridge.js';
import type { ReportDocument, ReportImportResult, ReportNode, ReportSource } from '../electron/reports/model.js';

const pdfjsMock = vi.hoisted(() => ({
  getDocument: vi.fn(),
  workerOptions: { workerSrc: '' },
}));

vi.mock('pdfjs-dist', () => ({
  GlobalWorkerOptions: pdfjsMock.workerOptions,
  getDocument: pdfjsMock.getDocument,
}));

const taskId = 'a'.repeat(32);
const source: ReportSource = { id: 'b'.repeat(32), name: 'source.xlsx', sha256: 'c'.repeat(64), format: 'xlsx' };
const repoRoot = resolve(process.cwd(), '..');
const success = <T,>(value: T): Answer<T> => ({ ok: true, value });

beforeEach(() => {
  Element.prototype.getClientRects = vi.fn(() => ({ length: 1, item: () => null, [0]: new DOMRect(0, 0, 120, 24) } as unknown as DOMRectList));
  Element.prototype.getBoundingClientRect = vi.fn(() => new DOMRect(0, 0, 120, 24));
  Range.prototype.getClientRects = vi.fn(() => ({ length: 1, item: () => null, [0]: new DOMRect(0, 0, 120, 24) } as unknown as DOMRectList));
  Range.prototype.getBoundingClientRect = vi.fn(() => new DOMRect(0, 0, 120, 24));
  window.scrollBy = vi.fn();
});

afterEach(() => { cleanup(); delete (globalThis as unknown as { foundry?: unknown }).foundry; vi.clearAllMocks(); pdfjsMock.getDocument.mockReset(); });

type HandlerMocks = { onTitle: Mock; onBody: Mock; onDocument: Mock; onLimitations: Mock; onReview: Mock; onExport: Mock };

function mount(props: Partial<React.ComponentProps<typeof ReportEditor>> = {}): HandlerMocks {
  const handlers: HandlerMocks = {
    onTitle: vi.fn(),
    onBody: vi.fn(),
    onDocument: vi.fn(),
    onLimitations: vi.fn(),
    onReview: vi.fn(),
    onExport: vi.fn(),
  };
  render(<ReportEditor taskId={taskId} title="经营分析" body="# 管理摘要\n正文\n" limitations="" review="reviewed" busy={false} initialMode="edit" {...handlers} {...props} />);
  return handlers;
}

function mountStateful(initial: Partial<React.ComponentProps<typeof ReportEditor>> = {}): HandlerMocks & { current: () => { title: string; body: string; document?: ReportDocument; review: string } } {
  const handlers: HandlerMocks = {
    onTitle: vi.fn(),
    onBody: vi.fn(),
    onDocument: vi.fn(),
    onLimitations: vi.fn(),
    onReview: vi.fn(),
    onExport: vi.fn(),
  };
  const state = {
    title: initial.title ?? '经营分析',
    body: initial.body ?? '# 管理摘要\n正文\n',
    document: initial.document,
    review: initial.review ?? 'reviewed',
  };
  function Harness() {
    const [title, setTitle] = useState(state.title);
    const [body, setBody] = useState(state.body);
    const [document, setDocument] = useState<ReportDocument | undefined>(state.document);
    const [review, setReview] = useState(state.review);
    state.title = title;
    state.body = body;
    state.document = document;
    state.review = review;
    return (
      <ReportEditor
        taskId={taskId}
        title={title}
        body={body}
        limitations={initial.limitations ?? ''}
        review={review}
        busy={initial.busy ?? false}
        initialMode={initial.initialMode ?? 'edit'}
        appendix={initial.appendix}
        document={document}
        onTitle={(value) => { handlers.onTitle(value); setTitle(value); }}
        onBody={(value) => { handlers.onBody(value); setBody(value); }}
        onDocument={(value) => { handlers.onDocument(value); setDocument(value); }}
        onLimitations={handlers.onLimitations}
        onReview={(value) => { handlers.onReview(value); setReview(value); }}
        onExport={handlers.onExport}
      />
    );
  }
  render(<Harness />);
  return { ...handlers, current: () => ({ ...state }) };
}

describe('report editor workspace', () => {
  it('preserves source and table metadata through a visual edit and writes block notes', async () => {
    const document: ReportDocument = {
      schema_version: 1,
      template_version: 'annual-v1',
      metadata: { company: '华宸物业', period: '2026-08', currency: 'CNY', unit: '万元' },
      sources: [source],
      content: [
        { type: 'heading', attrs: { level: 1, source_id: source.id, page: 3 }, content: [{ type: 'text', text: '管理摘要' }] },
        { type: 'paragraph', attrs: { source_id: source.id, sheet: '摘要', range: 'A1:B2' }, content: [{ type: 'text', text: '收入改善' }] },
        { type: 'image', attrs: { source_id: source.id, src: png1x1, alt: '经营趋势图', title: '本地图片' } },
        { type: 'table', attrs: { source_id: source.id, sheet: '利润表', range: 'A1:C3', caption: '利润表', period: '2026-08', currency: 'CNY', unit: '万元' }, content: [
          { type: 'tableRow', attrs: { source_id: source.id }, content: [cell('tableHeader', '项目'), cell('tableHeader', '金额')] },
          { type: 'tableRow', attrs: { source_id: source.id }, content: [cell('tableCell', '收入'), cell('tableCell', '1,234.50', { textAlign: 'right', source_id: source.id, sheet: '利润表', range: 'B2' })] },
        ] },
      ],
    };
    const handlers = mount({ document, body: documentToMarkdown(document) });

    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
    fireEvent.click(screen.getByRole('button', { name: '附注' }));
    fireEvent.change(screen.getByLabelText('附注编号'), { target: { value: '1' } });
    fireEvent.change(screen.getByLabelText('附注内容'), { target: { value: '金额来自总账缓存值。' } });
    fireEvent.click(screen.getByRole('button', { name: '插入附注引用' }));

    await waitFor(() => expect(handlers.onDocument).toHaveBeenCalled());
    const next = handlers.onDocument.mock.calls.at(-1)?.[0] as ReportDocument;
    expect(JSON.stringify(next)).not.toContain(':null');
    const table = next.content.find((node) => node.type === 'table')!;
    expect(table.attrs).toMatchObject({ source_id: source.id, sheet: '利润表', range: 'A1:C3', caption: '利润表', period: '2026-08', currency: 'CNY', unit: '万元' });
    expect(JSON.stringify(table)).toContain('"range":"B2"');
    const noteIndex = next.content.findIndex((node) => node.type === 'reportNote');
    expect(noteIndex).toBeGreaterThan(next.content.findIndex((node) => node.type === 'table'));
    const note = next.content[noteIndex]!;
    expect(note).toMatchObject({ type: 'reportNote', attrs: { id: '1' }, content: [{ type: 'paragraph' }] });
    expect(JSON.stringify(next)).toContain('经营趋势图');
    const validated = validateWithPython(next);
    expect(JSON.stringify(validated.document)).toContain('经营趋势图');
    expect(validated.markdown).toContain('1,234.50');
    expect(validated.markdown).toContain('![经营趋势图]');
    expect(validated.markdown).toContain('[^1]: 金额来自总账缓存值。');
    expect(JSON.stringify(validated.document)).toContain('"source_id":"' + source.id + '"');
    expect(JSON.stringify(validated.document)).toContain('"range":"B2"');
  });

  it('deduplicates an exact leading title from the reader body and outline', () => {
    const document = documentFromMarkdown('# 经营分析\n\n## 管理摘要\n正文\n\n# 附录\n用户附录。');
    mount({ initialMode: 'read', title: '经营分析', document, body: documentToMarkdown(document) });

    const reading = screen.getByRole('article', { name: '文稿阅读' });
    expect(within(reading).getAllByRole('heading', { name: '经营分析' })).toHaveLength(1);
    expect(screen.queryByRole('link', { name: '经营分析' })).toBeNull();
    const toolbar = screen.getByRole('group', { name: '文稿工具栏' });
    const toggle = within(toolbar).getByRole('button', { name: '目录' });
    const shell = toggle.closest('.report-shell') as HTMLElement;
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(screen.queryByRole('complementary', { name: '文稿目录' })).toBeNull();
    expect(shell.hasAttribute('data-outline-expanded')).toBe(false);
    fireEvent.click(toggle);
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(shell.getAttribute('data-outline-expanded')).toBe('true');
    const outline = screen.getByRole('complementary', { name: '文稿目录' });
    expect(toggle.getAttribute('aria-controls')).toBe(outline.id);
    expect(within(outline).getByRole('link', { name: '管理摘要' })).toBeTruthy();
    expect(within(outline).getByRole('link', { name: '附录' })).toBeTruthy();
    // Escape closes the outline and gives the focus back to 目录.
    within(outline).getByRole('link', { name: '管理摘要' }).focus();
    fireEvent.keyDown(outline, { key: 'Escape' });
    expect(screen.queryByRole('complementary', { name: '文稿目录' })).toBeNull();
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(window.document.activeElement).toBe(toggle);
  });

  it('decides drawer or column when each event comes, across a breakpoint, and keeps the focus with 目录', async () => {
    let mode = 'column';
    const original = window.getComputedStyle.bind(window);
    const styles = vi.spyOn(window, 'getComputedStyle').mockImplementation(((element: Element, pseudo?: string | null) =>
      element.classList.contains('report-outline')
        ? ({ getPropertyValue: (name: string) => (name === '--report-outline-mode' ? mode : '') } as unknown as CSSStyleDeclaration)
        : original(element, pseudo)) as typeof window.getComputedStyle);
    const document = documentFromMarkdown('## 管理摘要\n正文\n\n## 附录\n用户附录。');
    mount({ initialMode: 'read', document, body: documentToMarkdown(document) });
    const toggle = within(screen.getByRole('group', { name: '文稿工具栏' })).getByRole('button', { name: '目录' });
    const page = window.document;

    // Opened as a column: the focus stays on 目录.
    fireEvent.click(toggle);
    toggle.focus();
    expect(screen.getByRole('complementary', { name: '文稿目录' })).toBeTruthy();
    // The workspace narrows while it is open: Escape on 目录 now closes the drawer.
    mode = 'drawer';
    fireEvent.keyDown(page, { key: 'Escape' });
    expect(screen.queryByRole('complementary', { name: '文稿目录' })).toBeNull();
    expect(page.activeElement).toBe(toggle);

    // Opened as a drawer: the focus moves in, and a click on plain text outside closes it and gives the focus back.
    fireEvent.click(toggle);
    expect(page.activeElement).toBe(screen.getByRole('link', { name: '管理摘要' }));
    fireEvent.pointerDown(screen.getByRole('article', { name: '文稿阅读' }));
    expect(screen.queryByRole('complementary', { name: '文稿目录' })).toBeNull();
    await waitFor(() => expect(page.activeElement).toBe(toggle));

    // Escape with the focus neither in the drawer nor on 目录 leaves it open.
    mode = 'column';
    fireEvent.click(toggle);
    const importButton = screen.getByRole('button', { name: '导入' });
    importButton.focus();
    mode = 'drawer';
    fireEvent.keyDown(page, { key: 'Escape' });
    const outline = screen.getByRole('complementary', { name: '文稿目录' });
    // Moving the focus out of the drawer closes it.
    screen.getByRole('link', { name: '管理摘要' }).focus();
    fireEvent.focusOut(outline, { relatedTarget: importButton });
    expect(screen.queryByRole('complementary', { name: '文稿目录' })).toBeNull();
    styles.mockRestore();
  });

  it('marks reading-table cells by what they say and makes only an overflowing table a named region', () => {
    const body = [
      '## 二、区域经营',
      '',
      '表题：表 2-1 区域营业利润',
      '',
      '| 区域 | 1 至 8 月实际 | 营业利润差异率（同口径） |',
      '| --- | --- | --- |',
      '| 华东区域 | 325,644.00 万元 | -3.30% |',
      '| 华南区域 | -18,843.06 万元 | 预算为负，不作比率 |',
      '| 西南区域 | 117814.5625 万元（估算） | 12.5% |',
      '| 华北区域 | — | 1.5% |',
    ].join('\n');
    const widths = vi.spyOn(HTMLElement.prototype, 'scrollWidth', 'get').mockImplementation(function (this: HTMLElement) {
      return this.matches('figure.financial-table') ? 1200 : 0;
    });
    mount({ initialMode: 'read', body });
    widths.mockRestore();
    const main = screen.getByRole('article', { name: '文稿阅读' }).querySelector('.analysis-draft-main') as HTMLElement;
    const figure = within(main).getByRole('region', { name: '表 2-1 区域营业利润' });
    expect(figure.getAttribute('tabindex')).toBe('0');
    expect(figure.classList.contains('financial-table')).toBe(true);
    const cellClass = (text: string) => within(figure).getByText(text).closest('td, th')?.className;
    expect(cellClass('325,644.00 万元')).toBe('num');
    expect(cellClass('-18,843.06 万元')).toBe('num neg');
    expect(cellClass('117814.5625 万元（估算）')).toBe('num');
    expect(cellClass('-3.30%')).toBe('num neg');
    // A dash or a note in a numeric column follows the column and does not vote on it.
    expect(cellClass('预算为负，不作比率')).toBe('num note');
    expect(cellClass('—')).toBe('num note');
    expect(cellClass('华东区域')).toBe('text');
    expect(cellClass('区域')).toBe('text');
    expect(cellClass('1 至 8 月实际')).toBe('num');
    expect(cellClass('营业利润差异率（同口径）')).toBe('num');
  });

  it('leaves a table that fits as a plain figure', () => {
    mount({ initialMode: 'read', body: '| 区域 | 实际 |\n| --- | --- |\n| 华东 | 1,000.00 |' });
    const figure = screen.getByRole('article', { name: '文稿阅读' }).querySelector('figure.financial-table') as HTMLElement;
    expect(figure.hasAttribute('tabindex')).toBe(false);
    expect(figure.getAttribute('role')).toBeNull();
  });

  it('puts the archive action in the document toolbar after the export menu', () => {
    mount({ initialMode: 'read', archiveAction: <button type="button">归档此版</button>, assistantAction: <button type="button">继续分析</button> });
    const toolbar = screen.getByRole('group', { name: '文稿工具栏' });
    const archive = within(toolbar).getByRole('button', { name: '归档此版' });
    const exportMenu = within(toolbar).getByRole('button', { name: '导出' });
    const assistant = within(toolbar).getByRole('button', { name: '继续分析' });
    expect(exportMenu.compareDocumentPosition(archive) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(archive.compareDocumentPosition(assistant) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('folds the exact appendix without reparsing rich main content', () => {
    const appendixDoc = documentFromMarkdown('## 计算依据附录\n| 项目 | 金额 |\n| --- | --- |\n| 收入 | 1,234.50 |\n');
    const appendix = documentToMarkdown(appendixDoc).trim();
    const document: ReportDocument = {
      schema_version: 1,
      template_version: 'annual-v1',
      metadata: { company: '', period: '', currency: '', unit: '' },
      content: [
        { type: 'heading', attrs: { level: 1, source_id: source.id }, content: [{ type: 'text', text: '管理摘要' }] },
        { type: 'image', attrs: { source_id: source.id, src: png1x1, alt: '趋势图' } },
        { type: 'table', attrs: { source_id: source.id, caption: '合并测试' }, content: [
          { type: 'tableRow', content: [cell('tableHeader', '项目'), cell('tableHeader', '金额')] },
          { type: 'tableRow', content: [cell('tableCell', '合并单元格', { colspan: 2, source_id: source.id })] },
        ] },
        ...appendixDoc.content,
      ],
    };
    mount({ initialMode: 'read', document, body: documentToMarkdown(document), appendix });
    const reading = screen.getByRole('article', { name: '文稿阅读' });
    const main = reading.querySelector('.analysis-draft-main') as HTMLElement;

    expect(within(main).getByAltText('趋势图')).toBeTruthy();
    expect(main.querySelector('td[colspan="2"]')).toBeTruthy();
    expect(within(main).queryByRole('heading', { name: '计算依据附录' })).toBeNull();
    const fold = within(reading).getByText('系统生成计算依据附录').closest('details') as HTMLDetailsElement;
    fold.open = true;
    expect(within(fold).getByRole('heading', { name: '计算依据附录' })).toBeTruthy();
  });

  it('folds a canonical appendix suffix while preserving rich main content', () => {
    const appendix = '## 计算依据附录\n金额来自系统证据。';
    const appendixDoc = documentFromMarkdown(appendix);
    const document: ReportDocument = {
      schema_version: 1,
      template_version: 'annual-v1',
      metadata: { company: '', period: '', currency: '', unit: '' },
      content: [
        { type: 'heading', attrs: { level: 1, source_id: source.id }, content: [{ type: 'text', text: '管理摘要' }] },
        { type: 'image', attrs: { source_id: source.id, src: png1x1, alt: '趋势图' } },
        ...appendixDoc.content,
      ],
    };
    mount({ initialMode: 'read', document, body: documentToMarkdown(document), appendix });
    const reading = screen.getByRole('article', { name: '文稿阅读' });
    const main = reading.querySelector('.analysis-draft-main') as HTMLElement;

    expect(within(main).getByAltText('趋势图')).toBeTruthy();
    expect(within(main).queryByRole('heading', { name: '计算依据附录' })).toBeNull();
    expect(within(reading).getByText('系统生成计算依据附录')).toBeTruthy();
  });

  it('keeps a structurally tampered appendix visible even when the body has the stored suffix', () => {
    const appendix = '## 计算依据附录\n金额来自系统证据。';
    const tamperedAppendixDoc = documentFromMarkdown('## 计算依据附录\n金额来自经理改写。');
    const body = `# 管理摘要
正文

${documentToMarkdown(documentFromMarkdown(appendix)).trim()}`;
    const document: ReportDocument = {
      schema_version: 1,
      template_version: 'annual-v1',
      metadata: { company: '', period: '', currency: '', unit: '' },
      content: [
        { type: 'heading', attrs: { level: 1, source_id: source.id }, content: [{ type: 'text', text: '管理摘要' }] },
        ...tamperedAppendixDoc.content,
      ],
    };
    mount({ initialMode: 'read', document, body, appendix });
    const reading = screen.getByRole('article', { name: '文稿阅读' });

    expect(within(reading).getByRole('heading', { name: '计算依据附录' })).toBeTruthy();
    expect(within(reading).getByText('金额来自经理改写。')).toBeTruthy();
    expect(within(reading).queryByText('系统生成计算依据附录')).toBeNull();
  });

  it('keeps markdown source edits recoverable until explicitly adopted', async () => {
    const document = documentFromMarkdown('# 管理摘要\n原正文\n');
    const handlers = mount({ document, body: documentToMarkdown(document) });

    fireEvent.click(screen.getByRole('button', { name: 'Markdown 源码' }));
    fireEvent.change(screen.getByLabelText('文稿正文'), { target: { value: '# 降级版\n只保留源码\n' } });
    expect(handlers.onBody).not.toHaveBeenCalledWith('# 降级版\n只保留源码\n');
    expect(screen.getByLabelText('源码降级预览').textContent).toContain('降级版');
    fireEvent.click(screen.getByRole('button', { name: '取消源码编辑' }));
    expect(handlers.onDocument).toHaveBeenLastCalledWith(document);

    fireEvent.click(screen.getByRole('button', { name: 'Markdown 源码' }));
    fireEvent.change(screen.getByLabelText('文稿正文'), { target: { value: '# 降级版\n只保留源码\n' } });
    fireEvent.click(screen.getByRole('button', { name: '采用源码转换' }));
    expect(handlers.onDocument).toHaveBeenLastCalledWith(undefined);
    expect(handlers.onBody).toHaveBeenLastCalledWith('# 降级版\n只保留源码\n');
  });

  it('inserts an authored visual, edits its node, and restores structured content after source conversion', async () => {
    (globalThis as unknown as { foundry: unknown }).foundry = { financeCall: vi.fn(async () => success({ charts: [] })) };
    const handlers = mountStateful();
    fireEvent.click(screen.getByRole('button', { name: '插入图表' }));
    fireEvent.change(screen.getByLabelText('图表类型'), { target: { value: 'flow' } });
    fireEvent.change(screen.getByLabelText('图表标题'), { target: { value: '回款闭环' } });
    fireEvent.change(screen.getByLabelText('步骤 1'), { target: { value: '核对应收' } });
    fireEvent.change(screen.getByLabelText('步骤 2'), { target: { value: '收款核销' } });
    fireEvent.click(screen.getByRole('button', { name: '插入文稿' }));
    await waitFor(() => expect(handlers.current().document?.content.some((node) => node.type === 'reportVisual')).toBe(true));
    fireEvent.click(screen.getByRole('button', { name: '编辑图表：回款闭环' }));
    fireEvent.change(screen.getByLabelText('图表标题'), { target: { value: '经复核的回款闭环' } });
    fireEvent.click(screen.getByRole('button', { name: '更新图表' }));
    await screen.findByRole('button', { name: '编辑图表：经复核的回款闭环' });
    const structured = handlers.current().document;
    expect(handlers.current().review).toBe('unreviewed');
    expect(screen.queryByLabelText('文稿正文')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Markdown 源码' }));
    expect(screen.getByRole('status').textContent).toContain('图表将转换为数据表或流程文字');
    fireEvent.click(screen.getByRole('button', { name: '采用源码转换' }));
    expect(handlers.current().document).toBeUndefined();
    fireEvent.click(screen.getByRole('button', { name: '恢复结构版' }));
    expect(handlers.current().document).toEqual(structured);
    expect(screen.getByRole('button', { name: '编辑图表：经复核的回款闭环' })).toBeTruthy();
  });

  it('reopens a saved structured diagram and keeps its complete semantics on an unrelated edit', async () => {
    const visual = { kind: 'flow', title: '归档流程', source_label: '作者分析', version: 1, steps: [{ label: '来源确认', detail: '核对期间与单位', connector: '确认后' }, { label: '归档分析', detail: '保留判断和依据', connector: '' }], takeaway: '各步骤保留复核记录' };
    const document = documentFromMarkdown('# 管理摘要\n正文\n');
    document.content.push({ type: 'reportVisual', attrs: { visual } });
    const state = mountStateful({ document, body: documentToMarkdown(document) });
    fireEvent.click(await screen.findByRole('button', { name: '编辑图表：归档流程' }));
    fireEvent.change(screen.getByLabelText('图表标题'), { target: { value: '已归档的分析流程' } });
    fireEvent.click(screen.getByRole('button', { name: '更新图表' }));
    await waitFor(() => expect(state.current().document?.content.find((node) => node.type === 'reportVisual')?.attrs?.visual).toEqual({ ...visual, title: '已归档的分析流程' }));
    const validated = validateWithPython(state.current().document!);
    expect(validated.document.content.find((node) => node.type === 'reportVisual')?.attrs?.visual).toEqual({ ...visual, title: '已归档的分析流程' });
  });

  it('edits report metadata and inserts empty management-report sections only on request', async () => {
    const handlers = mount({ body: '', document: { schema_version: 1, template_version: 'annual-v1', metadata: { company: '', period: '', currency: '', unit: '' }, content: [] } });
    fireEvent.click(screen.getByText('报告信息'));
    fireEvent.change(screen.getByLabelText('报告公司'), { target: { value: '华宸物业' } });
    expect((handlers.onDocument.mock.calls.at(-1)?.[0] as ReportDocument).metadata.company).toBe('华宸物业');

    fireEvent.click(screen.getByRole('button', { name: '插入空白提纲' }));
    const next = handlers.onDocument.mock.calls.at(-1)?.[0] as ReportDocument;
    expect(next.content.filter((node) => node.type === 'heading').map((node) => node.content?.[0]?.text)).toEqual([
      '报告信息', '管理摘要', '经营与预算分析', '现金流与周转', '风险及行动', '财务表格', '范围与证据附注',
    ]);
    expect(documentToMarkdown(next)).not.toContain('自动');
  });

  it('applies a listed company template as a new draft and does not keep the local outline entry', async () => {
    const financeCall = vi.fn(async (_task: string, command: string) => {
      if (command === 'report-template-list') return success({ templates: [{ template_id: 'management-brief-v1', label: '经营简报', kind: 'word' }] });
      if (command === 'report-template-apply') return success({
        draft: {
          id: 'n'.repeat(32),
          title: '经营简报',
          document: { schema_version: 1, template_version: 'annual-v1', template_id: 'management-brief-v1', metadata: { company: '', period: '2026-08', currency: 'CNY', unit: '万元' }, content: [{ type: 'heading', attrs: { level: 1 }, content: [{ type: 'text', text: '经营简报' }] }] },
        },
      });
      return success({});
    });
    const onAppliedDraft = vi.fn();
    (globalThis as unknown as { foundry: unknown }).foundry = { financeCall };
    const handlers = mount({ body: '', document: { schema_version: 1, template_version: 'annual-v1', metadata: { company: '', period: '', currency: '', unit: '' }, content: [] }, onAppliedDraft, contextId: 'ctx-a' });
    fireEvent.click(screen.getByRole('button', { name: '套用公司模板' }));
    await screen.findByRole('button', { name: '经营简报 · word' });
    fireEvent.click(screen.getByRole('button', { name: '经营简报 · word' }));
    await waitFor(() => expect(financeCall).toHaveBeenCalledWith(taskId, 'report-template-apply', { template_id: 'management-brief-v1', context_id: 'ctx-a' }));
    expect(onAppliedDraft).toHaveBeenCalledWith(expect.objectContaining({ id: 'n'.repeat(32) }));
    expect(handlers.onDocument).not.toHaveBeenCalled();
  });

  it('loads PDF comparison from decoded data and does not leak data URLs in errors', async () => {
    const leakedDataUrl = 'data:application/pdf;base64,JVBERi0xLjQK';
    const failedLoad = new Promise((_, reject) => window.setTimeout(() => reject(new Error(`Unexpected server response (0) while retrieving PDF "${leakedDataUrl}"`)), 0));
    failedLoad.catch(() => undefined);
    pdfjsMock.getDocument.mockReturnValue({
      promise: failedLoad,
      destroy: vi.fn(),
    });
    const reportImport = vi.fn(async () => success<ReportImportResult>({
      source: { ...source, format: 'pdf', name: 'native-report.pdf' },
      title: 'native-report',
      document: documentFromMarkdown('# 管理摘要\nPDF 草稿已提取。\n'),
      warnings: [],
    }));
    const reportSource = vi.fn(async () => success({
      source: { ...source, format: 'pdf', name: 'native-report.pdf' },
      data_base64: 'JVBERi0xLjQK',
    }));
    (globalThis as unknown as { foundry: unknown }).foundry = { reportImport, reportSource };
    mount();

    fireEvent.click(screen.getByRole('button', { name: '导入' }));
    await waitFor(() => expect(pdfjsMock.getDocument).toHaveBeenCalled());
    const pdfArg = pdfjsMock.getDocument.mock.calls[0][0] as Record<string, unknown>;
    expect(pdfArg.url).toBeUndefined();
    expect(pdfArg.data).toBeInstanceOf(Uint8Array);
    expect(Array.from(pdfArg.data as Uint8Array)).toEqual(Array.from(new TextEncoder().encode('%PDF-1.4\n')));
    expect(pdfArg.isEvalSupported).toBe(false);
    await waitFor(() => expect(screen.getByRole('alert').textContent).toBe('PDF 原页暂时无法预览，可继续使用已提取的草稿内容。'));
    expect(screen.getByRole('alert').textContent).not.toContain('data:application/pdf;base64');
  });

  it('keeps the selected Excel sheet and range after rereading the import preview', async () => {
    const document = documentFromMarkdown('| 项目 | 金额 |\n| --- | --- |\n| 收入 | 1,234.50 |\n');
    const reportImport = vi.fn(async (_task: string, options?: Record<string, unknown>) => success<ReportImportResult>({
      source: { ...source, format: 'xlsx', name: '物业月结.xlsx' },
      title: options?.sheet === '04·合并利润表' ? '04·合并利润表 A1:F12' : '00·封面与编制说明',
      document,
      sheets: ['00·封面与编制说明', '04·合并利润表'],
      warnings: [],
    }));
    (globalThis as unknown as { foundry: unknown }).foundry = { reportImport };
    mount();

    fireEvent.click(screen.getByRole('button', { name: '导入' }));
    await waitFor(() => expect(screen.getByRole('combobox', { name: '导入工作表' })).toBeTruthy());
    const sheet = screen.getByRole('combobox', { name: '导入工作表' }) as HTMLSelectElement;
    const range = screen.getByLabelText('导入区域') as HTMLInputElement;

    fireEvent.change(sheet, { target: { value: '04·合并利润表' } });
    fireEvent.change(range, { target: { value: 'A1:F12' } });
    fireEvent.click(screen.getByRole('button', { name: '重新读取区域' }));

    await waitFor(() => expect(reportImport).toHaveBeenLastCalledWith(taskId, {
      sourceId: source.id,
      sheet: '04·合并利润表',
      range: 'A1:F12',
    }));
    expect((screen.getByRole('combobox', { name: '导入工作表' }) as HTMLSelectElement).value).toBe('04·合并利润表');
    expect((screen.getByLabelText('导入区域') as HTMLInputElement).value).toBe('A1:F12');
    const preview = screen.getByRole('region', { name: '导入预览' });
    expect(within(preview).getByRole('heading', { level: 3, name: '04·合并利润表 A1:F12' })).toBeTruthy();
  });

  it('reviews the numbers of an imported deck before adoption and leaves the document as imported', async () => {
    const document = documentFromMarkdown('## 第 1 页\n营业成本本月实际 820 万元。\n');
    const deck: ReportSource = { ...source, format: 'pptx', name: '八月月报.pptx' };
    const reportImport = vi.fn(async () => success<ReportImportResult>({
      source: deck, title: '八月月报.pptx', document, needsReview: true,
      warnings: ['PPT 导入只取文字和表格，图表、图片和版式不导入；数字需复核。'],
    }));
    const financeCall = vi.fn(async () => success<Record<string, unknown>>({
      id: 'f'.repeat(32),
      summary: { status: 'needs_attention', total: 1, match: 0, match_rounded: 0, match_scaled: 0, mismatch: 1, needs_review: 0 },
      items: [{ id: 'n1', text: '820 万元', value: '820', unit: '万元', status: 'mismatch', excerpt: '营业成本本月实际 820 万元。',
        location: { source_id: deck.id, page: '1', kind: 'paragraph' }, compared_value: '800', difference: '20',
        candidates: [{ kind: 'workbook', dataset_id: 'd'.repeat(32), sheet: '利润表', range: 'B5', label: '营业成本 · 本月实际', value: '800', unit: '万元' }] }],
      closing_note: '复核只比对数字，不判断表述是否恰当，也不代表报告可以对外发送。',
    }));
    (globalThis as unknown as { foundry: unknown }).foundry = { reportImport, financeCall };
    const handlers = mount();

    fireEvent.click(screen.getByRole('button', { name: '导入' }));
    const preview = await screen.findByRole('region', { name: '导入预览' });
    expect(within(preview).getByText(/PPT 导入只取文字和表格/)).toBeTruthy();
    fireEvent.click(within(preview).getByRole('button', { name: '复核数字' }));
    const result = await within(preview).findByRole('region', { name: '报告数字复核结果' });
    expect(financeCall).toHaveBeenCalledWith(taskId, 'report-review', { document });
    expect(within(result).getByText('来源：套表 利润表!B5 「营业成本 · 本月实际」 = 800 万元')).toBeTruthy();
    expect(within(result).getByText('第 1 页')).toBeTruthy();
    expect(handlers.onDocument).not.toHaveBeenCalled();
    expect(handlers.onReview).not.toHaveBeenCalled();

    fireEvent.click(within(preview).getByRole('button', { name: '采用此版本' }));
    expect(handlers.onDocument).toHaveBeenCalledWith(document);
  });

  it('previews, cancels, adopts, undoes and redoes deterministic paragraph reflow', async () => {
    const longParagraph = '管理层摘要显示，本期收入为1,234.50万元；预算为1,000.00万元，差异为234.50万元。现金流判断继续引用银行流水与应收明细，保持事实占位符 FACT-AR-001 和附注引用 [^1] 的原始顺序，不把未确认回款自动视为已收，也不补造管理层行动。后续说明只保留原始证据顺序，币种、期间、负号和单位都不改变。财务负责人补充说明，本段只做结构整理，不新增原因、行动或结论。';
    const original: ReportDocument = {
      schema_version: 1,
      template_version: 'annual-v1',
      metadata: { company: '华宸物业', period: '2026-08', currency: 'CNY', unit: '万元' },
      sources: [source],
      content: [
        { type: 'heading', attrs: { level: 1, source_id: source.id }, content: [{ type: 'text', text: '管理摘要' }] },
        { type: 'paragraph', attrs: { source_id: source.id, sheet: '摘要', range: 'A1:D9' }, content: [{ type: 'text', text: longParagraph }] },
        { type: 'table', attrs: { source_id: source.id, sheet: '利润表', range: 'A1:C3', caption: '利润表', period: '2026-08', currency: 'CNY', unit: '万元' }, content: [
          { type: 'tableRow', content: [cell('tableHeader', '项目'), cell('tableHeader', '金额')] },
          { type: 'tableRow', content: [cell('tableCell', '合并金额', { colspan: 2, source_id: source.id, range: 'A2:B2' })] },
        ] },
        { type: 'image', attrs: { source_id: source.id, src: png1x1, alt: '现金流趋势图' } },
        { type: 'reportNote', attrs: { id: '1' }, content: [{ type: 'paragraph', content: [{ type: 'text', text: '附注仍在章节末。' }] }] },
      ],
    };
    const handlers = mountStateful({ document: original, body: documentToMarkdown(original), initialMode: 'read' });

    fireEvent.click(screen.getByRole('button', { name: '整理段落' }));
    const previewRegion = screen.getByRole('region', { name: '段落整理预览' });
    expect(previewRegion.textContent).toContain('只按完整句、分号和已有换行拆段');
    expect(previewRegion.textContent).toContain('本次会整理 1 段，新增 4 个段落。');
    expect(handlers.current().document).toEqual(original);
    expect(handlers.onDocument).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: '取消整理' }));
    expect(screen.queryByRole('region', { name: '段落整理预览' })).toBeNull();
    expect(handlers.current().document).toEqual(original);

    fireEvent.click(screen.getByRole('button', { name: '整理段落' }));
    fireEvent.click(screen.getByRole('button', { name: '采用整理' }));

    await waitFor(() => expect(handlers.onDocument).toHaveBeenCalled());
    const adopted = handlers.current().document as ReportDocument;
    expect(handlers.current().review).toBe('unreviewed');
    expect(sourceParagraphs(adopted).map(textContent).join('')).toBe(longParagraph);
    expect(sourceParagraphs(adopted)).toHaveLength(5);
    expect(sourceParagraphs(adopted).every((node) => node.attrs?.source_id === source.id && node.attrs?.sheet === '摘要' && node.attrs?.range === 'A1:D9')).toBe(true);
    expect(JSON.stringify(adopted)).toContain('"colspan":2');
    expect(JSON.stringify(adopted)).toContain('现金流趋势图');
    expect(JSON.stringify(adopted)).toContain('reportNote');

    await waitFor(() => expect((screen.getByRole('button', { name: '撤销' }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole('button', { name: '撤销' }));
    await waitFor(() => expect(sourceParagraphs(handlers.current().document as ReportDocument)).toHaveLength(1));
    expect(sourceParagraphs(handlers.current().document as ReportDocument).map(textContent).join('')).toBe(longParagraph);

    await waitFor(() => expect((screen.getByRole('button', { name: '重做' }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole('button', { name: '重做' }));
    await waitFor(() => expect(sourceParagraphs(handlers.current().document as ReportDocument)).toHaveLength(5));
  });

  it('disables paragraph reflow for source mode, busy and empty reports without mutating content', () => {
    const document = documentFromMarkdown('# 管理摘要\n正文。\n');
    const sourceHandlers = mountStateful({ document, body: documentToMarkdown(document) });

    fireEvent.click(screen.getByRole('button', { name: 'Markdown 源码' }));
    expect((screen.getByRole('button', { name: '整理段落' }) as HTMLButtonElement).disabled).toBe(true);
    expect(sourceHandlers.current().document).toEqual(document);
    cleanup();

    mount({ busy: true });
    expect((screen.getByRole('button', { name: '整理段落' }) as HTMLButtonElement).disabled).toBe(true);
    cleanup();

    mount({ body: '', document: { schema_version: 1, template_version: 'annual-v1', metadata: { company: '', period: '', currency: '', unit: '' }, content: [] } });
    expect((screen.getByRole('button', { name: '整理段落' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('uses inline link controls and exposes cancellable report progress', async () => {
    const prompt = vi.spyOn(window, 'prompt').mockImplementation(() => 'https://bad.example');
    let progress!: (value: { task: string; phase: string }) => void;
    const reportCancel = vi.fn(async () => success({ cancelled: true }));
    const reportImport = vi.fn(async () => new Promise<Answer<ReportImportResult>>(() => undefined));
    (globalThis as unknown as { foundry: unknown }).foundry = { reportImport, reportCancel, onReportProgress: (cb: typeof progress) => { progress = cb; return vi.fn(); } };
    mount();

    fireEvent.click(screen.getByRole('button', { name: '链接' }));
    expect(screen.getByLabelText('链接地址')).toBeTruthy();
    expect(prompt).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: '导入' }));
    await waitFor(() => expect(screen.getByText('正在导入转换')).toBeTruthy());
    act(() => progress({ task: taskId, phase: '解析 PDF 原页' }));
    expect(screen.getByText('解析 PDF 原页')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '取消转换' }));
    await waitFor(() => expect(reportCancel).toHaveBeenCalledWith(taskId));
  });

  it('records a draft table circle-select as an invoice-basis revision', async () => {
    const financeCall = vi.fn(async (_task: string, command: string) => {
      if (command === 'analysis-circle-select') return success({ id: 'req-new', change_reason: '改成开票口径' });
      return success({});
    });
    (globalThis as unknown as { foundry: unknown }).foundry = { financeCall };
    const document: ReportDocument = {
      schema_version: 1,
      template_version: 'annual-v1',
      metadata: { company: '华宸物业', period: '2026-08', currency: 'CNY', unit: '万元' },
      sources: [source],
      content: [
        { type: 'heading', attrs: { level: 1 }, content: [{ type: 'text', text: '管理摘要' }] },
        { type: 'table', attrs: { caption: '利润表' }, content: [
          { type: 'tableRow', content: [cell('tableHeader', '项目'), cell('tableHeader', '金额')] },
          { type: 'tableRow', content: [cell('tableCell', '收入'), cell('tableCell', '30')] },
        ] },
      ],
    };
    mount({
      document,
      body: documentToMarkdown(document),
      draftId: 'f'.repeat(32),
      contextId: 'ctx-a',
    });
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
    fireEvent.click(screen.getByText('收入'));
    const circle = await screen.findByRole('button', { name: '改成开票口径' });
    expect((circle as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(circle);
    await waitFor(() => expect(financeCall).toHaveBeenCalledWith(taskId, 'analysis-circle-select', expect.objectContaining({
      kind: 'draft_table',
      draft_id: 'f'.repeat(32),
      block_id: '利润表',
      instruction: '改成开票口径',
      context_id: 'ctx-a',
    })));
    expect(await screen.findByText('已按圈选生成开票口径修订。')).toBeTruthy();
  });

  it('refuses circle-select until the selected table has a caption', async () => {
    const financeCall = vi.fn(async () => success({}));
    (globalThis as unknown as { foundry: unknown }).foundry = { financeCall };
    const document: ReportDocument = {
      schema_version: 1,
      template_version: 'annual-v1',
      metadata: { company: '华宸物业', period: '2026-08', currency: 'CNY', unit: '万元' },
      sources: [source],
      content: [
        { type: 'table', content: [
          { type: 'tableRow', content: [cell('tableHeader', '项目'), cell('tableHeader', '金额')] },
          { type: 'tableRow', content: [cell('tableCell', '费用'), cell('tableCell', '20')] },
        ] },
      ],
    };
    mount({ document, body: documentToMarkdown(document), draftId: 'f'.repeat(32), contextId: 'ctx-a' });
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
    fireEvent.click(screen.getByText('费用'));
    fireEvent.click(screen.getByRole('button', { name: '改成开票口径' }));
    expect(await screen.findByText('请先给表加上标题再圈选调整。')).toBeTruthy();
    expect(financeCall).not.toHaveBeenCalled();
  });

});


function validateWithPython(document: ReportDocument): { document: ReportDocument; markdown: string } {
  const python = existsSync(resolve(repoRoot, '.venv/bin/python')) ? resolve(repoRoot, '.venv/bin/python') : 'python3';
  const script = [
    'import json, os, sys',
    'from foundry.report_documents import report_document_markdown, validate_report_document',
    'document = json.load(sys.stdin)',
    'registered = set(json.loads(os.environ.get("REGISTERED_SOURCES", "[]")))',
    'clean = validate_report_document(document, registered_source_ids=registered)',
    'print(json.dumps({"document": clean, "markdown": report_document_markdown(clean)}, ensure_ascii=False))',
  ].join('\n');
  const result = spawnSync(python, ['-c', script], {
    cwd: repoRoot,
    input: JSON.stringify(document),
    encoding: 'utf8',
    env: { ...process.env, PYTHONPATH: repoRoot, REGISTERED_SOURCES: JSON.stringify(document.sources?.map((item) => item.id) ?? []) },
    maxBuffer: 2 * 1024 * 1024,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(result.stderr || result.stdout);
  return JSON.parse(result.stdout) as { document: ReportDocument; markdown: string };
}

function cell(type: 'tableHeader' | 'tableCell', text: string, attrs: Record<string, unknown> = {}) {
  return { type, attrs: { source_id: source.id, ...attrs }, content: [{ type: 'paragraph', content: [{ type: 'text', text }] }] };
}


function sourceParagraphs(document: ReportDocument): ReportNode[] {
  return document.content.filter((node) => node.type === 'paragraph' && node.attrs?.sheet === '摘要' && node.attrs?.range === 'A1:D9');
}

function textContent(node: ReportNode): string {
  if (node.type === 'text') return node.text ?? '';
  return (node.content ?? []).map(textContent).join('');
}

const png1x1 = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=';
