import { useCallback, useEffect, useState } from 'react';
import { bridge, type Answer, type AnalysisRun } from '../../bridge.js';
import { textValue } from './presentation.js';
import { Button } from '../../components/ui/button.js';
import { unwrap, errorText } from './shared.js';

type FinanceChart = {
  id: string;
  label?: string;
  run_id?: string;
  content_hash?: string;
  series?: { columns?: unknown[]; rows?: Record<string, unknown>[] };
};

export function FinanceChartPanel({ taskId, runs, busy, onRefresh }: {
  taskId: string; runs: AnalysisRun[]; busy: boolean; onRefresh(): Promise<void> | void;
}) {
  const [charts, setCharts] = useState<FinanceChart[]>([]);
  const [opened, setOpened] = useState<FinanceChart | null>(null);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [pending, setPending] = useState(false);
  const latest = [...runs].reverse().find((row) => row.execution_status === 'succeeded' || row.execution_status === 'success');
  const load = useCallback(async () => {
    const api = bridge(); if (!api?.financeCall) return;
    const listed = unwrap(await api.financeCall(taskId, 'chart-deliverable-list', {}) as Answer<{ charts?: FinanceChart[] }>);
    setCharts(listed.charts ?? []);
  }, [taskId]);
  useEffect(() => { void load().catch((failure) => setError(errorText(failure))); }, [load]);
  async function archive() {
    const api = bridge(); if (!api?.financeCall || !latest) return;
    setPending(true); setError(''); setMessage('');
    try {
      unwrap(await api.financeCall(taskId, 'chart-deliverable-save', { run_id: latest.id }));
      setMessage('已归档当前结果图。');
      await load();
      await onRefresh();
    } catch (failure) {
      setError(errorText(failure));
    } finally { setPending(false); }
  }
  async function open(id: string) {
    const api = bridge(); if (!api?.financeCall) return;
    setPending(true); setError(''); setMessage('');
    try {
      const record = unwrap(await api.financeCall(taskId, 'chart-deliverable-open', { id }) as Answer<FinanceChart>);
      setOpened(record);
    } catch (failure) {
      setError(errorText(failure));
    } finally { setPending(false); }
  }
  const rows = opened?.series?.rows ?? [];
  const columns = rows[0] ? Object.keys(rows[0]) : [];
  return <aside className="analysis-chart-panel" aria-label="归档图"><details className="analysis-details">
    <summary><div className="analysis-section-heading"><h3>归档图</h3><span className="analysis-note">{charts.length ? `${charts.length} 张 · ` : ''}归档当前结果，不重新计算。</span></div></summary>
    <Button type="button" disabled={busy || pending || !latest} onClick={() => void archive()}>{pending ? '归档中…' : '归档当前结果图'}</Button>
    {charts.length ? <ul className="analysis-history-list">{charts.map((row) => <li key={row.id} className="analysis-history-row analysis-history-row--static">
      <span>{row.label || row.id}</span>
      <Button type="button" disabled={busy || pending} onClick={() => void open(row.id)}>打开</Button>
    </li>)}</ul> : <p className="analysis-note">还没有归档图。</p>}
    {opened && columns.length ? <table className="analysis-table"><thead><tr>{columns.map((name) => <th key={name}>{name}</th>)}</tr></thead>
      <tbody>{rows.map((row, index) => <tr key={index}>{columns.map((name) => <td key={name}>{textValue(row[name])}</td>)}</tr>)}</tbody></table> : null}
  </details>
    {message && <p role="status" className="analysis-message">{message}</p>}
    {error && <p role="alert" className="analysis-message analysis-message--error">{error}</p>}
  </aside>;
}
