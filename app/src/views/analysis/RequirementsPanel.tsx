import { useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, MessageSquare, Plus, Save, Trash2 } from 'lucide-react';
import { bridge, type Answer, type FinanceContextState } from '../../bridge.js';
import { AccountingPeriodInput, FieldShell, SearchableSelect, TextField, type SelectOption } from '../../components/FinancialControls.js';
import { Button } from '../../components/ui/button.js';
import { Textarea } from '../../components/ui/textarea.js';

type RequirementScope = {
  ledger?: string;
  organization?: string;
  period?: string;
  currency?: string;
  unit?: string;
};

// The assistant's declaration that some grains are estimates or unavailable. The panel does not edit it,
// but it must survive a manager save: without it a declared estimate falls back to a pending grain.
type GrainBasis = {
  basis: string;
  organizations?: string[];
  periods?: string[];
  scenarios?: string[];
} & Record<string, unknown>;

type RequirementItem = {
  id: string;
  metric: string;
  label: string;
  dimensions: Record<string, unknown>;
  requires_drilldown: boolean;
  periods?: string[];
  organizations?: string[];
  scenarios?: string[];
  grain_basis?: GrainBasis[];
};

type RequirementMissingInput = {
  dataset_id?: string | null;
  alias?: string | null;
  columns: string[];
};

type RequirementSupportItem = {
  requirement_item_id: string;
  status: 'requires_execution' | 'requires_input' | 'unrecognized' | 'unverified' | string;
  canonical_metric?: string | null;
  next_action?: string | null;
  missing_inputs?: RequirementMissingInput[];
};

type RequirementSupport = {
  items?: RequirementSupportItem[];
};

export type AnalysisRequirementsRecord = {
  id: string;
  question: string;
  scope: RequirementScope & Record<string, unknown>;
  bindings: Record<string, string>;
  context_id?: string | null;
  items: RequirementItem[];
  parent_id?: string | null;
  change_reason?: string;
  removed_item_ids?: string[];
  support?: RequirementSupport | null;
};

type RequirementsListPayload = {
  requirements?: AnalysisRequirementsRecord[];
  current?: AnalysisRequirementsRecord | null;
};

export type RequirementsPanelProps = {
  taskId?: string;
  contextId?: string;
  draftRequirementsId?: string;
  onChanged?(requirements: AnalysisRequirementsRecord): void;
  onDiscuss?(draft: {
    question: string;
    scope: RequirementScope & Record<string, unknown>;
    items: RequirementItem[];
    currentRequirementsId?: string;
    draftRequirementsId?: string;
  }): void;
};

const blankScope: RequirementScope = {};
const metricOptions = [
  { value: 'profit', label: '利润', meta: 'profit / management_profit' },
  { value: 'revenue', label: '收入', meta: 'revenue' },
  { value: 'cost', label: '成本', meta: 'cost' },
  { value: 'expense', label: '费用', meta: 'expense' },
  { value: 'open_amount', label: '应收余额', meta: '账龄 open_amount' },
  { value: 'closing_cash', label: '期末现金', meta: '13周现金 closing_cash' },
  { value: 'ratio', label: '比率', meta: 'ratio' },
  { value: 'control_totals', label: '控制合计', meta: 'control_totals' },
  { value: 'account_total', label: '科目合计', meta: 'account_total' },
  { value: 'total_variance', label: '总额差异', meta: 'total_variance' },
  { value: 'price_quantity', label: '量价分解', meta: 'price_quantity' },
];
const currencyOptions = [
  { value: 'CNY', label: 'CNY', meta: '人民币' },
  { value: 'USD', label: 'USD', meta: '美元' },
  { value: 'EUR', label: 'EUR', meta: '欧元' },
];
const unitOptions = [
  { value: '万元', label: '万元', meta: '管理报表常用' },
  { value: '元', label: '元', meta: '明细账常用' },
];

function unwrap<T>(answer: Answer<T>): T {
  if (!answer.ok) throw new Error(answer.message);
  return answer.value;
}

function normalizeScope(value: unknown): RequirementScope & Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return { ...blankScope };
  return { ...(value as Record<string, unknown>) };
}

function pruneScope(value: RequirementScope & Record<string, unknown>): RequirementScope & Record<string, unknown> {
  return Object.fromEntries(Object.entries(value).filter(([, item]) => item !== '' && item !== undefined && item !== null)) as RequirementScope & Record<string, unknown>;
}

