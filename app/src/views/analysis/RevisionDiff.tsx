import type { AnalysisRun } from '../../bridge.js';
import { businessColumnLabel, columnSemantics, compareBusinessRuns, formatBusinessValue } from './businessResults.js';

type BackendRevisionIssue = {
  code?: string;
  severity?: string;
  message?: string;
  business_key?: string;
  column?: string;
  old_value?: string | number;
  new_value?: string | number;
  old_basis?: unknown;
  new_basis?: unknown;
  changed_columns?: { column: string; old_value: string; new_value: string }[];
  changed_hash_aliases?: { kind: string; alias: string }[];
};

type BackendRevisionComparison = {
  summary?: { status?: string; issue_count?: number; compared_business_keys?: number };
  issues?: BackendRevisionIssue[];
};

type RevisionEvidence = {
  affected_claims?: { id?: string; label?: string; message?: string }[];
  unresolved_issues?: { code?: string; severity?: string; message?: string }[];
};

export function RevisionDiff({ current, previous, currentRevision, previousRevision, comparison, evidence }: {
  current: AnalysisRun;
  previous?: AnalysisRun;
  currentRevision?: number | string;
  previousRevision?: number | string;
  comparison?: BackendRevisionComparison;
  evidence?: RevisionEvidence;
}) {
  const hasBackendComparison = Boolean(comparison);
  const backendIssues = comparison?.issues ?? [];
  const changes = hasBackendComparison ? [] : compareBusinessRuns(current, previous);
  if (!previous && !hasBackendComparison) return <p className="analysis-note">暂无可比较的上一版结果。</p>;
  return <section className="analysis-revision-diff" aria-label="修订差异">
    <div className="analysis-section-heading">
      <div><h4>修订差异</h4><p className="analysis-note">基于稳定业务身份比较，不按行号推断。</p></div>
      <span className="analysis-note">修订 {previousRevision ?? '上版'} → 修订 {currentRevision ?? '当前'}{comparisonSummary(comparison)}</span>
    </div>
    {hasBackendComparison
      ? <BackendComparisonBody comparison={comparison!} issues={backendIssues} />
      : changes.length ? <div className="analysis-history-list">
        {changes.map((change, index) => <article key={`${change.identity}:${change.field}:${index}`} className="analysis-history-row analysis-history-row--static">
          <span>{change.label}</span><span>{change.field}</span><span>{change.before} → {change.after}</span>
        </article>)}
      </div> : <p className="analysis-note">可比较指标没有发现数值变化。</p>}
    {evidence?.affected_claims?.length ? <details className="analysis-details"><summary>受影响结论 · {evidence.affected_claims.length} 项</summary>
      {evidence.affected_claims.map((claim, index) => <p key={claim.id ?? index}>{claim.label ?? claim.id ?? `结论 ${index + 1}`}：{claim.message ?? '需要按当前修订复核。'}</p>)}
    </details> : null}
    {evidence?.unresolved_issues?.length ? <details className="analysis-details"><summary>未解决问题 · {evidence.unresolved_issues.length} 项</summary>
      {evidence.unresolved_issues.map((issue, index) => <p key={`${issue.code ?? 'issue'}:${index}`}>{issue.message ?? issue.code ?? '仍需复核'}</p>)}
    </details> : null}
  </section>;
}

function BackendComparisonBody({ comparison, issues }: { comparison: BackendRevisionComparison; issues: BackendRevisionIssue[] }) {
  const status = comparison.summary?.status;
  if (issues.length) {
    return <div className="analysis-history-list">
      {issues.map((issue, index) => <article key={`${issue.code}:${issue.business_key}:${issue.column}:${index}`} className="analysis-history-row analysis-history-row--static">
        <span>{issueTitle(issue)}</span><span>{issueSeverity(issue)}</span><span>{issueMessage(issue)}</span>
      </article>)}
    </div>;
  }
  if (status === 'no_comparable_runs') {
    return <p className="analysis-note">没有找到可以比较的上一次计算；系统不会按行序或字段名猜测对应关系。</p>;
  }
  if (status === 'no_parent') {
    return <p className="analysis-note">没有找到上一版修订，无法生成修订差异。</p>;
  }
  if (status === 'ambiguous' || status === 'revision_comparison_ambiguous') {
    return <p className="analysis-note">两次计算的可比范围有歧义，无法自动对应；系统不会按行序或字段名猜测。</p>;
  }
  return <p className="analysis-note">比较完成：{comparedCountText(comparison)}未发现需要处理的修订差异。</p>;
}

