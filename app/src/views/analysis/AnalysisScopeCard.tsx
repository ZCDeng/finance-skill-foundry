import { useEffect, useRef, useState } from 'react';
import { Save } from 'lucide-react';
import { bridge, type Answer } from '../../bridge.js';
import { Button } from '../../components/ui/button.js';
import { Input } from '../../components/ui/input.js';
import { errorText } from './shared.js';

type ScopeRecord = {
  id: string;
  question: string;
  scope?: Record<string, unknown>;
  bindings?: Record<string, string>;
  items?: unknown[];
};

type RequirementsList = {
  current?: ScopeRecord | null;
  requirements?: ScopeRecord[];
};

function unwrap<T>(answer: Answer<T>): T {
  if (!answer.ok) throw new Error(answer.message);
  return answer.value;
}

function scopeValue(scope: Record<string, unknown> | undefined, key: string, fallback = ''): string {
  return String(scope?.[key] ?? fallback);
}

const editableScopeKeys = ['period', 'granularity', 'unit', 'currency', 'scenario', 'organization'] as const;
type EditableScope = Record<(typeof editableScopeKeys)[number], string>;

// The fields and the carried keys always mirror the stored record: a save may drop a legacy key (a
// drilldown level), and resending the copy loaded earlier would be refused on the next save.
function editableScope(scope: Record<string, unknown> | undefined): EditableScope {
  return Object.fromEntries(editableScopeKeys.map((key) => [key, scopeValue(scope, key)])) as EditableScope;
}

function carriedScope(scope: Record<string, unknown> | undefined): Record<string, unknown> {
  return Object.fromEntries(Object.entries(scope ?? {}).filter(([key]) => !editableScopeKeys.includes(key as (typeof editableScopeKeys)[number])));
}

const itemScopeKeys = [
  { field: 'period', itemField: 'periods', label: '期间' },
  { field: 'organization', itemField: 'organizations', label: '组织' },
  { field: 'scenario', itemField: 'scenarios', label: '情景' },
] as const;

function conflictingItemScope(items: unknown[] | undefined, itemField: string, value: string): boolean {
  return Boolean(value && items?.some((item) => {
    if (!item || typeof item !== 'object') return false;
    const values = (item as Record<string, unknown>)[itemField];
    return Array.isArray(values) && values.length > 0 && (values.length !== 1 || values[0] !== value);
  }));
}

export function AnalysisScopeCard({ taskId, question, datasets, disabled, onSaved }: {
  taskId: string;
  question: string;
  datasets: { id: string; name: string }[];
  disabled?: boolean;
  onSaved?(record: ScopeRecord): void;
}) {
  const [current, setCurrent] = useState<ScopeRecord | null>(null);
  const [scope, setScope] = useState<EditableScope>(() => editableScope(undefined));
  const [extraScope, setExtraScope] = useState<Record<string, unknown>>({});
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const request = useRef(0);
  const saveRequest = useRef(0);
  useEffect(() => {
    const api = bridge();
    const seq = request.current + 1;
    request.current = seq;
    if (!api?.financeCall || !taskId) return;
    setLoading(true);
    setError('');
    void api.financeCall(taskId, 'analysis-requirements-list', {}).then((answer) => {
      if (request.current !== seq) return;
      const payload = unwrap(answer as Answer<RequirementsList>);
      const next = payload.current ?? null;
      setCurrent(next);
      setScope(editableScope(next?.scope));
      setExtraScope(carriedScope(next?.scope));
    }).catch((reason: unknown) => {
      if (request.current !== seq) return;
      setError(errorText(reason));
    }).finally(() => {
      if (request.current === seq) setLoading(false);
    });
  }, [taskId]);
  const setField = (key: keyof typeof scope, value: string) => setScope((previous) => ({ ...previous, [key]: value }));
  async function save() {
    const api = bridge();
    if (!api?.financeCall) return;
    const seq = saveRequest.current + 1;
    saveRequest.current = seq;
    setSaving(true);
    setMessage('');
    setError('');
    try {
      const record = unwrap(await api.financeCall(taskId, 'analysis-requirements-save', {
        question: current?.question ?? question,
        scope: { ...extraScope, ...Object.fromEntries(Object.entries(scope).filter(([, value]) => value.trim())) },
        bindings: current?.bindings ?? {},
        ...(current?.id ? { parent_id: current.id } : {}),
        change_reason: current?.id ? '更新分析前置口径。' : undefined,
        items: current?.items ?? [],
      }) as Answer<ScopeRecord>);
      if (saveRequest.current !== seq) return;
      setCurrent(record);
      setScope(editableScope(record.scope));
      setExtraScope(carriedScope(record.scope));
      setMessage('已保存分析口径，旧版本仍保留。');
      onSaved?.(record);
    } catch (reason) {
      if (saveRequest.current !== seq) return;
      setError(errorText(reason));
    } finally {
      if (saveRequest.current === seq) setSaving(false);
    }
  }
  const blocked = disabled || loading || saving || !taskId || !bridge()?.financeCall;
  const conflicts = itemScopeKeys.filter(({ field, itemField }) => conflictingItemScope(current?.items, itemField, scope[field]));
  return <section className="analysis-scope-card" aria-label="分析口径">
    <div className="analysis-section-heading"><div><h3>分析口径</h3><p className="analysis-note">运行前确认期间、单位、情景和组织；保存会生成新版要求。</p></div>
      <span className="analysis-note" title={current?.id}>{current ? '已保存' : '未保存'} · 资料 {datasets.length} 份</span></div>
    {loading ? <p role="status" className="analysis-note">正在读取已保存口径…</p> : null}
    <div className="analysis-edit-grid">
      <label>期间<Input aria-label="分析口径期间" disabled={blocked} value={scope.period} onChange={(event) => setField('period', event.target.value)} placeholder="待确认，例如 2026-08 / 2026 YTD" /></label>
      <label>粒度<Input aria-label="分析口径粒度" disabled={blocked} value={scope.granularity} onChange={(event) => setField('granularity', event.target.value)} placeholder="待确认" /></label>
      <label>单位<Input aria-label="分析口径单位" disabled={blocked} value={scope.unit} onChange={(event) => setField('unit', event.target.value)} placeholder="待确认" /></label>
      <label>币种<Input aria-label="分析口径币种" disabled={blocked} value={scope.currency} onChange={(event) => setField('currency', event.target.value)} placeholder="待确认" /></label>
      <label>情景<Input aria-label="分析口径情景" disabled={blocked} value={scope.scenario} onChange={(event) => setField('scenario', event.target.value)} placeholder="待确认" /></label>
      <label>组织<Input aria-label="分析口径组织" disabled={blocked} value={scope.organization} onChange={(event) => setField('organization', event.target.value)} placeholder="待确认" /></label>
    </div>
    {conflicts.map(({ field, label }) => <p key={field} role="alert" className="analysis-message analysis-message--error">
      共享{label}与逐项{label}冲突。<Button type="button" variant="outline" disabled={blocked}
        onClick={() => setField(field, '')}>移除共享{label}，保留逐项{label}</Button>
    </p>)}
    {error ? <p role="alert" className="analysis-message analysis-message--error">{error}</p> : null}
    {message ? <p role="status" className="analysis-message">{message}</p> : null}
    <Button type="button" disabled={blocked || conflicts.length > 0} onClick={() => void save()}><Save size={14} aria-hidden />保存口径</Button>
  </section>;
}
