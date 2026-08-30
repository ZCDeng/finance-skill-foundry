// defineConfig comes from vitest/config (a superset of vite's) so the `test`
// block below type-checks without a separate vitest.config file.
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  // Packaged builds load the renderer through file://, so asset URLs must be
  // relative rather than rooted at /.
  base: './',
  build: { outDir: 'dist-vite', emptyOutDir: true },
  server: { port: 5273, strictPort: true },
  test: {
    environment: 'node',
    include: ['tests/**/*.test.{ts,tsx}', 'electron/**/*.test.ts', 'src/**/*.test.{ts,tsx}'],
  },
});
