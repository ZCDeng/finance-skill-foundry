import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { EditorContent, useEditor, type Editor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { Image } from "@tiptap/extension-image";
import {
  Table as TiptapTable,
  TableCell,
  TableHeader,
  TableRow,
} from "@tiptap/extension-table";
import TextAlign from "@tiptap/extension-text-align";
import { Extension, Node, mergeAttributes } from "@tiptap/core";
import {
  Bold,
  ChartNoAxesCombined,
  Code,
  Columns2,
  Download,
  FileSpreadsheet,
  FileText,
  Heading1,
  Heading2,
  Highlighter,
  ImagePlus,
  Italic,
  Link as LinkIcon,
  List,
  ListOrdered,
  ListTree,
  Redo2,
  Rows3,
  Scissors,
  Sparkles,
  Trash2,
  SplitSquareHorizontal,
  Table2,
  Undo2,
  Upload,
} from "lucide-react";
import type { AnalysisRun, Answer } from "../../bridge.js";
import { bridge } from "../../bridge.js";
import { WaitLoop } from "../../components/WaitLoop.js";
import { Button } from "../../components/ui/button.js";
import { Input } from "../../components/ui/input.js";
import { Textarea } from "../../components/ui/textarea.js";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuShortcut,
  DropdownMenuTrigger,
} from "../../components/ui/dropdown-menu.js";
import type {
  ReportDocument,
  ReportExportFormat,
  ReportImportResult,
  ReportNode,
  ReportProjectionMode,
  ReportSource,
} from "../../../electron/reports/model.js";
import {
  reflowReportParagraphs,
  type ReportParagraphReflowResult,
} from "../../../electron/reports/readability.js";
import {
  documentFromMarkdown,
  documentToMarkdown,
  renderReportHtml,
  safeHref,
  textContent,
} from "../../../electron/reports/format.js";
import "./report.css";
import { errorText, unwrap } from './shared.js';
import { ReportVisualComposer } from './ReportVisualComposer.js';
import { ReportReviewAction } from './ReportReviewPanel.js';
import { REPORT_VISUAL_EDIT_EVENT, ReportVisualNode } from './ReportVisualNode.js';
import { normalizeReportVisual, type ReportVisual } from '../../../electron/reports/visuals.js';
import { NativeSelect } from '../../components/ui/native-select.js';
import { DisclosureSummary } from '../../components/Disclosure.js';
import { ReportMinimap, useActiveHeading } from './ReportMinimap.js';

type ReportMode = "read" | "edit" | "print";
type ExportFormat = ReportExportFormat;
type ReportBridge = ReturnType<typeof bridge> & {
  reportImport?(
    task: string,
    options?: {
      sourceId?: string;
      sheet?: string;
      range?: string;
      ocr?: boolean;
    },
  ): Promise<Answer<ReportImportResult>>;
  reportSource?(
    task: string,
    sourceId: string,
  ): Promise<Answer<{ source: ReportSource; data_base64: string }>>;
  reportCancel?(task: string): Promise<Answer<{ cancelled?: boolean }>>;
  reportPreview?(
    task: string,
    document: ReportDocument,
    title: string,
  ): Promise<Answer<{ html: string }>>;
};

export type ReportDraftDocument = ReportDocument;
export type ReportDraftEdit = {
  document?: ReportDocument;
  sourceMode?: boolean;
  importedSource?: ReportSource;
};

/** The export menu's formats, in its order. 成果库 lists a revision's exports the same way. */
export const EXPORT_MENU_FORMATS: ExportFormat[] = ["docx", "pdf", "html", "md", "xlsx"];
const MAX_IMAGE_BYTES = 2 * 1024 * 1024;
const IMAGE_TYPES = new Set(["image/png", "image/jpeg"]);

const ReportMetadataAttributes = Extension.create({
  name: "reportMetadataAttributes",
  addGlobalAttributes() {
    const sourceAttrs = {
      source_id: {
        default: null,
        parseHTML: (element: HTMLElement) =>
          element.getAttribute("data-source-id"),
      },
      page: {
        default: null,
        parseHTML: (element: HTMLElement) => element.getAttribute("data-page"),
      },
      sheet: {
        default: null,
        parseHTML: (element: HTMLElement) => element.getAttribute("data-sheet"),
      },
      range: {
        default: null,
        parseHTML: (element: HTMLElement) => element.getAttribute("data-range"),
      },
    };
    return [
      {
        types: [
          "paragraph",
          "heading",
          "blockquote",
          "codeBlock",
          "bulletList",
          "orderedList",
          "listItem",
          "table",
          "tableRow",
          "tableCell",
          "tableHeader",
          "image",
          "reportNote",
          "reportPageBreak",
        ],
        attributes: sourceAttrs,
      },
      {
        types: ["table"],
        attributes: {
          caption: {
            default: null,
            parseHTML: (element: HTMLElement) =>
              element.getAttribute("data-caption"),
          },
          period: {
            default: null,
            parseHTML: (element: HTMLElement) =>
              element.getAttribute("data-period"),
          },
          currency: {
            default: null,
            parseHTML: (element: HTMLElement) =>
              element.getAttribute("data-currency"),
          },
          unit: {
            default: null,
            parseHTML: (element: HTMLElement) =>
              element.getAttribute("data-unit"),
          },
        },
      },
    ];
  },
});

const ReportPageBreak = Node.create({
  name: "reportPageBreak",
  group: "block",
  atom: true,
  parseHTML: () => [{ tag: "hr[data-report-page-break]" }],
  renderHTML: ({ HTMLAttributes }) => [
    "hr",
    mergeAttributes(HTMLAttributes, {
      "data-report-page-break": "true",
      class: "report-page-break",
    }),
  ],
});

const ReportNote = Node.create({
  name: "reportNote",
  group: "block",
  content: "block+",
  defining: true,
  addAttributes() {
    return { id: { default: "" } };
  },
  parseHTML: () => [{ tag: "aside[data-report-note]" }],
  renderHTML: ({ node, HTMLAttributes }) => [
    "aside",
    mergeAttributes(HTMLAttributes, {
      "data-report-note": "true",
      "data-note-id": node.attrs.id || "注",
      class: "report-note",
    }),
    0,
  ],
});

function documentFromEditor(
  editor: Editor,
  previous: ReportDocument | undefined,
): ReportDocument {
  const json = editor.getJSON() as { content?: ReportNode[] };
  return {
    schema_version: 1,
    template_version: "annual-v1",
    metadata: previous?.metadata ?? {
      company: "",
      period: "",
      currency: "",
      unit: "",
    },
    content: cleanEditorNodes(json.content ?? []),
    ...(previous?.sources?.length ? { sources: previous.sources } : {}),
  };
}

function cleanEditorNodes(nodes: ReportNode[]): ReportNode[] {
  return nodes.map(cleanEditorNode);
}

function cleanEditorNode(node: ReportNode): ReportNode {
  const next: ReportNode = { type: node.type };
  if (node.text != null) next.text = node.text;
  const attrs = cleanEditorRecord(node.attrs);
  if (attrs) next.attrs = attrs;
  const marks = node.marks?.map((mark) => {
    const cleanMark: NonNullable<ReportNode["marks"]>[number] = {
      type: mark.type,
    };
    const markAttrs = cleanEditorRecord(mark.attrs);
    if (markAttrs) cleanMark.attrs = markAttrs;
    return cleanMark;
  });
  if (marks?.length) next.marks = marks;
  if (node.content) next.content = cleanEditorNodes(node.content);
  return next;
}

function cleanEditorRecord(
  attrs: Record<string, unknown> | undefined,
): Record<string, unknown> | undefined {
  if (!attrs) return undefined;
  const entries = Object.entries(attrs).flatMap(([key, value]) => {
    if (value == null) return [];
    if (Array.isArray(value)) {
      const cleanArray = value.filter((item) => item != null);
      return cleanArray.length ? [[key, cleanArray] as const] : [];
    }
    if (key === "page" || key === "sheet" || key === "range")
      return [[key, String(value)] as const];
    return [[key, value] as const];
  });
  return entries.length ? Object.fromEntries(entries) : undefined;
}

