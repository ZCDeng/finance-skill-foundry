import { useEffect, useRef, useState } from 'react';
import { Info, TriangleAlert } from 'lucide-react';
import { bridge, type Answer, type DatasetSnapshot, type WorkbookHealth, type WorkbookHealthIssue, type WorkbookHealthSample } from '../../bridge.js';
import { Button } from '../../components/ui/button.js';
import { HelpLink } from '../guide/GuideHub.js';
import { WorkbookBrowser } from './WorkbookBrowser.js';
import { errorText, unwrap } from './shared.js';
import { DisclosureSummary } from '../../components/Disclosure.js';

/** What each hint means for the manager, and why it may matter at close. */
const HINTS: Record<string, { title: string; why: string; unit?: string }> = {
  external_links: { title: '链接了其他工作簿', unit: '个',
    why: '外部文件一改动或换了位置，这里的数字会跟着变，甚至断链。建议确认链接的是哪一版文件，交付前按需改为数值。' },
  iterative_calculation: { title: '开启了迭代计算',
    why: '开启后 Excel 不再提示循环引用，算出的数可能取决于计算次数。若不是有意设置，建议关闭后检查是否有循环引用。' },
  hidden_sheets: { title: '有隐藏的工作表', unit: '张',
    why: '隐藏表里的数字仍可能被其他表引用。深度隐藏的表在 Excel 里用“取消隐藏”也看不到。' },
  external_reference: { title: '公式引用了其他工作簿',
    why: '这些单元格的数字取自别的文件，这里只能读到保存时的结果，无法核对来源。' },
  volatile_function: { title: '用了易变函数',
    why: 'OFFSET、INDIRECT、TODAY、NOW、RAND 等函数每次打开都会重算，结果可能随日期或引用位置变化，复核时不容易追到来源。' },
  hardcoded_number: { title: '公式里写死了数字',
    why: '常见于手工调整或临时假设，建议改为引用输入单元格并注明来源。' },
  error_in_formula: { title: '公式里有 #REF! 断链',
    why: '公式里直接写着 #REF!，多半是被引用的行、列或工作表删掉后留下的断链，建议找回原来引用的位置后改正。' },
  cached_error: { title: '单元格的结果是错误值',
    why: '保存时这些单元格显示 #DIV/0!、#N/A 等错误，引用它们的合计也可能跟着出错。若是有意返回的 #N/A（例如让图表留空），可以忽略。' },
  formula_without_cache: { title: '公式没有保存计算结果',
    why: '这类文件通常由程序生成、没在 Excel 里打开保存过。系统不重算公式，这些工作表要在 Excel 中打开并保存后，才能当作数据表读取。' },
  inconsistent_row_formula: { title: '同一行的公式写法不一致',
    why: '这一行的公式大多按同一写法复制，这一格（夹在中间或紧接在最后）却不同，常见于复制后被手工改过，或新增月份后公式没跟着改。'
      + '引用本行这些格的小计、合计和比率不算在内；有意设置的其他写法也可能被列出，可以忽略。' },
  inconsistent_column_formula: { title: '同一列的公式写法不一致',
    why: '这一列的公式大多按同一写法复制，这一格（夹在中间或紧接在最后）却不同，常见于复制后被手工改过，或新增一行后公式没跟着改。'
      + '引用本列这些格的小计、合计不算在内；有意设置的其他写法也可能被列出，可以忽略。' },
  sheet_too_large: { title: '工作表太大，没有逐格体检', unit: '张',
    why: '超过 10 万行或 256 列的工作表没有逐格检查，其他工作表照常体检。' },
};
const SHEET_STATES: Record<string, string> = { hidden: '隐藏', veryHidden: '深度隐藏' };

type Opened = { datasetId: string; sheet: string; cell: string; range: string };
type Row = { dataset: DatasetSnapshot; health: WorkbookHealth | null; onDemand: boolean };

const isXlsxUpload = (dataset: DatasetSnapshot) => dataset.source_file === 'source.xlsx'
  && !dataset.metadata?.derived_from && !(dataset.transformation as { structure?: unknown } | undefined)?.structure;
