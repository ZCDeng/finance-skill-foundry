import { useEffect, useId, useRef, useState } from 'react';
import { ArrowRight, ExternalLink, FilePen, FolderOpen, X } from 'lucide-react';

import {
  type AnalysisDraftRow,
  type AnalysisExportRow,
  type ChartRow,
  type CollectionRunRow,
  type DashboardSnapshotRow,
  type LibraryDetail,
  type LibraryFile,
  type TaskRow,
  type WorkbookOutputRow,
  SNAPSHOT_FORMAT_WORDS,
  when,
} from '../bridge.js';
import { Button } from '../components/ui/button.js';
import { NativeSelect } from '../components/ui/native-select.js';
import { DisclosureSummary } from '../components/Disclosure.js';
import { Loading, SkeletonRows } from '../components/Loading.js';
import { Reader } from '../components/Reader.js';
import { formatPeriod } from '../lib/period.js';
import { diffCounts, lineDiff } from '../lib/textDiff.js';
import { draftStateText } from './analysis/presentation.js';

/** What the side panel is showing. A revision may be one that only has exports (`draft` null). */
export type LibrarySelection =
  | { kind: 'revision'; task: TaskRow; draftId: string; revision: number; title: string; draft: AnalysisDraftRow | null;
    state: { publication_status: string; review_status: string }; exports: AnalysisExportRow[] }
  | { kind: 'chart'; task: TaskRow; chart: ChartRow }
  | { kind: 'workbook'; task: TaskRow; output: WorkbookOutputRow }
  | { kind: 'collection'; task: TaskRow; run: CollectionRunRow }
  | { kind: 'dashboard'; task: TaskRow; snapshot: DashboardSnapshotRow };

export interface LibraryPanelActions {
  /** The draft's text, checks and what it rests on. Absent in a build without it: the panel then shows what the list knows. */
  onDetail?(task: TaskRow, draftId: string): Promise<LibraryDetail>;
  /** Go to that task's 文稿 tab with this version selected. */
  onOpenDraft?(task: TaskRow, draft: AnalysisDraftRow): void;
  /** Open a filed export or a 写回 Excel copy, or show it in Finder. */
  onFile?(task: TaskRow, file: LibraryFile, action: 'open' | 'reveal'): void;
  /** Open the task where this result lives: 分析结果 for a chart, 资料 for a 收缴率 run, 看板 for a snapshot. */
  onOpenTask?(task: TaskRow, target: 'drafts' | 'billing' | 'dashboard'): void;
}

const FORMAT_LABEL: Record<AnalysisExportRow['format'], string> = { md: 'Markdown', xlsx: 'Excel', docx: 'Word', pdf: 'PDF', html: 'HTML' };
const MODE_LABEL: Record<string, string> = { management: '管理版', audit: '审计版' };
const CHECK_WORDS: Record<string, string> = { pass: '通过', fail: '需要处理', warning: '需要处理', unreviewed: '未复核', not_configured: '未核验', unverified: '未核验' };
const CALIBER_WORDS: Record<CollectionRunRow['caliber']['status'], string> = { confirmed: '已确认口径', default: '默认口径（未确认）', trial: '试算' };
const RATE_LABELS: [string, string][] = [['collection_rate_current', '当期收缴率'], ['arrears_recovery_rate', '清欠率'], ['collection_rate_total', '综合收缴率']];
const SCOPE_LABELS: [string, string][] = [['period', '期间'], ['organization', '组织'], ['unit', '单位'], ['currency', '币种']];

function percent(value: string | null | undefined): string {
  if (value == null || value === '') return '—';
  const number = Number(value);
  return Number.isFinite(number) ? `${(number * 100).toFixed(2)}%` : String(value);
}

/**
 * 成果库's side panel: one thing the library holds, what it is, and where it came from.
 *
 * For a 文稿 revision that is the point of the panel: the runs it cites and the files those runs
 * read (by name and digest), the scope it was written against and its four checks. Nothing here
 * is judged again; every word is the store's.
 */
