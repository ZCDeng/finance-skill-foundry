// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
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
    press(screen.getByRole('button', { name: '任务工具' }));
    fireEvent.click(screen.getByRole('menuitem', { name: '数据台' }));
    expect(props.onData).toHaveBeenCalledOnce();
  });

  it('starts every task tool with a line icon that stays out of its name', async () => {
    render(<Workspace {...props} onArchive={vi.fn()} onTrash={vi.fn()} />);
    press(screen.getByRole('button', { name: '任务工具' }));
    const items = await screen.findAllByRole('menuitem');
    expect(items.map((item) => item.textContent)).toEqual(['方法库', '数据台', '任务记录与旧版流程', '归档任务', '移入回收站']);
    for (const item of items) {
      const icon = item.firstElementChild as SVGElement;
      expect(icon.tagName.toLowerCase(), item.textContent!).toBe('svg');
      expect(icon.getAttribute('aria-hidden')).toBe('true');
      expect(icon.getAttribute('width')).toBe('15');
    }
  });

  it('moves a task to the trash from a plain menu item, since it can be restored', async () => {
    const onTrash = vi.fn();
    render(<Workspace {...props} onArchive={vi.fn()} onTrash={onTrash} />);
    press(screen.getByRole('button', { name: '任务工具' }));
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
    press(screen.getByRole('button', { name: '任务工具' }));
    fireEvent.click(await screen.findByRole('menuitem', { name: '归档任务' }));
  });

  it('renders the task drawer as a titled navigation surface with a separate library footer', () => {
    render(<Workspace {...props} />);
    fireEvent.click(screen.getByRole('button', { name: '展开任务列表' }));
    const sidebar = screen.getByRole('dialog', { name: '财务任务' });
    expect(screen.getByRole('heading', { name: '任务' })).toBeTruthy();
    expect(sidebar.querySelector('.workspace-search input')).toBe(screen.getByRole('searchbox', { name: '搜索任务' }));
    expect(sidebar.querySelector('.workspace-sidebar-footer .workspace-library')).toBe(screen.getByRole('button', { name: '方法库' }));
  });

  it('shows a failed archive in the menu and lets the same task retry', async () => {
    const onArchive = vi.fn().mockRejectedValueOnce(new Error('任务暂时被占用，请重试。')).mockResolvedValueOnce(undefined);
    render(<Workspace {...props} onArchive={onArchive} />);
    press(screen.getByRole('button', { name: '任务工具' }));
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
