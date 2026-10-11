import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { CircleCheck, CircleHelp, CircleSlash, ClipboardList, RefreshCw, TriangleAlert } from 'lucide-react';
import { bridge, type Answer, type ReadinessDataset, type ReadinessReport } from '../../bridge.js';
import { Button } from '../../components/ui/button.js';
import { HelpLink } from '../guide/GuideHub.js';
import { FRESHNESS_TEXT, reasonText } from './evidenceLabels.js';
import { scenarioLabel } from './glossary.js';
import { errorText } from './shared.js';
import { PeriodWords, joinParts } from '../../components/PeriodWords.js';
import { TechnicalInfo } from './TechnicalInfo.js';

const CAPABILITY_LABELS: Record<string, string> = {
  management_pnl: '管理损益',
  control_totals: '合计校验',
  reconciliation: '勾稽核对',
  receivables_aging: '应收账龄',
  cash_13_weeks: '十三周现金',
};
const REASON_LABELS: Record<string, string> = {
  missing_scope: '范围没声明齐',
  identity_failed: '表头没声明期间和币种',
  mapping_incomplete: '管理科目没映射全',
  pending_structure: '表结构等经理确认',
  no_dataset: '还没有可用资料',
};
const FIELD_LABELS: Record<string, string> = {
  period: '期间',
  currency: '币种',
  unit: '单位',
  scenario: '情景',
  ledger: '账簿',
  organization: '组织',
  management_account: '管理科目',
  table_structure: '表结构',
  dataset: '资料',
};

const label = (map: Record<string, string>, key: string) => map[key] ?? key;
const fields = (names: string[]) => names.map((name) => label(FIELD_LABELS, name)).join('、');

/** What the file declares, written the way she would say it. */
function scopeLine(row: ReadinessDataset): ReactNode {
  const scope = row.scope ?? ({} as ReadinessDataset['scope']);
  const scenario = (scope as ReadinessDataset['scope'] & { scenario?: string }).scenario;
  const parts = [
    scope.period && <>期间 <PeriodWords value={scope.period} /></>,
    scope.unit && `单位 ${scope.unit}`,
    scope.currency && `币种 ${scope.currency}`,
    scope.organization && `组织 ${scope.organization}`,
    scenario && `情景 ${scenarioLabel(scenario)}`,
  ].filter(Boolean);
  return parts.length ? joinParts(parts) : '标题里没读到范围';
}

const PERIOD_KIND: Record<string, string> = { month: '月度', annual: '年度', as_of: '时点' };
const AS_OF_SOURCE: Record<string, string> = { title: '来自标题', source_refresh: '刷新截止' };

/** 截至日 and 期间 as the file declares them; 未声明 rather than a guess. */
function asOfLine(row: ReadinessDataset): ReactNode {
  const parts = [
    row.as_of && `截至 ${row.as_of}${row.as_of_source && AS_OF_SOURCE[row.as_of_source] ? `（${AS_OF_SOURCE[row.as_of_source]}）` : ''}`,
    (row.period || row.scope?.period) && <>期间 <PeriodWords value={row.period || row.scope?.period} /></>,
    row.period_kind && PERIOD_KIND[row.period_kind],
  ].filter(Boolean);
  return parts.length ? joinParts(parts) : '未声明';
}

/** Unknown because the analysis period is missing or unreadable, not because the file left something out. */
const NO_TASK_PERIOD = new Set(['no_task_period', 'task_period_unreadable']);

/** 当前 / 资料过期 / 期间不符 / 未声明 / 无法判断, in words and with an icon, never colour alone. */
function FreshnessCell({ row }: { row: ReadinessDataset }) {
  const state = row.freshness?.state;
  if (!state) return <>—</>;
  const undecided = state === 'unknown' && (row.freshness?.reasons ?? []).some((reason) => NO_TASK_PERIOD.has(reason.code));
  const words = undecided ? '无法判断' : (FRESHNESS_TEXT as Record<string, string>)[state] ?? state;
  const why = reasonText(row.freshness?.reasons);
  const warning = state === 'source_stale' || state === 'period_mismatch';
  const Icon = warning ? TriangleAlert : state === 'current' ? CircleCheck : CircleHelp;
  return <span className={`analysis-readiness-freshness analysis-readiness-freshness--${warning ? 'warning' : state === 'current' ? 'current' : 'unknown'}`}>
    <Icon size={14} strokeWidth={1.5} aria-hidden />
    <span>{state !== 'current' && why ? `${words}（${why}）` : words}</span>
  </span>;
}

function datasetLabel(row: ReadinessDataset, index: number): string {
  return row.name || `资料 ${index + 1}`;
}

/** Freshness the manager should act on: a file older than the period, or for another period. */
const isStale = (row: ReadinessDataset) => row.freshness?.state === 'source_stale' || row.freshness?.state === 'period_mismatch';

/**
 * A file's own line in the file list, where it says something is wrong: 时效 when the file is older than the
 * period or for another one, 还缺 when it leaves a field out. A file that is fine adds nothing to its row.
 */
export function FileReadinessStates({ row }: { row?: ReadinessDataset }) {
  if (!row) return null;
  return <>
    {isStale(row) ? <span className="analysis-file-status">
      <span className="analysis-file-status-label">时效</span><span className="analysis-file-state"><FreshnessCell row={row} /></span>
    </span> : null}
    {row.missing_fields?.length ? <span className="analysis-file-status">
      <span className="analysis-file-status-label">还缺</span><span className="analysis-file-state">{fields(row.missing_fields)}</span>
    </span> : null}
  </>;
}

