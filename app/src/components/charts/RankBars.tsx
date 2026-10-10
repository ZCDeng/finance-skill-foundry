import { accountingFigure } from '../../lib/figures.js';
import { extent, linear } from './scale.js';
import './charts.css';

export type RankItem = { label: string; value: number; text: string; note?: string };

const ROW = 24;
const LABEL = 112;
const VALUE = 88;
const WIDTH = 560;

/**
 * Objects side by side on one measure (城市公司 by 距生死线), longest first unless `keepOrder`. Bars below zero run
 * left of the zero line in the negative red; a `reference` (生死线, a target) is a dashed line with its own label.
 */
export function RankBars({ title, items, reference, keepOrder = false }: {
  title: string; items: RankItem[]; reference?: { value: number; label: string }; keepOrder?: boolean;
}) {
  const rows = keepOrder ? items : [...items].sort((a, b) => b.value - a.value);
  const domain = extent([...rows.map((item) => item.value), ...(reference ? [reference.value] : [])], true);
  const x = linear(domain, [LABEL + 8, WIDTH - VALUE]);
  const height = rows.length * ROW + (reference ? ROW : 8);
  const zero = x(0);
  return <figure className="fnd-chart-figure">
    <svg className="fnd-chart fnd-rank-bars" viewBox={`0 0 ${WIDTH} ${height}`} role="img"
      aria-label={`${title}：${rows.map((item) => `${item.label} ${item.text}`).join('，')}`}>
      <line className="fnd-chart__zero" x1={zero} x2={zero} y1={0} y2={rows.length * ROW} />
      {rows.map((item, index) => {
        const shown = accountingFigure(item.text);
        const left = Math.min(zero, x(item.value));
        const top = index * ROW + 4;
        return <g key={`${item.label}:${index}`}>
          <text className="fnd-chart__label" x={LABEL} y={top + 12} textAnchor="end">{item.label.length > 8 ? `${item.label.slice(0, 7)}…` : item.label}<title>{item.label}</title></text>
          <rect className={`fnd-rank-bars__bar${item.value < 0 ? ' fnd-rank-bars__bar--negative' : ''}`} x={left} y={top} width={Math.max(1, Math.abs(x(item.value) - zero))} height={ROW - 8}>
            <title>{`${item.label} ${item.text}${item.note ? ` · ${item.note}` : ''}`}</title>
          </rect>
          <text className="fnd-chart__value" data-negative={shown.negative || undefined} x={WIDTH - VALUE + 8} y={top + 12}>{shown.text}</text>
        </g>;
      })}
      {reference && <g>
        <line className="fnd-chart__reference" x1={x(reference.value)} x2={x(reference.value)} y1={0} y2={rows.length * ROW} />
        <text className="fnd-chart__label" x={x(reference.value)} y={rows.length * ROW + 16} textAnchor="middle">{reference.label}</text>
      </g>}
    </svg>
  </figure>;
}
