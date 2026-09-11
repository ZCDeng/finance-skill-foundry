/** Versioned interchange shared by converters, renderer and the Foundry validator. */
export type ReportFormat = 'docx' | 'pdf' | 'html' | 'md' | 'xlsx';
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
