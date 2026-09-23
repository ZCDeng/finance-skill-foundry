import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import * as path from 'node:path';
import { createHash } from 'node:crypto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ call: vi.fn(), open: vi.fn(), save: vi.fn(), printOptions: undefined as any, lastWindow: undefined as any }));
vi.mock('electron', () => ({
  app: { getAppPath: () => process.cwd() },
  BrowserWindow: class {
    destroyed = false;
    webContents = {
      session: {
        setPermissionRequestHandler: vi.fn(),
        webRequest: { onBeforeRequest: vi.fn() },
        clearStorageData: vi.fn(async () => undefined),
      },
      setWindowOpenHandler: vi.fn(),
      on: vi.fn(),
      executeJavaScript: vi.fn(async (script: string) => script === 'document.title' ? '正式<title>&报告' : undefined),
      printToPDF: vi.fn(async (options: any) => { mocks.printOptions = options; return Buffer.from('pdf'); }),
    };
    constructor() { mocks.lastWindow = this; }
    async loadURL(_url: string) { return undefined; }
    isDestroyed() { return this.destroyed; }
    destroy() { this.destroyed = true; }
  },
  dialog: { showOpenDialog: mocks.open, showSaveDialog: mocks.save },
}));
vi.mock('../electron/foundry.js', () => ({ runFoundryJson: mocks.call }));
vi.mock('node:worker_threads', () => ({
  Worker: class {
    private listeners = new Map<string, Function[]>();
    constructor(_filename: string, options: any) {
      setTimeout(() => {
        const payload = options.workerData.payload;
        const value = `<html><body>${payload.options?.marker ?? ''}</body></html>`;
        this.emit('message', { ok: true, value });
      }, 0);
    }
    once(event: string, listener: Function) { this.listeners.set(event, [...(this.listeners.get(event) ?? []), listener]); return this; }
    terminate() { return Promise.resolve(0); }
    private emit(event: string, value: unknown) { for (const listener of this.listeners.get(event) ?? []) listener(value); }
  },
}));
import { ReportHost, appendOcrDraft, printReportPdf, reportFormat, sourceId } from '../electron/reports/host.js';
import { createReportDocument } from '../electron/reports/format.js';
import type { ReportImportResult, ReportProjection, ReportSource } from '../electron/reports/model.js';

const task = 'a'.repeat(32), source = { id: 'b'.repeat(32), name: '报告.md', format: 'md', sha256: '' };
let directory: string;
beforeEach(async () => { vi.clearAllMocks(); directory = await mkdtemp(path.join(tmpdir(), 'report-host-test-')); });
afterEach(async () => { await rm(directory, { recursive: true, force: true }); });

function projection(document = createReportDocument()): ReportProjection {
  return {
    schema_version: 1,
    draft_id: 'draft',
    title: '财务报告',
    content_hash: 'c'.repeat(64),
    projection_hash: 'd'.repeat(64),
    content_mode: 'management',
    publication_status: 'draft',
    review_status: 'unreviewed',
    reproducibility_status: 'unverified',
    marker: '分析草稿·待复核',
    body: '分析草稿·待复核\n\n# 财务报告\n\n金额 123.4500\n',
    document,
  };
}

