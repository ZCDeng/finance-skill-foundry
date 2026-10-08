import { useEffect, useState } from 'react';
import { AlertTriangle, Check, RotateCcw, Table2, X } from 'lucide-react';
import { bridge } from '../../bridge.js';
import { Button } from '../../components/ui/button.js';
import { WaitLoop } from '../../components/WaitLoop.js';
import { Input } from '../../components/ui/input.js';
import { scenarioLabel } from './glossary.js';
import { errorText, unwrap } from './shared.js';
import { PeriodWords } from '../../components/PeriodWords.js';
import { NativeSelect } from '../../components/ui/native-select.js';
import { Checkbox } from '../../components/ui/checkbox.js';
import { DisclosureSummary } from '../../components/Disclosure.js';

/** One column of a sheet, as the engine read it. */
export interface ProposedColumn {
  letter: string;
  source_letter?: string;
  header: string;
  display: string;
  stable_name?: string;
  role: string;
  include?: boolean;
  exclusion_reason?: string;
  numeric?: boolean;
  pair: string | null;
  direction: string | null;
}

export interface ProposedPair {
  id: string;
  label: string;
  debit: string;
  credit: string;
  primary: boolean;
  direction: { kind: string; column?: string; side?: string };
}

export interface ProposedTableBlock {
  id: string;
  header_row: number;
  start_row: number;
  end_row: number;
  start_column: string;
  end_column: string;
  score?: number;
  columns?: ProposedColumn[];
  amount_pairs?: ProposedPair[];
  excluded_rows?: { row: number; text: string; reason: string }[];
  fill_down_columns?: string[];
  numeric_coverage?: ProposedSheet['numeric_coverage'];
  preview?: ProposedSheet['preview'];
  confidence?: number;
  blocked_reason?: string | null;
}

export interface ProposedSheet {
  sheet: string;
  decision: 'table' | 'excluded';
  reason: string | null;
  blocked_reason: string | null;
  header_row: number | null;
  title_rows: number[];
  columns: ProposedColumn[];
  amount_pairs: ProposedPair[];
  excluded_rows: { row: number; text: string; reason: string }[];
  fill_down_columns: string[];
  scope_hints: {
    period: string;
    currency: string;
    unit: string;
    granularity?: string;
    as_of_date?: string;
    scenario?: string;
    forecast?: string;
  };
  table_blocks?: ProposedTableBlock[];
  selected_block_id?: string | null;
  start_row?: number;
  end_row?: number;
  start_column?: string;
  end_column?: string;
  numeric_coverage?: {
    numeric_columns_total: number;
    numeric_columns_included: number;
    numeric_columns_excluded: number;
    retained_cell_coverage?: number;
    metadata_only?: boolean;
  };
  preview: { row: number; is_header: boolean; cells: { letter: string; text: string }[] }[];
  confidence: number;
  /** A KPI board or other presentation page that still has a table on it: set aside, but hers to adopt. */
  adoptable?: boolean;
}

export interface StructureProposal {
  id: string;
  dataset_id: string;
  revision: number;
  structure_state: string;
  sheets: ProposedSheet[];
  template_matches: { sheet: string; template_id: string; score: number; auto_apply: boolean }[];
}

interface Confirmation {
  id: string;
  dataset_id: string;
  source: string;
  state: string;
  parent_id: string | null;
  sheets?: { sheet: string; decision?: string; reason?: string | null }[];
}

const ROLE_LABELS: Record<string, string> = {
  account_code: '科目代码', account_name: '科目名称', management_account: '管理科目',
  category: '类别', direction: '方向', amount: '金额', debit: '借方', credit: '贷方',
  doc_id: '凭证号', line_id: '行号', date: '日期', summary: '摘要', period: '期间',
  currency: '币种', unit: '单位', organization: '组织', ledger: '账套',
  invoice_id: '发票号', due_date: '到期日', issue_date: '开票日期', effective_date: '回款日期',
  product: '业态/产品', quantity: '数量', price: '单价', posting_status: '过账状态', status: '状态',
  scenario: '情景', kind: '收付类型', event_id: '流水号', unknown: '未识别',
};
const EXCLUSION_LABELS: Record<string, string> = {
  section: '分节标题', subtotal: '小计或合计', note: '说明',
  presentation_sheet: '封面、看板或对标页', no_header: '没有找到表头',
  empty_sheet: '空白工作表', too_large: '超出行列上限',
  unreadable_columns: '是一张表，但没有一列能识别',
};

