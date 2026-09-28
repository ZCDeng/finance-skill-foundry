import { app, BrowserWindow, dialog } from 'electron';
import { Worker } from 'node:worker_threads';
import { copyFile, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import * as path from 'node:path';
import { createHash, randomUUID } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import { type Binding, FOUNDRY_MAX_BUFFER, runFoundryJson, runFoundryJsonSized } from '../foundry.js';
import type { ReportDocument, ReportFormat, ReportImportOptions, ReportImportResult, ReportProjection, ReportProjectionMode, ReportSource } from './model.js';
import { ocrDocument } from './ocr.js';
import { localReportResources } from './resources.js';
import { materializeReportVisualsForDocx } from './visual-raster.js';
import { reportVisualEvidence } from './visual-evidence.js';

const MAX_BYTES = 32 * 1024 * 1024;
const FORMATS = new Set<ReportFormat>(['docx', 'pdf', 'html', 'md', 'xlsx']);
const MODES = new Set<ReportProjectionMode>(['management', 'audit']);
export function reportFormat(value: unknown): ReportFormat {
  if (!FORMATS.has(value as ReportFormat)) throw new Error('不支持的文稿格式。');
  return value as ReportFormat;
}
function reportMode(value: unknown): ReportProjectionMode {
  if (!MODES.has(value as ReportProjectionMode)) throw new Error('不支持的文稿模式。');
  return value as ReportProjectionMode;
}
export function sourceId(value: unknown): string {
  if (typeof value !== 'string' || !/^[a-f0-9]{32}$/.test(value)) throw new Error('无效的文稿来源。');
  return value;
}
function assertDocument(value: unknown, room = 0): asserts value is ReportDocument {
  if (!value || typeof value !== 'object' || (value as ReportDocument).schema_version !== 1
    || !Array.isArray((value as ReportDocument).content) || Buffer.byteLength(JSON.stringify(value)) > MAX_BYTES + room) {
    throw new Error('文稿结构无效或超过容量。');
  }
}
/** Bytes the server's estimate declaration and labels add to a projection, which the size limits do not count. */
export function estimateRoom(projection: ReportProjection): number {
  const bytes = projection.estimate_headroom?.bytes;
  return typeof bytes === 'number' && Number.isSafeInteger(bytes) && bytes > 0 ? Math.min(bytes, MAX_BYTES) : 0;
}
function assertProjection(value: unknown): asserts value is ReportProjection {
  if (!value || typeof value !== 'object' || (value as ReportProjection).schema_version !== 1
    || typeof (value as ReportProjection).projection_hash !== 'string'
    || !/^[a-f0-9]{64}$/.test((value as ReportProjection).projection_hash)
    || !MODES.has((value as ReportProjection).content_mode)
    || typeof (value as ReportProjection).title !== 'string'
    || typeof (value as ReportProjection).body !== 'string') {
    throw new Error('文稿导出投影无效。');
  }
  assertDocument((value as ReportProjection).document, estimateRoom(value as ReportProjection));
}
function aborted(signal: AbortSignal) { if (signal.aborted) throw new Error('已取消文档转换。'); }

export function conversion<T>(operation: string, payload: unknown, signal: AbortSignal): Promise<T> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(new Error('已取消文档转换。'));
    const worker = new Worker(path.join(__dirname, 'worker.js'), { workerData: { operation, payload }, resourceLimits: { maxOldGenerationSizeMb: 384 } });
    let finished = false;
    const done = (error?: Error, value?: T) => {
      if (finished) return;
      finished = true; clearTimeout(timer); signal.removeEventListener('abort', cancel);
      void worker.terminate();
      if (error) reject(error); else resolve(value as T);
    };
    const cancel = () => done(new Error('已取消文档转换。'));
    const timer = setTimeout(() => done(new Error('文档转换超时，请按章节拆分后重试。')), 180_000);
    signal.addEventListener('abort', cancel, { once: true });
    worker.once('message', (message) => message.ok ? done(undefined, message.value) : done(new Error(message.message)));
    worker.once('error', (error) => done(error instanceof Error ? error : new Error(String(error))));
    worker.once('exit', (code) => { if (!finished) done(new Error(`转换进程提前退出（${code}）。`)); });
  });
}

let font: Promise<string> | undefined;
async function fontData(): Promise<string> {
  font ??= (async () => {
    const candidates = [path.join(process.resourcesPath, 'dsh/assets/fonts/NotoSansSC-variable.woff2'),
      path.join(app.getAppPath(), 'src/assets/fonts/noto-sans-sc/NotoSansSC-variable.woff2')];
    for (const candidate of candidates) {
      try { return `data:font/woff2;base64,${(await readFile(candidate)).toString('base64')}`; } catch { /* Try the development font after packaged location. */ }
    }
    throw new Error('缺少离线中文字体，无法生成可靠的打印文稿。');
  })();
  return font;
}

