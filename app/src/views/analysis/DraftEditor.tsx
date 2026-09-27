import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { MessageSquare } from 'lucide-react';
import { bridge, type Answer, type AnalysisDraft, type AnalysisRun, type DatasetSnapshot, type FinanceDrilldown } from '../../bridge.js';
import { RunStatus, draftStateText, textValue } from './presentation.js';
import { ClaimBindingRepair } from './ClaimBindingRepair.js';
import { RevisionDiff } from './RevisionDiff.js';
import { ReportEditor, type ReportDraftDocument } from './ReportEditor.js';
import { documentFromMarkdown, documentToMarkdown } from '../../../electron/reports/format.js';
import { RequirementsPanel } from './RequirementsPanel.js';
import { Button } from '../../components/ui/button.js';
import { CompletionRecoveriesPanel, type FinanceCompletionRecovery } from './CompletionRecoveriesPanel.js';
import { ExplanationQualityPanel, type ExplanationFact, type ExplanationQuality } from './ExplanationQualityPanel.js';
import { FinanceBackgroundPanel, type FinanceBackground } from './FinanceBackgroundPanel.js';
import { MaterialityFields, materialityScopeSummary, materialityToEdit, materialityToSpec, sameMateriality, type MaterialityEdit } from './MaterialityFields.js';
import { unwrap, errorText } from './shared.js';

export type DraftEdit = { title: string; body: string; limitations: string; review: string; document?: ReportDraftDocument; materiality?: MaterialityEdit; recovery?: FinanceCompletionRecovery | null };
type ReportMode = 'read' | 'edit' | 'print';

interface ExplanationPreparation { facts?: ExplanationFact[]; required_fact_ids?: string[]; diagnostics?: unknown[]; business_contexts?: FinanceBackground[] }

function appendixMarkdownVariants(appendix?: string): string[] {
  const cleanAppendix = appendix?.trim();
  if (!cleanAppendix) return [];
  const canonicalAppendix = documentToMarkdown(documentFromMarkdown(cleanAppendix)).trim();
  return Array.from(new Set([cleanAppendix, canonicalAppendix]));
}
function readableDraftParts(body: string, appendix?: string): { body: string; appendix?: string } {
  const variants = appendixMarkdownVariants(appendix);
  if (!variants.length) return { body };
  const trimmedBody = body.trimEnd();
  const matchedAppendix = variants.find((candidate) => trimmedBody.endsWith(candidate));
  if (!matchedAppendix) return { body };
  return { body: trimmedBody.slice(0, trimmedBody.length - matchedAppendix.length).trimEnd(), appendix: variants[0] };
}

