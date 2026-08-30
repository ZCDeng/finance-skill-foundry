"""Launching a Data Formulator this machine did not install.

A frozen bundle is a directory beside an application, not something on PATH, and
its own imports can only resolve from inside itself. Both facts change what the
kit has to be told and what it may assume.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from foundry import launch_formulator as lf


def test_a_named_binary_wins_over_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """There is nothing to find on PATH when the Formulator ships with the app."""
    fake = tmp_path / "bin" / "data_formulator"
    fake.parent.mkdir(parents=True)
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake.parent))
    assert lf.formulator_bin() == str(fake)

    frozen = tmp_path / "Resources" / "formulator" / "data_formulator"
    monkeypatch.setenv(lf.BIN_ENV, str(frozen))
    assert lf.formulator_bin() == str(frozen)


def test_the_resolver_is_shared_with_the_smoke_test(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two lookups that disagree would skip the real launch where it matters most.

    `host-smoke` used to re-scan PATH for the same names. On a machine carrying a
    frozen Formulator that scan finds nothing, so the smoke would take the
    spec-only branch on exactly the deployment whose launch is worth testing.
    """
    from foundry import host_profile

    source = Path(host_profile.__file__).read_text(encoding="utf-8")
    assert "FORMULATOR_BINS" not in source
    assert "formulator_bin()" in source


def test_the_child_is_told_not_to_fetch_a_cost_map(tmp_path: Path) -> None:
    """litellm reaches the network at import unless it is told the local copy will do.

    Up to five seconds of dead startup on a slow link, and an outright failure on
    a captive portal that answers with HTML. A frozen build has nowhere useful to
    cache the fetched copy either.
    """
    from tests.test_formulator_fence import _locked  # the fixture that locks a window

    _, window = _locked(tmp_path)
    spec = lf.launch_spec(window)
    assert spec["env"]["LITELLM_LOCAL_MODEL_COST_MAP"] == "true"


def test_identity_is_the_binary_the_launch_recorded(tmp_path: Path) -> None:
    """A frozen bundle under any name can still win, and prove it won.

    The home path stays the strong half: it is unique to the window, and a
    process serving somebody else's catalog cannot carry it. What the recorded
    binary adds is that the weaker half stops being a claim about a file name.
    """
    home = tmp_path / "home"
    home.mkdir()
    frozen = "/Applications/Foundry.app/Contents/Resources/formulator/fnd-df"

    # No record yet: an older home falls back to the name check.
    assert lf._command_matches_window(f"data_formulator --data-dir {home}", home)
    assert not lf._command_matches_window(f"{frozen} --data-dir {home}", home)

    (home / "binary").write_text(f"{frozen}\n")
    assert lf._command_matches_window(f"{frozen} --data-dir {home}", home)
    # And the name check no longer lets a different process through.
    assert not lf._command_matches_window(f"data_formulator --data-dir {home}", home)


def test_the_home_is_still_required(tmp_path: Path) -> None:
    """The strong half, unchanged: another window's Formulator is not this one."""
    home = tmp_path / "home"
    home.mkdir()
    (home / "binary").write_text("/x/data_formulator\n")
    assert not lf._command_matches_window("/x/data_formulator --data-dir /somewhere/else", home)
    assert not lf._command_matches_window("", home)


def test_the_plugin_dir_is_what_a_frozen_child_must_import(tmp_path: Path) -> None:
    """Why the frozen bundle has to carry the kit.

    `DF_PLUGIN_DIR` names a loose `.py` file that Data Formulator imports through
    `spec_from_file_location`. A frozen app can do that -- but it ignores
    PYTHONPATH, so that file's own `foundry.*` imports resolve only from inside
    the bundle. This pins what the file actually imports, so a freeze recipe that
    stopped carrying it fails here rather than by silently offering no connector.
    """
    from tests.test_formulator_fence import _locked

    _, window = _locked(tmp_path)
    spec = lf.launch_spec(window)
    plugin = Path(str(spec["env"]["DF_PLUGIN_DIR"])) / "locked_catalog_data_loader.py"
    body = plugin.read_text(encoding="utf-8")
    assert "from foundry" in body or "import foundry" in body
    assert "data_formulator" in body


