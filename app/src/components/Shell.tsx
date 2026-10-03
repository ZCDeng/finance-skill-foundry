import type { ReactNode } from 'react';
import { BookOpen } from 'lucide-react';
import './components.css';
import { Button } from './ui/button.js';

export type Screen = 'analysis' | 'workbench' | 'formulator' | 'tasks' | 'deliverables';
export interface ShellProps {
  screen: Screen;
  onScreen(screen: Screen): void;
  strip?: ReactNode;
  onGuide?(): void;
  covered?: boolean;
  children: ReactNode;
}
export const APP_NAME = 'FA Foundry';

export function Shell({ screen, onScreen, strip, onGuide, covered, children }: ShellProps) {
  const workspace = screen === 'analysis' || screen === 'workbench';
  const embedded = covered === true || workspace || screen === 'formulator';
  return (
    <div className="fnd-shell" data-screen={screen} data-embedded={embedded ? 'yes' : 'no'}>
      <header className="fnd-head">
        <span className="fnd-head__brand">
          <span className="fnd-head__logo" aria-hidden />
          <span className="fnd-head__mark">{APP_NAME}</span>
        </span>
        <nav className="fnd-head__nav" aria-label="主导航">
          <button type="button" className="fnd-head__tab" aria-current={workspace ? 'page' : undefined}
            onClick={() => onScreen('analysis')}>工作区</button>
          <button type="button" className="fnd-head__tab" aria-current={screen === 'deliverables' ? 'page' : undefined}
            onClick={() => onScreen('deliverables')}>成果库</button>
        </nav>
        <span className="fnd-head__end">
          {/* Neutral at rest, gold on hover (R14); the ghost variant's own hover would win over components.css. */}
          {onGuide ? <Button type="button" variant="ghost" size="sm"
            className="fnd-head__help enabled:hover:bg-transparent enabled:hover:text-[var(--fnd-selected)]"
            onClick={onGuide} title="使用指南（⌘/Ctrl + ?）" aria-keyshortcuts="Meta+? Control+?">
            <BookOpen size={16} strokeWidth={1.5} aria-hidden />使用指南
          </Button> : null}
        </span>
      </header>
      {strip}
      <main className="fnd-column">{children}</main>
    </div>
  );
}
