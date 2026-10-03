import { describe, expect, it } from 'vitest';
import { parseHTML } from 'linkedom';
import { normalizeReportVisual, renderReportVisualSvg, reportVisualCaption, reportVisualMarkdown } from '../electron/reports/visuals.js';
import contractFixtures from '../../tests/fixtures/report_visual_contract.json';

function chart(overrides: Record<string, unknown> = {}) {
  return {
    version: 1, kind: 'bar', title: '区域经营利润', takeaway: '对照相同口径的区域差异。',
    chart_id: 'c'.repeat(32), run_id: 'd'.repeat(32), snapshot_hash: 'a'.repeat(64), source_label: '八月核算',
    category: '区域', value_columns: ['利润'], unit: '万元',
    series: { columns: [{ name: '区域', type: 'VARCHAR' }, { name: '利润', type: 'DECIMAL(38, 2)' }], rows: [{ 区域: '华东', 利润: '120.00' }, { 区域: '华南', 利润: '-40.10' }, { 区域: '华北', 利润: '0.00' }, { 区域: '西南', 利润: null }] },
    ...overrides,
  };
}

function flow(overrides: Record<string, unknown> = {}) {
  return { version: 1, kind: 'flow', title: '回款改善机制', steps: [{ label: '合同确认', detail: '核对账期与结算条款', connector: '明确到期应收' }, { label: '催收计划', detail: '按责任人跟进', connector: '' }], ...overrides };
}