// Hierarchy levels a finance context may hold (finance_context_save accepts any key) but a requirement scope
// refuses (SCOPE_REFUSED_HIERARCHY_KEYS in foundry/finance_requirements.py). The panel has no field for them,
// so a context seed must not carry them into a save the manager cannot correct. granularity stays, and so does
// a key such as level, which may be a real row column the scope filters on.
const contextOnlyScopeLevels = new Set(['drilldown', 'drill_down']);

function primaryContextScope(payload: FinanceContextState | null | undefined, selectedContextId?: string): { scope: RequirementScope & Record<string, unknown>; bindings: Record<string, string> } {
  const context = payload?.contexts?.find((item) => item.id === selectedContextId);
  if (!context) return { scope: { ...blankScope }, bindings: {} };
  const firstScope = Object.values(context.scopes ?? {}).find((item) => item && typeof item === 'object' && !Array.isArray(item));
  const seeded = Object.fromEntries(Object.entries(normalizeScope(firstScope))
    .filter(([key]) => !contextOnlyScopeLevels.has(key.trim().toLowerCase()))) as RequirementScope & Record<string, unknown>;
  return { scope: seeded, bindings: context.bindings ?? {} };
}

function normalizePeriods(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item ?? '').trim()).filter(Boolean);
}

function itemOrganizations(item: RequirementItem): string[] {
  return normalizePeriods(item.organizations);
}

function itemScenarios(item: RequirementItem): string[] {
  return normalizePeriods(item.scenarios);
}

const grainBasisLists = ['organizations', 'periods', 'scenarios'] as const;

function normalizeGrainBasis(value: unknown): GrainBasis[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((entry): entry is GrainBasis => Boolean(entry) && typeof entry === 'object' && !Array.isArray(entry)
      && typeof (entry as Record<string, unknown>).basis === 'string')
    .map((entry) => ({ ...entry }));
}

// A declaration covers a subset of the item's grains. When the manager removes one of its members the
// declaration keeps the rest; one left with no member is dropped, because an empty list would widen it
// to every grain of the item.
function keptGrainBasis(item: RequirementItem): GrainBasis[] {
  const lists = { organizations: itemOrganizations(item), periods: itemPeriods(item), scenarios: itemScenarios(item) };
  return (item.grain_basis ?? []).flatMap((entry) => {
    const next: GrainBasis = { ...entry };
    for (const field of grainBasisLists) {
      const members = entry[field];
      if (!Array.isArray(members) || !members.length) continue;
      const kept = members.map(String).filter((member) => lists[field].includes(member));
      if (!kept.length) return [];
      next[field] = kept;
    }
    return [next];
  });
}

function normalizeMissingInputs(value: unknown): RequirementMissingInput[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => {
    if (typeof item === 'string') return { alias: item.trim(), columns: [] };
    if (!item || typeof item !== 'object' || Array.isArray(item)) return { columns: [] };
    const row = item as Record<string, unknown>;
    return {
      dataset_id: row.dataset_id == null ? null : String(row.dataset_id).trim(),
      alias: row.alias == null ? null : String(row.alias).trim(),
      columns: normalizePeriods(row.columns),
    };
  }).filter((item) => Boolean(item.alias || item.dataset_id || item.columns.length));
}

function formatMissingInput(input: RequirementMissingInput): string {
  const source = input.alias || input.dataset_id || '未指定资料';
  return input.columns.length ? `${source}（字段：${input.columns.join('、')}）` : source;
}

function normalizeSupport(value: unknown): RequirementSupport | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const support = value as { items?: unknown };
  return {
    items: Array.isArray(support.items) ? support.items.map((item) => {
      const row = item && typeof item === 'object' && !Array.isArray(item) ? item as Record<string, unknown> : {};
      return {
        requirement_item_id: String(row.requirement_item_id ?? ''),
        status: String(row.status ?? ''),
        canonical_metric: row.canonical_metric == null ? null : String(row.canonical_metric),
        next_action: row.next_action == null ? null : String(row.next_action),
        missing_inputs: normalizeMissingInputs(row.missing_inputs),
      };
    }).filter((item) => item.requirement_item_id && item.status) : [],
  };
}

