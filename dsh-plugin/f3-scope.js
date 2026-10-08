import { f3Allowlist } from "./index.js";
import { hideDeveloperSections } from "./seat-prompt.js";

/**
 * Narrow a leader's follow-up agent to the one tool it is allowed.
 *
 * The bundle registers its ten tools once, globally, from the profile row --
 * that is the only shape that works on a profile with no agent presets, where
 * the profile rows *are* the tool set. A preset therefore cannot register a
 * smaller foundry roster of its own: the names are taken, and the runtime
 * refuses the second registration by name.
 *
 * `restrict` is the seam the runtime provides for exactly this. It masks global
 * tools for the calling agent scope, so a row here -- inside the `f3` preset --
 * leaves every other agent in the deployment untouched while the follow-up
 * agent sees `query-locked` and nothing else. Restrictions intersect, so a
 * deployment that adds its own narrowing cannot widen this one.
 *
 * The allowlist is `f3Allowlist()` rather than a literal, so the preset and the
 * bundle's own `toolsForProfile` cannot drift into disagreeing about what F3 is.
 */
export const name = "finance-skill-foundry-f3-scope";
export const inject = ["tools"];

export function apply(ctx) {
  ctx.tools.restrict({ allow: f3Allowlist() });
  hideDeveloperSections(ctx);
}
