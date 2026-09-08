import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { BookOpen, Check, Columns2, Ellipsis, FolderOpen, MessageSquare, PanelLeftClose, PanelLeftOpen, Plus, Search, X } from 'lucide-react';
import type { TaskRow } from '../bridge.js';
import './workspace.css';
import { Button } from './ui/button.js';
import { Input } from './ui/input.js';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from './ui/dropdown-menu.js';

export interface WorkspaceRect { x: number; y: number; width: number; height: number }
interface Props {
  active: boolean;
  focusConversationRequest?: number;
  task: TaskRow | null;
  tasks: TaskRow[];
  onPick(id: string): void;
  onNew(): void;
  onMethods(): void;
  onData(): void;
  onHistory(): void;
  onRename?(id: string, title: string): Promise<void>;
  onLayout(rect: WorkspaceRect | null): void;
  conversation: ReactNode;
  children: ReactNode;
}
type Focus = 'split' | 'conversation' | 'results';
const mediaMatches = (query: string) => typeof window.matchMedia === 'function' && window.matchMedia(query).matches;

/** The native conversation gets a measured slot, independent of sidebar or zoom assumptions. */
export function Workspace({ active, focusConversationRequest = 0, task, tasks, onPick, onNew, onMethods, onData, onHistory, onRename, onLayout, conversation, children }: Props) {
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
      if (event.key !== 'Escape') return;
      if (toolsOpen) { setToolsOpen(false); return; }
      if (overlay) closeSidebar();
    };
    window.addEventListener('keydown', escape);
    return () => window.removeEventListener('keydown', escape);
  }, [overlay, toolsOpen, closeSidebar]);

  useEffect(() => {
    const cover = (event: Event) => setNativeCovered(Boolean((event as CustomEvent<{ open?: boolean }>).detail?.open));
    window.addEventListener('foundry:workspace-native-cover', cover);
    return () => window.removeEventListener('foundry:workspace-native-cover', cover);
  }, []);

  useLayoutEffect(() => {
    if (!active || !task || effective === 'results' || overlay || toolsOpen || nativeCovered || dragging) {
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
  }, [active, task?.id, effective, overlay, toolsOpen, nativeCovered, dragging, sidebar, chatWidth, onLayout]);

  const openMethods = () => { setFocus(narrow ? 'results' : 'split'); onMethods(); };
  const pick = (id: string) => { onPick(id); if (!wide) closeSidebar(); setToolsOpen(false); };
  const resized = (value: number) => setChatWidth(Math.min(640, Math.max(400, value)));
  const saveTitle = async () => {
    if (!task || !onRename || savingTitle || !title.trim()) return;
    const id = task.id;
    setSavingTitle(true); setTitleError('');
    try { await onRename(id, title.trim()); if (renamedTask.current === id) setRenaming(false); }
    catch (error) { if (renamedTask.current === id) setTitleError(error instanceof Error ? error.message : '保存名称失败，请重试。'); }
    finally { if (renamedTask.current === id) setSavingTitle(false); }
  };
  const shownTasks = [...tasks].reverse().filter((row) => `${row.title} ${row.period ?? ''}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()));

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
        <label className="workspace-search"><Search size={15} aria-hidden /><Input ref={search} type="search" aria-label="搜索任务"
          value={query} placeholder="搜索任务" onChange={(event) => setQuery(event.target.value)} /></label>
        <div className="workspace-tasklist">
          {shownTasks.map((row) => <button key={row.id} className="workspace-task" title={row.title} aria-current={task?.id === row.id ? 'true' : undefined}
            onClick={() => pick(row.id)}><span>{row.title}</span>{row.period ? <small>{row.period}</small> : null}</button>)}
          {shownTasks.length === 0 ? <p className="fnd-muted">{query ? '没有找到相关任务' : '从一个问题开始第一项分析'}</p> : null}
        </div>
        <div className="workspace-sidebar-footer">
          <button className="workspace-library" onClick={() => { openMethods(); if (!wide) closeSidebar(); }}><BookOpen size={16} aria-hidden />方法库</button>
        </div>
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
          {task?.period && !renaming ? <span>{task.period}</span> : null}</div>
          {task ? <div className="workspace-focus" role="group" aria-label="工作区布局">
            <Button size="icon" variant="ghost" hidden={narrow} aria-label="同时查看" title="同时查看" aria-pressed={effective === 'split'} onClick={() => setFocus(narrow ? 'conversation' : 'split')}><Columns2 size={17} aria-hidden /></Button>
            <Button size="icon" variant="ghost" aria-label="对话专注" title="对话专注" aria-pressed={effective === 'conversation'} onClick={() => setFocus('conversation')}><MessageSquare size={17} aria-hidden /></Button>
            <Button size="icon" variant="ghost" aria-label="成果专注" title="成果专注" aria-pressed={effective === 'results'} onClick={() => setFocus('results')}><FolderOpen size={17} aria-hidden /></Button>
          </div> : null}
          <DropdownMenu open={toolsOpen} onOpenChange={setToolsOpen}>
            <DropdownMenuTrigger asChild>
              <Button type="button" size="icon" variant="ghost" aria-label="任务工具" title="任务工具">
                <Ellipsis size={19} aria-hidden />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" aria-label="任务工具菜单">
              <DropdownMenuItem onSelect={() => openMethods()}>方法库</DropdownMenuItem>
              <DropdownMenuItem onSelect={() => onData()}>数据台</DropdownMenuItem>
              <DropdownMenuItem onSelect={() => onHistory()}>任务记录与旧版流程</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </header>
        <div className="workspace-panes">
          <section className="workspace-conversation" aria-label="持续对话" hidden={!task || effective === 'results'}>
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
    </div>
  );
}
