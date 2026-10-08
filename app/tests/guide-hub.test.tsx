// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { GUIDE_ARTICLES, GUIDE_SECTIONS, searchArticles } from '../src/views/guide/articles.js';
import { GUIDE_EVENT, GuideHub, HelpLink } from '../src/views/guide/GuideHub.js';

afterEach(cleanup);

// The audit's bar: at least 30 words a finance manager would search for, each finding something.
const WORDS = [
  '期间', '收缴率', '损坏', '未阅', '范围', '单位', '万元', '币种', '组织', '快照', '原文件', '表头', '合计行', '明细',
  '勾稽', '差异', '确认单', '编制方', '接受差异', '复核', '月结', '可提交', '导出', 'PDF', 'Word', 'Excel', '下钻',
  '版本', '模型未配置', '归档', '快捷键', '来源核验', '数值引用', '执行成功', '舍入', '1-8月', '对不上',
  // Places the guide did not cover before, and what the assistant can do.
  '助手', '技能', '凭证', '对账', '预算差异', '价量分解', '13 周现金', '计算历史', '版本比较', '科目映射', '考核调整',
  '回款延迟', '重要性阈值', '插入图表', '写回', '更新 ERP 来源', '截止时间', '回收站', '成果库', '恢复', '深色', '对话专注',
  // Words people type that the screens say differently.
  '关账', 'DSO', 'BVA', '利润表', '分录', '现金流', '主题', '删除', '上传', '系统刷新',
];

it('finds something for every word on the list', () => {
  expect(WORDS.length).toBeGreaterThanOrEqual(60);
  const missing = WORDS.filter((word) => searchArticles(word).length === 0);
  // 收缴率 was the one business word the guide did not explain; 回款与现金 explains it now.
  expect(missing).toEqual([]);
});

it('matches every word typed, not any', () => {
  expect(searchArticles('期间 累计').map((row) => row.id)).toEqual(['collection-health', 'scope']);
  expect(searchArticles('收缴率 风险雷达').map((row) => row.id)).toEqual(['follow-6', 'assistant-skills', 'collection-health']);
  expect(searchArticles('期间 不存在的词')).toEqual([]);
});

it('finds the screen\'s word for what people type', () => {
  expect(searchArticles('关账').map((row) => row.id)).toContain('month-close');
  expect(searchArticles('DSO').map((row) => row.id)).toContain('collection-health');
  expect(searchArticles('暗色').map((row) => row.id)).toEqual(['layout']);
  expect(searchArticles('系统刷新').map((row) => row.id)).toContain('source-refresh');
  // A synonym widens one word; every typed word still has to be found.
  expect(searchArticles('关账 不存在的词')).toEqual([]);
});

it('says what the assistant can and cannot do in every one of its six areas', () => {
  const article = GUIDE_ARTICLES.find((row) => row.id === 'assistant-skills')!;
  const list = article.body.find((block) => block.kind === 'list');
  expect(list && list.kind === 'list' ? list.items.map((item) => item.split('：')[0]) : [])
    .toEqual(['开始与资料体检', '月结与管理报表', '预算与差异分析', '对账', '凭证草稿', '回款与现金']);
  // What the reader sees: the words, not the ids the blocks carry.
  const text = article.body.map((block) => 'text' in block ? block.text : 'items' in block ? block.items.join('') : 'label' in block ? block.label : '').join('');
  expect(text).toContain('不能确认控制、处置差异、过账或付款');
  // English skill ids are for the model, not for the reader.
  expect(text).not.toMatch(/\b(setup|close|bva|cash|reconciliation|journal-entry|financial-statements|variance-analysis)\b/);
});

it('opens at the article a 「?」 asked for and shows where it applies', () => {
  render(<GuideHub article="controls" onOpen={vi.fn()} onClose={vi.fn()} />);
  expect(screen.getByRole('heading', { name: '勾稽控制与差异处置' })).toBeTruthy();
  expect(screen.getByText('适用于：月结页 · 勾稽控制')).toBeTruthy();
});