const issuesOf = (health: WorkbookHealth) => (Array.isArray(health.issues) ? health.issues : [])
  .filter((issue) => issue && typeof issue.code === 'string' && (issue.count ?? 0) > 0);

/**
 * 公式体检: what the import noticed in each uploaded workbook's formulas. Hints
 * only. Nothing here blocks an import, a calculation or a button; whether to
 * change the workbook is the manager's call. A workbook filed before the check
 * existed can be checked on demand; that result is shown, not stored.
 */
export function FormulaHealthPanel({ taskId, datasets }: { taskId: string; datasets: DatasetSnapshot[] }) {
  const [checked, setChecked] = useState<Record<string, WorkbookHealth>>({});
  const [working, setWorking] = useState('');
  const [error, setError] = useState('');
  const [opened, setOpened] = useState<Opened | null>(null);
  const canCheck = Boolean(bridge()?.financeCall);
  // A check started on one task must not land on the next one.
  const currentTask = useRef(taskId);
  currentTask.current = taskId;
  const mountedTask = useRef(taskId);
  useEffect(() => {
    if (mountedTask.current === taskId) return;
    mountedTask.current = taskId;
    setChecked({}); setWorking(''); setError(''); setOpened(null);
  }, [taskId]);

  const rows = datasets.flatMap((dataset): Row[] => {
    const health = dataset.workbook_health ?? checked[dataset.id];
    if (health && typeof health === 'object') return [{ dataset, health, onDemand: !dataset.workbook_health }];
    return isXlsxUpload(dataset) && canCheck ? [{ dataset, health: null, onDemand: true }] : [];
  });
  const shown = rows.filter(({ health, onDemand }) => !health || health.status !== 'checked' || issuesOf(health).length > 0 || onDemand);
  if (!shown.length && !error) return null;

  async function check(dataset: DatasetSnapshot) {
    const api = bridge(); if (!api?.financeCall) return;
    const forTask = taskId;
    setWorking(dataset.id); setError('');
    try {
      const result = unwrap(await api.financeCall(forTask, 'workbook-health', { dataset_id: dataset.id }) as Answer<Record<string, unknown>>);
      if (currentTask.current !== forTask) return;
      setChecked((current) => ({ ...current, [dataset.id]: result as unknown as WorkbookHealth }));
    } catch (failure) {
      if (currentTask.current === forTask) setError(errorText(failure));
    } finally {
      if (currentTask.current === forTask) setWorking('');
    }
  }

  return (
    <section className="analysis-formula-health" aria-label="公式体检">
      {error && <p role="alert" className="analysis-message analysis-message--error">{error}</p>}
      {shown.map(({ dataset, health, onDemand }) => {
        if (!health) {
          return <p key={dataset.id} className="analysis-formula-health-line">
            <span>{dataset.name} · 导入时还没有做公式体检。</span>
            <Button type="button" variant="outline" disabled={Boolean(working)} aria-label={`体检这本工作簿：${dataset.name}`}
              onClick={() => void check(dataset)}>{working === dataset.id ? '正在体检…' : '体检这本工作簿'}</Button>
            <HelpLink article="formula-health" label="工作簿公式体检" />
          </p>;
        }
        if (health.status !== 'checked') {
          return <p key={dataset.id} className="analysis-formula-health-line">{dataset.name}：这本工作簿未能完成公式体检（不影响使用）。</p>;
        }
        const issues = issuesOf(health);
        if (!issues.length) {
          return <p key={dataset.id} className="analysis-formula-health-line">{dataset.name}：公式体检没有发现需要提示的地方。</p>;
        }
        return <details key={dataset.id} className="analysis-details analysis-formula-health-book" open={onDemand || undefined}>
          <DisclosureSummary>公式体检 · {dataset.name} · {issues.length} 类提示</DisclosureSummary>
          <div className="analysis-formula-health-body">
            <ul className="analysis-formula-health-list">
              {[...issues].sort((a, b) => Number(a.severity !== 'warning') - Number(b.severity !== 'warning')).map((issue) => (
                <Hint key={issue.code} issue={issue} onOpen={(sample) => setOpened({ datasetId: dataset.id, sheet: sample.sheet,
                  cell: sample.cell!, range: sample.range ?? sample.cell! })} />
              ))}
            </ul>
            {health.truncated && <p className="analysis-note">公式较多，只检查了前 {health.checked_formula_cells ?? 0} 个公式单元格。</p>}
            {opened?.datasetId === dataset.id && <div className="analysis-formula-health-view">
              <p className="analysis-note">正在查看 {opened.sheet}!{opened.cell} 及周围区域。</p>
              <WorkbookBrowser key={`${opened.datasetId}:${opened.sheet}:${opened.range}`} taskId={taskId} datasetId={opened.datasetId}
                initialSheet={opened.sheet} initialRange={opened.range} showSheetPicker={false} />
            </div>}
            <p className="analysis-note analysis-formula-health-close">
              这些是提示，不影响导入和计算；是否需要修改由你判断。<HelpLink article="formula-health" label="工作簿公式体检" />
            </p>
          </div>
        </details>;
      })}
    </section>
  );
}

