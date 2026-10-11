import type { LucideIcon } from 'lucide-react';
import './components.css';

/** The four parts of a task, as the six steps group them: 月结 (1–3), 财务分析, 经营分析, 汇报. */
export type Segment = 'close' | 'finance' | 'operations' | 'report';

/**
 * A section title's icon (DESIGN.md 分区标题图标): the part's colour on a light tile of the same colour, placed as
 * the first child of the heading. Where the page leaves a gutter (`.fnd-hang`, the task's results column) it hangs
 * in it like a fold's chevron, so the title, its note and the content keep one left edge; elsewhere it sits before
 * the words. Decorative: the heading's words name the section.
 */
export function SectionIcon({ icon: Icon, segment }: { icon: LucideIcon; segment: Segment }) {
  return <span className="fnd-section-icon" data-segment={segment} aria-hidden><Icon strokeWidth={1.75} /></span>;
}
