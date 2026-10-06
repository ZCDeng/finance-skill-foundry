import { officeDenied } from "./index.js";

/**
 * Take the office tools away from the close seat.
 *
 * The period preset drops rows -- bash, the filesystem, the delegation block --
 * and for a long time that was the whole fence, because the only other tools in
 * the deployment were this bundle's own. A companion changes that. A plugin
 * registers its tools globally, at profile level, and a preset row cannot take
 * away a tool the preset never mounted: the thirteen `univer_*` tools would
 * appear next to a locked window with nothing standing between them and it.
 *
 * `restrict` is the seam, the same one `f3-scope` uses. Restrictions intersect,
 * so this narrows the period agent and leaves every other agent in the
 * deployment alone -- an authoring session on `standard` keeps all thirteen.
 *
 * Why all thirteen and not a careful subset. Two of them are reachability in
 * the plain sense: `univer_execute` runs arbitrary Facade JavaScript and takes
 * an absolute `codeFile`, and `univer_import` reads an xlsx from a path into a
 * unit -- both are a road to the archived books that `lock` exists to close.
 * The other eleven fail a second test. A figure typed into a spreadsheet cell
 * and exported is a figure with no basis: not 我重算, because no catalog
 * produced it, and not 外部引用, because nobody published it. The bundle's own
 * skills teach exactly that -- computing derived money figures inside the
 * document, and editing a percentage by string replacement. There is no mark
 * that fixes it afterwards, because the mark would be written by the same
 * session that made the number up.
 *
 * This is not a claim that Univer is unsafe. It is the KTD11 line: the close
 * seat gets tools whose output can be traced, and a spreadsheet the model
 * authors cannot be.
 */
export const name = "finance-skill-foundry-period-scope";
export const inject = ["tools"];

/*
 * The manifest list is the floor, not the whole fence. A later companion
 * release can register a fourteenth `univer_*` tool (0.2.14 added
 * `univer_print_pdf`), and a name the list does not carry would stand on the
 * close seat with nothing in its way. So every `univer_*` name registered when
 * the scope applies is masked too, and a guard refuses any `univer_*` call that
 * registers later -- the mask hides, the guard is what holds.
 */
const OFFICE_PREFIX = "univer_";

export function periodOfficeDenied(registered, declared = officeDenied()) {
  const late = registered.filter((name) => name.startsWith(OFFICE_PREFIX));
  return [...new Set([...declared, ...late])];
}

export function apply(ctx) {
  const registered = (ctx.tools.schemas?.() ?? []).map((tool) => tool.name);
  ctx.tools.restrict({ deny: periodOfficeDenied(registered) });
  ctx.tools.guard((exec) =>
    String(exec?.name ?? "").startsWith(OFFICE_PREFIX)
      ? `period cannot execute ${exec.name}`
      : undefined,
  );
}
