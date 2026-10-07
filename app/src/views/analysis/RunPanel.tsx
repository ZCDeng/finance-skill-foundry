import { useEffect, useRef, useState, type ReactNode } from 'react';
import { TriangleAlert, X } from 'lucide-react';
import { when, type AnalysisDraft, type AnalysisRevision, type AnalysisRun, type DatasetSnapshot, type FinanceDrilldown, type ResultContractWarning } from '../../bridge.js';
import { readCopy, writeCopy } from './workingCopy.js';
import { assumptionSummary, parameterSummary, RunStatus, STATUS, Table } from './presentation.js';
import { Button } from '../../components/ui/button.js';
import { Input } from '../../components/ui/input.js';
import { BusinessResultView } from './BusinessResultView.js';
import { RevisionDiff } from './RevisionDiff.js';
import { TechnicalInfo, type TechnicalRow } from './TechnicalInfo.js';
import { businessColumnLabel, runPresentationRole, selectBusinessResult } from './businessResults.js';
import { errorText } from './shared.js';
import { RUN_ROLE_LABELS, scenarioLabel } from './glossary.js';
import { NativeSelect } from '../../components/ui/native-select.js';
import { DisclosureSummary } from '../../components/Disclosure.js';
import { formatPeriod } from '../../lib/period.js';
import { decimalToFixed, groupDigits } from '../../lib/figures.js';

