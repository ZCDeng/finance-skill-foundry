import { when } from '../../bridge.js';
import { textValue } from './presentation.js';
import { Button } from '../../components/ui/button.js';
import { TechnicalInfo } from './TechnicalInfo.js';
import { errorText } from './glossary.js';
import { DisclosureSummary } from '../../components/Disclosure.js';

export interface FinanceCompletionRecovery {
  operation_id: string; status: string; revision?: number; title?: string; body?: string; limitations?: string[] | string; run_ids?: string[]; fact_ids?: string[];
  claims?: unknown[]; materiality?: Record<string, unknown>; requirements_id?: string | null; parent_id?: string | null; updated_at?: string;
  evidence_recipes?: Record<string, unknown>[]; consistency_rules?: Record<string, unknown>[]; consistency_sources?: Record<string, unknown>[] | Record<string, unknown>;
  attempt_status?: string | null; validation_error?: { code?: string; message?: string; details?: unknown[] } | null;
}

function recoveryLimitationsText(value: FinanceCompletionRecovery['limitations']): string {
  return Array.isArray(value) ? value.filter(Boolean).join('；') : textValue(value ?? '');
}

function recoveryStatusLabel(status: string): string {
  return ({ repair_available: '可修复', timed_out: '超时', cancelled: '已取消', failed: '失败', needs_review: '待审阅', awaiting_input: '等待输入' } as Record<string, string>)[status] ?? status;
}

function recoveryValidationText(item: FinanceCompletionRecovery): string {
  const error = item.validation_error;
  if (!error) return '';
  const first = Array.isArray(error.details) ? error.details[0] : null;
  if (first && typeof first === 'object') {
    const detail = first as Record<string, unknown>;
    const location = [typeof detail.row === 'number' ? `第 ${detail.row + 1} 行` : '', detail.column]
      .filter((part) => part !== undefined && part !== null && String(part).trim()).join(' · ');
    const values = detail.expected !== undefined || detail.actual !== undefined
      ? `填报 ${textValue(detail.expected ?? '')}，结果 ${textValue(detail.actual ?? '')}`
      : '';
    return [location, values].filter(Boolean).join('：');
  }
  return error.message ? errorText(error.message) : '';
}

export function CompletionRecoveriesPanel({ recoveries, error, disabled, onRetry, onLoad }: {
  recoveries: FinanceCompletionRecovery[]; error?: string; disabled: boolean; onRetry(): void; onLoad(recovery: FinanceCompletionRecovery): void;
}) {
  if (!recoveries.length && !error) return null;
  return <details className="analysis-details analysis-recovery-panel">
    <DisclosureSummary>可恢复的未保存文稿 · {recoveries.length} 条</DisclosureSummary>
    <p className="analysis-note">这些内容来自已终止但尚未落成文稿版本的操作。载入后只是可编辑副本，需要你检查并保存。</p>
    {error && <p role="alert" className="analysis-message analysis-message--error">恢复稿读取失败：{errorText(error)} <Button variant="outline" type="button" onClick={onRetry}>重试</Button></p>}
    <div className="analysis-history-list">{recoveries.map((item) => <div className="analysis-history-row analysis-history-row--static" key={item.operation_id}>
      <span>{item.title?.trim() || '未命名恢复稿'}</span>
      <span>{recoveryStatusLabel(item.status)}{item.updated_at ? ` · ${when(item.updated_at)}` : ''}{item.revision ? ` · ${item.revision}` : ''}</span>
      <span>{recoveryValidationText(item) || recoveryLimitationsText(item.limitations) || `${item.run_ids?.length ?? 0} 次计算 · ${item.fact_ids?.length ?? 0} 条事实`}</span>
      <Button variant="outline" type="button" disabled={disabled} onClick={() => onLoad(item)}>载入可编辑副本</Button>
      <TechnicalInfo rows={[
        ['操作编号', item.operation_id],
        ['计算编号', item.run_ids?.join('、')],
        ['原始检查', item.validation_error ? JSON.stringify(item.validation_error) : undefined],
      ]} />
    </div>)}</div>
  </details>;
}