function Hint({ issue, onOpen }: { issue: WorkbookHealthIssue; onOpen(sample: WorkbookHealthSample): void }) {
  const known = HINTS[issue.code] ?? { title: issue.code, why: '' };
  const warning = issue.severity === 'warning';
  const samples = Array.isArray(issue.samples) ? issue.samples : [];
  const targets = Array.isArray(issue.targets) ? issue.targets : [];
  return (
    <li className={`analysis-formula-health-item${warning ? ' analysis-formula-health-item--warning' : ''}`}>
      <div className="analysis-formula-health-head">
        <span className="analysis-formula-health-severity">
          {warning ? <TriangleAlert size={13} strokeWidth={1.75} aria-hidden /> : <Info size={13} strokeWidth={1.75} aria-hidden />}
          {warning ? '需留意' : '提示'}
        </span>
        <span>{known.title}</span>
        {issue.code !== 'iterative_calculation' && <span className="analysis-formula-health-count">{issue.count} {known.unit ?? '处'}</span>}
      </div>
      {known.why && <p className="analysis-formula-health-why">{known.why}</p>}
      {targets.length > 0 && <p className="analysis-formula-health-why">链接的文件：{targets.join('、')}</p>}
      {samples.length > 0 && <ul className="analysis-formula-health-samples">
        {samples.map((sample, index) => (
          <li key={`${sample.sheet}:${sample.cell ?? ''}:${index}`}>
            <span>{sample.cell ? `${sample.sheet}!${sample.cell}` : sample.sheet}</span>
            {sample.formula && <code className="analysis-formula-health-formula">{sample.formula}</code>}
            {detailText(issue.code, sample.detail) && <span className="analysis-formula-health-detail">{detailText(issue.code, sample.detail)}</span>}
            {sample.cell && <Button type="button" variant="link" size="sm" aria-label={`查看 ${sample.sheet}!${sample.cell}`}
              onClick={() => onOpen(sample)}>查看</Button>}
          </li>
        ))}
      </ul>}
    </li>
  );
}

/** The engine lists values as "a, b"; the manager reads "a、b". */
const listed = (detail: string) => detail.split(', ').join('、');

function detailText(code: string, detail?: string): string {
  if (!detail) return '';
  switch (code) {
    case 'hardcoded_number': return `写死的数字：${listed(detail)}`;
    case 'volatile_function': return `函数：${listed(detail)}`;
    case 'error_in_formula': return `错误值：${listed(detail)}`;
    case 'cached_error': return `结果：${detail}`;
    case 'inconsistent_row_formula':
    case 'inconsistent_column_formula': return `与 ${detail} 的写法不同`;
    case 'hidden_sheets': return SHEET_STATES[detail] ?? detail;
    default: return detail;
  }
}
