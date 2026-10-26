import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { Play } from 'lucide-react';
import { bridge, timeWait, when, type Answer, type AnalysisRun, type DatasetSnapshot, type FinanceContext, type FinanceContextState, type WaitKind } from '../../bridge.js';
import { textValue } from './presentation.js';
import { WaitLoop } from '../../components/WaitLoop.js';
import { ElasticSlider } from '../../components/ElasticSlider.js';
import { AccountMapEditor } from './AccountMapEditor.js';
import { AccountingPeriodInput, DateInput, DecimalInput, FieldShell, MultiSelect, SearchableSelect, TextField, type SelectOption } from '../../components/FinancialControls.js';
import { Button } from '../../components/ui/button.js';
import { Input } from '../../components/ui/input.js';
import { FinanceAdjustmentPanel } from './FinanceAdjustmentPanel.js';
import { SettingsGroup, SettingsPanel, useSettingsPanel } from './SettingsPanel.js';
import { PeriodPending, pendingPeriods } from './ScopePanel.js';
import { CURRENCY_OPTIONS } from './glossary.js';
import { editableScope, SCOPE_LABELS, type AnalysisScope, type ScopeKey, type ScopeValues } from './scope.js';
import { accountMapOptions, aliasOptions, aliasWords, contextOptions, datasetOptions, scopeFields, scopeParts, scopeSummary, unwrap, errorText } from './shared.js';
import { joinParts } from '../../components/PeriodWords.js';
import { NativeSelect } from '../../components/ui/native-select.js';
import { DisclosureSummary } from '../../components/Disclosure.js';

function bridgeScenarioLabels(context?: FinanceContext): { actual: string; baseline: string } {
  const scopes = context?.scopes ?? {};
  const actualScope = scopes.actual;
  const budgetScope = scopes.budget;
  if (!actualScope || !budgetScope) {
    throw new Error('预算差异分析需要同时选择实际资料和预算资料。请补上预算资料后重新保存范围，再计算。');
  }
  return {
    actual: textValue(actualScope.scenario ?? 'actual'),
    baseline: textValue(budgetScope.scenario ?? 'budget'),
  };
}

const bridgeDimensions = ['organization', 'period'];

const agingStatusOptions: SelectOption[] = [
  { value: 'active', label: '正常应收', meta: '正常、未逾期、open' },
  { value: 'overdue', label: '逾期应收', meta: '逾期、overdue' },
  { value: 'disputed', label: '争议应收', meta: '争议、disputed' },
  { value: 'collection_hold', label: '暂停催收', meta: '暂停催收、hold' },
  { value: 'written_off', label: '已核销', meta: '核销、writeoff' },
];
const agingStatusMapping = {
  active: ['正常', '未逾期', 'open', 'active'],
  overdue: ['逾期', 'overdue'],
  disputed: ['争议', 'disputed'],
  collection_hold: ['暂停催收', 'hold', 'collection_hold'],
  written_off: ['核销', '已核销', 'written_off'],
};

/** What a calculation cannot do without; the rest of the scope narrows it when set. */
const NEEDED_FIELDS: readonly ScopeKey[] = ['period', 'unit', 'currency'];
/** The scope read out in the order 范围 lists it. */
const SCOPE_ORDER = (['period', 'organization', 'unit', 'currency', 'scenario', 'ledger', 'granularity'] as ScopeKey[]).map((key) => SCOPE_LABELS[key]);

export type ScopeRequest = { count: number; contextId?: string };
type Calculation = 'pnl' | 'bridge';
const CALCULATION_NAMES: Record<Calculation, string> = { pnl: '计算损益表', bridge: '计算预算差异' };
const RERUN_NAMES: Record<Calculation, string> = { pnl: '按已保存范围重算损益表', bridge: '按已保存范围计算预算差异' };

/**
 * Which calculation is the main action: the analysis decides, never the form. Choosing
 * a budget file or a saved scope does not swap the buttons under her pointer.
 */
export function leadingCalculation({ comparesBudget }: { comparesBudget: boolean }): Calculation {
  return comparesBudget ? 'bridge' : 'pnl';
}

/**
 * The first reason that keeps a calculation closed, in the words the manager acts on;
 * '' when nothing does. Reading or saving the scope is a pause, not a reason, and is
 * not written here.
 */
export function calculationBlocker(kind: Calculation, state: {
  conflicts: boolean; scopeError: boolean; actual: string; periodPending: boolean; budget: string;
}): string {
  // The conflict and its 清空 button live on the 资料 page; the fields here are locked.
  if (state.conflicts) return '先到第 2 步「范围」处理冲突。';
  if (state.scopeError) return '分析范围没有读出来，见下方提示。';
  if (!state.actual) return '先选实际资料。';
  // PeriodPending above names the months; the line does not repeat them.
  if (state.periodPending) return '先确认任务期间，资料写的期间见上方提示。';
  if (kind === 'bridge' && !state.budget) return '先选预算资料。';
  return '';
}
/** How the last finance operation ended: its name, the sentence shown for it, and when. */
export type FinanceOutcome = { label: string; result: 'ok' | 'error'; message: string; at: string };

