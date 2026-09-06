import { useEffect, useRef, useState } from 'react';
import { X } from 'lucide-react';
import { shortSha, when, type AnalysisRevision, type AnalysisRun, type DatasetSnapshot, type FinanceDrilldown } from '../../bridge.js';
import { readCopy, writeCopy } from './workingCopy.js';
import { assumptionSummary, parameterSummary, RunStatus, STATUS, Table } from './presentation.js';

export function RunPanel({ analysis, analyses, runs, datasets, busy, onPick, onChat, onOpen, onSource, onSaveMethod, onDrilldown }: {
  analysis: AnalysisRevision; analyses: AnalysisRevision[]; runs: AnalysisRun[]; datasets: DatasetSnapshot[]; busy: boolean;
  onPick(id: string): void; onChat(question: string): void; onOpen(run: AnalysisRun, path: string): void;
  onSource(source: DatasetSnapshot): void; onSaveMethod(id: string, name: string): void;
  onDrilldown?(run: AnalysisRun, row: number, column?: string, section?: SourceDrilldownSection): Promise<FinanceDrilldown>;
}) {
  const [selected, setSelected] = useState(() => readCopy<string>(`${analysis.task_id}:run`) ?? '');
  const [evidence, setEvidence] = useState(false);
  const [comparing, setComparing] = useState(false);
  const [comparison, setComparison] = useState('');
  const [methodName, setMethodName] = useState('');
  const evidenceButton = useRef<HTMLButtonElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const relevant = runs.filter((run) => run.analysis_id === analysis.id);
  const run = relevant.find((row) => row.id === selected)
    ?? [...relevant].reverse().find((row) => row.execution_status === 'succeeded' || row.execution_status === 'success') ?? relevant.at(-1);
  const latest = runs.at(-1);
  const compared = runs.find((row) => row.id === comparison && row.id !== run?.id);
  const assumptions = run?.assumptions ?? analysis.assumptions;
  useEffect(() => { if (evidence) closeButton.current?.focus({ preventScroll: true }); }, [evidence]);
  const closeEvidence = () => { setEvidence(false); evidenceButton.current?.focus({ preventScroll: true }); };
  const pick = (next: AnalysisRun) => {
    setSelected(next.id); writeCopy(`${analysis.task_id}:run`, next.id); onPick(next.analysis_id);
    setEvidence(false); setComparing(false);
  };
  return <div className="analysis-result-area" data-evidence-open={evidence || undefined}>
    {latest && run && latest.id !== run.id && latest.execution_status === 'failed' && <p className="analysis-message analysis-message--error">
      最近一次运行失败，当前保留已成功的结果。<button type="button" className="fnd-button" onClick={() => pick(latest)}>查看失败记录</button></p>}
    {!run ? <p className="analysis-note">此版本尚未运行。检查口径后即可计算。</p> : <article className="analysis-result">
      <div className="analysis-section-heading"><div><h3>{analysis.question}</h3><p className="analysis-note">{when(run.created_at)} · 运行 {shortSha(run.id)}</p></div><RunStatus run={run} /></div>
      {run.error && <p role="alert" className="analysis-message analysis-message--error">{run.error}</p>}
      {run.result && run.result.columns.length > 0 && <RunResultTable run={run} />}
      {(run.engine === 'finance' || isStructuredAggregateRun(run)) && <SourceTraceDetails run={run} busy={busy} onDrilldown={onDrilldown} />}
      {run.stdout && <pre className="analysis-source-text" aria-label="脚本计算输出">{run.stdout}</pre>}
      {Boolean(run.outputs?.length) && <div className="analysis-output-list"><h4>生成的文件</h4>{run.outputs?.map((output) => <div key={output.path} className="analysis-actions">
        <span>{output.path}</span><button type="button" className="fnd-button" disabled={busy} aria-label={`打开文件 ${output.path}`}
          onClick={() => onOpen(run, output.path)}>打开文件</button></div>)}</div>}
      <div className="analysis-actions">
        <button ref={evidenceButton} type="button" className="fnd-button" aria-expanded={evidence} aria-controls={`analysis-evidence-${analysis.task_id}`} onClick={() => setEvidence(!evidence)}>查看本次计算依据</button>
        <button type="button" className="fnd-button" disabled={busy} onClick={() => onChat(`请把分析「${analysis.question}」的运行 ${run.id} 整理成可编辑的经营分析文稿，区分计算结果、假设与专业判断。`)}>整理成文稿</button>
        {runs.length > 1 && <button type="button" className="fnd-button" aria-expanded={comparing} onClick={() => setComparing(!comparing)}>比较版本</button>}
      </div>
      {analysis.sql && <details className="analysis-details"><summary>保存这次分析方法</summary><form className="analysis-method-form" onSubmit={(event) => {
        event.preventDefault(); if (methodName.trim()) onSaveMethod(analysis.id, methodName.trim());
      }}><label>方法名称<input className="fnd-field" value={methodName} onChange={(event) => setMethodName(event.target.value)} placeholder={analysis.question} disabled={busy} /></label>
        <button type="submit" className="fnd-button" disabled={busy || !methodName.trim()}>保存为方法</button></form>
        <p className="analysis-note">保留当前计算方式。下次使用时，重新选择资料和业务参数。</p></details>}
    </article>}
    {run && evidence && <div className="analysis-evidence-anchor"><aside id={`analysis-evidence-${analysis.task_id}`} role="dialog" aria-modal="false" className="analysis-evidence" aria-label="本次计算依据" onKeyDown={(event) => { if (event.key === 'Escape') { event.preventDefault(); closeEvidence(); } }}>
      <div className="analysis-section-heading"><h3>本次计算依据</h3><button ref={closeButton} className="fnd-button" type="button" onClick={closeEvidence} aria-label="关闭计算依据"><X size={16} aria-hidden /></button></div>
      <p className="analysis-note">按实际保存的资料版本和运行记录核对。</p>
      <div className="analysis-evidence-sources">{Object.entries(run.input_hashes ?? {}).map(([id, hash]) => {
        // SQL and script runs store alias -> data_hash. Bindings are immutable
        // snapshot IDs; never resolve by display name or the latest upload.
        const datasetId = (run.bindings ?? analysis.bindings)[id] ?? id;
        const source = datasets.find((row) => row.id === datasetId);
        const mismatch = source?.data_hash != null && source.data_hash !== hash;
        return <div key={id}><strong>{source?.name ?? '资料快照'}</strong><p className="analysis-note">{source?.source_name ?? datasetId}</p>
          {source && <button type="button" className="fnd-button" disabled={busy || mismatch} onClick={() => { if (!mismatch) onSource(source); }}>查看 {source.name}</button>}
          {mismatch && <p className="analysis-note">资料摘要与运行记录不一致，暂不可预览。</p>}
          <details className="analysis-details"><summary>资料标识与摘要</summary><p>{datasetId}</p><p>{hash}</p></details></div>;
      })}</div>
      <p>参数：{parameterSummary(run.parameters ?? analysis.parameters, run.parameter_metadata ?? analysis.parameter_metadata)}</p>
      {assumptions.length > 0 && <p>假设说明：{assumptionSummary(assumptions)}</p>}
      {run.finance_scope && <details className="analysis-details"><summary>财务范围</summary>{Object.entries(run.finance_scope).map(([alias, scope]) =>
        <p key={alias}>{alias}：{textValue(scope)}</p>)}</details>}
      <details className="analysis-details"><summary>运行标识与结果摘要</summary><p>{run.id}</p>{run.output_hash && <p>{run.output_hash}</p>}</details>
    </aside></div>}
    {run && comparing && <section className="analysis-comparison" aria-label="版本比较"><div className="analysis-section-heading"><h3>版本比较</h3>
      <button type="button" className="fnd-button" onClick={() => setComparing(false)}>关闭比较</button></div>
      <label className="analysis-select-label">对照运行<select className="fnd-field" value={comparison} onChange={(event) => setComparison(event.target.value)}>
        <option value="">选择一个已保存的运行</option>{[...runs].reverse().filter((row) => row.id !== run.id).map((row) =>
          <option key={row.id} value={row.id}>{analyses.find((item) => item.id === row.analysis_id)?.question ?? '分析'} · {when(row.created_at)} · {shortSha(row.id)}</option>)}</select></label>
      {compared && <><p className="analysis-note">按各次运行原有的行序展示，未推断业务主键或计算差额。</p><div className="analysis-comparison-grid">{[run, compared].map((row, index) => {
        const definition = analyses.find((item) => item.id === row.analysis_id);
        return <div key={row.id}><h4>{index === 0 ? '当前结果' : '对照结果'} · {shortSha(row.id)}</h4><RunStatus run={row} />
          <p>参数：{parameterSummary(row.parameters ?? definition?.parameters, row.parameter_metadata ?? definition?.parameter_metadata)}</p>
          <p>假设说明：{assumptionSummary(row.assumptions ?? definition?.assumptions)}</p>
          {row.result?.columns.length ? <Table columns={row.result.columns} rows={row.result.rows} caption={index === 0 ? '当前版本数据' : '对照版本数据'} />
            : <p className="analysis-note">{row.error ?? '此运行没有表格结果。'}</p>}</div>;
      })}</div></>}
    </section>}
    <details className="analysis-details analysis-history"><summary>运行历史 · {runs.length} 次</summary>
      <div className="analysis-history-list">{[...runs].reverse().map((row) => <button key={row.id} type="button" className="analysis-history-row" aria-current={row.id === run?.id ? 'true' : undefined} onClick={() => pick(row)}>
        <span>{analyses.find((item) => item.id === row.analysis_id)?.question ?? '分析'}</span><span>{STATUS[row.execution_status] ?? row.execution_status}</span><time>{when(row.created_at)}</time><span>{shortSha(row.id)}</span></button>)}</div>
    </details>
  </div>;
}


