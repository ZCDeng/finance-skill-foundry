import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { Archive, BookOpen, Check, Columns2, Ellipsis, FileClock, FolderOpen, MessageSquare, PanelLeftClose, PanelLeftOpen, Pencil, Plus, RotateCcw, Search, Sheet, Trash2, X, XCircle } from 'lucide-react';
import type { TaskLifecycleFilter, TaskRow } from '../bridge.js';
import './workspace.css';
import { Button } from './ui/button.js';
import { Input } from './ui/input.js';
import { formatPeriod } from '../lib/period.js';
import { searchKey } from '../lib/search.js';
import { PeriodWords, joinParts } from './PeriodWords.js';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from './ui/dropdown-menu.js';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from './ui/alert-dialog.js';

export interface WorkspaceRect { x: number; y: number; width: number; height: number }
interface Props {
  active: boolean;
  focusConversationRequest?: number;
  task: TaskRow | null;
  tasks: TaskRow[];
  lifecycleView: TaskLifecycleFilter;
  onLifecycleView(value: TaskLifecycleFilter): void;
  onPick(id: string): void;
  onNew(): void;
  onMethods(): void;
  onData(): void;
  onHistory(): void;
  onRename?(id: string, title: string): Promise<void>;
  onArchive?(id: string): Promise<void>;
  onTrash?(id: string): Promise<void>;
  onRestore?(id: string): Promise<void>;
  /** Delete one task in the trash for good. */
  onPurge?(id: string): Promise<void>;
  /** 已归档: every one to the trash. 回收站: every one deleted for good. Answers how many went. */
  onEmpty?(lifecycle: 'archived' | 'trashed', ids: string[]): Promise<number>;
  onLayout(rect: WorkspaceRect | null): void;
  conversation: ReactNode;
  /** What an example task is, under the header; nothing for a real task. */
  banner?: ReactNode;
  /** The guide is open in the conversation column: show the column even with no task or with results in focus. */
  guiding?: boolean;
  children: ReactNode;
}
type Focus = 'split' | 'conversation' | 'results';
/** What the list says after a task leaves it, with the way back when there is one. */
interface Notice { text: string; undo?: { id: string; to: 'active' | 'archived' } }
type Confirm = { kind: 'purge'; id: string; title: string } | { kind: 'empty'; lifecycle: 'archived' | 'trashed'; count: number; ids: string[] };
const mediaMatches = (query: string) => typeof window.matchMedia === 'function' && window.matchMedia(query).matches;

/** The native conversation gets a measured slot, independent of sidebar or zoom assumptions. */
const lifecycleLabels: Record<TaskLifecycleFilter, string> = {
  active: '进行中',
  archived: '已归档',
  trashed: '回收站',
  all: '全部',
};

