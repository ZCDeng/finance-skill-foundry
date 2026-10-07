import { formatPeriod } from '../../lib/period.js';
import { scenarioLabel } from './glossary.js';
import type { EvidenceIssue } from './EvidenceQuality.js';

/** One organization, period and scenario of a requirement, as the requirement check reports it. */
export type RequirementGrain = { organization?: string; period?: string; scenario?: string; state?: string; reason?: string };
export interface RequirementItemView {
  id: string; label: string; status: string; provenance_status: string;
  organizations?: string[];
  /** Why the item waits for the manager (finance_requirements._manager_reasons). */
  awaiting_manager?: string[];
  declared_grains?: RequirementGrain[]; missing_grains?: RequirementGrain[]; uncounted_grains?: RequirementGrain[];
}
/** One reason a requirement is still open, the requirements it holds back and where. */
export type RequirementGapRow = { reason: string; detail?: string; requirements: string[]; scopes: string[] };

// finance_completion.MANAGER_REASON_TEXT, said to the manager.
const MANAGER_REASONS: Record<string, string> = {
  estimate_factor_not_reproducible: '估算系数无法由归档单元格复算，需要你决定口径',
  unavailable_declared: '声明为资料缺失，需要你确认后才记为缺数',
  estimate_requires_acceptance: '估算组合待你确认是否按估算列示',
  structure_pending_confirmation: '工作簿结构待你确认',
  bindings_without_engine_rows: '绑定的资料读不出计算行，需要改绑或换依据',
};
const DECLARED = new Set(['estimate_factor_not_reproducible', 'unavailable_declared']);
const UNANSWERED = '还没有可计入的计算依据';
const SOURCE_MISSING = '指定来源还没有核查';

function quotedLabel(message: unknown): string {
  return /“([^”]+)”/.exec(String(message ?? ''))?.[1] ?? '';
}

function periodScenario(grain: RequirementGrain): string {
  return [formatPeriod(grain.period), grain.scenario ? scenarioLabel(grain.scenario) : ''].filter(Boolean).join(' · ');
}

/** Organizations grouped under the period and scenario they share: 华东区域、华南区域（2026 年 1–8 月 · 预算）. */
function scopeTexts(grains: RequirementGrain[]): string[] {
  const groups = new Map<string, string[]>();
  for (const grain of grains) {
    const when = periodScenario(grain);
    const organizations = groups.get(when) ?? [];
    if (grain.organization && !organizations.includes(grain.organization)) organizations.push(grain.organization);
    groups.set(when, organizations);
  }
  return [...groups].flatMap(([when, organizations]) => {
    if (!organizations.length) return when ? [when] : [];
    return [when ? `${organizations.join('、')}（${when}）` : organizations.join('、')];
  });
}

/**
 * The requirement issues of one group, merged by reason: each reason once, with the requirements it holds back
 * and the organizations or periods involved. The server's full sentence stays with each raw issue.
 */
export function requirementGapRows(issues: EvidenceIssue[], items: RequirementItemView[] = []): RequirementGapRow[] {
  const rows = new Map<string, { requirements: string[]; grains: RequirementGrain[] }>();
  const add = (reason: string, requirement: string, grains: RequirementGrain[]) => {
    const row = rows.get(reason) ?? { requirements: [], grains: [] };
    if (requirement && !row.requirements.includes(requirement)) row.requirements.push(requirement);
    row.grains.push(...grains);
    rows.set(reason, row);
  };
  for (const issue of issues) {
    const item = items.find((candidate) => candidate.id === issue.requirement_item_id);
    const label = item?.label || quotedLabel(issue.message);
    if (issue.code === 'requested_source_missing') {
      add(SOURCE_MISSING, label, []);
      continue;
    }
    if (issue.code !== 'requirement_unanswered') continue;
    const waiting = item?.awaiting_manager ?? [];
    const unbacked = [...(item?.missing_grains ?? []), ...(item?.uncounted_grains ?? [])];
    // Grains with no counted value are open whether or not other grains wait for the manager.
    if (!waiting.length || unbacked.length) add(UNANSWERED, label, unbacked);
    for (const code of waiting) {
      // A reason this view does not know yet is named by its code rather than folded into a general line.
      add(MANAGER_REASONS[code] ?? `需要你处理（${code}）`, label,
        DECLARED.has(code) ? (item?.declared_grains ?? []).filter((grain) => grain.state === code) : []);
    }
  }
  return [...rows].map(([reason, row]) => {
    const reasons = new Set(row.grains.map((grain) => grain.reason ?? ''));
    const detail = row.grains.length && reasons.size === 1 ? [...reasons][0] : '';
    return { reason, ...(detail ? { detail } : {}), requirements: row.requirements, scopes: scopeTexts(row.grains) };
  });
}
