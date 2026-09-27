import { useCallback, useEffect, useState } from 'react';
import { bridge, type Answer } from '../../bridge.js';
import { WaitOrb } from '../../components/WaitOrb.js';
import { Button } from '../../components/ui/button.js';
import { unwrap } from './shared.js';

type FinanceAdjustment = {
  id: string;
  label?: string;
  include_in_management_pnl?: boolean;
  note?: string;
  amount?: string;
  profit_impact?: string;
  parent_id?: string | null;
  /** The newer row that replaced this one. A superseded row, pending or confirmed, is history, not a choice. */
  superseded_by?: string | null;
};

export function FinanceAdjustmentPanel({ taskId, contextId, busy, onRefresh }: {
  taskId: string; contextId: string; busy: boolean; onRefresh(): Promise<void> | void;
}) {
  const [rows, setRows] = useState<FinanceAdjustment[]>([]);
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [pendingId, setPendingId] = useState('');
  const [rerunning, setRerunning] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const load = useCallback(async () => {
    const api = bridge(); if (!api?.financeCall || !contextId) return;
    const listed = unwrap(await api.financeCall(taskId, 'finance-adjustment-list', { context_id: contextId }) as Answer<{ adjustments?: FinanceAdjustment[] }>);
    const next = listed.adjustments ?? [];
    setRows(next);
    setSelected((current) => {
      const nextSelected: Record<string, boolean> = {};
      for (const row of next.filter((item) => item.include_in_management_pnl)) {
        nextSelected[row.id] = current[row.id] !== false;
      }
      return nextSelected;
    });
  }, [taskId, contextId]);
  useEffect(() => { void load().catch((failure) => setError(failure instanceof Error ? failure.message : String(failure))); }, [load]);
  const current = rows.filter((row) => !row.superseded_by);
  const confirmed = current.filter((row) => row.include_in_management_pnl);
  const pending = current.filter((row) => !row.include_in_management_pnl && !confirmed.some((item) => item.parent_id === row.id));
  const locked = busy || Boolean(pendingId) || rerunning;
  async function confirm(id: string) {
    const api = bridge(); if (!api?.financeCall) return;
    setPendingId(id); setError(''); setMessage('');
    try {
      unwrap(await api.financeCall(taskId, 'finance-adjustment-confirm', { id }));
      setMessage('已确认纳入考核。');
      await load();
      await onRefresh();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setPendingId('');
    }
  }
  async function rerun() {
    const api = bridge(); if (!api?.financeCall) return;
    setRerunning(true); setError(''); setMessage('');
    const ids = confirmed.filter((row) => selected[row.id] !== false).map((row) => row.id);
    try {
      unwrap(await api.financeCall(taskId, 'run-metric', { context_id: contextId, metric: { kind: 'management_pnl' }, adjustment_ids: ids }));
      setMessage(ids.length ? '已按勾选调整重算考核利润。' : '已无调整重跑账面利润。');
      await onRefresh();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setRerunning(false);
    }
  }
  if (!contextId) return null;
  return <aside className="analysis-adjustment-panel" aria-label="考核调整"><details className="analysis-details">
    <summary><div className="analysis-section-heading"><h3>考核调整</h3><span className="analysis-note">{pending.length ? `${pending.length} 条待确认 · ` : ''}确认后才会进入下一次管理损益。</span></div></summary>
    {pending.length ? <ul className="analysis-history-list">{pending.map((row) => <li key={row.id} className="analysis-history-row analysis-history-row--static">
      <span>{row.label || '调整'} · 待确认</span>
      <Button type="button" disabled={locked} onClick={() => void confirm(row.id)}>{pendingId === row.id ? '确认中…' : '确认纳入'}</Button>
    </li>)}</ul> : <p className="analysis-note">没有待确认的调整。</p>}
    {confirmed.length ? <div className="analysis-fieldset analysis-adjustment-rerun" aria-label="重算">
      <p className="analysis-note">重算</p>
      {confirmed.map((row) => <label key={row.id}><input type="checkbox" checked={selected[row.id] !== false}
        onChange={(event) => setSelected((value) => ({ ...value, [row.id]: event.target.checked }))} />{row.label || row.id}</label>)}
      <Button type="button" disabled={locked} onClick={() => void rerun()}>{rerunning ? <><WaitOrb state="solving" />重算中…</> : '重算'}</Button>
    </div> : null}
  </details>
    {/* Outside the fold: a failed list must not read as "nothing to confirm". */}
    {message && <p role="status" className="analysis-message">{message}</p>}
    {error && <p role="alert" className="analysis-message analysis-message--error">{error}</p>}
  </aside>;
}
