import { useCallback, useEffect, useState } from 'react';
import { ChevronDown, RefreshCw } from 'lucide-react';
import { bridge, shortSha, timeWait, when, type Answer, type FinanceSourceBatch } from '../../bridge.js';
import { WaitOrb } from '../../components/WaitOrb.js';
import { AccountingPeriodInput, FieldShell, TextField } from '../../components/FinancialControls.js';
import { Button } from '../../components/ui/button.js';
import { unwrap } from './shared.js';

export function SourceRefreshPanel({ taskId, busy, onRefresh }: { taskId: string; busy: boolean; onRefresh(): Promise<void> }) {
  const [batches, setBatches] = useState<FinanceSourceBatch[]>([]);
  const [scope, setScope] = useState({
    source_id: 'erp-export', tenant_id: 'default', ledger_id: '', organization_id: '', period: '',
    currency: 'CNY', cutoff_at: '', calendar: '', mode: 'snapshot',
  });
  const [product, setProduct] = useState('file');
  const [version, setVersion] = useState('export');
  const [name, setName] = useState('');
  const [policy, setPolicy] = useState<'snapshot_only' | 'business_key'>('snapshot_only');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const load = useCallback(async () => {
    const api = bridge(); if (!api?.financeCall) return;
    const answer = unwrap(await api.financeCall(taskId, 'finance-source-list') as Answer<{ batches: FinanceSourceBatch[] }>);
    setBatches(answer.batches ?? []);
  }, [taskId]);
  useEffect(() => { void load().catch(() => {}); }, [load]);
  async function refreshSource() {
    if (refreshing) return;
    setRefreshing(true);
    try {
      // Timed from the click, but main takes off the minutes the file dialog stood open.
      await timeWait('source.refresh', async (note) => {
        const api = bridge(); if (!api?.financeSourceRefresh) throw new Error('此版本暂不支持刷新财务来源文件。');
        setError(''); setMessage('');
        const cleanScope = Object.fromEntries(Object.entries(scope).filter(([, value]) => value.trim())) as Record<string, string>;
        const result = unwrap(await api.financeSourceRefresh(taskId, {
          product, version, name: name.trim() || undefined, file_identity_policy: policy, scope: cleanScope,
        }));
        if (result.cancelled) { note('cancelled'); setMessage('已取消刷新。'); return; }
        await onRefresh(); await load();
        const usable = typeof result.effective_dataset_id === 'string' ? result.effective_dataset_id : result.dataset_id;
        const datasetId = typeof usable === 'string' ? shortSha(usable) : '';
        setMessage(typeof result.dataset_id === 'string'
          ? `已发布新来源快照 ${datasetId}。历史结果仍按原快照保留。`
          : '文件内容与已发布快照一致，已保留原结果引用。');
      });
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setRefreshing(false);
    }
  }
  const ready = scope.source_id.trim() && scope.tenant_id.trim() && scope.ledger_id.trim()
    && scope.organization_id.trim() && scope.period.trim() && scope.currency.trim() && scope.cutoff_at.trim();
  return <details className="analysis-source-refresh" aria-label="刷新财务来源">
    <summary><span><span className="analysis-source-refresh-title">更新 ERP 来源</span>
      <span className="analysis-note">已有来源导出变化时，生成新的资料版本；旧运行仍引用旧快照。</span></span>
      <ChevronDown size={16} aria-hidden /></summary>
    <fieldset className="analysis-fieldset" disabled={busy || refreshing}><div className="analysis-edit-grid">
      <TextField label="来源编号" value={scope.source_id} onChange={(value) => setScope({ ...scope, source_id: value })} />
      <TextField label="租户/账套" value={scope.tenant_id} onChange={(value) => setScope({ ...scope, tenant_id: value })} />
      <TextField label="账簿" value={scope.ledger_id} onChange={(value) => setScope({ ...scope, ledger_id: value })} />
      <TextField label="组织" value={scope.organization_id} onChange={(value) => setScope({ ...scope, organization_id: value })} />
      <AccountingPeriodInput label="期间" value={scope.period} onChange={(value) => setScope({ ...scope, period: value })} />
      <TextField label="截止时间" value={scope.cutoff_at} placeholder="2026-08-31T23:59:59+08:00" onChange={(value) => setScope({ ...scope, cutoff_at: value })} />
      <TextField label="币种" value={scope.currency} onChange={(value) => setScope({ ...scope, currency: value })} />
      <TextField label="来源产品" value={product} onChange={setProduct} />
    </div>
    <details className="analysis-details"><summary>高级：来源身份与刷新方式</summary><div className="analysis-edit-grid">
      <TextField label="版本" value={version} onChange={setVersion} />
      <TextField label="资料名称" value={name} onChange={setName} />
      <TextField label="日历" value={scope.calendar} onChange={(value) => setScope({ ...scope, calendar: value })} />
      <TextField label="刷新模式" value={scope.mode} onChange={(value) => setScope({ ...scope, mode: value })} />
      <FieldShell label="文件身份策略"><select aria-label="文件身份策略" className="fnd-field" value={policy} onChange={(event) => setPolicy(event.target.value as typeof policy)}>
        <option value="snapshot_only">按文件快照</option><option value="business_key">按业务键识别</option></select></FieldShell>
    </div></details></fieldset>
    <div className="analysis-actions"><Button variant="outline" type="button" disabled={busy || refreshing || !ready} onClick={() => void refreshSource()}>
      <RefreshCw size={14} aria-hidden />选择文件并刷新</Button>
      {refreshing && <span role="status" className="analysis-note"><WaitOrb state="working" />正在选择文件并刷新来源…</span>}</div>
    {batches.length > 0 && <details className="analysis-details"><summary>来源刷新批次 · {batches.length} 个</summary>
      <div className="analysis-history-list">{[...batches].reverse().slice(0, 8).map((batch) => <div key={batch.id} className="analysis-history-row analysis-history-row--static">
        <span>{batch.source_name ?? batch.product ?? '来源文件'}</span><span>{batch.publication_status ?? 'recorded'} · {batch.row_count ?? 0} 行</span>
        <time>{when(batch.created_at)}</time><span>{batch.dataset_id ? `新快照 ${shortSha(batch.dataset_id)}` : batch.effective_dataset_id ? `沿用 ${shortSha(batch.effective_dataset_id)}` : batch.prior_snapshot_id ? `沿用 ${shortSha(batch.prior_snapshot_id)}` : shortSha(batch.id)}</span>
      </div>)}</div></details>}
    {message && <p role="status" className="analysis-message">{message}</p>}
    {error && <p role="alert" className="analysis-message analysis-message--error">{error}</p>}
  </details>;
}
