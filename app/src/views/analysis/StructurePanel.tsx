import { useCallback, useEffect, useState } from 'react';
import { bridge, type Answer, type DatasetSnapshot } from '../../bridge.js';
import { StructurePendingStrip, StructureProposalCard, type StructureProposal } from './StructureProposalCard.js';
import { unwrap, errorText } from './shared.js';
import { DisclosureSummary } from '../../components/Disclosure.js';

/**
 * Every file in this task that is waiting on the manager: one waiting for her to
 * say what its tables are, one somebody else confirmed on her behalf, one a
 * remembered structure was applied to.
 */
export function StructurePanel({ taskId, datasets, busy, onRefresh }: {
  taskId: string; datasets: DatasetSnapshot[]; busy: boolean; onRefresh(): Promise<void> | void;
}) {
  const [proposals, setProposals] = useState<StructureProposal[]>([]);
  const [pending, setPending] = useState<{ id: string; dataset_id: string; source: string; state: string; parent_id: string | null }[]>([]);
  const [error, setError] = useState('');
  const load = useCallback(async () => {
    const api = bridge(); if (!api?.financeCall) return;
    const listed = unwrap(await api.financeCall(taskId, 'structure-proposal-list', {}) as Answer<{ proposals?: StructureProposal[] }>);
    setProposals(listed.proposals ?? []);
    const settled = unwrap(await api.financeCall(taskId, 'structure-confirmation-list', {}) as Answer<{ confirmations?: typeof pending }>);
    const rows = settled.confirmations ?? [];
    const superseded = new Set(rows.map((row) => row.parent_id).filter(Boolean) as string[]);
    setPending(rows.filter((row) => row.state === 'pending_acknowledgement' && !superseded.has(row.id)));
  }, [taskId]);
  useEffect(() => { void load().catch((failure) => setError(errorText(failure))); }, [load, datasets]);

  const named = (id: string) => datasets.find((item) => item.id === id)?.name ?? id;
  const settle = async () => { await load(); await onRefresh(); };
  const waiting = proposals.filter((item) => item.structure_state === 'pending_confirmation' || item.structure_state === 'no_table');
  if (!waiting.length && !pending.length && !error) return null;
  return (
    <div className="analysis-structure-panel">
      {error && <p role="alert" className="analysis-structure-error">{error}</p>}
      {/* A to-do line per file; the confirmation form is long and opens on demand. */}
      {waiting.map((proposal) => (
        <details key={proposal.id} className="analysis-details analysis-structure-todo">
          <DisclosureSummary>待确认表结构 · {named(proposal.dataset_id)}{proposal.structure_state === 'no_table' ? ' · 没有识别出数据表' : ` · ${proposal.sheets.length} 张工作表`}</DisclosureSummary>
          <StructureProposalCard taskId={taskId} datasetName={named(proposal.dataset_id)}
            proposal={proposal} busy={busy} onSettled={settle} />
        </details>
      ))}
      {pending.map((confirmation) => (
        <StructurePendingStrip key={confirmation.id} taskId={taskId} datasetName={named(confirmation.dataset_id)}
          confirmation={confirmation} busy={busy} onSettled={settle} />
      ))}
    </div>
  );
}
