// defineConfig comes from vitest/config (a superset of vite's) so the `test`
// block below type-checks without a separate vitest.config file.
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

const root = fileURLToPath(new URL('.', import.meta.url));

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(root, 'src'),
    },
  },
  // Packaged builds load the renderer through file://, so asset URLs must be
  // relative rather than rooted at /.
  base: './',
  build: {
    outDir: 'dist-vite',
    emptyOutDir: true,
    /*
     * Nothing is inlined as a `data:` URI, and this is a correctness setting
     * rather than a size one.
     *
     * Vite inlines any asset under 4 KB by default. Three of the Chinese face's
     * 115 slices are under it, and the renderer's policy is `default-src 'none'`
     * with `font-src 'self'` -- which does not cover `data:`. Those three would
     * have been blocked in the packaged build only, drawing tofu for their
     * ranges while every other slice loaded, and the dev server would have shown
     * nothing wrong. `fonts.test.ts` checks the built stylesheet for them.
     */
    assetsInlineLimit: 0,
  },
  server: { port: 5273, strictPort: true },
  test: {
    environment: 'node',
    include: ['tests/**/*.test.{ts,tsx}', 'electron/**/*.test.ts', 'src/**/*.test.{ts,tsx}'],
    setupFiles: ['./tests/setup-jsdom.ts'],
  },
});
