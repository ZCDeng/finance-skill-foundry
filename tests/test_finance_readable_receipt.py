"""Readable save snapshots retain raw authority, diagnostics and the v2 result."""
from copy import deepcopy
import hashlib
import json
import os
import subprocess
import sys

import pytest

from foundry.finance_claim_semantics import CLAIM_SEMANTICS_VERSION
from test_finance_performance_semantics import performance_case
from test_finance_runtime_payload import ROOT, model_view, restore_table
from test_method_skill_runtime import _runtime_or_skip


PAIR = "本期履约收入与其对应收款分别按履约确认与债权形成追踪。"
UNCITED = "模型边界值为0。"
CLEAR = "收入按履约假设确认；相关收款清偿对应已识别债权；部分清偿保留未结清余额。"
IDENTITIES = ("id", "task_id", "requirements_id", "run_ids", "content_hash")
QUALITY = ("status", "issues", "readability", "status_dimensions", "claim_semantics_version")


def render(raw, tool="save_explanation_draft"):
    result = subprocess.run(["node", "--input-type=module", "-e", """
import fs from 'node:fs';
import {definitions} from './dsh-plugin/analysis.js';
const {raw,name}=JSON.parse(fs.readFileSync(0,'utf8'));
const tool=definitions(undefined,async()=>raw).find(t=>t.name===name);
const value=await tool.execute({spec:{}},{agent:{id:'receipt-render-session'}});
const blocks=tool.output.render({},value);
process.stdout.write(JSON.stringify({value,blocks}));
"""], cwd=ROOT, input=json.dumps({"raw": raw, "name": tool}), text=True,
        capture_output=True, check=True)
    observed = json.loads(result.stdout)
    assert observed["value"]["stdout"] == raw
    assert len(observed["blocks"]) == 1 and observed["blocks"][0]["type"] == "text"
    return observed, json.loads(observed["blocks"][0]["text"])


def residual(data, omitted):
    expected = deepcopy(data)
    for pointer in omitted:
        parts = pointer[1:].split("/")
        target = expected
        for part in parts[:-1]:
            target = target[int(part)] if isinstance(target, list) else target[part]
        del target[parts[-1]]
    return expected


def assert_snapshot(packet, saved, raw=None):
    meta = packet["_model_projection"]
    assert meta["schema"] == "foundry.model-result.v2" and meta["full_result"] is False
    assert meta["readable_receipt"]["kind"] == "convenience_duplicate"
    assert meta["readable_receipt"]["source"] == "decoded result"
    assert "authority" in meta["readable_receipt"]["instruction"]
    expected_residual = residual(saved, meta["omitted_paths"])
    assert restore_table(packet) == expected_residual
    expected = {name: saved[name] for name in IDENTITIES}
    expected["quality"] = {name: saved["quality"][name] for name in QUALITY}
    expected.update({name: saved[name] for name in ("completion", "final_response", "delivery_contract")})
    assert packet["receipt"] == expected
    assert len(json.dumps(packet, ensure_ascii=False, separators=(",", ":")).encode()) <= 48000
    raw = raw if raw is not None else json.dumps(saved, ensure_ascii=False)
    assert meta["raw_sha256"] == hashlib.sha256(raw.encode()).hexdigest()
    # Requirements, source posture and qualification remain in the full decoded
    # residual, even though the convenience duplicate is intentionally smaller.
    decoded = restore_table(packet)
    for key in ("requirements", "dataset_freshness", "evidence_posture", "evidence_report"):
        assert decoded["quality"][key] == expected_residual["quality"][key]
    assert decoded.get("completion_operation") == expected_residual.get("completion_operation")


