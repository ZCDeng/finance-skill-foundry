// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { Preferences, TaskRow } from '../src/bridge.js';
import { PreferencesProvider } from '../src/components/Preferences.js';
import { SampleBanner } from '../src/components/SampleBanner.js';
import { Shell } from '../src/components/Shell.js';
import { Settings } from '../src/views/Settings.js';
import { TechnicalInfo } from '../src/views/analysis/TechnicalInfo.js';

afterEach(() => { cleanup(); delete (globalThis as { foundry?: unknown }).foundry; });

/** A bridge that keeps preferences the way main does: a patch over what is saved. */
function install(saved: Partial<Preferences> = {}) {
  let preferences: Preferences = { technical: false, brief_open: true, start: 'overview', samples_read: [], ...saved };
  const api = {
    preferencesGet: vi.fn(async () => ({ ok: true, value: preferences })),
    preferencesSet: vi.fn(async (patch: Partial<Preferences>) => { preferences = { ...preferences, ...patch }; return { ok: true, value: preferences }; }),
    appInfo: vi.fn(async () => ({ ok: true, value: { version: '0.14.0', data_folder: '/Users/me/Library/FA Foundry/var' } })),
    appRevealData: vi.fn(async () => ({ ok: true, value: { revealed: true } })),
  };
  (globalThis as { foundry?: unknown }).foundry = api;
  return api;
}

it('hides technical details until 显示技术信息 is turned on in 设置', async () => {
  const api = install();
  render(<PreferencesProvider>
    <Settings onWorkspace={() => {}} />
    <TechnicalInfo rows={[['计算编号', 'run-123']]} />
  </PreferencesProvider>);
  const toggle = await screen.findByRole('switch', { name: '显示技术信息' });
  await waitFor(() => expect(api.preferencesGet).toHaveBeenCalled());
  expect(toggle.getAttribute('aria-checked')).toBe('false');
  expect(screen.queryByText('技术信息')).toBeNull();
  await act(async () => { fireEvent.click(toggle); });
  expect(api.preferencesSet).toHaveBeenCalledWith({ technical: true });
  expect(screen.getByRole('switch', { name: '显示技术信息' }).getAttribute('aria-checked')).toBe('true');
  expect(screen.getByText('技术信息')).toBeTruthy();
});

it('says which version this is and where the data lives, and shows that folder on request', async () => {
  const api = install();
  render(<PreferencesProvider><Settings onWorkspace={() => {}} /></PreferencesProvider>);
  expect(await screen.findByText('版本 0.14.0')).toBeTruthy();
  expect(screen.getByText('/Users/me/Library/FA Foundry/var')).toBeTruthy();
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: '在访达中显示' })); });
  expect(api.appRevealData).toHaveBeenCalled();
});

it('saves the start screen and 本月三句话 as chosen', async () => {
  const api = install({ start: 'workspace' });
  render(<PreferencesProvider><Settings onWorkspace={() => {}} /></PreferencesProvider>);
  const start = await screen.findByLabelText('打开应用时进入') as HTMLSelectElement;
  await waitFor(() => expect(start.value).toBe('workspace'));
  await act(async () => { fireEvent.change(start, { target: { value: 'overview' } }); });
  expect(api.preferencesSet).toHaveBeenCalledWith({ start: 'overview' });
  await act(async () => { fireEvent.click(screen.getByRole('switch', { name: '本月三句话默认展开' })); });
  expect(api.preferencesSet).toHaveBeenCalledWith({ brief_open: false });
});

it('says so and offers no working switch in a build that cannot keep a choice', () => {
  (globalThis as { foundry?: unknown }).foundry = {};
  render(<PreferencesProvider><Settings onWorkspace={() => {}} /><TechnicalInfo rows={[['计算编号', 'run-123']]} /></PreferencesProvider>);
  expect(screen.getByRole('note').textContent).toContain('当前安装版还不能保存设置');
  expect((screen.getByRole('switch', { name: '显示技术信息' }) as HTMLButtonElement).disabled).toBe(true);
  // Nothing to read: technical details show as they did before 设置.
  expect(screen.getByText('技术信息')).toBeTruthy();
});

it('puts a gear for 设置 after the theme switch, marked while its page is on', () => {
  const onSettings = vi.fn();
  render(<Shell screen="settings" onScreen={() => {}} onSettings={onSettings}><p>body</p></Shell>);
  const gear = screen.getByRole('button', { name: '设置' });
  expect(gear.getAttribute('aria-current')).toBe('page');
  fireEvent.click(gear);
  expect(onSettings).toHaveBeenCalled();
});

const practice = { id: 't1', title: '示例：华宸物业 8 月', sample: 'practice' } as TaskRow;

it('folds the example note to its 示例 tag once read, for every task of that kind, and opens it again from the tag', async () => {
  const api = install();
  const { rerender } = render(<PreferencesProvider><SampleBanner task={practice} building={false} error="" onReference={() => {}} /></PreferencesProvider>);
  await waitFor(() => expect(api.preferencesGet).toHaveBeenCalled());
  expect(screen.getByText(/这是练习用的示例任务/)).toBeTruthy();
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: '知道了' })); });
  expect(api.preferencesSet).toHaveBeenCalledWith({ samples_read: ['practice'] });
  expect(screen.queryByText(/这是练习用的示例任务/)).toBeNull();
  expect(screen.getByRole('button', { name: '打开参考结果' })).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: '示例' }));
  expect(screen.getByText(/这是练习用的示例任务/)).toBeTruthy();
  // A note that says something is wrong never folds.
  rerender(<PreferencesProvider><SampleBanner task={{ ...practice, sample: 'reference', sample_ready: false } as TaskRow} building={false} error="" /></PreferencesProvider>);
  expect(screen.getByText(/参考结果没有生成完/)).toBeTruthy();
  expect(screen.queryByRole('button', { name: '知道了' })).toBeNull();
});

it('keeps another kind of example open after one kind was read, and folds again on the next task', async () => {
  const api = install();
  const banner = (task: TaskRow) => <PreferencesProvider><SampleBanner task={task} building={false} error="" onReference={() => {}} /></PreferencesProvider>;
  const { rerender } = render(banner(practice));
  await waitFor(() => expect(api.preferencesGet).toHaveBeenCalled());
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: '知道了' })); });
  // The same banner moves on to the next-month task: that kind was never read.
  rerender(banner({ id: 't2', title: '示例：华宸物业 9 月', sample: 'next_month' } as TaskRow));
  expect(screen.getByText(/这是 9 月的练习任务/)).toBeTruthy();
  rerender(banner(practice));
  expect(screen.queryByText(/这是练习用的示例任务/)).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: '示例' }));
  expect(screen.getByText(/这是练习用的示例任务/)).toBeTruthy();
  // Opened on one task, the note stays folded on another task of the same kind.
  rerender(banner({ ...practice, id: 't3' }));
  expect(screen.queryByText(/这是练习用的示例任务/)).toBeNull();
});
