import { type FormEvent, type KeyboardEvent, useEffect, useMemo, useRef, useState } from 'react';
import { Search } from 'lucide-react';
import { bridge, type Answer } from '../../bridge.js';
import { Button } from '../../components/ui/button.js';
import { Input } from '../../components/ui/input.js';
import './WorkbookBrowser.css';
import { scenarioLabel } from './glossary.js';
import { errorText, unwrap } from './shared.js';
import { NativeSelect } from '../../components/ui/native-select.js';

export interface WorkbookCellPreview {
  address: string;
  row: number;
  column: number;
  column_letter: string;
  kind: string;
  display: string;
  exact: string | null;
  formula: string | null;
  cached_value_available: boolean;
  cached_value: string | null;
  number_format: string;
  merged: boolean;
}

export interface WorkbookRangePreview {
  dataset_id: string;
  source_hash: string;
  source_name: string;
  sheet: string;
  range: string;
  bounds: { min_row: number; min_col: number; max_row: number; max_col: number };
  header_context?: { address: string; text: string }[];
  cells: WorkbookCellPreview[];
  warnings: string[];
}

export function WorkbookBrowser({
  taskId,
  datasetId,
  initialSheet,
  initialRange = 'A1:L40',
  sheets = [],
  sheetContext = {},
  showSheetPicker = true,
  onRangePicked,
}: {
  taskId: string;
  datasetId: string;
  initialSheet: string;
  initialRange?: string;
  sheets?: string[];
  sheetContext?: Record<string, { period?: string; unit?: string; currency?: string; scenario?: string; granularity?: string }>;
  showSheetPicker?: boolean;
  onRangePicked?(range: { sheet: string; range: string; preview: WorkbookRangePreview }): void;
}) {
  const [sheet, setSheet] = useState(initialSheet);
  const [sheetQuery, setSheetQuery] = useState('');
  const [range, setRange] = useState(initialRange);
  const [preview, setPreview] = useState<WorkbookRangePreview | null>(null);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState('');
  const requestSeq = useRef(0);

  useEffect(() => {
    requestSeq.current += 1;
    setSheet(initialSheet);
    setSheetQuery('');
    setRange(initialRange);
    setPreview(null);
    setError('');
  }, [datasetId, initialSheet, initialRange]);

  const filteredSheets = useMemo(() => {
    const query = sheetQuery.trim().toLocaleLowerCase();
    if (!query) return sheets;
    return sheets.filter((name) => name.toLocaleLowerCase().includes(query));
  }, [sheetQuery, sheets]);

  const context = sheetContext[sheet] ?? {};
  const contextText = [
    context.period ? `期间 ${context.period}` : '',
    context.granularity ? `粒度 ${context.granularity}` : '',
    context.unit ? `单位 ${context.unit}` : '',
    context.currency ? `币种 ${context.currency}` : '',
    context.scenario ? `情景 ${scenarioLabel(context.scenario)}` : '',
  ].filter(Boolean).join(' · ');

  const rows = useMemo(() => {
    if (!preview) return [];
    const byRow = new Map<number, WorkbookCellPreview[]>();
    for (const cell of preview.cells) {
      const current = byRow.get(cell.row) ?? [];
      current.push(cell);
      byRow.set(cell.row, current);
    }
    return [...byRow.entries()].sort(([a], [b]) => a - b);
  }, [preview]);

  const columns = useMemo(() => {
    if (!preview) return [];
    const byColumn = new Map<number, string>();
    for (const cell of preview.cells) byColumn.set(cell.column, cell.column_letter);
    return [...byColumn.entries()].sort(([a], [b]) => a - b).map(([, letter]) => letter);
  }, [preview]);

  useEffect(() => {
    if (!sheet.trim()) return;
    void load();
    // Selection changes should preview the current range. Range edits submit on Enter/button.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId, datasetId, sheet]);

  async function load() {
    const api = bridge();
    if (!api?.financeCall) return;
    const seq = requestSeq.current + 1;
    requestSeq.current = seq;
    const expectedTask = taskId;
    const expectedDataset = datasetId;
    const expectedSheet = sheet;
    const expectedRange = range;
    setWorking(true);
    setError('');
    try {
      const spec: { dataset_id: string; sheet: string; range?: string } = {
        dataset_id: expectedDataset,
        sheet: expectedSheet,
      };
      if (expectedRange.trim() && expectedRange.trim() !== 'A1:L40') {
        spec.range = expectedRange;
      }
      const next = unwrapAnswer<WorkbookRangePreview>(
        await api.financeCall(expectedTask, 'workbook-range-preview', spec),
      );
      if (
        requestSeq.current !== seq
        || taskId !== expectedTask
        || datasetId !== expectedDataset
        || sheet !== expectedSheet
      ) return;
      setPreview(next);
      onRangePicked?.({ sheet: next.sheet, range: next.range, preview: next });
    } catch (failure) {
      if (requestSeq.current !== seq) return;
      setError(errorText(failure));
    } finally {
      if (requestSeq.current === seq) setWorking(false);
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void load();
  }

  function submitRangeOnEnter(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key !== 'Enter') return;
    event.preventDefault();
    void load();
  }

  return (
    <section
      className="analysis-workbook-browser"
      aria-label={`工作簿区域预览 ${preview ? `${preview.sheet} ${preview.range}` : `${sheet} ${range}`}`}
    >
      <form className="analysis-workbook-browser-form" onSubmit={submit}>
        {showSheetPicker && sheets.length > 0 && (
          <label>
            搜索工作表
            <Input value={sheetQuery} disabled={working} onChange={(event) => setSheetQuery(event.target.value)} />
          </label>
        )}
        {showSheetPicker ? (
          <label>
            工作表
            {sheets.length > 0 ? (
              <NativeSelect value={sheet} disabled={working} onChange={(event) => setSheet(event.target.value)}>
                {filteredSheets.map((name) => <option key={name} value={name}>{name}</option>)}
              </NativeSelect>
            ) : (
              <Input value={sheet} disabled={working} onChange={(event) => setSheet(event.target.value)} />
            )}
          </label>
        ) : <span className="analysis-note">工作表 {sheet}</span>}
        <label>
          区域
          <Input
            value={range}
            disabled={working}
            onChange={(event) => setRange(event.target.value)}
            onKeyDown={submitRangeOnEnter}
          />
        </label>
        <Button type="submit" variant="outline" disabled={working || !sheet.trim()}>
          <Search size={15} strokeWidth={1.5} aria-hidden />预览区域
        </Button>
      </form>
      {contextText && <p className="analysis-note">{contextText}</p>}
      {error && <p role="alert" className="analysis-structure-error">{error}</p>}
      {preview?.header_context?.length ? <div className="analysis-workbook-context" aria-label="原表标题区">
        <span>原表标题区：</span>
        {preview.header_context.map((cell) => <span key={cell.address}>{cell.address}：{cell.text}</span>)}
      </div> : null}
      {preview && (
        <div className="analysis-workbook-grid-wrap">
          <table className="analysis-workbook-grid" aria-label={preview ? `${preview.sheet} ${preview.range}` : undefined}>
            <caption className="analysis-note">
              {preview.sheet} {preview.range} · {preview.source_name}
            </caption>
            <thead>
              <tr>
                <th scope="col" className="analysis-workbook-corner" aria-label="行号" />
                {columns.map((letter) => <th key={letter} scope="col">{letter}</th>)}
              </tr>
            </thead>
            <tbody>
              {rows.map(([row, cells]) => (
                <tr key={row}>
                  <th scope="row">{row}</th>
                  {cells.map((cell) => (
                    <td key={cell.address} title={cellTitle(cell)}>
                      {cell.formula ? <span className="analysis-workbook-formula">{cell.formula}</span> : cell.display}
                      {cell.formula && !cell.cached_value_available ? '（无缓存值）' : ''}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function unwrapAnswer<T>(answer: Answer<Record<string, unknown>>): T {
  return unwrap(answer) as T;
}

function cellTitle(cell: WorkbookCellPreview): string {
  const lines = [`${cell.address}`];
  if (cell.formula) lines.push(`公式：${cell.formula}`);
  lines.push(`显示值：${cell.display}`);
  if (cell.exact) lines.push(`原始值：${cell.exact}`);
  if (cell.cached_value_available && cell.cached_value) lines.push(`缓存值：${cell.cached_value}`);
  if (cell.number_format) lines.push(`格式：${cell.number_format}`);
  return lines.join('\n');
}
