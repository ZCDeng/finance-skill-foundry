import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { Button } from '../../components/ui/button.js';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '../../components/ui/collapsible.js';

/**
 * Open state for 设置与高级. `setOpen` changes it quietly (a run closing the
 * settings, the first visit opening them); `openWithFocus` is a person asking
 * for them, so focus moves in and returns to where it came from on close.
 */
export function useSettingsPanel(initialOpen = false) {
  const [open, setOpen] = useState(initialOpen);
  const trigger = useRef<HTMLButtonElement>(null);
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
 * The one 设置与高级 panel: an in-flow disclosure (shadcn Collapsible) that
 * replaces its own entry while open. It stays in the page rather than floating,
 * because it holds searchable selects with popovers of their own and the run
 * outcome below it must stay readable.
 */
export function SettingsPanel({ state, summary, note, scrollIntoView = false, children }: {
  state: SettingsPanelState;
  /** Shown on the closed entry. */
  summary: string;
  /** Shown under the heading while open. */
  note: string;
  scrollIntoView?: boolean;
  children: ReactNode;
}) {
  const { open, openWithFocus, close, trigger, restoreFocusTo, focusAfterOpen } = state;
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
    if (scrollIntoView) content.current?.scrollIntoView?.({ block: 'start', behavior: 'smooth' });
    if (focusAfterOpen.current) {
      focusAfterOpen.current = false;
      content.current?.focus({ preventScroll: true });
    }
  }, [open]);
  return <Collapsible open={open} onOpenChange={(next) => { if (next) openWithFocus(); else close(); }} className="analysis-finance-setup">
    {!open ? <CollapsibleTrigger asChild>
      <button ref={trigger} type="button" className="analysis-finance-setup-trigger" aria-label="打开设置与高级">
        <div className="analysis-section-heading"><h3>设置与高级</h3><span className="analysis-note">{summary}</span></div>
      </button>
    </CollapsibleTrigger> : null}
    {/* Mounted only while open: a closed panel leaves no hidden dialog behind. */}
    {open ? <CollapsibleContent ref={content} className="analysis-finance-setup-dialog" role="dialog" aria-modal="false" aria-label="设置与高级" tabIndex={-1}
      onKeyDown={(event) => { if (event.key === 'Escape') { event.preventDefault(); close(); } }}>
      <div className="analysis-finance-setup-head analysis-section-heading"><div><h3>设置与高级</h3><p className="analysis-note">{note}</p></div>
        <Button variant="outline" type="button" aria-label="关闭设置与高级" onClick={close}>关闭</Button></div>
      <div className="analysis-finance-setup-scroll">{children}</div>
    </CollapsibleContent> : null}
  </Collapsible>;
}
