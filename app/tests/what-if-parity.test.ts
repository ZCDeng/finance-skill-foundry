/**
 * 倒推 and 敏感性 cards say the same of a run on the board and in the conversation. The board works them out here
 * (dashboardWhatIf.ts); the conversation on the server (foundry/what_if.py), held to the same cases by
 * tests/test_what_if.py.
 */
import { describe, expect, it } from 'vitest';
import type { SensitivityGrid } from '../src/views/analysis/CollectionHealthView.js';
import { goalBudget, goalCollection, linesOf, sensitivityView, type WhatIfRow } from '../src/views/analysis/dashboardWhatIf.js';
import cases from './fixtures/what-if-cases.json';

const keys = <T extends { basis: WhatIfRow[] }>(view: T) => ({ ...view, basis: view.basis.map((row) => row.metric_key) });

describe('倒推 and 敏感性 cards', () => {
  it('work back from a collection rate as the conversation does', () => {
    for (const row of cases.goals) {
      const view = goalCollection(linesOf(row.rows as unknown as WhatIfRow[], row.entity), row.entity, row.target ?? undefined, row.params as Record<string, string>);
      expect(keys(view), row.name).toEqual(row.view);
    }
  });

  it('work back from the revenue budget as the conversation does', () => {
    for (const row of cases.budgets) {
      expect(keys(goalBudget(linesOf(row.rows as unknown as WhatIfRow[], row.entity), row.entity)), row.name).toEqual(row.view);
    }
  });

  it('show the grid around where the entity stands as the conversation does', () => {
    for (const row of cases.grids) {
      expect(keys(sensitivityView(row.grid as unknown as SensitivityGrid, row.gap as unknown as WhatIfRow)), row.name).toEqual(row.view);
    }
  });
});
