import { useEffect, useRef, useState } from 'react';
import { Play } from 'lucide-react';
import { bridge, shortSha, timeWait, when, type Answer, type AnalysisRun, type DatasetSnapshot, type FinanceContext, type FinanceContextState, type WaitKind } from '../../bridge.js';
import { textValue } from './presentation.js';
import { WaitOrb } from '../../components/WaitOrb.js';
import { AccountMapEditor } from './AccountMapEditor.js';
import { AccountingPeriodInput, DateInput, DecimalInput, FieldShell, MultiSelect, SearchableSelect, TextField, type SelectOption } from '../../components/FinancialControls.js';
import { Button } from '../../components/ui/button.js';
import { Input } from '../../components/ui/input.js';
import { FinanceAdjustmentPanel } from './FinanceAdjustmentPanel.js';
import { FinanceChartPanel } from './FinanceChartPanel.js';
import { accountMapOptions, aliasOptions, contextOptions, datasetOptions, scopeFields, scopeSummary, unwrap, errorText } from './shared.js';

function bridgeScenarioLabels(context?: FinanceContext): { actual: string; baseline: string } {
  const scopes = context?.scopes ?? {};
  const actualScope = scopes.actual;
  const budgetScope = scopes.budget;
  if (!actualScope || !budgetScope) {
    throw new Error('预算桥需要已保存口径包含明确的 actual 与 budget 情景别名。请用实际资料和预算资料重新保存口径后再运行。');
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

export type ScopeRequest = { count: number; contextId?: string };
/** How the last finance operation ended: its name, the sentence shown for it, and when. */
export type FinanceOutcome = { label: string; result: 'ok' | 'error'; message: string; at: string };

export function FinanceWorkbench({ taskId, datasets, runs, busy, openRequest = { count: 0 }, running = '', outcome, onRunning, onOutcome, onRefresh }: {
  taskId: string; datasets: DatasetSnapshot[]; runs: AnalysisRun[]; busy: boolean;
  /** Bumped by 调整口径 on a result; each new count opens the settings on that result's scope. */
  openRequest?: ScopeRequest;
  /** What is running right now, in words; owned by the parent so it outlives this component. */
  running?: string; onRunning(label: string, active: boolean): void;
  /** Owned by the parent for the same reason; null clears it. */
  outcome?: FinanceOutcome; onOutcome(outcome: FinanceOutcome | null): void;
  onRefresh(): Promise<void>;
}) {
  const [finance, setFinance] = useState<FinanceContextState | null>(null);
  const [actual, setActual] = useState(datasets[0]?.id ?? '');
  const [budget, setBudget] = useState('');
  const [scope, setScope] = useState<Record<string, string>>({ ledger: '', organization: '', period: '', currency: 'CNY', unit: '元', scenario: 'actual' });
  const [budgetScope, setBudgetScope] = useState<Record<string, string>>({ scenario: 'budget' });
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
  const [setupOpen, setSetupOpen] = useState(!hasSuccessfulResults);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const setup = useRef<HTMLDetailsElement>(null);
  // A remount (tab change, new task) must not replay a request it did not see.
  const seenRequest = useRef(openRequest.count);
  useEffect(() => { setActual((value) => value || datasets[0]?.id || ''); }, [datasets]);
  useEffect(() => { if (hasSuccessfulResults) setSetupOpen(false); }, [hasSuccessfulResults]);
  useEffect(() => {
    if (openRequest.count === seenRequest.current) return;
    seenRequest.current = openRequest.count;
    setSetupOpen(true);
    setup.current?.scrollIntoView?.({ block: 'start', behavior: 'smooth' });
    setup.current?.querySelector('summary')?.focus({ preventScroll: true });
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
    if (!wanted) { setMessage('这条结果没有记录财务口径，设置区显示的是当前选中的口径。'); return; }
    let context = finance?.contexts.find((item) => item.id === wanted);
    if (!context) {
      try {
        const api = bridge(); if (!api?.financeCall) throw new Error('此版本暂不支持财务业务口径。');
        const value = unwrap(await api.financeCall(taskId, 'list-finance-context') as Answer<FinanceContextState>);
        setFinance(value);
        context = value.contexts.find((item) => item.id === wanted);
      } catch (failure) {
        setError(errorText(failure));
        return;
      }
    }
    if (context) { loadContext(context); setMessage(''); }
    else setMessage('没有找到这条结果用的财务口径，设置区显示的是当前选中的口径。');
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
    setScope((current) => ({ ...current, ...Object.fromEntries(scopeFields.map(([key]) => [key, text(actualScope[key])])) }));
    if (budgetScope) {
      setBudgetScope({ scenario: text(budgetScope.scenario) || 'budget' });
      setComparePeriod(text(budgetScope.period) !== text(actualScope.period) ? text(budgetScope.period) : '');
    }
  }
  /** One operation as the manager waits on it: both calls of 保存并运行 and the read-back after are one timed wait. */
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
  function saveContext(runAfter?: 'pnl' | 'bridge') {
    return track(runAfter === 'pnl' ? 'finance.pnl' : runAfter === 'bridge' ? 'finance.bridge' : 'finance.save',
      runAfter === 'pnl' ? '正在保存口径并运行管理口径损益…' : runAfter === 'bridge' ? '正在保存口径并运行预算差异桥…' : '正在保存口径…', async (done) => {
      const api = bridge(); if (!api?.financeCall) throw new Error('此版本暂不支持财务业务口径。');
      const bindings = { actual, ...(budget ? { budget } : {}) };
      const scopes = { actual: scope, ...(budget ? { budget: { ...scope, ...budgetScope, ...(comparePeriod ? { period: comparePeriod } : {}) } } : {}) };
      // A form refilled from a saved scope keeps what it does not show: each alias's
      // policies (field map, target unit) while that alias still binds the same dataset.
      const base = loaded.current?.id === contextId ? loaded.current : null;
      const policies = Object.fromEntries(Object.entries(base?.policies ?? {})
        .filter(([alias]) => (bindings as Record<string, string>)[alias] === base?.bindings?.[alias]));
      const context = unwrap(await api.financeCall(taskId, 'finance-context-save', {
        name: `${scope.period || '本期'}${scope.organization ? ` ${scope.organization}` : ''}经营口径`,
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
        done('已保存口径并运行管理口径损益。', run);
        setSetupOpen(false);
      } else if (runAfter === 'bridge') {
        const labels = bridgeScenarioLabels(context);
        const run = unwrap(await api.financeCall(taskId, 'explain-variance', {
          context_id: context.id, actual_scenario: labels.actual, baseline_scenario: labels.baseline,
          dimensions: bridgeDimensions,
        }));
        done('已保存口径并运行预算差异桥。', run);
        setSetupOpen(false);
      } else {
        done('已保存财务分析口径。');
      }
      await onRefresh();
    });
  }
  function saveMap() {
    return track('finance.save', '正在保存映射…', async (done) => {
      const api = bridge(); if (!api?.financeCall) throw new Error('此版本暂不支持管理科目映射。');
      const parsed = JSON.parse(mapRows);
      if (!Array.isArray(parsed)) throw new Error('映射 JSON 需要是数组。');
      const record = unwrap(await api.financeCall(taskId, 'finance-map-save', { name: mapName, rows: parsed }) as Answer<Record<string, unknown>>);
      setAccountMapId(String(record.id ?? ''));
      setFinance((value) => value ? { ...value, account_maps: [...value.account_maps, record] } : value);
      done('已保存管理科目映射，可用于下一次口径保存。');
    });
  }
  const runExisting = (kind: 'pnl' | 'bridge') => track(kind === 'pnl' ? 'finance.pnl' : 'finance.bridge', kind === 'pnl' ? '正在运行管理口径损益…' : '正在运行预算差异桥…', async (done) => {
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
    done(kind === 'pnl' ? '已运行管理口径损益。' : '已运行预算差异桥。', run);
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
    return track('finance.scenario', child ? '正在运行延迟回款子情景…' : '正在运行基准情景…', async (done) => {
      const api = bridge(); if (!api?.financeCall || !contextId) throw new Error('请先保存或选择财务口径。');
      const scenarioScope = selectedContext?.scopes?.[scenarioPrimary] ?? scope;
      let scenario: Record<string, unknown>;
      if (child) {
        if (scenarioKind !== 'cash_13_weeks') throw new Error('延迟回款子情景仅适用于 13 周现金测算。');
        if (!baselineScenarioId) throw new Error('请先运行一个 13 周现金基准情景。');
        const parent = finance?.scenarios.find((item) => item.id === baselineScenarioId);
        if (parent && (parent.kind !== 'cash_13_weeks' || parent.context_id !== contextId)) throw new Error('请选择同一财务口径下的 13 周现金基准情景。');
        scenario = unwrap(await api.financeCall(taskId, 'finance-scenario-save', {
          parent_id: baselineScenarioId,
          label: `${scenarioLabel || '情景'} · 延迟 ${delayDays || '0'} 天`,
          changes: { scenario: { delay_receipts_days: Number(delayDays || 0), label: `回款延迟 ${delayDays || 0} 天` } },
        }));
      } else {
        const inputs = scenarioKind === 'receivables_aging'
          ? { as_of: scenarioAsOf || scope.period || scope.cutoff_at, scope: scenarioScope, invoices_alias: scenarioPrimary,
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
      done(child ? '已运行延迟回款子情景。' : '已运行基准情景。', run);
      setSetupOpen(false);
      await onRefresh();
    });
  }
  const locked = busy || Boolean(running);
  const disabled = locked || !actual;
  const moreScope = scopeFields.filter(([key]) => key !== 'period');
  const moreScopeSummary = moreScope.map(([key, label]) => scope[key] ? `${label} ${scope[key]}` : '').filter(Boolean).join(' · ');
  return <><details ref={setup} className="analysis-finance-setup" aria-label="财务分析设置" open={setupOpen}
    onToggle={(event) => setSetupOpen((event.currentTarget as HTMLDetailsElement).open)}>
    <summary><div className="analysis-section-heading"><h3>财务业务口径</h3><span className="analysis-note">用已登记资料建立范围，结果仍保留 SQL 与脚本高级路径。</span></div></summary>
    <fieldset className="analysis-fieldset" disabled={locked}><div className="analysis-edit-grid">
      <SearchableSelect label="实际资料" value={actual} options={datasetOptions(datasets)} onChange={(value) => {
        setActual(value);
        if (budget === value) setBudget('');
      }} placeholder="搜索资料名称、来源或快照" />
      <SearchableSelect label="预算资料（可选）" value={budget} options={datasetOptions(datasets.filter((source) => source.id !== actual))}
        onChange={setBudget} placeholder="搜索预算资料" allowEmptyLabel="暂不选择" />
      {finance?.contexts.length ? <SearchableSelect label="已保存口径" value={contextId} options={contextOptions(finance)}
        onChange={setContextId} placeholder="搜索口径名称或范围" /> : null}
      <AccountingPeriodInput label="期间" value={scope.period ?? ''} onChange={(value) => setScope({ ...scope, period: value })} />
      {budget && <TextField label="预算情景名称" value={budgetScope.scenario ?? ''} onChange={(value) => setBudgetScope({ ...budgetScope, scenario: value })} />}
      {budget && <AccountingPeriodInput label="对比期间" value={comparePeriod} onChange={setComparePeriod}
        shortcutBaseValue={scope.period} shortcutBaseLabel="实际期间"
        help="快捷项基于实际期间；留空时沿用实际期间，填写后预算桥按该期间保存 baseline 范围。" />}
    </div>
    <details className="analysis-details"><summary>更多范围{moreScopeSummary ? ` · ${moreScopeSummary}` : ''}</summary>
      <div className="analysis-edit-grid">{moreScope.map(([key, label]) =>
        <TextField key={key} label={label} value={scope[key] ?? ''} onChange={(value) => setScope({ ...scope, [key]: value })} />)}</div>
    </details></fieldset>
    <div className="analysis-actions">
      <Button variant="outline" type="button" disabled={disabled} onClick={() => void saveContext()}>保存口径</Button>
      <Button type="button" disabled={disabled} onClick={() => void saveContext('pnl')}>保存并运行 P&L</Button>
      <Button variant="outline" type="button" disabled={disabled || !budget} onClick={() => void saveContext('bridge')}>运行预算桥</Button>
      {contextId && <Button variant="outline" type="button" disabled={locked} onClick={() => void runExisting('pnl')}>用已保存口径重跑 P&L</Button>}
      {contextId && <Button variant="outline" type="button" disabled={locked} onClick={() => void runExisting('bridge')}>用已保存口径运行预算桥</Button>}
    </div>
    {contextId && <details className="analysis-details analysis-scenario-panel"><summary>情景测算</summary>
      <fieldset className="analysis-fieldset" disabled={locked}><div className="analysis-edit-grid">
        <FieldShell label="情景类型"><select aria-label="情景类型" className="fnd-field" value={scenarioKind} onChange={(event) => setScenarioKind(event.target.value as typeof scenarioKind)}>
          <option value="receivables_aging">应收账龄</option><option value="cash_13_weeks">13 周现金</option></select></FieldShell>
        <TextField label="情景名称" value={scenarioLabel} onChange={setScenarioLabel} />
        <SearchableSelect label={scenarioKind === 'receivables_aging' ? '应收/发票资料' : '回款资料'} value={scenarioPrimary}
          options={aliasOptions(aliases, selectedContext)} onChange={setScenarioPrimary} placeholder="搜索情景别名或资料编号" />
        <SearchableSelect label={scenarioKind === 'receivables_aging' ? '核销活动（可选）' : '付款资料（可选）'} value={scenarioSecondary}
          options={aliasOptions(aliases.filter((alias) => alias !== scenarioPrimary), selectedContext)}
          onChange={setScenarioSecondary} placeholder="搜索情景别名或资料编号" allowEmptyLabel="暂不选择" />
        {scenarioKind === 'receivables_aging' ? <>
          <DateInput label="账龄日期" value={scenarioAsOf} onChange={setScenarioAsOf} />
          <TextField label="状态字段" value={scenarioStatusField} onChange={setScenarioStatusField} help="账龄计算会按这个列名识别发票状态。" />
          <MultiSelect label="应收状态筛选" values={scenarioStatuses} options={agingStatusOptions} onChange={setScenarioStatuses}
            placeholder="默认纳入全部状态" help="选择后只纳入这些状态；不选则纳入全部应收记录。" />
        </> : <>
          <DecimalInput label="期初现金" value={openingCash} onChange={setOpeningCash} placeholder="5000000.00" unit={scope.unit || '元'} />
          <DateInput label="预测开始日" value={scenarioStart} onChange={setScenarioStart}
            help="写入 start_date；通常晚于实际收支截止日。" />
          <DateInput label="实际收支截止日" value={scenarioCutoff} onChange={setScenarioCutoff}
            help="写入 actual_cutoff；这是历史实际收支边界，不是预测结束日。" />
        </>}
        {scenarioKind === 'cash_13_weeks' && <DecimalInput label="回款延迟天数" value={delayDays} onChange={setDelayDays} unit="天" />}
      </div></fieldset>
      <div className="analysis-actions">
        <Button variant="outline" type="button" disabled={locked || !contextId || !scenarioPrimary || (scenarioKind === 'cash_13_weeks' && (!openingCash || !scenarioStart || !scenarioCutoff))} onClick={() => void runScenario(false)}><Play size={14} aria-hidden />运行基准情景</Button>
        <Button variant="outline" type="button" disabled={locked || scenarioKind !== 'cash_13_weeks' || !baselineScenarioId} onClick={() => void runScenario(true)}>运行延迟回款子情景</Button>
      </div>
      {finance?.scenarios.filter((scenario) => scenario.context_id === contextId && scenario.kind === scenarioKind).length ? <div className="analysis-history-list">{[...finance.scenarios].filter((scenario) => scenario.context_id === contextId && scenario.kind === scenarioKind).reverse().slice(0, 6).map((scenario) => <button type="button" className="analysis-history-row" key={String(scenario.id)} disabled={locked}
        aria-current={scenario.id === baselineScenarioId ? 'true' : undefined} onClick={() => setBaselineScenarioId(String(scenario.id ?? ''))}>
        <span>{textValue(scenario.label ?? scenario.kind)}</span><span>{textValue(scenario.kind)}</span><time>{when(String(scenario.created_at ?? ''))}</time><span>{shortSha(String(scenario.id ?? ''))}</span></button>)}</div> : null}
    </details>}
    {finance?.contexts.length ? <details className="analysis-details"><summary>已保存财务口径 · {finance.contexts.length} 个</summary>
      <div className="analysis-history-list">{[...finance.contexts].reverse().map((context) => <button key={context.id} type="button" className="analysis-history-row" disabled={locked}
        aria-current={context.id === contextId ? 'true' : undefined} onClick={() => setContextId(context.id)}>
        <span>{context.name}</span><span>{Object.entries(context.scopes ?? {}).map(([alias, item]) => `${alias} ${scopeSummary(item)}`).join('；')}</span><span>{shortSha(context.id)}</span></button>)}</div></details> : null}
    <details className="analysis-details"><summary>管理科目映射</summary>
      <p className="analysis-note">损益算不出来，多半是这里没配齐。引擎只认收入、成本、费用三个管理科目，把原表的科目代码归到这三类。</p>
      <div className="analysis-edit-grid"><label>映射名称<Input className="min-w-0 flex-1" value={mapName} disabled={locked} onChange={(event) => setMapName(event.target.value)}  /></label>
        <SearchableSelect label="已保存映射" value={accountMapId} disabled={locked} options={accountMapOptions(finance)} onChange={setAccountMapId}
          placeholder="搜索映射名称或编号" allowEmptyLabel="暂不使用" /></div>
      <AccountMapEditor value={mapRows} disabled={locked} onChange={setMapRows} />
      {accountMapId && <p className="analysis-note">当前口径保存时会使用映射 {shortSha(accountMapId)}。</p>}
      <Button variant="outline" type="button" disabled={locked || !mapRows.trim()} onClick={() => void saveMap()}>保存映射</Button>
    </details>
  </details>
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
