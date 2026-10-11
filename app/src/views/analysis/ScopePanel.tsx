import { useId, useState } from 'react';
import { Save } from 'lucide-react';
import { AccountingPeriodInput, SearchableSelect, TextField, type SelectOption } from '../../components/FinancialControls.js';
import { Button } from '../../components/ui/button.js';
import { HelpLink } from '../guide/GuideHub.js';
import { CURRENCY_OPTIONS, SCENARIO_OPTIONS, UNIT_OPTIONS, scenarioLabel } from './glossary.js';
import { SCOPE_LABELS, orderCandidates, type AnalysisScope, type CandidateRank, type ScopeCandidateRanks, type ScopeCandidateSources, type ScopeCandidates, type ScopeKey, type ScopeValues } from './scope.js';
import { DisclosureSummary } from '../../components/Disclosure.js';
import { formatPeriods } from '../../lib/period.js';

const validPeriod = (value: string) => /^\d{4}-(0[1-9]|1[0-2])$/.test(value);

/** Fixed choices, plus what the files declare, plus a saved value none of them list. */
function choices(fixed: SelectOption[], inferred: string[] | undefined, saved: string, labelOf: (value: string) => string = (value) => value): SelectOption[] {
  const options = [...fixed];
  for (const value of inferred ?? []) if (!options.some((option) => option.value === value)) options.push({ value, label: labelOf(value), meta: '资料里读到' });
  if (saved && !options.some((option) => option.value === saved)) options.push({ value: saved, label: labelOf(saved), meta: '已保存的值' });
  return options;
}

/** Candidates shown before 其他 N 个: enough to choose between the likely ones without a wall of buttons. */
const SHOWN_CANDIDATES = 3;

/**
 * The values the files declare for one field, strongest first, one row each: the button that adopts it and one
 * line on how the files back it. The full list of places stays in the line's tooltip; past three, the rest open
 * on 其他 N 个.
 */
function Candidates({ field, values, sources, ranks, current, disabled, onPick }: {
  field: ScopeKey; values: string[] | undefined; sources?: Record<string, string>; ranks?: Record<string, CandidateRank>;
  current: string; disabled?: boolean; onPick(value: string): void;
}) {
  const [more, setMore] = useState(false);
  const listId = useId();
  // Recommend from every candidate, the one already chosen included, and only then leave that one out of the list:
  // once the manager has taken the recommendation, the runner-up is not recommended in its place.
  const all = orderCandidates(values ?? [], ranks);
  const { recommended } = all;
  const ordered = all.ordered.filter((value) => value !== current);
  if (!ordered.length) return null;
  const visible = (value: string) => field === 'scenario' ? scenarioLabel(value) : value;
  const shown = more || ordered.length <= SHOWN_CANDIDATES ? ordered : ordered.slice(0, SHOWN_CANDIDATES - 1);
  const hidden = ordered.length - shown.length;
  return <div className="analysis-scope-candidates">
    <span className="analysis-note">资料里读到</span>
    <ul id={listId}>{shown.map((value) => {
      const places = sources?.[value]?.split('；') ?? [];
      const files = ranks?.[value]?.files ?? 0;
      const meta = [value === recommended && all.ordered.length > 1 ? '推荐' : '', files > 1 ? `${files} 份资料` : '',
        places.length ? `来自 ${places[0]}${places.length > 1 ? ` 等 ${places.length} 处` : ''}` : ''].filter(Boolean).join(' · ');
      return <li key={value}>
        <Button variant="outline" type="button" size="chip" disabled={disabled} aria-label={`采用资料里的${SCOPE_LABELS[field]} ${value}`}
          onClick={() => onPick(value)}>{visible(value)}</Button>
        {meta ? <span className="analysis-scope-candidate-source" title={places.length ? `来自 ${places.join('；')}` : undefined}>{meta}</span> : null}
      </li>;
    })}</ul>
    {hidden > 0 || more ? <Button variant="link" size="sm" type="button" className="self-start" aria-expanded={more} aria-controls={listId}
      onClick={() => setMore((value) => !value)}>{more ? '收起' : `其他 ${hidden} 个`}</Button> : null}
  </div>;
}

