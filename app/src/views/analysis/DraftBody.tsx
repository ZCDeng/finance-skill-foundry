import { createElement, type ReactNode } from 'react';

// Deliberately render a small Markdown subset as React elements. Raw HTML and
// links stay text; this preview never creates executable markup or navigations.
function inline(text: string): ReactNode[] {
  const output: ReactNode[] = [];
  const tokens = /(`+)([^`]*?)\1|\*\*([^*]+)\*\*|__([^_]+)__/g;
  let cursor = 0;
  for (const match of text.matchAll(tokens)) {
    if (match.index! > cursor) output.push(text.slice(cursor, match.index));
    output.push(match[1] ? <code key={match.index}>{match[2]}</code>
      : <strong key={match.index}>{match[3] ?? match[4]}</strong>);
    cursor = match.index! + match[0].length;
  }
  if (cursor < text.length) output.push(text.slice(cursor));
  return output;
}

function cells(line: string): string[] {
  return line.trim().replace(/^\|/, '').replace(/\|$/, '').split(/(?<!\\)\|/).map((value) => value.trim().replace(/\\\|/g, '|'));
}
const heading = /^(#{1,6})\s+(.+?)(?:\s+#+)?$/;
const bullet = /^\s*([-+*]|\d+[.)])\s+(.+)$/;
const fence = /^\s*(`{3,}|~{3,})/;
const isTableDivider = (line = '') => cells(line).length > 0 && cells(line).every((cell) => /^:?-{3,}:?$/.test(cell));
const clampHeadingLevel = (level: number) => Math.min(6, Math.max(3, level));

function topHeadingDepth(lines: string[]): number {
  let top = 7;
  for (let index = 0; index < lines.length;) {
    const codeFence = lines[index].match(fence);
    if (codeFence) {
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith(codeFence[1])) index += 1;
      if (index < lines.length) index += 1;
      continue;
    }
    const title = lines[index].match(heading);
    if (title) top = Math.min(top, title[1].length);
    index += 1;
  }
  return top === 7 ? 1 : top;
}

export function DraftBody({ body }: { body: string }) {
  const lines = body.replace(/\r\n?/g, '\n').split('\n');
  const topDepth = topHeadingDepth(lines);
  const blocks: ReactNode[] = [];
  for (let index = 0; index < lines.length;) {
    const line = lines[index];
    const key = index;
    if (!line.trim()) { index += 1; continue; }
    const title = line.match(heading);
    if (title) {
      const level = clampHeadingLevel(3 + title[1].length - topDepth);
      blocks.push(createElement(`h${level}`, { key }, inline(title[2])));
      index += 1; continue;
    }
    const codeFence = line.match(fence);
    if (codeFence) {
      const code: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith(codeFence[1])) code.push(lines[index++]);
      if (index < lines.length) index += 1;
      blocks.push(<pre key={key}><code>{code.join('\n')}</code></pre>);
      continue;
    }
    if (line.includes('|') && isTableDivider(lines[index + 1])) {
      const headers = cells(line);
      const alignment = cells(lines[index + 1]).map((cell) => cell.endsWith(':') ? cell.startsWith(':') ? 'center' : 'right' : 'left');
      const rows: string[][] = [];
      index += 2;
      while (index < lines.length && lines[index].includes('|') && lines[index].trim()) rows.push(cells(lines[index++]));
      blocks.push(<div key={key} className="fnd-tablewrap" role="region" aria-label="文稿表格" tabIndex={0}><table className="fnd-table analysis-markdown-table">
        <thead><tr>{headers.map((cell, column) => <th scope="col" key={column} style={{ textAlign: alignment[column] }}>{inline(cell)}</th>)}</tr></thead>
        <tbody>{rows.map((row, rowIndex) => <tr key={rowIndex}>{headers.map((_, column) => <td key={column} style={{ textAlign: alignment[column] }}>{inline(row[column] ?? '')}</td>)}</tr>)}</tbody>
      </table></div>);
      continue;
    }
    const list = line.match(bullet);
    if (list) {
      const ordered = /^\d/.test(list[1]);
      const items: ReactNode[] = [];
      while (index < lines.length) {
        const item = lines[index].match(bullet);
        if (!item || /^\d/.test(item[1]) !== ordered) break;
        items.push(<li key={index}>{inline(item[2])}</li>);
        index += 1;
      }
      blocks.push(ordered ? <ol key={key} start={parseInt(list[1], 10)}>{items}</ol> : <ul key={key}>{items}</ul>);
      continue;
    }
    const paragraph = [line];
    index += 1;
    while (index < lines.length && lines[index].trim() && !heading.test(lines[index]) && !bullet.test(lines[index]) && !fence.test(lines[index])
      && !(lines[index].includes('|') && isTableDivider(lines[index + 1]))) paragraph.push(lines[index++]);
    blocks.push(<p key={key}>{inline(paragraph.join('\n'))}</p>);
  }
  return <div className="analysis-draft-body">{blocks}</div>;
}
