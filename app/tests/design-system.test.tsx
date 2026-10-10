// @vitest-environment jsdom
import { readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { DesignSystem } from '../src/design-system/DesignSystem.js';

afterEach(cleanup);

// jsdom gives import.meta.url an http scheme; the suite runs from app/.
const APP = process.cwd();

describe('the design system page (DESIGN.md 设计系统页)', () => {
  it('shows every ui primitive', () => {
    // The shadcn skill's showcase-coverage check, reading this repo's `.js` import paths.
    const page = readFileSync(resolve(APP, 'src/design-system/DesignSystem.tsx'), 'utf8');
    const primitives = readdirSync(resolve(APP, 'src/components/ui')).filter((name) => name.endsWith('.tsx')).map((name) => name.slice(0, -4));
    expect(primitives.length).toBeGreaterThanOrEqual(18);
    expect(primitives.filter((name) => !page.includes(`/ui/${name}.js'`))).toEqual([]);
  });

  it('stays out of the packaged build', () => {
    // index.html is Vite's only build input; a second entry would need rollupOptions.input.
    expect(readFileSync(resolve(APP, 'vite.config.mts'), 'utf8')).not.toMatch(/rollupOptions|design-system/);
  });

  it('renders both theme switches and the button state matrix', () => {
    render(<DesignSystem />);
    expect(screen.getByRole('tab', { name: '浅色' })).toBeTruthy();
    expect(screen.getByRole('tab', { name: '深色' })).toBeTruthy();
    expect(document.querySelectorAll('[data-preview="hover"]').length).toBeGreaterThanOrEqual(6);
    expect(document.documentElement.dataset.theme).toMatch(/^(light|dark)$/);
  });
});
