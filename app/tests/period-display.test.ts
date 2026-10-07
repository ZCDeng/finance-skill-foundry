import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

// A tripwire, not a proof. Where the interface shows a task's or a file's period it goes
// through formatPeriod (or PeriodWords / ScopeSummary, which call it; DESIGN.md). This
// catches the plain ways of printing one as stored, `{task.period}`, `期间 ${scope.period}`,
// `[row.period, …]`, `{periods.join(…)}`, in the files that show periods today. It misses
// `{task.period ?? ''}`, a period read into a local variable first, and any new file not
// listed here. Inputs, stored values and what goes to the assistant are not listed.
const DISPLAYS = [
  'src/components/Workspace.tsx',
  'src/views/Tasks.tsx',
  'src/views/TaskDetail.tsx',
  'src/views/Workbench.tsx',
  'src/views/Deliverables.tsx',
  'src/views/analysis/ReadinessPanel.tsx',
  'src/views/analysis/ScopePanel.tsx',
  'src/views/analysis/StructureProposalCard.tsx',
  'src/views/analysis/WorkbookBrowser.tsx',
  'src/views/analysis/FinanceBackgroundPanel.tsx',
  'src/views/analysis/MonthCloseControlCenter.tsx',
  'src/views/analysis/MaterialsFileList.tsx',
  'src/views/analysis/shared.ts',
];

describe('period display', () => {
  it.each(DISPLAYS)('%s shows no period as stored', (file) => {
    const source = readFileSync(resolve(file), 'utf8');
    expect(source).toMatch(/formatPeriod|PeriodWords|ScopeSummary/);
    // `value={row.period}` hands the stored value to a component; it is not printed.
    expect(source).not.toMatch(/(?<!=)\{\s*[\w.?]+\.period\s*\}/);
    expect(source).not.toMatch(/期间 \$\{\s*[\w.?]+\.period\s*\}/);
    expect(source).not.toMatch(/\[\s*[\w.?]+\.period\s*,/);
    expect(source).not.toMatch(/\{periods\.join\(/);
  });
});
