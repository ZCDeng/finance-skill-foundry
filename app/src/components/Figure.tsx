import { accountingFigure } from '../lib/figures.js';

/**
 * One figure as a result table or KPI card shows it: IBM Plex Mono, a bare negative in accounting parentheses and
 * every negative in the muted negative red. `hang` holds a bare figure one place in from the right edge, level with
 * the digits of a parenthesized negative in the same column. Text that is not a figure shows as it is. `exact` keeps a
 * value written exactly as it will be stored (a write-back cell): its sign stays, only the face and colour change.
 */
export function Figure({ text, hang = false, exact = false }: { text: string; hang?: boolean; exact?: boolean }) {
  const shown = exact ? { ...accountingFigure(text), text, bare: false } : accountingFigure(text);
  const classes = ['fnd-figure'];
  if (shown.negative) classes.push('fnd-figure--negative');
  if (hang && shown.bare) classes.push('fnd-figure--hang');
  return <span className={classes.join(' ')}>{shown.text}</span>;
}
