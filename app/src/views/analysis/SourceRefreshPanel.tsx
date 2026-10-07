import { useCallback, useEffect, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { bridge, timeWait, when, type Answer, type FinanceSourceBatch } from '../../bridge.js';
import { WaitLoop } from '../../components/WaitLoop.js';
import { AccountingPeriodInput, FieldShell, TextField } from '../../components/FinancialControls.js';
import { Button } from '../../components/ui/button.js';
import { unwrap, errorText } from './shared.js';
import { NativeSelect } from '../../components/ui/native-select.js';
import { DisclosureSummary } from '../../components/Disclosure.js';

// The engine refreshes a whole period or only what changed since the last refresh; it takes nothing else.
type SourceRefreshMode = 'full_period' | 'incremental';

export function SourceRefreshPanel({ taskId, busy, onRefresh }: { taskId: string; busy: boolean; onRefresh(): Promise<void> }) {
  const [batches, setBatches] = useState<FinanceSourceBatch[]>([]);
  const [scope, setScope] = useState({
    source_id: 'erp-export', tenant_id: 'default', ledger_id: '', organization_id: '', period: '',
    currency: 'CNY', cutoff_at: '', calendar: '', mode: 'full_period' as SourceRefreshMode,
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
        setMessage(typeof result.dataset_id === 'string'
          ? '已发布新来源快照，资料列表里是最新一版。历史结果仍按原快照保留。'
          : '文件内容与已发布快照一致，已保留原结果引用。');
      });
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      setRefreshing(false);
    }
  }
  const ready = scope.source_id.trim() && scope.tenant_id.trim() && scope.ledger_id.trim()
    && scope.organization_id.trim() && scope.period.trim() && scope.currency.trim() && scope.cutoff_at.trim();
  return <details className="analysis-source-refresh" aria-label="刷新财务来源">
    <DisclosureSummary><span className="analysis-source-refresh-title">更新 ERP 来源</span>
      <span className="analysis-note">来源系统重新导出后，在这里生成新的资料版本；已完成的计算仍按当时的资料保留。</span></DisclosureSummary>
    <fieldset className="analysis-fieldset" disabled={busy || refreshing}><div className="analysis-edit-grid">
      <TextField label="来源编号" value={scope.source_id} onChange={(value) => setScope({ ...scope, source_id: value })} />
      <TextField label="账套" value={scope.tenant_id} onChange={(value) => setScope({ ...scope, tenant_id: value })} />
      <TextField label="账簿" value={scope.ledger_id} onChange={(value) => setScope({ ...scope, ledger_id: value })} />
      <TextField label="组织" value={scope.organization_id} onChange={(value) => setScope({ ...scope, organization_id: value })} />
      <AccountingPeriodInput label="期间" value={scope.period} onChange={(value) => setScope({ ...scope, period: value })} />
      <TextField label="截止时间" value={scope.cutoff_at} placeholder="2026-08-31T23:59:59+08:00" onChange={(value) => setScope({ ...scope, cutoff_at: value })} />
      <TextField label="币种" value={scope.currency} onChange={(value) => setScope({ ...scope, currency: value })} />
      <TextField label="来源系统" value={product} onChange={setProduct} />
    </div>
    <details className="analysis-details"><DisclosureSummary>高级：来源识别与刷新方式</DisclosureSummary><div className="analysis-edit-grid">
      <TextField label="版本" value={version} onChange={setVersion} />
      <TextField label="资料名称" value={name} onChange={setName} />
      <TextField label="日历" value={scope.calendar} onChange={(value) => setScope({ ...scope, calendar: value })} />
      <FieldShell label="刷新模式"><NativeSelect aria-label="刷新模式" value={scope.mode} onChange={(event) => setScope({ ...scope, mode: event.target.value as SourceRefreshMode })}>
        <option value="full_period">整期</option><option value="incremental">增量</option></NativeSelect></FieldShell>
      <p className="analysis-note">按业务键逐行比对时生效：整期把文件视为整个期间，文件里没有的行记为已删除；增量只更新文件里出现的行。旧结果仍按原资料保留。</p>
      <FieldShell label="文件识别方式"><NativeSelect aria-label="文件识别方式" value={policy} onChange={(event) => setPolicy(event.target.value as typeof policy)}>
        <option value="snapshot_only">整份替换</option><option value="business_key">按业务键逐行比对</option></NativeSelect></FieldShell>
    </div></details></fieldset>
    <div className="analysis-actions"><Button variant="outline" type="button" disabled={busy || refreshing || !ready} onClick={() => void refreshSource()}>
      <RefreshCw size={14} aria-hidden />选择文件并刷新</Button>
      {refreshing && <span role="status" className="analysis-note"><WaitLoop />正在选择文件并刷新来源…</span>}</div>
    {batches.length > 0 && <details className="analysis-details"><DisclosureSummary>来源刷新批次 · {batches.length} 个</DisclosureSummary>
      <div className="analysis-history-list">{[...batches].reverse().slice(0, 8).map((batch) => <div key={batch.id} className="analysis-history-row analysis-history-row--static">
        <span>{batch.source_name ?? batch.product ?? '来源文件'}</span><span>{batch.publication_status ?? 'recorded'} · {batch.row_count ?? 0} 行</span>
        <time>{when(batch.created_at)}</time><span>{batch.dataset_id ? '生成了新快照' : batch.effective_dataset_id || batch.prior_snapshot_id ? '内容未变，沿用原快照' : '已记录'}</span>
      </div>)}</div></details>}
    {message && <p role="status" className="analysis-message">{message}</p>}
    {error && <p role="alert" className="analysis-message analysis-message--error">{error}</p>}
  </details>;
}
