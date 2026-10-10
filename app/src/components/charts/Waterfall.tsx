import { accountingFigure } from '../../lib/figures.js';
import { extent, linear, niceTicks, tickText } from './scale.js';
import './charts.css';

/**
 * One bar of a bridge. A `total` stands on zero (预算利润, 实际利润); a `delta` floats from where the bridge stands to
 * where it moves (收入 +, 成本 −). `value` is for the geometry; `text` is the figure as the caller wrote it.
 */
export type BridgeStep = { label: string; kind: 'total' | 'delta'; value: number; text: string };

export type BridgeBar = BridgeStep & { from: number; to: number };

/** Where each bar starts and ends. A total resets the level; a delta moves it. */
export function bridgeBars(steps: BridgeStep[]): BridgeBar[] {
  let level = 0;
  return steps.map((step) => {
    const from = step.kind === 'total' ? 0 : level;
    const to = step.kind === 'total' ? step.value : level + step.value;
    level = to;
    return { ...step, from, to };
  });
}

/**
 * Whether the deltas carry the first total to the last one, to a tolerance of half a cent per step. A bridge that
 * does not close is not drawn: the table below it says what is missing.
 */
export function bridgeCloses(steps: BridgeStep[]): boolean {
  const totals = steps.filter((step) => step.kind === 'total');
  if (totals.length < 2 || steps[0]?.kind !== 'total' || steps.at(-1)?.kind !== 'total') return false;
  const moved = steps.slice(1, -1).reduce((sum, step) => sum + (step.kind === 'delta' ? step.value : 0), 0);
  return Math.abs(steps[0].value + moved - steps.at(-1)!.value) <= 0.005 * steps.length;
}

const WIDTH = 560;
const HEIGHT = 240;
const LEFT = 64;
const RIGHT = 16;
const TOP = 24;
const BOTTOM = 40;

/**
 * A bridge (瀑布图): from one total to another through the changes between them. A rise to profit is drawn in the
 * level-ok green, a fall in the negative red, totals in ink; every bar carries its figure, so colour never speaks
 * alone.
 */
export function Waterfall({ title, steps, unit }: { title: string; steps: BridgeStep[]; unit?: string }) {
  const bars = bridgeBars(steps);
  const { domain, ticks } = niceTicks(extent(bars.flatMap((bar) => [bar.from, bar.to]), true), 4);
  const step = ticks.length > 1 ? ticks[1] - ticks[0] : 1;
  const y = linear(domain, [HEIGHT - BOTTOM, TOP]);
  const band = (WIDTH - LEFT - RIGHT) / Math.max(1, bars.length);
  const barWidth = Math.min(56, band * 0.6);
  const center = (index: number) => LEFT + band * index + band / 2;
  const summary = `${title}：${bars.map((bar) => `${bar.label} ${bar.text}`).join('，')}${unit ? `（${unit}）` : ''}`;
  return <figure className="fnd-chart-figure">
    <svg className="fnd-chart fnd-waterfall" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label={summary}>
      {ticks.map((tick) => <g key={tick}>
        <line className={tick === 0 ? 'fnd-chart__zero' : 'fnd-chart__grid'} x1={LEFT} x2={WIDTH - RIGHT} y1={y(tick)} y2={y(tick)} />
        <text className="fnd-chart__tick" x={LEFT - 8} y={y(tick) + 4} textAnchor="end">{tickText(tick, step)}</text>
      </g>)}
      {bars.map((bar, index) => {
        const top = Math.min(y(bar.from), y(bar.to));
        const height = Math.max(1, Math.abs(y(bar.from) - y(bar.to)));
        const tone = bar.kind === 'total' ? 'total' : bar.value < 0 ? 'down' : 'up';
        const shown = accountingFigure(bar.text);
        const above = bar.kind === 'total' ? bar.to >= 0 : bar.value >= 0;
        const next = bars[index + 1];
        return <g key={`${bar.label}:${index}`}>
          <rect className={`fnd-waterfall__bar fnd-waterfall__bar--${tone}`} x={center(index) - barWidth / 2} y={top} width={barWidth} height={height}>
            <title>{`${bar.label} ${bar.text}`}</title>
          </rect>
          {next && next.kind === 'delta' && <line className="fnd-waterfall__link" x1={center(index) + barWidth / 2} x2={center(index + 1) - barWidth / 2} y1={y(bar.to)} y2={y(bar.to)} />}
          <text className="fnd-chart__value" data-negative={shown.negative || undefined} x={center(index)}
            y={above ? top - 6 : top + height + 14} textAnchor="middle">{shown.text}</text>
          <text className="fnd-chart__label" x={center(index)} y={HEIGHT - BOTTOM + 20} textAnchor="middle">{bar.label}</text>
        </g>;
      })}
    </svg>
    {unit ? <figcaption className="fnd-chart-figure__note">单位：{unit}</figcaption> : null}
  </figure>;
}