describe('report visual evidence and validation', () => {
  it.each(contractFixtures)('agrees with the Python density contract: $name', (fixture) => {
    if (!fixture.accepted) {
      expect(() => normalizeReportVisual(fixture.visual)).toThrow();
      return;
    }
    const svg = renderReportVisualSvg(fixture.visual);
    const height = Number(parseHTML(svg).document.querySelector('svg')?.getAttribute('height'));
    expect(height).toBe(fixture.height);
    expect(height).toBeLessThanOrEqual(1200);
  });

  it('preserves exact Decimal values and nested evidence without mutating the input', () => {
    const raw = chart();
    raw.series.rows[0].利润 = '900719925474099.990000';
    Object.assign(raw.series.rows[0], { source_rows: [{ dataset_id: 'ds-1', row_index: 4 }] });
    const normalized = normalizeReportVisual(raw);
    expect(normalized.kind).toBe('bar');
    if (normalized.kind === 'flow') throw new Error('Expected data visual');
    expect(normalized.series).toEqual(raw.series);
    normalized.series.rows[0].利润 = '1';
    expect(raw.series.rows[0].利润).toBe('900719925474099.990000');
    expect(reportVisualMarkdown(raw)).toContain('900719925474099.990000');
    const texts = Array.from(parseHTML(renderReportVisualSvg(raw)).document.querySelectorAll('text')).map((node) => node.textContent);
    expect(texts).toContain('900719925474099.990000');
  });

  it.each([true, false, '', ' ', 'NaN', 'Infinity', Infinity, NaN, '-Infinity', '1e999', '1e-999', '0x10', '1,000', {}, undefined])('rejects invalid selected numeric value %s', (value) => {
    const raw = chart();
    Object.assign(raw.series.rows[0], { 利润: value });
    expect(() => normalizeReportVisual(raw)).toThrow(/十进制|有限|JSON/);
  });

  it('rejects missing, repeated, unknown and entirely empty series explicitly', () => {
    expect(() => normalizeReportVisual(chart({ value_columns: ['利润', '利润'] }))).toThrow('重复');
    expect(() => normalizeReportVisual(chart({ value_columns: ['区域'] }))).toThrow('重复');
    expect(() => normalizeReportVisual(chart({ value_columns: ['未知'] }))).toThrow('不在冻结数据');
    const raw = chart(); raw.series.rows.forEach((row) => { row.利润 = null; });
    expect(() => normalizeReportVisual(raw)).toThrow('全部缺失');
  });

  it('does not truncate excess data or silently collapse duplicate categories', () => {
    const raw = chart();
    raw.series.rows = Array.from({ length: 13 }, (_, index) => ({ 区域: String(index), 利润: '1' }));
    expect(() => normalizeReportVisual(raw)).toThrow('1–12 行');
    raw.kind = 'line'; raw.series.rows = Array.from({ length: 25 }, (_, index) => ({ 区域: String(index), 利润: '1' }));
    expect(() => normalizeReportVisual(raw)).toThrow('1–24 行');
    const duplicate = chart(); duplicate.series.rows[1].区域 = ' 华东 ';
    expect(() => normalizeReportVisual(duplicate)).toThrow('类别必须唯一');
  });

  it('requires frozen snapshot identifiers and rejects unbounded or unsafe metadata', () => {
    expect(() => normalizeReportVisual(chart({ snapshot_hash: 'not-a-hash' }))).toThrow('SHA-256');
    expect(() => normalizeReportVisual(chart({ run_id: '' }))).toThrow('不能为空');
    const raw = chart();
    Object.assign(raw.series.rows[0], { extra: JSON.parse('{"__proto__": {"x": "unsafe"}}') });
    expect(() => normalizeReportVisual(raw)).toThrow('不允许的字段');
    expect(() => normalizeReportVisual(chart({ title: '中'.repeat(161) }))).toThrow('160');
    expect(() => normalizeReportVisual(chart({ unit: '' }))).toThrow('单位不能为空');
  });

  it.each(['chart_id', 'run_id'])('matches backend identity validation for %s', (field) => {
    for (const id of ['short-id', 'A'.repeat(32), 'g'.repeat(32), 'a'.repeat(31), 'a'.repeat(33)]) {
      expect(() => normalizeReportVisual(chart({ [field]: id }))).toThrow(/标识/);
    }
    expect(() => normalizeReportVisual(chart({ [field]: '0123456789abcdef'.repeat(2) }))).not.toThrow();
  });

  it('retains whitespace in field identifiers while checking category uniqueness on trimmed text', () => {
    const raw = chart({ category: ' 区域 ', value_columns: [' 利润 '], title: ' 保留空格 ' });
    raw.series.columns = [{ name: ' 区域 ', type: 'VARCHAR' }, { name: ' 利润 ', type: 'DECIMAL' }];
    raw.series.rows = [{ ' 区域 ': ' 甲 ', ' 利润 ': '123.4500' }] as unknown as typeof raw.series.rows;
    expect(normalizeReportVisual(raw)).toMatchObject({ category: ' 区域 ', value_columns: [' 利润 '], title: ' 保留空格 ' });
    expect(reportVisualMarkdown(raw)).toContain('|  甲  | 123.4500 |');
  });

  it('rejects unreadable density without silently reducing rows or precision', () => {
    const raw = chart({ value_columns: ['利润', '预算'] });
    raw.series.columns.push({ name: '预算', type: 'DECIMAL' });
    raw.series.rows = Array.from({ length: 7 }, (_, index) => ({ 区域: String(index), 利润: '1', 预算: '2' }));
    expect(() => normalizeReportVisual(raw)).toThrow('12 个数据位置');
    const crowded = flow({ steps: Array.from({ length: 6 }, (_, index) => ({ label: '步'.repeat(60), detail: '说'.repeat(140), connector: index < 5 ? '原因'.repeat(20) : '' })) });
    expect(() => normalizeReportVisual(crowded)).toThrow('内容过密');
    const trend = chart({ kind: 'line' });
    trend.series.rows = Array.from({ length: 24 }, (_, index) => ({ 区域: `${index + 1} 月`, 利润: String(index) }));
    const svg = renderReportVisualSvg(trend);
    expect(Number(parseHTML(svg).document.querySelector('svg')?.getAttribute('height'))).toBeLessThanOrEqual(1200);
    expect(svg).toContain('24. 24 月');
    trend.series.rows.forEach((row) => { row.区域 += '特别长的业务类别'.repeat(8); });
    expect(() => normalizeReportVisual(trend)).toThrow('内容过密');
  });

  it('keeps the standard estimate notice in every presentation and rejects arbitrary notices', () => {
    const notice = '本图含估算值，经理确认前不作为批复预算。';
    const raw = chart({ estimate_notice: notice });
    expect(reportVisualCaption(raw)).toContain(notice);
    expect(reportVisualMarkdown(raw)).toContain(notice);
    expect(renderReportVisualSvg(raw)).toContain(notice);
    expect(() => normalizeReportVisual(chart({ estimate_notice: '已经批复' }))).toThrow('标准文案');
  });

  it('normalizes explicit author explanations, bounds steps and forbids a trailing edge', () => {
    expect(normalizeReportVisual(flow())).toMatchObject({ kind: 'flow', takeaway: '', source_label: '作者分析' });
    expect(() => normalizeReportVisual(flow({ steps: [{ label: '孤立节点' }] }))).toThrow('2–6');
    const raw = flow(); raw.steps[1].connector = '错误下一步';
    expect(() => normalizeReportVisual(raw)).toThrow('最后一个步骤');
  });
});

