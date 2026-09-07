// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Workspace } from '../src/components/Workspace.js';
import type { TaskRow } from '../src/bridge.js';
import { press } from './press.js';

const tasks: TaskRow[] = [
  { id: 'a'.repeat(32), title: '华东利润分析', period: '2026-08', skill_id: null, created_at: '', windows: 0 },
  { id: 'b'.repeat(32), title: '西南回款', period: null, skill_id: null, created_at: '', windows: 0 },
];
const props = { active: true, task: tasks[0], tasks, onPick: vi.fn(), onNew: vi.fn(),
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
});