export function LibraryPanel({ selection, actions, onClose }: { selection: LibrarySelection; actions: LibraryPanelActions; onClose(): void }) {
  const id = useId();
  const panel = useRef<HTMLElement>(null);
  // Under 1100px the panel sits below the list; bring it into view rather than open it off screen.
  useEffect(() => {
    if (window.matchMedia?.('(max-width: 1100px)').matches) panel.current?.scrollIntoView?.({ block: 'nearest' });
  }, []);
  const title = selection.kind === 'revision' ? `${selection.title || '文稿'} · 修订 ${selection.revision}`
    : selection.kind === 'chart' ? selection.chart.label || '归档图'
      : selection.kind === 'workbook' ? `写回 Excel · ${selection.output.dataset}`
        : selection.kind === 'dashboard' ? `看板快照 · ${SNAPSHOT_FORMAT_WORDS[selection.snapshot.format]}`
          : `收缴率计算 · 截至 ${selection.run.as_of}`;
  return (
    <aside ref={panel} className="fnd-library__panel" aria-labelledby={`${id}-title`}>
      <div className="fnd-library__panel-head">
        <div>
          <h2 id={`${id}-title`} className="fnd-library__panel-title">{title}</h2>
          <p className="fnd-muted">{selection.task.title}{selection.task.period ? <> · <span className="fnd-period">{formatPeriod(selection.task.period)}</span></> : null}</p>
        </div>
        <Button type="button" size="icon" variant="ghost" aria-label="关闭详情" onClick={onClose}><X size={16} aria-hidden /></Button>
      </div>
      {selection.kind === 'revision' ? <RevisionDetail selection={selection} actions={actions} />
        : selection.kind === 'chart' ? <ChartDetail chart={selection.chart} task={selection.task} actions={actions} />
          : selection.kind === 'workbook' ? <WorkbookDetail output={selection.output} task={selection.task} actions={actions} />
            : selection.kind === 'dashboard' ? <DashboardDetail snapshot={selection.snapshot} task={selection.task} actions={actions} />
              : <CollectionDetail run={selection.run} task={selection.task} actions={actions} />}
    </aside>
  );
}

function Pairs({ rows }: { rows: [string, React.ReactNode][] }) {
  return <dl className="fnd-library__pairs">{rows.map(([term, value]) => <div key={term}><dt>{term}</dt><dd>{value}</dd></div>)}</dl>;
}