describe('static report visual rendering', () => {
  it('draws signed bars on opposite sides of a visible zero baseline and preserves null', () => {
    const { document } = parseHTML(renderReportVisualSvg(chart()));
    const bars = Array.from(document.querySelectorAll('rect[fill="#8a6729"]'));
    expect(bars).toHaveLength(2);
    const baseline = document.querySelector('line[stroke="#aaa49a"]')!;
    const zero = Number(baseline.getAttribute('x1'));
    expect(Number(bars[0].getAttribute('x'))).toBeCloseTo(zero, 1);
    expect(Number(bars[1].getAttribute('x'))).toBeLessThan(zero);
    expect(Number(bars[1].getAttribute('width'))).toBeGreaterThan(0);
    expect(document.querySelector('svg')?.textContent).not.toContain('NaN');
    expect(document.querySelector('svg')?.textContent).toContain('缺失值显示为“缺失”，不补零');
    expect(document.querySelector('svg')?.textContent).toContain('0.00');
  });

  it.each([['0', '0'], ['-2', '-1']])('uses finite geometry for edge-case values %j', (first, second) => {
    const raw = chart(); raw.series.rows = [{ 区域: '甲', 利润: first }, { 区域: '乙', 利润: second }];
    const svg = renderReportVisualSvg(raw);
    expect(svg).not.toMatch(/(?:x|y|width|height)="(?:NaN|Infinity|-Infinity)"/);
    for (const match of svg.matchAll(/(?:width|height)="([\d.-]+)"/g)) expect(Number(match[1])).toBeGreaterThanOrEqual(0);
  });

  it('normalizes the domain before subtracting opposite finite extremes', () => {
    const raw = chart({ kind: 'line' }); raw.series.rows = [{ 区域: '甲', 利润: '1e308' }, { 区域: '乙', 利润: '-1e308' }];
    const svg = renderReportVisualSvg(raw);
    expect(svg).not.toContain('NaN'); expect(svg).not.toContain('Infinity');
    const points = parseHTML(svg).document.querySelector('polyline')!.getAttribute('points')!;
    expect(points).toMatch(/^144,[\d.]+ 656,[\d.]+$/);
  });

  it.each([
    { values: ['0', '600'], expected: ['0', '200', '400', '600'] },
    { values: ['-300', '600'], expected: ['-300', '0', '300', '600'] },
    { values: ['1e308', '-1e308'], expected: ['-1e308', '-3.33e307', '0', '3.33e307', '1e308'] },
    { values: ['5e-324', '0'], expected: ['0', '1.65e-324', '3.29e-324', '4.94e-324'] },
    { values: ['395000000', '418400000'], expected: ['0', '139,000,000', '279,000,000', '418,000,000'] },
    { values: ['-12500', '96000'], expected: ['-12,500', '0', '23,700', '59,800', '96,000'] },
    { values: ['0', '-99900000000'], expected: ['-99,900,000,000', '-66,600,000,000', '-33,300,000,000', '0'] },
    { values: ['0', '420000000000'], expected: ['0', '1.4e11', '2.8e11', '4.2e11'] },
    // One style per axis: an axis that reaches 1e11 never mixes 40,000,000,000 with 1.2e11.
    { values: ['0', '120000000000'], expected: ['0', '4e10', '8e10', '1.2e11'] },
  ])('labels the zero baseline and compact numeric scale for $values', ({ values, expected }) => {
    const raw = chart({ kind: 'line' });
    raw.series.rows = values.map((value, index) => ({ 区域: String(index + 1), 利润: value }));
    const { document } = parseHTML(renderReportVisualSvg(raw));
    const ticks = Array.from(document.querySelectorAll('[data-report-axis-tick] text')).map((node) => node.textContent);
    expect(ticks).toEqual(expected);
    expect(ticks.length).toBeGreaterThanOrEqual(3); expect(ticks.length).toBeLessThanOrEqual(5);
    expect(ticks.filter((tick) => tick === '0')).toHaveLength(1);
    // 15 characters is what fits right-aligned left of the plot at 14px.
    expect(ticks.every((tick) => tick!.length <= 15)).toBe(true);
  });

  it('expands scientific labels without rounding Decimal precision away', () => {
    const raw = chart(); raw.series.rows = [{ 区域: '甲', 利润: '9.0071992547409999000e+14' }, { 区域: '乙', 利润: '1.2300e-3' }];
    const markdown = reportVisualMarkdown(raw);
    expect(markdown).toContain('9.0071992547409999000e+14');
    expect(markdown).toContain('1.2300e-3');
    const texts = Array.from(parseHTML(renderReportVisualSvg(raw)).document.querySelectorAll('text')).map((node) => node.textContent);
    expect(texts).toContain('900719925474099.99000');
    expect(texts).toContain('0.0012300');
  });

  it('does not connect across missing values and retains original time ordering', () => {
    const raw = chart({ kind: 'line' });
    raw.series.rows = ['09', '07', '08', '06', '05'].map((month, index) => ({ 区域: month, 利润: index === 2 ? null : String(index) }));
    const { document } = parseHTML(renderReportVisualSvg(raw));
    const paths = Array.from(document.querySelectorAll('polyline'));
    expect(paths).toHaveLength(2);
    expect(paths.map((path) => path.getAttribute('points')?.split(' ').length)).toEqual([2, 2]);
    const markdown = reportVisualMarkdown(raw);
    expect(markdown.indexOf('| 09 |')).toBeLessThan(markdown.indexOf('| 07 |'));
    expect(markdown).toContain('| 08 | 缺失 |');
  });

  it('directly labels all three groups and distinguishes line patterns', () => {
    const raw = chart({ value_columns: ['利润', '预算', '上期'] });
    raw.series.columns.push({ name: '预算', type: 'DECIMAL' }, { name: '上期', type: 'DECIMAL' });
    raw.series.rows.forEach((row) => Object.assign(row, { 预算: '100.00', 上期: '80.00' }));
    const bar = renderReportVisualSvg(raw);
    expect(bar).toContain('预算'); expect(bar).toContain('上期'); expect(bar).toContain('100.00');
    const trend = renderReportVisualSvg({ ...raw, kind: 'line' });
    expect(trend).toContain('stroke-dasharray="7 4"'); expect(trend).toContain('stroke-dasharray="2 4"');
    expect(trend).toContain('末项 缺失');
  });

  it('wraps long Chinese labels and grows without dropping source, conclusion or characters', () => {
    const raw = chart();
    raw.title = '年度综合运营管理与经营质量改进分析'.repeat(6);
    raw.series.rows[0].区域 = '长三角城市综合服务及公共设施管理业务项目'.repeat(6);
    const svg = renderReportVisualSvg(raw); const { document } = parseHTML(svg);
    const baseline = renderReportVisualSvg(chart());
    expect(Number(document.querySelector('svg')?.getAttribute('height'))).toBeGreaterThan(Number(parseHTML(baseline).document.querySelector('svg')?.getAttribute('height')));
    const texts = Array.from(document.querySelectorAll('text')).map((node) => node.textContent);
    expect(texts).toContain(raw.title); expect(texts).toContain(raw.series.rows[0].区域);
    expect(svg).toContain('来源：八月核算'); expect(svg).toContain('作者结论：');
    expect(svg).not.toContain('run-1');
  });

  it('escapes every label and only emits static SVG primitives with accessible text', () => {
    const malicious = '<script>alert("x")</script><image href="https://bad">';
    const raw = chart({ title: malicious, takeaway: malicious, source_label: malicious });
    raw.series.rows[0].区域 = malicious;
    const svg = renderReportVisualSvg(raw); const { document } = parseHTML(svg);
    const root = document.querySelector('svg')!;
    expect(root.getAttribute('role')).toBe('img'); expect(root.firstElementChild?.tagName.toLowerCase()).toBe('title');
    expect(root.querySelectorAll('script, image, foreignObject, a, style, defs')).toHaveLength(0);
    expect(root.querySelectorAll('[id]')).toHaveLength(0);
    expect(svg).not.toContain('<script>'); expect(root.getAttribute('aria-label')).toBe(malicious);
    expect(reportVisualMarkdown(raw)).not.toContain('<script>');
  });

  it('renders directional labeled flow relationships and marks them as author explanations', () => {
    const raw = flow(); const svg = renderReportVisualSvg(raw); const { document } = parseHTML(svg);
    expect(document.querySelectorAll('path')).toHaveLength(1);
    expect(svg).toContain('明确到期应收');
    expect(reportVisualCaption(raw)).toContain('作者解释流程');
    expect(reportVisualMarkdown(raw)).toContain('→ 明确到期应收');
    expect(svg).toContain('不构成计算证据');
    expect(reportVisualCaption(chart())).toContain('来源：八月核算');
    expect(reportVisualCaption(chart())).not.toContain('run-1');
  });
});