export function DraftEditor({ taskId, draft, drafts, busy, runs, datasets, edit, onEdit, onSave, onExport, onChat, onDiscussRequirements, versionPicker, onLocatorPreview, onAppliedDraft }: {
  taskId: string; draft?: AnalysisDraft; drafts: AnalysisDraft[]; busy: boolean; runs: AnalysisRun[]; datasets: DatasetSnapshot[]; onSave(spec: Record<string, unknown>): void;
  edit?: DraftEdit; onEdit(edit: DraftEdit): void;
  onExport(format: 'docx' | 'pdf' | 'html' | 'md' | 'xlsx', spec?: Record<string, unknown>, mode?: 'management' | 'audit'): void | Promise<void>; onChat(spec?: Record<string, unknown>): void;
  onDiscussRequirements(request: Record<string, unknown>): void;
  versionPicker?: ReactNode;
  onLocatorPreview?(preview: import('../../bridge.js').LocatorPreviewSpec): void;
  onAppliedDraft?(draft: AnalysisDraft): void;
}) {
  const initialEditUnsaved = Boolean(draft && edit && draftEditDiffers(draft, edit));
  const [title, setTitle] = useState(edit?.title ?? draft?.title ?? '经营分析');
  const [body, setBody] = useState(edit?.body ?? draft?.body ?? '');
  const [document, setDocument] = useState<ReportDraftDocument | undefined>(() => edit?.document ?? richDraftDocument(draft));
  const [limitations, setLimitations] = useState(edit?.limitations ?? draft?.limitations.join('\n') ?? '');
  const [review, setReview] = useState(edit?.review ?? draft?.review_status ?? 'unreviewed');
  const [materiality, setMateriality] = useState<MaterialityEdit>(() => edit?.materiality ?? materialityToEdit(draft?.materiality));
  const [recovery, setRecovery] = useState<FinanceCompletionRecovery | null>(edit?.recovery ?? null);
  const [reportMode, setReportMode] = useState<ReportMode>(() => (!draft || Boolean(edit && (edit.body !== draft.body || edit.title !== draft.title
    || edit.limitations !== draft.limitations.join('\n') || edit.review !== draft.review_status || !sameDocument(edit.document, richDraftDocument(draft)) || !sameMateriality(edit.materiality, draft.materiality) || edit.recovery))) ? 'edit' : 'read');
  const [quality, setQuality] = useState<ExplanationQuality | null>(initialEditUnsaved ? null : (draft?.quality as ExplanationQuality | undefined) ?? null);
  const [qualityState, setQualityState] = useState<'idle' | 'checking' | 'passed' | 'issues' | 'stale' | 'unavailable'>(initialEditUnsaved ? 'stale' : 'idle');
  const [updatedRequirementsId, setUpdatedRequirementsId] = useState<string | null>(null);
  const [recoveries, setRecoveries] = useState<FinanceCompletionRecovery[]>([]);
  const [recoveryError, setRecoveryError] = useState('');
  const [facts, setFacts] = useState<ExplanationFact[]>([]);
  const [factDetails, setFactDetails] = useState<Record<string, FinanceDrilldown>>({});
  const [locatorNotice, setLocatorNotice] = useState<Record<string, string>>({});
  const [locatorPdf, setLocatorPdf] = useState<{ factId: string; dataUrl: string; page?: number } | null>(null);
  const [backgrounds, setBackgrounds] = useState<FinanceBackground[]>([]);
  const [background, setBackground] = useState({ label: '', text: '', basis: 'professional_judgment', effective_from: '', effective_to: '', dataset_id: '', paragraph: '', source: '', retrieved_at: '' });
  const [backgroundScope, setBackgroundScope] = useState<Record<string, string>>({ ledger: '', organization: '', period: '', currency: '', unit: '' });
  const [scopeJson, setScopeJson] = useState('');
  const [backgroundMessage, setBackgroundMessage] = useState('');
  const [toolError, setToolError] = useState('');
  const [requirementsOpen, setRequirementsOpen] = useState(!draft);
  const qualityRequest = useRef(0);
  const factRequest = useRef(0);
  const backgroundRequest = useRef(0);
  const recoveryRequest = useRef(0);
  const draftRuns = runs.filter((run) => draft?.run_ids.includes(run.id));
  const parentDraft = drafts.find((candidate) => candidate.id === draft?.parent_id);
  const previousRun = runs.find((run) => parentDraft?.run_ids.includes(run.id));
  const comparison = draft?.revision_comparison;
  const affectedClaims = (comparison?.issues ?? []).filter((issue) => issue.code === 'revision_numeric_regression').map((issue) => ({
    label: `${issue.column ?? '指标'} · 原值 ${issue.old_value ?? ''} → 新值 ${issue.new_value ?? ''}`,
    message: `${(draft?.claims ?? []).filter((claim) => Boolean(claim && typeof claim === 'object'
      && (claim as Record<string, unknown>).column === issue.column
      && [(issue as { old_run_id?: string }).old_run_id, (issue as { new_run_id?: string }).new_run_id].includes(String((claim as Record<string, unknown>).run_id)))).length} 条计算引用需要按当前版本核对。`,
  }));
  const financeRuns = draftRuns.filter((run) => (run.engine === 'finance' || run.engine === 'structured_aggregate'));
  const primaryFinanceRun = financeRuns[0];
  const defaultScope = firstFinanceScope(primaryFinanceRun);
  const contextId = primaryFinanceRun?.finance_context_id;
  const effectiveRunIds = recovery?.run_ids ?? draft?.run_ids ?? [];
  const effectiveClaims = recovery ? (recovery.claims ?? []) : (draft?.claims ?? []);
  const citedFactIds = explicitFactIds(recovery ? undefined : draft, body, recovery?.fact_ids);
  const boundDatasetIds = Array.from(new Set(draftRuns.flatMap((run) => Object.values(run.bindings ?? {}))));
  const sourceDatasets = datasets.filter((source) => boundDatasetIds.includes(source.id));
  const materialitySpec = materialityToSpec(materiality);
  const materialityChanged = !sameMateriality(materiality, draft?.materiality);
  const materialityError = materiality.relative.trim().startsWith('-') ? '相对阈值不能为负数。0.1 表示 10%。' : '';
  const hasUnsavedQualityInputs = Boolean(draft && ((edit?.body != null && edit.body !== draft.body) || materialityChanged
    || (updatedRequirementsId && updatedRequirementsId !== draft.requirements_id) || recovery));
  const reading = readableDraftParts(body, draft?.evidence_appendix);
  useEffect(() => { onEdit({ title, body, limitations, review, document, materiality, recovery }); }, [title, body, limitations, review, document, materiality, recovery, onEdit]);
  useEffect(() => {
    setTitle(edit?.title ?? draft?.title ?? '经营分析');
    setBody(edit?.body ?? draft?.body ?? '');
    setDocument(edit?.document ?? richDraftDocument(draft));
    setLimitations(edit?.limitations ?? draft?.limitations.join('\n') ?? '');
    setReview(edit?.review ?? draft?.review_status ?? 'unreviewed');
    setMateriality(edit?.materiality ?? materialityToEdit(draft?.materiality));
    setRecovery(edit?.recovery ?? null);
    const restoredUnsaved = Boolean(draft && edit && draftEditDiffers(draft, edit));
    setQuality(restoredUnsaved ? null : (draft?.quality as ExplanationQuality | undefined) ?? null);
    setQualityState(restoredUnsaved ? 'stale' : 'idle');
    setUpdatedRequirementsId(null);
    setRequirementsOpen(!draft);
    setReportMode(!draft || restoredUnsaved ? 'edit' : 'read');
    setFacts([]); setFactDetails({}); setBackgrounds([]); setToolError(''); setBackgroundMessage('');
    setBackgroundScope(scopeToFields(defaultScope)); setScopeJson(JSON.stringify(defaultScope, null, 2));
    qualityRequest.current += 1; factRequest.current += 1; backgroundRequest.current += 1;
  }, [draft?.id]);
  const loadRecoveries = useCallback(async () => {
    const api = bridge(); if (!api?.financeCall) return;
    const request = ++recoveryRequest.current;
    setRecoveryError('');
    try {
      const answer = await api.financeCall(taskId, 'finance-completion-recoveries');
      if (request !== recoveryRequest.current) return;
      const result = unwrap(answer as Answer<{ recoveries?: FinanceCompletionRecovery[] }>);
      setRecoveries((result.recoveries ?? []).filter(isVisibleRecovery));
    } catch (failure) {
      if (request === recoveryRequest.current) {
        setRecoveries([]);
        setRecoveryError(errorText(failure));
      }
    }
  }, [taskId]);
  useEffect(() => {
    void loadRecoveries();
    return () => { recoveryRequest.current += 1; };
  }, [loadRecoveries]);
  useEffect(() => {
    if (Object.values(backgroundScope).some(Boolean)) return;
    const next = scopeToFields(defaultScope);
    if (Object.values(next).some(Boolean)) { setBackgroundScope(next); setScopeJson(JSON.stringify(defaultScope, null, 2)); }
  }, [primaryFinanceRun?.id]);
  useEffect(() => {
    if (!draft || !draft.run_ids.length) return;
    const api = bridge();
    if (!api?.financeCall) { setQuality(null); setQualityState('unavailable'); return; }
    const request = ++qualityRequest.current;
    const bgRequest = ++backgroundRequest.current;
    if (hasUnsavedQualityInputs) {
      setQuality(null); setQualityState('stale'); setToolError('');
      void loadBackgrounds(bgRequest, defaultScope);
      return () => { qualityRequest.current += 1; factRequest.current += 1; backgroundRequest.current += 1; };
    }
    setQuality(null); setQualityState('checking'); setToolError('');
    void Promise.allSettled([
      api.financeCall(taskId, 'prepare-explanation', { run_ids: draft.run_ids, materiality: materialitySpec }),
      api.financeCall(taskId, 'validate-explanation', edit?.body != null && edit.body !== draft.body || materialityChanged || updatedRequirementsId
        ? { draft_id: draft.id, body, run_ids: draft.run_ids, fact_ids: citedFactIds, claims: draft.claims,
          ...(updatedRequirementsId ? { requirements_id: updatedRequirementsId } : {}), materiality: materialitySpec }
        : { draft_id: draft.id, materiality: materialitySpec }),
    ]).then(([prepared, checked]) => {
      if (request !== qualityRequest.current) return;
      if (prepared.status === 'fulfilled') {
        const value = unwrap(prepared.value as Answer<ExplanationPreparation>);
        setFacts(value.facts ?? []);
        if (value.business_contexts?.length) setBackgrounds(value.business_contexts);
      }
      if (checked.status === 'fulfilled') {
        const value = unwrap(checked.value as Answer<ExplanationQuality>);
        setQuality(value);
        setQualityState(qualityStateFromResult(value));
      } else setQualityState('unavailable');
    }).catch((failure) => { if (request === qualityRequest.current) { setQualityState('unavailable'); setToolError(errorText(failure)); } });
    void loadBackgrounds(bgRequest, defaultScope);
    return () => { qualityRequest.current += 1; factRequest.current += 1; backgroundRequest.current += 1; };
  }, [draft?.id, taskId]);
  const changed = !draft || title !== draft.title || body !== draft.body || !sameDocument(document, richDraftDocument(draft)) || limitations !== draft.limitations.join('\n') || review !== draft.review_status
    || Boolean(updatedRequirementsId && updatedRequirementsId !== draft.requirements_id) || materialityChanged || Boolean(recovery);
  const canLoadRecovery = !hasMeaningfulUnsavedDraft(draft, { title, body, limitations, review, materiality, recovery }, materialityChanged);
  function spec(publication: 'draft' | 'archived') {
    const parentId = recovery ? recovery.parent_id : draft?.id;
    return { title: title.trim(), body, ...(document ? { document } : richDraftDocument(draft) ? { document: null } : {}), run_ids: effectiveRunIds, claims: effectiveClaims, ...(citedFactIds.length ? { fact_ids: citedFactIds } : {}),
      ...(recovery ? { recovery_ref: { operation_id: recovery.operation_id, revision: recovery.revision },
        evidence_recipes: recovery.evidence_recipes ?? [], consistency_rules: recovery.consistency_rules ?? [], consistency_sources: recovery.consistency_sources ?? [] } : {}),
      ...(parentId ? { parent_id: parentId } : {}),
      ...((updatedRequirementsId ?? recovery?.requirements_id) ? { requirements_id: updatedRequirementsId ?? recovery?.requirements_id } : {}),
      materiality: materialitySpec, publication_status: publication, review_status: review,
      limitations: limitations.split('\n').map((line) => line.trim()).filter(Boolean) };
  }
  async function recheck() {
    if (!draft && !recovery) return;
    const api = bridge(); if (!api?.financeCall) { setQuality(null); setQualityState('unavailable'); return; }
    const request = ++qualityRequest.current;
    try {
      setQuality(null); setQualityState('checking'); setToolError('');
      const prepared = unwrap(await api.financeCall(taskId, 'prepare-explanation', { run_ids: effectiveRunIds, materiality: materialitySpec }) as Answer<ExplanationPreparation>);
      if (request !== qualityRequest.current) return;
      setFacts(prepared.facts ?? []);
      const checked = unwrap(await api.financeCall(taskId, 'validate-explanation', { ...(recovery ? {} : { draft_id: draft!.id }), body, review_status: review, run_ids: effectiveRunIds, fact_ids: explicitFactIds(recovery ? undefined : draft, body, recovery?.fact_ids), claims: effectiveClaims,
        ...(recovery ? { evidence_recipes: recovery.evidence_recipes ?? [], consistency_rules: recovery.consistency_rules ?? [], consistency_sources: recovery.consistency_sources ?? [] } : {}),
        ...((updatedRequirementsId ?? recovery?.requirements_id) ? { requirements_id: updatedRequirementsId ?? recovery?.requirements_id } : {}), materiality: materialitySpec }) as Answer<ExplanationQuality>);
      if (request !== qualityRequest.current) return;
      setQuality(checked); setQualityState(qualityStateFromResult(checked));
    } catch (failure) {
      if (request === qualityRequest.current) { setQuality(null); setQualityState('unavailable'); setToolError(errorText(failure)); }
    }
  }
  async function openFact(fact: ExplanationFact) {
    const api = bridge(); if (!api?.financeCall || fact.row == null) return;
    const request = ++factRequest.current;
    try {
      setToolError('');
      const result = unwrap(await api.financeCall(taskId, 'drilldown-fact', { run_id: fact.run_id, row: fact.row, ...(fact.column ? { column: fact.column } : {}), offset: 0, limit: 100 }) as Answer<FinanceDrilldown>);
      if (request === factRequest.current) setFactDetails((value) => ({ ...value, [fact.id]: result }));
    } catch (failure) { if (request === factRequest.current) setToolError(errorText(failure)); }
  }
  async function openLocator(fact: ExplanationFact) {
    const api = bridge();
    const request = ++factRequest.current;
    try {
      setToolError('');
      setLocatorNotice((value) => ({ ...value, [fact.id]: '' }));
      setLocatorPdf(null);
      if (!api?.sourceLocatorOpen) {
        await openFact(fact);
        return;
      }
      const located = unwrap(await api.sourceLocatorOpen(taskId, { fact_id: fact.id }));
      if (request !== factRequest.current) return;
      if (located.status === 'locator_forbidden') {
        setLocatorNotice((value) => ({ ...value, [fact.id]: '无权打开' }));
        return;
      }
      if (located.status === 'locator_unavailable') {
        await openFact(fact);
        return;
      }
      if (located.preview?.available === false) {
        setLocatorNotice((value) => ({ ...value, [fact.id]: '该页未归档' }));
        await openFact(fact);
        return;
      }
      if (located.viewer === 'univer' && located.sha256 && located.task) {
        onLocatorPreview?.({ task: located.task, sha256: located.sha256, excel_range: typeof located.locator?.excel_range === 'string' ? located.locator.excel_range : undefined });
        return;
      }
      if (located.viewer === 'pdf') {
        // A locator names a dataset, not a report source. The archived page
        // is the report source whose bytes hash to the locator's source; a
        // draft that imported no such file has no page to show.
        const sourceHash = typeof located.locator?.source_hash === 'string' ? located.locator.source_hash : '';
        const archived = sourceHash ? document?.sources?.find((item) => item.sha256 === sourceHash) : undefined;
        if (!api.reportSource || !archived) {
          setLocatorNotice((value) => ({ ...value, [fact.id]: '该页未归档' }));
          await openFact(fact);
          return;
        }
        const payload = unwrap(await api.reportSource(taskId, archived.id) as Answer<{ data_base64?: string }>);
        if (!payload.data_base64) {
          setLocatorNotice((value) => ({ ...value, [fact.id]: '该页未归档' }));
          await openFact(fact);
          return;
        }
        const page = typeof located.locator?.page === 'number' && Number.isInteger(located.locator.page) && located.locator.page > 0 ? located.locator.page : undefined;
        setLocatorPdf({ factId: fact.id, dataUrl: `data:application/pdf;base64,${payload.data_base64}`, ...(page ? { page } : {}) });
        return;
      }
      await openFact(fact);
    } catch (failure) { if (request === factRequest.current) setToolError(locatorFailureText(failure)); }
  }
  async function loadBackgrounds(request = ++backgroundRequest.current, scopeOverride?: Record<string, unknown>) {
    const api = bridge(); if (!api?.financeCall) return;
    try {
      const scope = scopeOverride ?? currentBackgroundScope(backgroundScope, scopeJson);
      const result = unwrap(await api.financeCall(taskId, 'finance-background-list', { ...(contextId ? { context_id: contextId } : {}), scope, as_of: scope.period }) as Answer<{ backgrounds?: FinanceBackground[]; business_contexts?: FinanceBackground[]; items?: FinanceBackground[] }>);
      if (request === backgroundRequest.current) setBackgrounds(result.backgrounds ?? result.business_contexts ?? result.items ?? []);
    } catch { /* background list is optional for old backends */ }
  }
  async function saveBackground() {
    const api = bridge(); if (!api?.financeCall) { setToolError('此版本暂不支持财务背景。'); return; }
    const request = ++backgroundRequest.current;
    try {
      setToolError(''); setBackgroundMessage('');
      const scope = currentBackgroundScope(backgroundScope, scopeJson);
      const paragraph = background.paragraph.trim() ? Number(background.paragraph) : undefined;
      if (background.basis === 'source_fact' && (!background.dataset_id || !paragraph)) throw new Error('资料事实需要选择授权资料并填写段落编号。');
      if (background.basis === 'external_reference' && (!background.source.trim() || !background.retrieved_at.trim())) throw new Error('外部依据需要填写来源和查询日期。');
      const saved = unwrap(await api.financeCall(taskId, 'finance-background-save', {
        ...(contextId ? { context_id: contextId } : {}), label: background.label.trim() || undefined, text: background.text.trim(), basis: background.basis,
        scope, effective_from: background.effective_from || scope.period, effective_to: background.effective_to || undefined,
        ...(background.basis === 'source_fact' && background.dataset_id ? { dataset_id: background.dataset_id } : {}),
        ...(background.basis === 'source_fact' && paragraph ? { paragraph } : {}),
        ...(background.basis === 'external_reference' ? { external_reference: externalReferencePayload(background.source.trim(), background.retrieved_at.trim()) } : {}),
      }) as Answer<FinanceBackground>);
      if (request !== backgroundRequest.current) return;
      setBackgroundMessage('已保存财务背景。'); setBackground({ ...background, label: '', text: '', paragraph: '', source: '', retrieved_at: '' });
      setBackgrounds((value) => [saved, ...value.filter((item) => item.id !== saved.id)]);
    } catch (failure) { if (request === backgroundRequest.current) setToolError(errorText(failure)); }
  }
  function markQualityStale() {
    qualityRequest.current += 1;
    setQuality(null); setQualityState('stale');
  }
  function onBodyChange(value: string) {
    markQualityStale();
    setBody(value); setReview('unreviewed');
  }
  function onDocumentChange(value: ReportDraftDocument | undefined) {
    markQualityStale();
    setDocument(value);
  }
  function onMaterialityChange(next: MaterialityEdit) {
    setMateriality(next);
    markQualityStale();
  }
  function loadRecovery(next: FinanceCompletionRecovery) {
    if (!canLoadRecovery) return;
    setRecovery(next);
    setTitle(next.title?.trim() || title);
    setBody(next.body ?? '');
    setDocument(richRecoveryDocument(next));
    setLimitations(Array.isArray(next.limitations) ? next.limitations.join('\n') : textValue(next.limitations ?? ''));
    if (next.materiality) setMateriality(materialityToEdit(next.materiality));
    setReview('unreviewed');
    setReportMode('edit');
    markQualityStale();
  }
  return <div className="analysis-draft">
    <CompletionRecoveriesPanel recoveries={recoveries} error={recoveryError} disabled={busy || !canLoadRecovery} onRetry={() => void loadRecoveries()} onLoad={loadRecovery} />
    {recoveries.length > 0 && !canLoadRecovery && <p className="analysis-note">当前有未保存输入；保存或放弃当前修改后再载入恢复稿，避免覆盖你的编辑。</p>}
    {recovery && <p role="status" className="analysis-message">已载入未保存恢复稿，尚未检查；保存后才会成为新的文稿版本。</p>}
    {recovery && <ClaimBindingRepair claims={effectiveClaims} runs={runs.filter((run) => effectiveRunIds.includes(run.id))} disabled={busy}
      onChange={(claims) => { setRecovery({ ...recovery, claims }); markQualityStale(); setReview('unreviewed'); }} />}
    <div className="analysis-draft-navigation" data-expanded={bridge()?.financeCall && requirementsOpen ? 'true' : undefined}>
    {versionPicker && <div className="analysis-version-picker">{versionPicker}</div>}
    {bridge()?.financeCall && <details className="analysis-details analysis-requirements" open={requirementsOpen}
      onToggle={(event) => setRequirementsOpen((event.currentTarget as HTMLDetailsElement).open)}>
      <summary>本次分析要求</summary>
      <RequirementsPanel taskId={taskId} contextId={contextId} draftRequirementsId={draft?.requirements_id ?? undefined}
        onChanged={(requirements) => { qualityRequest.current += 1; setUpdatedRequirementsId(requirements.id); setQuality(null); setQualityState('stale'); }}
        onDiscuss={onDiscussRequirements} />
    </details>}
    </div>
    <ReportEditor key={`${draft?.id ?? 'new'}`} taskId={taskId} draftId={draft?.id} contextId={contextId} title={title} body={body} appendix={reading.appendix}
      toolbarLabel={draft ? '文稿' : '写下判断与建议'}
      status={draft ? `${draftStateText(draft)} · 检查：${qualityShortLabel(qualityState)}` : undefined}
      assistantAction={<Button variant="ghost" size="sm" type="button" aria-label={draft ? '围绕此稿继续分析' : '请助手整理文稿'} title={draft ? '围绕此稿继续分析' : '请助手整理文稿'}
        disabled={busy || Boolean(draft && changed && (!title.trim() || !body.trim() || materialityError))}
        onClick={() => onChat(changed && body.trim() ? spec('draft') : undefined)}><MessageSquare size={14} aria-hidden />{draft ? '继续分析' : '请助手整理文稿'}</Button>}
      limitations={limitations} review={review} document={document} busy={busy} initialMode={reportMode} mode={reportMode} onMode={setReportMode} onTitle={setTitle}
      onBody={onBodyChange} onDocument={onDocumentChange} onLimitations={setLimitations} onReview={setReview} onExport={(format, mode) => onExport(format, changed ? spec('draft') : undefined, mode)}
      onAppliedDraft={onAppliedDraft} />
    {draft && parentDraft && draftRuns[0] && <RevisionDiff current={draftRuns[0]} previous={previousRun} comparison={comparison}
      currentRevision={drafts.findIndex((item) => item.id === draft.id) + 1} previousRevision={drafts.findIndex((item) => item.id === parentDraft.id) + 1}
      evidence={{ affected_claims: affectedClaims, unresolved_issues: quality?.issues ?? [] }} />}
    {/* Everything that decides whether this version can go out, after the text it checks. */}
    <section className="analysis-prepublish" aria-label="发布前检查">
    <div className="analysis-section-heading"><h3>发布前检查</h3><p className="analysis-note">质量检查、重要性阈值、引用的计算和经理判断背景。</p></div>
    {(draft || recovery) && <ExplanationQualityPanel taskId={taskId} quality={quality} state={qualityState} facts={facts} citedFactIds={citedFactIds} factDetails={factDetails} locatorNotice={locatorNotice} locatorPdf={locatorPdf} busy={busy} onRecheck={() => void recheck()} onOpenFact={(fact) => void openFact(fact)} onOpenLocator={(fact) => void openLocator(fact)} />}
    <fieldset className="analysis-fieldset analysis-draft-fields" disabled={busy}>
    <MaterialityFields value={materiality} scopeText={materialityScopeSummary(financeRuns)} error={materialityError} disabled={busy} onChange={onMaterialityChange} />
    </fieldset>
    {draft && <details className="analysis-details"><summary>引用的计算与依据 · {draft.run_ids.length} 次运行</summary>
      {draft.run_ids.length === 0 && <p>这份文稿尚未引用计算记录。</p>}
      {draft.run_ids.map((id) => { const run = runs.find((item) => item.id === id); return <div key={id}>
        <p>{id}</p>{run ? <RunStatus run={run} /> : <p>此运行记录暂不可读取。</p>}</div>; })}
      {draft.claims.map((claim, index) => <p key={index}>{textValue(claim)}</p>)}</details>}
    {draft && financeRuns.length > 0 && <FinanceBackgroundPanel background={background} scope={backgroundScope} scopeJson={scopeJson} backgrounds={backgrounds} datasets={sourceDatasets} busy={busy}
      message={backgroundMessage} onBackground={setBackground} onScope={setBackgroundScope} onScopeJson={setScopeJson} onSave={() => void saveBackground()} onList={() => void loadBackgrounds()} />}
    </section>
    <div className="analysis-actions">{changed && <Button type="button" disabled={busy || !title.trim() || !body.trim() || Boolean(materialityError)} onClick={() => onSave(spec('draft'))}>保存文稿新版</Button>}
      <Button variant="outline" type="button" disabled={busy || !title.trim() || !body.trim() || Boolean(materialityError)} onClick={() => onSave(spec('archived'))}>选定并归档此版</Button></div>
    {changed && <p className="analysis-note">交给助手或导出时，会先保存当前内容为新版本。</p>}
    {toolError && <p role="alert" className="analysis-message analysis-message--error">{toolError}</p>}
  </div>;
}

