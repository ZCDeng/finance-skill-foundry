import './components.css';

import { Marks } from './Chip.js';

/**
 * A deliverable, read as the document it is.
 *
 * Both things this product writes are documents with a shape: the brief is a
 * heading per question and a sentence under it; the workpaper is a heading per
 * question, a few named facts, and a table of every line that went into the
 * figure. Rendering either into a `<pre>` shows the operator the same thing a
 * log would -- which is the whole of the complaint this answers. A 536-line
 * workpaper whose 394 table rows arrive as monospace pipes is not a working
 * paper, it is a dump.
 *
 * Hand-written rather than a Markdown dependency, and that is a decision about
 * who writes the input rather than about bundle size. `brief.py` and
 * `workpaper.py` emit these files; the grammar below is theirs, all of it, and
 * a renderer that only knows that grammar cannot be surprised by input it was
 * not built for. A general Markdown renderer would accept far more than this
 * product can ever produce and still need the same table and provenance
 * treatment on top.
 */

export type Block =
  | { kind: 'title'; text: string }
  | { kind: 'section'; text: string }
  | { kind: 'meta'; rows: [string, string][] }
  | { kind: 'locks'; label: string; entries: [string, string][] }
  | { kind: 'table'; head: string[]; rows: string[][] }
  | { kind: 'text'; text: string };

/** A named fact under a heading: `来源: brief`, `我重算: 282670.7525`. */
const META = /^([^:：|]{1,10})[:：][ \t]*(.*)$/;

/** `| a | b |` split into cells, without the empty ends the pipes make. */
function cells(line: string): string[] {
  return line
    .replace(/^\s*\|/, '')
    .replace(/\|\s*$/, '')
    .split('|')
    .map((cell) => cell.trim());
}

const isRule = (line: string) => /^\s*\|[\s:|-]+\|\s*$/.test(line);

/**
 * The document as blocks.
 *
 * One pass, no lookahead beyond the run being gathered. Anything the grammar
 * does not recognise stays a paragraph rather than being dropped, so a line
 * added upstream shows up as text instead of disappearing.
 */
export function readDocument(source: string): Block[] {
  const lines = source.split('\n');
  const out: Block[] = [];
  let at = 0;

  const pushMeta = (rows: [string, string][]) => {
    if (rows.length) out.push({ kind: 'meta', rows });
  };

  while (at < lines.length) {
    const line = lines[at];

    if (line.trim() === '') {
      at += 1;
      continue;
    }

    if (line.startsWith('## ')) {
      out.push({ kind: 'section', text: line.slice(3).trim() });
      at += 1;
      continue;
    }
    if (line.startsWith('# ')) {
      out.push({ kind: 'title', text: line.slice(2).trim() });
      at += 1;
      continue;
    }

    if (line.trim().startsWith('|')) {
      const head = cells(line);
      let cursor = at + 1;
      if (cursor < lines.length && isRule(lines[cursor])) cursor += 1;
      const rows: string[][] = [];
      while (cursor < lines.length && lines[cursor].trim().startsWith('|')) {
        if (!isRule(lines[cursor])) rows.push(cells(lines[cursor]));
        cursor += 1;
      }
      out.push({ kind: 'table', head, rows });
      at = cursor;
      continue;
    }

    const match = META.exec(line);
    if (match) {
      const [, label, value] = match;
      /*
       * The lock digests are a named fact by grammar and a wall of text on
       * screen: one line carrying a sha for every table in the window, which in
       * a real close is twenty-five of them. It is the most load-bearing line
       * in the file -- it is what makes the figures reproducible -- so it is
       * pulled apart rather than truncated.
       */
      if (/哈希/.test(label) && value.includes('=')) {
        const entries = value
          .split(/\s+/)
          .filter(Boolean)
          .map((pair) => {
            const cut = pair.indexOf('=');
            return cut < 0
              ? ([pair, ''] as [string, string])
              : ([pair.slice(0, cut), pair.slice(cut + 1)] as [string, string]);
          });
        out.push({ kind: 'locks', label, entries });
        at += 1;
        continue;
      }
      const rows: [string, string][] = [];
      let cursor = at;
      while (cursor < lines.length) {
        const next = META.exec(lines[cursor]);
        if (!next || lines[cursor].trim().startsWith('|')) break;
        if (/哈希/.test(next[1]) && next[2].includes('=')) break;
        rows.push([next[1], next[2]]);
        cursor += 1;
      }
      pushMeta(rows);
      at = cursor;
      continue;
    }

    out.push({ kind: 'text', text: line.trim() });
    at += 1;
  }
  return out;
}

/** The label `workpaper.py` writes above a claim's marks. */
const TAG_LABEL = '标签';

/** Digests are identity, not numbers to read. Twelve characters is plenty. */
const short = (sha: string) => (sha.length > 12 ? `${sha.slice(0, 12)}…` : sha);

export function Reader({ source }: { source: string }) {
  const blocks = readDocument(source);
  return (
    <article className="fnd-doc">
      {blocks.map((block, index) => {
        const key = `${block.kind}-${index}`;
        if (block.kind === 'title') {
          return (
            <h2 key={key} className="fnd-doc__title">
              {block.text}
            </h2>
          );
        }
        if (block.kind === 'section') {
          return (
            <h3 key={key} className="fnd-doc__section">
              {block.text}
            </h3>
          );
        }
        if (block.kind === 'meta') {
          return (
            <dl key={key} className="fnd-doc__meta">
              {block.rows.map(([label, value]) => (
                <div key={label} className="fnd-doc__pair">
                  <dt>{label}</dt>
                  {/*
                    * The tag row is the one an operator reads down a workpaper
                    * looking for. `外部引用` beside `我重算` in the same ink is a
                    * distinction that only exists if you read every line; as
                    * chips it is the thing you see first.
                    */}
                  <dd>{label === TAG_LABEL ? <Marks tag={value} /> : value}</dd>
                </div>
              ))}
            </dl>
          );
        }
        if (block.kind === 'locks') {
          return (
            <details key={key} className="fnd-doc__locks">
              <summary>
                {block.label}
                <span className="fnd-muted">{` ${block.entries.length} 张表`}</span>
              </summary>
              <dl className="fnd-doc__meta">
                {block.entries.map(([name, sha]) => (
                  <div key={name} className="fnd-doc__pair">
                    <dt>{name}</dt>
                    <dd className="fnd-sha" title={sha}>
                      {short(sha)}
                    </dd>
                  </div>
                ))}
              </dl>
            </details>
          );
        }
        if (block.kind === 'table') {
          return (
            <div key={key} className="fnd-tablewrap">
              <table className="fnd-table">
                <thead>
                  <tr>
                    {block.head.map((cell, i) => (
                      <th key={`${cell}-${i}`}>{cell}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {block.rows.map((row, r) => (
                    <tr key={r}>
                      {row.map((cell, c) => (
                        // The figure column is the one an operator reads down.
                        <td key={c} className={/^[-\d.,]+$/.test(cell) ? 'fnd-num' : undefined}>
                          {cell}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }
        return (
          <p key={key} className="fnd-doc__text">
            {block.text}
          </p>
        );
      })}
    </article>
  );
}