function sameEditorContent(left: unknown, right: unknown): boolean {
  return (
    JSON.stringify(cleanEditorNodes((left ?? []) as ReportNode[])) ===
    JSON.stringify(cleanEditorNodes((right ?? []) as ReportNode[]))
  );
}

function reportHeadings(
  document: ReportDocument,
  title: string,
): { id: string; level: number; text: string; headingIndex: number }[] {
  let headingIndex = 0;
  const normalizedTitle = normalizeReportTitle(title);
  return document.content.flatMap((node) => {
    if (node.type !== "heading") return [];
    headingIndex += 1;
    const level = Number(node.attrs?.level ?? 1);
    const text = textContent(node).trim();
    if (headingIndex === 1 && level === 1 && normalizeReportTitle(text) === normalizedTitle) return [];
    if (level > 2) return [];
    return [
      {
        id: `section-${headingIndex}`,
        level,
        headingIndex,
        text: text || `章节 ${headingIndex}`,
      },
    ];
  });
}

function normalizeReportTitle(value: string): string {
  return value.replace(/\s+/g, "").trim().toLocaleLowerCase();
}

function appendixMarkdownVariants(appendix?: string): string[] {
  const cleanAppendix = appendix?.trim();
  if (!cleanAppendix) return [];
  const canonicalAppendix = documentToMarkdown(documentFromMarkdown(cleanAppendix)).trim();
  return Array.from(new Set([cleanAppendix, canonicalAppendix]));
}

function exactAppendixResult(
  document: ReportDocument,
  body: string,
  appendix: string | undefined,
  preserveStructured: boolean,
): { document: ReportDocument; folded: boolean } {
  const appendixVariants = appendixMarkdownVariants(appendix);
  if (!appendixVariants.length) return { document, folded: false };
  const trimmedBody = body.trimEnd();
  const matchedAppendix = appendixVariants.find((candidate) => trimmedBody.endsWith(candidate));
  if (!matchedAppendix) return { document, folded: false };
  for (let index = document.content.length - 1; index >= 0; index -= 1) {
    const suffix = {
      ...document,
      metadata: { company: "", period: "", currency: "", unit: "" },
      content: document.content.slice(index),
    };
    if (appendixVariants.includes(documentToMarkdown(suffix).trim()))
      return { document: { ...document, content: document.content.slice(0, index) }, folded: true };
  }
  return preserveStructured
    ? { document, folded: false }
    : {
        document: documentFromMarkdown(
          trimmedBody
            .slice(0, trimmedBody.length - matchedAppendix.length)
            .trimEnd(),
        ),
        folded: true,
      };
}

function sourceLabel(format: ExportFormat): string {
  return (
    {
      docx: "Word",
      pdf: "PDF",
      html: "HTML",
      md: "Markdown",
      xlsx: "Excel",
    } as Record<ExportFormat, string>
  )[format];
}

function exportCommandLabel(format: ExportFormat): string {
  if (format === "md") return "导出文稿";
  if (format === "xlsx") return "导出工作簿";
  return `导出${sourceLabel(format)}`;
}

function formatWarnings(warnings: string[]): string {
  return warnings.length
    ? warnings.join("；")
    : "已转换为可编辑结构，导入的审核状态和证据声明不会被信任。";
}

