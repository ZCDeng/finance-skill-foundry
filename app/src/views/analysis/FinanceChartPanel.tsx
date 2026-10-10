import { useCallback, useEffect, useState } from 'react';
import { bridge, type Answer, type AnalysisRun } from '../../bridge.js';
import { textValue } from './presentation.js';
import { Button } from '../../components/ui/button.js';
import { unwrap, errorText } from './shared.js';
import { DisclosureSummary } from '../../components/Disclosure.js';
import { RankBars, type RankItem } from '../../components/charts/RankBars.js';
import { groupDigits } from '../../lib/figures.js';

type FinanceChart = {
  id: string;
  label?: string;
  run_id?: string;
  content_hash?: string;
  series?: { columns?: unknown[]; rows?: Record<string, unknown>[] };
};

const plainDecimal = (value: unknown) => (typeof value === 'number' && Number.isFinite(value)) || (typeof value === 'string' && /^[-+]?\d*\.?\d+$/.test(value.trim()));
/** Value columns a manager means first, before any other figure column. */
const preferredValues = ['actual', '实际', 'amount', '金额', 'value', '数值'];
/** An archived chart draws bars for at most this many rows; a longer series stays a table. */
const drawnRows = 30;

/**
 * The bars an archived series draws: one text column names the bars, one figure column sizes them (actual first).
 * A series without such a pair, or longer than a screen, is not drawn and reads as its table.
 */
export function archivedBars(rows: Record<string, unknown>[]): { category: string; value: string; items: RankItem[] } | null {
  if (!rows.length || rows.length > drawnRows) return null;
  const columns = Object.keys(rows[0]);
  const filled = (name: string) => rows.filter((row) => row[name] != null && row[name] !== '');
  const numeric = columns.filter((name) => filled(name).length === rows.length && rows.every((row) => plainDecimal(row[name])));
  const category = columns.find((name) => !numeric.includes(name) && filled(name).length === rows.length && rows.every((row) => typeof row[name] === 'string'));
  const value = preferredValues.find((name) => numeric.includes(name)) ?? numeric[0];
  if (!category || !value) return null;
  return { category, value, items: rows.map((row) => ({ label: String(row[category]), value: Number(row[value]), text: groupDigits(String(row[value]).trim()) })) };
}

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
  const bars = opened ? archivedBars(rows) : null;
  return <><details className="analysis-details analysis-chart-panel" aria-label="归档图">
    <DisclosureSummary>归档图<span className="analysis-note"> · {charts.length ? `${charts.length} 张，` : ''}归档当前结果，不重新计算</span></DisclosureSummary>
    <Button type="button" disabled={busy || pending || !latest} onClick={() => void archive()}>{pending ? '归档中…' : '归档当前结果图'}</Button>
    {charts.length ? <ul className="analysis-history-list">{charts.map((row) => <li key={row.id} className="analysis-history-row analysis-history-row--static">
      <span>{row.label || row.id}</span>
      <Button type="button" disabled={busy || pending} onClick={() => void open(row.id)}>打开</Button>
    </li>)}</ul> : <p className="analysis-note">还没有归档图。</p>}
    {bars && <RankBars title={`${opened?.label || '归档图'} · ${bars.value}`} items={bars.items} keepOrder />}
    {opened && columns.length ? (() => {
      const table = <table className="analysis-table"><thead><tr>{columns.map((name) => <th key={name}>{name}</th>)}</tr></thead>
        <tbody>{rows.map((row, index) => <tr key={index}>{columns.map((name) => <td key={name}>{textValue(row[name])}</td>)}</tr>)}</tbody></table>;
      // Drawn, the series stays one fold away; undrawable, it is the table as before.
      return bars ? <details className="analysis-details"><DisclosureSummary tone="quiet">图中数据 · {rows.length} 行</DisclosureSummary>{table}</details> : table;
    })() : null}
  </details>
    {message && <p role="status" className="analysis-message">{message}</p>}
    {error && <p role="alert" className="analysis-message analysis-message--error">{error}</p>}
  </>;
}