function normalizeRecord(value: unknown): AnalysisRequirementsRecord | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const record = value as Partial<AnalysisRequirementsRecord>;
  if (typeof record.id !== 'string' || typeof record.question !== 'string') return null;
  return {
    id: record.id,
    question: record.question,
    scope: normalizeScope(record.scope),
    bindings: record.bindings && typeof record.bindings === 'object' && !Array.isArray(record.bindings) ? record.bindings : {},
    context_id: record.context_id ?? null,
    parent_id: record.parent_id ?? null,
    change_reason: record.change_reason,
    removed_item_ids: Array.isArray(record.removed_item_ids) ? record.removed_item_ids : [],
    support: normalizeSupport((record as Record<string, unknown>).support),
    items: Array.isArray(record.items) ? record.items.map((item) => ({
      id: String(item.id),
      metric: String(item.metric ?? ''),
      label: String(item.label ?? item.metric ?? ''),
      dimensions: item.dimensions && typeof item.dimensions === 'object' && !Array.isArray(item.dimensions) ? item.dimensions : {},
      requires_drilldown: item.requires_drilldown === true,
      periods: normalizePeriods((item as Record<string, unknown>).periods),
      ...(Array.isArray((item as Record<string, unknown>).scenarios)
        ? { scenarios: normalizePeriods((item as Record<string, unknown>).scenarios) }
        : {}),
      ...(Array.isArray((item as Record<string, unknown>).organizations)
        ? { organizations: normalizePeriods((item as Record<string, unknown>).organizations) }
        : {}),
      ...(normalizeGrainBasis((item as Record<string, unknown>).grain_basis).length
        ? { grain_basis: normalizeGrainBasis((item as Record<string, unknown>).grain_basis) }
        : {}),
    })).filter((item) => item.id && item.metric) : [],
  };
}

function nextItemId(items: RequirementItem[]): string {
  const used = new Set(items.map((item) => item.id));
  for (let index = items.length + 1; index < items.length + 200; index += 1) {
    const id = `req_${index}`;
    if (!used.has(id)) return id;
  }
  return `req_${Date.now().toString(36)}`;
}

function itemLabel(metric: string): string {
  return metricOptions.find((option) => option.value === metric)?.label ?? metric;
}

function itemPeriods(item: RequirementItem): string[] {
  return normalizePeriods(item.periods);
}


