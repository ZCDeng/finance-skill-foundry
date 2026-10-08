import { useEffect, useMemo, useRef, useState } from 'react';
import { bridge, when, type AnalysisRun, type Answer } from '../../bridge.js';
import { Button } from '../../components/ui/button.js';
import { Input } from '../../components/ui/input.js';
import { Textarea } from '../../components/ui/textarea.js';
import { normalizeReportVisual, renderReportVisualSvg, type ReportVisual } from '../../../electron/reports/visuals.js';
import { errorText, unwrap } from './shared.js';
import { NativeSelect } from '../../components/ui/native-select.js';
import { Checkbox } from '../../components/ui/checkbox.js';
import { DisclosureSummary } from '../../components/Disclosure.js';
import { Loading, SkeletonRows } from '../../components/Loading.js';

type ChartSeries = { columns: unknown[]; rows: Record<string, unknown>[] };
type ChartRecord = { id: string; label?: string; run_id?: string; snapshot_hash?: string; series?: ChartSeries; report_series?: ChartSeries };
type Step = { label: string; detail: string; connector: string };
const blankSteps = (): Step[] => [{ label: '', detail: '', connector: '' }, { label: '', detail: '', connector: '' }];
const columnsOf = (chart: ChartRecord | null): string[] => (chart?.series?.columns ?? []).flatMap((column) => {
  const name = typeof column === 'string' ? column : column && typeof column === 'object' && 'name' in column ? String(column.name) : '';
  return name ? [name] : [];
});

