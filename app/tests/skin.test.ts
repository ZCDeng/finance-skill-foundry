import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import {
  COMPOSER_CARD_ATTRIBUTE,
  DARK_THEME,
  DSH_DARK_ATTRIBUTE,
  EDGE,
  EDGE_LIGHT,
  HARNESS_SKIN,
  HERO_HEADLINE,
  LIGHT_THEME,
  LINE,
  LINE_HOVER,
  LINE_HOVER_LIGHT,
  LINE_LIGHT,
  SEND_PRIMARY_CLASS,
  SEND_TRAILING_CLASS,
  SETTINGS_CLOSE_CLASS,
} from '../electron/harness/skin.js';

const read = (rel: string) => readFileSync(fileURLToPath(new URL(rel, import.meta.url)), 'utf8');

const TOKENS = read('../src/styles/tokens.css');
const LAYOUT = read('../extra/dsh/.foundry-client-stock/layout.js');
const CONVERSATION = read('../extra/dsh/.foundry-client-stock/conversation.js');
const SETTINGS = read('../extra/dsh/.foundry-client-stock/settings-general.js');
const COMPACT = read('../harness-client/compact.css');
const BUNDLE = JSON.parse(read('../../dsh-plugin/package.json')) as {
  dsh?: { client?: { platform?: string; inject?: string[] } };
  exports?: Record<string, unknown>;
};
const CLIENT = read('../../dsh-plugin/client.js');

const token = (name: string, mode: 'light' | 'dark') => {
  const source =
    mode === 'dark'
      ? /:root\[data-theme='dark'\]\s*\{(?<body>[^}]+)\}/.exec(TOKENS)?.groups?.body
      : /:root\s*\{(?<body>[^}]+)\}/.exec(TOKENS)?.groups?.body;
  expect(source, `no ${mode} token block`).toBeTruthy();
  const value = new RegExp(`${name}:\\s*([^;]+);`).exec(source!)?.[1]?.trim();
  expect(value, `no ${mode} ${name}`).toBeTruthy();
  return value!;
};

