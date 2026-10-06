from __future__ import annotations

import json
from pathlib import Path

import pytest
from openpyxl import Workbook

from foundry.cli import main
from foundry.errors import FoundryError, LockRefused, QueryRefused
from foundry.harness import DROP_EXTS, LINE_LEAKS, file_upload_companion, harness_text, map_drop
from foundry.host_profile import REQUIRED_TOOLS, HostProfile
from foundry.window import WindowStore

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "dsh-plugin" / "package.json"
OVERLAY = ROOT / "dsh-plugin" / "file-upload.overlay.yml"
FIXTURES = ROOT / "fixtures" / "period-smoke"


def _xlsx(path: Path, headers: list[str], rows: list[list[object]]) -> Path:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(headers)
    for row in rows:
        ws.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def test_companion_is_pinned_input_drop() -> None:
    companion = file_upload_companion()
    declared = json.loads(PACKAGE.read_text())["dsh"]["foundry"]["companions"]["file-upload"]
    assert companion == declared
    assert companion["package"] == "dsh-file-upload"
    assert companion["version"] == "0.4.3"
    assert companion["role"] == "input-drop"
    assert LINE_LEAKS <= set(companion["omitTools"])
    assert companion["config"]["allowedExtensions"] == ["xlsx", "csv", "json"]
    assert companion["config"]["inlineTextLimit"] == 0
    assert OVERLAY.is_file()
    overlay = OVERLAY.read_text()
    assert "read_document" in overlay
    assert "input drop" in overlay


def test_period_and_f3_omit_read_document() -> None:
    foundry = json.loads(PACKAGE.read_text())["dsh"]["foundry"]
    assert "read_document" in foundry["profiles"]["period"]["omit"]
    assert "read_document" in foundry["profiles"]["f3"]["omit"]
    assert ".dsh-uploads" in foundry["profiles"]["f3"]["deny_paths"]


def test_startup_fails_if_read_document_mounted() -> None:
    with pytest.raises(FoundryError, match="line leak"):
        HostProfile("period", [*REQUIRED_TOOLS, "read_document"])


def test_f3_denies_read_document_and_upload_path(tmp_path: Path) -> None:
    f3 = HostProfile.f3()
    with pytest.raises(QueryRefused, match="read_document"):
        f3.execute(WindowStore(tmp_path / "var").create(), "read_document")
    assert f3.deny_path(tmp_path / ".dsh-uploads" / "coa.xlsx") is True


def test_map_drop_uses_reserved_stems(tmp_path: Path) -> None:
    drop = tmp_path / "uploads"
    _xlsx(drop / "coa.xlsx", ["account_code", "account_name"], [["1001", "Cash"]])
    _xlsx(drop / "aux.xlsx", ["dim_id", "dim_name", "member_id", "member_name"], [["unit", "Unit", "OU1", "North"]])
    _xlsx(drop / "map.xlsx", ["source_account_code", "analysis_node_id", "analysis_node_name"], [["1001", "cash", "Cash"]])
    _xlsx(drop / "gl.xlsx", ["account_code", "amount"], [["1001", 70]])
    (drop / "notes.txt").write_text("ignore")
    (drop / "questions.json").write_text("[]")
    mapped = map_drop(drop)
    assert mapped.coa == drop / "coa.xlsx"
    assert mapped.aux == drop / "aux.xlsx"
    assert mapped.map == drop / "map.xlsx"
    assert mapped.units is None
    assert mapped.named == [{"id": "gl", "path": drop / "gl.xlsx"}]
    assert "notes.txt" in mapped.skipped


def test_map_drop_refuses_duplicate_stems(tmp_path: Path) -> None:
    drop = tmp_path / "uploads"
    _xlsx(drop / "gl.xlsx", ["account_code", "amount"], [["1001", 1]])
    (drop / "gl.csv").write_text("account_code,amount\n1001,2\n")
    with pytest.raises(LockRefused, match="two files"):
        map_drop(drop)


def test_map_drop_refuses_symlinks(tmp_path: Path) -> None:
    drop = tmp_path / "uploads"
    drop.mkdir()
    outside = tmp_path / "outside.csv"
    outside.write_text("account_code,amount\n1001,1\n", encoding="utf-8")
    (drop / "gl.csv").symlink_to(outside)

    with pytest.raises(LockRefused, match="symlink"):
        map_drop(drop)


