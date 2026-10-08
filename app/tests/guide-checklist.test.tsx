// @vitest-environment jsdom
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { GUIDE_ARTICLES } from '../src/views/guide/articles.js';
import { GuideHub } from '../src/views/guide/GuideHub.js';

afterEach(cleanup);

const source = (file: string) => readFileSync(resolve(process.cwd(), '../foundry', file), 'utf8');
const quoted = (text: string) => new Set([...text.matchAll(/"([^"]+)"/g)].map((match) => match[1]));

it('names only columns the structure proposal recognises, or inputs 回款健康 binds', () => {
  const proposal = source('structure_proposal.py');
  const aliases = quoted(proposal.slice(proposal.indexOf('ROLE_ALIASES'), proposal.indexOf('EXACT_ONLY_ALIASES')));
  const metrics = source('collection_metrics.py');
  const inputs = quoted(metrics.slice(metrics.indexOf('INPUT_LABELS'), metrics.indexOf('"""Every input')));
  const article = GUIDE_ARTICLES.find((row) => row.id === 'data-checklist');
  const rows = article?.body.flatMap((block) => block.kind === 'fields' ? block.rows : []) ?? [];
  expect(rows.length).toBeGreaterThanOrEqual(8);
  for (const row of rows) {
    for (const name of [...row.columns, ...(row.optional ?? [])]) {
      expect(aliases.has(name) || inputs.has(name), `${row.analysis}：${name}`).toBe(true);
    }
  }
});

it('saves the templates and says where they went', async () => {
  const exported = vi.fn().mockResolvedValue('/Users/a/Desktop/补充数据模板');
  render(<GuideHub article="data-checklist" onOpen={vi.fn()} onClose={vi.fn()} onExportTemplates={exported} />);
  expect(screen.getByRole('table').textContent).toContain('「发票号」');
  fireEvent.click(screen.getByRole('button', { name: '导出补充模板' }));
  await waitFor(() => expect(screen.getByText(/已导出到「\/Users\/a\/Desktop\/补充数据模板」/)).toBeTruthy());
  expect(exported).toHaveBeenCalledOnce();
});

it('says nothing when the folder pick is cancelled, and shows a failure', async () => {
  const exported = vi.fn().mockResolvedValueOnce(null).mockRejectedValueOnce(new Error('磁盘已满'));
  render(<GuideHub article="data-checklist" onOpen={vi.fn()} onClose={vi.fn()} onExportTemplates={exported} />);
  fireEvent.click(screen.getByRole('button', { name: '导出补充模板' }));
  await waitFor(() => expect(exported).toHaveBeenCalledOnce());
  expect(screen.queryByText(/已导出到/)).toBeNull();
  await waitFor(() => expect((screen.getByRole('button', { name: '导出补充模板' }) as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(screen.getByRole('button', { name: '导出补充模板' }));
  await waitFor(() => expect(screen.getByRole('alert').textContent).toBe('磁盘已满'));
});

it('leaves the button out where this build cannot save files', () => {
  render(<GuideHub article="data-checklist" onOpen={vi.fn()} onClose={vi.fn()} />);
  expect(screen.queryByRole('button', { name: '导出补充模板' })).toBeNull();
});
