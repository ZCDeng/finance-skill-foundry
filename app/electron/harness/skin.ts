/**
 * The few edges of the embedded page this window draws in its own colour.
 *
 * Almost nothing belongs here. The page is upstream's, and restyling somebody
 * else's app by selector is a bet that their class names outlive the next
 * version. What earns a place is the seam an operator can see: the composer
 * sits directly under this app's own strips, in this app's own window, and its
 * edge was the one line on screen still drawn in another product's accent.
 *
 * The selectors are substring matches on the CSS-module *local* name rather
 * than the whole class. A build carries `uV2eYG_cardWorkspaceTrigger`, where
 * the prefix is a content hash that moves whenever upstream rebuilds and the
 * half after the underscore is the name someone wrote. Matching the second half
 * survives a rebuild; matching the first would not survive one. Measured on the
 * pinned build: each of these matches exactly one element.
 *
 * The failure mode is the point. If a name does change, the rule stops applying
 * and the page renders exactly as upstream drew it -- a lost accent, not a
 * broken pane. Nothing here changes behaviour, hides a control, or moves
 * anything.
 */

/**
 * The gold, and the same value the window's own hovered edges use.
 *
 * Taken from `--fnd-line-hover`'s dark answer rather than referenced: this
 * string is injected into a document that has never heard of this app's tokens.
 * `skin.test.ts` holds the two together so a change to the palette cannot leave
 * this one behind.
 */
export const EDGE = '#e2c180';

/** The same gold, lifted, for the state upstream draws in its own blue. */
export const EDGE_HOVER = '#f4dda9';

/** What the hero says once its whale has been replaced by this product's mark. */
export const HERO_HEADLINE = 'FA Foundry harness';

/**
 * The composer's edge, and the hero's line.
 *
 * The edge is solid rather than dashed, and that took two rules because the
 * dashed one is not a border. Upstream draws it as an `::after` inset by a
 * pixel whose background is masked into a dashed rectangle, while the card's
 * own border sits underneath at `transparent`. So the ring's background goes
 * away and the real border underneath is given the colour -- one line, 1px,
 * following the card's own 22px radius, and the hover still changes.
 *
 * Nothing is hidden to do it. The `::after` keeps its box, its mask and its
 * transition; it just stops painting, which is what a transparent background
 * means everywhere else in CSS too.
 *
 * The headline is text, and CSS cannot set text -- so the original is collapsed
 * to nothing and the replacement is drawn as generated content. That is the
 * ugliest thing in this file and it is deliberate: the string lives in the
 * runtime's own `conversation` locale namespace, and that service throws
 * `locale namespace "conversation" already has locale "en"` on a second
 * registration, so there is no supported override to prefer over this.
 */
export const HARNESS_SKIN = `
:root { --ds-font-family-base:'Noto Sans SC',sans-serif; --ds-font-family-sans:'Noto Sans SC',sans-serif; }
body, button, input, textarea, select { font-family:'Noto Sans SC',sans-serif !important; }

[class*="_cardWorkspaceTrigger"]::after {
  background: transparent !important;
}

[class*="_cardWorkspaceTrigger"] {
  border-color: ${EDGE} !important;
}

[class*="_cardWorkspaceTrigger"]:hover {
  border-color: ${EDGE_HOVER} !important;
}

[class*="_card"]:not([class*="_cardWorkspaceTrigger"]) {
  border-color: ${EDGE} !important;
}

[class*="_headlineText"] {
  font-size: 0 !important;
}

[class*="_headlineText"]::after {
  content: '${HERO_HEADLINE}';
  font-size: 28px;
  letter-spacing: 0.01em;
}
`;
