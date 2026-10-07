// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import { ReadinessPanel } from '../src/views/analysis/ReadinessPanel.js';
import { ExplanationQualityPanel, type ExplanationFact, type ExplanationQuality } from '../src/views/analysis/ExplanationQualityPanel.js';
import { countSummary, EVIDENCE_LABELS, evidenceLabelText } from '../src/views/analysis/evidenceLabels.js';

afterEach(() => { cleanup(); delete (globalThis as { foundry?: unknown }).foundry; });

const scope = (period: string) => ({ ledger: '', organization: '', period, currency: 'CNY', unit: '元' });
const report = {
  proposed_scope: scope(''),
  datasets: [
    { dataset_id: 'a'.repeat(32), name: '8月总账', scope: scope('2026-08'), missing_fields: [], can_run: ['control_totals'], blocked: [],
      as_of: null, as_of_source: null, period_kind: 'month', freshness: { state: 'current', reasons: [] } },
    { dataset_id: 'b'.repeat(32), name: '7月总账', scope: scope('2026-07'), missing_fields: [], can_run: [], blocked: [],
      as_of: null, as_of_source: null, period_kind: 'month',
      freshness: { state: 'period_mismatch', reasons: [{ code: 'period_differs', text: '资料期间 2026-07 与分析期间 2026-08 不同' }] } },
    { dataset_id: 'c'.repeat(32), name: '余额表', scope: scope(''), missing_fields: [], can_run: [], blocked: [],
      as_of: '2026-08-20', as_of_source: 'title', period_kind: 'as_of',
      freshness: { state: 'source_stale', reasons: [{ code: 'as_of_before_period_end', text: '截至日 2026-08-20 早于期末 2026-08-31' }] } },
    { dataset_id: 'd'.repeat(32), name: '预算', scope: scope(''), missing_fields: ['period'], can_run: [], blocked: [],
      as_of: null, period_kind: null, freshness: { state: 'unknown', reasons: [{ code: 'no_dataset_period', text: '资料没有声明期间或截至日' }] } },
    // A source refresh whose rows carry no period column: the period is the one the refresh was for.
    { dataset_id: 'f'.repeat(32), name: 'ERP 刷新', scope: scope(''), missing_fields: ['period'], can_run: [], blocked: [],
      period: '2026-08', as_of: '2026-09-05', as_of_source: 'source_refresh', period_kind: 'month', freshness: { state: 'current', reasons: [] } },
    // An older CLI: none of the new fields.
    { dataset_id: 'e'.repeat(32), name: '旧版报告', scope: scope('2026-08'), missing_fields: [], can_run: [], blocked: [] },
  ],
  can_run: ['control_totals'], blocked: [], file_identity_policy: 'snapshot_only', diagnostics: [], erp_connected: false,
};

function mountReadiness(value: unknown) {
  const financeCall = vi.fn(async () => ({ ok: true, value }));
  (globalThis as { foundry?: unknown }).foundry = { financeCall };
}

