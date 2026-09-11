/**
 * Path-free source locator IPC helpers.
 *
 * The renderer may name a fact or a run cell. Main resolves that through the
 * CLI, copies authorized bytes into digest scratch, and fences Univer to that
 * directory. This file never opens `preview:open` or `deliverable-path`.
 */
import { rmSync } from 'node:fs';
import * as path from 'node:path';

const FORBIDDEN = new Set(['dataset_id', 'path', 'url', 'file', 'allowedRoot', 'preview_path', 'origin']);
const DIGEST = /^[0-9a-f]{64}$/;
/** A fact id, a run id, or a column name. CJK is allowed because columns are named in Chinese. */
const IDENT = /^[A-Za-z0-9_.:\-\u4e00-\u9fff]{1,128}$/;
const MAX_ROW = 1_000_000;
/** Keys that never reach the renderer, whatever they hold. */
const STRIPPED_KEYS = new Set(['path', 'url', 'file', 'allowedRoot', 'origin']);
/** A string that is a location rather than a value: a URL, or an absolute path on any platform. */
const LOCATION = /^(?:(?:file|https?|wss?):\/\/|\/|[A-Za-z]:[\\/]|\\\\)/i;
const PASSAGE_LIMIT = 500;

/** The four ways a locator open can fail, as the renderer is allowed to see them. */
export type LocatorErrorCode = 'locator_forbidden' | 'locator_unavailable' | 'preview_unavailable' | 'locator_error';

export class LocatorError extends Error {
  constructor(readonly code: LocatorErrorCode) {
    super(code);
    this.name = 'LocatorError';
  }
}

function ident(value: unknown, what: string): string {
  if (typeof value !== 'string' || !IDENT.test(value)) throw new Error(`invalid ${what}`);
  return value;
}

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
    return { fact_id: ident(record.fact_id, 'fact id') };
  }
  const extra = keys.filter((key) => !['run_id', 'row', 'column'].includes(key));
  if ('run_id' in record && 'row' in record && extra.length === 0) {
    const runId = ident(record.run_id, 'run id');
    const row = record.row;
    if (typeof row !== 'number' || !Number.isInteger(row) || row < 0 || row > MAX_ROW) throw new Error('invalid row');
    if (record.column === undefined || record.column === null) return { run_id: runId, row };
    return { run_id: runId, row, column: ident(record.column, 'column') };
  }
  throw new Error('open_source_locator arguments must be fact_id or run_id,row,column');
}

/** Whether `target` is `root` itself or something under it. Separator-aware, not a substring test. */
function within(root: string, target: string): boolean {
  const relative = path.relative(root, target);
  return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative));
}

/** Where the store keeps one task: `<varRoot>/tasks/<id>`, as `foundry/task.py` lays it out. */
export function taskRoot(varRoot: string, task: string): string {
  return path.join(varRoot, 'tasks', task);
}

/**
 * The directory Univer may be fenced to for one locator preview.
 *
 * The file the CLI named must sit directly in the task's own
 * `artifacts/preview/<digest>/`, and nowhere under the task's `analysis/`
 * tree. Both are decided with `path.relative` against directories derived
 * from the store root and the task id -- never from the file itself, and
 * never by looking for a word in the path.
 */
export function previewFence(file: string, sourceHash: string, task: string): { file: string; allowedRoot: string } {
  if (!DIGEST.test(sourceHash)) throw new Error(`not a digest: ${sourceHash}`);
  if (!path.isAbsolute(file)) throw new Error('a preview file must be an absolute path');
  const resolved = path.resolve(file);
  const allowedRoot = path.dirname(resolved);
  const leaf = path.relative(allowedRoot, resolved);
  if (!leaf || leaf.startsWith('..') || leaf.includes(path.sep)) {
    throw new Error('a preview may only open a file under its own fence');
  }
  const analysisRoot = path.resolve(task, 'analysis');
  if (within(analysisRoot, resolved) || within(analysisRoot, allowedRoot)) {
    throw new Error('a source locator preview may not use the analysis tree as its fence');
  }
  const scratch = path.resolve(task, 'artifacts', 'preview', sourceHash);
  if (path.relative(scratch, allowedRoot) !== '') {
    throw new Error('a source locator preview must be fenced to its digest scratch');
  }
  return { file: resolved, allowedRoot };
}

/**
 * The scratch directories this process fenced Univer to, by task.
 *
 * Only a root that came through `previewFence` is ever remembered, so the
 * only directories this can remove are ones this process chose from a path
 * the CLI resolved -- never one the renderer named.
 */
export class ScratchFences {
  private readonly roots = new Map<string, string>();

  /** Remember one fence; whatever that task had before is removed first. */
  fence(task: string, root: string): void {
    this.discard(task);
    this.roots.set(task, root);
  }

  discard(task: string): void {
    const root = this.roots.get(task);
    if (!root) return;
    this.roots.delete(task);
    rmSync(root, { recursive: true, force: true });
  }

  discardAll(): void {
    for (const task of [...this.roots.keys()]) this.discard(task);
  }
}

export function pathFreePayload(value: unknown): Record<string, unknown> {
  return stripPaths(value) as Record<string, unknown>;
}

function stripPaths(value: unknown, key?: string): unknown {
  if (Array.isArray(value)) return value.map((item) => stripPaths(item)).filter((item) => item !== undefined);
  if (!value || typeof value !== 'object') {
    if (typeof value === 'string') {
      if (LOCATION.test(value)) return undefined;
      if (key === 'passage' && value.length > PASSAGE_LIMIT) return value.slice(0, PASSAGE_LIMIT);
    }
    return value;
  }
  const out: Record<string, unknown> = {};
  for (const [name, item] of Object.entries(value as Record<string, unknown>)) {
    if (STRIPPED_KEYS.has(name)) continue;
    const clean = stripPaths(item, name);
    if (clean !== undefined) out[name] = clean;
  }
  return out;
}

/**
 * What the viewer should put in front for one locator.
 *
 * `excel_range` comes as Excel writes it, `费用!D18` or `'Sheet 1'!A1:B2`;
 * the sheet part wins over `sheet` only when `sheet` is absent, and the cell
 * part is handed over bare, which is the notation the viewer's `getRange` reads.
 */
export function locatorHighlight(locator: Record<string, unknown>): { sheet?: string; range?: string } {
  const excelRange = typeof locator.excel_range === 'string' ? locator.excel_range.trim() : '';
  const named = typeof locator.sheet === 'string' ? locator.sheet.trim() : '';
  const bang = excelRange.lastIndexOf('!');
  let sheet = named;
  let range = excelRange;
  if (bang > 0) {
    const prefix = excelRange.slice(0, bang);
    range = excelRange.slice(bang + 1);
    if (!sheet) sheet = prefix.startsWith("'") && prefix.endsWith("'") ? prefix.slice(1, -1).replace(/''/g, "'") : prefix;
  }
  const out: { sheet?: string; range?: string } = {};
  if (sheet) out.sheet = sheet;
  if (range) out.range = range;
  return out;
}
