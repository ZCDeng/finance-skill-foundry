import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { Calculator, FilePlus2, Sparkles } from 'lucide-react';
import {
  bridge, timeWait, when,
  type BillingCommand, type BillingDetail, type BillingKind, type CollectionCaliber, type CollectionCaliberParams,
  type CollectionIssue, type CollectionRun, type CollectionRunSummary, type DrillFigure,
} from '../../bridge.js';
import { Button } from '../../components/ui/button.js';
import { Badge } from '../../components/ui/badge.js';
import { Checkbox } from '../../components/ui/checkbox.js';
import { NativeSelect } from '../../components/ui/native-select.js';
import { DateInput, DecimalInput, FieldShell, TextField } from '../../components/FinancialControls.js';
import { DisclosureSummary } from '../../components/Disclosure.js';
import { Figure } from '../../components/Figure.js';
import { WaitLoop } from '../../components/WaitLoop.js';
import { decimalToFixed, formatAmount } from '../../lib/figures.js';
import { HelpLink } from '../guide/GuideHub.js';
import { BillingDrill } from './BillingDrill.js';
import { errorText, unwrap } from './shared.js';

/**
 * 收费明细: the household-level 应收、实收 and 房产主数据 (foundry/billing_detail.py), and the collection
 * rates computed from them.
 *
 * Every rate comes from a run the engine filed; this panel only orders and draws it. The manager confirms
 * what each column is and which 口径 holds; the assistant can only propose either, and a run on values
 * nobody confirmed is marked 试算.
 */

export const KIND_LABELS: Record<BillingKind, string> = { receivable: '应收明细', receipt: '实收明细', property: '房产主数据' };
const KINDS: BillingKind[] = ['receivable', 'receipt', 'property'];
const GROUPS: [string, string][] = [
  ['', '不分组'], ['nature', '房产性质'], ['project', '项目'], ['fee_item', '收费项目'], ['customer_type', '客户性质'],
  ['type', '房产类型'], ['owner', '产权归属'], ['city', '城市公司'],
];
const GROUP_KIND: Record<string, BillingKind> = {
  nature: 'property', type: 'property', owner: 'property', city: 'property', project: 'receivable', fee_item: 'receivable', customer_type: 'receivable',
};
const ISSUES: Record<string, string> = {
  void_bills: '作废账单，不计入',
  red_letter_lines: '冲红行，原单和冲红一起剔除',
  unreadable_bill_lines: '读不出账单号、账期或金额的应收行',
  unreadable_receipts: '读不出日期或金额的收款行',
  receipts_without_bill: '找不到对应账单的收款，记作预收',
  mixed_fee_bills: '一张账单里既有剔除的又有保留的收费项目，收款按金额比例分摊',
  bills_without_property: '房产主数据里没有的房产',
  repeated_properties: '重复的房产编号，只取第一行',
  advance_labelled_current: '收费系统标为「当期」，账期却在统计月之后（实为预收）',
  arrears_labelled_current: '收费系统标为「当期」，账期却在本年之前（实为清欠）',
};
const CALIBER_KEYS: Record<string, string> = {
  year_start_month: '统计年度起始月', total_method: '综合收缴率算法', related_owners: '关联方产权归属',
  exclude_related: '是否剔除关联方', excluded_fee_items: '不计入的收费项目',
};

/** 0.8212 as 82.12%. */
export const percent = (rate: string | null | undefined) => rate == null ? '—' : `${decimalToFixed(rate, 2, 100)}%`;

/** What the manager typed in percent (83.76) as the rate the engine takes (0.8376), without floating point. */
export function percentToRate(text: string): string | null {
  const match = /^\s*(-?)(\d+)(?:\.(\d+))?\s*%?\s*$/.exec(text);
  if (!match) return null;
  const [, sign, whole, fraction = ''] = match;
  // Move the point two places left: 83.76 → 0.8376, 5 → 0.05, 100 → 1.00.
  const padded = whole.padStart(3, '0');
  const integer = padded.slice(0, -2).replace(/^0+(?=\d)/, '');
  return `${sign}${integer}.${padded.slice(-2)}${fraction}`;
}

