// @vitest-environment jsdom
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { DisclosureSummary } from '../src/components/Disclosure.js';

afterEach(cleanup);

// jsdom gives import.meta.url an http scheme; the suite runs from app/.
const SRC = resolve(process.cwd(), 'src');

function files(dir: string, ext: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return files(path, ext);
    return name.endsWith(ext) ? [path] : [];
  });
}

describe('DisclosureSummary (DESIGN.md 折叠段落)', () => {
  it('keeps the label as the whole summary text and its accessible name', () => {
    render(<details><DisclosureSummary>核对明细 · 3 项</DisclosureSummary><p>明细</p></details>);
    const summary = screen.getByText('核对明细 · 3 项', { selector: 'summary' });
    expect(summary.textContent).toBe('核对明细 · 3 项');
    // What a screen reader names it from: everything that is not aria-hidden.
    const named = summary.cloneNode(true) as HTMLElement;
    named.querySelectorAll('[aria-hidden="true"]').forEach((node) => node.remove());
    expect(named.textContent).toBe('核对明细 · 3 项');
    expect(summary.querySelectorAll('[aria-hidden="true"]')).toHaveLength(1);
  });

  it('draws one hidden Lucide chevron on the product stroke, no text triangles', () => {
    render(<details><DisclosureSummary>来源明细 · 12 行</DisclosureSummary></details>);
    const summary = screen.getByText('来源明细 · 12 行', { selector: 'summary' });
    const icons = summary.querySelectorAll('svg');
    expect(icons).toHaveLength(1);
    const [icon] = icons;
    expect(icon.classList.contains('lucide-chevron-right')).toBe(true);
    expect(icon.getAttribute('aria-hidden')).toBe('true');
    expect(icon.getAttribute('width')).toBe('16');
    expect(icon.getAttribute('stroke-width')).toBe('1.5');
    expect(summary.textContent).not.toMatch(/[▶▸►▾▼]/);
  });

  it('leaves the open state to the native details', () => {
    render(<details><DisclosureSummary>计算范围</DisclosureSummary><p>范围</p></details>);
    const summary = screen.getByText('计算范围', { selector: 'summary' });
    const details = summary.closest('details')!;
    expect(details.open).toBe(false);
    fireEvent.click(summary);
    expect(details.open).toBe(true);
  });

  it('marks the quiet tone and leaves the default unmarked', () => {
    render(<>
      <details><DisclosureSummary tone="quiet">技术信息</DisclosureSummary></details>
      <details><DisclosureSummary>报告信息</DisclosureSummary></details>
    </>);
    expect(screen.getByText('技术信息', { selector: 'summary' }).getAttribute('data-tone')).toBe('quiet');
    expect(screen.getByText('报告信息', { selector: 'summary' }).hasAttribute('data-tone')).toBe(false);
  });
});

describe('every in-app disclosure goes through DisclosureSummary', () => {
  it('writes <summary> only inside components/Disclosure.tsx', () => {
    const writers = files(SRC, '.tsx')
      .filter((path) => readFileSync(path, 'utf8').includes('<summary'))
      .map((path) => path.slice(SRC.length + 1));
    expect(writers).toEqual(['components/Disclosure.tsx']);
  });

  it('never styles the native disclosure marker', () => {
    const offenders = files(SRC, '.css').flatMap((path) => {
      const css = readFileSync(path, 'utf8');
      return ['::-webkit-details-marker', 'summary::marker']
        .filter((needle) => css.includes(needle))
        .map((needle) => `${path.slice(SRC.length + 1)}: ${needle}`);
    });
    expect(offenders).toEqual([]);
  });
});
