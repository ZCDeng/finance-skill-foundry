/**
 * Text as a search compares it: no whitespace, the en dash of a worded period read as a
 * hyphen, lower case. So 2026年8月, 2026 年 8 月 and 1-8月 all find 2026 年 1–8 月.
 */
export const searchKey = (text: string): string => text.replace(/\s+/g, '').replace(/–/g, '-').toLocaleLowerCase();
