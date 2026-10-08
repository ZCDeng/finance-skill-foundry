// @vitest-environment jsdom
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { GUIDE_ARTICLES, type GuideBlock } from '../src/views/guide/articles.js';
import { GuideHub } from '../src/views/guide/GuideHub.js';

afterEach(cleanup);

/** The figures the backend tests compute; the guide must print the same ones. */
const EXPECTED = JSON.parse(readFileSync(resolve(process.cwd(), '../foundry/resources/demo_pack/expected.json'), 'utf8'));
const route = GUIDE_ARTICLES.filter((row) => row.section === '跟着做：华宸物业 8 月');
const seen = (id: string) => route.find((row) => row.id === id)!.body
  .flatMap((block: GuideBlock) => block.kind === 'expect' ? block.items : []).join('\n');
const money = (value: string) => Number(value).toLocaleString('en-US', { maximumFractionDigits: 2 });

it('walks nine steps, each saying what the reader should see', () => {
  expect(route.map((row) => row.id)).toEqual(Array.from({ length: 9 }, (_, index) => `follow-${index + 1}`));
  for (const row of route) expect(seen(row.id), row.id).not.toBe('');
});

it('prints the figures the engine computes for the example', () => {
  expect(seen('follow-2')).toContain(`${EXPECTED.formula_issues} 类提示`);
  const { confirmed, pass, breaks } = EXPECTED.controls;
  expect(seen('follow-5')).toContain(`${confirmed} 条控制，${pass} 条相符，${breaks} 处差异`);
  expect(seen('follow-5')).toContain(`${money(EXPECTED.f01_difference)} 万元`);
  expect(seen('follow-5')).toContain(`少 ${money(EXPECTED.f02_difference.replace('-', ''))} 万元`);
  expect(seen('follow-5')).toContain(`多 ${money(EXPECTED.ar_rollforward_difference)} 万元`);
  expect(seen('follow-6')).toContain(`生死线 ${EXPECTED.break_even_collection}%`);
  expect(seen('follow-6')).toContain(`低于生死线 ${EXPECTED.collection_gap.replace('-', '')} 个百分点`);
  expect(seen('follow-6')).toContain(`综合收缴率低 ${EXPECTED.collection_gap_total.replace('-', '')} 个百分点`);
  const { red, orange, yellow, green } = EXPECTED.radar;
  expect(seen('follow-6')).toContain(`红 ${red}、橙 ${orange}、黄 ${yellow}、绿 ${green}`);
  expect(seen('follow-7')).toContain(`多 ${EXPECTED.office_price_quantity_gap} 万元`);
  expect(seen('follow-8')).toContain(`${money(EXPECTED.report_operating_cost)} 元`);
  expect(seen('follow-8')).toContain(`${money(EXPECTED.report_operating_cash_flow)} 万元`);
  expect(seen('follow-8')).toContain(`${money(EXPECTED.book_operating_cash_flow)} 万元`);
  const { matched, auto_apply: auto, differs } = EXPECTED.next_month;
  expect(seen('follow-9')).toContain(`${matched} 张表`);
  expect(seen('follow-9')).toContain(`其中 ${auto} 张直接套用`);
  expect(seen('follow-9')).toContain(`「${differs}」`);
});

it('opens the reference at the same place, and says a failed build next to the button', async () => {
  const reference = vi.fn().mockRejectedValueOnce(new Error('参考结果生成失败')).mockResolvedValue(undefined);
  render(<GuideHub article="follow-5" onOpen={() => undefined} onClose={() => undefined} onReference={reference} />);
  expect(screen.getByRole('heading', { name: '你应该看到' })).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: '对照参考结果的月结' }));
  await waitFor(() => expect(screen.getByRole('alert').textContent).toBe('参考结果生成失败'));
  expect(reference).toHaveBeenCalledWith('close');
});

it('makes the September task from the last step', async () => {
  const nextMonth = vi.fn().mockResolvedValue(undefined);
  render(<GuideHub article="follow-9" onOpen={() => undefined} onClose={() => undefined} onNextMonth={nextMonth} />);
  fireEvent.click(screen.getByRole('button', { name: '建 9 月练习任务' }));
  await waitFor(() => expect(nextMonth).toHaveBeenCalledOnce());
});

it('leaves a button out where this build cannot do it', () => {
  render(<GuideHub article="follow-9" onOpen={() => undefined} onClose={() => undefined} />);
  expect(screen.queryByRole('button', { name: '建 9 月练习任务' })).toBeNull();
});
