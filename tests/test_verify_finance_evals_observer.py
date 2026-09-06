from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


def run_observer(tmp_path: Path, *, fail_state: bool = False, max_buffer_bytes: str | None = None) -> dict:
    if NODE is None:
        pytest.skip("node is unavailable")
    probe = tmp_path / "probe"
    probe.mkdir()
    (probe / "index.mjs").write_text((ROOT / "tools" / "verify_finance_evals.mjs").read_text(encoding="utf-8"), encoding="utf-8")
    report = tmp_path / "report.json"
    dsh_root = tmp_path / "dsh-root"
    llm = dsh_root / "node_modules" / "@deepseek-ai" / "dsh-llm" / "lib"
    llm.mkdir(parents=True)
    (llm / "index.js").write_text("export const createUserMessage = (message) => message;\n", encoding="utf-8")
    config = {
        "report": str(report),
        "dshRoot": str(dsh_root),
        "ids": [],
        "timeoutSeconds": 1,
        "cases": [{
            "id": "F01",
            "sessionId": "session-f01",
            "taskId": "task-f01",
            "workspace": str(tmp_path),
            "inputSha256": "abc",
            "question": "解释利润",
        }],
    }
    (probe / "config.json").write_text(json.dumps(config), encoding="utf-8")
    foundry = tmp_path / "foundry.mjs"
    foundry.write_text(
        """
#!/usr/bin/env node
const args = process.argv.slice(2);
const hasCommand = (name) => args.includes(name);
if (hasCommand('record-session')) {
  process.stdout.write(JSON.stringify({recorded: true}));
} else if (hasCommand('analysis-state')) {
  if (process.env.FAIL_STATE === '1') {
    console.error('analysis-state failed marker');
    process.exit(7);
  }
  const body = 'x'.repeat(1_250_000);
  process.stdout.write(JSON.stringify({drafts: [{id: 'draft-large', body}], runs: [{id: 'run-1'}, {id: 'run-2'}]}));
} else {
  console.error(`unexpected foundry args: ${JSON.stringify(args)}`);
  process.exit(2);
}
""".strip(),
        encoding="utf-8",
    )
    foundry.chmod(0o755)
    driver = tmp_path / "driver.mjs"
    driver.write_text(
        f"""
import {{ apply }} from {json.dumps((probe / 'index.mjs').as_uri())};
const events = [];
const agent = {{
  id: 'session-f01',
  session: {{ events, deriveMessages: () => [] }},
  followup: () => {{}},
  whenIdle: async () => {{}},
}};
const ctx = {{
  agentPresets: {{ standingKeyFor: async () => 'analysis', mount: async () => {{}} }},
  agentDefaultModel: {{ currentSelection: () => ({{ provider: 'fake', model: 'fake-model' }}) }},
  agents: {{ create: async () => ({{ agent, dispose: async () => {{}} }}) }},
  tools: {{ execute: async () => ({{ isError: false, value: {{ provider: 'fake', resourceBase: 'fake', content: '' }} }}) }},
  skills: {{ snapshot: async () => ({{ skills: [], complete: true }}) }},
}};
apply(ctx);
for (let i = 0; i < 100; i += 1) {{
  await new Promise((resolve) => setTimeout(resolve, 20));
  try {{
    const report = JSON.parse(await import('node:fs/promises').then(fs => fs.readFile({json.dumps(str(report))}, 'utf8')));
    if (report.status !== 'running') {{
      console.log(JSON.stringify(report));
      process.exit(0);
    }}
  }} catch {{}}
}}
console.error('observer did not finish');
process.exit(1);
""",
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "FOUNDRY_BIN": str(foundry),
        "FOUNDRY_VAR": str(tmp_path / "var"),
        **({"FAIL_STATE": "1"} if fail_state else {}),
    }
    if max_buffer_bytes is not None:
        env["FOUNDRY_OBSERVER_MAX_BUFFER_BYTES"] = max_buffer_bytes
    result = subprocess.run(
        [NODE, str(driver)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=10,
        env=env,
    )
    assert result.returncode == 0, result.stdout[-1000:] + result.stderr[-1000:]
    return json.loads(report.read_text(encoding="utf-8"))


def test_finance_eval_observer_reads_large_analysis_state_without_enobufs(tmp_path: Path) -> None:
    report = run_observer(tmp_path)
    case = report["cases"][0]
    assert report["status"] == "completed"
    assert "state_error" not in case
    assert case["final_draft"]["id"] == "draft-large"
    assert len(case["final_draft"]["body"]) == 1_250_000
    assert case["runs_seen"] == 2


def test_finance_eval_observer_records_analysis_state_failure_on_case(tmp_path: Path) -> None:
    report = run_observer(tmp_path, fail_state=True)
    case = report["cases"][0]
    assert report["status"] == "completed"
    assert case["completed"] is True
    assert "analysis-state failed marker" in case["state_error"]
    assert case.get("final_draft") is None


def test_finance_eval_observer_rejects_invalid_buffer_override(tmp_path: Path) -> None:
    report = run_observer(tmp_path, max_buffer_bytes="Infinity")
    case = report["cases"][0]
    assert report["status"] == "completed"
    assert case["completed"] is True
    assert "state_error" not in case
    assert case["final_draft"]["id"] == "draft-large"


def test_finance_eval_observer_keeps_case_completed_when_analysis_state_exceeds_buffer(tmp_path: Path) -> None:
    report = run_observer(tmp_path, max_buffer_bytes="1024")
    case = report["cases"][0]
    assert report["status"] == "completed"
    assert case["completed"] is True
    assert "ENOBUFS" in case["state_error"]
    assert case.get("final_draft") is None
