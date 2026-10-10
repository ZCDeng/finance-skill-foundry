/**
 * Where one figure on a result came from, in the words a manager reads: the metric and period, the cells and notes
 * the calculation wrote beside it, the files it read and when, and how it was calculated. Everything here is read
 * from the run and its version as stored; nothing is recalculated or inferred.
 */
import { when, type AnalysisRevision, type AnalysisRun, type DatasetSnapshot } from '../../bridge.js';
import { STATUS, textValue } from './presentation.js';

/** What a result page knows about the calculation its figures came from. */
export type FigureSourceContext = {
  run: AnalysisRun;
  analysis?: AnalysisRevision;
  datasets: DatasetSnapshot[];
  /** Snapshots a newer file or a published source refresh replaced (analysis-state superseded_datasets). */
  superseded: ReadonlySet<string>;
};

export type FigureSourceFile = { name: string; digest: string; replaced: boolean };

export type FigureSourceInfo = {
  /** What the figure measures: 收入 · 华南. */
  metric: string;
  /** Which figure of the row: 实际, 预算, 差异, a column's label. */
  part: string;
  /** The figure as the page shows it. */
  value: string;
  /** 期间, 单位, 依据 … as the row declares them; a fact the row leaves out is left out. */
  facts: [label: string, text: string][];
  /** The row's own source lines (cell references, 口径 notes), each with what it is. */
  sources: [label: string, text: string][];
  files: FigureSourceFile[];
  /** When the run was calculated, its review state and engine, in one line. */
  computed: string;
  /** The SQL, script or finance spec of the version, for a reader who wants to check the arithmetic. */
  method?: { label: string; text: string };
  /** A file the run read has since been replaced: the figure stands until it is calculated again. */
  stale: boolean;
  runId: string;
};

/** The row fields that say where a figure came from, in the order the card lists them. */
const sourceFields: [field: string, label: string][] = [
  ['source', '取数'], ['来源', '取数'], ['source_note', '说明'], ['口径与来源', '口径与来源'],
  ['actual_label', '实际'], ['budget_label', '预算'], ['caliber', '口径'], ['口径', '口径'], ['formula', '公式'], ['公式', '公式'],
];

const engineLabels: Record<string, string> = {
  sql: 'SQL 计算', python: '脚本计算', shell: '脚本计算', finance: '财务引擎', structured_aggregate: '按结构汇总',
};

/** A method text past this many characters is cut: the card shows how, the 技术信息 fold keeps the rest. */
const methodChars = 4000;

const filled = (value: unknown) => value != null && value !== '' && textValue(value) !== '—';

/** The files a run read, in binding order, each with the digest it was read at. */
export function runFiles(context: FigureSourceContext): FigureSourceFile[] {
  const { run, datasets, superseded } = context;
  const bindings = run.bindings ?? context.analysis?.bindings ?? {};
  return Object.entries(bindings).map(([alias, id]) => {
    const dataset = datasets.find((row) => row.id === id);
    const digest = run.input_hashes?.[alias] ?? dataset?.data_hash ?? dataset?.source_hash ?? '';
    return { name: dataset?.name ?? alias, digest: digest.slice(0, 12), replaced: superseded.has(id) };
  });
}

/** Whether a file the run read has been replaced since. */
export function runIsStale(context: FigureSourceContext): boolean {
  return runFiles(context).some((file) => file.replaced);
}

function methodOf(context: FigureSourceContext): FigureSourceInfo['method'] {
  const { analysis, run } = context;
  const cut = (text: string) => text.length > methodChars ? `${text.slice(0, methodChars)}\n…（其余见「技术信息」）` : text;
  if (analysis?.sql?.trim()) return { label: 'SQL', text: cut(analysis.sql.trim()) };
  const code = (run.code ?? analysis?.code ?? '').trim();
  if (code) return { label: '脚本', text: cut(code) };
  if (analysis?.finance_spec && Object.keys(analysis.finance_spec).length) return { label: '计算参数', text: cut(JSON.stringify(analysis.finance_spec, null, 2)) };
  return undefined;
}

/** One figure's source card, from the row it sits in. `facts` are what the page already shows beside the figure. */
export function figureSource(context: FigureSourceContext, row: Record<string, unknown>, {
  metric, part, value, facts = [],
}: { metric: string; part: string; value: string; facts?: [string, string][] }): FigureSourceInfo {
  const { run } = context;
  const seen = new Set<string>();
  const sources: [string, string][] = [];
  for (const [field, label] of sourceFields) {
    if (!(field in row) || !filled(row[field])) continue;
    const text = textValue(row[field]);
    if (seen.has(text)) continue;
    seen.add(text);
    sources.push([label, text]);
  }
  const computed = [
    `${when(run.created_at)} 计算`,
    STATUS[run.review_status] ?? run.review_status,
    run.engine ? engineLabels[run.engine] ?? run.engine : '',
  ].filter(Boolean).join(' · ');
  return {
    metric, part, value,
    facts: facts.filter(([, text]) => filled(text)),
    sources,
    files: runFiles(context),
    computed,
    method: methodOf(context),
    stale: runIsStale(context),
    runId: run.id,
  };
}

/** The card as plain lines, for 复制来源: what a manager pastes into a note or a mail. */
export function sourceText(info: FigureSourceInfo): string {
  return [
    `${info.metric} · ${info.part}：${info.value}`,
    ...info.facts.map(([label, text]) => `${label}：${text}`),
    ...info.sources.map(([label, text]) => `${label}：${text}`),
    ...info.files.map((file) => `资料：${file.name}${file.digest ? `（摘要 ${file.digest}）` : ''}${file.replaced ? ' · 已被新版本取代' : ''}`),
    `计算：${info.computed} · 计算编号 ${info.runId}`,
    ...(info.stale ? ['资料已更新，这个数按旧版本算出，重新计算后才算数。'] : []),
  ].join('\n');
}

/** The question 问助手解释 puts into the conversation. It is not sent: the manager edits it first. */
export function askAboutFigure(info: FigureSourceInfo): string {
  const period = info.facts.find(([label]) => label === '期间')?.[1];
  return `解释这个数：${info.metric}的${info.part}${period ? `（${period}）` : ''}是 ${info.value}。它是怎么算出来的，取了哪些资料和单元格，用的什么口径？计算编号 ${info.runId}。`;
}
