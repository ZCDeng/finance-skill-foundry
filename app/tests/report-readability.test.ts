import { describe, expect, it } from 'vitest';
import { reflowReportParagraphs } from '../electron/reports/readability.js';
import type { ReportDocument, ReportNode } from '../electron/reports/model.js';

const metadata = { company: '华宸物业', period: '2026-08', currency: 'CNY', unit: '万元' };
const source = { id: 'source-a', name: '月结.xlsx', sha256: 'a'.repeat(64), format: 'xlsx' as const };

function doc(content: ReportNode[]): ReportDocument {
  return { schema_version: 1, template_version: 'annual-v1', metadata, sources: [source], content };
}

describe('reflowReportParagraphs', () => {
  it('splits only long top-level Chinese paragraphs at complete sentence boundaries', () => {
    const text =
      '管理层摘要显示，本期收入保持稳定，核心物业服务收入与预算口径一致，未发现需要改写原始口径的事项，并且所有判断都只来自已导入的月结数据。成本端的人工、外包和能耗费用均保留原始精度，相关差异需要继续结合合同台账复核，不改变任何原始金额。现金流判断只引用已导入的银行和应收明细，不把未确认回款自动视为已收，也不补造管理层行动，且保留原始证据顺序。';
    const input = doc([paragraph(text, { source_id: source.id, page: 1 })]);

    const result = reflowReportParagraphs(input);

    expect(result.changedParagraphs).toBe(1);
    expect(result.addedParagraphs).toBe(2);
    expect(result.document.content).toHaveLength(3);
    expect(result.document.content.map(textContent).join('')).toBe(text);
    expect(result.document.content.every((node) => node.attrs?.source_id === source.id && node.attrs?.page === 1)).toBe(true);
    expect(input.content).toHaveLength(1);
  });

  it('turns existing safe newlines into real paragraphs while preserving punctuation order', () => {
    const text = '第一项结论已经核对。\n第二项原因只保留原文分号；\n第三项行动不自动补造。';
    const result = reflowReportParagraphs(doc([paragraph(text)]));

    expect(result.changedParagraphs).toBe(1);
    expect(result.addedParagraphs).toBe(2);
    expect(result.document.content.map(textContent)).toEqual(['第一项结论已经核对。', '第二项原因只保留原文分号；', '第三项行动不自动补造。']);
  });

  it('does not split inside balanced brackets or Chinese quotes', () => {
    const text =
      '本期解释引用原文（预算口径为“收入确认；不含税金。”且需要保留括号内完整表达），因此括号内的句号和分号不能成为拆段边界，并继续说明该引用只作为原文展示。后续结论只在括号外拆分，并继续保留事实占位符 FACT-AR-001，同时保持审阅状态不变，后续人工可继续核对但不会自动改写事实，并保持原始引用、期间、币种和单位字段原值。';
    const result = reflowReportParagraphs(doc([paragraph(text)]));

    expect(result.document.content.map(textContent)).toEqual([
      '本期解释引用原文（预算口径为“收入确认；不含税金。”且需要保留括号内完整表达），因此括号内的句号和分号不能成为拆段边界，并继续说明该引用只作为原文展示。',
      '后续结论只在括号外拆分，并继续保留事实占位符 FACT-AR-001，同时保持审阅状态不变，后续人工可继续核对但不会自动改写事实，并保持原始引用、期间、币种和单位字段原值。',
    ]);
  });

  it('keeps sentence-end footnote references attached to the preceding paragraph', () => {
    const text =
      '本期收入与预算保持一致。[^1]后续说明需要独立成段，继续保留证据顺序、金额精度和管理层口径，不把附注引用移动到下一段，也不改变任何原始字符，并补充预算、现金、成本、应收、应付、税费和合同台账七类证据，确保段落超过阈值后仍按句界稳定拆分，并保留集团、项目、科目、月份和审批口径。第三句继续补足长度，确保拆分发生但引用仍然贴合前一句。';
    const result = reflowReportParagraphs(doc([paragraph(text)]));

    expect(result.document.content.map(textContent)).toEqual([
      '本期收入与预算保持一致。[^1]',
      '后续说明需要独立成段，继续保留证据顺序、金额精度和管理层口径，不把附注引用移动到下一段，也不改变任何原始字符，并补充预算、现金、成本、应收、应付、税费和合同台账七类证据，确保段落超过阈值后仍按句界稳定拆分，并保留集团、项目、科目、月份和审批口径。',
      '第三句继续补足长度，确保拆分发生但引用仍然贴合前一句。',
    ]);
    expect(result.document.content.map(textContent).join('')).toBe(text);
  });

  it('does not split semicolons inside ASCII double quotes or treat apostrophes as quote bounds', () => {
    const text =
      '管理层原文为 "keep revenue; cost; cash together"，英文引号内的分号不能拆段，且 owner\'s review 中的 apostrophe 不能开启保护范围，并继续保留期间、币种、单位、证据编号、表格来源和审阅状态字段。括号外第二句可以拆分，继续补充足够长度以触发重排并保持所有英文和中文字符顺序。';
    const result = reflowReportParagraphs(doc([paragraph(text)]));

    expect(result.document.content.map(textContent)).toEqual([
      '管理层原文为 "keep revenue; cost; cash together"，英文引号内的分号不能拆段，且 owner\'s review 中的 apostrophe 不能开启保护范围，并继续保留期间、币种、单位、证据编号、表格来源和审阅状态字段。',
      '括号外第二句可以拆分，继续补充足够长度以触发重排并保持所有英文和中文字符顺序。',
    ]);
    expect(result.document.content.map(textContent).join('')).toBe(text);
  });

  it('preserves marks, source attrs, negative numbers and precision across text-node boundaries', () => {
    const input = doc([
      {
        type: 'paragraph',
        attrs: { source_id: source.id, range: 'A1:D9' },
        content: [
          { type: 'text', text: '预算差异为 ', attrs: { source_id: source.id } },
          { type: 'text', text: '-98,765.4300', marks: [{ type: 'bold' }], attrs: { source_id: source.id, sheet: '利润表' } },
          {
            type: 'text',
            text: ' 万元，保持原始精度并引用 SRC-LINK-001。第二句继续说明原因，不改变任何数字或负号。第三句用于达到长段阈值，确保拆段发生在句号而不是小数点或逗号。',
          },
        ],
      },
    ]);

    const result = reflowReportParagraphs(input);
    const rendered = result.document.content.map(textContent).join('');
    const boldNumber = result.document.content.flatMap((node) => node.content ?? []).find((node) => node.text === '-98,765.4300');

    expect(rendered).toContain('-98,765.4300');
    expect(rendered).toContain('SRC-LINK-001');
    expect(boldNumber?.marks).toEqual([{ type: 'bold' }]);
    expect(boldNumber?.attrs).toMatchObject({ source_id: source.id, sheet: '利润表' });
    expect(result.document.content.every((node) => node.attrs?.range === 'A1:D9')).toBe(true);
  });

  it('is idempotent and keeps metadata and sources unchanged', () => {
    const input = doc([paragraph('第一句较长但有完整句界，用于首次整理。第二句继续补充，达到阈值后拆分。第三句结束。'.repeat(3))]);
    const first = reflowReportParagraphs(input);
    const second = reflowReportParagraphs(first.document);

    expect(second.changedParagraphs).toBe(0);
    expect(second.addedParagraphs).toBe(0);
    expect(second.document).toEqual(first.document);
    expect(first.document.metadata).toEqual(metadata);
    expect(first.document.sources).toEqual([source]);
    expect(input.content).toHaveLength(1);
  });

  it('skips tables, lists, code blocks, report notes, complex inline nodes and the calculation appendix', () => {
    const table: ReportNode = {
      type: 'table',
      content: [{ type: 'tableRow', content: [{ type: 'tableCell', content: [{ type: 'text', text: '表内长句。表内不拆。' }] }] }],
    };
    const list: ReportNode = { type: 'bulletList', content: [{ type: 'listItem', content: [paragraph('列表长句。列表不拆。')] }] };
    const note: ReportNode = { type: 'reportNote', attrs: { id: 'n1' }, content: [paragraph('附注长句。附注不拆。')] };
    const code: ReportNode = { type: 'codeBlock', content: [{ type: 'text', text: '代码长句。代码不拆。' }] };
    const complex = {
      type: 'paragraph',
      content: [
        { type: 'text', text: '含图片前。' },
        { type: 'image', attrs: { src: 'data:image/png;base64,AAAA' } },
        { type: 'text', text: '含图片后。' },
      ],
    };
    const appendixParagraph = paragraph('计算依据附录中的系统内容很长。即使有句号也不拆。继续保持原状。'.repeat(3));
    const input = doc([table, list, note, code, complex, heading('计算依据'), appendixParagraph]);

    const result = reflowReportParagraphs(input);

    expect(result.changedParagraphs).toBe(0);
    expect(result.addedParagraphs).toBe(0);
    expect(result.document.content).toEqual(input.content);
  });

  it('keeps formulas without safe sentence boundaries and skips code/link marked inline text', () => {
    const formula = paragraph('归母净利差异=-98765.4300+1200.55-300.10= -97864.9800 / BUD 27201.9089 * 100%');
    const linked: ReportNode = {
      type: 'paragraph',
      content: [
        {
          type: 'text',
          text: '这段很长但是包含链接标记，不能在 link 内或同段随意拆开。'.repeat(8),
          marks: [{ type: 'link', attrs: { href: 'https://example.com' } }],
        },
      ],
    };
    const coded: ReportNode = {
      type: 'paragraph',
      content: [{ type: 'text', text: '这段很长但是包含 code 标记，不能拆。'.repeat(8), marks: [{ type: 'code' }] }],
    };

    const result = reflowReportParagraphs(doc([formula, linked, coded]));

    expect(result.changedParagraphs).toBe(0);
    expect(result.document.content.map(textContent)).toEqual([textContent(formula), textContent(linked), textContent(coded)]);
  });
});

function paragraph(text: string, attrs: Record<string, unknown> = {}): ReportNode {
  return { type: 'paragraph', attrs, content: [{ type: 'text', text }] };
}

function heading(text: string): ReportNode {
  return { type: 'heading', attrs: { level: 2 }, content: [{ type: 'text', text }] };
}

function textContent(node: ReportNode): string {
  if (node.type === 'text') return node.text ?? '';
  return (node.content ?? []).map(textContent).join('');
}
