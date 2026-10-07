// @vitest-environment jsdom
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { act, cleanup, render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { WaitLoop } from '../src/components/WaitLoop.js';

afterEach(() => { cleanup(); vi.useRealTimers(); });

describe('WaitLoop', () => {
  it('stays away for waits under two seconds, then appears as decoration beside the text', () => {
    vi.useFakeTimers();
    const { container } = render(<p role="status"><WaitLoop />正在运行管理口径损益…</p>);
    expect(container.querySelector('svg')).toBeNull();
    act(() => { vi.advanceTimersByTime(1999); });
    expect(container.querySelector('svg')).toBeNull();
    act(() => { vi.advanceTimersByTime(1); });
    const loop = container.querySelector('svg')!;
    expect(loop.getAttribute('aria-hidden')).toBe('true');
    expect(loop.getAttribute('class')).toBe('fnd-wait-loop');
    expect(container.textContent).toBe('正在运行管理口径损益…');
  });

  it('shows at once when the caller has no quick case to hide, and never after unmount', () => {
    vi.useFakeTimers();
    const immediate = render(<WaitLoop delay={0} />);
    expect(immediate.container.querySelector('svg.fnd-wait-loop')).toBeTruthy();
    const pending = render(<WaitLoop />);
    pending.unmount();
    expect(() => act(() => { vi.advanceTimersByTime(5000); })).not.toThrow();
  });

  it('morphs between paths a CSS animation can tween, and holds still under reduced motion', () => {
    const css = readFileSync(resolve('src/components/components.css'), 'utf8');
    const keyframes = css.slice(css.indexOf('@keyframes fnd-wait-loop'));
    const paths = [...keyframes.slice(0, keyframes.indexOf('\n}')).matchAll(/path\('([^']+)'\)/g)].map((match) => match[1]);
    expect(paths).toHaveLength(3);
    // Path interpolation needs the same commands in the same order: a move, four curves, a close.
    for (const path of paths) expect(path.replace(/[^A-Za-z]/g, '')).toBe('MCCCCZ');
    // The still frame in the markup is the middle keyframe.
    const { container } = render(<WaitLoop delay={0} />);
    expect(container.querySelector('path')!.getAttribute('d')).toBe(paths[1]);
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\) \{\n {2}\.fnd-wait-loop path \{ animation: none; \}/);
  });
});
