import { mkdtemp, mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import * as path from 'node:path';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ home: '', call: vi.fn(), connect: vi.fn(), close: vi.fn() }));
vi.mock('node:os', async (original) => ({ ...await original<typeof import('node:os')>(), homedir: () => mocks.home }));
vi.mock('@modelcontextprotocol/sdk/client/index.js', () => ({ Client: class { connect = mocks.connect; callTool = mocks.call; close = mocks.close; } }));
vi.mock('@modelcontextprotocol/sdk/client/stdio.js', () => ({ StdioClientTransport: class { close = mocks.close; } }));
import { ocrDocument } from '../electron/reports/ocr.js';
const envelope = (value: unknown) => ({ content: [{ type: 'text', text: JSON.stringify(value) }] });
let source: string;
beforeEach(async () => {
  vi.clearAllMocks(); mocks.connect.mockResolvedValue(undefined); mocks.close.mockResolvedValue(undefined);
  mocks.home = await mkdtemp(path.join(tmpdir(), 'ocr-test-home-'));
  await mkdir(path.join(mocks.home, '.local/bin'), { recursive: true });
  await writeFile(path.join(mocks.home, '.local/bin/ocr-studio-mcp'), 'test');
  source = path.join(mocks.home, 'original.pdf'); await writeFile(source, '%PDF-1.7\noriginal');
});
afterEach(async () => { await rm(mocks.home, { recursive: true, force: true }); });

it('preserves the original and does not start parsing when the local model is unavailable', async () => {
  mocks.call.mockResolvedValue(envelope({ ok: true, vl_ready: false }));
  expect(await ocrDocument(source, new AbortController().signal)).toMatchObject({ warning: expect.stringContaining('尚未就绪') });
  expect(mocks.call).toHaveBeenCalledTimes(1);
  expect(await readFile(source, 'utf8')).toBe('%PDF-1.7\noriginal');
});

it('reads a complete truncated-response sidecar only from the private scratch directory and removes it', async () => {
  let scratch = '';
  mocks.call.mockImplementation(async ({ name, arguments: args }) => {
    if (name === 'service_status') return envelope({ ok: true, vl_ready: true });
    scratch = path.dirname(args.path);
    expect(args.path).not.toBe(source);
    const sidecar = path.join(scratch, 'source.ocrstudio.md'); await writeFile(sidecar, '完整识别 123.4500');
    return envelope({ ok: true, partial: true, markdown: '截断', sidecar_path: sidecar });
  });
  expect(await ocrDocument(source, new AbortController().signal)).toMatchObject({ markdown: '完整识别 123.4500' });
  await expect(readdir(scratch)).rejects.toMatchObject({ code: 'ENOENT' });
  expect((await readdir(mocks.home)).sort()).toEqual(['.local', 'original.pdf']);
});

it('does not trust a sidecar path outside the conversion scratch directory', async () => {
  mocks.call.mockResolvedValueOnce(envelope({ ok: true, vl_ready: true }))
    .mockResolvedValueOnce(envelope({ ok: true, partial: true, sidecar_path: source }));
  const result = await ocrDocument(source, new AbortController().signal);
  expect(result.markdown).toBeUndefined(); expect(result.warning).toContain('完整结果路径无效');
});

it('propagates cancellation instead of presenting it as a recognition result', async () => {
  const controller = new AbortController(); controller.abort();
  await expect(ocrDocument(source, controller.signal)).rejects.toThrow('已取消');
  expect(mocks.call).not.toHaveBeenCalled();
});
