import { useEffect, useState } from 'react';

/**
 * The loop beside a wait's own words: a ring that turns into a figure-eight and
 * back, drawn by a CSS path animation (components.css). The shape is chanhdai.com's
 * mobius-loop-icon (MIT; chanhdai.LICENSE.txt), redrawn without its animation library.
 *
 * It only appears once the wait has lasted `delay` ms: on a quick call a flash of
 * motion reads as a glitch. It is decorative; the Chinese text next to it carries
 * the status for assistive technology. It animates only while mounted, so only
 * while something is actually running, and reduced motion holds the still
 * figure-eight. Its colour is the text colour around it.
 */
export function WaitLoop({ delay = 2000 }: { delay?: number }) {
  const [shown, setShown] = useState(delay <= 0);
  useEffect(() => {
    if (delay <= 0) return;
    const timer = setTimeout(() => setShown(true), delay);
    return () => clearTimeout(timer);
  }, [delay]);
  return shown ? <svg className="fnd-wait-loop" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
    <path d="M6 16C11 16 13 8 18 8C23.333 8 23.333 16 18 16C13 16 11 8 6 8C0.667 8 0.667 16 6 16Z" />
  </svg> : null;
}
