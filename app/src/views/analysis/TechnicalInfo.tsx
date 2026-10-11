/**
 * Identifiers and digests, folded under one line. A manager never needs them to
 * read a result; support and the assistant do, so they stay reachable and exact.
 * They show only while 设置 › 显示技术信息 is on; the assistant reads them through
 * its own tools either way.
 */
import { useState, type ReactNode } from 'react';
import { DisclosureSummary } from '../../components/Disclosure.js';
import { Button } from '../../components/ui/button.js';
import { useTechnical } from '../../components/Preferences.js';

export type TechnicalRow = [label: string, value: unknown];

export function TechnicalInfo({ rows = [], summary = '技术信息', children, onToggle }: { rows?: TechnicalRow[]; summary?: string; children?: ReactNode; onToggle?(open: boolean): void }) {
  const technical = useTechnical();
  const shown = rows.filter(([, value]) => value != null && value !== '');
  if (!technical || (!shown.length && !children)) return null;
  return <details className="analysis-details analysis-technical" onToggle={(event) => onToggle?.(event.currentTarget.open)}><DisclosureSummary tone="quiet">{summary}</DisclosureSummary>
    {shown.length > 0 && <div className="analysis-technical-frame"><dl className="analysis-technical-list fnd-scroll-fade">{shown.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{String(value)}</dd></div>)}</dl></div>}
    {children}
  </details>;
}

/**
 * Beside an error while technical details are hidden: the ids and diagnostics behind it, copied as plain lines
 * to paste to the assistant or support. Nothing shows when there is nothing to copy or the details are on screen.
 */
export function CopyDiagnostics({ rows }: { rows: TechnicalRow[] }) {
  const technical = useTechnical();
  const [copied, setCopied] = useState(false);
  const shown = rows.filter(([, value]) => value != null && value !== '');
  if (technical || !shown.length) return null;
  const text = shown.map(([label, value]) => `${label}：${typeof value === 'string' ? value : JSON.stringify(value)}`).join('\n');
  return <Button variant="outline" size="sm" type="button" onClick={() => {
    void navigator.clipboard?.writeText(text).then(() => setCopied(true), () => setCopied(false));
  }}>{copied ? '已复制' : '复制诊断信息'}</Button>;
}
