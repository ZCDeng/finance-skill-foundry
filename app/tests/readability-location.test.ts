// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { findReadingParagraph, paragraphLocation } from '../src/views/analysis/readabilityLocation.js';
import { renderReportHtml, documentFromMarkdown } from '../electron/reports/format.js';

// Positions are code-point offsets, as Python reports them.
const at = (body: string, text: string) => Array.from(body.slice(0, body.indexOf(text))).length;

const body = [
  '账套：华宸物业；组织：华东区域；期间：2026-01:2026-08',
  '',
  '# 经营分析',
  '',
  '开篇段落说明本期总体情况。',
  '',
  '## 一、结论',
  '',
  '表题：表 1-1 收入；单位：万元',
  '',
  '| 区域 | 收入 |',
  '| --- | --- |',
  '| 华东 | 1,000.00 |',
  '',
  '- 列表一项',
  '- 列表二项',
  '',
  '> 引文按段落显示',
  '',
  '第一段结论：收入增长主要来自华东区域。',
  '',
  '**第二段**：成本控制良好，利润率提升。',
  '',
  '[^1]: 来源附注。',
  '',
  '## 二、𠀀驱动',
  '',
  '𠀀字开头的段落也要按码点对齐。',
].join('\n');

describe('paragraph location', () => {
  it('counts rendered paragraphs within each chapter, skipping metadata, tables, lists and notes', () => {
    expect(paragraphLocation(body, at(body, '开篇段落'))).toEqual({ section: '经营分析', ordinal: 1, excerpt: '开篇段落说明本期总体情况。' });
    // The quote line renders as a paragraph in this reading view, so it is counted.
    expect(paragraphLocation(body, at(body, '> 引文'))).toMatchObject({ section: '一、结论', ordinal: 1 });
    expect(paragraphLocation(body, at(body, '第一段结论'))).toMatchObject({ section: '一、结论', ordinal: 2 });
    expect(paragraphLocation(body, at(body, '**第二段**'))).toEqual({ section: '一、结论', ordinal: 3, excerpt: '第二段：成本控制良好，利润率提升。' });
    expect(paragraphLocation(body, at(body, '表题：'))).toBeUndefined();
    expect(paragraphLocation(body, at(body, '账套：'))).toBeUndefined();
    expect(paragraphLocation(body, at(body, '- 列表一项'))).toBeUndefined();
  });

  it('aligns positions after a supplementary-plane character', () => {
    expect(paragraphLocation(body, at(body, '𠀀字开头'))).toMatchObject({ section: '二、𠀀驱动', ordinal: 1 });
    expect(paragraphLocation(body, at(body, '𠀀字开头') + 1)).toMatchObject({ section: '二、𠀀驱动', ordinal: 1 });
  });

  it('returns undefined outside the body and shortens long excerpts', () => {
    expect(paragraphLocation(body, Array.from(body).length + 5)).toBeUndefined();
    expect(paragraphLocation(body, -1)).toBeUndefined();
    const long = '很长的一段'.repeat(10);
    expect(paragraphLocation(long, 0)?.excerpt).toBe(`${Array.from(long).slice(0, 20).join('')}…`);
  });
});

describe('finding the paragraph in the reading view', () => {
  const container = (markdown: string) => {
    const element = document.createElement('div');
    const html = renderReportHtml(documentFromMarkdown(markdown), '经营分析');
    element.innerHTML = html.match(/<article class="report-body">([\s\S]*?)<\/article>/)?.[1] ?? '';
    return element;
  };

  it('finds paragraphs that begin the same way in order, and one that opens in bold', () => {
    const markdown = ['## 一、结论', '', '收入增长主要来自华东区域的新项目。', '', '收入增长主要来自华东区域的老项目。', '', '**成本**控制良好。'].join('\n');
    const view = container(markdown);
    expect(findReadingParagraph(view, markdown, at(markdown, '收入增长主要来自华东区域的老'))?.textContent).toContain('老项目');
    expect(findReadingParagraph(view, markdown, at(markdown, '收入增长主要来自华东区域的新'))?.textContent).toContain('新项目');
    expect(findReadingParagraph(view, markdown, at(markdown, '**成本**'))?.textContent).toBe('成本控制良好。');
  });

  it('returns null for a paragraph that reads as metadata on its own, without throwing', () => {
    const markdown = ['开头一段。', '', '期间：2026-08；单位：万元'].join('\n');
    expect(findReadingParagraph(container(markdown), markdown, at(markdown, '期间：'))).toBeNull();
    expect(findReadingParagraph(container(markdown), markdown, 999)).toBeNull();
  });
});