def test_map_drop_refuses_a_symlinked_drop_root(tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere"
    _xlsx(outside / "gl.xlsx", ["account_code", "amount"], [["1001", 1]])
    drop = tmp_path / "uploads"
    drop.symlink_to(outside, target_is_directory=True)

    with pytest.raises(LockRefused, match="symlink"):
        map_drop(drop)


def test_import_from_upload_drop_only(tmp_path: Path) -> None:
    drop = tmp_path / "uploads"
    _xlsx(drop / "coa.xlsx", ["account_code", "account_name"], [["1001", "Cash"]])
    _xlsx(drop / "units.xlsx", ["unit_id", "unit_name"], [["OU1", "North"]])
    _xlsx(drop / "gl.xlsx", ["account_code", "amount"], [["1001", 100]])
    store = WindowStore(tmp_path / "var")
    window = store.create()
    window.import_tables(drop_dir=drop)
    window.lock()
    assert "gl" in window.table_names()
    assert "coa" in window.table_names()
    assert "units" in window.table_names()


def test_explicit_named_does_not_absorb_drop_extras() -> None:
    from foundry.harness import merge_import_sources

    mapped = map_drop(FIXTURES)
    assert mapped.coa == FIXTURES / "coa.xlsx"
    assert {item["id"] for item in mapped.named} >= {"gl", "ar", "notes"}
    store_named = [{"id": "gl", "path": FIXTURES / "gl.xlsx"}]
    resolved = merge_import_sources(
        coa=None,
        named=store_named,
        aux=None,
        map=None,
        units=None,
        drop_dir=FIXTURES,
    )
    assert resolved.named == store_named
    assert resolved.coa == FIXTURES / "coa.xlsx"


def test_cli_harness_prints_pin(tmp_path: Path) -> None:
    assert main(["--var", str(tmp_path / "var"), "harness"]) == 0
    text = harness_text()
    assert "dsh-file-upload@0.4.3" in text
    assert "input-drop" in text
    assert "read_document" in text


def test_cli_import_from_drop_dir(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    drop = tmp_path / "uploads"
    _xlsx(drop / "coa.xlsx", ["account_code", "account_name"], [["1001", "Cash"]])
    _xlsx(drop / "gl.xlsx", ["account_code", "amount"], [["1001", 40]])
    var = tmp_path / "var"
    assert main(["--var", str(var), "create"]) == 0
    assert main(["--var", str(var), "import", "--drop-dir", str(drop)]) == 0
    capsys.readouterr()
    assert (var / "current").exists()


def test_drop_exts_match_catalog() -> None:
    assert DROP_EXTS == {".xlsx", ".csv", ".json"}


def test_import_json_from_upload_drop(tmp_path: Path) -> None:
    drop = tmp_path / "uploads"
    _xlsx(drop / "coa.xlsx", ["account_code", "account_name"], [["1001", "Cash"]])
    (drop / "gl.json").write_text(json.dumps([{"account_code": "1001", "amount": "12.50"}]))
    window = WindowStore(tmp_path / "var").create()
    window.import_tables(drop_dir=drop)
    window.lock()
    assert window.query("SELECT SUM(amount) FROM gl")[0][0].to_eng_string() == "12.50"


def test_every_preset_tells_the_picker_what_it_is():
    """A preset with no `preset.yml` lists as its bare id and "No description".

    The runtime's picker reads display text from `preset.yml` beside
    `agent.cordis.yml` and renders the id when there is none. That is the least
    useful thing to say about `period`, which is the preset deciding whether a
    model can read around a locked window, and about `f3`, which offers one
    verb. `install_presets` copies the whole directory, so the file only has to
    exist here.
    """
    import yaml

    from foundry.harness import preset_dir, preset_ids

    for preset_id in preset_ids():
        path = preset_dir() / preset_id / "preset.yml"
        assert path.is_file(), f"{preset_id} has no preset.yml"
        meta = yaml.safe_load(path.read_text())
        assert meta.get("name"), f"{preset_id} preset.yml has no name"
        assert meta.get("description"), f"{preset_id} preset.yml has no description"


def test_preset_display_text_travels_with_the_preset(tmp_path):
    """The copy the runtime reads has to carry it, not just the checkout."""
    from foundry.harness import install_presets, preset_ids

    install_presets(tmp_path)
    for preset_id in preset_ids():
        assert (tmp_path / ".agent-presets" / preset_id / "preset.yml").is_file()


# --- what the period preset may carry, and the rule that decides it --------

def _period_rows():
    """Every row id the period preset composes, groups flattened."""
    import yaml

    from foundry.harness import preset_dir

    def ids(rows, out):
        for row in rows:
            out.append(row["id"])
            if isinstance(row.get("config"), list):
                ids(row["config"], out)
        return out

    text = (preset_dir() / "period" / "agent.cordis.yml").read_text()
    return ids(yaml.safe_load(text), [])


def test_period_omits_exactly_what_can_reach_the_books():
    """Reachability is the rule, not tidiness.

    The fence exists so a figure on the brief can be traced to the locked
    catalog. A row earns removal by being a path to the archived workbooks, and
    the earlier list was broader than that -- it removed the model's ability to
    look anything up at all, which protected nothing and meant an industry
    benchmark had to be copied out of a spreadsheet with no source on it.
    """
    rows = _period_rows()
    for reaches_files in [
        "tool-bash",
        "tool-pwsh",
        "tool-fs",
        "tool-fs-search",
        "tool-subagent",
        "tool-subagent-fork",
        "tool-workflow",
        "tool-ralph",
    ]:
        assert reaches_files not in rows, f"{reaches_files} can reach the books"


def test_period_keeps_what_cannot():
    # None of these can read a file. `tool-web` ships from upstream with
    # `fetch: false`, so it is search and its snippets.
    rows = _period_rows()
    for harmless in ["tool-goal", "plan-mode", "tool-web", "tool-skill", "tool-ask-user"]:
        assert harmless in rows, f"{harmless} was dropped without reaching anything"


def test_web_stays_search_only():
    """`fetch: true` would turn a snippet into an arbitrary URL read.

    Still not a path to the books, but a different decision from the one made
    here, and one that should be made deliberately rather than inherited.
    """
    import yaml

    from foundry.harness import preset_dir

    rows = yaml.safe_load((preset_dir() / "period" / "agent.cordis.yml").read_text())
    web = next(row for row in rows if row["id"] == "tool-web")
    assert web["config"]["fetch"] is False


def test_every_copied_row_keeps_the_config_upstream_requires():
    """The mount failure this pins was real, and immediate.

    `plan-mode` was copied across without its `section`, and the runtime
    refused the whole preset: `PlanModeConfig needs a non-empty section`. A
    preset is derived from `standard` by deletion, so a surviving row keeps the
    configuration upstream gives it -- trimming one is how a preset stops
    mounting.
    """
    import yaml

    from foundry.harness import preset_dir

    rows = yaml.safe_load((preset_dir() / "period" / "agent.cordis.yml").read_text())
    planning = next(row for row in rows if row["id"] == "planning")
    plan_mode = next(row for row in planning["config"] if row["id"] == "plan-mode")
    assert plan_mode["config"]["section"].strip()


def test_the_persona_does_not_claim_a_fence_that_moved():
    """The persona is what the model reads about its own limits.

    It said 不能上网 while the preset now carries search, and a persona that
    describes the wrong fence is worse than no persona: the model believes it.
    """
    import yaml

    from foundry.harness import preset_dir

    rows = yaml.safe_load((preset_dir() / "period" / "agent.cordis.yml").read_text())
    text = next(row for row in rows if row["id"] == "persona")["config"]["text"]
    assert "不能上网" not in text
    # And it has to say what the new capability may not become.
    assert "我重算" in text


def test_period_deletes_exactly_the_procedural_rows():
    """KTD11, as a test rather than a paragraph.

    A preset is derived from `standard` by deletion, and which rows go is the
    whole of the period fence. Named here so that adding one back is a visible
    decision rather than a copy-paste: a shell, a file tool, a background job or
    a subagent lets a session reach the archived workbook directly, and a figure
    obtained that way is indistinguishable in the brief from one the catalog
    produced. `tool-web` is not on this list -- what it returns can only enter a
    document through `record-reference`, which demands a source.
    """
    import yaml

    from foundry.harness import preset_dir

    rows = yaml.safe_load((preset_dir() / "period" / "agent.cordis.yml").read_text())
    ids = {row["id"] for row in rows}
    assert ids.isdisjoint(
        {"tool-bash", "tool-pwsh", "tool-fs", "tool-fs-search", "tool-jobs", "delegation"}
    )
    assert {"tool-web", "planning", "tool-todo", "tool-skill"} <= ids


def test_the_office_companion_cannot_ship_without_its_telemetry_switches():
    """Third-party plugin code runs with the operator's full privileges.

    Choosing that is the operator's call, and ours did not get to make it --
    they got the bundle inside a product. So the two switches are set on their
    behalf, and this is what notices if either goes missing. The published
    0.2.12 build already carries an empty endpoint in `lib/build-info.json`; a
    later version could bake one in, which is exactly the case this covers.
    """
    from foundry.harness import companion_env, office_companion

    companion = office_companion()
    assert companion["package"] == "dsh-univer-office"
    assert companion["role"] == "deliverable-surface"
    env = companion_env()
    assert env["DO_NOT_TRACK"] == "1"
    # Empty is not absent. The bundle reads this name as an override and treats
    # an empty string as "no endpoint"; leaving it unset falls back to whatever
    # the build baked in.
    assert env["UNIVER_TELEMETRY_ENDPOINT"] == ""


def test_a_companion_that_dropped_do_not_track_is_refused(monkeypatch):
    """The switch above is only worth having if losing it is loud."""
    import json

    import foundry.harness as harness_module
    from foundry.errors import FoundryError

    weakened = json.loads(json.dumps(harness_module.load_foundry_dsh()))
    weakened["companions"]["office"]["env"]["DO_NOT_TRACK"] = ""
    monkeypatch.setattr(harness_module, "load_foundry_dsh", lambda: weakened)
    with pytest.raises(FoundryError, match="DO_NOT_TRACK"):
        harness_module.office_companion()


def test_the_period_preset_masks_the_office_tools():
    """A companion's tools are global; a preset row cannot take away what it never mounted.

    The period fence is built by deleting rows from upstream's `standard`, and
    that only ever reached upstream's own tools. `dsh-univer-office` registers
    thirteen `univer_*` tools at profile level, so without a scope row they
    stand next to a locked window. `restrict` is the same seam `f3` uses, and
    restrictions intersect, so this narrows the close seat and leaves an
    authoring session on `standard` with all thirteen.
    """
    import yaml

    from foundry.harness import office_companion, preset_dir

    rows = yaml.safe_load((preset_dir() / "period" / "agent.cordis.yml").read_text())
    scope = next(row for row in rows if row["id"] == "finance-skill-foundry-period-scope")
    assert scope["name"] == "finance-skill-foundry-dsh/period-scope"

    declared = office_companion()["omitTools"]
    assert len(declared) == 13
    assert all(name.startswith("univer_") for name in declared)
    # The two that are reachability in the plain sense have to be in there.
    assert {"univer_execute", "univer_import"} <= set(declared)


def test_the_period_scope_masks_every_office_tool_not_only_the_listed_ones(tmp_path):
    """A companion release can add a `univer_*` tool the manifest does not list.

    0.2.14 added `univer_print_pdf`. The listed thirteen are the floor; any
    `univer_*` name registered when the scope applies is masked as well, and a
    guard refuses one that registers afterwards.
    """
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("node is unavailable")
    scope = Path(__file__).resolve().parents[1] / "dsh-plugin" / "period-scope.js"
    driver = tmp_path / "driver.mjs"
    driver.write_text(
        f'import {{ apply }} from "{scope.as_uri()}";\n'
        """
const restrictions = [], guards = [];
apply({tools: {
  schemas: () => [{name: 'univer_execute'}, {name: 'univer_print_pdf'}, {name: 'query-locked'}],
  restrict: (r) => restrictions.push(r), guard: (g) => guards.push(g)}});
process.stdout.write(JSON.stringify({deny: restrictions[0].deny,
  guards: [guards[0]({name: 'univer_later_tool'}), guards[0]({name: 'query-locked'}) ?? null]}));
"""
    )
    result = subprocess.run([node, str(driver)], text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)

    from foundry.harness import office_companion

    assert set(office_companion()["omitTools"]) | {"univer_print_pdf"} == set(out["deny"])
    assert "query-locked" not in out["deny"]
    assert out["guards"] == ["period cannot execute univer_later_tool", None]


def test_the_office_companion_names_where_it_can_reach():
    """A tool that fetches has to say what it fetches from.

    `univer_resources` downloads SVGs whose URLs come from
    `@univerjs-pro/cli-assets/manifest.json`, not from the plugin. Reading that
    manifest is the only way to know; these are the two hosts it holds, and
    naming them here is what makes the omission of that tool a decision rather
    than a guess.
    """
    from foundry.harness import office_companion

    assert office_companion()["egress"] == ["cdn.jsdelivr.net", "cdn.undraw.co"]
