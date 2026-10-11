import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent } from 'react';
import { Monitor, Moon, Sun } from 'lucide-react';
import { bridge, type Appearance } from '../bridge.js';

/**
 * 跟随系统 / 浅色 / 深色, at the right of the header.
 *
 * After chanhdai.com's theme-switcher (MIT; chanhdai.LICENSE.txt), without
 * next-themes or an animation library: main applies the choice to the whole
 * window, and the ring that marks it slides with the shell's own transition,
 * which reduced motion sets to zero. It moves only when picked.
 *
 * A radio group: one tab stop, arrows move and choose, as the ARIA pattern has
 * it. A build without the channel shows nothing rather than a switch that does nothing.
 * 设置 draws a second one; a pick in either moves both (APPEARANCE_EVENT).
 */
const APPEARANCE_EVENT = 'foundry:appearance-picked';
const OPTIONS: { value: Appearance; label: string; Icon: typeof Monitor }[] = [
  { value: 'system', label: '跟随系统外观', Icon: Monitor },
  { value: 'light', label: '浅色', Icon: Sun },
  { value: 'dark', label: '深色', Icon: Moon },
];

export function ThemeSwitch() {
  const api = bridge();
  const available = Boolean(api?.appearanceGet && api.appearanceSet);
  const [value, setValue] = useState<Appearance | null>(null);
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  // A pick made before the saved choice arrives wins over it: main already holds the newer one.
  const picked = useRef(false);

  useEffect(() => {
    if (!available) return;
    let live = true;
    void api!.appearanceGet!().then((answer) => {
      if (live && answer.ok && !picked.current) setValue(answer.value.appearance);
    }).catch(() => {});
    return () => { live = false; };
  }, [api, available]);
  useEffect(() => {
    const follow = (event: Event) => { picked.current = true; setValue((event as CustomEvent<Appearance>).detail); };
    window.addEventListener(APPEARANCE_EVENT, follow);
    return () => window.removeEventListener(APPEARANCE_EVENT, follow);
  }, []);

  if (!available) return null;
  const shown = value ?? 'system';
  const index = OPTIONS.findIndex((option) => option.value === shown);

  const pick = (next: Appearance) => {
    if (next === shown) return;
    picked.current = true;
    const before = value;
    setValue(next);
    window.dispatchEvent(new CustomEvent(APPEARANCE_EVENT, { detail: next }));
    const undo = () => window.dispatchEvent(new CustomEvent(APPEARANCE_EVENT, { detail: before ?? 'system' }));
    void api!.appearanceSet!(next).then((answer) => {
      if (!answer.ok) undo();
    }).catch(undo);
  };

  const move = (event: KeyboardEvent<HTMLDivElement>) => {
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
    if (!step) return;
    event.preventDefault();
    const next = (index + step + OPTIONS.length) % OPTIONS.length;
    pick(OPTIONS[next].value);
    buttons.current[next]?.focus();
  };

  return <div className="fnd-theme" role="radiogroup" aria-label="外观" onKeyDown={move}
    style={{ '--fnd-theme-index': index } as CSSProperties}>
    <span className="fnd-theme__ring" aria-hidden />
    {OPTIONS.map(({ value: option, label, Icon }, at) => <button key={option} type="button" role="radio"
      ref={(node) => { buttons.current[at] = node; }}
      className="fnd-theme__option" aria-checked={option === shown} aria-label={label} title={label}
      tabIndex={option === shown ? 0 : -1} onClick={() => pick(option)}>
      <Icon size={14} strokeWidth={1.5} aria-hidden />
    </button>)}
  </div>;
}
