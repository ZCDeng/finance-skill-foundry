import { useLayoutEffect, useRef, useState, type CSSProperties, type PointerEvent } from 'react';
import { Slider as SliderPrimitive } from 'radix-ui';

/**
 * A bounded number picked by feel, next to the field that holds it exactly.
 *
 * After chanhdai.com's elastic-slider (MIT; chanhdai.LICENSE.txt), on Radix Slider rather than its own pointer
 * maths and without an animation library: the label sits inside the track at the left and the value at the
 * right, ticks and the handle show on hover, and dragging past either end stretches the track a few pixels and
 * lets it spring back. Radix carries the keyboard (arrows, Page keys, Home, End) and the slider role.
 *
 * Never alone and never for an amount: the caller keeps the text field, which takes any value the business
 * allows. A value outside the track's range pins the handle at that end and is left as typed. Reduced motion
 * drops the stretch and the spring; the value still moves.
 */
const DEAD_ZONE = 32;
const MAX_REACH = 200;
const MAX_STRETCH = 8;

export function ElasticSlider({ label, ariaLabel, value, min, max, step, format, disabled, onChange }: {
  /** Shown inside the track. */
  label: string;
  /** The slider's accessible name; the text field beside it keeps the field's own. */
  ariaLabel: string;
  /** The field's number, or null when it is empty or not a number yet. */
  value: number | null;
  min: number; max: number; step: number;
  format(value: number): string;
  disabled?: boolean;
  onChange(value: number): void;
}) {
  const root = useRef<HTMLSpanElement>(null);
  const labelRef = useRef<HTMLSpanElement>(null);
  const valueRef = useRef<HTMLSpanElement>(null);
  const [stretch, setStretch] = useState(0);
  // Where the label ends and the value begins, in percent of the track: ticks under the words are left out and
  // the handle dims over them, so neither is drawn through the text.
  const [clear, setClear] = useState({ from: 0, to: 100 });
  const [dragging, setDragging] = useState(false);
  const shown = value == null || Number.isNaN(value) ? min : Math.min(max, Math.max(min, value));
  const text = format(shown);
  useLayoutEffect(() => {
    const track = root.current;
    if (!track) return;
    const measure = () => {
      const width = track.offsetWidth;
      if (!width) return;
      const from = ((12 + (labelRef.current?.offsetWidth ?? 0) + 8) / width) * 100;
      const to = ((width - 12 - (valueRef.current?.offsetWidth ?? 0) - 8) / width) * 100;
      setClear((held) => held.from === from && held.to === to ? held : { from, to });
    };
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure);
    observer.observe(track);
    return () => observer.disconnect();
  }, [label, text]);
  const position = ((shown - min) / (max - min)) * 100;
  const ticks = Math.round((max - min) / step) <= 10 ? Math.round((max - min) / step) - 1 : 9;
  const tickAt = (index: number) => Math.round((max - min) / step) <= 10 ? ((index + 1) * step) / (max - min) * 100 : (index + 1) * 10;

  const pull = (event: PointerEvent<HTMLSpanElement>) => {
    if (!dragging || !root.current || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const box = root.current.getBoundingClientRect();
    const past = event.clientX < box.left ? box.left - event.clientX : event.clientX > box.right ? event.clientX - box.right : 0;
    const reach = Math.max(0, past - DEAD_ZONE);
    const amount = MAX_STRETCH * Math.sqrt(Math.min(reach / MAX_REACH, 1));
    setStretch(event.clientX < box.left ? -amount : amount);
  };
  const release = () => { setDragging(false); setStretch(0); };

  return <SliderPrimitive.Root ref={root} className="fnd-elastic" data-dragging={dragging ? 'true' : undefined}
    style={{ '--fnd-elastic-grow': `${Math.abs(stretch)}px`, '--fnd-elastic-shift': `${Math.min(stretch, 0)}px` } as CSSProperties}
    min={min} max={max} step={step} value={[shown]} disabled={disabled}
    onValueChange={([next]) => { if (next !== undefined) onChange(next); }}
    onPointerDown={() => setDragging(true)} onPointerMove={pull} onPointerUp={release} onPointerCancel={release}
    onLostPointerCapture={release} data-over-text={position < clear.from || position > clear.to ? 'true' : undefined}>
    <SliderPrimitive.Track className="fnd-elastic__track">
      <span className="fnd-elastic__ticks" aria-hidden="true">
        {Array.from({ length: Math.max(0, ticks) }, (_, index) => tickAt(index)).filter((at) => at > clear.from && at < clear.to)
          .map((at) => <span key={at} style={{ left: `${at}%` }} />)}
      </span>
      <SliderPrimitive.Range className="fnd-elastic__fill" />
      <span ref={labelRef} className="fnd-elastic__label" aria-hidden="true">{label}</span>
      <span ref={valueRef} className="fnd-elastic__value" aria-hidden="true">{text}</span>
    </SliderPrimitive.Track>
    <SliderPrimitive.Thumb className="fnd-elastic__thumb" aria-label={ariaLabel} aria-valuetext={text} />
  </SliderPrimitive.Root>;
}