function RunResultTable({ run }: { run: AnalysisRun }) {
  if (isFinanceVarianceRun(run)) return <FinanceVarianceTable run={run} />;
  if (isStructuredAggregateRun(run)) return <StructuredAggregateTable run={run} />;
  return <><Table key={run.id} columns={run.result!.columns} rows={run.result!.rows} caption="计算结果" />
    <p className="analysis-note">{run.result!.row_count} 行{run.result!.truncated ? ' · 当前为截断预览' : ''}</p></>;
}

type SourceDrilldownSection = 'rows' | 'detail_rows' | 'excluded_detail_rows';

const structuredAggregateHiddenColumns = new Set(['result_key', 'source_rows', 'excluded_source_rows', 'provenance_status']);

function isStructuredAggregateRun(run: AnalysisRun): boolean {
  return run.engine === 'structured_aggregate';
}

function structuredAggregateColumns(run: AnalysisRun, rows: Record<string, unknown>[] = run.result?.rows ?? []) {
  const columnByName = new Map((run.result?.columns ?? []).map((column) => [column.name, column]));
  const rowNames = Array.from(new Set(rows.flatMap((row) => Object.keys(row))));
  const names = rowNames.length ? rowNames : run.result?.columns.map((column) => column.name) ?? [];
  return names.filter((name) => !structuredAggregateHiddenColumns.has(name))
    .map((name) => columnByName.get(name) ?? { name, type: typeof rows.find((row) => row[name] != null)?.[name] === 'number' ? 'DOUBLE' : 'VARCHAR' });
}

