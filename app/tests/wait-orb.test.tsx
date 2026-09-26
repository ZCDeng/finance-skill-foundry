// @vitest-environment jsdom
import { act, cleanup, render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { WaitOrb } from '../src/components/WaitOrb.js';

afterEach(() => { cleanup(); vi.useRealTimers(); });

describe('WaitOrb', () => {
  it('stays away for waits under two seconds, then appears as decoration beside the text', () => {
    vi.useFakeTimers();
    const { container } = render(<p role="status"><WaitOrb state="solving" />正在运行管理口径损益…</p>);
    expect(container.querySelector('canvas')).toBeNull();
    act(() => { vi.advanceTimersByTime(1999); });
    expect(container.querySelector('canvas')).toBeNull();
    act(() => { vi.advanceTimersByTime(1); });
    const orb = container.querySelector('canvas')!;
    expect(orb.getAttribute('aria-hidden')).toBe('true');
    expect(orb.style.display).toBe('inline-block');
    expect(container.textContent).toBe('正在运行管理口径损益…');
  });

  it('shows at once when the caller has no quick case to hide, and never after unmount', () => {
    vi.useFakeTimers();
    const immediate = render(<WaitOrb state="connecting" delay={0} />);
    expect(immediate.container.querySelector('canvas')).toBeTruthy();
    const pending = render(<WaitOrb state="working" />);
    pending.unmount();
    expect(() => act(() => { vi.advanceTimersByTime(5000); })).not.toThrow();
  });
});