it('says plainly when a search finds nothing', () => {
  render(<GuideHub onOpen={vi.fn()} onClose={vi.fn()} />);
  // The live region is there before anything is typed, so the change is announced.
  expect(screen.getByRole('status').textContent).toBe('');
  fireEvent.change(screen.getByLabelText('搜索使用指南'), { target: { value: '汇率' } });
  expect(screen.getByRole('status').textContent).toBe('没有找到「汇率」相关的说明。');
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

it('moves focus to the article when it opens', () => {
  render(<GuideHub article="scope" onOpen={vi.fn()} onClose={vi.fn()} />);
  expect(document.activeElement?.textContent).toBe('分析范围与期间');
});

it('says why it cannot take you anywhere with no editable task open', () => {
  render(<GuideHub article="month-close" canOpen={false} onOpen={vi.fn()} onClose={vi.fn()} />);
  expect((screen.getByRole('button', { name: /打开月结页/ }) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText('先打开一个可编辑的任务，才能跳到这里。')).toBeTruthy();
});

it('uses the quality words the 文稿质量检查 panel shows', () => {
  render(<GuideHub article="statuses" onOpen={vi.fn()} onClose={vi.fn()} />);
  const legend = document.querySelector('.fnd-guide-legend')!;
  expect(legend.textContent).toBe('计算成功≠不等于引用值一致≠不等于源数据核验通过≠不等于已专业复核');
});

it('lists every article in one drop-down at the top, grouped by section', () => {
  render(<GuideHub onOpen={vi.fn()} onClose={vi.fn()} />);
  const contents = screen.getByRole('combobox', { name: '指南目录' });
  expect(within(contents).getAllByRole('option')).toHaveLength(GUIDE_ARTICLES.length);
  const sections = [...contents.querySelectorAll('optgroup')].map((group) => group.label);
  expect(sections).toEqual(GUIDE_SECTIONS.filter((section) => GUIDE_ARTICLES.some((row) => row.section === section)));
  expect(screen.queryByRole('navigation', { name: '指南目录' })).toBeNull();
});

it('changes the article from the drop-down and leaves focus on it', () => {
  render(<GuideHub onOpen={vi.fn()} onClose={vi.fn()} />);
  const contents = screen.getByRole('combobox', { name: '指南目录' }) as HTMLSelectElement;
  contents.focus();
  fireEvent.change(contents, { target: { value: 'export' } });
  expect(screen.getByRole('heading', { level: 3, name: '文稿与导出' })).toBeTruthy();
  expect(document.activeElement).toBe(contents);
  expect(screen.getByRole('status').textContent).toBe('已显示「文稿与导出」');
});

it('lists search hits above the article and moves to the one picked', async () => {
  render(<GuideHub onOpen={vi.fn()} onClose={vi.fn()} />);
  fireEvent.change(screen.getByLabelText('搜索使用指南'), { target: { value: '归档' } });
  const hits = screen.getByRole('navigation', { name: '搜索结果' });
  fireEvent.click(within(hits).getByRole('button', { name: /无法继续时怎么办/ }));
  const title = screen.getByRole('heading', { level: 3, name: /无法继续时怎么办/ });
  await waitFor(() => expect(document.activeElement).toBe(title));
  expect((screen.getByRole('combobox', { name: '指南目录' }) as HTMLSelectElement).value).toBe('troubleshooting');
});

it('has a map of the workspace and one article per page, found by the words people use when lost', () => {
  for (const id of ['workspace-map', 'page-datasets', 'page-results', 'page-drafts', 'page-close']) {
    expect(GUIDE_ARTICLES.some((row) => row.id === id), id).toBe(true);
  }
  expect(searchArticles('三个点').map((row) => row.id)).toContain('workspace-map');
  expect(searchArticles('归档 菜单').map((row) => row.id)).toEqual(expect.arrayContaining(['workspace-map', 'tasks-library']));
  expect(searchArticles('考核调整').map((row) => row.id)).toContain('page-results');
});
