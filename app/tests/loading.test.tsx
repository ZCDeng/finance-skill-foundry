// @vitest-environment jsdom
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Loading, SkeletonCards, SkeletonRows } from '../src/components/Loading.js';

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe('loading placeholders', () => {
  it('keeps the words as the status and shows the shape only after the delay', () => {
    vi.useFakeTimers();
    render(<Loading label="正在读取这一版…"><SkeletonRows rows={2} /></Loading>);
    const status = screen.getByRole('status');
    expect(status.textContent).toBe('正在读取这一版…');
    expect(status.querySelector('[data-slot="skeleton"]')).toBeNull();
    act(() => { vi.advanceTimersByTime(300); });
    expect(status.querySelectorAll('[data-slot="skeleton"]')).toHaveLength(4);
    expect(status.textContent).toBe('正在读取这一版…');
  });

  it('draws result cards under a headline line, and the blocks are hidden from screen readers', () => {
    const { container } = render(<SkeletonCards cards={3} />);
    expect(container.querySelectorAll('.fnd-skeleton--card')).toHaveLength(3);
    expect(container.querySelector('.fnd-skeleton--headline')).toBeTruthy();
    expect([...container.querySelectorAll('[data-slot="skeleton"]')].every((block) => block.getAttribute('aria-hidden') === 'true')).toBe(true);
  });

  it('breathes in the strong surface and holds still under reduced motion', () => {
    const css = readFileSync(resolve(process.cwd(), 'src/components/components.css'), 'utf8');
    expect(css).toMatch(/\.fnd-skeleton \{[^}]*background: var\(--fnd-surface-strong\);[^}]*animation: fnd-skeleton 1\.5s ease-in-out infinite;/);
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\) \{\s*\.fnd-skeleton \{ animation: none; \}/);
    expect(css).toMatch(/@keyframes fnd-skeleton \{/);
  });
});
