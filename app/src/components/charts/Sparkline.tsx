import { accountingFigure } from '../../lib/figures.js';
import { extent, linear, type Domain } from './scale.js';
import './charts.css';

/** One point of a series: its label (a month), its value for the geometry, and its figure as written. */
export type SeriesPoint = { label: string; value: number | null; text: string };

const PAD = 3;

/** The line's pieces: a missing value or a declared break (a 口径 change) ends one and starts the next. */
export function segments(points: SeriesPoint[], breaks: number[] = []): { index: number; value: number }[][] {
  const out: { index: number; value: number }[][] = [];
  let current: { index: number; value: number }[] = [];
  points.forEach((point, index) => {
    if (breaks.includes(index) && current.length) { out.push(current); current = []; }
    if (point.value == null || !Number.isFinite(point.value)) {
      if (current.length) { out.push(current); current = []; }
      return;
    }
    current.push({ index, value: point.value });
  });
  if (current.length) out.push(current);
  return out;
}

/** What a screen reader hears instead of the line: where it starts, where it ends, its high and its low. */
export function seriesSummary(title: string, points: SeriesPoint[]): string {
  const shown = points.filter((point) => point.value != null && Number.isFinite(point.value));
  if (!shown.length) return `${title}：没有数值`;
  const first = shown[0];
  const last = shown.at(-1)!;
  const high = shown.reduce((best, point) => (point.value! > best.value! ? point : best));
  const low = shown.reduce((best, point) => (point.value! < best.value! ? point : best));
  const ends = shown.length > 1 ? `从${first.label} ${first.text} 到${last.label} ${last.text}` : `${last.label} ${last.text}`;
  return shown.length > 2 ? `${title}：${ends}，最高${high.label} ${high.text}，最低${low.label} ${low.text}` : `${title}：${ends}`;
}

/**
 * A word-sized line of one series (DESIGN.md 图表): no axes, a dot on the last value, a gap where a value is missing
 * or the 口径 changed. `domain` is shared when several sparklines are read against each other.
 */
export function Sparkline({ title, points, breaks = [], domain, width: WIDTH = 120, height: HEIGHT = 32 }: {
  title: string; points: SeriesPoint[]; breaks?: number[]; domain?: Domain;
  /** The drawing's size in CSS pixels; a wider one (a small-multiples cell) keeps the same stroke and dots. */
  width?: number; height?: number;
}) {
  const span = domain ?? extent(points.map((point) => point.value));
  const x = linear([0, Math.max(1, points.length - 1)], [PAD, WIDTH - PAD]);
  const y = linear(span, [HEIGHT - PAD, PAD]);
  const pieces = segments(points, breaks);
  const last = pieces.at(-1)?.at(-1);
  const zero = span[0] < 0 && span[1] > 0 ? y(0) : null;
  return <svg className="fnd-chart fnd-sparkline" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} style={{ maxWidth: WIDTH }} role="img" aria-label={seriesSummary(title, points)}>
    {zero != null && <line className="fnd-chart__zero" x1={0} x2={WIDTH} y1={zero} y2={zero} />}
    {pieces.map((piece, index) => piece.length === 1
      ? <circle key={index} className="fnd-sparkline__dot" cx={x(piece[0].index)} cy={y(piece[0].value)} r={1.5} />
      : <polyline key={index} className="fnd-sparkline__line" points={piece.map((point) => `${x(point.index)},${y(point.value)}`).join(' ')} />)}
    {last && <circle className="fnd-sparkline__last" data-negative={accountingFigure(points[last.index].text).negative || undefined}
      cx={x(last.index)} cy={y(last.value)} r={2.5} />}
    {points.map((point, index) => point.value == null ? null : <circle key={`hit${index}`} className="fnd-chart__hit" cx={x(index)} cy={y(point.value)} r={4}>
      <title>{`${point.label} ${point.text}`}</title>
    </circle>)}
  </svg>;
}
