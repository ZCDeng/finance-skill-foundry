import type { ReactNode } from 'react';
import { CircleAlert, CircleCheck, CircleDashed, CircleMinus } from 'lucide-react';
import type { AnalysisRun } from '../../bridge.js';
import { Figure } from '../../components/Figure.js';
import { DisclosureSummary } from '../../components/Disclosure.js';
import { decimalToFixed } from '../../lib/figures.js';
import { TechnicalInfo, type TechnicalRow } from './TechnicalInfo.js';

/**
 * 回款与现金: a collection_health finance run (foundry/collection_metrics.py) as a manager reads it.
 *
 * Every figure and every red/yellow/green light comes from the run; this view only orders and draws them. The
 * break-even collection rate is 1 − gross margin + expense ratio; below it, each 100 collected costs cash.
 */

export type HealthRow = {
  entity: string; metric_key: string; metric_label: string; scenario: string;
  value: string; unit: string | null; display_value: string;
  level: Level | null; level_label: string | null; estimate: boolean; formula: string; note: string;
};

type Level = 'red' | 'yellow' | 'green' | 'unknown';

export type SensitivityGrid = {
  entity: string; expense_ratio: string; gross_margins: string[]; collection_rates: string[]; cells: string[][];
  current: { gross_margin: string | null; collection_rate: string | null }; formula: string;
};

type HealthResult = { rows: HealthRow[]; sensitivity?: SensitivityGrid[]; diagnostics?: unknown[]; scenario_kind?: string };

export function isCollectionHealthRun(run: AnalysisRun): boolean {
  const result = run.result as (HealthResult & { columns?: unknown }) | undefined;
  return run.engine === 'finance' && result?.scenario_kind === 'collection_health' && Array.isArray(result.rows);
}

/** The columns of the 生死线 table, in the order a manager reads across. */
const POSITION_COLUMNS: { key: string; label: string }[] = [
  { key: 'gross_margin', label: '毛利率' },
  { key: 'expense_ratio', label: '期间费用率' },
  { key: 'break_even_collection', label: '生死线收缴率' },
  { key: 'collection_gap', label: '距生死线' },
  { key: 'dso', label: '应收天数' },
  { key: 'cash_collection_ratio', label: '现金回收比' },
  { key: 'impairment_to_gross_profit', label: '减值占毛利' },
];

const LEVEL_ICONS: Record<Level, typeof CircleAlert> = {
  red: CircleAlert, yellow: CircleMinus, green: CircleCheck, unknown: CircleDashed,
};

export function LevelMark({ level, label }: { level: Level | null; label: string | null }) {
  if (!level) return null;
  const Icon = LEVEL_ICONS[level];
  return <span className={`analysis-health-level analysis-health-level--${level}`}>
    <Icon size={13} strokeWidth={1.5} aria-hidden />{label ?? ''}
  </span>;
}

/** Period rows by entity and metric. */
function periodRows(rows: HealthRow[]): Map<string, Map<string, HealthRow>> {
  const byEntity = new Map<string, Map<string, HealthRow>>();
  for (const row of rows) {
    if (row.scenario !== '本期') continue;
    if (!byEntity.has(row.entity)) byEntity.set(row.entity, new Map());
    byEntity.get(row.entity)!.set(row.metric_key, row);
  }
  return byEntity;
}

function numeric(row?: HealthRow): number | null {
  if (!row) return null;
  const value = Number(row.value);
  return Number.isFinite(value) ? value : null;
}

/** The one-line reading the rows already say: how many units sit below their own break-even line. */
export function healthHeadline(rows: HealthRow[]): string | null {
  const gaps = [...periodRows(rows).values()].map((metrics) => metrics.get('collection_gap')).filter((row): row is HealthRow => Boolean(row));
  if (!gaps.length) return null;
  const below = gaps.filter((row) => (numeric(row) ?? 0) < 0);
  if (gaps.length === 1) {
    const [gap] = gaps;
    return below.length
      ? `${gap.entity}本年账单收缴率比生死线低 ${gap.display_value.replace(/^-/, '')}，每收 100 元倒贴现金`
      : `${gap.entity}本年账单收缴率在生死线以上 ${gap.display_value.replace(/^\+/, '')}`;
  }
  return below.length
    ? `${gaps.length} 个主体中 ${below.length} 个收缴率低于自身生死线`
    : `${gaps.length} 个主体的收缴率都在自身生死线以上`;
}