export function RunPanel({ analysis, analyses, runs, drafts = [], datasets, busy, question, versionPicker, versionNote, onPick, onChat, onOpen, onSource, onSaveMethod, onDrilldown, onAdjustScope }: {
  analysis: AnalysisRevision; analyses: AnalysisRevision[]; runs: AnalysisRun[]; drafts?: AnalysisDraft[]; datasets: DatasetSnapshot[]; busy: boolean;
  onPick(id: string): void; onChat(question: string): void; onOpen(run: AnalysisRun, path: string): void;
  onSource(source: DatasetSnapshot): void; onSaveMethod(id: string, name: string): void;
  onDrilldown?(run: AnalysisRun, row: number, column?: string, section?: SourceDrilldownSection): Promise<FinanceDrilldown>;
  /** Opens the finance scope settings, which sit below the result, on the scope this run used. */
  onAdjustScope?(run: AnalysisRun): void;
  /** The task's own name: the result's heading for screen readers, since the page header already shows it. */
  question?: string;
  /** The 分析版本 picker, drawn above the result with 比较版本 beside it. */
  versionPicker?: ReactNode;
  /** One line under the picker, such as which version is on screen. */
  versionNote?: ReactNode;
}) {
  const [selected, setSelected] = useState(() => readCopy<string>(`${analysis.task_id}:run`) ?? '');
  const [evidence, setEvidence] = useState(false);
  const [comparing, setComparing] = useState(false);
  const [comparison, setComparison] = useState('');
  const [methodName, setMethodName] = useState('');
  const evidenceButton = useRef<HTMLButtonElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const relevant = runs.filter((run) => run.analysis_id === analysis.id);
  const selection = selectBusinessResult(analysis, runs, drafts);
  const run = relevant.find((row) => row.id === selected) ?? selection.primary;
  const latest = runs.at(-1);
  const compared = runs.find((row) => row.id === comparison && row.id !== run?.id);
  const assumptions = run?.assumptions ?? analysis.assumptions;
  useEffect(() => { if (evidence) closeButton.current?.focus({ preventScroll: true }); }, [evidence]);
  // Another version from the picker: the comparison and the evidence panel described the one before.
  useEffect(() => { setComparing(false); setEvidence(false); }, [analysis.id]);
  const closeEvidence = () => { setEvidence(false); evidenceButton.current?.focus({ preventScroll: true }); };
  const pick = (next: AnalysisRun) => {
    setSelected(next.id); writeCopy(`${analysis.task_id}:run`, next.id); onPick(next.analysis_id);
    setEvidence(false); setComparing(false);
  };
  // The page header shows the task name in full, so the result's heading is there for screen readers only.
  const heading = question?.trim() || analysis.question;
  // The version's own question is written for the assistant; it stays reachable under 技术信息.
  const technical: TechnicalRow[] = [['版本问题', analysis.question]];
  const compareButton = run && runs.length > 1 ? <Button variant="outline" type="button" aria-expanded={comparing} onClick={() => setComparing(!comparing)}>比较版本</Button> : null;
  // Only the run the latest draft cites is that run; once another is picked the sentence no longer holds.
  const draftReference = Boolean(run && selection.reason === 'draft_reference' && run.id === selection.primary?.id);
  const versionBlock = versionPicker || compareButton || versionNote || draftReference ? <div className="analysis-version">
    {versionPicker || compareButton ? <div className="analysis-version-row">{versionPicker}{compareButton}</div> : null}
    {versionNote ? <p className="analysis-version-note">{versionNote}</p> : null}
    {draftReference && <p className="analysis-version-note">当前结果是最新文稿引用的那次计算；之后的探查和重试保留在「中间步骤」里。</p>}
  </div> : null;
  const resultActions = run ? <div className="analysis-actions">
    <Button variant={runPresentationRole(run) === 'business' ? 'default' : 'outline'} type="button" disabled={busy} onClick={() => onChat(`请把分析「${analysis.question}」的计算 ${run.id} 整理成可编辑的经营分析文稿，区分计算结果、假设与专业判断。`)}>整理成文稿</Button>
    <Button variant="outline" ref={evidenceButton} type="button" aria-expanded={evidence} aria-controls={`analysis-evidence-${analysis.task_id}`} onClick={() => setEvidence(!evidence)}>查看本次计算依据</Button>
    {onAdjustScope && run.engine === 'finance' && <Button variant="outline" type="button" disabled={busy} onClick={() => onAdjustScope(run)}>调整范围</Button>}
  </div> : null;
  return <div className="analysis-result-area" data-evidence-open={evidence || undefined}>
    {!run ? <>{versionBlock}<NotRunYet runs={runs} onPick={(next) => pick(next)} /></> : <article className="analysis-result">
      {versionBlock}
      {latest && latest.id !== run.id && latest.execution_status === 'failed' && <p className="analysis-message analysis-message--error">
        最近一次计算没有完成，当前保留的是上一次成功的结果。<Button variant="outline" type="button" onClick={() => pick(latest)}>查看未完成的计算</Button></p>}
      {comparing && <section className="analysis-comparison" aria-label="版本比较"><div className="analysis-section-heading"><h3>版本比较</h3>
        <Button variant="outline" type="button" onClick={() => setComparing(false)}>关闭比较</Button></div>
        <label className="analysis-select-label">对照结果<NativeSelect value={comparison} onChange={(event) => setComparison(event.target.value)}>
          <option value="">选择一次已保存的计算</option>{[...runs].reverse().filter((row) => row.id !== run.id).map((row) =>
            <option key={row.id} value={row.id}>{analyses.find((item) => item.id === row.analysis_id)?.question ?? '分析'} · 第 {revisionLabel(row, runs)} 次计算 · {when(row.created_at)}</option>)}</NativeSelect></label>
        {compared && <><RevisionDiff current={run} previous={compared} currentRevision={revisionLabel(run, runs)} previousRevision={revisionLabel(compared, runs)} tablesBelow />
        <p className="analysis-note">完整原始结果仍按各次计算自身表格展示；未识别业务身份的行不参与修订差异，未推断业务主键或计算差额。</p><div className="analysis-comparison-grid">{[run, compared].map((row, index) => {
          const definition = analyses.find((item) => item.id === row.analysis_id);
          return <div key={row.id}><h4>{index === 0 ? '当前结果' : '对照结果'} · 第 {revisionLabel(row, runs)} 次计算 · {when(row.created_at)}</h4><RunStatus run={row} />
            <p>参数：{parameterSummary(row.parameters ?? definition?.parameters, row.parameter_metadata ?? definition?.parameter_metadata)}</p>
            <p>假设说明：{assumptionSummary(row.assumptions ?? definition?.assumptions)}</p>
            {row.result?.columns.length ? <Table columns={row.result.columns} rows={row.result.rows} caption={index === 0 ? '当前版本数据' : '对照版本数据'} />
              : <p className="analysis-note">{row.error ? errorText(row.error) : '这次计算没有表格结果。'}</p>}</div>;
        })}</div></>}
      </section>}
      <header className="analysis-result-head"><h3 className="sr-only">{heading}</h3>
        <p className="analysis-note" title={run.id}>{when(run.created_at)} · 第 {revisionLabel(run, runs)} 次计算 · {runRoleLabel(run)}</p><RunStatus run={run} /></header>
      {run.error && <p role="alert" className="analysis-message analysis-message--error">{errorText(run.error)}</p>}
      {isFinanceVarianceRun(run) && <FinanceVarianceHeadline run={run} />}
      {Boolean(run.row_declarations?.warnings?.length) && <ContractWarnings warnings={run.row_declarations!.warnings!} />}
      {run.result && run.result.columns.length > 0 ? <RunResultTable run={run} actions={resultActions} technical={technical} />
        : <>{resultActions}<TechnicalInfo rows={technical}>{run.result?.diagnostics?.length ? <RawDiagnostics items={run.result.diagnostics} /> : null}</TechnicalInfo></>}
      {(run.engine === 'finance' || isStructuredAggregateRun(run)) && <SourceTraceDetails run={run} busy={busy} onDrilldown={onDrilldown} />}
      {run.stdout && <details className="analysis-details"><DisclosureSummary tone="quiet">脚本输出 · {run.stdout.trimEnd().split('\n').length} 行</DisclosureSummary>
        <pre className="analysis-source-text" aria-label="脚本计算输出">{run.stdout}</pre></details>}
      {Boolean(run.outputs?.length) && <div className="analysis-output-list"><h4>生成的文件</h4>{run.outputs?.map((output) => <div key={output.path} className="analysis-actions">
        <span>{output.path}</span><Button variant="outline" type="button" disabled={busy} aria-label={`打开文件 ${output.path}`}
          onClick={() => onOpen(run, output.path)}>打开文件</Button></div>)}</div>}
      {analysis.sql && <details className="analysis-details"><DisclosureSummary>保存这次分析方法</DisclosureSummary><form className="analysis-method-form" onSubmit={(event) => {
        event.preventDefault(); if (methodName.trim()) onSaveMethod(analysis.id, methodName.trim());
      }}><label>方法名称<Input className="min-w-0 flex-1" value={methodName} onChange={(event) => setMethodName(event.target.value)} placeholder={analysis.question} disabled={busy}  /></label>
        <Button variant="outline" type="submit" disabled={busy || !methodName.trim()}>保存为方法</Button></form>
        <p className="analysis-note">保留当前计算方式。下次使用时，重新选择资料和业务参数。</p></details>}
    </article>}
    {run && evidence && <div className="analysis-evidence-anchor"><aside id={`analysis-evidence-${analysis.task_id}`} role="dialog" aria-modal="false" className="analysis-evidence" aria-label="本次计算依据" onKeyDown={(event) => { if (event.key === 'Escape') { event.preventDefault(); closeEvidence(); } }}>
      <div className="analysis-section-heading"><h3>本次计算依据</h3><Button variant="outline" ref={closeButton} type="button" onClick={closeEvidence} aria-label="关闭计算依据"><X size={16} aria-hidden /></Button></div>
      <div className="analysis-evidence-body fnd-scroll-fade">
      <p className="analysis-note">按实际保存的资料版本和这次计算的记录核对。</p>
      <div className="analysis-evidence-sources">{Object.entries(run.input_hashes ?? {}).map(([id, hash]) => {
        // SQL and script runs store alias -> data_hash. Bindings are immutable
        // snapshot IDs; never resolve by display name or the latest upload.
        const datasetId = (run.bindings ?? analysis.bindings)[id] ?? id;
        const source = datasets.find((row) => row.id === datasetId);
        const mismatch = source?.data_hash != null && source.data_hash !== hash;
        return <div key={id}><strong>{source?.name ?? '资料快照'}</strong>{source?.source_name && <p className="analysis-note">{source.source_name}</p>}
          {source && <Button variant="outline" type="button" disabled={busy || mismatch} onClick={() => { if (!mismatch) onSource(source); }}>查看 {source.name}</Button>}
          {mismatch && <p className="analysis-note">资料内容与这次计算用的版本不一致，暂不可预览。</p>}
          <TechnicalInfo rows={[['资料编号', datasetId], ['资料摘要', hash]]} /></div>;
      })}</div>
      <p>参数：{parameterSummary(run.parameters ?? analysis.parameters, run.parameter_metadata ?? analysis.parameter_metadata)}</p>
      {assumptions.length > 0 && <p>假设说明：{assumptionSummary(assumptions)}</p>}
      {run.finance_scope && <details className="analysis-details"><DisclosureSummary>计算范围</DisclosureSummary>{Object.entries(run.finance_scope).map(([alias, scope]) =>
        <p key={alias}>{scenarioLabel(alias)}：{scopeText(scope)}</p>)}</details>}
      <TechnicalInfo rows={[['计算编号', run.id], ['结果摘要', run.output_hash]]} />
    </div></aside></div>}
    <details className="analysis-details analysis-history"><DisclosureSummary>计算历史 · 结果 {selection.businessRuns.length}{selection.failedRuns.length ? ` · 未完成 ${selection.failedRuns.length}` : ''}</DisclosureSummary>
      <HistoryRows rows={[...runs].reverse().filter((row) => runPresentationRole(row) !== 'activity')} runs={runs} analyses={analyses} current={run} onPick={pick} />
      {selection.activityRuns.length > 0 && <details className="analysis-details analysis-history-steps"><DisclosureSummary tone="quiet">中间步骤 · {selection.activityRuns.length}</DisclosureSummary>
        <p className="analysis-note">助手在得到结果前做的探查和重试。它们不是结论，文稿也不会引用它们。</p>
        <HistoryRows rows={[...selection.activityRuns].reverse()} runs={runs} analyses={analyses} current={run} onPick={pick} />
      </details>}
    </details>
  </div>;
}

