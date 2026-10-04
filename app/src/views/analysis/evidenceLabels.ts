/**
 * The words for evidence labels, the evidence posture and dataset freshness.
 * The engine (foundry/evidence_labels.py) assigns the codes; this is the same map, and
 * tests/test_evidence_labels.py holds the two to each other.
 */

export const EVIDENCE_LABELS = {
  fact_source_reported: '来源原文',
  fact_provider_standardized: '标准化数据',
  derived_calculation: '派生计算',
  management_claim: '管理层说法',
  analyst_interpretation: '分析判断',
  assumption_user_provided: '用户假设',
  assumption_inferred: '推断假设',
  estimate: '估算',
  stale_source: '过期来源',
  contradicted_source: '矛盾来源',
  missing_required_source: '缺必需来源',
  unknown: '未知',
} as const;

export const EVIDENCE_POSTURES = {
  decision_grade: '可决策',
  research_grade: '研究级',
  preliminary: '初步',
  assumption_led: '假设主导',
  unsupported: '无法支持',
} as const;

export const FRESHNESS_TEXT = {
  current: '当前',
  source_stale: '资料过期',
  period_mismatch: '期间不符',
  unknown: '未声明',
} as const;

type EvidenceLabelCode = keyof typeof EVIDENCE_LABELS;

export interface EvidenceReason { code: string; text?: string }
export interface EvidenceLabelEntry {
  key?: {
    kind?: 'claim' | 'fact' | 'location' | 'requirement' | 'assertion' | 'revision' | 'number' | string;
    claim_index?: number; basis?: string | null; fact_id?: string; run_id?: string; row?: number; column?: string;
    dataset_id?: string; paragraph?: number; requirement_item_id?: string; rule_id?: string; text?: string; position?: number;
  };
  label?: string; text?: string; base_label?: string; reasons?: EvidenceReason[];
  source_refs?: { dataset_id: string; source_hash?: string; sheet?: string; range?: string; paragraph?: number }[];
  as_of?: string; period?: string;
}
export interface EvidencePosture {
  level?: string; text?: string; counts?: Record<string, number>; drivers?: EvidenceReason[]; rules_version?: string;
}
export interface DatasetFreshness { state?: string; reasons?: EvidenceReason[] }

/** The labels that say something is wrong with the evidence: shown with the warning colour and an icon. */
export const PROBLEM_LABELS: ReadonlySet<string> = new Set(['contradicted_source', 'missing_required_source', 'stale_source']);

export function evidenceLabelText(code: string | undefined, fallback?: string): string {
  return (code && (EVIDENCE_LABELS as Record<string, string>)[code]) || fallback || '未知';
}

export function postureText(level: string | undefined, fallback?: string): string {
  return (level && (EVIDENCE_POSTURES as Record<string, string>)[level]) || fallback || '';
}

/** 「来源原文 3 · 派生计算 5 · 用户假设 1」 in the label order, counts the engine already de-duplicated. */
export function countSummary(counts: Record<string, number> | undefined): string {
  if (!counts) return '';
  return (Object.keys(EVIDENCE_LABELS) as EvidenceLabelCode[])
    .filter((code) => Number(counts[code]) > 0)
    .map((code) => `${EVIDENCE_LABELS[code]} ${counts[code]}`)
    .join(' · ');
}

export function reasonText(reasons: EvidenceReason[] | undefined): string {
  return (reasons ?? []).map((reason) => reason.text).filter(Boolean).join('；');
}
