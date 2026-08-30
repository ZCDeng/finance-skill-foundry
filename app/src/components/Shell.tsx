import type { ReactNode } from 'react';

import './components.css';

export interface ShellProps {
  screen: 'tasks' | 'deliverables';
  onScreen(screen: 'tasks' | 'deliverables'): void;
  children: ReactNode;
}

const DESTINATIONS = [
  { id: 'tasks', label: '任务' },
  { id: 'deliverables', label: '交付物' },
] as const;

/** Page shell: the header strip, and one capped scrolling column under it. */
export function Shell({ screen, onScreen, children }: ShellProps) {
  return (
    <div className="fnd-shell">
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
      <main className="fnd-column">{children}</main>
    </div>
  );
}
