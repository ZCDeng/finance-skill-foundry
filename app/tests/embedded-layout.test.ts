import { describe, expect, it } from 'vitest';
import { PaneGeometry } from '../electron/harness/bounds.js';

describe('embedded conversation geometry', () => {
  it('uses renderer zoom once, clamps to native content and keeps the header clear', () => {
    const geometry = new PaneGeometry();
    expect(geometry.accept({ x: 190, y: 100, width: 420, height: 900, revision: 1 }, 1.25)).toBe(true);
    expect(geometry.bounds({ width: 1000, height: 800 })).toEqual({ x: 238, y: 125, width: 525, height: 675 });
    expect(geometry.bounds({ width: 400, height: 200 })).toEqual({ x: 238, y: 125, width: 162, height: 75 });
    expect(geometry.accept({ x: 0, y: 0, width: 900, height: 900, revision: 2 }, 1)).toBe(true);
    expect(geometry.bounds({ width: 800, height: 700 })).toEqual({ x: 0, y: 56, width: 800, height: 644 });
  });
  it('ignores stale layouts and rejects malformed input without replacing the last rectangle', () => {
    const geometry = new PaneGeometry();
    geometry.accept({ x: 200, y: 100, width: 420, height: 600, revision: 9 }, 1);
    expect(geometry.accept({ x: 0, y: 0, width: 1, height: 1, revision: 8 }, 1)).toBe(false);
    expect(() => geometry.accept({ x: -1, y: 0, width: 400, height: 600, revision: 10 }, 1)).toThrow();
    expect(() => geometry.accept({ x: 0, y: 0, width: Infinity, height: 600, revision: 10 }, 1)).toThrow();
    expect(geometry.bounds({ width: 1000, height: 800 }).x).toBe(200);
  });
});
