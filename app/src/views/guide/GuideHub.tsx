import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowRight, BookOpen, CircleHelp, Search, X } from 'lucide-react';
import { Button } from '../../components/ui/button.js';
import { Input } from '../../components/ui/input.js';
import { GUIDE_ARTICLES, GUIDE_SECTIONS, searchArticles, type GuideArticle, type GuideTarget } from './articles.js';

/** Window event that opens the guide at one article, from a 「?」 next to the thing it explains. */
export const GUIDE_EVENT = 'fnd:guide';

export function openGuide(article?: string) {
  window.dispatchEvent(new CustomEvent(GUIDE_EVENT, { detail: article ?? '' }));
}

/** A small 「?」 that opens the article explaining the block beside it. */
export function HelpLink({ article, label }: { article: string; label: string }) {
  return <Button variant="ghost" size="icon" type="button" className="fnd-help-link" aria-label={`使用指南：${label}`} title={`使用指南：${label}`}
    onClick={() => openGuide(article)}><CircleHelp size={14} strokeWidth={1.5} aria-hidden /></Button>;
}

/** 执行成功 ≠ 数值已引用 ≠ 来源已核验 ≠ 经理已复核 ≠ 可发布, drawn so no step reads as implying the next. */
export function StatusLegend() {
  const steps = ['执行成功', '数值已引用', '来源已核验', '经理已复核', '可发布'];
  return <p className="fnd-guide-legend" aria-label={steps.join('不等于')}>
    {steps.map((step, index) => <span key={step}>{index ? <span className="fnd-guide-legend__ne" aria-hidden>≠</span> : null}<span>{step}</span></span>)}
  </p>;
}

/**
 * 使用指南: topics on the left, the article on the right, a search over both.
 *
 * It sits where the conversation sits, so the workspace it explains stays visible beside
 * it. Opening a place from an article moves the workspace there and never runs anything.
 */
export function GuideHub({ article: requested, onOpen, onClose }: {
  article?: string; onOpen(target: GuideTarget): void; onClose(): void;
}) {
  const [query, setQuery] = useState('');
  const [current, setCurrent] = useState(() => GUIDE_ARTICLES.find((row) => row.id === requested)?.id ?? GUIDE_ARTICLES[0].id);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { if (requested && GUIDE_ARTICLES.some((row) => row.id === requested)) setCurrent(requested); }, [requested]);
  const found = useMemo(() => searchArticles(query), [query]);
  const article = GUIDE_ARTICLES.find((row) => row.id === current) ?? GUIDE_ARTICLES[0];
  const pick = (id: string) => { setCurrent(id); requestAnimationFrame(() => heading.current?.focus()); };
  return (
    <div className="fnd-guide-hub" role="region" aria-label="使用指南"
      onKeyDown={(event) => { if (event.key === 'Escape') { event.preventDefault(); onClose(); } }}>
      <div className="fnd-guide-hub__head">
        <h2><BookOpen size={16} strokeWidth={1.5} aria-hidden /> 使用指南</h2>
        <Button variant="ghost" size="icon" type="button" aria-label="关闭使用指南" onClick={onClose}><X size={16} strokeWidth={1.5} aria-hidden /></Button>
      </div>
      <label className="fnd-guide-hub__search">
        <Search size={14} strokeWidth={1.5} aria-hidden />
        <Input aria-label="搜索使用指南" placeholder="搜索，例如：收缴率、期间、损坏 Excel、未阅" value={query} onChange={(event) => setQuery(event.target.value)} />
      </label>
      <div className="fnd-guide-hub__body">
        <nav aria-label="指南目录" className="fnd-guide-hub__toc">
          {query.trim()
            ? found.length ? <ul>{found.map((row) => <TocItem key={row.id} row={row} current={current} onPick={pick} />)}</ul>
              : <p className="analysis-note" role="status">没有找到「{query.trim()}」相关的说明。</p>
            : GUIDE_SECTIONS.map((section) => {
              const rows = GUIDE_ARTICLES.filter((row) => row.section === section);
              return rows.length ? <div key={section}><h3>{section}</h3><ul>{rows.map((row) => <TocItem key={row.id} row={row} current={current} onPick={pick} />)}</ul></div> : null;
            })}
        </nav>
        <article className="fnd-guide-hub__article" aria-labelledby="fnd-guide-article-title">
          <h3 id="fnd-guide-article-title" ref={heading} tabIndex={-1}>{article.title}</h3>
          <p className="analysis-note">适用于：{article.appliesTo}</p>
          {article.body.map((block, index) => {
            if (block.kind === 'p') return <p key={index}>{block.text}</p>;
            if (block.kind === 'steps') return <ol key={index}>{block.items.map((item) => <li key={item}>{item}</li>)}</ol>;
            if (block.kind === 'list') return <ul key={index}>{block.items.map((item) => <li key={item}>{item}</li>)}</ul>;
            if (block.kind === 'legend') return <StatusLegend key={index} />;
            return <Button key={index} variant="outline" type="button" onClick={() => onOpen(block.target)}>
              {block.label}<ArrowRight size={14} strokeWidth={1.5} aria-hidden /></Button>;
          })}
        </article>
      </div>
    </div>
  );
}

function TocItem({ row, current, onPick }: { row: GuideArticle; current: string; onPick(id: string): void }) {
  return <li><button type="button" className="fnd-guide-hub__toc-item" aria-current={row.id === current ? 'page' : undefined} onClick={() => onPick(row.id)}>{row.title}</button></li>;
}