@pytest.fixture(scope="module")
def actual_receipts(tmp_path_factory):
    path = tmp_path_factory.mktemp("real-readable-save")
    service, _, _, run = performance_case(path)
    prepared = service.prepare_explanation({"run_ids": [run["id"]]})
    bad = service.save_explanation_draft({**prepared["save_template_spec"],
        "qualitative_note": PAIR + UNCITED})
    good = service.save_explanation_draft({**prepared["save_template_spec"], "parent_id": bad["id"],
        "qualitative_note": CLEAR})
    assert any(i["code"] == "uncited_number" and i["text"] == "0" for i in bad["quality"]["issues"])
    assert bad["quality"]["readability"]["issues"]
    assert bad["completion"]["status"] != "complete" and good["completion"]["status"] == "complete"
    for name, data in (("prepared", prepared), ("repair", bad), ("complete", good)):
        (path / f"actual-{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return prepared, bad, good, path


@pytest.mark.parametrize("index", [1, 2], ids=["repair-with-advice", "complete"])
def test_real_prepare_save_registered_render_exposes_exact_snapshot(actual_receipts, index):
    prepared, _, _, path = actual_receipts
    assert len(prepared["facts"]) == 13 and len(prepared["input_facts"]) == 16
    saved = actual_receipts[index]
    raw = json.dumps(saved, ensure_ascii=False)
    observed, packet = render(raw)
    (path / f"registered-render-{index}.json").write_text(json.dumps(observed, ensure_ascii=False, indent=2))
    assert_snapshot(packet, saved)
    assert saved["quality"]["claim_semantics_version"] == CLAIM_SEMANTICS_VERSION


@pytest.mark.parametrize("status", ["complete", "repair_available", "awaiting_input", "needs_review",
                                    "timed_out", "cancelled", "failed"])
@pytest.mark.parametrize("mixed", [False, True], ids=["empty", "mixed-issues"])
def test_same_returned_status_never_borrows_historical_complete(actual_receipts, status, mixed):
    saved = deepcopy(actual_receipts[2])
    saved["completion"].update(status=status, original_requirements_completed=status == "complete")
    saved["delivery_contract"]["completion_status"] = status
    saved["quality"]["issues"] = ([{"code": "foreign_scope", "severity": "error", "text": "旧稿",
        "position": 7, "details": {"requirements_id": "FOREIGN-REQ", "counts_as_amount_evidence": False}},
        {"code": "missing_source", "severity": "warning", "text": "来源", "position": 11}] if mixed else [])
    saved["completion_operation"] = {"status": status, "current": {"receipt_id": saved["completion"]["id"]},
        "revisions": [{"status": "complete", "receipt_id": "HISTORICAL-COMPLETE", "payload": {"body": "history"}}]}
    _, packet = render(json.dumps(saved, ensure_ascii=False))
    assert_snapshot(packet, saved)
    assert packet["receipt"]["completion"]["status"] == status
    assert packet["receipt"]["completion"]["id"] != "HISTORICAL-COMPLETE"


@pytest.mark.parametrize("field", ["receipt", "unknown_financial_detail", "foreign_completion"])
def test_unknown_or_conflicting_fields_remain_in_decoded_result(actual_receipts, field):
    saved = deepcopy(actual_receipts[1])
    saved[field] = {"status": "complete", "requirements_id": "FOREIGN", "amount": "9007199254740993"}
    _, packet = render(json.dumps(saved, ensure_ascii=False))
    assert restore_table(packet) == residual(saved, packet["_model_projection"]["omitted_paths"])
    if field == "receipt":
        assert "receipt" not in packet and "readable_receipt" not in packet["_model_projection"]
    else:
        assert_snapshot(packet, saved)


@pytest.mark.parametrize("field", ["final_response", "delivery_contract", "task_id", "content_hash"])
def test_unsupported_receipt_shape_keeps_old_encoded_fallback(actual_receipts, field):
    saved = deepcopy(actual_receipts[2])
    del saved[field]
    _, packet = render(json.dumps(saved, ensure_ascii=False))
    assert "receipt" not in packet and "readable_receipt" not in packet["_model_projection"]
    assert restore_table(packet) == residual(saved, packet["_model_projection"]["omitted_paths"])


@pytest.mark.parametrize("field,value", [("completion", "complete"), ("completion", []),
    ("run_ids", []), ("run_ids", [None]), ("quality.status_dimensions", "pass")])
def test_malformed_receipt_shape_is_not_given_a_convenience_snapshot(actual_receipts, field, value):
    saved = deepcopy(actual_receipts[1])
    target = saved
    parts = field.split(".")
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = value
    _, packet = render(json.dumps(saved, ensure_ascii=False))
    assert "receipt" not in packet and "readable_receipt" not in packet["_model_projection"]
    assert restore_table(packet) == residual(saved, packet["_model_projection"]["omitted_paths"])


def test_large_diagnostics_keep_all_issues_even_when_duplicate_exceeds_budget(actual_receipts):
    saved = deepcopy(actual_receipts[1])
    saved["quality"]["issues"] = [{"code": f"issue-{i}", "text": hashlib.sha256(str(i).encode()).hexdigest() * 2,
        "position": i, "severity": "error"} for i in range(90)]
    _, packet = render(json.dumps(saved, ensure_ascii=False))
    assert packet["_model_projection"]["full_result"] is False
    assert "receipt" not in packet
    assert restore_table(packet) == residual(saved, packet["_model_projection"]["omitted_paths"])
    assert len(restore_table(packet)["quality"]["issues"]) == 90


def test_large_requirements_overflow_is_explicit_not_a_complete_receipt(actual_receipts):
    saved = deepcopy(actual_receipts[1])
    saved["quality"]["requirements"]["independent"] = "".join(hashlib.sha256(str(i).encode()).hexdigest() for i in range(1000))
    _, packet = render(json.dumps(saved, ensure_ascii=False))
    assert packet["code"] == "FOUNDRY_MODEL_RESULT_TOO_LARGE" and packet["model_view_complete"] is False
    assert "completion" not in packet and "receipt" not in packet


@pytest.mark.parametrize("number", ["9007199254740993", "1e400", "1e-400", "0.123456789012345678901", "-0"])
def test_unsafe_save_numbers_do_not_acquire_readable_authority(actual_receipts, number):
    raw = json.dumps(actual_receipts[1], ensure_ascii=False)
    raw = raw[:-1] + ',"unsafe_amount":' + number + '}'
    _, packet = render(raw)
    assert packet["code"] == "FOUNDRY_MODEL_RESULT_TOO_LARGE" and packet["model_view_complete"] is False
    assert "receipt" not in packet


@pytest.mark.parametrize("key", ["$r", "$v", "$foundry_ref", "_model_projection"])
def test_reserved_save_fields_fail_closed(actual_receipts, key):
    saved = deepcopy(actual_receipts[1])
    saved["nested_source"] = {key: {"completion": "complete"}}
    _, packet = render(json.dumps(saved, ensure_ascii=False))
    assert packet["code"] == "FOUNDRY_MODEL_RESULT_TOO_LARGE" and packet["model_view_complete"] is False
    assert "receipt" not in packet


def test_short_note_guidance_does_not_create_a_numeric_exemption(actual_receipts):
    prepared, bad, good, _ = actual_receipts
    summary = prepared["writing_guidance"]["summary"]
    assert "模板未表达" in summary and "边界数字" in summary and "空串" in summary
    assert "必要" in summary
    assert UNCITED in bad["body_template"] and CLEAR in good["body_template"]
    assert any(i["code"] == "uncited_number" and i["text"] == "0" for i in bad["quality"]["issues"])
    assert all(good["quality"][key] == good["explanation_check"][key] for key in ("issues", "readability"))


def test_necessary_additional_qualified_reference_is_still_allowed(tmp_path):
    service, _, _, run = performance_case(tmp_path)
    prepared = service.prepare_explanation({"run_ids": [run["id"]]})
    fact = prepared["facts"][0]
    note = "补充核对注册输出：" + fact["reference_template"]["body_token"] + "。"
    saved = service.save_explanation_draft({**prepared["save_template_spec"], "qualitative_note": note})
    assert note in saved["body_template"]
    assert saved["quality"]["status"] == "pass" and saved["completion"]["status"] == "complete"
    assert any(claim.get("fact_id") == fact["id"] for claim in saved["claims"])


@pytest.mark.parametrize("raw", ["not JSON", "{broken", '{"completion":"complete",' + 'x' * 50000])
def test_malformed_save_keeps_existing_raw_or_explicit_overflow(raw):
    text = model_view("save_explanation_draft", raw)
    if len(raw.encode()) <= 48000:
        assert text == raw
    else:
        packet = json.loads(text)
        assert packet["code"] == "FOUNDRY_MODEL_RESULT_TOO_LARGE"
        assert packet["model_view_complete"] is False and "receipt" not in packet


@pytest.mark.parametrize("repair", [False, True], ids=["complete-final", "repair-and-qualification"])
def test_production_sdk_next_model_tool_result_keeps_raw_native_authority(tmp_path, repair):
    service, context, _, initial = performance_case(tmp_path)
    session = "readable-receipt-sdk"
    service.task.record_session(session, role="analysis")
    modules = _runtime_or_skip() / "@deepseek-ai"
    imports = "\n".join(f"import {name} from {(modules / package / 'lib/index.js').as_uri()!r};"
        for name, package in [("Agents", "dsh-agent"), ("Sessions", "dsh-session"), ("Llm", "dsh-llm"),
                              ("Tools", "dsh-tools"), ("Prompt", "dsh-system-prompt"), ("Loop", "dsh-agent-loop")])
    driver = tmp_path / "receipt-sdk.mjs"
    driver.write_text(imports + f'''
import {{writeFileSync}} from 'node:fs';
import {{Context}} from {(modules / 'cordis/lib/index.js').as_uri()!r};
import {{LlmAdapter,createUserMessage}} from {(modules / 'dsh-llm/lib/index.js').as_uri()!r};
import {{apply,definitions}} from {(ROOT / 'dsh-plugin/analysis.js').as_uri()!r};
const ctx=new Context();const diagnostics=[];
ctx.on('finance/delivery-observation',event=>diagnostics.push(event));
await ctx.plugin(Agents,{{}});await ctx.plugin(Sessions,{{}});await ctx.plugin(Llm,{{}});
await ctx.plugin(Prompt,{{includeHarnessIdentity:false,includeRuntimeContext:false}});
await ctx.plugin(Tools,{{}});await ctx.plugin(Loop,{{agents:[],maxParallelToolCalls:1}});ctx.provide('subagents',{{}});
let calls=0,runId,prepared;const results=[],rounds=[];
const publicRaw={json.dumps('来源绑定输入均具备金额证据资格。Input_facts are model_verified.' if repair else '按来源核对履约与债权清偿。', ensure_ascii=False)};
function* text(s){{yield{{type:'block-start',index:0,blockType:'text'}};yield{{type:'text-delta',index:0,text:s}};
yield{{type:'block-end',index:0,block:{{type:'text',text:s}}}};}}
function* tool(name,id,spec){{const args=JSON.stringify({{spec}});yield{{type:'block-start',index:1,blockType:'tool-call'}};
yield{{type:'tool-call-delta',index:1,id,name,argumentsDelta:args}};
yield{{type:'block-end',index:1,block:{{type:'tool-call',id,name,arguments:args}}}};}}
class Offline extends LlmAdapter{{async *stream(options){{calls++;rounds.push(structuredClone(options.messages));
if(calls===1)yield*tool('finance_scenario_run','receipt-run',{{scenario_id:{initial['result']['scenario_id']!r}}});
else if(calls===2)yield*tool('prepare_explanation','receipt-prepare',{{run_ids:[runId]}});
else if(calls===3){{yield*text(publicRaw);yield*tool('save_explanation_draft','receipt-save',
 {{...prepared.save_template_spec,qualitative_note:{json.dumps(PAIR + UNCITED if repair else CLEAR, ensure_ascii=False)}}});}}
else yield*text('模型扩写了正文没有的检查明细。');
yield{{type:'finish',reason:{{kind:calls<4?'tool-calls':'stop'}}}};
}}}}
ctx.llm.registerAdapter(['offline'],new Offline());
const handle=await ctx.agents.create({{sessionId:{session!r},agentOptions:{{provider:'offline',model:'fake'}},setup(agentCtx){{
apply(agentCtx);agentCtx.on('tools/result',(exec,result)=>{{
 const value=result.value;results.push({{name:exec.name,isError:result.isError,value,
 rendered:value?definitions().find(t=>t.name===exec.name).output.render({{}},value):null}});
 if(!result.isError&&exec.name==='finance_scenario_run')runId=JSON.parse(value.stdout).id;
 if(!result.isError&&exec.name==='prepare_explanation')prepared=JSON.parse(value.stdout);
}});}}}});
handle.agent.followup(createUserMessage({{content:[{{type:'text',text:'按当前来源核对并保存三表。'}}],source:{{kind:'user'}}}}));
await handle.agent.whenIdle();const events=handle.agent.session.events;
const {{DeepSeekAdapter,resolveAdapterOptions}}=await import({(modules / 'dsh-llm-deepseek/lib/index.js').as_uri()!r});
const serializedMessages=results.at(-1).value?.final_delivery?handle.agent.session.deriveMessages():rounds.at(-1);
const originalFetch=globalThis.fetch;let wire,transportCalls=0;
globalThis.fetch=async(_url,options)=>{{transportCalls++;wire=JSON.parse(options.body);return new Response(
 'data: {{"choices":[{{"delta":{{"content":"ok"}},"finish_reason":"stop"}}]}}\\n\\ndata: [DONE]\\n\\n',
 {{status:200,headers:{{'content-type':'text/event-stream'}}}});}};
try{{const connection=resolveAdapterOptions({{baseURL:'https://offline.invalid',models:[{{id:'fake'}}]}},undefined);
 const adapter=new DeepSeekAdapter({{options:()=>connection,resolveApiKey:async()=> 'offline-stub',resolveUserId:()=> 'offline'}});
 for await(const _chunk of adapter.stream({{model:'fake',messages:serializedMessages}})){{}}
}}finally{{globalThis.fetch=originalFetch;}}
const observation={{calls,results,rounds,serializedMessages,wire,transportCalls,events,diagnostics,publicRaw,provider_calls:0}};
writeFileSync({str(tmp_path / 'sdk-observation.json')!r},JSON.stringify(observation,null,2));
await handle.dispose();process.stdout.write(JSON.stringify({{calls,provider_calls:0}}));
''')
    launcher = tmp_path / "foundry"
    launcher.write_text(f'#!{sys.executable}\nimport runpy,sys\nsys.path.insert(0,{str(ROOT)!r})\n'
                        'runpy.run_module("foundry.cli",run_name="__main__")\n')
    launcher.chmod(0o700)
    process = subprocess.run(["node", str(driver)], cwd=ROOT, text=True, capture_output=True,
        env=os.environ | {"FOUNDRY_BIN": str(launcher), "FOUNDRY_VAR": str(tmp_path / "var")}, timeout=90)
    (tmp_path / "sdk-process.json").write_text(json.dumps({"exit_code": process.returncode,
        "stdout": process.stdout, "stderr": process.stderr, "provider_calls": 0}, ensure_ascii=False, indent=2))
    assert process.returncode == 0, process.stderr
    observed = json.loads((tmp_path / "sdk-observation.json").read_text())
    assert observed["calls"] == (4 if repair else 3) and observed["provider_calls"] == 0 and observed["transportCalls"] == 1
    assert [r["name"] for r in observed["results"]] == ["finance_scenario_run", "prepare_explanation", "save_explanation_draft"]
    assert all(r["isError"] is False for r in observed["results"])
    raw = observed["results"][-1]["value"]["stdout"]
    saved = json.loads(raw)
    packet = json.loads(observed["results"][-1]["rendered"][0]["text"]) if repair else render(raw)[1]
    (tmp_path / "saved-raw.json").write_text(raw)
    # Repair reaches the next real LlmAdapter call; a complete receipt ends at
    # its native tool/result. Serialize each actual SDK history through DeepSeek.
    rendered_text = observed["results"][-1]["rendered"][0]["text"]
    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for item in value.values():
                yield from strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)
    assert rendered_text in list(strings(observed["serializedMessages"]))
    assert any(m.get("role") == "tool" and m.get("content") == rendered_text for m in observed["wire"]["messages"])
    tool_events = [e for e in observed["events"] if e["type"] == "tool/result"]
    assert tool_events[-1]["data"]["message"]["content"][0]["content"] == [{"type": "text", "text": rendered_text}]
    assert_snapshot(packet, saved, raw)
    assert saved["completion"]["status"] != "complete" if repair else saved["completion"]["status"] == "complete"
    prepared = json.loads(observed["results"][1]["value"]["stdout"])
    assert len(prepared["facts"]) == 13 and len(prepared["input_facts"]) == 16
    assert all(not f["evidence_eligibility"]["counts_as_amount_evidence"] for f in prepared["input_facts"])
    assert all(f["evidence_eligibility"]["counts_as_amount_evidence"] for f in prepared["facts"])
    persisted = service.analysis.get_draft(saved["id"])
    for key in ("body", "body_template", "claims", "run_ids", "requirements_id", "content_hash"):
        assert persisted[key] == saved[key]
    if repair:
        assert UNCITED in persisted["body_template"]
        assert any(i["code"] == "uncited_number" and i["text"] == "0" for i in packet["receipt"]["quality"]["issues"])
    audits = [e for e in observed["diagnostics"] if e["type"] == "finance/final-delivery"]
    if repair:
        assert len(audits) == 1 and audits[0]["data"]["status"] == "replaced"
        bindings = audits[0]["data"]["bindings"]
        assert audits[0]["data"]["delivered_text"] == saved["final_response"]
    else:
        assert audits == []
        delivery = tool_events[-1]["data"]["meta"]["final_delivery"]
        bindings = delivery["bindings"]
        assert delivery["status"] == "verified" and delivery["final_response"] == saved["final_response"]
        assert delivery["final_response_sha256"] == hashlib.sha256(saved["final_response"].encode()).hexdigest()
    assert bindings["draft_id"] == saved["id"]
    assert bindings["receipt_id"] == saved["completion"]["id"]
    assert bindings["draft_content_hash"] == saved["content_hash"]
    selected = [e for e in observed["diagnostics"] if e["type"] == "finance/public-text-delivery" and e["data"]["phase"] == "selected"]
    assert len(selected) == 1 and selected[0]["data"]["status"] == ("contradicted" if repair else "unchanged")
    assert selected[0]["data"]["server_source_binding"]["claim_semantics_version"] == CLAIM_SEMANTICS_VERSION
    delivered = selected[0]["data"]["delivered_text"]
    texts = [e["data"]["chunk"]["text"] for e in observed["events"] if e["type"] == "assistant/chunk" and e["data"]["chunk"]["type"] == "text-delta"]
    assert texts == ([delivered, saved["final_response"]] if repair else [delivered])
    block_ends = [e["data"]["chunk"]["block"]["text"] for e in observed["events"]
        if e["type"] == "assistant/chunk" and e["data"]["chunk"]["type"] == "block-end"
        and e["data"]["chunk"]["block"]["type"] == "text"]
    messages = [block["text"] for e in observed["events"] if e["type"] == "assistant/message"
        for block in e["data"]["message"]["content"] if block["type"] == "text"]
    assert block_ends == messages == texts
    held = [e for e in observed["diagnostics"] if e["type"] == "finance/public-text-delivery" and e["data"]["phase"] == "held"]
    delta_events = [e for e in observed["events"] if e["type"] == "assistant/chunk" and e["data"]["chunk"]["type"] == "text-delta"]
    assert observed["diagnostics"].index(held[0]) < observed["diagnostics"].index(selected[0])
    assert selected[0]["observed_after_seq"] < delta_events[0]["seq"]
    assert delivered in list(strings(observed["serializedMessages"]))
    if repair:
        assert observed["publicRaw"] not in list(strings(observed["serializedMessages"]))
    ends = [e for e in observed["events"] if e["type"] == "turn/end"]
    assert ends[-1]["data"]["reason"]["kind"] == "completed"
