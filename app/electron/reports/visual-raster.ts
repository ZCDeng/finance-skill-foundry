import { BrowserWindow } from 'electron';
import { randomUUID } from 'node:crypto';
import type { ReportDocument, ReportNode } from './model.js';
import { renderReportVisualSvg, reportVisualCaption } from './visuals.js';

/** Only the controlled renderer's primitives reach this isolated, offline rasterizer. */
export async function materializeReportVisualsForDocx(document: ReportDocument, fontDataUrl: string, signal: AbortSignal): Promise<ReportDocument> {
  const visuals: ReportNode[] = [];
  const collect = (nodes: ReportNode[]) => nodes.forEach((node) => {
    if (node.type === 'reportVisual') visuals.push(node);
    collect(node.content ?? []);
  });
  collect(document.content);
  if (!visuals.length) return document;
  if (visuals.length > 20) throw new Error('文稿最多包含 20 张图表，请按章节拆分。');
  if (!/^data:font\/woff2;base64,[A-Za-z0-9+/=]+$/.test(fontDataUrl)) throw new Error('图表导出缺少离线字体。');
  if (signal.aborted) throw new Error('已取消文档转换。');
  const window = new BrowserWindow({ show: false, width: 960, height: 800, webPreferences: {
    sandbox: true, contextIsolation: true, nodeIntegration: false, partition: `report-visual-${randomUUID()}`,
  } });
  const session = window.webContents.session;
  session.setPermissionRequestHandler((_web, _permission, callback) => callback(false));
  session.webRequest.onBeforeRequest({ urls: ['http://*/*', 'https://*/*', 'file://*/*'] }, (_details, callback) => callback({ cancel: true }));
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  window.webContents.on('will-navigate', (event) => event.preventDefault());
  const close = () => { if (!window.isDestroyed()) window.destroy(); };
  const timeout = setTimeout(close, 60_000);
  signal.addEventListener('abort', close, { once: true });
  try {
    await window.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent('<!doctype html><meta charset="utf-8"><title>图表导出</title>'));
    const replacements = new Map<ReportNode, ReportNode>();
    let totalBytes = 0;
    for (const node of visuals) {
      if (signal.aborted) throw new Error('已取消文档转换。');
      const svg = renderReportVisualSvg(node.attrs?.visual).replace(/(<svg\b[^>]*>)/, `$1<style>@font-face{font-family:"Noto Sans SC";src:url("${fontDataUrl}") format("woff2");font-weight:100 900;}text{font-family:"Noto Sans SC",sans-serif}</style>`);
      const src = await window.webContents.executeJavaScript(`(async () => {
        const svg = ${JSON.stringify(svg)};
        const markup = new DOMParser().parseFromString(svg, 'image/svg+xml').documentElement;
        const box = markup.getAttribute('viewBox').split(/\\s+/).map(Number);
        const width = box[2], height = box[3];
        if (!(width > 0 && width <= 1920 && height > 0 && height <= 6000)) throw new Error('图表尺寸无效');
        // Warm the exact embedded font before decoding the standalone SVG image.
        const font = new FontFace('Noto Sans SC', 'url(' + ${JSON.stringify(fontDataUrl)} + ')');
        document.fonts.add(await font.load()); await document.fonts.ready;
        const image = new Image();
        image.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
        await image.decode();
        const canvas = document.createElement('canvas'); canvas.width = width * 2; canvas.height = height * 2;
        const context = canvas.getContext('2d');
        context.fillStyle = '#ffffff'; context.fillRect(0, 0, canvas.width, canvas.height);
        context.drawImage(image, 0, 0, canvas.width, canvas.height);
        return canvas.toDataURL('image/png');
      })()`) as unknown;
      if (typeof src !== 'string' || !src.startsWith('data:image/png;base64,') || src.length > 2 * 1024 * 1024) throw new Error('图表导出图片无效或超过容量。');
      totalBytes += src.length;
      if (totalBytes > 16 * 1024 * 1024) throw new Error('图表图片总量超过容量，请拆分文稿。');
      replacements.set(node, { type: 'image', attrs: { src, title: reportVisualCaption(node.attrs?.visual), alt: reportVisualCaption(node.attrs?.visual) } });
    }
    const replace = (nodes: ReportNode[]): ReportNode[] => nodes.map((node) => replacements.get(node) ?? { ...node, ...(node.content ? { content: replace(node.content) } : {}) });
    return { ...document, content: replace(document.content) };
  } finally {
    clearTimeout(timeout); signal.removeEventListener('abort', close); close();
    await session.clearStorageData();
  }
}
