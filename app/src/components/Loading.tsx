import { useEffect, useState, type ReactNode } from 'react';
import { Skeleton } from './ui/skeleton.js';

/**
 * A read in progress: the shape of what is coming, drawn in skeleton blocks,
 * in place of a bare 正在读取… line. The words stay as the status for screen
 * readers, hidden from view. The blocks wait `delay` ms before they show, so a
 * quick read does not flash grey; actions that compute or save keep WaitLoop.
 */
export function Loading({ label, delay = 300, className, children }: {
  label: string; delay?: number; className?: string; children: ReactNode;
}) {
  const [shown, setShown] = useState(delay <= 0);
  useEffect(() => {
    if (delay <= 0) return;
    const timer = setTimeout(() => setShown(true), delay);
    return () => clearTimeout(timer);
  }, [delay]);
  return <div role="status" className={className ? `fnd-loading ${className}` : 'fnd-loading'} data-shown={shown ? 'yes' : 'no'}>
    <span className="fnd-loading__label">{label}</span>
    {shown ? children : null}
  </div>;
}

/** List rows: a name line and, with `meta`, a shorter line of details under it. */
export function SkeletonRows({ rows = 3, meta = true }: { rows?: number; meta?: boolean }) {
  return <div className="fnd-skeleton-rows" aria-hidden>
    {Array.from({ length: rows }, (_, index) => <div key={index} className="fnd-skeleton-row">
      <Skeleton className="fnd-skeleton--line" style={{ width: `${[56, 44, 64, 50, 38][index % 5]}%` }} />
      {meta ? <Skeleton className="fnd-skeleton--meta" style={{ width: `${[32, 26, 36, 28, 22][index % 5]}%` }} /> : null}
    </div>)}
  </div>;
}

/** A headline line and a row of summary cards, the shape of a result page. */
export function SkeletonCards({ cards = 3, headline = true }: { cards?: number; headline?: boolean }) {
  return <div className="fnd-skeleton-result" aria-hidden>
    {headline ? <Skeleton className="fnd-skeleton--headline" /> : null}
    <div className="fnd-skeleton-cards">{Array.from({ length: cards }, (_, index) => <Skeleton key={index} className="fnd-skeleton--card" />)}</div>
  </div>;
}
