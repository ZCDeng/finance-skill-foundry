import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowRight, BookOpen, CircleHelp, MessageSquare, Search, X } from 'lucide-react';
import { Button } from '../../components/ui/button.js';
import { Input } from '../../components/ui/input.js';
import { NativeSelect, NativeSelectOption } from '../../components/ui/native-select.js';
import { GUIDE_ARTICLES, GUIDE_SECTIONS, searchArticles, type GuideArticle, type GuideTarget } from './articles.js';
import { QuickStartChecklist } from './QuickStartChecklist.js';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '../../components/ui/alert-dialog.js';
import { askAssistant, askText, type AskId } from './ask.js';

/** Window event that opens the guide at one article, from a 「?」 next to the thing it explains. */
export const GUIDE_EVENT = 'fnd:guide';

export function openGuide(article?: string) {
  window.dispatchEvent(new CustomEvent(GUIDE_EVENT, { detail: article ?? '' }));
}

/** A small 「?」 that opens the article explaining the block beside it. */
export function HelpLink({ article, label }: { article: string; label: string }) {
  return <Button variant="ghost" size="icon" type="button" className="fnd-help-link size-[22px]" aria-label={`使用指南：${label}`} title={`使用指南：${label}`}
    onClick={() => openGuide(article)}><CircleHelp size={14} strokeWidth={1.5} aria-hidden /></Button>;
}

/**
 * A 「让助手…」 button: puts the question into the conversation for the manager to edit and send.
 * The question is its title, so what lands in the composer is readable before pressing.
 */
export function AskLink({ ask, label, about, disabled }: { ask: AskId; label: string; about?: string; disabled?: boolean }) {
  return <Button variant="link" size="sm" type="button" className="fnd-ask-link" disabled={disabled} title={askText(ask, about)}
    onClick={() => askAssistant(ask, about)}><MessageSquare size={14} strokeWidth={1.5} aria-hidden />{label}</Button>;
}

/** The four quality words the 文稿质量检查 panel shows, drawn so no step reads as implying the next. */
export function StatusLegend() {
  const steps = ['计算成功', '引用值一致', '源数据核验通过', '已专业复核'];
  return <p className="fnd-guide-legend">
    {steps.map((step, index) => <span key={step}>{index ? <span className="fnd-guide-legend__ne"><span aria-hidden>≠</span><span className="sr-only">不等于</span></span> : null}<span>{step}</span></span>)}
  </p>;
}

/**
 * 使用指南 in one column: the contents as a drop-down at the top, grouped by section, then a search, then the
 * article, which is the column's only scroll area. Search hits list above the article.
 *
 * It sits where the conversation sits, so the workspace it explains stays visible beside
 * it. Opening a place from an article moves the workspace there and never runs anything.
 */