/**
 * The calculation history as a timeline (after chanhdai.com's work-experience, MIT; components/chanhdai.LICENSE.txt):
 * the calculations of one analysis version sit under its question, joined by a thin line, one dot per
 * calculation and the one on screen in gold. Only the layout is borrowed; each row stays a button that opens it.
 */
/**
 * One group per analysis version, in the order its newest calculation appears; rerunning an older version after a
 * newer one still adds to that version's group rather than starting a second one.
 */
export function historyGroups(rows: AnalysisRun[]): { analysisId: string; rows: AnalysisRun[] }[] {
  const groups = new Map<string, AnalysisRun[]>();
  for (const row of rows) {
    const group = groups.get(row.analysis_id);
    if (group) group.push(row);
    else groups.set(row.analysis_id, [row]);
  }
  return [...groups].map(([analysisId, items]) => ({ analysisId, rows: items }));
}

function HistoryRows({ rows, runs, analyses, current, onPick }: {
  rows: AnalysisRun[]; runs: AnalysisRun[]; analyses: AnalysisRevision[]; current: AnalysisRun | undefined; onPick(run: AnalysisRun): void;
}) {
  return <div className="analysis-history-list analysis-history-timeline">{historyGroups(rows).map((group) => {
    const question = analyses.find((item) => item.id === group.analysisId)?.question ?? '分析';
    return <div key={group.analysisId} className="analysis-history-group" role="group" aria-label={question}>
      <p className="analysis-history-group__question">{question}</p>
      {group.rows.map((row) => <button key={row.id} type="button" className="analysis-history-row" aria-current={row.id === current?.id ? 'true' : undefined} onClick={() => onPick(row)}>
        <span className="analysis-history-row__title">第 {revisionLabel(row, runs)} 次计算</span>
        <span className="analysis-history-row__meta"><span>{runRoleLabel(row)}</span><span>{STATUS[row.execution_status] ?? row.execution_status}</span><time>{when(row.created_at)}</time></span>
      </button>)}
    </div>;
  })}</div>;
}

