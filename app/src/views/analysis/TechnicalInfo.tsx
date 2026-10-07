/**
 * Identifiers and digests, folded under one line. A manager never needs them to
 * read a result; support and the assistant do, so they stay reachable and exact.
 */
import type { ReactNode } from 'react';
import { DisclosureSummary } from '../../components/Disclosure.js';

export type TechnicalRow = [label: string, value: unknown];

export function TechnicalInfo({ rows = [], summary = '技术信息', children, onToggle }: { rows?: TechnicalRow[]; summary?: string; children?: ReactNode; onToggle?(open: boolean): void }) {
  const shown = rows.filter(([, value]) => value != null && value !== '');
  if (!shown.length && !children) return null;
  return <details className="analysis-details analysis-technical" onToggle={(event) => onToggle?.(event.currentTarget.open)}><DisclosureSummary tone="quiet">{summary}</DisclosureSummary>
    {shown.length > 0 && <dl className="analysis-technical-list">{shown.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{String(value)}</dd></div>)}</dl>}
    {children}
  </details>;
}
