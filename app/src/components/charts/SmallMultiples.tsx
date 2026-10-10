import { Figure } from '../Figure.js';
import { extent } from './scale.js';
import { Sparkline, type SeriesPoint } from './Sparkline.js';
import './charts.css';

/**
 * The same series for many objects (50 城市公司), one sparkline each on one shared scale, so a taller line is a larger
 * value and not just a busier company. The latest figure stands beside each name.
 */
export function SmallMultiples({ title, series }: { title: string; series: { label: string; points: SeriesPoint[]; breaks?: number[] }[] }) {
  const domain = extent(series.flatMap((item) => item.points.map((point) => point.value)));
  return <ul className="fnd-small-multiples" aria-label={title}>
    {series.map((item) => {
      const last = [...item.points].reverse().find((point) => point.value != null);
      return <li key={item.label} className="fnd-small-multiples__cell">
        <span className="fnd-small-multiples__label" title={item.label}>{item.label}</span>
        <span className="fnd-small-multiples__value">{last ? <Figure text={last.text} /> : '—'}</span>
        <Sparkline title={item.label} points={item.points} breaks={item.breaks} domain={domain} width={200} height={36} />
      </li>;
    })}
  </ul>;
}