let wordFont: Promise<Buffer> | undefined;
async function docxFontData(): Promise<Buffer> {
  wordFont ??= (async () => {
    for (const candidate of [path.join(process.resourcesPath, 'fonts/NotoSansSC-report.ttf'),
      path.join(app.getAppPath(), 'src/assets/fonts/noto-sans-sc/NotoSansSC-report.ttf')]) {
      try { return await readFile(candidate); } catch { /* Try the development resource. */ }
    }
    throw new Error('缺少 Word 内嵌中文字体，无法生成完整文稿。');
  })();
  return wordFont;
}

/** OCR without a page map supplements the page-located extraction; it never replaces it. */
export function appendOcrDraft(result: ReportImportResult, supplement: ReportImportResult, source: ReportSource): void {
  const document = result.document ?? supplement.document;
  if (!document || !supplement.document) return;
  const original = result.document?.content ?? [];
  result.document = { ...document, sources: [source], content: [
    ...original,
    { type: 'heading', attrs: { level: 2, source_id: source.id }, content: [{ type: 'text', text: 'OCR 补充草稿（页码未知，需核对）' }] },
    ...supplement.document.content.map((node) => ({ ...node, attrs: { ...node.attrs, source_id: source.id } })),
  ] };
  result.warnings.push(...supplement.warnings, 'OCR 未提供逐页定位；已保留原页抽取内容，补充草稿需与原 PDF 核对后采用。');
  result.needsReview = true;
}

/** A private renderer prints only our escaped template, with no preload, network or navigation. */
export async function printReportPdf(html: string, signal: AbortSignal, marker = ''): Promise<Buffer> {
  aborted(signal);
  const scratch = await mkdtemp(path.join(tmpdir(), 'fa-report-print-'));
  const entry = pathToFileURL(path.join(scratch, 'report.html')).href;
  await writeFile(path.join(scratch, 'report.html'), html, { mode: 0o600 });
  const window = new BrowserWindow({ show: false, width: 1000, height: 1400, webPreferences: {
    sandbox: true, contextIsolation: true, nodeIntegration: false, partition: `report-print-${randomUUID()}`,
  } });
  const session = window.webContents.session;
  session.setPermissionRequestHandler((_web, _permission, callback) => callback(false));
  session.webRequest.onBeforeRequest({ urls: ['http://*/*', 'https://*/*', 'file://*/*'] }, (details, callback) => callback({ cancel: details.url !== entry }));
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  window.webContents.on('will-navigate', (event) => event.preventDefault());
  const cancel = () => { if (!window.isDestroyed()) window.destroy(); };
  signal.addEventListener('abort', cancel, { once: true });
  try {
    await window.loadURL(entry);
    await window.webContents.executeJavaScript(`(async () => {
      await document.fonts.ready;
      await Promise.all(Array.from(document.images, image => image.decode()));
      if (!document.fonts.check('11pt "Noto Sans SC"', '财务报告')) throw new Error('中文字体未加载');
    })()`);
    const rawTitle = String(await window.webContents.executeJavaScript('document.title'));
    const reportTitle = escapePdfHeaderText(rawTitle);
    if (marker) await injectPrintablePageMarginHeader(window, `${marker} · ${rawTitle}`);
    aborted(signal);
    return await window.webContents.printToPDF({ pageSize: 'A4', printBackground: true, preferCSSPageSize: true,
      displayHeaderFooter: true, margins: { top: 20 / 25.4, bottom: 20 / 25.4, left: 20 / 25.4, right: 20 / 25.4 },
      headerTemplate: marker ? '<div></div>' : `<div style="font:9pt sans-serif;margin:0 20mm;width:170mm;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#666">${reportTitle}</div>`,
      footerTemplate: '<div style="font:9pt sans-serif;width:100%;text-align:center;color:#666"><span class="pageNumber"></span> / <span class="totalPages"></span></div>',
    });
  } finally {
    signal.removeEventListener('abort', cancel);
    if (!window.isDestroyed()) window.destroy();
    await session.clearStorageData();
    await rm(scratch, { recursive: true, force: true });
  }
}



