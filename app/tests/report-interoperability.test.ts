import { describe, expect, it } from 'vitest';
import {
  documentFromMarkdown,
  documentToMarkdown,
  importReport,
  renderReportHtml,
} from '../electron/reports/converters.js';
import type { ReportDocument, ReportNode, ReportSource } from '../electron/reports/model.js';

const source: ReportSource = {
  id: '1234567890abcdef1234567890abcdef',
  name: '华宸物业_验收.xlsx',
  sha256: 'a'.repeat(64),
  format: 'xlsx',
};
const expectedAmounts = ['3,256,440,000', '129,753,049', '527,999.9999', '7,201.91', '120,120.0120', '912,345.6789'];
const requiredMarkers = ['BODYFONT-MARKER-001', 'LT-ROW-001', 'LT-ROW-060', 'LT-ROW-120', 'WD-MERGE-001', 'WD-COL-12', 'NOTE-SEMANTIC-001', 'IMG-ALT-001', 'SRC-LINK-001', 'PDF-END-MARKER-001'];

describe('report interoperability acceptance fixtures', () => {
  it('keeps real management-report amounts stable when rich fixtures are appended', () => {
    const document = propertyDocument();
    const markdown = documentToMarkdown(document);

    expect(markdown).toContain('华宸物业2026年8月月结与预算执行分析');
    expect(markdown).toContain('账套：未声明；组织：未声明；企业：华宸物业；期间：2026-08；币种：CNY；单位：元/万元');
    expect(markdown).toContain('表题：长表跨页压力测试；期间：2026-08；单位：元/万元');
    for (const amount of expectedAmounts) expect(markdown).toContain(amount);
    for (const marker of requiredMarkers) expect(markdown).toContain(marker);
    expect(markdown).toContain('长表跨页压力测试');
    expect(markdown).toContain('宽表分段压力测试');
  });

  it('round-trips HTML without trusting executable imports and preserves table, notes and source text', async () => {
    const html = renderReportHtml(propertyDocument(), '华宸物业经营分析报告', { print: true });
    const imported = await importReport(Buffer.from(html, 'utf8'), 'html', { ...source, format: 'html', name: 'report.html' });
    const markdown = documentToMarkdown(imported.document!);
    const structure = summarizeDocument(imported.document!);

    expect(html).toContain('@page{size:A4;margin:20mm}');
    expect(html).toContain('max-width:42em');
    expect(html).toContain('border-top:1px solid');
    for (const amount of expectedAmounts) expect(markdown).toContain(amount);
    for (const marker of requiredMarkers) expect(markdown.replace(/\s+/g, '')).toContain(marker);
    expect(structure.tables).toBeGreaterThanOrEqual(2);
    expect(structure.notes).toBeGreaterThanOrEqual(1);
    expect(structure.images).toBeGreaterThanOrEqual(1);
    expect(JSON.stringify(imported.document)).toContain('"source_id":"1234567890abcdef1234567890abcdef"');
    expect(JSON.stringify(imported.document)).not.toContain('javascript:');
  });

  it('makes Markdown degradation visible while retaining exact text and notes', () => {
    const markdown = documentToMarkdown(propertyDocument());
    const degraded = documentFromMarkdown(markdown);
    const projected = documentToMarkdown(degraded);

    expect(projected).toContain('账套：未声明；组织：未声明；企业：华宸物业；期间：2026-08；币种：CNY；单位：元/万元');
    expect(projected).toContain('表题：长表跨页压力测试；期间：2026-08；单位：元/万元');
    expect(projected).toContain('| 序号 | 指标 | 本期金额 | 累计金额 | 说明 |');
    expect(projected).toContain('| LT-ROW-120 | 跨页收入项目 120 | 120,120.0120 | 12000,500.00 | PDF-END-MARKER-001 |');
    expect(projected).toContain('| 项目 | 预算 | 本期 | 累计 | 达成率 | 华东 | 华南 | 华北 | 华中 | 西部 | 租户 | WD-COL-12 |');
    expect(projected).toContain('[^1]: NOTE-SEMANTIC-001 附注统一放在章节末，导出时不依赖页底脚注位置。');
  });
});

function propertyDocument(): ReportDocument {
  const document = documentFromMarkdown([
    '# 华宸物业2026年8月月结与预算执行分析',
    '',
    '## 一、月结核对（1—8月累计，期末2026-08-31）',
    '',
    '累计收入 3,256,440,000 元＝325,644 万元；归母净利 129,753,049 元＝12,975.30 万元。',
    '',
    '## 二、BUD→LE：归母净利下修 7,201.91 万元（-26.5%）',
    '',
    'BUD（年初批复）：收入527,999.9999万元、归母27,201.9089万元。',
  ].join('\n'));
  document.metadata = { company: '华宸物业', period: '2026-08', currency: 'CNY', unit: '元/万元' };
  document.sources = [source];
  document.content.push(...stressNodes(source.id));
  return document;
}

