import { useEffect, useRef, useState } from 'react';
import { X } from 'lucide-react';
import { shortSha, when, type AnalysisRevision, type AnalysisRun, type DatasetSnapshot } from '../../bridge.js';
import { readCopy, writeCopy } from './workingCopy.js';
import { assumptionSummary, parameterSummary, RunStatus, STATUS, Table } from './presentation.js';

export function RunPanel({ analysis, analyses, runs, datasets, busy, onPick, onChat, onOpen, onSource, onSaveMethod }: {
  analysis: AnalysisRevision; analyses: AnalysisRevision[]; runs: AnalysisRun[]; datasets: DatasetSnapshot[]; busy: boolean;
  onPick(id: string): void; onChat(question: string): void; onOpen(run: AnalysisRun, path: string): void;
  onSource(source: DatasetSnapshot): void; onSaveMethod(id: string, name: string): void;
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
      {run.result && run.result.columns.length > 0 && <><Table key={run.id} columns={run.result.columns} rows={run.result.rows} caption="计算结果" />
        <p className="analysis-note">{run.result.row_count} 行{run.result.truncated ? ' · 当前为截断预览' : ''}</p></>}
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