export function ScopeField({ field, scope, candidates, sources, ranks, disabled, onField, ariaLabel, help }: {
  field: ScopeKey; scope: ScopeValues; candidates: ScopeCandidates; sources?: ScopeCandidateSources; ranks?: ScopeCandidateRanks; disabled?: boolean; ariaLabel?: string; help?: string;
  onField(key: ScopeKey, value: string): void;
}) {
  const label = SCOPE_LABELS[field];
  const value = scope[field];
  const pick = (next: string) => onField(field, next);
  const inferred = candidates[field];
  const suggestions = <Candidates field={field} values={inferred} sources={sources?.[field]} ranks={ranks?.[field]} current={value} disabled={disabled} onPick={pick} />;
  switch (field) {
    case 'period':
      return <div>{value && !validPeriod(value)
        ? <TextField label={label} ariaLabel={ariaLabel} value={value} onChange={pick} disabled={disabled} help={help ?? '已保存的是一段说明，例如累计范围；可改成 YYYY-MM。'} />
        : <AccountingPeriodInput label={label} ariaLabel={ariaLabel} value={value} onChange={pick} disabled={disabled} help={help} />}{suggestions}</div>;
    case 'unit':
      return <div><SearchableSelect label={label} ariaLabel={ariaLabel} value={value} onChange={pick} disabled={disabled} help={help}
        options={choices(UNIT_OPTIONS, inferred, value)} allowEmptyLabel="待确认" clearable placeholder="选择单位" />{suggestions}</div>;
    case 'currency':
      return <div><SearchableSelect label={label} ariaLabel={ariaLabel} value={value} onChange={pick} disabled={disabled} help={help}
        options={choices(CURRENCY_OPTIONS, inferred, value)} allowEmptyLabel="待确认" clearable placeholder="选择币种" />{suggestions}</div>;
    case 'scenario':
      return <div><SearchableSelect label={label} ariaLabel={ariaLabel} value={value} onChange={pick} disabled={disabled} help={help}
        options={choices(SCENARIO_OPTIONS, inferred, value, scenarioLabel)} allowEmptyLabel="待确认" clearable placeholder="选择情景" />{suggestions}</div>;
    default:
      return <div><TextField label={label} ariaLabel={ariaLabel} value={value} onChange={pick} disabled={disabled} help={help}
        placeholder={field === 'organization' ? '例如：华东、集团合并' : field === 'ledger' ? '例如：经营总账' : '例如：月度'} />{suggestions}</div>;
  }
}

/** The scope fields in a grid; the same fields wherever the scope is edited. */
export function ScopeFields({ fields, scope, candidates, sources, ranks, disabled, onField, ariaPrefix }: {
  fields: readonly ScopeKey[]; scope: ScopeValues; candidates: ScopeCandidates; sources?: ScopeCandidateSources; ranks?: ScopeCandidateRanks; disabled?: boolean; ariaPrefix?: string;
  onField(key: ScopeKey, value: string): void;
}) {
  return <div className="analysis-edit-grid">{fields.map((field) =>
    <ScopeField key={field} field={field} scope={scope} candidates={candidates} sources={sources} ranks={ranks} disabled={disabled} onField={onField}
      ariaLabel={ariaPrefix ? `${ariaPrefix}${SCOPE_LABELS[field]}` : undefined} />)}</div>;
}

/** The months the files declare while the task has none: the calculations stay closed until one is chosen. */
export function pendingPeriods(scope: Pick<AnalysisScope, 'scope' | 'candidates'>): string[] {
  return scope.scope.period.trim() ? [] : scope.candidates.period ?? [];
}

