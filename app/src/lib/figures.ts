/**
 * How a financial figure is written on screen (DESIGN.md 字体 / 财务数字): grouped thousands, a fixed number of places,
 * and on result tables and KPI cards a negative in accounting parentheses with a muted dark red. Stored values, text
 * given to the assistant, drafts and exports keep their own minus sign: only what a cell shows changes.
 */

function decimalParts(value: unknown): { negative: boolean; digits: string; scale: number } | null {
  if (value == null || value === '') return null;
  const text = String(value).trim().replace(/,/g, '');
  const match = /^([+-])?(\d+)(?:\.(\d+))?$/.exec(text);
  if (!match) return null;
  const [, sign, integer, fraction = ''] = match;
  const digits = `${integer}${fraction}`.replace(/^0+(?=\d)/, '') || '0';
  return { negative: sign === '-', digits, scale: fraction.length };
}

/** A decimal at a fixed number of places, rounded half away from zero in exact arithmetic, thousands grouped. */
export function decimalToFixed(value: unknown, places: number, multiplier = 1): string {
  const parsed = decimalParts(value);
  if (!parsed) return value == null || value === '' ? '—' : String(value);
  const targetScale = places;
  const current = BigInt(parsed.digits) * BigInt(multiplier);
  const scaleDiff = parsed.scale - targetScale;
  let rounded: bigint;
  if (scaleDiff > 0) {
    const divisor = 10n ** BigInt(scaleDiff);
    rounded = current / divisor;
    if (current % divisor >= divisor / 2n) rounded += 1n;
  } else {
    rounded = current * (10n ** BigInt(-scaleDiff));
  }
  const sign = parsed.negative && rounded !== 0n ? '-' : '';
  const raw = rounded.toString().padStart(places + 1, '0');
  const integer = places ? raw.slice(0, -places) : raw;
  const fraction = places ? raw.slice(-places) : '';
  return `${sign}${integer.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}${places ? `.${fraction}` : ''}`;
}

/** An amount as every result surface writes it: two places, thousands grouped. Text that is not a number stays. */
export function formatAmount(value: unknown): string {
  return decimalToFixed(value, 2);
}

/**
 * A decimal with its thousands grouped and every place it was written with: a tie-out difference of 0.0004 must not
 * read as 0.00 beside 不相符. Text that is not a plain decimal stays as it is; a missing value reads as a dash.
 */
export function groupDigits(value: unknown): string {
  if (value == null || value === '') return '—';
  const text = String(value).trim();
  const match = /^([+-]?)(\d+)(\.\d+)?$/.exec(text);
  if (!match) return text;
  return `${match[1]}${match[2].replace(/\B(?=(\d{3})+(?!\d))/g, ',')}${match[3] ?? ''}`;
}

/**
 * Text that reads as one figure: an optional sign or accounting parentheses, an optional currency mark, grouped or
 * plain digits, an optional %, then at most one unit word and one short bracketed note (325,644.00 万元（估算）).
 */
const FIGURE = /^[(（]?[-+−]?(?:¥|￥|\$)?\s*\d[\d,]*(?:\.\d+)?%?[)）]?(?:\s*(?:个百分点|百万元|万元|亿元|千元|元|天|倍|%))?(?:\s*[（(][^（）()]{1,8}[)）])?$/;
/** A figure with nothing after it: the only kind written in parentheses when negative. */
const PURE_NEGATIVE = /^[-−]((?:¥|￥|\$)?\d[\d,]*(?:\.\d+)?%?)$/;
const NEGATIVE = /^(?:[-−]|[(（](?=[-−]?(?:¥|￥|\$)?\s*\d))/;

export function isFigureText(text: string): boolean {
  return FIGURE.test(text.trim());
}

/** A missing value reads as a dash and takes no side in deciding whether a column holds figures. */
export function isMissingText(text: string): boolean {
  const trimmed = text.trim();
  return trimmed === '' || trimmed === '—' || trimmed === '-' || trimmed === '缺失';
}

export type ShownFigure = {
  /** What the cell shows. */
  text: string;
  /** A value below zero, however it is written: it takes the muted negative red. */
  negative: boolean;
  /** A figure that ends in its last digit or %, so beside a parenthesized negative it holds the ) column open. */
  bare: boolean;
};

/**
 * One cell's figure in accounting form. A bare negative (-18,843.06, -3.30%) becomes (18,843.06), (3.30%); a figure
 * carrying a unit word (-0.65 个百分点, -1,234.00 万元) keeps its minus sign, since parentheses around a number with a word
 * after it read as a note. Non-figures come back as they are and are never negative.
 */
export function accountingFigure(text: string): ShownFigure {
  const trimmed = text.trim();
  if (!isFigureText(trimmed)) return { text, negative: false, bare: false };
  const pure = PURE_NEGATIVE.exec(trimmed);
  if (pure) return { text: `(${pure[1]})`, negative: true, bare: false };
  const negative = NEGATIVE.test(trimmed);
  return { text: trimmed, negative, bare: !negative && /[\d%]$/.test(trimmed) };
}

/** Whether a figure written in accounting parentheses is among these texts, so bare ones beside it hang one place in. */
export function hasParenthesizedNegative(texts: string[]): boolean {
  return texts.some((text) => accountingFigure(text).text.startsWith('('));
}
