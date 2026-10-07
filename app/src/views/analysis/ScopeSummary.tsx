import { joinParts } from '../../components/PeriodWords.js';
import { scopeParts } from './shared.js';

/** scopeSummary as a line on screen: the same words, with the period kept on one line. */
export function ScopeSummary({ scope }: { scope?: Record<string, unknown> }) {
  const parts = scopeParts(scope ?? {});
  if (!parts.length) return <>未限定</>;
  return <>{joinParts(parts.map(({ label, text, period }) => <>{label} {period ? <span className="fnd-period">{text}</span> : text}</>))}</>;
}
