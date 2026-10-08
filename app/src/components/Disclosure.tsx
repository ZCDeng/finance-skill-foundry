import './components.css';

import type { ReactNode, Ref } from 'react';
import { ChevronRight } from 'lucide-react';

/**
 * The summary line of an in-place disclosure (DESIGN.md 折叠段落).
 *
 * The caller keeps the native <details> and its open state; this draws only the
 * row: body text, a 16px chevron on the left that turns when the section opens.
 * `quiet` is for technical and diagnostic folds.
 */
export function DisclosureSummary({ children, tone, ref }: { children: ReactNode; tone?: 'quiet'; ref?: Ref<HTMLElement> }) {
  return (
    <summary ref={ref} className="fnd-disclosure-summary" data-tone={tone}>
      <ChevronRight className="fnd-disclosure-summary__icon" size={16} strokeWidth={1.5} aria-hidden />
      {children}
    </summary>
  );
}
