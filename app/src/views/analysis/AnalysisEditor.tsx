import { useEffect, useState } from 'react';
import type { AnalysisRevision, DatasetSnapshot } from '../../bridge.js';
import { textValue } from './presentation.js';
import { ParameterField } from './ParameterField.js';
import { SearchableSelect, TextField } from '../../components/FinancialControls.js';
import { Button } from '../../components/ui/button.js';
import { Input } from '../../components/ui/input.js';
import { Textarea } from '../../components/ui/textarea.js';
import { datasetOptions, metricLabel } from './shared.js';

export type AnalysisEdit = Pick<AnalysisRevision, 'parameters' | 'assumptions' | 'bindings'> & { sql: string };

const itemLabel = (value: unknown, index: number) => typeof value === 'object' && value !== null
  ? String((value as Record<string, unknown>).label ?? (value as Record<string, unknown>).name ?? `第 ${index + 1} 项`)
  : `第 ${index + 1} 项`;
const itemValue = (value: unknown) => typeof value === 'object' && value !== null
  ? textValue((value as Record<string, unknown>).value ?? (value as Record<string, unknown>).description ?? value)
  : value == null ? '' : String(value);
function editItem(value: unknown, next: string): unknown {
  if (typeof value !== 'object' || value === null) return next;
  const record = value as Record<string, unknown>;
  return { ...record, ['value' in record ? 'value' : 'description']: next };
}

