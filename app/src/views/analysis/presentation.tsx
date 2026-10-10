import { useEffect, useId, useState, type ReactNode } from 'react';
import type { AnalysisParameterMetadata, AnalysisRun } from '../../bridge.js';
import { Figure } from '../../components/Figure.js';
import { Button } from '../../components/ui/button.js';
import { hasParenthesizedNegative, isFigureText, isMissingText } from '../../lib/figures.js';
import { formatRawFigure } from './businessResults.js';

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
export type TableColumn = {
  name: string;
  type?: string;
  /** How a cell shows; without one the cell is its text. */
  render?: (value: unknown, row: Record<string, unknown>) => ReactNode;
};
type TableGroup = { name: string; continued: boolean; rows: Record<string, unknown>[] };

const pageSize = 100;
const numericType = (type?: string) => /^(DECIMAL|NUMERIC|HUGEINT|UHUGEINT|UBIGINT|BIGINT|UINTEGER|INTEGER|USMALLINT|SMALLINT|UTINYINT|TINYINT|FLOAT|DOUBLE|REAL|INT\d*)\b/i.test(type ?? '');

type ShownCell = { node: ReactNode; text: string | null; raw?: string };

const plainDecimal = (value: unknown) => (typeof value === 'number' && Number.isFinite(value)) || (typeof value === 'string' && /^[+-]?\d+(?:\.\d+)?$/.test(value.trim()));

/**
 * Whether a column's raw values are quantities to format (6B): an engine number type, or text that is a plain decimal
 * in every row that has a value, as a script's 数值 column often is. A text column mixing words and digits stays.
 */
function rawFigureColumn(column: TableColumn, rows: Record<string, unknown>[]): number | null {
  if (column.render) return null;
  const present = rows.map((row) => row[column.name]).filter((value) => value != null && value !== '');
  if (!numericType(column.type) && !(present.length > 0 && present.every(plainDecimal))) return null;
  // The column's most places, so a whole number beside decimals is padded to line up.
  return Math.max(0, ...present.filter(plainDecimal).map((value) => String(value).trim().split('.')[1]?.length ?? 0));
}

/** One cell before layout: a render's own node, else the value with a raw figure formatted (6B) and its original kept. */
function shownCell(column: TableColumn, row: Record<string, unknown>, columnPlaces: number | null): ShownCell {
  const value = row[column.name];
  if (column.render) {
    const node = column.render(value, row);
    return { node, text: typeof node === 'string' ? node : null };
  }
  const formatted = columnPlaces == null ? null : formatRawFigure(value, column.name, columnPlaces);
  const text = formatted ?? textValue(value);
  return { node: text, text, raw: formatted != null && formatted !== String(value) ? String(value) : undefined };
}

/** A column of figures: its engine type says so, or every value it shows is a figure (差异率, a script's 数值). */
function figureColumn(column: TableColumn, cells: ShownCell[]): boolean {
  if (numericType(column.type)) return true;
  const texts = cells.map((cell) => cell.text);
  if (texts.some((text) => text == null)) return false;
  const present = (texts as string[]).filter((text) => !isMissingText(text));
  return present.length > 0 && present.every(isFigureText);
}

/** 合计/总计 rows at the total weight, 小计 at the subtotal weight, by the row's first cell: three weights per table. */
function rowWeight(first: ShownCell | undefined): string | undefined {
  const text = first?.text?.trim() ?? '';
  if (/^(?:合计|总计|总额|total\b)/i.test(text)) return 'analysis-row--total';
  if (/^(?:小计|subtotal\b)/i.test(text)) return 'analysis-row--subtotal';
  return undefined;
}

