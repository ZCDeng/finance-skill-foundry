import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import * as path from 'node:path';
import { createHash } from 'node:crypto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ call: vi.fn(), open: vi.fn(), save: vi.fn() }));
vi.mock('electron', () => ({ app: {}, BrowserWindow: class {}, dialog: { showOpenDialog: mocks.open, showSaveDialog: mocks.save } }));
vi.mock('../electron/foundry.js', () => ({ runFoundryJson: mocks.call }));
import { ReportHost, appendOcrDraft, reportFormat, sourceId } from '../electron/reports/host.js';
import { createReportDocument } from '../electron/reports/format.js';
import type { ReportImportResult, ReportSource } from '../electron/reports/model.js';

const task = 'a'.repeat(32), source = { id: 'b'.repeat(32), name: '报告.md', format: 'md', sha256: '' };
let directory: string;
beforeEach(async () => { vi.clearAllMocks(); directory = await mkdtemp(path.join(tmpdir(), 'report-host-test-')); });
afterEach(async () => { await rm(directory, { recursive: true, force: true }); });

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
    mocks.call.mockImplementation(async (_binding, command) => command === 'report-draft-read'
      ? { title: '财务报告', body: '金额 123.4500' } : { path: archive, sha256: 'receipt' });
    const host = new ReportHost({ varRoot: '/store' });
    const result = await host.export(task, 'draft', 'md');
    expect(await readFile(chosen, 'utf8')).toBe(await readFile(archive, 'utf8'));
    expect(result).toMatchObject({ path: chosen, archived_path: archive, sha256: 'receipt' });
    expect(mocks.call.mock.calls.map((call) => call[1])).toEqual(['report-draft-read', 'analysis-export']);
  });
  it('cancelled save creates no export record and releases the task job', async () => {
    mocks.call.mockResolvedValue({ title: '报告', body: '原文' });
    mocks.save.mockResolvedValue({ canceled: true });
    const host = new ReportHost({ varRoot: '/store' });
    expect(await host.export(task, 'draft', 'pdf')).toEqual({ cancelled: true });
    expect(await host.export(task, 'draft', 'docx')).toEqual({ cancelled: true });
    expect(mocks.call.mock.calls.map((call) => call[1])).toEqual(['report-draft-read', 'report-draft-read']);
    expect(host.cancel(task)).toEqual({ cancelled: false });
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
