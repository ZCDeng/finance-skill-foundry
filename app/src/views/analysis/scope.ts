import { useCallback, useEffect, useRef, useState } from 'react';
import { bridge, type Answer, type DatasetSnapshot, type ReadinessReport } from '../../bridge.js';
import { textValue } from './presentation.js';
import { errorText, unwrap } from './shared.js';

/**
 * The one scope a task is analysed under: the fields every form used to ask
 * for separately (the 资料 page card, the finance settings, the requirements
 * panel, the background panel). It is held once per task and edited from the
 * places that need it; saving writes the task's requirements record.
 */

export const SCOPE_KEYS = ['period', 'organization', 'unit', 'currency', 'scenario', 'ledger', 'granularity'] as const;
export type ScopeKey = (typeof SCOPE_KEYS)[number];
export type ScopeValues = Record<ScopeKey, string>;
export const SCOPE_LABELS: Record<ScopeKey, string> = {
  period: '期间', organization: '组织', unit: '单位', currency: '币种', scenario: '情景', ledger: '账簿', granularity: '粒度',
};

export type ScopeRecord = {
  id: string;
  question: string;
  scope?: Record<string, unknown>;
  bindings?: Record<string, string>;
  items?: unknown[];
};

type RequirementsList = { current?: ScopeRecord | null; requirements?: ScopeRecord[] };

export const emptyScope = (): ScopeValues => Object.fromEntries(SCOPE_KEYS.map((key) => [key, ''])) as ScopeValues;

const isScopeKey = (key: string): key is ScopeKey => (SCOPE_KEYS as readonly string[]).includes(key);

/** The stored scope's editable fields, blank where the record has none. */
export function editableScope(scope: Record<string, unknown> | undefined): ScopeValues {
  const next = emptyScope();
  for (const key of SCOPE_KEYS) {
    const value = scope?.[key];
    next[key] = value == null ? '' : String(value);
  }
  return next;
}

// The carried keys always mirror the stored record: a save may drop a legacy key, and
// resending the copy loaded earlier would be refused on the next save.
export function carriedScope(scope: Record<string, unknown> | undefined): Record<string, unknown> {
  return Object.fromEntries(Object.entries(scope ?? {}).filter(([key]) => !isScopeKey(key)));
}

/** The fields that carry a value, as the record stores them. */
export function filledScope(scope: ScopeValues): Partial<ScopeValues> {
  return Object.fromEntries(Object.entries(scope).filter(([, value]) => value.trim())) as Partial<ScopeValues>;
}

const ITEM_SCOPE_KEYS: { field: ScopeKey; itemField: string }[] = [
  { field: 'period', itemField: 'periods' },
  { field: 'organization', itemField: 'organizations' },
  { field: 'scenario', itemField: 'scenarios' },
];

export type ScopeConflict = { field: ScopeKey; label: string };

/** A shared value that disagrees with what a requirement item lists for itself. */
export function scopeConflicts(items: unknown[] | undefined, scope: ScopeValues): ScopeConflict[] {
  return ITEM_SCOPE_KEYS.filter(({ field, itemField }) => {
    const value = scope[field];
    return Boolean(value && items?.some((item) => {
      if (!item || typeof item !== 'object') return false;
      const values = (item as Record<string, unknown>)[itemField];
      return Array.isArray(values) && values.length > 0 && (values.length !== 1 || values[0] !== value);
    }));
  }).map(({ field }) => ({ field, label: SCOPE_LABELS[field] }));
}

/** What the files themselves say each field is, so the manager confirms rather than types. */
export type ScopeCandidates = Partial<Record<ScopeKey, string[]>>;

function addCandidate(into: ScopeCandidates, key: ScopeKey, value: unknown) {
  if (value == null || typeof value === 'object') return;
  const text = textValue(value).trim();
  if (!text || text === '—') return;
  const list = into[key] ?? (into[key] = []);
  if (!list.includes(text)) list.push(text);
}

/** Candidates read from the files' own declarations (title rows, sheet hints), then from the readiness report. */
export function inferScopeCandidates(datasets: DatasetSnapshot[], report?: ReadinessReport | null): ScopeCandidates {
  const found: ScopeCandidates = {};
  for (const source of datasets) {
    const metadata = source.metadata ?? {};
    for (const key of SCOPE_KEYS) addCandidate(found, key, metadata[key]);
    const hints = metadata.scope_hints;
    if (hints && typeof hints === 'object') for (const key of SCOPE_KEYS) addCandidate(found, key, (hints as Record<string, unknown>)[key]);
  }
  if (report) {
    const proposed = (report.proposed_scope ?? {}) as Record<string, unknown>;
    for (const key of SCOPE_KEYS) addCandidate(found, key, proposed[key]);
    for (const row of report.datasets ?? []) for (const key of SCOPE_KEYS) addCandidate(found, key, (row.scope as Record<string, unknown> | undefined)?.[key]);
  }
  return found;
}