function RevisionDetail({ selection, actions }: { selection: Extract<LibrarySelection, { kind: 'revision' }>; actions: LibraryPanelActions }) {
  const { task, draftId, draft } = selection;
  const [detail, setDetail] = useState<LibraryDetail | null>(null);
  const [error, setError] = useState('');
  const [other, setOther] = useState('');
  const [otherBody, setOtherBody] = useState<{ id: string; body: string } | null>(null);
  useEffect(() => {
    let live = true;
    setDetail(null); setError(''); setOther(''); setOtherBody(null);
    actions.onDetail?.(task, draftId).then((value) => { if (live) setDetail(value); },
      (failure: unknown) => { if (live) setError(failure instanceof Error ? failure.message : String(failure)); });
    return () => { live = false; };
  }, [task.id, draftId]);
  useEffect(() => {
    if (!other || !actions.onDetail) { setOtherBody(null); return; }
    let live = true;
    actions.onDetail(task, other).then((value) => { if (live) setOtherBody({ id: other, body: value.draft.body }); },
      (failure: unknown) => { if (live) setError(failure instanceof Error ? failure.message : String(failure)); });
    return () => { live = false; };
  }, [other, task.id]);
  const versions = detail?.versions.filter((row) => row.draft_id !== draftId) ?? [];
  const comparing = otherBody && detail && otherBody.id === other
    ? (() => {
      const older = (detail.versions.find((row) => row.draft_id === other)?.revision ?? 0) < detail.draft.revision;
      return { older, lines: older ? lineDiff(otherBody.body, detail.draft.body) : lineDiff(detail.draft.body, otherBody.body) };
    })()
    : null;
  return <div className="fnd-library__panel-body">
    <Pairs rows={[
      ['状态', draftStateText(selection.state)],
      ['保存时间', draft ? when(draft.created_at) : detail ? when(detail.draft.created_at) : '—'],
    ]} />
    <div className="fnd-library__panel-actions">
      {draft && actions.onOpenDraft ? <Button type="button" variant="outline" onClick={() => actions.onOpenDraft!(task, draft)}>
        <FilePen size={14} strokeWidth={1.5} aria-hidden />在文稿页打开
      </Button> : null}
    </div>
    {selection.exports.length ? <section className="fnd-library__panel-section" aria-label="导出件">
      <h3>导出件</h3>
      <ul className="fnd-library__files">
        {selection.exports.map((exported) => <li key={exported.export_id}>
          <span>{FORMAT_LABEL[exported.format]}{exported.content_mode ? ` · ${MODE_LABEL[exported.content_mode] ?? exported.content_mode}` : ''}
            <span className="fnd-muted"> · {when(exported.created_at)}</span></span>
          {actions.onFile ? <span className="fnd-library__file-actions">
            <Button type="button" size="sm" variant="ghost" onClick={() => actions.onFile!(task, { kind: 'export', sha: exported.sha256, format: exported.format }, 'open')}>
              <ExternalLink size={13} strokeWidth={1.5} aria-hidden />打开<span className="sr-only">{FORMAT_LABEL[exported.format]}</span></Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => actions.onFile!(task, { kind: 'export', sha: exported.sha256, format: exported.format }, 'reveal')}>
              <FolderOpen size={13} strokeWidth={1.5} aria-hidden />在访达中显示<span className="sr-only">{FORMAT_LABEL[exported.format]}</span></Button>
          </span> : null}
        </li>)}
      </ul>
      {selection.exports.some((row) => row.review_marker) ? <p className="fnd-muted">导出件带「{selection.exports.find((row) => row.review_marker)!.review_marker}」标记。</p> : null}
    </section> : null}
    {error ? <p role="alert" className="analysis-message analysis-message--error">{error}</p> : null}
    {actions.onDetail && !detail && !error ? <Loading label="正在读取这一版的依据…"><SkeletonRows rows={3} meta={false} /></Loading> : null}
    {detail ? <>
      <section className="fnd-library__panel-section" aria-label="检查">
        <h3>检查</h3>
        <ul className="fnd-library__checks">
          {detail.checks.map((check) => <li key={check.key} data-status={check.status === 'pass' ? 'pass' : 'open'}>
            <span>{check.label}</span><span>{CHECK_WORDS[check.status] ?? check.status}</span>
          </li>)}
        </ul>
      </section>
      <section className="fnd-library__panel-section" aria-label="来源追溯">
        <h3>来源追溯</h3>
        <p className="fnd-muted">这一版引用的计算，以及每次计算读的资料（摘要前 12 位）。</p>
        {detail.requirements ? <Pairs rows={SCOPE_LABELS.filter(([key]) => detail.requirements!.scope[key])
          .map(([key, label]) => [label, key === 'period' ? formatPeriod(String(detail.requirements!.scope[key])) : String(detail.requirements!.scope[key])])} /> : null}
        {detail.rests_on.length === 0 ? <p className="fnd-muted">这一版没有引用计算结果。</p> : <ul className="fnd-library__sources">
          {detail.rests_on.map((run) => <li key={run.run_id}>
            <span className="fnd-library__source-run">{run.label}{run.created_at ? <span className="fnd-muted"> · {when(run.created_at)}</span> : null}</span>
            {run.datasets.length ? <ul>{run.datasets.map((dataset) => <li key={dataset.id}>
              {dataset.name}{dataset.hash ? <span className="fnd-muted fnd-figure"> · {dataset.hash}</span> : null}
            </li>)}</ul> : null}
          </li>)}
        </ul>}
      </section>
      <section className="fnd-library__panel-section" aria-label="两版对比">
        <h3>两版对比</h3>
        {versions.length === 0 ? <p className="fnd-muted">这个任务只有这一版文稿。</p> : <>
          <NativeSelect aria-label="和哪一版比较" value={other} onChange={(event) => setOther(event.target.value)}>
            <option value="">选另一版…</option>
            {[...versions].reverse().map((row) => <option key={row.draft_id} value={row.draft_id}>修订 {row.revision} · {row.title} · {when(row.created_at)}</option>)}
          </NativeSelect>
          {other && !comparing ? <p className="fnd-muted" role="status">正在读取…</p> : null}
          {comparing ? <TextDiff older={comparing.older} lines={comparing.lines} /> : null}
        </>}
      </section>
      <details className="analysis-details fnd-library__body">
        <DisclosureSummary>正文</DisclosureSummary>
        {detail.draft.body.trim() ? <Reader source={detail.draft.body} /> : <p className="fnd-muted">这一版没有正文。</p>}
      </details>
    </> : null}
  </div>;
}

