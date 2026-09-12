import { useEffect, useState } from 'react';
import { AlertTriangle, Check, FileSpreadsheet, RotateCcw, X } from 'lucide-react';
import { bridge, type Answer } from '../../bridge.js';
import { Button } from '../../components/ui/button.js';
import { Input } from '../../components/ui/input.js';

/** One column of a sheet, as the engine read it. */
export interface ProposedColumn {
  letter: string;
  header: string;
  display: string;
  role: string;
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
  scope_hints: { period: string; currency: string; unit: string };
  preview: { row: number; is_header: boolean; cells: { letter: string; text: string }[] }[];
  confidence: number;
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
}

const ROLE_LABELS: Record<string, string> = {
  account_code: '科目代码', account_name: '科目名称', management_account: '管理科目',
  category: '类别', direction: '方向', amount: '金额', debit: '借方', credit: '贷方',
  doc_id: '凭证号', line_id: '行号', date: '日期', summary: '摘要', period: '期间',
  currency: '币种', unit: '单位', organization: '组织', ledger: '账套', unknown: '未识别',
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
  'organization', 'ledger', 'unknown'];

function undecided(sheet: ProposedSheet): boolean {
  return sheet.amount_pairs.some((pair) => pair.primary && pair.direction.kind === 'undecided');
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

  useEffect(() => {
    setSheets(proposal.sheets);
    const next: Record<string, boolean> = {};
    for (const sheet of proposal.sheets) {
      if (sheet.decision === 'table' && !sheet.blocked_reason) next[sheet.sheet] = true;
    }
    setChosen(next);
  }, [proposal]);

  const tables = sheets.filter((sheet) => sheet.decision === 'table' && !sheet.blocked_reason);
  // A sheet the engine read as a table but cannot derive anything from. It is
  // shown with the headers it did read, and never offered: ticking it would
  // only produce a refusal she had no way to see coming.
  const setAside = sheets.filter((sheet) => sheet.blocked_reason !== null);
  const selected = tables.filter((sheet) => chosen[sheet.sheet]);
  const blocking = selected.filter(undecided);
  const locked = busy || working;

  function edit(name: string, change: (sheet: ProposedSheet) => ProposedSheet) {
    setSheets((current) => current.map((sheet) => (sheet.sheet === name ? change(sheet) : sheet)));
  }

  async function confirm() {
    const api = bridge(); if (!api?.financeCall) return;
    setWorking(true); setError('');
    try {
      unwrapAnswer(await api.financeCall(taskId, 'structure-proposal-confirm', {
        dataset_id: proposal.dataset_id, revision: proposal.revision, sheets: selected,
      }));
      await onSettled();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setWorking(false);
    }
  }

  if (proposal.structure_state === 'no_table') {
    return (
      <section className="fnd-card analysis-structure-card">
        <div className="analysis-section-heading">
          <h4><FileSpreadsheet size={15} strokeWidth={1.5} aria-hidden /> {datasetName}</h4>
        </div>
        <p className="analysis-note">这份文件里没有可以计算的表。每张表的判断如下。</p>
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
            </li>
          ))}
        </ul>
      </section>
    );
  }

  return (
    <section className="fnd-card analysis-structure-card">
      <div className="analysis-section-heading">
        <h4><FileSpreadsheet size={15} strokeWidth={1.5} aria-hidden /> {datasetName}</h4>
        <span className="analysis-note">确认表结构后才能计算</span>
      </div>
      {tables.map((sheet) => (
        <div key={sheet.sheet} className="analysis-structure-sheet">
          <label className="analysis-structure-sheet-name">
            <input type="checkbox" checked={chosen[sheet.sheet] ?? false} disabled={locked}
              aria-label={`采用 ${sheet.sheet}`}
              onChange={(event) => setChosen((current) => ({ ...current, [sheet.sheet]: event.target.checked }))} />
            <span className="fnd-title">{sheet.sheet}</span>
          </label>

          <div className="analysis-structure-field">
            <label htmlFor={`header-${sheet.sheet}`}>表头行</label>
            <Input id={`header-${sheet.sheet}`} type="number" min={1} disabled={locked}
              value={String(sheet.header_row ?? '')}
              onChange={(event) => edit(sheet.sheet, (current) => ({
                ...current, header_row: Number(event.target.value) || current.header_row,
              }))} />
          </div>
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
            <thead><tr><th scope="col">列</th><th scope="col">原表头</th><th scope="col">含义</th></tr></thead>
            <tbody>
              {sheet.columns.map((column) => (
                <tr key={column.letter}>
                  <th scope="row">{column.letter}</th>
                  <td>{column.display}</td>
                  <td>
                    <select aria-label={`${sheet.sheet} ${column.letter} 列含义`} disabled={locked}
                      value={column.role}
                      onChange={(event) => edit(sheet.sheet, (current) => ({
                        ...current,
                        columns: current.columns.map((item) => (item.letter === column.letter
                          ? { ...item, role: event.target.value } : item)),
                      }))}>
                      {ROLE_CHOICES.map((role) => <option key={role} value={role}>{ROLE_LABELS[role] ?? role}</option>)}
                    </select>
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
              <select id={`dir-${sheet.sheet}-${pair.id}`} disabled={locked}
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
              </select>
            </div>
          ))}

          {sheet.excluded_rows.length > 0 && (
            <details className="analysis-structure-excluded">
              <summary>不计入的行 {sheet.excluded_rows.length} 条</summary>
              <ul>
                {sheet.excluded_rows.map((row) => (
                  <li key={row.row}>
                    <label>
                      <input type="checkbox" checked disabled={locked}
                        aria-label={`第 ${row.row} 行不计入`}
                        onChange={() => edit(sheet.sheet, (current) => ({
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
            标题读到：期间 {sheet.scope_hints.period || '未声明'} · 单位 {sheet.scope_hints.unit || '未声明'} · 币种 {sheet.scope_hints.currency || '未声明'}
          </p>
          {undecided(sheet) && (
            <p role="status" className="analysis-structure-blocked">
              <AlertTriangle size={14} strokeWidth={1.5} aria-hidden /> 这张表的借贷方向还没定，选定后才能确认。
            </p>
          )}
        </div>
      ))}

      {setAside.length > 0 && (
        <details className="analysis-structure-excluded">
          <summary>不能确认的工作表 {setAside.length} 张</summary>
          <ul>
            {setAside.map((sheet) => (
              <li key={sheet.sheet}>
                {sheet.sheet} · {EXCLUSION_LABELS[sheet.blocked_reason ?? ''] ?? sheet.blocked_reason}
                {unreadHeaders(sheet).length > 0 && (
                  <span className="analysis-note">读到的列：{unreadHeaders(sheet).join('、')}</span>
                )}
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

  async function settle(command: 'structure-acknowledge' | 'structure-reject' | 'structure-withdraw') {
    const api = bridge(); if (!api?.financeCall) return;
    setWorking(command); setError('');
    try {
      unwrapAnswer(await api.financeCall(taskId, command, { id: confirmation.id }));
      await onSettled();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setWorking('');
    }
  }

  return (
    <section className="fnd-card analysis-structure-card">
      <div className="analysis-section-heading">
        <h4><FileSpreadsheet size={15} strokeWidth={1.5} aria-hidden /> {datasetName}</h4>
        <span className="analysis-note">待经理追认</span>
      </div>
      <p className="analysis-note">
        {fromTemplate ? '这份文件的表结构套用了上次记住的结构，还没有经过你确认。' : '助手代你确认了这份文件的表结构，还没有经过你追认。'}
        表已经可以计算，追认只是把这条记录归到你名下。
      </p>
      {error && <p role="alert" className="analysis-structure-error">{error}</p>}
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

function unwrapAnswer<T>(answer: Answer<T>): T {
  if (!answer.ok) throw new Error(answer.message);
  return answer.value;
}
