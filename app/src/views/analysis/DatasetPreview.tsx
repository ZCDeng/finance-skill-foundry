import type { DatasetSnapshot } from '../../bridge.js';
import { Table, textValue } from './presentation.js';
import { TechnicalInfo } from './TechnicalInfo.js';

export function DatasetPreview({ source, content }: { source: DatasetSnapshot; content: Record<string, unknown> }) {
  const columns = Array.isArray(content.columns) ? content.columns.map((column: unknown) => typeof column === 'string'
    ? { name: column } : column as { name: string; type?: string }) : source.schema ?? [];
  const rows = Array.isArray(content.rows) ? content.rows as Record<string, unknown>[] : [];
  const workbook = content.workbook as { sheets?: { name: string; rows: number; columns: number }[] } | undefined;
  return <article className="analysis-source-preview"><h3>{source.name}</h3>
    {source.kind === 'workbook' && <>
      <p className="analysis-note">已保留完整工作簿及所有工作表。请与助手确定分析范围，封面和标题不会被当作数据表头。</p>
      {Array.isArray(workbook?.sheets) && <Table caption="工作表目录"
        columns={[{ name: '工作表' }, { name: '已用行' }, { name: '已用列' }]}
        rows={workbook.sheets.map((sheet) => ({ 工作表: sheet.name, 已用行: sheet.rows, 已用列: sheet.columns }))} />}
    </>}
    {columns.length > 0 && <Table columns={columns} rows={rows} caption="资料预览" />}
    {typeof content.text === 'string' && <><pre className="analysis-source-text">{content.text.slice(0, 30000)}</pre>
      {content.text.length > 30000 && <p className="analysis-note">当前显示前 30,000 个字符，助手可以继续读取全文。</p>}</>}
    {Boolean(content.truncated) && <p className="analysis-note">当前仅显示部分内容。</p>}
    <details className="analysis-details"><summary>来源与资料范围</summary><p>原始文件：{source.source_name ?? source.name}</p>{Object.entries(source.metadata ?? {}).map(([key, value]) =>
      <p key={key}>{key}：{textValue(value)}</p>)}
      {columns.length > 0 && <p>字段：{columns.map((column) => `${column.name}${column.type ? ` (${column.type})` : ''}`).join('、')}</p>}
    </details>
    <TechnicalInfo rows={[['资料编号', source.id], ['原始摘要', source.source_hash ?? source.sha256]]} /></article>;
}
