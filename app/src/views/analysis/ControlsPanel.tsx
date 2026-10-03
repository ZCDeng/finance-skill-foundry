import { useCallback, useEffect, useState } from 'react';
import { ClipboardCopy, GitCompareArrows, ListChecks, Play, Scale, SearchCheck } from 'lucide-react';
import { bridge, type Answer } from '../../bridge.js';
import { Button } from '../../components/ui/button.js';
import { Input } from '../../components/ui/input.js';
import { Textarea } from '../../components/ui/textarea.js';
import { HelpLink } from '../guide/GuideHub.js';
import {
  DECISION_LABELS, ISSUE_LABELS, STATUS_LABELS, where,
  type ControlList, type ControlRow, type Disposition, type Suggestion,
} from './controls.js';
import { errorText, unwrap } from './shared.js';
import { TieOutForm } from './TieOutForm.js';

type Decision = Disposition['decision'];

/**
 * 勾稽控制: does each total equal what it totals, and what the manager decided where it does not.
 *
 * The system finds a difference and never picks a side. A difference holds the close until
 * the manager accepts it with a reason, or it stops being a difference. Waiting on whoever
 * compiled the books, or on a corrected file, still holds it.
 */
export function ControlsPanel({ taskId, refreshKey, busy, onChanged }: { taskId: string; refreshKey?: unknown; busy?: boolean; onChanged?(): void }) {
  const [list, setList] = useState<ControlList | null>(null);
  const [suggestions, setSuggestions] = useState<Suggestion[] | null>(null);
  const [picked, setPicked] = useState<Record<number, boolean>>({});
  const [working, setWorking] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [declaring, setDeclaring] = useState(false);

  const call = useCallback(async <T,>(command: string, spec?: unknown): Promise<T> => {
    const api = bridge(); if (!api?.financeCall) throw new Error('此版本暂不支持勾稽控制。');
    return unwrap(await api.financeCall(taskId, command as never, spec as never) as Answer<T>);
  }, [taskId]);

  const load = useCallback(async () => {
    if (!bridge()?.financeCall) return;
    try { setList(await call<ControlList>('finance-controls-list', {})); } catch (failure) { setError(errorText(failure)); }
  }, [call]);
  useEffect(() => { void load(); }, [load, refreshKey]);

  async function act(label: string, work: () => Promise<string | void>) {
    setWorking(label); setError(''); setMessage('');
    try {
      const done = await work();
      if (done) setMessage(done);
      await load();
      onChanged?.();
      window.dispatchEvent(new Event('fnd:task-changed'));
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      setWorking('');
    }
  }

  const propose = () => act('正在从合计行找控制…', async () => {
    const found = (await call<{ suggestions: Suggestion[] }>('finance-controls-propose', {})).suggestions
      .filter((row) => !row.saved_id)
      // Differences first: those are the ones worth a manager's minute.
      .sort((a, b) => Number(a.preview.status === 'pass') - Number(b.preview.status === 'pass'));
    setSuggestions(found);
    setPicked(Object.fromEntries(found.map((row, index) => [index, row.preview.status !== 'pass'])));
    return found.length ? `找到 ${found.length} 条建议，其中 ${found.filter((row) => row.preview.status === 'break').length} 条不相符。` : '没有新的建议。';
  });

  const confirmPicked = () => act('正在确认…', async () => {
    const chosen = (suggestions ?? []).filter((_, index) => picked[index]).map((row) => row.control);
    if (!chosen.length) return '没有选中的建议。';
    await call('finance-controls-save', { controls: chosen, origin: 'suggested', confirm: true });
    await call('finance-controls-run', {});
    setSuggestions(null);
    return `已确认 ${chosen.length} 条控制并运行。`;
  });

  const run = () => act('正在运行控制…', async () => { await call('finance-controls-run', {}); return '已重新运行。'; });

  const copySheet = () => act('正在生成确认单…', async () => {
    const sheet = await call<{ count: number; markdown: string; tsv: string }>('finance-control-confirmation-sheet', {});
    if (!sheet.count) return '没有需要对方确认的差异。';
    await navigator.clipboard.writeText(sheet.markdown);
    return `已复制确认单（${sheet.count} 项）。粘贴到邮件或文档即可。`;
  });
  const copyTable = () => act('正在生成表格…', async () => {
    const sheet = await call<{ count: number; tsv: string }>('finance-control-confirmation-sheet', {});
    if (!sheet.count) return '没有需要对方确认的差异。';
    await navigator.clipboard.writeText(sheet.tsv);
    return '已复制为表格，可直接粘贴到 Excel。';
  });

  const toggleReview = (on: boolean) => act('正在保存设置…', async () => {
    await call('finance-control-settings-save', { require_second_review: on });
    return on ? '接受差异后需要第二人复核。' : '之后接受差异由一人确认即可；已在等复核的仍需复核。';
  });

  if (!bridge()?.financeCall) return null;
  const rows = list?.controls ?? [];
  const issues = rows.filter((row) => row.issue);
  const summary = list?.summary;
  const locked = Boolean(busy || working);

  return (
    <section className="fnd-card analysis-controls-card" aria-label="勾稽控制">
      <div className="analysis-section-heading">
        <div>
          <span className="fnd-with-help"><h4><Scale size={15} strokeWidth={1.5} aria-hidden /> 勾稽控制</h4><HelpLink article="controls" label="勾稽控制与差异处置" /></span>
          <p className="analysis-note">合计是否等于分项、两处取数是否一致。系统只指出差异，不替你选口径。</p>
        </div>
        <div className="analysis-actions">
          <Button variant="outline" type="button" disabled={locked} onClick={() => void propose()}><SearchCheck size={15} strokeWidth={1.5} aria-hidden />找建议控制</Button>
          <Button variant="outline" type="button" disabled={locked || declaring} onClick={() => { setDeclaring(true); setMessage(''); }}><GitCompareArrows size={15} strokeWidth={1.5} aria-hidden />添加两处取数对比</Button>
          <Button variant="outline" type="button" disabled={locked || !summary?.confirmed} onClick={() => void run()}><Play size={15} strokeWidth={1.5} aria-hidden />重新运行</Button>
        </div>
      </div>

      {summary ? <p className="analysis-note" role="status">
        {summary.confirmed
          ? `已确认 ${summary.confirmed} 条 · 相符 ${summary.pass} · 不相符 ${summary.break}${summary.break_within_rounding ? `（其中 ${summary.break_within_rounding} 条可能是显示舍入）` : ''} · 读不出 ${summary.error} · 已过期 ${summary.stale} · 挡住月结 ${summary.blocking ?? 0} 项`
          : '还没有确认的控制。先找建议控制，确认要检查的那些。'}
      </p> : null}
      {working ? <p className="analysis-note" role="status">{working}</p> : null}
      {error ? <p role="alert" className="analysis-message analysis-message--error">{error}</p> : null}
      {message ? <p className="analysis-message">{message}</p> : null}

      {declaring ? <TieOutForm call={call} locked={locked} onCancel={() => setDeclaring(false)} onSaved={async (done) => {
        setDeclaring(false); setMessage(done);
        await load(); onChanged?.(); window.dispatchEvent(new Event('fnd:task-changed'));
      }} /> : null}

      {suggestions && suggestions.length > 0 ? <fieldset className="analysis-fieldset analysis-controls-suggestions" disabled={locked}>
        <legend>建议的控制（勾选要确认的）</legend>
        <ul className="analysis-controls-list">
          {suggestions.map((row, index) => <li key={index}>
            <label className="analysis-controls-pick">
              <input type="checkbox" checked={Boolean(picked[index])} onChange={(event) => setPicked((current) => ({ ...current, [index]: event.target.checked }))} />
              <span>{row.control.label}</span>
              <span className={`analysis-controls-status analysis-controls-status--${row.preview.status}`}>{STATUS_LABELS[row.preview.status]}</span>
              {row.preview.status === 'break' ? <span className="analysis-note">差额 {row.preview.difference} · {where(row.control.left)} 对 {where(row.control.right)}</span> : null}
            </label>
          </li>)}
        </ul>
        <div className="analysis-actions">
          <Button type="button" onClick={() => void confirmPicked()}><ListChecks size={15} strokeWidth={1.5} aria-hidden />确认选中的 {Object.values(picked).filter(Boolean).length} 条</Button>
          <Button variant="outline" type="button" onClick={() => setSuggestions(null)}>先不确认</Button>
        </div>
      </fieldset> : null}

      {issues.length > 0 ? <div className="analysis-controls-issues">
        <div className="analysis-section-heading"><h5>差异与处置 · {issues.filter((row) => row.issue?.blocking).length} 项挡住月结</h5>
          <div className="analysis-actions">
            <Button variant="outline" size="sm" type="button" disabled={locked} onClick={() => void copySheet()}><ClipboardCopy size={14} strokeWidth={1.5} aria-hidden />复制确认单</Button>
            <Button variant="outline" size="sm" type="button" disabled={locked} onClick={() => void copyTable()}>复制为表格</Button>
          </div></div>
        <ul className="analysis-controls-list">
          {issues.map((row) => <IssueRow key={`${row.id}:${row.issue?.disposition?.id ?? ''}:${row.issue?.state}`} row={row} locked={locked} requireReview={Boolean(list?.settings?.require_second_review)}
            onDecide={(spec) => act('正在保存处置…', async () => { await call('finance-control-disposition-save', { control_id: row.id, ...spec }); return '已保存处置。'; })}
            onRetire={(reason) => act('正在停用…', async () => { await call('finance-controls-retire', { id: row.id, reason }); return '已停用这条控制。'; })}
            onReview={(id, reviewer) => act('正在保存复核…', async () => { await call('finance-control-disposition-review', { id, reviewer }); return '已复核。'; })} />)}
        </ul>
      </div> : null}

      <label className="analysis-controls-setting">
        <input type="checkbox" disabled={locked} checked={Boolean(list?.settings?.require_second_review)} onChange={(event) => void toggleReview(event.target.checked)} />
        接受差异后需要第二人复核
      </label>
    </section>
  );
}

