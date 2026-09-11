import { describe, expect, it } from 'vitest';

import { locatorArgs, pathFreePayload, previewFence } from '../electron/source-locator.js';

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
  });

  it('fences Univer to digest scratch and refuses the analysis tree', () => {
    const hash = 'c'.repeat(64);
    const file = `/store/tasks/${'a'.repeat(32)}/artifacts/preview/${hash}/${hash}.xlsx`;
    expect(previewFence(file, hash)).toEqual({
      file,
      allowedRoot: `/store/tasks/${'a'.repeat(32)}/artifacts/preview/${hash}`,
    });
    expect(() =>
      previewFence(`/store/tasks/${'a'.repeat(32)}/analysis/datasets/ds/source.xlsx`, hash),
    ).toThrow(/analysis tree/);
    expect(() => previewFence(`/tmp/${hash}.xlsx`, hash)).toThrow(/digest scratch/);
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
});
