"""The model-facing schema and argv must support the guarded short save path."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def registered_save(tmp_path_factory):
    node = shutil.which("node")
    assert node, "Node is required to check the registered plugin"
    roots = [ROOT / "app/extra/dsh/node_modules"]
    if os.environ.get("FOUNDRY_DSH_BIN"):
        roots.extend(Path(os.environ["FOUNDRY_DSH_BIN"]).resolve().parents)
    ajv = next((p / "ajv/dist/ajv.js" for p in roots if (p / "ajv/dist/ajv.js").is_file()), None)
    assert ajv, "Use the existing DSH runtime validator; do not skip this input contract"
    script = tmp_path_factory.mktemp("prepared-save-schema") / "probe.mjs"
    script.write_text(f"""
import {{ definitions }} from {json.dumps((ROOT / 'dsh-plugin/analysis.js').as_uri())};
import Ajv from {json.dumps(ajv.as_uri())};
const calls = [];
const tool = definitions(undefined, async (argv) => {{ calls.push(argv); return '{{}}'; }})
  .find(tool => tool.name === 'save_explanation_draft');
const validate = new Ajv({{strict:false}}).compile(tool.parameters);
const short = {{use_prepared_template:true,run_ids:['run-owned'],requirements_id:'requirements-owned',qualitative_note:'保留专业复核限制。'}};
const inputs = {{
  short, shortEmptyNote:{{...short,qualitative_note:''}},
  repair:{{...short,parent_id:'draft-owned'}},
  ordinary:{{body:'经理说明'}}, ordinaryFalse:{{body:'经理说明',use_prepared_template:false}},
  missingRuns:{{use_prepared_template:true,requirements_id:'requirements-owned'}},
  emptyRuns:{{...short,run_ids:[]}}, emptyRequirements:{{...short,requirements_id:''}},
  missingRequirements:{{use_prepared_template:true,run_ids:['run-owned']}},
  wrongFlag:{{...short,use_prepared_template:'true'}},
  noTemplateNote:{{body:'原文',qualitative_note:'不得忽略'}},
  noBody:{{run_ids:['run-owned']}},
  ...Object.fromEntries(['body','body_template','document','claims','fact_ids'].map(
    key => ['conflict_'+key,{{...short,[key]:key === 'claims' || key === 'fact_ids' ? [] : ''}}])),
}};
const checks = Object.fromEntries(Object.entries(inputs).map(([name,spec])=>[name,validate({{spec}})]));
await tool.execute({{spec:short}},{{agent:{{id:'registered-session'}}}});
process.stdout.write(JSON.stringify({{checks,short,calls,properties:tool.parameters.properties.spec.properties}}));
""")
    run = subprocess.run([node, str(script)], text=True, capture_output=True, timeout=30)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def test_registered_schema_accepts_short_and_existing_body_saves(registered_save):
    expected = {"short", "shortEmptyNote", "repair", "ordinary", "ordinaryFalse"}
    assert {name for name, valid in registered_save["checks"].items() if valid} == expected
    fields = registered_save["properties"]
    assert fields["use_prepared_template"]["type"] == "boolean"
    assert fields["qualitative_note"]["type"] == "string"


def test_registered_tool_forwards_short_spec_without_fabricating_a_body(registered_save):
    assert len(registered_save["calls"]) == 1
    command, option, value = registered_save["calls"][0]
    assert (command, option) == ("save-explanation-draft", "--spec")
    assert json.loads(value) == registered_save["short"]