export function AnalysisEditor({ analysis, datasets, busy, edit, onEdit, onRun, onSave, onChat }: {
  analysis: AnalysisRevision; datasets: DatasetSnapshot[]; busy: boolean;
  edit?: AnalysisEdit; onEdit(edit: AnalysisEdit): void;
  onRun(): void; onSave(spec: Record<string, unknown>): void; onChat(spec?: Record<string, unknown>): void;
}) {
  const [sql, setSql] = useState(edit?.sql ?? analysis.sql ?? '');
  const [parameters, setParameters] = useState(edit?.parameters ?? analysis.parameters);
  const [assumptions, setAssumptions] = useState(edit?.assumptions ?? analysis.assumptions);
  const [bindings, setBindings] = useState(edit?.bindings ?? analysis.bindings);
  useEffect(() => { onEdit({ sql, parameters, assumptions, bindings }); }, [sql, parameters, assumptions, bindings, onEdit]);
  function updateParameter(key: string, value: unknown, next: string | boolean | null) {
    setParameters(Array.isArray(parameters)
      ? parameters.map((item, index) => String(index) === key ? typeof next === 'string' ? editItem(value, next) : next : item)
      : { ...parameters, [key]: typeof next === 'string' ? editItem(value, next) : next });
  }
  const calculationChanged = sql !== analysis.sql || JSON.stringify(parameters) !== JSON.stringify(analysis.parameters)
    || JSON.stringify(bindings) !== JSON.stringify(analysis.bindings);
  const changed = calculationChanged || JSON.stringify(assumptions) !== JSON.stringify(analysis.assumptions);
  const spec = () => ({
    question: analysis.question, sql, bindings, parameters, assumptions, parent_id: analysis.id,
    grain: analysis.grain, relationships: analysis.relationships, metrics: analysis.metrics,
    ...(analysis.parameter_metadata == null ? {} : { parameter_metadata: analysis.parameter_metadata }),
    ...(analysis.timeout_seconds == null ? {} : { timeout_seconds: analysis.timeout_seconds }),
    ...(analysis.max_rows == null ? {} : { max_rows: analysis.max_rows }),
    ...(analysis.missing_inputs == null ? {} : { missing_inputs: analysis.missing_inputs }),
    ...(analysis.conversion_rules == null ? {} : { conversion_rules: analysis.conversion_rules }),
  });
  const metadataFor = (key: string) => analysis.parameter_metadata?.find((metadata) => metadata.key.toLowerCase()
    === (Array.isArray(parameters) ? String(Number(key) + 1) : key.toLowerCase()));
  return <div className="analysis-definition">
    {calculationChanged && <p className="analysis-message" role="status">计算口径已修改，当前结果尚未更新。保存新版并重跑后查看新结果。</p>}
    {!calculationChanged && changed && <p className="analysis-note" role="status">假设说明已修改；说明文字本身不会改变计算。可以保存并交给助手继续调整。</p>}
    <details className="analysis-details analysis-definition-fold"><summary>口径与计算定义{changed ? ' · 有未提交修改' : ''}</summary>
    <div className="analysis-logic">{analysis.metrics?.length > 0 && <p>指标：{analysis.metrics.map(metricLabel).join('；')}</p>}
      {analysis.grain?.length > 0 && <p>计算粒度：{analysis.grain.map(textValue).join('；')}</p>}
      {analysis.relationships?.length > 0 && <p>资料关联：{analysis.relationships.map(textValue).join('；')}</p>}</div>
    {Boolean(analysis.missing_inputs?.length) && <p className="analysis-message">待补资料：{analysis.missing_inputs?.join('、')}</p>}
    <section className="analysis-details"><h4>参数、假设与资料</h4>
      <fieldset disabled={busy} className="analysis-fieldset"><div className="analysis-edit-grid">{Object.entries(bindings).map(([alias, id]) =>
        <SearchableSelect key={alias} label={`资料 · ${alias}`} value={id} options={datasetOptions(datasets)}
          onChange={(value) => setBindings({ ...bindings, [alias]: value })} placeholder="搜索资料名称、来源或快照" />)}
        {Object.entries(parameters).filter(([key]) => metadataFor(key)?.role === 'business').map(([key, value]) =>
          <ParameterField key={key} metadata={metadataFor(key)!} value={value} onChange={(next) => updateParameter(key, value, next)} />)}
        {assumptions.map((value, index) => <label key={`assumption-${index}`}>假设 · {itemLabel(value, index)}
          <Input className="min-w-0 flex-1" value={itemValue(value)} onChange={(event) => setAssumptions(assumptions.map((item, at) => at === index ? editItem(item, event.target.value) : item))}  /></label>)}
      </div>
      <details className="analysis-details"><summary>高级参数与公式常量</summary>
        <p className="analysis-note">未标注业务含义的参数按计算定义中的名称或顺序展示。</p>
        <div className="analysis-edit-grid">{Object.entries(parameters).filter(([key]) => metadataFor(key)?.role !== 'business').map(([key, value], index) =>
          <TextField key={key} label={`参数 · ${Array.isArray(parameters) ? itemLabel(value, index) : key}`} value={itemValue(value)}
            onChange={(next) => updateParameter(key, value, next)} />)}</div>
      </details>
      {Array.isArray(parameters) && <Button variant="outline" type="button" onClick={() => setParameters([...parameters, ''])}>添加计算参数</Button>}
      </fieldset>
      <p className="analysis-note">修改后保存并重跑会创建新版本，之前的结果仍可查看。</p>
      <p className="analysis-note">参数会传入计算，假设说明用于记录依据；改变计算口径可请助手更新表达式。</p>
      <Button variant="outline" type="button" disabled={busy} onClick={() => onChat(changed ? spec() : undefined)}>与助手调整口径</Button>
    </section>
    <details className="analysis-details"><summary>高级：查看或编辑计算 SQL</summary>
      <Textarea className="analysis-code" aria-label="计算 SQL" rows={7} value={sql} disabled={busy} onChange={(event) => setSql(event.target.value)} /></details>
    <div className="analysis-actions"><Button type="button" disabled={busy || !sql.trim()} onClick={() => onSave(spec())}>保存新版并重跑</Button><Button variant="outline" type="button" disabled={busy} onClick={onRun}>重跑当前已保存版本</Button></div>
    </details>
  </div>;
}
