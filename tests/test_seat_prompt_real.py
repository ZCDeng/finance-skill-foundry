"""What a finance seat's model is actually shown, on a real DSH boot.

An exported analysis session (2026-10-08) showed the model 309 skills, nearly all
from the manager's own ~/.agents/skills, and a system prompt that opened with the
harness's developer notes (the source checkout, HMR, `pnpm run dev:web`). This
boots the web profile with a deterministic adapter, a personal skills root that
holds a `close` of its own, and reads back the first request.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from foundry.harness import install_presets
from foundry.task import TaskStore
from test_real_load import WEB_SETTLE_SECONDS, ROOT, DSH_BIN, _dsh_args, _prepare, _probe_package, needs_dsh

SEAT_PROMPT_PROBE = r"""
export const name = 'foundry-seat-prompt-probe';
export const inject = ['tools', 'agentPresets', 'llm', 'agents'];
export function apply(ctx) {
  (async () => {
    const { LlmAdapter, createUserMessage } = await import(process.env.FOUNDRY_LLM_MODULE);
    const report = {system: null, messages: null};
    ctx.llm.registerAdapter(['foundry-seat-fixture'], new class extends LlmAdapter {
      async *stream(options) {
        if (report.system === null) {
          report.system = options.system;
          report.messages = JSON.stringify(options.messages);
        }
        const block = {type: 'text', text: 'OK'};
        yield {type: 'block-start', index: 0, blockType: 'text'};
        yield {type: 'block-end', index: 0, block};
        yield {type: 'finish', reason: {kind: 'stop'}};
      }
    }());
    await ctx.agentPresets.standingKeyFor('analysis');
    const handle = await ctx.agents.create({
      sessionId: 'seat-prompt-real',
      meta: {cwd: process.env.FOUNDRY_TEST_WORKSPACE, agentPreset: 'analysis'},
      agentOptions: {provider: 'foundry-seat-fixture', model: 'deterministic'},
      setup: async (agentCtx) => { await ctx.agentPresets.mount(agentCtx, 'analysis'); },
    });
    try {
      handle.agent.followup(createUserMessage({content: [{type: 'text', text: '看看资料'}], source: {kind: 'user'}}));
      await handle.agent.whenIdle();
      process.stdout.write('FOUNDRY_SEAT_PROMPT ' + JSON.stringify(report) + '\n');
    } finally {
      await handle.dispose();
    }
  })().catch(error => process.stdout.write('FOUNDRY_SEAT_PROMPT_ERROR ' + (error.stack ?? error.message) + '\n'));
}
"""


@needs_dsh
def test_analysis_seat_sees_shipped_methods_only_and_no_harness_dev_notes(tmp_path: Path) -> None:
    home = tmp_path / "dsh-home"
    _prepare(home, _probe_package(tmp_path / "probe", SEAT_PROMPT_PROBE), "web")
    install_presets(home)

    personal = tmp_path / "agents-home"
    for skill, text in (("close", "PERSONAL_CLOSE_SHADOW"), ("agent-reach", "PERSONAL_SKILL_LEAK")):
        (personal / "skills" / skill).mkdir(parents=True)
        (personal / "skills" / skill / "SKILL.md").write_text(
            f"---\nname: {skill}\ndescription: {text}\n---\n\n{text}\n", encoding="utf-8")

    var = tmp_path / "var"
    task = TaskStore(var).create(title="席位提示")
    task.record_session("seat-prompt-real", role="analysis")
    argv, env, cwd = _dsh_args(home, "--profile", "web", "--no-open")
    env.update({
        "FOUNDRY_VAR": str(var),
        "FOUNDRY_BIN": str(ROOT / ".venv" / "bin" / "foundry"),
        "FOUNDRY_LLM_MODULE": (Path(DSH_BIN).resolve().parents[2] / "dsh-llm" / "lib" / "index.js").as_uri(),
        "FOUNDRY_TEST_WORKSPACE": str(task.root / "analysis"),
        "DSH_AGENTS_HOME": str(personal),
    })
    log = tmp_path / "seat-prompt.log"
    with log.open("wb") as sink:
        child = subprocess.Popen(argv, stdout=sink, stderr=subprocess.STDOUT, env=env, cwd=cwd)
        try:
            deadline = time.monotonic() + WEB_SETTLE_SECONDS
            while time.monotonic() < deadline:
                output = log.read_text(encoding="utf-8", errors="replace")
                if "FOUNDRY_SEAT_PROMPT " in output or "FOUNDRY_SEAT_PROMPT_ERROR " in output:
                    break
                time.sleep(0.2)
        finally:
            child.terminate()
            try:
                child.wait(timeout=20)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=10)

    output = log.read_text(encoding="utf-8", errors="replace")
    assert "FOUNDRY_SEAT_PROMPT_ERROR " not in output, output[-12000:]
    lines = [line for line in output.splitlines() if line.startswith("FOUNDRY_SEAT_PROMPT ")]
    assert lines, output[-12000:]
    report = json.loads(lines[-1].split(" ", 1)[1])
    system, messages = report["system"], report["messages"]

    assert "财务经理的分析助手" in system
    assert "implementation checkout" not in system
    assert "HMR" not in system and "dev:web" not in system

    assert "financial-statements" in messages and "variance-analysis" in messages
    assert "PERSONAL_SKILL_LEAK" not in messages and "agent-reach" not in messages
    assert "PERSONAL_CLOSE_SHADOW" not in messages