function PositionTable({ byEntity }: { byEntity: Map<string, Map<string, HealthRow>> }) {
  const entities = [...byEntity.entries()].sort(([, left], [, right]) =>
    (numeric(left.get('collection_gap')) ?? Infinity) - (numeric(right.get('collection_gap')) ?? Infinity));
  const shown = POSITION_COLUMNS.filter((column) => entities.some(([, metrics]) => metrics.has(column.key)));
  if (!shown.length) return null;
  return <div className="fnd-tablewrap">
    <table className="analysis-table analysis-health-table">
      <caption>生死线定位（按距生死线从低到高）</caption>
      <thead><tr><th scope="col">主体</th>{shown.map((column) => <th key={column.key} scope="col" className="fnd-num">{column.label}</th>)}</tr></thead>
      <tbody>{entities.map(([entity, metrics]) => <tr key={entity}>
        <th scope="row">{entity}</th>
        {shown.map((column) => {
          const row = metrics.get(column.key);
          return <td key={column.key} className="fnd-num">
            {row ? <><Figure text={row.display_value} />{row.level ? <LevelMark level={row.level} label={row.level_label} /> : null}</> : '—'}
          </td>;
        })}
      </tr>)}</tbody>
    </table>
  </div>;
}

/** Each unit at its gross margin and collection rate, against the break-even line at the median expense ratio. */
function PositionChart({ byEntity }: { byEntity: Map<string, Map<string, HealthRow>> }) {
  const points = [...byEntity.entries()].flatMap(([entity, metrics]) => {
    const margin = numeric(metrics.get('gross_margin'));
    const line = numeric(metrics.get('break_even_collection'));
    const gap = metrics.get('collection_gap');
    const expense = numeric(metrics.get('expense_ratio'));
    if (margin === null || line === null || !gap || expense === null) return [];
    return [{ entity, margin, rate: line + (numeric(gap) ?? 0), expense, gap }];
  });
  if (points.length < 2) return null;
  const expenses = points.map((point) => point.expense).sort((a, b) => a - b);
  const expense = expenses[Math.floor(expenses.length / 2)];
  const margins = points.map((point) => point.margin);
  const rates = points.map((point) => point.rate);
  const pad = (low: number, high: number) => [Math.floor(low - 2), Math.ceil(high + 2)];
  const [yMin, yMax] = pad(Math.min(...margins), Math.max(...margins));
  const [xMin, xMax] = pad(Math.min(...rates, 100 - yMax + expense), Math.max(...rates, 100 - yMin + expense));
  const width = 560, height = 320, left = 52, right = 16, top = 16, bottom = 40;
  const x = (rate: number) => left + ((rate - xMin) / (xMax - xMin)) * (width - left - right);
  const y = (margin: number) => top + (1 - (margin - yMin) / (yMax - yMin)) * (height - top - bottom);
  const ticks = (low: number, high: number) => {
    const step = Math.max(1, Math.ceil((high - low) / 5));
    return Array.from({ length: Math.floor((high - low) / step) + 1 }, (_, index) => low + index * step);
  };
  return <figure className="analysis-health-chart">
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`收缴率与毛利率散点，虚线为期间费用率 ${expense.toFixed(2)}% 下的生死线`}>
      {ticks(xMin, xMax).map((tick) => <g key={`x${tick}`}>
        <line className="analysis-health-grid" x1={x(tick)} x2={x(tick)} y1={top} y2={height - bottom} />
        <text className="analysis-health-tick" x={x(tick)} y={height - bottom + 16} textAnchor="middle">{tick}%</text>
      </g>)}
      {ticks(yMin, yMax).map((tick) => <g key={`y${tick}`}>
        <line className="analysis-health-grid" x1={left} x2={width - right} y1={y(tick)} y2={y(tick)} />
        <text className="analysis-health-tick" x={left - 8} y={y(tick) + 4} textAnchor="end">{tick}%</text>
      </g>)}
      <line className="analysis-health-line" x1={x(100 - yMin + expense)} y1={y(yMin)} x2={x(100 - yMax + expense)} y2={y(yMax)} />
      <text className="analysis-health-axis" x={(left + width - right) / 2} y={height - 6} textAnchor="middle">本年账单收缴率</text>
      <text className="analysis-health-axis" x={14} y={(top + height - bottom) / 2} textAnchor="middle" transform={`rotate(-90 14 ${(top + height - bottom) / 2})`}>毛利率</text>
      {points.map((point) => <circle key={point.entity} className={`analysis-health-dot analysis-health-dot--${point.gap.level ?? 'unknown'}`}
        cx={x(point.rate)} cy={y(point.margin)} r={5}>
        <title>{`${point.entity}：收缴率 ${point.rate.toFixed(2)}%，毛利率 ${point.margin.toFixed(2)}%，距生死线 ${point.gap.display_value}`}</title>
      </circle>)}
    </svg>
    <figcaption className="analysis-note">虚线是期间费用率取中位数 {expense.toFixed(2)}% 时的生死线；线左侧的点按自身费用率也可能在线上，以表格的距生死线为准。</figcaption>
  </figure>;
}

