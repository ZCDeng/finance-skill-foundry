import type { ReactNode } from 'react';

import './components.css';

export type Screen = 'workbench' | 'tasks' | 'deliverables';

export interface ShellProps {
  screen: Screen;
  onScreen(screen: Screen): void;
  /** Drawn between the header and the column. The workbench puts its task bar here. */
  strip?: ReactNode;
  children: ReactNode;
}

const DESTINATIONS = [
  { id: 'workbench', label: '工作台' },
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
export function Shell({ screen, onScreen, strip, children }: ShellProps) {
  return (
    <div className="fnd-shell" data-screen={screen}>
      <header className="fnd-head">
        <span className="fnd-head__mark">Foundry</span>
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
      </header>
      {strip}
      <main className="fnd-column">{children}</main>
    </div>
  );
}
