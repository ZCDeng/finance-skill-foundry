/**
 * Keep the harness's developer notes out of the finance seats' system prompt.
 *
 * The web runtime adds two global prompt sections to every agent: where the DSH
 * source checkout lives ("use this checkout only to inspect or extend DSH
 * itself") and how the web GUI's HMR and `pnpm run dev:web` behave. They tell a
 * coding agent how to work on the harness. A finance manager's assistant has no
 * shell and nothing to rebuild, and the lines only invite it to talk about DSH.
 *
 * A section registered in an agent's own scope shadows the global one of the
 * same name, and an empty section is dropped when the prompt is assembled, so
 * the seat registers both names empty. Other agents keep them.
 */
export const DEVELOPER_SECTIONS = ["harness:source", "app:web-surface"];

export function hideDeveloperSections(ctx) {
  if (typeof ctx?.inject !== "function") return;
  ctx.inject(["systemPrompt"], (promptCtx) => {
    for (const [index, name] of DEVELOPER_SECTIONS.entries()) {
      promptCtx.systemPrompt.section({ name, order: -99 + index, text: "" });
    }
  });
}