function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`;
  if (value && typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>).sort(([left], [right]) => left.localeCompare(right));
    return `{${entries.map(([key, item]) => `${JSON.stringify(key)}:${canonicalJson(item)}`).join(',')}}`;
  }
  return JSON.stringify(value);
}

function equalStringArrays(left: string[] | undefined, right: string[] | undefined): boolean {
  const leftValues = normalizePeriods(left);
  const rightValues = normalizePeriods(right);
  return leftValues.length === rightValues.length && leftValues.every((value, index) => value === rightValues[index]);
}

function safeJsonObject(text: string): Record<string, unknown> | null {
  try {
    const parsed = JSON.parse(text || '{}') as unknown;
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) return parsed as Record<string, unknown>;
  } catch {
    return null;
  }
  return null;
}

function shortId(value?: string | null): string {
  return value ? value.slice(0, 12) : '未保存';
}

function validAccountingPeriod(value: string): boolean {
  return /^\d{4}-(0[1-9]|1[0-2])$/.test(value);
}

function validPeriodRange(value: string): boolean {
  const match = /^(\d{4}-(?:0[1-9]|1[0-2])):(\d{4}-(?:0[1-9]|1[0-2]))$/.exec(value);
  return Boolean(match && match[1] <= match[2]);
}

function optionsWithSavedValue(options: SelectOption[], current: unknown, meta = '已保存自定义值'): SelectOption[] {
  const value = String(current ?? '');
  if (!value || options.some((option) => option.value === value)) return options;
  return [{ value, label: value, meta }, ...options];
}

function metricOptionsForItem(item: RequirementItem): SelectOption[] {
  const option = metricOptions.find((candidate) => candidate.value === item.metric);
  if (option || !item.metric) return metricOptions;
  return [{ value: item.metric, label: item.label || item.metric, meta: '已保存自定义指标' }, ...metricOptions];
}

export function RequirementsPanel({ taskId, contextId, draftRequirementsId, onChanged, onDiscuss }: RequirementsPanelProps) {
  const [records, setRecords] = useState<AnalysisRequirementsRecord[]>([]);
  const [current, setCurrent] = useState<AnalysisRequirementsRecord | null>(null);
  const [question, setQuestion] = useState('');
  const [scope, setScope] = useState<RequirementScope & Record<string, unknown>>({ ...blankScope });
  const [bindings, setBindings] = useState<Record<string, string>>({});
  const [items, setItems] = useState<RequirementItem[]>([]);
  const [removed, setRemoved] = useState<string[]>([]);
  const [changeReason, setChangeReason] = useState('');
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [invalidItemDimensions, setInvalidItemDimensions] = useState<Set<string>>(() => new Set());
  const requestSeq = useRef(0);
  const api = bridge();

  useEffect(() => {
    const seq = requestSeq.current + 1;
    requestSeq.current = seq;
    setMessage('');
    setError('');
    setRemoved([]);
    setChangeReason('');
    if (!taskId || !api?.financeCall) {
      setRecords([]);
      setCurrent(null);
      setQuestion('');
      setScope({ ...blankScope });
      setBindings({});
      setItems([]);
      setInvalidItemDimensions(new Set());
      setLoading(false);
      return;
    }
    const financeCall = api.financeCall;
    setLoading(true);
    void (async () => {
      const [requirementsAnswer, contextAnswer] = await Promise.all([
        financeCall(taskId, 'analysis-requirements-list', contextId ? { context_id: contextId } : {}),
        contextId ? financeCall(taskId, 'list-finance-context') : Promise.resolve(null),
      ]);
      if (requestSeq.current !== seq) return;
      const payload = unwrap(requirementsAnswer as Answer<RequirementsListPayload>);
      const contextSeed = contextAnswer ? primaryContextScope(unwrap(contextAnswer as Answer<FinanceContextState>), contextId) : { scope: { ...blankScope }, bindings: {} };
      const nextRecords = (payload.requirements ?? []).map(normalizeRecord).filter((row): row is AnalysisRequirementsRecord => Boolean(row));
      const nextCurrent = normalizeRecord(payload.current ?? nextRecords.at(-1));
      setRecords(nextRecords);
      setCurrent(nextCurrent);
      setQuestion(nextCurrent?.question ?? '');
      setScope(nextCurrent ? normalizeScope(nextCurrent.scope) : contextSeed.scope);
      setBindings(nextCurrent?.bindings ?? contextSeed.bindings);
      setItems(nextCurrent?.items ?? []);
      setInvalidItemDimensions(new Set());
    })().catch((reason: unknown) => {
      if (requestSeq.current !== seq) return;
      setError(reason instanceof Error ? reason.message : '读取分析要求失败。');
      setRecords([]);
      setCurrent(null);
      setQuestion('');
      setScope({ ...blankScope });
      setBindings({});
      setItems([]);
      setInvalidItemDimensions(new Set());
    }).finally(() => {
      if (requestSeq.current === seq) setLoading(false);
    });
  }, [api, contextId, taskId]);

  const removedExisting = useMemo(() => {
    const existing = new Set(current?.items.map((item) => item.id) ?? []);
    return removed.filter((id) => existing.has(id));
  }, [current, removed]);
  const duplicateIds = useMemo(() => items.some((item, index) => items.findIndex((other) => other.id === item.id) !== index), [items]);
  const hasInvalidDimensions = invalidItemDimensions.size > 0;
  const organizationConflict = Boolean(scope.organization && items.some((item) => {
    const organizations = itemOrganizations(item);
    return organizations.length && (organizations.length !== 1 || organizations[0] !== scope.organization);
  }));
  const periodConflict = Boolean(scope.period && items.some((item) => {
    const periods = itemPeriods(item);
    return periods.length && (periods.length !== 1 || periods[0] !== scope.period);
  }));
  const scopeChangedForDraft = Boolean(draftRequirementsId && current?.id && draftRequirementsId !== current.id);
  const canSave = Boolean(taskId && api?.financeCall && question.trim() && items.every((item) => item.metric.trim()) && !duplicateIds
    && !hasInvalidDimensions && !organizationConflict && !periodConflict && (!removedExisting.length || changeReason.trim()));

  const setScopeField = (key: keyof RequirementScope, value: string) => setScope((previous) => {
    const next = { ...previous };
    if (value) next[key] = value; else delete next[key];
    return next;
  });
  const setItem = (id: string, patch: Partial<RequirementItem>) => {
    setItems((previous) => previous.map((item) => item.id === id ? { ...item, ...patch } : item));
  };
  const addItem = () => {
    setItems((previous) => {
      const id = nextItemId(previous);
      return [...previous, { id, metric: 'profit', label: '利润', dimensions: {}, requires_drilldown: false, periods: [], organizations: [], scenarios: [] }];
    });
  };
  const removeItem = (id: string) => {
    setItems((previous) => previous.filter((item) => item.id !== id));
    setRemoved((previous) => previous.includes(id) ? previous : [...previous, id]);
    setInvalidItemDimensions((previous) => {
      if (!previous.has(id)) return previous;
      const next = new Set(previous);
      next.delete(id);
      return next;
    });
  };
  const setItemDimensionsValidity = (id: string, valid: boolean) => {
    setInvalidItemDimensions((previous) => {
      const hasId = previous.has(id);
      if (valid && !hasId) return previous;
      if (!valid && hasId) return previous;
      const next = new Set(previous);
      if (valid) next.delete(id); else next.add(id);
      return next;
    });
  };

  const save = async () => {
    if (!taskId || !api?.financeCall) return;
    setSaving(true);
    setError('');
    setMessage('');
    try {
      const nextScope = pruneScope(scope);
      const spec = {
        question: question.trim(),
        ...(Object.keys(nextScope).length ? { scope: nextScope } : {}),
        bindings,
        ...(contextId ? { context_id: contextId } : {}),
        ...(current?.id ? { parent_id: current.id } : {}),
        ...(changeReason.trim() ? { change_reason: changeReason.trim() } : {}),
        items: items.map((item) => ({
          id: item.id,
          metric: item.metric.trim(),
          label: item.label.trim() || itemLabel(item.metric),
          dimensions: pruneScope(item.dimensions as RequirementScope & Record<string, unknown>),
          requires_drilldown: item.requires_drilldown,
          ...(itemPeriods(item).length ? { periods: itemPeriods(item) } : {}),
          ...(itemOrganizations(item).length ? { organizations: itemOrganizations(item) } : {}),
          ...(itemScenarios(item).length ? { scenarios: itemScenarios(item) } : {}),
          ...(keptGrainBasis(item).length ? { grain_basis: keptGrainBasis(item) } : {}),
        })),
      };
      const saved = normalizeRecord(unwrap(await api.financeCall(taskId, 'analysis-requirements-save', spec) as Answer<AnalysisRequirementsRecord>));
      if (!saved) throw new Error('保存分析要求后没有返回版本。');
      setCurrent(saved);
      setRecords((previous) => [...previous.filter((record) => record.id !== saved.id), saved]);
      setQuestion(saved.question);
      setScope(saved.scope);
      setBindings(saved.bindings);
      setItems(saved.items);
      setInvalidItemDimensions(new Set());
      setRemoved([]);
      setChangeReason('');
      setMessage(`已保存要求版本 ${shortId(saved.id)}。保存不会自动计算或批准文稿。`);
      onChanged?.(saved);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '保存分析要求失败。');
    } finally {
      setSaving(false);
    }
  };

  const supportByItem = useMemo(() => new Map((current?.support?.items ?? []).map((item) => [item.requirement_item_id, item])), [current]);
  const currentItemById = useMemo(() => new Map((current?.items ?? []).map((item) => [item.id, item])), [current]);
  const supportContextStale = Boolean(current && (canonicalJson(pruneScope(scope)) !== canonicalJson(pruneScope(current.scope)) || canonicalJson(bindings) !== canonicalJson(current.bindings)));
  const isSupportStale = (item: RequirementItem): boolean => {
    const savedItem = currentItemById.get(item.id);
    if (!savedItem) return false;
    return supportContextStale
      || savedItem.metric !== item.metric
      || !equalStringArrays(savedItem.periods, item.periods)
      || !equalStringArrays(savedItem.organizations, item.organizations)
      || !equalStringArrays(savedItem.scenarios, item.scenarios)
      || canonicalJson(savedItem.dimensions) !== canonicalJson(item.dimensions);
  };

  const discuss = () => onDiscuss?.({ question, scope, items, currentRequirementsId: current?.id, draftRequirementsId });
  const periodValue = String(scope.period ?? '');
  const currentSavedPeriod = String(current?.scope.period ?? '');
  const hasSavedCustomPeriod = Boolean(currentSavedPeriod && !validAccountingPeriod(currentSavedPeriod) && periodValue && !validAccountingPeriod(periodValue));

  if (!taskId) {
    return <section className="analysis-definition" aria-label="本次分析要求">
      <div className="analysis-section-heading"><div><h3>本次分析要求</h3><p className="analysis-note">先选择一个任务，再登记问题、范围和必答指标。</p></div></div>
    </section>;
  }

  return <section className="analysis-definition" aria-label="本次分析要求">
    <div className="analysis-section-heading">
      <div><h3>本次分析要求</h3><p className="analysis-note">登记用户问题、财务范围和必答指标；保存只生成新版本。</p></div>
      <span className="analysis-note">{current ? `当前版本 ${shortId(current.id)}` : records.length ? `${records.length} 个历史版本` : '尚未保存'}</span>
    </div>
    {loading ? <p role="status" className="analysis-note">正在读取本次分析要求…</p> : null}
    {scopeChangedForDraft ? <p role="status" className="analysis-message"><AlertCircle size={14} aria-hidden />范围已变：当前要求 {shortId(current?.id)}，这份旧稿绑定的是 {shortId(draftRequirementsId)}。</p> : null}
    {!api?.financeCall ? <p role="alert" className="analysis-message analysis-message--error">当前窗口没有可用的财务分析接口。</p> : null}
    <fieldset className="analysis-fieldset" disabled={loading || saving || !api?.financeCall}>
      <label>用户问题<Textarea aria-label="用户问题" className="analysis-code" rows={3} value={question}
        onChange={(event) => setQuestion(event.target.value)} placeholder="例如：解释本期利润差异并下钻利润来源。" /></label>
      <div className="analysis-edit-grid">
        <TextField label="账套" value={String(scope.ledger ?? '')} onChange={(value) => setScopeField('ledger', value)} placeholder="ledger 或账套名称" />
        <TextField label="组织" value={String(scope.organization ?? '')} onChange={(value) => setScopeField('organization', value)}
          help="只填单个共同组织；多组织请清空这里，并在必答指标中逐一添加。" placeholder="单个组织名称" />
        {hasSavedCustomPeriod
          ? <TextField label="期间" value={periodValue} onChange={(value) => setScopeField('period', value)}
            help="只填各指标共同的单个期间；累计加单月等多期间要求请清空这里，并在指标中逐一添加。" placeholder="YYYY-MM 或范围说明" />
          : <AccountingPeriodInput label="期间" value={periodValue} onChange={(value) => setScopeField('period', value)}
            help="只填各指标共同的单个期间；多期间要求请清空这里，并在指标中逐一添加。" />}
        <SearchableSelect label="币种" value={String(scope.currency ?? '')} onChange={(value) => setScopeField('currency', value)}
          options={optionsWithSavedValue(currencyOptions, scope.currency)} allowEmptyLabel="未指定" clearable />
        <SearchableSelect label="单位" value={String(scope.unit ?? '')} onChange={(value) => setScopeField('unit', value)}
          options={optionsWithSavedValue(unitOptions, scope.unit)} allowEmptyLabel="未指定" clearable />
      </div>
      <div className="analysis-section-heading"><h4>必答指标</h4><Button variant="outline" type="button" onClick={addItem}><Plus size={14} aria-hidden />添加指标</Button></div>
      {items.length ? <div className="analysis-history-list">
        {items.map((item, index) => <RequirementItemEditor key={item.id} item={item} index={index} support={supportByItem.get(item.id)} supportStale={isSupportStale(item)} onChange={(patch) => setItem(item.id, patch)}
          onDimensionsValidity={(valid) => setItemDimensionsValidity(item.id, valid)} onRemove={() => removeItem(item.id)} />)}
      </div> : <p className="analysis-note">尚未登记必答指标。至少添加一项，才能让文稿覆盖检查有明确对象。</p>}
      {removedExisting.length ? <TextField label="删除要求的变更原因" value={changeReason} onChange={setChangeReason}
        error={changeReason.trim() ? undefined : '删要求必须写明变更原因。'} placeholder="例如：经理改为只核对范围，不再要求费用下钻。" /> : null}
      <details className="analysis-details"><summary>高级：绑定与历史版本</summary>
        <p className="analysis-note">绑定随当前口径保存。上下文口径存在时，后端会校验并补齐授权绑定。</p>
        <pre className="analysis-source-text">{JSON.stringify({ context_id: contextId ?? current?.context_id ?? null, bindings, versions: records.map((record) => record.id) }, null, 2)}</pre>
      </details>
    </fieldset>
    {duplicateIds ? <p role="alert" className="analysis-message analysis-message--error">要求项 ID 重复，请保留每项稳定且唯一的 ID。</p> : null}
    {hasInvalidDimensions ? <p role="alert" className="analysis-message analysis-message--error">请先修正维度 JSON，再保存要求新版。</p> : null}
    {organizationConflict ? <p role="alert" className="analysis-message analysis-message--error">上方组织与指标覆盖组织冲突。请清空上方组织，或只保留同一个组织。</p> : null}
    {periodConflict ? <p role="alert" className="analysis-message analysis-message--error">上方期间与指标适用期间冲突。请清空上方期间，或只保留同一个期间。</p> : null}
    {error ? <p role="alert" className="analysis-message analysis-message--error">{error}</p> : null}
    {message ? <p role="status" className="analysis-message">{message}</p> : null}
    <div className="analysis-actions">
      <Button type="button" disabled={!canSave || saving} onClick={() => void save()}><Save size={14} aria-hidden />保存要求新版</Button>
      <Button variant="outline" type="button" disabled={saving} onClick={discuss}><MessageSquare size={14} aria-hidden />与助手讨论范围</Button>
    </div>
  </section>;
}

function RequirementItemEditor({ item, index, support, supportStale, onChange, onDimensionsValidity, onRemove }: {
  item: RequirementItem; index: number; support?: RequirementSupportItem; supportStale: boolean; onChange(patch: Partial<RequirementItem>): void; onDimensionsValidity(valid: boolean): void; onRemove(): void;
}) {
  const [dimensionsText, setDimensionsText] = useState(() => JSON.stringify(item.dimensions, null, 2));
  const dimensions = safeJsonObject(dimensionsText);
  useEffect(() => setDimensionsText(JSON.stringify(item.dimensions, null, 2)), [item.id, item.dimensions]);
  useEffect(() => onDimensionsValidity(Boolean(dimensions)), [dimensions, onDimensionsValidity]);
  const [nextPeriod, setNextPeriod] = useState('');
  const [nextPeriodRange, setNextPeriodRange] = useState('');
  const [nextOrganization, setNextOrganization] = useState('');
  const [nextScenario, setNextScenario] = useState('');
  const addPeriod = () => {
    const value = nextPeriod.trim();
    const periods = itemPeriods(item);
    if (!value || periods.includes(value)) return;
    onChange({ periods: [...periods, value] });
    setNextPeriod('');
  };
  const periods = itemPeriods(item);
  const addPeriodRange = () => {
    const value = nextPeriodRange.trim();
    if (!validPeriodRange(value) || periods.includes(value)) return;
    onChange({ periods: [...periods, value] });
    setNextPeriodRange('');
  };
  const removePeriod = (period: string) => onChange({ periods: periods.filter((value) => value !== period) });
  const organizations = itemOrganizations(item);
  const addOrganization = () => {
    const value = nextOrganization.trim();
    if (!value || organizations.includes(value)) return;
    onChange({ organizations: [...organizations, value] });
    setNextOrganization('');
  };
  const removeOrganization = (organization: string) => onChange({ organizations: organizations.filter((value) => value !== organization) });
  const scenarios = itemScenarios(item);
  const addScenario = () => {
    const value = nextScenario.trim();
    if (!value || scenarios.includes(value)) return;
    onChange({ scenarios: [...scenarios, value] });
    setNextScenario('');
  };
  const removeScenario = (scenario: string) => onChange({ scenarios: scenarios.filter((value) => value !== scenario) });
  const exactMetricKey = typeof item.dimensions.metric_key === 'string' ? item.dimensions.metric_key : '';
  const setExactMetricKey = (value: string) => {
    const dimensions = { ...item.dimensions };
    if (value.trim()) dimensions.metric_key = value.trim(); else delete dimensions.metric_key;
    onChange({ dimensions });
  };
  return <article className="analysis-history-row analysis-history-row--static" aria-label={`必答指标 ${index + 1}`}>
    <div className="analysis-edit-grid">
      <SearchableSelect label={`指标 ${index + 1}`} value={item.metric} onChange={(value) => onChange({ metric: value, label: item.label || itemLabel(value) })}
        options={metricOptionsForItem(item)} placeholder="选择指标" />
      <TextField label="显示名称" value={item.label} onChange={(value) => onChange({ label: value })} placeholder={itemLabel(item.metric)} />
      <FieldShell label="指定下钻"><label className="analysis-select-label"><input type="checkbox" checked={item.requires_drilldown}
        onChange={(event) => onChange({ requires_drilldown: event.target.checked })} />需要读取来源行</label></FieldShell>
    </div>
    <FieldShell label="适用期间">
      <div className="analysis-actions">
        <AccountingPeriodInput label={`添加期间 ${index + 1}`} value={nextPeriod} onChange={setNextPeriod} />
        <Button variant="outline" type="button" onClick={addPeriod} disabled={!nextPeriod.trim() || periods.includes(nextPeriod.trim())}>添加期间</Button>
      </div>
      <div className="analysis-actions">
        <TextField label={`添加累计范围 ${index + 1}`} value={nextPeriodRange} onChange={setNextPeriodRange} placeholder="2026-01:2026-08" />
        <Button variant="outline" type="button" onClick={addPeriodRange} disabled={!validPeriodRange(nextPeriodRange.trim()) || periods.includes(nextPeriodRange.trim())}>添加累计范围</Button>
      </div>
      {periods.length ? <div className="analysis-actions" aria-label={`已选期间 ${index + 1}`}>
        {periods.map((period) => <Button variant="outline" key={period} type="button" onClick={() => removePeriod(period)}>{period} ×</Button>)}
      </div> : <p className="analysis-note">未指定时沿用上方本期范围；可添加单月或累计范围，列出的每个期间都须有结果。</p>}
    </FieldShell>
    <FieldShell label="须逐一覆盖的组织">
      <div className="analysis-actions">
        <TextField label={`添加组织 ${index + 1}`} value={nextOrganization} onChange={setNextOrganization} placeholder="例如：集团合并、华东区域" />
        <Button variant="outline" type="button" onClick={addOrganization} disabled={!nextOrganization.trim() || organizations.includes(nextOrganization.trim())}>添加组织</Button>
      </div>
      {organizations.length ? <div className="analysis-actions" aria-label={`已选组织 ${index + 1}`}>
        {organizations.map((organization) => <Button variant="outline" key={organization} type="button" onClick={() => removeOrganization(organization)}>{organization} ×</Button>)}
      </div> : <p className="analysis-note">未指定时沿用上方单个组织；指定多个后，每个组织与每个适用期间都须有结果。</p>}
    </FieldShell>
    <FieldShell label="须逐一覆盖的结果情景">
      <div className="analysis-actions">
        <TextField label={`添加结果情景 ${index + 1}`} value={nextScenario} onChange={setNextScenario} placeholder="例如：actual_ytd、budget_ytd、achievement_ratio" />
        <Button variant="outline" type="button" onClick={addScenario} disabled={!nextScenario.trim() || scenarios.includes(nextScenario.trim())}>添加情景</Button>
      </div>
      {scenarios.length ? <div className="analysis-actions" aria-label={`已选结果情景 ${index + 1}`}>
        {scenarios.map((scenario) => <Button variant="outline" key={scenario} type="button" onClick={() => removeScenario(scenario)}>{scenario} ×</Button>)}
      </div> : <p className="analysis-note">只在承诺多个结果情景时填写；每个组织、期间和情景都须有对应结果。情景键须与运行结果中的 scenario 一致。</p>}
    </FieldShell>
    <div>
      <TextField label={`精确结果键 ${index + 1}`} value={exactMetricKey} onChange={setExactMetricKey} placeholder="例如：operating_profit、revenue" />
      <p className="analysis-note">与运行结果中的 metric_key 完全一致；指定后，毛利不会代替营业利润，收入达成率不会代替利润达成率。</p>
    </div>
    <label>维度 JSON<Textarea aria-label={`维度 JSON ${index + 1}`} className="analysis-code" rows={3} value={dimensionsText}
      onChange={(event) => {
        const next = event.target.value;
        setDimensionsText(next);
        const parsed = safeJsonObject(next);
        if (parsed) onChange({ dimensions: parsed });
      }} /></label>
    {!dimensions ? <p role="alert" className="analysis-message analysis-message--error">维度必须是 JSON object。</p> : null}
    {support ? <RequirementSupportHint support={support} stale={supportStale} /> : null}
    <div className="analysis-actions"><span className="analysis-note">稳定 ID：{item.id}</span>
      <Button variant="destructive" type="button" onClick={onRemove}><Trash2 size={14} aria-hidden />删除要求</Button></div>
  </article>;
}

function RequirementSupportHint({ support, stale }: { support: RequirementSupportItem; stale: boolean }) {
  if (stale) {
    return <p role="status" className="analysis-message"><AlertCircle size={14} aria-hidden />条件已修改，保存后重新检查资料匹配。</p>;
  }
  if (support.status === 'requires_execution') {
    return <p className="analysis-note">{support.next_action || `已识别为 ${support.canonical_metric || '可分析指标'}，保存后可运行分析。`}</p>;
  }
  const missing = support.missing_inputs?.length ? `缺少资料：${support.missing_inputs.map(formatMissingInput).join('、')}。` : '';
  const action = support.next_action || ({
    requires_input: '请补充这些资料或字段。',
    unrecognized: '暂未识别这项分析能力，可继续自由编辑。',
    unverified: '这项要求还没有检查依据，保存后可重新检查。',
  }[support.status] ?? '保存后重新检查这项要求。');
  return <p role="status" className="analysis-message"><AlertCircle size={14} aria-hidden />{missing}{action}</p>;
}
