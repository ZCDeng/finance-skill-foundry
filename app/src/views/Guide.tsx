import { useState } from 'react';
import { PlayCircle } from 'lucide-react';

/**
 * What this window is, for someone opening it for the first time.
 *
 * Drawn rather than listed. The three ways in are a sequence -- a method is
 * written once, a period runs against it, a leader's question comes back to
 * the window that period locked -- and a bulleted list of three nouns says
 * none of that. Each step carries a small monoline sketch of the thing it
 * produces, and the arrows between them are the product's actual order.
 *
 * The sketches are hand-authored paths rather than an icon set. Lucide draws
 * icons, which are signs; these are pictures of this product's own objects --
 * a locked ledger, a brief with a question coming back at it -- and no icon
 * set has those. Everything is one stroke weight, no fill, round caps, and the
 * lines are deliberately not quite straight: a period close is exacting work,
 * and a diagram that looks CAD-drawn suggests the software will be exacting
 * about the wrong things.
 *
 * It occupies the whole workbench because the runtime's page is a native view
 * under it -- `App` takes the rectangle away while this is up. That is what
 * makes it read as a layer over the window rather than a panel inside it.
 */

/** One sketch's shared pen. 1.4 keeps every line the same weight at any size. */
const PEN = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.4,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
} as const;

/** A method, written once and read every period after. */
function MethodSketch() {
  return (
    <svg viewBox="0 0 132 92" className="fnd-step__art" aria-hidden focusable="false">
      <g {...PEN}>
        <path d="M30 14.5C29.8 12.5 31 11.4 33 11.3L78 10c1.6 0 2.6.4 3.6 1.4l14 13.8c1 1 1.4 1.8 1.4 3.4l.6 45.4c0 2-1.2 3.2-3.2 3.4L34 79c-2 0-3.2-1-3.4-3z" />
        <path d="M80 10.6l.6 14.4c0 1.6.8 2.4 2.4 2.4l13.8-.4" />
        <path d="M43 38l35-.8M43 49l30-.8M43 60l23-.6" />
        <path d="M74 74.6l16.4-17.2c1.6-1.6 3.6-1.6 5-.2s1.4 3.4-.2 5L78.8 79.4l-7.2 2z" />
        <path d="M88 60.4l4.6 4.4" />
      </g>
    </svg>
  );
}

/** This period's books, imported and then locked. */
function LockSketch() {
  return (
    <svg viewBox="0 0 132 92" className="fnd-step__art" aria-hidden focusable="false">
      <g {...PEN}>
        <path d="M22 20c-.2-1.8.8-2.8 2.6-3L62 15.4c1.8 0 2.8.8 3 2.6l2 40c.2 1.8-.8 2.8-2.6 3L27 62.6c-1.8 0-2.8-.8-3-2.6z" />
        <path d="M16 30c-.2-1.8.8-2.8 2.6-3L56 25.4c1.8 0 2.8.8 3 2.6l2 42c.2 1.8-.8 2.8-2.6 3L21 74.6c-1.8 0-2.8-.8-3-2.6z" />
        <path d="M27 40l23-.8M27 50l18-.6" />
        <path d="M74 52.6c-.2-3 1.4-4.6 4.4-4.8l27.6-.8c3-.1 4.6 1.4 4.8 4.4l.8 18.6c.2 3-1.4 4.6-4.4 4.8l-27.6.8c-3 .1-4.6-1.4-4.8-4.4z" />
        <path d="M82 47.8l-.4-8.2c-.2-6 3.6-10 10.2-10.2s10.6 3.6 10.8 9.6l.3 7.8" />
        <path d="M92.6 57c1.8 0 3 1.2 3 3 0 1.2-.6 2.2-1.6 2.8l.4 5.2" />
      </g>
    </svg>
  );
}

