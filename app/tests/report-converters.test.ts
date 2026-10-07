import JSZip from 'jszip';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { documentFromMarkdown, documentToMarkdown, exportDocx, importReport, renderReportHtml } from '../electron/reports/converters.js';
import type { ReportDocument, ReportNode, ReportSource } from '../electron/reports/model.js';

const source: ReportSource = {
  id: 'source-a',
  name: 'monthly-report.md',
  sha256: 'a'.repeat(64),
  format: 'md',
};
const png1x1 = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=';

describe('report document converters', () => {
  it('keeps financial text, notes and tables stable through Markdown projection', () => {
    const markdown = [
      '# 华宸物业月结分析',
      '',
      '收入为 **1,234,567.89** 元，空值保持为 -。',
      '',
      '| 项目 | 本期 | 上期 |',
      '| --- | --- | --- |',
      '| 经营收入 | 1,234,567.89 | -98,765.43 |',
      '| 空值 | - |  |',
      '',
      '[^1]: 金额来自总账，不四舍五入。',
    ].join('\n');

    const doc = documentFromMarkdown(markdown);
    const projected = documentToMarkdown(doc);

    expect(projected).toContain('1,234,567.89');
    expect(projected).toContain('-98,765.43');
    expect(projected).toContain('| 经营收入 | 1,234,567.89 | -98,765.43 |');
    expect(projected).toContain('[^1]: 金额来自总账，不四舍五入。');
  });

  it('preserves nested lists and escaped Markdown table delimiters', () => {
    const markdown = [
      '# 转义测试',
      '',
      '1. 一级\\*事项\\*',
      '   - 二级项目 A\\|B',
      '   - 二级项目 C',
      '2. 第二项',
      '',
      '| 项目 | 说明 |',
      '| --- | --- |',
      '| 现金\\|银行 | 保留\\*星号\\*与 1,000.00 |',
    ].join('\n');

    const doc = documentFromMarkdown(markdown);
    const projected = documentToMarkdown(doc);

    expect(projected).toContain('1. 一级\\*事项\\*');
    expect(projected).toContain('  - 二级项目 A|B');
    expect(projected).toContain('  - 二级项目 C');
    expect(projected).toContain('| 现金\\|银行 | 保留\\*星号\\*与 1,000.00 |');
    expect(documentToMarkdown(documentFromMarkdown(projected))).toBe(projected);
  });

  it('projects and imports document/table metadata using the backend Markdown contract', () => {
    const doc = documentFromMarkdown('# 管理摘要\n\n正文。');
    doc.metadata = { company: '华宸物业', period: '2026-08', currency: 'CNY', unit: '万元' };
    doc.content.push({
      type: 'table',
      attrs: { caption: '利润预算差异', period: '2026-08', currency: 'CNY', unit: '万元' },
      content: [
        { type: 'tableRow', content: [cell('tableHeader', '项目'), cell('tableHeader', '金额')] },
        { type: 'tableRow', content: [cell('tableCell', '利润'), cell('tableCell', '5.00', { textAlign: 'right' })] },
      ],
    });

    const markdown = documentToMarkdown(doc);
    const imported = documentFromMarkdown(markdown);
    const html = renderReportHtml(imported, '经营分析报告');

    expect(markdown).toContain('账套：未声明；组织：未声明；企业：华宸物业；期间：2026-08；币种：CNY；单位：万元');
    expect(markdown).toContain('表题：利润预算差异；期间：2026-08；币种：CNY；单位：万元\n\n| 项目 | 金额 |');
    expect(imported.metadata).toEqual({ ledger: '', organization: '', company: '华宸物业', period: '2026-08', currency: 'CNY', unit: '万元' });
    expect(imported.content.find((node) => node.type === 'table')?.attrs).toMatchObject({ caption: '利润预算差异', period: '2026-08', currency: 'CNY', unit: '万元' });
    expect(html).not.toContain('企业：华宸物业');
    expect(html).not.toContain('表题：利润预算差异');
  });

  it('projects merged Markdown table cells as a rectangular degradation', () => {
    const doc = documentFromMarkdown('# 合并表\n');
    doc.content.push({
      type: 'table',
      content: [
        { type: 'tableRow', content: [cell('tableHeader', '项目'), cell('tableHeader', '金额')] },
        { type: 'tableRow', content: [cell('tableCell', '合并行', { colspan: 2 })] },
      ],
    });

    expect(documentToMarkdown(doc)).toContain('| 合并行 |  |');
  });

  it('renders formal HTML with offline print layout and safe links only', () => {
    const doc = documentFromMarkdown([
      '# 管理摘要',
      '',
      '### 三级指标不进目录',
      '',
      '[官网](https://example.com) [危险链接](javascript:alert(1))',
      '',
      '| 项目 | 一月 | 二月 | 三月 | 四月 | 五月 | 六月 | 七月 |',
      '| --- | --- | --- | --- | --- | --- | --- | --- |',
      '| 应收账款 | 1,000.00 | 2,000.00 | 3,000.00 | 4,000.00 | 5,000.00 | 6,000.00 | 7,000.00 |',
    ].join('\n'));

    const html = renderReportHtml(doc, '经营分析报告', { print: true });

    expect(html).toContain('@page{size:A4;margin:20mm}');
    expect(html).toContain("default-src 'none'");
    expect(html).toContain('img-src data:');
    expect(html).toContain('font-src data:');
    expect(html).toContain('.report-shell.is-print{width:auto;min-height:0;max-width:none;margin:0;padding:0;background:#fff;box-shadow:none}');
    expect(html).toContain('max-width:42em');
    expect(html).toContain('width:210mm');
    expect(html).toContain('font-size:11pt');
    expect(html).toContain('href="https://example.com"');
    expect(html).not.toContain('javascript:alert');
    expect(html).toContain('<thead>');
    expect(html).toContain('class="num"');
    expect(html).toContain('wide-table-group');
    expect(html).toContain('续表');
    expect(html.match(/<nav[\s\S]*<\/nav>/)?.[0]).not.toContain('三级指标不进目录');
  });

  it('renders management exports with conclusions before receipt metadata and no automatic TOC', async () => {
    const doc = documentFromMarkdown('# 经营分析报告\n\n## 管理摘要\n\n管理层第一屏结论。\n\n## 经营拆解\n\n正文继续。');
    const options = { marker: '分析草稿·待复核', contentMode: 'management', projectionHash: 'd'.repeat(64), draftId: 'draft-1', contentHash: 'c'.repeat(64), publicationStatus: 'draft', reviewStatus: 'unreviewed', reproducibilityStatus: 'unverified', sources: ['report.md（md；ID source-1；SHA-256 aaaaaaaaaaaa）'] };
    const html = renderReportHtml(doc, '经营分析报告', { print: true, ...options });

    expect(html).toContain('data-report-projection-hash="dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"');
    expect(html).toContain('class="report-review-marker">分析草稿·待复核</p>');
    expect(html).not.toContain('class="report-toc"');
    expect(html.indexOf('管理层第一屏结论。')).toBeLessThan(html.indexOf('草稿版本'));
    expect(html).toContain('draft-1');
    expect(html).toContain('内容 SHA-256');
    expect(html).toContain('report.md');
    expect(html.match(/<h1>经营分析报告<\/h1>/g)).toHaveLength(1);
    expect(html.match(/经营分析报告/g)!.length).toBeLessThan(5);

    const buffer = await exportDocx(doc, '经营分析报告', undefined, options);
    const zip = await JSZip.loadAsync(buffer);
    const documentXml = await zip.file('word/document.xml')!.async('string');
    const headerXml = await zip.file('word/header1.xml')!.async('string');
    expect(documentXml).toContain('分析草稿·待复核');
    expect(documentXml).not.toContain('w:instrText xml:space="preserve">TOC');
    expect(documentXml.indexOf('管理层第一屏结论')).toBeLessThan(documentXml.indexOf('草稿版本'));
    expect(documentXml).toContain('draft-1');
    expect(documentXml).toContain('内容 SHA-256');
    expect(documentXml).toContain('report.md');
    expect(headerXml).toContain('分析草稿·待复核');
    expect(headerXml).toContain('management');
    expect(headerXml).toContain('dddddddddddd');
  });

  it('renders the projection 估算值声明 block first and keeps template 估算 labels in HTML, print HTML and DOCX', async () => {
    // Shapes as foundry/report_estimates.py builds them: the declaration opens the projection document.
    const declaredValue = '117814.5625 万元';
    const formula = '05·区域预算分解!C5 × （01·年度预算总表!B12:C12 ÷ 01·年度预算总表!N12）';
    const doc: ReportDocument = {
      schema_version: 1,
      template_version: 'annual-v1',
      metadata: { company: '华宸物业', period: '2026-01:2026-08', currency: 'CNY', unit: '万元' },
      content: [
        { type: 'heading', attrs: { level: 2 }, content: [{ type: 'text', text: '估算值声明' }] },
        { type: 'paragraph', content: [{ type: 'text', text: '以下数值为估算，经理确认前不作为批复预算。' }] },
        { type: 'table', content: [
          { type: 'tableRow', content: ['要求', '组织', '期间', '情景', '估算值', '估算公式'].map((text) => cell('tableHeader', text, { textAlign: 'left' })) },
          { type: 'tableRow', content: [
            ...['1-8 月营业收入', '华东区域', '2026-01:2026-08', 'budget_1_8'].map((text) => cell('tableCell', text, { textAlign: 'left' })),
            cell('tableCell', declaredValue, { textAlign: 'right' }),
            cell('tableCell', formula, { textAlign: 'left' }),
          ] },
        ] },
        { type: 'paragraph', content: [{ type: 'text', text: '华东区域同期预算 117814.5625 万元（估算），实际 109742.028 万元。' }] },
        { type: 'table', content: [
          { type: 'tableRow', content: ['区域', '实际', '预算'].map((text) => cell('tableHeader', text)) },
          { type: 'tableRow', content: [cell('tableCell', '华东区域'), cell('tableCell', '109742.028 万元', { textAlign: 'right' }), cell('tableCell', '117814.5625 万元（估算）', { textAlign: 'right' })] },
        ] },
      ],
    };

    for (const contentMode of ['management', 'audit']) {
      const options = { marker: '分析草稿·待复核', contentMode, projectionHash: 'e'.repeat(64) };
      for (const html of [renderReportHtml(doc, '区域收入', options), renderReportHtml(doc, '区域收入', { print: true, ...options })]) {
        const order = ['<h1>区域收入</h1>', '估算值声明</h2>', '以下数值为估算，经理确认前不作为批复预算。', formula, '华东区域同期预算'].map((text) => html.indexOf(text));
        expect(order.every((position, index) => position >= 0 && (index === 0 || position > order[index - 1]))).toBe(true);
        expect(html).toContain(`<td class="num"><p>${declaredValue}</p></td>`);
        expect(html).toContain('同期预算 117814.5625 万元（估算），实际 109742.028 万元。');
        expect(html).toContain('<td class="num"><p>117814.5625 万元（估算）</p></td>');
        expect(html).not.toContain('109742.028 万元（估算）');
      }

      // Prose digits are their own Plex Mono runs, so sentences are read as the text Word shows.
      const documentXml = wordText(await (await JSZip.loadAsync(await exportDocx(doc, '区域收入', undefined, options))).file('word/document.xml')!.async('string'));
      const positions = ['估算值声明', '以下数值为估算，经理确认前不作为批复预算。', formula, '华东区域同期预算 117814.5625 万元（估算）'].map((text) => documentXml.indexOf(text));
      expect(positions.every((position, index) => position >= 0 && (index === 0 || position > positions[index - 1]))).toBe(true);
      expect(documentXml).toContain(declaredValue);
      expect(documentXml).toContain('117814.5625 万元（估算）');
      expect(documentXml).not.toContain('109742.028 万元（估算）');
    }
  });

  it('keeps the legacy receipt-first layout and TOC outside management mode', async () => {
    const doc = documentFromMarkdown('# 经营分析报告\n\n## 管理摘要\n\n正文。');
    const options = { marker: '分析草稿·待复核', contentMode: 'audit', projectionHash: 'd'.repeat(64), draftId: 'draft-1', contentHash: 'c'.repeat(64), publicationStatus: 'draft', reviewStatus: 'unreviewed', reproducibilityStatus: 'unverified', sources: ['report.md（md；ID source-1；SHA-256 aaaaaaaaaaaa）'] };
    const html = renderReportHtml(doc, '经营分析报告', { print: true, ...options });

    expect(html).toContain('class="report-toc"');
    expect(html.indexOf('草稿版本')).toBeLessThan(html.indexOf('正文。'));

    const buffer = await exportDocx(doc, '经营分析报告', undefined, options);
    const zip = await JSZip.loadAsync(buffer);
    const documentXml = await zip.file('word/document.xml')!.async('string');
    expect(documentXml).toContain('w:instrText xml:space="preserve">TOC');
    expect(documentXml.indexOf('草稿版本')).toBeLessThan(documentXml.indexOf('正文'));
  });

  it('imports HTML inertly and preserves source anchors without trusting executable content', async () => {
    const html = Buffer.from(`
      <article>
        <h1 onclick="steal()">月结报告</h1>
        <script>window.evil = true</script>
        <p>收入 <strong>3,456.70</strong> 元 <a href="javascript:bad()">坏链接</a></p>
        <table><tr><th>项目</th><th>金额</th></tr><tr><td>现金</td><td style="text-align:right">3,456.70</td></tr></table>
        <img src="https://remote.example/a.png">
      </article>
    `);

    const result = await importReport(html, 'html', { ...source, format: 'html', name: 'unsafe.html' });

    expect(result.needsReview).toBe(true);
    expect(result.warnings.join('\n')).toContain('脚本');
    expect(result.warnings.join('\n')).toContain('事件处理属性');
    expect(documentToMarkdown(result.document!)).toContain('3,456.70');
    expect(JSON.stringify(result.document)).toContain('"source_id":"source-a"');
    expect(JSON.stringify(result.document)).not.toContain('javascript:bad');
    expect(JSON.stringify(result.document)).not.toContain('remote.example');
  });

  it('renders matching footnote references as safe anchors and restores them from HTML import', async () => {
    const doc = documentFromMarkdown('正文引用 [^n1]，未知引用 [^missing]，代码 `[^n1]` 和链接 [^n1](https://example.com) 不应误转。\n\n[^n1]: 附注正文保留。');
    const html = renderReportHtml(doc, '附注报告');

    expect(html).toContain('data-report-note-ref="n1"');
    expect(html).toContain('href="#note-n1"');
    expect(html).toContain('id="note-n1"');
    expect(html).toContain('data-note-id="n1"');
    expect(html).toContain('未知引用 [^missing]');
    expect(html).toContain('<code>[^n1]</code>');
    expect(html).toContain('href="https://example.com"');

    const imported = await importReport(Buffer.from(html), 'html', { ...source, format: 'html', name: 'notes.html' });
    const markdown = documentToMarkdown(imported.document!);

    expect(markdown).toContain('正文引用 [^n1]');
    expect(markdown).toContain('未知引用 [^missing]');
    expect(markdown).toContain('[^n1]: 附注正文保留。');
  });

  it('round-trips formal HTML structure with captions, units, notes and PNG images', async () => {
    const doc = documentFromMarkdown('# 图文表报告\n\n正文引用 [^n1]。');
    doc.metadata = { company: '华宸物业', period: '2026-08', currency: 'CNY', unit: '万元' };
    doc.sources = [{ ...source, format: 'html', name: 'report.html' }];
    doc.content.push({
      type: 'table',
      attrs: { source_id: source.id, caption: '利润预算差异', period: '2026-08', currency: 'CNY', unit: '万元', sheet: '月结', range: 'A1:C2' },
      content: [
        { type: 'tableRow', content: [cell('tableHeader', '项目'), cell('tableHeader', '金额')] },
        { type: 'tableRow', content: [cell('tableCell', '利润'), cell('tableCell', '5.00', { textAlign: 'right' })] },
      ],
    });
    doc.content.push({ type: 'image', attrs: { source_id: source.id, src: png1x1, alt: '趋势图', title: '经营趋势' } });
    doc.content.push({ type: 'reportNote', attrs: { id: 'n1', source_id: source.id }, content: [{ type: 'paragraph', content: [{ type: 'text', text: '附注正文保留。' }] }] });

    const html = renderReportHtml(doc, '图文表报告', { print: true });
    const imported = await importReport(Buffer.from(html), 'html', { ...source, format: 'html', name: 'roundtrip.html' });
    const importedJson = JSON.stringify(imported.document);
    const table = imported.document!.content.find((node) => node.type === 'table')!;
    const image = imported.document!.content.find((node) => node.type === 'image')!;
    const note = imported.document!.content.find((node) => node.type === 'reportNote')!;

    expect(table.attrs).toMatchObject({ caption: '利润预算差异', period: '2026-08', currency: 'CNY', unit: '万元' });
    expect(documentToMarkdown(doc)).toContain('账套：未声明；组织：未声明；企业：华宸物业；期间：2026-08；币种：CNY；单位：万元');
    expect(documentToMarkdown(doc)).toContain('表题：利润预算差异；期间：2026-08；币种：CNY；单位：万元');
    expect(image.attrs).toMatchObject({ src: png1x1, alt: '趋势图' });
    expect(note.attrs).toMatchObject({ id: 'n1', source_id: 'source-a' });
    expect(documentToMarkdown(imported.document!)).toContain('[^n1]: 附注正文保留。');
    expect(importedJson).not.toContain('data:image/gif');
  });

  it('resolves Markdown and HTML image resources only from provided safe data URLs', async () => {
    const md = Buffer.from('# 图片导入\n\n![本地图](charts/trend.png)\n\n![缺失](charts/missing.png)');
    const html = Buffer.from('<article><p><img src="images/a.png" alt="HTML图"></p><p><img src="file:///tmp/b.png" alt="不可信"></p><p><a href="./images/a.png">本地链接不替换</a></p></article>');

    const mdResult = await importReport(md, 'md', source, { 'charts/trend.png': png1x1 });
    const htmlResult = await importReport(html, 'html', { ...source, format: 'html', name: 'images.html' }, { 'images/a.png': png1x1 });

    expect(JSON.stringify(mdResult.document)).toContain(png1x1);
    expect(JSON.stringify(mdResult.document)).not.toContain('charts/trend.png');
    expect(JSON.stringify(mdResult.document)).not.toContain('charts/missing.png');
    expect(mdResult.warnings.join('\n')).toContain('charts/missing.png');
    expect(mdResult.needsReview).toBe(true);

    expect(JSON.stringify(htmlResult.document)).toContain(png1x1);
    expect(JSON.stringify(htmlResult.document)).not.toContain('file:///tmp/b.png');
    expect(JSON.stringify(htmlResult.document)).toContain('./images/a.png');
    expect(htmlResult.warnings.join('\n')).toContain('file:///tmp/b.png');
  });

  it('imports PDF text conservatively and marks it for review', async () => {
    const pdf = minimalPdf('Revenue 1234.50 CNY');
    const result = await importReport(pdf, 'pdf', { ...source, format: 'pdf', name: 'report.pdf' });

    expect(result.needsReview).toBe(true);
    expect(result.warnings.join('\n')).toContain('复杂表格');
    expect(documentToMarkdown(result.document!)).toContain('1234.50 CNY');
    expect(JSON.stringify(result.document)).toContain('"page":1');
  });

  it('embeds IBM Plex Mono in HTML and PDF exports: whole figure cells, and digits inside prose', () => {
    const doc = documentFromMarkdown(['利润 12 万元。', '', '| 项目 | 本月 |', '| --- | --- |', '| 小计 | 1.00 |', '| 合计 | -2.00 |'].join('\n'));
    const url = 'data:font/woff2;base64,AAAA';
    const html = renderReportHtml(doc, '数字', { print: true, figureFonts: [400, 600, 700].map((weight) => ({ weight, url })) });
    for (const weight of [400, 600, 700]) {
      expect(html).toContain(`@font-face{font-family:"IBM Plex Mono";src:url("${url}") format("woff2");font-weight:${weight};font-style:normal;font-display:block;unicode-range:U+0020-007E,U+00A0-00FF,U+2030,U+2212;}`);
      expect(html).toContain(`@font-face{font-family:"FND Figures";src:url("${url}") format("woff2");font-weight:${weight};font-style:normal;font-display:block;unicode-range:U+0025,U+0030-0039;}`);
    }
    expect(html).toContain('body{margin:0;background:var(--report-bg);color:var(--report-ink);font-family:var(--report-prose);');
    expect(html).toContain('td.num{font-family:var(--report-figure)}');
    expect(html).toContain('<tr class="row-subtotal">');
    expect(html).toContain('<tr class="row-total"><td class="text" data-first-column=""><p>合计</p></td><td class="num neg"><p>-2.00</p></td></tr>');
    // Anything but an inline WOFF2 data URL is dropped, so an export never reaches for a network font.
    expect(renderReportHtml(doc, '数字', { figureFonts: [{ weight: 400, url: 'https://example.com/plex.woff2' }] })).not.toContain('example.com');
  });

  it('sets Word figure cells in the embedded IBM Plex Mono, negatives in the muted red and totals bold', async () => {
    const doc = documentFromMarkdown([
      '营业利润 1,250,000.00 元。',
      '',
      '| 项目 | 本月 |',
      '| --- | --- |',
      '| 收入 | 1,250,000.00 |',
      '| 成本 | -98,765.43 |',
      '| 小计 | 1,151,234.57 |',
      '| 合计 | 1,151,234.57 |',
      '| 差异 | −3.30 个百分点 |',
      '| 年份 | 2026 |',
      '',
      '详见[2026 年预算](https://example.com/b)。',
    ].join('\n'));
    const plex = new Uint8Array(readFileSync(fileURLToPath(new URL('../src/assets/fonts/ibm-plex-mono/IBMPlexMono-Regular.ttf', import.meta.url))));
    const zip = await JSZip.loadAsync(await exportDocx(doc, '数字', undefined, {}, plex));
    const documentXml = await zip.file('word/document.xml')!.async('string');
    const fontTable = await zip.file('word/fontTable.xml')!.async('string');
    expect(fontTable).toContain('w:name="IBM Plex Mono"');
    expect(fontTable).toContain('w:embedRegular');
    expect(Object.keys(zip.files).some((name) => /^word\/fonts\/.+\.odttf$/.test(name))).toBe(true);
    const run = (text: string) => documentXml.match(new RegExp(`<w:r>(?:(?!<w:r>).)*?<w:t[^>]*>${text.replace(/[.()]/g, '\\$&')}</w:t>`))?.[0] ?? '';
    // A figure cell: Plex Mono for its Latin characters, Noto Sans SC for any unit, in one run.
    expect(run('1,250,000.00')).toContain('w:ascii="IBM Plex Mono"');
    expect(run('1,250,000.00')).toContain('w:eastAsia="Noto Sans SC"');
    expect(run('-98,765.43')).toContain('w:val="94463D"');
    expect(run('1,250,000.00')).not.toContain('94463D');
    // Prose keeps its words and separators in Noto Sans SC; only the digit runs take Plex Mono.
    expect(run('营业利润 ')).toContain('w:ascii="Noto Sans SC"');
    expect(run('250')).toContain('w:ascii="IBM Plex Mono"');
    // A figure with a unit is a figure, as in the HTML export: one Plex Mono run, in the negative red.
    expect(run('−3.30 个百分点')).toContain('w:ascii="IBM Plex Mono"');
    expect(run('−3.30 个百分点')).toContain('w:val="94463D"');
    // Linked prose keeps its digit runs.
    const hyperlink = documentXml.match(/<w:hyperlink[\s\S]*?<\/w:hyperlink>/)?.[0] ?? '';
    expect(hyperlink).toMatch(/w:ascii="IBM Plex Mono"[\s\S]*?>2026<\/w:t>/);
    // 小计 and 合计 rows are bold; the 合计 row also sits under a rule.
    const rows = documentXml.match(/<w:tr>[\s\S]*?<\/w:tr>/g) ?? [];
    const row = (name: string) => rows.find((xml) => xml.includes(`>${name}</w:t>`)) ?? '';
    expect(row('收入')).not.toContain('<w:b/>');
    expect(row('小计')).toContain('<w:b/>');
    expect(row('合计')).toContain('<w:b/>');
    expect(row('合计')).toContain('<w:top w:val="single"');
    expect(row('小计')).not.toContain('<w:top w:val="single"');
  });

  it('exports DOCX with A4 margins, repeated table headers, footer page numbers and exact numbers', async () => {
    const doc: ReportDocument = documentFromMarkdown([
      '# 经营与预算分析',
      '',
      '预算差异为 -98,765.43 元。正文引用 [^n1]。',
      '',
      '[^n1]: Word 回读附注。',
      '',
      '1. 跟进现金回款',
      '',
      '| 项目 | 一月 | 二月 | 三月 | 四月 | 五月 | 六月 | 七月 |',
      '| --- | --- | --- | --- | --- | --- | --- | --- |',
      '| 收入 | 1.00 | 2.00 | 3.00 | 4.00 | 5.00 | 6.00 | 7.00 |',
    ].join('\n'));
    doc.metadata = { company: '华宸物业', period: '2026-08', currency: 'CNY', unit: '万元' };

    const buffer = await exportDocx(doc, '经营分析报告');
    const zip = await JSZip.loadAsync(buffer);
    const documentXml = await zip.file('word/document.xml')!.async('string');
    const footerXml = await zip.file('word/footer1.xml')!.async('string');
    const numberingXml = await zip.file('word/numbering.xml')!.async('string');

    expect(documentXml).toContain('w:w="11906"');
    expect(documentXml).toContain('w:h="16838"');
    expect(documentXml).toContain('w:top="1134"');
    expect(documentXml).toContain('华宸物业 / 2026-08 / CNY / 万元');
    expect(documentXml).toContain('<w:tblHeader/>');
    expect(documentXml).toContain('经营与预算分析');
    expect(wordText(documentXml)).toContain('预算差异为 -98,765.43 元。');
    expect(documentXml).toContain('<w:vertAlign w:val="superscript"/>');
    expect(documentXml).toContain('续表');
    expect(footerXml).toContain('PAGE');
    expect(numberingXml).toContain('%1.');

    const imported = await importReport(buffer, 'docx', { ...source, format: 'docx', name: 'roundtrip.docx' });
    expect(imported.needsReview).toBe(true);
    expect(imported.warnings.join('\n')).toContain('Word 导入采用语义转换');
    expect(documentToMarkdown(imported.document!)).toContain('-98,765.43');
    expect(documentToMarkdown(imported.document!)).toContain('[^n1]');
    expect(documentToMarkdown(imported.document!)).toContain('[^n1]: Word 回读附注。');
  });

  it('embeds provided Noto Sans SC font data in DOCX exports', async () => {
    const doc = documentFromMarkdown('# 字体嵌入\n\n正文。');
    const buffer = await exportDocx(doc, '字体报告', new Uint8Array([0, 1, 2, 3, 4, 5]));
    const zip = await JSZip.loadAsync(buffer);
    const fontTable = await zip.file('word/fontTable.xml')!.async('string');
    const fontRels = await zip.file('word/_rels/fontTable.xml.rels')!.async('string');

    expect(fontTable).toContain('Noto Sans SC');
    expect(fontTable).toContain('fontKey');
    expect(fontRels).toContain('font');
  });

  it('marks table headers over numeric columns in HTML and print exports, per wide-table group', () => {
    const doc = documentFromMarkdown([
      '表题：表 2-1 区域营业利润',
      '',
      '| 区域 | 1 至 8 月实际 | 差异率 |',
      '| --- | --- | --- |',
      '| 华东区域 | 325,644.00 万元 | -3.30% |',
      '| 华南区域 | -18,843.06 万元 | 预算为负，不作比率 |',
      '| 西南区域 | 117814.5625 万元（估算） | 12.5% |',
      '',
      '| 项目 | 说明 | 一月 | 二月 | 三月 | 四月 | 五月 |',
      '| --- | --- | --- | --- | --- | --- | --- |',
      '| 应收账款 | 按账龄 | 1,000.00 | 2,000.00 | 3,000.00 | 4,000.00 | 5,000.00 |',
      '| 预收账款 | 按合同 | 6,000.00 | 7,000.00 | 8,000.00 | 9,000.00 | 10,000.00 |',
    ].join('\n'));
    for (const html of [renderReportHtml(doc, '区域经营'), renderReportHtml(doc, '区域经营', { print: true })]) {
      // The export names each table but makes no figure focusable; only the in-app reading view does, when it scrolls.
      expect(html).toContain('<figure class="financial-table" aria-label="表 2-1 区域营业利润">');
      expect(html).not.toContain('tabindex');
      expect(html).not.toContain('role="region"');
      expect(html).toContain('<th class="text" data-first-column=""><p>区域</p></th><th class="num"><p>1 至 8 月实际</p></th><th class="num"><p>差异率</p></th>');
      expect(html).toContain('<td class="num"><p>325,644.00 万元</p></td>');
      // A negative keeps the author's sign and is only marked for the muted red.
      expect(html).toContain('<td class="num neg"><p>-18,843.06 万元</p></td>');
      expect(html).toContain('<td class="num neg"><p>-3.30%</p></td>');
      expect(html).toContain('<td class="num"><p>117814.5625 万元（估算）</p></td>');
      expect(html).toContain('<td class="num note"><p>预算为负，不作比率</p></td>');
      expect(html).toContain('<td class="text" data-first-column=""><p>华东区域</p></td>');
      // Seven columns split into two groups; each group judges its own columns and names itself a continuation.
      const groups = html.match(/<div class="wide-table-group"[\s\S]*?<\/div>/)?.[0] ?? '';
      expect(groups).toContain('<th class="text" data-first-column=""><p>项目</p></th><th class="text"><p>说明</p></th><th class="num"><p>一月</p></th>');
      expect(groups).toContain('aria-label="财务表格（续表）"');
      expect(groups).toContain('<th class="text" data-first-column=""><p>项目</p></th><th class="num"><p>五月</p></th>');
    }

    const spanned: ReportDocument = { schema_version: 1, template_version: 'annual-v1', metadata: { company: '', period: '', currency: '', unit: '' }, content: [
      { type: 'table', content: [
        { type: 'tableRow', content: [cell('tableHeader', '区域'), cell('tableHeader', '实际')] },
        { type: 'tableRow', content: [cell('tableCell', '华东', { rowspan: 2 }), cell('tableCell', '1,000.00')] },
        { type: 'tableRow', content: [cell('tableCell', '2,000.00')] },
      ] },
    ] };
    const spannedHtml = renderReportHtml(spanned, '合并单元格');
    expect(spannedHtml).toContain('<th class="text" data-first-column=""><p>区域</p></th><th class="text"><p>实际</p></th>');
    // The row under a row span starts in the second column: its cell is not the first column.
    expect(spannedHtml).toContain('<tr><td class="num"><p>2,000.00</p></td></tr>');
  });

  it('reads signed numbers with area and count units, and leaves broken brackets and loose commas as text', () => {
    const doc = documentFromMarkdown([
      '| 项目 | 值 |',
      '| --- | --- |',
      '| 差值 | −3.30 个百分点 |',
      '| 增加 | +1,200.00 万元 |',
      '| 面积 | 12,500 平方米 |',
      '| 面积二 | 300 ㎡ |',
      '| 户数 | 35 户 |',
      '| 人数 | 120 人 |',
      '| 笔数 | 8 笔 |',
      '| 规模 | 3.5 亿 |',
      '| 规模二 | 120 万 |',
      '| 半括号 | (123 |',
      '| 编号 | 1,2,3 |',
      '| 缺值 | — |',
      '| 暂缺 | 暂无数据 |',
      '| 全角 | 12.5％ |',
      '| 年份 | 2026 |',
    ].join('\n'));
    const html = renderReportHtml(doc, '单位');
    expect(html).toContain('<td class="num neg"><p>−3.30 个百分点</p></td>');
    for (const text of ['+1,200.00 万元', '12,500 平方米', '300 ㎡', '35 户', '120 人', '8 笔', '3.5 亿', '120 万']) {
      expect(html).toContain(`<td class="num"><p>${text}</p></td>`);
    }
    expect(html).toContain('<td class="text"><p>(123</p></td>');
    expect(html).toContain('<td class="text"><p>1,2,3</p></td>');
    expect(html).toContain('<td class="num note"><p>—</p></td>');
    expect(html).toContain('<td class="num note"><p>暂无数据</p></td>');
    expect(html).toContain('<td class="num"><p>12.5％</p></td>');
    expect(html).toContain('<td class="text"><p>2026</p></td>');
  });

  it('keeps a column of years and the first column as text, with their headers on the left', () => {
    const html = renderReportHtml(documentFromMarkdown([
      '| 年度 | 收入 |',
      '| --- | --- |',
      '| 2025 | 1,000.00 |',
      '| 2026 | 1,200.00 |',
    ].join('\n')), '年度');
    expect(html).toContain('<th class="text" data-first-column=""><p>年度</p></th><th class="num"><p>收入</p></th>');
    expect(html).toContain('<td class="text" data-first-column=""><p>2025</p></td><td class="num"><p>1,000.00</p></td>');
  });

  it('exports merged cells, captions and PNG images to DOCX without silently segmenting the merge', async () => {
    const doc: ReportDocument = {
      schema_version: 1,
      template_version: 'annual-v1',
      metadata: { company: '华宸物业', period: '2026-08', currency: 'CNY', unit: '万元' },
      sources: [source],
      content: [
        { type: 'table', attrs: { caption: '合并宽表', period: '2026-08', currency: 'CNY', unit: '万元' }, content: [
          { type: 'tableRow', content: ['项目', '一月', '二月', '三月', '四月', '五月', '六月'].map((text) => cell('tableHeader', text)) },
          { type: 'tableRow', content: [
            cell('tableCell', '合并单元格', { colspan: 2 }),
            cell('tableCell', '1.00'), cell('tableCell', '2.00'), cell('tableCell', '3.00'), cell('tableCell', '4.00'), cell('tableCell', '5.00'),
          ] },
        ] },
        { type: 'image', attrs: { src: png1x1, alt: '趋势图' } },
      ],
    };

    const buffer = await exportDocx(doc, '合并宽表报告');
    const zip = await JSZip.loadAsync(buffer);
    const documentXml = await zip.file('word/document.xml')!.async('string');
    const relationships = await zip.file('word/_rels/document.xml.rels')!.async('string');

    expect(documentXml).toContain('合并宽表');
    expect(documentXml).toContain('2026-08 / CNY / 万元');
    expect(documentXml).toContain('合并单元格');
    expect(documentXml).toContain('续表');
    expect(relationships).toContain('image');
  });
});

