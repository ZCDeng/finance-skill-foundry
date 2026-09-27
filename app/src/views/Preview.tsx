import { Eye, X } from 'lucide-react';

import { type PreviewSpec, type TaskRow } from '../bridge.js';
import { TechnicalInfo } from './analysis/TechnicalInfo.js';

/**
 * The strip above a workbook being looked at.
 *
 * The viewer under it is a native view, like the harness page, so this line
 * is the whole of what this app says about it: which task, which version, and
 * that nothing typed into it lands anywhere. The close control is here for
 * the same reason -- a button drawn in the column would be under the view.
 *
 * It says the gateway's origin because the operator accepted a server that
 * lives only while this strip does (KTD20), and a strip that names it is a
 * strip that can be checked against `lsof`.
 */
export function PreviewBar({
  preview,
  task,
  onClose,
  onTechnicalOpenChange,
}: {
  preview: PreviewSpec;
  task: TaskRow | null;
  onClose(): void;
  onTechnicalOpenChange?(open: boolean): void;
}) {
  return (
    <div className="fnd-taskbar">
      <Eye size={13} strokeWidth={1.5} aria-hidden />
      <span className="fnd-title">表格预览</span>
      <span className="fnd-taskbar__sep">/</span>
      <span className="fnd-muted">{task?.title ?? '当前任务'}</span>
      <span className="fnd-taskbar__sep">/</span>
      <span className="fnd-muted">{preview.excel_range
        ? `看的是授权预览副本 · ${preview.excel_range} · 在这里改什么都不落盘`
        : '看的是归档副本，在这里改什么都不落盘'}</span>
      <span className="fnd-taskbar__technical">
        <TechnicalInfo rows={[['任务编号', preview.task], ['资料摘要', preview.sha256], ['预览服务', preview.origin]]} onToggle={onTechnicalOpenChange} />
      </span>
      <span className="fnd-taskbar__spacer" />
      <button type="button" className="fnd-start" onClick={onClose}>
        <X size={13} strokeWidth={1.5} aria-hidden />
        关闭预览
      </button>
    </div>
  );
}