export function ReportEditor({
  taskId,
  draftId,
  contextId,
  title,
  body,
  appendix,
  limitations,
  review,
  document,
  runs = [],
  busy,
  toolbarLabel = "文稿",
  status,
  assistantAction,
  archiveAction,
  initialMode = "read",
  mode: controlledMode,
  onMode,
  onTitle,
  onBody,
  onDocument,
  onLimitations,
  onReview,
  onExport,
  onAppliedDraft,
}: {
  taskId: string;
  draftId?: string;
  contextId?: string;
  title: string;
  body: string;
  appendix?: string;
  limitations: string;
  review: string;
  document?: ReportDocument;
  runs?: AnalysisRun[];
  busy: boolean;
  toolbarLabel?: string;
  status?: string;
  assistantAction?: ReactNode;
  /** The draft's own archive action, beside the export menu. */
  archiveAction?: ReactNode;
  initialMode?: ReportMode;
  mode?: ReportMode;
  onMode?(value: ReportMode): void;
  onTitle(value: string): void;
  onBody(value: string): void;
  onDocument(value: ReportDocument | undefined): void;
  onLimitations(value: string): void;
  onReview(value: string): void;
  onExport(format: ExportFormat, mode?: ReportProjectionMode): void | Promise<void>;
  onAppliedDraft?(draft: { id: string; title?: string; body?: string; document?: ReportDocument }): void;
}) {
  const [localMode, setLocalMode] = useState<ReportMode>(initialMode);
  // The outline opens from the toolbar: a left column when the workspace has room beside the 56rem text column,
  // otherwise a drawer over the text (report.css). The text column keeps its width either way.
  const [outlineOpen, setOutlineOpen] = useState(false);
  const outlineId = useId();
  const outlineRef = useRef<HTMLElement>(null);
  const outlineToggleRef = useRef<HTMLButtonElement>(null);
  const outlineOpenedByToggle = useRef(false);
  const mode = controlledMode ?? localMode;
  const [templates, setTemplates] = useState<{ template_id: string; label: string; kind: string }[]>([]);
  const [templateError, setTemplateError] = useState('');
  const [templateOpen, setTemplateOpen] = useState(false);
  const [sourceMode, setSourceMode] = useState(false);
  const [sourceText, setSourceText] = useState(body);
  const [sourceBackup, setSourceBackup] = useState<{
    body: string;
    document: ReportDocument | undefined;
  } | null>(null);
  const [structuredBackup, setStructuredBackup] = useState<{ body: string; document: ReportDocument | undefined } | null>(null);
  const [visualEditor, setVisualEditor] = useState<{ taskId: string; position?: number; initial?: ReportVisual; original?: string } | null>(null);
  const [linkOpen, setLinkOpen] = useState(false);
  const [linkHref, setLinkHref] = useState("");
  const [noteOpen, setNoteOpen] = useState(false);
  const [noteId, setNoteId] = useState("1");
  const [noteText, setNoteText] = useState("");
  const [toolError, setToolError] = useState("");
  const [circleMessage, setCircleMessage] = useState("");
  const [circleBusy, setCircleBusy] = useState(false);

  const [importing, setImporting] = useState(false);
  const [importPreview, setImportPreview] = useState<ReportImportResult | null>(
    null,
  );
  const [importSheet, setImportSheet] = useState("");
  const [importRange, setImportRange] = useState("");
  const [printHtml, setPrintHtml] = useState("");
  const [pdfSource, setPdfSource] = useState<{
    source: ReportSource;
    dataUrl: string;
  } | null>(null);
  const [reportPhase, setReportPhase] = useState("");
  const [exporting, setExporting] = useState(false);
  const [exportMode, setExportMode] = useState<ReportProjectionMode>("management");
  const [reflowPreview, setReflowPreview] =
    useState<ReportParagraphReflowResult | null>(null);
  const [, setEditorRevision] = useState(0);
  const changeMode = (next: ReportMode) => {
    setLocalMode(next);
    onMode?.(next);
  };
  const imageInput = useRef<HTMLInputElement>(null);
  const editorReady = useRef(false);
  const mainMarkdown = useMemo(() => body, [body]);
  const workingDocument = useMemo(
    () => document ?? documentFromMarkdown(mainMarkdown),
    [document, mainMarkdown],
  );
  const hasVisuals = workingDocument.content.some((node) => node.type === 'reportVisual');
  const isEmptyDocument =
    workingDocument.content.length === 0 ||
    documentToMarkdown(workingDocument).trim() === "";
  const readingResult = useMemo(
    () =>
      exactAppendixResult(workingDocument, body, appendix, Boolean(document)),
    [appendix, body, document, workingDocument],
  );
  const readingDocument = readingResult.document;
  const headings = useMemo(
    () => reportHeadings(readingDocument, title),
    [readingDocument, title],
  );
  const headingIds = useMemo(() => headings.map((item) => item.id), [headings]);
  // Only the reading view carries the heading ids (renderReportHtml); the editor's headings have none.
  const activeHeading = useActiveHeading(headingIds, mode === "read");
  const closeOutline = (returnFocus: boolean) => {
    setOutlineOpen(false);
    if (returnFocus) outlineToggleRef.current?.focus();
  };
  // Whether the open outline is the drawer or the column beside the text is the stylesheet's call (report.css
  // --report-outline-mode); it is read whenever an event needs it, so a resize across the breakpoint is followed.
  const outlineFloating = () => Boolean(outlineRef.current
    && getComputedStyle(outlineRef.current).getPropertyValue("--report-outline-mode").trim() !== "column");
  useEffect(() => {
    if (!outlineOpen) return;
    const aside = outlineRef.current;
    const openedByToggle = outlineOpenedByToggle.current;
    outlineOpenedByToggle.current = false;
    if (!aside) return;
    // A drawer takes the focus while it is open and gives it back to 目录 when it closes.
    if (openedByToggle && outlineFloating()) (aside.querySelector<HTMLElement>("a") ?? aside).focus();
    const page = aside.ownerDocument;
    const toggle = () => outlineToggleRef.current;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || !outlineFloating()) return;
      const active = page.activeElement;
      if (aside.contains(active) || active === toggle()) closeOutline(true);
    };
    const onPointer = (event: PointerEvent) => {
      if (!outlineFloating()) return;
      const target = event.target instanceof Element ? event.target : null;
      if (aside.contains(target) || toggle()?.contains(target)) return;
      const focusable = target?.closest("a[href], button, input, select, textarea, summary, [contenteditable='true'], [tabindex]:not([tabindex='-1'])");
      closeOutline(false);
      // A click on something that takes no focus would leave it nowhere; 目录 takes it back.
      if (!focusable) setTimeout(() => toggle()?.focus(), 0);
    };
    const onFocusOut = (event: FocusEvent) => {
      const next = event.relatedTarget instanceof globalThis.Node ? event.relatedTarget : null;
      if (!next || aside.contains(next) || next === toggle() || !outlineFloating()) return;
      closeOutline(false);
    };
    page.addEventListener("keydown", onKey);
    page.addEventListener("pointerdown", onPointer);
    aside.addEventListener("focusout", onFocusOut);
    return () => {
      page.removeEventListener("keydown", onKey);
      page.removeEventListener("pointerdown", onPointer);
      aside.removeEventListener("focusout", onFocusOut);
    };
  }, [outlineOpen]);
  const editor = useEditor({
    extensions: [
      StarterKit.configure({ heading: { levels: [1, 2, 3, 4, 5, 6] } }),
      ReportMetadataAttributes,
      TextAlign.configure({
        types: ["heading", "paragraph", "tableCell", "tableHeader"],
      }),
      TiptapTable.configure({ resizable: true }),
      TableRow,
      TableHeader,
      TableCell,
      Image.configure({ inline: false, allowBase64: true }),
      ReportNote,
      ReportPageBreak,
      ReportVisualNode,
    ],
    content: { type: "doc", content: workingDocument.content },
    editable: !busy && mode === "edit" && !sourceMode && !visualEditor,
    immediatelyRender: false,
    editorProps: {
      attributes: {
        class: "report-prosemirror",
        "aria-label": "可视化文稿编辑器",
      },
    },
    onUpdate: ({ editor: instance }) => {
      if (!editorReady.current) return;
      const next = documentFromEditor(instance, workingDocument);
      onDocument(next);
      onBody(documentToMarkdown(next));
      onReview("unreviewed");
    },
    onTransaction: () => setEditorRevision((value) => value + 1),
  });

  async function circleSelect() {
    const api = bridge();
    if (!api?.financeCall) return;
    setCircleBusy(true);
    setToolError("");
    setCircleMessage("");
    try {
      if (!draftId) throw new Error("请先保存文稿再圈选调整。");
      if (!contextId) throw new Error("请先保存分析范围。");
      const table = editor?.getAttributes("table") as { caption?: string; id?: string } | undefined;
      const blockId = String(table?.caption || table?.id || "").trim();
      if (!blockId) throw new Error("请先给表加上标题再圈选调整。");
      unwrap(await api.financeCall(taskId, "analysis-circle-select", {
        kind: "draft_table",
        draft_id: draftId,
        block_id: blockId,
        range: "selection",
        instruction: "改成开票口径",
        context_id: contextId,
      }) as Answer<Record<string, unknown>>);
      setCircleMessage("已按圈选生成开票口径修订。");
    } catch (failure) {
      setToolError(errorText(failure));
    } finally {
      setCircleBusy(false);
    }
  }

  useEffect(() => {
    if (!editor) return;
    editorReady.current = false;
    const timer = window.setTimeout(() => {
      editorReady.current = true;
    }, 0);
    editor.setEditable(!busy && mode === "edit" && !sourceMode && !visualEditor);
    return () => window.clearTimeout(timer);
  }, [busy, editor, mode, sourceMode, visualEditor]);

  useEffect(() => {
    setVisualEditor(null);
    setStructuredBackup(null);
  }, [taskId, draftId]);

  useEffect(() => {
    if (!editor) return;
    const editVisual = (event: Event) => {
      const position = (event as CustomEvent<{ position: number }>).detail.position;
      const node = editor.state.doc.nodeAt(position);
      if (busy || sourceMode || node?.type.name !== 'reportVisual') return;
      try { setVisualEditor({ taskId, position, initial: normalizeReportVisual(node.attrs.visual), original: JSON.stringify(node.attrs.visual) }); }
      catch (failure) { setToolError(errorText(failure)); }
    };
    const element = editor.view.dom;
    element.addEventListener(REPORT_VISUAL_EDIT_EVENT, editVisual);
    return () => element.removeEventListener(REPORT_VISUAL_EDIT_EVENT, editVisual);
  }, [editor, busy, sourceMode, taskId]);

  useEffect(() => {
    if (!editor || editor.isFocused) return;
    if (sameEditorContent(editor.getJSON().content, workingDocument.content))
      return;
    editorReady.current = false;
    editor.commands.setContent(
      { type: "doc", content: workingDocument.content },
      { emitUpdate: false },
    );
    const timer = window.setTimeout(() => {
      editorReady.current = true;
    }, 0);
    return () => window.clearTimeout(timer);
  }, [editor, workingDocument]);

  useEffect(() => {
    if (mode !== "print") return;
    let cancelled = false;
    const api = bridge() as ReportBridge;
    const load = async () => {
      try {
        setToolError("");
        if (api?.reportPreview) {
          const result = unwrap(
            await api.reportPreview(taskId, workingDocument, title),
          );
          if (!cancelled) setPrintHtml(result.html);
        } else {
          setPrintHtml(
            renderReportHtml(workingDocument, title, { print: true }),
          );
        }
      } catch (failure) {
        if (!cancelled) {
          setPrintHtml(
            renderReportHtml(workingDocument, title, { print: true }),
          );
          setToolError(
            errorText(failure),
          );
        }
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [mode, taskId, title, workingDocument, limitations]);

  useEffect(() => setSourceText(body), [body]);

  useEffect(() => {
    const api = bridge() as ReportBridge;
    return api?.onReportProgress?.((progress) => {
      if (progress.task === taskId) setReportPhase(progress.phase);
    });
  }, [taskId]);

  const commitDocument = (next: ReportDocument) => {
    onDocument(next);
    onBody(documentToMarkdown(next));
    onReview("unreviewed");
  };

  const changeSourceBody = (next: string) => {
    onDocument(undefined);
    onBody(next);
    onReview("unreviewed");
  };

  const updateMetadata = (
    key: keyof ReportDocument["metadata"],
    value: string,
  ) => {
    commitDocument({
      ...workingDocument,
      metadata: { ...workingDocument.metadata, [key]: value },
    });
  };

  const insertManagementTemplate = () => {
    const sections = [
      "报告信息",
      "管理摘要",
      "经营与预算分析",
      "现金流与周转",
      "风险及行动",
      "财务表格",
      "范围与证据附注",
    ];
    commitDocument({
      ...workingDocument,
      content: sections.flatMap((text) => [
        {
          type: "heading",
          attrs: { level: 1 },
          content: [{ type: "text", text }],
        },
        { type: "paragraph", content: [] },
      ]),
    });
  };

  async function loadTemplates() {
    const api = bridge();
    if (!api?.financeCall) return;
    setTemplateError('');
    try {
      const listed = unwrap(await api.financeCall(taskId, 'report-template-list', {}) as Answer<{ templates?: { template_id: string; label: string; kind: string }[] }>);
      setTemplates(listed.templates ?? []);
    } catch (failure) {
      setTemplateError(errorText(failure));
    }
  }

  async function publishCompanyTemplate() {
    const api = bridge();
    if (!api?.reportTemplatePublish) throw new Error('此版本暂不支持发布公司模板。');
    setTemplateError('');
    try {
      const published = unwrap(await api.reportTemplatePublish(taskId) as Answer<{ cancelled?: boolean; template_id?: string }>);
      if (published && published.cancelled) return;
      await loadTemplates();
    } catch (failure) {
      setTemplateError(errorText(failure));
    }
  }

  async function applyCompanyTemplate(templateId: string) {
    const api = bridge();
    if (!api?.financeCall) throw new Error('此版本暂不支持套用公司模板。');
    setTemplateError('');
    try {
      const applied = unwrap(await api.financeCall(taskId, 'report-template-apply', { template_id: templateId, ...(contextId ? { context_id: contextId } : {}) }) as Answer<{ draft?: { id: string; title?: string; body?: string; document?: ReportDocument } }>);
      const draft = applied.draft;
      if (!draft) throw new Error('套用公司模板没有返回新草稿。');
      if (onAppliedDraft) onAppliedDraft(draft);
      else if (draft.document) commitDocument({ ...draft.document, template_id: templateId });
    } catch (failure) {
      setTemplateError(errorText(failure));
    }
  }

  const openSourceEditor = () => {
    setVisualEditor(null);
    setSourceBackup({ body, document });
    setSourceText(body);
    setSourceMode(true);
  };

  const applySourceEditor = () => {
    if (sourceBackup?.document) setStructuredBackup(sourceBackup);
    changeSourceBody(sourceText);
    setSourceBackup(null);
    setSourceMode(false);
  };

  const restoreStructuredDocument = () => {
    if (!structuredBackup) return;
    onDocument(structuredBackup.document);
    onBody(structuredBackup.body);
    onReview('unreviewed');
    setStructuredBackup(null);
    if (editor) editor.commands.setContent({ type: 'doc', content: structuredBackup.document?.content ?? documentFromMarkdown(structuredBackup.body).content }, { emitUpdate: false });
  };

  const applyVisual = (visual: ReportVisual) => {
    if (!editor || !visualEditor || visualEditor.taskId !== taskId) return;
    const node = { type: 'reportVisual', attrs: { visual } };
    editorReady.current = true;
    if (visualEditor.position != null) {
      const selected = editor.state.doc.nodeAt(visualEditor.position);
      if (selected?.type.name !== 'reportVisual' || JSON.stringify(selected.attrs.visual) !== visualEditor.original) { setToolError('图表内容或位置已变化，请重新选择要编辑的图表。'); setVisualEditor(null); return; }
      editor.chain().focus().insertContentAt({ from: visualEditor.position, to: visualEditor.position + selected.nodeSize }, node).run();
    } else editor.chain().focus().insertContent(node).run();
    setVisualEditor(null);
  };

  const cancelSourceEditor = () => {
    if (sourceBackup) {
      onDocument(sourceBackup.document);
      onBody(sourceBackup.body);
    }
    setSourceText(sourceBackup?.body ?? body);
    setSourceBackup(null);
    setSourceMode(false);
  };

  const insertNote = () => {
    if (!editor) return;
    const id = noteId.trim() || "1";
    const text = noteText.trim() || "待补充附注。";
    editor
      .chain()
      .focus()
      .insertContent({ type: "text", text: ` [^${id}]` })
      .run();
    editor
      .chain()
      .focus("end")
      .insertContent({
        type: "reportNote",
        attrs: { id },
        content: [{ type: "paragraph", content: [{ type: "text", text }] }],
      })
      .run();
    setNoteOpen(false);
    setNoteText("");
  };

  const applyLink = () => {
    if (!editor || !safeHref(linkHref)) return;
    editor.chain().focus().setLink({ href: linkHref }).run();
    setLinkOpen(false);
    setLinkHref("");
  };

  const cancelReportJob = async () => {
    const api = bridge() as ReportBridge;
    try {
      await api?.reportCancel?.(taskId);
    } catch {
      /* best-effort cancellation */
    }
    setImporting(false);
    setExporting(false);
    setReportPhase("");
  };

  const openReflowPreview = () => {
    setToolError("");
    const result = reflowReportParagraphs(workingDocument);
    if (!result.changedParagraphs) {
      setToolError("当前文稿没有可安全拆分的长段落。");
      return;
    }
    setReflowPreview(result);
  };

  const cancelReflowPreview = () => setReflowPreview(null);

  const applyReflowPreview = () => {
    if (!reflowPreview) return;
    const next = reflowPreview.document;
    setReflowPreview(null);
    setSourceMode(false);
    changeMode("edit");
    if (editor) {
      editorReady.current = true;
      const nextDoc = editor.schema.nodeFromJSON({
        type: "doc",
        content: next.content,
      });
      editor.view.dispatch(
        editor.state.tr
          .replaceWith(0, editor.state.doc.content.size, nextDoc.content)
          .scrollIntoView(),
      );
    } else {
      commitDocument(next);
    }
  };

  const handleExport = async (format: ExportFormat) => {
    setExporting(true);
    setReportPhase(`导出 ${exportMode === "audit" ? "审计版" : "管理版"} ${sourceLabel(format)}`);
    try {
      await onExport(format, exportMode);
    } finally {
      setExporting(false);
      setReportPhase("");
    }
  };

  const applyImport = () => {
    if (!importPreview?.document) return;
    const next = importPreview.document;
    onDocument(next);
    onBody(documentToMarkdown(next));
    onTitle(importPreview.title?.trim() || title);
    onReview("unreviewed");
    changeMode("edit");
    setSourceMode(false);
    setImportPreview(null);
    setPdfSource(null);
  };

  const importReport = async (options?: {
    sourceId?: string;
    sheet?: string;
    range?: string;
    ocr?: boolean;
  }) => {
    const api = bridge() as ReportBridge;
    if (!api?.reportImport) {
      setToolError("此版本暂不支持导入文稿。");
      return;
    }
    try {
      setImporting(true);
      setToolError("");
      const result = unwrap(await api.reportImport(taskId, options));
      if (result.cancelled) return;
      const refreshingExistingSource = Boolean(options?.sourceId);
      setImportPreview(result);
      setImportSheet(
        refreshingExistingSource
          ? (options?.sheet ?? importSheet)
          : (result.sheets?.[0] ?? ""),
      );
      setImportRange(
        refreshingExistingSource ? (options?.range ?? importRange) : "",
      );
      if (result.source?.format === "pdf" && api.reportSource) {
        try {
          const source = unwrap(
            await api.reportSource(taskId, result.source.id),
          );
          setPdfSource({
            source: source.source,
            dataUrl: `data:application/pdf;base64,${source.data_base64}`,
          });
        } catch {
          setPdfSource(null);
        }
      } else setPdfSource(null);
    } catch (failure) {
      setToolError(
        errorText(failure),
      );
    } finally {
      setImporting(false);
    }
  };

  const cancelImport = async () => {
    const api = bridge() as ReportBridge;
    try {
      await api?.reportCancel?.(taskId);
    } catch {
      /* cancellation is best-effort */
    }
    setImportPreview(null);
    setPdfSource(null);
    setImporting(false);
  };

  const importSheetRange = () => {
    if (!importPreview?.source) return;
    void importReport({
      sourceId: importPreview.source.id,
      sheet: importSheet || undefined,
      range: importRange || undefined,
    });
  };

  const retryOcr = () => {
    if (!importPreview?.source) return;
    void importReport({ sourceId: importPreview.source.id, ocr: true });
  };

  useEffect(() => {
    setReflowPreview(null);
  }, [body, document, sourceMode]);

  useEffect(() => {
    window.dispatchEvent(
      new CustomEvent("foundry:workspace-native-cover", {
        detail: { open: Boolean(importPreview) },
      }),
    );
    return () => {
      window.dispatchEvent(
        new CustomEvent("foundry:workspace-native-cover", {
          detail: { open: false },
        }),
      );
    };
  }, [importPreview]);

  const insertImage = async (file: File | undefined) => {
    if (!file || !editor) return;
    if (!IMAGE_TYPES.has(file.type) || file.size > MAX_IMAGE_BYTES) {
      setToolError("只支持 2MB 以内的 PNG/JPEG 图片。");
      return;
    }
    const dataUrl = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result ?? ""));
      reader.onerror = () => reject(new Error("图片读取失败。"));
      reader.readAsDataURL(file);
    });
    editor.chain().focus().setImage({ src: dataUrl, alt: file.name }).run();
  };

  return (
    <section className="report-workspace" aria-label="财务文稿工作区">
      {(importing || exporting || reportPhase) && (
        <div className="report-progress" role="status">
          <span>
            <WaitLoop />
            {reportPhase || (importing ? "正在导入转换" : "正在导出转换")}
          </span>
          <Button
            variant="outline"
            type="button"
            onClick={() => void cancelReportJob()}
          >
            取消转换
          </Button>
        </div>
      )}
      <div className="report-shell" data-outline-expanded={outlineOpen ? 'true' : undefined}>
        <div className="report-toolbar" role="group" aria-label="文稿工具栏">
          <div className="report-context">
            <h3>{toolbarLabel}</h3>
            {status && <span className="report-status">{status}</span>}
          </div>
          <div className="report-topbar">
            <div className="report-view-controls">
            <Button
              ref={outlineToggleRef}
              variant="ghost"
              size="sm"
              type="button"
              aria-expanded={outlineOpen}
              aria-controls={outlineId}
              onClick={() => {
                outlineOpenedByToggle.current = !outlineOpen;
                setOutlineOpen((open) => !open);
              }}
            >
              <ListTree size={14} strokeWidth={1.5} aria-hidden />
              目录
            </Button>
            <div className="report-modes" role="tablist" aria-label="文稿模式">
              {(
                [
                  ["read", "阅读"],
                  ["edit", "编辑"],
                  ["print", "打印预览"],
                ] as const
              ).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  role="tab"
                  aria-selected={mode === value}
                  onClick={() => changeMode(value)}
                >
                  {label}
                </button>
              ))}
            </div>
            </div>
            <div className="report-actions">
              <Button
                variant="ghost"
                size="sm"
                type="button"
                disabled={busy || importing}
                onClick={() => void importReport()}
              >
                <Upload size={14} aria-hidden />
                导入
              </Button>
              {mode !== "print" && (
                <Button
                  variant="ghost"
                  size="sm"
                  type="button"
                  disabled={busy || sourceMode || isEmptyDocument}
                  onClick={openReflowPreview}
                >
                  <Sparkles size={14} aria-hidden />
                  整理段落
                </Button>
              )}
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="outline"
                    size="sm"
                    type="button"
                    aria-label="导出"
                    disabled={busy || !title.trim() || !body.trim()}
                  >
                    <Download size={14} aria-hidden />
                    导出·{exportMode === "audit" ? "审计版" : "管理版"}
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" collisionPadding={16}>
                  <DropdownMenuItem
                    onSelect={(event) => {
                      event.preventDefault();
                      setExportMode("management");
                    }}
                  >
                    管理版
                    <DropdownMenuShortcut>{exportMode === "management" ? "已选" : ""}</DropdownMenuShortcut>
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onSelect={(event) => {
                      event.preventDefault();
                      setExportMode("audit");
                    }}
                  >
                    审计版
                    <DropdownMenuShortcut>{exportMode === "audit" ? "已选" : ""}</DropdownMenuShortcut>
                  </DropdownMenuItem>
                  {EXPORT_MENU_FORMATS.map((format) => (
                    <DropdownMenuItem
                      key={format}
                      disabled={busy}
                      onSelect={() => void handleExport(format)}
                    >
                      {exportCommandLabel(format)}
                      <DropdownMenuShortcut>
                        {format.toUpperCase()}
                      </DropdownMenuShortcut>
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
              {archiveAction}
              {assistantAction && <span className="report-assistant-action">{assistantAction}</span>}
            </div>
          </div>
        </div>
        {outlineOpen && (
          <aside
            ref={outlineRef}
            id={outlineId}
            className="report-outline"
            aria-label="文稿目录"
            tabIndex={-1}
            onKeyDown={(event) => {
              if (event.key !== "Escape") return;
              event.stopPropagation();
              closeOutline(true);
            }}
            onClick={(event) => {
              // Following a heading link closes the drawer without pulling the focus back up to 目录.
              if ((event.target as Element).closest("a") && outlineFloating()) closeOutline(false);
            }}
          >
            {headings.length ? (
              <nav className="fnd-scroll-fade">
                {headings.map((item) => (
                  <a
                    key={item.id}
                    href={`#${item.id}`}
                    aria-current={item.id === activeHeading ? "location" : undefined}
                    style={{
                      paddingLeft: `${Math.max(0, item.level - 1) * 12}px`,
                    }}
                  >
                    {item.text}
                  </a>
                ))}
              </nav>
            ) : (
              <p className="analysis-note">添加一、二级标题后生成目录。</p>
            )}
          </aside>
        )}
        {mode === "read" && !outlineOpen && headings.length > 1 && (
          <ReportMinimap headings={headings} active={activeHeading} />
        )}
        <div className="report-main">

          {reflowPreview && (
            <section
              className="report-reflow-preview"
              aria-label="段落整理预览"
            >
              <div className="analysis-section-heading">
                <div>
                  <h3>段落整理预览</h3>
                  <p className="analysis-note">
                    只按完整句、分号和已有换行拆段；文字、数字、引用和顺序保持不变。
                    本次会整理 {reflowPreview.changedParagraphs} 段，新增{" "}
                    {reflowPreview.addedParagraphs} 个段落。
                  </p>
                </div>
                <div className="analysis-actions">
                  <Button
                    variant="outline"
                    type="button"
                    onClick={cancelReflowPreview}
                  >
                    取消整理
                  </Button>
                  <Button type="button" onClick={applyReflowPreview}>
                    采用整理
                  </Button>
                </div>
              </div>
              <ReportReading
                title={title}
                body={documentToMarkdown(reflowPreview.document)}
                document={reflowPreview.document}
                limitations={limitations}
                appendix={undefined}
                preserveStructured
              />
            </section>
          )}

          {mode === "edit" && (
            <fieldset className="report-editor-panel" disabled={busy}>
              <label>
                文稿标题
                <Input
                  aria-label="文稿标题"
                  value={title}
                  onChange={(event) => onTitle(event.target.value)}
                />
              </label>
              <details className="report-info-fields">
                <DisclosureSummary>报告信息</DisclosureSummary>
                <div>
                  <label>
                    账套
                    <Input
                      aria-label="报告账套"
                      value={workingDocument.metadata.ledger ?? ""}
                      onChange={(event) =>
                        updateMetadata("ledger", event.target.value)
                      }
                    />
                  </label>
                  <label>
                    组织
                    <Input
                      aria-label="报告组织"
                      value={workingDocument.metadata.organization ?? ""}
                      onChange={(event) =>
                        updateMetadata("organization", event.target.value)
                      }
                    />
                  </label>
                  <label>
                    公司
                    <Input
                      aria-label="报告公司"
                      value={workingDocument.metadata.company}
                      onChange={(event) =>
                        updateMetadata("company", event.target.value)
                      }
                    />
                  </label>
                  <label>
                    期间
                    <Input
                      aria-label="报告期间"
                      value={workingDocument.metadata.period}
                      onChange={(event) =>
                        updateMetadata("period", event.target.value)
                      }
                    />
                  </label>
                  <label>
                    币种
                    <Input
                      aria-label="报告币种"
                      value={workingDocument.metadata.currency}
                      onChange={(event) =>
                        updateMetadata("currency", event.target.value)
                      }
                    />
                  </label>
                  <label>
                    单位
                    <Input
                      aria-label="报告单位"
                      value={workingDocument.metadata.unit}
                      onChange={(event) =>
                        updateMetadata("unit", event.target.value)
                      }
                    />
                  </label>
                </div>
              </details>
              {isEmptyDocument && (
                <Button
                  variant="outline"
                  type="button"
                  onClick={insertManagementTemplate}
                >
                  插入空白提纲
                </Button>
              )}
              <div className="analysis-actions">
                <Button variant="outline" type="button" onClick={() => void publishCompanyTemplate()}>发布本公司模板</Button>
                <Button variant="outline" type="button" onClick={() => { setTemplateOpen(true); void loadTemplates(); }}>套用公司模板</Button>
              </div>
              {templateOpen ? <div className="analysis-details" aria-label="已发布模板">
                {templates.length ? templates.map((row) => (
                  <Button key={row.template_id} variant="outline" type="button" onClick={() => void applyCompanyTemplate(row.template_id)}>
                    {row.label} · {row.kind}
                  </Button>
                )) : <p className="analysis-note">暂无已发布模板</p>}
                {templateError ? <p role="alert" className="analysis-message analysis-message--error">{templateError}</p> : null}
              </div> : null}
              <div
                className="report-editor-toolbar"
                aria-label="文稿编辑工具栏"
              >
                <IconButton
                  label="撤销"
                  disabled={!editor?.can().undo()}
                  onClick={() => editor?.chain().focus().undo().run()}
                >
                  <Undo2 size={15} />
                </IconButton>
                <IconButton
                  label="重做"
                  disabled={!editor?.can().redo()}
                  onClick={() => editor?.chain().focus().redo().run()}
                >
                  <Redo2 size={15} />
                </IconButton>
                <IconButton
                  label="一级标题"
                  active={editor?.isActive("heading", { level: 1 })}
                  onClick={() =>
                    editor?.chain().focus().toggleHeading({ level: 1 }).run()
                  }
                >
                  <Heading1 size={15} />
                </IconButton>
                <IconButton
                  label="二级标题"
                  active={editor?.isActive("heading", { level: 2 })}
                  onClick={() =>
                    editor?.chain().focus().toggleHeading({ level: 2 }).run()
                  }
                >
                  <Heading2 size={15} />
                </IconButton>
                <IconButton
                  label="加粗"
                  active={editor?.isActive("bold")}
                  onClick={() => editor?.chain().focus().toggleBold().run()}
                >
                  <Bold size={15} />
                </IconButton>
                <IconButton
                  label="斜体"
                  active={editor?.isActive("italic")}
                  onClick={() => editor?.chain().focus().toggleItalic().run()}
                >
                  <Italic size={15} />
                </IconButton>
                <IconButton
                  label="下划线"
                  active={editor?.isActive("underline")}
                  onClick={() =>
                    editor?.chain().focus().toggleMark("underline").run()
                  }
                >
                  <Highlighter size={15} />
                </IconButton>
                <IconButton
                  label="行内代码"
                  active={editor?.isActive("code")}
                  onClick={() => editor?.chain().focus().toggleCode().run()}
                >
                  <Code size={15} />
                </IconButton>
                <IconButton
                  label="无序列表"
                  active={editor?.isActive("bulletList")}
                  onClick={() =>
                    editor?.chain().focus().toggleBulletList().run()
                  }
                >
                  <List size={15} />
                </IconButton>
                <IconButton
                  label="有序列表"
                  active={editor?.isActive("orderedList")}
                  onClick={() =>
                    editor?.chain().focus().toggleOrderedList().run()
                  }
                >
                  <ListOrdered size={15} />
                </IconButton>
                <IconButton
                  label="链接"
                  active={linkOpen}
                  onClick={() => setLinkOpen((value) => !value)}
                >
                  <LinkIcon size={15} />
                </IconButton>
                <IconButton
                  label="插入表格"
                  onClick={() =>
                    editor
                      ?.chain()
                      .focus()
                      .insertTable({ rows: 3, cols: 4, withHeaderRow: true })
                      .run()
                  }
                >
                  <Table2 size={15} />
                </IconButton>
                {editor?.isActive("table") && (
                  <>
                    <IconButton
                      label="改成开票口径"
                      disabled={circleBusy || busy || !draftId || !contextId}
                      onClick={() => void circleSelect()}
                    >
                      <Scissors size={15} />
                    </IconButton>
                    <IconButton
                      label="合并单元格"
                      disabled={!editor?.can().mergeCells()}
                      onClick={() => editor?.chain().focus().mergeCells().run()}
                    >
                      <Columns2 size={15} />
                    </IconButton>
                    <IconButton
                      label="拆分单元格"
                      disabled={!editor?.can().splitCell()}
                      onClick={() => editor?.chain().focus().splitCell().run()}
                    >
                      <SplitSquareHorizontal size={15} />
                    </IconButton>
                    <IconButton
                      label="新增行"
                      disabled={!editor?.can().addRowAfter()}
                      onClick={() =>
                        editor?.chain().focus().addRowAfter().run()
                      }
                    >
                      <Rows3 size={15} />
                    </IconButton>
                    <IconButton
                      label="删除行"
                      disabled={!editor?.can().deleteRow()}
                      onClick={() => editor?.chain().focus().deleteRow().run()}
                    >
                      <Trash2 size={15} />
                    </IconButton>
                    <IconButton
                      label="新增列"
                      disabled={!editor?.can().addColumnAfter()}
                      onClick={() =>
                        editor?.chain().focus().addColumnAfter().run()
                      }
                    >
                      <Columns2 size={15} />
                    </IconButton>
                    <IconButton
                      label="删除列"
                      disabled={!editor?.can().deleteColumn()}
                      onClick={() =>
                        editor?.chain().focus().deleteColumn().run()
                      }
                    >
                      <Trash2 size={15} />
                    </IconButton>
                  </>
                )}
                <IconButton
                  label="分页符"
                  onClick={() =>
                    editor
                      ?.chain()
                      .focus()
                      .insertContent({ type: "reportPageBreak" })
                      .run()
                  }
                >
                  <Scissors size={15} />
                </IconButton>
                <IconButton
                  label="附注"
                  active={noteOpen}
                  onClick={() => setNoteOpen((value) => !value)}
                >
                  <FileText size={15} />
                </IconButton>
                <IconButton
                  label="插入图表"
                  disabled={sourceMode || Boolean(visualEditor)}
                  onClick={() => setVisualEditor({ taskId })}
                >
                  <ChartNoAxesCombined size={15} />
                </IconButton>
                <IconButton
                  label="图片"
                  onClick={() => imageInput.current?.click()}
                >
                  <ImagePlus size={15} />
                </IconButton>
                <input
                  ref={imageInput}
                  type="file"
                  accept="image/png,image/jpeg"
                  hidden
                  onChange={(event) =>
                    void insertImage(event.currentTarget.files?.[0])
                  }
                />
                <Button
                  variant="ghost"
                  type="button"
                  aria-pressed={sourceMode}
                  onClick={sourceMode ? cancelSourceEditor : openSourceEditor}
                >
                  <FileText size={14} aria-hidden />
                  Markdown 源码
                </Button>
              </div>
              {visualEditor?.taskId === taskId && <ReportVisualComposer key={`${taskId}:${visualEditor.position ?? 'new'}`} taskId={taskId} runs={runs} initial={visualEditor.initial} onApply={applyVisual} onCancel={() => setVisualEditor(null)} />}
              {structuredBackup && !sourceMode && <div className="report-source-recovery"><p className="analysis-note">当前显示源码转换后的内容。之前的结构版仍保留在本次编辑中；恢复会替换当前正文。</p><Button type="button" variant="outline" onClick={restoreStructuredDocument}>恢复结构版</Button></div>}
              {linkOpen && (
                <div
                  className="report-inline-popover"
                  role="group"
                  aria-label="链接设置"
                >
                  <Input
                    aria-label="链接地址"
                    placeholder="https://example.com"
                    value={linkHref}
                    onChange={(event) => setLinkHref(event.target.value)}
                  />
                  <Button
                    type="button"
                    disabled={!safeHref(linkHref)}
                    onClick={applyLink}
                  >
                    应用链接
                  </Button>
                  <Button
                    variant="outline"
                    type="button"
                    onClick={() => setLinkOpen(false)}
                  >
                    取消
                  </Button>
                </div>
              )}
              {noteOpen && (
                <div
                  className="report-inline-popover"
                  role="group"
                  aria-label="附注设置"
                >
                  <Input
                    aria-label="附注编号"
                    value={noteId}
                    onChange={(event) => setNoteId(event.target.value)}
                  />
                  <Input
                    aria-label="附注内容"
                    value={noteText}
                    onChange={(event) => setNoteText(event.target.value)}
                    placeholder="输入章节末附注"
                  />
                  <Button type="button" onClick={insertNote}>
                    插入附注引用
                  </Button>
                  <Button
                    variant="outline"
                    type="button"
                    onClick={() => setNoteOpen(false)}
                  >
                    取消
                  </Button>
                </div>
              )}
              {sourceMode ? (
                <div className="report-source-editor">
                  <p role="status" className="analysis-message">
                    源码编辑会生成降级预览；点击“采用源码转换”后才会用 Markdown
                    版本替换当前结构。图表将转换为数据表或流程文字，原结构版可恢复。
                  </p>
                  <Textarea
                    aria-label="文稿正文"
                    rows={18}
                    value={sourceText}
                    onChange={(event) => setSourceText(event.target.value)}
                  />
                  <div
                    className="report-source-preview"
                    aria-label="源码降级预览"
                  >
                    <ReportReading
                      title={title}
                      body={sourceText}
                      document={documentFromMarkdown(sourceText)}
                      limitations=""
                      appendix={undefined}
                      preserveStructured={false}
                    />
                  </div>
                  <div className="analysis-actions">
                    <Button type="button" onClick={applySourceEditor}>
                      采用源码转换
                    </Button>
                    <Button
                      variant="outline"
                      type="button"
                      onClick={cancelSourceEditor}
                    >
                      取消源码编辑
                    </Button>
                  </div>
                </div>
              ) : (
                <>
                  <EditorContent editor={editor} />
                  {!hasVisuals && <label className="report-source-compat">
                    Markdown 源码快速编辑
                    <Textarea
                      aria-label="文稿正文"
                      rows={6}
                      value={body}
                      onChange={(event) => changeSourceBody(event.target.value)}
                    />
                  </label>}
                </>
              )}
              <div className="analysis-edit-grid">
                <label>
                  局限与待确认事项（每行一项）
                  <Textarea
                    aria-label="局限与待确认事项（每行一项）"
                    rows={3}
                    value={limitations}
                    onChange={(event) => onLimitations(event.target.value)}
                  />
                </label>
                <label>
                  我的审阅状态
                  <NativeSelect
                    aria-label="我的审阅状态"
                    value={review}
                    onChange={(event) => onReview(event.target.value)}
                  >
                    <option value="unreviewed">未阅</option>
                    <option value="reviewed">已阅</option>
                    <option value="accepted">认可</option>
                  </NativeSelect>
                </label>
              </div>
            </fieldset>
          )}

          {mode === "read" && (
            <ReportReading
              title={title}
              body={body}
              document={readingDocument}
              limitations={limitations}
              appendix={appendix}
              preserveStructured={Boolean(document)}
              appendixFolded={readingResult.folded}
              main
            />
          )}
          {mode === "print" && (
            <div className="report-print-frame" aria-label="正式预览">
              <iframe
                title="正式预览"
                sandbox=""
                srcDoc={
                  printHtml ||
                  renderReportHtml(workingDocument, title, { print: true })
                }
              />
            </div>
          )}
        </div>
      </div>
      {importPreview && (
        <ImportPreview
          taskId={taskId}
          result={importPreview}
          sheet={importSheet}
          range={importRange}
          pdfSource={pdfSource?.dataUrl}
          importing={importing}
          onSheet={setImportSheet}
          onRange={setImportRange}
          onSheetRange={importSheetRange}
          onRetryOcr={retryOcr}
          onCancel={() => void cancelImport()}
          onApply={applyImport}
        />
      )}
      {circleMessage && <p role="status" className="report-status">{circleMessage}</p>}
      {toolError && (
        <p role="alert" className="analysis-message analysis-message--error">
          {toolError}
        </p>
      )}
    </section>
  );
}

function IconButton({
  label,
  active,
  disabled,
  onClick,
  children,
}: {
  label: string;
  active?: boolean;
  disabled?: boolean;
  onClick(): void;
  children: React.ReactNode;
}) {
  return (
    <button
      className="report-icon-button"
      type="button"
      title={label}
      aria-label={label}
      aria-pressed={active}
      disabled={disabled}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

function reportArticleFragment(html: string): string {
  const match = html.match(
    /<article class=\"report-body\">([\s\S]*?)<\/article>/i,
  );
  return match?.[1] ?? html;
}

function ReportReading({
  title,
  body,
  document,
  limitations,
  appendix,
  preserveStructured = true,
  appendixFolded,
  main,
}: {
  title: string;
  body: string;
  document: ReportDocument;
  limitations: string;
  appendix?: string;
  preserveStructured?: boolean;
  appendixFolded?: boolean;
  /** The draft's one reading view; previews leave it out so a paragraph is located here only. */
  main?: boolean;
}) {
  const appendixResult = useMemo(
    () => exactAppendixResult(document, body, appendix, preserveStructured),
    [body, document, appendix, preserveStructured],
  );
  const html = useMemo(
    () => reportArticleFragment(renderReportHtml(appendixResult.document, title)),
    [appendixResult.document, title],
  );
  // React rewrites innerHTML whenever this object changes, which would drop a located paragraph's mark.
  const mainHtml = useMemo(() => ({ __html: html }), [html]);
  const mainRef = useRef<HTMLDivElement>(null);
  // A table wider than the column scrolls inside its figure; only then is the figure a named, focusable region,
  // so the keyboard can scroll it. The exported HTML leaves figures as they are.
  useEffect(() => {
    const main = mainRef.current;
    if (!main) return;
    const mark = () => {
      for (const figure of main.querySelectorAll<HTMLElement>("figure.financial-table")) {
        if (figure.scrollWidth > figure.clientWidth) {
          figure.tabIndex = 0;
          figure.setAttribute("role", "region");
        } else {
          figure.removeAttribute("tabindex");
          figure.removeAttribute("role");
        }
      }
    };
    mark();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(mark);
    observer.observe(main);
    return () => observer.disconnect();
  }, [mainHtml]);
  const appendixHtml = useMemo(
    () =>
      appendix
        ? reportArticleFragment(
            renderReportHtml(
              documentFromMarkdown(appendix),
              "系统生成计算依据附录",
            ),
          )
        : "",
    [appendix],
  );
  return (
    <article className="report-reading" aria-label="文稿阅读" data-reading-main={main ? "" : undefined}>
      <h2>{title}</h2>
      <div
        ref={mainRef}
        className="analysis-draft-main"
        dangerouslySetInnerHTML={mainHtml}
      />
      {appendix && (appendixFolded ?? appendixResult.folded) && (
        <details className="analysis-details analysis-appendix-fold">
          <DisclosureSummary>系统生成计算依据附录</DisclosureSummary>
          <div dangerouslySetInnerHTML={{ __html: appendixHtml }} />
          <pre className="analysis-source-text">{appendix}</pre>
        </details>
      )}
      {limitations.trim() && (
        <section>
          <h2>局限与待确认事项</h2>
          <ul>
            {limitations
              .split("\n")
              .filter(Boolean)
              .map((line, index) => (
                <li key={index}>{line}</li>
              ))}
          </ul>
        </section>
      )}
    </article>
  );
}

function ImportPreview({
  taskId,
  result,
  sheet,
  range,
  pdfSource,
  importing,
  onSheet,
  onRange,
  onSheetRange,
  onRetryOcr,
  onCancel,
  onApply,
}: {
  taskId: string;
  result: ReportImportResult;
  sheet: string;
  range: string;
  pdfSource: string | undefined;
  importing: boolean;
  onSheet(value: string): void;
  onRange(value: string): void;
  onSheetRange(): void;
  onRetryOcr(): void;
  onCancel(): void;
  onApply(): void;
}) {
  const title = result.title?.trim() || result.source?.name || "导入预览";
  return (
    <section className="report-import-preview" aria-label="导入预览">
      <div className="report-import-preview__panel">
        <div className="analysis-section-heading">
          <div>
            <h3>{title}</h3>
            <p className="analysis-note">
              {formatWarnings(result.warnings)}
              {result.needsReview ? " · 需要人工核对" : ""}
            </p>
          </div>
          <div className="analysis-actions">
            <Button
              variant="outline"
              type="button"
              disabled={importing}
              onClick={onCancel}
            >
              取消
            </Button>
            <Button
              type="button"
              disabled={!result.document || importing}
              onClick={onApply}
            >
              采用此版本
            </Button>
          </div>
        </div>
        {result.sheets?.length ? (
          <div className="report-import-sheet">
            <label>
              工作表
              <NativeSelect
                aria-label="导入工作表"
                value={sheet}
                onChange={(event) => onSheet(event.target.value)}
              >
                {result.sheets.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </NativeSelect>
            </label>
            <label>
              区域
              <Input
                aria-label="导入区域"
                placeholder="例如 A1:H40"
                value={range}
                onChange={(event) => onRange(event.target.value)}
              />
            </label>
            <Button
              variant="outline"
              type="button"
              disabled={importing}
              onClick={onSheetRange}
            >
              <FileSpreadsheet size={14} aria-hidden />
              重新读取区域
            </Button>
          </div>
        ) : null}
        {result.document ? (
          <ReportReviewAction
            taskId={taskId}
            spec={{ document: result.document }}
            label="复核数字"
            intro="采用前可以先把文稿里的数字和当前任务的套表、资料表、计算结果逐项比对；复核不改动这份文稿。"
            disabled={importing}
            pdf={
              pdfSource && result.source
                ? {
                    load: async (id) => (id === result.source?.id ? pdfSource : undefined),
                    render: (dataUrl, page) => <PdfComparison dataUrl={dataUrl} page={page} />,
                  }
                : undefined
            }
          />
        ) : null}
        {pdfSource ? <PdfComparison dataUrl={pdfSource} /> : null}
        {result.source?.format === "pdf" && result.needsReview ? (
          <Button
            variant="outline"
            type="button"
            disabled={importing}
            onClick={onRetryOcr}
          >
            重试 OCR
          </Button>
        ) : null}
        {result.document ? (
          <ReportReading
            title={title}
            body={documentToMarkdown(result.document)}
            document={result.document}
            limitations=""
            appendix={undefined}
            preserveStructured
          />
        ) : (
          <p className="analysis-note">没有可采用的结构化内容。</p>
        )}
      </div>
    </section>
  );
}

function pdfDataFromDataUrl(dataUrl: string): Uint8Array {
  const prefix = "data:application/pdf;base64,";
  if (!dataUrl.startsWith(prefix)) throw new Error("PDF_SOURCE_INVALID");
  try {
    const binary = atob(dataUrl.slice(prefix.length));
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1)
      bytes[index] = binary.charCodeAt(index);
    return bytes;
  } catch {
    throw new Error("PDF_SOURCE_INVALID");
  }
}

function pdfPreviewErrorMessage(failure: unknown): string {
  if (
    failure instanceof Error &&
    failure.name === "RenderingCancelledException"
  )
    return "";
  return "PDF 原页暂时无法预览，可继续使用已提取的草稿内容。";
}

/**
 * The archived PDF beside the draft, one page at a time.
 *
 * `page` is where to open: a locator names the page it cited, and a viewer
 * that always opened on page 1 was showing the operator the cover of a
 * document they asked about page 7 of. Clamped to the document once it is
 * loaded; absent, page 1.
 */
export function PdfComparison({ dataUrl, page: initialPage }: { dataUrl: string; page?: number }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const pdfRef = useRef<{
    numPages: number;
    getPage(page: number): Promise<any>;
    destroy?(): Promise<void> | void;
  } | null>(null);
  const renderTaskRef = useRef<{
    cancel(): void;
    promise: Promise<unknown>;
  } | null>(null);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    let loadingTask: {
      promise: Promise<any>;
      destroy?(): Promise<void> | void;
    } | null = null;
    const load = async () => {
      try {
        setError("");
        const pdfjs = await import("pdfjs-dist");
        pdfjs.GlobalWorkerOptions.workerSrc = new URL(
          "pdfjs-dist/build/pdf.worker.mjs",
          import.meta.url,
        ).toString();
        loadingTask = pdfjs.getDocument({
          data: pdfDataFromDataUrl(dataUrl),
          isEvalSupported: false,
        } as Parameters<typeof pdfjs.getDocument>[0] & {
          isEvalSupported: boolean;
        });
        const pdf = await loadingTask.promise;
        if (cancelled) {
          await pdf.destroy?.();
          return;
        }
        pdfRef.current = pdf;
        setPages(pdf.numPages);
        setPage(Math.min(Math.max(1, initialPage ?? 1), pdf.numPages || 1));
      } catch (failure) {
        const message = pdfPreviewErrorMessage(failure);
        if (!cancelled && message) setError(message);
      }
    };
    void load();
    return () => {
      cancelled = true;
      renderTaskRef.current?.cancel();
      void loadingTask?.destroy?.();
      void pdfRef.current?.destroy?.();
      pdfRef.current = null;
    };
  }, [dataUrl, initialPage]);

  useEffect(() => {
    let cancelled = false;
    const render = async () => {
      try {
        setError("");
        const pdf = pdfRef.current;
        if (!pdf) return;
        renderTaskRef.current?.cancel();
        const pdfPage = await pdf.getPage(page);
        if (cancelled) return;
        const viewport = pdfPage.getViewport({ scale: 0.8 });
        const canvas = canvasRef.current;
        const context = canvas?.getContext("2d");
        if (!canvas || !context) return;
        canvas.width = Math.floor(viewport.width);
        canvas.height = Math.floor(viewport.height);
        const task = pdfPage.render({
          canvas,
          canvasContext: context,
          viewport,
        });
        renderTaskRef.current = task;
        await task.promise;
      } catch (failure) {
        const message = pdfPreviewErrorMessage(failure);
        if (!cancelled && message) setError(message);
      }
    };
    void render();
    return () => {
      cancelled = true;
      renderTaskRef.current?.cancel();
    };
  }, [page, pages]);

  return (
    <div className="report-pdf-compare">
      <div className="analysis-section-heading">
        <h4>PDF 原页对照</h4>
        <div className="analysis-actions">
          <Button
            variant="outline"
            type="button"
            disabled={page <= 1}
            onClick={() => setPage((value) => Math.max(1, value - 1))}
          >
            上一页
          </Button>
          <span className="analysis-note">
            {page}/{pages}
          </span>
          <Button
            variant="outline"
            type="button"
            disabled={page >= pages}
            onClick={() => setPage((value) => Math.min(pages, value + 1))}
          >
            下一页
          </Button>
        </div>
      </div>
      <canvas ref={canvasRef} aria-label="PDF 原页画布" />
      {error && (
        <p role="alert" className="analysis-message analysis-message--error">
          {error}
        </p>
      )}
    </div>
  );
}