// An unrecognised header is only actionable if she can see which one it was.
function unreadHeaders(sheet: ProposedSheet): string[] {
  if (sheet.blocked_reason !== 'unreadable_columns') return [];
  return sheet.columns.map((column) => column.display || column.header).filter(Boolean);
}
const ROLE_CHOICES = ['account_code', 'account_name', 'management_account', 'category', 'direction',
  'amount', 'debit', 'credit', 'doc_id', 'line_id', 'date', 'summary', 'period', 'currency', 'unit',
  'organization', 'ledger', 'invoice_id', 'due_date', 'issue_date', 'effective_date', 'product', 'quantity',
  'price', 'posting_status', 'status', 'scenario', 'kind', 'event_id', 'unknown'];

function undecided(sheet: ProposedSheet): boolean {
  return sheet.amount_pairs.some((pair) => pair.primary && pair.direction.kind === 'undecided');
}

function hasIncludedColumn(sheet: ProposedSheet): boolean {
  return sheet.columns.some((column) => column.include !== false || column.role === 'debit' || column.role === 'credit');
}

function applyBlock(sheet: ProposedSheet, blockId: string): ProposedSheet {
  const block = sheet.table_blocks?.find((item) => item.id === blockId);
  if (!block) return { ...sheet, selected_block_id: blockId };
  return {
    ...sheet,
    selected_block_id: block.id,
    header_row: block.header_row,
    start_row: block.start_row,
    end_row: block.end_row,
    start_column: block.start_column,
    end_column: block.end_column,
    columns: block.columns ?? sheet.columns,
    amount_pairs: block.amount_pairs ?? sheet.amount_pairs,
    excluded_rows: block.excluded_rows ?? sheet.excluded_rows,
    fill_down_columns: block.fill_down_columns ?? sheet.fill_down_columns,
    numeric_coverage: block.numeric_coverage ?? sheet.numeric_coverage,
    preview: block.preview ?? sheet.preview,
    confidence: block.confidence ?? sheet.confidence,
    blocked_reason: block.blocked_reason ?? null,
  };
}

function blockLabel(block: ProposedTableBlock, index: number): string {
  const area = `${block.start_column}${block.start_row}:${block.end_column}${block.end_row}`;
  const header = block.header_row ? `表头第 ${block.header_row} 行` : '表头未定';
  return `区域 ${index + 1} · ${area} · ${header}`;
}

function markRepairable(sheet: ProposedSheet): ProposedSheet {
  return { ...sheet, blocked_reason: null, reason: null };
}

/**
 * The card the manager answers before a workbook becomes calculable.
 *
 * It shows what the engine made of each sheet and lets her correct it: which row
 * is the header (with the rows around it, so the number is not a guess), what
 * each column is, which side of a 借/贷 pair carries the amount, and which rows
 * are sections or subtotals rather than data. Nothing is calculated until she
 * answers, and a sheet she excludes never blocks the others.
 */
