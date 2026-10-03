import { useCallback, useEffect, useState } from 'react';
import { CircleAlert, CircleCheck, CircleDashed, CircleSlash, RefreshCw } from 'lucide-react';
import { bridge, type Answer } from '../../bridge.js';
import { Button } from '../../components/ui/button.js';
import { ControlsPanel } from './ControlsPanel.js';
import { errorText } from './shared.js';

export type CloseTarget = 'scope' | 'datasets' | 'structure' | 'controls' | 'results' | 'drafts';
type BlockState = 'done' | 'blocked' | 'attention' | 'not_started';
type CloseItem = { text: string; blocking: boolean; attention?: boolean; target?: CloseTarget };
type CloseBlock = { key: string; label: string; state: BlockState; items: CloseItem[] };
export type CloseStatus = {
  headline: { state: 'not_ready' | 'calculable' | 'needs_review' | 'ready_for_review' | 'archived'; text: string };
  blocks: CloseBlock[];
  blocking: string[];
};

const STATE_WORDS: Record<BlockState, string> = { done: '已就绪', blocked: '待处理', attention: '请留意', not_started: '尚未开始' };
const STATE_ICONS = { done: CircleCheck, blocked: CircleSlash, attention: CircleAlert, not_started: CircleDashed } as const;

/**
 * 月结控制中心: whether this month can go to the manager for sign-off, and what is in the way.
 *
 * The headline and every block come from the server (finance_close_status); nothing here
 * decides a status. The words never say 完成: the best the system can say is that a
 * close is ready for the manager to review. Colour is never the only signal: each block
 * also says its state in words and carries its own icon.
 */
export function MonthCloseControlCenter({ taskId, refreshKey, busy, onOpen }: {
  taskId: string; refreshKey?: unknown; busy?: boolean; onOpen(target: CloseTarget): void;
}) {
  const [status, setStatus] = useState<CloseStatus | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [controlsVersion, setControlsVersion] = useState(0);

  const load = useCallback(async () => {
    const api = bridge(); if (!api?.financeCall) return;
    setLoading(true); setError('');
    try {
      const answer = await api.financeCall(taskId, 'finance-close-status') as Answer<CloseStatus> | undefined;
      if (!answer) return;
      if (!answer.ok) throw new Error(answer.message);
      setStatus(answer.value);
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      setLoading(false);
    }
  }, [taskId]);
  useEffect(() => { void load(); }, [load, refreshKey, controlsVersion]);

  if (!bridge()?.financeCall) return <p className="analysis-note">此版本暂不支持月结控制中心。</p>;
  return (
    <div className="analysis-close" aria-busy={loading}>
      {/* Only the headline is announced; the button and the loading line are not news. */}
      <span className="sr-only" role="status">{status?.headline.text ?? ''}</span>
      <div className={`analysis-close-headline analysis-close-headline--${status?.headline.state ?? 'loading'}`}>
        <h3>{status ? status.headline.text : loading ? '正在检查月结状态…' : '还没读到月结状态'}</h3>
        <Button variant="outline" type="button" disabled={loading || busy} onClick={() => void load()}>
          <RefreshCw size={14} strokeWidth={1.5} aria-hidden />重新检查</Button>
      </div>
      {error ? <p role="alert" className="analysis-message analysis-message--error">{error}</p> : null}
      {status && !['ready_for_review', 'archived'].includes(status.headline.state) && status.blocking.length
        ? <p className="analysis-note">下一步：{status.blocking[0]}</p> : null}
      {status ? <ol className="analysis-close-blocks">
        {status.blocks.map((block, index) => {
          const Icon = STATE_ICONS[block.state];
          return <li key={block.key} className={`analysis-close-block analysis-close-block--${block.state}`} aria-label={`${index + 1} ${block.label}：${STATE_WORDS[block.state]}`}>
            <div className="analysis-close-block-head">
              <Icon size={16} strokeWidth={1.5} aria-hidden />
              <h4>{index + 1} {block.label}</h4>
              <span className="analysis-close-block-state">{STATE_WORDS[block.state]}</span>
            </div>
            <ul>
              {block.items.map((item, itemIndex) => <li key={itemIndex} className={item.blocking ? 'analysis-close-item--blocking' : undefined}>
                <span>{item.text}</span>
                {item.blocking && item.target && item.target !== 'controls' ? <Button variant="link" size="sm" type="button" onClick={() => onOpen(item.target!)}>去处理</Button> : null}
              </li>)}
            </ul>
          </li>;
        })}
      </ol> : null}
      <div id="month-close-controls">
        <ControlsPanel taskId={taskId} refreshKey={`${String(refreshKey)}:${controlsVersion}`} busy={busy} onChanged={() => setControlsVersion((value) => value + 1)} />
      </div>
    </div>
  );
}
