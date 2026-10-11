import { useId } from 'react';
import { ArrowRight, CircleCheck } from 'lucide-react';
import type { OverviewTask, OverviewTodo, TaskRow } from '../../bridge.js';
import { DisclosureSummary } from '../../components/Disclosure.js';
import { Button } from '../../components/ui/button.js';
import { formatPeriod } from '../../lib/period.js';
import { STEP_ICONS } from '../analysis/StepNav.js';
import { sectionOf, stepOf, STEP_INTROS, STEP_WORDS, STEPS, type Step, type StepState } from '../analysis/steps.js';
import { stepLines } from './lines.js';

/** The four segments' colours (tokens.css --fnd-seg-*), by the group a step belongs to. */
const SEGMENTS: Record<string, string> = { 月结: 'close', 财务分析: 'finance', 经营分析: 'operations', 汇报: 'report' };
/** The groups over the strip, each over the steps it holds. */
const GROUPS = STEPS.reduce<{ group: string; span: number }[]>((all, { group }) => {
  const last = all[all.length - 1];
  if (last?.group === group) last.span += 1; else all.push({ group, span: 1 });
  return all;
}, []);
/** To-dos shown under the strip before the rest fold away. */
export const TODO_SHOWN = 3;
/** Tasks the switcher names as pills; the rest are a row each under 其他进行中的任务. */
const PILLS = 5;

/** The step a task opens on: the first that waits on someone, else the first not begun, else 汇报. */
export function stepToOpen(states: Record<Step, StepState>): Step {
  const order = STEPS.map((item) => item.step);
  return order.find((step) => states[step] === 'todo' || states[step] === 'attention')
    ?? order.find((step) => states[step] === 'not_started') ?? 'report';
}

/** The task 总览 opens on: the one chosen this session while it is still active, else the one worked on last. */
export function currentRow(rows: OverviewTask[], chosen: string | null): OverviewTask | null {
  const picked = chosen ? rows.find((row) => row.task.id === chosen) : undefined;
  if (picked) return picked;
  // Overview order breaks ties: real tasks first, newest period first.
  return rows.reduce<OverviewTask | null>((best, row) => (!best || (row.active_at ?? '') > (best.active_at ?? '') ? row : best), null);
}

/** A to-do's step, as 1 资料 … 6 汇报: where its target lands among the six. */
export function stepWords(target: string | undefined): string | null {
  if (!target) return null;
  const step = stepOf(sectionOf(target));
  const index = STEPS.findIndex((item) => item.step === step);
  return index < 0 ? null : `${index + 1} ${STEPS[index].label}`;
}

const numbered = (step: Step) => `第 ${STEPS.findIndex((item) => item.step === step) + 1} 步 ${STEPS.find((item) => item.step === step)!.label}`;

/** A task's name with its period, the way every list in the app writes it. */
export function TaskName({ task }: { task: TaskRow }) {
  return <>
    <span className="fnd-overview__task-title">{task.title}</span>
    {task.period ? <span className="fnd-muted"> · <span className="fnd-period">{formatPeriod(task.period)}</span></span> : null}
    {task.sample && !task.title.startsWith('示例') ? <span className="fnd-overview__tag">示例</span> : null}
  </>;
}

/**
 * 总览's main card: the task worked on last, its six steps large with a line each, one button to the step that waits,
 * and its to-dos. Nothing here is decided anew: the states are steps.ts's, the lines read what the step pages show, the
 * to-dos are the month close's.
 */
export function Cockpit({ row, rows, states, onPick, onOpen, onOpenStep }: {
  row: OverviewTask; rows: OverviewTask[]; states: Record<Step, StepState> | null;
  onPick(taskId: string): void;
  onOpen(task: TaskRow, target: string): void;
  onOpenStep(task: TaskRow, step: Step): void;
}) {
  const id = useId();
  const { task } = row;
  // A framed card: its folds keep their chevrons inside (DESIGN.md 折叠段落).
  return <section className="fnd-cockpit fnd-fold-inset" aria-labelledby={`${id}-task`}>
    <header className="fnd-cockpit__head">
      <div className="fnd-cockpit__name">
        <p className="fnd-cockpit__eyebrow">当前任务</p>
        <h2 id={`${id}-task`} className="fnd-cockpit__title"><TaskName task={task} /></h2>
        <p className="fnd-cockpit__status">
          <span>{row.building ? '参考结果正在生成' : row.error ? `读取失败：${row.error}` : row.headline?.text ?? ''}</span>
          {row.headline?.detail ? <span className="fnd-muted">（{row.headline.detail}）</span> : null}
          {row.conclusion ? <span className="fnd-overview__conclusion" data-level={row.conclusion.level}>账：{row.conclusion.text}</span> : null}
        </p>
      </div>
      {rows.length > 1 ? <div className="fnd-cockpit__switch" role="group" aria-label="切换任务">
        {rows.slice(0, PILLS).map((other) => <button key={other.task.id} type="button" className="fnd-cockpit__pill"
          aria-pressed={other.task.id === task.id} title={other.task.period ? `${other.task.title} · ${formatPeriod(other.task.period)}` : other.task.title}
          onClick={() => onPick(other.task.id)}>{other.task.title}</button>)}
      </div> : null}
    </header>
    {states ? <>
      <Strip row={row} states={states} onOpenStep={onOpenStep} />
      <Next row={row} states={states} onOpenStep={onOpenStep} />
    </> : null}
    <Todos row={row} onOpen={onOpen} />
  </section>;
}

