import { describe, expect, it } from 'vitest';
import type { OverviewTask, TaskRow } from '../src/bridge.js';
import { stepLines } from '../src/views/cockpit/lines.js';
import { currentRow } from '../src/views/cockpit/Cockpit.js';
import { untried } from '../src/views/cockpit/TryCards.js';
import type { Step, StepState } from '../src/views/analysis/steps.js';

const task = (id: string, extra: Partial<TaskRow> = {}): TaskRow =>
  ({ id: id.repeat(32), title: id, period: '2026-09', skill_id: null, created_at: '2026-10-01T00:00:00Z', windows: 0, ...extra });
const states = (overrides: Partial<Record<Step, StepState>> = {}): Record<Step, StepState> =>
  ({ materials: 'done', scope: 'done', close: 'done', results: 'done', operations: 'done', report: 'done', ...overrides });
type Items = Record<string, { text: string; blocking: boolean; target?: string; scope?: Record<string, string> }[]>;
const row = (items: Items, extra: Partial<OverviewTask> = {}): OverviewTask => ({
  task: task('a'), todo: [],
  blocks: ['scope', 'source', 'structure', 'controls', 'exceptions', 'review'].map((key) => ({ key, label: key, state: 'done' as const, items: items[key] ?? [] })),
  work: { runs: [], cards: [], drafts: 0, datasets: 2 }, ...extra,
});
const digest = (extra: Record<string, unknown>) => ({ execution_status: 'succeeded', engine: 'finance', role: '', columns: ['actual'], rows: true, outputs: false, ...extra });

describe('the line under each step on 总览', () => {
  it('says what the month close holds: the files and their structures, the scope in words, the controls and differences', () => {
    const lines = stepLines(row({
      structure: [{ text: '月结.xlsx 的表结构等你确认', blocking: true }],
      scope: [{ text: '2026-09 · 华宸 · 万元 · CNY', blocking: false, scope: { period: '2026-09', organization: '华宸', unit: '万元', currency: 'CNY' } }],
      controls: [{ text: '应收滚动：待外部确认', blocking: true }, { text: '已确认 6 条，相符 5 条', blocking: false }],
      exceptions: [{ text: '收入勾稽：差异待处理，差额 1200', blocking: true }],
    }), states());
    expect(lines.materials).toBe('2 份资料，1 份表结构等你确认');
    expect(lines.scope).toBe('2026 年 9 月 · 华宸 · 万元 · CNY');
    expect(lines.close).toBe('已确认 6 条，相符 5 条；1 条控制待处理，1 处差异待处置');
    const clear = stepLines(row({ structure: [{ text: '已确认', blocking: false }], controls: [{ text: '已确认 6 条，相符 6 条', blocking: false }] }), states());
    expect(clear.materials).toBe('2 份资料，表结构都已确认');
    expect(clear.close).toBe('已确认 6 条，相符 6 条，没有未处置的差异');
  });

  it('before any file, says what comes first', () => {
    const lines = stepLines(row({ scope: [{ text: '期间未确认', blocking: true }, { text: '单位未确认', blocking: true }],
      controls: [{ text: '还没有确认的勾稽控制', blocking: true }] }, { work: { runs: [], cards: [], drafts: 0, datasets: 0 } }), states());
    expect([lines.materials, lines.scope, lines.close]).toEqual(['还没有资料', '先加资料，再确认范围', '先加资料']);
    const missing = stepLines(row({ scope: [{ text: '期间未确认', blocking: true }, { text: '单位未确认', blocking: true }] }), states());
    expect(missing.scope).toBe('期间、单位还没确认');
  });

  it('names the questions answered, the radar\'s lights, the board and the drafts, and what waits on each', () => {
    const work = { runs: [digest({ label: '管理损益', analysis_id: 'p' }), digest({ label: '管理损益', analysis_id: 'p' }), digest({ label: '预算差异', analysis_id: 'b' }),
      digest({ label: '费用明细', analysis_id: 'e' }), digest({ label: '回款健康', analysis_id: 'h', scenario_kind: 'collection_health' })],
      cards: [{ state: 'accepted', kind: 'figure' }, { state: 'pinned', kind: 'figure' }, { state: 'pinned', kind: 'scenario' }, { state: 'explore', kind: 'figure' }], drafts: 2, datasets: 1 };
    const lines = stepLines(row({}, { work, health: { run_id: 'h', levels: { red: 2, orange: 1, green: 9 } },
      todo: [{ kind: 'review', text: '计算要按新资料重算', target: 'results' }] }), states());
    expect(lines.results).toBe('已算：费用明细、预算差异 等 3 项；1 件等你处理');
    expect(lines.operations).toBe('回款健康：风险雷达 2 个红色、1 个橙色');
    expect(lines.report).toBe('看板 3 张卡，1 张待认可；文稿 2 版');
    const quiet = stepLines(row({}, { work: { ...work, runs: [], cards: [], drafts: 0 }, health: { run_id: 'h', levels: { green: 5 } } }), states());
    expect([quiet.results, quiet.operations, quiet.report]).toEqual(['还没有财务分析结果', '回款健康：风险雷达 5 个主体都是绿色', '看板还没有卡']);
    expect(stepLines(row({}), states({ report: 'skipped' })).report).toBe('本期不做');
  });
});

describe('which task 总览 opens on', () => {
  it('opens on the task worked on last, or the one chosen while it is still there', () => {
    const rows = [row({}, { task: task('a'), active_at: '2026-10-02T00:00:00Z' }), row({}, { task: task('b'), active_at: '2026-10-05T00:00:00Z' }), row({}, { task: task('c') })];
    expect(currentRow(rows, null)?.task.id).toBe(task('b').id);
    expect(currentRow(rows, task('c').id)?.task.id).toBe(task('c').id);
    expect(currentRow(rows, task('z').id)?.task.id).toBe(task('b').id);
    expect(currentRow([], null)).toBeNull();
  });

  it('offers features no real task used and the preferences do not keep, three at most', () => {
    const real = row({}, { task: task('a'), tried: ['scenario', 'billing'] });
    const example = row({}, { task: task('b', { sample: 'reference' } as Partial<TaskRow>), tried: ['goal', 'snapshot', 'recompute'] });
    expect(untried([real, example], ['source']).map((item) => item.feature)).toEqual(['goal', 'present', 'snapshot']);
    expect(untried([row({}, { tried: ['scenario', 'goal', 'billing', 'snapshot', 'recompute'] })], ['source', 'present'])).toEqual([]);
  });
});
