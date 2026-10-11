import { type FormEvent, useEffect, useState } from 'react';
import { bridge, type DatasetSnapshot } from '../../bridge.js';
import { Button } from '../../components/ui/button.js';
import { Input } from '../../components/ui/input.js';
import { SearchableSelect } from '../../components/FinancialControls.js';
import { WorkbookBrowser } from './WorkbookBrowser.js';
import { Loading, SkeletonRows } from '../../components/Loading.js';

type Sheet = { dataset: DatasetSnapshot; name: string; rows: number; columns: number };
export function WorkbookOverview({ taskId, datasets }: { taskId: string; datasets: DatasetSnapshot[] }) {
  const workbooks = datasets.filter((dataset) => dataset.kind === 'workbook');
  const signature = JSON.stringify(workbooks.map((dataset) => [dataset.id, dataset.source_hash]));
  const [sheets, setSheets] = useState<Sheet[]>([]);
  const [selection, setSelection] = useState('');
  const [jumpText, setJumpText] = useState('');
  const [jumpRange, setJumpRange] = useState('A1:L40');
  const [jumpError, setJumpError] = useState('');
  const [errors, setErrors] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    let active = true;
    setSheets([]); setSelection(''); setJumpText(''); setJumpRange('A1:L40'); setJumpError(''); setErrors([]); setLoading(false);
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
  function jump(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const separator = jumpText.lastIndexOf('!');
    const name = jumpText.slice(0, separator).trim().replace(/^'(.*)'$/, '$1');
    const range = jumpText.slice(separator + 1).trim().toUpperCase();
    if (separator < 1 || !/^[A-Z]{1,3}[1-9]\d*(?::[A-Z]{1,3}[1-9]\d*)?$/.test(range)) {
      setJumpError('请输入“工作表!B36:I39”形式的单元格区域。');
      return;
    }
    const matches = sheets.filter((sheet) => name === sheet.name
      || name === `${sheet.dataset.name}/${sheet.name}`
      || name === `${sheet.dataset.source_name}/${sheet.name}`);
    if (matches.length !== 1) {
      setJumpError(matches.length ? '多个工作簿有同名工作表，请加“工作簿名/”。' : '未找到工作表，请核对名称或从下方列表选择。');
      return;
    }
    setJumpError('');
    setSelection(sheetKey(matches[0]));
    setJumpRange(range);
  }
  return <section className="analysis-workbook-overview" aria-label="工作簿总览">
    <h3>工作簿总览 · {workbooks.length} 本 · {sheets.length} 张工作表</h3>
    <p className="analysis-note">原件已归档，可以直接查阅单元格。</p>
    {loading && (sheets.length ? <p role="status">正在读取工作表目录…</p>
      : <Loading label="正在读取工作表目录…"><SkeletonRows rows={5} /></Loading>)}
    {errors.map((error) => <p role="alert" key={error}>{error}</p>)}
    {sheets.length > 0 && <form className="analysis-workbook-overview-jump" onSubmit={jump}>
      <label>快速定位工作表及区域
        <Input value={jumpText} onChange={(event) => setJumpText(event.target.value)}
          placeholder="例如 01·年度预算总表!B36:I39" />
      </label>
      <Button type="submit" variant="outline">定位区域</Button>
    </form>}
    {jumpError && <p role="alert" className="analysis-structure-error">{jumpError}</p>}
    {sheets.length > 0 && <SearchableSelect label="查找工作表" value={selection} onChange={(value) => { setSelection(value); setJumpRange('A1:L40'); setJumpError(''); }}
      options={sheets.map((sheet) => ({ value: sheetKey(sheet), label: sheet.name,
        meta: `${sheet.dataset.name} · ${sheet.rows} 行 × ${sheet.columns} 列` }))} placeholder="搜索工作簿或工作表名称" />}
    {selected && <WorkbookBrowser key={`${taskId}:${selection}:${jumpRange}`} taskId={taskId} datasetId={selected.dataset.id}
      initialSheet={selected.name} initialRange={jumpRange} showSheetPicker={false} />}
  </section>;
}
const sheetKey = (sheet: Sheet) => JSON.stringify([sheet.dataset.id, sheet.name]);