def test_the_launch_records_its_binary_before_spawning(tmp_path: Path) -> None:
    """Recorded before the spawn, not after readiness.

    A CLI killed during the eight-second readiness wait leaves a detached child.
    The pid file is what lets stop-formulator find it; the binary file is what
    lets stop-formulator prove it is the right one.
    """
    source = Path(lf.__file__).read_text(encoding="utf-8")
    write_binary = source.index("write_text_atomic(binary_path(window)")
    spawn = source.index("proc = subprocess.Popen(")
    assert write_binary < spawn


def test_a_failed_launch_keeps_what_the_child_said(tmp_path: Path) -> None:
    """The purge takes the home, and the log lives in it.

    A frozen bundle can die during startup on a data file its recipe forgot to
    collect. The refusal says `did not become ready`; the traceback naming the
    file is in `formulator.log`, inside the directory the cleanup then deletes.
    Diagnosing that once cost a round trip, which is the whole argument for
    keeping the copy.

    Driven directly rather than through a launch: the copy races a child that has
    not flushed yet, and a test that sometimes finds an empty log is worse than
    no test. The ordering that makes it work in a real launch is asserted below.
    """
    from tests.test_formulator_fence import _locked

    _, window = _locked(tmp_path)
    home = window.formulator_home
    home.mkdir(parents=True, exist_ok=True)
    (home / "formulator.log").write_text("FileNotFoundError: azure/kusto/data/kcsb.json\n")

    lf._keep_failure_log(window)
    kept = lf.failed_log_path(window)
    assert kept.is_file()
    assert "kcsb.json" in kept.read_text()

    # Beside the home, not in it, so the purge still leaves nothing a later
    # launch could mistake for live state.
    lf.purge_formulator_home(window)
    assert not home.exists()
    assert kept.is_file()


def test_an_empty_log_is_not_kept(tmp_path: Path) -> None:
    """A zero-byte file explains nothing and would only be clutter."""
    from tests.test_formulator_fence import _locked

    _, window = _locked(tmp_path)
    window.formulator_home.mkdir(parents=True, exist_ok=True)
    (window.formulator_home / "formulator.log").write_text("")
    lf._keep_failure_log(window)
    assert not lf.failed_log_path(window).exists()


def test_the_log_is_copied_before_the_purge_deletes_it(tmp_path: Path) -> None:
    """Ordering, which is the half the direct test above cannot show."""
    source = Path(lf.__file__).read_text(encoding="utf-8")
    cleanup = source[source.index("    except BaseException:"):]
    assert cleanup.index("_keep_failure_log(window)") < cleanup.index("stop_lease(window)")


def test_a_frozen_bundle_gets_a_cold_start_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """Eight seconds is right for a process starting and wrong for one being paged in.

    Measured on this kit's own build: 43s to answer cold, 2.4s warm. The long
    bound costs nothing when a launch is broken, because `_ready` returns as soon
    as the child exits.
    """
    monkeypatch.delenv(lf.BIN_ENV, raising=False)
    monkeypatch.delenv(lf.TIMEOUT_ENV, raising=False)
    assert lf.ready_timeout() == lf.READY_TIMEOUT

    monkeypatch.setenv(lf.BIN_ENV, "/Applications/Foundry.app/Contents/Resources/formulator/data_formulator")
    assert lf.ready_timeout() == lf.FROZEN_READY_TIMEOUT

    monkeypatch.setenv(lf.TIMEOUT_ENV, "45")
    assert lf.ready_timeout() == 45.0


def test_a_nonsense_timeout_is_refused_rather_than_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    from foundry.errors import LockRefused

    monkeypatch.setenv(lf.TIMEOUT_ENV, "soon")
    with pytest.raises(LockRefused, match="is not a number"):
        lf.ready_timeout()
    monkeypatch.setenv(lf.TIMEOUT_ENV, "0")
    with pytest.raises(LockRefused, match="must be positive"):
        lf.ready_timeout()


def test_the_early_readiness_exit_is_what_makes_the_long_bound_safe() -> None:
    """A crashed child fails at once, whatever the bound is."""
    source = Path(lf.__file__).read_text(encoding="utf-8")
    body = source[source.index("def _ready("):]
    body = body[: body.index("\ndef ")]
    assert body.index("proc.poll() is not None") < body.index("urlopen")
