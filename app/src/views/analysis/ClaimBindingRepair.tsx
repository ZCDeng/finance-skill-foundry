import { useState } from 'react';
import { when, type AnalysisRun } from '../../bridge.js';
import { Button } from '../../components/ui/button.js';
import { SearchableSelect } from '../../components/FinancialControls.js';
import { DisclosureSummary } from '../../components/Disclosure.js';

/** Only selects real result cells. The backend still validates the complete draft. */
export function ClaimBindingRepair({ claims, runs, disabled, onChange }: {
  claims: unknown[]; runs: AnalysisRun[]; disabled: boolean; onChange(claims: unknown[]): void;
}) {
  const [selections, setSelections] = useState<Record<number, string>>({});
  const cells = runs.filter((run) => ['succeeded', 'success'].includes(run.execution_status)).flatMap((run) =>
    (run.result?.rows ?? []).flatMap((row, index) => Object.entries(row).filter(([, value]) =>
      typeof value === 'number' || typeof value === 'string' && /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(value)
    ).map(([column, value]) => ({ id: JSON.stringify([run.id, index, column]), run_id: run.id, row: index, column,
      value: String(value), label: `${String(row.metric ?? row.label ?? row.name ?? `第 ${index + 1} 行`)} · ${column} = ${String(value)}`,
      meta: `${when(run.created_at)} 的计算 · 第 ${index + 1} 行` }))));
  const calculated = claims.flatMap((value, index) => value && typeof value === 'object'
    && (value as Record<string, unknown>).basis === 'calculation' ? [{ claim: value as Record<string, unknown>, index }] : []);
  if (!calculated.length) return null;
  return <details className="analysis-details" open>
    <DisclosureSummary>修正计算引用 · {calculated.length} 条</DisclosureSummary>
    <p className="analysis-note">选择真实计算结果后采用对应数字。正文保留原文，仍需同步核对；保存时会再次检查。</p>
    {calculated.map(({ claim, index }) => {
      const selected = selections[index] ?? JSON.stringify([claim.run_id, claim.row, claim.column]);
      const cell = cells.find((candidate) => candidate.id === selected);
      return <div className="analysis-claim-repair" key={index}>
        <p>引用 {index + 1} · 填报值 {String(claim.value ?? '未填写')}{cell ? ` · 所选结果 ${cell.value}` : ' · 原位置不可用'}</p>
        <SearchableSelect label={`计算引用 ${index + 1} 的依据`} value={selected} disabled={disabled}
          options={cells.map((candidate) => ({ value: candidate.id, label: candidate.label, meta: candidate.meta }))}
          onChange={(value) => setSelections((previous) => ({ ...previous, [index]: value }))} placeholder="搜索指标、列名或结果值" />
        <Button type="button" variant="outline" disabled={disabled || !cell} onClick={() => {
          if (!cell) return;
          const { fact_id: _oldFact, ...rest } = claim;
          onChange(claims.map((value, current) => current === index ? { ...rest, basis: 'calculation', run_id: cell.run_id,
            row: cell.row, column: cell.column, value: cell.value } : value));
        }}>采用引用 {index + 1} 的结果值</Button>
      </div>;
    })}
  </details>;
}
