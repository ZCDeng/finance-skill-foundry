import { describe, expect, it } from 'vitest';

import { locatorArgs, locatorHighlight, pathFreePayload, previewFence, taskRoot } from '../electron/source-locator.js';
import { highlightScript } from '../electron/univer.js';

describe('source locator IPC arguments', () => {
  it('accepts a fact id or a run cell and rejects paths', () => {
    expect(locatorArgs({ fact_id: 'fact-expense' })).toEqual({ fact_id: 'fact-expense' });
    expect(locatorArgs({ run_id: 'run-a', row: 0, column: 'expense' })).toEqual({
      run_id: 'run-a',
      row: 0,
      column: 'expense',
    });
    expect(() => locatorArgs({ fact_id: 'fact-expense', dataset_id: 'ds' })).toThrow(/fact_id or run_id/);
    expect(() => locatorArgs({ path: '/tmp/secret.xlsx' })).toThrow(/fact_id or run_id/);
    expect(() => locatorArgs({ url: 'file:///tmp/secret.xlsx' })).toThrow(/fact_id or run_id/);
    expect(() => locatorArgs({ fact_id: 'x', origin: 'http://127.0.0.1:9081' })).toThrow(/fact_id or run_id/);
  });

  it('bounds identifiers and rows, and keeps Chinese column names', () => {
    expect(locatorArgs({ run_id: 'run-a', row: 3, column: '费用.本期:合计' })).toEqual({ run_id: 'run-a', row: 3, column: '费用.本期:合计' });
    expect(locatorArgs({ run_id: 'run-a', row: 1_000_000 })).toEqual({ run_id: 'run-a', row: 1_000_000 });
    expect(() => locatorArgs({ run_id: 'run-a', row: 1_000_001 })).toThrow(/invalid row/);
    expect(() => locatorArgs({ run_id: 'run-a', row: -1 })).toThrow(/invalid row/);
    expect(() => locatorArgs({ run_id: 'run-a', row: 1.5 })).toThrow(/invalid row/);
    expect(() => locatorArgs({ run_id: 'run-a', row: '0' })).toThrow(/invalid row/);
    expect(() => locatorArgs({ fact_id: { toString: () => 'fact' } })).toThrow(/invalid fact id/);
    expect(() => locatorArgs({ fact_id: 'fact/../secret' })).toThrow(/invalid fact id/);
    expect(() => locatorArgs({ fact_id: 'fact expense' })).toThrow(/invalid fact id/);
    expect(() => locatorArgs({ fact_id: 'f'.repeat(129) })).toThrow(/invalid fact id/);
    expect(() => locatorArgs({ fact_id: '' })).toThrow(/invalid fact id/);
    expect(() => locatorArgs({ run_id: 'run-a', row: 0, column: ['expense'] })).toThrow(/invalid column/);
    expect(() => locatorArgs({ run_id: 'run-a', row: 0, column: 'a\nb' })).toThrow(/invalid column/);
    expect(() => locatorArgs({ run_id: { id: 'run-a' }, row: 0 })).toThrow(/invalid run id/);
  });

  it('fences Univer to digest scratch and refuses the analysis tree', () => {
    const hash = 'c'.repeat(64);
    const task = taskRoot('/store', 'a'.repeat(32));
    expect(task).toBe(`/store/tasks/${'a'.repeat(32)}`);
    const file = `${task}/artifacts/preview/${hash}/${hash}.xlsx`;
    expect(previewFence(file, hash, task)).toEqual({
      file,
      allowedRoot: `${task}/artifacts/preview/${hash}`,
    });
    expect(() => previewFence(`${task}/analysis/datasets/ds/source.xlsx`, hash, task)).toThrow(/analysis tree/);
    // A digest-shaped scratch that sits inside the task's analysis tree is still the analysis tree.
    expect(() => previewFence(`${task}/analysis/artifacts/preview/${hash}/${hash}.xlsx`, hash, task)).toThrow(/analysis tree/);
    // Another task's scratch is not this task's fence.
    expect(() => previewFence(`/store/tasks/${'b'.repeat(32)}/artifacts/preview/${hash}/${hash}.xlsx`, hash, task)).toThrow(/digest scratch/);
    expect(() => previewFence(`/tmp/${hash}.xlsx`, hash, task)).toThrow(/digest scratch/);
    expect(() => previewFence(`${task}/artifacts/preview/${'d'.repeat(64)}/${hash}.xlsx`, hash, task)).toThrow(/digest scratch/);
    expect(() => previewFence(`${task}/artifacts/preview/${hash}/deeper/${hash}.xlsx`, hash, task)).toThrow(/digest scratch/);
    expect(() => previewFence(`${task}/artifacts/preview/${hash}/../${hash}.xlsx`, hash, task)).toThrow(/digest scratch/);
    expect(() => previewFence(`artifacts/preview/${hash}/${hash}.xlsx`, hash, task)).toThrow(/absolute/);
    expect(() => previewFence(file, 'not-a-digest', task)).toThrow(/not a digest/);
  });

  it('decides "inside the analysis tree" by path, not by substring', () => {
    const hash = 'c'.repeat(64);
    // A store whose own directory is called `analysis` is not the task's analysis tree.
    const task = taskRoot('/store/analysis', 'a'.repeat(32));
    const file = `${task}/artifacts/preview/${hash}/${hash}.xlsx`;
    expect(previewFence(file, hash, task).allowedRoot).toBe(`${task}/artifacts/preview/${hash}`);
    // And `analysis-old` beside `analysis` is not under it: the tree check is separator-aware.
    expect(() => previewFence(`${task}/analysis-old/${hash}.xlsx`, hash, task)).toThrow(/digest scratch/);
    expect(() => previewFence(`${task}/analysis-old/${hash}.xlsx`, hash, task)).not.toThrow(/analysis tree/);
  });

  it('strips filesystem paths from locator payloads returned to the renderer', () => {
    const clean = pathFreePayload({
      status: 'ok',
      locator: { dataset_id: 'ds', source_hash: 'c'.repeat(64), kind: 'xlsx', excel_range: '费用!D18' },
      preview: { available: true, handle: 'h'.repeat(64), file: '/store/secret.xlsx' },
      path: '/store/secret.xlsx',
    });
    expect(JSON.stringify(clean)).not.toContain('/');
    expect(clean).toEqual({
      status: 'ok',
      locator: { dataset_id: 'ds', source_hash: 'c'.repeat(64), kind: 'xlsx', excel_range: '费用!D18' },
      preview: { available: true, handle: 'h'.repeat(64) },
    });
  });

  it('drops every location shape and the origin key, keeps ordinary strings, and caps the passage', () => {
    const clean = pathFreePayload({
      status: 'ok',
      origin: 'http://127.0.0.1:9081',
      file: '/store/tasks/a/artifacts/preview/c.xlsx',
      allowedRoot: '/store/tasks/a/artifacts/preview',
      locator: {
        excel_range: '费用!D18',
        sheet: '费用/成本',
        label: 'A/B 对比',
        note: 'http://example.com/x',
        win: 'C:\\Users\\x\\secret.xlsx',
        winFwd: 'c:/Users/x/secret.xlsx',
        unc: '\\\\server\\share\\secret.xlsx',
        fileUrl: 'file:///Users/x/secret.xlsx',
        wss: 'wss://127.0.0.1:9081/socket',
        posix: '/Users/x/secret.xlsx',
        passage: 'x'.repeat(800),
        list: ['/Users/x/secret.xlsx', 'D18', 'https://example.com'],
      },
    });
    const encoded = JSON.stringify(clean);
    expect(encoded).not.toContain('127.0.0.1');
    expect(encoded).not.toContain('/store/');
    expect(encoded).not.toContain('C:\\\\');
    expect(encoded).not.toContain('c:/');
    expect(encoded).not.toContain('\\\\\\\\server');
    expect(encoded).not.toContain('file://');
    expect(encoded).not.toContain('http://');
    expect(encoded).not.toContain('https://');
    expect(encoded).not.toContain('wss://');
    expect(encoded).not.toContain('/Users/');
    expect(clean).not.toHaveProperty('origin');
    expect(clean).not.toHaveProperty('file');
    expect(clean).not.toHaveProperty('allowedRoot');
    const locator = clean.locator as Record<string, unknown>;
    expect(locator.excel_range).toBe('费用!D18');
    expect(locator.sheet).toBe('费用/成本');
    expect(locator.label).toBe('A/B 对比');
    expect(locator.list).toEqual(['D18']);
    expect((locator.passage as string).length).toBe(500);
    for (const key of ['note', 'win', 'winFwd', 'unc', 'fileUrl', 'wss', 'posix']) expect(locator).not.toHaveProperty(key);
  });
});

describe('source locator highlight', () => {
  it('names the sheet and the bare cell from an Excel range', () => {
    expect(locatorHighlight({ sheet: '费用', excel_range: '费用!D18' })).toEqual({ sheet: '费用', range: 'D18' });
    expect(locatorHighlight({ excel_range: "'My Sheet'!A1:B2" })).toEqual({ sheet: 'My Sheet', range: 'A1:B2' });
    expect(locatorHighlight({ sheet: '费用' })).toEqual({ sheet: '费用' });
    expect(locatorHighlight({ excel_range: 'D18' })).toEqual({ range: 'D18' });
    expect(locatorHighlight({})).toEqual({});
  });

  it('writes both names into the viewer script as data, never as code', () => {
    const script = highlightScript({ sheet: "费用'); alert(1); ('", range: 'D18' });
    expect(script).toContain(JSON.stringify("费用'); alert(1); ('"));
    expect(script).toContain('"D18"');
    expect(script).toContain('getSheetByName');
    expect(script).toContain('setActiveSheet');
    expect(script).toContain('getRange');
    expect(script).toContain('activate()');
    expect(script).toContain('window.univerAPI');
    // Balanced: the injected sheet name did not close the script early.
    expect(() => new Function(script)).not.toThrow();
  });
});
