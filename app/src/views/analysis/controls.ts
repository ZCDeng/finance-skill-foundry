/**
 * The tie-out controls a task keeps (foundry/finance_controls.py), as the workspace reads them.
 *
 * The server decides every status here: whether a control passes, whether a
 * difference is still open, whether it holds the close. These types only carry
 * that answer to the screen.
 */

export type ControlSide = {
  dataset_id: string; source_hash?: string; sheet: string; range: string; scale: string;
  value?: string; cells?: number; text_cells?: number; blank_cells?: number;
};

export type ControlSpec = {
  kind: 'subtotal' | 'tie_out'; label: string; left: ControlSide; right: ControlSide;
  tolerance: string; unit?: string; note?: string;
};

export type ControlStatus = 'pass' | 'break' | 'error' | 'stale';

export type ControlResult = {
  status: ControlStatus; difference?: string; within_rounding?: boolean; reason?: string;
  left?: ControlSide; right?: ControlSide; run_at?: string;
};

export type Disposition = {
  id: string; decision: 'corrected' | 'waived' | 'pending_external'; reason?: string; counterparty?: string;
  decided_by_name?: string; reviewer?: string; reviewed_at?: string; created_at?: string;
};

export type IssueState = 'open' | 'stale' | 'not_run' | 'waived' | 'awaiting_review' | 'pending_external' | 'awaiting_reimport';

export type ControlIssue = {
  state: IssueState; blocking: boolean; disposition?: Disposition; outdated_disposition?: Disposition;
};

export type ControlRow = {
  id: string; state: 'proposed' | 'confirmed' | 'retired'; origin?: string; control: ControlSpec;
  result?: ControlResult | null; issue?: ControlIssue | null;
};

export type ControlSummary = {
  controls: number; confirmed: number; pass: number; break: number; stale: number; error: number;
  break_within_rounding?: number; blocking?: number;
};

export type ControlList = { controls: ControlRow[]; summary: ControlSummary; settings?: { require_second_review: boolean } };

export type Suggestion = { control: ControlSpec; preview: ControlResult; saved_id?: string };

export const ISSUE_LABELS: Record<IssueState, string> = {
  open: '待处理',
  stale: '资料已更新',
  not_run: '还没运行',
  waived: '已接受差异',
  awaiting_review: '待第二人复核',
  pending_external: '待外部确认',
  awaiting_reimport: '待重新导入',
};

export const STATUS_LABELS: Record<ControlStatus, string> = {
  pass: '相符',
  break: '不相符',
  error: '读不出',
  stale: '已过期',
};

export const DECISION_LABELS: Record<Disposition['decision'], string> = {
  corrected: '修正资料后重新导入',
  waived: '接受差异并说明',
  pending_external: '待外部确认',
};

/** 「08·AR收缴率与欠费!D25:D30」, the way a manager finds the cells. */
export function where(side?: ControlSide): string {
  return side ? `${side.sheet}!${side.range}` : '—';
}
