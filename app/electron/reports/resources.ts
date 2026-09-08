import { readFile, realpath, stat } from 'node:fs/promises';
import * as path from 'node:path';
import { parseHTML } from 'linkedom';
import type { ReportFormat } from './model.js';

/** Only images beside the user-selected document may be embedded. No network or parent traversal. */
export function imageResourceReferences(data: Buffer, format: ReportFormat): string[] {
  if (format !== 'html' && format !== 'md') return [];
  const body = data.toString('utf8');
  const references = format === 'html'
    ? Array.from(parseHTML(body).document.querySelectorAll('img')).map((image) => (image as any).getAttribute('src') ?? '')
    : Array.from(body.matchAll(/!\[[^\]]*\]\(([^\s)]+)(?:\s+"[^"]*")?\)/g), (match) => match[1]);
  return [...new Set(references)].slice(0, 128);
}

export async function localReportResources(filename: string, references: string[], signal: AbortSignal): Promise<Record<string, string>> {
  const root = await realpath(path.dirname(filename));
  const resources: Record<string, string> = Object.create(null);
  let total = 0;
  for (const reference of new Set(references)) {
    if (signal.aborted) throw new Error('已取消文档转换。');
    if (!reference || /^(?:[a-z][a-z\d+.-]*:|[\\/])/i.test(reference)) continue;
    try {
      const relative = decodeURIComponent(reference).split(/[?#]/, 1)[0];
      const candidate = await realpath(path.resolve(root, relative));
      if (!candidate.startsWith(`${root}${path.sep}`)) continue;
      const extension = path.extname(candidate).toLowerCase();
      if (!['.png', '.jpg', '.jpeg'].includes(extension)) continue;
      const size = (await stat(candidate)).size;
      if (size > 2 * 1024 * 1024 || total + size > 16 * 1024 * 1024) continue;
      const image = await readFile(candidate, { signal });
      const png = image.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]));
      const jpeg = image[0] === 255 && image[1] === 216 && image[2] === 255;
      if (!png && !jpeg) continue;
      resources[reference] = `data:image/${png ? 'png' : 'jpeg'};base64,${image.toString('base64')}`;
      total += image.length;
    } catch (error) {
      if (signal.aborted) throw error;
      // The converter reports a missing resource, while keeping its alt text.
    }
  }
  return resources;
}
