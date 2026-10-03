// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { ReadinessReport } from '../src/bridge.js';
import { emptyScope, inferCandidateSources, inferScopeCandidates, type AnalysisScope } from '../src/views/analysis/scope.js';
import { PeriodPending, ScopePanel, pendingPeriods } from '../src/views/analysis/ScopePanel.js';

afterEach(cleanup);

const blank = { ledger: '', organization: '', period: '', currency: '', unit: '' };
const report = (datasets: ReadinessReport['datasets']): ReadinessReport => ({
  proposed_scope: blank, datasets, can_run: [], blocked: [], file_identity_policy: 'snapshot_only', diagnostics: [], erp_connected: false,
});
const pack = report([
  {
    dataset_id: 'close', name: '华宸物业_2026年08月_月结', scope: { ...blank, period: '2026-08' }, missing_fields: ['currency'], can_run: [], blocked: [],
    scope_sources: { period: { origin: 'title', sheet: '00·封面与编制说明', text: '2026年08月', sheet_count: 13 } },
    name_scope: { period: '2026-08', text: '2026年08月' },
  },
  {
    dataset_id: 'budget', name: '华宸物业_2026年度_预算', scope: { ...blank, period: '2026-08' }, missing_fields: ['currency'], can_run: [], blocked: [],
    scope_sources: { period: { origin: 'title', sheet: '09·预算执行分析', text: '2026年1-8月', sheet_count: 1 } },
  },
]);
const scopeOf = (period: string, candidates: string[]): AnalysisScope => ({
  current: null, scope: { ...emptyScope(), period }, candidates: { period: candidates },
  candidateSources: inferCandidateSources(pack), conflicts: [],
  loading: false, saving: false, message: '', error: '', setField: vi.fn(), setFields: vi.fn(), applyRecord: vi.fn(), save: vi.fn(),
});

it('says which sheet and which words each period candidate was read from', () => {
  expect(inferScopeCandidates([], pack).period).toEqual(['2026-08']);
  expect(inferCandidateSources(pack).period?.['2026-08']).toBe(
    '00·封面与编制说明 等 13 张表的标题「2026年08月」；文件名「2026年08月」；09·预算执行分析的标题「2026年1-8月」',
  );
});

it('offers a period only the file name carries, and says so', () => {
  const named = report([{ dataset_id: 'x', name: '华宸_2026年07月', scope: blank, missing_fields: ['period'], can_run: [], blocked: [],
    name_scope: { period: '2026-07', text: '2026年07月' } }]);
  expect(inferScopeCandidates([], named).period).toEqual(['2026-07']);
  expect(inferCandidateSources(named).period?.['2026-07']).toBe('文件名「2026年07月」');
});

it('names no source for a candidate nothing vouches for', () => {
  expect(inferCandidateSources(report([{ dataset_id: 'x', name: 'x', scope: { ...blank, period: '2026-08' }, missing_fields: [], can_run: [], blocked: [] }]))).toEqual({});
  expect(inferCandidateSources(null)).toEqual({});
});

it('holds the period-bound actions while the files name a month the task has not confirmed', () => {
  expect(pendingPeriods(scopeOf('', ['2026-08']))).toEqual(['2026-08']);
  render(<PeriodPending scope={scopeOf('', ['2026-08'])} />);
  expect(screen.getByRole('status').textContent).toContain('资料写的期间是 2026-08，但任务期间还没确认');
});

it('does not hold anything once a period is chosen, or when no file names one', () => {
  expect(pendingPeriods(scopeOf('2026-08', ['2026-08']))).toEqual([]);
  expect(pendingPeriods(scopeOf('2026-07', ['2026-08']))).toEqual([]);
  expect(pendingPeriods(scopeOf('', []))).toEqual([]);
  const { container } = render(<PeriodPending scope={scopeOf('', [])} />);
  expect(container.textContent).toBe('');
});

it('shows the source beside the candidate button in the scope card', () => {
  render(<ScopePanel scope={scopeOf('', ['2026-08'])} datasetCount={2} />);
  expect(screen.getByRole('button', { name: '采用资料里的期间 2026-08' })).toBeTruthy();
  expect(screen.getByText(/来自 00·封面与编制说明 等 13 张表的标题「2026年08月」/)).toBeTruthy();
});

it('names the file title when a derived table has no sheet name', () => {
  const derived = report([{ dataset_id: 'd', name: 'd', scope: { ...blank, period: '2026-08' }, missing_fields: [], can_run: [], blocked: [],
    scope_sources: { period: { origin: 'title', sheet: '', text: '2026年08月', sheet_count: 1 } } }]);
  expect(inferCandidateSources(derived).period?.['2026-08']).toBe('资料的标题「2026年08月」');
});

it('announces the pending period from one place only', () => {
  render(<><PeriodPending scope={scopeOf('', ['2026-08'])} /><PeriodPending scope={scopeOf('', ['2026-08'])} announce={false} /></>);
  expect(screen.getAllByRole('status')).toHaveLength(1);
});
