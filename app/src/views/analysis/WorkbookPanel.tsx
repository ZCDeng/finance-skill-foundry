import { useEffect, useRef, useState } from 'react';
import { FileSpreadsheet } from 'lucide-react';
import { bridge, type AnalysisRun, type DatasetSnapshot } from '../../bridge.js';
import { Table, textValue } from './presentation.js';
import { WaitOrb } from '../../components/WaitOrb.js';
import { FieldShell, SearchableSelect, TextField } from '../../components/FinancialControls.js';
import { Button } from '../../components/ui/button.js';
import { Textarea } from '../../components/ui/textarea.js';
import { datasetOptions, runOptions, unwrap, errorText } from './shared.js';
import { NativeSelect } from '../../components/ui/native-select.js';

const fileDatasets = (datasets: DatasetSnapshot[]) => datasets.filter((source) =>
  String(source.source_name ?? source.filename ?? '').toLowerCase().endsWith('.xlsx')
  || source.metadata?.source_file === 'source.xlsx');

export function WorkbookPanel({ taskId, datasets, runs, busy, contextId }: { taskId: string; datasets: DatasetSnapshot[]; runs: AnalysisRun[]; busy: boolean; contextId?: string }) {
  const xlsx = fileDatasets(datasets);
  const [datasetId, setDatasetId] = useState(xlsx[0]?.id ?? '');
  const [inspection, setInspection] = useState<Record<string, unknown> | null>(null);
  const [inspecting, setInspecting] = useState(false);
  const [inspectionError, setInspectionError] = useState('');
  const [bindingId, setBindingId] = useState('');
  const [sourceKind, setSourceKind] = useState<'table' | 'named_range' | 'range'>('table');
  const [sourceName, setSourceName] = useState('');
  const [sheet, setSheet] = useState('');
  const [range, setRange] = useState('');
  const [role, setRole] = useState<'input' | 'output'>('input');
  const [fields, setFields] = useState('[{"name":"amount","policy":"amount"}]');
  const [writes, setWrites] = useState('[{"row":1,"field":"amount","value":"0.00"}]');
  const [runId, setRunId] = useState('');
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const [resolutions, setResolutions] = useState<Record<string, 'keep' | 'apply'>>({});
  const [readResult, setReadResult] = useState<Record<string, unknown> | null>(null);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  // What the panel is doing, in words; every action below waits on the foundry.
  const [running, setRunning] = useState('');
  const locked = busy || Boolean(running);
  const track = (label: string, work: () => Promise<void>) => {
    if (running) return;
    setRunning(label);
    void work().finally(() => setRunning(''));
  };
  const workbookRequest = useRef(0);
  const workbookPreviewMounted = useRef(false);
  const workbookDatasetMounted = useRef(false);
  useEffect(() => { setDatasetId((value) => value || xlsx[0]?.id || ''); }, [xlsx]);
  useEffect(() => {
    if (!workbookPreviewMounted.current) { workbookPreviewMounted.current = true; return; }
    workbookRequest.current += 1; setPreview(null); setResolutions({});
  }, [datasetId, bindingId, writes, runId]);
  useEffect(() => {
    if (!workbookDatasetMounted.current) { workbookDatasetMounted.current = true; return; }
    workbookRequest.current += 1; setInspection(null); setInspectionError(''); setReadResult(null);
  }, [datasetId]);
  if (!xlsx.length) return null;
  const sourceSpec = () => sourceKind === 'range' ? { kind: 'range', sheet, range } : { kind: sourceKind, name: sourceName };
  async function call(command: 'workbook-inspect' | 'workbook-bind' | 'workbook-read' | 'workbook-preview' | 'workbook-apply' | 'analysis-circle-select', spec: Record<string, unknown>) {
    const api = bridge(); if (!api?.financeCall) throw new Error('此版本暂不支持 Excel 协作。');
    return unwrap(await api.financeCall(taskId, command, spec));
  }
  async function inspect() {
    const request = ++workbookRequest.current;
    try {
      setError(''); setInspectionError(''); setMessage(''); setInspecting(true);
      const result = await call('workbook-inspect', { dataset_id: datasetId });
      if (request !== workbookRequest.current) return;
      setInspection(result); setMessage('已读取工作簿结构。');
    } catch (failure) {
      if (request === workbookRequest.current) {
        const text = errorText(failure);
        setInspectionError(text);
        setError(text);
      }
    } finally {
      if (request === workbookRequest.current) setInspecting(false);
    }
  }
  async function bind() {
    const request = ++workbookRequest.current;
    try {
      setError(''); setMessage('');
      const parsed = JSON.parse(fields);
      if (!Array.isArray(parsed)) throw new Error('字段 JSON 需要是数组。');
      const result = await call('workbook-bind', { dataset_id: datasetId, source: sourceSpec(), fields: parsed, role, writable: role === 'output', header: true });
      if (request !== workbookRequest.current) return;
      setBindingId(String(result.id ?? '')); setPreview(null); setResolutions({}); setMessage('已保存 Excel 区域绑定。');
    } catch (failure) { if (request === workbookRequest.current) setError(errorText(failure)); }
  }
  async function circleSelect() {
    try {
      setError(''); setMessage('');
      if (!contextId) throw new Error('请先保存财务范围。');
      await call('analysis-circle-select', { kind: 'workbook', binding_id: bindingId, range: range || sourceName || 'A:A', instruction: '改成开票口径', context_id: contextId });
      setMessage('已按圈选生成开票口径修订。');
    } catch (failure) { setError(errorText(failure)); }
  }
  async function read() {
    const request = ++workbookRequest.current;
    try {
      setError(''); setMessage('');
      const result = await call('workbook-read', { binding_id: bindingId, dataset_id: datasetId });
      if (request !== workbookRequest.current) return;
      setReadResult(result); setMessage('已读取绑定区域。');
    } catch (failure) { if (request === workbookRequest.current) setError(errorText(failure)); }
  }
  async function previewPatch() {
    const request = ++workbookRequest.current;
    try {
      setError(''); setMessage('');
      const parsed = JSON.parse(writes);
      if (!Array.isArray(parsed)) throw new Error('写入 JSON 需要是数组。');
      const result = await call('workbook-preview', { binding_id: bindingId, dataset_id: datasetId, writes: parsed, ...(runId ? { run_id: runId } : {}) });
      if (request !== workbookRequest.current) return;
      const patch = result.patch as Record<string, unknown> | undefined;
      const nextCells = Array.isArray(patch?.cells) ? patch.cells as Record<string, unknown>[] : [];
      setResolutions(Object.fromEntries(nextCells
        .filter((cell) => cell.conflict === true && cell.cell)
        .map((cell) => [String(cell.cell), 'keep'])));
      setPreview(result); setMessage('已生成写回预览。冲突单元格需要选择保留或应用后再生成文件。');
    } catch (failure) { if (request === workbookRequest.current) setError(errorText(failure)); }
  }
  async function applyPatch() {
    try {
      setError(''); setMessage('');
      if (!preview?.patch_id) throw new Error('请先生成写回预览。');
      const result = await call('workbook-apply', { patch_id: preview.patch_id, resolutions });
      setMessage(`已生成协作工作簿：${textValue(result.artifact_path ?? result.path ?? result.id)}`);
    } catch (failure) { setError(errorText(failure)); }
  }
  const sheetNames = Array.isArray(inspection?.sheet_names) ? inspection.sheet_names.map(String) : [];
  const tables = Array.isArray(inspection?.tables) ? inspection.tables.map(String) : [];
  const names = Array.isArray(inspection?.named_ranges) ? inspection.named_ranges.map(String) : [];
  const previewPatchValue = preview?.patch as Record<string, unknown> | undefined;
  const cells = Array.isArray(previewPatchValue?.cells) ? previewPatchValue.cells as Record<string, unknown>[] : [];
  const conflictCells = cells.filter((cell) => cell.conflict === true && cell.cell);
  return <section className="analysis-workbook-panel" aria-label="Excel 协作">
    <div className="analysis-section-heading"><div><h3>Excel 协作</h3><p className="analysis-note">在任务快照上检查表格、绑定区域，预览写回，再生成新的工作簿文件。</p></div></div>
    <fieldset className="analysis-fieldset" disabled={locked}><div className="analysis-edit-grid">
      <SearchableSelect label="工作簿资料" value={datasetId} options={datasetOptions(xlsx)} onChange={setDatasetId} placeholder="搜索工作簿名或快照" />
      <TextField label="绑定编号" value={bindingId} onChange={setBindingId} placeholder="读取、预览或应用已有绑定" />
      <FieldShell label="区域类型"><NativeSelect aria-label="区域类型" value={sourceKind} onChange={(event) => setSourceKind(event.target.value as typeof sourceKind)}>
        <option value="table">表格</option><option value="named_range">命名区域</option><option value="range">工作表范围</option></NativeSelect></FieldShell>
      {sourceKind === 'range' ? <><SearchableSelect label="工作表" value={sheet} options={sheetNames.map((name) => ({ value: name, label: name }))}
          onChange={setSheet} placeholder={sheetNames.length ? '搜索工作表' : '先检查结构'} allowEmptyLabel="暂不选择"
          loading={inspecting} loadError={inspectionError} unconfigured={!inspection && !inspectionError && !inspecting}
          unconfiguredLabel="请先点击“检查结构”，读取工作表后再选择。" />
        <TextField label="范围" value={range} placeholder="A1:D20" onChange={setRange} /></>
        : <TextField label={sourceKind === 'table' ? '表格名称' : '命名区域'} value={sourceName} onChange={setSourceName} />}
      <FieldShell label="用途"><NativeSelect aria-label="用途" value={role} onChange={(event) => setRole(event.target.value as typeof role)}>
        <option value="input">读取输入</option><option value="output">写回输出</option></NativeSelect></FieldShell>
      <SearchableSelect label="校验计算（可选）" value={runId} options={runOptions(runs)} onChange={setRunId}
        placeholder="搜索计算时间" allowEmptyLabel="经理直接写入" />
    </div>
    <details className="analysis-details"><summary>高级：字段与写入 JSON</summary><div className="analysis-edit-grid">
      <label>字段数组<Textarea className="analysis-code" rows={4} value={fields} onChange={(event) => setFields(event.target.value)} /></label>
      <label>写入数组<Textarea className="analysis-code" rows={4} value={writes} onChange={(event) => setWrites(event.target.value)} /></label>
    </div></details></fieldset>
    <p className="analysis-note">绑定基准由绑定记录保存；读取和写回预览使用当前选择的目标资料。</p>
    <div className="analysis-actions">
      <Button variant="outline" type="button" disabled={locked || !datasetId} onClick={() => track('正在检查工作簿结构…', inspect)}><FileSpreadsheet size={14} aria-hidden />检查结构</Button>
      <Button variant="outline" type="button" disabled={locked || !datasetId || (sourceKind === 'range' ? !sheet || !range : !sourceName)} onClick={() => track('正在保存绑定…', bind)}>保存绑定</Button>
      <Button variant="outline" type="button" disabled={locked || !bindingId || !contextId} onClick={() => track('正在按圈选生成开票口径修订…', circleSelect)}>改成开票口径</Button>
      <Button variant="outline" type="button" disabled={locked || !bindingId} onClick={() => track('正在读取绑定区域…', read)}>读取区域</Button>
      <Button variant="outline" type="button" disabled={locked || !bindingId} onClick={() => track('正在生成写回预览…', previewPatch)}>预览写回</Button>
      <Button type="button" disabled={locked || !preview?.patch_id} onClick={() => track('正在生成工作簿…', applyPatch)}>生成工作簿</Button>
      {running && <span role="status" className="analysis-note"><WaitOrb state="working" />{running}</span>}
    </div>
    {inspection && <details className="analysis-details" open><summary>工作簿结构</summary>
      <p>工作表：{sheetNames.join('、') || '未读取'}</p><p>表格：{tables.join('、') || '无'}</p><p>命名区域：{names.join('、') || '无'}</p>
      {Array.isArray(inspection.unsupported_features) && inspection.unsupported_features.length > 0 && <p>需生成独立结果工作簿：{inspection.unsupported_features.map(textValue).join('、')}</p>}
    </details>}
    {readResult && Array.isArray(readResult.rows) && <Table columns={Object.keys(readResult.rows[0] ?? {}).map((name) => ({ name, type: 'VARCHAR' }))} rows={readResult.rows as Record<string, unknown>[]} caption="绑定区域读取结果" />}
    {cells.length > 0 && <Table columns={[{ name: '单元格', type: 'VARCHAR' }, { name: '字段', type: 'VARCHAR' }, { name: '原值', type: 'VARCHAR' }, { name: '新值', type: 'VARCHAR' }, { name: '冲突', type: 'VARCHAR' }]}
      rows={cells.map((cell) => ({ 单元格: cell.cell, 字段: cell.field, 原值: cell.old_value, 新值: cell.new_value, 冲突: cell.conflict === true ? '是' : '否' }))} caption="写回预览" />}
    {conflictCells.length > 0 && <div className="analysis-workbook-conflicts" aria-label="写回冲突处理">
      <strong>冲突处理</strong>
      {conflictCells.map((cell) => {
        const cellId = String(cell.cell);
        return <label key={cellId}>{cellId} · 原值 {textValue(cell.old_value)} → 新值 {textValue(cell.new_value)}
          <NativeSelect value={resolutions[cellId] ?? 'keep'} onChange={(event) => setResolutions((value) => ({ ...value, [cellId]: event.target.value as 'keep' | 'apply' }))}>
            <option value="keep">保留原单元格</option><option value="apply">应用新结果</option>
          </NativeSelect></label>;
      })}
    </div>}
    {message && <p role="status" className="analysis-message">{message}</p>}
    {error && <p role="alert" className="analysis-message analysis-message--error">{error}</p>}
  </section>;
}
