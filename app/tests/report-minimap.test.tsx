// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, renderHook, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ReportMinimap, useActiveHeading } from '../src/views/analysis/ReportMinimap.js';

const headings = [
  { id: 'section-2', level: 1, text: '一、经营概况' },
  { id: 'section-3', level: 2, text: '（一）收入' },
  { id: 'section-5', level: 1, text: '二、差异说明' },
];

/** A reading view whose headings sit at the given tops, in the page's own scroll. */
function page(tops: Record<string, number>) {
  document.body.innerHTML = `<article data-reading-main>${Object.keys(tops).map((id) => `<h2 id="${id}"></h2>`).join('')}</article>
    <details><div><h2 id="section-2"></h2></div></details>`;
  for (const [id, top] of Object.entries(tops)) {
    const node = document.querySelector<HTMLElement>(`[data-reading-main] [id="${id}"]`)!;
    node.getBoundingClientRect = () => ({ top } as DOMRect);
  }
}

beforeEach(() => {
  vi.spyOn(window, 'requestAnimationFrame').mockImplementation((cb) => { cb(0); return 1; });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); document.body.innerHTML = ''; });

describe('useActiveHeading', () => {
  it('is the last heading past the reading line, and follows a scroll', () => {
    page({ 'section-2': 20, 'section-3': 400, 'section-5': 900 });
    const { result } = renderHook(() => useActiveHeading(headings.map((item) => item.id), true));
    expect(result.current).toBe('section-2');
    for (const [id, top] of Object.entries({ 'section-2': -500, 'section-3': 60, 'section-5': 400 })) {
      document.querySelector<HTMLElement>(`[data-reading-main] [id="${id}"]`)!.getBoundingClientRect = () => ({ top } as DOMRect);
    }
    act(() => { document.dispatchEvent(new Event('scroll')); });
    expect(result.current).toBe('section-3');
  });

  it('is nothing while the reader is still above the first heading', () => {
    page({ 'section-2': 300, 'section-3': 700, 'section-5': 1100 });
    const { result } = renderHook(() => useActiveHeading(headings.map((item) => item.id), true));
    expect(result.current).toBeNull();
  });

  it('is nothing outside the reading view, where the headings carry no ids', () => {
    page({ 'section-2': 20 });
    const { result } = renderHook(() => useActiveHeading(['section-2'], false));
    expect(result.current).toBeNull();
    document.body.innerHTML = '';
    const missing = renderHook(() => useActiveHeading(['section-2'], true));
    expect(missing.result.current).toBeNull();
  });
});

describe('ReportMinimap', () => {
  it('draws one mark per heading, hidden from assistive technology, with the current one marked', () => {
    const { container } = render(<ReportMinimap headings={headings} active="section-3" />);
    const marks = container.querySelector('.report-minimap__marks')!;
    expect(marks.getAttribute('aria-hidden')).toBe('true');
    expect([...marks.children].map((mark) => [mark.getAttribute('data-level'), mark.getAttribute('data-active')]))
      .toEqual([['1', null], ['2', 'true'], ['1', null]]);
    expect(container.querySelector('[tabindex], a, button')).toBeNull();
  });

  it('opens the outline on hover, marks where the reader is, and closes on a pick', async () => {
    const { container } = render(<ReportMinimap headings={headings} active="section-5" />);
    await act(async () => { fireEvent.pointerEnter(container.querySelector('.report-minimap__marks')!, { pointerType: 'mouse' }); });
    const links = await screen.findAllByRole('link');
    expect(links.map((link) => [link.textContent, link.getAttribute('href')])).toEqual([
      ['一、经营概况', '#section-2'], ['（一）收入', '#section-3'], ['二、差异说明', '#section-5'],
    ]);
    expect(screen.getByRole('link', { name: '二、差异说明' }).getAttribute('aria-current')).toBe('location');
    await act(async () => { fireEvent.click(screen.getByRole('link', { name: '（一）收入' })); });
    expect(screen.queryAllByRole('link')).toHaveLength(0);
  });
});
