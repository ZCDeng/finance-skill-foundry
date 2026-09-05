/** The cell naming the session the page opens on: { sessionId, subagentAddress? }. */
export const SESSION_SELECTION_KEY = 'dsh.sessions.current';

/** The per-session conversation store; the real key carries the session id. */
export const CHAT_STORE_PREFIX = 'dsh.conversation.chat';

/** Where one session's composer draft is kept. */
export function chatStoreKey(sessionId: string): string {
  return `${CHAT_STORE_PREFIX}.${sessionId}`;
}

/**
 * The script that selects a session and parks a draft, run before the page's
 * own bundle does.
 *
 * Values go through `JSON.stringify` on this side so a window id or a question
 * carrying a quote cannot end the string it is written into.
 */
export function handoffScript(sessionId: string, draft: string): string {
  const cell = JSON.stringify(SESSION_SELECTION_KEY);
  const chat = JSON.stringify(chatStoreKey(sessionId));
  const id = JSON.stringify(sessionId);
  const text = JSON.stringify(draft);
  return [
    'try {',
    `  window.localStorage.setItem(${cell}, JSON.stringify({ sessionId: ${id} }));`,
    ...(draft ? [
      '  let previous = {};',
      '  try {',
      `    const saved = JSON.parse(window.localStorage.getItem(${chat}) ?? 'null');`,
      '    if (saved && typeof saved === "object" && !Array.isArray(saved)) previous = saved;',
      '  } catch {}',
      // Upstream restores the whole value, replacing its defaults. Include all
      // fields on first use and preserve existing view/selection on a follow-up.
      `  window.localStorage.setItem(${chat}, JSON.stringify({ selection: null, view: null, inspect: null, ...previous, draft: ${text} }));`,
    ] : []),
    '} catch (error) { console.error("foundry handoff failed", error); }',
  ]
    .filter(Boolean)
    .join('\n');
}

/**
 * What a follow-up session opens with in its composer.
 *
 * Not the question itself. The operator pastes what the leader asked; this names
 * the window the answer must come from and the exact version they were holding,
 * because those are the two the model cannot work out and must not guess. The
 * brief sha is what makes an answer traceable to the sheet of paper the question
 * was asked against.
 */
export function followupDraft(opts: { windowId: string; briefSha?: string | null }): string {
  const lines = [
    `这一问是针对窗口 ${opts.windowId} 那一稿的。`,
    opts.briefSha ? `领导手上是 ${opts.briefSha} 那一版。` : '',
    '用 query-locked 重算, 把 --brief-window 指到这个窗口。下面贴领导的原话:',
    '',
  ];
  return lines.filter((line, index) => line !== '' || index === lines.length - 1).join('\n');
}

export interface EmbeddedInput {
  sessionId: string;
  draft?: string;
  submit?: boolean;
  requestId?: string;
}
export interface EmbeddedReply {
  sessionId: string;
  submitted: boolean;
  blockedReason?: string;
}

/** The checked client adapter calls the resident session and input services. */
export function residentHandoffScript(request: EmbeddedInput): string {
  return `(async () => {
    const end = Date.now() + 12000;
    while (!window.__foundryEmbedded && Date.now() < end) await new Promise(resolve => setTimeout(resolve, 25));
    if (window.__foundryEmbedded?.version !== 1) throw new Error('对话输入通道尚未就绪，请重试。');
    return window.__foundryEmbedded.dispatch(${JSON.stringify(request)});
  })()`;
}

export const snapshotDraftsScript = 'window.__foundryEmbedded?.snapshot() ?? {}';
export function restoreDraftsScript(drafts: Record<string, unknown>): string {
  return `(() => {
    const snapshot = ${JSON.stringify(drafts)};
    for (const [key, value] of Object.entries(snapshot.receipts ?? {})) {
      if (key.startsWith('fnd.submitted.') && typeof value === 'string') window.localStorage.setItem(key, value);
    }
    for (const [id, value] of Object.entries(snapshot.drafts ?? {})) {
      if (id.length <= 200 && value && typeof value === 'object' && typeof value.draft === 'string') {
        window.localStorage.setItem('dsh.conversation.chat.' + id, JSON.stringify(value));
      }
    }
  })()`;
}
