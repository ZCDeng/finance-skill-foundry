import type { ReactNode } from 'react';
import { BookOpen, Settings } from 'lucide-react';
import './components.css';
import { Button } from './ui/button.js';
import { ThemeSwitch } from './ThemeSwitch.js';

export type Screen = 'overview' | 'analysis' | 'workbench' | 'formulator' | 'tasks' | 'deliverables' | 'settings';
export interface ShellProps {
  screen: Screen;
  onScreen(screen: Screen): void;
  strip?: ReactNode;
  onGuide?(): void;
  /** 设置 opens from the gear at the far right; a build without settings shows no gear. */
  onSettings?(): void;
  covered?: boolean;
  /** False in a build whose bridge cannot read 总览: the tab is left out rather than opening an empty page. */
  overview?: boolean;
  children: ReactNode;
}
export const APP_NAME = 'FA Foundry';

export function Shell({ screen, onScreen, strip, onGuide, onSettings, covered, overview = true, children }: ShellProps) {
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
          {overview ? <button type="button" className="fnd-head__tab" aria-current={screen === 'overview' ? 'page' : undefined}
            onClick={() => onScreen('overview')}>总览</button> : null}
          <button type="button" className="fnd-head__tab" aria-current={workspace ? 'page' : undefined}
            onClick={() => onScreen('analysis')}>工作区</button>
          <button type="button" className="fnd-head__tab" aria-current={screen === 'deliverables' ? 'page' : undefined}
            onClick={() => onScreen('deliverables')}>成果库</button>
        </nav>
        <span className="fnd-head__end">
          {/* Neutral at rest, gold on hover (R14); the ghost variant's own hover would win over components.css. Below 620px only the icon stays. */}
          {onGuide ? <Button type="button" variant="ghost" size="sm"
            className="fnd-head__help enabled:hover:bg-transparent enabled:hover:text-[var(--fnd-selected)] max-[620px]:w-(--fnd-button-height) max-[620px]:px-0"
            onClick={onGuide} title="使用指南（⌘/Ctrl + ?）" aria-keyshortcuts="Meta+? Control+?">
            <BookOpen size={16} strokeWidth={1.5} aria-hidden /><span className="fnd-head__help-label">使用指南</span>
          </Button> : null}
          <ThemeSwitch />
          {onSettings ? <Button type="button" variant="ghost" size="sm"
            className="fnd-head__help fnd-head__settings enabled:hover:bg-transparent enabled:hover:text-[var(--fnd-selected)] aria-[current=page]:text-[var(--fnd-selected)]"
            aria-current={screen === 'settings' ? 'page' : undefined} onClick={onSettings}
            aria-label="设置" title="设置（⌘/Ctrl + ,）" aria-keyshortcuts="Meta+, Control+,">
            <Settings size={16} strokeWidth={1.5} aria-hidden />
          </Button> : null}
        </span>
      </header>
      {strip}
      <main className="fnd-column">{children}</main>
    </div>
  );
}
