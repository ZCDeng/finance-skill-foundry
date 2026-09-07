import { fireEvent } from '@testing-library/react';

/** Radix menus listen for pointer events; jsdom `click` does not synthesise them. */
export function press(element: HTMLElement) {
  fireEvent.pointerDown(element, {
    pointerId: 1,
    pointerType: 'mouse',
    isPrimary: true,
    button: 0,
    buttons: 1,
  });
  fireEvent.pointerUp(element, {
    pointerId: 1,
    pointerType: 'mouse',
    isPrimary: true,
    button: 0,
    buttons: 0,
  });
  fireEvent.click(element);
}
