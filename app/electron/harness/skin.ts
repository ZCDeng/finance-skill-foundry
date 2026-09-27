/**
 * Native harness theme bridge.
 *
 * The embedded DSH page owns its behavior and layout. This file only maps the
 * pinned runtime's theme tokens and a few inspected chrome edges to FA Foundry's
 * semantic palette.
 */

export const LIGHT_THEME = {
  bg: '#ffffff',
  surface: '#ffffff',
  surfaceStrong: '#f7f7f7',
  ink: '#000000e0',
  muted: '#00000099',
  line: '#1f1f1f24',
  lineHover: '#1f1f1f66',
  focus: '#8a6729',
  selected: '#8a6729',
  onSelected: '#f9fafb',
  selectionSurface: '#efefed',
  warning: '#a3372b',
  warningFill: '#c96a5c1f',
} as const;

export const DARK_THEME = {
  bg: '#111111',
  surface: '#1f1f1f',
  surfaceStrong: '#161616',
  ink: '#f9fafb',
  muted: '#a6a6a6',
  line: '#ffffff24',
  lineHover: '#ffffff59',
  focus: '#bfa36c',
  selected: '#e2c180',
  onSelected: '#1f1f1f',
  selectionSurface: '#292929',
  warning: '#eb9a8c',
  warningFill: '#eb9a8c1f',
} as const;

/** The body attribute written by the pinned DSH ThemePresenter for dark mode. */
export const DSH_DARK_ATTRIBUTE = 'data-ds-dark-theme';

export const COMPOSER_CARD_ATTRIBUTE = 'data-composer-card';
export const SEND_PRIMARY_CLASS = 'uV2eYG_primary';
export const SEND_TRAILING_CLASS = 'uV2eYG_trailing';
export const SETTINGS_CLOSE_CLASS = 'VOzbGW_close';

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

[class*="_headlineText"] {
  font-size: 0 !important;
}

[class*="_headlineText"]::after {
  content: '${HERO_HEADLINE}';
  font-size: 28px;
  letter-spacing: 0.01em;
}
`;