async function injectPrintablePageMarginHeader(window: BrowserWindow, text: string): Promise<void> {
  const header = text.length > 96 ? `${text.slice(0, 95)}…` : text;
  await window.webContents.executeJavaScript(`(() => {
    const existingStyle = document.querySelector('[data-fa-report-print-header="style"]');
    if (existingStyle) existingStyle.remove();
    const style = document.createElement('style');
    style.setAttribute('data-fa-report-print-header', 'style');
    style.textContent = ${JSON.stringify(`
      @page {
        margin: 20mm;
        @top-left {
          content: ${cssString(header)};
          color: #666;
          font: 9pt "Noto Sans SC", sans-serif;
        }
      }
    `)};
    document.head.appendChild(style);
  })()`);
}

function cssString(value: string): string {
  return `"${value.replace(/[\\\"\n\r\f]/g, (char) => ({ '\\': '\\\\', '"': '\\"', '\n': '\\A ', '\r': '\\A ', '\f': '\\A ' }[char]!))}"`;
}

function escapePdfHeaderText(value: string): string {
  return value.replace(/[&<>\"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '\"': '&quot;', "'": '&#39;' }[char]!));
}

type Job = { controller: AbortController; committing: boolean };
export class ReportHost {
  private jobs = new Map<string, Job>();
  constructor(private binding: Omit<Binding, 'task' | 'session'>, private progress: (task: string, phase: string) => void = () => {}) {}
  cancel(task: string) {
    const job = this.jobs.get(task);
    if (job?.committing) return { cancelled: false, finishing: true };
    job?.controller.abort(); return { cancelled: Boolean(job) };
  }
  private async job<T>(task: string, work: (signal: AbortSignal, commit: () => void) => Promise<T>): Promise<T> {
    if (this.jobs.has(task)) throw new Error('此任务正在转换文档，请等待完成或先取消。');
    const job: Job = { controller: new AbortController(), committing: false };
    this.jobs.set(task, job);
    try { return await work(job.controller.signal, () => { aborted(job.controller.signal); job.committing = true; }); }
    finally { this.jobs.delete(task); this.progress(task, ''); }
  }
  private call<T>(task: string, command: string, args: string[] = [], signal?: AbortSignal): Promise<T> {
    return runFoundryJson<T>({ ...this.binding, task }, command, args, { signal });
  }
  async source(task: string, id: unknown) {
    const result = await this.call<{ source: ReportSource; path: string }>(task, 'report-source-read', ['--source', sourceId(id)]);
    const data = await readFile(result.path);
    if (data.length > MAX_BYTES || createHash('sha256').update(data).digest('hex') !== result.source.sha256) throw new Error('文稿来源校验失败。');
    return { source: result.source, data_base64: data.toString('base64') };
  }
  async import(task: string, options: ReportImportOptions = {}): Promise<ReportImportResult> {
    if (!options || typeof options !== 'object' || Object.keys(options).some((key) => !['sourceId', 'sheet', 'range', 'ocr'].includes(key))) throw new Error('无效的文稿导入选项。');
    if (options.ocr !== undefined && typeof options.ocr !== 'boolean') throw new Error('无效的识别选项。');
    return this.job(task, async (signal) => {
      let snapshot: { source: ReportSource; path: string };
      let selectedPath: string | undefined;
      if (options.sourceId) snapshot = await this.call(task, 'report-source-read', ['--source', sourceId(options.sourceId)], signal);
      else {
        const selected = await dialog.showOpenDialog({ title: '导入财务文稿', properties: ['openFile'], filters: [{ name: '财务文稿', extensions: [...FORMATS] }] });
        if (selected.canceled || !selected.filePaths[0]) return { cancelled: true, warnings: [] };
        selectedPath = selected.filePaths[0];
        aborted(signal); this.progress(task, '保存原始文件');
        snapshot = await this.call(task, 'report-source-add', ['--path', selected.filePaths[0]], signal);
      }
      aborted(signal); this.progress(task, '解析文稿结构');
      if (snapshot.source.format === 'xlsx') {
        const args = ['--source', snapshot.source.id];
        for (const key of ['sheet', 'range'] as const) if (options[key] !== undefined) {
          if (typeof options[key] !== 'string' || options[key]!.length > 200) throw new Error('无效的工作表或区域。');
          args.push(`--${key}`, options[key]!);
        }
        return this.call<ReportImportResult>(task, 'report-xlsx-read', args, signal);
      }
      const data = await readFile(snapshot.path);
      if (data.length > MAX_BYTES || createHash('sha256').update(data).digest('hex') !== snapshot.source.sha256) throw new Error('原始文件校验失败。');
      let resources: Record<string, string> = {};
      if (selectedPath && ['html', 'md'].includes(snapshot.source.format)) {
        const references = await conversion<string[]>('resource-references', { data, format: snapshot.source.format }, signal);
        resources = await localReportResources(selectedPath, references, signal);
      }
      const result = await conversion<ReportImportResult>('import', { data, format: snapshot.source.format, source: snapshot.source, resources }, signal);
      if (snapshot.source.format === 'pdf' && (options.ocr || result.needsReview)) {
        this.progress(task, '检查本机 OCR 识别服务');
        const ocr = await ocrDocument(snapshot.path, signal);
        if (ocr.markdown) {
          const supplement = await conversion<ReportImportResult>('import', {
            data: Buffer.from(ocr.markdown), format: 'md', source: snapshot.source,
          }, signal);
          appendOcrDraft(result, supplement, snapshot.source);
        }
        if (ocr.warning) result.warnings.push(ocr.warning);
      }
      aborted(signal);
      return { ...result, source: snapshot.source };
    });
  }
  async preview(task: string, document: unknown, title: unknown): Promise<{ html: string }> {
    assertDocument(document);
    if (typeof title !== 'string' || title.length > 1000) throw new Error('文稿标题无效。');
    return this.job(task, async (signal) => {
      this.progress(task, '生成打印预览');
      return { html: await conversion<string>('html', { document, title, options: { print: true, fontDataUrl: await fontData() } }, signal) };
    });
  }
  async export(task: string, id: string, rawFormat: unknown, rawMode: unknown = 'management'): Promise<Record<string, unknown>> {
    const format = reportFormat(rawFormat);
    const mode = reportMode(rawMode);
    return this.job(task, async (signal, commit) => {
      // Read with room for the estimate declaration, then hold everything else to the usual 32 MiB (issue #32).
      const { value: projection, bytes } = await runFoundryJsonSized<ReportProjection>(
        { ...this.binding, task }, 'report-projection-read', ['--draft', id, '--mode', mode],
        { signal, maxBuffer: 2 * FOUNDRY_MAX_BUFFER });
      assertProjection(projection);
      if (bytes - estimateRoom(projection) > FOUNDRY_MAX_BUFFER) throw new Error('文稿导出投影超过容量，请拆分图片或章节。');
      const selected = await dialog.showSaveDialog({ title: '导出财务文稿', defaultPath: `${projection.title.replace(/[\\/:*?"<>|\u0000-\u001f]/g, '_').slice(0, 100)}-${projection.content_mode}.${format}`,
        filters: [{ name: format.toUpperCase(), extensions: [format] }] });
      if (selected.canceled || !selected.filePath) return { cancelled: true };
      aborted(signal); this.progress(task, '生成导出文件');
      const scratch = await mkdtemp(path.join(tmpdir(), 'fa-report-export-'));
      try {
        let archived: { path: string; [key: string]: unknown };
        if (format === 'md' || format === 'xlsx') {
          commit();
          archived = await this.call(task, 'analysis-export', ['--draft', id, '--format', format, '--mode', projection.content_mode]);
        } else {
          let data: Buffer;
          const renderOptions = { marker: projection.marker, contentMode: projection.content_mode, projectionHash: projection.projection_hash, draftId: projection.draft_id, contentHash: projection.content_hash, publicationStatus: projection.publication_status, reviewStatus: projection.review_status, reproducibilityStatus: projection.reproducibility_status, sources: projection.sources ?? [] };
          if (format === 'docx') {
            const document = await materializeReportVisualsForDocx(projection.document, await fontData(), signal);
            data = Buffer.from(await conversion<Uint8Array>('docx', { document, title: projection.title, fontData: await docxFontData(), options: { ...renderOptions, visualSources: reportVisualEvidence(projection.document) } }, signal));
          }
          else {
            const html = await conversion<string>('html', { document: projection.document, title: projection.title, options: { print: format === 'pdf', fontDataUrl: await fontData(), ...renderOptions } }, signal);
            data = format === 'pdf' ? await printReportPdf(html, signal, projection.marker) : Buffer.from(html);
          }
          aborted(signal);
          const temp = path.join(scratch, `report.${format}`);
          await writeFile(temp, data, { mode: 0o600 });
          commit(); this.progress(task, '保存导出记录');
          archived = await this.call(task, 'report-export-register', ['--draft', id, '--format', format, '--path', temp, '--mode', projection.content_mode, '--projection-hash', projection.projection_hash]);
        }
        await copyFile(archived.path, selected.filePath);
        return { ...archived, path: selected.filePath, archived_path: archived.path, format };
      } finally { await rm(scratch, { recursive: true, force: true }); }
    });
  }
}