describe('readiness: as-of, period and freshness per file', () => {
  it('names the as-of date and period and says in words whether each file is current', async () => {
    mountReadiness(report);
    render(<ReadinessPanel taskId="t" />);
    await screen.findByText('这批资料能算什么');
    expect(screen.getByRole('columnheader', { name: '截至日 / 期间' })).toBeTruthy();
    expect(screen.getByRole('columnheader', { name: '时效' })).toBeTruthy();

    const current = screen.getByRole('row', { name: /8月总账/ });
    expect(current.textContent).toContain('期间 2026 年 8 月 · 月度');
    expect(current.querySelector('.analysis-readiness-freshness--current')?.textContent).toBe('当前');

    const july = screen.getByRole('row', { name: /7月总账/ });
    const mismatch = july.querySelector('.analysis-readiness-freshness--warning')!;
    expect(mismatch.textContent).toBe('期间不符（资料期间 2026-07 与分析期间 2026-08 不同）');
    // Words and an icon, never colour alone.
    expect(mismatch.querySelector('svg')).toBeTruthy();

    const balance = screen.getByRole('row', { name: /余额表/ });
    expect(balance.textContent).toContain('截至 2026-08-20（来自标题） · 时点');
    expect(balance.textContent).toContain('资料过期（截至日 2026-08-20 早于期末 2026-08-31）');

    const budget = screen.getByRole('row', { name: /预算/ });
    expect(budget.querySelector('.analysis-readiness-freshness--unknown')?.textContent).toBe('未声明（资料没有声明期间或截至日）');

    const refreshed = screen.getByRole('row', { name: /ERP 刷新/ });
    expect(refreshed.textContent).toContain('截至 2026-09-05（刷新截止） · 期间 2026 年 8 月 · 月度');
    expect(refreshed.querySelector('.analysis-readiness-freshness--current')?.textContent).toBe('当前');
    expect(screen.getByRole('button', { name: '使用指南：资料时效与证据标签' })).toBeTruthy();
  });

  it('says it cannot judge, rather than that the file left something out, while the analysis period is missing', async () => {
    mountReadiness({ ...report, datasets: [{ ...report.datasets[0],
      freshness: { state: 'unknown', reasons: [{ code: 'no_task_period', text: '分析期间还没确认，无法判断时效' }] } }] });
    render(<ReadinessPanel taskId="t" />);
    await screen.findByText('这批资料能算什么');
    const row = screen.getByRole('row', { name: /8月总账/ });
    expect(row.querySelector('.analysis-readiness-freshness--unknown')?.textContent).toBe('无法判断（分析期间还没确认，无法判断时效）');
    expect(row.textContent).toContain('期间 2026 年 8 月 · 月度');
  });

  it('shows a dash for a file an older CLI reported without freshness', async () => {
    mountReadiness(report);
    render(<ReadinessPanel taskId="t" />);
    await screen.findByText('这批资料能算什么');
    const old = screen.getByRole('row', { name: /旧版报告/ });
    const cells = within(old).getAllByRole('cell');
    expect(cells[1].textContent).toBe('期间 2026 年 8 月');
    expect(cells[2].textContent).toBe('—');
  });
});

const fact = (id: string, row: number): ExplanationFact => ({ id, run_id: 'r'.repeat(32), row, column: 'actual', display_value: `${100 + row} 万元`, label: 'revenue' });
const FACTS = [fact('1'.repeat(64), 0), fact('2'.repeat(64), 1)];

function quality(extra: Partial<ExplanationQuality>): ExplanationQuality {
  return { status: 'pass', issues: [], checks: { numbers: { status: 'pass' }, coverage: { status: 'pass' }, provenance: { status: 'pass' } }, ...extra };
}

function panel(value: ExplanationQuality | null, state: 'passed' | 'issues' | 'stale' = 'passed') {
  return render(<ExplanationQualityPanel taskId="t" quality={value} state={state} facts={FACTS} citedFactIds={FACTS.map((row) => row.id)}
    factDetails={{}} locatorNotice={{}} locatorPdf={null} busy={false} onRecheck={vi.fn()} onOpenFact={vi.fn()} onOpenLocator={vi.fn()} />);
}

const LABELLED = quality({
  evidence_labels: [
    { key: { kind: 'claim', claim_index: 0, basis: 'user_assumption' }, label: 'assumption_user_provided', text: '用户假设',
      base_label: 'assumption_user_provided', reasons: [{ code: 'claim_assumption', text: '按假设写入，没有来源可核对' }] },
    { key: { kind: 'fact', fact_id: '1'.repeat(64), run_id: 'r'.repeat(32), row: 0, column: 'actual' }, label: 'fact_provider_standardized',
      text: '标准化数据', base_label: 'fact_provider_standardized', reasons: [{ code: 'engine_finance', text: '财务引擎按科目映射汇总的结果' }] },
    { key: { kind: 'fact', fact_id: '2'.repeat(64), run_id: 'r'.repeat(32), row: 1, column: 'actual' }, label: 'stale_source',
      text: '过期来源', base_label: 'fact_provider_standardized', reasons: [{ code: 'older_run', text: '引用的是旧一版计算结果，同一计算之后又算过' }] },
    { key: { kind: 'claim', claim_index: 1, basis: 'calculation', run_id: 'r'.repeat(32), row: 0, column: 'total' },
      label: 'derived_calculation', text: '派生计算', base_label: 'derived_calculation',
      reasons: [{ code: 'run_calculation', text: '由一次计算得出，引用值与结果一致' }] },
    { key: { kind: 'number', text: '999', position: 3 }, label: 'unknown', text: '未知', base_label: 'unknown',
      reasons: [{ code: 'uncited_number', text: '正文数字「999」没有绑定到事实或引用' }] },
  ],
  evidence_posture: { level: 'preliminary', text: '初步', rules_version: '1',
    counts: { fact_provider_standardized: 1, assumption_user_provided: 1, stale_source: 1, unknown: 1 },
    drivers: [{ code: 'stale_source', text: '过期来源 1 项' }, { code: 'unknown', text: '未知 1 项' }] },
});

