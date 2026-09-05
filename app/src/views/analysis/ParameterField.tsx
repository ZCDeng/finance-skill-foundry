import type { AnalysisParameterMetadata } from '../../bridge.js';

/** Keep numeric inputs as decimal text. The calculation service validates declared constraints. */
export function ParameterField({ metadata, value, disabled, onChange }: {
  metadata: AnalysisParameterMetadata; value: unknown; disabled?: boolean; onChange(value: string | boolean | null): void;
}) {
  const name = `${metadata.label}${metadata.unit ? `（${metadata.unit}）` : ''}`;
  const choices = metadata.constraints?.choices;
  const shown = value == null ? '' : String(value);
  const help = [metadata.description,
    metadata.constraints?.min != null ? `最小值 ${metadata.constraints.min}` : '',
    metadata.constraints?.max != null ? `最大值 ${metadata.constraints.max}` : '',
  ].filter(Boolean).join(' · ');
  return <label>{name}
    {choices ? <select aria-label={name} className="fnd-field" value={shown} disabled={disabled} onChange={(event) => {
      const match = choices.find((item) => String(item ?? '') === event.target.value);
      onChange(match == null ? null : typeof match === 'boolean' ? match : String(match));
    }}><option value="">请选择</option>{choices.map((item, index) => <option key={index} value={String(item ?? '')}>{item == null ? '未指定' : String(item)}</option>)}</select>
      : metadata.type === 'boolean' ? <select aria-label={name} className="fnd-field" value={shown} disabled={disabled}
        onChange={(event) => onChange(event.target.value === '' ? null : event.target.value === 'true')}>
        <option value="">请选择</option><option value="true">是</option><option value="false">否</option></select>
        : <input aria-label={name} className="fnd-field" type={metadata.type === 'date' ? 'date' : 'text'}
          inputMode={metadata.type === 'decimal' || metadata.type === 'integer' ? 'decimal' : undefined}
          value={shown} disabled={disabled} onChange={(event) => onChange(event.target.value === '' && metadata.constraints?.nullable ? null : event.target.value)} />}
    {help && <span className="analysis-note">{help}</span>}
  </label>;
}
