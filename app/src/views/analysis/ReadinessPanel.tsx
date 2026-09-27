import { useCallback, useEffect, useState } from 'react';
import { CircleCheck, CircleSlash, ClipboardList, RefreshCw } from 'lucide-react';
import { bridge, type Answer, type ReadinessDataset, type ReadinessReport } from '../../bridge.js';
import { Button } from '../../components/ui/button.js';
import { errorText } from './shared.js';

const CAPABILITY_LABELS: Record<string, string> = {
  management_pnl: '管理损益',
  control_totals: '合计校验',
  reconciliation: '勾稽核对',
  receivables_aging: '应收账龄',
  cash_13_weeks: '十三周现金',
};
const REASON_LABELS: Record<string, string> = {
  missing_scope: '口径没声明齐',
  identity_failed: '表头没声明期间和币种',
  mapping_incomplete: '管理科目没映射全',
  pending_structure: '表结构等经理确认',
  no_dataset: '还没有可用资料',
};
const FIELD_LABELS: Record<string, string> = {
  period: '期间',
  currency: '币种',
  unit: '单位',
  ledger: '账簿',
  organization: '组织',
  management_account: '管理科目',
  table_structure: '表结构',
  dataset: '资料',
};

const label = (map: Record<string, string>, key: string) => map[key] ?? key;
const fields = (names: string[]) => names.map((name) => label(FIELD_LABELS, name)).join('、');

/** What the file declares, written the way she would say it. */
function scopeLine(row: ReadinessDataset): string {
  const scope = row.scope ?? ({} as ReadinessDataset['scope']);
  const parts = [
    scope.period && `期间 ${scope.period}`,
    scope.unit && `单位 ${scope.unit}`,
    scope.currency && `币种 ${scope.currency}`,
    scope.organization && `组织 ${scope.organization}`,
  ].filter(Boolean);
  return parts.length ? parts.join(' · ') : '标题里没读到口径';
}

/**
 * The report that says what is missing, where the manager can read it.
 *
 * It existed only as a tool the assistant could call, so a file that could not
 * be calculated on said nothing in the workspace and she had no way to find out
 * which file was holding the month up.
 */
export function ReadinessPanel({ taskId, refreshKey }: { taskId: string; refreshKey?: unknown }) {
  const [report, setReport] = useState<ReadinessReport | null>(null);
  const [error, setError] = useState('');
  const [working, setWorking] = useState(false);

  const load = useCallback(async () => {
    const api = bridge(); if (!api?.financeCall) return;
    setWorking(true); setError('');
    try {
      const answer = await api.financeCall(taskId, 'finance-readiness') as Answer<ReadinessReport> | undefined;
      // A build whose bridge does not know this command answers with nothing;
      // that is not an error the manager needs to see.
      if (!answer) return;
      if (!answer.ok) throw new Error(answer.message);
      setReport(answer.value ?? null);
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      setWorking(false);
    }
  }, [taskId]);

  useEffect(() => { void load(); }, [load, refreshKey]);

  if (!report && !error) return null;
  // An older CLI answers with fewer fields than this build knows about, and a
  // report is a read: it must never be the thing that takes the workspace down.
  const ready = report?.can_run ?? [];
  const blocked = report?.blocked ?? [];
  const perFile = report?.datasets ?? [];
  const named = (id?: string) =>
    perFile.find((row) => row.dataset_id === id)?.name || '这份资料';

  return (
    <section className="fnd-card analysis-readiness-card">
      <div className="analysis-section-heading">
        <h4><ClipboardList size={15} strokeWidth={1.5} aria-hidden /> 这批资料能算什么</h4>
        <Button variant="outline" type="button" disabled={working} onClick={() => void load()}>
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

          {perFile.length > 0 && (
            <table className="analysis-readiness-table">
              <caption className="analysis-note">
                每份文件各自声明的口径。空着的格子表示标题和数据里都没有这一项。
              </caption>
              <thead>
                <tr><th scope="col">资料</th><th scope="col">读到的口径</th><th scope="col">还缺</th><th scope="col">能算</th></tr>
              </thead>
              <tbody>
                {perFile.map((row) => (
                  <tr key={row.dataset_id}>
                    <th scope="row">{row.name || String(row.dataset_id ?? '').slice(0, 8)}</th>
                    <td>{scopeLine(row)}</td>
                    <td>{row.missing_fields?.length ? fields(row.missing_fields) : '—'}</td>
                    <td>
                      {row.can_run?.length
                        ? row.can_run.map((name) => label(CAPABILITY_LABELS, name)).join('、')
                        : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <p className="analysis-note">
            文件身份策略：{report.file_identity_policy === 'business_key' ? '按业务键比对' : '按快照整份替换'}
            {report.erp_connected ? '' : ' · 未接外部账套，数字全部来自这些文件'}
          </p>
        </>
      )}
    </section>
  );
}