function structuredAggregateRows(rows: Record<string, unknown>[]) {
  return rows.map((row) => Object.fromEntries(Object.entries(row).filter(([key]) => !structuredAggregateHiddenColumns.has(key))));
}

function provenanceVerified(run: AnalysisRun): boolean {
  const provenance = run.result?.provenance;
  return Boolean(provenance && provenance.mode === 'executor_verified_source_map' && provenance.status === 'verified');
}

function diagnosticField(item: Record<string, unknown>, names: string[]): unknown {
  for (const name of names) if (item[name] != null && item[name] !== '') return item[name];
  return undefined;
}

function structuredDiagnosticText(value: unknown): string {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return textValue(value);
  const item = value as Record<string, unknown>;
  const code = textValue(item.code);
  if (code === 'aggregate_missing_measure_values') {
    const metric = diagnosticField(item, ['metric', 'measure', 'field', 'column', 'name']);
    const count = diagnosticField(item, ['missing_count', 'count', 'source_count', 'row_count', 'rows']);
    const method = textValue(item.aggregation ?? 'sum').toLowerCase();
    const countText = count == null ? '部分' : textValue(count);
    const metricText = metric == null ? '某指标' : `指标“${textValue(metric)}”`;
    if (method.includes('sum')) return `${metricText}有 ${countText} 条来源金额缺失，汇总未完成。`;
    const methodText = method.includes('count_distinct') ? '去重计数'
      : method.includes('min') ? '最小值' : method.includes('max') ? '最大值' : textValue(item.aggregation ?? '聚合');
    return `${metricText}有 ${countText} 条来源金额缺失，${methodText}结果已排除这些缺失来源，请复核口径。`;
  }
  const message = typeof item.message === 'string' ? item.message : '';
  return message || `结构化汇总诊断：${textValue(value)}`;
}

