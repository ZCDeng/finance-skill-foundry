import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { CircleAlert, CircleCheck, CircleDashed, CircleSlash, RefreshCw } from 'lucide-react';
import { bridge, type Answer } from '../../bridge.js';
import { Button } from '../../components/ui/button.js';
import { ControlsPanel } from './ControlsPanel.js';
import { HelpLink } from '../guide/GuideHub.js';
import { errorText } from './shared.js';
import { formatPeriod } from '../../lib/period.js';
import { joinParts } from '../../components/PeriodWords.js';
import { DisclosureSummary } from '../../components/Disclosure.js';
import { Loading, SkeletonCards } from '../../components/Loading.js';

export type CloseTarget = 'scope' | 'datasets' | 'structure' | 'controls' | 'results' | 'drafts';
type BlockState = 'done' | 'blocked' | 'attention' | 'not_started';
type CloseItem = { text: string; blocking: boolean; attention?: boolean; target?: CloseTarget; hint?: string; scope?: Record<string, string> };
type CloseBlock = { key: string; label: string; state: BlockState; items: CloseItem[] };
type ConclusionLevel = 'usable' | 'usable_with_caveats' | 'not_usable' | 'not_assessable';
type ConclusionReason = { text: string; target?: CloseTarget };
/** 可用结论: separate from the headline, read only from the controls and dispositions the manager confirmed. */
export type CloseConclusion = {
  level: ConclusionLevel; text: string; reasons?: ConclusionReason[];
  basis?: { confirmed: number; passed: number; waived: number; open: number };
  workbooks?: { dataset_id: string; name: string; level: ConclusionLevel; text: string; reasons?: ConclusionReason[] }[];
};
export type CloseStatus = {
  headline: { state: 'not_ready' | 'calculable' | 'needs_review' | 'ready_for_review' | 'archived'; text: string; detail?: string };
  blocks: CloseBlock[];
  blocking: string[];
  conclusion?: CloseConclusion;
};

const STATE_WORDS: Record<BlockState, string> = { done: '已就绪', blocked: '待处理', attention: '请留意', not_started: '尚未开始' };
const STATE_ICONS = { done: CircleCheck, blocked: CircleSlash, attention: CircleAlert, not_started: CircleDashed } as const;
const CONCLUSION_ICONS = { usable: CircleCheck, usable_with_caveats: CircleAlert, not_usable: CircleSlash, not_assessable: CircleDashed } as const;

/**
 * 月结控制中心: whether this month can go to the manager for sign-off, and what is in the way.
 *
 * The headline and every block come from the server (finance_close_status); nothing here
 * decides a status. The words never say 完成: the best the system can say is that a
 * close is ready for the manager to review. Colour is never the only signal: each block
 * also says its state in words and carries its own icon.
 *
 * The headline number is the length of `status.blocking`, which is exactly the rows listed in
 * the open (待处理) cards, so a manager can count it there. Only 待处理 and 请留意 blocks open
 * as cards; the settled ones fold into one 已就绪 line and one 尚未开始 line. The page reads
 * top down as headline, 下一步, the open cards, those two lines, then the 套表可用结论, so the
 * conclusion's reasons never sit beside the number they are not counted in.
 */