/** The 口径 in a manager's words, one line per setting. */
export function caliberLines(params: CollectionCaliberParams): string[] {
  return [
    params.year_start_month === 1 ? '统计年度：自然年，1 月起累计' : `统计年度：服务年度，${params.year_start_month} 月起累计`,
    params.total_method === 'bounded'
      ? '综合收缴率 =（当期已收 + 本年清欠）÷（本年应收 + 年初欠费）'
      : '综合收缴率 = 本年全部实收 ÷ 本年应收（预收和清欠都算进分子）',
    params.exclude_related
      ? `关联方（产权归属为${params.related_owners.join('、')}）不计入`
      : `关联方（产权归属为${params.related_owners.join('、')}）计入，另列剔除后的数`,
    params.excluded_fee_items.length ? `不算物业费的收费项目：${params.excluded_fee_items.join('、')}` : '全部收费项目都计入',
  ];
}

const listText = (values: string[]) => values.join('、');
const splitList = (text: string) => [...new Set(text.split(/[、,，;；\s]+/).map((item) => item.trim()).filter(Boolean))];
const lastDay = (period: string | null | undefined) => {
  const match = /^(\d{4})-(\d{2})$/.exec(period ?? '');
  if (!match) return '';
  const day = new Date(Date.UTC(Number(match[1]), Number(match[2]), 0)).getUTCDate();
  return `${match[1]}-${match[2]}-${String(day).padStart(2, '0')}`;
};

