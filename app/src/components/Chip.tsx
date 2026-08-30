import './components.css';

import { COLOURED, MARKS, type MarkName } from './marks.js';

export function Chip({ mark }: { mark: MarkName }) {
  const coloured = COLOURED.includes(mark);
  return (
    <span className="fnd-chip" data-mark={mark} data-coloured={coloured ? 'yes' : 'no'}>
      {MARKS[mark]}
    </span>
  );
}

/** Every mark a tag string carries, in the fixed order `marks.ts` declares. */
export function Marks({ tag }: { tag: string }) {
  const marks = (Object.keys(MARKS) as MarkName[]).filter((name) => tag.includes(MARKS[name]));
  if (marks.length === 0) return null;
  return (
    <span className="fnd-marks">
      {marks.map((mark) => (
        <Chip key={mark} mark={mark} />
      ))}
    </span>
  );
}