export function MonthCloseControlCenter({ taskId, refreshKey, busy, onOpen }: {
  taskId: string; refreshKey?: unknown; busy?: boolean; onOpen(target: CloseTarget): void;
}) {
  const [status, setStatus] = useState<CloseStatus | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [controlsVersion, setControlsVersion] = useState(0);
  const controlsRef = useRef<HTMLDivElement>(null);

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

  // The tie-out controls sit below on this page; the 资料 tab is no place to fix them.
  const open = (target: CloseTarget) => {
    if (target !== 'controls') { onOpen(target); return; }
    // Only the pane that scrolls moves: the app frame around it clips, but would still scroll.
    // (`container` is in Chromium since 140; the DOM typings do not list it yet.)
    controlsRef.current?.scrollIntoView?.({ block: 'start', container: 'nearest' } as ScrollIntoViewOptions);
    controlsRef.current?.querySelector<HTMLElement>('#analysis-controls-heading')?.focus({ preventScroll: true });
  };
  const blocks = status?.blocks.map((block, index) => ({ block, number: index + 1 })) ?? [];
  const holding = status && ['not_ready', 'needs_review'].includes(status.headline.state);

  if (!bridge()?.financeCall) return <p className="analysis-note">此版本暂不支持月结控制中心。</p>;
  return (
    <div className="analysis-close" aria-busy={loading}>
      {/* The headline is announced, and the first read through Loading; the button is not news. */}
      <span className="sr-only" role="status">{status ? [status.headline.text, status.headline.detail].filter(Boolean).join('。') : ''}</span>
      <div className="analysis-close-headline">
        <div className="analysis-close-headline-text">
          <span className="fnd-with-help"><span className="analysis-close-headline-title">
            {holding ? <CircleAlert className="analysis-close-headline-icon" size={20} strokeWidth={1.5} aria-hidden /> : null}
            <h3>{status ? status.headline.text : loading ? '正在检查月结状态…' : '还没读到月结状态'}</h3></span>
            <HelpLink article="month-close" label="月结怎么走一遍" /></span>
          {status?.headline.detail ? <p className="analysis-close-detail"><CircleAlert size={16} strokeWidth={1.5} aria-hidden />{status.headline.detail}</p> : null}
        </div>
        <Button variant="outline" type="button" disabled={loading || busy} onClick={() => void load()}>
          <RefreshCw size={14} strokeWidth={1.5} aria-hidden />重新检查</Button>
      </div>
      {loading && !status ? <Loading label="正在检查月结状态…"><SkeletonCards cards={4} headline={false} /></Loading> : null}
      {error ? <p role="alert" className="analysis-message analysis-message--error">{error}</p> : null}
      {status && !['ready_for_review', 'archived'].includes(status.headline.state) && status.blocking.length
        ? <p className="analysis-note">下一步：{status.blocking[0]}</p> : null}
      {blocks.some(({ block }) => block.state === 'blocked' || block.state === 'attention') ? <ol className="analysis-close-blocks">
        {blocks.filter(({ block }) => block.state === 'blocked' || block.state === 'attention')
          .map(({ block, number }) => <OpenBlock key={block.key} block={block} number={number} onOpen={open} />)}
      </ol> : null}
      <SettledLine words="已就绪" Icon={CircleCheck} blocks={blocks.filter(({ block }) => block.state === 'done').map(({ block }) => block)} />
      <SettledLine words="尚未开始" Icon={CircleDashed} blocks={blocks.filter(({ block }) => block.state === 'not_started').map(({ block }) => block)} />
      {status?.conclusion ? <Conclusion conclusion={status.conclusion} /> : null}
      <div id="month-close-controls" ref={controlsRef}>
        <ControlsPanel taskId={taskId} refreshKey={`${String(refreshKey)}:${controlsVersion}`} busy={busy} onChanged={() => setControlsVersion((value) => value + 1)} />
      </div>
    </div>
  );
}

/**
 * An item as the page writes it. The confirmed scope comes with its values by key, so its period
 * reads 2026 年 1–8 月; the text stays as stored for the assistant, and an older answer without
 * the values shows that text.
 */
// The order the server writes the scope text in (SCOPE_REQUIRED), not the order the keys arrive in.
const SCOPE_ORDER = ['period', 'organization', 'unit', 'currency'] as const;

/** The scope segments in order, each with whether it is the worded period; null for any other item. */
function scopeSegments(item: CloseItem): { text: string; period: boolean }[] | null {
  if (!item.scope) return null;
  const scope = item.scope;
  return SCOPE_ORDER.filter((key) => scope[key]).map((key) => ({ text: key === 'period' ? formatPeriod(scope[key]) : scope[key], period: key === 'period' }));
}

const itemWords = (item: CloseItem): string => scopeSegments(item)?.map(({ text }) => text).join(' · ') ?? item.text;

/** The same words on screen, the period kept on one line. */
const itemNode = (item: CloseItem): ReactNode => {
  const segments = scopeSegments(item);
  return segments ? joinParts(segments.map(({ text, period }) => period ? <span className="fnd-period">{text}</span> : text)) : item.text;
};

/** An item's words; a hint (a file's digest) rides only in the tooltip: a hash read aloud tells nobody anything. */
function ItemText({ item }: { item: CloseItem }) {
  return item.hint ? <span title={item.hint}>{itemNode(item)}</span> : <>{itemNode(item)}</>;
}

/**
 * What a settled block says in plain view. 范围 shows what was confirmed and 复核 its line about
 * the manager, so 已就绪 is never read as signed off; a note on replaced files stays in view too.
 * File rows and the other blocks' one-line summaries are left to the tooltip and screen readers.
 */
const inView = (block: CloseBlock, item: CloseItem) =>
  block.key === 'scope' || block.key === 'review' || (block.key === 'source' && item.target !== 'datasets');

/**
 * A 待处理 or 请留意 card. A 待处理 card lists only the rows that hold the close, the ones the
 * headline counts; anything else it says sits below the list, so neither depends on colour. One
 * 去处理 at the foot goes where the first of those rows is fixed.
 */