export function BillingPanel({ taskId, period, practice, readOnly, refreshKey, show, onShown }: {
  taskId: string;
  /** The task's 期间 (YYYY-MM): its last day is the first 统计截止日 offered. */
  period?: string | null;
  /** A practice task of the example, which can take the example's 收费明细. */
  practice?: boolean;
  readOnly?: boolean;
  refreshKey?: unknown;
  /** A run to show and bring into view: 打开收缴率结果 on a card in the conversation. `count` makes a repeat click count. */
  show?: { id: string; count: number };
  /** The run asked for is on screen; the caller lets go of the request, so coming back later does not scroll again. */
  onShown?(): void;
}) {
  const [details, setDetails] = useState<BillingDetail[]>([]);
  const [caliber, setCaliber] = useState<CollectionCaliber | null>(null);
  const [runs, setRuns] = useState<CollectionRunSummary[]>([]);
  const [run, setRun] = useState<CollectionRun | null>(null);
  const [working, setWorking] = useState<string>('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const call = useCallback(async <T,>(command: BillingCommand, spec?: Record<string, unknown>) => {
    const api = bridge(); if (!api?.billingCall) throw new Error('此版本暂不支持收费明细。');
    return unwrap(await api.billingCall(taskId, command, spec)) as T;
  }, [taskId]);
  const seen = useRef({ signature: '', newest: '' });
  const shown = useRef<string | undefined>(undefined);
  /** One read of the tables, the 口径 and the run list; the shown run is read again only when asked or a new run lands. */
  const load = useCallback(async (show?: string) => {
    const state = await call<{ details: BillingDetail[]; caliber: CollectionCaliber; runs: CollectionRunSummary[] }>('collection-state');
    const signature = JSON.stringify(state);
    const newest = state.runs.at(-1)?.id ?? '';
    const before = seen.current;
    seen.current = { signature, newest };
    if (!show && signature === before.signature) return;
    // Keep the run the manager picked, unless a newer run has landed since.
    const pick = show ?? (shown.current && newest === before.newest ? shown.current : newest || undefined);
    setDetails(state.details); setCaliber(state.caliber); setRuns(state.runs);
    shown.current = pick;
    setRun(pick ? await call<CollectionRun>('collection-run-read', { run: pick }) : null);
  }, [call]);
  // A panel opened to show a run starts on it, so its first read does not land on the newest run after it.
  const asked = useRef(show);
  asked.current = show;
  useEffect(() => { seen.current = { signature: '', newest: '' }; shown.current = undefined; setRun(null); void load(asked.current?.id).catch(() => {}); }, [load, refreshKey]);
  const heading = useRef<HTMLHeadingElement>(null);
  const shownDone = useRef(onShown);
  shownDone.current = onShown;
  useEffect(() => {
    if (!show) return;
    void load(show.id).then(() => {
      heading.current?.scrollIntoView?.({ block: 'start' });
      shownDone.current?.();
    }, (failure: unknown) => setError(errorText(failure)));
  }, [load, show]);
  // The assistant proposes columns and 口径 and runs trials from the conversation beside this page; read again
  // every few seconds while the window is in view, so what it proposed is here to confirm.
  useEffect(() => {
    const timer = window.setInterval(() => { if (document.visibilityState === 'visible') void load().catch(() => {}); }, 8000);
    return () => window.clearInterval(timer);
  }, [load]);
  const act = async (name: string, work: () => Promise<string | void>) => {
    if (working) return;
    setWorking(name); setError(''); setMessage('');
    try {
      const said = await work();
      if (said) setMessage(said);
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      setWorking('');
    }
  };
  const addTable = (kind: BillingKind) => act(`add:${kind}`, () => timeWait('billing.import', async (note) => {
    const api = bridge(); if (!api?.billingAdd) throw new Error('此版本暂不支持导入收费明细。');
    const added = unwrap(await api.billingAdd(taskId, kind));
    if ('cancelled' in added) { note('cancelled'); return; }
    await load();
    return `已导入「${added.name}」，共 ${added.row_count.toLocaleString('en-US')} 行。请在下面确认每一列是什么。`;
  }));
  const addSample = () => act('sample', async () => {
    const api = bridge(); if (!api?.taskSampleBilling) throw new Error('此版本暂不支持导入示例收费明细。');
    unwrap(await api.taskSampleBilling(taskId));
    await load();
    return '已导入海口城市公司的三张收费明细。系统按列名认出了各列，请逐张确认。';
  });
  const disabled = readOnly || Boolean(working);
  const confirmed = (kind: BillingKind) => details.filter((row) => row.kind === kind && row.confirmation);

  return <section className="analysis-billing" aria-labelledby="analysis-billing-title">
    <div className="analysis-section-heading"><span className="fnd-with-help"><h3 id="analysis-billing-title" ref={heading}>收费明细与收缴率</h3>
      <HelpLink article="billing-detail" label="收费明细与收缴率口径" /></span></div>
    <p className="analysis-note">按户的应收、实收和房产主数据单独导入（CSV，GBK 或 UTF-8，单张最多 500 万行），算当期收缴率、清欠率和综合收缴率，并和套表填报的数对照。</p>
    <div className="analysis-actions">
      {KINDS.map((kind) => <Button key={kind} variant="outline" type="button" disabled={disabled} onClick={() => void addTable(kind)}>
        <FilePlus2 size={14} aria-hidden />导入{KIND_LABELS[kind]}</Button>)}
      {practice && details.length < 3 ? <Button type="button" disabled={disabled} onClick={() => void addSample()}>
        <Sparkles size={14} aria-hidden />导入示例收费明细</Button> : null}
    </div>
    {working === 'sample' ? <p role="status" className="analysis-note"><WaitLoop />正在生成并导入示例收费明细（约 78 万行），要一两分钟…</p> : null}
    {working.startsWith('add:') ? <p role="status" className="analysis-note"><WaitLoop />正在读入明细，行数多时要几分钟…</p> : null}
    {details.length > 0 && <div className="analysis-billing-tables">
      {details.map((row) => <DetailCard key={row.id} row={row} disabled={disabled}
        onConfirm={(mapping) => act(`confirm:${row.id}`, async () => {
          await call('detail-confirm', { detail: row.id, mapping }); await load(run?.id);
          return `已确认「${row.name}」的列。`;
        })} />)}
    </div>}
    {caliber && <CaliberCard caliber={caliber} disabled={disabled}
      onConfirm={(spec) => act('caliber', async () => {
        await call('collection-caliber-confirm', spec); await load(run?.id);
        return '口径已确认，之后的计算按这个口径；之前的计算记录保持原样。';
      })} />}
    {details.length > 0 && <RunForm key={`${taskId}:${runs.at(-1)?.id ?? ''}`} details={details} confirmed={confirmed} caliber={caliber}
      last={run} period={period} disabled={disabled} running={working === 'run'}
      onRun={(spec) => act('run', () => timeWait('billing.run', async () => {
        const made = await call<CollectionRun>('collection-run', spec);
        await load(made.id);
        return made.caliber.status === 'trial' ? '已算完。这次用了未确认的口径，结果标为「试算」。' : '已算完。';
      }))} />}
    {message && <p role="status" className="analysis-message">{message}</p>}
    {error && <p role="alert" className="analysis-message analysis-message--error">{error}</p>}
    {run && <RunView key={run.id} taskId={taskId} run={run} runs={runs} onPick={(id) => void act('read', async () => {
      shown.current = id;
      setRun(await call<CollectionRun>('collection-run-read', { run: id }));
    })} />}
  </section>;
}