function firstFinanceScope(run?: AnalysisRun): Record<string, unknown> {
  const scopes = Object.values(run?.finance_scope ?? {});
  return scopes[0] ?? {};
}

function scopeToFields(scope: Record<string, unknown>): Record<string, string> {
  return Object.fromEntries(['ledger', 'organization', 'period', 'currency', 'unit'].map((key) => [key, scope[key] == null ? '' : textValue(scope[key])])) as Record<string, string>;
}

function currentBackgroundScope(fields: Record<string, string>, extraJson: string): Record<string, unknown> {
  const base = Object.fromEntries(Object.entries(fields).filter(([, value]) => value.trim()).map(([key, value]) => [key, value.trim()]));
  return { ...parseObject(extraJson, '高级范围 JSON'), ...base };
}

function parseObject(value: string, label: string): Record<string, unknown> {
  if (!value.trim()) return {};
  const parsed = JSON.parse(value);
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error(`${label} 需要是对象。`);
  return parsed as Record<string, unknown>;
}

function explicitFactIds(draft: AnalysisDraft | undefined, body: string, extraFactIds: string[] = []): string[] {
  const fromDraft = draft?.fact_ids ?? [];
  const fromBody = Array.from(body.matchAll(/\{\{\s*fact:([A-Za-z0-9_.:-]+)\s*\}\}/g), (match) => match[1]);
  return Array.from(new Set([...fromDraft, ...extraFactIds, ...fromBody].filter(Boolean)));
}

