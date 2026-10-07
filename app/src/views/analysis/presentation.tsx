import { useEffect, useId, useState, type ReactNode } from 'react';
import type { AnalysisParameterMetadata, AnalysisRun } from '../../bridge.js';
import { Button } from '../../components/ui/button.js';

export const STATUS: Record<string, string> = {
  pending: '未计算', running: '计算中', succeeded: '计算成功', success: '计算成功', failed: '计算失败',
  verified: '可复算', reproducible: '可复算', unverified: '未验证复算', non_reproducible: '不可复算',
  unreviewed: '未阅', reviewed: '已阅', accepted: '经理认可', draft: '草稿', archived: '已归档',
};
/** A draft revision's state in the words the 文稿 toolbar uses: 草稿 · 未阅. */
export function draftStateText(row: { publication_status: string; review_status: string }): string {
  return `${STATUS[row.publication_status] ?? row.publication_status} · ${STATUS[row.review_status] ?? row.review_status}`;
}
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
  const parts = (assumptions ?? []).map((item) => {
    if (item && typeof item === 'object' && !Array.isArray(item)) {
      const entry = item as Record<string, unknown>;
      const label = typeof entry.name === 'string' ? entry.name : entry.label;
      if (typeof label === 'string' && ('value' in entry || 'description' in entry)) {
        return `${label}：${textValue('value' in entry ? entry.value : entry.description)}`;
      }
    }
    return textValue(item);
  });
  // Each item may end on its own 。 or ；; joined with ； that reads 。；, so all but the last lose it. ASCII full stops stay.
  return parts.map((part, index) => index < parts.length - 1 ? part.trimEnd().replace(/[。；;]+$/, '') : part).join('；') || '—';
}
type TableColumn = {
  name: string;
  type?: string;
  /** How a cell shows; without one the cell is its text. */
  render?: (value: unknown, row: Record<string, unknown>) => ReactNode;
};
type TableGroup = { name: string; continued: boolean; rows: Record<string, unknown>[] };

const pageSize = 100;

/** A group's name; a missing one (empty, or the missing-value dash a formatted row carries) reads as the fallback. */
function groupName(value: unknown, fallback: string): string {
  return value == null || value === '' || value === '—' ? fallback : String(value);
}

/**
 * Rows grouped by one column, in the order each group first appears and each group's rows in their own order, then
 * cut into pages. A page's groups each become one tbody; a group carried over from the page before says （续）.
 */
function groupedPages(rows: Record<string, unknown>[], groupBy: string, fallback: string): TableGroup[][] {
  const groups = new Map<string, Record<string, unknown>[]>();
  for (const row of rows) {
    const name = groupName(row[groupBy], fallback);
    groups.set(name, [...(groups.get(name) ?? []), row]);
  }
  const ordered = [...groups].flatMap(([name, members]) => members.map((row) => ({ name, row })));
  const pages: TableGroup[][] = [];
  for (let start = 0; start < ordered.length; start += pageSize) {
    const page: TableGroup[] = [];
    for (const [index, { name, row }] of ordered.slice(start, start + pageSize).entries()) {
      const last = page.at(-1);
      if (last?.name === name) last.rows.push(row);
      else page.push({ name, continued: index === 0 && start > 0 && ordered[start - 1].name === name, rows: [row] });
    }
    pages.push(page);
  }
  return pages;
}

/** Whether the table is wider than its scroll area. Without ResizeObserver (jsdom) it never says so. */
function useOverflow(enabled: boolean): [(node: HTMLDivElement | null) => void, boolean] {
  const [node, setNode] = useState<HTMLDivElement | null>(null);
  const [overflowing, setOverflowing] = useState(false);
  useEffect(() => {
    if (!enabled || !node || typeof ResizeObserver === 'undefined') return;
    const measure = () => setOverflowing(node.scrollWidth > node.clientWidth);
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    const table = node.querySelector('table');
    if (table) observer.observe(table);
    measure();
    return () => observer.disconnect();
  }, [enabled, node]);
  return [setNode, enabled && overflowing];
}

export function Table({ columns, rows, caption, groupBy, groupFallback = '', scrollHint = false }: {
  columns: TableColumn[];
  rows: Record<string, unknown>[];
  caption: string;
  /** A column whose value groups the rows under one rowgroup heading each; that column is not among columns. */
  groupBy?: string;
  /** The heading of rows that have no value in groupBy. */
  groupFallback?: string;
  /** Say below the table, in words, that more columns sit to the right when it is wider than its area. */
  scrollHint?: boolean;
}) {
  const [page, setPage] = useState(0);
  const [measured, overflowing] = useOverflow(scrollHint);
  const hintId = useId();
  const pages = Math.max(1, Math.ceil(rows.length / pageSize));
  const current = Math.min(page, pages - 1);
  const numeric = (type?: string) => /^(DECIMAL|NUMERIC|HUGEINT|UHUGEINT|UBIGINT|BIGINT|UINTEGER|INTEGER|USMALLINT|SMALLINT|UTINYINT|TINYINT|FLOAT|DOUBLE|REAL|INT\d*)\b/i.test(type ?? '');
  const row = (item: Record<string, unknown>, index: number) => <tr key={index}>{columns.map((column) =>
    <td className={numeric(column.type) ? 'analysis-number' : undefined} key={column.name}>{column.render ? column.render(item[column.name], item) : textValue(item[column.name])}</td>)}</tr>;
  const body = groupBy == null
    ? <tbody>{rows.slice(current * pageSize, (current + 1) * pageSize).map(row)}</tbody>
    : (groupedPages(rows, groupBy, groupFallback)[current] ?? []).map((group, index) => <tbody key={`${index}:${group.name}`}>
      <tr><th scope="rowgroup" colSpan={columns.length}><span>{group.continued ? `${group.name}（续）` : group.name}</span></th></tr>
      {group.rows.map(row)}
    </tbody>);
  return <div className="fnd-tablewrap" tabIndex={0} role="region" aria-label={caption} ref={measured} aria-describedby={overflowing ? hintId : undefined}>
    <table className="fnd-table analysis-table"><caption>{caption}</caption>
      <thead><tr>{columns.map((column) => <th className={numeric(column.type) ? 'analysis-number' : undefined} scope="col" key={column.name}>{column.name}</th>)}</tr></thead>
      {body}
    </table>
    {overflowing && <p className="analysis-note analysis-table-scroll-hint" id={hintId}>右侧还有列，可横向滚动查看</p>}
    {rows.length === 0 && <p className="analysis-note">没有符合当前范围的行。</p>}
    {pages > 1 && <div className="analysis-actions"><Button variant="outline" type="button" disabled={current === 0}
      onClick={() => setPage(current - 1)}>上一页</Button><span className="analysis-note">第 {current + 1} / {pages} 页 · 共 {rows.length} 行</span>
      <Button variant="outline" type="button" disabled={current === pages - 1} onClick={() => setPage(current + 1)}>下一页</Button></div>}
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
