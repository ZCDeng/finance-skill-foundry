import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { bridge, type Feature, type Preferences } from '../bridge.js';

/**
 * 设置's app-wide choices, read once at the shell and handed down. Technical details (ids, digests, scripts, raw
 * JSON, engine diagnostics) show only when the manager turns them on; 本月三句话 opens or stays folded as chosen.
 *
 * Outside the shell, a component rendered on its own, or a build without the channel, there is nothing to read,
 * so everything shows as it did before 设置 existed.
 */
export type PreferencesState = {
  preferences: Preferences;
  /** False where this build cannot keep a choice; 设置 then says so instead of offering switches that do nothing. */
  available: boolean;
  /** True once the saved choices are read, or at once where there are none to read. */
  loaded: boolean;
  set(patch: Partial<Preferences>): Promise<void>;
};

const AS_BEFORE: Preferences = {
  technical: true, brief_open: true, start: 'overview', samples_read: [], skipped_steps: {}, people: [], current_person: '', tried: [], tips_open: true,
};
/** What a build that can keep the choices starts from until the saved file is read (electron/preferences.ts). */
const DEFAULTS: Preferences = {
  technical: false, brief_open: true, start: 'overview', samples_read: [], skipped_steps: {}, people: [], current_person: '', tried: [], tips_open: true,
};

const PreferencesContext = createContext<PreferencesState>({ preferences: AS_BEFORE, available: false, loaded: true, set: async () => {} });

export function PreferencesProvider({ children }: { children: ReactNode }) {
  const api = bridge();
  const available = Boolean(api?.preferencesGet && api.preferencesSet);
  const [preferences, setPreferences] = useState<Preferences>(available ? DEFAULTS : AS_BEFORE);
  const [loaded, setLoaded] = useState(!available);
  useEffect(() => {
    if (!available) return;
    let live = true;
    void api!.preferencesGet!().then((answer) => { if (live && answer.ok) setPreferences(answer.value); })
      .catch(() => {}).finally(() => { if (live) setLoaded(true); });
    return () => { live = false; };
  }, [api, available]);
  const set = useCallback(async (patch: Partial<Preferences>) => {
    if (!available) return;
    const before = preferences;
    setPreferences({ ...preferences, ...patch });
    try {
      const answer = await api!.preferencesSet!(patch);
      setPreferences(answer.ok ? answer.value : before);
      if (!answer.ok) throw new Error(answer.message);
    } catch (failure) {
      setPreferences(before);
      throw failure;
    }
  }, [api, available, preferences]);
  const value = useMemo(() => ({ preferences, available, loaded, set }), [preferences, available, loaded, set]);
  return <PreferencesContext.Provider value={value}>{children}</PreferencesContext.Provider>;
}

export function usePreferences(): PreferencesState {
  return useContext(PreferencesContext);
}

/** Whether ids, digests, scripts, raw JSON and diagnostics are on screen. */
export function useTechnical(): boolean {
  return useContext(PreferencesContext).preferences.technical;
}

/** Its children only while technical details are shown. */
export function Technical({ children }: { children: ReactNode }) {
  return useTechnical() ? <>{children}</> : null;
}

/**
 * The current person's 署名 (设置 › 使用者), filled in wherever a record is signed: a disposition, its review, a board
 * card's 认可, the one-page board. '' when nobody is chosen, and the name is typed as before. It is who signed, not who may.
 */
export function useSigner(): string {
  const { preferences } = useContext(PreferencesContext);
  return preferences.people.find((person) => person.id === preferences.current_person)?.signature ?? '';
}

/**
 * Marks a feature used that no task records (点一个数看来源, 汇报模式), once: 总览's 还没试过 stops offering it. Where the
 * choice cannot be kept, or it is already marked, nothing is written.
 */
export function useMarkTried(): (feature: Feature) => void {
  const { preferences, available, loaded, set } = useContext(PreferencesContext);
  return useCallback((feature: Feature) => {
    if (!available || !loaded || preferences.tried.includes(feature)) return;
    void set({ tried: [...preferences.tried, feature] }).catch(() => undefined);
  }, [available, loaded, preferences.tried, set]);
}
