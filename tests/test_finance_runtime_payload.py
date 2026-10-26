"""The model view is compact; the registry and evaluator retain exact raw evidence."""
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def node(script):
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT,
                            text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def restore(value, root):
    if isinstance(value, dict) and list(value) == ["$foundry_ref"]:
        target = root
        for part in value["$foundry_ref"][2:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            target = target[int(part)] if isinstance(target, list) else target[part]
        return restore(target, root)
    if isinstance(value, dict):
        return {key: restore(item, root) for key, item in value.items()}
    if isinstance(value, list):
        return [restore(item, root) for item in value]
    return value


def restore_table(packet):
    def decode(value):
        if isinstance(value, dict) and list(value) == ["$v"]:
            return decode(packet["values"][value["$v"]])
        if isinstance(value, dict) and list(value) == ["$r"]:
            index, items = value["$r"]
            return dict(zip(packet["columns"][index], [decode(v) for v in items], strict=True))
        if isinstance(value, dict):
            return {key: decode(v) for key, v in value.items()}
        if isinstance(value, list):
            return [decode(v) for v in value]
        return value
    return decode(packet["result"])


def model_view(tool, raw):
    # stdin avoids shell quoting and OS argument-size limits for large evidence.
    result = subprocess.run(["node", "--input-type=module", "-e", """
      import fs from 'node:fs';
      import {workflowModelResult} from './dsh-plugin/model-result.js';
      const {tool,raw}=JSON.parse(fs.readFileSync(0,'utf8'));
      process.stdout.write(workflowModelResult(tool,raw));
    """], cwd=ROOT, input=json.dumps({"tool": tool, "raw": raw}), text=True,
        capture_output=True, check=True)
    return result.stdout


def test_tabular_view_preserves_every_value_and_qualification_below_spill_budget():
    data = {"rows": [{f"financial_identity_dimension_{col}": f"row-{row}-值-{col}"
                      for col in range(18)} for row in range(130)],
            "issues": [{"code": "missing_source", "severity": "error", "value": "-0.00001"}],
            "eligibility": {"counts_as_amount_evidence": False},
            "scope": {"currency": "CNY", "period": "2026-10"}}
    raw = json.dumps(data, ensure_ascii=False)
    text = model_view("prepare_explanation", raw)
    packet = json.loads(text)
    assert len(text.encode()) <= 48000
    assert packet["_model_projection"]["schema"] == "foundry.model-result.v2"
    assert packet["_model_projection"]["lossless"] is True
    assert restore_table(packet) == data


def test_large_save_returns_exact_receipt_and_failures_without_document_echo():
    facts = [{"id": str(i), "value": str(i), "detail": f"{i}-" + "unique evidence " * 80}
             for i in range(120)]
    data = {"id": "draft-1", "requirements_id": "req-1", "run_ids": ["run-1"],
            "fact_ids": ["fact-1"], "body": "Submitted but not approved", "claims": [],
            "quality": {"status": "needs_attention", "status_dimensions": {"numeric_citation": "failed"},
                        "facts": facts, "issues": [{"code": "missing_source", "severity": "error"}],
                        "requirements": {"provenance": {"status": "failed", "reason": "source_revoked"},
                                         "support": {"supported_metrics": facts, "version": "unchanged"}}},
            "completion": {"status": "repair_available", "original_requirements_completed": False},
            "completion_operation": {"status": "active", "repair_attempts_reserved": 1,
                                     "stop_reason": "source_revoked", "deadline_at": "unchanged",
                                     "revisions": [{"status": "failed", "payload": facts}]}}
    text = model_view("save_explanation_draft", json.dumps(data))
    packet = json.loads(text)
    assert len(text.encode()) <= 48000
    assert packet["_model_projection"]["full_result"] is False
    expected = json.loads(json.dumps(data))
    for path in packet["_model_projection"]["omitted_paths"]:
        parts = path.strip("/").split("/")
        target = expected
        for part in parts[:-1]:
            target = target[int(part)] if isinstance(target, list) else target[part]
        del target[parts[-1]]
    assert restore_table(packet) == expected
    assert expected["quality"]["issues"] == data["quality"]["issues"]
    assert expected["quality"]["requirements"]["provenance"]["status"] == "failed"
    assert expected["completion"] == data["completion"]


def test_large_unsafe_or_reserved_results_report_incomplete_without_rounding():
    padding = "x" * 55000
    samples = [json.dumps({"padding": padding, "input": {"$r": [0, []]}}),
               '{"padding":' + json.dumps(padding) + ',"amount":9007199254740993}']
    for raw in samples:
        result = json.loads(model_view("prepare_explanation", raw))
        assert result["code"] == "FOUNDRY_MODEL_RESULT_TOO_LARGE"
        assert result["model_view_complete"] is False
        assert "amount" not in result and "completion" not in result


def test_model_projection_preserves_raw_and_all_financial_evidence():
    sources = [{"dataset_id": "source-ledger", "row_index": i, "source_row": i + 1,
                "column": "amount", "unit": "元", "original_unit": "元",
                "unit_multiplier": "1"} for i in range(24)]
    rows = [{"metric_key": f"metric_{i}", "value": str(i - 5), "source_rows": sources,
             "period": "2026-10", "unit": "元", "currency": "CNY",
             "eligibility": {"counts_as_amount_evidence": i != 3,
                             "reason_codes": ["missing_source"] if i == 3 else []}}
            for i in range(13)]
    raw = json.dumps({"id": "run-1", "requirements_id": "req-1", "result": {"rows": rows},
                      "quality": {"issues": [{"code": "missing_source", "severity": "error"}],
                                  "facts": rows}, "completion": {"status": "needs_review"}},
                     ensure_ascii=False)
    report = node(f"""
      import {{definitions}} from './dsh-plugin/analysis.js';
      const raw = {json.dumps(raw)};
      const tool = definitions(undefined, async () => raw).find(t => t.name === 'finance_scenario_run');
      const value = await tool.execute({{spec: {{scenario_id: 'scenario-1'}}}}, {{agent: {{id:'session-1'}}}});
      const text = tool.output.render({{}}, value)[0].text;
      process.stdout.write(JSON.stringify({{value, text}}));
    """)
    assert report["value"]["stdout"] == raw
    assert len(report["text"]) < len(raw) * .45
    projected = json.loads(report["text"])
    assert projected["_model_projection"]["lossless"] is True
    del projected["_model_projection"]
    assert restore(projected, projected) == json.loads(raw)
    assert "missing_source" in report["text"] and "needs_review" in report["text"]


def test_projection_does_not_interpret_reserved_source_fields_or_non_json():
    samples = ['plain error, not JSON', '{broken', '{"$foundry_ref":"#/private"}',
               '{"_model_projection":{"lossless":false}}']
    report = node(f"""
      import {{definitions}} from './dsh-plugin/analysis.js';
      const tool = definitions().find(t => t.name === 'analysis-state');
      process.stdout.write(JSON.stringify({json.dumps(samples)}.map(stdout => tool.output.render({{}}, {{stdout}})[0].text)));
    """)
    assert report == samples


def test_projection_never_rounds_json_numeric_amounts():
    numbers = ["9007199254740993", "1e400", "1e-400", "0.123456789012345678901", "-0"]
    samples = ['{"amount":' + number + ',"source_rows":' + json.dumps([{"source": "x" * 500}] * 20) + '}'
               for number in numbers]
    report = node(f"""
      import {{definitions}} from './dsh-plugin/analysis.js';
      const tool = definitions().find(t => t.name === 'analysis-state');
      process.stdout.write(JSON.stringify({json.dumps(samples)}.map(stdout => tool.output.render({{}}, {{stdout}})[0].text)));
    """)
    assert report == samples


def test_cancel_diagnostic_distinguishes_disposal_and_timeout_without_secret_values():
    report = node("""
      import {invokeFoundry} from './dsh-plugin/index.js';
      process.env.FOUNDRY_VAR='/unused';
      const results=[];
      for (const reason of [{kind:'disposed'}, {kind:'hook',reason:'finance completion timeout'},
          {kind:'unknown', api_key:'DO_NOT_DISPLAY_SECRET'}, new DOMException('expired','TimeoutError')]) {
        const controller=new AbortController(); controller.abort(reason);
        try {await invokeFoundry(['save-explanation-draft','--spec','{}'],
          {agent:{id:'session-1'},callId:'call-1',signal:controller.signal});}
        catch(error) {results.push({message:error.message,name:error.name,cancelled:error.cancelled});}
      }
      process.stdout.write(JSON.stringify(results));
    """)
    assert all(item["cancelled"] and item["name"] == "FoundryCancelled" for item in report)
    diagnostics = [json.loads(item["message"]) for item in report]
    assert [item["cause_kind"] for item in diagnostics] == ["disposed", "hook", "unknown", "timeout"]
    assert all(item["code"] == "FOUNDRY_CANCELLED" and item["call_id"] == "call-1" for item in diagnostics)
    assert "DO_NOT_DISPLAY_SECRET" not in str(report)
    assert all("not confirmed" in item["message"] for item in diagnostics)


def test_cancel_diagnostic_does_not_copy_arbitrary_exception_messages():
    report = node(r'''
      import {invokeFoundry} from './dsh-plugin/index.js';
      process.env.FOUNDRY_VAR='/unused';
      const results=[];
      for (const message of ['{"api_key":"SYNTHETIC_REVIEW_SECRET"}',
          'password="SYNTHETIC REVIEW SECRET"', 'C:\\Users\\synthetic\\private\\file.txt']) {
        const controller=new AbortController(); controller.abort(new Error(message));
        try {await invokeFoundry(['save-explanation-draft'],
          {agent:{id:'session-1'},callId:'call-1',signal:controller.signal});}
        catch(error) {results.push(JSON.parse(error.message));}
      }
      process.stdout.write(JSON.stringify(results));
    ''')
    assert all("reason" not in item and item["code"] == "FOUNDRY_CANCELLED" for item in report)
    assert "SECRET" not in str(report) and "private" not in str(report)
