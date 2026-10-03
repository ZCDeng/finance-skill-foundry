/**
 * The words the workspace uses with a finance manager, in one place.
 *
 * Engine vocabulary (scenario keys, run roles, status codes) and the engine's
 * own error sentences are written for the assistant and the log. The manager
 * reads this file's words instead; the engine text stays reachable as a
 * "系统提示" so support can still match it to the log.
 */

const SCENARIO_LABELS: Record<string, string> = {
  actual: '实际', budget: '预算', forecast: '预测', baseline: '对照', current: '本期', prior: '上期',
  actual_ytd: '累计实际', budget_ytd: '累计预算', forecast_ytd: '累计预测',
  actual_month: '单月实际', budget_month: '单月预算',
  estimated_budget: '预算（估算）', estimated_budget_ytd: '累计预算（估算）',
  variance: '差异', variance_favorable: '差异（有利为正）', achievement_ratio: '达成率', attainment_pct: '达成率', achievement_pct: '达成率',
  actual_py: '上年同期实际', actual_ly: '上年同期实际', budget_bud_fy: '全年预算',
};

/** A scenario key in words; a key this file does not know is shown as written. */
export function scenarioLabel(value: unknown): string {
  if (value == null || value === '') return '—';
  const key = String(value);
  const known = SCENARIO_LABELS[key] ?? SCENARIO_LABELS[key.toLowerCase()];
  if (known) return known;
  if (/^actual_py_|^actual_ly_/i.test(key)) return '上年同期实际';
  if (/^actual_/i.test(key)) return '实际';
  if (/^estimated_budget/i.test(key)) return '预算（估算）';
  if (/^budget_/i.test(key)) return '预算';
  if (/^variance/i.test(key)) return '差异';
  return key;
}

/** Fixed choices for the scope's 情景 field, with the key the engine stores. */
export const SCENARIO_OPTIONS: { value: string; label: string; meta?: string }[] = [
  { value: 'actual', label: '实际', meta: '账面发生数' },
  { value: 'budget', label: '预算', meta: '批复预算' },
  { value: 'forecast', label: '预测', meta: '滚动预测或最新估计' },
  { value: 'actual_ytd', label: '累计实际', meta: '年初至今' },
  { value: 'budget_ytd', label: '累计预算', meta: '年初至今' },
];

/** The result scenarios a requirement item may promise, beyond the scope's own. */
export const RESULT_SCENARIO_OPTIONS: { value: string; label: string; meta?: string }[] = [
  ...SCENARIO_OPTIONS,
  { value: 'actual_month', label: '单月实际' },
  { value: 'budget_month', label: '单月预算' },
  { value: 'actual_py', label: '上年同期实际' },
  { value: 'variance', label: '差异', meta: '实际减预算' },
  { value: 'achievement_ratio', label: '达成率', meta: '实际 ÷ 预算' },
];

export const CURRENCY_OPTIONS: { value: string; label: string; meta?: string }[] = [
  { value: 'CNY', label: '人民币', meta: 'CNY' },
  { value: 'USD', label: '美元', meta: 'USD' },
  { value: 'EUR', label: '欧元', meta: 'EUR' },
  { value: 'HKD', label: '港币', meta: 'HKD' },
  { value: 'JPY', label: '日元', meta: 'JPY' },
];

export const UNIT_OPTIONS: { value: string; label: string; meta?: string }[] = [
  { value: '万元', label: '万元', meta: '管理报表常用' },
  { value: '元', label: '元', meta: '明细账常用' },
  { value: '千元', label: '千元' },
  { value: '亿元', label: '亿元' },
];

/** The three states a saved calculation can be in, as the result page names them. */
export const RUN_ROLE_LABELS = { business: '结果', activity: '中间步骤', failure: '未完成的计算' } as const;

const HEX_ID = /\b[0-9a-f]{32}\b/gi;
const HEX_HASH = /\b(?:sha256:)?[0-9a-f]{64}\b/gi;

/** A sentence without the 32/64-character identifiers the engine embeds in it. */
export function withoutIdentifiers(text: string): string {
  return text.replace(HEX_HASH, '（摘要已省略）').replace(HEX_ID, '（编号已省略）');
}