describe('the edge this window draws on the embedded page', () => {
  it('uses the same focus gold and neutral hover the window uses on its own edges', () => {
    // The skin is injected into a document that has never heard of this app's
    // tokens, so the value is a literal there. This is what stops the two
    // drifting into two different golds.
    expect(EDGE).toBe(token('--fnd-focus', 'dark'));
    expect(EDGE_LIGHT).toBe(token('--fnd-focus', 'light'));
    expect(LINE_HOVER).toBe(token('--fnd-line-hover', 'dark'));
    expect(LINE_HOVER_LIGHT).toBe(token('--fnd-line-hover', 'light'));
  });

  it('uses the same idle line the window uses on its own dark edges', () => {
    expect(LINE).toBe(token('--fnd-line', 'dark'));
    expect(LINE_LIGHT).toBe(token('--fnd-line', 'light'));
  });

  it('keeps the bridge palette pinned to the host semantic tokens', () => {
    expect(LIGHT_THEME.bg).toBe(token('--fnd-bg', 'light'));
    expect(LIGHT_THEME.surface).toBe(token('--fnd-surface', 'light'));
    expect(LIGHT_THEME.surfaceStrong).toBe(token('--fnd-surface-strong', 'light'));
    expect(LIGHT_THEME.ink).toBe(token('--fnd-ink', 'light'));
    expect(LIGHT_THEME.muted).toBe(token('--fnd-muted', 'light'));
    expect(LIGHT_THEME.selected).toBe(token('--fnd-selected', 'light'));
    expect(LIGHT_THEME.onSelected).toBe(token('--fnd-on-selected', 'light'));
    expect(LIGHT_THEME.selectionSurface).toBe(token('--fnd-selection-surface', 'light'));
    expect(DARK_THEME.bg).toBe(token('--fnd-bg', 'dark'));
    expect(DARK_THEME.surface).toBe(token('--fnd-surface', 'dark'));
    expect(DARK_THEME.surfaceStrong).toBe(token('--fnd-surface-strong', 'dark'));
    expect(DARK_THEME.ink).toBe(token('--fnd-ink', 'dark'));
    expect(DARK_THEME.muted).toBe(token('--fnd-muted', 'dark'));
    expect(DARK_THEME.selected).toBe(token('--fnd-selected', 'dark'));
    expect(DARK_THEME.onSelected).toBe(token('--fnd-on-selected', 'dark'));
    expect(DARK_THEME.selectionSurface).toBe(token('--fnd-selection-surface', 'dark'));
  });

  it('follows the resolved DSH theme attribute rather than the OS media query', () => {
    expect(LAYOUT).toContain(`const DARK_ATTRIBUTE = "${DSH_DARK_ATTRIBUTE}"`);
    expect(LAYOUT).toContain(`body.setAttribute(DARK_ATTRIBUTE, "")`);
    expect(HARNESS_SKIN).toContain(`body[${DSH_DARK_ATTRIBUTE}]`);
    expect(HARNESS_SKIN).not.toContain('@media (prefers-color-scheme: dark)');
  });

  it('keeps idle neutral and only emphasizes interactive states', () => {
    expect(LINE).not.toBe(EDGE);
    expect(LINE_LIGHT).not.toBe(EDGE_LIGHT);
    expect(HARNESS_SKIN).toContain('border-color: var(--foundry-native-line) !important');
    expect(HARNESS_SKIN).toContain(`[data-foundry-frame] [${COMPOSER_CARD_ATTRIBUTE}]:hover`);
    expect(HARNESS_SKIN).toContain(`[data-foundry-frame] [${COMPOSER_CARD_ATTRIBUTE}]:focus-within`);
  });

  it('bridges upstream DSW business aliases to Foundry semantic colour', () => {
    for (const alias of [
      '--dsw-alias-bg-base:var(--foundry-native-bg) !important',
      '--dsw-specific-input-major:var(--foundry-native-surface) !important',
      '--dsw-alias-label-primary:var(--foundry-native-ink) !important',
      '--dsw-alias-label-secondary:var(--foundry-native-muted) !important',
      '--dsw-alias-border-l2-darkmode-thin:var(--foundry-native-line) !important',
      '--dsw-alias-border-l3:var(--foundry-native-line-hover) !important',
      '--dsw-alias-state-business-primary:var(--foundry-native-selected) !important',
      '--dsw-alias-button-info-fill:var(--foundry-native-selected) !important',
      '--dsw-alias-button-info-hover:var(--foundry-native-focus) !important',
      '--dsw-static-blue-450:var(--foundry-native-selected) !important',
    ]) {
      expect(HARNESS_SKIN).toContain(alias);
    }
  });

  /*
   * The dashed ring is an `::after` with a mask, not a border, and the card's
   * real border sits under it at `transparent`. Colouring the ring would give
   * a gold dashed line; the solid one asks for both halves.
   */
  it('draws one solid line rather than colouring the dashed one', () => {
    expect(HARNESS_SKIN).toContain('background: transparent !important');
    expect(HARNESS_SKIN).toMatch(
      /\[data-foundry-frame\]\s*\[data-composer-card\]\s*\{\s*border-color:\s*var\(--foundry-native-line\)/,
    );
    expect(HARNESS_SKIN).toContain('box-shadow: none !important');
    expect(HARNESS_SKIN).toContain('outline: none !important');
  });

  it('targets every real composer card through the upstream data attribute', () => {
    expect(CONVERSATION).toContain(`"${COMPOSER_CARD_ATTRIBUTE}": true`);
    expect(HARNESS_SKIN).toContain(`[data-foundry-frame] [${COMPOSER_CARD_ATTRIBUTE}]`);
    expect(HARNESS_SKIN).toContain(`[data-foundry-frame] [${COMPOSER_CARD_ATTRIBUTE}]:focus-within`);
  });
});

describe('how the skin holds on', () => {
  /*
   * The class names carry a content hash that moves on every upstream rebuild:
   * `uV2eYG_cardWorkspaceTrigger`. Matching the whole class would pin this file
   * to one build of somebody else's frontend. Matching the half a person named
   * survives a rebuild.
   */
  it('matches the name someone wrote, never the build hash in front of it', () => {
    for (const local of ['_cardWorkspaceTrigger', '_headlineText']) {
      expect(HARNESS_SKIN, local).toContain(`[class*="${local}"]`);
    }
    expect(HARNESS_SKIN, 'a build hash leaked into a selector').not.toMatch(
      /\[class\*="[A-Za-z0-9]{4,}_/,
    );
  });

  it('does not repaint every upstream card', () => {
    expect(HARNESS_SKIN).not.toContain('[class*="_card"]:not([class*="_cardWorkspaceTrigger"])');
    expect(HARNESS_SKIN).not.toContain('[class*="_card"]');
    expect(HARNESS_SKIN).not.toContain('[class*="_card"]:');
  });

  it('uses the pinned send-button class rather than a broad primary substring', () => {
    expect(CONVERSATION).toContain(`"primary": "${SEND_PRIMARY_CLASS}"`);
    expect(CONVERSATION).toContain(`"trailing": "${SEND_TRAILING_CLASS}"`);
    expect(HARNESS_SKIN).toContain(`.${SEND_TRAILING_CLASS} > button.${SEND_PRIMARY_CLASS}`);
    expect(HARNESS_SKIN).not.toContain('[class*="_primary"]');
  });

  it('changes how the page looks and nothing about what it does', () => {
    // A rule that hid or moved a control would be this app editing upstream's
    // product. `font-size: 0` is the one collapse here and it has generated
    // content behind it, which the check below holds it to.
    for (const forbidden of ['display: none', 'visibility: hidden', 'pointer-events']) {
      expect(HARNESS_SKIN, forbidden).not.toContain(forbidden);
    }
  });

  it('puts a line back wherever it takes one away', () => {
    expect(HARNESS_SKIN).toContain('font-size: 0');
    expect(HARNESS_SKIN).toContain(`content: '${HERO_HEADLINE}'`);
    expect(HERO_HEADLINE).toContain('FA Foundry');
  });

  it('keeps native details keyboard focus in the same theme bridge', () => {
    expect(HARNESS_SKIN).toContain('[data-foundry-frame] summary:focus-visible');
    expect(HARNESS_SKIN).toContain('outline: 1px solid var(--foundry-native-focus) !important');
    expect(HARNESS_SKIN).toContain('outline-offset: -1px');
  });

  it('replaces the settings close default focus without adding a second ring', () => {
    expect(SETTINGS).toContain(`"close": "${SETTINGS_CLOSE_CLASS}"`);
    expect(SETTINGS).toContain(`.${SETTINGS_CLOSE_CLASS}{`);
    expect(SETTINGS).not.toContain(`.${SETTINGS_CLOSE_CLASS}:focus-visible`);
    expect(HARNESS_SKIN).toContain(`.${SETTINGS_CLOSE_CLASS}:focus-visible`);
    expect(HARNESS_SKIN).toContain('outline: 1px solid var(--foundry-native-focus) !important');
    expect(HARNESS_SKIN).toContain('outline-offset: -1px');
    expect(HARNESS_SKIN).toContain('box-shadow: none !important');
    expect(HARNESS_SKIN).not.toContain('[data-foundry-frame] button:focus-visible');
  });
});

describe('native compact reading rhythm', () => {
  it('keeps native chrome at 14px and prose at 16px/28px', () => {
    expect(COMPACT).toContain('[data-foundry-frame] .wSkVaW_root { --dsh-composer-side-clearance:24px; font-size:14px; line-height:22px; }');
    expect(COMPACT).toContain('[data-foundry-frame] [data-composer-card] { border-radius:12px; font-size:16px; line-height:28px; }');
    expect(COMPACT).toContain('[data-foundry-frame] textarea { font-size:16px; line-height:28px; }');
    expect(COMPACT).toContain('[data-foundry-frame] .gdEzaW_bubble { line-height:28px; }');
  });

  it('gives panes at least 20px gutters and scroll content breathing room', () => {
    expect(COMPACT).toContain('[data-foundry-frame] .wSkVaW_scrollBody { padding:0 0 32px; box-sizing:border-box; }');
    expect(COMPACT).toContain('[data-foundry-frame] .Md3f7G_scroll { padding:24px 24px 32px; }');
    expect(COMPACT).toContain('[data-foundry-frame] .wSkVaW_composerHero { padding-bottom:24px; }');
    expect(COMPACT).toContain('[data-foundry-frame] .wSkVaW_root { --dsh-composer-side-clearance:20px; }');
    expect(COMPACT).toContain('[data-foundry-frame] .Md3f7G_scroll { padding-left:20px; padding-right:20px; }');
  });
});

describe('the brand this product puts in the page', () => {
  /*
   * The declaration that made the bundle visible to the client-module registry,
   * and the one that took a debugging round to find. The registry resolves
   * `<pkg>/package.json` through Node's exports map; a map that does not list
   * it makes that resolve throw, and the registry catches the throw as "this
   * package has no client half". The bundle loads, the tools work, and the
   * client bundle is never served -- with nothing anywhere saying why.
   */
  it('lets the registry read its own manifest', () => {
    expect(BUNDLE.exports?.['./package.json']).toBe('./package.json');
  });

  it('declares a web client half and exports it', () => {
    expect(BUNDLE.dsh?.client?.platform).toBe('web');
    expect(BUNDLE.exports?.['./client']).toBe('./client.js');
  });

  it('asks for the services the slots it fills belong to', () => {
    expect(BUNDLE.dsh?.client?.inject).toEqual([
      '@deepseek-ai/dsh-client-runtime',
      '@deepseek-ai/dsh-client-ui-conversation',
      '@deepseek-ai/dsh-client-ui-sidebar',
    ]);
  });

  it('takes the layout service it needs to close the rail', () => {
    expect(CLIENT).toContain("const inject = ['slots', 'layout'];");
  });

  /*
   * These are single-occupant slots and upstream is already in all three at
   * priority 0. Registering beside it is refused in so many words, and the
   * refusal names the way through: a lower priority shadows.
   */
  it('shadows the official occupant rather than colliding with it', () => {
    for (const slot of [
      'sidebar.brand.mark',
      'sidebar.brand.name',
      'conversation.hero.brand.mark',
    ]) {
      expect(CLIENT, slot).toContain(`name: '${slot}', priority: SHADOW`);
    }
    expect(CLIENT).toMatch(/const SHADOW = -\d+;/);
  });

  /*
   * One artwork, two appearances. The coloured mark is the product's identity
   * and the window's header says it; drawing the same gradients again in the
   * rail and on the hero put them on screen three times within one glance. A
   * filter rather than a second embed, so replacing the artwork recolours this
   * with it.
   */
  it('draws the embedded mark in one colour, derived from the same bytes', () => {
    expect(CLIENT).toContain("filter: 'brightness(0) invert(1)'");
    expect((CLIENT.match(/data:image\/png;base64,/g) ?? []).length).toBe(1);
  });

  it('carries the mark with it rather than fetching one', () => {
    // The page is served by a child process on a port this bundle cannot know
    // the shape of. A data URI is the one form that needs no path.
    expect(CLIENT).toContain("const MARK = 'data:image/png;base64,");
  });

  /*
   * Occupying the name slot with nothing is the point, not an oversight.
   * Leaving it unoccupied puts the vendor's wordmark back, and filling it puts
   * this product's name on screen a third time within 40px of the second.
   */
  it('occupies the sidebar name slot and draws nothing in it', () => {
    expect(CLIENT).toContain('function BrandName() {\n      return null;\n    }');
  });

  it('starts the rail closed without firing a blind toggle', () => {
    // `toggleSidebar` is the only verb and it toggles, so something has to say
    // which way the sidebar currently is before it fires.
    expect(CLIENT).toContain('ctx.layout.toggleSidebar()');
    expect(CLIENT).toContain('RAIL_EDGE');
  });

  /*
   * The bug this pins is the one that cost two rounds. Both states worth
   * reading -- the frame's own `data-sidebar-collapsed` and the toggle's
   * position -- are transiently wrong in the first frames after mount, so a
   * single measurement decides on a layout that is about to change. Two runs
   * shipped a no-op that way.
   */
  it('waits for the measurement to stop moving before it decides', () => {
    expect(CLIENT).toContain('SETTLED_TICKS');
    expect(CLIENT).toMatch(/agreed\s*<\s*SETTLED_TICKS/);
    expect(CLIENT, 'reads a state that lies on the first frame').not.toContain(
      "querySelector('[data-sidebar-collapsed]')",
    );
  });
});