/** A scope in the words the settings use, one field per phrase. */
function scopeText(scope: unknown): string {
  if (!scope || typeof scope !== 'object' || Array.isArray(scope)) return textValue(scope);
  return Object.entries(scope as Record<string, unknown>).map(([key, item]) => `${financeScopeLabels[key] ?? key} ${key === 'scenario' ? scenarioLabel(textValue(item)) : key === 'period' ? periodText(item) : textValue(item)}`).join(' · ') || '—';
}

/** A period as the result area writes it (2026 年 1–8 月); the stored value stays in the run and in what goes to the assistant. */
function periodText(value: unknown): string {
  if (value == null || value === '') return '—';
  return typeof value === 'object' ? textValue(value) : formatPeriod(value);
}


/**
 * A version with no run yet. The tab counts every result in the task, so say
 * the others exist and offer the newest, rather than read as "nothing here".
 */
function NotRunYet({ runs, onPick }: { runs: AnalysisRun[]; onPick(run: AnalysisRun): void }) {
  const business = runs.filter((row) => runPresentationRole(row) === 'business');
  const newest = business.at(-1);
  return <div className="analysis-actions"><p className="analysis-note">此版本尚未计算。{business.length
    ? `本任务另有 ${business.length} 个结果。` : '确认范围后即可计算。'}</p>
    {newest && <Button variant="outline" type="button" onClick={() => onPick(newest)}>查看最新结果</Button>}</div>;
}

/**
 * Result rows that break the result-row contract. The run still succeeded, so
 * this stays folded to one line above the table; the assistant reads the same
 * messages from the run record.
 */
function ContractWarnings({ warnings }: { warnings: ResultContractWarning[] }) {
  return <details className="analysis-details">
    <DisclosureSummary><TriangleAlert size={15} strokeWidth={1.5} aria-hidden /> {`结果行有 ${warnings.length} 处不合约定`}</DisclosureSummary>
    {warnings.map((warning, index) => <p key={`${warning.code}:${index}`}>{warning.message}</p>)}
  </details>;
}

/** Whether the result is drawn by BusinessResultView, which then also holds the run's diagnostics. */
function rendersBusinessView(run: AnalysisRun): boolean {
  return Boolean(run.result?.columns.length) && !isFinanceVarianceRun(run) && !isStructuredAggregateRun(run) && !isScriptSummaryRun(run)
    && runPresentationRole(run) === 'business' && Boolean(run.result?.rows.length);
}

/** The result, with the run's next steps right after what a manager reads first and one 技术信息 fold. */
function RunResultTable({ run, actions, technical }: { run: AnalysisRun; actions: ReactNode; technical: TechnicalRow[] }) {
  if (isFinanceVarianceRun(run)) return <FinanceVarianceTable run={run} actions={actions} technical={technical} />;
  if (isStructuredAggregateRun(run)) return <StructuredAggregateTable run={run} actions={actions} technical={technical} />;
  if (isScriptSummaryRun(run)) return <ScriptSummaryTable run={run} actions={actions} technical={technical} />;
  if (rendersBusinessView(run)) return <BusinessResultView run={run} actions={actions} technicalRows={technical} diagnostics={run.result?.diagnostics ?? []} />;
  const diagnostics = run.result!.diagnostics ?? [];
  return <><Table key={run.id} columns={run.result!.columns} rows={run.result!.rows} caption="计算结果" />
    <p className="analysis-note">{run.result!.row_count} 行{run.result!.truncated ? ' · 当前为截断预览' : ''}</p>
    {actions}<TechnicalInfo rows={technical}>{diagnostics.length > 0 ? <RawDiagnostics items={diagnostics} /> : null}</TechnicalInfo></>;
}

