import { useEffect, useState } from 'react';
import { ChevronRight, FileSpreadsheet, X } from 'lucide-react';
import { bridge, type DrillFigure, type DrillLevel, type DrillRow } from '../../bridge.js';
import { Button } from '../../components/ui/button.js';
import { Figure } from '../../components/Figure.js';
import { WaitLoop } from '../../components/WaitLoop.js';
import { formatAmount } from '../../lib/figures.js';
import { percent } from './BillingPanel.js';
import { errorText, unwrap } from './shared.js';

/**
 * 往下拆 (foundry/billing_drill.py): one rate of a collection run taken apart 城市公司 → 项目 → 房产 → 账单, with the
 * run's own 口径 and mapping. Each level says whether its rows add up to the row it was opened from; a bill names the
 * export lines it was read from. The engine works every figure out; this only draws a level and asks for the next.
 */
export function BillingDrill({ taskId, runId, figure, onClose }: {
  taskId: string; runId: string; figure: DrillFigure; onClose(): void;
}) {
  const [path, setPath] = useState<(string | null)[]>([]);
  // The level on screen and the path it was read for: while the next one loads, every row, link and export still
  // acts from the level shown, never from the path asked for since.
  const [shown, setShown] = useState<{ path: (string | null)[]; level: DrillLevel } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [exporting, setExporting] = useState(false);
  const key = JSON.stringify(path);
  useEffect(() => {
    let live = true;
    setLoading(true); setError('');
    void (async () => {
      const api = bridge(); if (!api?.billingCall) throw new Error('此版本暂不支持往下拆。');
      return unwrap(await api.billingCall(taskId, 'collection-drill', { run: runId, figure, path: JSON.parse(key) })) as DrillLevel;
    })().then((found) => { if (live) setShown({ path: JSON.parse(key) as (string | null)[], level: found }); },
      (failure: unknown) => { if (live) setError(errorText(failure)); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [taskId, runId, figure, key]);
  const level = shown?.level ?? null;
  const at = shown?.path ?? [];
  const go = (next: (string | null)[]) => { setMessage(''); setPath(next); };
  const save = async () => {
    if (!level || exporting) return;
    setExporting(true); setError(''); setMessage('');
    try {
      const api = bridge(); if (!api?.billingDrillExport) throw new Error('此版本暂不支持导出往下拆。');
      const name = [level.label, ...level.path.map((step) => step.label), level.level.label].join('-');
      const done = unwrap(await api.billingDrillExport(taskId, { run: runId, figure, path: at, name }));
      if ('exported' in done) setMessage(`已导出 ${done.rows.toLocaleString('en-US')} 行。`);
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      setExporting(false);
    }
  };
  const label = level?.label ?? '';
  const bills = level?.level.key === 'bill';
  const parent = level ? (level.path.at(-1) ?? level.whole) : null;
  const next = level ? level.levels[level.path.length + 1] : undefined;
  return <section className="analysis-billing-drill" aria-label={`往下拆：${label || '收缴率'}`}>
    <div className="analysis-billing-caliber__head">
      <h5>往下拆{label ? ` · ${label}` : ''}</h5>
      <Button variant="ghost" size="sm" type="button" onClick={onClose}><X size={14} aria-hidden />收起</Button>
    </div>
    {level ? <nav aria-label="拆到哪一层"><ol className="analysis-billing-drill__trail">
      {[level.whole, ...level.path].map((step, index, all) => <li key={index}>
        {index > 0 ? <ChevronRight size={12} aria-hidden /> : null}
        {index === all.length - 1 ? <span aria-current="location">{step.label}</span>
          : <Button variant="link" type="button" onClick={() => go(at.slice(0, index))}>{step.label}</Button>}
      </li>)}
    </ol></nav> : null}
    {loading && !level ? <p role="status" className="analysis-note"><WaitLoop />正在拆分。第一次要把这次计算的账单整理一遍，几十万行要几秒…</p> : null}
    {error ? <p role="alert" className="analysis-message analysis-message--error">{error}</p> : null}
    {level && !level.run_check.ties ? <p role="alert" className="analysis-message analysis-message--error">
      {`从明细重新加总的${level.base_label} ${formatAmount(level.whole.base)}、${level.done_label} ${formatAmount(level.whole.done)}，`
        + `和这次计算记下的 ${formatAmount(level.run_check.base)}、${formatAmount(level.run_check.done)} 不一致。请重新计算后再拆。`}</p> : null}
    {level && parent ? <p className="analysis-billing-drill__check" aria-live="polite">
      本层合计：{level.base_label} <Figure text={formatAmount(level.total.base)} />，{level.done_label} <Figure text={formatAmount(level.total.done)} />，
      {label} <Figure text={percent(level.total.rate)} />。
      {!level.path.length && !level.run_check.ties ? null
        : level.ties ? <>等于{level.path.length ? `上一层「${parent.label}」` : '这次计算结果'}的数。</>
        : <strong className="analysis-billing-drill__miss">和{level.path.length ? `上一层「${parent.label}」` : '这次计算结果'}的数对不上：
          {level.base_label}差 <Figure text={formatAmount(level.gap.base)} />，{level.done_label}差 <Figure text={formatAmount(level.gap.done)} />。</strong>}
      {loading ? <span className="analysis-note"> <WaitLoop />正在读取…</span> : null}
    </p> : null}
    {level ? <div className="fnd-tablewrap"><table className="analysis-table analysis-billing-drill__table">
      <caption className="sr-only">{`${[level.whole, ...level.path].map((step) => step.label).join(' › ')}：按${level.level.label}`}</caption>
      <thead><tr>
        <th scope="col">{level.level.label}</th>
        {bills ? <><th scope="col">收费项目</th><th scope="col">账期</th></> : <th scope="col">户数</th>}
        <th scope="col">{level.base_label}</th><th scope="col">{level.done_label}</th><th scope="col">未收</th><th scope="col">{label}</th>
        {bills ? <th scope="col">来源</th> : null}
      </tr></thead>
      <tbody>{level.rows.map((row) => <DrillLine key={`${row.value}`} row={row} bills={bills} next={next?.label}
        onOpen={() => go([...at, row.value])} />)}</tbody>
    </table></div> : null}
    {level ? <div className="analysis-actions">
      <span className="analysis-note">{level.row_count > level.rows.length
        ? `共 ${level.row_count.toLocaleString('en-US')} 行，按未收从多到少列出前 ${level.rows.length} 行；全部见导出。`
        : `共 ${level.row_count.toLocaleString('en-US')} 行，按未收从多到少排列。`}{bills ? '' : '点名称往下拆一层。'}</span>
      <Button variant="outline" type="button" disabled={exporting} onClick={() => void save()}>
        <FileSpreadsheet size={14} aria-hidden />导出 Excel</Button>
    </div> : null}
    {message ? <p role="status" className="analysis-message">{message}</p> : null}
  </section>;
}

function DrillLine({ row, bills, next, onOpen }: { row: DrillRow; bills: boolean; next?: string; onOpen(): void }) {
  return <tr>
    <th scope="row">{bills ? row.label
      : <Button variant="link" type="button" aria-label={`拆开「${row.label}」，看${next ?? '下一层'}`} onClick={onOpen}>{row.label}</Button>}</th>
    {bills ? <><td>{row.fee_item ?? '（空）'}</td><td>{row.period}{row.place === 'arrears' ? '（往年）' : ''}</td></>
      : <td className="fnd-num">{(row.properties ?? 0).toLocaleString('en-US')}</td>}
    <td className="fnd-num"><Figure text={formatAmount(row.base)} /></td>
    <td className="fnd-num"><Figure text={formatAmount(row.done)} /></td>
    <td className="fnd-num"><Figure text={formatAmount(row.outstanding)} /></td>
    <td className="fnd-num"><Figure text={percent(row.rate)} /></td>
    {bills ? <td className="analysis-billing-drill__source">
      <span>应收：{row.lines?.length ? `${row.lines.join('；')}${(row.line_count ?? 0) > row.lines.length ? ` 等 ${row.line_count} 行` : ''}` : '—'}</span>
      <span>收款：{row.receipts?.length ? `${row.receipts.join('；')}${(row.receipt_count ?? 0) > row.receipts.length ? ` 等 ${row.receipt_count} 笔` : ''}` : '没有'}</span>
    </td> : null}
  </tr>;
}
