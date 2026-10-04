import { useEffect, useMemo, useRef, useState } from 'react';
import { Ban, ClipboardCopy, Download, Equal, FileSearch, FileSpreadsheet, Hand, ListPlus, PenLine, Plus, Save, Trash2, TriangleAlert } from 'lucide-react';
import { bridge, type AnalysisRun, type Answer, type DatasetSnapshot } from '../../bridge.js';
import { WaitOrb } from '../../components/WaitOrb.js';
import { AccountingPeriodInput, SearchableSelect, TextField, type SelectOption } from '../../components/FinancialControls.js';
import { Badge } from '../../components/ui/badge.js';
import { Button } from '../../components/ui/button.js';
import { HelpLink } from '../guide/GuideHub.js';
import { textValue } from './presentation.js';
import { datasetOptions, errorText, runOptions, unwrap } from './shared.js';

type SourceKind = 'cell' | 'sum' | 'run' | 'value';
type Mapping = {
  key: number; target: string; kind: SourceKind;
  datasetId: string; range: string; runId: string; row: string; column: string; value: string; note: string;
  /** From a template: last month's file name and typed value, shown as reminders only. */
  hint?: string; lastValue?: string;
};
type PlanRow = {
  index: number; target: string; status: 'write' | 'blocked' | 'unchanged'; reason_code?: string; reason?: string;
  old_value?: unknown; new_value?: unknown; cell_type?: string | null; notes?: string[]; source?: Record<string, unknown>;
};
type TitleHint = { sheet: string; cell: string; target: string; text: string; period: string; mapped: boolean };
type ChangeLog = { tsv: string; markdown: string };
type Plan = {
  plan_id: string; period: string; workbook_supported: boolean; unsupported_features?: string[];
  rows?: PlanRow[]; counts?: { write: number; blocked: number; unchanged: number }; title_hints?: TitleHint[]; change_log?: ChangeLog;
};
type Applied = { run_id: string; output_name?: string; counts?: Plan['counts']; formula_cache_cleared?: boolean; change_log?: ChangeLog };
type TemplateSource = { kind: 'dataset'; sheet: string; range: string; hint?: string } | { kind: 'run'; row: number; column: string } | { kind: 'value'; note?: string; last_value?: string };
type Template = { id: string; name: string; mapping_count?: number; mappings?: { target: { sheet: string; cell: string }; source: TemplateSource }[] };

const KIND_OPTIONS: SelectOption[] = [
  { value: 'cell', label: '资料单元格', meta: '一个单元格的数字或文字' },
  { value: 'sum', label: '资料区域合计', meta: '区域里数字的合计' },
  { value: 'run', label: '计算结果', meta: '一次计算结果里的一格' },
  { value: 'value', label: '手填值', meta: '例如标题里的月份' },
];
// The parts openpyxl would drop, as _unsupported_features names them.
const FEATURE_WORDS: Record<string, string> = {
  charts: '图表', drawings: '图片、形状或批注', externalLinks: '外部链接', 'macro project': '宏', 'macro-enabled extension': '宏',
  extensions: '迷你图、部分下拉列表或条件格式等扩展内容',
};
const NOTE_WORDS: Record<string, string> = {
  decimal_written_as_text: '位数超出 Excel 能精确保存的范围，按文字写入完整数字',
  formula_like_text: '以 = + - @ 开头，按文字写入，不会变成公式',
};

/** 「利润表!B5」 → sheet and cell. A full-width ！ is read as !, and a quoted sheet name loses its quotes. */
export function splitAddress(text: string): { sheet: string; cell: string } {
  const value = text.trim().replace(/！/g, '!');
  const at = value.lastIndexOf('!');
  if (at < 0) return { sheet: '', cell: value };
  let sheet = value.slice(0, at).trim();
  if (sheet.length >= 2 && sheet.startsWith("'") && sheet.endsWith("'")) sheet = sheet.slice(1, -1).replace(/''/g, "'");
  return { sheet, cell: value.slice(at + 1).trim().replace(/\$/g, '').toUpperCase() };
}

