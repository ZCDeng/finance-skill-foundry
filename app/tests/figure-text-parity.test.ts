/**
 * The figures the assistant's cards print are written on the server (foundry/figure_text.py, foundry/answer_cards.py),
 * a port of these rules. The shared cases hold both sides to one answer: here the renderer is held to them, and
 * tests/test_figure_text.py holds the port.
 */
import { describe, expect, it } from 'vitest';
import type { AnalysisRun } from '../src/bridge.js';
import { accountingFigure, groupDigits } from '../src/lib/figures.js';
import { formatPeriod } from '../src/lib/period.js';
import { businessColumnLabel, columnSemantics, formatBusinessCell } from '../src/views/analysis/businessResults.js';
import type { DashboardCard } from '../src/views/analysis/dashboardModel.js';
import { figureView, rankItems } from '../src/views/analysis/dashboardViews.js';
import { profitBridges } from '../src/views/analysis/RunPanel.js';
import cases from './fixtures/figure-text-cases.json';
import health from './fixtures/collection-health-run.json';

type Cell = { value: unknown; column: string; row: Record<string, unknown>; text: string };
const runs = { ...cases.runs, health } as unknown as Record<string, AnalysisRun>;

describe('the figures a card in the conversation prints', () => {
  it('reads each cell as the result area writes it', () => {
    for (const cell of cases.cells as Cell[]) {
      expect(formatBusinessCell(cell.value, { name: cell.column, label: businessColumnLabel(cell.column), semantics: columnSemantics(cell.column) }, cell.row), cell.column)
        .toBe(cell.text);
    }
  });

  it('writes negatives, periods and grouped digits the same way', () => {
    for (const row of cases.accounting) expect(accountingFigure(row.text), row.text).toMatchObject({ text: row.shown, negative: row.negative });
    for (const row of cases.periods) expect(formatPeriod(row.value)).toBe(row.text);
    for (const row of cases.digits) expect(groupDigits(row.value)).toBe(row.text);
  });

  it('draws figure, rank and bridge cards as the board draws them', () => {
    for (const row of cases.figures) {
      const view = figureView({ kind: 'figure', select: row.select } as unknown as DashboardCard, runs[row.run])!;
      expect({ subject: view.subject, part: view.part, value: view.value, beside: view.beside.slice(0, 6), level: view.level ?? null, level_label: view.levelLabel ?? null })
        .toEqual(row.view);
    }
    for (const row of cases.ranks) {
      const { items, unit } = rankItems({ kind: 'rank', select: row.select } as unknown as DashboardCard, runs[row.run]);
      expect({ unit, items: items.map((item) => ({ label: item.label, value: item.value, text: item.text, note: item.note ?? null })) }).toEqual(row.view);
    }
    for (const row of cases.bridges) {
      const [bridge] = profitBridges(runs[row.run]);
      expect({ unit: bridge.unit, steps: bridge.steps.map((step) => ({ label: step.label, kind: step.kind, value: step.value, text: step.text })) }).toEqual(row.view);
    }
  });
});
