import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import { EDGE, EDGE_HOVER, HARNESS_SKIN, HERO_HEADLINE } from '../electron/harness/skin.js';

const read = (rel: string) => readFileSync(fileURLToPath(new URL(rel, import.meta.url)), 'utf8');

const TOKENS = read('../src/styles/tokens.css');
const BUNDLE = JSON.parse(read('../../dsh-plugin/package.json')) as {
  dsh?: { client?: { platform?: string; inject?: string[] } };
  exports?: Record<string, unknown>;
};
const CLIENT = read('../../dsh-plugin/client.js');

describe('the edge this window draws on the embedded page', () => {
  it('is the same gold the window uses on its own edges', () => {
    // The skin is injected into a document that has never heard of this app's
    // tokens, so the value is a literal there. This is what stops the two
    // drifting into two different golds.
    const dark = /:root\[data-theme='dark'\][^}]*--fnd-line-hover:\s*([^;]+);/.exec(TOKENS)?.[1];
    expect(dark, 'no dark --fnd-line-hover').toBeTruthy();
    expect(EDGE).toBe(dark!.trim());
  });

  it('keeps upstream’s change of state, and only takes the hue', () => {
    // The composer's edge changes colour on hover. Flattening that to one
    // colour would be this app quietly removing a piece of feedback rather
    // than restyling it.
    expect(EDGE_HOVER).not.toBe(EDGE);
    expect(HARNESS_SKIN).toContain('[class*="_cardWorkspaceTrigger"]:hover');
  });

  /*
   * The dashed ring is an `::after` with a mask, not a border, and the card's
   * real border sits under it at `transparent`. Colouring the ring would give
   * a gold dashed line; the solid one asks for both halves.
   */
  it('draws one solid line rather than colouring the dashed one', () => {
    expect(HARNESS_SKIN).toContain('background: transparent !important');
    expect(HARNESS_SKIN).toMatch(
      /\[class\*="_cardWorkspaceTrigger"\]\s*\{\s*border-color/,
    );
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
    for (const local of ['_cardWorkspaceTrigger', '_headlineText', '_card']) {
      expect(HARNESS_SKIN, local).toContain(`[class*="${local}"]`);
    }
    expect(HARNESS_SKIN, 'a build hash leaked into a selector').not.toMatch(
      /\[class\*="[A-Za-z0-9]{4,}_/,
    );
  });

  it('leaves the composer card alone where the trigger already owns it', () => {
    // Both rules would otherwise apply to the same element and the later one
    // would win by accident rather than by decision.
    expect(HARNESS_SKIN).toContain('[class*="_card"]:not([class*="_cardWorkspaceTrigger"])');
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
