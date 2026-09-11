from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from foundry.method_skills import BUNDLED_IDS, BUNDLED_PACKS, method_root

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


def _dsh_node_modules() -> Path:
    override = os.environ.get("FOUNDRY_DSH_BIN")
    if override:
        candidate = Path(override).expanduser()
        if candidate.is_file():
            for parent in candidate.parents:
                if parent.name == "node_modules":
                    return parent
            return candidate.parent
        for option in (candidate / "node_modules", candidate):
            if (option / "@deepseek-ai" / "dsh-skill" / "lib" / "index.js").exists():
                return option
        return candidate / "node_modules"
    return ROOT / "app" / "extra" / "dsh" / "node_modules"


def _runtime_or_skip() -> Path:
    modules = _dsh_node_modules()
    required = [
        modules / "@deepseek-ai" / "cordis" / "lib" / "index.js",
        modules / "@deepseek-ai" / "dsh-skill" / "lib" / "index.js",
        modules / "@deepseek-ai" / "dsh-skill-filesystem" / "lib" / "index.js",
    ]
    missing = [path for path in required if not path.exists()]
    if missing:
        pytest.skip(f"staged DSH skill runtime is unavailable at {modules}")
    return modules


def _driver(tmp_path: Path, body: str) -> dict:
    if not NODE:
        pytest.skip("node is unavailable")
    dsh_node_modules = _runtime_or_skip()
    path = tmp_path / "driver.mjs"
    path.write_text(
        f"""
import {{ createHash }} from 'node:crypto';
import {{ mkdirSync, readFileSync, writeFileSync }} from 'node:fs';
import {{ join }} from 'node:path';
import {{ Context }} from {(dsh_node_modules / "@deepseek-ai/cordis/lib/index.js").as_uri()!r};
import SkillRegistry from {(dsh_node_modules / "@deepseek-ai/dsh-skill/lib/index.js").as_uri()!r};
import {{ apply as applySkillFilesystem }} from {(dsh_node_modules / "@deepseek-ai/dsh-skill-filesystem/lib/index.js").as_uri()!r};

const root = {str(ROOT)!r};
const tmp = {str(tmp_path)!r};
const bundled = {str(method_root())!r};
const dshHome = join(tmp, 'dsh-home');
const agentsHome = join(tmp, 'agents-home');
const cwd = join(tmp, 'workspace');
mkdirSync(cwd, {{recursive: true}});

function sha256(path) {{
  return createHash('sha256').update(readFileSync(path)).digest('hex');
}}

async function collect(config = {{}}) {{
  const ctx = new Context();
  const exportedLogs = [];
  ctx.logger.exporter({{levels: {{default: 10}}, export(message) {{ exportedLogs.push(message); }}}});
  await ctx.plugin(SkillRegistry, {{}});
  await ctx.plugin({{name: 'fs-provider', inject: ['skills'], apply: applySkillFilesystem}}, {{
    dshHome,
    agentsHome,
    bundledSkillDir: bundled,
    watch: false,
    ...config,
  }});
  const lookup = {{cwd}};
  const summaries = await ctx.skills.list(lookup);
  const logs = exportedLogs.map(message => ({{
    level: message.level,
    type: message.type,
    name: message.name,
    content: (message.args ?? []).join(' '),
  }}));
  const loaded = {{}};
  for (const name of {json.dumps(list(BUNDLED_IDS) + list(BUNDLED_PACKS))}) {{
    const skill = await ctx.skills.get(name, lookup);
    loaded[name] = skill === undefined ? null : {{
      name: skill.name,
      provider: skill.provider,
      source: skill.source,
      path: skill.path,
      resourceBase: skill.resourceBase,
      sha256: sha256(skill.path),
      content: skill.content,
    }};
  }}
  return {{summaries, loaded, logs}};
}}

{body}
""",
        encoding="utf-8",
    )
    env = os.environ | {"NODE_PATH": str(dsh_node_modules)}
    result = subprocess.run([NODE, str(path)], text=True, capture_output=True, env=env, timeout=30)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_real_filesystem_provider_discovers_and_loads_bundled_methods(tmp_path: Path) -> None:
    result = _driver(
        tmp_path,
        """
const result = await collect();
process.stdout.write(JSON.stringify(result));
""",
    )
    summaries = {skill["name"]: skill for skill in result["summaries"]}
    assert set(BUNDLED_IDS) <= set(summaries)
    for skill_id in BUNDLED_IDS:
        summary = summaries[skill_id]
        loaded = result["loaded"][skill_id]
        assert summary["provider"] == "filesystem"
        assert summary["source"] == "bundled"
        assert loaded["provider"] == "filesystem"
        assert loaded["source"] == "bundled"
        assert loaded["path"].endswith(f"{skill_id}/SKILL.md")
        assert loaded["resourceBase"]["kind"] == "directory"
        assert loaded["resourceBase"]["path"].endswith(skill_id)
        assert len(loaded["sha256"]) == 64
        assert "Foundry runtime note" in loaded["content"]


def test_real_filesystem_provider_preserves_user_override_precedence(tmp_path: Path) -> None:
    result = _driver(
        tmp_path,
        """
const userDir = join(agentsHome, 'skills', 'variance-analysis');
mkdirSync(userDir, {recursive: true});
const userSkill = join(userDir, 'SKILL.md');
writeFileSync(userSkill, `---
name: variance-analysis
description: Personal variance workflow
---

USER PERSONAL METHOD BODY
`);
const before = sha256(userSkill);
const result = await collect();
result.userSkill = {path: userSkill, before, after: sha256(userSkill)};
process.stdout.write(JSON.stringify(result));
""",
    )
    summaries = {skill["name"]: skill for skill in result["summaries"]}
    override = result["loaded"]["variance-analysis"]
    assert summaries["variance-analysis"]["source"] == "user-agents"
    assert override["source"] == "user-agents"
    assert override["content"] == "USER PERSONAL METHOD BODY"
    assert result["userSkill"]["before"] == result["userSkill"]["after"]
    assert {skill_id for skill_id in BUNDLED_IDS if skill_id != "variance-analysis"} <= {
        name for name, skill in result["loaded"].items() if skill and skill["source"] == "bundled"
    }


def test_real_filesystem_provider_reports_absent_and_invalid_roots(tmp_path: Path) -> None:
    result = _driver(
        tmp_path,
        """
const invalidDir = join(agentsHome, 'skills', 'bad-skill');
mkdirSync(invalidDir, {recursive: true});
writeFileSync(join(invalidDir, 'SKILL.md'), `---
name: bad-skill
description:
---

bad body
`);
const missingRoot = join(tmp, 'missing-bundled-root');
const missing = await collect({bundledSkillDir: missingRoot});
const badSummary = missing.summaries.find(skill => skill.name === 'bad-skill') ?? null;
const badLoaded = missing.loaded['bad-skill'] ?? null;
process.stdout.write(JSON.stringify({
  missing,
  diagnostics: {
    missingRoot,
    badSummary,
    badLoaded,
    providerWarnings: missing.logs.filter(message => message.type === 'warn').map(message => message.content),
  },
}));
""",
    )
    assert result["missing"]["loaded"] == {skill_id: None for skill_id in list(BUNDLED_IDS) + list(BUNDLED_PACKS)}
    assert result["diagnostics"]["missingRoot"].endswith("missing-bundled-root")
    assert result["diagnostics"]["badSummary"] is None
    assert result["diagnostics"]["badLoaded"] is None
    warnings = "\n".join(result["diagnostics"]["providerWarnings"])
    assert "bad-skill/SKILL.md ignored: frontmatter requires name and description" in warnings
