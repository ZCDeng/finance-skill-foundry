import type { ReportDocument, ReportNode } from './model.js';
import { normalizeReportVisual } from './visuals.js';

/** Export identity belongs in the receipt, separate from the reader-facing figure. */
export function reportVisualEvidence(document: ReportDocument): string[] {
  const sources: string[] = [];
  const visit = (nodes: ReportNode[]) => nodes.forEach((node) => {
    if (node.type === 'reportVisual') {
      const visual = normalizeReportVisual(node.attrs?.visual);
      if (visual.kind !== 'flow') sources.push(`${visual.title}；归档图：${visual.chart_id}；计算：${visual.run_id}；快照 SHA-256：${visual.snapshot_hash}`);
    }
    visit(node.content ?? []);
  });
  visit(document.content);
  return sources;
}