export function GuideHub({ article: requested, request = 0, canOpen = true, taskId, onOpen, onClose, onSample, onOwnData, samples, onRemoveSamples, onReplaceSamples }: {
  article?: string;
  /** Bumped on every request, so asking for the article already shown still moves back to it. */
  request?: number;
  /** False with no task open, or a task that can only be read: the workspace has nowhere to go. */
  canOpen?: boolean;
  /** The open task, whose own state the quick-start checklist reads. */
  taskId?: string;
  onOpen(target: GuideTarget): void; onClose(): void;
  /** Open (or create, once) the synthetic practice task. Absent where this build cannot. */
  onSample?(): Promise<void>;
  /** Start with the reader's own files: close the guide and go to the new-task box. */
  onOwnData?(): void;
  /** The example tasks on the 进行中 list; absent while another list is shown. */
  samples?: { count: number; outdated: boolean };
  /** Every example task to the trash; answers how many went. */
  onRemoveSamples?(): Promise<number>;
  /** The old examples to the trash and the current pack's opened in their place. */
  onReplaceSamples?(): Promise<void>;
}) {
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState('');
  const [confirm, setConfirm] = useState<'remove' | 'replace' | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const [confirmError, setConfirmError] = useState('');
  const [removed, setRemoved] = useState('');
  const confirmed = async () => {
    if (!confirm || confirmBusy) return;
    setConfirmBusy(true); setConfirmError('');
    try {
      if (confirm === 'remove') {
        const count = await onRemoveSamples?.() ?? 0;
        setRemoved(count ? `已把 ${count} 个示例任务移入回收站，在回收站里还能恢复。` : '没有需要移除的示例任务。');
      } else {
        await onReplaceSamples?.();
        setRemoved('');
      }
      setConfirm(null);
    } catch (failure) {
      setConfirmError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setConfirmBusy(false);
    }
  };
  const [query, setQuery] = useState('');
  // What the drop-down just put up, said through the status line since focus stays on the drop-down.
  const [shown, setShown] = useState('');
  const [current, setCurrent] = useState(() => GUIDE_ARTICLES.find((row) => row.id === requested)?.id ?? GUIDE_ARTICLES[0].id);
  const heading = useRef<HTMLHeadingElement>(null);
  const body = useRef<HTMLDivElement>(null);
  useEffect(() => { if (requested && GUIDE_ARTICLES.some((row) => row.id === requested)) setCurrent(requested); }, [requested, request]);
  // Opening the guide moves focus into it, so a keyboard or screen-reader user knows the column changed.
  useEffect(() => { heading.current?.focus(); }, [requested, request]);
  const found = useMemo(() => searchArticles(query), [query]);
  const article = GUIDE_ARTICLES.find((row) => row.id === current) ?? GUIDE_ARTICLES[0];
  const pick = (id: string) => { setCurrent(id); requestAnimationFrame(() => heading.current?.focus()); };
  // Focus stays on the drop-down, so arrow keys can keep changing it (Windows changes the value per key press).
  // Escape while the platform's own list is open is meant to close only the list; not yet checked on a machine.
  const choose = (id: string) => {
    setCurrent(id);
    setShown(`已显示「${GUIDE_ARTICLES.find((row) => row.id === id)?.title ?? ''}」`);
    if (body.current) body.current.scrollTop = 0;
  };
  return (
    <div className="fnd-guide-hub" role="region" aria-label="使用指南"
      onKeyDown={(event) => { if (event.key === 'Escape') { event.preventDefault(); onClose(); } }}>
      <div className="fnd-guide-hub__head">
        <h2><BookOpen size={16} strokeWidth={1.5} aria-hidden /> 使用指南</h2>
        <Button variant="ghost" size="icon" type="button" aria-label="关闭使用指南" onClick={onClose}><X size={16} strokeWidth={1.5} aria-hidden /></Button>
      </div>
      <NativeSelect aria-label="指南目录" value={current} onChange={(event) => choose(event.target.value)}>
        {GUIDE_SECTIONS.map((section) => {
          const rows = GUIDE_ARTICLES.filter((row) => row.section === section);
          return rows.length ? <optgroup key={section} label={section}>
            {rows.map((row) => <NativeSelectOption key={row.id} value={row.id}>{row.title}</NativeSelectOption>)}
          </optgroup> : null;
        })}
      </NativeSelect>
      <label className="fnd-guide-hub__search">
        <Search size={14} strokeWidth={1.5} aria-hidden />
        <Input aria-label="搜索使用指南" placeholder="搜索，例如：收缴率、期间、损坏 Excel、未阅" value={query} onChange={(event) => { setQuery(event.target.value); setShown(''); }} />
      </label>
      <div className="fnd-guide-hub__body" ref={body}>
        {/* Present from the start so a change is announced, not inserted with its words. */}
        <span className="sr-only" role="status">{query.trim() ? found.length ? `找到 ${found.length} 篇` : `没有找到「${query.trim()}」相关的说明。` : shown}</span>
        {query.trim() ? <nav aria-label="搜索结果" className="fnd-guide-hub__results">
          {found.length ? <ul>{found.map((row) => <GuideHit key={row.id} row={row} current={current} onPick={pick} />)}</ul>
            : <p className="analysis-note">没有找到「{query.trim()}」相关的说明。</p>}
        </nav> : null}
        <article className="fnd-guide-hub__article" aria-labelledby="fnd-guide-article-title">
          <h3 id="fnd-guide-article-title" ref={heading} tabIndex={-1}>{article.title}</h3>
          <p className="analysis-note">适用于：{article.appliesTo}</p>
          {article.body.map((block, index) => {
            if (block.kind === 'p') return <p key={index}>{block.text}</p>;
            if (block.kind === 'steps') return <ol key={index}>{block.items.map((item) => <li key={item}>{item}</li>)}</ol>;
            if (block.kind === 'list') return <ul key={index}>{block.items.map((item) => <li key={item}>{item}</li>)}</ul>;
            if (block.kind === 'legend') return <StatusLegend key={index} />;
            if (block.kind === 'checklist') return <QuickStartChecklist key={index} taskId={taskId} canOpen={canOpen} onOpen={onOpen} />;
            if (block.kind === 'start') return <div key={index} className="fnd-guide-hub__start">
              {onSample ? <Button type="button" disabled={starting} onClick={() => {
                setStarting(true); setStartError('');
                void onSample().catch((failure: unknown) => setStartError(failure instanceof Error ? failure.message : String(failure))).finally(() => setStarting(false));
              }}>{starting ? '正在准备示例任务…' : '用示例任务练习（推荐）'}</Button> : null}
              <Button variant="outline" type="button" onClick={() => onOwnData?.()}>使用自己的资料</Button>
              {startError ? <p role="alert" className="analysis-message analysis-message--error">{startError}</p> : null}
              {samples?.outdated && onReplaceSamples ? <p className="fnd-guide-hub__samples">
                <span>示例资料有新版本。</span>
                <Button variant="link" size="sm" type="button" onClick={() => { setConfirmError(''); setConfirm('replace'); }}>换成新版示例</Button>
              </p> : null}
              {samples && samples.count > 0 && onRemoveSamples ? <p className="fnd-guide-hub__samples">
                <span>练完了？示例任务可以一起移走，你自己的任务不受影响。</span>
                <Button variant="link" size="sm" type="button" onClick={() => { setConfirmError(''); setConfirm('remove'); }}>移除示例任务</Button>
              </p> : null}
              {removed ? <p role="status" className="analysis-note">{removed}</p> : null}
            </div>;
            if (block.kind === 'ask') return <span key={index} className="fnd-guide-hub__open">
              <AskLink ask={block.ask} label={block.label} disabled={!canOpen} />
              {/* Said once, after the last of a run of these buttons. */}
              {article.body[index + 1]?.kind === 'ask' ? null
                : <span className="analysis-note">{canOpen ? '只填进对话框，改好再发送。' : '先打开一个可编辑的任务，才能问助手。'}</span>}
            </span>;
            return <span key={index} className="fnd-guide-hub__open">
              <Button variant="outline" type="button" disabled={!canOpen} onClick={() => onOpen(block.target)}>
                {block.label}<ArrowRight size={14} strokeWidth={1.5} aria-hidden /></Button>
              {canOpen ? null : <span className="analysis-note">先打开一个可编辑的任务，才能跳到这里。</span>}
            </span>;
          })}
        </article>
      </div>
      <AlertDialog open={Boolean(confirm)} onOpenChange={(open) => { if (!open && !confirmBusy) setConfirm(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{confirm === 'replace' ? '换成新版示例？' : `把 ${samples?.count ?? 0} 个示例任务移入回收站？`}</AlertDialogTitle>
            <AlertDialogDescription>{confirm === 'replace'
              ? `现有的 ${samples?.count ?? 0} 个示例任务会移入回收站，再用新版资料建练习任务，参考结果在后台重新生成。你自己的任务不受影响。`
              : '只移动示例任务，你自己的任务不受影响。在回收站里还能恢复，之后也可以随时再建示例任务。'}</AlertDialogDescription>
          </AlertDialogHeader>
          {confirmError ? <p role="alert" className="m-0 text-[length:var(--fnd-size-body)] text-[var(--fnd-warning)]">{confirmError}</p> : null}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={confirmBusy}>取消</AlertDialogCancel>
            <AlertDialogAction disabled={confirmBusy} aria-busy={confirmBusy || undefined}
              onClick={(event) => { event.preventDefault(); void confirmed(); }}>
              {confirm === 'replace' ? '换成新版示例' : '移入回收站'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

function GuideHit({ row, current, onPick }: { row: GuideArticle; current: string; onPick(id: string): void }) {
  return <li><button type="button" className="fnd-guide-hub__hit" aria-current={row.id === current ? 'page' : undefined} onClick={() => onPick(row.id)}>{row.title}</button></li>;
}
