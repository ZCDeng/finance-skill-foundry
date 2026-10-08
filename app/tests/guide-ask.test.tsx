// @vitest-environment jsdom
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { GUIDE_ARTICLES } from '../src/views/guide/articles.js';
import { ASK_EVENT, ASK_PROMPTS } from '../src/views/guide/ask.js';
import { AskLink, GuideHub } from '../src/views/guide/GuideHub.js';

afterEach(cleanup);

const CLIENT = readFileSync(resolve(process.cwd(), '../dsh-plugin/client.js'), 'utf8');

it('asks with the same words as the composer\'s 「/」 menu', () => {
  const shared = Object.entries(ASK_PROMPTS).filter(([id]) => CLIENT.includes(`id: '${id}'`));
  expect(shared.length).toBeGreaterThanOrEqual(6);
  for (const [id, prompt] of shared) expect(CLIENT, id).toContain(`prompt: '${prompt}'`);
});

it('puts the question into the conversation and nothing else', () => {
  const heard = vi.fn();
  window.addEventListener(ASK_EVENT, (event) => heard((event as CustomEvent).detail));
  render(<AskLink ask="collection-health" label="让助手做回款健康分析" />);
  const button = screen.getByRole('button', { name: '让助手做回款健康分析' });
  // The question is readable before pressing.
  expect(button.getAttribute('title')).toBe(ASK_PROMPTS['collection-health']);
  fireEvent.click(button);
  expect(heard).toHaveBeenCalledWith(ASK_PROMPTS['collection-health']);
});

it('every ask in the guide names a question the window has', () => {
  const asks = GUIDE_ARTICLES.flatMap((article) => article.body.filter((block) => block.kind === 'ask'));
  expect(asks.length).toBeGreaterThanOrEqual(5);
  for (const block of asks) if (block.kind === 'ask') expect(Object.keys(ASK_PROMPTS)).toContain(block.ask);
});

it('says once, after a run of asks, that nothing is sent', () => {
  render(<GuideHub article="assistant-skills" onOpen={vi.fn()} onClose={vi.fn()} />);
  expect(screen.getByRole('button', { name: '让助手做资料体检' })).toBeTruthy();
  expect(screen.getAllByText('只填进对话框，改好再发送。')).toHaveLength(1);
});

it('cannot ask with no editable task open, and says why', () => {
  render(<GuideHub article="assistant-skills" canOpen={false} onOpen={vi.fn()} onClose={vi.fn()} />);
  expect((screen.getByRole('button', { name: '让助手走一遍月结' }) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText('先打开一个可编辑的任务，才能问助手。')).toBeTruthy();
});

it('names the workbook it asks about, so the assistant knows which one', () => {
  const heard = vi.fn();
  window.addEventListener(ASK_EVENT, (event) => heard((event as CustomEvent).detail));
  render(<AskLink ask="formula-health" label="让助手解释这些提示" about="物业套表.xlsx" />);
  fireEvent.click(screen.getByRole('button', { name: '让助手解释这些提示' }));
  expect(heard).toHaveBeenCalledWith(`关于「物业套表.xlsx」：${ASK_PROMPTS['formula-health']}`);
});