function OpenBlock({ block, number, onOpen }: { block: CloseBlock; number: number; onOpen(target: CloseTarget): void }) {
  const Icon = STATE_ICONS[block.state];
  const blocked = block.state === 'blocked';
  const rows = blocked ? block.items.filter((item) => item.blocking) : block.items;
  const notes = blocked ? block.items.filter((item) => !item.blocking) : [];
  const target = rows.find((item) => item.blocking && item.target)?.target;
  return <li value={number} className={`analysis-close-block analysis-close-block--${block.state} fnd-fold-inset`} aria-label={`${number} ${block.label}：${STATE_WORDS[block.state]}`}>
    <div className="analysis-close-block-head">
      <Icon size={16} strokeWidth={1.5} aria-hidden />
      <h4>{number} {block.label}</h4>
      <span className="analysis-close-block-state">{STATE_WORDS[block.state]}</span>
    </div>
    <ul>{rows.map((item, index) => <li key={index}><ItemText item={item} /></li>)}</ul>
    {notes.map((item, index) => <p key={index} className="analysis-note">{item.attention ? '请留意：' : ''}<ItemText item={item} /></p>)}
    {target ? <Button variant="outline" type="button" className="analysis-close-block-action" onClick={() => onOpen(target)}>去处理</Button> : null}
  </li>;
}

/** 已就绪：范围（…）、来源、异常 — the settled blocks in one line, each name with its details. */
function SettledLine({ words, Icon, blocks }: { words: string; Icon: typeof CircleCheck; blocks: CloseBlock[] }) {
  if (!blocks.length) return null;
  return <p className="analysis-close-settled">
    <Icon size={16} strokeWidth={1.5} aria-hidden />
    <span>{words}：{blocks.map((block, index) => {
      const shown = block.items.filter((item) => inView(block, item));
      const tucked = block.items.filter((item) => !inView(block, item));
      const title = tucked.map((item) => [itemWords(item), item.hint].filter(Boolean).join(' · ')).join('\n');
      return <span key={block.key}>{index ? '、' : ''}<span title={title || undefined}>{block.label}</span>
        {shown.length ? <span className="analysis-close-settled-detail">（{joinParts(shown.map(itemNode), '；')}）</span> : null}
        {tucked.length ? <span className="sr-only">（{tucked.map(itemWords).join('；')}）</span> : null}</span>;
    })}</span>
  </p>;
}

/**
 * 套表可用结论 below the step cards, never in place of the headline: the headline says where the
 * close stands, this says whether the books as they stand can be used. Words and an icon carry
 * the level; under 不可用 the level word and icon take the warning colour and under 无法判断 the
 * muted one, while the label stays in ink. Never the gold of location.
 */
function Conclusion({ conclusion }: { conclusion: CloseConclusion }) {
  const Icon = CONCLUSION_ICONS[conclusion.level] ?? CircleDashed;
  const reasons = conclusion.reasons ?? [];
  const workbooks = conclusion.workbooks ?? [];
  const basis = conclusion.basis;
  // Five reasons read at a glance; past that, three lead and the rest fold.
  const shown = reasons.length > 5 ? 3 : reasons.length;
  return <section className={`analysis-close-conclusion analysis-close-conclusion--${conclusion.level}`} aria-label="套表可用结论">
    <div className="analysis-close-conclusion-head">
      <Icon size={16} strokeWidth={1.5} aria-hidden />
      <h3>套表可用结论：<span className="analysis-close-conclusion-level">{conclusion.text}</span></h3>
    </div>
    <p className="analysis-note">结论只根据你确认过的控制和处置得出；助手的类型建议不改变结论。</p>
    {basis && Object.values(basis).some((count) => count > 0) ? <p className="analysis-note">依据：你确认的 {basis.confirmed} 条控制，相符 {basis.passed} 条，已接受差异 {basis.waived} 条，仍挡住月结 {basis.open} 条。</p> : null}
    {reasons.length ? <ul className="analysis-close-conclusion-reasons">
      {reasons.slice(0, shown).map((reason, index) => <li key={index}>{reason.text}</li>)}
    </ul> : null}
    {reasons.length > shown ? <details className="analysis-details">
      <DisclosureSummary>另外 {reasons.length - shown} 条原因</DisclosureSummary>
      <ul className="analysis-close-conclusion-reasons">{reasons.slice(shown).map((reason, index) => <li key={index}>{reason.text}</li>)}</ul>
    </details> : null}
    {workbooks.length ? <details className="analysis-details">
      <DisclosureSummary>按工作簿看</DisclosureSummary>
      <ul className="analysis-close-conclusion-books">
        {workbooks.map((book) => <li key={book.dataset_id} className={`analysis-close-conclusion-book--${book.level}`}>
          <span><strong>{book.name}</strong>：<span className="analysis-close-conclusion-level">{book.text}</span></span>
          {book.reasons?.length ? <ul className="analysis-close-conclusion-reasons">{book.reasons.map((reason, index) => <li key={index}>{reason.text}</li>)}</ul> : null}
        </li>)}
      </ul>
    </details> : null}
  </section>;
}