export function StructureProposalCard({ taskId, datasetName, proposal, busy, onSettled }: {
  taskId: string;
  datasetName: string;
  proposal: StructureProposal;
  busy: boolean;
  onSettled(): Promise<void> | void;
}) {
  const [sheets, setSheets] = useState<ProposedSheet[]>(proposal.sheets);
  const [chosen, setChosen] = useState<Record<string, boolean>>({});
  const [working, setWorking] = useState(false);
  const [error, setError] = useState('');

  // Only another proposal or a new revision of it starts the form over. The page reads
  // the task back every 5 seconds and may hand over an equal proposal as a new object;
  // that must not wipe what the manager has changed but not yet confirmed.
  useEffect(() => {
    setSheets(proposal.sheets);
    const next: Record<string, boolean> = {};
    for (const sheet of proposal.sheets) {
      if (sheet.decision === 'table') next[sheet.sheet] = true;
    }
    setChosen(next);
  }, [proposal.id, proposal.revision]);

  const tables = sheets.filter((sheet) => sheet.decision === 'table');
  const setAside = sheets.filter((sheet) => sheet.decision !== 'table');
  const selected = tables.filter((sheet) => chosen[sheet.sheet]);
  const blocking = selected.filter((sheet) => undecided(sheet) || !hasIncludedColumn(sheet));
  const locked = busy || working;

  function edit(name: string, change: (sheet: ProposedSheet) => ProposedSheet) {
    setSheets((current) => current.map((sheet) => (sheet.sheet === name ? change(sheet) : sheet)));
  }

  // A set-aside KPI board comes back as a table she can review column by column like any other.
  function adopt(name: string) {
    edit(name, (sheet) => ({ ...sheet, decision: 'table', reason: 'adopted_presentation_sheet', blocked_reason: null }));
    setChosen((current) => ({ ...current, [name]: true }));
  }

  function adoptButton(sheet: ProposedSheet) {
    if (!sheet.adoptable) return null;
    return (
      <Button type="button" variant="outline" size="sm" disabled={locked} onClick={() => adopt(sheet.sheet)}>
        <Table2 size={14} strokeWidth={1.5} aria-hidden />当作数据表
      </Button>
    );
  }

  async function confirm() {
    const api = bridge(); if (!api?.financeCall) return;
    setWorking(true); setError('');
    try {
      unwrap(await api.financeCall(taskId, 'structure-proposal-confirm', {
        dataset_id: proposal.dataset_id, revision: proposal.revision, sheets: selected,
      }));
      await onSettled();
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      setWorking(false);
    }
  }

  if (proposal.structure_state === 'no_table' && tables.length === 0) {
    return (
      <section className="analysis-structure-card">
        {/* Opened under the file's own row, which already names it: the heading is for screen readers. */}
        <h4 className="sr-only">{datasetName}</h4>
        <p className="analysis-note">
          {setAside.some((sheet) => sheet.adoptable)
            ? '这份文件里没有直接可以计算的表；看板页上的表可以点「当作数据表」采用。每张表的判断如下。'
            : '这份文件里没有可以计算的表。每张表的判断如下。'}
        </p>
        <ul className="analysis-structure-reasons">
          {setAside.map((sheet) => (
            <li key={sheet.sheet}>
              <span className="fnd-title">{sheet.sheet}</span>
              <span className="analysis-note">
                {EXCLUSION_LABELS[sheet.blocked_reason ?? ''] ?? sheet.blocked_reason}
              </span>
              {unreadHeaders(sheet).length > 0 && (
                <span className="analysis-note">读到的列：{unreadHeaders(sheet).join('、')}</span>
              )}
              {adoptButton(sheet)}
            </li>
          ))}
        </ul>
      </section>
    );
  }

  return (
    <section className="analysis-structure-card">
      <div className="analysis-section-heading">
        <h4 className="sr-only">{datasetName}</h4>
        <span className="analysis-note">确认表结构后才能计算</span>
      </div>
      {tables.map((sheet) => (
        <div key={sheet.sheet} className="analysis-structure-sheet">
          <label className="analysis-structure-sheet-name">
            <Checkbox checked={chosen[sheet.sheet] ?? false} disabled={locked}
              aria-label={`采用 ${sheet.sheet}`}
              onCheckedChange={(state) => setChosen((current) => ({ ...current, [sheet.sheet]: state === true }))} />
            <span className="fnd-title">{sheet.sheet}</span>
          </label>

          <div className="analysis-structure-field">
            <label htmlFor={`header-${sheet.sheet}`}>表头行</label>
            <Input id={`header-${sheet.sheet}`} type="number" min={1} disabled={locked}
              value={String(sheet.header_row ?? '')}
              onChange={(event) => edit(sheet.sheet, (current) => ({
                ...markRepairable(current), header_row: Number(event.target.value) || current.header_row,
              }))} />
          </div>
          {sheet.table_blocks && sheet.table_blocks.length > 0 && (
            <div className="analysis-structure-field">
              <label htmlFor={`block-${sheet.sheet}`}>表块</label>
              <NativeSelect id={`block-${sheet.sheet}`} disabled={locked}
                value={sheet.selected_block_id ?? ''}
                onChange={(event) => edit(sheet.sheet, (current) => applyBlock(current, event.target.value))}>
                {sheet.table_blocks.map((block, index) => (
                  <option key={block.id} value={block.id}>
                    {blockLabel(block, index)}
                  </option>
                ))}
              </NativeSelect>
            </div>
          )}
          <div className="analysis-structure-field">
            <label htmlFor={`start-row-${sheet.sheet}`}>起始行</label>
            <Input id={`start-row-${sheet.sheet}`} type="number" min={1} disabled={locked}
              value={String(sheet.start_row ?? sheet.header_row ?? '')}
              onChange={(event) => edit(sheet.sheet, (current) => ({
                ...markRepairable(current), start_row: Number(event.target.value) || current.start_row,
              }))} />
          </div>
          <div className="analysis-structure-field">
            <label htmlFor={`end-row-${sheet.sheet}`}>结束行</label>
            <Input id={`end-row-${sheet.sheet}`} type="number" min={1} disabled={locked}
              value={String(sheet.end_row ?? '')}
              onChange={(event) => edit(sheet.sheet, (current) => ({
                ...markRepairable(current), end_row: Number(event.target.value) || current.end_row,
              }))} />
          </div>
          <div className="analysis-structure-field">
            <label htmlFor={`start-col-${sheet.sheet}`}>起始列</label>
            <Input id={`start-col-${sheet.sheet}`} disabled={locked}
              value={sheet.start_column ?? ''}
              onChange={(event) => edit(sheet.sheet, (current) => ({
                ...markRepairable(current), start_column: event.target.value.toUpperCase(),
              }))} />
          </div>
          <div className="analysis-structure-field">
            <label htmlFor={`end-col-${sheet.sheet}`}>结束列</label>
            <Input id={`end-col-${sheet.sheet}`} disabled={locked}
              value={sheet.end_column ?? ''}
              onChange={(event) => edit(sheet.sheet, (current) => ({
                ...markRepairable(current), end_column: event.target.value.toUpperCase(),
              }))} />
          </div>
          {sheet.numeric_coverage && (
            <p className="analysis-note">
              数值列覆盖：纳入 {sheet.numeric_coverage.numeric_columns_included}/{sheet.numeric_coverage.numeric_columns_total}
              {sheet.numeric_coverage.metadata_only ? ' · 仅元数据表' : ''}
            </p>
          )}
          <table className="analysis-structure-preview">
            <caption className="analysis-note">原件第 {sheet.preview[0]?.row ?? 1} 行起</caption>
            <tbody>
              {sheet.preview.map((row) => (
                <tr key={row.row} className={row.row === sheet.header_row ? 'is-header' : undefined}>
                  <th scope="row">{row.row}</th>
                  {row.cells.map((cell) => <td key={cell.letter}>{cell.text}</td>)}
                </tr>
              ))}
            </tbody>
          </table>

          <table className="analysis-structure-columns">
            <thead><tr><th scope="col">纳入</th><th scope="col">列</th><th scope="col">原表头</th><th scope="col">含义</th><th scope="col">排除原因</th></tr></thead>
            <tbody>
              {sheet.columns.map((column) => (
                <tr key={column.letter}>
                  <td>
                    <Checkbox checked={column.include !== false} disabled={locked}
                      aria-label={`${sheet.sheet} ${column.letter} 列纳入`}
                      onCheckedChange={(state) => edit(sheet.sheet, (current) => ({
                        ...markRepairable(current),
                        columns: current.columns.map((item) => (item.letter === column.letter
                          ? { ...item, include: state === true } : item)),
                      }))} />
                  </td>
                  <th scope="row">{column.letter}{column.numeric ? ' · 数值' : ''}</th>
                  <td>{column.display}</td>
                  <td>
                    <NativeSelect aria-label={`${sheet.sheet} ${column.letter} 列含义`} disabled={locked}
                      value={column.role}
                      onChange={(event) => edit(sheet.sheet, (current) => ({
                        ...markRepairable(current),
                        columns: current.columns.map((item) => (item.letter === column.letter
                          ? { ...item, role: event.target.value } : item)),
                      }))}>
                      {ROLE_CHOICES.map((role) => <option key={role} value={role}>{ROLE_LABELS[role] ?? role}</option>)}
                    </NativeSelect>
                  </td>
                  <td>
                    <Input aria-label={`${sheet.sheet} ${column.letter} 列排除原因`} disabled={locked || column.include !== false}
                      value={column.exclusion_reason ?? ''}
                      onChange={(event) => edit(sheet.sheet, (current) => ({
                        ...markRepairable(current),
                        columns: current.columns.map((item) => (item.letter === column.letter
                          ? { ...item, exclusion_reason: event.target.value } : item)),
                      }))} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {sheet.amount_pairs.map((pair) => (
            <div key={pair.id} className="analysis-structure-field">
              <label htmlFor={`dir-${sheet.sheet}-${pair.id}`}>
                {pair.label || '借贷'} 哪一侧是金额{pair.primary ? '（主）' : ''}
              </label>
              <NativeSelect id={`dir-${sheet.sheet}-${pair.id}`} disabled={locked}
                value={pair.direction.kind === 'fixed' ? `fixed:${pair.direction.side}` : pair.direction.kind}
                onChange={(event) => edit(sheet.sheet, (current) => ({
                  ...current,
                  amount_pairs: current.amount_pairs.map((item) => (item.id === pair.id
                    ? { ...item, direction: directionFrom(event.target.value, item.direction) } : item)),
                }))}>
                <option value="undecided">未定，请选择</option>
                <option value="by_category">按科目类别</option>
                <option value="by_direction_column">按方向列</option>
                <option value="by_populated_side">按有值的一侧</option>
                <option value="fixed:debit">一律借方</option>
                <option value="fixed:credit">一律贷方</option>
              </NativeSelect>
            </div>
          ))}

          {sheet.excluded_rows.length > 0 && (
            <details className="analysis-structure-excluded">
              <DisclosureSummary>不计入的行 {sheet.excluded_rows.length} 条</DisclosureSummary>
              <ul>
                {sheet.excluded_rows.map((row) => (
                  <li key={row.row}>
                    <label>
                      <Checkbox checked disabled={locked}
                        aria-label={`第 ${row.row} 行不计入`}
                        onCheckedChange={() => edit(sheet.sheet, (current) => ({
                          ...current,
                          excluded_rows: current.excluded_rows.filter((item) => item.row !== row.row),
                        }))} />
                      第 {row.row} 行 · {EXCLUSION_LABELS[row.reason] ?? row.reason} · {row.text}
                    </label>
                  </li>
                ))}
              </ul>
            </details>
          )}

          {sheet.fill_down_columns.length > 0 && (
            <p className="analysis-note">向下填充：{sheet.fill_down_columns.join('、')} 列只在每组首行有值。</p>
          )}
          <p className="analysis-note">
            标题读到：期间 {sheet.scope_hints.period ? <PeriodWords value={sheet.scope_hints.period} /> : '未声明'} · 单位 {sheet.scope_hints.unit || '未声明'} · 币种 {sheet.scope_hints.currency || '未声明'}
            {sheet.scope_hints.granularity ? ` · 粒度 ${sheet.scope_hints.granularity}` : ''}
            {sheet.scope_hints.as_of_date ? ` · 基准日 ${sheet.scope_hints.as_of_date}` : ''}
            {sheet.scope_hints.scenario ? ` · 情景 ${scenarioLabel(sheet.scope_hints.scenario)}` : ''}
            {sheet.scope_hints.forecast ? ` · 预测 ${sheet.scope_hints.forecast}` : ''}
          </p>
          {undecided(sheet) && (
            <p role="status" className="analysis-structure-blocked">
              <AlertTriangle size={14} strokeWidth={1.5} aria-hidden /> 这张表的借贷方向还没定，选定后才能确认。
            </p>
          )}
          {!hasIncludedColumn(sheet) && (
            <p role="status" className="analysis-structure-blocked">
              <AlertTriangle size={14} strokeWidth={1.5} aria-hidden /> 至少保留一列，或取消采用这张表。
            </p>
          )}
        </div>
      ))}

      {setAside.length > 0 && (
        <details className="analysis-structure-excluded">
          <DisclosureSummary>暂不计算的工作表 {setAside.length} 张</DisclosureSummary>
          <ul>
            {setAside.map((sheet) => (
              <li key={sheet.sheet}>
                {sheet.sheet} · {EXCLUSION_LABELS[sheet.blocked_reason ?? ''] ?? sheet.blocked_reason}
                {unreadHeaders(sheet).length > 0 && (
                  <span className="analysis-note">读到的列：{unreadHeaders(sheet).join('、')}</span>
                )}
                {adoptButton(sheet)}
              </li>
            ))}
          </ul>
        </details>
      )}

      {error && <p role="alert" className="analysis-structure-error">{error}</p>}
      <div className="analysis-structure-actions">
        <Button type="button" disabled={locked || selected.length === 0 || blocking.length > 0}
          onClick={() => void confirm()}>
          <Check size={15} strokeWidth={1.5} aria-hidden />确认表结构
        </Button>
        {working && <span role="status" className="analysis-note"><WaitLoop />正在按确认的结构整理数据…</span>}
        {blocking.length > 0 && (
          <span className="analysis-note">先为 {blocking.map((sheet) => sheet.sheet).join('、')} 选定借贷方向。</span>
        )}
      </div>
    </section>
  );
}

function directionFrom(value: string, current: ProposedPair['direction']): ProposedPair['direction'] {
  if (value.startsWith('fixed:')) return { kind: 'fixed', side: value.slice('fixed:'.length) };
  if (value === 'by_category' || value === 'by_direction_column') {
    return { kind: value, column: current.column };
  }
  return { kind: value };
}

/** The acknowledge / reject / withdraw strip for a structure somebody else settled. */
export function StructurePendingStrip({ taskId, datasetName, confirmation, busy, onSettled }: {
  taskId: string;
  datasetName: string;
  confirmation: Confirmation;
  busy: boolean;
  onSettled(): Promise<void> | void;
}) {
  const [working, setWorking] = useState('');
  const [error, setError] = useState('');
  const locked = busy || Boolean(working);
  const fromTemplate = confirmation.source === 'template';
  // A presentation page taken into calculation by someone else is the one thing here she must see by name.
  const adopted = (confirmation.sheets ?? [])
    .filter((sheet) => sheet.decision === 'table' && sheet.reason === 'adopted_presentation_sheet')
    .map((sheet) => sheet.sheet);

  async function settle(command: 'structure-acknowledge' | 'structure-reject' | 'structure-withdraw') {
    const api = bridge(); if (!api?.financeCall) return;
    setWorking(command); setError('');
    try {
      unwrap(await api.financeCall(taskId, command, { id: confirmation.id }));
      await onSettled();
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      setWorking('');
    }
  }

  return (
    <section className="analysis-structure-card">
      <div className="analysis-section-heading">
        <h4 className="sr-only">{datasetName}</h4>
        <span className="analysis-note">待经理追认</span>
      </div>
      <p className="analysis-note">
        {fromTemplate ? '这份文件的表结构套用了上次记住的结构，还没有经过你确认。' : '助手代你确认了这份文件的表结构，还没有经过你追认。'}
        表已经可以计算，追认只是把这条记录归到你名下。
      </p>
      {adopted.length > 0 && (
        <p role="status" className="analysis-structure-blocked">
          <AlertTriangle size={14} strokeWidth={1.5} aria-hidden />
          {adopted.join('、')} 原本是看板或封面页，这次当作数据表计算了；不该算的话请{fromTemplate ? '撤销套用' : '拒绝'}。
        </p>
      )}
      {error && <p role="alert" className="analysis-structure-error">{error}</p>}
      {working && <p role="status" className="analysis-note"><WaitLoop />正在保存你的决定…</p>}
      <div className="analysis-structure-actions">
        <Button type="button" disabled={locked} onClick={() => void settle('structure-acknowledge')}>
          <Check size={15} strokeWidth={1.5} aria-hidden />追认
        </Button>
        <Button type="button" variant="outline" disabled={locked}
          onClick={() => void settle(fromTemplate ? 'structure-withdraw' : 'structure-reject')}>
          {fromTemplate
            ? <><RotateCcw size={15} strokeWidth={1.5} aria-hidden />撤销套用</>
            : <><X size={15} strokeWidth={1.5} aria-hidden />拒绝</>}
        </Button>
      </div>
    </section>
  );
}
