/**
 * The 使用指南 articles. Each one says what the product does today, in the words its
 * screens use, and where on screen to do it. Nothing here makes a financial judgement
 * for the reader, and nothing claims a check the software does not run.
 */

export type GuideTarget = 'datasets' | 'scope' | 'structure' | 'results' | 'drafts' | 'close';

export type GuideBlock =
  | { kind: 'p'; text: string }
  | { kind: 'steps'; items: string[] }
  | { kind: 'list'; items: string[] }
  | { kind: 'legend' }
  /** The six quick-start steps, read from the open task's own state. */
  | { kind: 'checklist' }
  /** First run: practise on the synthetic task, or start with your own files. */
  | { kind: 'start' }
  | { kind: 'open'; target: GuideTarget; label: string };

export type GuideArticle = {
  id: string;
  section: string;
  title: string;
  /** Where in the window this applies. */
  appliesTo: string;
  /** Words a finance manager would type when looking for it. */
  keywords: string[];
  body: GuideBlock[];
};

export const GUIDE_SECTIONS = ['快速开始', '月结工作流', '读懂状态', '资料与数据安全', '结果、依据和版本', '文稿与导出', '故障排查', '快捷键与无障碍'] as const;

export const GUIDE_ARTICLES: GuideArticle[] = [
  {
    id: 'first-run', section: '快速开始', title: '第一次使用', appliesTo: '工作区',
    keywords: ['第一次', '示例', '练习', '示例任务', '合成数据', '入门'],
    body: [
      { kind: 'p', text: '可以先用示例任务练一遍，再用自己的资料。示例任务是单独的一个任务，里面是一套虚构的 2026 年 6 月月结套表，不会碰到你的任何资料。' },
      { kind: 'p', text: '示例套表的应收账龄表里，坏账准备分项故意比合计多 50 万元，用来练习勾稽控制和差异处置。' },
      { kind: 'start' },
      { kind: 'p', text: '系统为资料保存只读快照，原文件不会被改写。随时可以从顶栏的「使用指南」回到这里。' },
    ],
  },
  {
    id: 'quick-start', section: '快速开始', title: '5 分钟快速开始', appliesTo: '工作区',
    keywords: ['开始', '新建任务', '添加资料', '入门', '第一次', '怎么用'],
    body: [
      { kind: 'p', text: '一个任务对应一件要弄清楚的事，比如「华东区 8 月回款」。左边和助手讨论，右边看资料、结果和文稿。' },
      { kind: 'checklist' },
      { kind: 'steps', items: [
        '新建任务，用一句话写清要回答的问题。',
        '在「资料」页添加 Excel 或 CSV。系统保存只读快照，原文件不会被改写。',
        '确认表结构：表头在哪一行、哪些行是明细、哪些是合计。',
        '确认分析范围：期间、组织、单位、币种。资料里读到的值会列在字段下方；期间候选还写明来自哪张表的标题或文件名。',
        '计算，然后在「分析结果」里打开本次计算依据，核对来源单元格。',
        '在「文稿」里编辑和导出。保存草稿不等于经理认可。',
      ] },
      { kind: 'open', target: 'datasets', label: '打开资料页' },
    ],
  },
  {
    id: 'month-close', section: '月结工作流', title: '月结怎么走一遍', appliesTo: '月结页',
    keywords: ['月结', '关账', '控制中心', '可提交', '复核', '勾稽', '放行', '可用结论', '带保留可用', '不可用', '无法判断', '问题类型'],
    body: [
      { kind: 'p', text: '「月结」页把一次月结拆成六块：范围、来源、结构、控制、异常、复核。顶部只会出现五种说法之一：尚未准备、可计算、需要复核、可提交经理复核、已归档。系统最多说到「可提交经理复核」，不会说月结已完成。' },
      { kind: 'p', text: '顶部状态下面另有一行「套表可用结论」，回答这套表现在能不能用，只有四种：可用、带保留可用、不可用、无法判断，并可「按工作簿看」。它只根据你确认过的控制和你的处置得出：还没有确认的控制、有工作簿还没有确认的控制读到、控制还没运行、有控制还读着旧版本资料（在新版本上确认对应控制后，要把旧的停用）、有读不出数的区域，或范围、来源、结构还没确认，都是「无法判断」；还有差异挡住月结是「不可用」；差异都已接受并写明理由是「带保留可用」，会列出这些差异和理由；确认的控制全部相符才是「可用」。原因里会写差异的问题类型，助手的类型建议不改变结论。可用结论和顶部状态各看各的，不会合成一句「全部通过」。' },
      { kind: 'steps', items: [
        '冻结本期输入：添加本期资料，旧版本被新上传的同名资料取代后只读保留。',
        '确认期间、组织、单位、币种。资料没写组织时不要求组织。',
        '确认每张表的表头、明细区和合计行。',
        '在「勾稽控制」里找建议控制，确认要检查的那些并运行。',
        '处理每一项差异：接受差异并写明理由、标记待外部确认（写明由谁确认），或修正资料后重新导入。',
        '计算并生成文稿，逐项看执行、数值引用和来源核验。',
        '顶部显示「可提交经理复核」后，由经理复核、导出、归档。',
      ] },
      { kind: 'open', target: 'close', label: '打开月结页' },
    ],
  },
  {
    id: 'controls', section: '月结工作流', title: '勾稽控制与差异处置', appliesTo: '月结页 · 勾稽控制',
    keywords: ['勾稽', '合计', '分项', '对不上', '差异', '跨表', '两处取数', '确认单', '编制方', '接受差异', '第二人复核', '舍入', '问题类型', '来源矛盾', '口径不同', '助手建议'],
    body: [
      { kind: 'p', text: '勾稽控制检查两件事：表里的合计是否等于分项，两处取数是否一致（可以跨表、跨工作簿）。系统按原始单元格逐格加总，只指出差异，不替你选口径。' },
      { kind: 'list', items: [
        '建议控制来自工作簿自己的合计行。比率、占比、天数、进度类的列不会被加总。',
        '两处应当相等、但不在同一张表的数字（例如合同台账实收对月结区域实收），用「添加两处取数对比」：选两个工作簿里的单元格或区域，先看两边合计和差额，确认后才保存为控制。',
        '只有经理确认过的控制才计入月结。助手可以建议和运行，不能确认、停用或处置。',
        '区域里有任何文字单元格（例如存成文本的「1,200」，或混进区域的「小计」字样）时，控制显示「读不出」，只能修正资料。',
        '「可能是显示舍入」只是提示，差异仍算不相符，需要处置。',
        '处置绑定在当时那笔差额上。差额或资料一变，原处置不再适用。',
        '每项差异可以标一个问题类型：公式或控制缺陷、来源矛盾、无依据假设、未更新、口径不同。助手可以建议类型并附一句理由，显示为「助手建议」；由你点「采用建议」或另选一类保存，才算定下；你已经定了类型、不同意建议时，点「保留我的类型」。类型同样绑定在当时那笔差额上；它不是处置的前提，也不改变差异是否挡住月结。',
        '「复制确认单」生成发给编制方的清单，其中「问题类型」一列写你定的类型，只有助手建议时写明「助手建议」；「复制为表格」可直接粘贴到 Excel。',
        '可以设置「接受差异后需要第二人复核」，此时接受差异要署名，复核人的署名不能与接受人相同。系统只比对署名，分工靠团队自己执行。',
      ] },
      { kind: 'open', target: 'close', label: '打开勾稽控制' },
    ],
  },
  {
    id: 'statuses', section: '读懂状态', title: '状态互不替代', appliesTo: '分析结果 · 文稿 · 月结',
    keywords: ['状态', '未阅', '未验证', '需复核', '执行成功', '来源核验', '数值引用', '专业复核', '发布', '过期'],
    body: [
      { kind: 'legend' },
      { kind: 'p', text: '计算成功只说明计算跑完了，不说明文稿里的数字都引用了结果，也不说明源数据已经核验过，更不说明经理已经认可。每一项单独看。' },
      { kind: 'list', items: [
        '计算：有没有跑完（计算成功）。',
        '数字引用：文稿里的数字是否都能对应到计算结果（引用值一致）。',
        '源数据核验：数字能否追到原始单元格。显示「尚未独立核验」时不等于通过。',
        '专业复核：经理是否已阅。保存草稿不会自动变成已专业复核。',
        '控制「已过期」：它读的资料已有更新版本，旧的相符结果不再算数。',
      ] },
    ],
  },
  {
    id: 'scope', section: '读懂状态', title: '分析范围与期间', appliesTo: '资料页 · 分析范围',
    keywords: ['期间', '范围', '本期', '上期', '1-8月', '累计', '单位', '币种', '组织', '万元'],
    body: [
      { kind: 'p', text: '每一次计算和每一份文稿都按任务的分析范围取数。资料里读到的期间、单位、币种会作为候选列在字段下方，点一下才会采用；期间候选还写明来自哪张表的标题或文件名。' },
      { kind: 'list', items: [
        '「2026年1-8月」这样的累计区间不会被当成某一个月，由写明月份的表决定期间。',
        '资料写明了期间而任务期间还空着时，「计算损益表」和「计算预算差异」会暂时不可用。',
        '同一本工作簿混用元和万元时，单位不会被猜成一个，需要你确认。',
        '系统不会自动用电脑当前的月份代替任务期间。期间输入框的「本期」按钮填的是电脑当前月份，「上期」「上年同期」在期间为空时也按当前月份推算，用之前请核对。',
      ] },
      { kind: 'open', target: 'scope', label: '打开分析范围' },
    ],
  },
  {
    id: 'data-safety', section: '资料与数据安全', title: '资料快照与原文件', appliesTo: '资料页',
    keywords: ['快照', '原文件', '摘要', '哈希', '安全', '隔离', '覆盖', '更新资料'],
    body: [
      { kind: 'list', items: [
        '添加资料时保存只读快照和摘要，之后的计算都读快照，原文件不会被改写。',
        '同名资料再次上传会成为新版本，旧版本仍在资料列表里。月结页和勾稽控制会把读旧版本的控制标为已过期，并提示最近一次计算需要重算；其他页面选资料时请选新版本。',
        '每个任务的资料只在这个任务里可见。',
        '写回 Excel 先预览。冲突单元格默认保留原值，可以逐格改为应用新结果，再生成工作簿副本。',
      ] },
      { kind: 'open', target: 'datasets', label: '打开资料页' },
    ],
  },
  {
    id: 'structure', section: '资料与数据安全', title: '表结构确认', appliesTo: '资料页 · 表结构',
    keywords: ['表头', '合计行', '明细', '表结构', '合并表头', '封面', '小计'],
    body: [
      { kind: 'p', text: '报表式的 Excel 常有封面、合并表头、几段表格和合计行。系统先给出表结构提议，你确认后才生成可计算的表。合计行和说明行不会被当成明细重复计入。' },
      { kind: 'open', target: 'structure', label: '打开表结构' },
    ],
  },
  {
    id: 'evidence', section: '结果、依据和版本', title: '结果成功为什么还要复核', appliesTo: '分析结果',
    keywords: ['依据', '下钻', '单元格', '来源', '版本', '运行', '比较'],
    body: [
      { kind: 'p', text: '每次计算都记录用了哪些快照、什么参数、输出摘要。在结果里打开计算依据可以下钻到来源行和单元格。分析版本和文稿修订都保留，旧版本不会被覆盖。' },
      { kind: 'open', target: 'results', label: '打开分析结果' },
    ],
  },
  {
    id: 'export', section: '文稿与导出', title: '文稿与导出', appliesTo: '文稿',
    keywords: ['文稿', '导出', 'Word', 'PDF', 'Excel', 'Markdown', 'HTML', '引用检查'],
    body: [
      { kind: 'p', text: '文稿可以阅读和编辑，保存时检查数字引用。导出支持 Word、PDF、HTML、Markdown 和 Excel。有未保存的修改时，导出前会先另存为新版本，再导出这一版。' },
      { kind: 'open', target: 'drafts', label: '打开文稿' },
    ],
  },
  {
    id: 'troubleshooting', section: '故障排查', title: '无法继续时怎么办', appliesTo: '任何位置',
    keywords: ['报错', '打不开', '损坏', '模型未配置', '凭据', '空白', '连接', '超时', '中断', '归档'],
    body: [
      { kind: 'list', items: [
        '对话模型未配置：现有资料和成果仍可查看；配置模型后可继续对话。',
        '对话中断：点「重新连接」重新打开这个任务的对话。',
        '资料打不开：文件可能损坏或扩展名不对。原资料未加入，已有资料不受影响；在 Excel 里另存为 .xlsx 后再试。',
        '表结构未确认：到资料页确认后才能计算。',
        '控制「读不出」：区域里有文字格式的数字或公式错误，修正资料后重新导入。',
        '任务已归档或在回收站：只能查看，恢复任务后才能继续。',
      ] },
    ],
  },
  {
    id: 'shortcuts', section: '快捷键与无障碍', title: '快捷键与键盘操作', appliesTo: '任何位置',
    keywords: ['快捷键', '键盘', '无障碍', '屏幕阅读器', 'Esc'],
    body: [
      { kind: 'list', items: [
        '⌘ + ?（Windows 为 Ctrl + ?）：打开或关闭使用指南。',
        '页签之间用左右方向键、Home、End 切换。',
        'Esc 关闭设置面板、弹出层和使用指南，焦点回到打开它的按钮。',
        '状态都有文字说明，不只靠颜色区分。',
      ] },
    ],
  },
];

/** Articles whose title, keywords or text mention every word typed. */
export function searchArticles(query: string, articles: GuideArticle[] = GUIDE_ARTICLES): GuideArticle[] {
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return articles;
  return articles.filter((article) => {
    const text = [article.title, article.section, article.appliesTo, ...article.keywords, ...article.body.flatMap(blockText)].join(' ').toLowerCase();
    return words.every((word) => text.includes(word));
  });
}

function blockText(block: GuideBlock): string[] {
  if (block.kind === 'p') return [block.text];
  if (block.kind === 'steps' || block.kind === 'list') return block.items;
  if (block.kind === 'open') return [block.label];
  if (block.kind === 'checklist') return ['添加资料', '确认表结构', '确认分析范围', '运行计算', '核对来源与异常', '保存文稿并复核'];
  if (block.kind === 'start') return ['用示例任务练习', '使用自己的资料'];
  return ['计算成功', '引用值一致', '源数据核验通过', '已专业复核'];
}
