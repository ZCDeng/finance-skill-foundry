import { useEffect, useState } from 'react';
import type { AnalysisRun } from '../../bridge.js';
import { textValue } from './presentation.js';
import { DecimalInput, FieldShell, SearchableSelect, type SelectOption } from '../../components/FinancialControls.js';
import { DisclosureSummary } from '../../components/Disclosure.js';
import { ElasticSlider } from '../../components/ElasticSlider.js';

type MaterialityDenominator = 'baseline_abs' | 'actual_abs' | 'max_abs';
type MaterialityNegativePolicy = 'absolute' | 'signed';
export type MaterialityEdit = { absolute: string; relative: string; denominator: MaterialityDenominator; negativePolicy: MaterialityNegativePolicy };

const denominatorOptions: SelectOption[] = [
  { value: 'baseline_abs', label: '按基准金额' },
  { value: 'actual_abs', label: '按实际金额' },
  { value: 'max_abs', label: '按较大金额' },
];
const negativePolicyOptions: SelectOption[] = [
  { value: 'absolute', label: '按绝对值比较' },
  { value: 'signed', label: '保留正负方向' },
];
function validDenominator(value: unknown): MaterialityDenominator {
  return value === 'actual_abs' || value === 'max_abs' ? value : 'baseline_abs';
}

function validNegativePolicy(value: unknown): MaterialityNegativePolicy {
  return value === 'signed' ? 'signed' : 'absolute';
}

export function materialityToEdit(value: unknown): MaterialityEdit {
  const source = value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
  const relativeObject = source.relative && typeof source.relative === 'object' && !Array.isArray(source.relative) ? source.relative as Record<string, unknown> : null;
  const relativeValue = relativeObject ? relativeObject.threshold ?? relativeObject.value : source.relative;
  return {
    absolute: String(source.absolute ?? '0'),
    relative: relativeValue == null ? '' : String(relativeValue),
    denominator: validDenominator(relativeObject?.denominator),
    negativePolicy: validNegativePolicy(relativeObject?.negative_policy),
  };
}

export function materialityToSpec(value: MaterialityEdit): Record<string, unknown> {
  const absolute = value.absolute.trim() || '0';
  const relative = value.relative.trim();
  return {
    absolute,
    ...(relative ? { relative: { threshold: relative, denominator: value.denominator, negative_policy: value.negativePolicy } } : {}),
  };
}

export function sameMateriality(edit: MaterialityEdit | undefined, saved: unknown): boolean {
  return JSON.stringify(materialityToSpec(edit ?? materialityToEdit(undefined))) === JSON.stringify(materialityToSpec(materialityToEdit(saved)));
}


export function materialityScopeSummary(runs: AnalysisRun[]): string {
  const groups = Array.from(new Set(runs.flatMap((run) => Object.values(run.finance_scope ?? {}).map((scope) => {
    const currency = scope.currency ? textValue(scope.currency) : '未注明币种';
    const unit = scope.unit ? textValue(scope.unit) : '未注明单位';
    return `${currency}/${unit}`;
  }))));
  if (!groups.length) return '按运行结果的原币原单位判断；当前运行未注明币种或单位。';
  if (groups.length === 1) return `按运行结果原币原单位判断：${groups[0]}。`;
  return `按每组运行结果的原币原单位判断：${groups.join('；')}。`;
}

export function MaterialityFields({ value, scopeText, error, disabled, onChange }: { value: MaterialityEdit; scopeText: string; error?: string; disabled?: boolean; onChange(value: MaterialityEdit): void }) {

  const set = (patch: Partial<MaterialityEdit>) => onChange({ ...value, ...patch });
  // Folded by default with the values in its summary; an error opens it, and
  // clearing the error never closes it under the manager's cursor.
  const [open, setOpen] = useState(Boolean(error));
  useEffect(() => { if (error) setOpen(true); }, [error]);
  const summary = [value.absolute && `绝对 ${value.absolute}`, value.relative && `相对 ${value.relative}`].filter(Boolean).join(' · ');
  return <details className="analysis-details" open={open} onToggle={(event) => setOpen((event.currentTarget as HTMLDetailsElement).open)}>
    <DisclosureSummary>重要性阈值{summary ? ` · ${summary}` : ' · 未设置'}</DisclosureSummary>
    <p className="analysis-note">用于准备可引用事实和重检覆盖范围。相对阈值填 0.1 表示 10%。</p>
    <div className="analysis-edit-grid">
      <DecimalInput label="重要性绝对金额" value={value.absolute} onChange={(absolute) => set({ absolute })} placeholder="0"
        disabled={disabled} help="只填阈值，不做单位换算。" />
      <FieldShell label="阈值单位"><p className="analysis-note">{scopeText}</p></FieldShell>
      <div className="fnd-slider-pair">
        <DecimalInput label="相对重要性阈值" value={value.relative} onChange={(relative) => set({ relative })} placeholder="0.1" unit="比例"
          disabled={disabled} help={error || '可选；0.1 = 10%，留空则只使用绝对金额。滑块覆盖 0–30%，更大的值直接填写。'} />
        <ElasticSlider label="相对阈值" ariaLabel="相对重要性阈值，拖动选择" value={value.relative.trim() ? Number(value.relative) : null}
          min={0} max={0.3} step={0.005} format={(ratio) => `${(ratio * 100).toFixed(1)}%`} disabled={disabled}
          onChange={(ratio) => set({ relative: String(Number(ratio.toFixed(3))) })} />
      </div>
      <SearchableSelect label="相对分母" value={value.denominator} options={denominatorOptions} onChange={(denominator) => set({ denominator: validDenominator(denominator) })}
        disabled={disabled} />
      <SearchableSelect label="负数比较规则" value={value.negativePolicy} options={negativePolicyOptions} onChange={(negativePolicy) => set({ negativePolicy: validNegativePolicy(negativePolicy) })}
        disabled={disabled} />
    </div>
    {error ? <p role="alert" className="analysis-message analysis-message--error">{error}</p> : null}
  </details>;
}