function stressNodes(sourceId: string): ReportNode[] {
  const longRows = [
    ['序号', '指标', '本期金额', '累计金额', '说明'].map((text) => cell('tableHeader', text, sourceId)),
    ...Array.from({ length: 120 }, (_, index) => {
      const row = index + 1;
      const marker = `LT-ROW-${String(row).padStart(3, '0')}`;
      return [
        cell('tableCell', marker, sourceId),
        cell('tableCell', `跨页收入项目 ${row}`, sourceId),
        cell('tableCell', row === 120 ? '120,120.0120' : `${row},000.000${row % 10}`, sourceId),
        cell('tableCell', row === 60 ? '912,345.6789' : `${row * 100},500.00`, sourceId),
        cell('tableCell', row === 1 ? 'BODYFONT-MARKER-001' : row === 120 ? 'PDF-END-MARKER-001' : '保留原始精度', sourceId),
      ];
    }),
  ];
  const wideRows = [
    ['项目', '预算', '本期', '累计', '达成率', '华东', '华南', '华北', '华中', '西部', '租户', 'WD-COL-12'].map((text) => cell('tableHeader', text, sourceId)),
    [
      cell('tableCell', 'WD-MERGE-001 合并单元格', sourceId, { colspan: 2 }),
      cell('tableCell', '1,234.5600', sourceId),
      cell('tableCell', '-98.7600', sourceId),
      cell('tableCell', '', sourceId),
      cell('tableCell', '45.00%', sourceId),
      cell('tableCell', '7,201.91', sourceId),
      cell('tableCell', '129,753,049', sourceId),
      cell('tableCell', '174,319,387', sourceId),
      cell('tableCell', '3,256,440,000', sourceId),
      cell('tableCell', '527,999.9999', sourceId),
    ],
    ['现金流压力', '预算', '174,319,387', '3,256,440,000', '527,999.9999', '15.00亿元', '2.2125亿元', '12.7875亿元', '18.60亿元', '-84,005,613', 'SRC-LINK-001', 'WD-COL-12']
      .map((text) => cell('tableCell', text, sourceId)),
  ];
  return [
    { type: 'heading', attrs: { level: 1, source_id: sourceId }, content: [{ type: 'text', text: '验收附录：长表跨页压力测试' }] },
    { type: 'paragraph', attrs: { source_id: sourceId }, content: [{ type: 'text', text: 'BODYFONT-MARKER-001 这一段用于核验正式 PDF 正文不低于 11pt 且不被双重边距挤窄。' }] },
    {
      type: 'table',
      attrs: { source_id: sourceId, sheet: '验收', range: 'A1:E121', caption: '长表跨页压力测试', period: '2026-08', unit: '元/万元' },
      content: longRows.map((content) => ({ type: 'tableRow', attrs: { source_id: sourceId }, content })),
    },
    { type: 'heading', attrs: { level: 1, source_id: sourceId }, content: [{ type: 'text', text: '验收附录：宽表分段压力测试' }] },
    {
      type: 'table',
      attrs: { source_id: sourceId, sheet: '验收', range: 'A1:L3', caption: '宽表分段压力测试', period: '2026-08', unit: '元/万元' },
      content: wideRows.map((content) => ({ type: 'tableRow', attrs: { source_id: sourceId }, content })),
    },
    { type: 'image', attrs: { source_id: sourceId, src: 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/lOjG0wAAAABJRU5ErkJggg==', alt: 'IMG-ALT-001 验收图片', title: '本地嵌入图片' } },
    { type: 'paragraph', attrs: { source_id: sourceId }, content: [{ type: 'text', text: 'IMG-ALT-001 图片说明：本地嵌入图片应随文稿导出，文字说明不能丢失。' }] },
    {
      type: 'paragraph',
      attrs: { source_id: sourceId },
      content: [
        { type: 'text', text: 'SRC-LINK-001 来源链接', marks: [{ type: 'link', attrs: { href: 'https://example.com/local-evidence' } }] },
        { type: 'text', text: ' [1]' },
      ],
    },
    { type: 'reportNote', attrs: { id: '1', source_id: sourceId }, content: [{ type: 'paragraph', content: [{ type: 'text', text: 'NOTE-SEMANTIC-001 附注统一放在章节末，导出时不依赖页底脚注位置。' }] }] },
  ];
}

function cell(type: 'tableHeader' | 'tableCell', text: string, sourceId: string, attrs: Record<string, unknown> = {}): ReportNode {
  return {
    type,
    attrs: { source_id: sourceId, textAlign: numericLike(text) ? 'right' : 'left', ...attrs },
    content: [{ type: 'paragraph', content: [{ type: 'text', text }] }],
  };
}

function numericLike(text: string): boolean {
  return /^[(（]?-?(?:¥|￥|\$)?\s*\d[\d,]*(?:\.\d+)?%?[)）]?/.test(text);
}

function summarizeDocument(document: ReportDocument) {
  const counts = { tables: 0, notes: 0, images: 0 };
  walk(document.content, (node) => {
    if (node.type === 'table') counts.tables += 1;
    if (node.type === 'reportNote') counts.notes += 1;
    if (node.type === 'image') counts.images += 1;
  });
  return counts;
}

function walk(nodes: ReportNode[], visit: (node: ReportNode) => void): void {
  for (const node of nodes) {
    visit(node);
    if (node.content) walk(node.content, visit);
  }
}
