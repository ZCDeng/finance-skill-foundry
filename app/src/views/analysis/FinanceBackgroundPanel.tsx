import type { DatasetSnapshot } from '../../bridge.js';
import { textValue } from './presentation.js';
import { AccountingPeriodInput, DateInput, FieldShell, PeriodRangeInput, SearchableSelect, TextField } from '../../components/FinancialControls.js';
import { Button } from '../../components/ui/button.js';
import { Input } from '../../components/ui/input.js';
import { Textarea } from '../../components/ui/textarea.js';
import { CURRENCY_OPTIONS, UNIT_OPTIONS } from './glossary.js';
import { datasetOptions, scopeSummary } from './shared.js';
import { NativeSelect } from '../../components/ui/native-select.js';
import { DisclosureSummary } from '../../components/Disclosure.js';

export interface FinanceBackground {
  id?: string; label?: string; text?: string; paragraph?: string; basis?: string; scope?: Record<string, unknown>; effective_from?: string; effective_to?: string; dataset_id?: string; created_at?: string;
}

function choices(options: { value: string; label: string; meta?: string }[], saved: string) {
  if (!saved || options.some((option) => option.value === saved)) return options;
  return [{ value: saved, label: saved, meta: '已保存的值' }, ...options];
}

export function FinanceBackgroundPanel({ background, scope, scopeJson, backgrounds, datasets, busy, message, onBackground, onScope, onScopeJson, onSave, onList }: {
  background: { label: string; text: string; basis: string; effective_from: string; effective_to: string; dataset_id: string; paragraph: string; source: string; retrieved_at: string };
  scope: Record<string, string>; scopeJson: string; backgrounds: FinanceBackground[]; datasets: DatasetSnapshot[]; busy: boolean; message: string;
  onBackground(next: { label: string; text: string; basis: string; effective_from: string; effective_to: string; dataset_id: string; paragraph: string; source: string; retrieved_at: string }): void;
  onScope(next: Record<string, string>): void; onScopeJson(next: string): void; onSave(): void; onList(): void;
}) {
  return <details className="analysis-details analysis-background-panel"><DisclosureSummary>财务背景与经理判断</DisclosureSummary>
    <p className="analysis-note">保存业务原因、经理判断或资料来源解释。背景按范围和有效期复用，经理可改适用范围。</p>
    <fieldset className="analysis-fieldset" disabled={busy}><div className="analysis-edit-grid">
      <label>标题<Input className="min-w-0 flex-1" value={background.label} onChange={(event) => onBackground({ ...background, label: event.target.value })}  /></label>
      <FieldShell label="依据类型"><NativeSelect aria-label="依据类型" value={background.basis} onChange={(event) => onBackground({ ...background, basis: event.target.value })}>
        <option value="professional_judgment">经理专业判断</option><option value="user_assumption">业务假设</option><option value="source_fact">资料事实</option><option value="external_reference">外部依据</option></NativeSelect></FieldShell>
      <div className="analysis-period-range"><PeriodRangeInput label="适用期间范围" start={background.effective_from} end={background.effective_to}
        onChange={({ start, end }) => onBackground({ ...background, effective_from: start, effective_to: end })}
        help="设置这项背景适用的开始与结束期间；结束期间可留空。" /></div>
      {(background.basis === 'source_fact') && <><SearchableSelect label="授权资料" ariaLabel="背景授权资料" value={background.dataset_id}
        options={datasetOptions(datasets)} onChange={(value) => onBackground({ ...background, dataset_id: value })} placeholder="搜索授权资料" allowEmptyLabel="选择资料" />
        <TextField label="段落编号" ariaLabel="背景段落编号" value={background.paragraph} onChange={(value) => onBackground({ ...background, paragraph: value })} inputMode="numeric" /></>}
      {(background.basis === 'external_reference') && <><TextField label="外部来源" ariaLabel="背景外部来源" value={background.source} onChange={(value) => onBackground({ ...background, source: value })} />
        <DateInput label="查询日期" ariaLabel="背景查询日期" value={background.retrieved_at} onChange={(value) => onBackground({ ...background, retrieved_at: value })} /></>}
    </div><label>背景正文<Textarea className="analysis-code" rows={3} value={background.text} onChange={(event) => onBackground({ ...background, text: event.target.value })} /></label>
    <details className="analysis-details"><DisclosureSummary>适用范围 · {scopeSummary(scope)}</DisclosureSummary>
      <p className="analysis-note">默认沿用这次计算的范围；只在这项背景另有适用范围时修改。</p>
      <div className="analysis-edit-grid">
        <AccountingPeriodInput label="期间" ariaLabel="背景期间" value={scope.period ?? ''} onChange={(value) => onScope({ ...scope, period: value })} />
        <TextField label="组织" ariaLabel="背景组织" value={scope.organization ?? ''} onChange={(value) => onScope({ ...scope, organization: value })} />
        <SearchableSelect label="单位" ariaLabel="背景单位" value={scope.unit ?? ''} options={choices(UNIT_OPTIONS, scope.unit ?? '')}
          onChange={(value) => onScope({ ...scope, unit: value })} allowEmptyLabel="待确认" clearable placeholder="选择单位" />
        <SearchableSelect label="币种" ariaLabel="背景币种" value={scope.currency ?? ''} options={choices(CURRENCY_OPTIONS, scope.currency ?? '')}
          onChange={(value) => onScope({ ...scope, currency: value })} allowEmptyLabel="待确认" clearable placeholder="选择币种" />
        <TextField label="账簿" ariaLabel="背景账簿" value={scope.ledger ?? ''} onChange={(value) => onScope({ ...scope, ledger: value })} />
      </div>
      <details className="analysis-details"><DisclosureSummary>高级：补充范围 JSON</DisclosureSummary><Textarea aria-label="补充范围 JSON" className="analysis-code" rows={4} value={scopeJson} onChange={(event) => onScopeJson(event.target.value)} /></details>
    </details></fieldset>
    <div className="analysis-actions"><Button variant="outline" type="button" disabled={busy || !background.text.trim()} onClick={onSave}>保存背景</Button>
      <Button variant="outline" type="button" disabled={busy} onClick={onList}>刷新适用背景</Button></div>
    {message && <p role="status" className="analysis-message">{message}</p>}
    {backgrounds.length > 0 && <div className="analysis-history-list">{backgrounds.map((item, index) => <div className="analysis-history-row analysis-history-row--static" key={item.id ?? index}>
      <span>{textValue(item.label ?? item.basis ?? '财务背景')}</span><span>{textValue(item.text ?? item.paragraph ?? '')}</span>
      <span>{scopeSummary(item.scope ?? {})}</span><span>{textValue(item.effective_from ?? '未设期间')}{item.effective_to ? ` 至 ${textValue(item.effective_to)}` : ''}</span>
    </div>)}</div>}
  </details>;
}