function SensitivityTable({ grid }: { grid: SensitivityGrid }) {
  const near = (value: string | null, candidates: string[]) => {
    if (value === null) return -1;
    const target = Number(value);
    let best = -1, distance = Infinity;
    candidates.forEach((candidate, index) => {
      const gap = Math.abs(Number(candidate) - target);
      if (gap < distance) { best = index; distance = gap; }
    });
    return best;
  };
  const row = near(grid.current.gross_margin, grid.gross_margins);
  const column = near(grid.current.collection_rate, grid.collection_rates);
  return <div className="fnd-tablewrap">
    <table className="analysis-table analysis-health-grid-table">
      <caption>{grid.entity}现金经营利润率（期间费用率 {decimalToFixed(grid.expense_ratio, 2, 100)}%，框出的格最接近当前位置）</caption>
      <thead><tr><th scope="col">毛利率 \ 收缴率</th>{grid.collection_rates.map((rate) => <th key={rate} scope="col" className="fnd-num">{decimalToFixed(rate, 1, 100)}%</th>)}</tr></thead>
      <tbody>{grid.gross_margins.map((margin, rowIndex) => <tr key={margin}>
        <th scope="row" className="fnd-num">{decimalToFixed(margin, 0, 100)}%</th>
        {grid.cells[rowIndex].map((cell, columnIndex) => {
          const value = Number(cell);
          const tone = value < 0 ? 'loss' : value < 0.03 ? 'edge' : 'gain';
          const current = rowIndex === row && columnIndex === column;
          return <td key={grid.collection_rates[columnIndex]}
            className={`fnd-num analysis-health-cell analysis-health-cell--${tone}${current ? ' analysis-health-cell--current' : ''}`}
            aria-current={current ? 'true' : undefined}>
            <Figure text={decimalToFixed(cell, 1, 100)} />
          </td>;
        })}
      </tr>)}</tbody>
    </table>
    <p className="analysis-note">{grid.formula}。负数表示每收 100 元要倒贴的现金。</p>
  </div>;
}

function DetailTable({ rows }: { rows: HealthRow[] }) {
  return <div className="fnd-tablewrap">
    <table className="analysis-table analysis-health-detail">
      <thead><tr><th scope="col">指标</th><th scope="col">口径</th><th scope="col" className="fnd-num">数值</th><th scope="col">筛查</th><th scope="col">说明</th></tr></thead>
      <tbody>{rows.map((row, index) => <tr key={`${row.metric_key}:${row.scenario}:${index}`}>
        <th scope="row"><span title={row.formula}>{row.metric_label}</span></th>
        <td>{row.scenario}</td>
        <td className="fnd-num"><Figure text={row.display_value} /></td>
        <td>{row.level ? <LevelMark level={row.level} label={row.level_label} /> : null}</td>
        <td className="analysis-health-note">{row.note}</td>
      </tr>)}</tbody>
    </table>
  </div>;
}

export function CollectionHealthView({ run, actions, technical }: { run: AnalysisRun; actions: ReactNode; technical: TechnicalRow[] }) {
  const result = run.result as unknown as HealthResult;
  const rows = result.rows;
  const byEntity = periodRows(rows);
  const headline = healthHeadline(rows);
  const entities = [...new Set(rows.map((row) => row.entity))];
  const diagnostics = result.diagnostics ?? [];
  const skipped = diagnostics.filter((item): item is { message: string } =>
    typeof item === 'object' && item !== null && (item as { code?: string }).code === 'collection_metric_skipped');
  return <section className="analysis-health" aria-label="回款与现金">
    {headline ? <p className="analysis-headline">{headline}</p> : null}
    <p className="analysis-note">红黄绿是筛查提示，不是结论；每个数都能在明细里看到公式和取数位置。</p>
    <PositionTable byEntity={byEntity} />
    <PositionChart byEntity={byEntity} />
    {(result.sensitivity ?? []).map((grid) => <SensitivityTable key={grid.entity} grid={grid} />)}
    {entities.map((entity, index) => <details key={entity} className="analysis-details" open={entities.length === 1 || index === 0}>
      <DisclosureSummary>{`${entity}的全部指标`}</DisclosureSummary>
      <DetailTable rows={rows.filter((row) => row.entity === entity)} />
    </details>)}
    {skipped.length ? <p className="analysis-note">{skipped.length === 1 ? skipped[0].message : `${skipped.length} 个主体各有指标缺取数，没有计算`}；缺哪些取数见技术信息，补上后重算即可。</p> : null}
    {actions}
    <TechnicalInfo rows={technical}>{skipped.length ? <ul className="analysis-note">{skipped.map((item, index) => <li key={index}>{item.message}</li>)}</ul> : null}</TechnicalInfo>
  </section>;
}
