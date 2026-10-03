import { useCallback, useEffect, useRef, useState } from 'react';

import './styles/base.css';

import { Shell, type Screen } from './components/Shell.js';
import { Workspace, type WorkspaceRect } from './components/Workspace.js';
import {
  type AnalysisDraftRow,
  type AnalysisExportRow,
  type Answer,
  type DeliverableRow,
  type GalleryRow,
  type LaunchSpec,
  type PreviewSpec,
  type TaskLifecycleFilter,
  type TaskDetail as Detail,
  type HarnessStatus,
  type TaskRow,
  bridge,
  isWorkbook,
} from './bridge.js';
import { Deliverables, type OpenDeliverable } from './views/Deliverables.js';
import { PreviewBar } from './views/Preview.js';
import { TaskDetail } from './views/TaskDetail.js';
import { Tasks } from './views/Tasks.js';
import { DataBar, Formulator } from './views/Formulator.js';
import { Analysis } from './views/Analysis.js';
import { readCopy, writeCopy } from './views/analysis/workingCopy.js';
import { Booting, WiringTrouble, type OpenSession } from './views/Workbench.js';
import { Button } from './components/ui/button.js';
import { GUIDE_EVENT, GuideHub } from './views/guide/GuideHub.js';
import type { GuideTarget } from './views/guide/articles.js';

/**
 * A refusal is a sentence the store wrote. Show it, do not translate it.
 *
 * `onDismiss` is not decoration. On the two embedded screens this sentence is
 * drawn in a column the native page covers, so it is shown *instead* of that
 * page -- and nothing else would ever clear it: the status poll stops once the
 * wiring is ready, so a failed call would leave the harness hidden behind an
 * error with no way back to it.
 */
function Refusal({ message, onDismiss }: { message: string; onDismiss?: () => void }) {
  // `onDismiss` is only passed where this is standing in for a page it displaced,
  // so it is also the signal to draw as a panel rather than as a stripe across
  // the column.
  return (
    <div className={onDismiss ? 'fnd-refusal fnd-refusal--panel' : 'fnd-refusal'}>
      <p>{message}</p>
      {onDismiss ? (
        <Button variant="link" type="button" style={{ marginTop: 12 }} onClick={onDismiss}>
          知道了
        </Button>
      ) : null}
    </div>
  );
}

