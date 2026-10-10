import { useState } from 'react';
import { Copy, MessageSquare } from 'lucide-react';
import { Figure } from '../../components/Figure.js';
import { Button } from '../../components/ui/button.js';
import { Popover, PopoverContent, PopoverTrigger } from '../../components/ui/popover.js';
import { DisclosureSummary } from '../../components/Disclosure.js';
import { askWith } from '../guide/ask.js';
import { askAboutFigure, sourceText, type FigureSourceInfo } from './figureSource.js';
import { PinButton } from './PinButton.js';
import type { CardDraft } from './dashboard.js';
import './FigureSource.css';

/**
 * A figure a manager can open to see where it came from. A figure without a value (—) stays plain text: there is
 * nothing to trace. The card only reads; 问助手解释 fills the conversation and sends nothing.
 */
export function FigureSource({ text, info, hang = false, exact = false, pin }: {
  text: string; info?: FigureSourceInfo; hang?: boolean; exact?: boolean;
  /** The card 钉到看板 puts on the task's board; without one the source card offers no pin. */
  pin?: CardDraft | null;
}) {
  const [copied, setCopied] = useState(false);
  if (!info || text.trim() === '' || text === '—') return <Figure text={text} hang={hang} exact={exact} />;
  const copy = () => {
    void navigator.clipboard?.writeText(sourceText(info)).then(() => setCopied(true), () => setCopied(false));
  };
  return <Popover onOpenChange={(open) => { if (!open) setCopied(false); }}>
    <PopoverTrigger asChild>
      <button type="button" className="fnd-figure-source" data-stale={info.stale || undefined}
        aria-label={`${info.metric}${info.part} ${info.value}${info.stale ? '（资料已更新，待重算）' : ''}，查看来源`}>
        <Figure text={text} hang={hang} exact={exact} />
      </button>
    </PopoverTrigger>
    <PopoverContent className="fnd-source-card" aria-label={`${info.metric}${info.part}的来源`}>
      <header className="fnd-source-card__head">
        <p className="fnd-source-card__title">{info.metric} · {info.part}</p>
        <p className="fnd-source-card__value"><Figure text={info.value} exact={exact} /></p>
      </header>
      {info.stale && <p className="fnd-source-card__stale" role="note">资料已更新，这个数按旧版本算出，重新计算后才算数。</p>}
      {info.facts.length > 0 && <dl className="fnd-source-card__list">
        {info.facts.map(([label, text]) => <div key={label}><dt>{label}</dt><dd>{text}</dd></div>)}
      </dl>}
      {info.sources.length > 0 && <section aria-label="取数与口径">
        <h4 className="fnd-source-card__heading">取数与口径</h4>
        <dl className="fnd-source-card__list">
          {info.sources.map(([label, text], index) => <div key={`${label}:${index}`}><dt>{label}</dt><dd>{text}</dd></div>)}
        </dl>
      </section>}
      {info.files.length > 0 && <section aria-label="读取的资料">
        <h4 className="fnd-source-card__heading">读取的资料</h4>
        <ul className="fnd-source-card__files">
          {info.files.map((file, index) => <li key={`${file.name}:${index}`}>
            <span>{file.name}</span>
            {file.digest ? <span className="fnd-source-card__digest" title="资料摘要前 12 位">{file.digest}</span> : null}
            {file.replaced ? <span className="fnd-source-card__replaced">已被新版本取代</span> : null}
          </li>)}
        </ul>
      </section>}
      <p className="fnd-source-card__computed">{info.computed}</p>
      {info.method && <details className="analysis-details fnd-source-card__method">
        <DisclosureSummary tone="quiet">{info.method.label}</DisclosureSummary>
        <pre>{info.method.text}</pre>
      </details>}
      <div className="fnd-source-card__actions">
        <Button type="button" variant="outline" size="sm" onClick={copy}><Copy size={14} strokeWidth={1.5} aria-hidden />{copied ? '已复制' : '复制来源'}</Button>
        <Button type="button" variant="outline" size="sm" onClick={() => askWith(askAboutFigure(info))}><MessageSquare size={14} strokeWidth={1.5} aria-hidden />问助手解释</Button>
        <PinButton draft={pin} />
      </div>
      <p className="fnd-source-card__note">问助手只填进对话框，改好再发送。</p>
    </PopoverContent>
  </Popover>;
}
