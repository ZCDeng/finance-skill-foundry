/**
 * A getByText matcher for words split across elements (a period kept whole in its own
 * span): the innermost element whose whole text matches.
 */
export const acrossElements = (pattern: RegExp) => (_content: string, element: Element | null): boolean =>
  !!element && pattern.test(element.textContent ?? '')
  && !Array.from(element.children).some((child) => pattern.test(child.textContent ?? ''));