/** The engine's diagnostics as recorded, for the one 技术信息 fold of a result. */
function RawDiagnostics({ items }: { items: unknown[] }) {
  return <><h4>原始诊断细节 · {items.length} 项</h4>
    {items.map((item, index) => <p key={index}>{textValue(item)}</p>)}</>;
}

function runRoleLabel(run: AnalysisRun): string {
  return RUN_ROLE_LABELS[runPresentationRole(run)];
}

function revisionLabel(run: AnalysisRun, runs: AnalysisRun[]): string {
  return (runs.filter((row) => row.analysis_id === run.analysis_id).findIndex((row) => row.id === run.id) + 1).toString();
}

type SourceDrilldownSection = 'rows' | 'detail_rows' | 'excluded_detail_rows';

const scriptSummaryKeys = ['label', 'value', 'unit'] as const;
const scriptSummaryAllowedColumns = new Set(['label', 'value', 'unit', 'metric', 'wb', 'sheet', 'cell', 'note', 'check']);
const scriptSummaryLabels: Record<(typeof scriptSummaryKeys)[number], string> = {
  label: '项目',
  value: '数值',
  unit: '单位',
};

function columnType(run: AnalysisRun, name: string): string {
  return run.result?.columns.find((column) => column.name === name)?.type ?? 'VARCHAR';
}

function isScriptSummaryRun(run: AnalysisRun): boolean {
  if (run.engine !== 'python' && run.engine !== 'shell') return false;
  const names = run.result?.columns.map((column) => column.name) ?? [];
  if (names.some((name) => !scriptSummaryAllowedColumns.has(name))) return false;
  const set = new Set(names);
  return scriptSummaryKeys.every((name) => set.has(name));
}

function ScriptSummaryTable({ run, actions, technical }: { run: AnalysisRun; actions: ReactNode; technical: TechnicalRow[] }) {
  const result = run.result!;
  const columns = scriptSummaryKeys.map((name) => ({ name: scriptSummaryLabels[name], type: columnType(run, name) }));
  const rows = result.rows.map((row) => Object.fromEntries(scriptSummaryKeys.map((name) => [scriptSummaryLabels[name], row[name]])));
  return <section className="analysis-script-summary">
    <Table key={`${run.id}:summary`} columns={columns} rows={rows} caption="计算结果" />
    <p className="analysis-note">{result.row_count} 行{result.truncated ? ' · 当前为截断预览' : ''}</p>
    {actions}
    <details className="analysis-details"><DisclosureSummary>完整明细 · {result.columns.length} 列</DisclosureSummary>
      <Table key={`${run.id}:full`} columns={result.columns} rows={result.rows} caption="完整明细" />
    </details>
    <TechnicalInfo rows={technical} />
  </section>;
}

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
    return `${metricText}有 ${countText} 条来源金额缺失，${methodText}结果已排除这些缺失来源，请复核结果。`;
  }
  const message = typeof item.message === 'string' ? item.message : '';
  return message || `结构化汇总诊断：${textValue(value)}`;
}

function RawResultDetails({ run, rows }: { run: AnalysisRun; rows: TechnicalRow[] }) {
  const result = run.result!;
  const diagnostics = result.diagnostics ?? [];
  return <TechnicalInfo rows={rows}>
    {diagnostics.length > 0 && <RawDiagnostics items={diagnostics} />}
    <h4>原始结果字段 · {result.columns.length} 列</h4>
    <Table key={`${run.id}:raw`} columns={result.columns} rows={result.rows} caption="原始计算结果" />
  </TechnicalInfo>;
}

function StructuredAggregateTable({ run, actions, technical }: { run: AnalysisRun; actions: ReactNode; technical: TechnicalRow[] }) {
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
    {actions}
    {detailRows.length > 0 && <details className="analysis-details"><DisclosureSummary>来源明细 · {detailRows.length} 行</DisclosureSummary>
      <Table key={`${run.id}:detail`} columns={structuredAggregateColumns(run, detailRows)} rows={structuredAggregateRows(detailRows)} caption="来源明细" />
    </details>}
    {excludedRows.length > 0 && <details className="analysis-details"><DisclosureSummary>剔除明细 · {excludedRows.length} 行</DisclosureSummary>
      <Table key={`${run.id}:excluded`} columns={structuredAggregateColumns(run, excludedRows)} rows={structuredAggregateRows(excludedRows)} caption="剔除明细" />
    </details>}
    <RawResultDetails run={run} rows={technical} />
  </section>;
}

