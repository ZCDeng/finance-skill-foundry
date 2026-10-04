// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from '../src/components/ui/empty.js';

afterEach(cleanup);

it('keeps the page heading level and the shadcn empty slots', () => {
  render(<Empty><EmptyHeader><EmptyTitle asChild><h2>任务已停用编辑</h2></EmptyTitle><EmptyDescription>恢复后可继续。</EmptyDescription></EmptyHeader>
    <EmptyContent><button type="button">恢复任务</button></EmptyContent></Empty>);
  const heading = screen.getByRole('heading', { level: 2, name: '任务已停用编辑' });
  expect(heading.getAttribute('data-slot')).toBe('empty-title');
  const root = heading.closest('[data-slot="empty"]');
  expect(root?.classList.contains('fnd-empty')).toBe(true);
  expect(screen.getByText('恢复后可继续。').getAttribute('data-slot')).toBe('empty-description');
  expect(screen.getByRole('button', { name: '恢复任务' }).parentElement?.getAttribute('data-slot')).toBe('empty-content');
});
