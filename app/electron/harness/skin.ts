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
  focus: '#a67e3c',
  selected: '#8a6729',
  onSelected: '#f9fafb',
  selectionSurface: '#f5efe3',
} as const;

export const DARK_THEME = {
  bg: '#111111',
  surface: '#1f1f1f',
  surfaceStrong: '#161616',
  ink: '#f9fafb',
  muted: '#a6a6a6',
  line: '#ffffff24',
  focus: '#e2c180',
  selected: '#e2c180',
  onSelected: '#1f1f1f',
  selectionSurface: '#302b21',
} as const;

/** The body attribute written by the pinned DSH ThemePresenter for dark mode. */
export const DSH_DARK_ATTRIBUTE = 'data-ds-dark-theme';

export const COMPOSER_CARD_ATTRIBUTE = 'data-composer-card';
export const SEND_PRIMARY_CLASS = 'uV2eYG_primary';
export const SEND_TRAILING_CLASS = 'uV2eYG_trailing';
export const SETTINGS_CLOSE_CLASS = 'VOzbGW_close';

/** The dark-theme focus gold, matching the host's `--fnd-line-hover`. */
export const EDGE = DARK_THEME.focus;

/** The light-theme focus gold, matching the host's `--fnd-line-hover`. */
export const EDGE_LIGHT = LIGHT_THEME.focus;

/** The dark neutral edge used before hover or focus. */
export const LINE = DARK_THEME.line;

/** The light neutral edge used before hover or focus. */
export const LINE_LIGHT = LIGHT_THEME.line;

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
  --foundry-native-focus:${LIGHT_THEME.focus};
  --foundry-native-selected:${LIGHT_THEME.selected};
  --foundry-native-on-selected:${LIGHT_THEME.onSelected};
  --foundry-native-selection-surface:${LIGHT_THEME.selectionSurface};
}

body[${DSH_DARK_ATTRIBUTE}] {
  --foundry-native-bg:${DARK_THEME.bg};
  --foundry-native-surface:${DARK_THEME.surface};
  --foundry-native-surface-strong:${DARK_THEME.surfaceStrong};
  --foundry-native-ink:${DARK_THEME.ink};
  --foundry-native-muted:${DARK_THEME.muted};
  --foundry-native-line:${DARK_THEME.line};
  --foundry-native-focus:${DARK_THEME.focus};
  --foundry-native-selected:${DARK_THEME.selected};
  --foundry-native-on-selected:${DARK_THEME.onSelected};
  --foundry-native-selection-surface:${DARK_THEME.selectionSurface};
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
  --dsw-alias-border-l3:var(--foundry-native-line) !important;
  --dsw-alias-border-l4:var(--foundry-native-line) !important;
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
}

body, button, input, textarea, select { font-family:'Noto Sans SC',sans-serif !important; }

[class*="_cardWorkspaceTrigger"]::after {
  background: transparent !important;
}

[data-foundry-frame] [${COMPOSER_CARD_ATTRIBUTE}] {
  border-color: var(--foundry-native-line) !important;
}

[data-foundry-frame] [${COMPOSER_CARD_ATTRIBUTE}]:hover,
[data-foundry-frame] [${COMPOSER_CARD_ATTRIBUTE}]:focus-within {
  border-color: var(--foundry-native-focus) !important;
}

[data-foundry-frame] [${COMPOSER_CARD_ATTRIBUTE}]:focus-within {
  outline: 2px solid var(--foundry-native-focus) !important;
  outline-offset: -1px;
}

.${SEND_TRAILING_CLASS} > button.${SEND_PRIMARY_CLASS} {
  color: var(--foundry-native-on-selected) !important;
}

[data-foundry-frame] summary:focus-visible {
  outline: 2px solid var(--foundry-native-focus) !important;
  outline-offset: -1px;
}

.${SETTINGS_CLOSE_CLASS}:focus-visible {
  outline: 2px solid var(--foundry-native-focus) !important;
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