function StructuredAggregateTable({ run }: { run: AnalysisRun }) {
  const result = run.result!;
  const detailRows = result.detail_rows ?? [];
  const excludedRows = result.excluded_detail_rows ?? [];
  const columns = structuredAggregateColumns(run);
  const diagnostics = result.diagnostics ?? [];
  return <section className="analysis-structured-aggregate">
    {provenanceVerified(run) && <p className="analysis-note">来源可追溯：执行器已核对来源映射；这不代表业务判断已经通过。</p>}
    {diagnostics.length > 0 && <div className="analysis-message analysis-message--warning" role="status">
      {diagnostics.map((item, index) => <p key={index}>{structuredDiagnosticText(item)}</p>)}
    </div>}
    <Table key={`${run.id}:structured`} columns={columns} rows={structuredAggregateRows(result.rows)} caption="结构化汇总结果" />
    <p className="analysis-note">{result.row_count} 行{result.truncated ? ' · 当前为截断预览' : ''}</p>
    {detailRows.length > 0 && <details className="analysis-details"><summary>来源明细 · {detailRows.length} 行</summary>
      <Table key={`${run.id}:detail`} columns={structuredAggregateColumns(run, detailRows)} rows={structuredAggregateRows(detailRows)} caption="来源明细" />
    </details>}
    {excludedRows.length > 0 && <details className="analysis-details"><summary>剔除明细 · {excludedRows.length} 行</summary>
      <Table key={`${run.id}:excluded`} columns={structuredAggregateColumns(run, excludedRows)} rows={structuredAggregateRows(excludedRows)} caption="剔除明细" />
    </details>}
    {diagnostics.length > 0 && <details className="analysis-details"><summary>原始诊断细节 · {diagnostics.length} 项</summary>
      {diagnostics.map((item, index) => <p key={index}>{textValue(item)}</p>)}
    </details>}
    <details className="analysis-details"><summary>原始结果字段 · {result.columns.length} 列</summary>
      <Table key={`${run.id}:structured-raw`} columns={result.columns} rows={result.rows} caption="原始计算结果" />
    </details>
  </section>;
}

type FinanceVarianceResult = NonNullable<AnalysisRun['result']> & {
  method?: unknown;
  comparison?: { actual_scenario?: unknown; baseline_scenario?: unknown } | Record<string, unknown>;
};

const financeVarianceReservedColumns = new Set(['metric', 'actual', 'baseline', 'amount_change', 'profit_impact', 'contribution', 'ratio', 'ratio_status', 'favorability', 'comparison_status']);

function financeVarianceResult(run: AnalysisRun): FinanceVarianceResult | undefined {
  return run.result as FinanceVarianceResult | undefined;
}

function isFinanceVarianceRun(run: AnalysisRun): boolean {
  const result = financeVarianceResult(run);
  const names = new Set(result?.columns.map((column) => column.name) ?? []);
  return run.engine === 'finance' && result?.method === 'revenue_minus_cost_minus_expense'
    && ['metric', 'actual', 'baseline', 'contribution', 'ratio'].every((name) => names.has(name));
}

const financeMetricLabel: Record<string, string> = { revenue: '收入', cost: '成本', expense: '费用', profit: '利润' };
const financeScopeLabels: Record<string, string> = {
  ledger: '账簿', ledger_id: '账簿', organization: '组织', organization_id: '组织', period: '期间', currency: '币种', unit: '单位', scenario: '情景',
};

function formatVarianceRatio(value: unknown): string {
  if (value == null || value === '') return '—';
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return `${textValue(value)} 倍`;
  if (Math.abs(numeric) > 1000) return `${textValue(value)} 倍`;
  return `${(numeric * 100).toLocaleString('zh-CN', { maximumFractionDigits: 2, minimumFractionDigits: 0 })}%`;
}

function distinctFinanceValues(rows: Record<string, unknown>[], name: string): string[] {
  return Array.from(new Set(rows.map((row) => row[name]).filter((value) => value != null && value !== '').map(textValue)));
}

function financeVarianceScope(run: AnalysisRun): string {
  const rows = run.result?.rows ?? [];
  const columns = run.result?.columns.map((column) => column.name) ?? [];
  const parts = columns.filter((name) => !financeVarianceReservedColumns.has(name)).flatMap((name) => {
    const values = distinctFinanceValues(rows, name);
    if (values.length !== 1) return [];
    const label = financeScopeLabels[name] ?? name;
    return `${label} ${values[0]}`;
  });
  return parts.join(' · ') || '按当前财务口径汇总';
}

