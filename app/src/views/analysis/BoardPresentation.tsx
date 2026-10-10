import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { Dialog as DialogPrimitive } from 'radix-ui';
import { ChevronLeft, ChevronRight, X } from 'lucide-react';
import { bridge } from '../../bridge.js';
import { Button } from '../../components/ui/button.js';
import type { DashboardCard } from './dashboardModel.js';

/** The workspace takes its native conversation view down while this is said open (components/Workspace.tsx). */
const NATIVE_COVER = 'foundry:workspace-native-cover';
const cover = (open: boolean) => window.dispatchEvent(new CustomEvent(NATIVE_COVER, { detail: { open } }));

const NEXT = new Set(['ArrowRight', 'ArrowDown', 'PageDown']);
const BACK = new Set(['ArrowLeft', 'ArrowUp', 'PageUp']);

/**
 * 汇报模式: the board one card at a time, filling the screen, for a meeting. The window goes full screen where it
 * can (the window's own full screen, given back on leaving if it was not full screen before), and the conversation
 * steps aside while it shows. ← → (or PageUp/PageDown) turn the cards and Esc leaves. A figure still opens to its
 * source and a 回款情景 card still moves: keys pressed in its box or in an open source stay theirs, and Esc with a
 * source open closes only the source.
 */
export function BoardPresentation({ title, cards, said, slide, onClose }: {
  /** The task and its period, as the page names them. */
  title: string;
  cards: DashboardCard[];
  /** What is on the slides and what was left off, said once under the title. */
  said: string;
  slide(card: DashboardCard): ReactNode;
  onClose(): void;
}) {
  const [at, setAt] = useState(0);
  const stage = useRef<HTMLDivElement>(null);
  const index = Math.min(at, cards.length - 1);
  const card = cards[index];

  useEffect(() => {
    cover(true);
    // Not the page's full screen: in it the window takes Esc for itself, before an open source could close on it.
    const api = bridge();
    let open = true;
    let took = false;
    const giveBack = () => void api?.windowFullScreen?.(false).catch(() => undefined);
    void api?.windowFullScreen?.(true).then((answer) => {
      if (!answer.ok || answer.value.was) return;
      if (open) took = true; else giveBack();
    }).catch(() => undefined);
    return () => {
      open = false;
      if (took) giveBack();
      cover(false);
    };
  }, []);
  // A new slide starts at its top, with the keys on the stage.
  useEffect(() => { stage.current?.scrollTo?.({ top: 0 }); }, [index]);

  const turn = (by: number) => setAt(Math.max(0, Math.min(cards.length - 1, index + by)));
  const keys = (event: KeyboardEvent<HTMLDivElement>) => {
    // Keys in an open source (portalled outside) or in a field on the slide are theirs, not the deck's.
    const target = event.target as HTMLElement;
    if (!event.currentTarget.contains(target) || target.closest('input, textarea, select, [role="slider"]')) return;
    if (NEXT.has(event.key)) { event.preventDefault(); turn(1); }
    else if (BACK.has(event.key)) { event.preventDefault(); turn(-1); }
    else if (event.key === 'Home') { event.preventDefault(); setAt(0); }
    else if (event.key === 'End') { event.preventDefault(); setAt(cards.length - 1); }
  };

  if (!card) return null;
  return <DialogPrimitive.Root open onOpenChange={(open) => { if (!open) onClose(); }}>
    <DialogPrimitive.Portal>
      <DialogPrimitive.Content className="dashboard-present" aria-describedby="dashboard-present-said" onKeyDown={keys}>
        <header className="dashboard-present__bar">
          <div className="dashboard-present__heading">
            <DialogPrimitive.Title className="dashboard-present__title">{title}</DialogPrimitive.Title>
            <DialogPrimitive.Description id="dashboard-present-said" className="dashboard-present__said">{said}</DialogPrimitive.Description>
          </div>
          <p className="dashboard-present__count" aria-live="polite">{`${index + 1} / ${cards.length}`}</p>
          <DialogPrimitive.Close asChild>
            <Button type="button" variant="outline"><X size={14} strokeWidth={1.5} aria-hidden />退出汇报</Button>
          </DialogPrimitive.Close>
        </header>
        <div ref={stage} className="dashboard-present__stage">{slide(card)}</div>
        <footer className="dashboard-present__foot">
          <Button type="button" variant="ghost" disabled={index === 0} onClick={() => turn(-1)}>
            <ChevronLeft size={16} strokeWidth={1.5} aria-hidden />上一张</Button>
          <ol className="dashboard-present__dots" aria-label="翻到">
            {cards.map((row, n) => <li key={row.id}>
              <button type="button" className="dashboard-present__dot" aria-label={`第 ${n + 1} 张：${row.title}`}
                aria-current={n === index ? 'step' : undefined} onClick={() => setAt(n)} />
            </li>)}
          </ol>
          <Button type="button" variant="ghost" disabled={index === cards.length - 1} onClick={() => turn(1)}>
            下一张<ChevronRight size={16} strokeWidth={1.5} aria-hidden /></Button>
          <p className="dashboard-present__hint">← → 翻页，点数字看来源，Esc 退出</p>
        </footer>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  </DialogPrimitive.Root>;
}
