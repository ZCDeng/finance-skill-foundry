/**
 * Native harness theme bridge.
 *
 * The embedded DSH page owns its behavior and layout. This file only maps the
 * pinned runtime's theme tokens and a few inspected chrome edges to FA Foundry's
 * semantic palette.
 */

export const LIGHT_THEME = {
  bg: '#f5f6f8',
  surface: '#ffffff',
  surfaceStrong: '#edeff3',
  ink: '#1c2232',
  muted: '#5b6176',
  line: '#20294c1f',
  lineHover: '#20294c59',
  focus: '#8a6729',
  selected: '#8a6729',
  onSelected: '#f9fafb',
  selectionSurface: '#eef0f4',
  warning: '#a3372b',
  warningFill: '#c96a5c1f',
  // The figures on a card the assistant draws in its answer: a negative, and the four lights of a screening.
  negative: '#94463d',
  warningLine: '#c96a5c',
  levelWatch: '#a35f1f',
  levelOk: '#4f7553',
  markAbsent: '#6b6b6b',
} as const;

export const DARK_THEME = {
  bg: '#0f1117',
  surface: '#1a1d26',
  surfaceStrong: '#14171f',
  ink: '#f3f4f7',
  muted: '#a4a9b8',
  line: '#ffffff1f',
  lineHover: '#ffffff52',
  focus: '#bfa36c',
  selected: '#e2c180',
  onSelected: '#1a1d26',
  selectionSurface: '#262a35',
  warning: '#eb9a8c',
  warningFill: '#eb9a8c1f',
  negative: '#d9a097',
  warningLine: '#eb9a8c',
  levelWatch: '#e0a46a',
  levelOk: '#9cc0a0',
  markAbsent: '#9a9a9a',
} as const;

/** The body attribute written by the pinned DSH ThemePresenter for dark mode. */
export const DSH_DARK_ATTRIBUTE = 'data-ds-dark-theme';

export const COMPOSER_CARD_ATTRIBUTE = 'data-composer-card';
export const SEND_PRIMARY_CLASS = 'uV2eYG_primary';
export const SEND_TRAILING_CLASS = 'uV2eYG_trailing';
export const SETTINGS_CLOSE_CLASS = 'VOzbGW_close';

/**
 * The card the assistant's point-and-pick question (`ask_user_question`) is drawn in, by the pinned
 * `dsh-client-ui-user-questions` bundle. Its module classes carry this prefix; the skin test holds it to the bundle.
 */
export const QUESTION_CLASS_PREFIX = 'Mbwy4a_';
const question = (name: string) => `.${QUESTION_CLASS_PREFIX}${name}`;

/** The dark-theme focus gold, matching the host's `--fnd-focus`. */
export const EDGE = DARK_THEME.focus;

/** The light-theme focus gold, matching the host's `--fnd-focus`. */
export const EDGE_LIGHT = LIGHT_THEME.focus;

/** The dark neutral edge used before hover or focus. */
export const LINE = DARK_THEME.line;

/** The light neutral edge used before hover or focus. */
export const LINE_LIGHT = LIGHT_THEME.line;

/** The dark neutral edge used for hover affordance. */
export const LINE_HOVER = DARK_THEME.lineHover;

/** The light neutral edge used for hover affordance. */
export const LINE_HOVER_LIGHT = LIGHT_THEME.lineHover;

/** What the hero says once its whale has been replaced by this product's mark. */
export const HERO_HEADLINE = 'FA Foundry harness';

