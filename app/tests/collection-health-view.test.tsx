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
    expect(healthHeadline(rows)).toBe('11 个主体中 5 个收缴率低于自身生死线');
    const group = rows.filter((row) => row.entity === '集团');
    expect(healthHeadline(group)).toBe('集团本年账单收缴率比生死线低 3.22 个百分点，每收 100 元倒贴现金');
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