/** What changed between two versions, oldest on the left of the arrow. */
function TextDiff({ older, lines }: { older: boolean; lines: ReturnType<typeof lineDiff> }) {
  if (lines === null) return <p className="fnd-muted">两版都太长，这里比较不了，请在文稿页逐段查看。</p>;
  const { added, removed } = diffCounts(lines);
  if (!added && !removed) return <p className="fnd-muted" role="status">两版正文相同。</p>;
  return <div className="fnd-library__diff">
    <p className="fnd-muted" role="status">{older ? '从所选那一版到这一版' : '从这一版到所选那一版'}：新增 {added} 行，删除 {removed} 行。</p>
    <ol>
      {lines.map((line, index) => {
        if (line.kind === 'added') return <li key={index} data-kind="added"><ins><span className="sr-only">新增：</span>{line.text || ' '}</ins></li>;
        if (line.kind === 'removed') return <li key={index} data-kind="removed"><del><span className="sr-only">删除：</span>{line.text || ' '}</del></li>;
        if (near(lines, index)) return <li key={index} data-kind="same">{line.text || ' '}</li>;
        // One mark where a run of unchanged lines is left out.
        return index === 0 || lines[index - 1].kind !== 'same' || near(lines, index - 1) ? <li key={index} data-kind="gap" aria-hidden>…</li> : null;
      })}
    </ol>
  </div>;
}

/** An unchanged line is kept when it sits next to a change, for context; the rest of the document is left out. */
function near(lines: { kind: string }[], index: number): boolean {
  const changed = (at: number) => at >= 0 && at < lines.length && lines[at].kind !== 'same';
  return changed(index - 1) || changed(index + 1);
}

function ChartDetail({ chart, task, actions }: { chart: ChartRow; task: TaskRow; actions: LibraryPanelActions }) {
  return <div className="fnd-library__panel-body">
    <Pairs rows={[['保存时间', when(chart.created_at)], ['读的资料', chart.datasets.join('、') || '—']]} />
    <p className="fnd-muted">归档图按保存时的计算结果画出，打开时会核对资料没有变过。</p>
    {actions.onOpenTask ? <div className="fnd-library__panel-actions"><Button type="button" variant="outline" onClick={() => actions.onOpenTask!(task, 'drafts')}>
      在「汇报 · 文稿」查看</Button></div> : null}
  </div>;
}