function financeVarianceDimensionColumns(run: AnalysisRun): { name: string; type?: string }[] {
  const rows = run.result?.rows ?? [];
  return run.result?.columns.filter((column) => !financeVarianceReservedColumns.has(column.name) && distinctFinanceValues(rows, column.name).length > 1) ?? [];
}

function financeVarianceCopy(run: AnalysisRun): { caption: string; baselineLabel: string; actualLabel: string } {
  const comparison = financeVarianceResult(run)?.comparison;
  const actual = textValue(comparison?.actual_scenario ?? 'actual');
  const baseline = textValue(comparison?.baseline_scenario ?? 'baseline');
  const baselineIsBudget = /budget|预算/i.test(baseline);
  const actualIsDefault = /^actual$/i.test(actual) || actual === '实际';
  return {
    caption: baselineIsBudget ? '预算差异桥' : actualIsDefault ? '损益差异桥' : '对照损益差异桥',
    actualLabel: actualIsDefault ? '实际' : actual,
    baselineLabel: baselineIsBudget ? '预算' : baseline === 'baseline' ? '对照' : `对照（${baseline}）`,
  };
}

function FinanceVarianceTable({ run }: { run: AnalysisRun }) {
  const dimensions = financeVarianceDimensionColumns(run);
  const copy = financeVarianceCopy(run);
  const hasAmountChange = new Set(run.result?.columns.map((column) => column.name) ?? []).has('amount_change');
  const rows = (run.result?.rows ?? []).map((row) => ({
    ...Object.fromEntries(dimensions.map((column) => [financeScopeLabels[column.name] ?? column.name, row[column.name]])),
    科目: financeMetricLabel[textValue(row.metric)] ?? textValue(row.metric),
    [copy.actualLabel]: row.actual,
    [copy.baselineLabel]: row.baseline,
    ...(hasAmountChange ? { 科目增减: row.amount_change } : {}),
    差异贡献: row.contribution,
    差异率: formatVarianceRatio(row.ratio),
  }));
  const dimensionHeaders = dimensions.map((column) => ({ name: financeScopeLabels[column.name] ?? column.name, type: column.type }));
  return <section className="analysis-finance-variance">
    <p className="analysis-note">范围：{financeVarianceScope(run)}</p>
    <Table key={`${run.id}:finance-variance`} columns={[
      ...dimensionHeaders, { name: '科目', type: 'VARCHAR' }, { name: copy.actualLabel, type: 'DECIMAL' }, { name: copy.baselineLabel, type: 'DECIMAL' },
      ...(hasAmountChange ? [{ name: '科目增减', type: 'DECIMAL' }] : []), { name: '差异贡献', type: 'DECIMAL' }, { name: '差异率', type: 'VARCHAR' },
    ]} rows={rows} caption={copy.caption} />
    <p className="analysis-note">{run.result!.row_count} 行{run.result!.truncated ? ' · 当前为截断预览' : ''}</p>
    <details className="analysis-details"><summary>原始结果字段 · {run.result!.columns.length} 列</summary>
      <Table key={`${run.id}:raw`} columns={run.result!.columns} rows={run.result!.rows} caption="原始计算结果" />
    </details>
  </section>;
}

function textValue(value: unknown): string {
  if (value == null || value === '') return '—';
  if (typeof value !== 'object') return String(value);
  return Object.entries(value as Record<string, unknown>).map(([key, item]) => `${key}：${textValue(item)}`).join(' · ');
}

function financeCompleteness(value?: string): string {
  return ({
    incomplete: '范围尚未完成：存在需要处理的诊断。',
    not_reconciled: '范围尚未完成：尚未做控制数核对。',
    complete: '范围已完成控制核对。',
  } as Record<string, string>)[value ?? ''] ?? (value ? `范围状态：${value}` : '范围状态尚未记录。');
}

function rowHasSources(row: Record<string, unknown>): boolean {
  const sources = row.source_rows;
  const excluded = row.excluded_source_rows;
  const evidence = row.evidence;
  return Array.isArray(sources) && sources.length > 0
    || Array.isArray(excluded) && excluded.length > 0
    || Boolean(evidence && typeof evidence === 'object' && Object.keys(evidence).length > 0);
}

function sourceLabel(row: Record<string, unknown>, index: number, prefix = '第'): string {
  return `${prefix} ${index + 1} 行 · ${textValue(row.management_account ?? row.account_code ?? row.period ?? row.scenario ?? row.metric ?? row.customer ?? row.item ?? '')}`;
}

