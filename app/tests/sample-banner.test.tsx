// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { TaskRow } from '../src/bridge.js';
import { SampleBanner } from '../src/components/SampleBanner.js';
import { GuideHub } from '../src/views/guide/GuideHub.js';

afterEach(cleanup);

const row = (fields: Partial<TaskRow>): TaskRow => ({
  id: 'a'.repeat(32), title: '示例', period: '2026-08', skill_id: null, created_at: '', windows: 0, ...fields,
});

it('says the reference was filled in by the example and offers to put it back', () => {
  const rebuild = vi.fn();
  render(<SampleBanner task={row({ sample: 'reference', sample_ready: true })} building={false} error="" onRebuild={rebuild} />);
  expect(screen.getByRole('note').textContent).toContain('示例预置');
  expect(screen.getByRole('note').textContent).toContain('不是经理的确认');
  fireEvent.click(screen.getByRole('button', { name: '重建参考结果' }));
  expect(rebuild).toHaveBeenCalledOnce();
});

it('holds the button while the reference is being built and shows a failure', () => {
  render(<SampleBanner task={row({ sample: 'reference' })} building error="生成失败" onRebuild={() => undefined} />);
  expect((screen.getByRole('button', { name: '正在重建…' }) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByRole('alert').textContent).toBe('生成失败');
});

it('says a reference left half made is not finished', () => {
  render(<SampleBanner task={row({ sample: 'reference', sample_ready: false })} building={false} error="" onRebuild={() => undefined} />);
  expect(screen.getByRole('note').textContent).toContain('没有生成完');
});

it('points the practice task at the reference, and an old pack at the newer one', () => {
  const reference = vi.fn();
  render(<SampleBanner task={row({ sample: 'practice', sample_outdated: true })} building={false} error="" onReference={reference} />);
  expect(screen.getByRole('note').textContent).toContain('新版本');
  fireEvent.click(screen.getByRole('button', { name: '打开参考结果' }));
  expect(reference).toHaveBeenCalledOnce();
});

it('draws nothing for a real task', () => {
  const { container } = render(<SampleBanner task={row({ sample: null })} building={false} error="" />);
  expect(container.textContent).toBe('');
});

it('removes the example tasks only after the count is confirmed', async () => {
  const remove = vi.fn().mockResolvedValue(3);
  render(<GuideHub article="first-run" onOpen={() => undefined} onClose={() => undefined} onSample={async () => undefined}
    samples={{ count: 3, outdated: false }} onRemoveSamples={remove} />);
  expect(screen.queryByRole('button', { name: '换成新版示例' })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: '移除示例任务' }));
  expect(screen.getByRole('alertdialog').textContent).toContain('3 个示例任务');
  expect(remove).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '移入回收站' }));
  await waitFor(() => expect(remove).toHaveBeenCalledOnce());
  await waitFor(() => expect(screen.getByText(/已把 3 个示例任务移入回收站/)).toBeTruthy());
});

it('offers the newer pack when an example on the list is older', () => {
  render(<GuideHub article="first-run" onOpen={() => undefined} onClose={() => undefined} onSample={async () => undefined}
    samples={{ count: 1, outdated: true }} onRemoveSamples={async () => 1} onReplaceSamples={async () => undefined} />);
  fireEvent.click(screen.getByRole('button', { name: '换成新版示例' }));
  expect(screen.getByRole('alertdialog').textContent).toContain('新版资料');
});
