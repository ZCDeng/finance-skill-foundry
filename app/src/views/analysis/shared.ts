import { shortSha, when, type Answer, type AnalysisRun, type DatasetSnapshot, type FinanceContext, type FinanceContextState } from '../../bridge.js';
import { textValue } from './presentation.js';
import type { SelectOption } from '../../components/FinancialControls.js';

export const metricLabel = (value: unknown): string => {
  if (value && typeof value === 'object' && 'name' in value && 'expression' in value
    && typeof value.name === 'string' && typeof value.expression === 'string') {
    return `${value.name}：${value.expression}`;
  }
  return textValue(value);
};

export function unwrap<T>(answer: Answer<T>): T {
  if (!answer.ok) throw new Error(answer.message);
  return answer.value;
}

export const scopeFields = [
  ['ledger', '账簿'], ['organization', '组织'], ['period', '期间'],
  ['currency', '币种'], ['unit', '单位'], ['scenario', '情景'],
] as const;

export const datasetSize = (source: DatasetSnapshot): string => source.kind === 'workbook'
  ? typeof source.transformation?.sheet_count === 'number' ? `${source.transformation.sheet_count} 张工作表` : ''
  : source.row_count == null ? '' : `${source.row_count} 行`;
export const datasetOptions = (datasets: DatasetSnapshot[]): SelectOption[] => datasets.map((source) => ({
  value: source.id,
  label: source.name,
  meta: [source.source_name ?? source.kind, datasetSize(source), shortSha(source.id)].filter(Boolean).join(' · '),
}));
export const runOptions = (runs: AnalysisRun[]): SelectOption[] => runs.filter((row) => row.execution_status === 'succeeded').map((row) => ({
  value: row.id,
  label: when(row.created_at),
  meta: shortSha(row.id),
}));
export const contextOptions = (finance: FinanceContextState | null): SelectOption[] => finance?.contexts.map((context) => ({
  value: context.id,
  label: context.name,
  meta: Object.entries(context.scopes ?? {}).map(([alias, item]) => `${alias} ${scopeSummary(item)}`).join('；') || shortSha(context.id),
})) ?? [];
export const accountMapOptions = (finance: FinanceContextState | null): SelectOption[] => finance?.account_maps.map((item) => ({
  value: String(item.id ?? ''),
  label: textValue(item.name ?? '管理科目映射'),
  meta: shortSha(String(item.id ?? '')),
})).filter((item) => item.value) ?? [];
export const aliasOptions = (aliases: string[], context?: FinanceContext): SelectOption[] => aliases.map((alias) => ({
  value: alias,
  label: alias,
  meta: shortSha(context?.bindings[alias] ?? ''),
}));

export function scopeSummary(scope: Record<string, unknown> = {}): string {
  return scopeFields.map(([key, label]) => scope[key] ? `${label} ${textValue(scope[key])}` : '').filter(Boolean).join(' · ') || '未限定';
}

const STRUCTURE_LABELS: Record<string, string> = {
  pending_confirmation: '待确认表结构',
  pending_acknowledgement: '待经理追认',
  no_table: '没有可用的表',
  withdrawn: '已撤回',
};

export function structureLabel(source: DatasetSnapshot): string {
  const state = (source as { structure_state?: string }).structure_state ?? '';
  return STRUCTURE_LABELS[state] ?? '';
}
