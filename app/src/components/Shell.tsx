import type { ReactNode } from 'react';
import { BookOpen } from 'lucide-react';

import './components.css';

export type Screen = 'workbench' | 'formulator' | 'tasks' | 'deliverables';

export interface ShellProps {
  screen: Screen;
  onScreen(screen: Screen): void;
  /** Drawn between the header and the column. The workbench puts its task bar here. */
  strip?: ReactNode;
  /** Brings the first-run guide back. Absent on screens that cannot show it. */
  onGuide?(): void;
  /**
   * A native view is over the column right now, on a screen that does not
   * always have one. The workbook preview is the case: it is opened from the
   * record-keeping screens, and while it is up the column under it must not
   * scroll for the same reason the workbench's never does.
   */
  covered?: boolean;
  children: ReactNode;
}

/**
 * What the product is called, in the one place it is said.
 *
 * Not in the window title, which `main.ts` keeps blank, and not in the bundle
 * name, which is the identifier macOS filed the app under.
 */
export const APP_NAME = 'FA Foundry';

/**
 * The four destinations, workbench first.
 *
 * The order is the product's answer to "what is this": the first thing on
 * screen is the conversation, and the three record-keeping screens are behind
 * it. It used to open on 任务, which is a form for naming something an
 * operator has no reason to name yet.
 */
const DESTINATIONS = [
  { id: 'workbench', label: '工作台' },
  { id: 'formulator', label: '数据台' },
  { id: 'tasks', label: '任务' },
  { id: 'deliverables', label: '交付物' },
] as const;

/**
 * Page shell: the header strip, an optional second strip, and one column.
 *
 * The workbench stops the column scrolling. The harness page under it is a
 * native view positioned in window coordinates, so it does not move when the
 * document does -- anything behind it that could scroll away would slide out
 * from under a view that stays put.
 */
export function Shell({ screen, onScreen, strip, onGuide, covered, children }: ShellProps) {
  // Every embedded page clips the column for the same reason; `data-screen`
  // carries which one is on so the stylesheet can stop it scrolling.
  const embedded = covered === true || screen === 'workbench' || screen === 'formulator';
  return (
    <div className="fnd-shell" data-screen={screen} data-embedded={embedded ? 'yes' : 'no'}>
      <header className="fnd-head">
        {/*
          * The mark and the name, and this is the only place either appears.
          * The window's title bar is deliberately blank -- see `main.ts` -- so
          * this strip carries the whole of the product's identity, on a screen
          * that is otherwise entirely someone else's page.
          *
          * The mark is a background rather than an `img` for the same reason
          * the faces are `@font-face` urls: a relative url out of this
          * stylesheet resolves under `file://` in the packaged app, and it is
          * decorative here anyway -- the product's name is the text beside it.
          */}
        <span className="fnd-head__brand">
          <span className="fnd-head__logo" aria-hidden />
          <span className="fnd-head__mark">{APP_NAME}</span>
        </span>
        <nav className="fnd-head__nav">
          {DESTINATIONS.map((item) => (
            <button
              key={item.id}
              type="button"
              className="fnd-head__tab"
              aria-current={screen === item.id ? 'page' : undefined}
              onClick={() => onScreen(item.id)}
            >
              {item.label}
            </button>
          ))}
        </nav>
        {/*
          * Always rendered, even with nothing in it. It is the right-hand half
          * of what centres the destinations: two outer parts taking equal
          * shares of the free space. A slot that disappeared with the help
          * control would move the row off centre on the screens that have no
          * guide to offer.
          */}
        <span className="fnd-head__end">
          {onGuide ? (
            /*
              * A mark rather than a word. It brings back a panel that names
              * itself in its own first line, and spending a labelled control
              * on saying that twice put the second-longest string in the
              * header on the thing an operator needs least often. The name
              * stays where a pointer and a screen reader can both reach it.
              */
            <button
              type="button"
              className="fnd-head__help"
              onClick={onGuide}
              aria-label="怎么用"
              title="怎么用"
            >
              <BookOpen size={16} strokeWidth={1.5} aria-hidden />
            </button>
          ) : null}
        </span>
      </header>
      {strip}
      <main className="fnd-column">{children}</main>
    </div>
  );
}
