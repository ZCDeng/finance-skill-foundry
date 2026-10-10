import { useState } from 'react';
import { RotateCcw } from 'lucide-react';
import { Button } from '../../components/ui/button.js';
import { ElasticSlider } from '../../components/ElasticSlider.js';
import { DecimalInput } from '../../components/FinancialControls.js';
import { Figure } from '../../components/Figure.js';
import { decimalToFixed } from '../../lib/figures.js';
import { LevelMark, type HealthRow } from './CollectionHealthView.js';
import { FigureSource } from './FigureSource.js';
import { figureSource, type FigureSourceContext } from './figureSource.js';
import { scenarioAt, type ScenarioBase } from './dashboardScenario.js';

const LEVEL_WORDS = { red: '低于生死线', yellow: '贴近生死线', green: '高于生死线' } as const;

/** A number worked out here, written as the run writes its own: fixed places, grouped, its sign kept. */
const fixed = (value: number, places: number) => decimalToFixed(value.toFixed(8), places);
const signed = (value: number, places: number) => `${value > 0 ? '+' : ''}${fixed(value, places)}`;

/**
 * 回款情景: the collection rate moved by hand over one entity's lines of a collection-health run. The run's own lines
 * (毛利率、期间费用率、生死线) open to their source like any figure on the board; what the card works out from them
 * is flagged as a what-if on every view and is never accepted (foundry/dashboards.py).
 */
export function ScenarioCard({ base, context }: { base: ScenarioBase; context: FigureSourceContext }) {
  const [moved, setMoved] = useState<number | null>(null);
  const [typed, setTyped] = useState('');
  const rate = moved ?? base.current;
  const at = scenarioAt(base, rate);
  const min = Math.min(60, Math.floor(base.current / 5) * 5 - 5);
  const max = Math.max(100, Math.ceil(base.current));
  const move = (value: number) => { setMoved(value); setTyped(String(value)); };
  const unit = base.revenue?.unit ?? '';
  const source = (row: HealthRow, metric: string) => <FigureSource text={row.display_value}
    info={figureSource(context, row as unknown as Record<string, unknown>, { metric, part: row.scenario, value: row.display_value,
      facts: [['主体', row.entity], ['公式', row.formula]] })} />;
  return <div className="dashboard-scenario">
    <p className="dashboard-scenario__flag">情景，不是实际数</p>
    <p className="dashboard-card__subject">{`${base.entity} · 这次计算的本年账单收缴率 ${fixed(base.current, 2)}%`}</p>
    <div className="fnd-slider-pair">
      <DecimalInput label="假设收缴率" unit="%" value={moved === null ? fixed(base.current, 2) : typed}
        onChange={(text) => { setTyped(text); if (text.trim() && Number.isFinite(Number(text))) setMoved(Number(text)); }} />
      <ElasticSlider label="收缴率" ariaLabel="假设收缴率，拖动选择" value={rate} min={min} max={max} step={0.5}
        format={(value) => `${value.toFixed(1)}%`} onChange={move} />
    </div>
    <dl className="dashboard-card__beside" aria-live="polite">
      <div><dt>距生死线</dt><dd><Figure text={`${signed(at.gap, 2)} 个百分点`} /><LevelMark level={at.level} label={LEVEL_WORDS[at.level]} /></dd></div>
      {at.profit !== null && <div><dt>现金经营利润（一年）</dt><dd><Figure text={`${fixed(at.profit, 0)} ${unit}`} /></dd></div>}
      {at.collected !== null && <div><dt>一年回款比现在</dt><dd><Figure text={`${signed(at.collected, 0)} ${unit}`} /></dd></div>}
    </dl>
    {moved !== null && <Button type="button" size="sm" variant="ghost" className="dashboard-scenario__reset" onClick={() => { setMoved(null); setTyped(''); }}>
      <RotateCcw size={14} strokeWidth={1.5} aria-hidden />回到这次计算的收缴率</Button>}
    <dl className="dashboard-scenario__base">
      <div><dt>毛利率</dt><dd>{source(base.margin, '毛利率')}</dd></div>
      <div><dt>期间费用率</dt><dd>{source(base.expense, '期间费用率')}</dd></div>
      <div><dt>生死线收缴率</dt><dd>{source(base.breakEven, '生死线收缴率')}</dd></div>
      {base.revenue && <div><dt>近 12 个月营业收入</dt><dd>{source(base.revenue, '近12个月营业收入')}</dd></div>}
    </dl>
    <p className="fnd-chart__caption">{`以上几项读自这次计算，只有收缴率是假设。距生死线 = 收缴率 − 生死线收缴率，也是每收 100 元赚或倒贴的现金。${base.revenue
      ? `现金经营利润 = 距生死线 × 近 12 个月营业收入；一年回款变化 = 收缴率变化 × 近 12 个月营业收入 × ${base.vat}（回款含增值税）。` : '这次计算没有近 12 个月营业收入，算不出金额。'}`}</p>
  </div>;
}