type FinanceVarianceResult = NonNullable<AnalysisRun['result']> & {
  method?: unknown;
  /** The backend's own caveat on what the bridge does and does not show. */
  interpretation?: unknown;
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

const sourceColumnLabels: Record<string, string> = {
  ratio_status: '差异率说明', favorability: '有利或不利', comparison_status: '比较状态',
  management_account: '管理科目', amount: '金额', signed_amount: '带符号金额', numerator: '分子', denominator: '分母',
  display_value: '显示值', row_count: '行数', bucket: '账龄段', customer: '客户', open_amount: '未清金额', invoice_id: '发票号',
  as_of: '截至日期', week: '周', week_start: '周起始日', week_end: '周结束日', opening_cash: '期初现金', receipts: '收款',
  payments: '付款', closing_cash: '期末现金', quantity_contribution: '数量影响', price_contribution: '价格影响',
  interaction: '交互影响', total_variance: '总差异', residual: '残差',
};

/**
 * A result column in the words the tables above use, for choosing which column's sources to open. The option's
 * value stays the column's own name; two columns that read alike keep their names beside the label.
 */
function sourceColumnOptions(run: AnalysisRun, names: string[]): { name: string; label: string }[] {
  const copy = isFinanceVarianceRun(run) ? financeVarianceCopy(run) : null;
  const varianceLabels: Record<string, string> = copy ? { metric: '科目', actual: copy.actualLabel, baseline: copy.baselineLabel } : {};
  const label = (name: string): string => varianceLabels[name] ?? financeScopeLabels[name] ?? sourceColumnLabels[name] ?? businessColumnLabel(name);
  // The engine's exact companions (ratio_exact beside ratio) read as their base column, exactly.
  const labels = names.map((name) => name.endsWith('_exact') && label(name) === name ? `${label(name.slice(0, -'_exact'.length))}（精确值）` : label(name));
  return names.map((name, index) => ({
    name, label: labels.indexOf(labels[index]) !== labels.lastIndexOf(labels[index]) && labels[index] !== name ? `${labels[index]}（${name}）` : labels[index],
  }));
}

function formatVarianceRatio(value: unknown): string {
  if (value == null || value === '') return '—';
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return `${textValue(value)} 倍`;
  if (Math.abs(numeric) > 1000) return `${textValue(value)} 倍`;
  // Two places like every other ratio on the page; the exact decimal, not the float, is what rounds.
  const exact = decimalToFixed(String(value).trim(), 2, 100);
  return exact === String(value).trim() ? `${(numeric * 100).toFixed(2)}%` : `${exact}%`;
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
    return `${label} ${name === 'period' ? periodText(values[0]) : values[0]}`;
  });
  return parts.join(' · ') || '按当前范围汇总';
}

function financeVarianceDimensionColumns(run: AnalysisRun): { name: string; type?: string }[] {
  const rows = run.result?.rows ?? [];
  return run.result?.columns.filter((column) => !financeVarianceReservedColumns.has(column.name) && distinctFinanceValues(rows, column.name).length > 1) ?? [];
}

/** One side of a comparison in words. An estimate says 估算; a label it cannot name stays as written. */
function scenarioWords(label: string, side: 'actual' | 'baseline'): string {
  if (/^actual$/i.test(label) || label === '实际') return '实际';
  const estimate = /estimat|估算|推算|预估/i.test(label);
  if (/budget|预算/i.test(label)) return estimate ? '预算（估算）' : '预算';
  if (/forecast|预测|rolling|滚动/i.test(label)) return '预测';
  if (label === 'baseline') return '对照';
  return side === 'actual' ? label : `对照（${label}）`;
}

function financeVarianceCopy(run: AnalysisRun): { caption: string; baselineLabel: string; actualLabel: string } {
  const comparison = financeVarianceResult(run)?.comparison as Record<string, unknown> | undefined;
  const actual = textValue(comparison?.actual_scenario ?? 'actual');
  const baseline = textValue(comparison?.baseline_scenario ?? 'baseline');
  const period = (filters: unknown) => {
    const value = filters && typeof filters === 'object' ? (filters as Record<string, unknown>).period : undefined;
    return typeof value === 'string' ? value : '';
  };
  const actualPeriod = period(comparison?.actual_filters);
  const baselinePeriod = period(comparison?.baseline_filters);
  // Periods are named only when the two sides differ; the same words on both sides get their codes.
  // Two stored periods that read alike in words (2026-08 and 2026-08:2026-08) keep their stored values.
  const sameWords = periodText(actualPeriod) === periodText(baselinePeriod);
  const withPeriod = (words: string, value: string) => actualPeriod !== baselinePeriod && value ? `${words}（${sameWords ? value : periodText(value)}）` : words;
  const actualLabel = withPeriod(scenarioWords(actual, 'actual'), actualPeriod);
  let baselineLabel = withPeriod(scenarioWords(baseline, 'baseline'), baselinePeriod);
  // Same words on both sides (the same scenario under other filters) must still read as two sides.
  if (actualLabel === baselineLabel) baselineLabel = `对照（${baselineLabel}）`;
  const budget = /budget|预算/i.test(baseline);
  const estimate = /estimat|估算|推算|预估/i.test(baseline);
  return {
    caption: budget ? (estimate ? '估算预算差异桥' : '预算差异桥') : /^actual$/i.test(actual) || actual === '实际' ? '损益差异桥' : '对照损益差异桥',
    actualLabel,
    baselineLabel,
  };
}

