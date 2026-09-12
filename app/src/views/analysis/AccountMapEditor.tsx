import { useMemo } from 'react';
import { Plus, X } from 'lucide-react';
import { Button } from '../../components/ui/button.js';
import { Input } from '../../components/ui/input.js';
import { Textarea } from '../../components/ui/textarea.js';

/** The three the engine knows. Chinese account names map onto these. */
const ACCOUNTS: { value: string; label: string }[] = [
  { value: 'revenue', label: '收入 revenue' },
  { value: 'cost', label: '成本 cost' },
  { value: 'expense', label: '费用 expense' },
];

export interface AccountMapRow {
  account_code: string;
  management_account: string;
}

function parse(json: string): AccountMapRow[] | null {
  try {
    const value = JSON.parse(json);
    if (!Array.isArray(value)) return null;
    return value.map((row) => ({
      account_code: String((row as AccountMapRow)?.account_code ?? ''),
      management_account: String((row as AccountMapRow)?.management_account ?? ''),
    }));
  } catch {
    return null;
  }
}

const serialize = (rows: AccountMapRow[]) => JSON.stringify(rows);

/**
 * Which ledger accounts count as revenue, cost and expense, edited as rows.
 *
 * It was a JSON textarea, so the one step that decides whether the month's
 * figures come out at all was the one step a finance manager could not take
 * without an assistant to write the array for her.
 */
export function AccountMapEditor({ value, disabled, onChange }: {
  value: string;
  disabled?: boolean;
  onChange(json: string): void;
}) {
  const rows = useMemo(() => parse(value), [value]);

  if (rows === null) {
    return (
      <div className="analysis-account-map">
        <p role="alert" className="analysis-message analysis-message--error">
          映射不是合法的 JSON 数组，先改好下面这段再用表格编辑。
        </p>
        <Textarea className="analysis-code" rows={4} value={value} disabled={disabled}
          onChange={(event) => onChange(event.target.value)} />
      </div>
    );
  }

  const edit = (index: number, change: Partial<AccountMapRow>) =>
    onChange(serialize(rows.map((row, at) => (at === index ? { ...row, ...change } : row))));

  return (
    <div className="analysis-account-map">
      <table className="analysis-account-map-table">
        <caption className="analysis-note">
          科目代码写原表里的写法；管理科目只有收入、成本、费用三种，其它科目不用列。
        </caption>
        <thead>
          <tr><th scope="col">科目代码</th><th scope="col">管理科目</th><th scope="col"><span className="sr-only">删除</span></th></tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>
              <td>
                <Input aria-label={`第 ${index + 1} 行科目代码`} value={row.account_code} disabled={disabled}
                  onChange={(event) => edit(index, { account_code: event.target.value })} />
              </td>
              <td>
                <select aria-label={`第 ${index + 1} 行管理科目`} value={row.management_account} disabled={disabled}
                  onChange={(event) => edit(index, { management_account: event.target.value })}>
                  <option value="">未选</option>
                  {ACCOUNTS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
                </select>
              </td>
              <td>
                <Button variant="outline" type="button" disabled={disabled}
                  aria-label={`删除第 ${index + 1} 行`}
                  onClick={() => onChange(serialize(rows.filter((_, at) => at !== index)))}>
                  <X size={15} strokeWidth={1.5} aria-hidden />
                </Button>
              </td>
            </tr>
          ))}
          {!rows.length && (
            <tr><td colSpan={3} className="analysis-note">还没有映射行。</td></tr>
          )}
        </tbody>
      </table>
      <Button variant="outline" type="button" disabled={disabled}
        onClick={() => onChange(serialize([...rows, { account_code: '', management_account: '' }]))}>
        <Plus size={15} strokeWidth={1.5} aria-hidden />加一行
      </Button>
      <details className="analysis-details">
        <summary>高级：直接改 JSON</summary>
        <Textarea className="analysis-code" rows={4} value={value} disabled={disabled}
          onChange={(event) => onChange(event.target.value)} />
      </details>
    </div>
  );
}