const SCOPE_FIELD_WORDS: Record<string, string> = {
  period: '期间', organization: '组织', scenario: '情景', ledger: '账簿', currency: '币种', unit: '单位',
  cutoff: '截止时间', cutoff_at: '截止时间', source: '来源系统', tenant: '账套', granularity: '粒度',
  as_of: '截至日期', start_date: '预测开始日', actual_cutoff: '实际收支截止日', opening_cash: '期初现金',
};

const fieldWord = (name: string): string => SCOPE_FIELD_WORDS[name.trim().toLowerCase()] ?? name.trim();

type Rule = [RegExp, string | ((match: RegExpMatchArray) => string)];

/**
 * Engine sentences a manager may meet, in the order they are tried. Each says
 * what happened in her words and what to do next. Anything unmatched is shown
 * as written, so a new engine sentence is never hidden.
 */
const RULES: Rule[] = [
  // Tie-out controls the manager declares (添加两处取数对比).
  [/control (left|right) range must be a bounded A1 reference/i, '单元格或区域要写成 T605 或 B5:B604 这样的格式，不能是整列或整行。'],
  [/control (left|right) range is too large/i, '区域太大，请缩小到 2 万个单元格以内，或改选合计所在的单元格。'],
  [/control refers to a snapshot a newer upload has replaced/i, '这本工作簿已被新上传的版本取代，请在新版本上选择。'],
  [/control refers to a snapshot that is not in this task/i, '这本工作簿不在当前任务里，请重新打开表单选择。'],
  // The scope record (analysis requirements).
  [/requirements update must reference the latest version/i, '范围在别处已经更新过，请刷新后再保存。'],
  [/requirements parent does not exist/i, '这个范围版本已不存在，请刷新后重新保存。'],
  [/requirement (periods|organizations|scenarios) conflict with scope\.(\w+)/i, (match) => {
    const word = fieldWord(match[2]);
    return `共同${word}与逐项${word}冲突：清空上方的共同${word}，或让每一项都用同一个${word}。`;
  }],
  [/requirement \w+ must be an array of non-empty strings/i, '逐项条件里有空值，请删掉空白项后再保存。'],
  [/requirements items must be an array of at most (\d+) items/i, (match) => `必答指标最多 ${match[1]} 项，请合并或删除部分指标。`],
  // Finance scope and bindings.
  [/\w+ scope requires one (\w+)/i, (match) => `范围里的${fieldWord(match[1])}只能有一个值，请在范围面板确认。`],
  [/(\w+) scope is required/i, '还没有确认范围，请先在范围面板填写期间、组织和单位。'],
  [/source scope requires source\/tenant\/ledger\/organization\/period\/currency\/cutoff fields/i, '更新来源需要填齐来源系统、账套、账簿、组织、期间、币种和截止时间。'],
  [/scope\/policy alias is not bound|finance bindings must map aliases to snapshot IDs/i, '资料与范围没有对上，请重新选择实际资料（和预算资料）后再保存。'],
  [/预算桥需要已保存口径|actual 与 budget 情景别名/i, '预算差异分析需要同时选择实际资料和预算资料，请补上预算资料后重新保存范围。'],
  [/profit bridge already groups accounts as metric rows/i, '预算差异分析已经按科目分行，维度里不要再放科目；请改用组织或期间。'],
  [/adjustment_ids apply only to run_metric\(kind=management_pnl\)/i, '考核调整只作用于损益表，请先计算损益表。'],
  [/adjustment bindings (must match the finance context|are required)/i, '考核调整引用的资料与当前范围不一致，请在当前范围下重新登记调整。'],
  // Data files.
  [/cannot parse \.xls[xm] source/i, '无法读取这份 Excel：文件可能已损坏，或扩展名与实际格式不符。这次读取没有生成任何数据，已有资料不受影响。请在 Excel 中另存为 .xlsx 后重试。'],
  [/CSV row has more fields than its header/i, '无法读取这份 CSV：有的行比表头多出字段，通常是分隔符或引号用错了。这次读取没有生成任何数据，已有资料不受影响。请检查分隔符和引号，另存为 UTF-8 编码的 CSV 后重试。'],
  [/cannot parse \.csv source/i, '无法读取这份 CSV：编码或分隔格式有误。这次读取没有生成任何数据，已有资料不受影响。请另存为 UTF-8 编码的 CSV 后重试。'],
  [/cannot parse \.\w+ source/i, '无法读取这份文件：内容与扩展名标示的格式不符。这次读取没有生成任何数据，已有资料不受影响。请检查文件后重试。'],
  [/dataset source workbook integrity check failed/i, '这份 Excel 与登记时的内容不一致，请重新添加这份资料。'],
  [/integrity check failed/i, '资料内容与登记时不一致，请重新添加这份资料后再计算。'],
  [/outside (this session context|run bindings|the run)|is outside/i, '引用的资料不属于当前任务或这次计算，请重新选择资料。'],
  [/source batch is not published|snapshot is unavailable/i, '这份来源还没有可用的数据快照，请先完成来源更新。'],
  [/source batch publication does not match snapshot/i, '来源更新与登记的资料不一致，请重新执行一次来源更新。'],
  [/structure confirmation produced no table/i, '按这个表结构没有读到数据行，请检查表头行和数据区域。'],
  [/pending_structure|表结构等经理确认/i, '这份资料的表结构还没有确认，请先在资料页确认表结构。'],
  [/management[_ ]account|mapping[_ ]incomplete|account map/i, '管理科目还没有映射齐（收入、成本、费用），请在「管理科目映射」里补齐后再计算。'],
  // Workbook writes.
  [/workbook output already exists/i, '这个 Excel 结果文件已经存在，请换一个文件名或先移走旧文件。'],
  [/workbook source changed since saved patch/i, 'Excel 原表在保存写回方案后又改动过，请重新预览再写回。'],
  [/binding header missing fields: (.+)/i, (match) => `Excel 区域的表头里找不到这些字段：${match[1]}。请核对表头。`],
  [/binding range exceeds/i, 'Excel 区域超出了工作表范围，请缩小区域。'],
  [/write value differs from referenced run result/i, '要写回的数字与这次计算的结果不一致，请先重新计算。'],
  // Scenarios.
  [/(\w+) before actual_cutoff cannot be forecast/i, '预测开始日必须晚于实际收支截止日。'],
  [/no aging bucket covers (\d+) overdue days/i, (match) => `账龄段没有覆盖逾期 ${match[1]} 天的应收，请补充账龄段。`],
  [/negative activity amount requires reversal/i, '负数核销需要标记为冲销，请检查核销记录。'],
  [/status_filter/i, '应收状态筛选的设置有误，请重新选择状态。'],
  // Generic engine validation and infrastructure.
  [/must be an? (ISO )?YYYY-MM-DD date/i, '日期需要写成 YYYY-MM-DD。'],
  [/must be a finite decimal|invalid decimal value|must be nonnegative/i, '金额需要是有效的数字。'],
  [/timeout_seconds must be between/i, '超时时间超出允许范围。'],
  [/timed? ?out|timeout/i, '计算超时，请缩小范围或稍后再试。'],
  [/already (exists|complete|settled)/i, '这一步已经完成过，不需要重复操作。'],
  [/does not exist|not found|unknown \w+/i, '找不到对应的记录，可能已被删除或改名，请刷新后重试。'],
  [/must be (an? )?(object|array|list|map)/i, '提交的内容格式不对，请刷新页面后重试；若仍出现，请联系维护人员。'],
  [/Unexpected token|JSON\.parse|in JSON at position|is not valid JSON/i, 'JSON 格式有误，请检查括号、逗号和引号。'],
  [/ECONNREFUSED|ENOTFOUND|socket hang up|not connected|未连接|无法连接/i, '本地分析服务暂时没有响应，请稍后重试。'],
  [/EACCES|EPERM|permission denied/i, '没有权限读写这个文件，请检查文件是否被占用或只读。'],
  [/ENOENT/i, '找不到这个文件，可能已被移动或删除。'],
];

/**
 * An engine or system sentence as the manager should read it. A sentence this
 * file does not know is returned as written, minus embedded identifiers.
 */
export function friendlyError(message: string): string {
  const text = message.trim();
  if (!text) return '操作没有完成，但系统没有说明原因。请重试一次。';
  // Already translated once (by unwrap); the engine sentence inside must not be matched again.
  if (text.includes('（系统提示：')) return withoutIdentifiers(text);
  for (const [pattern, replacement] of RULES) {
    const match = text.match(pattern);
    if (!match) continue;
    const words = typeof replacement === 'function' ? replacement(match) : replacement;
    return withoutIdentifiers(`${words}（系统提示：${text}）`);
  }
  return withoutIdentifiers(text);
}

/** The manager-facing text of a thrown value. */
export function errorText(failure: unknown): string {
  return friendlyError(failure instanceof Error ? failure.message : String(failure));
}
