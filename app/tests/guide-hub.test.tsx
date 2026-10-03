// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { GUIDE_ARTICLES, searchArticles } from '../src/views/guide/articles.js';
import { GUIDE_EVENT, GuideHub, HelpLink } from '../src/views/guide/GuideHub.js';

afterEach(cleanup);

// The audit's bar: at least 30 words a finance manager would search for, each finding something.
const WORDS = [
  '期间', '收缴率', '损坏', '未阅', '范围', '单位', '万元', '币种', '组织', '快照', '原文件', '表头', '合计行', '明细',
  '勾稽', '差异', '确认单', '编制方', '接受差异', '复核', '月结', '可提交', '导出', 'PDF', 'Word', 'Excel', '下钻',
  '版本', '模型未配置', '归档', '快捷键', '来源核验', '数值引用', '执行成功', '舍入', '1-8月', '对不上',
];

it('finds something for every word on the list', () => {
  expect(WORDS.length).toBeGreaterThanOrEqual(30);
  const missing = WORDS.filter((word) => searchArticles(word).length === 0);
  // 收缴率 is the one business word the guide does not explain; it should say so rather than guess.
  expect(missing).toEqual(['收缴率']);
});

it('matches every word typed, not any', () => {
  expect(searchArticles('期间 累计').map((row) => row.id)).toEqual(['scope']);
  expect(searchArticles('期间 不存在的词')).toEqual([]);
});

it('opens at the article a 「?」 asked for and shows where it applies', () => {
  render(<GuideHub article="controls" onOpen={vi.fn()} onClose={vi.fn()} />);
  expect(screen.getByRole('heading', { name: '勾稽控制与差异处置' })).toBeTruthy();
  expect(screen.getByText('适用于：月结页 · 勾稽控制')).toBeTruthy();
});

it('says plainly when a search finds nothing', () => {
  render(<GuideHub onOpen={vi.fn()} onClose={vi.fn()} />);
  fireEvent.change(screen.getByLabelText('搜索使用指南'), { target: { value: '收缴率' } });
  expect(screen.getByRole('status').textContent).toBe('没有找到「收缴率」相关的说明。');
});

it('moves the workspace to the place an article describes, without running anything', () => {
  const onOpen = vi.fn();
  render(<GuideHub article="month-close" onOpen={onOpen} onClose={vi.fn()} />);
  fireEvent.click(screen.getByRole('button', { name: /打开月结页/ }));
  expect(onOpen).toHaveBeenCalledWith('close');
});

it('closes on Escape', () => {
  const onClose = vi.fn();
  render(<GuideHub onOpen={vi.fn()} onClose={onClose} />);
  fireEvent.keyDown(screen.getByLabelText('搜索使用指南'), { key: 'Escape' });
  expect(onClose).toHaveBeenCalled();
});

it('shows that the statuses do not stand in for one another', () => {
  render(<GuideHub article="statuses" onOpen={vi.fn()} onClose={vi.fn()} />);
  expect(screen.getByLabelText('执行成功不等于数值已引用不等于来源已核验不等于经理已复核不等于可发布')).toBeTruthy();
});

it('a 「?」 asks the window for its article', () => {
  const heard = vi.fn();
  window.addEventListener(GUIDE_EVENT, (event) => heard((event as CustomEvent).detail));
  render(<HelpLink article="scope" label="分析范围与期间" />);
  fireEvent.click(screen.getByRole('button', { name: '使用指南：分析范围与期间' }));
  expect(heard).toHaveBeenCalledWith('scope');
});

it('every article names where it applies and every link goes somewhere the workspace has', () => {
  for (const article of GUIDE_ARTICLES) {
    expect(article.appliesTo).toBeTruthy();
    for (const block of article.body) if (block.kind === 'open') expect(['datasets', 'scope', 'structure', 'results', 'drafts', 'close']).toContain(block.target);
  }
});