function DetailCard({ row, disabled, onConfirm }: { row: BillingDetail; disabled: boolean; onConfirm(mapping: Record<string, string>): void }) {
  const proposal = row.proposal?.mapping;
  // A proposal made after the last confirmation, and different from it, is what waits to be confirmed: show it.
  const waiting = Boolean(proposal && row.confirmation && row.proposal!.at > row.confirmation.at
    && JSON.stringify(proposal) !== JSON.stringify(row.confirmation.mapping));
  const standing = (waiting ? proposal : row.confirmation?.mapping ?? proposal) ?? {};
  const [mapping, setMapping] = useState<Record<string, string>>(standing);
  const key = JSON.stringify(standing);
  useEffect(() => { setMapping(JSON.parse(key)); }, [key]);
  const missing = row.fields.filter((field) => field.required && !mapping[field.field])
    .filter((field) => !(field.field === 'amount_net' && mapping.amount_gross) && !(field.field === 'amount_gross' && mapping.amount_net));
  const used = new Set(Object.values(mapping));
  return <details className="analysis-details analysis-billing-table" open={!row.confirmation}>
    <DisclosureSummary><span className="analysis-billing-table__summary">
      <span className="analysis-billing-table__name">{row.name}</span>
      <span className="analysis-note">{KIND_LABELS[row.kind]} · {row.row_count.toLocaleString('en-US')} 行{row.files.length > 1 ? ` · ${row.files.length} 个文件` : ''}</span>
      {row.confirmation ? <Badge variant="secondary">列已确认</Badge> : <Badge variant="destructive">待确认列</Badge>}
      {waiting ? <Badge variant="outline">助手提议了新的对应</Badge> : null}
    </span></DisclosureSummary>
    <p className="analysis-note">{waiting ? '下面是助手新提议的对应，和之前确认的不同；看一眼再确认。' : row.confirmation ? '下面是经理确认过的对应。' : row.proposal?.by === 'system' ? '系统按列名认出了下面这些列，看一眼再确认。' : '下面是助手提议的对应，看一眼再确认。'}
      带 * 的必须有；没有的列选「不用」。</p>
    <div className="analysis-edit-grid">
      {row.fields.map((field) => <FieldShell key={field.field} label={field.label} required={field.required && !['amount_net', 'amount_gross'].includes(field.field)}>
        <NativeSelect aria-label={`${row.name} ${field.label}`} value={mapping[field.field] ?? ''} disabled={disabled}
          onChange={(event) => {
            const next = { ...mapping };
            if (event.target.value) next[field.field] = event.target.value; else delete next[field.field];
            setMapping(next);
          }}>
          <option value="">不用</option>
          {row.columns.map((column) => <option key={column} value={column} disabled={used.has(column) && mapping[field.field] !== column}>{column}</option>)}
        </NativeSelect>
      </FieldShell>)}
    </div>
    {missing.length ? <p className="analysis-note">还缺：{missing.map((field) => field.label).join('、')}。</p> : null}
    <div className="analysis-actions">
      <Button type="button" disabled={disabled || missing.length > 0} onClick={() => onConfirm(mapping)}>确认这些列</Button>
    </div>
  </details>;
}

