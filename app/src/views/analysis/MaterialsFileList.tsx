import { useEffect, useState, type ReactNode } from 'react';
import { ChevronDown, TriangleAlert } from 'lucide-react';
import { when, type DatasetSnapshot } from '../../bridge.js';
import { Button } from '../../components/ui/button.js';
import { formatPeriod } from '../../lib/period.js';
import { DatasetPreview } from './DatasetPreview.js';
import { FormulaHealthDetails, issuesOf, useFormulaHealth } from './FormulaHealthPanel.js';
import { StructurePendingStrip, StructureProposalCard } from './StructureProposalCard.js';
import { isStructureTodo, useStructureTodos, type StructureTodo } from './StructurePanel.js';
import { textValue } from './presentation.js';
import { datasetSize } from './shared.js';

export type MaterialsPreview = { source: DatasetSnapshot; content: Record<string, unknown> };
type Opened = { structure?: boolean; health?: boolean };

const KIND_LABELS: Record<string, string> = { table: '数据表', background: '背景资料', workbook: 'Excel 工作簿' };

/**
 * One line under the file name: what it is, how big, where a derived table came from,
 * when it was added, and the period, unit and currency it declares. The period reads as
 * words (formatPeriod); unit and currency stay as written.
 */
export function fileMeta(dataset: DatasetSnapshot, datasets: DatasetSnapshot[] = []): string {
  const metadata = dataset.metadata ?? {};
  const parentId = typeof metadata.derived_from === 'string' ? metadata.derived_from : '';
  const parent = parentId ? datasets.find((item) => item.id === parentId)?.name ?? '原工作簿' : '';
  const origin = parent ? `来自 ${[parent, textValue(metadata.sheet ?? '')].filter(Boolean).join(' / ')}` : '';
  const declared = [metadata.period != null ? formatPeriod(metadata.period) : '',
    ...(['unit', 'currency'] as const).map((key) => metadata[key] != null ? textValue(metadata[key]) : '')].filter(Boolean);
  return [KIND_LABELS[dataset.kind] ?? dataset.kind, datasetSize(dataset), origin, when(dataset.created_at), ...declared]
    .filter(Boolean).join(' · ');
}

/** Where the month-close page and the guide land on the 资料 page; a structure to-do falls back to the list. */
export function materialsAnchor(target: 'scope' | 'structure' | 'datasets'): Element | null {
  if (target === 'scope') return document.querySelector('.analysis-scope-card');
  if (target === 'structure') return document.querySelector('[data-structure-todo]') ?? document.querySelector('.analysis-source-list');
  return document.querySelector('.analysis-source-list');
}

const rowId = (datasetId: string, part: 'structure' | 'health' | 'content') => `materials-${datasetId}-${part}`;

function Toggle({ expanded, controls, name, onClick, disabled, children }: {
  expanded: boolean; controls: string; name: string; onClick(): void; disabled?: boolean; children: ReactNode;
}) {
  return <Button type="button" variant="outline" size="sm" className="analysis-file-toggle" aria-expanded={expanded} aria-controls={controls}
    aria-label={name} disabled={disabled} onClick={onClick}>{children}<ChevronDown size={14} strokeWidth={1.5} aria-hidden /></Button>;
}

/**
 * The 资料 page's file list: one row per file, and under it, opened in place, the
 * file's table structure, its formula health and its content. Each opens on its own.
 */
