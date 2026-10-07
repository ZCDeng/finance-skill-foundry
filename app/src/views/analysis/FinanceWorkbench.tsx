import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { Play } from 'lucide-react';
import { bridge, timeWait, when, type Answer, type AnalysisRun, type DatasetSnapshot, type FinanceContext, type FinanceContextState, type WaitKind } from '../../bridge.js';
import { textValue } from './presentation.js';
import { WaitOrb } from '../../components/WaitOrb.js';
import { AccountMapEditor } from './AccountMapEditor.js';
import { AccountingPeriodInput, DateInput, DecimalInput, FieldShell, MultiSelect, SearchableSelect, TextField, type SelectOption } from '../../components/FinancialControls.js';
import { Button } from '../../components/ui/button.js';
import { Input } from '../../components/ui/input.js';
import { FinanceAdjustmentPanel } from './FinanceAdjustmentPanel.js';
import { FinanceChartPanel } from './FinanceChartPanel.js';
import { SettingsPanel, useSettingsPanel } from './SettingsPanel.js';
import { PeriodPending, ScopeFields, pendingPeriods } from './ScopePanel.js';
import { scenarioLabel as displayScenarioLabel } from './glossary.js';
import { editableScope, SCOPE_LABELS, type AnalysisScope, type ScopeKey, type ScopeValues } from './scope.js';
import { accountMapOptions, aliasOptions, contextOptions, datasetOptions, scopeFields, scopeSummary, unwrap, errorText } from './shared.js';
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

const PRIMARY_FIELDS: readonly ScopeKey[] = ['period', 'organization', 'unit'];
const MORE_FIELDS: readonly ScopeKey[] = ['currency', 'scenario', 'ledger'];

export type ScopeRequest = { count: number; contextId?: string };
type Calculation = 'pnl' | 'bridge';
const CALCULATION_NAMES: Record<Calculation, string> = { pnl: '计算损益表', bridge: '计算预算差异' };

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
  if (state.conflicts) return '先到资料页「分析范围」处理冲突。';
  if (state.scopeError) return '分析范围没有读出来，见下方提示。';
  if (!state.actual) return '先选实际资料。';
  // PeriodPending above names the months; the line does not repeat them.
  if (state.periodPending) return '先确认任务期间，资料写的期间见上方提示。';
  if (kind === 'bridge' && !state.budget) return '先选预算资料。';
  return '';
}
/** How the last finance operation ended: its name, the sentence shown for it, and when. */
export type FinanceOutcome = { label: string; result: 'ok' | 'error'; message: string; at: string };

