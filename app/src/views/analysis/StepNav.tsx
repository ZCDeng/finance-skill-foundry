import { Fragment, type KeyboardEvent, type ReactNode } from 'react';
import { CircleAlert, CircleCheck, CircleDashed, CircleSlash } from 'lucide-react';
import { Tabs, TabsList, TabsTrigger } from '../../components/ui/tabs.js';
import { REPORT_VIEWS, STEPS, STEP_WORDS, type ReportView, type Step, type StepState } from './steps.js';

const ICONS = { done: CircleCheck, todo: CircleSlash, attention: CircleAlert, not_started: CircleDashed } as const;

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
