// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { BusinessResultView } from '../src/views/analysis/BusinessResultView.js';
import { askAboutFigure, figureSource, runIsStale, sourceText, type FigureSourceContext } from '../src/views/analysis/figureSource.js';
import { ASK_EVENT } from '../src/views/guide/ask.js';
import type { AnalysisRevision, AnalysisRun, DatasetSnapshot } from '../src/bridge.js';

const taskId = 't'.repeat(32);
const pack = { id: 'd'.repeat(32), name: '8月套表', kind: 'table', source_hash: 'h'.repeat(64), data_hash: 'e'.repeat(64), source_name: 'pack.xlsx', metadata: {}, task_id: taskId, schema_version: 1, created_at: '2026-09-01T00:00:00Z' } as DatasetSnapshot;

const row = {
  period: '2026-08', metric_key: 'revenue', metric: '收入', unit: '万元',
  actual: 1234.5, budget: 1300, variance: -65.5, attainment_rate: 0.9496,
  source: '01·核心指标看板!C5；01·核心指标看板!D5',
  source_note: '本月实际取看板 C 列',
};

function run(): AnalysisRun {
  return {
    id: 'r'.repeat(32), task_id: taskId, analysis_id: 'a'.repeat(32), schema_version: 1, created_at: '2026-10-09T06:20:00Z',
    execution_status: 'succeeded', reproducibility_status: 'verified', review_status: 'unreviewed', publication_status: 'draft',
    bindings: { pack: pack.id }, input_hashes: { pack: 'f'.repeat(64) }, engine: 'sql',
    result: {
      columns: Object.keys(row).map((name) => ({ name, type: typeof (row as Record<string, unknown>)[name] === 'number' ? 'DOUBLE' : 'VARCHAR' })),
      rows: [row], row_count: 1, truncated: false,
    },
  };
}

const analysis = { id: 'a'.repeat(32), task_id: taskId, schema_version: 1, created_at: '2026-10-09T06:00:00Z', question: '本月收入达成', sql: 'SELECT actual FROM pack', bindings: { pack: pack.id }, parameters: [], assumptions: [], grain: [], relationships: [], metrics: [] } as AnalysisRevision;

const context = (superseded: string[] = []): FigureSourceContext => ({ run: run(), analysis, datasets: [pack], superseded: new Set(superseded) });

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe('a figure\'s source', () => {
  it('reads the row\'s own source lines, the files the run read and how it was calculated', () => {
    const info = figureSource(context(), row, { metric: '收入', part: '实际', value: '1,234.50', facts: [['期间', '2026 年 8 月'], ['单位', '万元'], ['口径', '']] });
    expect(info.facts).toEqual([['期间', '2026 年 8 月'], ['单位', '万元']]);
    expect(info.sources).toEqual([['取数', row.source], ['说明', row.source_note]]);
    // The digest the run read the file at, not the file's current one.
    expect(info.files).toEqual([{ name: '8月套表', digest: 'f'.repeat(12), replaced: false }]);
    expect(info.method).toEqual({ label: 'SQL', text: 'SELECT actual FROM pack' });
    expect(info.computed).toContain('未阅');
    expect(info.stale).toBe(false);
  });

  it('says the figure waits to be recalculated once a file it read is replaced', () => {
    expect(runIsStale(context([pack.id]))).toBe(true);
    const info = figureSource(context([pack.id]), row, { metric: '收入', part: '实际', value: '1,234.50' });
    expect(info.files[0].replaced).toBe(true);
    expect(sourceText(info)).toContain('重新计算后才算数');
  });

  it('asks about the figure with its period and calculation, for the manager to edit', () => {
    const info = figureSource(context(), row, { metric: '收入', part: '实际', value: '1,234.50', facts: [['期间', '2026 年 8 月']] });
    expect(askAboutFigure(info)).toBe(`解释这个数：收入的实际（2026 年 8 月）是 1,234.50。它是怎么算出来的，取了哪些资料和单元格，用的什么口径？计算编号 ${'r'.repeat(32)}。`);
  });
});

describe('figures on a result', () => {
  it('open a source card from a KPI card and fill the conversation without sending', async () => {
    const asked = vi.fn();
    window.addEventListener(ASK_EVENT, asked);
    render(<BusinessResultView run={run()} source={context()} />);
    const cards = screen.getByLabelText('关键指标');
    fireEvent.click(within(cards).getByRole('button', { name: /收入实际 .*查看来源/ }));
    const card = await screen.findByLabelText('收入实际的来源');
    expect(within(card).getByText('8月套表')).toBeTruthy();
    expect(within(card).getByText(row.source)).toBeTruthy();
    fireEvent.click(within(card).getByRole('button', { name: /问助手解释/ }));
    expect(asked).toHaveBeenCalledTimes(1);
    expect(String((asked.mock.calls[0][0] as CustomEvent).detail)).toMatch(/^解释这个数：收入的实际/);
    window.removeEventListener(ASK_EVENT, asked);
  });

  it('stay plain figures when the page does not know the calculation', () => {
    render(<BusinessResultView run={run()} />);
    expect(screen.queryByRole('button', { name: /查看来源/ })).toBeNull();
  });

  it('mark every traced figure quieter when the run read a replaced file', () => {
    render(<BusinessResultView run={run()} source={context([pack.id])} />);
    const traced = screen.getAllByRole('button', { name: /查看来源/ });
    expect(traced.length).toBeGreaterThan(1);
    for (const button of traced) expect(button.getAttribute('data-stale')).toBe('true');
  });
});
