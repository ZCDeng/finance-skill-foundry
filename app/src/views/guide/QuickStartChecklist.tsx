import { useEffect, useState } from 'react';
import { bridge, type Answer } from '../../bridge.js';
import { Button } from '../../components/ui/button.js';
import type { CloseStatus } from '../analysis/MonthCloseControlCenter.js';
import { errorText } from '../analysis/shared.js';
import type { GuideTarget } from './articles.js';

type StepState = 'done' | 'todo' | 'not_started';
type Step = { label: string; state: StepState; detail: string; target: GuideTarget };

const WORDS: Record<StepState, string> = { done: '已完成', todo: '待处理', not_started: '尚未开始' };

/**
 * The six quick-start steps, each read from the open task's month-close status, so a step
 * is done because the task says so and never because it was ticked or remembered locally.
 * Each row has one action, which goes to where the step is done. There is no 跳过.
 */
export function stepsFrom(status: CloseStatus): Step[] {
  const block = (key: string) => status.blocks.find((item) => item.key === key);
  const blocked = (key: string) => block(key)?.state === 'blocked';
  const firstItem = (key: string) => block(key)?.items.find((item) => item.blocking);
  const first = (key: string) => firstItem(key)?.text ?? '';
  const toGuide = (target: string | undefined, fallback: GuideTarget): GuideTarget =>
    target === 'controls' ? 'close' : (target as GuideTarget | undefined) ?? fallback;
  const source = block('source');
  const files = source?.items.filter((item) => item.target === 'datasets').length ?? 0;
  const review = block('review');
  const calculated = Boolean(review && review.state !== 'not_started');
  // A calculation made before the scope or the data changed has to run again; it is not done.
  const rerun = review?.items.find((item) => item.blocking && item.target === 'results');
  const draftItem = review?.items.find((item) => item.blocking && item.target !== 'results');
  const awaitingManager = review?.items.some((item) => item.text.startsWith('经理尚未复核'));
  return [
    { label: '添加资料', state: blocked('source') ? 'todo' : 'done', detail: blocked('source') ? '还没有资料' : `${files} 份`, target: 'datasets' },
    { label: '确认表结构', state: !files ? 'not_started' : blocked('structure') ? 'todo' : 'done', detail: first('structure'), target: 'structure' },
    { label: '确认分析范围', state: blocked('scope') ? 'todo' : 'done', detail: first('scope'), target: 'scope' },
    { label: '运行计算', state: !calculated ? 'not_started' : rerun ? 'todo' : 'done', detail: !calculated ? '还没有计算结果' : rerun?.text ?? '', target: 'results' },
    { label: '核对来源与异常', state: !files ? 'not_started' : blocked('controls') || blocked('exceptions') ? 'todo' : 'done',
      detail: first('controls') || first('exceptions'), target: toGuide((firstItem('controls') ?? firstItem('exceptions'))?.target, 'close') },
    { label: '保存文稿并复核', state: !calculated ? 'not_started' : draftItem ? 'todo' : 'done',
      detail: draftItem?.text ?? (calculated && awaitingManager ? '待经理复核' : ''), target: toGuide(draftItem?.target, 'drafts') },
  ];
}

/** Anything that changes a task's state says so on this event; the checklist reads it again. */
export const TASK_CHANGED_EVENT = 'fnd:task-changed';

export function QuickStartChecklist({ taskId, canOpen, onOpen }: { taskId?: string; canOpen: boolean; onOpen(target: GuideTarget): void }) {
  const [status, setStatus] = useState<CloseStatus | null>(null);
  const [error, setError] = useState('');
  const [version, setVersion] = useState(0);
  useEffect(() => {
    const changed = () => setVersion((value) => value + 1);
    window.addEventListener(TASK_CHANGED_EVENT, changed);
    return () => window.removeEventListener(TASK_CHANGED_EVENT, changed);
  }, []);
  useEffect(() => { setStatus(null); }, [taskId]);
  useEffect(() => {
    setError('');
    const api = bridge(); if (!api?.financeCall || !taskId) return;
    let live = true;
    void Promise.resolve(api.financeCall(taskId, 'finance-close-status') as Promise<Answer<CloseStatus> | undefined>).then((answer) => {
      if (!live || !answer) return;
      if (!answer.ok) setError(answer.message); else setStatus(answer.value);
    }).catch((failure) => { if (live) setError(errorText(failure)); });
    return () => { live = false; };
  }, [taskId, version]);
  if (!taskId) return <p className="analysis-note">打开或新建一个任务后，这里按任务的实际状态显示六步进度。</p>;
  if (error) return <p className="analysis-message analysis-message--error" role="alert">{error}</p>;
  if (!status) return <p className="analysis-note">正在读取这个任务的进度…</p>;
  return <ol className="fnd-checklist" aria-label="快速开始清单">
    {stepsFrom(status).map((step, index) => <li key={step.label} className={`fnd-checklist__step fnd-checklist__step--${step.state}`}>
      <span className="fnd-checklist__label">{index + 1} {step.label}</span>
      <span className="fnd-checklist__state">{WORDS[step.state]}{step.detail ? ` · ${step.detail}` : ''}</span>
      {step.state !== 'done' && canOpen ? <Button variant="link" size="sm" type="button" onClick={() => onOpen(step.target)}>去处理</Button> : null}
    </li>)}
  </ol>;
}
