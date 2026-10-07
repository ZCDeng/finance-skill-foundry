import { Fragment, type ReactNode } from 'react';
import { formatPeriod } from '../lib/period.js';

/**
 * A period in words that never breaks across lines (2026 年 1–8 月 stays whole);
 * the line around it still wraps at its separators. Nothing when there is no period.
 */
export function PeriodWords({ value }: { value: unknown }) {
  const words = formatPeriod(value);
  return words ? <span className="fnd-period">{words}</span> : null;
}

/** Display segments joined by 「 · 」, skipping empty ones; each segment may hold a PeriodWords. */
export function joinParts(parts: ReactNode[], separator = ' · '): ReactNode {
  return parts.filter((part) => part != null && part !== false && part !== '')
    .map((part, index) => <Fragment key={index}>{index ? separator : null}{part}</Fragment>);
}