export function FinanceWorkbench({ taskId, datasets, runs, busy, scope: analysisScope, comparesBudget = false, openRequest = { count: 0 }, running = '', outcome, onRunning, onOutcome, onRefresh, onScope, children }: {
  taskId: string; datasets: DatasetSnapshot[]; runs: AnalysisRun[]; busy: boolean;
  /** The analysis compares against a budget (a variance, or a budget file bound): 计算预算差异 leads. */
  comparesBudget?: boolean;
  /** The task's one scope, edited on 范围 alone; here it is read, and saved with the calculation. */
  scope: AnalysisScope;
  /** Opens 范围, where the scope is changed. */
  onScope?(): void;
  /** Bumped by 调整范围 on a result; each new count opens the settings on that result's scope. */
  openRequest?: ScopeRequest;
  /** What is running right now, in words; owned by the parent so it outlives this component. */
  running?: string; onRunning(label: string, active: boolean): void;
  /** Owned by the parent for the same reason; null clears it. */
  outcome?: FinanceOutcome; onOutcome(outcome: FinanceOutcome | null): void;
  onRefresh(): Promise<void>; children?: ReactNode | ((close: () => void) => ReactNode);
}) {
  const scope = analysisScope.scope;
  const [finance, setFinance] = useState<FinanceContextState | null>(null);
  const [actual, setActual] = useState(datasets[0]?.id ?? '');
  const [budget, setBudget] = useState('');
  // The budget side's scenario key: 'budget' unless a saved scope named it otherwise.
  const [budgetScenario, setBudgetScenario] = useState('budget');
  const [comparePeriod, setComparePeriod] = useState('');
  const [contextId, setContextId] = useState('');
  const [mapName, setMapName] = useState('管理科目映射');
  const [mapRows, setMapRows] = useState('[{"account_code":"6001","management_account":"revenue"},{"account_code":"6401","management_account":"cost"},{"account_code":"6601","management_account":"expense"}]');
  const [accountMapId, setAccountMapId] = useState('');
  const [scenarioKind, setScenarioKind] = useState<'receivables_aging' | 'cash_13_weeks'>('receivables_aging');
  const [scenarioLabel, setScenarioLabel] = useState('基准情景');
  const [scenarioPrimary, setScenarioPrimary] = useState('actual');
  const [scenarioSecondary, setScenarioSecondary] = useState('');
  const [scenarioAsOf, setScenarioAsOf] = useState('');
  const [scenarioStart, setScenarioStart] = useState('');
  const [scenarioCutoff, setScenarioCutoff] = useState('');
  const [scenarioStatusField, setScenarioStatusField] = useState('invoice_status');
  const [scenarioStatuses, setScenarioStatuses] = useState<string[]>([]);
  const [openingCash, setOpeningCash] = useState('');
  const [delayDays, setDelayDays] = useState('14');
  const [baselineScenarioId, setBaselineScenarioId] = useState('');
  const [boundaryScenarioId, setBoundaryScenarioId] = useState('');
  const [boundaryPreview, setBoundaryPreview] = useState<{ scenario_id: string; period: string; boundaries: Record<string, { value: string; source_rows: unknown[] }> } | null>(null);
  const hasSuccessfulResults = runs.some((row) => row.execution_status === 'succeeded' || row.execution_status === 'success');
  const settings = useSettingsPanel(!hasSuccessfulResults);
  const setSetupOpen = settings.setOpen;
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  // A remount (tab change, new task) must not replay a request it did not see.
  const seenRequest = useRef(openRequest.count);
  useEffect(() => { setActual((value) => value || datasets[0]?.id || ''); }, [datasets]);
  useEffect(() => { if (hasSuccessfulResults) setSetupOpen(false); }, [hasSuccessfulResults]);
  useEffect(() => {
    if (openRequest.count === seenRequest.current) return;
    seenRequest.current = openRequest.count;
    settings.openWithFocus();
    void openScopeOf(openRequest.contextId);
  }, [openRequest.count]);
  /**
   * Loads the scope a result used into the form. The list read at mount may not
   * have it yet (still loading, or saved by the assistant since), so read it
   * again; if it is still not there, say so rather than show another scope as if
   * it were this result's.
   */
  async function openScopeOf(wanted?: string) {
    setError(''); onOutcome(null);
    if (!wanted) { setMessage('这条结果没有记录范围，下面显示的是当前选中的范围。'); return; }
    let context = finance?.contexts.find((item) => item.id === wanted);
    if (!context) {
      try {
        const api = bridge(); if (!api?.financeCall) throw new Error('此版本暂不支持财务计算。');
        const value = unwrap(await api.financeCall(taskId, 'list-finance-context') as Answer<FinanceContextState>);
        setFinance(value);
        context = value.contexts.find((item) => item.id === wanted);
      } catch (failure) {
        setError(errorText(failure));
        return;
      }
    }
    if (context) { loadContext(context); setMessage(''); }
    else setMessage('没有找到这条结果用的范围，下面显示的是当前选中的范围。');
  }
  // The saved scope the form was last refilled from, for what the form cannot show.
  const loaded = useRef<FinanceContext | null>(null);
  /** Puts a saved scope back into the form, so the settings show what that result used. */
  function loadContext(context: FinanceContext) {
    loaded.current = context;
    const text = (value: unknown) => typeof value === 'string' ? value : '';
    const actualScope = (context.scopes?.actual ?? {}) as Record<string, unknown>;
    const budgetScope = context.scopes?.budget as Record<string, unknown> | undefined;
    setContextId(context.id);
    // The account map is part of the scope: dropping it would rerun on another mapping.
    setAccountMapId(context.account_map_id ?? '');
    if (text(context.bindings?.actual)) setActual(text(context.bindings.actual));
    setBudget(text(context.bindings?.budget));
    analysisScope.setFields(Object.fromEntries(scopeFields.map(([key]) => [key, text(actualScope[key])])));
    if (budgetScope) {
      setBudgetScenario(text(budgetScope.scenario) || 'budget');
      setComparePeriod(text(budgetScope.period) !== text(actualScope.period) ? text(budgetScope.period) : '');
    }
  }
  /** One operation as the manager waits on it: both calls of 保存并计算 and the read-back after are one timed wait. */
  function track(kind: WaitKind, label: string, work: (done: (message: string, run?: unknown) => void) => Promise<void>) {
    if (running) return Promise.resolve();
    return timeWait(kind, async (note) => {
      onOutcome(null); setMessage(''); setError('');
      onRunning(label, true);
      let succeeded = false;
      try {
        await work((message, run) => { succeeded = true; note('ok', run); onOutcome({ label, result: 'ok', message, at: new Date().toISOString() }); });
        if (!succeeded) note('cancelled');
      } catch (failure) {
        const message = errorText(failure);
        // After done only reading the page back can fail; the operation itself went through.
        if (succeeded) setError(message);
        else { note('error'); onOutcome({ label, result: 'error', message, at: new Date().toISOString() }); }
      } finally { onRunning(label, false); }
    });
  }
  useEffect(() => {
    let cancelled = false;
    const api = bridge();
    if (!api?.financeCall) return;
    void api.financeCall(taskId, 'list-finance-context').then((answer) => {
      if (!cancelled) {
        const value = unwrap(answer as Answer<FinanceContextState>);
        setFinance(value);
        setContextId((current) => current || value.contexts.at(-1)?.id || '');
      }
    }).catch((failure) => { if (!cancelled) setError(errorText(failure)); });
    return () => { cancelled = true; };
  }, [taskId]);
  /**
   * The scope as the engine stores it: what she confirmed, else the one value
   * the files declare, else the engine's plain default. A blank field never
   * reaches the engine as a blank.
   */
  function engineScope(sourceScope: ScopeValues = scope): Record<string, string> {
    const inferred = (key: ScopeKey) => (analysisScope.candidates[key]?.length === 1 ? analysisScope.candidates[key]![0] : '');
    const fallback: Partial<Record<ScopeKey, string>> = { currency: 'CNY', unit: '元', scenario: 'actual' };
    const next: Record<string, string> = {};
    for (const [key] of scopeFields) {
      const value = sourceScope[key] || inferred(key) || fallback[key] || '';
      if (value) next[key] = value;
    }
    return next;
  }
  function saveContext(runAfter?: 'pnl' | 'bridge') {
    return track(runAfter === 'pnl' ? 'finance.pnl' : runAfter === 'bridge' ? 'finance.bridge' : 'finance.save',
      runAfter === 'pnl' ? '正在保存范围并计算损益表…' : runAfter === 'bridge' ? '正在保存范围并计算预算差异…' : '正在保存范围…', async (done) => {
      const api = bridge(); if (!api?.financeCall) throw new Error('此版本暂不支持财务计算。');
      if (analysisScope.loading || analysisScope.saving) throw new Error('分析范围正在读取或保存，请稍后再试。');
      if (analysisScope.error) throw new Error(analysisScope.error);
      if (analysisScope.conflicts.length) throw new Error(`共同${analysisScope.conflicts.map((item) => item.label).join('、')}与指标逐项范围冲突，请先清空共同范围或调整指标。`);
      const savedRequirements = await analysisScope.save();
      if (!savedRequirements) throw new Error('分析范围尚未保存，不能开始计算。');
      const actualScope = engineScope(editableScope(savedRequirements.scope));
      const bindings = { actual, ...(budget ? { budget } : {}) };
      const scopes = { actual: actualScope, ...(budget ? { budget: { ...actualScope, scenario: budgetScenario, ...(comparePeriod ? { period: comparePeriod } : {}) } } : {}) };
      // A form refilled from a saved scope keeps what it does not show: each alias's
      // policies (field map, target unit) while that alias still binds the same dataset.
      const base = loaded.current?.id === contextId ? loaded.current : null;
      const policies = Object.fromEntries(Object.entries(base?.policies ?? {})
        .filter(([alias]) => (bindings as Record<string, string>)[alias] === base?.bindings?.[alias]));
      const context = unwrap(await api.financeCall(taskId, 'finance-context-save', {
        name: `${actualScope.period || '本期'}${actualScope.organization ? ` ${actualScope.organization}` : ''} 经营范围`,
        bindings, scopes, ...(accountMapId ? { account_map_id: accountMapId } : {}),
        ...(Object.keys(policies).length ? { policies } : {}),
        ...(base ? { parent_id: base.id } : {}),
        ...(base?.reporting_profile ? { reporting_profile: base.reporting_profile } : {}),
      }) as Answer<FinanceContext>);
      setContextId(context.id);
      setFinance((value) => value ? {
        ...value,
        contexts: value.contexts.some((item) => item.id === context.id) ? value.contexts : [...value.contexts, context],
      } : value);
      if (runAfter === 'pnl') {
        const run = unwrap(await api.financeCall(taskId, 'run-metric', { context_id: context.id, metric: { kind: 'management_pnl' } }));
        done('已保存范围并计算损益表。', run);
        setSetupOpen(false);
      } else if (runAfter === 'bridge') {
        const labels = bridgeScenarioLabels(context);
        const run = unwrap(await api.financeCall(taskId, 'explain-variance', {
          context_id: context.id, actual_scenario: labels.actual, baseline_scenario: labels.baseline,
          dimensions: bridgeDimensions,
        }));
        done('已保存范围并计算预算差异。', run);
        setSetupOpen(false);
      } else {
        done('已保存范围。');
      }
      await onRefresh();
    });
  }
  function saveMap() {
    return track('finance.save', '正在保存映射…', async (done) => {
      const api = bridge(); if (!api?.financeCall) throw new Error('此版本暂不支持管理科目映射。');
      const parsed = JSON.parse(mapRows);
      if (!Array.isArray(parsed)) throw new Error('映射需要是一行一个科目的列表。');
      const record = unwrap(await api.financeCall(taskId, 'finance-map-save', { name: mapName, rows: parsed }) as Answer<Record<string, unknown>>);
      setAccountMapId(String(record.id ?? ''));
      setFinance((value) => value ? { ...value, account_maps: [...value.account_maps, record] } : value);
      done('已保存管理科目映射，下一次计算会使用它。');
    });
  }
  const runExisting = (kind: 'pnl' | 'bridge') => track(kind === 'pnl' ? 'finance.pnl' : 'finance.bridge', kind === 'pnl' ? '正在计算损益表…' : '正在计算预算差异…', async (done) => {
    const api = bridge(); if (!api?.financeCall || !contextId) return;
    let run: unknown;
    if (kind === 'pnl') run = unwrap(await api.financeCall(taskId, 'run-metric', { context_id: contextId, metric: { kind: 'management_pnl' } }));
    else {
      const labels = bridgeScenarioLabels(selectedContext);
      run = unwrap(await api.financeCall(taskId, 'explain-variance', {
        context_id: contextId, actual_scenario: labels.actual, baseline_scenario: labels.baseline,
        dimensions: bridgeDimensions,
      }));
    }
    done(kind === 'pnl' ? '已计算损益表。' : '已计算预算差异。', run);
    setSetupOpen(false);
    await onRefresh();
  });
  const selectedContext = finance?.contexts.find((context) => context.id === contextId);
  const aliases = Object.keys(selectedContext?.bindings ?? {});
  useEffect(() => {
    setScenarioPrimary((value) => value || aliases[0] || 'actual');
  }, [aliases.join('|')]);
  useEffect(() => { setBaselineScenarioId(''); }, [contextId, scenarioKind]);
  function runScenario(child = false) {
    return track('finance.scenario', child ? '正在计算延迟回款情景…' : '正在计算基准情景…', async (done) => {
      const api = bridge(); if (!api?.financeCall || !contextId) throw new Error('请先保存或选择范围。');
      const scenarioScope = selectedContext?.scopes?.[scenarioPrimary] ?? engineScope();
      let scenario: Record<string, unknown>;
      if (child) {
        if (scenarioKind !== 'cash_13_weeks') throw new Error('延迟回款情景只适用于 13 周现金测算。');
        if (!baselineScenarioId) throw new Error('请先计算一个 13 周现金基准情景。');
        const parent = finance?.scenarios.find((item) => item.id === baselineScenarioId);
        if (parent && (parent.kind !== 'cash_13_weeks' || parent.context_id !== contextId)) throw new Error('请选择同一范围下的 13 周现金基准情景。');
        scenario = unwrap(await api.financeCall(taskId, 'finance-scenario-save', {
          parent_id: baselineScenarioId,
          label: `${scenarioLabel || '情景'} · 延迟 ${delayDays || '0'} 天`,
          changes: { scenario: { delay_receipts_days: Number(delayDays || 0), label: `回款延迟 ${delayDays || 0} 天` } },
        }));
      } else {
        const inputs = scenarioKind === 'receivables_aging'
          ? { as_of: scenarioAsOf || scope.period, scope: scenarioScope, invoices_alias: scenarioPrimary,
              ...(scenarioSecondary ? { activity_alias: scenarioSecondary } : {}),
              ...(scenarioStatuses.length ? { status_filter: { field: scenarioStatusField || 'status', include: scenarioStatuses, mapping: agingStatusMapping } } : {}) }
          : { opening_cash: openingCash, start_date: scenarioStart, actual_cutoff: scenarioCutoff, scope: scenarioScope,
              receipts_alias: scenarioPrimary, ...(scenarioSecondary ? { payments_alias: scenarioSecondary } : {}), scenario: { delay_receipts_days: 0 } };
        scenario = unwrap(await api.financeCall(taskId, 'finance-scenario-save', {
          context_id: contextId, kind: scenarioKind, label: scenarioLabel || '基准情景', inputs,
        }));
        setBaselineScenarioId(String(scenario.id ?? ''));
      }
      const run = unwrap(await api.financeCall(taskId, 'finance-scenario-run', { scenario_id: String(scenario.id) }));
      setFinance((value) => value && !value.scenarios.some((item) => item.id === scenario.id)
        ? { ...value, scenarios: [...value.scenarios, scenario] } : value);
      done(child ? '已计算延迟回款情景。' : '已计算基准情景。', run);
      setSetupOpen(false);
      await onRefresh();
    });
  }

  const closeSetup = settings.close;
  const locked = busy || Boolean(running) || analysisScope.loading || analysisScope.saving || analysisScope.conflicts.length > 0 || Boolean(analysisScope.error);
  const disabled = locked || !actual;
  const transient = busy || Boolean(running) || analysisScope.loading || analysisScope.saving;
  const lead = leadingCalculation({ comparesBudget });
  const second: Calculation = lead === 'bridge' ? 'pnl' : 'bridge';
  // A file that names its month must not be calculated across every month it holds.
  const blockers: Record<Calculation, string> = Object.fromEntries((['pnl', 'bridge'] as const).map((kind) => [kind, calculationBlocker(kind, {
    conflicts: analysisScope.conflicts.length > 0, scopeError: Boolean(analysisScope.error), actual,
    periodPending: pendingPeriods(analysisScope).length > 0, budget,
  })])) as Record<Calculation, string>;
  // The saved-scope reruns need no form, only a readable scope without conflicts.
  const rerunBlocker = analysisScope.conflicts.length > 0 ? '先到第 2 步「范围」处理冲突。'
    : analysisScope.error ? '分析范围没有读出来，见下方提示。' : '';
  const reasonId = useId();
  // Every closed button says why. A reason several buttons share is one line; a profit task that only lacks a
  // budget file keeps that to screen readers rather than a standing line under the main action.
  const gates: { key: string; name: string; reason: string; quiet?: boolean }[] = [
    ...([lead, second] as const).map((kind) => ({ key: kind, name: CALCULATION_NAMES[kind], reason: blockers[kind],
      quiet: kind === 'bridge' && lead === 'pnl' && !blockers.pnl })),
    ...(contextId ? (['pnl', 'bridge'] as const).map((kind) => ({ key: `rerun-${kind}`, name: RERUN_NAMES[kind], reason: rerunBlocker })) : []),
  ].filter((gate) => gate.reason);
  const reasonLines: { id: string; text: string; keys: string[]; quiet?: boolean }[] = [];
  for (const gate of gates) {
    if (gate.quiet) { reasonLines.push({ id: `${reasonId}-${gate.key}`, text: `${gate.name}：${gate.reason}`, keys: [gate.key], quiet: true }); continue; }
    const line = reasonLines.find((item) => !item.quiet && item.text === gate.reason);
    if (line) line.keys.push(gate.key);
    else reasonLines.push({ id: `${reasonId}-${gate.key}`, text: gate.reason, keys: [gate.key] });
  }
  // A line one button owns names it.
  for (const line of reasonLines) if (!line.quiet && line.keys.length === 1) line.text = `${gates.find((gate) => gate.key === line.keys[0])!.name}：${line.text}`;
  const describedBy = (key: string) => reasonLines.find((line) => line.keys.includes(key))?.id;
  const calculate = (kind: Calculation, variant: 'default' | 'outline') => <Button key={kind} variant={variant} type="button"
    disabled={transient || Boolean(blockers[kind])} aria-describedby={describedBy(kind)} onClick={() => void saveContext(kind)}>{CALCULATION_NAMES[kind]}</Button>;
  const rerun = (kind: Calculation) => <Button key={kind} variant="outline" type="button" disabled={locked} aria-describedby={describedBy(`rerun-${kind}`)}
    onClick={() => void runExisting(kind)}>{RERUN_NAMES[kind]}</Button>;
  // Read as 范围 shows it: the period in words, the currency by name (人民币, not CNY).
  const scopeWords = scopeParts(scope).sort((left, right) => SCOPE_ORDER.indexOf(left.label) - SCOPE_ORDER.indexOf(right.label))
    .map(({ label, text, period }) => period ? <>{label} <span className="fnd-period">{text}</span></>
      : `${label} ${label === SCOPE_LABELS.currency ? CURRENCY_OPTIONS.find((option) => option.value === text)?.label ?? text : text}`);
  const unconfirmed = NEEDED_FIELDS.filter((key) => !scope[key]).map((key) => SCOPE_LABELS[key]);
  const advancedChildren = typeof children === 'function' ? children(closeSetup) : children;
  const accountMapName = finance?.account_maps.find((item) => String(item.id ?? '') === accountMapId)?.name;
  const status = <>
    {/* Between the heading and the folds: a run closes 范围与计算 on success, and the outcome must stay in view. */}
    {running ? <p role="status" className="analysis-message"><WaitLoop />{running}</p>
      : outcome?.result === 'ok' ? <p role="status" className="analysis-message">{outcome.message}</p>
      : message ? <p role="status" className="analysis-message">{message}</p> : null}
    {outcome?.result === 'error' && <p role="alert" className="analysis-message analysis-message--error">{outcome.message}</p>}
    {error && <p role="alert" className="analysis-message analysis-message--error">{error}</p>}
  </>;
  // 考核调整 changes the next management P&L, so it sits with the result, before the group; 归档图 is 汇报's.
  return <>{contextId ? <FinanceAdjustmentPanel taskId={taskId} contextId={contextId} busy={locked} onRefresh={onRefresh} /> : null}
  <SettingsGroup note="选实际资料（和预算资料），按第 2 步的范围算损益表或预算差异；也能看和改计算定义。">{status}<SettingsPanel state={settings} scrollIntoView label="范围与计算" summary="选好实际资料（和预算资料），确认范围后计算">
    <fieldset className="analysis-fieldset" disabled={locked}><div className="analysis-edit-grid">
      <SearchableSelect label="实际资料" value={actual} options={datasetOptions(datasets)} onChange={(value) => {
        setActual(value);
        if (budget === value) setBudget('');
      }} placeholder="搜索资料名称或来源" />
      <SearchableSelect label="预算资料（可选）" value={budget} options={datasetOptions(datasets.filter((source) => source.id !== actual))}
        onChange={setBudget} placeholder="搜索预算资料" allowEmptyLabel="暂不选择" />
      {finance?.contexts.length ? <SearchableSelect label="已保存的范围" value={contextId} options={contextOptions(finance)}
        onChange={setContextId} placeholder="搜索范围名称或期间" /> : null}
    </div>
    <PeriodPending scope={analysisScope} announce={false} />
    {/* The scope is set on 范围 alone; here it is only read, so there is one place to change it. */}
    <div className="analysis-scope-line" role="group" aria-label="计算用的范围">
      <p><span className="analysis-scope-line__label">范围</span>{scopeWords.length ? joinParts(scopeWords) : '还没确认'}
        {scopeWords.length && unconfirmed.length ? <span className="analysis-note">（{unconfirmed.join('、')}还没确认）</span> : null}</p>
      {onScope ? <Button variant="link" size="sm" type="button" onClick={onScope}>到「范围」修改</Button> : null}
    </div>
    {budget && <div className="analysis-edit-grid"><AccountingPeriodInput label="对比期间" value={comparePeriod} onChange={setComparePeriod}
      shortcutBaseValue={scope.period} shortcutBaseLabel="实际期间"
      help="留空时预算与实际取同一期间；填写后预算按这个期间取数。" /></div>}
    </fieldset>
    {/* One main action, at the right; which one is the analysis's choice, so nothing moves while she fills the form in. */}
    <div className="analysis-actions analysis-actions--end">
      <Button variant="outline" type="button" disabled={disabled} onClick={() => void saveContext()}>保存范围</Button>
      {calculate(second, 'outline')}
      {calculate(lead, 'default')}
    </div>
    {contextId && <div className="analysis-actions analysis-actions--end">{rerun(lead)}{rerun(second)}</div>}
    {selectedContext?.reporting_profile && <details className="analysis-details"><DisclosureSummary>专业口径确认</DisclosureSummary>
      <p>{selectedContext.reporting_profile.basis} · {selectedContext.reporting_profile.basis_version} · {selectedContext.reporting_profile.purpose === 'forecast' ? '管理预测' : selectedContext.reporting_profile.purpose === 'statutory' ? '法定列报（仅已支持方法可用）' : '管理分析'}</p>
      <p>年度起始 {selectedContext.reporting_profile.fiscal_year_start}；有效期间 {selectedContext.reporting_profile.effective_period.start} 至 {selectedContext.reporting_profile.effective_period.end}；提前采用 {selectedContext.reporting_profile.early_adoption === 'unknown' ? '待核实' : selectedContext.reporting_profile.early_adoption ? '是' : '否'}。</p>
      <p>主体 {selectedContext.reporting_profile.entity_scope}；本位币 {selectedContext.reporting_profile.functional_currency}；列报 {selectedContext.reporting_profile.presentation_currency} / {selectedContext.reporting_profile.presentation_unit}。</p>
      {Object.entries(selectedContext.reporting_profile.policies ?? {}).map(([key, value]) => <p key={key}>{key === 'depreciation_start' ? '折旧起算' : '现金流量表方法'}：{({ in_service_month: '达到可使用状态当月', following_month: '达到可使用状态次月', direct: '直接法', indirect: '间接法' } as Record<string, string>)[String(value)] ?? String(value)}。</p>)}
      <p>确认只适用于当前来源、期间和所列字段。换月或换资料需要重新确认。</p>
      <Button variant="outline" type="button" disabled={locked} onClick={() => void track('finance.save', '正在确认专业口径…', async (done) => {
        const api = bridge(); if (!api?.financeCall) throw new Error('此版本不支持专业口径确认。');
        const profile = selectedContext.reporting_profile!;
        const fields = Object.entries(profile).flatMap(([key, value]) => typeof value === 'object' && value !== null ? Object.keys(value).map((child) => `${key}.${child}`) : [key]);
        unwrap(await api.financeCall(taskId, 'finance-profile-confirm', { context_id: selectedContext.id, confirmed_fields: fields }) as Answer<unknown>);
        done('已确认当前专业口径。新增分析将按该口径校验；旧运行保留历史身份。');
        await onRefresh();
      })}>确认所列专业口径</Button>
      <FieldShell label="管理预测模型"><NativeSelect aria-label="管理预测模型" value={boundaryScenarioId} onChange={(event) => { setBoundaryScenarioId(event.target.value); setBoundaryPreview(null); }}>
        <option value="">选择需要确认边界的模型</option>
        {(finance?.scenarios ?? []).filter((item) => item.context_id === selectedContext.id && (item.inputs as Record<string, unknown> | undefined)?.template_id === 'linked_three_statement_management_v1').map((item) => <option key={String(item.id)} value={String(item.id)}>{String(item.label ?? item.id)}</option>)}
      </NativeSelect></FieldShell>
      <Button variant="outline" type="button" disabled={locked || !boundaryScenarioId} onClick={() => void track('finance.save', '正在核验模型边界来源…', async (done) => {
        const api = bridge(); if (!api?.financeCall) throw new Error('此版本不支持模型边界预览。');
        const result = unwrap(await api.financeCall(taskId, 'finance-profile-status', { context_id: selectedContext.id, scenario_id: boundaryScenarioId }) as Answer<Record<string, unknown>>);
        setBoundaryPreview(result.model_boundary_preview as typeof boundaryPreview);
        done('已按归档来源核验模型边界，请复核下列假设。');
      })}>预览八项模型边界</Button>
      {boundaryPreview?.scenario_id === boundaryScenarioId && <div>
        <p>本预测模型在 {boundaryPreview.period} 明确假设下列八项影响为零；这项批准仅适用于当前模型及来源，不代表历史交易不存在。</p>
        <ul>{Object.entries(boundaryPreview.boundaries).map(([key, value]) => <li key={key}>{({ 'boundary.inventory_movement': '存货变动', 'boundary.tax_effect': '税项影响', 'boundary.interest_effect': '利息影响', 'boundary.vat_effect': '增值税影响', 'boundary.fx_effect': '汇率影响', 'boundary.oci_effect': '其他综合收益', 'boundary.noncash_investing_financing': '非现金投资筹资', 'boundary.other_balance_sheet_movements': '其他资产负债表变动' } as Record<string, string>)[key] ?? key}：{value.value}（{value.source_rows.length} 条来源）</li>)}</ul>
        <Button variant="outline" type="button" disabled={locked} onClick={() => void track('finance.save', '正在确认模型边界…', async (done) => {
          const api = bridge(); if (!api?.financeCall) throw new Error('此版本不支持模型边界确认。');
          unwrap(await api.financeCall(taskId, 'finance-profile-confirm', { context_id: selectedContext.id, scenario_id: boundaryScenarioId, confirmed_model_boundaries: Object.keys(boundaryPreview.boundaries) }) as Answer<unknown>);
          done('已确认当前预测模型的八项零值边界。'); await onRefresh();
        })}>确认本模型八项边界均为零</Button>
      </div>}
    </details>}
    {reasonLines.some((line) => !line.quiet) ? <div className="analysis-actions-reasons">
      {reasonLines.filter((line) => !line.quiet).map((line) => <p key={line.id} id={line.id}>{line.text}</p>)}</div> : null}
    {reasonLines.filter((line) => line.quiet).map((line) => <span key={line.id} id={line.id} className="sr-only">{line.text}</span>)}
    {analysisScope.error ? <p className="analysis-message analysis-message--error">{analysisScope.error}</p> : null}
    {advancedChildren ? <section className="analysis-finance-definition" aria-label="计算定义">{advancedChildren}</section> : null}
    {contextId && <details className="analysis-details analysis-scenario-panel"><DisclosureSummary>情景测算</DisclosureSummary>
      <fieldset className="analysis-fieldset" disabled={locked}><div className="analysis-edit-grid">
        <FieldShell label="情景类型"><NativeSelect aria-label="情景类型" value={scenarioKind} onChange={(event) => setScenarioKind(event.target.value as typeof scenarioKind)}>
          <option value="receivables_aging">应收账龄</option><option value="cash_13_weeks">13 周现金</option></NativeSelect></FieldShell>
        <TextField label="情景名称" value={scenarioLabel} onChange={setScenarioLabel} />
        <SearchableSelect label={scenarioKind === 'receivables_aging' ? '应收/发票资料' : '回款资料'} value={scenarioPrimary}
          options={aliasOptions(aliases, selectedContext, datasets)} onChange={setScenarioPrimary} placeholder="选择资料" />
        <SearchableSelect label={scenarioKind === 'receivables_aging' ? '核销记录（可选）' : '付款资料（可选）'} value={scenarioSecondary}
          options={aliasOptions(aliases.filter((alias) => alias !== scenarioPrimary), selectedContext, datasets)}
          onChange={setScenarioSecondary} placeholder="选择资料" allowEmptyLabel="暂不选择" />
        {scenarioKind === 'receivables_aging' ? <>
          <DateInput label="账龄日期" value={scenarioAsOf} onChange={setScenarioAsOf} />
          <MultiSelect label="应收状态筛选" values={scenarioStatuses} options={agingStatusOptions} onChange={setScenarioStatuses}
            placeholder="默认纳入全部状态" help="选择后只纳入这些状态；不选则纳入全部应收记录。" />
          {scenarioStatuses.length > 0 && <TextField label="发票状态列名" value={scenarioStatusField} onChange={setScenarioStatusField} help="账龄按原表的这一列识别发票状态。" />}
        </> : <>
          <DecimalInput label="期初现金" value={openingCash} onChange={setOpeningCash} placeholder="5000000.00" unit={scope.unit || '元'} />
          <DateInput label="预测开始日" value={scenarioStart} onChange={setScenarioStart}
            help="从这一天起按预测取数；通常是实际收支截止日的下一天。" />
          <DateInput label="实际收支截止日" value={scenarioCutoff} onChange={setScenarioCutoff}
            help="到这一天为止用实际收支；这不是预测的结束日。" />
        </>}
        {scenarioKind === 'cash_13_weeks' && <div className="fnd-slider-pair">
          <DecimalInput label="回款延迟天数" value={delayDays} onChange={setDelayDays} unit="天" help="滑块覆盖 0–90 天，更长的延迟直接填写。" />
          <ElasticSlider label="回款延迟" ariaLabel="回款延迟天数，拖动选择" value={delayDays.trim() ? Number(delayDays) : null}
            min={0} max={90} step={1} format={(days) => `${days} 天`} onChange={(days) => setDelayDays(String(days))} />
        </div>}
      </div></fieldset>
      <div className="analysis-actions">
        <Button variant="outline" type="button" disabled={locked || !contextId || !scenarioPrimary || (scenarioKind === 'cash_13_weeks' && (!openingCash || !scenarioStart || !scenarioCutoff))} onClick={() => void runScenario(false)}><Play size={14} aria-hidden />计算基准情景</Button>
        <Button variant="outline" type="button" disabled={locked || scenarioKind !== 'cash_13_weeks' || !baselineScenarioId} onClick={() => void runScenario(true)}>计算延迟回款情景</Button>
      </div>
      {finance?.scenarios.filter((scenario) => scenario.context_id === contextId && scenario.kind === scenarioKind).length ? <div className="analysis-history-list">{[...finance.scenarios].filter((scenario) => scenario.context_id === contextId && scenario.kind === scenarioKind).reverse().slice(0, 6).map((scenario) => <button type="button" className="analysis-history-row" key={String(scenario.id)} disabled={locked}
        aria-current={scenario.id === baselineScenarioId ? 'true' : undefined} onClick={() => setBaselineScenarioId(String(scenario.id ?? ''))}>
        <span>{textValue(scenario.label ?? scenario.kind)}</span><span>{scenario.kind === 'cash_13_weeks' ? '13 周现金' : scenario.kind === 'receivables_aging' ? '应收账龄' : scenario.kind === 'collection_health' ? '回款健康' : textValue(scenario.kind)}</span><time>{when(String(scenario.created_at ?? ''))}</time></button>)}</div> : null}
    </details>}
    {finance?.contexts.length ? <details className="analysis-details"><DisclosureSummary>已保存的范围 · {finance.contexts.length} 个</DisclosureSummary>
      <div className="analysis-history-list">{[...finance.contexts].reverse().map((context) => <button key={context.id} type="button" className="analysis-history-row" disabled={locked}
        aria-current={context.id === contextId ? 'true' : undefined} onClick={() => setContextId(context.id)}>
        <span>{context.name}</span><span>{Object.entries(context.scopes ?? {}).map(([alias, item]) => `${aliasWords(alias, context, datasets)} ${scopeSummary(item)}`).join('；')}</span></button>)}</div></details> : null}
    <details className="analysis-details"><DisclosureSummary>管理科目映射</DisclosureSummary>
      <p className="analysis-note">损益表算不出来，多半是这里没配齐。系统只认收入、成本、费用三类管理科目，把原表的科目代码归到这三类。</p>
      <div className="analysis-edit-grid"><label>映射名称<Input className="min-w-0 flex-1" value={mapName} disabled={locked} onChange={(event) => setMapName(event.target.value)}  /></label>
        <SearchableSelect label="已保存映射" value={accountMapId} disabled={locked} options={accountMapOptions(finance)} onChange={setAccountMapId}
          placeholder="搜索映射名称" allowEmptyLabel="暂不使用" /></div>
      <AccountMapEditor value={mapRows} disabled={locked} onChange={setMapRows} />
      {accountMapId && <p className="analysis-note">计算损益表时使用管理科目映射：{textValue(accountMapName ?? '已保存的映射')}。</p>}
      <Button variant="outline" type="button" disabled={locked || !mapRows.trim()} onClick={() => void saveMap()}>保存映射</Button>
    </details>
  </SettingsPanel>
  </SettingsGroup></>;
}
