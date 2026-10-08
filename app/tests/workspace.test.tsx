// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Workspace } from '../src/components/Workspace.js';
import type { TaskRow } from '../src/bridge.js';
import { press } from './press.js';

const tasks: TaskRow[] = [
  { id: 'a'.repeat(32), title: '华东利润分析', period: '2026-08', skill_id: null, created_at: '', windows: 0 },
  { id: 'b'.repeat(32), title: '西南回款', period: null, skill_id: null, created_at: '', windows: 0 },
];
const props = { active: true, task: tasks[0], tasks, onPick: vi.fn(), onNew: vi.fn(),
  lifecycleView: 'active' as const, onLifecycleView: vi.fn(),
  onMethods: vi.fn(), onData: vi.fn(), onHistory: vi.fn(), onLayout: vi.fn(),
  conversation: <p>对话连接中</p>, children: <textarea aria-label="文稿正文" defaultValue="保留这份草稿" /> };
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe('one task workspace', () => {
  it('switches focus without unmounting the edited result', () => {
    render(<Workspace {...props} />);
    const draft = screen.getByLabelText('文稿正文');
    fireEvent.change(draft, { target: { value: '经理刚修改的解释' } });
    fireEvent.click(screen.getByRole('button', { name: '对话专注' }));
    fireEvent.click(screen.getByRole('button', { name: '同时查看' }));
    expect(screen.getByLabelText('文稿正文')).toBe(draft);
    expect((draft as HTMLTextAreaElement).value).toBe('经理刚修改的解释');
  });

  it('finds and selects a task by its business name without editing current content', () => {
    render(<Workspace {...props} />);
    fireEvent.click(screen.getByRole('button', { name: '展开任务列表' }));
    fireEvent.change(screen.getByRole('searchbox', { name: '搜索任务' }), { target: { value: '西南' } });
    fireEvent.click(screen.getByRole('button', { name: '西南回款' }));
    expect(props.onPick).toHaveBeenCalledExactlyOnceWith(tasks[1].id);
    expect(props.onNew).not.toHaveBeenCalled();
  });

  it('writes the period in words beside the title and in the list, and finds it either way', () => {
    render(<Workspace {...props} />);
    expect(document.querySelector('.workspace-title > span')!.textContent).toBe('2026 年 8 月');
    fireEvent.click(screen.getByRole('button', { name: '展开任务列表' }));
    const row = screen.getByRole('button', { name: '华东利润分析' });
    expect(row.querySelector('small')!.textContent).toBe('2026 年 8 月 · 进行中');
    const search = screen.getByRole('searchbox', { name: '搜索任务' });
    for (const query of ['8 月', '2026-08']) {
      fireEvent.change(search, { target: { value: query } });
      expect(screen.getByRole('button', { name: '华东利润分析' })).toBeTruthy();
      expect(screen.queryByRole('button', { name: '西南回款' })).toBeNull();
    }
  });

  it('finds a period written with or without spaces and with a plain hyphen, and keeps it on one line', () => {
    const rows: TaskRow[] = [...tasks, { id: 'c'.repeat(32), title: '集团累计', period: '2026-01:2026-08', skill_id: null, created_at: '', windows: 0 }];
    render(<Workspace {...props} tasks={rows} />);
    fireEvent.click(screen.getByRole('button', { name: '展开任务列表' }));
    expect(screen.getByRole('button', { name: '集团累计' }).querySelector('small .fnd-period')!.textContent).toBe('2026 年 1–8 月');
    const search = screen.getByRole('searchbox', { name: '搜索任务' });
    const found = () => screen.queryAllByRole('button').filter((button) => button.classList.contains('workspace-task')).map((button) => button.getAttribute('aria-label'));
    fireEvent.change(search, { target: { value: '2026年8月' } });
    expect(found()).toEqual(['华东利润分析']);
    fireEvent.change(search, { target: { value: '8月' } });
    expect(found()).toEqual(expect.arrayContaining(['华东利润分析', '集团累计']));
    expect(found()).toHaveLength(2);
    fireEvent.change(search, { target: { value: '1-8月' } });
    expect(found()).toEqual(['集团累计']);
  });

  it('lets keyboard users resize and reset the dialogue width', () => {
    render(<Workspace {...props} />);
    const separator = screen.getByRole('separator', { name: '调整对话宽度' });
    const before = Number(separator.getAttribute('aria-valuenow'));
    fireEvent.keyDown(separator, { key: 'ArrowRight' });
    expect(Number(separator.getAttribute('aria-valuenow'))).toBeGreaterThan(before);
    fireEvent.keyDown(separator, { key: 'Home' });
    expect(separator.getAttribute('aria-valuenow')).toBe('400');
  });

  it('keeps methods, data tools and task history reachable', () => {
    render(<Workspace {...props} />);
    fireEvent.click(screen.getByRole('button', { name: '展开任务列表' }));
    fireEvent.click(screen.getByRole('button', { name: '方法库' }));
    expect(props.onMethods).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole('button', { name: '展开任务列表' }));
    fireEvent.click(screen.getByRole('button', { name: '数据台' }));
    expect(props.onData).toHaveBeenCalledOnce();
  });

  it('keeps only what acts on the open task in its menu, each with a line icon that stays out of its name', async () => {
    render(<Workspace {...props} onRename={vi.fn()} onArchive={vi.fn()} onTrash={vi.fn()} />);
    press(screen.getByRole('button', { name: '这个任务' }));
    const menu = await screen.findByRole('menu');
    expect(menu.textContent).toContain(tasks[0].title);
    const items = await screen.findAllByRole('menuitem');
    expect(items.map((item) => item.textContent)).toEqual(['改名', '归档任务', '移入回收站']);
    for (const item of items) {
      const icon = item.firstElementChild as SVGElement;
      expect(icon.tagName.toLowerCase(), item.textContent!).toBe('svg');
      expect(icon.getAttribute('aria-hidden')).toBe('true');
      expect(icon.getAttribute('width')).toBe('15');
      expect(icon.getAttribute('stroke-width'), item.textContent!).toBe('1.5');
    }
  });

  it('moves a task to the trash from a plain menu item, since it can be restored', async () => {
    const onTrash = vi.fn();
    render(<Workspace {...props} onArchive={vi.fn()} onTrash={onTrash} />);
    press(screen.getByRole('button', { name: '这个任务' }));
    const trash = await screen.findByRole('menuitem', { name: '移入回收站' });
    expect(trash.getAttribute('data-variant')).toBe('default');
    fireEvent.click(trash);
    await waitFor(() => expect(onTrash).toHaveBeenCalledWith(tasks[0].id));
  });

  it('filters lifecycle buckets and exposes recoverable task actions', async () => {
    render(<Workspace {...props} onArchive={vi.fn()} onTrash={vi.fn()} onRestore={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: '展开任务列表' }));
    fireEvent.click(screen.getByRole('button', { name: '已归档' }));
    expect(props.onLifecycleView).toHaveBeenCalledWith('archived');
    press(screen.getByRole('button', { name: '这个任务' }));
    fireEvent.click(await screen.findByRole('menuitem', { name: '归档任务' }));
  });

  it('renders the task drawer as a titled navigation surface with a separate library footer', () => {
    render(<Workspace {...props} />);
    fireEvent.click(screen.getByRole('button', { name: '展开任务列表' }));
    const sidebar = screen.getByRole('dialog', { name: '财务任务' });
    expect(screen.getByRole('heading', { name: '任务' })).toBeTruthy();
    expect(sidebar.querySelector('.workspace-search input')).toBe(screen.getByRole('searchbox', { name: '搜索任务' }));
    const tools = within(sidebar).getByRole('navigation', { name: '更多工具' });
    expect([...tools.querySelectorAll('.workspace-library')].map((item) => item.textContent)).toEqual(['方法库', '数据台', '任务记录与旧版流程']);
  });

  it('shows a failed archive in the menu and lets the same task retry', async () => {
    const onArchive = vi.fn().mockRejectedValueOnce(new Error('任务暂时被占用，请重试。')).mockResolvedValueOnce(undefined);
    render(<Workspace {...props} onArchive={onArchive} />);
    press(screen.getByRole('button', { name: '这个任务' }));
    fireEvent.click(await screen.findByRole('menuitem', { name: '归档任务' }));
    expect((await screen.findByRole('alert')).textContent).toBe('任务暂时被占用，请重试。');
    expect(screen.getByText(tasks[0].title, { selector: 'h1' })).toBeTruthy();
    fireEvent.click(screen.getByRole('menuitem', { name: '归档任务' }));
    await waitFor(() => expect(screen.queryByRole('menuitem', { name: '归档任务' })).toBeNull());
    expect(onArchive).toHaveBeenCalledTimes(2);
    expect(onArchive).toHaveBeenLastCalledWith(tasks[0].id);
    expect(screen.queryByRole('alert')).toBeNull();
  });

});
