import { Save } from 'lucide-react';
import { AccountingPeriodInput, SearchableSelect, TextField, type SelectOption } from '../../components/FinancialControls.js';
import { Button } from '../../components/ui/button.js';
import { HelpLink } from '../guide/GuideHub.js';
import { CURRENCY_OPTIONS, SCENARIO_OPTIONS, UNIT_OPTIONS, scenarioLabel } from './glossary.js';
import { SCOPE_LABELS, type AnalysisScope, type ScopeCandidateSources, type ScopeCandidates, type ScopeKey, type ScopeValues } from './scope.js';
import { DisclosureSummary } from '../../components/Disclosure.js';

const validPeriod = (value: string) => /^\d{4}-(0[1-9]|1[0-2])$/.test(value);

/** Fixed choices, plus what the files declare, plus a saved value none of them list. */
function choices(fixed: SelectOption[], inferred: string[] | undefined, saved: string, labelOf: (value: string) => string = (value) => value): SelectOption[] {
  const options = [...fixed];
  for (const value of inferred ?? []) if (!options.some((option) => option.value === value)) options.push({ value, label: labelOf(value), meta: '资料里读到' });
  if (saved && !options.some((option) => option.value === saved)) options.push({ value: saved, label: labelOf(saved), meta: '已保存的值' });
  return options;
}

/** The values the files declare for one field, offered as one click each. */
function Candidates({ field, values, sources, current, disabled, onPick }: {
  field: ScopeKey; values: string[] | undefined; sources?: Record<string, string>; current: string; disabled?: boolean; onPick(value: string): void;
}) {
  const offered = (values ?? []).filter((value) => value !== current);
  if (!offered.length) return null;
  const visible = (value: string) => field === 'scenario' ? scenarioLabel(value) : value;
  return <p className="analysis-note analysis-scope-candidates">资料里读到：{offered.map((value) => <span key={value}>
    <Button variant="outline" type="button" size="chip" disabled={disabled} aria-label={`采用资料里的${SCOPE_LABELS[field]} ${value}`}
      onClick={() => onPick(value)}>{visible(value)}</Button>
    {sources?.[value] ? <span className="analysis-scope-candidate-source">来自 {sources[value]}</span> : null}</span>)}</p>;
}

export function ScopeField({ field, scope, candidates, sources, disabled, onField, ariaLabel, help }: {
  field: ScopeKey; scope: ScopeValues; candidates: ScopeCandidates; sources?: ScopeCandidateSources; disabled?: boolean; ariaLabel?: string; help?: string;
  onField(key: ScopeKey, value: string): void;
}) {
  const label = SCOPE_LABELS[field];
  const value = scope[field];
  const pick = (next: string) => onField(field, next);
  const inferred = candidates[field];
  const suggestions = <Candidates field={field} values={inferred} sources={sources?.[field]} current={value} disabled={disabled} onPick={pick} />;
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
export function ScopeFields({ fields, scope, candidates, sources, disabled, onField, ariaPrefix }: {
  fields: readonly ScopeKey[]; scope: ScopeValues; candidates: ScopeCandidates; sources?: ScopeCandidateSources; disabled?: boolean; ariaPrefix?: string;
  onField(key: ScopeKey, value: string): void;
}) {
  return <div className="analysis-edit-grid">{fields.map((field) =>
    <ScopeField key={field} field={field} scope={scope} candidates={candidates} sources={sources} disabled={disabled} onField={onField}
      ariaLabel={ariaPrefix ? `${ariaPrefix}${SCOPE_LABELS[field]}` : undefined} />)}</div>;
}

/** The months the files declare while the task has none: the calculations stay closed until one is chosen. */
export function pendingPeriods(scope: Pick<AnalysisScope, 'scope' | 'candidates'>): string[] {
  return scope.scope.period.trim() ? [] : scope.candidates.period ?? [];
}

/** Says why the period-bound actions are closed, in the words of the files themselves. */
export function PeriodPending({ scope, announce = true }: { scope: Pick<AnalysisScope, 'scope' | 'candidates'>; announce?: boolean }) {
  const periods = pendingPeriods(scope);
  if (!periods.length) return null;
  // The scope card announces it; a second copy in the settings dialog would read it twice.
  return <p role={announce ? 'status' : undefined} className="analysis-message">资料写的期间是 {periods.join('、')}，但任务期间还没确认。确认后，计算、背景和文稿才会使用该期间。</p>;
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
    <div className="analysis-section-heading"><div><span className="fnd-with-help"><h3>分析范围</h3><HelpLink article="scope" label="分析范围与期间" /></span>
      <p className="analysis-note">资料里读到的值列在字段下方，点一下即可采用；确认后保存，之后的计算和文稿都按这个范围。</p></div>
      <span className="analysis-note" title={state.current?.id}>{state.current ? '已保存' : '未保存'} · 资料 {datasetCount} 份</span></div>
    {state.loading ? <p role="status" className="analysis-note">正在读取已保存范围…</p> : null}
    <PeriodPending scope={state} />
    <ScopeFields fields={PRIMARY_FIELDS} scope={state.scope} candidates={state.candidates} sources={state.candidateSources} disabled={blocked} onField={state.setField} ariaPrefix="分析范围" />
    <details className="analysis-details"><DisclosureSummary>更多范围{more ? ` · ${more}` : ''}</DisclosureSummary>
      <ScopeFields fields={MORE_FIELDS} scope={state.scope} candidates={state.candidates} sources={state.candidateSources} disabled={blocked} onField={state.setField} ariaPrefix="分析范围" />
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