/**
 * Says why the period-bound actions are closed. It names the month the files back most strongly (weighed by where
 * each read it, so not always the most files) rather than every month any title mentions; the candidates under
 * 期间 list the rest with where each was read.
 */
export function PeriodPending({ scope, announce = true }: { scope: Pick<AnalysisScope, 'scope' | 'candidates' | 'candidateRanks'>; announce?: boolean }) {
  const periods = pendingPeriods(scope);
  if (!periods.length) return null;
  const { recommended } = orderCandidates(periods, scope.candidateRanks?.period);
  const said = periods.length === 1 ? <>资料写的期间是 <span className="fnd-period">{formatPeriods(periods)[0]}</span></>
    : recommended ? <>资料里依据最充分的期间是 <span className="fnd-period">{formatPeriods([recommended])[0]}</span></>
    : <>资料里读到 {periods.length} 个不同的期间</>;
  // The scope card announces it; a second copy in the settings dialog would read it twice.
  return <p role={announce ? 'status' : undefined} className="analysis-message">{said}，但任务期间还没确认。确认后，计算、背景和文稿才会使用该期间。</p>;
}

const PRIMARY_FIELDS: readonly ScopeKey[] = ['period', 'organization', 'unit', 'currency', 'scenario'];
const MORE_FIELDS: readonly ScopeKey[] = ['ledger', 'granularity'];

/**
 * The task's scope as one card: confirm what the files declare, save once.
 * Every calculation and every draft reads this record.
 */
export function ScopePanel({ scope: state, datasetCount, disabled, onSaved }: {
  scope: AnalysisScope; datasetCount: number; disabled?: boolean; onSaved?(): void;
}) {
  const blocked = disabled || state.loading || state.saving;
  const more = MORE_FIELDS.map((field) => state.scope[field] ? `${SCOPE_LABELS[field]} ${state.scope[field]}` : '').filter(Boolean).join(' · ');
  return <section className="analysis-scope-card" aria-label="分析范围">
    <div><span className="fnd-with-help"><h3>分析范围</h3><HelpLink article="scope" label="分析范围与期间" /></span>
      <p className="analysis-note">资料里读到的值列在字段下方，点一下即可采用；确认后保存，之后的计算和文稿都按这个范围。<span title={state.current?.id}>当前{state.current ? '已保存' : '未保存'} · 资料 {datasetCount} 份。</span></p></div>
    {state.loading ? <p role="status" className="analysis-note">正在读取已保存范围…</p> : null}
    <PeriodPending scope={state} />
    <ScopeFields fields={PRIMARY_FIELDS} scope={state.scope} candidates={state.candidates} sources={state.candidateSources} ranks={state.candidateRanks} disabled={blocked} onField={state.setField} ariaPrefix="分析范围" />
    <details className="analysis-details"><DisclosureSummary>更多范围{more ? ` · ${more}` : ''}</DisclosureSummary>
      <ScopeFields fields={MORE_FIELDS} scope={state.scope} candidates={state.candidates} sources={state.candidateSources} ranks={state.candidateRanks} disabled={blocked} onField={state.setField} ariaPrefix="分析范围" />
    </details>
    {state.conflicts.map(({ field, label }) => <p key={field} role="alert" className="analysis-message analysis-message--error">
      共同{label}与指标里逐项列出的{label}不一致。<Button type="button" variant="outline" disabled={blocked}
        onClick={() => state.setField(field, '')}>清空共同{label}，保留逐项{label}</Button>
    </p>)}
    {state.error ? <p role="alert" className="analysis-message analysis-message--error">{state.error}</p> : null}
    {state.message ? <p role="status" className="analysis-message">{state.message}</p> : null}
    <div className="analysis-actions analysis-actions--end"><Button type="button" disabled={blocked || state.conflicts.length > 0} onClick={() => void state.save().then((record) => { if (record) onSaved?.(); })}>
      <Save size={14} aria-hidden />保存范围</Button></div>
  </section>;
}