describe('quality panel: evidence posture and label chips', () => {
  it('says the posture is a classification of the evidence and not the manager approving anything', () => {
    panel(LABELLED);
    const block = screen.getByRole('region', { name: '证据等级' });
    expect(within(block).getByText('证据等级：初步')).toBeTruthy();
    expect(within(block).getByText('这是对引用依据的分类，不代表经理认可。')).toBeTruthy();
    expect(within(block).getByRole('list', { name: '证据等级的依据' }).textContent).toBe('过期来源 1 项未知 1 项');
    expect(within(block).getByLabelText('依据分类计数').textContent).toBe('标准化数据 1 · 用户假设 1 · 过期来源 1 · 未知 1');
    expect(within(block).getByRole('button', { name: '使用指南：证据标签与证据等级' })).toBeTruthy();
    // The checks keep their own words; the posture is not folded into them.
    expect(screen.getByLabelText('待处理核对').textContent).not.toContain('初步');
  });

  it('puts a chip on each fact card, with the reason in words for a stale one', () => {
    panel(LABELLED);
    const first = screen.getByRole('article', { name: `事实 ${'1'.repeat(64)}` });
    const chip = first.querySelector('[data-slot="badge"]')!;
    expect(chip.textContent).toBe('证据标签：标准化数据');
    expect(chip.getAttribute('data-variant')).toBe('outline');
    expect(chip.getAttribute('title')).toBe('财务引擎按科目映射汇总的结果');

    const second = screen.getByRole('article', { name: `事实 ${'2'.repeat(64)}` });
    const stale = second.querySelector('[data-slot="badge"]')!;
    expect(stale.textContent).toBe('证据标签：过期来源（原为标准化数据）');
    expect(stale.getAttribute('data-variant')).toBe('destructive');
    expect(stale.querySelector('svg')).toBeTruthy();
    expect(second.textContent).toContain('引用的是旧一版计算结果，同一计算之后又算过');
  });

  it('lists the claims and the other labelled items once, leaving facts to their cards', () => {
    panel(LABELLED);
    const block = screen.getByRole('region', { name: '证据等级' });
    expect(within(block).getByText('依据分类 · 3 项')).toBeTruthy();
    const items = within(block).getAllByRole('listitem').filter((item) => item.closest('.analysis-evidence-list'));
    expect(items.map((item) => item.textContent)).toEqual([
      '引用 1 · 用户假设证据标签：用户假设按假设写入，没有来源可核对',
      '引用 2 · 计算 · 结果第 1 行 · total证据标签：派生计算由一次计算得出，引用值与结果一致',
      '正文数字「999」证据标签：未知正文数字「999」没有绑定到事实或引用',
    ]);
  });

  it('marks an unsupported posture with the warning words and icon', () => {
    panel(quality({ evidence_labels: [], evidence_posture: { level: 'unsupported', text: '无法支持', counts: { contradicted_source: 1 },
      drivers: [{ code: 'contradicted_source', text: '矛盾来源 1 项' }] } }), 'issues');
    const block = screen.getByRole('region', { name: '证据等级' });
    expect(block.getAttribute('data-level')).toBe('unsupported');
    expect(block.querySelector('.analysis-evidence-posture-line svg')).toBeTruthy();
    expect(within(block).getByText('证据等级：无法支持')).toBeTruthy();
  });

  it('says the posture is from before the edit while the draft waits for a recheck', () => {
    panel(LABELLED, 'stale');
    expect(screen.getByText('证据等级：初步（改稿前的分类，重检后更新）')).toBeTruthy();
  });

  it('renders nothing new for a check from an older CLI', () => {
    panel(quality({}));
    expect(screen.queryByRole('region', { name: '证据等级' })).toBeNull();
    expect(document.querySelector('.analysis-fact-card [data-slot="badge"]')).toBeNull();
    cleanup();
    panel(quality({ evidence_labels: 'broken' as never, evidence_posture: {} }));
    expect(screen.queryByRole('region', { name: '证据等级' })).toBeNull();
  });
});

describe('label words', () => {
  it('counts in the label order and falls back to 未知', () => {
    expect(countSummary({ unknown: 2, fact_source_reported: 3, derived_calculation: 0, estimate: 1 })).toBe('来源原文 3 · 估算 1 · 未知 2');
    expect(countSummary(undefined)).toBe('');
    expect(evidenceLabelText('no_such_code')).toBe('未知');
    expect(Object.keys(EVIDENCE_LABELS)).toHaveLength(12);
  });
});
