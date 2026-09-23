import { useEffect, useState } from 'react';
import { bridge, type DatasetSnapshot } from '../../bridge.js';
import { SearchableSelect } from '../../components/FinancialControls.js';
import { WorkbookBrowser } from './WorkbookBrowser.js';

type Sheet = { dataset: DatasetSnapshot; name: string; rows: number; columns: number };
export function WorkbookOverview({ taskId, datasets }: { taskId: string; datasets: DatasetSnapshot[] }) {
  const workbooks = datasets.filter((dataset) => dataset.kind === 'workbook');
  const signature = JSON.stringify(workbooks.map((dataset) => [dataset.id, dataset.source_hash]));
  const [sheets, setSheets] = useState<Sheet[]>([]);
  const [selection, setSelection] = useState('');
  const [errors, setErrors] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    let active = true;
    setSheets([]); setSelection(''); setErrors([]); setLoading(false);
    const api = bridge();
    if (!api?.analysisReadDataset || !workbooks.length) return;
    setLoading(true);
    void Promise.allSettled(workbooks.map(async (dataset) => {
      const answer = await api.analysisReadDataset!(taskId, dataset.id);
      if (!answer.ok) throw new Error(`${dataset.name}：${answer.message}`);
      const book = answer.value.workbook as { sheets?: { name: string; rows: number; columns: number }[] } | undefined;
      return (book?.sheets ?? []).map((sheet) => ({ ...sheet, dataset }));
    })).then((results) => {
      if (!active) return;
      const next = results.flatMap((result) => result.status === 'fulfilled' ? result.value : []);
      setSheets(next); setSelection(next[0] ? sheetKey(next[0]) : '');
      setErrors(results.flatMap((result) => result.status === 'rejected' ? [String(result.reason)] : []));
      setLoading(false);
    });
    return () => { active = false; };
  }, [taskId, signature]);
  if (!workbooks.length || !bridge()?.financeCall) return null;
  const selected = sheets.find((sheet) => sheetKey(sheet) === selection);
  return <section className="analysis-workbook-overview" aria-label="工作簿总览">
    <h3>工作簿总览 · {workbooks.length} 本 · {sheets.length} 张工作表</h3>
    <p className="analysis-note">原件已归档；可直接查阅单元格。结构确认和分析口径另行保存。</p>
    {loading && <p role="status">正在读取工作表目录…</p>}
    {errors.map((error) => <p role="alert" key={error}>{error}</p>)}
    {sheets.length > 0 && <SearchableSelect label="查找工作表" value={selection} onChange={setSelection}
      options={sheets.map((sheet) => ({ value: sheetKey(sheet), label: sheet.name,
        meta: `${sheet.dataset.name} · ${sheet.rows} 行 × ${sheet.columns} 列` }))} placeholder="搜索工作簿或工作表名称" />}
    {selected && <WorkbookBrowser key={`${taskId}:${selection}`} taskId={taskId} datasetId={selected.dataset.id}
      initialSheet={selected.name} showSheetPicker={false} />}
  </section>;
}
const sheetKey = (sheet: Sheet) => JSON.stringify([sheet.dataset.id, sheet.name]);
