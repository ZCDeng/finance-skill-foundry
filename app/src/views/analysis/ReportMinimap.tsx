import { useEffect, useState } from 'react';
import { HoverCard, HoverCardContent, HoverCardTrigger } from '../../components/ui/hover-card.js';

/**
 * Where the reader is in a draft, for the outline and the minimap beside the text.
 *
 * After chanhdai.com's toc-minimap (MIT; components/chanhdai.LICENSE.txt), on Radix rather than Base UI and
 * without its sound. The current heading is the last one whose top has passed a line a little below the
 * top of the scrolling area (none while the reader is still above the first), and the last heading once the
 * area is scrolled to its end, so a short final section still lights up. Measured on scroll, at most once a frame; nothing runs while the page is still.
 */
export interface ReportHeading { id: string; level: number; text: string }

const LINE = 96;

function scroller(from: HTMLElement): HTMLElement | null {
  for (let node = from.parentElement; node; node = node.parentElement) {
    const overflow = getComputedStyle(node).overflowY;
    if ((overflow === 'auto' || overflow === 'scroll') && node.scrollHeight > node.clientHeight) return node;
  }
  return null;
}

/** The reading view's heading by id; the folded appendix repeats the ids, so only the main text counts. */
const headingNode = (id: string) => document.querySelector<HTMLElement>(`[data-reading-main] [id="${id}"]`);

export function useActiveHeading(ids: string[], enabled: boolean): string | null {
  const [active, setActive] = useState<string | null>(null);
  const key = ids.join(' ');
  useEffect(() => {
    const list = key ? key.split(' ') : [];
    if (!enabled || !list.length) { setActive(null); return; }
    let frame = 0;
    const measure = () => {
      frame = 0;
      const first = headingNode(list[0]);
      if (!first) { setActive(null); return; }
      const area = scroller(first);
      const box = area ?? document.documentElement;
      const top = area ? area.getBoundingClientRect().top : 0;
      const atEnd = box.scrollHeight > box.clientHeight && box.scrollTop + box.clientHeight >= box.scrollHeight - 2;
      let current: string | null = null;
      for (const id of list) {
        const node = headingNode(id);
        if (node && node.getBoundingClientRect().top - top <= LINE) current = id;
      }
      setActive(atEnd ? list[list.length - 1] : current);
    };
    const schedule = () => { if (!frame) frame = requestAnimationFrame(measure); };
    measure();
    document.addEventListener('scroll', schedule, { capture: true, passive: true });
    window.addEventListener('resize', schedule);
    return () => {
      if (frame) cancelAnimationFrame(frame);
      document.removeEventListener('scroll', schedule, { capture: true });
      window.removeEventListener('resize', schedule);
    };
  }, [key, enabled]);
  return active;
}

/**
 * A short mark per heading beside the text, shorter for a 节 than a 章, the current one in gold. Hovering
 * opens the outline over the marks. Pointer-only by design: the marks are hidden from assistive technology
 * and take no focus, and 目录 in the toolbar is the way in for the keyboard and screen readers.
 */
export function ReportMinimap({ headings, active }: { headings: ReportHeading[]; active: string | null }) {
  const [open, setOpen] = useState(false);
  return <div className="report-minimap">
    <HoverCard open={open} onOpenChange={setOpen} openDelay={0} closeDelay={120}>
      <HoverCardTrigger asChild>
        <div className="report-minimap__marks" aria-hidden="true" data-open={open ? 'true' : undefined}>
          {headings.map((item) => <span key={item.id} className="report-minimap__mark" data-level={item.level}
            data-active={item.id === active ? 'true' : undefined} />)}
        </div>
      </HoverCardTrigger>
      <HoverCardContent className="report-minimap__card" side="right" align="start" sideOffset={-40}>
        <nav className="fnd-scroll-fade" aria-label="文稿目录预览" onClick={(event) => {
          if ((event.target as Element).closest('a')) setOpen(false);
        }}>
          {headings.map((item) => <a key={item.id} href={`#${item.id}`} data-level={item.level}
            aria-current={item.id === active ? 'location' : undefined}>{item.text}</a>)}
        </nav>
      </HoverCardContent>
    </HoverCard>
  </div>;
}