const CELL = /^[A-Z]{1,3}[1-9]\d{0,6}$/;
const RANGE = /^[A-Z]{1,3}[1-9]\d{0,6}:[A-Z]{1,3}[1-9]\d{0,6}$/;
const isXlsx = (source: DatasetSnapshot) => String(source.source_name ?? '').toLowerCase().endsWith('.xlsx')
  || (source as { source_file?: string }).source_file === 'source.xlsx';
const blank = (key: number, kind: SourceKind = 'cell'): Mapping => ({ key, target: '', kind, datasetId: '', range: '', runId: '', row: '1', column: '', value: '', note: '' });

/** What is still missing on one row, in the words the field shows; empty when the row can be previewed. */
function missing(row: Mapping): string {
  const target = splitAddress(row.target);
  if (!target.sheet || !CELL.test(target.cell)) return '目标单元格要写成 工作表!单元格，例如 利润表!B5';
  if (row.kind === 'cell' || row.kind === 'sum') {
    if (!row.datasetId) return '请选择来源资料';
    const where = splitAddress(row.range);
    if (!where.sheet) return '区域要写成 工作表!B5';
    if (row.kind === 'cell' && !CELL.test(where.cell)) return '资料单元格只填一个单元格，例如 科目余额!D15';
    if (row.kind === 'sum' && !RANGE.test(where.cell)) return '区域合计要写成 工作表!D5:D20';
    return '';
  }
  if (row.kind === 'run') {
    if (!row.runId) return '请选择计算结果';
    if (!/^[1-9]\d*$/.test(row.row.trim())) return '第几行要填 1 以上的整数';
    return row.column ? '' : '请选择列';
  }
  return row.value.trim() ? '' : '请填写手填值';
}

function sourceSpec(row: Mapping, datasets: DatasetSnapshot[]): Record<string, unknown> {
  if (row.kind === 'cell' || row.kind === 'sum') {
    const where = splitAddress(row.range);
    return { kind: 'dataset', dataset_id: row.datasetId, source_hash: datasets.find((item) => item.id === row.datasetId)?.source_hash ?? '', sheet: where.sheet, range: where.cell };
  }
  if (row.kind === 'run') return { kind: 'run', run_id: row.runId, row: Number(row.row.trim()) - 1, column: row.column };
  return { kind: 'value', value: row.value, ...(row.note.trim() ? { note: row.note.trim() } : {}) };
}

function sourceText(source: Record<string, unknown> = {}): string {
  if (source.kind === 'dataset') {
    const range = String(source.range ?? '');
    return `${textValue(source.name || '资料')} · ${String(source.sheet ?? '')}!${range}${range.includes(':') ? '（合计）' : ''}`;
  }
  if (source.kind === 'run') return `计算结果 第 ${Number(source.row ?? 0) + 1} 行 · ${String(source.column ?? '')}`;
  return `手填${source.note ? `：${String(source.note)}` : ''}`;
}

/** No copy is made of a workbook it would damage, so its 「将写入」 rows are hers to fill in. */
function StatusBadge({ row, copied }: { row: PlanRow; copied: boolean }) {
  if (row.status === 'write' && !copied) return <Badge variant="outline"><Hand size={12} aria-hidden />需手工填写</Badge>;
  if (row.status === 'write') return <Badge variant="outline"><PenLine size={12} aria-hidden />将写入</Badge>;
  if (row.status === 'unchanged') return <Badge variant="secondary"><Equal size={12} aria-hidden />无变化</Badge>;
  return <Badge variant="destructive"><Ban size={12} aria-hidden />不写入</Badge>;
}

/**
 * 滚动到下月: this month's figures written into a copy of last month's workbook.
 *
 * The manager maps each figure to a cell and reads the preview before anything is
 * written. Formula cells, merged cells and the like are listed, never overwritten;
 * the copy becomes a new snapshot and last month's stays as it was.
 */
