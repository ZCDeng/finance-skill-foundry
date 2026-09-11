/**
 * Path-free source locator IPC helpers.
 *
 * The renderer may name a fact or a run cell. Main resolves that through the
 * CLI, copies authorized bytes into digest scratch, and fences Univer to that
 * directory. This file never opens `preview:open` or `deliverable-path`.
 */
import * as path from 'node:path';

const FORBIDDEN = new Set(['dataset_id', 'path', 'url', 'file', 'allowedRoot', 'preview_path']);
const DIGEST = /^[0-9a-f]{64}$/;
const PATH_MARKERS = ['file://'];

export function locatorArgs(spec: unknown): { fact_id: string } | { run_id: string; row: number; column?: string } {
  if (!spec || typeof spec !== 'object' || Array.isArray(spec)) {
    throw new Error('open_source_locator arguments must be fact_id or run_id,row,column');
  }
  const record = spec as Record<string, unknown>;
  const keys = Object.keys(record);
  if (keys.some((key) => FORBIDDEN.has(key))) {
    throw new Error('open_source_locator arguments must be fact_id or run_id,row,column');
  }
  if (keys.length === 1 && keys[0] === 'fact_id') {
    const factId = String(record.fact_id ?? '');
    if (!factId || factId.length > 128) throw new Error('invalid fact id');
    return { fact_id: factId };
  }
  const extra = keys.filter((key) => !['run_id', 'row', 'column'].includes(key));
  if ('run_id' in record && 'row' in record && extra.length === 0) {
    const runId = String(record.run_id ?? '');
    const row = record.row;
    if (!runId || runId.length > 128) throw new Error('invalid run id');
    if (typeof row !== 'number' || !Number.isInteger(row) || row < 0) throw new Error('invalid row');
    const column = record.column == null ? undefined : String(record.column);
    if (column !== undefined && column.length > 128) throw new Error('invalid column');
    return column ? { run_id: runId, row, column } : { run_id: runId, row };
  }
  throw new Error('open_source_locator arguments must be fact_id or run_id,row,column');
}

export function previewFence(file: string, sourceHash: string): { file: string; allowedRoot: string } {
  if (!DIGEST.test(sourceHash)) throw new Error(`not a digest: ${sourceHash}`);
  const allowedRoot = path.dirname(file);
  if (!file.startsWith(`${allowedRoot}${path.sep}`)) {
    throw new Error('a preview may only open a file under its own fence');
  }
  const normalized = file.replace(/\\/g, '/');
  const root = allowedRoot.replace(/\\/g, '/');
  if (normalized.includes('/analysis/') || root.endsWith('/analysis')) {
    throw new Error('a source locator preview may not use the analysis tree as its fence');
  }
  if (!root.endsWith(`/artifacts/preview/${sourceHash}`)) {
    throw new Error('a source locator preview must be fenced to its digest scratch');
  }
  return { file, allowedRoot };
}

export function pathFreePayload(value: unknown): Record<string, unknown> {
  return stripPaths(value) as Record<string, unknown>;
}

function stripPaths(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stripPaths);
  if (!value || typeof value !== 'object') {
    if (typeof value === 'string') {
      if (PATH_MARKERS.some((marker) => value.includes(marker))) return undefined;
      if (value.startsWith('/') || value.includes('\\')) return undefined;
    }
    return value;
  }
  const out: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
    if (key === 'path' || key === 'url' || key === 'file' || key === 'allowedRoot') continue;
    const clean = stripPaths(item);
    if (clean !== undefined) out[key] = clean;
  }
  return out;
}