describe('document boundary and task ownership', () => {
  it('keeps page-located PDF text when OCR returns an unlocated supplemental draft', () => {
    const pdfSource: ReportSource = { ...source, format: 'pdf' };
    const page = { type: 'paragraph', attrs: { source_id: source.id, page: '3' }, content: [{ type: 'text', text: '原页 123.4500' }] };
    const result: ReportImportResult = { document: createReportDocument([page]), warnings: [] };
    const extra: ReportImportResult = { document: createReportDocument([{ type: 'paragraph', content: [{ type: 'text', text: '补充内容' }] }]), warnings: ['图片未识别'] };
    appendOcrDraft(result, extra, pdfSource);
    expect(result.document?.content[0]).toEqual(page);
    expect(result.document?.content[2].attrs?.source_id).toBe(source.id);
    expect(result.document?.content[1].content?.[0].text).toContain('页码未知');
    expect(result.warnings.join(' ')).toContain('保留原页');
    expect(result.warnings).toContain('图片未识别');
    expect(result.needsReview).toBe(true);
  });

  it('prints the draft marker before an escaped title in every PDF page header', async () => {
    const pdf = await printReportPdf('<!doctype html><title>正式&lt;title&gt;&amp;报告</title><body>正文</body>', new AbortController().signal, '分析草稿<待复核>&');

    expect(pdf.toString()).toBe('pdf');
    expect(mocks.printOptions.headerTemplate).toBe('<div></div>');
    const injected = mocks.lastWindow.webContents.executeJavaScript.mock.calls.map((call: [string]) => call[0]).join('\n');
    expect(injected).toContain('@top-left');
    expect(injected).toContain('font: 9pt');
    expect(injected).toContain('Noto Sans SC');
    expect(injected).toContain('sans-serif');
    expect(injected).toContain('data-fa-report-print-header');
    expect(injected).toContain('content:');
    expect(injected).toContain('分析草稿<待复核>& · 正式<title>&报告');
    expect(injected).not.toContain('position: fixed');
  });
  it('does not accept paths or arbitrary formats from a renderer', async () => {
    const host = new ReportHost({ varRoot: '/store' });
    await expect(host.import(task, { path: '/secret' } as any)).rejects.toThrow('无效');
    await expect(host.source(task, '../secret')).rejects.toThrow('无效');
    expect(() => reportFormat('exe')).toThrow();
    expect(() => sourceId('b'.repeat(31))).toThrow();
    expect(mocks.call).not.toHaveBeenCalled();
  });
  it('cancelling the native import picker creates no source snapshot', async () => {
    mocks.open.mockResolvedValue({ canceled: true, filePaths: [] });
    const host = new ReportHost({ varRoot: '/store' });
    expect(await host.import(task)).toEqual({ cancelled: true, warnings: [] });
    expect(mocks.call).not.toHaveBeenCalled();
  });
  it('checks the actual source bytes before giving the original to the viewer', async () => {
    const original = path.join(directory, 'source.md');
    await writeFile(original, '收入 123.4500 万元');
    const data = await readFile(original);
    const receipt = { ...source, sha256: createHash('sha256').update(data).digest('hex') };
    mocks.call.mockResolvedValue({ source: receipt, path: original });
    const host = new ReportHost({ varRoot: '/store' });
    expect((await host.source(task, source.id)).data_base64).toBe(data.toString('base64'));
    expect(mocks.call).toHaveBeenCalledWith({ varRoot: '/store', task }, 'report-source-read', ['--source', source.id], { signal: undefined });
    await writeFile(original, 'tampered');
    await expect(host.source(task, source.id)).rejects.toThrow('校验失败');
  });
  it('shows save destination before export and copies only the backend archived bytes', async () => {
    const archive = path.join(directory, 'archive.md'), chosen = path.join(directory, 'chosen.md');
    await writeFile(archive, '# 财务报告\n\n金额 123.4500');
    mocks.save.mockResolvedValue({ canceled: false, filePath: chosen });
    mocks.call.mockImplementation(async (_binding, command) => command === 'report-projection-read'
      ? projection() : { path: archive, sha256: 'receipt', projection_hash: 'd'.repeat(64), content_mode: 'management' });
    const host = new ReportHost({ varRoot: '/store' });
    const result = await host.export(task, 'draft', 'md');
    expect(await readFile(chosen, 'utf8')).toBe(await readFile(archive, 'utf8'));
    expect(result).toMatchObject({ path: chosen, archived_path: archive, sha256: 'receipt', projection_hash: 'd'.repeat(64), content_mode: 'management' });
    expect(mocks.call.mock.calls.map((call) => call[1])).toEqual(['report-projection-read', 'analysis-export']);
    expect(mocks.call.mock.calls[0][2]).toEqual(['--draft', 'draft', '--mode', 'management']);
    expect(mocks.call.mock.calls[1][2]).toEqual(['--draft', 'draft', '--format', 'md', '--mode', 'management']);
  });
  it('cancelled save creates no export record and releases the task job', async () => {
    mocks.call.mockResolvedValue(projection());
    mocks.save.mockResolvedValue({ canceled: true });
    const host = new ReportHost({ varRoot: '/store' });
    expect(await host.export(task, 'draft', 'pdf')).toEqual({ cancelled: true });
    expect(await host.export(task, 'draft', 'docx')).toEqual({ cancelled: true });
    expect(mocks.call.mock.calls.map((call) => call[1])).toEqual(['report-projection-read', 'report-projection-read']);
    expect(host.cancel(task)).toEqual({ cancelled: false });
  });
  it('renders converter formats from the immutable projection and registers its identity', async () => {
    const chosen = path.join(directory, 'chosen.html');
    mocks.save.mockResolvedValue({ canceled: false, filePath: chosen });
    mocks.call.mockImplementation(async (_binding, command, args) => {
      if (command === 'report-projection-read') return projection(createReportDocument([{ type: 'paragraph', content: [{ type: 'text', text: '金额 123.4500' }] }]));
      expect(args).toEqual(['--draft', 'draft', '--format', 'html', '--path', expect.any(String), '--mode', 'management', '--projection-hash', 'd'.repeat(64)]);
      return { path: args[5], sha256: 'receipt', projection_hash: 'd'.repeat(64), content_mode: 'management' };
    });
    const host = new ReportHost({ varRoot: '/store' });
    const result = await host.export(task, 'draft', 'html');
    expect(await readFile(chosen, 'utf8')).toContain('分析草稿·待复核');
    expect(result).toMatchObject({ content_mode: 'management', projection_hash: 'd'.repeat(64) });
    expect(mocks.call.mock.calls.map((call) => call[1])).toEqual(['report-projection-read', 'report-export-register']);
  });

  it('passes the projection marker into PDF page headers before registering the export', async () => {
    const chosen = path.join(directory, 'chosen.pdf');
    const fontPath = path.join(directory, 'dsh/assets/fonts/NotoSansSC-variable.woff2');
    await mkdir(path.dirname(fontPath), { recursive: true });
    await writeFile(fontPath, 'font');
    Object.defineProperty(process, 'resourcesPath', { value: directory, configurable: true });
    mocks.save.mockResolvedValue({ canceled: false, filePath: chosen });
    mocks.call.mockImplementation(async (_binding, command, args) => {
      if (command === 'report-projection-read') return projection(createReportDocument([{ type: 'paragraph', content: [{ type: 'text', text: '金额 123.4500' }] }]));
      expect(args).toEqual(['--draft', 'draft', '--format', 'pdf', '--path', expect.any(String), '--mode', 'management', '--projection-hash', 'd'.repeat(64)]);
      return { path: args[5], sha256: 'receipt', projection_hash: 'd'.repeat(64), content_mode: 'management' };
    });
    const host = new ReportHost({ varRoot: '/store' });
    const result = await host.export(task, 'draft', 'pdf');

    expect(await readFile(chosen, 'utf8')).toBe('pdf');
    expect(mocks.printOptions.headerTemplate).toBe('<div></div>');
    const injected = mocks.lastWindow.webContents.executeJavaScript.mock.calls.map((call: [string]) => call[0]).join('\n');
    expect(injected).toContain('@top-left');
    expect(injected).toContain('font: 9pt');
    expect(injected).toContain('Noto Sans SC');
    expect(injected).toContain('sans-serif');
    expect(injected).toContain('content:');
    expect(injected).toContain('分析草稿·待复核 · 正式<title>&报告');
    expect(injected).not.toContain('position: fixed');
    expect(result).toMatchObject({ content_mode: 'management', projection_hash: 'd'.repeat(64) });
  });
  it('refuses overlapping work for the same task instead of overwriting cancellation state', async () => {
    let release!: (value: unknown) => void;
    mocks.open.mockReturnValue(new Promise((resolve) => { release = resolve; }));
    const host = new ReportHost({ varRoot: '/store' });
    const pending = host.import(task);
    await expect(host.import(task)).rejects.toThrow('正在转换');
    release({ canceled: true, filePaths: [] });
    await pending;
  });
});
