import { parentPort, workerData } from 'node:worker_threads';
import { importReport, exportDocx } from './converters.js';
import { documentFromMarkdown, renderReportHtml } from './format.js';
import { imageResourceReferences } from './resources.js';

async function run() {
  const { operation, payload } = workerData;
  if (operation === 'resource-references') return imageResourceReferences(Buffer.from(payload.data), payload.format);
  if (operation === 'import') return importReport(Buffer.from(payload.data), payload.format, payload.source, payload.resources);
  if (operation === 'docx') return exportDocx(payload.document, payload.title, payload.fontData ? new Uint8Array(payload.fontData) : undefined, payload.options, payload.figureFontData ? new Uint8Array(payload.figureFontData) : undefined);
  if (operation === 'html') return renderReportHtml(payload.document, payload.title, payload.options);
  if (operation === 'markdown') return documentFromMarkdown(payload.body);
  throw new Error('Unsupported document operation');
}
run().then((value) => parentPort?.postMessage({ ok: true, value }),
  (error) => parentPort?.postMessage({ ok: false, message: error instanceof Error ? error.message : String(error) }));