/** A question arriving after the brief, and going back to the locked window. */
function AskSketch() {
  return (
    <svg viewBox="0 0 132 92" className="fnd-step__art" aria-hidden focusable="false">
      <g {...PEN}>
        <path d="M24 22c-.2-2.4 1.2-3.8 3.6-4L82 15.6c2.4-.1 3.8 1.2 4 3.6l1.6 26.8c.2 2.4-1.2 3.8-3.6 4L48 51.6 36 62l.4-9.8-8.4.4c-2.4.1-3.8-1.2-4-3.6z" />
        <path d="M48 28.6c0-3 2.6-5 6.6-5.2s6.8 1.6 7 4.6c.2 3.4-3 4.6-5 6.4-1.2 1-1.4 2.2-1.2 4" />
        <path d="M55.6 42.8h.1" />
        <path d="M92 66c-.2-1.6.6-2.4 2.2-2.5l15.8-.5c1.6-.05 2.4.7 2.5 2.3l.4 8.7c.1 1.6-.7 2.4-2.3 2.5l-15.8.5c-1.6.05-2.4-.7-2.5-2.3z" />
        <path d="M96.4 63.4l-.2-3.8c-.1-3 1.8-5 5.2-5.1s5.4 1.7 5.6 4.7l.1 3.9" />
        <path d="M46 66c10 10 24 12 38 7.4" />
        <path d="M78.6 68.2l6.2 5-6.8 4.2" />
      </g>
    </svg>
  );
}

/** The order between two steps. Same pen, so it belongs to the same drawing. */
function StepArrow() {
  return (
    <svg viewBox="0 0 34 20" className="fnd-arrow" aria-hidden focusable="false">
      <g {...PEN}>
        <path d="M3 10.4c8-1.6 16 1.2 24-.2" />
        <path d="M21.8 5.8l5.6 4.4-5.8 4.4" />
      </g>
    </svg>
  );
}

const STEPS = [
  {
    id: 'author',
    label: '写方法',
    hint: 'standard · 把这类分析怎么做定下来, 以后每期照着跑',
    Art: MethodSketch,
  },
  {
    id: 'period',
    label: '开始本期',
    hint: 'period · 开窗 导入 锁 出稿',
    Art: LockSketch,
  },
  {
    id: 'followup',
    label: '追问',
    hint: 'f3 · 只有 query-locked',
    Art: AskSketch,
  },
] as const;

export function Guide({
  busy,
  canStart,
  onStart,
  onDismiss,
}: {
  busy: boolean;
  /** False when this build has no harness to open a session in. */
  canStart: boolean;
  onStart(title: string, period: string): void;
  onDismiss(): void;
}) {
  const [title, setTitle] = useState('');
  const [period, setPeriod] = useState('');
  const ready = title.trim().length > 0 && canStart && !busy;
  return (
    <div className="fnd-scrim">
      <div className="fnd-guide">
        <h2 className="fnd-guide__lede">
          一个把结账期间当成任务来管的工作台。上面是对话, 下面这三条是进去的路。
        </h2>

        <ol className="fnd-guide__steps">
          {STEPS.map(({ id, label, hint, Art }, index) => (
            <li key={id} className="fnd-step">
              {index > 0 ? <StepArrow /> : null}
              <span className="fnd-step__body">
                <Art />
                <span className="fnd-step__label">{label}</span>
                <span className="fnd-step__hint">{hint}</span>
              </span>
            </li>
          ))}
        </ol>

        <p className="fnd-muted fnd-guide__note">
          会话开在哪个任务上, 顶上那条一直写着。任务、每一版交付物和它们的来路, 在「任务」和「交付物」两屏。
        </p>

        {/*
          * The one press that gets a cold install moving. The alternative is
          * naming a task on one screen, finding it on another, and choosing a
          * way in on a third, with nothing on any of them saying that was the
          * sequence.
          */}
        <form
          className="fnd-new"
          onSubmit={(event) => {
            event.preventDefault();
            if (!ready) return;
            onStart(title.trim(), period.trim());
          }}
        >
          <input
            className="fnd-field"
            value={title}
            maxLength={120}
            placeholder="任务名, 比如 华东区 8 月回款"
            aria-label="任务名"
            onChange={(event) => setTitle(event.target.value)}
          />
          <input
            className="fnd-field fnd-field--short"
            value={period}
            maxLength={32}
            placeholder="期间 2026-08"
            aria-label="期间"
            onChange={(event) => setPeriod(event.target.value)}
          />
          <button type="submit" className="fnd-go" disabled={!ready}>
            <PlayCircle size={14} strokeWidth={1.5} aria-hidden />
            建任务并开始本期
          </button>
        </form>

        <button type="button" className="fnd-quiet" onClick={onDismiss}>
          先看看再说
        </button>
      </div>
    </div>
  );
}
