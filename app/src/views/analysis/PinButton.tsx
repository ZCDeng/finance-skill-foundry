import { useContext, useState } from 'react';
import { Pin } from 'lucide-react';
import { Button } from '../../components/ui/button.js';
import { DashboardPinContext, type CardDraft } from './dashboard.js';
import { errorText } from './shared.js';
import './FigureSource.css';

/**
 * 钉到看板: puts a card for this figure or chart on the task's board, waiting for the manager to accept it. Shown only
 * where the page can pin (DashboardPinContext) and the result names the figure on its own (a draft).
 */
export function PinButton({ draft }: { draft: CardDraft | null | undefined }) {
  const board = useContext(DashboardPinContext);
  const [said, setSaid] = useState('');
  const [pending, setPending] = useState(false);
  if (!board || !draft) return null;
  const pin = async () => {
    setPending(true);
    try {
      setSaid(await board.pin(draft));
    } catch (failure) {
      setSaid(errorText(failure));
    } finally {
      setPending(false);
    }
  };
  return <span className="fnd-pin">
    <Button type="button" variant="outline" size="sm" disabled={pending} onClick={() => void pin()}>
      <Pin size={14} strokeWidth={1.5} aria-hidden />钉到看板</Button>
    {said ? <span className="fnd-pin__said" role="status">{said}</span> : null}
  </span>;
}