export function Workspace({ active, focusConversationRequest = 0, task, tasks, lifecycleView, onLifecycleView, onPick, onNew, onMethods, onData, onHistory, onRename, onArchive, onTrash, onRestore, onPurge, onEmpty, onLayout, conversation, banner, guiding = false, children }: Props) {
  const [sidebar, setSidebar] = useState(() => mediaMatches('(min-width: 1360px)'));
  const [wide, setWide] = useState(() => mediaMatches('(min-width: 1360px)'));
  const [narrow, setNarrow] = useState(() => mediaMatches('(max-width: 1100px)'));
  const [query, setQuery] = useState('');
  const [focusByTask, setFocusByTask] = useState<Record<string, Focus>>({});
  const focus = focusByTask[task?.id ?? ''] ?? 'split';
  const setFocus = (value: Focus) => setFocusByTask((held) => ({ ...held, [task?.id ?? '']: value }));
  const [chatWidth, setChatWidth] = useState(420);
  const [toolsOpen, setToolsOpen] = useState(false);
  const [nativeCovered, setNativeCovered] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [title, setTitle] = useState('');
  const [savingTitle, setSavingTitle] = useState(false);
  const [titleError, setTitleError] = useState('');
  const [lifecycleBusy, setLifecycleBusy] = useState('');
  const [lifecycleError, setLifecycleError] = useState('');
  useEffect(() => setLifecycleError(''), [task?.id]);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [confirm, setConfirm] = useState<Confirm | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const [confirmError, setConfirmError] = useState('');
  // The notice speaks about the list the task left; opening another task or another list ends it.
  useEffect(() => { if (task) setNotice(null); }, [task?.id]);
  useEffect(() => setNotice(null), [lifecycleView]);
  const renamedTask = useRef(task?.id);
  renamedTask.current = task?.id;
  const slot = useRef<HTMLDivElement>(null);
  const drag = useRef<{ x: number; width: number } | null>(null);
  const sidebarToggle = useRef<HTMLButtonElement>(null);
  const search = useRef<HTMLInputElement>(null);
  const sidebarPanel = useRef<HTMLElement>(null);
  const canvas = useRef<HTMLElement>(null);
  const scrollPositions = useRef(new Map<string, number>());
  const effective = narrow && focus === 'split' ? 'results' : focus;
  const overlay = sidebar && !wide;

  useEffect(() => {
    if (focusConversationRequest > 0) setFocus(narrow ? 'conversation' : 'split');
  }, [focusConversationRequest]);
  useEffect(() => { setRenaming(false); setTitleError(''); setSavingTitle(false); }, [task?.id]);

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return;
    const large = window.matchMedia('(min-width: 1360px)');
    const small = window.matchMedia('(max-width: 1100px)');
    const resize = () => { setWide(large.matches); setNarrow(small.matches); if (!large.matches) setSidebar(false); };
    large.addEventListener('change', resize); small.addEventListener('change', resize);
    return () => { large.removeEventListener('change', resize); small.removeEventListener('change', resize); };
  }, []);

  const closeSidebar = useCallback(() => { setSidebar(false); sidebarToggle.current?.focus(); }, []);
  useEffect(() => { if (overlay) search.current?.focus(); }, [overlay]);
  useLayoutEffect(() => {
    const node = canvas.current;
    const key = task?.id ?? '';
    if (node) node.scrollTop = scrollPositions.current.get(key) ?? 0;
    return () => { if (node) scrollPositions.current.set(key, node.scrollTop); };
  }, [task?.id]);
  useEffect(() => {
    const escape = (event: KeyboardEvent) => {
      if (overlay && event.key === 'Tab') {
        const stops = [...(sidebarPanel.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled)') ?? [])];
        const first = stops[0], last = stops.at(-1);
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
      if (event.key !== 'Escape' || confirm) return;
      if (toolsOpen) { setToolsOpen(false); return; }
      if (overlay) closeSidebar();
    };
    window.addEventListener('keydown', escape);
    return () => window.removeEventListener('keydown', escape);
  }, [overlay, toolsOpen, confirm, closeSidebar]);

  useEffect(() => {
    const cover = (event: Event) => setNativeCovered(Boolean((event as CustomEvent<{ open?: boolean }>).detail?.open));
    window.addEventListener('foundry:workspace-native-cover', cover);
    return () => window.removeEventListener('foundry:workspace-native-cover', cover);
  }, []);

  useLayoutEffect(() => {
    if (!active || !task || effective === 'results' || overlay || toolsOpen || nativeCovered || dragging || confirm) {
      onLayout(null); return;
    }
    let scheduled = 0;
    const measure = () => {
      const rect = slot.current?.getBoundingClientRect();
      onLayout(rect && rect.width > 0 && rect.height > 0
        ? { x: rect.x, y: rect.y, width: rect.width, height: rect.height } : null);
    };
    const resize = () => { cancelAnimationFrame(scheduled); scheduled = requestAnimationFrame(measure); };
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(resize);
    if (slot.current) observer?.observe(slot.current);
    window.addEventListener('resize', resize);
    measure();
    return () => { observer?.disconnect(); window.removeEventListener('resize', resize); cancelAnimationFrame(scheduled); };
  }, [active, task?.id, effective, overlay, toolsOpen, nativeCovered, dragging, confirm, sidebar, chatWidth, onLayout]);

  const openMethods = () => { setFocus(narrow ? 'results' : 'split'); onMethods(); };
  const pick = (id: string) => { onPick(id); if (!wide) closeSidebar(); setToolsOpen(false); };
  const lifecycleStatus = task?.lifecycle_status ?? 'active';
  /** After a task leaves the list on screen, the list is where the operator lands. */
  const backToList = (text: string, undo?: Notice['undo']) => {
    setNotice({ text, undo });
    setSidebar(true);
  };
  const lifecycleAction = async (action: 'archive' | 'trash' | 'restore') => {
    if (!task || lifecycleBusy) return;
    const { id, title: name } = task;
    setLifecycleBusy(action);
    setLifecycleError('');
    try {
      if (action === 'archive') await onArchive?.(id);
      else if (action === 'trash') await onTrash?.(id);
      else await onRestore?.(id);
      if (renamedTask.current === id) setToolsOpen(false);
      if (action === 'archive') backToList(`已归档「${name}」`, { id, to: 'active' });
      else if (action === 'trash') backToList(`已将「${name}」移入回收站`, { id, to: lifecycleStatus === 'archived' ? 'archived' : 'active' });
    } catch (error) {
      if (renamedTask.current === task.id) setLifecycleError(error instanceof Error ? error.message : '任务操作未完成，请重试。');
    } finally {
      setLifecycleBusy('');
    }
  };
  const undo = async () => {
    const back = notice?.undo;
    if (!back || lifecycleBusy) return;
    setLifecycleBusy('undo');
    try {
      if (back.to === 'active') await onRestore?.(back.id);
      else await onArchive?.(back.id);
      setNotice(null);
    } catch (error) {
      setNotice({ text: error instanceof Error ? error.message : '撤销未完成，请重试。' });
    } finally {
      setLifecycleBusy('');
    }
  };
  const confirmed = async () => {
    if (!confirm || confirmBusy) return;
    setConfirmBusy(true);
    setConfirmError('');
    try {
      if (confirm.kind === 'purge') {
        await onPurge?.(confirm.id);
        backToList(`已永久删除「${confirm.title}」`);
      } else {
        const count = await onEmpty?.(confirm.lifecycle, confirm.ids) ?? 0;
        backToList(confirm.lifecycle === 'archived' ? `已把 ${count} 个归档任务移入回收站` : `已永久删除 ${count} 个任务`);
      }
      setConfirm(null);
    } catch (error) {
      setConfirmError(error instanceof Error ? error.message : '操作未完成，请重试。');
    } finally {
      setConfirmBusy(false);
    }
  };
  const emptyable = lifecycleView === 'archived' || lifecycleView === 'trashed' ? lifecycleView : null;
  const resized = (value: number) => setChatWidth(Math.min(640, Math.max(400, value)));
  const saveTitle = async () => {
    if (!task || !onRename || savingTitle || !title.trim()) return;
    const id = task.id;
    setSavingTitle(true); setTitleError('');
    try { await onRename(id, title.trim()); if (renamedTask.current === id) setRenaming(false); }
    catch (error) { if (renamedTask.current === id) setTitleError(error instanceof Error ? error.message : '保存名称失败，请重试。'); }
    finally { if (renamedTask.current === id) setSavingTitle(false); }
  };
  // The period is found both as written (2026-08) and as shown (2026 年 8 月, 2026年8月, 1-8月).
  const shownTasks = [...tasks].reverse().filter((row) => searchKey(`${row.title} ${row.period ?? ''} ${formatPeriod(row.period)}`).includes(searchKey(query)));

  return (
    <div className="workspace" data-sidebar={sidebar ? 'open' : 'closed'} data-focus={task ? effective : 'empty'} data-dragging={dragging ? 'yes' : 'no'}
      style={{ '--chat-width': `${chatWidth}px` } as CSSProperties}>
      {overlay ? <button className="workspace-scrim" aria-label="关闭任务列表" onClick={closeSidebar} /> : null}
      <aside ref={sidebarPanel} className="workspace-sidebar" hidden={!sidebar} role={overlay ? 'dialog' : undefined} aria-modal={overlay ? true : undefined} aria-label="财务任务">
        <div className="workspace-sidebar-header">
          <h2>任务</h2>
          {overlay ? <Button size="icon" variant="ghost" aria-label="收起任务列表" onClick={closeSidebar}><X size={18} aria-hidden /></Button> : null}
        </div>
        <Button className="workspace-new" onClick={() => { onNew(); if (!wide) closeSidebar(); }}><Plus size={16} aria-hidden />新建任务</Button>
        <div className="workspace-lifecycle" role="group" aria-label="任务状态">
          {(['active', 'archived', 'trashed'] as const).map((value) =>
            <button key={value} type="button" aria-pressed={lifecycleView === value} onClick={() => onLifecycleView(value)}>{lifecycleLabels[value]}</button>)}
        </div>
        {notice ? <div className="workspace-notice" role="status">
          <span>{notice.text}</span>
          {notice.undo ? <Button size="sm" variant="link" disabled={Boolean(lifecycleBusy)} onClick={() => void undo()}>撤销</Button> : null}
          <Button size="icon" variant="ghost" aria-label="关闭提示" onClick={() => setNotice(null)}><X size={14} aria-hidden /></Button>
        </div> : null}
        <label className="workspace-search"><Search size={15} aria-hidden /><Input ref={search} type="search" aria-label="搜索任务"
          value={query} placeholder="搜索任务" onChange={(event) => setQuery(event.target.value)} /></label>
        {emptyable && onEmpty && tasks.length ? <Button className="workspace-empty-list" size="sm" variant={emptyable === 'trashed' ? 'destructive' : 'ghost'}
          onClick={() => { setConfirmError(''); setConfirm({ kind: 'empty', lifecycle: emptyable, count: tasks.length, ids: tasks.map((row) => row.id) }); }}>
          {emptyable === 'archived' ? <><Trash2 size={14} aria-hidden />全部移入回收站</> : <><XCircle size={14} aria-hidden />清空回收站</>}
        </Button> : null}
        <div className="workspace-tasklist">
          {shownTasks.map((row) => <button key={row.id} className="workspace-task" title={row.title} aria-label={row.title} aria-current={task?.id === row.id ? 'true' : undefined}
            onClick={() => pick(row.id)}><span>{row.title}</span><small>{joinParts([row.period ? <PeriodWords value={row.period} /> : null, row.sample ? '示例' : null, lifecycleLabels[row.lifecycle_status ?? 'active']])}</small></button>)}
          {shownTasks.length === 0 ? <p className="fnd-muted">{query ? '没有找到相关任务' : lifecycleView === 'archived' ? '没有已归档的任务' : lifecycleView === 'trashed' ? '回收站是空的' : '从一个问题开始第一项分析'}</p> : null}
        </div>
        {/* Places to go, kept apart from what can be done to the open task (the header's 这个任务 menu). */}
        <nav className="workspace-sidebar-footer" aria-label="更多工具">
          <button className="workspace-library" onClick={() => { openMethods(); if (!wide) closeSidebar(); }}><BookOpen size={16} aria-hidden />方法库</button>
          <button className="workspace-library" onClick={() => { onData(); if (!wide) closeSidebar(); }}><Sheet size={16} aria-hidden />数据台</button>
          <button className="workspace-library" onClick={() => { onHistory(); if (!wide) closeSidebar(); }}><FileClock size={16} aria-hidden />任务记录与旧版流程</button>
        </nav>
      </aside>
      <section className="workspace-main" aria-label="任务工作区" inert={overlay ? true : undefined}>
        <header className="workspace-header">
          <Button size="icon" variant="ghost" ref={sidebarToggle} aria-label={sidebar ? '收起任务列表' : '展开任务列表'}
            aria-expanded={sidebar} onClick={() => setSidebar((value) => !value)} title="任务列表">
            {sidebar ? <PanelLeftClose size={18} aria-hidden /> : <PanelLeftOpen size={18} aria-hidden />}
          </Button>
          <div className="workspace-title">{renaming ? <form className="workspace-rename" onSubmit={(event) => { event.preventDefault(); void saveTitle(); }}>
            <Input aria-label="任务名称" autoFocus value={title} maxLength={240} disabled={savingTitle} onChange={(event) => setTitle(event.target.value)}
              onKeyDown={(event) => { if (event.key === 'Enter' && event.nativeEvent.isComposing) event.preventDefault(); if (event.key === 'Escape') { event.preventDefault(); setRenaming(false); } }} />
            <Button size="icon" variant="ghost" aria-label="保存任务名称" disabled={savingTitle || !title.trim()}><Check size={16} aria-hidden /></Button>
            <Button size="icon" variant="ghost" type="button" aria-label="取消改名" onClick={() => setRenaming(false)}><X size={16} aria-hidden /></Button>
            {titleError ? <span role="alert">{titleError}</span> : null}
          </form> : <h1 title={task?.title}>{task && onRename ? <button className="workspace-title-button" aria-label={`修改任务名称：${task.title}`}
            onClick={() => { setTitle(task.title); setTitleError(''); setRenaming(true); }}>{task.title}</button> : task?.title ?? '开始一项分析'}</h1>}
          {task?.period && !renaming ? <span className="fnd-period">{formatPeriod(task.period)}</span> : null}</div>
          {task ? <div className="workspace-focus" role="group" aria-label="工作区布局">
            <Button size="icon" variant="ghost" hidden={narrow} aria-label="同时查看" title="同时查看" aria-pressed={effective === 'split'} onClick={() => setFocus(narrow ? 'conversation' : 'split')}><Columns2 size={17} aria-hidden /></Button>
            <Button size="icon" variant="ghost" aria-label="对话专注" title="对话专注" aria-pressed={effective === 'conversation'} onClick={() => setFocus('conversation')}><MessageSquare size={17} aria-hidden /></Button>
            <Button size="icon" variant="ghost" aria-label="成果专注" title="成果专注" aria-pressed={effective === 'results'} onClick={() => setFocus('results')}><FolderOpen size={17} aria-hidden /></Button>
          </div> : null}
          {/* Only what acts on the open task, named on the menu's first line so it is clear which task it is. */}
          {task ? <DropdownMenu open={toolsOpen} onOpenChange={setToolsOpen}>
            <DropdownMenuTrigger asChild>
              <Button type="button" size="icon" variant="ghost" aria-label="这个任务" title="这个任务的操作">
                <Ellipsis size={19} aria-hidden />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" aria-label="这个任务的操作">
              <DropdownMenuLabel className="max-w-72 truncate font-normal text-[var(--fnd-muted)]" title={task.title}>{task.title}</DropdownMenuLabel>
              {onRename && lifecycleStatus === 'active' ? <DropdownMenuItem onSelect={() => {
                setTitle(task.title); setTitleError('');
                // After the menu has closed, so its focus return does not pull focus off the name field.
                setTimeout(() => setRenaming(true), 0);
              }}><Pencil size={15} strokeWidth={1.5} aria-hidden />改名</DropdownMenuItem> : null}
              {lifecycleStatus === 'active' && onArchive ? <DropdownMenuItem disabled={Boolean(lifecycleBusy)} onSelect={(event) => { event.preventDefault(); void lifecycleAction('archive'); }}><Archive size={15} strokeWidth={1.5} aria-hidden />归档任务</DropdownMenuItem> : null}
              {lifecycleStatus !== 'active' && onRestore ? <DropdownMenuItem disabled={Boolean(lifecycleBusy)} onSelect={(event) => { event.preventDefault(); void lifecycleAction('restore'); }}><RotateCcw size={15} strokeWidth={1.5} aria-hidden />恢复任务</DropdownMenuItem> : null}
              {(lifecycleStatus !== 'trashed' && onTrash) || (lifecycleStatus === 'trashed' && onPurge) ? <DropdownMenuSeparator /> : null}
              {lifecycleStatus !== 'trashed' && onTrash ? <DropdownMenuItem disabled={Boolean(lifecycleBusy)} onSelect={(event) => { event.preventDefault(); void lifecycleAction('trash'); }}><Trash2 size={15} strokeWidth={1.5} aria-hidden />移入回收站</DropdownMenuItem> : null}
              {lifecycleStatus === 'trashed' && onPurge ? <DropdownMenuItem variant="destructive" disabled={Boolean(lifecycleBusy)} onSelect={() => {
                const target = { kind: 'purge' as const, id: task.id, title: task.title };
                setConfirmError('');
                // Open after the menu has closed, so the menu's focus return does not land on the dialog.
                setTimeout(() => setConfirm(target), 0);
              }}><XCircle size={15} strokeWidth={1.5} aria-hidden />永久删除</DropdownMenuItem> : null}
              {lifecycleError ? <p role="alert" className="max-w-72 px-2 py-1 text-sm break-words">{lifecycleError}</p> : null}
            </DropdownMenuContent>
          </DropdownMenu> : null}
        </header>
        {task ? banner : null}
        <div className="workspace-panes">
          <section className="workspace-conversation" aria-label={guiding ? '使用指南' : '持续对话'} hidden={!guiding && (!task || effective === 'results')}>
            <div className="workspace-native" ref={slot}>{conversation}</div>
          </section>
          <div className="workspace-divider" role="separator" aria-label="调整对话宽度" aria-orientation="vertical"
            tabIndex={0} aria-valuemin={400} aria-valuemax={640} aria-valuenow={chatWidth} hidden={!task || effective !== 'split'}
            onKeyDown={(event) => {
              if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
              event.preventDefault(); resized(event.key === 'Home' ? 400 : event.key === 'End' ? 640 : chatWidth + (event.key === 'ArrowRight' ? 20 : -20));
            }} onDoubleClick={() => resized(420)}
            onPointerDown={(event) => { drag.current = { x: event.clientX, width: chatWidth }; event.currentTarget.setPointerCapture(event.pointerId); setDragging(true); }}
            onPointerMove={(event) => { if (drag.current) resized(drag.current.width + event.clientX - drag.current.x); }}
            onPointerUp={() => { drag.current = null; setDragging(false); }}
            onLostPointerCapture={() => { drag.current = null; setDragging(false); }} />
          <section className="workspace-results" ref={canvas} aria-label="分析成果" hidden={Boolean(task) && effective === 'conversation'}>{children}</section>
        </div>
      </section>
      <AlertDialog open={Boolean(confirm)} onOpenChange={(open) => { if (!open && !confirmBusy) setConfirm(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{confirm?.kind === 'purge' ? `永久删除「${confirm.title}」？`
              : confirm?.lifecycle === 'archived' ? `把已归档的 ${confirm.count} 个任务移入回收站？`
              : `永久删除回收站里的 ${confirm?.count ?? 0} 个任务？`}</AlertDialogTitle>
            <AlertDialogDescription>{confirm?.kind === 'empty' && confirm.lifecycle === 'archived'
              ? '移入后它们只在回收站里，还可以逐个恢复。'
              : '任务的资料、分析结果、文稿和导出文件都会一起删除，删除后不能恢复。'}</AlertDialogDescription>
          </AlertDialogHeader>
          {confirmError ? <p role="alert" className="m-0 text-[length:var(--fnd-size-body)] text-[var(--fnd-warning)]">{confirmError}</p> : null}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={confirmBusy}>取消</AlertDialogCancel>
            <AlertDialogAction variant={confirm?.kind === 'empty' && confirm.lifecycle === 'archived' ? 'default' : 'destructive'} disabled={confirmBusy} aria-busy={confirmBusy || undefined}
              onClick={(event) => { event.preventDefault(); void confirmed(); }}>
              {confirm?.kind === 'purge' ? '永久删除'
                : confirm?.lifecycle === 'archived' ? '全部移入回收站' : `永久删除 ${confirm?.count ?? 0} 个任务`}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