function IssueRow({ row, locked, requireReview, onDecide, onReview, onRetire }: {
  row: ControlRow; locked: boolean; requireReview: boolean;
  onDecide(spec: { decision: Decision; reason: string; counterparty?: string; decided_by_name?: string }): void;
  onReview(id: string, reviewer: string): void;
  onRetire(reason: string): void;
}) {
  const [changing, setChanging] = useState(false);
  const [retireReason, setRetireReason] = useState('');
  const [decision, setDecision] = useState<Decision | ''>('');
  const [reason, setReason] = useState('');
  const [counterparty, setCounterparty] = useState('');
  const [name, setName] = useState('');
  const [reviewer, setReviewer] = useState('');
  const issue = row.issue!;
  const result = row.result;
  const decidable = result && (result.status === 'break' || result.status === 'error') && issue.state !== 'stale';
  // A range that cannot be read is fixed in the file, never accepted.
  const choices: Decision[] = result?.status === 'error' ? ['corrected'] : ['waived', 'pending_external', 'corrected'];
  const settled = issue.state === 'waived' || issue.state === 'awaiting_review';
  const needsReason = decision === 'waived' || decision === 'pending_external';
  const needsName = decision === 'waived' && requireReview;
  const ready = decision && (!needsReason || reason.trim()) && (decision !== 'pending_external' || counterparty.trim()) && (!needsName || name.trim());
  return <li className="analysis-controls-issue">
    <div className="analysis-controls-issue-head">
      <strong>{row.control.label}</strong>
      <span className={`analysis-controls-state analysis-controls-state--${issue.blocking ? 'blocking' : 'clear'}`}>{ISSUE_LABELS[issue.state]}</span>
    </div>
    {result?.left ? <p className="analysis-note">
      {where(result.left)} 合计 {result.left.value ?? '—'}；{where(result.right)} 合计 {result.right?.value ?? '—'}
      {result.difference ? `；差额 ${result.difference}` : ''}{result.within_rounding ? '（可能是显示舍入）' : ''}
    </p> : null}
    {result?.reason ? <p className="analysis-note">{result.reason}</p> : null}
    {issue.state === 'stale' ? <div className="analysis-controls-decide">
      <p className="analysis-note">这条控制读的资料已有更新版本。在新版本上找建议控制并确认后，停用这一条。</p>
      <div className="analysis-actions">
        <Input aria-label="停用原因" placeholder="停用原因，例如：已换用修正后的资料" value={retireReason} disabled={locked} onChange={(event) => setRetireReason(event.target.value)} />
        <Button type="button" size="sm" variant="outline" disabled={locked || !retireReason.trim()} onClick={() => onRetire(retireReason.trim())}>停用这条控制</Button>
      </div></div> : null}
    {issue.disposition ? <p className="analysis-note">处置：{DECISION_LABELS[issue.disposition.decision]}
      {issue.disposition.counterparty ? ` · ${issue.disposition.counterparty}` : ''}{issue.disposition.reason ? ` · ${issue.disposition.reason}` : ''}
      {issue.disposition.reviewer ? ` · 复核人 ${issue.disposition.reviewer}` : ''}</p> : null}
    {issue.outdated_disposition ? <p className="analysis-note">之前的处置针对的是另一笔差额，已不适用。</p> : null}
    {issue.state === 'awaiting_review' && issue.disposition ? <div className="analysis-actions">
      <Input aria-label="复核人" placeholder="复核人姓名" value={reviewer} disabled={locked} onChange={(event) => setReviewer(event.target.value)} />
      <Button type="button" size="sm" disabled={locked || !reviewer.trim()} onClick={() => onReview(issue.disposition!.id, reviewer.trim())}>复核通过</Button>
    </div> : null}
    {decidable && settled && !changing ? <div className="analysis-actions">
      <Button type="button" size="sm" variant="outline" disabled={locked} onClick={() => setChanging(true)}>{issue.state === 'awaiting_review' ? '不同意，改处置' : '改处置'}</Button></div> : null}
    {decidable && (!settled || changing) ? <fieldset className="analysis-fieldset analysis-controls-decide" disabled={locked}>
      <legend className="sr-only">处置这项差异</legend>
      <div className="analysis-actions" role="radiogroup" aria-label="处置方式">
        {choices.map((item) => <label key={item}>
          <input type="radio" name={`decision-${row.id}`} checked={decision === item} onChange={() => setDecision(item)} />{DECISION_LABELS[item]}
        </label>)}
      </div>
      {decision ? <>
        {decision === 'pending_external' ? <Input aria-label="由谁确认" placeholder="由谁确认，例如：账套编制方" value={counterparty} onChange={(event) => setCounterparty(event.target.value)} /> : null}
        <Textarea aria-label="说明" placeholder={needsReason ? '必填：为什么接受这笔差异，或请对方确认什么' : '可选：修正了什么'} value={reason} onChange={(event) => setReason(event.target.value)} rows={2} />
        {needsName ? <Input aria-label="你的姓名" placeholder="必填：你的姓名（复核人需是另一个人）" value={name} onChange={(event) => setName(event.target.value)} /> : null}
        <div className="analysis-actions"><Button type="button" size="sm" disabled={!ready}
          onClick={() => onDecide({ decision: decision as Decision, reason: reason.trim(), ...(counterparty.trim() ? { counterparty: counterparty.trim() } : {}), ...(name.trim() ? { decided_by_name: name.trim() } : {}) })}>保存处置</Button></div>
      </> : null}
    </fieldset> : null}
  </li>;
}
