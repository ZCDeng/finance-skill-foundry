/**
 * The arithmetic every in-app chart shares: a linear scale and round ticks. Geometry only: a figure's label is the
 * text its caller wrote (exact, grouped, in accounting form), never a number this file formatted.
 */

export type Domain = [low: number, high: number];

/** The smallest domain holding every value, and zero when `withZero`: a bar starts at zero or it lies. */
export function extent(values: (number | null | undefined)[], withZero = false): Domain {
  const finite = values.filter((value): value is number => typeof value === 'number' && Number.isFinite(value));
  let low = finite.length ? Math.min(...finite) : 0;
  let high = finite.length ? Math.max(...finite) : 0;
  if (withZero) { low = Math.min(low, 0); high = Math.max(high, 0); }
  if (low === high) {
    // One value (or all equal): give it room on both sides so it does not sit on an edge.
    const pad = low === 0 ? 1 : Math.abs(low) * 0.1;
    return withZero && low >= 0 ? [0, high + pad] : withZero && high <= 0 ? [low - pad, 0] : [low - pad, high + pad];
  }
  return [low, high];
}

/** A step of 1, 2 or 5 times a power of ten that cuts the domain into about `count` parts. */
export function niceStep(domain: Domain, count = 4): number {
  const span = Math.abs(domain[1] - domain[0]) || 1;
  const raw = span / Math.max(1, count);
  const power = 10 ** Math.floor(Math.log10(raw));
  const unit = raw / power;
  return (unit <= 1 ? 1 : unit <= 2 ? 2 : unit <= 5 ? 5 : 10) * power;
}

/** The domain widened to whole steps, and the ticks on it. */
export function niceTicks(domain: Domain, count = 4): { domain: Domain; ticks: number[] } {
  const step = niceStep(domain, count);
  const low = Math.floor(domain[0] / step) * step;
  const high = Math.ceil(domain[1] / step) * step;
  const ticks: number[] = [];
  for (let value = low; value <= high + step / 2; value += step) ticks.push(Number(value.toPrecision(12)));
  return { domain: [low, high], ticks };
}

/** Maps a domain onto a pixel range; a reversed range (bottom to top) is how a y axis reads. */
export function linear(domain: Domain, range: [number, number]): (value: number) => number {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  const span = d1 - d0 || 1;
  return (value: number) => r0 + ((value - d0) / span) * (r1 - r0);
}

/** A tick as the axis writes it: thousands grouped, no more places than the step needs. */
export function tickText(value: number, step: number): string {
  const places = Math.max(0, Math.min(4, -Math.floor(Math.log10(Math.abs(step) || 1))));
  const fixed = Math.abs(value).toFixed(places);
  const [whole, fraction] = fixed.split('.');
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return `${value < 0 && Number(fixed) !== 0 ? '-' : ''}${grouped}${fraction ? `.${fraction}` : ''}`;
}
