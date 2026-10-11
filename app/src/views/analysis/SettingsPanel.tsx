import { Calculator } from 'lucide-react';
import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { DisclosureSummary } from '../../components/Disclosure.js';
import { SectionIcon } from '../../components/SectionIcon.js';

/**
 * Open state for the 范围与计算 fold. `setOpen` opens or closes without taking
 * focus (the first visit opening it, a run closing it); `openWithFocus` is a
 * person asking for it from elsewhere (调整范围), so focus moves in. Once a
 * person has opened the fold, any close hands focus back to where they were,
 * so a run closing it never leaves focus on the page body.
 */
export function useSettingsPanel(initialOpen = false) {
  const [open, setOpen] = useState(initialOpen);
  const trigger = useRef<HTMLElement>(null);
  const restoreFocusTo = useRef<HTMLElement | null>(null);
  const focusAfterOpen = useRef(false);
  const openWithFocus = useCallback(() => {
    const activeElement = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    restoreFocusTo.current = activeElement && activeElement !== document.body ? activeElement : trigger.current;
    focusAfterOpen.current = true;
    setOpen(true);
  }, []);
  const close = useCallback(() => setOpen(false), []);
  return { open, setOpen, openWithFocus, close, trigger, restoreFocusTo, focusAfterOpen };
}

export type SettingsPanelState = ReturnType<typeof useSettingsPanel>;

/**
 * 自己动手算 (DESIGN.md 分区与标题层级): one section heading with its note on
 * the line below, then the folds it groups, all drawn the same way. Named so it is
 * not taken for the app's 设置 page. Status
 * lines a run leaves go between the heading and the folds, so a run that
 * closes a fold still leaves its outcome in view.
 */
export function SettingsGroup({ note, children }: { note: string; children: ReactNode }) {
  const heading = useId();
  return <section className="analysis-settings-group" aria-labelledby={heading}>
    <div className="analysis-settings-group__head"><h3 id={heading}><SectionIcon icon={Calculator} segment="finance" />自己动手算</h3><p className="analysis-note">{note}</p></div>
    {children}
  </section>;
}

/**
 * The fold where a person picks the data and scope and calculates: a native
 * <details> like every other fold, kept open by the caller's state so a run
 * can close it and 调整范围 can open it. Its content is mounted only while
 * open, so a closed fold leaves no hidden form behind.
 */
export function SettingsPanel({ state, label, summary, scrollIntoView = false, children }: {
  state: SettingsPanelState;
  /** The fold's name, also the name of the region it opens. */
  label: string;
  /** Shown after the name on the summary line. */
  summary?: string;
  scrollIntoView?: boolean;
  children: ReactNode;
}) {
  const { open, setOpen, close, trigger, restoreFocusTo, focusAfterOpen } = state;
  const content = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) {
      const previous = restoreFocusTo.current;
      restoreFocusTo.current = null;
      if (!previous) return;
      const target = previous.isConnected ? previous : trigger.current;
      target?.focus({ preventScroll: true });
      return;
    }
    if (scrollIntoView && focusAfterOpen.current) content.current?.scrollIntoView?.({ block: 'start', behavior: 'smooth' });
    if (focusAfterOpen.current) {
      focusAfterOpen.current = false;
      content.current?.focus({ preventScroll: true });
    }
  }, [open]);
  return <details className="analysis-details analysis-finance-setup" open={open} onToggle={(event) => {
    const next = event.currentTarget.open;
    if (next === open) return;
    // A person opening the fold from its own line keeps focus there, and gets it back there when a run closes it.
    if (next) restoreFocusTo.current = trigger.current;
    setOpen(next);
  }}>
    <DisclosureSummary ref={trigger}>{label}{summary ? <span className="analysis-note"> · {summary}</span> : null}</DisclosureSummary>
    {open ? <div ref={content} className="analysis-finance-setup-body" role="region" aria-label={label} tabIndex={-1}
      onKeyDown={(event) => { if (event.key === 'Escape') { event.preventDefault(); restoreFocusTo.current ??= trigger.current; close(); } }}>
      {children}
    </div> : null}
  </details>;
}