export const HARNESS_SKIN = `
:root {
  --ds-font-family-base:'Noto Sans SC',sans-serif;
  --ds-font-family-sans:'Noto Sans SC',sans-serif;
  /* Figures on the assistant's cards: this window's own figure face, injected beside the text face (host.ts). */
  --foundry-native-figure:'IBM Plex Mono','Noto Sans SC',ui-monospace,monospace;
}

body {
  --foundry-native-bg:${LIGHT_THEME.bg};
  --foundry-native-surface:${LIGHT_THEME.surface};
  --foundry-native-surface-strong:${LIGHT_THEME.surfaceStrong};
  --foundry-native-ink:${LIGHT_THEME.ink};
  --foundry-native-muted:${LIGHT_THEME.muted};
  --foundry-native-line:${LIGHT_THEME.line};
  --foundry-native-line-hover:${LIGHT_THEME.lineHover};
  --foundry-native-focus:${LIGHT_THEME.focus};
  --foundry-native-selected:${LIGHT_THEME.selected};
  --foundry-native-on-selected:${LIGHT_THEME.onSelected};
  --foundry-native-selection-surface:${LIGHT_THEME.selectionSurface};
  --foundry-native-warning:${LIGHT_THEME.warning};
  --foundry-native-warning-fill:${LIGHT_THEME.warningFill};
  --foundry-native-negative:${LIGHT_THEME.negative};
  --foundry-native-warning-line:${LIGHT_THEME.warningLine};
  --foundry-native-level-watch:${LIGHT_THEME.levelWatch};
  --foundry-native-level-ok:${LIGHT_THEME.levelOk};
  --foundry-native-mark-absent:${LIGHT_THEME.markAbsent};
}

body[${DSH_DARK_ATTRIBUTE}] {
  --foundry-native-bg:${DARK_THEME.bg};
  --foundry-native-surface:${DARK_THEME.surface};
  --foundry-native-surface-strong:${DARK_THEME.surfaceStrong};
  --foundry-native-ink:${DARK_THEME.ink};
  --foundry-native-muted:${DARK_THEME.muted};
  --foundry-native-line:${DARK_THEME.line};
  --foundry-native-line-hover:${DARK_THEME.lineHover};
  --foundry-native-focus:${DARK_THEME.focus};
  --foundry-native-selected:${DARK_THEME.selected};
  --foundry-native-on-selected:${DARK_THEME.onSelected};
  --foundry-native-selection-surface:${DARK_THEME.selectionSurface};
  --foundry-native-warning:${DARK_THEME.warning};
  --foundry-native-warning-fill:${DARK_THEME.warningFill};
  --foundry-native-negative:${DARK_THEME.negative};
  --foundry-native-warning-line:${DARK_THEME.warningLine};
  --foundry-native-level-watch:${DARK_THEME.levelWatch};
  --foundry-native-level-ok:${DARK_THEME.levelOk};
  --foundry-native-mark-absent:${DARK_THEME.markAbsent};
}

body {
  --dsw-alias-bg-base:var(--foundry-native-bg) !important;
  --dsw-alias-bg-layer-2:var(--foundry-native-surface) !important;
  --dsw-specific-sidebar-fill:var(--foundry-native-surface-strong) !important;
  --dsw-specific-input-major:var(--foundry-native-surface) !important;
  --dsw-specific-selector:var(--foundry-native-surface-strong) !important;
  --dsw-specific-menu:var(--foundry-native-surface) !important;
  --dsw-specific-tip:var(--foundry-native-surface) !important;
  --dsw-specific-bubble:var(--foundry-native-selection-surface) !important;
  --dsw-alias-label-primary:var(--foundry-native-ink) !important;
  --dsw-alias-label-secondary:var(--foundry-native-muted) !important;
  --dsw-alias-label-tertiary:var(--foundry-native-muted) !important;
  --dsw-alias-label-caption:var(--foundry-native-muted) !important;
  --dsw-alias-label-primary-dimmed:var(--foundry-native-muted) !important;
  --dsw-alias-label-primary-bluish:var(--foundry-native-selected) !important;
  --dsw-alias-border-l1:var(--foundry-native-line) !important;
  --dsw-alias-border-l2:var(--foundry-native-line) !important;
  --dsw-alias-border-l2-darkmode-thin:var(--foundry-native-line) !important;
  --dsw-alias-border-l3:var(--foundry-native-line-hover) !important;
  --dsw-alias-border-l4:var(--foundry-native-line-hover) !important;
  --dsw-alias-separator-primary:var(--foundry-native-line) !important;
  --dsw-alias-interactive-bg-hover:color-mix(in srgb, var(--foundry-native-ink) 8%, transparent) !important;
  --dsw-alias-interactive-bg-hover-solid:color-mix(in srgb, var(--foundry-native-ink) 8%, var(--foundry-native-bg)) !important;
  --dsw-alias-button-elevated-fill:var(--foundry-native-surface) !important;
  --dsw-alias-button-floating-fill:var(--foundry-native-surface) !important;
  --dsw-alias-button-floating-hover:var(--foundry-native-surface-strong) !important;
  --dsw-alias-state-business-primary:var(--foundry-native-selected) !important;
  --dsw-alias-state-business-secondary:var(--foundry-native-focus) !important;
  --dsw-alias-state-business-tertiary:var(--foundry-native-selection-surface) !important;
  --dsw-static-blue-450:var(--foundry-native-selected) !important;
  --dsw-alias-button-info-fill:var(--foundry-native-selected) !important;
  --dsw-alias-button-info-hover:var(--foundry-native-focus) !important;
  --dsw-alias-state-error-primary:var(--foundry-native-warning) !important;
  --dsw-alias-label-error:var(--foundry-native-warning) !important;
  --dsw-alias-interactive-bg-hover-danger:var(--foundry-native-warning-fill) !important;
}

body, button, input, textarea, select {
  font-family:'Noto Sans SC',sans-serif !important;
}

body, button, input, select {
  font-size:14px;
  line-height:22px;
}

[class*="_cardWorkspaceTrigger"]::after {
  background: transparent !important;
}

[data-foundry-frame] [${COMPOSER_CARD_ATTRIBUTE}] {
  border-color: var(--foundry-native-line) !important;
  box-shadow: none !important;
}

[data-foundry-frame] [${COMPOSER_CARD_ATTRIBUTE}]:hover {
  border-color: var(--foundry-native-line-hover) !important;
}

[data-foundry-frame] [${COMPOSER_CARD_ATTRIBUTE}]:focus-within {
  border-color: var(--foundry-native-focus) !important;
}

[data-foundry-frame] [${COMPOSER_CARD_ATTRIBUTE}]:focus-within {
  outline: none !important;
}

.${SEND_TRAILING_CLASS} > button.${SEND_PRIMARY_CLASS} {
  color: var(--foundry-native-on-selected) !important;
}

[data-foundry-frame] summary:focus-visible {
  outline: 1px solid var(--foundry-native-focus) !important;
  outline-offset: -1px;
  box-shadow: none !important;
}

.${SETTINGS_CLOSE_CLASS}:focus-visible {
  outline: 1px solid var(--foundry-native-focus) !important;
  outline-offset: -1px;
  box-shadow: none !important;
}

/*
 * The assistant's point-and-pick question: this window's card rather than the runtime's bubble. The runtime already
 * draws it from the palette above; what is left is the shape (the window's 12/8 px radii, no floating shadow, like
 * the composer it replaces), the gold of a picked option and of 推荐, and the 12 px floor of this window's type.
 */
${question('card')} {
  border-radius: 12px !important;
  box-shadow: none !important;
}

${question('option')}, ${question('customRow')}, ${question('customBlock')} {
  border-radius: 8px !important;
}

${question('optionSelected')} {
  border-color: var(--foundry-native-selected) !important;
  background: var(--foundry-native-selection-surface) !important;
}

${question('option')}:focus-visible {
  outline: 1px solid var(--foundry-native-focus) !important;
  outline-offset: -1px;
}

${question('badge')} {
  background: color-mix(in srgb, var(--foundry-native-selected) 14%, transparent) !important;
  color: var(--foundry-native-selected) !important;
  font-size: 12px !important;
  font-weight: 500 !important;
}

${question('eyebrow')}, ${question('feedback')} {
  font-size: 12px !important;
}

${question('customBlock')}:focus-within {
  border-color: var(--foundry-native-focus) !important;
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
