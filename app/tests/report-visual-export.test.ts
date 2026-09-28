import JSZip from 'jszip';
import { describe, expect, it } from 'vitest';
import { documentToMarkdown, exportDocx, importReport, renderReportHtml } from '../electron/reports/converters.js';
import { createReportDocument } from '../electron/reports/format.js';
import { reportVisualEvidence } from '../electron/reports/visual-evidence.js';

const chart = {
  version: 1, kind: 'bar', title: '经营贡献比较', takeaway: '保留原始值与缺失项', unit: '万元',
  chart_id: 'a'.repeat(32), run_id: 'b'.repeat(32), snapshot_hash: 'c'.repeat(64), source_label: '核定计算',
  category: '项目', value_columns: ['金额'], series: {
    columns: [{ name: '项目', type: 'VARCHAR' }, { name: '金额', type: 'DECIMAL' }],
    rows: [{ 项目: '住宅', 金额: '123.4500' }, { 项目: '商业', 金额: '-25.0120' }, { 项目: '待核对', 金额: null }],
  },
};
const flow = {
  version: 1, kind: 'flow', title: '预算复核流程', takeaway: '复核通过后形成文稿', source_label: '作者分析',
  steps: [{ label: '核对范围', detail: '检查组织与期间', connector: '口径一致' }, { label: '形成判断', detail: '说明差异驱动', connector: '' }],
};
const document = createReportDocument([{ type: 'reportVisual', attrs: { visual: chart } }, { type: 'reportVisual', attrs: { visual: flow } }]);

describe('report visual export integration', () => {
  it('renders controlled SVG and exact source data in offline HTML', () => {
    const html = renderReportHtml(document, '经营分析');
    expect(html.match(/<svg\b/g)).toHaveLength(2);
    expect(html).toContain('report-visual-data');
    for (const value of ['123.4500', '-25.0120', '待核对', '万元', '核定计算', '口径一致']) expect(html).toContain(value);
    expect(html).toContain('break-inside:avoid');
    expect(html).not.toMatch(/<script\b|<foreignObject\b|<iframe\b/);
    expect(html).toContain(chart.snapshot_hash);
    const article = html.match(/<article[^>]*>([\s\S]*?)<\/article>/)?.[1];
    expect(article).toBeDefined();
    expect(article).not.toContain(chart.chart_id);
  });

  it('retains values, unit, source and relationships in the Markdown fallback', () => {
    const md = documentToMarkdown(document);
    for (const value of ['123.4500', '-25.0120', '万元', '核定计算', '口径一致', '作者分析']) expect(md).toContain(value);
  });

  it('imports HTML as reviewable data without trusting foreign chart bindings or SVG', async () => {
    const result = await importReport(Buffer.from(renderReportHtml(document, '经营分析')), 'html', {
      id: 'd'.repeat(32), name: '经营分析.html', format: 'html', sha256: 'e'.repeat(64),
    });
    expect(result.warnings.join(' ')).toContain('重新绑定计算');
    const value = JSON.stringify(result.document);
    expect(value).toContain('123.4500');
    expect(value).toContain('口径一致');
    expect(value).not.toContain('"type":"reportVisual"');
    expect(value).not.toContain('"chart_id":');
  });

  it('refuses to silently drop unrendered charts when called outside the desktop exporter', async () => {
    await expect(exportDocx(document, '经营分析')).rejects.toThrow('图表尚未完成导出渲染');
  });

  it('preserves image aspect ratio and caption in Word', async () => {
    const src = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=';
    const doc = createReportDocument([{ type: 'image', attrs: { src, title: '图：核定结果；来源：计算快照', alt: '核定结果比较图' } }]);
    const zip = await JSZip.loadAsync(await exportDocx(doc, '经营分析', undefined, { visualSources: reportVisualEvidence(document) }));
    const xml = await zip.file('word/document.xml')!.async('string');
    const size = xml.match(/<wp:extent cx="(\d+)" cy="(\d+)"/);
    expect(size).not.toBeNull();
    expect(size![1]).toBe(size![2]);
    expect(xml).toContain('图：核定结果；来源：计算快照');
    expect(xml).toContain('核定结果比较图');
    expect(xml).toContain('图表依据：经营贡献比较');
    expect(xml).toContain(chart.chart_id);
    expect(xml).toContain(chart.run_id);
    expect(xml).toContain(chart.snapshot_hash);
  });
});
