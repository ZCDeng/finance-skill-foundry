/**
 * The one way the interface writes an accounting period (DESIGN.md 结果区).
 *
 * `2026-08` reads 2026 年 8 月, `2026` reads 2026 年, `2026-01:2026-08` reads
 * 2026 年 1–8 月, and a range across years names both years. Anything else
 * (YTD, 1_8月, a full date, a range that runs backwards, month 13) is shown
 * exactly as stored. Display only: storage, export, filters and the text handed
 * to the assistant keep the stored value.
 */
const MONTH = /^(\d{4})-(\d{2})$/;
const YEAR = /^(\d{4})$/;
const RANGE = /^(\d{4})-(\d{2}):(\d{4})-(\d{2})$/;

function validMonth(month: string): boolean {
  const value = Number(month);
  return value >= 1 && value <= 12;
}

export function formatPeriod(value: unknown): string {
  if (value == null || value === '') return '';
  const text = typeof value === 'object' ? JSON.stringify(value) : String(value);
  const year = YEAR.exec(text);
  if (year) return `${year[1]} 年`;
  const month = MONTH.exec(text);
  if (month) return validMonth(month[2]) ? `${month[1]} 年 ${Number(month[2])} 月` : text;
  const range = RANGE.exec(text);
  if (!range) return text;
  const [, startYear, startMonth, endYear, endMonth] = range;
  if (!validMonth(startMonth) || !validMonth(endMonth)) return text;
  const start = Number(startYear) * 12 + Number(startMonth);
  const end = Number(endYear) * 12 + Number(endMonth);
  if (start > end) return text;
  if (start === end) return `${endYear} 年 ${Number(endMonth)} 月`;
  if (startYear === endYear) return `${startYear} 年 ${Number(startMonth)}–${Number(endMonth)} 月`;
  return `${startYear} 年 ${Number(startMonth)} 月–${endYear} 年 ${Number(endMonth)} 月`;
}