export type AnalysisScope = {
  /** The saved requirements record the fields were loaded from, if any. */
  current: ScopeRecord | null;
  scope: ScopeValues;
  candidates: ScopeCandidates;
  conflicts: ScopeConflict[];
  loading: boolean;
  saving: boolean;
  message: string;
  error: string;
  setField(key: ScopeKey, value: string): void;
  /** Several fields at once, e.g. from a saved finance scope; blank values are kept blank. */
  setFields(patch: Partial<Record<string, string>>): void;
  /** Writes the fields as a new version of the requirements record, keeping question, items and bindings. */
  save(): Promise<ScopeRecord | null>;
};

export function useAnalysisScope(taskId: string | undefined, question: string, datasets: DatasetSnapshot[]): AnalysisScope {
  const [current, setCurrent] = useState<ScopeRecord | null>(null);
  const [scope, setScope] = useState<ScopeValues>(emptyScope);
  const [extra, setExtra] = useState<Record<string, unknown>>({});
  const [report, setReport] = useState<ReadinessReport | null>(null);
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
    setCurrent(null); setScope(emptyScope()); setExtra({}); setReport(null); setMessage(''); setError('');
    if (!api?.financeCall || !taskId) return;
    setLoading(true);
    void api.financeCall(taskId, 'analysis-requirements-list', {}).then((answer) => {
      if (request.current !== seq) return;
      // A build that does not know the record answers with an empty object.
      const payload = (unwrap(answer as Answer<RequirementsList>) ?? {}) as RequirementsList;
      const next = payload.current ?? null;
      setCurrent(next);
      setScope(editableScope(next?.scope));
      setExtra(carriedScope(next?.scope));
    }).catch((reason: unknown) => {
      if (request.current === seq) setError(errorText(reason));
    }).finally(() => {
      if (request.current === seq) setLoading(false);
    });
    // The readiness report is only a source of suggestions; failing to read it says nothing.
    void Promise.resolve(api.financeCall(taskId, 'finance-readiness') as Promise<Answer<ReadinessReport> | undefined>).then((answer) => {
      if (request.current !== seq || !answer?.ok || !answer.value || typeof answer.value !== 'object') return;
      setReport(answer.value);
    }).catch(() => undefined);
  }, [taskId]);

  const setField = useCallback((key: ScopeKey, value: string) => {
    setScope((previous) => ({ ...previous, [key]: value }));
    setMessage('');
  }, []);
  const setFields = useCallback((patch: Partial<Record<string, string>>) => {
    setScope((previous) => {
      const next = { ...previous };
      for (const [key, value] of Object.entries(patch)) if (isScopeKey(key)) next[key] = value ?? '';
      return next;
    });
    setMessage('');
  }, []);

  const save = useCallback(async (): Promise<ScopeRecord | null> => {
    const api = bridge();
    if (!api?.financeCall || !taskId) return null;
    const seq = saveRequest.current + 1;
    saveRequest.current = seq;
    setSaving(true); setMessage(''); setError('');
    try {
      const record = unwrap(await api.financeCall(taskId, 'analysis-requirements-save', {
        question: current?.question ?? question,
        scope: { ...extra, ...filledScope(scope) },
        bindings: current?.bindings ?? {},
        ...(current?.id ? { parent_id: current.id } : {}),
        change_reason: current?.id ? '更新分析范围。' : undefined,
        items: current?.items ?? [],
      }) as Answer<ScopeRecord>);
      if (saveRequest.current !== seq) return null;
      setCurrent(record);
      setScope(editableScope(record.scope));
      setExtra(carriedScope(record.scope));
      setMessage('已保存分析范围，旧版本仍保留。');
      return record;
    } catch (reason) {
      if (saveRequest.current === seq) setError(errorText(reason));
      return null;
    } finally {
      if (saveRequest.current === seq) setSaving(false);
    }
  }, [taskId, question, current, extra, scope]);

  return {
    current, scope, conflicts: scopeConflicts(current?.items, scope), loading, saving, message, error,
    candidates: inferScopeCandidates(datasets, report),
    setField, setFields, save,
  };
}