function WorkbookDetail({ output, task, actions }: { output: WorkbookOutputRow; task: TaskRow; actions: LibraryPanelActions }) {
  return <div className="fnd-library__panel-body">
    <Pairs rows={[
      ['生成时间', when(output.created_at)],
      ['写自', output.dataset],
      ['写入单元格', `${output.applied} 个`],
      ['保留原值', `${output.kept} 个`],
      ['摘要', <span className="fnd-figure">{output.sha256.slice(0, 12)}</span>],
    ]} />
    {actions.onFile ? <div className="fnd-library__panel-actions">
      <Button type="button" variant="outline" onClick={() => actions.onFile!(task, { kind: 'workbook', id: output.id }, 'open')}>
        <ExternalLink size={14} strokeWidth={1.5} aria-hidden />在表格软件里打开</Button>
      <Button type="button" variant="ghost" onClick={() => actions.onFile!(task, { kind: 'workbook', id: output.id }, 'reveal')}>
        <FolderOpen size={14} strokeWidth={1.5} aria-hidden />在访达中显示</Button>
    </div> : null}
  </div>;
}

function CollectionDetail({ run, task, actions }: { run: CollectionRunRow; task: TaskRow; actions: LibraryPanelActions }) {
  const caliber = CALIBER_WORDS[run.caliber.status] + (run.caliber.status === 'confirmed' && run.caliber.version ? ` 第 ${run.caliber.version} 版` : '');
  return <div className="fnd-library__panel-body">
    <Pairs rows={[
      ['计算时间', when(run.created_at)],
      ['截至', run.as_of],
      ['口径', caliber],
      ...RATE_LABELS.map(([key, label]): [string, React.ReactNode] => [label, <span className="fnd-figure">{percent(run.figures[key])}</span>]),
      ['明细', Object.values(run.inputs).join('、') || '—'],
    ]} />
    {run.caliber.status !== 'confirmed' ? <p className="fnd-muted">口径还没有经理确认，这些数只作参考。</p> : null}
    {actions.onOpenTask ? <div className="fnd-library__panel-actions"><Button type="button" variant="outline" onClick={() => actions.onOpenTask!(task, 'billing')}>
      在「经营分析」查看</Button></div> : null}
  </div>;
}

/** A 看板快照: the accepted cards it shows, the ones it left out and why, and the file itself. */
function DashboardDetail({ snapshot, task, actions }: { snapshot: DashboardSnapshotRow; task: TaskRow; actions: LibraryPanelActions }) {
  const file: LibraryFile = { kind: 'dashboard', id: snapshot.id };
  const left = [
    snapshot.left_out.pinned.length ? `待认可 ${snapshot.left_out.pinned.length} 张` : '',
    snapshot.left_out.scenario.length ? `情景 ${snapshot.left_out.scenario.length} 张` : '',
    snapshot.beyond.length ? `一页放不下 ${snapshot.beyond.length} 张（${snapshot.beyond.join('、')}）` : '',
  ].filter(Boolean).join('；');
  return <div className="fnd-library__panel-body">
    <Pairs rows={[
      ['导出时间', when(snapshot.created_at)],
      ['格式', SNAPSHOT_FORMAT_WORDS[snapshot.format]],
      ['放进来的卡', snapshot.cards.join('、') || '—'],
      ...(left ? [['没放进来', left] as [string, React.ReactNode]] : []),
      ['摘要', <span className="fnd-figure">{snapshot.sha256.slice(0, 12)}</span>],
    ]} />
    <p className="fnd-muted">只放经理认可的卡。导出时逐个核对过，每个数都是它读的那次计算里的数；情景卡不放进来。</p>
    <div className="fnd-library__panel-actions">
      {actions.onFile ? <>
        <Button type="button" variant="outline" onClick={() => actions.onFile!(task, file, 'open')}>
          <ExternalLink size={14} strokeWidth={1.5} aria-hidden />打开</Button>
        <Button type="button" variant="ghost" onClick={() => actions.onFile!(task, file, 'reveal')}>
          <FolderOpen size={14} strokeWidth={1.5} aria-hidden />在访达中显示</Button>
      </> : null}
      {actions.onOpenTask ? <Button type="button" variant="ghost" onClick={() => actions.onOpenTask!(task, 'dashboard')}>
        去这个任务的看板<ArrowRight size={14} strokeWidth={1.5} aria-hidden /></Button> : null}
    </div>
  </div>;
}
