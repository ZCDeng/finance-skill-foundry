/**
 * Identifiers and digests, folded under one line. A manager never needs them to
 * read a result; support and the assistant do, so they stay reachable and exact.
 */
export type TechnicalRow = [label: string, value: unknown];

export function TechnicalInfo({ rows, summary = '技术信息' }: { rows: TechnicalRow[]; summary?: string }) {
  const shown = rows.filter(([, value]) => value != null && value !== '');
  if (!shown.length) return null;
  return <details className="analysis-details analysis-technical"><summary>{summary}</summary>
    <dl className="analysis-technical-list">{shown.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{String(value)}</dd></div>)}</dl>
  </details>;
}