export function ReportVisualComposer({ taskId, runs, initial, onApply, onCancel }: {
  taskId: string; runs: AnalysisRun[]; initial?: ReportVisual; onApply(visual: ReportVisual): void; onCancel(): void;
}) {
  const [kind, setKind] = useState<ReportVisual['kind']>(initial?.kind ?? 'bar');
  const [title, setTitle] = useState(initial?.title ?? '');
  const [takeaway, setTakeaway] = useState(initial?.takeaway ?? '');
  const [sourceLabel, setSourceLabel] = useState(initial?.kind === 'flow' ? initial.source_label : '作者分析');
  const [steps, setSteps] = useState<Step[]>(initial?.kind === 'flow' ? initial.steps.map((step) => ({ ...step })) : blankSteps);
  const numeric = initial && initial.kind !== 'flow' ? initial : undefined;
  const [selection, setSelection] = useState(numeric ? `chart:${numeric.chart_id}` : '');
  const [category, setCategory] = useState(numeric?.category ?? '');
  const [values, setValues] = useState<string[]>(numeric?.value_columns ?? []);
  const [unit, setUnit] = useState(numeric?.unit ?? '');
  const [charts, setCharts] = useState<ChartRecord[]>([]);
  const [opened, setOpened] = useState<ChartRecord | null>(numeric ? { id: numeric.chart_id, label: numeric.source_label, run_id: numeric.run_id, snapshot_hash: numeric.snapshot_hash, series: numeric.series } : null);
  const [loadingList, setLoadingList] = useState(true);
  const [loadingSource, setLoadingSource] = useState(false);
  const [error, setError] = useState('');
  const request = useRef(0);
  const currentTask = useRef(taskId);
  currentTask.current = taskId;
  const mountedTask = useRef(taskId);
  const successfulRuns = runs.filter((run) => ['succeeded', 'success'].includes(run.execution_status));

  useEffect(() => {
    let cancelled = false;
    if (mountedTask.current !== taskId) {
      mountedTask.current = taskId;
      request.current += 1;
      setCharts([]); setOpened(null); setSelection(''); setCategory(''); setValues([]); setUnit('');
      setTitle(''); setTakeaway(''); setKind('bar'); setSteps(blankSteps()); setSourceLabel('作者分析'); setLoadingSource(false);
    }
    setLoadingList(true); setError('');
    const api = bridge();
    if (!api?.financeCall) { setLoadingList(false); return; }
    void api.financeCall(taskId, 'chart-deliverable-list', {}).then((answer) => {
      if (cancelled || currentTask.current !== taskId) return;
      const value = unwrap(answer as Answer<{ charts?: ChartRecord[] }>);
      setCharts(value.charts ?? []);
    }).catch((failure) => {
      if (!cancelled && currentTask.current === taskId) setError(errorText(failure));
    }).finally(() => {
      if (!cancelled && currentTask.current === taskId) setLoadingList(false);
    });
    return () => { cancelled = true; request.current += 1; };
  }, [taskId]);

  async function selectSource(next: string) {
    const activeRequest = ++request.current;
    setSelection(next); setOpened(null); setCategory(''); setValues([]); setError('');
    if (!next) { setLoadingSource(false); return; }
    const api = bridge();
    if (!api?.financeCall) { setError('暂时无法读取计算结果。'); return; }
    setLoadingSource(true);
    const current = () => activeRequest === request.current && currentTask.current === taskId;
    try {
      const [type, id] = next.split(':');
      const saved = type === 'run' ? unwrap(await api.financeCall(taskId, 'chart-deliverable-save', { run_id: id }) as Answer<ChartRecord>) : { id };
      if (!current()) return;
      const record = unwrap(await api.financeCall(taskId, 'chart-deliverable-open', { id: saved.id }) as Answer<ChartRecord>);
      if (current()) setOpened({ ...record, series: record.report_series ?? record.series });
    } catch (failure) { if (current()) setError(errorText(failure)); }
    finally { if (current()) setLoadingSource(false); }
  }

  const columns = columnsOf(opened);
  const preview = useMemo(() => {
    try {
      const visual = normalizeReportVisual(kind === 'flow' ? { version: 1, kind, title, takeaway, source_label: sourceLabel, steps } : {
        version: 1, kind, title, takeaway, chart_id: opened?.id, category, value_columns: values, unit,
        run_id: opened?.run_id, snapshot_hash: opened?.snapshot_hash, source_label: opened?.label, series: opened?.series,
      });
      return { visual, svg: renderReportVisualSvg(visual), error: '' };
    } catch (failure) { return { visual: undefined, svg: '', error: errorText(failure) }; }
  }, [kind, title, takeaway, sourceLabel, steps, opened, category, values, unit]);
  const readyForValidation = Boolean(title.trim() && (kind === 'flow' ? steps.every((step) => step.label.trim()) : opened && category && values.length && unit.trim()));
  const empty = !loadingList && !charts.length && !successfulRuns.length && !opened;
  function updateStep(index: number, key: keyof Step, value: string) { setSteps((previous) => previous.map((step, at) => at === index ? { ...step, [key]: value } : step)); }
  function removeStep(index: number) { setSteps((previous) => previous.filter((_, at) => at !== index).map((step, at, all) => ({ ...step, connector: at === all.length - 1 ? '' : step.connector }))); }

  return <section className="report-visual-composer" aria-label={initial ? '编辑文稿图表' : '插入文稿图表'} onKeyDown={(event) => { if (event.key === 'Escape') { event.stopPropagation(); onCancel(); } }}>
    <div className="report-visual-composer__heading"><div><h3>{initial ? '编辑图表' : '插入图表'}</h3><p>先选适合问题的图型，再核对数据、单位和图题。</p></div><Button type="button" variant="ghost" onClick={onCancel}>取消图表</Button></div>
    <div className="report-visual-composer__fields">
      <label>图表类型<NativeSelect aria-label="图表类型" value={kind} onChange={(event) => setKind(event.target.value as ReportVisual['kind'])}><option value="bar">条形图 · 比较大小</option><option value="line">折线图 · 展示趋势</option><option value="flow">流程图 · 解释关系</option></NativeSelect></label>
      <label>图表标题<Input aria-label="图表标题" maxLength={160} value={title} onChange={(event) => setTitle(event.target.value)} placeholder="用标题说明要比较或解释的问题" /></label>
      <label className="report-visual-composer__wide">结论（可选）<Textarea aria-label="图表结论" rows={2} maxLength={300} value={takeaway} onChange={(event) => setTakeaway(event.target.value)} placeholder="写下经核对后能够支持的结论" /></label>
      {kind !== 'flow' ? <>
        <label className="report-visual-composer__wide">图表数据<NativeSelect aria-label="图表数据" value={selection} onChange={(event) => void selectSource(event.target.value)}><option value="">选择已有计算结果或归档图</option>
          {numeric && !charts.some((row) => row.id === numeric.chart_id) && <option value={`chart:${numeric.chart_id}`}>{numeric.source_label || '文稿中的结果图'}</option>}
          {charts.length > 0 && <optgroup label="已归档图">{charts.map((row, index) => <option key={row.id} value={`chart:${row.id}`}>{row.label || `归档图 ${index + 1}`}</option>)}</optgroup>}
          {successfulRuns.length > 0 && <optgroup label="已完成计算">{successfulRuns.map((run, index) => <option key={run.id} value={`run:${run.id}`}>第 {index + 1} 次计算 · {when(run.created_at)}</option>)}</optgroup>}
        </NativeSelect></label>
        {loadingList && <Loading label="正在读取归档图…" className="report-visual-composer__wide"><SkeletonRows rows={1} meta={false} /></Loading>}
        {empty && <p className="report-visual-composer__wide">还没有可用的计算结果。先完成一次计算后可制作数值图，也可以选择流程图解释分析步骤。</p>}
        {loadingSource && <Loading label="正在读取结果数据…" className="report-visual-composer__wide"><SkeletonRows rows={2} meta={false} /></Loading>}
        {opened && <>
          <label>类别列<NativeSelect aria-label="类别列" value={category} onChange={(event) => { setCategory(event.target.value); setValues((previous) => previous.filter((name) => name !== event.target.value)); }}><option value="">选择类别列</option>{columns.map((name) => <option key={name} value={name}>{name}</option>)}</NativeSelect></label>
          <label>单位<Input aria-label="图表单位" value={unit} maxLength={40} onChange={(event) => setUnit(event.target.value)} placeholder="例如：万元、%、天" /></label>
          <fieldset className="report-visual-composer__series report-visual-composer__wide"><legend>数值列（最多 3 列，单位必须一致）</legend>{columns.filter((name) => name !== category).map((name) => <label key={name}><Checkbox aria-label={`数值列 ${name}`} checked={values.includes(name)} disabled={!values.includes(name) && values.length >= 3} onCheckedChange={(state) => setValues((previous) => state === true ? [...previous, name] : previous.filter((value) => value !== name))} />{name}</label>)}</fieldset>
          <p className="report-visual-composer__wide analysis-note">单位仅作展示，不换算数值。条形图最多 12 条数值（类别数×数值列数），折线图最多 24 个点；文字过密时请缩短说明或拆图。折线按结果中的顺序连接。</p>
        </>}
      </> : <>
        <p className="report-visual-composer__wide analysis-note">流程图表达作者的分析与关系，不作为计算事实。</p>
        <label className="report-visual-composer__wide">来源说明<Input aria-label="流程来源说明" value={sourceLabel} maxLength={200} onChange={(event) => setSourceLabel(event.target.value)} /></label>
        <ol className="report-visual-composer__steps report-visual-composer__wide">{steps.map((step, index) => <li key={index}><div className="report-visual-composer__step-heading"><strong>步骤 {index + 1}</strong>{steps.length > 2 && <Button type="button" variant="ghost" aria-label={`移除步骤 ${index + 1}`} onClick={() => removeStep(index)}>移除</Button>}</div><label>步骤名称<Input aria-label={`步骤 ${index + 1}`} value={step.label} maxLength={60} onChange={(event) => updateStep(index, 'label', event.target.value)} /></label><label>补充说明<Textarea aria-label={`步骤说明 ${index + 1}`} rows={2} value={step.detail} maxLength={140} onChange={(event) => updateStep(index, 'detail', event.target.value)} /></label>{index < steps.length - 1 && <label>与下一步的关系<Input aria-label={`关系 ${index + 1}`} value={step.connector} maxLength={40} onChange={(event) => updateStep(index, 'connector', event.target.value)} placeholder="例如：复核通过后" /></label>}</li>)}</ol>
        <div className="report-visual-composer__wide"><Button type="button" variant="outline" disabled={steps.length >= 6} onClick={() => setSteps((previous) => [...previous, { label: '', detail: '', connector: '' }])}>增加步骤</Button></div>
      </>}
    </div>
    {error && <p role="alert" className="analysis-message analysis-message--error">{error}</p>}
    {readyForValidation && preview.error && <p role="alert" className="analysis-message analysis-message--error">{preview.error}</p>}
    <div className="report-visual-preview" aria-label="图表预览">{preview.svg ? <div dangerouslySetInnerHTML={{ __html: preview.svg }} /> : <p className="analysis-note">填好图题、{kind === 'flow' ? '步骤' : '列和单位'}后显示完整预览。</p>}</div>
    {kind !== 'flow' && opened?.series && <details className="report-visual-data"><DisclosureSummary tone="quiet">核对原始数据 · {opened.series.rows.length} 行</DisclosureSummary><div className="fnd-tablewrap" tabIndex={0} role="region" aria-label="图表原始数据"><table className="fnd-table"><thead><tr>{columns.map((name) => <th key={name} scope="col">{name}</th>)}</tr></thead><tbody>{opened.series.rows.map((row, index) => <tr key={index}>{columns.map((name) => <td key={name}>{row[name] == null ? '缺失' : String(row[name])}</td>)}</tr>)}</tbody></table></div></details>}
    <div className="report-visual-composer__actions"><Button type="button" disabled={!preview.visual || (kind !== 'flow' && loadingSource)} onClick={() => { if (preview.visual) onApply(preview.visual); }}>{initial ? '更新图表' : '插入文稿'}</Button></div>
  </section>;
}
