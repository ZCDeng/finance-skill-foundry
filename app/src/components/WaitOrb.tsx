import { useEffect, useState } from 'react';
import { ThinkingOrb, type OrbState } from 'thinking-orbs';

/**
 * The dotted orb beside a wait's own words. It only appears once the wait has
 * lasted `delay` ms: on a quick call a flash of motion reads as a glitch. It is
 * decorative; the Chinese text next to it carries the status for assistive
 * technology, so the canvas is hidden from it. Reduced motion draws one still
 * frame (the library's own handling), and theme follows `data-theme`.
 */
export function WaitOrb({ state, delay = 2000 }: { state: OrbState; delay?: number }) {
  const [shown, setShown] = useState(delay <= 0);
  useEffect(() => {
    if (delay <= 0) return;
    const timer = setTimeout(() => setShown(true), delay);
    return () => clearTimeout(timer);
  }, [delay]);
  return shown ? <ThinkingOrb state={state} size={20} aria-hidden className="fnd-wait-orb"
    style={{ display: 'inline-block', verticalAlign: 'middle' }} /> : null;
}
