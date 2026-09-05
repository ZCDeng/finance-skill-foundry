import { useState } from 'react';
import type { AnalysisParameterMetadata, AnalysisRun } from '../../bridge.js';
export const STATUS: Record<string, string> = {
  pending: '未运行', running: '运行中', succeeded: '运行成功', success: '运行成功', failed: '运行失败',
  verified: '可复算', reproducible: '可复算', unverified: '未验证复算', non_reproducible: '不可复算',
  unreviewed: '未阅', reviewed: '已阅', accepted: '经理认可', draft: '草稿', archived: '已归档',
};
export const textValue = (value: unknown): string => value == null ? '—' : typeof value === 'object'
  ? Object.entries(value).map(([key, item]) => `${key}：${textValue(item)}`).join(' · ')
  : String(value);
export function parameterSummary(parameters?: unknown[] | Record<string, unknown>, metadata: AnalysisParameterMetadata[] = []): string {
  const positional = Array.isArray(parameters);
  return Object.entries(parameters ?? {}).map(([key, value]) => {
    const parameterKey = positional ? String(Number(key) + 1) : key;
    const field = metadata.find((item) => item.key.toLowerCase() === parameterKey.toLowerCase());
    const label = field?.label ?? (positional ? `参数 ${parameterKey}` : key);
    return `${label}：${textValue(value)}${field?.unit ? ` ${field.unit}` : ''}`;
  }).join('；') || '—';
}
export function assumptionSummary(assumptions?: unknown[]): string {
  return (assumptions ?? []).map((item) => {
    if (item && typeof item === 'object' && !Array.isArray(item)) {
      const entry = item as Record<string, unknown>;
      const label = typeof entry.name === 'string' ? entry.name : entry.label;
      if (typeof label === 'string' && ('value' in entry || 'description' in entry)) {
        return `${label}：${textValue('value' in entry ? entry.value : entry.description)}`;
      }
    }
    return textValue(item);
  }).join('；') || '—';
}
export function Table({ columns, rows, caption }: {
  columns: { name: string; type?: string }[];
  rows: Record<string, unknown>[];
  caption: string;
}) {
  const [page, setPage] = useState(0);
  const pages = Math.max(1, Math.ceil(rows.length / 100));
  const current = Math.min(page, pages - 1);
  const visible = rows.slice(current * 100, (current + 1) * 100);
  const numeric = (type?: string) => /^(DECIMAL|NUMERIC|HUGEINT|UHUGEINT|UBIGINT|BIGINT|UINTEGER|INTEGER|USMALLINT|SMALLINT|UTINYINT|TINYINT|FLOAT|DOUBLE|REAL|INT\d*)\b/i.test(type ?? '');
  return <div className="fnd-tablewrap" tabIndex={0} role="region" aria-label={caption}>
    <table className="fnd-table analysis-table"><caption>{caption}</caption>
      <thead><tr>{columns.map((column) => <th className={numeric(column.type) ? 'analysis-number' : undefined} scope="col" key={column.name}>{column.name}</th>)}</tr></thead>
      <tbody>{visible.map((row, index) => <tr key={index}>{columns.map((column) =>
        <td className={numeric(column.type) ? 'analysis-number' : undefined} key={column.name}>{textValue(row[column.name])}</td>)}</tr>)}</tbody>
    </table>
    {rows.length === 0 && <p className="analysis-note">没有符合当前口径的行。</p>}
    {pages > 1 && <div className="analysis-actions"><button className="fnd-button" type="button" disabled={current === 0}
      onClick={() => setPage(current - 1)}>上一页</button><span className="analysis-note">第 {current + 1} / {pages} 页 · 共 {rows.length} 行</span>
      <button className="fnd-button" type="button" disabled={current === pages - 1} onClick={() => setPage(current + 1)}>下一页</button></div>}
  </div>;
}
export function RunStatus({ run }: { run: AnalysisRun }) {
  return <div className="analysis-status" aria-label="结果状态">
    <span>{STATUS[run.execution_status] ?? run.execution_status}</span>
    <span>{STATUS[run.reproducibility_status] ?? run.reproducibility_status}</span>
    <span>{STATUS[run.review_status] ?? run.review_status}</span>
    <span>{STATUS[run.publication_status] ?? run.publication_status}</span>
  </div>;
}