/** Everything the check read from one file, shown where the file's content opens: scope, as-of, freshness, what it can run. */
export function FileReadinessFacts({ row }: { row?: ReadinessDataset }) {
  if (!row) return null;
  return <><dl className="analysis-file-facts" aria-label="这份资料读到的范围">
    <div><dt>读到的范围</dt><dd>{scopeLine(row)}</dd></div>
    <div><dt>截至日 / 期间</dt><dd>{asOfLine(row)}</dd></div>
    <div><dt>时效</dt><dd><FreshnessCell row={row} /></dd></div>
    <div><dt>还缺</dt><dd>{row.missing_fields?.length ? fields(row.missing_fields) : '—'}</dd></div>
    <div><dt>能算</dt><dd>{row.can_run?.length ? row.can_run.map((name) => label(CAPABILITY_LABELS, name)).join('、') : '—'}</dd></div>
  </dl><TechnicalInfo rows={[['资料编号', row.dataset_id]]} /></>;
}

export type Readiness = { report: ReadinessReport | null; error: string; working: boolean; load(manual?: boolean): Promise<void> };

/**
 * The readiness report, read once for the page: the summary at the top of 资料 and each file's row read the same one.
 * No task, no read.
 */
export function useReadiness(taskId: string | null, refreshKey?: unknown): Readiness {
  const [report, setReport] = useState<ReadinessReport | null>(null);
  const [error, setError] = useState('');
  const [working, setWorking] = useState(false);

  // Only 重新检查 shows the read: the page hands over a new refreshKey on its 5-second re-read, and a button
  // that greys out and back every few seconds reads as the page shaking.
  const load = useCallback(async (manual = false) => {
    const api = bridge(); if (!taskId || !api?.financeCall) return;
    if (manual) { setWorking(true); setError(''); }
    try {
      const answer = await api.financeCall(taskId, 'finance-readiness') as Answer<ReadinessReport> | undefined;
      // A build whose bridge does not know this command answers with nothing;
      // that is not an error the manager needs to see.
      if (!answer) return;
      if (!answer.ok) throw new Error(answer.message);
      setReport(answer.value ?? null);
      setError('');
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      if (manual) setWorking(false);
    }
  }, [taskId]);

  useEffect(() => { setReport(null); setError(''); }, [taskId]);
  useEffect(() => { void load(); }, [load, refreshKey]);
  return { report, error, working, load };
}

/**
 * The report that says what is missing, where the manager can read it: what this batch can calculate and which
 * file holds up the rest. Each file's own scope, as-of and freshness sit on its row in the file list.
 *
 * It existed only as a tool the assistant could call, so a file that could not
 * be calculated on said nothing in the workspace and she had no way to find out
 * which file was holding the month up.
 */
export function ReadinessPanel({ taskId, refreshKey, readiness }: { taskId: string; refreshKey?: unknown; readiness?: Readiness }) {
  const own = useReadiness(readiness ? null : taskId, refreshKey);
  const { report, error, working, load } = readiness ?? own;

  if (!report && !error) return null;
  // An older CLI answers with fewer fields than this build knows about, and a
  // report is a read: it must never be the thing that takes the workspace down.
  const ready = report?.can_run ?? [];
  const blocked = report?.blocked ?? [];
  const perFile = report?.datasets ?? [];
  const named = (id?: string) => {
    const index = perFile.findIndex((row) => row.dataset_id === id);
    return index >= 0 ? datasetLabel(perFile[index], index) : '这份资料';
  };

  return (
    <section className="analysis-readiness">
      <div className="analysis-section-heading">
        <span className="fnd-with-help"><h4><ClipboardList size={15} strokeWidth={1.5} aria-hidden /> 这批资料能算什么</h4>
          <HelpLink article="data-checklist" label="导入前的资料准备清单" /></span>
        <Button variant="outline" type="button" disabled={working} onClick={() => void load(true)}>
          <RefreshCw size={15} strokeWidth={1.5} aria-hidden />重新检查
        </Button>
      </div>

      {error && <p role="alert" className="analysis-message analysis-message--error">{error}</p>}

      {report && (
        <>
          <ul className="analysis-readiness-capabilities">
            {ready.map((name) => (
              <li key={name} className="analysis-readiness-ready">
                <CircleCheck size={15} strokeWidth={1.5} aria-hidden />
                {label(CAPABILITY_LABELS, name)}
              </li>
            ))}
            {blocked.map((row, index) => (
              <li key={`${row.capability}-${row.dataset_id ?? index}`} className="analysis-readiness-blocked">
                <CircleSlash size={15} strokeWidth={1.5} aria-hidden />
                {label(CAPABILITY_LABELS, row.capability)}
                <span className="analysis-note">
                  {named(row.dataset_id)}{label(REASON_LABELS, row.reason)}
                  {row.missing_fields?.length ? `：缺${fields(row.missing_fields)}` : ''}
                </span>
              </li>
            ))}
            {!ready.length && !blocked.length && (
              <li className="analysis-note">还没有已授权的资料。</li>
            )}
          </ul>

          {/* One sentence; where each file's scope and freshness went is the guide's to say. */}
          <p className="analysis-note">
            {report.erp_connected ? '' : '未接外部账套，数字全部来自这些文件，'}
            {report.erp_connected ? '文件' : ''}更新时{report.file_identity_policy === 'business_key' ? '按业务键逐行比对' : '整份替换'}。
            {perFile.length ? <HelpLink article="evidence" label="资料时效与证据标签" /> : null}
          </p>
        </>
      )}
    </section>
  );
}
