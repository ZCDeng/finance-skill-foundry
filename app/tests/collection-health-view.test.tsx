// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import type { AnalysisRun } from '../src/bridge.js';
import {
  CollectionHealthView, healthHeadline, isCollectionHealthRun, type HealthRow,
} from '../src/views/analysis/CollectionHealthView.js';
import fixture from './fixtures/collection-health-run.json';

// A collection_health run on a property group's dashboard and ten city companies of its 11·城市公司明细表.
const run = fixture as unknown as AnalysisRun;

afterEach(cleanup);

describe('回款与现金', () => {
  it('claims only a finance collection_health run', () => {
    expect(isCollectionHealthRun(run)).toBe(true);
    expect(isCollectionHealthRun({ ...run, engine: 'python' })).toBe(false);
    expect(isCollectionHealthRun({ ...run, result: { ...run.result!, scenario_kind: 'cash_13_weeks' } as never })).toBe(false);
  });

  it('says how many units sit below their own break-even line', () => {
    const rows = (run.result as unknown as { rows: HealthRow[] }).rows;
    // The group total is named on its own, never counted with the city companies it sums.
    expect(healthHeadline(rows)).toBe('明细 10 个主体中 4 个收缴率低于自身生死线；集团本年账单收缴率比生死线低 3.22 个百分点，每收 100 元倒贴现金');
    const group = rows.filter((row) => row.entity === '集团');
    expect(healthHeadline(group)).toBe('集团本年账单收缴率比生死线低 3.22 个百分点，每收 100 元倒贴现金');
    const onTheLine = group.map((row) => row.metric_key === 'collection_gap' && row.scenario === '本期'
      ? { ...row, value: '0.0000001', display_value: '+0.00 个百分点' } : row);
    expect(healthHeadline(onTheLine)).toBe('集团本年账单收缴率正好在生死线上');
  });

  it('lists units from furthest below the line, with the run’s own figures and lights', () => {
    render(<CollectionHealthView run={run} actions={null} technical={[]} />);
    const table = screen.getByRole('table', { name: /生死线定位/ });
    const bodyRows = within(table).getAllByRole('row').slice(1);
    expect(within(bodyRows[0]).getByRole('rowheader').textContent).toBe('兰州城市公司');
    expect(within(bodyRows[bodyRows.length - 1]).getByRole('rowheader').textContent).toBe('上海城市公司');
    // A negative gap keeps its sign beside its unit and reads in the negative red.
    const worst = within(bodyRows[0]).getByText('-6.94 个百分点');
    expect(worst.className).toContain('fnd-figure--negative');
    expect(within(bodyRows[0]).getAllByText('红').length).toBeGreaterThan(0);
  });

  it('draws the scatter and the group’s sensitivity grid with the current cell marked', () => {
    render(<CollectionHealthView run={run} actions={null} technical={[]} />);
    expect(screen.getByRole('img', { name: /收缴率与毛利率散点/ })).toBeTruthy();
    const grid = screen.getByRole('table', { name: /集团现金经营利润率/ });
    const current = grid.querySelector('[aria-current="true"]');
    expect(current?.textContent).toMatch(/^\(/); // 18% margin at 87.5%: below the line
    expect(screen.getByText(/红黄绿是筛查提示/)).toBeTruthy();
  });
});

describe('回款与现金 edges', () => {
  it('frames no cell when the current position lies off the grid, and marks estimates in the table', () => {
    const result = run.result as unknown as { rows: HealthRow[]; sensitivity: { current: Record<string, string | null> }[] };
    const offGrid = {
      ...run,
      result: {
        ...run.result!,
        sensitivity: [{ ...result.sensitivity[0], current: { gross_margin: '0.45', collection_rate: '0.8' } }],
        rows: result.rows.map((row) => row.entity === '上海城市公司' && row.metric_key === 'gross_margin' ? { ...row, estimate: true } : row),
      },
    } as unknown as AnalysisRun;
    render(<CollectionHealthView run={offGrid} actions={null} technical={[]} />);
    const grid = screen.getByRole('table', { name: /当前位置不在表内/ });
    expect(grid.querySelector('[aria-current="true"]')).toBeNull();
    const shanghai = within(screen.getByRole('table', { name: /生死线定位/ })).getByRole('rowheader', { name: '上海城市公司' }).closest('tr')!;
    expect(within(shanghai).getByText('估算')).toBeTruthy();
  });
});
