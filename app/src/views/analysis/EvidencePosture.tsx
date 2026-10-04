import { CircleAlert, CircleCheck, CircleDashed, CircleHelp, TriangleAlert } from 'lucide-react';
import { Badge } from '../../components/ui/badge.js';
import { HelpLink } from '../guide/GuideHub.js';
import {
  countSummary, evidenceLabelText, postureText, PROBLEM_LABELS, reasonText,
  type EvidenceLabelEntry, type EvidencePosture,
} from './evidenceLabels.js';

const BASIS_WORDS: Record<string, string> = {
  calculation: '计算结果', source_fact: '来源事实', external_reference: '外部资料',
  user_assumption: '用户假设', professional_judgment: '专业判断',
};

function cellWords(key: NonNullable<EvidenceLabelEntry['key']>): string {
  return typeof key.row === 'number' ? `计算结果第 ${key.row + 1} 行${key.column ? ` · ${key.column}` : ''}` : '';
}

/** Which claim, fact or record a label is about, in the words the draft screens use. */
export function evidenceSubject(entry: EvidenceLabelEntry, index: number): string {
  const key = entry.key ?? {};
  const cell = cellWords(key);
  switch (key.kind) {
    case 'claim': {
      const basis = key.basis ? BASIS_WORDS[key.basis] ?? '' : '';
      const where = cell || (typeof key.paragraph === 'number' ? `资料第 ${key.paragraph} 段` : '');
      return [`引用 ${Number(key.claim_index ?? index) + 1}`, basis, where].filter(Boolean).join(' · ');
    }
    case 'fact': return cell ? `事实 · ${cell}` : '事实（已不在当前计算结果里）';
    case 'location': return `要求定位 · ${cell}`;
    case 'requirement': return '分析要求';
    case 'assertion': return '一致性说法';
    case 'revision': return `修订比较${key.column ? ` · ${key.column}` : ''}`;
    case 'number': return `正文数字「${key.text ?? ''}」`;
    default: return '依据';
  }
}

/**
 * One label as a small chip. A problem label (矛盾、缺必需、过期) uses the warning colour, an icon and
 * its reason in words; the others carry the reason as a tooltip and for screen readers.
 */
export function EvidenceLabelChip({ entry }: { entry?: EvidenceLabelEntry }) {
  if (!entry) return null;
  const code = entry.label ?? 'unknown';
  const problem = PROBLEM_LABELS.has(code);
  const text = evidenceLabelText(code, entry.text);
  const base = entry.base_label && entry.base_label !== code ? evidenceLabelText(entry.base_label) : '';
  const why = reasonText(entry.reasons);
  return <span className="analysis-evidence-chip">
    <Badge variant={problem ? 'destructive' : 'outline'} data-label={code} title={why || undefined}>
      {problem ? <TriangleAlert size={12} strokeWidth={1.5} aria-hidden /> : null}
      <span><span className="sr-only">证据标签：</span>{text}{base ? ` · 原依据 ${base}` : ''}</span>
    </Badge>
    {why ? problem ? <span className="analysis-evidence-reason">{why}</span> : <span className="sr-only">{why}</span> : null}
  </span>;
}

function PostureIcon({ level }: { level?: string }) {
  if (level === 'unsupported') return <TriangleAlert size={15} strokeWidth={1.5} aria-hidden />;
  if (level === 'decision_grade') return <CircleCheck size={15} strokeWidth={1.5} aria-hidden />;
  if (level === 'preliminary') return <CircleDashed size={15} strokeWidth={1.5} aria-hidden />;
  if (level === 'assumption_led') return <CircleAlert size={15} strokeWidth={1.5} aria-hidden />;
  return <CircleHelp size={15} strokeWidth={1.5} aria-hidden />;
}

/**
 * 证据等级: how much the cited evidence can bear. It is a classification of the evidence, kept apart
 * from the checks and statuses above it, and it never says the manager approved anything.
 */
export function EvidencePostureSummary({ posture, labels, stale = false, listed }: {
  posture?: EvidencePosture | null; labels?: EvidenceLabelEntry[] | null; stale?: boolean;
  /** Labels shown elsewhere (on the fact cards) are left out of the list here. */
  listed?(entry: EvidenceLabelEntry): boolean;
}) {
  if (!posture?.level && !posture?.text) return null;
  const text = postureText(posture.level, posture.text);
  const drivers = (posture.drivers ?? []).filter((driver) => driver.text);
  const summary = countSummary(posture.counts);
  const rows = (labels ?? []).filter((entry) => !listed || listed(entry));
  return <section className="analysis-evidence-posture" data-level={posture.level} aria-label="证据等级">
    <p className="analysis-evidence-posture-line">
      <PostureIcon level={posture.level} />
      <strong>证据等级：{text}{stale ? '（改稿前的分类，重检后更新）' : ''}</strong>
      <HelpLink article="evidence" label="证据标签与证据等级" />
    </p>
    <p className="analysis-note">这是对引用依据的分类，不代表经理认可。</p>
    {drivers.length > 0 && <ul className="analysis-evidence-drivers" aria-label="证据等级的依据">
      {drivers.slice(0, 5).map((driver) => <li key={driver.code}>{driver.text}</li>)}
    </ul>}
    {summary && <p className="analysis-note" aria-label="依据分类计数">{summary}</p>}
    {rows.length > 0 && <details className="analysis-details"><summary>依据分类 · {rows.length} 项</summary>
      <ul className="analysis-evidence-list">
        {rows.map((entry, index) => <li key={`${entry.key?.kind ?? 'entry'}-${index}`}>
          <span>{evidenceSubject(entry, index)}</span>
          <EvidenceLabelChip entry={entry} />
        </li>)}
      </ul>
    </details>}
  </section>;
}