function FinanceVarianceTable({ run, actions, technical }: { run: AnalysisRun; actions: ReactNode; technical: TechnicalRow[] }) {
  const dimensions = financeVarianceDimensionColumns(run);
  const copy = financeVarianceCopy(run);
  const hasAmountChange = new Set(run.result?.columns.map((column) => column.name) ?? []).has('amount_change');
  const rows = (run.result?.rows ?? []).map((row) => ({
    ...Object.fromEntries(dimensions.map((column) => [financeScopeLabels[column.name] ?? column.name, column.name === 'period' ? periodText(row.period) : row[column.name]])),
    科目: `${financeMetricLabel[textValue(row.metric)] ?? textValue(row.metric)}${isPartial(row) ? '（缺项）' : ''}`,
    [copy.actualLabel]: row.actual,
    [copy.baselineLabel]: row.baseline,
    ...(hasAmountChange ? { 科目增减: row.amount_change } : {}),
    差异贡献: row.contribution,
    差异率: formatVarianceRatio(row.ratio),
  }));
  const dimensionHeaders = dimensions.map((column) => ({ name: financeScopeLabels[column.name] ?? column.name, type: column.type }));
  return <section className="analysis-finance-variance">
    {actions}
    <p className="analysis-note">范围：{financeVarianceScope(run)}</p>
    <Table key={`${run.id}:finance-variance`} columns={[
      ...dimensionHeaders, { name: '科目', type: 'VARCHAR' }, { name: copy.actualLabel, type: 'DECIMAL' }, { name: copy.baselineLabel, type: 'DECIMAL' },
      ...(hasAmountChange ? [{ name: '科目增减', type: 'DECIMAL' }] : []), { name: '差异贡献', type: 'DECIMAL' }, { name: '差异率', type: 'VARCHAR' },
    ]} rows={rows} caption={copy.caption} />
    <p className="analysis-note">{run.result!.row_count} 行{run.result!.truncated ? ' · 当前为截断预览' : ''}</p>
    <RawResultDetails run={run} rows={technical} />
  </section>;
}

/**
 * The conclusion a manager reads before the bridge table. Every figure is a
 * string the backend computed; this only picks rows and reads the sign, so no
 * amount passes through Number. Groups without a profit change say nothing.
 */
function FinanceVarianceHeadline({ run }: { run: AnalysisRun }) {
  const result = financeVarianceResult(run);
  const dimensions = financeVarianceDimensionColumns(run).map((column) => column.name);
  const copy = financeVarianceCopy(run);
  const groups = new Map<string, Record<string, unknown>[]>();
  for (const row of result?.rows ?? []) {
    const key = JSON.stringify(dimensions.map((name) => row[name] ?? null));
    groups.set(key, [...(groups.get(key) ?? []), row]);
  }
  // Dimension columns skip empty values, so two groups can share a key. One
  // group with two profit rows is that case; say nothing rather than pick one.
  if ([...groups.values()].some((rows) => rows.filter((row) => row.metric === 'profit').length > 1)) return null;
  const lines = [...groups.values()].map((rows) => {
    const profit = rows.find((row) => row.metric === 'profit');
    // A 缺项 line compares an account only one side books; neither it nor the profit built on it is a conclusion.
    const partial = rows.some(isPartial);
    const missing = rows.filter((row) => isPartial(row) && row.metric !== 'profit')
      .map((row) => financeMetricLabel[textValue(row.metric)] ?? textValue(row.metric));
    return {
      label: dimensions.map((name) => name === 'period' ? periodText(rows[0][name]) : textValue(rows[0][name])).join(' · '),
      headline: profit && !partial ? changePhrase(profit, true) : null,
      partial: partial ? (missing.length ? `${missing.join('、')}是缺项，只在一侧有来源行，利润差异不完整，见下表。` : '利润差异是缺项，不完整，见下表。') : null,
      drivers: ['revenue', 'cost', 'expense'].map((metric) => rows.find((row) => row.metric === metric))
        .flatMap((row) => row && !isPartial(row) ? [changePhrase(row, false)] : []).filter((phrase): phrase is string => Boolean(phrase)),
      assumedZero: rows.some((row) => row.comparison_status === 'assumed_zero'),
    };
  }).filter((line) => line.headline || line.partial);
  if (!lines.length) return null;
  const shown = lines.slice(0, 3);
  const interpretation = typeof result?.interpretation === 'string' ? result.interpretation : '';
  return <section className="analysis-headline" aria-label="结论">
    {shown.map((line, index) => <div key={index} className="analysis-headline-line">
      <p className="analysis-headline-text">{line.label ? `${line.label}：` : ''}{line.headline ? `${copy.actualLabel}与${copy.baselineLabel}相比，${line.headline}` : line.partial}</p>
      {line.drivers.length > 0 && <p className="analysis-note">{line.drivers.join(' · ')}</p>}
      {line.assumedZero && <p className="analysis-note">这一组有一侧没有数据，已按 0 计入，差异等于另一侧的全额。</p>}
    </div>)}
    {groups.size > shown.length && <p className="analysis-note">共 {groups.size} 组，其余见下表。</p>}
    {interpretation && <p className="analysis-note">{interpretation}</p>}
  </section>;
}

