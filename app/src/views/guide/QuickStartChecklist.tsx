import { useEffect, useState } from 'react';
import { bridge, type OverviewTask } from '../../bridge.js';
import { Button } from '../../components/ui/button.js';
import { usePreferences } from '../../components/Preferences.js';
import { STEP_ICONS } from '../analysis/StepNav.js';
import { STEPS, STEP_WORDS, overviewStepStates, sectionOf, stepOf, type Step, type StepState } from '../analysis/steps.js';
import { errorText } from '../analysis/shared.js';
import type { GuideTarget } from './articles.js';
import { Loading, SkeletonRows } from '../../components/Loading.js';

type Row = { step: Step; label: string; state: StepState; detail: string; target: GuideTarget };

/** Where each step opens when no to-do names a closer place. */
const STEP_TARGETS: Record<Step, GuideTarget> = {
  materials: 'datasets', scope: 'scope', close: 'close', results: 'results', operations: 'operations', report: 'dashboard',
};
const GUIDE_TARGETS: readonly string[] = ['datasets', 'scope', 'structure', 'billing', 'results', 'operations', 'dashboard', 'drafts', 'workbook', 'close'];
const NOT_STARTED: Record<Step, string> = {
  materials: '还没有资料', scope: '', close: '', results: '还没有计算结果', operations: '还没有经营分析结果', report: '还没有看板卡片或文稿',
};

/** A to-do's place in the guide's words: a control is handled on 勾稽, next month's draft on 资料. */
function guideTarget(target: string, step: Step): GuideTarget {
  if (target === 'controls') return 'close';
  if (target === 'rollforward') return 'datasets';
  return GUIDE_TARGETS.includes(target) ? target as GuideTarget : STEP_TARGETS[step];
}

/**
 * The task's six steps, read the way its step row and 总览's 本月进度 read them (steps.ts), so a step is done
 * because the task says so and never because it was ticked or remembered locally. A step with a to-do names the
 * first one and goes where it is handled; a step this period does without says 本期不做. There is no 跳过 here.
 */
export function stepsFrom(row: OverviewTask, skipped: readonly Step[] = []): Row[] | null {
  const read = overviewStepStates(row);
  if (!read) return null;
  return STEPS.map(({ step, label }) => {
    const state: StepState = skipped.includes(step) ? 'skipped' : read[step];
    const todo = row.todo.find((item) => item.target && stepOf(sectionOf(item.target)) === step);
    const detail = state === 'skipped' ? ''
      : state === 'done' ? (step === 'materials' ? `${row.work?.datasets ?? 0} 份资料` : '')
        : state === 'not_started' ? NOT_STARTED[step]
          : todo?.text ?? (step === 'report' ? '看板上有卡等你认可' : '');
    return { step, label, state, detail, target: todo?.target ? guideTarget(todo.target, step) : STEP_TARGETS[step] };
  });
}

/** The step row's mark for a state; the state is written beside it, so the mark is only decoration. */
function mark(state: StepState) {
  const Icon = STEP_ICONS[state];
  return <Icon className="fnd-checklist__mark" size={14} strokeWidth={1.75} aria-hidden />;
}

/** Anything that changes a task's state says so on this event; the checklist reads it again. */
export const TASK_CHANGED_EVENT = 'fnd:task-changed';

export function QuickStartChecklist({ taskId, canOpen, onOpen }: { taskId?: string; canOpen: boolean; onOpen(target: GuideTarget): void }) {
  const { preferences } = usePreferences();
  // undefined while reading; null when 总览 does not list the task (archived, or in the trash).
  const [row, setRow] = useState<OverviewTask | null | undefined>(undefined);
  const [error, setError] = useState('');
  const [version, setVersion] = useState(0);
  const readable = Boolean(bridge()?.overview);
  useEffect(() => {
    const changed = () => setVersion((value) => value + 1);
    window.addEventListener(TASK_CHANGED_EVENT, changed);
    return () => window.removeEventListener(TASK_CHANGED_EVENT, changed);
  }, []);
  useEffect(() => { setRow(undefined); }, [taskId]);
  useEffect(() => {
    setError('');
    const api = bridge(); if (!api?.overview || !taskId) return;
    let live = true;
    void Promise.resolve(api.overview()).then((answer) => {
      if (!live || !answer) return;
      if (!answer.ok) setError(answer.message);
      else setRow(answer.value.tasks.find((item) => item.task.id === taskId) ?? null);
    }).catch((failure) => { if (live) setError(errorText(failure)); });
    return () => { live = false; };
  }, [taskId, version]);
  if (!taskId) return <p className="analysis-note">打开或新建一个任务后，这里按任务的实际状态显示六步进度。</p>;
  if (!readable) return <p className="analysis-note">这里读不到任务的进度，打开任务后看步骤行上的状态。</p>;
  if (error) return <p className="analysis-message analysis-message--error" role="alert">{error}</p>;
  if (row === undefined) return <Loading label="正在读取这个任务的进度…"><SkeletonRows rows={6} meta={false} /></Loading>;
  if (row === null) return <p className="analysis-note">这个任务不在进行中，恢复后这里才显示六步进度。</p>;
  const steps = stepsFrom(row, preferences.skipped_steps[taskId] ?? []);
  if (!steps) return <p className="analysis-note">{row.building ? '参考结果正在生成，生成后这里显示六步进度。' : row.error ? `读取失败：${row.error}` : '这个任务的进度还读不出来。'}</p>;
  return <ol className="fnd-checklist" aria-label="快速开始清单">
    {steps.map((step, index) => <li key={step.step} className={`fnd-checklist__step fnd-checklist__step--${step.state}`}>
      <span className="fnd-checklist__label">{mark(step.state)}{index + 1} {step.label}</span>
      <span className="fnd-checklist__state">{STEP_WORDS[step.state]}{step.detail ? ` · ${step.detail}` : ''}</span>
      {step.state !== 'done' && step.state !== 'skipped' && canOpen
        ? <Button variant="link" size="sm" type="button" onClick={() => onOpen(step.target)}>去处理</Button> : null}
    </li>)}
  </ol>;
}
