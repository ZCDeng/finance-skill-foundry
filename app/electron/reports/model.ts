/** Versioned interchange shared by converters, renderer and the Foundry validator. */
/** Formats a draft can be exported to; PPTX decks are read, never written. */
export type ReportExportFormat = 'docx' | 'pdf' | 'html' | 'md' | 'xlsx';
export type ReportFormat = ReportExportFormat | 'pptx';
export interface ReportSource { id: string; name: string; sha256: string; format: ReportFormat }
export interface ReportMark { type: string; attrs?: Record<string, unknown> }
export interface ReportNode {
  type: string;
  text?: string;
  attrs?: Record<string, unknown>;
  marks?: ReportMark[];
  content?: ReportNode[];
}
export interface ReportDocument {
  schema_version: 1;
  template_version: 'annual-v1';
  template_id?: string;
  metadata: { ledger?: string; organization?: string; company: string; period: string; currency: string; unit: string };
  content: ReportNode[];
  sources?: ReportSource[];
}
export interface ReportImportOptions { sourceId?: string; sheet?: string; range?: string; ocr?: boolean }
export interface ReportImportResult {
  cancelled?: boolean;
  document?: ReportDocument;
  title?: string;
  warnings: string[];
  source?: ReportSource;
  sheets?: string[];
  needsReview?: boolean;
}
export type ReportProjectionMode = 'management' | 'audit';
export interface ReportProjection {
  schema_version: 1;
  draft_id: string;
  task_id?: string;
  title: string;
  content_hash: string;
  projection_hash: string;
  content_mode: ReportProjectionMode;
  publication_status: string;
  review_status: string;
  reproducibility_status: string;
  marker: string;
  body: string;
  document: ReportDocument;
  limitations?: string[];
  sources?: string[];
  /** Room beyond the limits for the estimate declaration and labels the server added (absent without estimates). */
  estimate_headroom?: { text: number; nodes: number; bytes?: number };
}
