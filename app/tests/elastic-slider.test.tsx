// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { ElasticSlider } from '../src/components/ElasticSlider.js';

beforeAll(() => {
  globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver;
});
afterEach(cleanup);

const percent = (ratio: number) => `${(ratio * 100).toFixed(1)}%`;

describe('ElasticSlider', () => {
  it('names itself apart from the field and reads its value the way the track shows it', () => {
    render(<ElasticSlider label="相对阈值" ariaLabel="相对重要性阈值，拖动选择" value={0.1} min={0} max={0.3} step={0.005} format={percent} onChange={() => {}} />);
    const slider = screen.getByRole('slider', { name: '相对重要性阈值，拖动选择' });
    expect(slider.getAttribute('aria-valuenow')).toBe('0.1');
    expect(slider.getAttribute('aria-valuetext')).toBe('10.0%');
    expect(document.querySelector('.fnd-elastic__value')!.textContent).toBe('10.0%');
    expect(document.querySelector('.fnd-elastic__label')!.getAttribute('aria-hidden')).toBe('true');
  });

  it('moves by its step from the keyboard', () => {
    const onChange = vi.fn();
    render(<ElasticSlider label="回款延迟" ariaLabel="回款延迟天数，拖动选择" value={15} min={0} max={90} step={1} format={(days) => `${days} 天`} onChange={onChange} />);
    fireEvent.keyDown(screen.getByRole('slider'), { key: 'ArrowRight' });
    expect(onChange).toHaveBeenLastCalledWith(16);
    fireEvent.keyDown(screen.getByRole('slider'), { key: 'Home' });
    expect(onChange).toHaveBeenLastCalledWith(0);
  });

  it('pins a typed value outside its range at that end without rewriting it, and starts empty fields at the bottom', () => {
    const onChange = vi.fn();
    const { rerender } = render(<ElasticSlider label="相对阈值" ariaLabel="滑块" value={0.5} min={0} max={0.3} step={0.005} format={percent} onChange={onChange} />);
    expect(screen.getByRole('slider').getAttribute('aria-valuenow')).toBe('0.3');
    rerender(<ElasticSlider label="相对阈值" ariaLabel="滑块" value={null} min={0} max={0.3} step={0.005} format={percent} onChange={onChange} />);
    expect(screen.getByRole('slider').getAttribute('aria-valuenow')).toBe('0');
    expect(onChange).not.toHaveBeenCalled();
  });

  it('draws nine ticks on a fine range and one per step on a coarse one', () => {
    const { container, rerender } = render(<ElasticSlider label="a" ariaLabel="a" value={0} min={0} max={90} step={1} format={String} onChange={() => {}} />);
    expect(container.querySelectorAll('.fnd-elastic__ticks > span')).toHaveLength(9);
    rerender(<ElasticSlider label="a" ariaLabel="a" value={0} min={0} max={4} step={1} format={String} onChange={() => {}} />);
    expect(container.querySelectorAll('.fnd-elastic__ticks > span')).toHaveLength(3);
  });
});