function CaliberCard({ caliber, disabled, onConfirm }: {
  caliber: CollectionCaliber; disabled: boolean; onConfirm(spec: { version?: number; params?: CollectionCaliberParams }): void;
}) {
  const [draft, setDraft] = useState(caliber.effective);
  const key = JSON.stringify(caliber.effective);
  useEffect(() => { setDraft(JSON.parse(key)); }, [key]);
  const [owners, setOwners] = useState(listText(caliber.effective.related_owners));
  const [items, setItems] = useState(listText(caliber.effective.excluded_fee_items));
  useEffect(() => {
    const effective = JSON.parse(key) as CollectionCaliberParams;
    setOwners(listText(effective.related_owners)); setItems(listText(effective.excluded_fee_items));
  }, [key]);
  const proposed = caliber.proposed;
  const yearId = useId(), methodId = useId(), relatedId = useId();
  return <article className="analysis-billing-caliber" aria-labelledby="analysis-billing-caliber">
    <div className="analysis-billing-caliber__head">
      <h4 id="analysis-billing-caliber">收缴率口径</h4>
      {caliber.confirmed ? <Badge variant="secondary">已确认 · 第 {caliber.confirmed.version} 版</Badge> : <Badge variant="outline">行业通行默认，未确认</Badge>}
    </div>
    <ul className="analysis-billing-caliber__lines">{caliberLines(caliber.effective).map((line) => <li key={line}>{line}</li>)}</ul>
    <p className="analysis-note">比率按金额算；应收取减免后的净额；预收冲抵到账单才算已收；作废和冲红剔除。这几条是通行做法，不随口径变。</p>
    {proposed ? <div className="analysis-billing-proposal" role="note" aria-label="助手提议的口径">
      <p><strong>{proposed.by === 'manager' ? '待确认的口径' : '助手提议的口径'} · 第 {proposed.version} 版</strong></p>
      {proposed.note ? <p className="analysis-note">理由：{proposed.note}</p> : null}
      <ul className="analysis-billing-caliber__lines">{caliberLines(proposed.params).map((line) => <li key={line}>{line}</li>)}</ul>
      <div className="analysis-actions">
        <Button type="button" disabled={disabled} onClick={() => onConfirm({ version: proposed.version })}>确认这个口径</Button>
        <span className="analysis-note">只有经理能确认。未确认前，助手按这个口径算出的数标为「试算」。</span>
      </div>
    </div> : null}
    <details className="analysis-details"><DisclosureSummary>自己改口径</DisclosureSummary>
      <fieldset className="analysis-fieldset" disabled={disabled}><div className="analysis-edit-grid">
        <FieldShell label={CALIBER_KEYS.year_start_month} htmlFor={yearId}>
          <NativeSelect id={yearId} value={String(draft.year_start_month)} onChange={(event) => setDraft({ ...draft, year_start_month: Number(event.target.value) })}>
            {Array.from({ length: 12 }, (_, index) => <option key={index} value={index + 1}>{index ? `${index + 1} 月（服务年度）` : '1 月（自然年）'}</option>)}
          </NativeSelect></FieldShell>
        <FieldShell label={CALIBER_KEYS.total_method} htmlFor={methodId}>
          <NativeSelect id={methodId} value={draft.total_method} onChange={(event) => setDraft({ ...draft, total_method: event.target.value as CollectionCaliberParams['total_method'] })}>
            <option value="bounded">（当期已收 + 本年清欠）÷（本年应收 + 年初欠费）</option>
            <option value="all_receipts">本年全部实收 ÷ 本年应收</option>
          </NativeSelect></FieldShell>
        <TextField label={CALIBER_KEYS.related_owners} value={owners} onChange={setOwners} help="房产主数据「产权归属」里算关联方的值，用顿号分开。" />
        <TextField label={CALIBER_KEYS.excluded_fee_items} value={items} onChange={setItems} help="不算物业费的收费项目，如商业租金代收；用顿号分开。" />
        <label className="analysis-billing-check" htmlFor={relatedId}>
          <Checkbox id={relatedId} checked={draft.exclude_related} onCheckedChange={(state) => setDraft({ ...draft, exclude_related: state === true })} />
          主数字剔除关联方</label>
      </div>
      <div className="analysis-actions"><Button variant="outline" type="button" disabled={disabled || !splitList(owners).length}
        onClick={() => onConfirm({ params: { ...draft, related_owners: splitList(owners), excluded_fee_items: splitList(items) } })}>确认我改的口径</Button></div>
      </fieldset>
    </details>
  </article>;
}