export function RollforwardPanel({ taskId, datasets, runs, busy, onApplied }: {
  taskId: string; datasets: DatasetSnapshot[]; runs: AnalysisRun[]; busy: boolean; onApplied?(): Promise<void> | void;
}) {
  const xlsx = useMemo(() => datasets.filter(isXlsx), [datasets]);
  // Last month's workbook is the manager's choice; nothing is picked for her.
  const [datasetId, setDatasetId] = useState('');
  const [period, setPeriod] = useState('');
  const nextKey = useRef(1);
  const [rows, setRows] = useState<Mapping[]>(() => [blank(0)]);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [templatesError, setTemplatesError] = useState('');
  const [templateId, setTemplateId] = useState('');
  const [templateName, setTemplateName] = useState('');
  const [previewed, setPreviewed] = useState<{ key: string; plan: Plan } | null>(null);
  const [applied, setApplied] = useState<Applied | null>(null);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [running, setRunning] = useState('');
  const templateRequest = useRef(0);
  const locked = busy || Boolean(running);
  const workbook = xlsx.find((item) => item.id === datasetId);

  async function call<T>(command: 'workbook-rollforward-preview' | 'workbook-rollforward-apply' | 'workbook-rollforward-templates' | 'workbook-rollforward-template-save', spec: Record<string, unknown>): Promise<T> {
    const api = bridge(); if (!api?.financeCall) throw new Error('此版本暂不支持滚动到下月。');
    return unwrap(await api.financeCall(taskId, command, spec) as Answer<T>);
  }
  const track = (label: string, work: () => Promise<void>) => {
    if (running) return;
    setRunning(label); setError(''); setMessage('');
    void work().catch((failure) => setError(errorText(failure))).finally(() => setRunning(''));
  };

  const spec = useMemo(() => ({
    dataset_id: datasetId, source_hash: workbook?.source_hash ?? '', period,
    mappings: rows.map((row) => ({ target: splitAddress(row.target), source: sourceSpec(row, xlsx) })),
  }), [datasetId, workbook, period, rows, xlsx]);
  const specKey = JSON.stringify(spec);
  // A preview speaks only for the inputs it was made from; any edit retires it.
  const plan = previewed && previewed.key === specKey ? previewed.plan : null;

  useEffect(() => {
    setTemplates([]); setTemplateId(''); setTemplatesError('');
    if (!datasetId || !bridge()?.financeCall) return;
    const asked = ++templateRequest.current;
    void call<{ templates?: Template[] }>('workbook-rollforward-templates', { dataset_id: datasetId })
      .then((answer) => { if (asked === templateRequest.current) setTemplates(Array.isArray(answer.templates) ? answer.templates : []); })
      .catch((failure) => { if (asked === templateRequest.current) setTemplatesError(errorText(failure)); });
  }, [datasetId, taskId]);

  if (!xlsx.length) return null;
  const update = (key: number, change: Partial<Mapping>) => setRows((current) => current.map((row) => row.key === key ? { ...row, ...change } : row));
  const add = (row: Partial<Mapping> = {}) => setRows((current) => [...current, { ...blank(nextKey.current++), ...row }]);
  const gaps = rows.map(missing);
  const incomplete = gaps.map((gap, index) => gap ? index + 1 : 0).filter(Boolean);
  const periodReady = /^\d{4}-(0[1-9]|1[0-2])$/.test(period);
  const counts = plan?.counts ?? { write: 0, blocked: 0, unchanged: 0 };
  const planRows = Array.isArray(plan?.rows) ? plan.rows : [];
  const unmappedTitles = (plan?.title_hints ?? []).filter((hint) => !hint.mapped);
  const features = (plan?.unsupported_features ?? []).map((name) => FEATURE_WORDS[name] ?? name).filter((word, index, all) => all.indexOf(word) === index);
  const copied = plan?.workbook_supported !== false;
  const writeWord = copied ? '将写入' : '需手工填写';

  const preview = () => track('正在预览…', async () => {
    const key = specKey;
    setApplied(null);
    const result = await call<Plan>('workbook-rollforward-preview', spec);
    setPreviewed({ key, plan: result });
    setMessage(result.workbook_supported === false ? '' : `预览完成：将写入 ${result.counts?.write ?? 0} 格，不写入 ${result.counts?.blocked ?? 0} 格，无变化 ${result.counts?.unchanged ?? 0} 格。确认无误后再生成下月副本。`);
  });
  const apply = () => track('正在生成下月副本…', async () => {
    if (!plan?.plan_id) return;
    const result = await call<Applied>('workbook-rollforward-apply', { plan_id: plan.plan_id });
    setApplied(result);
    const skipped = result.counts?.blocked ? ` 另有 ${result.counts.blocked} 格没有写入，见变更记录。` : '';
    const formulas = result.formula_cache_cleared === false ? '' : '公式会在 Excel 打开时重算：请「导出下月副本」，在 Excel 里打开并保存，再重新添加，本应用才能读到公式结果。';
    setMessage(`已生成「${result.output_name ?? '下月副本'}」，在资料列表里。原工作簿未改动；${formulas}${skipped}`);
    window.dispatchEvent(new Event('fnd:task-changed'));
    await onApplied?.();
  });
  const exportCopy = () => track('正在导出…', async () => {
    const api = bridge();
    if (!applied?.run_id || !api?.rollforwardExport) return;
    const saved = unwrap(await api.rollforwardExport(taskId, applied.run_id, applied.output_name));
    if (saved.cancelled) return;
    setMessage(`已导出「${saved.filename ?? '下月副本'}」。在 Excel 里打开、检查并保存后，再到资料页重新添加，本应用才能读到公式结果。保存时保留这个文件名，重新添加后会取代列表里的副本。`);
  });
  const copy = (text: string | undefined, done: string) => track('正在复制…', async () => {
    if (!text) throw new Error('没有可复制的记录。');
    await navigator.clipboard.writeText(text);
    setMessage(done);
  });
  const saveTemplate = () => track('正在保存模板…', async () => {
    if (!plan?.plan_id) return;
    const saved = await call<Template>('workbook-rollforward-template-save', { plan_id: plan.plan_id, name: templateName.trim() });
    setTemplates((current) => [...current, saved]);
    setTemplateName('');
    setMessage(`已存为下月模板「${saved.name}」。下个月选同一套表时可以套用；来源资料和手填值到时重新选、重新填。`);
  });
  const applyTemplate = (id: string) => {
    setTemplateId(id);
    const template = templates.find((item) => item.id === id);
    if (!template) return;
    const filled = (template.mappings ?? []).map((mapping): Mapping => {
      const row = { ...blank(nextKey.current++), target: `${mapping.target.sheet}!${mapping.target.cell}` };
      const source = mapping.source;
      if (source.kind === 'dataset') return { ...row, kind: source.range.includes(':') ? 'sum' : 'cell', range: `${source.sheet}!${source.range}`, hint: source.hint };
      if (source.kind === 'run') return { ...row, kind: 'run', row: String(source.row + 1), column: source.column };
      return { ...row, kind: 'value', note: source.note ?? '', lastValue: source.last_value };
    });
    if (!filled.length) return;
    setRows(filled);
    setMessage(`已套用模板「${template.name}」。请为每一行选本月的来源资料或计算结果；手填值要重新填写。`);
  };
  const addTitles = () => {
    unmappedTitles.forEach((hint) => add({ target: hint.target, kind: 'value', note: '标题里的月份', lastValue: hint.text }));
    setMessage('已把这些标题单元格加到映射末尾，请填写本月的标题文字后重新预览。');
  };

  return <section className="analysis-rollforward" aria-label="滚动到下月">
    <div className="analysis-section-heading"><div>
      <span className="fnd-with-help"><h3>滚动到下月</h3><HelpLink article="rollforward" label="滚动到下月" /></span>
      <p className="analysis-note">把本月的数写进上月套表的副本。只写普通单元格，公式、合并单元格、受保护的格子只列出来，由你在 Excel 里处理；上月的原工作簿不会改动。</p>
    </div></div>
    <fieldset className="analysis-fieldset" disabled={locked}>
      <div className="analysis-edit-grid">
        <SearchableSelect label="上月套表" value={datasetId} options={datasetOptions(xlsx)} onChange={setDatasetId} placeholder="选择上月的工作簿" />
        <AccountingPeriodInput label="新月份" value={period} onChange={setPeriod} help="副本对应的月份，由你填写；系统不会按电脑日期推算。" />
        <SearchableSelect label="套用模板" value={templateId} options={templates.map((item) => ({ value: item.id, label: item.name, meta: `${item.mapping_count ?? item.mappings?.length ?? 0} 行映射` }))}
          onChange={applyTemplate} placeholder="选择存过的映射" allowEmptyLabel="不套用" loadError={templatesError}
          unconfigured={!datasetId} unconfiguredLabel="先选择上月套表，再看这本套表存过的模板。" emptyLabel="这本套表还没有存过模板" />
      </div>
      <p className="analysis-note">副本会保留上月的标题和期间文字。记得把标题、期间单元格也加进映射（来源选「手填值」）。</p>
      <ol className="analysis-rollforward-rows" aria-label="映射">
        {rows.map((row, index) => {
          const n = index + 1;
          const run = runs.find((item) => item.id === row.runId);
          const columns: SelectOption[] = (run?.result?.columns ?? []).map((column) => ({ value: column.name, label: column.name, meta: column.type }));
          return <li key={row.key} className="analysis-rollforward-row">
            <span className="analysis-rollforward-row-number" aria-hidden>{n}</span>
            <TextField label="目标单元格" ariaLabel={`第 ${n} 行目标单元格`} value={row.target} placeholder="利润表!B5" onChange={(target) => update(row.key, { target })} />
            <SearchableSelect label="来源" ariaLabel={`第 ${n} 行来源`} value={row.kind} options={KIND_OPTIONS} onChange={(kind) => kind && update(row.key, { kind: kind as SourceKind })} />
            {(row.kind === 'cell' || row.kind === 'sum') && <>
              <SearchableSelect label="来源资料" ariaLabel={`第 ${n} 行来源资料`} value={row.datasetId} options={datasetOptions(xlsx)} onChange={(datasetId) => update(row.key, { datasetId })}
                placeholder="选择本月的资料" help={row.hint ? `上次用的是：${row.hint}` : undefined} />
              <TextField label={row.kind === 'sum' ? '区域' : '单元格'} ariaLabel={`第 ${n} 行${row.kind === 'sum' ? '区域' : '单元格'}`} value={row.range}
                placeholder={row.kind === 'sum' ? '科目余额!D5:D20' : '科目余额!D15'} onChange={(range) => update(row.key, { range })} />
            </>}
            {row.kind === 'run' && <>
              <SearchableSelect label="计算结果" ariaLabel={`第 ${n} 行计算结果`} value={row.runId} options={runOptions(runs)} onChange={(runId) => update(row.key, { runId, column: '' })} placeholder="选择一次计算" />
              <TextField label="第几行" ariaLabel={`第 ${n} 行取第几行`} value={row.row} inputMode="numeric" onChange={(value) => update(row.key, { row: value })} />
              <SearchableSelect label="列" ariaLabel={`第 ${n} 行取哪一列`} value={row.column} options={columns} onChange={(column) => update(row.key, { column })}
                unconfigured={!run} unconfiguredLabel="先选择计算结果" />
            </>}
            {row.kind === 'value' && <>
              <TextField label="手填值" ariaLabel={`第 ${n} 行手填值`} value={row.value} placeholder={row.lastValue ? `上次：${row.lastValue}` : '例如 2026年09月'} onChange={(value) => update(row.key, { value })} />
              <TextField label="说明（可选）" ariaLabel={`第 ${n} 行说明`} value={row.note} onChange={(note) => update(row.key, { note })} />
            </>}
            <Button variant="ghost" size="icon" type="button" aria-label={`删除第 ${n} 行`} title="删除这一行" disabled={rows.length === 1}
              onClick={() => setRows((current) => current.filter((item) => item.key !== row.key))}><Trash2 size={14} aria-hidden /></Button>
            {row.target.trim() && gaps[index] ? <p className="analysis-rollforward-gap">{gaps[index]}</p> : null}
          </li>;
        })}
      </ol>
    </fieldset>
    <div className="analysis-actions">
      <Button variant="outline" type="button" disabled={locked || rows.length >= 2000} onClick={() => add()}><Plus size={14} aria-hidden />添加一行</Button>
      <Button variant="outline" type="button" disabled={locked || !datasetId || !periodReady || incomplete.length > 0} onClick={preview}><FileSearch size={14} aria-hidden />预览</Button>
      <Button type="button" disabled={locked || !plan?.plan_id || plan.workbook_supported === false || !counts.write || Boolean(applied)} onClick={apply}>
        <FileSpreadsheet size={14} aria-hidden />生成下月副本</Button>
      {running && <span role="status" className="analysis-note"><WaitOrb state="working" />{running}</span>}
    </div>
    {incomplete.length > 0 && <p className="analysis-note">还有 {incomplete.length} 行没填完（第 {incomplete.join('、')} 行），填完才能预览。</p>}
    {!datasetId || !periodReady ? <p className="analysis-note">先选上月套表、填新月份，再预览。</p> : null}

    {plan && plan.workbook_supported === false && <div className="analysis-rollforward-warning" role="note">
      <TriangleAlert size={16} aria-hidden />
      <div><p>这本工作簿含有{features.join('、') || '复制时会丢失的内容'}，复制后会丢失，所以不会生成副本。下面是按映射整理的清单，请在 Excel 里手工更新。</p>
        <Button variant="outline" size="sm" type="button" disabled={locked} onClick={() => copy(plan.change_log?.tsv, '已复制清单，可直接粘贴到 Excel。')}>
          <ClipboardCopy size={14} aria-hidden />复制清单</Button></div>
    </div>}
    {plan && unmappedTitles.length > 0 && <div className="analysis-rollforward-warning" role="note">
      <TriangleAlert size={16} aria-hidden />
      <div><p>这些单元格看起来还写着别的月份，副本会原样保留：{unmappedTitles.map((hint) => `${hint.target}「${hint.text}」`).join('；')}。</p>
        <Button variant="outline" size="sm" type="button" disabled={locked} onClick={addTitles}><ListPlus size={14} aria-hidden />加到映射</Button></div>
    </div>}
    {plan && <div className="fnd-tablewrap" tabIndex={0} role="region" aria-label="滚动预览">
      <table className="fnd-table analysis-table analysis-rollforward-table">
        <caption>
          <span className="analysis-rollforward-counts">
            <span>{copied ? <PenLine size={13} aria-hidden /> : <Hand size={13} aria-hidden />}{writeWord} {counts.write}</span>
            <span><Ban size={13} aria-hidden />不写入 {counts.blocked}</span>
            <span><Equal size={13} aria-hidden />无变化 {counts.unchanged}</span>
          </span>
        </caption>
        <thead><tr><th scope="col">目标单元格</th><th scope="col">状态</th><th scope="col">原值</th><th scope="col">新值</th><th scope="col">来源</th></tr></thead>
        <tbody>{planRows.map((row) => <tr key={row.index} data-status={row.status}>
          <td>{row.target}</td>
          <td><StatusBadge row={row} copied={copied} />{row.status === 'blocked' && row.reason ? <span className="analysis-rollforward-reason">{row.reason}</span> : null}</td>
          <td>{textValue(row.old_value)}</td>
          <td>{textValue(row.new_value)}{(row.notes ?? []).map((note) => <span key={note} className="analysis-rollforward-reason">{NOTE_WORDS[note] ?? note}</span>)}
            {row.status === 'write' && row.cell_type === 'text' && !(row.notes ?? []).length ? <span className="analysis-rollforward-reason">按文字写入</span> : null}</td>
          <td>{sourceText(row.source)}</td>
        </tr>)}</tbody>
      </table>
    </div>}
    {plan?.plan_id && <div className="analysis-actions">
      <TextField label="模板名称" value={templateName} placeholder="例如 华东月度套表" onChange={setTemplateName} />
      <Button variant="outline" type="button" disabled={locked || !templateName.trim()} onClick={saveTemplate}><Save size={14} aria-hidden />存为下月模板</Button>
    </div>}
    {applied && <div className="analysis-actions">
      {bridge()?.rollforwardExport && <Button size="sm" type="button" disabled={locked} onClick={exportCopy}>
        <Download size={14} aria-hidden />导出下月副本</Button>}
      <Button variant="outline" size="sm" type="button" disabled={locked} onClick={() => copy(applied.change_log?.tsv, '已复制变更记录，可直接粘贴到 Excel。')}>
        <ClipboardCopy size={14} aria-hidden />复制变更记录</Button>
      <Button variant="outline" size="sm" type="button" disabled={locked} onClick={() => copy(applied.change_log?.markdown, '已复制为文字，可粘贴到邮件或文档。')}>复制为文字</Button>
    </div>}
    {message && <p role="status" className="analysis-message">{message}</p>}
    {error && <p role="alert" className="analysis-message analysis-message--error">{error}</p>}
  </section>;
}