export function FinanceWorkbench({ taskId, datasets, runs, busy, scope: analysisScope, comparesBudget = false, openRequest = { count: 0 }, running = '', outcome, onRunning, onOutcome, onRefresh, children }: {
  taskId: string; datasets: DatasetSnapshot[]; runs: AnalysisRun[]; busy: boolean;
  /** The analysis compares against a budget (a variance, or a budget file bound): 计算预算差异 leads. */
  comparesBudget?: boolean;
  /** The task's one scope; the fields here edit the same record as the 资料 page. */
  scope: AnalysisScope;
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
  // A missing budget is only worth a standing line when the budget comparison is the main action.
  const reasons = ([lead, second] as const).filter((kind) => blockers[kind] && !(kind === 'bridge' && lead !== 'bridge' && blockers.bridge === '先选预算资料。'));
  const reasonId = useId();
  const sameReason = reasons.length === 2 && blockers.pnl === blockers.bridge;
  const reasonLines: { id: string; text: string; kinds: Calculation[] }[] = sameReason
    ? [{ id: `${reasonId}-both`, text: blockers[lead], kinds: reasons }]
    : reasons.map((kind) => ({ id: `${reasonId}-${kind}`, text: `${CALCULATION_NAMES[kind]}：${blockers[kind]}`, kinds: [kind] }));
  const describedBy = (kind: Calculation) => reasonLines.find((line) => line.kinds.includes(kind))?.id;
  const calculate = (kind: Calculation, variant: 'default' | 'outline') => <Button key={kind} variant={variant} type="button"
    disabled={transient || Boolean(blockers[kind])} aria-describedby={describedBy(kind)} onClick={() => void saveContext(kind)}>{CALCULATION_NAMES[kind]}</Button>;
  const rerun = (kind: Calculation) => <Button key={kind} variant="outline" type="button" disabled={locked} onClick={() => void runExisting(kind)}>
    {kind === 'pnl' ? '按已保存范围重算损益表' : '按已保存范围计算预算差异'}</Button>;
  const moreScopeSummary = MORE_FIELDS.map((key) => scope[key] ? `${SCOPE_LABELS[key]} ${key === 'scenario' ? displayScenarioLabel(scope[key]) : scope[key]}` : '').filter(Boolean).join(' · ');
  const advancedChildren = typeof children === 'function' ? children(closeSetup) : children;
  const accountMapName = finance?.account_maps.find((item) => String(item.id ?? '') === accountMapId)?.name;
  return <><SettingsPanel state={settings} scrollIntoView summary="选好实际资料（和预算资料），确认范围后计算；高级定义也从这里进入。" note="选好范围后计算；高级定义也从这里进入。">
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
    <ScopeFields fields={PRIMARY_FIELDS} scope={scope} candidates={analysisScope.candidates} sources={analysisScope.candidateSources} disabled={locked} onField={analysisScope.setField} />
    {budget && <div className="analysis-edit-grid"><AccountingPeriodInput label="对比期间" value={comparePeriod} onChange={setComparePeriod}
      shortcutBaseValue={scope.period} shortcutBaseLabel="实际期间"
      help="留空时预算与实际取同一期间；填写后预算按这个期间取数。" /></div>}
    <details className="analysis-details"><DisclosureSummary>更多范围{moreScopeSummary ? ` · ${moreScopeSummary}` : ''}</DisclosureSummary>
      <ScopeFields fields={MORE_FIELDS} scope={scope} candidates={analysisScope.candidates} sources={analysisScope.candidateSources} disabled={locked} onField={analysisScope.setField} />
    </details></fieldset>
    {/* One main action, at the right; which one is the analysis's choice, so nothing moves while she fills the form in. */}
    <div className="analysis-actions analysis-actions--end">
      <Button variant="outline" type="button" disabled={disabled} onClick={() => void saveContext()}>保存范围</Button>
      {calculate(second, 'outline')}
      {calculate(lead, 'default')}
    </div>
    {reasonLines.length ? <div className="analysis-actions-reasons">{reasonLines.map((line) => <p key={line.id} id={line.id}>{line.text}</p>)}</div> : null}
    {contextId && <div className="analysis-actions analysis-actions--end">{rerun(lead)}{rerun(second)}</div>}
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
        {scenarioKind === 'cash_13_weeks' && <DecimalInput label="回款延迟天数" value={delayDays} onChange={setDelayDays} unit="天" />}
      </div></fieldset>
      <div className="analysis-actions">
        <Button variant="outline" type="button" disabled={locked || !contextId || !scenarioPrimary || (scenarioKind === 'cash_13_weeks' && (!openingCash || !scenarioStart || !scenarioCutoff))} onClick={() => void runScenario(false)}><Play size={14} aria-hidden />计算基准情景</Button>
        <Button variant="outline" type="button" disabled={locked || scenarioKind !== 'cash_13_weeks' || !baselineScenarioId} onClick={() => void runScenario(true)}>计算延迟回款情景</Button>
      </div>
      {finance?.scenarios.filter((scenario) => scenario.context_id === contextId && scenario.kind === scenarioKind).length ? <div className="analysis-history-list">{[...finance.scenarios].filter((scenario) => scenario.context_id === contextId && scenario.kind === scenarioKind).reverse().slice(0, 6).map((scenario) => <button type="button" className="analysis-history-row" key={String(scenario.id)} disabled={locked}
        aria-current={scenario.id === baselineScenarioId ? 'true' : undefined} onClick={() => setBaselineScenarioId(String(scenario.id ?? ''))}>
        <span>{textValue(scenario.label ?? scenario.kind)}</span><span>{scenario.kind === 'cash_13_weeks' ? '13 周现金' : scenario.kind === 'receivables_aging' ? '应收账龄' : textValue(scenario.kind)}</span><time>{when(String(scenario.created_at ?? ''))}</time></button>)}</div> : null}
    </details>}
    {finance?.contexts.length ? <details className="analysis-details"><DisclosureSummary>已保存的范围 · {finance.contexts.length} 个</DisclosureSummary>
      <div className="analysis-history-list">{[...finance.contexts].reverse().map((context) => <button key={context.id} type="button" className="analysis-history-row" disabled={locked}
        aria-current={context.id === contextId ? 'true' : undefined} onClick={() => setContextId(context.id)}>
        <span>{context.name}</span><span>{Object.entries(context.scopes ?? {}).map(([alias, item]) => `${alias === 'actual' ? '实际' : alias === 'budget' ? '预算' : alias} ${scopeSummary(item)}`).join('；')}</span></button>)}</div></details> : null}
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
  {/* Outside the settings: a run closes them on success, and the outcome must stay readable. */}
  {running ? <p role="status" className="analysis-message"><WaitOrb state="solving" />{running}</p>
    : outcome?.result === 'ok' ? <p role="status" className="analysis-message">{outcome.message}</p>
    : message ? <p role="status" className="analysis-message">{message}</p> : null}
  {outcome?.result === 'error' && <p role="alert" className="analysis-message analysis-message--error">{outcome.message}</p>}
  {error && <p role="alert" className="analysis-message analysis-message--error">{error}</p>}
  {contextId ? <FinanceAdjustmentPanel taskId={taskId} contextId={contextId} busy={locked} onRefresh={onRefresh} /> : null}
  {contextId ? <FinanceChartPanel taskId={taskId} runs={runs} busy={locked} onRefresh={onRefresh} /> : null}
  </>;
}
