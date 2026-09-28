"""Bundled guidance is readable in an analysis session without general file access."""

import hashlib
import json

import pytest

from foundry.cli import main
from foundry.method_skills import method_root
from foundry.task import TaskStore


@pytest.mark.parametrize("resource", ["FOUNDRY.md", "report-visuals.md"])
def test_analysis_reads_guidance_without_a_window(tmp_path, capsys, resource):
    var = tmp_path / "var"
    task = TaskStore(var).create(title="方法资源")
    task.record_session("analysis-guidance", role="analysis")
    args = ["--var", str(var), "--session", "analysis-guidance", "method-resource",
            "--skill", "variance-analysis", "--resource", resource]
    assert main(args) == 0
    result = json.loads(capsys.readouterr().out)
    source = method_root() / resource
    assert result["skill"] == "variance-analysis"
    assert result["resource"] == resource
    assert result["content"] == source.read_text(encoding="utf-8")
    assert result["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert task.windows() == []


@pytest.mark.parametrize("skill,resource", [
    ("variance-analysis", "../../.credentials.yaml"),
    ("variance-analysis", "/etc/passwd"),
    ("variance-analysis", "SKILL.md"),
    ("missing-skill", "FOUNDRY.md"),
])
def test_resource_lookup_cannot_read_arbitrary_files(tmp_path, capsys, skill, resource):
    var = tmp_path / "var"
    task = TaskStore(var).create(title="限定资源")
    task.record_session("guidance-scope", role="analysis")
    assert main(["--var", str(var), "--session", "guidance-scope", "method-resource",
                 "--skill", skill, "--resource", resource]) == 3
    assert not capsys.readouterr().out


def test_unknown_session_cannot_use_the_resource_tool(tmp_path, capsys):
    var = tmp_path / "var"
    assert main(["--var", str(var), "--session", "unknown", "method-resource",
                 "--skill", "variance-analysis", "--resource", "FOUNDRY.md"]) == 3
    assert "unknown session" in capsys.readouterr().err
    assert not var.exists()