function RunForm({ details, confirmed, caliber, last, period, disabled, running, onRun }: {
  details: BillingDetail[]; confirmed(kind: BillingKind): BillingDetail[]; caliber: CollectionCaliber | null; last: CollectionRun | null;
  period?: string | null; disabled: boolean; running: boolean; onRun(spec: Record<string, unknown>): void;
}) {
  const latest = (kind: BillingKind) => confirmed(kind).at(-1)?.id ?? '';
  const [chosen, setChosen] = useState<Record<BillingKind, string>>(() => ({
    receivable: latest('receivable'), receipt: latest('receipt'), property: latest('property'),
  }));
  const ids = details.map((row) => `${row.id}:${Boolean(row.confirmation)}`).join(',');
  useEffect(() => {
    setChosen((previous) => Object.fromEntries(KINDS.map((kind) => [kind,
      confirmed(kind).some((row) => row.id === previous[kind]) ? previous[kind] : latest(kind)])) as Record<BillingKind, string>);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ids]);
  const [asOf, setAsOf] = useState(last?.params.as_of ?? lastDay(period));
  const [group, setGroup] = useState(last?.params.group_by[0] ?? '');
  const [reported, setReported] = useState(last?.params.reported.collection_rate_current
    ? decimalToFixed(last.params.reported.collection_rate_current, 2, 100) : '');
  const groupMapped = !group || Boolean(details.find((row) => row.id === chosen[GROUP_KIND[group]])?.confirmation?.mapping[group]);
  const reportedRate = reported.trim() ? percentToRate(reported) : undefined;
  const blocked = !chosen.receivable || !chosen.receipt ? '应收明细和实收明细都要先确认列。'
    : !/^\d{4}-\d{2}-\d{2}$/.test(asOf) ? '填统计截止日。'
    : !groupMapped ? `按${GROUPS.find(([id]) => id === group)?.[1]}分组要先在${KIND_LABELS[GROUP_KIND[group]]}里确认这一列。`
    : reportedRate === null ? '套表填报的收缴率写成百分数，如 83.76。'
    : caliber?.effective.exclude_related && !details.find((row) => row.id === chosen.property)?.confirmation?.mapping.owner
      ? '口径剔除关联方，要用确认了「产权归属」的房产主数据。' : '';
  const ids2 = useId();
  return <article className="analysis-billing-run" aria-label="计算收缴率">
    <h4>计算收缴率</h4>
    <fieldset className="analysis-fieldset" disabled={disabled}><div className="analysis-edit-grid">
      {KINDS.map((kind) => <FieldShell key={kind} label={KIND_LABELS[kind]} htmlFor={`${ids2}-${kind}`}>
        <NativeSelect id={`${ids2}-${kind}`} value={chosen[kind]} onChange={(event) => setChosen({ ...chosen, [kind]: event.target.value })}>
          {kind === 'property' ? <option value="">不用房产主数据</option> : confirmed(kind).length ? null : <option value="">还没有确认列的{KIND_LABELS[kind]}</option>}
          {confirmed(kind).map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}
        </NativeSelect></FieldShell>)}
      <DateInput label="统计截止日" value={asOf} onChange={setAsOf} help="本年从口径的起始月算到这一天。" />
      <FieldShell label="分组" htmlFor={`${ids2}-group`}>
        <NativeSelect id={`${ids2}-group`} value={group} onChange={(event) => setGroup(event.target.value)}>
          {GROUPS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
        </NativeSelect></FieldShell>
      <DecimalInput label="套表填报的本年收缴率" value={reported} onChange={setReported} unit="%" placeholder="可不填"
        help="填了会列出明细算出的数和填报数差几个百分点。" />
    </div></fieldset>
    <div className="analysis-actions">
      <Button type="button" disabled={disabled || Boolean(blocked)} onClick={() => onRun({
        receivable: chosen.receivable, receipt: chosen.receipt, ...(chosen.property ? { property: chosen.property } : {}),
        as_of: asOf, group_by: group ? [group] : [], ...(reportedRate ? { reported: { collection_rate_current: reportedRate } } : {}),
      })}><Calculator size={14} aria-hidden />计算收缴率</Button>
      {running ? <span role="status" className="analysis-note"><WaitLoop />正在计算，几十万行要十几秒…</span>
        : blocked ? <span className="analysis-note">{blocked}</span> : null}
    </div>
  </article>;
}

const CALIBER_STATUS: Record<CollectionRun['caliber']['status'], string> = { confirmed: '已确认口径', default: '默认口径（未确认）', trial: '试算' };

function RunView({ taskId, run, runs, onPick }: { taskId: string; run: CollectionRun; runs: CollectionRunSummary[]; onPick(id: string): void }) {
  const { figures } = run.result;
  const [drill, setDrill] = useState<DrillFigure | null>(null);
  // 综合收缴率 counted over every receipt holds prepayments that name no bill: it does not come apart by bill.
  const apart = (figure: DrillFigure, rate: string | null) => rate != null
    && (figure !== 'collection_rate_total' || run.params.total_method === 'bounded') ? () => setDrill(figure) : undefined;
  const caliberText = run.caliber.status === 'confirmed' && run.caliber.version ? `已确认口径 · 第 ${run.caliber.version} 版` : CALIBER_STATUS[run.caliber.status];
  const groupLabel = GROUPS.find(([id]) => id === run.params.group_by[0])?.[1];
  const history = useMemo(() => [...runs].reverse(), [runs]);
  return <article className="analysis-billing-result" aria-label="收缴率结果">
    <div className="analysis-billing-caliber__head">
      <h4>结果 · 截至 {run.result.window.as_of}</h4>
      <Badge variant={run.caliber.status === 'trial' ? 'destructive' : run.caliber.status === 'confirmed' ? 'secondary' : 'outline'}>{caliberText}</Badge>
      {history.length > 1 ? <NativeSelect aria-label="计算记录" value={run.id} onChange={(event) => onPick(event.target.value)}>
        {history.map((row, index) => <option key={row.id} value={row.id}>
          第 {history.length - index} 次 · {when(row.created_at)} · {CALIBER_STATUS[row.caliber.status]}</option>)}
      </NativeSelect> : null}
    </div>
    {run.caliber.status === 'trial' ? <p className="analysis-note">这次和已确认口径不同的地方：{run.caliber.differs.map((key) => CALIBER_KEYS[key] ?? key).join('、')}。经理确认口径前，这些数只作参考。</p> : null}
    <p className="analysis-note">本年 {run.result.window.year_start} 起到 {run.result.window.as_of}；资料：{Object.values(run.inputs).map((input) => input?.name).filter(Boolean).join('、')}。</p>
    <div className="analysis-kpi-grid" aria-label="收缴率">
      <Kpi title="当期收缴率" rate={figures.collection_rate_current} rows={[['本年应收', figures.receivable], ['当期已收', figures.collected]]}
        onDrill={apart('collection_rate_current', figures.collection_rate_current)} />
      <Kpi title="清欠率" rate={figures.arrears_recovery_rate} rows={[['年初往年欠费', figures.arrears_opening], ['本年收回', figures.arrears_collected]]}
        onDrill={apart('arrears_recovery_rate', figures.arrears_recovery_rate)} />
      <Kpi title="综合收缴率" rate={figures.collection_rate_total} rows={[['未收合计', figures.outstanding], ['预收余额', figures.advance_balance]]}
        onDrill={apart('collection_rate_total', figures.collection_rate_total)} />
      <Kpi title="本月收缴率" rate={figures.collection_rate_month} rows={[['本月应收', figures.month_receivable], ['本月已收', figures.month_collected]]}
        onDrill={apart('collection_rate_month', figures.collection_rate_month)} />
    </div>
    {drill ? <BillingDrill key={drill} taskId={taskId} runId={run.id} figure={drill} onClose={() => setDrill(null)} /> : null}
    <dl className="analysis-billing-facts">
      <div><dt>减免率</dt><dd><Figure text={percent(figures.waiver_rate)} /></dd></div>
      <div><dt>减免额</dt><dd><Figure text={formatAmount(figures.waiver)} /></dd></div>
      <div><dt>交清的户</dt><dd>{figures.households_settled.toLocaleString('en-US')} / {figures.households.toLocaleString('en-US')}（<Figure text={percent(figures.household_rate)} />）</dd></div>
    </dl>
    {figures.reported?.collection_rate_current ? (() => {
      const row = figures.reported.collection_rate_current;
      return <p className="analysis-billing-reported">套表填报本年收缴率 <Figure text={percent(row.reported)} />，明细算出 <Figure text={percent(row.computed)} />，差{' '}
        <Figure text={`${row.difference_points ?? '—'} 个百分点`} />。{row.difference_points && row.difference_points !== '0.00' ? '看下面「收费系统标签和账期对不上」找原因。' : ''}</p>;
    })() : null}
    {run.result.related ? <p className="analysis-note">关联方（产权归属为{run.result.related.owners.join('、')}）：只算关联方的综合收缴率 {percent(run.result.related.only.collection_rate_total)}，{''
      }剔除关联方后 {percent(run.result.related.excluded.collection_rate_total)}。</p> : null}
    {run.result.groups?.length ? <div className="fnd-tablewrap"><table className="analysis-table analysis-billing-groups">
      <caption>按{groupLabel ?? run.params.group_by.join('、')}</caption>
      <thead><tr><th scope="col">{groupLabel}</th><th scope="col">本年应收</th><th scope="col">当期收缴率</th><th scope="col">清欠率</th><th scope="col">综合收缴率</th><th scope="col">减免率</th></tr></thead>
      <tbody>{run.result.groups.map((row) => <tr key={JSON.stringify(row.key)}>
        <th scope="row">{Object.values(row.key).map((value) => value ?? '（空）').join(' · ')}</th>
        <td><Figure text={formatAmount(row.figures.receivable)} /></td>
        <td><Figure text={percent(row.figures.collection_rate_current)} /></td>
        <td><Figure text={percent(row.figures.arrears_recovery_rate)} /></td>
        <td><Figure text={percent(row.figures.collection_rate_total)} /></td>
        <td><Figure text={percent(row.figures.waiver_rate)} /></td>
      </tr>)}</tbody>
    </table></div> : null}
    <Issues title="数据质量" issues={run.result.quality} empty="没有发现作废、冲红或对不上的行。" />
    {run.result.labels ? <Issues title="收费系统标签和账期对不上" issues={run.result.labels} empty="收费系统标的「当期」都落在本年账期里。" /> : null}
  </article>;
}

function Kpi({ title, rate, rows, onDrill }: { title: string; rate: string | null; rows: [string, string][]; onDrill?(): void }) {
  return <article className="analysis-kpi-card">
    <span className="analysis-kpi-title">{title}</span>
    <strong aria-label={title}><Figure text={percent(rate)} /></strong>
    <dl className="analysis-kpi-list">{rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd><Figure text={formatAmount(value)} /></dd></div>)}</dl>
    {onDrill ? <Button variant="link" type="button" className="analysis-billing-drill__open" aria-label={`往下拆${title}`} onClick={onDrill}>
      往下拆</Button> : null}
  </article>;
}

function Issues({ title, issues, empty }: { title: string; issues: CollectionIssue[]; empty: string }) {
  return <section className="analysis-billing-issues" aria-label={title}>
    <h5>{title}</h5>
    {issues.length ? <ul>{issues.map((issue: CollectionIssue) => <li key={issue.code}>
      <details className="analysis-details"><DisclosureSummary tone="quiet">
        {ISSUES[issue.code] ?? issue.code}：{issue.rows.toLocaleString('en-US')} 行{issue.amount !== '0.00' ? <>，<Figure text={formatAmount(issue.amount)} /> 元</> : null}
      </DisclosureSummary>
        <p className="analysis-note">先看这几行：{issue.lines.join('；')}{issue.rows > issue.lines.length ? ' 等' : ''}</p>
      </details></li>)}</ul> : <p className="analysis-note">{empty}</p>}
  </section>;
}
