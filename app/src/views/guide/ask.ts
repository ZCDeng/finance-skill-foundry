/**
 * Questions the window can put into the conversation for the manager to edit and send.
 *
 * Asking never sends and never runs anything: the question lands in the composer after any text
 * already there, and the manager decides what goes. The words of the ones that are also in the
 * composer's 「/」 menu are the same words (`dsh-plugin/client.js`, FINANCE_SHORTCUTS); a test
 * holds them together.
 */
export const ASK_EVENT = 'fnd:ask';

export const ASK_PROMPTS = {
  readiness: '这些资料能不能出管理利润表？能算什么，还缺期间、币种还是科目映射？',
  'data-gaps': '看看我这批资料还缺什么：想做的分析各要读哪些列，现在缺哪几列，哪些地方要先在 Excel 里处理。',
  'close-walk': '按本期套表走一遍月结：先列出要确认的勾稽控制，和现在还挡住月结的事项。',
  'budget-bridge': '本月利润为什么没有达到预算？给出利润桥，每一段都对得上总差异。',
  'bank-rec': '把本期银行存款余额和银行对账单核对一下，列出未达项，编一张余额调节表。',
  'accrual-je': '起草本期的费用计提凭证草稿，写明每笔的计算依据。只出草稿，不过账。',
  'collection-health': '做一次回款健康分析：收缴率对生死线、应收天数和风险雷达，集团带上毛利率和收缴率的敏感性表。',
  'formula-controls': '按套表起草按公式重算的勾稽控制：应收滚动、按套表重算的应收天数、用应收变动反推的回款率对综合收缴率。起草后先列给我确认。',
  'collection-caliber': '按我们公司的口径重算收缴率：综合收缴率用本年全部实收除以本年应收，商业租金代收不算物业费。先把口径提给我确认，再按它计算。',
  'formula-health': '解释资料页公式体检列出的这些提示：哪些可能影响取数，哪些可以忽略，建议先核对哪几格。',
  'dashboard-cards': '看看这个任务已经算好的结果，提议几张值得放上看板的卡，说明每张看什么。先放在「助手提议」里，我钉住才算。',
  'dashboard-by-city': '在看板上提议一张按城市公司排的卡：距生死线从低到高，标出生死线。先放在「助手提议」里。',
  'collection-scenario': '在看板上加一张回款情景卡：拖收缴率看距生死线、现金经营利润和一年回款怎么变。',
  'collection-goal': '倒推一下：收缴率回到生死线一年要多收多少，全年收入预算还差多少、剩下几个月每月要做到多少。各提议一张倒推卡，先放在「助手提议」里。',
  'collection-sensitivity': '在看板上提议一张敏感性表：毛利率和收缴率一起变时，距生死线怎么变。先放在「助手提议」里。',
} as const;

export type AskId = keyof typeof ASK_PROMPTS;

/** The words that go in: the question, led by what it is about when the page knows (a workbook's name, say). */
export function askText(id: AskId, about?: string) {
  return about ? `关于「${about}」：${ASK_PROMPTS[id]}` : ASK_PROMPTS[id];
}

/** Put one of the questions into the open task's conversation. */
export function askAssistant(id: AskId, about?: string) {
  window.dispatchEvent(new CustomEvent(ASK_EVENT, { detail: askText(id, about) }));
}

/** Put a question the page wrote (about one figure, say) into the open task's conversation, unsent like the rest. */
export function askWith(text: string) {
  window.dispatchEvent(new CustomEvent(ASK_EVENT, { detail: text }));
}