function minimalPdf(text: string): Buffer {
  const escaped = text.replace(/[()\\]/g, '\\$&');
  const stream = `BT /F1 18 Tf 72 760 Td (${escaped}) Tj ET`;
  const objects = [
    '1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n',
    '2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n',
    '3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\nendobj\n',
    '4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n',
    `5 0 obj\n<< /Length ${Buffer.byteLength(stream)} >>\nstream\n${stream}\nendstream\nendobj\n`,
  ];
  let output = '%PDF-1.4\n';
  const offsets = [0];
  for (const object of objects) {
    offsets.push(Buffer.byteLength(output));
    output += object;
  }
  const xref = Buffer.byteLength(output);
  output += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  for (let index = 1; index < offsets.length; index += 1) {
    output += `${String(offsets[index]).padStart(10, '0')} 00000 n \n`;
  }
  output += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`;
  return Buffer.from(output);
}

/** The text Word shows: runs joined, one line per paragraph. */
function wordText(xml: string): string {
  return xml.replace(/<\/w:p>/g, '\n').replace(/<[^>]+>/g, '').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>');
}

function cell(type: 'tableHeader' | 'tableCell', text: string, attrs: Record<string, unknown> = {}): ReportNode {
  return {
    type,
    attrs,
    content: [{ type: 'paragraph', content: [{ type: 'text', text }] }],
  };
}
