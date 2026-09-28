import { Node } from '@tiptap/core';
import { normalizeReportVisual, renderReportVisualSvg, reportVisualCaption } from '../../../electron/reports/visuals.js';

export const REPORT_VISUAL_EDIT_EVENT = 'foundry:report-visual-edit';

/** Only the shared renderer creates SVG. Pasted HTML cannot construct a visual node. */
export const ReportVisualNode = Node.create({
  name: 'reportVisual',
  group: 'block',
  atom: true,
  selectable: true,
  draggable: true,
  addAttributes: () => ({ visual: { default: null, rendered: false } }),
  parseHTML: () => [],
  renderHTML: ({ node }) => ['figure', { 'data-report-visual': 'true', class: 'report-visual' }, reportVisualCaption(node.attrs.visual)],
  addNodeView() {
    return ({ node, editor, getPos }) => {
      const dom = document.createElement('div');
      dom.className = 'report-visual-node';
      dom.contentEditable = 'false';
      const content = document.createElement('div');
      content.className = 'report-visual-node__graphic';
      const edit = document.createElement('button');
      edit.type = 'button';
      edit.className = 'report-visual-node__edit';
      edit.textContent = '编辑图表';
      edit.addEventListener('click', () => {
        const position = getPos();
        if (typeof position !== 'number' || !editor.isEditable) return;
        editor.commands.setNodeSelection(position);
        editor.view.dom.dispatchEvent(new CustomEvent(REPORT_VISUAL_EDIT_EVENT, { detail: { position } }));
      });
      dom.append(content, edit);
      const render = () => {
        try {
          const visual = normalizeReportVisual(node.attrs.visual);
          content.innerHTML = renderReportVisualSvg(visual);
          edit.setAttribute('aria-label', `编辑图表：${visual.title}`);
        } catch {
          content.textContent = '此图表暂时无法显示，请检查图表设置。';
        }
      };
      render();
      return {
        dom,
        update(next) { if (next.type.name !== 'reportVisual') return false; node = next; render(); return true; },
        selectNode() { dom.classList.add('ProseMirror-selectednode'); },
        deselectNode() { dom.classList.remove('ProseMirror-selectednode'); },
        stopEvent: (event) => edit.contains(event.target as globalThis.Node),
        ignoreMutation: () => true,
      };
    };
  },
});
