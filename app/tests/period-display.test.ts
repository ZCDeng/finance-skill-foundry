import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

// Where the interface shows a task's or a file's period, it goes through formatPeriod
// (DESIGN.md). A new line written as `{task.period}` or `期间 ${scope.period}` would show
// 2026-08 again; inputs, stored values and what goes to the assistant are not listed here.
const DISPLAYS = [
  'src/components/Workspace.tsx',
  'src/views/Tasks.tsx',
  'src/views/TaskDetail.tsx',
  'src/views/Workbench.tsx',
  'src/views/analysis/ReadinessPanel.tsx',
  'src/views/analysis/ScopePanel.tsx',
  'src/views/analysis/StructureProposalCard.tsx',
  'src/views/analysis/WorkbookBrowser.tsx',
  'src/views/analysis/FinanceBackgroundPanel.tsx',
];

describe('period display', () => {
  it.each(DISPLAYS)('%s shows no period as stored', (file) => {
    const source = readFileSync(resolve(file), 'utf8');
    expect(source).toContain('formatPeriod');
    expect(source).not.toMatch(/\{\s*[\w.?]+\.period\s*\}/);
    expect(source).not.toMatch(/期间 \$\{\s*[\w.?]+\.period\s*\}/);
    expect(source).not.toMatch(/\[\s*[\w.?]+\.period\s*,/);
    expect(source).not.toMatch(/\{periods\.join\(/);
  });
});
