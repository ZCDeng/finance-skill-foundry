"""Text contracts for the bundled method skills.

The skills are model-facing text. A sentence that promises an ERP connection,
posting, a payment, live market data or a command Foundry does not have is a
product defect even when every engine test passes. Where upstream accounting
methodology legitimately talks about connections or posting, these tests
require a guard sentence next to it instead of banning the vocabulary.

Both shipped trees are checked: the repo `method/` and the packaged
`foundry/resources/method/` copy that the frozen app reads.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

from foundry.method_skills import BUNDLED_IDS, BUNDLED_PACKS, METHOD_RESOURCE_NAMES

ROOT = Path(__file__).resolve().parents[1]
TREES = (ROOT / "method", ROOT / "foundry" / "resources" / "method")
SKILL_IDS = BUNDLED_IDS + BUNDLED_PACKS

# Same grammar as the DSH skill registry (dsh-skill SKILL_NAME).
SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
LEGACY_KEYS = ("disableModelInvocation", "modelInvocable", "userInvocable")
# dsh-tool-skill normalises whitespace and cuts catalog descriptions here.
CATALOG_DESCRIPTION_LIMIT = 500

# Backticked snake_case words in skill text that are result fields or metric
# keys, not tools. Each must be a quoted literal in the engine and be used by a
# skill (both checked below), so the list cannot hide an invented tool.
RESULT_FIELDS = frozenset(
    {
        # finance_readiness report
        "can_run",
        "erp_connected",
        "identity_failed",
        "mapping_incomplete",
        "no_dataset",
        "pending_structure",
        "proposed_scope",
        # run_metric capability and metric keys
        "control_totals",
        "management_pnl",
        # aging run sections passed to drilldown_fact
        "detail_rows",
        "excluded_detail_rows",
        # explanation, chart and completion references
        "chart_id",
        "fact_ids",
        "no_progress",
        "run_id",
    }
)

# A bare name, a field path (`tool.field`) or a call (`tool(args)`).
TOOL_TOKEN = re.compile(r"`([a-z][a-z0-9]*(?:_[a-z0-9]+)+)(?:\.[A-Za-z0-9_.]+|\([^`)]*\))?`")
# The DSH gesture grammar is whitespace-bounded; skills also write commands in
# backticks or parentheses, so this reads a little wider than the runtime.
SLASH_COMMAND = re.compile(
    r"(?:^|(?<=[\s`(\"'“（]))/([a-z0-9]+(?:-[a-z0-9]+)*)(?=[\s`)\"'”），。,.;:!?]|$)",
    re.MULTILINE,
)
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
METHOD_RESOURCE_REF = re.compile(
    r'method-resource\s*\{\s*skill:\s*"([^"]*)"\s*,\s*resource:\s*"([^"]*)"\s*\}'
)

# Phrase patterns use \s+ so that hard-wrapped or double-spaced text still matches.
CONNECTOR_CONDITIONAL = re.compile(
    r"\bis\s+connected\b|\bif\s+~~|\bconnect\s+~~", re.IGNORECASE
)
CONNECTOR_GUARD = re.compile(
    r"\bdo not\b[^.\n]*\bclaim\b[^.\n]*\bunless\b[^.\n]*\bconfigured\b[^.\n]*\bnamed\b",
    re.IGNORECASE,
)
CONNECTION_CLAIM = re.compile(
    r"is\s+connected\s+to|connected\s+ERP|live\s+ledger\s+connection|已\s*连接|已\s*接通",
    re.IGNORECASE,
)
NEGATION = re.compile(r"\b(?:not|no|never)\b|不|未|没有", re.IGNORECASE)
# A negation only counts inside the clause that makes the claim, so "has a
# connected ERP, but does not pay" is still a claim.
CLAUSE_BREAK = re.compile(
    r"[,;:|，；：、]|\b(?:but|while|whereas|although|though)\b|但|而", re.IGNORECASE
)
LIVE_MARKET_DATA = re.compile(
    r"\b(?:Bloomberg|FactSet|Refinitiv|Capital\s+IQ|PitchBook)\b"
    r"|real(?:-|\s+)time\s+(?:quotes?|prices?|market)"
    r"|live\s+(?:market\s+data|quotes?|prices?)"
    r"|万得|实时行情",
    re.IGNORECASE,
)
# `post-acquisition` is not posting; `books` (closing the books) is not booking.
POSTING = re.compile(r"\b(?:post(?:s|ed|ing)?|book(?:ed|ing)?)\b(?!-)", re.IGNORECASE)
POSTING_GUARD = re.compile(
    r"\b(?:does not|do not|never)\b[^.\n]{0,60}\bpost"
    r"|\bno\b[^.\n]{0,40}\bposting\b"
    r"|\bdrafts? only\b",
    re.IGNORECASE,
)
PAYMENT = re.compile(r"\b(?:payments?|pay)\b", re.IGNORECASE)
PAYMENT_GUARD = re.compile(
    r"\b(?:does not|do not|never)\b[^.\n]{0,60}\b(?:pay|payments?)\b"
    r"|\bno\b[^.\n]{0,20}\bpayments?\b",
    re.IGNORECASE,
)
# An instruction to post, book or pay. Each one needs its own guard: a
# disclaimer elsewhere in the file does not cover a later instruction.
LIST_LEAD = r"^(?:[-*+]\s+|\d+[.)]\s+)?(?:\*\*[^*]+\*\*\s*)?"
POSTING_ACTION = re.compile(
    LIST_LEAD + r"(?:post|book)\b"
    r"|\b(?:post|book)\w*\b[^.\n]{0,40}\b(?:to|into)\s+(?:the\s+|an\s+|your\s+)?"
    r"(?:ERP|ledger|GL|general\s+ledger|books)\b",
    re.IGNORECASE,
)
PAYMENT_ACTION = re.compile(
    LIST_LEAD + r"pay\b"
    r"|\b(?:initiate|release|send|make|execute|submit|schedule|approve|run)\b"
    r"[^.\n]{0,30}\bpayments?\b",
    re.IGNORECASE,
)
# A hard-wrapped line continues its sentence. Sentence punctuation, a blank line
# and the start of a list item, table row, heading or quote end one.
SENTENCE_BREAK = re.compile(
    r"(?<=[.!?;:])\s+|[。！？；]|\n[ \t]*\n\s*"
    r"|\n(?=[ \t]*(?:[-*+][ \t]|\d+[.)][ \t]|[|#>]|```))"
)


def _label(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _file_params(pattern: str) -> list:
    return [
        pytest.param(tree, path.relative_to(tree), id=_label(path))
        for tree in TREES
        for path in sorted(tree.rglob(pattern))
        if path.is_file()
    ]


SKILLS = [
    pytest.param(tree, path.parent.name, id=f"{_label(tree)}:{path.parent.name}")
    for tree in TREES
    for path in sorted(tree.glob("*/SKILL.md"))
]
MARKDOWN = _file_params("*.md")
FILES = _file_params("*")
TREE_PARAMS = [pytest.param(tree, id=_label(tree)) for tree in TREES]
PLUGINS = [ROOT / "dsh-plugin", ROOT / "foundry" / "resources" / "dsh-plugin"]


def _frontmatter(text: str) -> tuple[dict, str]:
    lines = text.split("\n")
    assert lines[0] == "---", "SKILL.md must open with YAML frontmatter"
    end = lines.index("---", 1)
    data = yaml.safe_load("\n".join(lines[1:end]))
    assert isinstance(data, dict)
    return data, "\n".join(lines[end + 1 :])


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _skill(tree: Path, skill_id: str) -> tuple[dict, str]:
    return _frontmatter(_read(tree / skill_id / "SKILL.md"))


def _description(data: dict) -> str:
    return " ".join(str(data["description"]).split())


def _sentences(text: str) -> list[str]:
    return [part for part in SENTENCE_BREAK.split(text) if part.strip()]


def _claim_clause(sentence: str, match: re.Match[str]) -> str:
    breaks = [found.end() for found in CLAUSE_BREAK.finditer(sentence, 0, match.start())]
    return sentence[(breaks[-1] if breaks else 0) : match.end()]


def _unnegated_claims(text: str) -> list[str]:
    claims = []
    for sentence in _sentences(text):
        flat = " ".join(sentence.split())
        if any(
            not NEGATION.search(_claim_clause(flat, match))
            for match in CONNECTION_CLAIM.finditer(flat)
        ):
            claims.append(flat)
    return claims


def _unguarded_actions(text: str) -> list[str]:
    actions = []
    for sentence in _sentences(text):
        flat = " ".join(sentence.split())
        if (POSTING_ACTION.search(flat) and not POSTING_GUARD.search(flat)) or (
            PAYMENT_ACTION.search(flat) and not PAYMENT_GUARD.search(flat)
        ):
            actions.append(flat)
    return actions


def _method_resource_errors(tree: Path, relative: Path, text: str) -> list[str]:
    owner = relative.parts[0] if len(relative.parts) == 2 and relative.name == "SKILL.md" else None
    references = METHOD_RESOURCE_REF.findall(text)
    errors = []
    if owner in BUNDLED_IDS and not references:
        errors.append(f"{relative}: companion notes are no longer referenced")
    for skill, resource in references:
        # read_method_resource serves any of the four method ids, whichever skill
        # is loaded, and never a pack id. A method's own notes name the method
        # itself; packs and root notes may name any bundled method.
        if skill not in BUNDLED_IDS:
            errors.append(f"{relative}: {skill} is not a bundled method")
        elif owner in BUNDLED_IDS and skill != owner:
            errors.append(f"{relative}: references {skill}")
        if resource not in METHOD_RESOURCE_NAMES:
            errors.append(f"{relative}: {resource} is not a method resource")
        elif not (tree / resource).is_file():
            errors.append(f"{relative}: {resource} is missing")
    return errors


def _block(source: str, start_marker: str) -> str:
    start = source.index(start_marker)
    return source[start : source.index("\n};", start)]


def _finance_tools() -> set[str]:
    block = _block(_read(ROOT / "dsh-plugin" / "finance-tools.js"), "export const FINANCE_TOOLS = {")
    return set(re.findall(r"^  ([a-z_]+):", block, re.MULTILINE))


def _analysis_specs() -> set[str]:
    block = _block(_read(ROOT / "dsh-plugin" / "analysis.js"), "const SPECS = {")
    return set(re.findall(r'^  "([a-z-]+)":', block, re.MULTILINE))


def test_every_skill_directory_is_a_bundled_skill_or_pack() -> None:
    # The DSH provider catalogs any <root>/<dir>/SKILL.md, registered or not.
    for tree in TREES:
        found = {path.parent.name for path in tree.glob("*/SKILL.md")}
        assert found == set(SKILL_IDS), _label(tree)
    assert len(SKILLS) == 2 * len(SKILL_IDS)


@pytest.mark.parametrize(
    ("text", "pattern", "guard"),
    [
        ("If ~~erp is connected, pull the ledger.", CONNECTOR_CONDITIONAL, CONNECTOR_GUARD),
        ("Post the accrual to the ledger.", POSTING, POSTING_GUARD),
        ("Initiate the vendor payment run.", PAYMENT, PAYMENT_GUARD),
        ("Foundry is connected to your ERP.", CONNECTION_CLAIM, NEGATION),
        ("本产品已接通金蝶账套。", CONNECTION_CLAIM, NEGATION),
    ],
)
def test_contract_patterns_reject_unguarded_wording(
    text: str, pattern: re.Pattern[str], guard: re.Pattern[str]
) -> None:
    assert pattern.search(text) and not guard.search(text)


def test_contract_patterns_find_invented_names_and_market_data() -> None:
    assert LIVE_MARKET_DATA.search("Pull real-time quotes from Bloomberg.")
    assert SLASH_COMMAND.findall("Drill in with `/flux` or /je now") == ["flux", "je"]
    assert TOOL_TOKEN.findall(
        "Call `post_journal_entry`, `post_journal_entry()`, `post_journal_entry(entry)` "
        'then `drilldown_fact.section` and `drilldown_fact(section="detail_rows")`.'
    ) == ["post_journal_entry"] * 3 + ["drilldown_fact"] * 2
    assert TOOL_TOKEN.findall('`file_identity_policy: "snapshot_only"`') == []


@pytest.mark.parametrize(
    "text",
    [
        "Foundry is connected\nto NetSuite for these skills.",
        "Foundry has a connected\nERP.",
        "the connected  ERP",
        "Pull from the live ledger\n   connection.",
        "本产品已\n接通金蝶账套。",
        "- Foundry is connected to NetSuite\n- not reviewed",
        "| ERP | is connected to NetSuite |\n| no | other |",
    ],
)
def test_connection_claims_are_found_across_wrapped_lines(text: str) -> None:
    assert _unnegated_claims(text)


@pytest.mark.parametrize(
    "text",
    [
        "Foundry has a connected ERP, but does not initiate payments.",
        "Foundry never pays vendors while it is connected to NetSuite.",
        "| no | is connected to NetSuite |",
        "本产品不付款，但已接通金蝶账套。",
    ],
)
def test_a_negation_in_another_clause_does_not_cover_the_claim(text: str) -> None:
    assert _unnegated_claims(text)


def test_wrapped_negated_connection_wording_passes() -> None:
    assert _unnegated_claims("No ERP is connected\nto Foundry; work from the files.") == []
    assert _unnegated_claims("Foundry does not have a connected\nERP.") == []
    assert CONNECTOR_CONDITIONAL.search("When the ledger is\nconnected, pull it.")
    assert LIVE_MARKET_DATA.search("Pull real-time\nquotes or live  market data.")


@pytest.mark.parametrize(("tree", "skill_id"), SKILLS)
def test_skill_frontmatter_follows_the_catalog_rules(tree: Path, skill_id: str) -> None:
    data, _ = _skill(tree, skill_id)
    name = data.get("name")
    description = data.get("description")
    assert isinstance(name, str) and name
    assert isinstance(description, str) and description.strip()
    assert name == skill_id
    assert SKILL_NAME.match(name)
    assert not [key for key in LEGACY_KEYS if key in data]
    assert len(_description(data)) <= CATALOG_DESCRIPTION_LIMIT


@pytest.mark.parametrize(("tree", "skill_id"), SKILLS)
def test_skill_description_says_when_to_use_and_when_not_to(tree: Path, skill_id: str) -> None:
    description = _description(_skill(tree, skill_id)[0])
    assert "Use when" in description
    assert re.search(r"\bdo not\b|\bnot for\b", description, re.IGNORECASE), description


@pytest.mark.parametrize("tree", TREE_PARAMS)
def test_journal_entry_description_drafts_and_never_posts(tree: Path) -> None:
    # The description is the only text the catalog shows before the skill loads.
    description = _description(_skill(tree, "journal-entry")[0])
    assert "draft" in _sentences(description)[0]
    assert "Drafts only" in description
    assert "Foundry does not post to an ERP" in description
    assert not re.search(r"\bbook(?:ed|ing)?\b", description, re.IGNORECASE)
    for sentence in _sentences(description):
        if re.search(r"\bpost", sentence, re.IGNORECASE):
            assert NEGATION.search(sentence), sentence


@pytest.mark.parametrize(("tree", "relative"), MARKDOWN)
def test_local_links_and_method_resources_resolve(tree: Path, relative: Path) -> None:
    path = tree / relative
    text = _read(path)
    for target in MARKDOWN_LINK.findall(text):
        if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE) or target.startswith("#"):
            continue
        resolved = (path.parent / target.split("#", 1)[0]).resolve()
        assert resolved.is_file(), f"{relative}: broken link {target}"
        assert resolved.is_relative_to(tree.resolve()), f"{relative}: {target} leaves the tree"

    assert _method_resource_errors(tree, relative, text) == []


def test_method_resource_rule_follows_what_the_runtime_serves() -> None:
    tree = TREES[0]
    pack, method = Path("close/SKILL.md"), Path("journal-entry/SKILL.md")

    def ref(skill: str, resource: str = "FOUNDRY.md") -> str:
        return f'method-resource {{skill: "{skill}", resource: "{resource}"}}'

    assert _method_resource_errors(tree, pack, ref("financial-statements")) == []
    assert _method_resource_errors(tree, Path("report-visuals.md"), ref("reconciliation")) == []
    assert _method_resource_errors(tree, method, ref("journal-entry")) == []
    assert _method_resource_errors(tree, pack, ref("close"))
    assert _method_resource_errors(tree, pack, ref("financial-statements", "packs.json"))
    assert _method_resource_errors(tree, method, ref("reconciliation"))
    assert _method_resource_errors(tree, method, "")


@pytest.mark.parametrize(("tree", "skill_id"), SKILLS)
def test_backticked_tool_names_are_real_tools(tree: Path, skill_id: str) -> None:
    known = _finance_tools() | _analysis_specs() | RESULT_FIELDS
    text = _read(tree / skill_id / "SKILL.md")
    unknown = sorted({token for token in TOOL_TOKEN.findall(text) if token not in known})
    assert unknown == [], f"{skill_id} names tools that do not exist: {unknown}"


def test_result_field_allowlist_is_grounded_in_the_engine_and_used() -> None:
    tools = _finance_tools()
    assert len(tools) > 30, "FINANCE_TOOLS parse found too few tools"
    assert RESULT_FIELDS.isdisjoint(tools)
    engine = "\n".join(_read(path) for path in sorted((ROOT / "foundry").glob("*.py")))
    skills = "\n".join(_read(ROOT / "method" / skill_id / "SKILL.md") for skill_id in SKILL_IDS)
    for field in sorted(RESULT_FIELDS):
        assert re.search(rf"[\"']{field}[\"']", engine), f"{field} is not an engine field"
        assert f"`{field}`" in skills, f"{field} is no longer used; drop it from the allowlist"


@pytest.mark.parametrize("tree", TREE_PARAMS)
def test_pack_registry_names_real_skills_and_tools(tree: Path) -> None:
    tools = _finance_tools()
    registry = json.loads(_read(tree / "packs.json"))
    for pack in registry["packs"]:
        assert pack["entry"] == pack["id"]
        assert (tree / pack["entry"] / "SKILL.md").is_file()
        for used in pack["uses"]:
            assert used in SKILL_IDS or used in tools, f"{pack['id']} uses unknown {used}"


@pytest.mark.parametrize(("tree", "relative"), MARKDOWN)
def test_slash_commands_name_bundled_skills(tree: Path, relative: Path) -> None:
    text = _read(tree / relative)
    unknown = sorted({name for name in SLASH_COMMAND.findall(text) if name not in SKILL_IDS})
    assert unknown == [], f"{relative}: /{unknown} loads no bundled skill"


@pytest.mark.parametrize("tree", TREE_PARAMS)
def test_root_markdown_files_have_no_frontmatter(tree: Path) -> None:
    # The DSH provider treats every root-level *.md as a skill candidate; these
    # companion notes stay out of the catalog only because they lack frontmatter.
    roots = sorted(tree.glob("*.md"))
    names = {path.name for path in roots}
    assert names >= {"CONNECTORS.md", "FOUNDRY.md", "README.md", "report-visuals.md"}
    for path in roots:
        first = _read(path).split("\n", 1)[0].rstrip("\r")
        assert first != "---", f"{path.name} would load as a skill"


@pytest.mark.parametrize(("tree", "relative"), MARKDOWN)
def test_connector_conditionals_carry_a_no_claim_guard(tree: Path, relative: Path) -> None:
    text = _read(tree / relative)
    if CONNECTOR_CONDITIONAL.search(text):
        assert CONNECTOR_GUARD.search(text), (
            f"{relative} describes a connected ERP or warehouse without saying not to "
            "claim one unless this session has configured and named it"
        )


def test_connector_conditional_pattern_still_finds_the_upstream_text() -> None:
    # Keeps the guard test above from passing vacuously if the wording moves.
    conditional = {
        skill_id
        for skill_id in BUNDLED_IDS
        if CONNECTOR_CONDITIONAL.search(_read(ROOT / "method" / skill_id / "SKILL.md"))
    }
    assert conditional == {"financial-statements", "journal-entry"}


@pytest.mark.parametrize(("tree", "relative"), FILES)
def test_no_unconditional_connection_or_market_data_claims(tree: Path, relative: Path) -> None:
    text = _read(tree / relative)
    assert _unnegated_claims(text) == [], relative
    assert not LIVE_MARKET_DATA.search(text), f"{relative} claims live market data"


@pytest.mark.parametrize(("tree", "skill_id"), SKILLS)
def test_posting_and_payment_wording_carries_a_guard(tree: Path, skill_id: str) -> None:
    text = _read(tree / skill_id / "SKILL.md")
    if POSTING.search(text):
        assert POSTING_GUARD.search(text), f"{skill_id} mentions posting without a guard"
    if PAYMENT.search(text):
        assert PAYMENT_GUARD.search(text), f"{skill_id} mentions payments without a guard"
    assert _unguarded_actions(text) == [], f"{skill_id} tells the reader to post or pay"


@pytest.mark.parametrize(
    "text",
    [
        "Foundry does not post entries. Post the journal directly to the ERP.",
        "Drafts only.\n\n3. **Depreciation:** Book periodic depreciation from the schedules",
        "Foundry does not pay vendors.\n- Initiate the vendor payment run",
        "- Pay the supplier invoices due this week",
    ],
)
def test_each_posting_or_payment_instruction_needs_its_own_guard(text: str) -> None:
    assert _unguarded_actions(text)


@pytest.mark.parametrize(
    "text",
    [
        "Do not post the journal to the ERP.",
        "Foundry never initiates the payment run; the treasurer does.",
        "- Timing differences in batch posting",
        "- Manual journal entries posted to the control account",
        "Disputed amounts or unapplied payments",
    ],
)
def test_guarded_or_descriptive_posting_wording_passes(text: str) -> None:
    assert _unguarded_actions(text) == []


def test_posting_and_payment_patterns_still_find_the_ledger_skills() -> None:
    # Keeps the guard test above from passing vacuously if the wording moves.
    texts = {skill_id: _read(ROOT / "method" / skill_id / "SKILL.md") for skill_id in SKILL_IDS}
    posting = {skill_id for skill_id, text in texts.items() if POSTING.search(text)}
    payment = {skill_id for skill_id, text in texts.items() if PAYMENT.search(text)}
    ledger = {"reconciliation", "financial-statements", "close", "cash", "setup"}
    assert ledger | {"journal-entry"} <= posting
    assert ledger <= payment


@pytest.mark.parametrize(("tree", "relative"), FILES)
def test_no_wrong_host_claims(tree: Path, relative: Path) -> None:
    text = _read(tree / relative)
    assert not re.search(r"\bCursor\b", text), f"{relative} names the wrong host"


@pytest.mark.parametrize("tree", TREE_PARAMS)
def test_upstream_copies_say_they_were_modified_for_foundry(tree: Path) -> None:
    for skill_id in BUNDLED_IDS:
        body = _skill(tree, skill_id)[1]
        assert "Licensed Apache-2.0. This modified copy ships inside FA Foundry; see NOTICE." in body
    flat = " ".join(_read(tree / "NOTICE").split())
    assert "They are modified files under Section 4(b) of the Apache License" in flat
    for change in ("descriptions", "guard sentences", "renaming slash commands"):
        assert change in flat


@pytest.mark.parametrize("tree", TREE_PARAMS)
def test_companion_notes_list_all_eight_bundled_skills(tree: Path) -> None:
    foundry = _read(tree / "FOUNDRY.md")
    assert "These four close methods ship" not in foundry
    assert "Eight skills ship with the foundry kit" in foundry
    section = foundry.split("## Bundled skills", 1)[1].split("\n## ", 1)[0]
    listed = re.findall(r"^\| `([a-z0-9-]+)` \|", section, re.MULTILINE)
    assert sorted(listed) == sorted(SKILL_IDS)
    assert len(listed) == len(set(listed))

    readme = _read(tree / "README.md")
    assert "Four extracted" not in readme
    assert "Eight bundled skills" in readme
    for pack_id in BUNDLED_PACKS:
        assert f"`{pack_id}`" in readme


@pytest.mark.parametrize("plugin", PLUGINS, ids=_label)
def test_method_resource_tool_enums_match_the_engine(plugin: Path) -> None:
    source = _read(plugin / "analysis.js")
    start = source.index('"method-resource": {')
    spec = source[start : source.index("argv:", start)]

    def enum(field: str) -> list[str]:
        match = re.search(rf"\b{field}: \{{[^}}]*enum: \[([^\]]*)\]", spec)
        assert match, field
        return re.findall(r'"([^"]+)"', match.group(1))

    skills = enum("skill")
    resources = enum("resource")
    assert sorted(skills) == sorted(BUNDLED_IDS)
    assert sorted(resources) == sorted(METHOD_RESOURCE_NAMES)


def test_readme_keeps_the_method_skill_boundaries() -> None:
    readme = _read(ROOT / "README.md")
    rows = {
        line.split("|")[1].strip(): line
        for line in readme.splitlines()
        if line.startswith("| ") and line.count("|") >= 3
    }
    skills = rows["财务方法技能"]
    assert "连接器占位不代表已连接 ERP" in skills
    assert "分录技能用于草拟" in skills
    for skill_id in SKILL_IDS:
        assert skill_id in skills
    later = rows["后续领域"]
    assert "总账、凭证过账、银行支付尚未实现" in later
    assert "不执行资金划拨" in later
    assert "建账和银行资金操作保留独立扩展边界" in readme