function Strip({ row, states, onOpenStep }: { row: OverviewTask; states: Record<Step, StepState>; onOpenStep(task: TaskRow, step: Step): void }) {
  const lines = stepLines(row, states);
  return <div className="fnd-cockpit__strip">
    {/* The four segments over their steps, in their colours; a reader hears each step's group in its name instead. */}
    <div className="fnd-cockpit__groups" aria-hidden>
      {GROUPS.map(({ group, span }) => <span key={group} data-segment={SEGMENTS[group]} style={{ gridColumn: `span ${span}` }}>{group}</span>)}
    </div>
    <ol className="fnd-cockpit__steps">
      {STEPS.map(({ step, label, group }, index) => {
        const Icon = STEP_ICONS[states[step]];
        return <li key={step} data-segment={SEGMENTS[group]}>
          <button type="button" className="fnd-cockpit__step" data-state={states[step]} onClick={() => onOpenStep(row.task, step)}
            aria-label={`${index + 1} ${label}（${group}），${STEP_WORDS[states[step]]}：${lines[step]}`}>
            <span className="fnd-cockpit__step-head">
              <Icon className="fnd-cockpit__step-icon" size={20} strokeWidth={1.75} aria-hidden />
              <span className="fnd-cockpit__step-name">{`${index + 1} ${label}`}</span>
            </span>
            <span className="fnd-cockpit__step-state">{STEP_WORDS[states[step]]}</span>
            <span className="fnd-cockpit__step-line">{lines[step]}</span>
          </button>
        </li>;
      })}
    </ol>
  </div>;
}

/** 继续：第 n 步: the first step that waits on someone, else the first not begun, and why in a few words. */
function Next({ row, states, onOpenStep }: { row: OverviewTask; states: Record<Step, StepState>; onOpenStep(task: TaskRow, step: Step): void }) {
  const step = stepToOpen(states);
  const waiting = row.todo.find((item) => item.target && stepOf(sectionOf(item.target)) === step);
  const reason = waiting?.text ?? (states[step] === 'not_started' ? STEP_INTROS[step] : '每一步都没有等你处理的事。');
  return <div className="fnd-cockpit__next">
    <Button type="button" onClick={() => onOpenStep(row.task, step)}>{`继续：${numbered(step)}`}<ArrowRight size={15} strokeWidth={1.5} aria-hidden /></Button>
    <span className="fnd-muted">{reason}</span>
  </div>;
}

function Todos({ row, onOpen }: { row: OverviewTask; onOpen(task: TaskRow, target: string): void }) {
  const id = useId();
  if (row.building || row.error) return null;
  if (!row.todo.length) return <p className="fnd-overview__clear"><CircleCheck size={16} strokeWidth={1.5} aria-hidden />没有挡住月结的事项。</p>;
  const item = (todo: OverviewTodo, index: number) => <li key={index}>
    <div className="fnd-overview__todo-text">
      <span>{todo.text}{stepWords(todo.target) ? <span className="fnd-overview__tag">{stepWords(todo.target)}</span> : null}</span>
    </div>
    {todo.target ? <Button type="button" size="sm" variant="outline" onClick={() => onOpen(row.task, todo.target!)}>
      去处理<ArrowRight size={13} strokeWidth={1.5} aria-hidden /><span className="sr-only">：{todo.text}</span>
    </Button> : null}
  </li>;
  const rest = row.todo.slice(TODO_SHOWN);
  return <section className="fnd-cockpit__todos" aria-labelledby={`${id}-todo`}>
    <h3 id={`${id}-todo`} className="fnd-cockpit__h">{`等你处理（${row.todo.length}）`}</h3>
    <ul className="fnd-overview__todos">{row.todo.slice(0, TODO_SHOWN).map(item)}</ul>
    {rest.length ? <details className="analysis-details">
      <DisclosureSummary>{`其余 ${rest.length} 条`}</DisclosureSummary>
      <ul className="fnd-overview__todos">{rest.map((todo, index) => item(todo, index + TODO_SHOWN))}</ul>
    </details> : null}
  </section>;
}