/** A bridge line whose account has source rows on one side only (缺项), or the profit line built on one. */
function isPartial(row: Record<string, unknown>): boolean {
  return row.comparison_status === 'partial';
}

/**
 * The backend's own phrase when it wrote one with a unit, otherwise the same
 * phrase from the sign of amount_change. Bridges grouped by organization and
 * period carry the unit only in the side scopes, and the backend phrase then
 * has none; a figure without its unit is off by 10,000 between 元 and 万元.
 */
function changePhrase(row: Record<string, unknown>, profit: boolean): string | null {
  const unit = rowUnit(row);
  if (unit === null) return null;
  if (typeof row.amount_change_display === 'string' && row.amount_change_display && typeof row.unit === 'string' && row.unit) return row.amount_change_display;
  const value = row.amount_change ?? (profit ? row.contribution : undefined);
  if (value == null || value === '') return null;
  const text = String(value).trim();
  const amount = text.replace(/^[-+]/, '');
  if (!/^\d*\.?\d+$/.test(amount)) return null;
  const word = /^0*\.?0*$/.test(amount) ? '持平' : text.startsWith('-') ? '减少' : '增加';
  return `${financeMetricLabel[textValue(row.metric)] ?? textValue(row.metric)}${word}${word === '持平' ? '' : ` ${groupDigits(amount)}${unit ? ` ${unit}` : ''}`}`;
}

/** The row's unit, or the one both sides declare; null when the two sides disagree. */
function rowUnit(row: Record<string, unknown>): string | null {
  if (typeof row.unit === 'string' && row.unit) return row.unit;
  // A side scope lists several units when its rows mixed them; that is a conflict too.
  const side = (scope: unknown): string | null => {
    const unit = scope && typeof scope === 'object' ? (scope as Record<string, unknown>).unit : undefined;
    if (Array.isArray(unit)) return null;
    return typeof unit === 'string' ? unit : '';
  };
  const actual = side(row.actual_scope);
  const baseline = side(row.baseline_scope);
  if (actual === null || baseline === null || (actual && baseline && actual !== baseline)) return null;
  return actual || baseline;
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
  // A row named by its period reads it in words; an account name or code is shown as written.
  const byPeriod = row.management_account == null && row.account_code == null && row.period != null;
  return `${prefix} ${index + 1} 行 · ${byPeriod ? periodText(row.period) : textValue(row.management_account ?? row.account_code ?? row.period ?? row.scenario ?? row.metric ?? row.customer ?? row.item ?? '')}`;
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
    catch (failure) { if (request === drilldownRequest.current) setError(errorText(failure)); }
  }
  return <section className="analysis-finance-run" aria-label="结果范围与来源">
    {(run.engine === 'finance' || run.completeness) && <p className="analysis-note">{financeCompleteness(run.completeness)}</p>}
    {run.finance_scope && <details className="analysis-details"><DisclosureSummary>计算范围</DisclosureSummary>{Object.entries(run.finance_scope).map(([alias, scope]) =>
      <p key={alias}>{scenarioLabel(alias)}：{scopeText(scope)}</p>)}</details>}
    {sourceRows.length > 0 && onDrilldown && <div className="analysis-drilldown">
      <div className="analysis-edit-grid"><label>结果行来源<NativeSelect value={target} onChange={(event) => setTarget(event.target.value)}>
        <option value="">选择一行查看来源</option>{sourceRows.map(({ value, label }) => <option key={value} value={value}>{label}</option>)}
      </NativeSelect></label><label>来源列（可选）<NativeSelect value={column} onChange={(event) => setColumn(event.target.value)}>
        <option value="">整行来源</option>{sourceColumnOptions(run, columns).map(({ name, label }) => <option key={name} value={name}>{label}</option>)}</NativeSelect></label></div>
      <Button variant="outline" type="button" disabled={busy || !target} onClick={() => void open()}>查看来源行</Button>
      {error && <p role="alert" className="analysis-message analysis-message--error">{error}</p>}
      {drilldown && <div className="analysis-drilldown-result"><p className="analysis-note">{drilldown.message} · {drilldown.total} 行来源{drilldown.has_more ? ' · 仍有更多' : ''}</p>
        {drilldown.rows.map((item, index) => <details className="analysis-details" key={index}><DisclosureSummary>来源 {index + 1} · {textValue(item.source)}</DisclosureSummary>
          <p>凭证明细：{item.voucher_detail_available ? '可用' : '不可用'}</p>
          <pre className="analysis-source-text">{JSON.stringify(item.data, null, 2)}</pre>
          <TechnicalInfo rows={[['来源摘要', item.source_hash]]} /></details>)}</div>}
    </div>}
  </section>;
}
