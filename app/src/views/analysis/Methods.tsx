import { useEffect, useState } from 'react';
import type { AnalysisMethod, AnalysisState, DatasetSnapshot } from '../../bridge.js';
import { readCopy, writeCopy } from './workingCopy.js';
import { textValue } from './presentation.js';
import { ParameterField } from './ParameterField.js';
import { SearchableSelect, TextField } from '../../components/FinancialControls.js';
import { Button } from '../../components/ui/button.js';
import { datasetOptions } from './shared.js';
import { scenarioLabel } from './glossary.js';
import { DisclosureSummary } from '../../components/Disclosure.js';

export function Methods({ state, busy, onApply }: {
  state: AnalysisState; busy: boolean;
  onApply(methodId: string, bindings: Record<string, string>, parameters: unknown[] | Record<string, unknown>): void;
}) {
  return <div className="fnd-stack"><h3>方法库</h3>
    <p className="analysis-note">{state.methods.length === 0 ? '完成一次分析后，可把有效做法保存在这里。' : '选用已保存的做法，并填写本次资料与参数。'}</p>
    {state.methods.map((method) => <Method key={`${state.task_id}:${method.id}`} taskId={state.task_id} method={method} datasets={state.datasets} busy={busy} onApply={onApply} />)}
  </div>;
}

function Method({ method, datasets, taskId, busy, onApply }: {
  method: AnalysisMethod; datasets: DatasetSnapshot[]; taskId: string; busy: boolean;
  onApply(id: string, bindings: Record<string, string>, parameters: unknown[] | Record<string, unknown>): void;
}) {
  const copyKey = `${taskId}:method:${method.id}`;
  const cached = readCopy<{ bindings: Record<string, string>; parameters: { name: string; value: unknown }[] }>(copyKey);
  const [bindings, setBindings] = useState<Record<string, string>>(cached?.bindings ?? {});
  const contract = method.parameter_contract ?? [];
  const formula = (index: number) => contract[index]?.role === 'formula_constant' && Object.prototype.hasOwnProperty.call(contract[index], 'default');
  const [parameters, setParameters] = useState<{ name: string; value: unknown }[]>(() => cached?.parameters
    ?? contract.map((entry, index) => ({ name: '', value: formula(index) ? entry.default : '' })));
  useEffect(() => { writeCopy(copyKey, { bindings, parameters }); }, [copyKey, bindings, parameters]);
  const aliases = method.inputs ?? Object.keys(method.input_contracts ?? method.bindings ?? {});
  const typeLabel: Record<string, string> = { VARCHAR: '文本', DECIMAL: '金额', DATE: '日期', TIMESTAMP: '日期与时间', INTEGER: '数值', BIGINT: '数值', DOUBLE: '数值', BOOLEAN: '是或否', caller_supplied: '本次取值' };
  const named = parameters.some((parameter) => parameter.name.trim());
  const invalidNames = named && (parameters.some((parameter) => !parameter.name.trim())
    || new Set(parameters.map((parameter) => parameter.name.trim())).size !== parameters.length);
  const metadataAt = (index: number) => contract[index]?.metadata
    ?? method.parameter_metadata?.find((item) => item.key === contract[index]?.parameter);
  const missingValues = contract.some((_, index) => !formula(index)
    && (parameters[index]?.value === '' || parameters[index]?.value == null) && !metadataAt(index)?.constraints?.nullable);
  const update = (index: number, value: unknown) => setParameters(parameters.map((item, at) => at === index ? { ...item, value } : item));
  return <article className="analysis-method"><h3>{method.name}</h3><fieldset className="analysis-fieldset" disabled={busy}><div className="analysis-edit-grid">
    {aliases.map((alias) => <SearchableSelect key={alias} label={`选择 ${scenarioLabel(alias)}资料`} value={bindings[alias] ?? ''}
      options={datasetOptions(datasets)} onChange={(value) => setBindings({ ...bindings, [alias]: value })}
      placeholder="搜索本次资料" allowEmptyLabel="请选择本次资料"
      help={method.input_contracts?.[alias]?.schema?.length ? `所需字段：${method.input_contracts[alias].schema.map((column) => column.name).join('、')}` : undefined} />)}
    </div>
    <div className="analysis-edit-grid">{parameters.map((parameter, index) => {
      const metadata = metadataAt(index);
      return !formula(index) && metadata?.role === 'business' ? <ParameterField key={index} metadata={metadata} value={parameter.value} onChange={(value) => update(index, value)} /> : null;
    })}</div>
    <details className="analysis-details"><DisclosureSummary>高级：参数与计算定义</DisclosureSummary><p className="analysis-note">未提供业务含义的参数按计算定义顺序填写。上次的业务数值不会自动带入。</p>
      {parameters.map((parameter, index) => formula(index) || metadataAt(index)?.role === 'business' ? null : <div className="analysis-edit-grid" key={index}>
        <TextField label={`参数 ${index + 1} 的值${contract[index] ? ` · ${typeLabel[contract[index].type] ?? contract[index].type}` : ''}`}
          value={parameter.value == null ? '' : String(parameter.value)} onChange={(value) => update(index, value)} />
        {contract.length === 0 && <><TextField label={`参数 ${index + 1} 的名称（可选）`} value={parameter.name}
          onChange={(value) => setParameters(parameters.map((item, at) => at === index ? { ...item, name: value } : item))} />
          <Button variant="outline" type="button" onClick={() => setParameters(parameters.filter((_, at) => at !== index))}>移除参数 {index + 1}</Button></>}
      </div>)}
      {contract.length === 0 && <Button variant="outline" type="button" onClick={() => setParameters([...parameters, { name: '', value: '' }])}>添加方法参数</Button>}
      {invalidNames && <p className="analysis-note">按名称填写参数时，每一项都需要有名称，且名称不能重复。</p>}
      {contract.filter((_, index) => formula(index)).map((entry) => <p key={entry.parameter}>公式常量 {entry.parameter}：{textValue(entry.default)}</p>)}
      <pre className="analysis-source-text">{method.sql}</pre></details>
    </fieldset>
    <Button variant="outline" type="button" disabled={busy || missingValues || invalidNames || aliases.some((alias) => !bindings[alias])}
      onClick={() => onApply(method.id, bindings, contract.some((_, index) => formula(index))
        ? Object.fromEntries(contract.map((entry, index) => [entry.parameter, parameters[index]?.value]))
        : named ? Object.fromEntries(parameters.map((parameter) => [parameter.name.trim(), parameter.value])) : parameters.map((parameter) => parameter.value))}>用这些资料创建分析</Button></article>;
}
