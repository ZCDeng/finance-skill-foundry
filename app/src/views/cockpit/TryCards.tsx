import { ArrowRight, ChartNoAxesCombined, Crosshair, FileDown, Presentation, Receipt, RefreshCw, SearchCheck, type LucideIcon } from 'lucide-react';
import type { Feature, OverviewTask } from '../../bridge.js';
import { DisclosureSummary } from '../../components/Disclosure.js';
import { usePreferences } from '../../components/Preferences.js';
import { Button } from '../../components/ui/button.js';

/** Where 试一下 lands: the place on the task where the feature is. */
export type TryTarget = 'results' | 'operations' | 'billing' | 'dashboard' | 'rollforward';
/** The step a feature lives on gives its icon the step's segment colour. */
const SEGMENT: Record<TryTarget, string> = { results: 'finance', operations: 'operations', billing: 'operations', dashboard: 'report', rollforward: 'report' };

/** 还没试过's cards, in the order they are offered: the ones that show why the app is worth opening first. */
export const TRIES: { feature: Feature; title: string; text: string; target: TryTarget; icon: LucideIcon }[] = [
  { feature: 'source', title: '点一个数看来源', text: '结果里任何一个数都能点开，看它来自哪份表的哪个单元格。', target: 'results', icon: SearchCheck },
  { feature: 'scenario', title: '回款情景', text: '拖一下收缴率，看利润和距生死线跟着怎么变。', target: 'operations', icon: ChartNoAxesCombined },
  { feature: 'goal', title: '倒推到目标', text: '给一个目标收缴率或全年收入预算，倒推还差多少。', target: 'operations', icon: Crosshair },
  { feature: 'billing', title: '收缴率下钻到账单', text: '加一份收费明细，收缴率能一路点到每一张账单。', target: 'billing', icon: Receipt },
  { feature: 'present', title: '汇报模式', text: '认可的卡一张一屏，直接拿去开会。', target: 'dashboard', icon: Presentation },
  { feature: 'snapshot', title: '导出一页纸', text: '把认可的卡导出成一页 PDF 或 PPTX，成果库里也留一份。', target: 'dashboard', icon: FileDown },
  { feature: 'recompute', title: '下月自动重算', text: '下个月用上月套表起草，看板上的卡换上新资料按原来的算法重算。', target: 'rollforward', icon: RefreshCw },
];
/** How many 还没试过 offers at once. */
export const TRY_COUNT = 3;

/**
 * The features not used yet: none a real task's records show (an example task's 参考结果 is built by the app, not
 * used by the manager), none the preferences keep (点一个数看来源, 汇报模式), the first three in TRIES' order.
 */
export function untried(rows: OverviewTask[], kept: readonly Feature[]): typeof TRIES {
  const used = new Set<Feature>([...kept, ...rows.filter((row) => !row.task.sample).flatMap((row) => row.tried ?? [])]);
  return TRIES.filter((item) => !used.has(item.feature)).slice(0, TRY_COUNT);
}

/** 还没试过: three features this manager has not used, each a sentence and a way in. Folding it is kept. */
export function TryCards({ rows, taskTitle, onTry }: { rows: OverviewTask[]; taskTitle: string; onTry(target: TryTarget): void }) {
  const { preferences, available, set } = usePreferences();
  const offers = untried(rows, preferences.tried);
  if (!offers.length) return null;
  return <details className="analysis-details fnd-cockpit__tries" open={preferences.tips_open}
    onToggle={(event) => {
      const open = (event.currentTarget as HTMLDetailsElement).open;
      if (available && open !== preferences.tips_open) void set({ tips_open: open }).catch(() => undefined);
    }}>
    <DisclosureSummary>还没试过</DisclosureSummary>
    <p className="fnd-muted fnd-overview__note">{`挑了 ${offers.length} 个还没用过的功能，在「${taskTitle}」上试一下；用过的不再出现。`}</p>
    <ul className="fnd-cockpit__try-list">
      {offers.map(({ feature, title, text, target, icon: Icon }) => <li key={feature} className="fnd-cockpit__try" data-segment={SEGMENT[target]}>
        <span className="fnd-cockpit__try-icon" aria-hidden><Icon strokeWidth={1.75} /></span>
        <div className="fnd-cockpit__try-text">
          <p className="fnd-cockpit__try-title">{title}</p>
          <p className="fnd-muted">{text}</p>
        </div>
        <Button type="button" size="sm" variant="outline" onClick={() => onTry(target)}>
          试一下<ArrowRight size={13} strokeWidth={1.5} aria-hidden /><span className="sr-only">：{title}</span>
        </Button>
      </li>)}
    </ul>
  </details>;
}