function comparisonSummary(comparison?: BackendRevisionComparison): string {
  if (!comparison) return '';
  const parts: string[] = [];
  if (comparison.summary?.status) parts.push(statusLabel(comparison.summary.status));
  if (typeof comparison.summary?.issue_count === 'number') parts.push(`${comparison.summary.issue_count} 项问题`);
  if (typeof comparison.summary?.compared_business_keys === 'number') parts.push(`${comparison.summary.compared_business_keys} 个可比指标`);
  return parts.length ? ` · ${parts.join(' · ')}` : '';
}

function comparedCountText(comparison: BackendRevisionComparison): string {
  const count = comparison.summary?.compared_business_keys;
  return typeof count === 'number' ? `${count} 个业务指标可比，` : '';
}

function statusLabel(status: string): string {
  return ({
    needs_attention: '需要处理',
    pass: '已比较',
    no_parent: '无上版',
    no_comparable_runs: '无可比计算',
    ambiguous: '比较歧义',
    revision_comparison_ambiguous: '比较歧义',
  } as Record<string, string>)[status] ?? status;
}

function issueTitle(issue: BackendRevisionIssue): string {
  const key = issue.business_key ? safeBusinessKey(issue.business_key) : '业务指标';
  if (issue.column === 'value') {
    const scenario = issue.business_key ? businessKeyField(issue.business_key, 'scenario') : undefined;
    const scenarioLabels: Record<string, string> = {
      actual_ytd: '累计实际', budget_ytd: '累计预算', estimated_budget_ytd: '累计估算预算',
      actual_month: '当月实际', budget_month: '当月预算', variance: '差异',
      achievement_ratio: '达成率', attainment_pct: '达成率',
    };
    return `${formatBusinessValue(key, 'text')} · ${scenarioLabels[scenario ?? ''] ?? scenario ?? '指标值'}`;
  }
  return issue.column ? `${key} · ${businessColumnLabel(issue.column)}` : key;
}

function issueSeverity(issue: BackendRevisionIssue): string {
  if (issue.severity === 'error') return '需处理';
  if (issue.severity === 'info') return '口径变化';
  if (issue.severity === 'warning') return '需复核';
  return '提示';
}

function issueMessage(issue: BackendRevisionIssue): string {
  if (issue.code === 'revision_numeric_regression') {
    const semantics = issueValueSemantics(issue, issue.column ?? '');
    return `${formatBusinessValue(issue.old_value, semantics)} → ${formatBusinessValue(issue.new_value, semantics)}；${issue.message ?? '同源同口径数值变化。'}`;
  }
  if (issue.code === 'revision_basis_changed') {
    const changes = issue.changed_columns?.map((change) =>
      `${formatBusinessValue(change.old_value, issueValueSemantics(issue, change.column))} → ${formatBusinessValue(change.new_value, issueValueSemantics(issue, change.column))}`,
    ) ?? [];
    const aliases = [...new Set(issue.changed_hash_aliases?.map((item) => item.alias) ?? [])];
    return [
      changes.length ? `数值变化：${changes.join('；')}` : '',
      aliases.length ? `变更资料：${aliases.join('、')}` : '',
      issue.message ?? '来源或口径发生变化，需核对后说明。',
    ].filter(Boolean).join('；');
  }
  if (issue.code === 'revision_comparison_ambiguous') {
    return issue.message ?? '业务身份匹配存在歧义，未按行号推断差异。';
  }
  return issue.message ?? issue.code ?? '修订差异需要复核。';
}

function issueValueSemantics(issue: BackendRevisionIssue, column: string) {
  if (column !== 'value') return columnSemantics(column);
  const scenario = issue.business_key ? businessKeyField(issue.business_key, 'scenario') : undefined;
  const unit = issue.business_key ? businessKeyField(issue.business_key, 'unit') : undefined;
  return scenario?.endsWith('_pct') ? 'ratio_pct' : unit === '比率' ? 'ratio' : 'amount';
}

function safeBusinessKey(value: string): string {
  return businessKeyField(value, 'metric') ?? value;
}

function businessKeyField(value: string, field: string): string | undefined {
  return new RegExp(`'${field}': '([^']+)'`).exec(value)?.[1]
    ?? new RegExp(`"${field}"\\s*:\\s*"([^"]+)"`).exec(value)?.[1];
}
