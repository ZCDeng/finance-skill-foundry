import { Figure } from '../../components/Figure.js';
import { FigureSource } from './FigureSource.js';
import { figureSource, type FigureSourceContext } from './figureSourceInfo.js';
import { WHAT_IF_FLAG, type GoalView, type SensitivityView, type WhatIfRow } from './dashboardWhatIf.js';

/** The run's own lines a what-if works from, each opening to its source like any figure on the board. */
function BasisLines({ rows, context }: { rows: WhatIfRow[]; context: FigureSourceContext }) {
  return <dl className="dashboard-scenario__base">
    {rows.map((row) => <div key={row.metric_key}><dt>{row.metric_label}</dt><dd>
      <FigureSource text={row.display_value} info={figureSource(context, row as unknown as Record<string, unknown>, {
        metric: row.metric_label, part: row.scenario, value: row.display_value, facts: [['主体', row.entity], ['公式', row.formula]],
      })} />
    </dd></div>)}
  </dl>;
}

/**
 * 倒推: one entity's lines worked back from a target, the collection rate or the full-year revenue budget
 * (dashboardWhatIf.ts). What the card works out is flagged as a what-if, and the card is never accepted.
 */
export function GoalCard({ view, context }: { view: GoalView; context: FigureSourceContext }) {
  return <div className="dashboard-scenario dashboard-goal">
    <p className="dashboard-scenario__flag">{WHAT_IF_FLAG}</p>
    <p className="dashboard-card__subject">{view.subject}</p>
    <p className="dashboard-goal__part">{view.part}</p>
    <p className="dashboard-card__value"><Figure text={view.value} /></p>
    {view.beside.length > 0 && <dl className="dashboard-card__beside">
      {view.beside.map(([label, text]) => <div key={label}><dt>{label}</dt><dd><Figure text={text} /></dd></div>)}
    </dl>}
    <BasisLines rows={view.basis} context={context} />
    <p className="fnd-chart__caption">{view.caption}</p>
  </div>;
}

/**
 * 敏感性表: 距生死线 over gross margins and collection rates around where the entity stands, read from the run's own
 * grid and toned as the result page tones it; the cell nearest where it stands is framed.
 */
export function SensitivityCard({ view, context }: { view: SensitivityView; context: FigureSourceContext }) {
  return <div className="dashboard-scenario dashboard-sensitivity">
    <p className="dashboard-scenario__flag">{WHAT_IF_FLAG}</p>
    <p className="dashboard-card__subject">{view.subject}</p>
    <div className="fnd-tablewrap">
      <table className="analysis-table analysis-health-grid-table dashboard-sensitivity__grid">
        <caption className="sr-only">{`${view.subject}：各毛利率和收缴率下的距生死线（个百分点）`}</caption>
        <thead><tr><th scope="col">{view.corner}</th>{view.columns.map((text) => <th key={text} scope="col" className="fnd-num">{text}</th>)}</tr></thead>
        <tbody>{view.rows.map((row) => <tr key={row.label}>
          <th scope="row" className="fnd-num">{row.label}</th>
          {row.cells.map((cell, index) => <td key={view.columns[index]}
            className={`fnd-num analysis-health-cell analysis-health-cell--${cell.tone}${cell.current ? ' analysis-health-cell--current' : ''}`}
            aria-current={cell.current ? 'true' : undefined}><Figure text={cell.text} /></td>)}
        </tr>)}</tbody>
      </table>
    </div>
    <BasisLines rows={view.basis} context={context} />
    <p className="fnd-chart__caption">{view.caption}</p>
  </div>;
}