export function App() {
  const api = bridge();
  const [screen, setScreen] = useState<Screen>('analysis');
  /** The task every session opened here binds to. Survives a screen change. */
  const [current, setCurrent] = useState<string | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  /** The task being read on 任务. A different question from which one is bound. */
  const [open, setOpen] = useState<string | null>(null);
  const [openDetail, setOpenDetail] = useState<Detail | null>(null);
  const [session, setSession] = useState<(OpenSession & { taskId: string }) | null>(null);
  const [opening, setOpening] = useState(false);
  const [creating, setCreating] = useState(false);
  const [status, setStatus] = useState<HarnessStatus | null>(null);
  const [formulator, setFormulator] = useState<LaunchSpec | null>(null);
  const [busyData, setBusyData] = useState(false);
  const [tasks, setTasks] = useState<TaskRow[]>([]);
  /** True once the store has answered for the active list: before that, empty means "not asked yet". */
  const [tasksLoaded, setTasksLoaded] = useState(false);
  const [taskLifecycleView, setTaskLifecycleView] = useState<TaskLifecycleFilter>('active');
  /** Until this is true, an empty list is "not asked yet", not "no tasks". */
  const [gallery, setGallery] = useState<GalleryRow[]>([]);
  /** The version the gallery is showing, and its text once the store answers. */
  const [opened, setOpened] = useState<OpenDeliverable | null>(null);
  /** The window whose workbook is being written, so its button can say so. */
  const [exporting, setExporting] = useState<string | null>(null);
  /** The workbook on screen in the Univer viewer, and the digest being put up. */
  const [preview, setPreview] = useState<PreviewSpec | null>(null);
  const [previewing, setPreviewing] = useState<string | null>(null);
  const [previewTechnicalOpen, setPreviewTechnicalOpen] = useState(false);
  const [locatorPreview, setLocatorPreview] = useState(false);
  const [reading, setReading] = useState<{ sha: string; text: string } | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [asked, setAsked] = useState(false);
  const [guideArticle, setGuideArticle] = useState('');
  // Where focus was when the guide opened, so closing it puts the reader back there.
  const guideOpener = useRef<HTMLElement | null>(null);
  const askedRef = useRef(false);
  askedRef.current = asked;
  const openGuideAt = useCallback((article: string) => {
    if (!askedRef.current) guideOpener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setGuideArticle(article);
    setAsked(true);
  }, []);
  const closeGuide = useCallback(() => {
    setAsked(false);
    const back = guideOpener.current;
    guideOpener.current = null;
    requestAnimationFrame(() => (back?.isConnected ? back : document.querySelector<HTMLElement>('.fnd-head__help'))?.focus());
  }, []);
  // First run: a store with no task opens the guide at 第一次使用, once per launch. Nothing is
  // remembered on disk; "has this store ever had a task" answers the same question better.
  const firstRunShown = useRef(false);
  useEffect(() => {
    if (firstRunShown.current || !tasksLoaded || tasks.length || !inWorkspaceRef.current) return;
    firstRunShown.current = true;
    openGuideAt('first-run');
  }, [tasksLoaded, tasks.length, screen, openGuideAt]);
  // A 「?」 in the workspace opens the guide at its block's article; ⌘/Ctrl + ? opens or
  // closes it, on the screens where it can be drawn and nowhere else.
  useEffect(() => {
    const open = (event: Event) => openGuideAt(String((event as CustomEvent).detail ?? ''));
    const key = (event: KeyboardEvent) => {
      if (event.defaultPrevented || !(event.metaKey || event.ctrlKey) || event.key !== '?') return;
      if (screenRef.current !== 'analysis' && screenRef.current !== 'workbench') return;
      event.preventDefault();
      if (askedRef.current) closeGuide(); else openGuideAt('');
    };
    window.addEventListener(GUIDE_EVENT, open);
    window.addEventListener('keydown', key);
    return () => { window.removeEventListener(GUIDE_EVENT, open); window.removeEventListener('keydown', key); };
  }, [openGuideAt, closeGuide]);
  const [conversationFocus, setConversationFocus] = useState(0);
  const [conversationProblem, setConversationProblem] = useState<string | null>(null);
  const [nativeRect, setNativeRect] = useState<WorkspaceRect | null>(null);
  const [sections, setSections] = useState<Record<string, 'materials' | 'results' | 'drafts' | 'close' | 'methods'>>({});
  const analysisSection = sections[current ?? ''] ?? 'results';
  const [draftRequest, setDraftRequest] = useState({ count: 0, taskId: '', draftId: '' });
  const setAnalysisSection = useCallback((value: 'materials' | 'results' | 'drafts' | 'close' | 'methods') => {
    setSections((held) => ({ ...held, [current ?? '']: value }));
  }, [current]);
  const openRef = useRef(open);
  openRef.current = open;
  const screenRef = useRef(screen);
  screenRef.current = screen;
  const inWorkspaceRef = useRef(false);
  inWorkspaceRef.current = screen === 'analysis' || screen === 'workbench';
  const openedRef = useRef(opened);
  openedRef.current = opened;
  const locatorPreviewRef = useRef(locatorPreview);
  locatorPreviewRef.current = locatorPreview;
  const previewRequest = useRef(0);
  const pendingPreview = useRef<{ request: number; taskId: string; sha: string } | null>(null);
  const previewOperation = useRef<Promise<void>>(Promise.resolve());
  const detailSequence = useRef(0);
  const openSequence = useRef(0);
  const readerSequence = useRef(0);
  const currentRef = useRef(current);
  currentRef.current = current;
  const explicitSelection = useRef(false);
  const selectionRevision = useRef(0);
  const taskListSequence = useRef(0);
  const gallerySequence = useRef(0);
  const taskLifecycleViewRef = useRef(taskLifecycleView);
  taskLifecycleViewRef.current = taskLifecycleView;
  const tasksRef = useRef(tasks);
  tasksRef.current = tasks;
  const conversationQueue = useRef<Promise<unknown>>(Promise.resolve());
  const layoutRevision = useRef(0);
  const inWorkspace = screen === 'analysis' || screen === 'workbench';
  const onWorkspaceLayout = useCallback((next: WorkspaceRect | null) => {
    setNativeRect((held) => JSON.stringify(held) === JSON.stringify(next) ? held : next);
  }, []);

  const ownsPreviewTarget = useCallback((taskId: string, sha: string) => {
    if (screenRef.current === 'tasks') return openRef.current === taskId;
    if (screenRef.current === 'deliverables') {
      const currentOpen = openedRef.current;
      return currentOpen?.task.id === taskId && currentOpen.row.sha256 === sha;
    }
    return false;
  }, []);
  const ownsPreview = useCallback((candidate: PreviewSpec | null) => {
    if (!candidate) return false;
    if (locatorPreviewRef.current) return screenRef.current === 'analysis';
    return ownsPreviewTarget(candidate.task, candidate.sha256);
  }, [ownsPreviewTarget]);

  /** Every answer lands here, so one refusal path serves every screen. */
  const take = useCallback(<T,>(answer: Answer<T>, use: (value: T) => void) => {
    if (answer.ok) {
      setProblem(null);
      use(answer.value);
    } else {
      setProblem(answer.message);
    }
  }, []);

  const previewErrorMessage = useCallback((error: unknown) => (
    error instanceof Error ? error.message : '表格预览暂未就绪，请重试。'
  ), []);

  /*
   * The list, for the strip as much as for 任务.
   *
   * The picker in the task bar is on every screen the workbench draws, so this
   * is no longer something only the list screen needs. It also carries the
   * binding: with no task chosen, the newest one is taken, because an operator
   * coming back to this window is almost always coming back to what they were
   * last doing, and a strip that says nothing is a strip they have to act on
   * before the app does anything.
   */
  const refreshTasks = useCallback((view: TaskLifecycleFilter = taskLifecycleView) => {
    if (!api) return;
    const sequence = ++taskListSequence.current;
    void api.tasks(view).then((a) =>
      take(a, (rows) => {
        if (taskListSequence.current !== sequence) return;
        setTasks(rows);
        if (view === 'active') setTasksLoaded(true);
        setCurrent((held) => (held && rows.some((row) => row.id === held)) ? held : (explicitSelection.current ? null : rows[rows.length - 1]?.id ?? null));
      }),
    );
  }, [api, take, taskLifecycleView]);

  useEffect(() => {
    refreshTasks(taskLifecycleView);
  }, [refreshTasks, taskLifecycleView]);

  /** Every version this machine has produced, newest first, across all tasks. */
  const refreshGallery = useCallback(() => {
    if (!api) return;
    const sequence = ++gallerySequence.current;
    void api.gallery().then((answer) => {
      if (gallerySequence.current === sequence) take(answer, setGallery);
    });
  }, [api, take]);

  useEffect(() => {
    if (screen !== 'deliverables') return;
    refreshGallery();
  }, [screen, refreshGallery]);

  /** Ignore stale reads after a task switch, including failures from the prior task. */
  const refreshDetail = useCallback((id: string | null) => {
    if (currentRef.current !== id) return;
    const sequence = ++detailSequence.current;
    if (!api || !id) { setDetail(null); return; }
    void api.task(id).then((answer) => {
      if (currentRef.current === id && detailSequence.current === sequence) take(answer, setDetail);
    });
  }, [api, take]);
  useEffect(() => { refreshDetail(current); }, [refreshDetail, current]);

  const refreshOpenDetail = useCallback((id: string | null) => {
    if (openRef.current !== id) return;
    const sequence = ++openSequence.current;
    setOpenDetail(null);
    if (!api || !id) return;
    void api.task(id).then((answer) => {
      if (openRef.current === id && openSequence.current === sequence) take(answer, setOpenDetail);
    });
  }, [api, take]);
  useEffect(() => {
    readerSequence.current += 1;
    setReading(null);
    refreshOpenDetail(open);
  }, [refreshOpenDetail, open]);

  /*
   * Polled while the workbench is open rather than read once: the wiring runs
   * after the window is already up, so a screen that asked once would report
   * `pending` forever and a failure that arrived a second later would never be
   * drawn. It stops on its own as soon as the answer is not `pending`.
   */
  useEffect(() => {
    if (!api?.harnessStatus || !inWorkspace) return;
    let live = true;
    const ask = () => {
      void api.harnessStatus?.().then((a) =>
        take(a, (value) => {
          if (!live) return;
          setStatus(value);
          if (value.wiring.state === 'pending') window.setTimeout(ask, 1000);
        }),
      );
    };
    ask();
    return () => {
      live = false;
    };
  }, [api, inWorkspace, take]);

  /*
   * What the fence stopped, said in this window rather than in the page.
   *
   * A cancelled request surfaces inside the runtime's own UI as a call that did
   * not arrive, which names nothing an operator can act on. Subscribed once for
   * the life of the window and on every screen: the page keeps running when the
   * operator is on 任务, and a refusal that arrived while they were there would
   * otherwise be lost.
   */
  useEffect(() => {
    if (!api?.onHarnessRefused) return;
    return api.onHarnessRefused((reason) => {
      setConversationProblem(reason);
    });
  }, [api]);

  // A runtime that dies keeps its last page in the pane; say so and offer 重新连接, which starts a new one.
  useEffect(() => {
    if (!api?.onHarnessExited) return;
    return api.onHarnessExited(() => {
      setConversationProblem('对话服务意外停止。资料和已保存的成果不受影响，点「重新连接」会重新启动对话并回到这项任务。');
    });
  }, [api]);

  useEffect(() => {
    if (!api?.formulatorStatus || screen !== 'formulator') return;
    void api.formulatorStatus().then((a) => take(a, (value) => setFormulator(value.running)));
  }, [api, screen, take]);

  /*
   * The guide covers the workbench, so it decides whether the page below gets a
   * rectangle at all.
   *
   * Shown on a store with no task, which is the one moment it is certainly true
   * that nobody here has done this before, and otherwise only when the header
   * asks for it. Not remembered anywhere: `file://` has no storage worth
   * relying on, and "has this operator ever made a task" is a better answer to
   * the same question than a flag would be.
   */
  const guide = inWorkspace && asked;
  const ready = status?.wiring.state === 'ready';
  const failed = status?.wiring.state === 'failed';

  // Hide before geometry changes, then reveal only the current, correctly bound session.
  useEffect(() => {
    let live = true;
    const revision = ++layoutRevision.current;
    const show = async () => {
      if (previewTechnicalOpen && ownsPreview(preview)) {
        await api?.paneVisible?.('');
        return;
      }
      if (inWorkspace && locatorPreview && preview) {
        await api?.paneVisible?.('preview');
        return;
      }
      if (inWorkspace) {
        if (!nativeRect || !ready || guide || conversationProblem || opening || session?.taskId !== current) {
          await api?.paneVisible?.(''); return;
        }
        const layout = await api?.harnessLayout?.({ ...nativeRect, revision });
        if (!live) return;
        if (layout && !layout.ok) { setConversationProblem(layout.message); return; }
        await api?.paneVisible?.('workbench');
      } else {
        if (!problem && locatorPreview && preview) {
          await api?.paneVisible?.('preview');
          return;
        }
        const shown = !problem && screen === 'formulator' && formulator ? 'formulator'
          : !problem && (screen === 'deliverables' || screen === 'tasks') && ownsPreview(preview) ? 'preview' : '';
        await api?.paneVisible?.(shown);
      }
    };
    void show().catch((error: unknown) => { if (live) setConversationProblem(error instanceof Error ? error.message : '对话布局暂未就绪，请重试。'); });
    return () => { live = false; };
  }, [api, inWorkspace, nativeRect, ready, guide, conversationProblem, opening, session, current, screen, problem, formulator, preview, previewTechnicalOpen, locatorPreview, ownsPreview]);

  /**
   * Take the preview down, gateway and all.
   *
   * The renderer's own state is cleared only once main confirms: the strip
   * says a server is running, and it must not stop saying so before the
   * server has stopped.
   */
  const closePreview = useCallback(() => {
    const request = ++previewRequest.current;
    pendingPreview.current = null;
    setPreviewing(null);
    setPreviewTechnicalOpen(false);
    if (!api?.previewClose) {
      setPreview(null);
      setLocatorPreview(false);
      return;
    }
    previewOperation.current = previewOperation.current
      .catch(() => undefined)
      .then(async () => {
        const answer = await api.previewClose!();
        take(answer, () => {
          if (previewRequest.current !== request) return;
          setPreview(null);
          setLocatorPreview(false);
        });
      })
      .catch((error: unknown) => {
        if (previewRequest.current === request) setProblem(previewErrorMessage(error));
      });
    void previewOperation.current;
  }, [api, previewErrorMessage, take]);

  /**
   * Put one archived workbook up in the viewer.
   *
   * Main resolves the digest to a path, fences the gateway to that path's own
   * directory, and starts it; the renderer only ever names the task and the
   * digest, which it already has. The import can take seconds, so the button
   * that asked says so until the answer comes.
   */
  const openPreview = useCallback(
    (taskId: string, sha: string, ext: string) => {
      if (!api?.previewOpen) return;
      const request = ++previewRequest.current;
      pendingPreview.current = { request, taskId, sha };
      setPreviewing(sha);
      setPreviewTechnicalOpen(false);
      previewOperation.current = previewOperation.current
        .catch(() => undefined)
        .then(async () => {
          if (previewRequest.current !== request || !ownsPreviewTarget(taskId, sha)) return;
          const answer = await api.previewOpen!(taskId, sha, ext);
          if (pendingPreview.current?.request === request) pendingPreview.current = null;
          if (previewRequest.current !== request || !ownsPreviewTarget(taskId, sha)) {
            if (api.previewClose) await api.previewClose();
            return;
          }
          take(answer, (next) => {
            if (previewRequest.current !== request || !ownsPreviewTarget(taskId, sha)) return;
            setPreviewTechnicalOpen(false);
            setLocatorPreview(false);
            setPreview(next);
          });
        })
        .catch((error: unknown) => {
          if (previewRequest.current === request) setProblem(previewErrorMessage(error));
        })
        .finally(() => {
          if (pendingPreview.current?.request === request) pendingPreview.current = null;
          if (previewRequest.current === request) setPreviewing(null);
        });
      void previewOperation.current;
    },
    [api, ownsPreviewTarget, previewErrorMessage, take],
  );

  /*
   * The preview lives only while the version it shows is the one on screen.
   *
   * That is the operator's second condition (KTD20): the gateway runs while a
   * preview is open, and "open" means the strip above the viewer is naming
   * this version on this screen. Leaving the screen, going back to the list,
   * or opening a different version takes it down rather than leaving a server
   * up behind a page that no longer mentions it.
   */
  useEffect(() => {
    const pending = pendingPreview.current;
    if (pending && !ownsPreviewTarget(pending.taskId, pending.sha)) {
      previewRequest.current += 1;
      pendingPreview.current = null;
      setPreviewing(null);
    }
    if (!preview) return;
    if (!ownsPreview(preview)) closePreview();
  }, [preview, screen, opened, open, ownsPreview, ownsPreviewTarget, closePreview]);

  const launchFormulator = useCallback(() => {
    if (!api?.formulatorLaunch) return;
    setBusyData(true);
    void api
      .formulatorLaunch()
      .then((a) => take(a, setFormulator))
      .finally(() => setBusyData(false));
  }, [api, take]);

  const stopFormulator = useCallback(() => {
    if (!api?.formulatorStop) return;
    setBusyData(true);
    void api
      .formulatorStop()
      .then((a) => take(a, () => setFormulator(null)))
      .finally(() => setBusyData(false));
  }, [api, take]);

  const newAnalysisTask = useCallback(async (question: string) => {
    if (!api) throw new Error('分析服务暂未连接，请重新打开应用。');
    const selection = selectionRevision.current;
    const result = await api.taskNew(question.trim().replace(/\s+/g, ' ').slice(0, 120) || '新的财务分析', '');
    if (!result.ok) { setProblem(result.message); throw new Error(result.message); }
    if (selectionRevision.current === selection) {
      setTaskLifecycleView('active');
      currentRef.current = result.value.id;
      explicitSelection.current = true;
      setCurrent(result.value.id);
    }
    refreshTasks('active');
    return result.value.id;
  }, [api, refreshTasks]);

  /** The synthetic practice task, opened on the 资料 tab with the guide's checklist beside it. */
  const openSampleTask = useCallback(async () => {
    if (!api?.taskSample) throw new Error('这个版本还不能创建示例任务。');
    const result = await api.taskSample();
    if (!result.ok) throw new Error(result.message);
    setTaskLifecycleView('active');
    currentRef.current = result.value.id;
    explicitSelection.current = true;
    setCurrent(result.value.id);
    refreshTasks('active');
    setSections((held) => ({ ...held, [result.value.id]: 'materials' }));
    setGuideArticle('quick-start');
  }, [api, refreshTasks]);

  const changeTaskLifecycle = useCallback(async (id: string, action: 'archive' | 'trash' | 'restore') => {
    if (!api) throw new Error('任务服务暂未连接，请重新打开应用。');
    const call = action === 'archive' ? api.taskArchive : action === 'trash' ? api.taskTrash : api.taskRestore;
    if (!call) throw new Error('当前安装版还没有任务归档接口，请更新后重试。');
    const selection = selectionRevision.current;
    const currentAtStart = currentRef.current;
    const result = await call(id);
    if (!result.ok) throw new Error(result.message);
    const nextView = result.value.lifecycle_status;
    // Invalidate reads started before this mutation and update the retained list
    // before the user can reopen it while the next gallery read is still loading.
    gallerySequence.current += 1;
    setGallery((rows) => nextView === 'trashed'
      ? rows.filter((row) => row.task.id !== id)
      : rows.map((row) => row.task.id === id ? { ...row, task: { ...row.task, lifecycle_status: nextView } } : row));
    const stillSameSelection = selectionRevision.current === selection && currentRef.current === currentAtStart;
    setTasks((rows) => rows.filter((row) => row.id !== id));
    if (!stillSameSelection) {
      refreshTasks(taskLifecycleViewRef.current);
      if (screenRef.current === 'deliverables') refreshGallery();
      return;
    }
    setTaskLifecycleView(nextView);
    if (currentRef.current === id) {
      closePreview();
      currentRef.current = id;
      explicitSelection.current = true;
      setCurrent(id);
      if (nextView !== 'active') {
        setConversationProblem(null);
        setSession(null);
      }
    }
    refreshTasks(nextView);
    if (screenRef.current === 'deliverables') refreshGallery();
  }, [api, closePreview, refreshGallery, refreshTasks]);

  const chatAnalysis = useCallback(async (question?: string, draftId?: string,
    options?: { submit?: boolean; requestId?: string; targetTaskId?: string }) => {
    const target = options?.targetTaskId ?? currentRef.current;
    if (!api?.harnessOpen || !target) throw new Error('请先选择任务，或等待对话服务连接。');
    const targetRow = tasksRef.current.find((row) => row.id === target);
    if (targetRow && (targetRow.lifecycle_status ?? 'active') !== 'active') {
      const message = '归档或回收站任务只能查看已有成果，恢复后才能继续对话。';
      if (currentRef.current === target) {
        setSession(null);
        setConversationProblem(message);
      }
      throw new Error(message);
    }
    if (currentRef.current === target && (question !== undefined || draftId !== undefined)) setConversationFocus((value) => value + 1);
    const operation = conversationQueue.current.catch(() => undefined).then(async () => {
      if (question === undefined && draftId === undefined && currentRef.current !== target) return;
      setOpening(true);
      setSession(null);
      let connected = false;
      try {
        const result = await api.harnessOpen!('analysis', target, {
          verbatim: question, draftId, submit: options?.submit, requestId: options?.requestId,
        });
        if (!result.ok) throw new Error(result.message);
        connected = true;
        if (currentRef.current === target) {
          setSession({ ...result.value, intent: 'analysis', taskId: target });
          setConversationProblem(null);
          // Sending something takes the column back for the conversation; a background reconnect leaves the guide open.
          if (question !== undefined || draftId !== undefined) setAsked(false);
        }
        if (options?.submit && result.value.submitted !== true) {
          throw new Error(result.value.blockedReason || '问题尚未发送，请检查对话中的模型设置后重试。');
        }
      } catch (error) {
        if (!connected && currentRef.current === target) setConversationProblem(error instanceof Error ? error.message : '对话连接失败，请重试。');
        throw error;
      } finally {
        // A background seed may have moved the one resident native view. Rebind
        // the visible task before revealing it, even if current never changed.
        const visibleTask = currentRef.current;
        const visibleRow = visibleTask ? tasksRef.current.find((row) => row.id === visibleTask) : undefined;
        if (visibleTask && visibleTask !== target && (!visibleRow || (visibleRow.lifecycle_status ?? 'active') === 'active')) {
          try {
            const restored = await api.harnessOpen!('analysis', visibleTask);
            if (currentRef.current === visibleTask) {
              if (restored.ok) {
                setSession({ ...restored.value, intent: 'analysis', taskId: visibleTask });
                setConversationProblem(null);
              } else setConversationProblem(restored.message);
            }
          } catch (error) {
            if (currentRef.current === visibleTask) setConversationProblem(error instanceof Error ? error.message : '对话连接失败，请重试。');
          }
        }
        setOpening(false);
      }
    });
    conversationQueue.current = operation;
    await operation;
  }, [api]);

  useEffect(() => {
    if (!inWorkspace || !ready || !current) return;
    const row = tasks.find((task) => task.id === current);
    if (!row || (row.lifecycle_status ?? 'active') !== 'active') return;
    // Opening without a seed restores the session's own draft and never submits it.
    void chatAnalysis(undefined, undefined, { targetTaskId: current }).catch(() => undefined);
  }, [inWorkspace, ready, current, tasks, chatAnalysis]);

  /** Name a task from 任务, and open it there. The workbench binds to it too. */
  const createTask = useCallback(
    (title: string, period: string) => {
      if (!api) return;
      setCreating(true);
      void api
        .taskNew(title, period)
        .then((a) =>
          take(a, ({ id }) => {
            setTaskLifecycleView('active');
            refreshTasks('active');
            setCurrent(id);
            setOpen(id);
          }),
        )
        .finally(() => setCreating(false));
    },
    [api, take, refreshTasks],
  );

  /*
   * Open one version from the gallery.
   *
   * The row is shown before its text arrives, so the header an operator needs
   * to place the document -- task, cause, digest -- is on screen while the
   * store is still being read. A refusal clears it rather than leaving a
   * header over an empty page.
   */
  const openDeliverable = useCallback(
    (task: TaskRow, row: DeliverableRow) => {
      if (!api) return;
      setOpened({ task, row, text: null });
      // A workbook is not read here. The header still opens -- an operator has
      // to be able to place the version they are about to hand to Excel -- and
      // the body offers the handoff instead of a document.
      if (isWorkbook(row)) return;
      void api.deliverableText(task.id, row.sha256).then((a) =>
        take(a, (text) =>
          setOpened((held) =>
            held && held.row.sha256 === row.sha256 ? { ...held, text } : held,
          ),
        ),
      );
    },
    [api, take],
  );

  /**
   * Hand a filed analysis export to the default program.
   *
   * The row's task, digest and format go over the bridge and nothing else; main
   * asks the CLI where this task filed those bytes.
   */
  const openExport = useCallback(
    (task: TaskRow, exported: AnalysisExportRow) => {
      if (!api?.analysisExportOpen) return;
      void api.analysisExportOpen(task.id, exported.sha256, exported.format).then((a) => take(a, () => undefined));
    },
    [api, take],
  );

  /** Hand the open workbook to whatever this machine opens spreadsheets with. */
  const openWorkbook = useCallback(() => {
    if (!api || !opened) return;
    void api
      .deliverableOpen(opened.task.id, opened.row.sha256, opened.row.ext ?? '.xlsx')
      .then((a) => take(a, () => undefined));
  }, [api, opened, take]);

  /**
   * Export from the deliverables screen, where the task is the row's own.
   *
   * `exportWorkbook` reads `open`, which is the task screen's selection and is
   * null here. This one is told which task, and refreshes the gallery rather
   * than a task detail.
   */
  const exportFromGallery = useCallback(
    (task: TaskRow, windowId: string) => {
      if (!api) return;
      setExporting(windowId);
      void api
        .exportWorkbook(task.id, windowId)
        .then((a) =>
          take(a, (filed) => {
            void refreshGallery();
            void api.deliverableOpen(task.id, filed.sha256, filed.ext).then((b) => take(b, () => undefined));
          }),
        )
        .finally(() => setExporting(null));
    },
    [api, take, refreshGallery],
  );

  /** The same handoff from the task screen, where the version is a row. */
  const openWorkbookOnTask = useCallback(
    (sha: string, ext: string) => {
      if (!api || open === null) return;
      void api.deliverableOpen(open, sha, ext).then((a) => take(a, () => undefined));
    },
    [api, open, take],
  );

  /**
   * Render a window as a workbook, then open it.
   *
   * Opening it is the point of asking, and a button that filed a version and
   * said nothing would leave the operator hunting a row they cannot tell from
   * the last one. The list is refreshed either way, so the new version is on
   * screen behind whatever their spreadsheet software did.
   */
  const exportWorkbook = useCallback(
    (windowId: string) => {
      if (!api || open === null) return;
      setExporting(windowId);
      void api
        .exportWorkbook(open, windowId)
        .then((a) =>
          take(a, (filed) => {
            refreshOpenDetail(open);
            void refreshDetail(open);
            void api.deliverableOpen(open, filed.sha256, filed.ext).then((b) => take(b, () => undefined));
          }),
        )
        .finally(() => setExporting(null));
    },
    [api, open, take, refreshDetail, refreshOpenDetail],
  );

  const read = useCallback(
    (sha: string) => {
      if (!api || open === null) return;
      const target = open;
      const sequence = ++readerSequence.current;
      void api.deliverableText(target, sha).then((answer) => {
        if (openRef.current === target && readerSequence.current === sequence) take(answer, (text) => setReading({ sha, text }));
      });
    },
    [api, open, take],
  );

  if (!api) {
    return (
      <Shell screen={screen} onScreen={setScreen}>
        <p className="fnd-empty">
          分析服务尚未连接。请从 FA Foundry 桌面应用打开工作区。
        </p>
      </Shell>
    );
  }

  const bound = tasks.find((row) => row.id === current) ?? null;
  const boundLifecycle = bound?.lifecycle_status ?? 'active';
  const boundReadOnly = Boolean(bound && boundLifecycle !== 'active');
  const pickAnalysisTask = (id: string) => {
    selectionRevision.current += 1;
    explicitSelection.current = true; currentRef.current = id || null;
    setCurrent(id || null); setDetail(null); setSession(null); setConversationProblem(null); setScreen('analysis');
  };
  /**
   * Open a draft from 成果库 on its task's 文稿 tab, with that version selected.
   *
   * The selection is written first, because the analysis screen reads it when
   * another task is bound the way the task picker binds it. The task already
   * bound gets the version through `draftRequest` instead.
   */
  const openDraft = (task: TaskRow, draft: AnalysisDraftRow) => {
    const saved = `${task.id}:selection`;
    const view = task.lifecycle_status ?? 'active';
    writeCopy(saved, { ...readCopy<{ analysis?: string; draft?: string }>(saved), draft: draft.draft_id });
    setSections((held) => ({ ...held, [task.id]: 'drafts' }));
    setOpened(null);
    setTaskLifecycleView(view);
    setTasks((rows) => rows.some((row) => row.id === task.id) ? rows : [...rows, task]);
    refreshTasks(view);
    setDraftRequest((held) => ({ count: held.count + 1, taskId: task.id, draftId: draft.draft_id }));
    if (task.id === current) {
      setScreen('analysis');
    } else {
      pickAnalysisTask(task.id);
    }
  };

  return (
    <Shell
      screen={screen}
      onScreen={(next) => {
        if (next !== 'deliverables') setOpened(null);
        setScreen(next);
      }}
      onGuide={inWorkspace ? () => openGuideAt('') : undefined}
      covered={preview !== null && (screen === 'deliverables' || screen === 'tasks' || locatorPreview)}
      strip={
        screen === 'formulator' ? (
          <DataBar
            task={bound}
            detail={detail}
            running={formulator}
            busy={busyData}
            onLaunch={launchFormulator}
            onStop={stopFormulator}
          />
        ) : preview && (screen === 'deliverables' || screen === 'tasks' || locatorPreview) ? (
          <PreviewBar
            preview={preview}
            task={tasks.find((row) => row.id === preview.task) ?? null}
            onTechnicalOpenChange={setPreviewTechnicalOpen}
            onClose={closePreview}
          />
        ) : undefined
      }
    >
      {problem && !inWorkspace ? <Refusal message={problem} onDismiss={() => setProblem(null)} /> : null}
      <div className="workspace-mount" hidden={!inWorkspace}>
        <Workspace active={inWorkspace} focusConversationRequest={conversationFocus} task={bound} tasks={tasks} guiding={guide}
          lifecycleView={taskLifecycleView} onLifecycleView={(view) => {
            if (taskLifecycleViewRef.current === view) return;
            selectionRevision.current += 1;
            taskListSequence.current += 1;
            taskLifecycleViewRef.current = view;
            setTaskLifecycleView(view);
          }} onPick={pickAnalysisTask}
          onNew={() => pickAnalysisTask('')}
          onMethods={() => setAnalysisSection('methods')}
          onData={() => setScreen('formulator')}
          onHistory={() => { setOpen(current); setScreen('tasks'); }}
          onRename={api.taskRename ? async (id, title) => {
            const result = await api.taskRename!(id, title);
            if (!result.ok) throw new Error(result.message);
            setTasks((rows) => rows.map((row) => row.id === id ? { ...row, title: result.value.title } : row));
          } : undefined}
          onArchive={api.taskArchive ? (id) => changeTaskLifecycle(id, 'archive') : undefined}
          onTrash={api.taskTrash ? (id) => changeTaskLifecycle(id, 'trash') : undefined}
          onRestore={api.taskRestore ? (id) => changeTaskLifecycle(id, 'restore') : undefined}
          onLayout={onWorkspaceLayout}
          conversation={guide ? <GuideHub article={guideArticle} canOpen={Boolean(bound) && !boundReadOnly} taskId={bound?.id}
              onClose={closeGuide}
              onSample={api.taskSample ? openSampleTask : undefined}
              onOwnData={() => { closeGuide(); requestAnimationFrame(() => document.getElementById('analysis-question')?.focus()); }}
              onOpen={(target: GuideTarget) => {
                setAnalysisSection(target === 'results' ? 'results' : target === 'drafts' ? 'drafts' : target === 'close' ? 'close' : 'materials');
                const anchor = { scope: '.analysis-scope-card', structure: '.analysis-structure-panel', datasets: '.analysis-source-list' }[target as 'scope' | 'structure' | 'datasets'];
                if (anchor) setTimeout(() => document.querySelector(anchor)?.scrollIntoView?.({ block: 'start' }), 60);
              }} />
            : boundReadOnly ? <div className="workspace-connection"><h2>任务已停用对话</h2><p>归档或回收站任务只能查看已有成果，恢复后才能继续分析。</p></div>
            : conversationProblem ? <div className="workspace-connection" role="alert"><h2>对话暂时中断</h2><p>{conversationProblem}</p>
              <Button variant="outline" disabled={opening}
                onClick={() => { setConversationProblem(null); void chatAnalysis().catch(() => undefined); }}>重新连接</Button></div>
            : failed ? <div className="workspace-connection"><WiringTrouble status={status} /></div>
            : !ready || opening ? <div className="workspace-connection"><Booting /></div>
            : session?.taskId !== current ? <div className="workspace-connection"><p>连接这项任务的对话</p><Button variant="outline" onClick={() => void chatAnalysis().catch(() => undefined)}>继续分析</Button></div> : null}>
          {problem ? <Refusal message={problem} onDismiss={() => setProblem(null)} /> : null}
          {boundReadOnly ? <div className="fnd-empty"><h2>任务已停用编辑</h2><p>这个任务在{boundLifecycle === 'archived' ? '归档' : '回收站'}中。可以查看已生成成果，恢复任务后打开文稿、继续提问或打开数据定位。</p><Button variant="outline" onClick={() => bound ? void changeTaskLifecycle(bound.id, 'restore') : undefined}>恢复任务</Button></div> :
            <Analysis active={inWorkspace} embedded section={analysisSection} onSectionChange={setAnalysisSection}
              task={bound} tasks={tasks} draftRequest={draftRequest} onPick={pickAnalysisTask} onNew={newAnalysisTask} onChat={chatAnalysis}
              onLocatorPreview={api.sourceLocatorOpen ? (spec) => {
                // The locator answer carries no origin. Where the viewer is
                // comes from `previewStatus`, as it does for every other preview.
                void (async () => {
                  let origin = '';
                  if (api.previewStatus) {
                    const status = await api.previewStatus();
                    if (status.ok) origin = status.value.running?.origin ?? '';
                  }
                  setPreview({ ...spec, origin });
                  setLocatorPreview(true);
                })();
              } : undefined} />}
        </Workspace>
      </div>
      {screen === 'tasks' && open === null ? (
        <Tasks tasks={tasks} busy={creating} onOpen={setOpen} onCreate={createTask} />
      ) : null}
      {screen === 'tasks' && open !== null && openDetail ? (
        <TaskDetail
          detail={openDetail}
          onBack={() => setOpen(null)}
          onRead={read}
          onExport={exportWorkbook}
          onOpenWorkbook={openWorkbookOnTask}
          onPreview={api.previewOpen ? (sha, ext) => openPreview(open, sha, ext) : undefined}
          previewing={previewing}
          busy={exporting}
          reading={reading}
        />
      ) : null}
      {screen === 'formulator' ? <Formulator running={formulator} /> : null}
      {screen === 'deliverables' ? (
        <Deliverables
          rows={gallery}
          open={opened}
          onOpen={openDeliverable}
          onOpenDraft={openDraft}
          onOpenExport={api.analysisExportOpen ? openExport : undefined}
          onOpenWorkbook={openWorkbook}
          onPreview={
            api.previewOpen ? (task, row) => openPreview(task.id, row.sha256, row.ext ?? '.xlsx') : undefined
          }
          previewing={previewing}
          onExport={exportFromGallery}
          busy={exporting}
          onBack={() => setOpened(null)}
        />
      ) : null}
    </Shell>
  );
}
