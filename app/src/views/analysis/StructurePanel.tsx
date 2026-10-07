import { useCallback, useEffect, useRef, useState } from 'react';
import { bridge, type Answer, type DatasetSnapshot } from '../../bridge.js';
import type { StructureProposal } from './StructureProposalCard.js';
import { unwrap, errorText } from './shared.js';

/** A structure somebody else settled, waiting for the manager to own it. */
export type StructurePending = { id: string; dataset_id: string; source: string; state: string; parent_id: string | null };
/** What one file's table structure says: the engine's latest proposal, and a settlement waiting on her. */
export type StructureTodo = { proposal?: StructureProposal; pending?: StructurePending };

/** A proposal or settlement waiting on the manager, as opposed to one already settled. */
export const isStructureTodo = (todo: StructureTodo | undefined): boolean => Boolean(todo?.pending
  || todo?.proposal?.structure_state === 'pending_confirmation' || todo?.proposal?.structure_state === 'no_table');

const sameProposal = (a: StructureProposal, b: StructureProposal) =>
  a.id === b.id && a.revision === b.revision && a.structure_state === b.structure_state;
const samePending = (a: StructurePending, b: StructurePending) => a.id === b.id && a.state === b.state;

/** The new list, keeping each old object the new read did not change so an open form keeps its proposal. */
function keep<T extends { id: string }>(current: T[], next: T[], same: (a: T, b: T) => boolean): T[] {
  const reused = next.map((row) => current.find((old) => same(old, row)) ?? row);
  return reused.length === current.length && reused.every((row, index) => row === current[index]) ? current : reused;
}

/**
 * Every file in this task and what its table structure is waiting on: one waiting for
 * her to say what its tables are, one somebody else confirmed on her behalf, one a
 * remembered structure was applied to. Read again when the files change, not on every
 * read of the page: the page reads the task every 5 seconds and hands over a new list
 * each time.
 */
export function useStructureTodos(taskId: string, datasets: DatasetSnapshot[]) {
  const [proposals, setProposals] = useState<StructureProposal[]>([]);
  const [pending, setPending] = useState<StructurePending[]>([]);
  const [error, setError] = useState('');
  // A read started on one task must not land on the next one.
  const currentTask = useRef(taskId);
  currentTask.current = taskId;
  const load = useCallback(async () => {
    const api = bridge(); if (!api?.financeCall) return;
    const forTask = taskId;
    const listed = unwrap(await api.financeCall(forTask, 'structure-proposal-list', {}) as Answer<{ proposals?: StructureProposal[] }>);
    const settled = unwrap(await api.financeCall(forTask, 'structure-confirmation-list', {}) as Answer<{ confirmations?: StructurePending[] }>);
    if (currentTask.current !== forTask) return;
    const rows = settled.confirmations ?? [];
    const superseded = new Set(rows.map((row) => row.parent_id).filter(Boolean) as string[]);
    setProposals((current) => keep(current, listed.proposals ?? [], sameProposal));
    setPending((current) => keep(current, rows.filter((row) => row.state === 'pending_acknowledgement' && !superseded.has(row.id)), samePending));
    setError('');
  }, [taskId]);
  useEffect(() => { setProposals([]); setPending([]); setError(''); }, [taskId]);
  // The files as a key, not the array: the same files read again are the same key.
  const key = datasets.map((dataset) => `${dataset.id}:${(dataset as { structure_state?: string }).structure_state ?? ''}`).join('|');
  useEffect(() => {
    const forTask = taskId;
    void load().catch((failure) => { if (currentTask.current === forTask) setError(errorText(failure)); });
  }, [load, key]);

  const byDataset: Record<string, StructureTodo> = {};
  for (const proposal of proposals) byDataset[proposal.dataset_id] = { ...byDataset[proposal.dataset_id], proposal };
  for (const confirmation of pending) byDataset[confirmation.dataset_id] = { ...byDataset[confirmation.dataset_id], pending: confirmation };
  // A to-do for a file the page does not list is still a to-do: it gets a row of its own.
  const listed = new Set(datasets.map((dataset) => dataset.id));
  const orphans = Object.keys(byDataset).filter((id) => !listed.has(id) && isStructureTodo(byDataset[id]));
  return { byDataset, orphans, error, reload: load };
}