function isVisibleRecovery(item: FinanceCompletionRecovery): boolean {
  return ['repair_available', 'timed_out', 'cancelled', 'failed', 'needs_review', 'awaiting_input'].includes(item.status)
    && Boolean(String(item.body ?? item.title ?? '').trim());
}

function hasMeaningfulUnsavedDraft(draft: AnalysisDraft | undefined, edit: DraftEdit, materialityChanged: boolean): boolean {
  if (draft) {
    return draftEditDiffers(draft, edit) || materialityChanged || Boolean(edit.recovery);
  }
  return Boolean(edit.body.trim() || edit.limitations.trim() || (edit.title.trim() && edit.title.trim() !== '经营分析') || edit.recovery);
}

function draftEditDiffers(draft: AnalysisDraft, edit: DraftEdit): boolean {
  return edit.title !== draft.title || edit.body !== draft.body || edit.limitations !== draft.limitations.join('\n')
    || edit.review !== draft.review_status || !sameDocument(edit.document, richDraftDocument(draft)) || !sameMateriality(edit.materiality, draft.materiality) || Boolean(edit.recovery);
}

function richDraftDocument(draft: AnalysisDraft | undefined): ReportDraftDocument | undefined {
  const value = (draft as (AnalysisDraft & { document?: unknown }) | undefined)?.document;
  return isReportDocument(value) ? value : undefined;
}