function SourceTraceDetails({ run, busy, onDrilldown }: {
  run: AnalysisRun; busy: boolean; onDrilldown?: (run: AnalysisRun, row: number, column?: string, section?: SourceDrilldownSection) => Promise<FinanceDrilldown>;
}) {
  const [target, setTarget] = useState('');
  const [column, setColumn] = useState('');
  const [drilldown, setDrilldown] = useState<FinanceDrilldown | null>(null);
  const [error, setError] = useState('');
  const drilldownRequest = useRef(0);
  const rows = run.result?.rows ?? [];
  const mainSourceRows = rows.map((row, index) => ({ row, index, section: 'rows' as SourceDrilldownSection, value: run.engine === 'structured_aggregate' ? `rows:${index}` : String(index), label: sourceLabel(row, index) })).filter(({ row }) => rowHasSources(row));
  const detailRows = (run.result?.detail_rows ?? []).map((row, index) => ({ row, index, section: 'detail_rows' as SourceDrilldownSection, value: `detail_rows:${index}`, label: sourceLabel(row, index, '明细') })).filter(({ row }) => rowHasSources(row));
  const excludedRows = (run.result?.excluded_detail_rows ?? []).map((row, index) => ({ row, index, section: 'excluded_detail_rows' as SourceDrilldownSection, value: `excluded_detail_rows:${index}`, label: sourceLabel(row, index, '剔除') })).filter(({ row }) => rowHasSources(row));
  const sourceRows = [...mainSourceRows, ...detailRows, ...excludedRows];
  const columns = run.result?.columns.map((item) => item.name).filter((name) => !structuredAggregateHiddenColumns.has(name)) ?? [];
  useEffect(() => {
    drilldownRequest.current += 1;
    setTarget(''); setColumn(''); setDrilldown(null); setError('');
  }, [run.id]);
  async function open() {
    if (!onDrilldown || !target) return;
    const request = ++drilldownRequest.current;
    setError('');
    try {
      const selectedSource = sourceRows.find((item) => item.value === target);
      if (!selectedSource) return;
      const result = await onDrilldown(run, selectedSource.index, column || undefined, run.engine === 'structured_aggregate' ? selectedSource.section : undefined);
      if (request === drilldownRequest.current) setDrilldown(result);
    }
    catch (failure) { if (request === drilldownRequest.current) setError(failure instanceof Error ? failure.message : String(failure)); }
  }
  return <section className="analysis-finance-run" aria-label="结果范围与来源">
    {(run.engine === 'finance' || run.completeness) && <p className="analysis-note">{financeCompleteness(run.completeness)}</p>}
    {run.engine === 'finance' && Array.isArray(run.result?.diagnostics) && run.result.diagnostics.length > 0 && <details className="analysis-details"><summary>诊断 · {run.result.diagnostics.length} 项</summary>
      {run.result.diagnostics.map((item, index) => <p key={index}>{textValue(item)}</p>)}</details>}
    {run.finance_scope && <details className="analysis-details"><summary>运行范围</summary>{Object.entries(run.finance_scope).map(([alias, scope]) =>
      <p key={alias}>{alias}：{textValue(scope)}</p>)}</details>}
    {sourceRows.length > 0 && onDrilldown && <div className="analysis-drilldown">
      <div className="analysis-edit-grid"><label>结果行来源<select className="fnd-field" value={target} onChange={(event) => setTarget(event.target.value)}>
        <option value="">选择一行查看来源</option>{sourceRows.map(({ value, label }) => <option key={value} value={value}>{label}</option>)}
      </select></label><label>来源列（可选）<select className="fnd-field" value={column} onChange={(event) => setColumn(event.target.value)}>
        <option value="">整行来源</option>{columns.map((name) => <option key={name} value={name}>{name}</option>)}</select></label></div>
      <button type="button" className="fnd-button" disabled={busy || !target} onClick={() => void open()}>查看来源行</button>
      {error && <p role="alert" className="analysis-message analysis-message--error">{error}</p>}
      {drilldown && <div className="analysis-drilldown-result"><p className="analysis-note">{drilldown.message} · {drilldown.total} 行来源{drilldown.has_more ? ' · 仍有更多' : ''}</p>
        {drilldown.rows.map((item, index) => <details className="analysis-details" key={index}><summary>来源 {index + 1} · {textValue(item.source)}</summary>
          <p>来源摘要：{item.source_hash}</p><p>凭证明细：{item.voucher_detail_available ? '可用' : '不可用'}</p>
          <pre className="analysis-source-text">{JSON.stringify(item.data, null, 2)}</pre></details>)}</div>}
    </div>}
  </section>;
}