export function MaterialsFileList({ taskId, datasets, busy, preview, onPreview, onClosePreview, onRefresh }: {
  taskId: string; datasets: DatasetSnapshot[]; busy: boolean;
  /** The file whose content is open, if any; owned by the page so 结果 can open one too. */
  preview: MaterialsPreview | null;
  onPreview(source: DatasetSnapshot): void; onClosePreview(): void;
  onRefresh(): Promise<void> | void;
}) {
  const structure = useStructureTodos(taskId, datasets);
  const health = useFormulaHealth(taskId);
  const [opened, setOpened] = useState<Record<string, Opened>>({});
  useEffect(() => { setOpened({}); }, [taskId]);
  const toggle = (id: string, part: keyof Opened, value?: boolean) =>
    setOpened((current) => ({ ...current, [id]: { ...current[id], [part]: value ?? !current[id]?.[part] } }));
  const settle = async () => { await structure.reload(); await onRefresh(); };
  const nameOf = (id: string) => datasets.find((item) => item.id === id)?.name ?? id;

  function structureState(id: string, name: string, todo: StructureTodo | undefined): { word: string; action?: ReactNode } | null {
    const open = Boolean(opened[id]?.structure);
    const button = (text: string, label: string) => <Toggle expanded={open} controls={rowId(id, 'structure')} name={`${label}：${name}`}
      onClick={() => toggle(id, 'structure')}>{text}</Toggle>;
    if (todo?.pending) return { word: '待追认', action: button('处理', '处理表结构追认') };
    const state = todo?.proposal?.structure_state;
    if (state === 'pending_confirmation') return { word: '待确认', action: button('去确认', '去确认表结构') };
    if (state === 'no_table') return { word: '没有识别出数据表', action: button('查看原因', '查看原因') };
    if (state === 'pending_acknowledgement') return { word: '待追认' };
    if (state === 'confirmed') return { word: '已确认' };
    return null;
  }

  function healthState(dataset: DatasetSnapshot): { word: ReactNode; action?: ReactNode } | null {
    const entry = health.entryOf(dataset);
    if (!entry) return null;
    const id = dataset.id;
    if (!entry.health) {
      return { word: '未做', action: <Button type="button" variant="outline" size="sm" disabled={Boolean(health.working)}
        aria-label={`体检这本工作簿：${dataset.name}`} onClick={() => void health.check(dataset).then((result) => {
          if (result && result.status === 'checked' && issuesOf(result).length) toggle(id, 'health', true);
        })}>{health.working === id ? '正在体检…' : '体检'}</Button> };
    }
    if (entry.health.status !== 'checked') return { word: '未能完成（不影响使用）' };
    const issues = issuesOf(entry.health);
    if (!issues.length) return { word: '无提示' };
    const warnings = issues.filter((issue) => issue.severity === 'warning').length;
    return {
      word: <>{issues.length} 类提示{warnings ? <span className="analysis-file-state-warning"><TriangleAlert size={13} strokeWidth={1.5} aria-hidden />其中 {warnings} 类需留意</span> : null}</>,
      action: <Toggle expanded={Boolean(opened[id]?.health)} controls={rowId(id, 'health')} name={`查看公式体检提示：${dataset.name}`}
        onClick={() => toggle(id, 'health')}>查看</Toggle>,
    };
  }

  function row(id: string, dataset: DatasetSnapshot | null) {
    const name = dataset?.name ?? nameOf(id);
    const todo = structure.byDataset[id];
    const structureNow = structureState(id, name, todo);
    const healthNow = dataset ? healthState(dataset) : null;
    const entry = dataset ? health.entryOf(dataset) : null;
    const showing = Boolean(dataset && preview?.source.id === id);
    const structureOpen = Boolean(opened[id]?.structure) && isStructureTodo(todo);
    const healthOpen = Boolean(opened[id]?.health) && Boolean(entry?.health && issuesOf(entry.health).length);
    return <li key={id} className="analysis-file-row" data-structure-todo={isStructureTodo(todo) ? '' : undefined}>
      <div className="analysis-file-row-head">
        <div className="analysis-file-row-name">
          <span className="fnd-title">{name}</span>
          <span className="analysis-source-meta">{dataset ? fileMeta(dataset, datasets) : '这份资料不在当前列表里'}</span>
        </div>
        <div className="analysis-file-row-states">
          {structureNow && <span className="analysis-file-status">
            <span className="analysis-file-status-label">表结构</span>
            <span className="analysis-file-state">{structureNow.word}</span>{structureNow.action}
          </span>}
          {healthNow && <span className="analysis-file-status">
            <span className="analysis-file-status-label">公式体检</span>
            <span className="analysis-file-state">{healthNow.word}</span>{healthNow.action}
          </span>}
          {dataset && <Toggle expanded={showing} controls={rowId(id, 'content')} name={`查看内容：${name}`} disabled={busy}
            onClick={() => (showing ? onClosePreview() : onPreview(dataset))}>查看内容</Toggle>}
        </div>
      </div>
      {structureOpen && <div id={rowId(id, 'structure')} className="analysis-file-row-detail">
        {todo?.pending
          ? <StructurePendingStrip taskId={taskId} datasetName={name} confirmation={todo.pending} busy={busy} onSettled={settle} />
          : <StructureProposalCard taskId={taskId} datasetName={name} proposal={todo!.proposal!} busy={busy} onSettled={settle} />}
      </div>}
      {healthOpen && dataset && entry?.health && <div id={rowId(id, 'health')} className="analysis-file-row-detail">
        <FormulaHealthDetails taskId={taskId} dataset={dataset} health={entry.health} />
      </div>}
      {showing && preview && <div id={rowId(id, 'content')} className="analysis-file-row-detail">
        <DatasetPreview source={preview.source} content={preview.content} headingHidden />
      </div>}
    </li>;
  }

  const listed = preview ? datasets.some((dataset) => dataset.id === preview.source.id) : true;
  return <>
    {[structure.error, health.error].filter(Boolean).map((failure) =>
      <p key={failure} role="alert" className="analysis-message analysis-message--error">{failure}</p>)}
    <ul className="analysis-source-list" aria-label="资料文件">
      {datasets.map((dataset) => row(dataset.id, dataset))}
      {structure.orphans.map((id) => row(id, null))}
    </ul>
    {/* A file opened from a result that this list does not hold keeps its preview below the list. */}
    {preview && !listed && <DatasetPreview source={preview.source} content={preview.content} />}
  </>;
}