function richRecoveryDocument(recovery: FinanceCompletionRecovery): ReportDraftDocument | undefined {
  const value = (recovery as FinanceCompletionRecovery & { document?: unknown }).document;
  return isReportDocument(value) ? value : undefined;
}

function isReportDocument(value: unknown): value is ReportDraftDocument {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value)
    && (value as { schema_version?: unknown }).schema_version === 1
    && (value as { template_version?: unknown }).template_version === 'annual-v1'
    && Array.isArray((value as { content?: unknown }).content));
}

function sameDocument(left?: ReportDraftDocument, right?: ReportDraftDocument): boolean {
  return JSON.stringify(left ?? null) === JSON.stringify(right ?? null);
}

function qualityStateFromResult(value: ExplanationQuality): 'passed' | 'issues' | 'unavailable' {
  if (value.status === 'pass') return 'passed';
  if ((value.issues ?? []).length || ['needs_attention', 'issues', 'failed'].includes(String(value.status ?? ''))) return 'issues';
  return 'unavailable';
}

function externalReferencePayload(source: string, retrievedAt: string): Record<string, string> {
  const payload: Record<string, string> = { title: source, retrieved_at: retrievedAt };
  if (/^https?:\/\//i.test(source)) payload.url = source;
  return payload;
}

/** The check state in the document toolbar, one word beside 草稿 · 未阅; the panel below says it in full. */
function qualityShortLabel(state: 'idle' | 'checking' | 'passed' | 'issues' | 'stale' | 'unavailable'): string {
  return ({ idle: '未检查', checking: '进行中', passed: '通过', issues: '待复核', stale: '改稿后未重检', unavailable: '不可用' } as Record<typeof state, string>)[state];
}

/** Main answers a failed locator open with a code, not a sentence; the sentence is written here. */
const LOCATOR_FAILURES: Record<string, string> = {
  locator_forbidden: '无权打开',
  locator_unavailable: '原文定位暂不可用',
  preview_unavailable: '预览暂不可用',
  locator_error: '原文定位失败',
};

function locatorFailureText(failure: unknown): string {
  const message = errorText(failure);
  return LOCATOR_FAILURES[message] ?? message;
}
