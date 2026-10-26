"""The installed preset replies to a real input-gap save and still rejects late todo."""
import json
import subprocess
import sys
import time

import pytest

from foundry.finance_service import FinanceStore
from foundry.harness import install_presets
from foundry.task import TaskStore
from test_method_skill_runtime import ROOT, _runtime_or_skip
import test_real_load as real


@pytest.mark.parametrize("after_save", ["text", "todo-only"])
def test_installed_preset_input_gap_terminal_reply_and_late_todo_guard(tmp_path, monkeypatch, after_save):
    modules = _runtime_or_skip()
    monkeypatch.setattr(real, "DSH_BIN", str(modules / "@deepseek-ai/dsh/lib/bin.js"))
    service = FinanceStore(TaskStore(tmp_path / "var").create(title="终态收口"))
    path = tmp_path / "amounts.json"
    scope = {"ledger": "L1", "organization": "O1", "period": "2026-08",
             "currency": "CNY", "unit": "元", "scenario": "actual"}
    path.write_text(json.dumps([{**scope, "account_code": "1",
                                 "management_account": "revenue", "amount": "25"}]))
    source = service.analysis.add_dataset(path, name="只有金额")
    context = service.save_context({"bindings": {"source": source["id"]},
                                    "scopes": {"source": scope}})
    requirement = service.analysis_requirements_save({
        "question": "解释量价变化并核查可用来源", "bindings": context["bindings"],
        "items": [{"id": "pq", "metric": "price_quantity", "requires_drilldown": True}],
    })
    run = service.run_metric({"context_id": context["id"],
                              "metric": {"kind": "account_total", "accounts": ["revenue"]}})
    assert run["execution_status"] == "succeeded"
    session = "input-gap-terminal"
    service.task.record_session(session, role="analysis")
    probe = r'''
export const name='foundry-tool-probe';
export const inject=['agentPresets','llm','agents'];
export function apply(ctx){
 (async()=>{
 const {LlmAdapter,createUserMessage}=await import(process.env.FOUNDRY_LLM_MODULE);
 let count=0,nextRequest=false;const saves=[],tools=[];
 const text=function*(value){yield{type:'block-start',index:0,blockType:'text'};
   yield{type:'text-delta',index:0,text:value};yield{type:'block-end',index:0,block:{type:'text',text:value}};};
 const tool=function*(name,id,args,index=0){yield{type:'block-start',index,blockType:'tool-call'};
   yield{type:'tool-call-delta',index,id,name,argumentsDelta:JSON.stringify(args)};
   yield{type:'block-end',index,block:{type:'tool-call',id,name,arguments:JSON.stringify(args)}};};
 ctx.llm.registerAdapter(['terminal-fixture'],new class extends LlmAdapter{
   async *stream(options){
    if(options.purpose){yield*text('Input-gap draft');yield{type:'finish',reason:{kind:'stop'}};return;}
    count++;if(nextRequest){yield*text('NEXT_REQUEST_NO_SAVE');yield{type:'finish',reason:{kind:'stop'}};return;}
    if(count===1){yield*tool('save_explanation_draft','terminal-save',{spec:{
      body:'需要补充数量与单价资料；原量价分析尚未完成。',requirements_id:process.env.FOUNDRY_TEST_REQUIREMENT,
      run_ids:[process.env.FOUNDRY_TEST_RUN]}});
      if(process.env.FOUNDRY_TEST_AFTER==='todo-only')yield*tool('todo_write','late-todo',{todos:[{content:'收尾计划',status:'completed'}]},1);
      yield{type:'finish',reason:{kind:'tool-calls'}};return;}
    if(process.env.FOUNDRY_TEST_AFTER==='todo-only'){
      yield*tool('todo_write','late-todo',{todos:[{content:'收尾计划',status:'completed'}]});
      yield{type:'finish',reason:{kind:'tool-calls'}};
    }else{yield*text(saves.at(-1).final_response);yield{type:'finish',reason:{kind:'stop'}};}
   }
 }());
 await ctx.agentPresets.standingKeyFor('analysis');
 const handle=await ctx.agents.create({sessionId:'input-gap-terminal',
  meta:{cwd:process.env.FOUNDRY_TEST_WORKSPACE,agentPreset:'analysis'},
  agentOptions:{provider:'terminal-fixture',model:'deterministic'},
  setup:async(agentCtx)=>{await ctx.agentPresets.mount(agentCtx,'analysis');
   agentCtx.on('tools/result',(exec,result)=>{
    tools.push({name:exec.name,call_id:exec.callId,isError:result.isError});
    if(exec.name==='save_explanation_draft'&&result.isError===false){
     const saved=JSON.parse(result.value.stdout);saves.push({id:saved.id,content_hash:saved.content_hash,
      body:saved.body,run_ids:saved.run_ids,completion:saved.completion,operation_status:saved.completion_operation?.status,
      final_response:saved.final_response});}
   });}});
 try{
  handle.agent.followup(createUserMessage({content:[{type:'text',text:'保存资料缺口草稿并说明限制。'}],source:{kind:'user'}}));
  await handle.agent.whenIdle();const events=[...handle.agent.session.events];
  const publicTexts=(rows)=>rows.filter(e=>e.type==='assistant/message').flatMap(e=>
    e.data.message.content.filter(b=>b.type==='text').map(b=>b.text));
  nextRequest=true;handle.agent.followup(createUserMessage({content:[{type:'text',text:'另一次请求。'}],source:{kind:'user'}}));
  await handle.agent.whenIdle();const next=handle.agent.session.events.slice(events.length);
  const result={count,saves,tools,texts:publicTexts(events),nextTexts:publicTexts(next),
   ends:events.filter(e=>e.type==='turn/end').map(e=>e.data.reason),
   todoWrites:events.filter(e=>e.type==='todo/write').length,
   deliveries:events.filter(e=>e.type==='tool/result'&&e.data.meta?.final_delivery).map(e=>({meta:e.data.meta.final_delivery,content:e.data.message.content[0].content})),
   nextDeliveries:next.filter(e=>e.type==='tool/result'&&e.data.meta?.final_delivery).length,provider_calls:0};
  process.stdout.write('FOUNDRY_TERMINAL '+JSON.stringify(result)+'\n');
 }finally{await handle.dispose();}
 })().catch(error=>process.stdout.write('FOUNDRY_TERMINAL_ERROR '+(error.stack??error.message)+'\n'));
}
'''
    home = tmp_path / "harness"
    real._prepare(home, real._probe_package(tmp_path / "probe", probe), "web")
    install_presets(home)
    argv, env, cwd = real._dsh_args(home, "--profile", "web", "--no-open", "--port", "0")
    launcher = tmp_path / "foundry"
    launcher.write_text(f'#!{sys.executable}\nimport runpy,sys\nsys.path.insert(0,{str(ROOT)!r})\n'
                        'runpy.run_module("foundry.cli",run_name="__main__")\n')
    launcher.chmod(0o700)
    env.update({"FOUNDRY_VAR": str(tmp_path / "var"), "FOUNDRY_BIN": str(launcher),
                "FOUNDRY_LLM_MODULE": (modules / "@deepseek-ai/dsh-llm/lib/index.js").as_uri(),
                "FOUNDRY_TEST_WORKSPACE": str(service.task.root / "analysis"),
                "FOUNDRY_TEST_REQUIREMENT": requirement["id"], "FOUNDRY_TEST_RUN": run["id"],
                "FOUNDRY_TEST_AFTER": after_save})
    log = tmp_path / "runtime.log"
    with log.open("w") as sink:
        child = subprocess.Popen(argv, env=env, cwd=cwd, stdout=sink, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline:
                output = log.read_text()
                if "FOUNDRY_TERMINAL " in output or "FOUNDRY_TERMINAL_ERROR " in output:
                    break
                time.sleep(.1)
        finally:
            child.terminate()
            child.wait(timeout=10)
    output = log.read_text()
    assert "FOUNDRY_TERMINAL_ERROR " not in output, output[-6000:]
    rows = [line.split(" ", 1)[1] for line in output.splitlines() if line.startswith("FOUNDRY_TERMINAL ")]
    assert rows, output[-6000:]
    observed = json.loads(rows[-1])
    (tmp_path / "public-observation.json").write_text(json.dumps(observed, ensure_ascii=False, indent=2))
    assert observed["count"] == 2 and observed["provider_calls"] == 0
    assert len(observed["saves"]) == 1
    saved = observed["saves"][0]
    assert saved["completion"]["status"] == saved["operation_status"] == "awaiting_input"
    assert saved["completion"]["stop_reason"] == "verified_input_gap"
    assert saved["completion"]["original_requirements_completed"] is False
    assert saved["completion"]["repair_allowed"] is False
    assert saved["run_ids"] == [run["id"]]
    assert "未完成" in saved["body"]
    assert observed["nextTexts"] == ["NEXT_REQUEST_NO_SAVE"] and observed["nextDeliveries"] == 0
    persisted = service.analysis.get_draft(saved["id"])
    assert persisted["body"] == saved["body"] and persisted["content_hash"] == saved["content_hash"]
    coverage = persisted["explanation_check"]["requirements"]
    assert coverage["original_requirements_completed"] is False
    item = coverage["items"][0]
    assert item["requires_drilldown"] is True and item["provenance_status"] == "pending"
    assert item["status"] == "missing_data" and item["input_gap"]["sources"]
    assert observed["texts"] == [] and observed["todoWrites"] == 0
    assert observed["ends"][-1]["kind"] == "completed"
    assert len(observed["deliveries"]) == 1
    delivered = observed["deliveries"][0]
    assert delivered["content"] == [{"type": "text", "text": saved["final_response"]}]
    assert delivered["meta"]["bindings"]["completion_status"] == "awaiting_input"
    if after_save == "text":
        assert [tool["name"] for tool in observed["tools"]] == ["save_explanation_draft"]
    else:
        assert observed["tools"][-1] == {"name": "todo_write", "call_id": "late-todo", "isError": True}