/** A group's name; a missing one (null or empty) reads as the fallback. */
function groupName(value: unknown, fallback: string): string {
  return value == null || value === '' ? fallback : String(value);
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

/**
 * Whether columns sit to the right of what the scroll area shows: the table is wider than its area and the area is
 * not scrolled to its right end. Without ResizeObserver it never says so.
 */
function useOverflow(enabled: boolean): [(node: HTMLDivElement | null) => void, boolean] {
  const [node, setNode] = useState<HTMLDivElement | null>(null);
  const [overflowing, setOverflowing] = useState(false);
  useEffect(() => {
    if (!enabled || !node || typeof ResizeObserver === 'undefined') return;
    const measure = () => setOverflowing(node.scrollLeft + node.clientWidth < node.scrollWidth - 1);
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    const table = node.querySelector('table');
    if (table) observer.observe(table);
    node.addEventListener('scroll', measure, { passive: true });
    measure();
    return () => { observer.disconnect(); node.removeEventListener('scroll', measure); };
  }, [enabled, node]);
  return [setNode, enabled && overflowing];
}

export function Table({ columns, rows, caption, groupBy, groupFallback = '', scrollHint = false, exact = false, figure }: {
  columns: TableColumn[];
  rows: Record<string, unknown>[];
  caption: string;
  /** A column whose value groups the rows under one rowgroup heading each; that column is not among columns. */
  groupBy?: string;
  /** The heading of rows that have no value in groupBy. */
  groupFallback?: string;
  /** Say below the table, in words, that more columns sit to the right when it is wider than its area. */
  scrollHint?: boolean;
  /** Values that are, or will be, cell contents as written (a workbook read, a write-back preview): set as figures
   * but never reformatted, rounded or put in parentheses. */
  exact?: boolean;
  /** Draws a figure cell another way (a figure that opens its source); without one, or when it gives nothing back,
   * the cell is the plain figure. */
  figure?(row: Record<string, unknown>, column: TableColumn, text: string, hang: boolean): ReactNode | undefined;
}) {
  const [page, setPage] = useState(0);
  const [measured, overflowing] = useOverflow(scrollHint);
  const hintId = useId();
  const pages = Math.max(1, Math.ceil(rows.length / pageSize));
  const current = Math.min(page, pages - 1);
  const formatRaw = columns.map((column) => exact ? null : rawFigureColumn(column, rows));
  const shown = new Map(rows.map((item) => [item, columns.map((column, index) => shownCell(column, item, formatRaw[index]))]));
  const figures = columns.map((column, index) => figureColumn(column, rows.map((item) => shown.get(item)![index])));
  const hangs = columns.map((_, index) => !exact && figures[index] && hasParenthesizedNegative(rows.flatMap((item) => shown.get(item)![index].text ?? [])));
  const row = (item: Record<string, unknown>, index: number) => {
    const cells = shown.get(item)!;
    return <tr key={index} className={rowWeight(cells[0])}>{columns.map((column, at) => {
      const cell = cells[at];
      return <td className={figures[at] ? 'analysis-number' : undefined} key={column.name} title={cell.raw}>
        {figures[at] && cell.text != null ? figure?.(item, column, cell.text, hangs[at]) ?? <Figure text={cell.text} hang={hangs[at]} exact={exact} /> : cell.node}</td>;
    })}</tr>;
  };
  const body = groupBy == null
    ? <tbody>{rows.slice(current * pageSize, (current + 1) * pageSize).map(row)}</tbody>
    : (groupedPages(rows, groupBy, groupFallback)[current] ?? []).map((group, index) => <tbody key={`${index}:${group.name}`}>
      <tr><th scope="rowgroup" colSpan={columns.length}><span>{group.continued ? `${group.name}（续）` : group.name}</span></th></tr>
      {group.rows.map(row)}
    </tbody>);
  return <div className="fnd-tablewrap" tabIndex={0} role="region" aria-label={caption} ref={measured} aria-describedby={overflowing ? hintId : undefined}>
    <table className="fnd-table analysis-table"><caption>{caption}</caption>
      <thead><tr>{columns.map((column, index) => <th className={figures[index] ? 'analysis-number' : undefined} scope="col" key={column.name}>{column.name}</th>)}</tr></thead>
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
