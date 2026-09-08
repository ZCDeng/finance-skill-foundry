import { access, copyFile, mkdtemp, readFile, rm } from 'node:fs/promises';
import { homedir, tmpdir } from 'node:os';
import * as path from 'node:path';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';

/** OCR is optional and local. Never starts model services or writes beside the original PDF. */
export async function ocrDocument(sourcePath: string, signal: AbortSignal): Promise<{ markdown?: string; warning?: string }> {
  const launcher = path.join(homedir(), '.local/bin/ocr-studio-mcp');
  try { await access(launcher); } catch { return { warning: '未找到本机 OCR Studio；已保留 PDF 原页，可在安装后重试识别。' }; }
  const client = new Client({ name: 'fa-foundry-documents', version: '1.0.0' });
  const transport = new StdioClientTransport({ command: launcher, args: [], stderr: 'ignore' });
  const scratch = await mkdtemp(path.join(tmpdir(), 'fa-report-ocr-'));
  const close = () => { void client.close().catch(() => {}); };
  signal.addEventListener('abort', close, { once: true });
  const connectionTimeout = setTimeout(close, 15_000);
  const envelope = (response: unknown): Record<string, unknown> => {
    const result = response as { content?: { type: string; text?: string }[] };
    const text = result.content?.filter((item) => item.type === 'text').map((item) => item.text ?? '').join('\n');
    if (!text) throw new Error('OCR Studio 未返回识别内容。');
    return JSON.parse(text);
  };
  try {
    if (signal.aborted) throw new Error('已取消');
    await client.connect(transport);
    clearTimeout(connectionTimeout);
    const ready = envelope(await client.callTool({ name: 'service_status', arguments: {} }, undefined, { timeout: 10_000, signal }));
    if (ready.vl_ready === false || JSON.stringify(ready).includes('"vl_ready":false')) {
      return { warning: 'OCR Studio 识别服务尚未就绪；已保留 PDF 原页和可提取文字，启动服务后可重试。' };
    }
    const local = path.join(scratch, 'source.pdf');
    await copyFile(sourcePath, local);
    const parsed = envelope(await client.callTool({ name: 'parse_document', arguments: { path: local, write_sidecar: true } }, undefined, { timeout: 180_000, signal }));
    if (!parsed.ok) return { warning: `OCR 未完成：${String(parsed.message ?? parsed.code ?? '未返回正文')}。原页仍可核对。` };
    let markdown = typeof parsed.markdown === 'string' ? parsed.markdown : '';
    if (parsed.partial) {
      const sidecar = typeof parsed.sidecar_path === 'string' ? path.resolve(parsed.sidecar_path) : '';
      if (!sidecar || path.dirname(sidecar) !== scratch) throw new Error('OCR 返回不完整正文，完整结果路径无效。');
      markdown = await readFile(sidecar, 'utf8');
    }
    if (markdown.length > 1_000_000) return { warning: '识别正文超过文稿容量，请按章节拆分；原始 PDF 已保留。' };
    return markdown.trim() ? { markdown, warning: 'OCR 结果需要核对金额、表格顺序与附注；可逐页对照原始 PDF。' } : { warning: 'OCR 未提取出正文，原始 PDF 已保留。' };
  } catch (error) {
    if (signal.aborted) throw new Error('已取消文档转换。');
    return { warning: `OCR Studio 暂不可用：${error instanceof Error ? error.message : String(error)}。可继续核对原页或稍后重试。` };
  } finally {
    clearTimeout(connectionTimeout);
    signal.removeEventListener('abort', close);
    await client.close().catch(() => {});
    await transport.close().catch(() => {});
    await rm(scratch, { recursive: true, force: true });
  }
}
