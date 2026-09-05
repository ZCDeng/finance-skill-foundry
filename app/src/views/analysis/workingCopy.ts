const PREFIX = 'foundry.analysis.working-copy.v1:';

/** Session-local recovery only. Immutable analysis and draft records still require an explicit save. */
export function readCopy<T>(key: string): T | undefined {
  try {
    const saved = sessionStorage.getItem(PREFIX + key);
    return saved == null ? undefined : JSON.parse(saved) as T;
  } catch { return undefined; }
}

export function writeCopy(key: string, value: unknown): boolean {
  try { sessionStorage.setItem(PREFIX + key, JSON.stringify(value)); return true; }
  catch { return false; }
}

export function removeCopy(key: string): void {
  try { sessionStorage.removeItem(PREFIX + key); } catch { /* The in-memory copy remains usable. */ }
}
