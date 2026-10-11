import { Fragment, type KeyboardEvent, type ReactNode } from 'react';
import { ArrowRight, CircleAlert, CircleCheck, CircleDashed, CircleMinus, CircleSlash, TriangleAlert } from 'lucide-react';
import { Button } from '../../components/ui/button.js';
import { Tabs, TabsList, TabsTrigger } from '../../components/ui/tabs.js';
import { REPORT_VIEWS, STEPS, STEP_INTROS, STEP_WORDS, isSkippable, unreconciled, type ReportView, type Step, type StepState } from './steps.js';

const ICONS = { done: CircleCheck, todo: CircleSlash, attention: CircleAlert, not_started: CircleDashed, skipped: CircleMinus } as const;
const numberOf = (step: Step) => STEPS.findIndex((item) => item.step === step) + 1;
const labelOf = (step: Step) => STEPS.find((item) => item.step === step)!.label;

/** Arrow keys, Home and End move along a row of triggers and open the one they land on, as the tabs did. */
function roving<T extends string>(ids: T[], current: T, choose: (id: T) => void, prefix: string) {
  return (event: KeyboardEvent<HTMLButtonElement>) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const index = ids.indexOf(current);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? ids.length - 1
      : (index + (event.key === 'ArrowRight' ? 1 : -1) + ids.length) % ids.length;
    choose(ids[next]);
    document.getElementById(`${prefix}${ids[next]}`)?.focus();
  };
}

/**
 * The six steps in place of the six tabs: 月结 (1 资料 · 2 范围 · 3 勾稽) ｜ 4 财务分析 ｜ 5 经营分析 ｜ 6 汇报,
 * each with its state. Where the results column is narrow (the conversation open beside it) the names give way
 * to their numbers, still read out and shown on hover.
 */
export function StepNav({ step, states, onStep, tools }: {
  step: Step | 'methods'; states: Record<Step, StepState>; onStep(step: Step): void; tools?: ReactNode;
}) {
  const ids = STEPS.map((item) => item.step);
  return <Tabs value={step === 'methods' ? '' : step} onValueChange={(value) => onStep(value as Step)} activationMode="manual">
    <div className="analysis-tabbar analysis-steps-bar">
      <TabsList variant="line" className="analysis-tabs analysis-steps" aria-label="任务步骤">
        {STEPS.map(({ step: id, label, group }, index) => {
          const Icon = ICONS[states[id]];
          const opensGroup = index === 0 || STEPS[index - 1].group !== group;
          return <Fragment key={id}>
            {opensGroup && index > 0 ? <span className="analysis-steps__rule" aria-hidden /> : null}
            {opensGroup && group !== label ? <span className="analysis-steps__group" aria-hidden>{group}</span> : null}
            <TabsTrigger id={`analysis-tab-${id}`} value={id} data-state-step={states[id]}
              aria-label={`${index + 1} ${label}，${STEP_WORDS[states[id]]}`} title={`${index + 1} ${label} · ${STEP_WORDS[states[id]]}`}
              onClick={() => onStep(id)} onKeyDown={roving(ids, step === 'methods' ? ids[0] : step, onStep, 'analysis-tab-')}>
              <Icon className="analysis-steps__mark" size={14} strokeWidth={1.75} aria-hidden />
              <b className="analysis-steps__number">{index + 1}</b>
              <em className="analysis-steps__label">{label}</em>
            </TabsTrigger>
          </Fragment>;
        })}
      </TabsList>
      {tools ? <div className="analysis-tabbar-tools">{tools}</div> : null}
    </div>
  </Tabs>;
}

/** 汇报's three, under the steps while 汇报 is open; each counts what it holds where that helps. */
export function ReportNav({ view, counts, onView }: { view: ReportView; counts: Partial<Record<ReportView, number>>; onView(view: ReportView): void }) {
  const ids = REPORT_VIEWS.map((item) => item.view);
  return <Tabs value={view} onValueChange={(value) => onView(value as ReportView)} activationMode="manual">
    <TabsList variant="line" className="analysis-report-tabs" aria-label="汇报">
      {REPORT_VIEWS.map(({ view: id, label }) => <TabsTrigger key={id} id={`analysis-tab-${id}`} value={id}
        onClick={() => onView(id)} onKeyDown={roving(ids, view, onView, 'analysis-tab-')}>
        {label}{counts[id] != null ? <span>{counts[id]}</span> : null}
      </TabsTrigger>)}
    </TabsList>
  </Tabs>;
}

/**
 * The top of every step: what it is for in one sentence and where it stands. A step after 范围 can be marked
 * 本期不做 (and taken back); the marked step stays open to read and use. Below, what the step stands on: 勾稽 not
 * done or not done this period (未经月结勾稽), and, for the two analyses, a scope not yet confirmed.
 */
export function StepIntro({ step, states, canSkip, onSkip, onScope }: {
  step: Step; states: Record<Step, StepState>;
  /** The mark can be kept: a build that saves 设置, on a task that is not archived. */
  canSkip: boolean;
  onSkip(skip: boolean): void;
  onScope(): void;
}) {
  const state = states[step];
  const skipped = state === 'skipped';
  return <div className="analysis-step-intro">
    <div className="analysis-step-intro__line">
      <p>{STEP_INTROS[step]}</p>
      <div className="analysis-step-intro__side">
        <span className="analysis-step-intro__state" data-state-step={state}>{STEP_WORDS[state]}</span>
        {canSkip && isSkippable(step) ? <Button variant="ghost" size="sm" type="button" onClick={() => onSkip(!skipped)}>
          {skipped ? '恢复这一步' : '本期不做'}</Button> : null}
      </div>
    </div>
    {unreconciled(step, states) ? <p className="analysis-step-flag"><TriangleAlert size={14} strokeWidth={1.5} aria-hidden />
      <b>未经月结勾稽</b>第 3 步勾稽{states.close === 'skipped' ? '本期不做' : '还没到「可提交经理复核」'}，这里用到的套表数字没有经过勾稽。</p> : null}
    {(step === 'results' || step === 'operations') && states.scope !== 'done' && !skipped
      ? <p className="analysis-note analysis-step-gate">计算按第 2 步的范围算，先确认范围。<Button variant="link" size="sm" type="button" onClick={onScope}>去确认范围</Button></p> : null}
  </div>;
}

/** The bottom of steps 1–5: on to the next step this period does. */
export function StepNext({ next, onStep }: { next: Step | null; onStep(step: Step): void }) {
  if (!next) return null;
  return <div className="analysis-step-next">
    <Button variant="outline" type="button" onClick={() => onStep(next)}>下一步：{numberOf(next)} {labelOf(next)}<ArrowRight size={14} strokeWidth={1.5} aria-hidden /></Button>
  </div>;
}
