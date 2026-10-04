import { useEffect, useMemo, useState } from 'react';
import { Check, Scale } from 'lucide-react';
import { Button } from '../../components/ui/button.js';
import { Input } from '../../components/ui/input.js';
import { STATUS_LABELS, where, type ControlResult, type ControlSpec } from './controls.js';
import { errorText } from './shared.js';
import { NativeSelect } from '../../components/ui/native-select.js';

export type ControlSource = { dataset_id: string; source_hash: string; name: string; sheets: string[] };
type Place = { dataset_id: string; sheet: string; range: string; unit: string };

/** A unit conversion, never a coefficient: the side in the larger unit is scaled to the smaller one. */
const UNITS: [string, number][] = [['元', 1], ['千元', 1e3], ['万元', 1e4], ['百万元', 1e6], ['亿元', 1e8]];
const factor = (unit: string) => UNITS.find(([name]) => name === unit)?.[1] ?? 1;
const blank = (): Place => ({ dataset_id: '', sheet: '', range: '', unit: '万元' });
/** What a Chinese keyboard types for a range (B5：B6, B5－B6, ＄B＄5) in the A1 form the engine reads. */
const cellRange = (raw: string) => raw.normalize('NFKC').replace(/\s+/g, '').replace(/[-–—~～]/g, ':').toUpperCase();

/**
 * 添加两处取数对比: the manager names two places (sheet and cells, in the same or another workbook),
 * sees both sums and the difference, and only then confirms it as a control. A difference found
 * here is handled like any other: the system never picks the side that is right.
 */
export function TieOutForm({ call, locked, refreshKey, onBusy, onSaved, onCancel }: {
  call<T>(command: string, spec?: unknown): Promise<T>;
  locked: boolean;
  /** Changes when the task's files may have changed; the workbook list is read again. */
  refreshKey?: unknown;
  onBusy?(busy: boolean): void;
  onSaved(message: string): Promise<void> | void;
  onCancel(): void;
}) {
  const [sources, setSources] = useState<ControlSource[] | null>(null);
  const [left, setLeft] = useState<Place>(blank);
  const [right, setRight] = useState<Place>(blank);
  const [label, setLabel] = useState('');
  const [preview, setPreview] = useState<{ control: ControlSpec; preview: ControlResult } | null>(null);
  const [working, setWorking] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    let live = true;
    call<{ sources: ControlSource[] }>('finance-controls-sources', {})
      .then((answer) => { if (live) setSources(answer.sources); })
      .catch((failure) => { if (live) setError(errorText(failure)); });
    return () => { live = false; };
  }, [call, refreshKey]);

  const control = useMemo((): ControlSpec | null => {
    const side = (place: Place) => {
      const source = sources?.find((row) => row.dataset_id === place.dataset_id);
      return source && place.sheet && place.range.trim()
        ? { dataset_id: source.dataset_id, source_hash: source.source_hash, sheet: place.sheet, range: cellRange(place.range) }
        : null;
    };
    const l = side(left); const r = side(right);
    if (!l || !r) return null;
    const common = Math.min(factor(left.unit), factor(right.unit));
    const unit = UNITS.find(([, value]) => value === common)?.[0] ?? '';
    return {
      kind: 'tie_out', tolerance: '0', unit,
      label: label.trim() || `${where({ ...l, scale: '1' })} 对 ${where({ ...r, scale: '1' })}`,
      left: { ...l, scale: String(factor(left.unit) / common) },
      right: { ...r, scale: String(factor(right.unit) / common) },
    };
  }, [sources, left, right, label]);

  // Any edit makes the old preview a preview of something else.
  useEffect(() => { setPreview(null); }, [control]);

  async function work(text: string, task: () => Promise<void>) {
    setWorking(text); setError(''); onBusy?.(true);
    try { await task(); } catch (failure) { setError(errorText(failure)); } finally { setWorking(''); onBusy?.(false); }
  }
  const check = () => work('正在加总两处…', async () => {
    if (control) setPreview(await call('finance-controls-preview', { control }));
  });
  const save = () => work('正在保存…', async () => {
    if (!preview) return;
    await call('finance-controls-save', { controls: [preview.control], origin: 'declared', confirm: true });
    // Saved is saved: a run that fails afterwards is reported, never mistaken for a failed save.
    let ran = true;
    try { await call('finance-controls-run', {}); } catch { ran = false; }
    await onSaved(ran ? `已确认这条对比：${preview.control.label}` : `已确认这条对比：${preview.control.label}。运行没有完成，请点「重新运行」。`);
  });

  const busy = locked || Boolean(working);
  const result = preview?.preview;
  // Only a comparison both sides of which could be read is worth keeping as a control.
  const savable = result?.status === 'pass' || result?.status === 'break';
  return <section className="analysis-tieout" aria-label="添加两处取数对比"><fieldset className="analysis-fieldset analysis-tieout-fields" disabled={busy}>
    <legend><Scale size={15} strokeWidth={1.5} aria-hidden /> 添加两处取数对比</legend>
    <p className="analysis-note">选两处应当相等的数字，可以跨表、跨工作簿。系统加总两处并给出差额，不替你判断哪一处对。</p>
    {sources === null && !error ? <p className="analysis-note" role="status">正在读取工作簿…</p> : null}
    {sources && !sources.length ? <p className="analysis-note">这个任务还没有 Excel 工作簿。</p> : null}
    {sources?.length ? <div className="analysis-tieout-places">
      <PlaceFields title="第一处" place={left} sources={sources} onChange={setLeft} />
      <PlaceFields title="第二处" place={right} sources={sources} onChange={setRight} />
    </div> : null}
    <label className="analysis-tieout-label">对比名称
      <Input aria-label="对比名称" maxLength={200} value={label} placeholder={control?.label ?? '例如：合同台账实收 对 月结区域实收'} onChange={(event) => setLabel(event.target.value)} />
    </label>
    {working ? <p className="analysis-note" role="status">{working}</p> : null}
    {error ? <p role="alert" className="analysis-message analysis-message--error">{error}</p> : null}
    {result ? <div className="analysis-tieout-result" role="status">
      <p><span className={`analysis-controls-status analysis-controls-status--${result.status}`}>{STATUS_LABELS[result.status]}</span></p>
      {result.left ? <p>{where(result.left)} 合计 {result.left.value ?? '—'}</p> : null}
      {result.right ? <p>{where(result.right)} 合计 {result.right.value ?? '—'}</p> : null}
      {result.difference ? <p className="analysis-tieout-difference">差额 {result.difference}{preview?.control.unit ? ` ${preview.control.unit}` : ''}{result.within_rounding ? '（可能是显示舍入，仍算不相符）' : ''}</p> : null}
      {result.reason ? <p className="analysis-note">{result.reason}</p> : null}
    </div> : null}
    {result && !savable ? <p className="analysis-note">这两处读不出可比较的合计，改选单元格后再加总。</p> : null}
    <div className="analysis-actions">
      {preview && savable
        ? <Button type="button" onClick={() => void save()}><Check size={15} strokeWidth={1.5} aria-hidden />确认并保存这条对比</Button>
        : <Button type="button" disabled={!control || Boolean(preview)} onClick={() => void check()}>加总两处，看差额</Button>}
    </div>
  </fieldset>
    {/* Outside the fieldset: a slow save can still be left. */}
    <div className="analysis-actions"><Button type="button" variant="outline" onClick={onCancel}>取消</Button></div>
  </section>;
}

