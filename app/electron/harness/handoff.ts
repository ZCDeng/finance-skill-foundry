/**
 * Opening the embedded harness on a session this app created.
 *
 * `session.create` makes a session and hands back its id, but it does not decide
 * which one the page shows. That is `dsh.sessions.current`, a browser-storage
 * cell the client runtime reads once when its session service is constructed and
 * never again -- so a session created from out here cannot become the current
 * one without a fresh document. The seam is that cell plus a reload.
 *
 * The composer's text is the same kind of cell rather than server state: the
 * per-session conversation store persists its whole value to `localStorage`
 * under `<prefix>.<sessionId>` and rehydrates from it at construction.
 *
 * This is coupling to storage keys upstream owns, which is why the shapes are
 * named constants here with a test that reads them back out of an installed
 * runtime. A rename upstream has to turn into a red test rather than into a
 * hand-off that silently does nothing. Nothing here reads or writes the page's
 * markup, and the values written are what the page itself writes on every
 * keystroke.
 *
 * A draft is seeded rather than sent. There is no server verb that parks text:
 * `session.prompt` wakes the driver and opens a turn either way, so sending
 * would mean the agent had read the question and picked a model before the
 * operator had looked at the screen. A follow-up is the operator's to send.
 */

/** The cell naming the session the page opens on. */
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
    `  window.localStorage.setItem(${cell}, JSON.stringify(${id}));`,
    draft ? `  window.localStorage.setItem(${chat}, JSON.stringify({ draft: ${text} }));` : '',
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
