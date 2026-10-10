/**
 * A click on a card in the assistant's answer that this window acts on: 打开结果 and 钉到看板.
 *
 * The cards are drawn in the embedded page (dsh-plugin/client.js), which has no channel to this window but its
 * console. So a click arrives as one console line, stamped with a nonce this window put in the page after it loaded
 * (`cardNonceScript`). A line without it -- the page's own logging, or anything the model's text could make the page
 * print -- is not a click. What a click may ask is narrow and checked here: open one run of a task, or pin one card to
 * a task's board. The window then acts only for the task on screen, and the board's own save checks the card.
 *
 * No Node imports: the renderer reads the action's type from here.
 */

/** What the page writes before the action, as dsh-plugin/client.js writes it. */
export const CARD_ACTION_MARKER = '__foundry_card_action__';

/** The board cards a conversation card can be pinned as (foundry/answer_cards.py `draw`); goal and sensitivity pin as what-ifs. */
export const PINNABLE_KINDS = ['figure', 'rank', 'bridge', 'goal', 'sensitivity'] as const;

export type PinnedCard = {
  kind: (typeof PINNABLE_KINDS)[number];
  title: string;
  run_id: string;
  select: { match: Record<string, string> } & Record<string, unknown>;
};

export type CardAction =
  | { action: 'open'; taskId: string; kind: 'analysis'; runId: string; analysisId: string | null }
  | { action: 'open'; taskId: string; kind: 'collection'; runId: string }
  | { action: 'pin'; taskId: string; card: PinnedCard };

const ID = /^[0-9a-f]{32}$/;
const ANALYSIS_ID = /^[a-zA-Z0-9_-]{1,128}$/;
/** A board card's title (foundry/dashboards.py MAX_TITLE). */
const MAX_TITLE = 60;
/** A selector is a handful of column names and texts; anything near this is not one. */
const MAX_LINE = 16_384;

/** The script that tells the page this window's nonce, run after every load. */
export function cardNonceScript(nonce: string): string {
  return `window.__foundryCardNonce = ${JSON.stringify(nonce)}; undefined;`;
}

const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

function pinnedCard(value: unknown): PinnedCard | null {
  if (!record(value)) return null;
  const { kind, title, run_id: runId, select } = value;
  if (typeof kind !== 'string' || !(PINNABLE_KINDS as readonly string[]).includes(kind)) return null;
  if (typeof title !== 'string' || !title.trim() || title.length > MAX_TITLE || /[\r\n]/.test(title)) return null;
  if (typeof runId !== 'string' || !ID.test(runId)) return null;
  if (!record(select) || !record(select.match)) return null;
  if (!Object.values(select.match).every((text) => typeof text === 'string')) return null;
  return { kind: kind as PinnedCard['kind'], title: title.trim(), run_id: runId, select: select as PinnedCard['select'] };
}

/** The click one console line asks for, or null when the line is not a click this window made possible. */
export function readCardAction(line: unknown, nonce: string): CardAction | null {
  if (typeof line !== 'string' || !nonce || !line.startsWith(CARD_ACTION_MARKER) || line.length > MAX_LINE) return null;
  let value: unknown;
  try {
    value = JSON.parse(line.slice(CARD_ACTION_MARKER.length));
  } catch {
    return null;
  }
  if (!record(value) || value.nonce !== nonce) return null;
  const taskId = value.task_id;
  if (typeof taskId !== 'string' || !ID.test(taskId)) return null;
  if (value.action === 'pin') {
    const card = pinnedCard(value.card);
    return card ? { action: 'pin', taskId, card } : null;
  }
  if (value.action !== 'open' || typeof value.run_id !== 'string' || !ID.test(value.run_id)) return null;
  if (value.kind === 'collection') return { action: 'open', taskId, kind: 'collection', runId: value.run_id };
  if (value.kind !== 'analysis') return null;
  const analysisId = typeof value.analysis_id === 'string' && ANALYSIS_ID.test(value.analysis_id) ? value.analysis_id : null;
  return { action: 'open', taskId, kind: 'analysis', runId: value.run_id, analysisId };
}