function PlaceFields({ title, place, sources, onChange }: { title: string; place: Place; sources: ControlSource[]; onChange(next: Place): void }) {
  const sheets = sources.find((row) => row.dataset_id === place.dataset_id)?.sheets ?? [];
  return <div className="analysis-tieout-place" role="group" aria-label={title}>
    <h5>{title}</h5>
    <label>工作簿
      <NativeSelect aria-label={`${title}工作簿`} value={place.dataset_id} onChange={(event) => onChange({ ...place, dataset_id: event.target.value, sheet: '' })}>
        <option value="">选择工作簿</option>
        {sources.map((row) => <option key={row.dataset_id} value={row.dataset_id}>{row.name}</option>)}
      </NativeSelect></label>
    <label>工作表
      <NativeSelect aria-label={`${title}工作表`} value={place.sheet} disabled={!sheets.length} onChange={(event) => onChange({ ...place, sheet: event.target.value })}>
        <option value="">选择工作表</option>
        {sheets.map((name) => <option key={name} value={name}>{name}</option>)}
      </NativeSelect></label>
    <label>单元格或区域
      <Input aria-label={`${title}单元格`} maxLength={40} value={place.range} placeholder="例如 T605 或 B5:B604" onChange={(event) => onChange({ ...place, range: event.target.value })} /></label>
    <label>这一处的单位
      <NativeSelect aria-label={`${title}单位`} value={place.unit} onChange={(event) => onChange({ ...place, unit: event.target.value })}>
        {UNITS.map(([name]) => <option key={name} value={name}>{name}</option>)}
      </NativeSelect></label>
  </div>;
}
