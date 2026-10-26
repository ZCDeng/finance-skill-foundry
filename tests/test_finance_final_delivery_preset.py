"""Exercise the installed standing preset, not direct per-agent plugin mounting."""
import json
import subprocess
import time

from foundry.harness import install_presets
from test_finance_completion_fingerprint import ratio_case
from test_finance_saved_delivery import ratio_spec
from test_method_skill_runtime import ROOT, _runtime_or_skip
import test_real_load as real


def test_standing_analysis_preset_projects_current_saved_reply(tmp_path, monkeypatch):
    modules = _runtime_or_skip()
    monkeypatch.setattr(real, "DSH_BIN", str(modules / "@deepseek-ai/dsh/lib/bin.js"))
    manager, _, run, _ = ratio_case(tmp_path)
    manager.task.record_session("preset-final-reply", role="analysis")
    spec = ratio_spec(manager, run)
    # A genuine uncited amount must remain reviewable, even when the model says done.
    spec["body"] = "现金余额为 99999 元。"
    probe = r'''
export const name = 'foundry-tool-probe';
export const inject = ['agentPresets', 'llm', 'agents'];
export function apply(ctx) {
  const diagnostics=[];ctx.on('finance/delivery-observation',event=>diagnostics.push(event));
  (async () => {
    const {LlmAdapter,createUserMessage} = await import(process.env.FOUNDRY_LLM_MODULE);
    let count = 0;
    const saves = [], tools = [];
    ctx.llm.registerAdapter(['preset-final-fixture'],new class extends LlmAdapter {
      async *stream(options) {
        if (options.purpose) {
          yield {type:'block-start',index:0,blockType:'text'};
          yield {type:'block-end',index:0,block:{type:'text',text:'Saved draft'}};
          yield {type:'finish',reason:{kind:'stop'}};
          return;
        }
        if (options.sessionId!=='preset-final-reply' || count>=2) {
          const text=options.sessionId==='preset-final-reply'?'NEXT_REQUEST_NO_SAVE':'SECOND_SESSION_NO_SAVE';
          yield {type:'block-start',index:0,blockType:'text'};
          yield {type:'text-delta',index:0,text};
          yield {type:'block-end',index:0,block:{type:'text',text}};
          yield {type:'finish',reason:{kind:'stop'}};
          return;
        }
        const blocks = count++ === 0
          ? [{type:'tool-call',id:'save-current',name:'save_explanation_draft',
              arguments:JSON.stringify({spec:JSON.parse(process.env.FOUNDRY_TEST_DRAFT)})}]
          : [{type:'reasoning',text:'PRIVATE_SENTINEL'},
             {type:'text',text:'全部步骤已完成，所有检查均已通过。'},
             {type:'tool-call',id:'tool-after-review',name:'analysis-state',arguments:'{}'}];
        for (const [index,block] of blocks.entries()) {
          yield {type:'block-start',index,blockType:block.type};
          if (block.type==='text') yield {type:'text-delta',index,text:block.text};
          yield {type:'block-end',index,block};
        }
        yield {type:'finish',reason:{kind:'tool-calls'}};
      }
    }());
    await ctx.agentPresets.standingKeyFor('analysis');
    const handle = await ctx.agents.create({sessionId:'preset-final-reply',
      meta:{cwd:process.env.FOUNDRY_TEST_WORKSPACE,agentPreset:'analysis'},
      agentOptions:{provider:'preset-final-fixture',model:'deterministic'},
      setup:async(agentCtx)=>{
        await ctx.agentPresets.mount(agentCtx,'analysis');
        agentCtx.on('tools/result',(exec,result)=>{
          tools.push({callId:exec.callId,name:exec.name,isError:result.isError});
          if (exec.name==='save_explanation_draft' && result.isError===false) {
            const saved=JSON.parse(result.value.stdout);
            saves.push({final_response:saved.final_response,completion_status:saved.delivery_contract?.completion_status,
              operation_status:saved.completion_operation?.status});
          }
        });
      }});
    try {
      handle.agent.followup(createUserMessage({content:[{type:'text',text:'请保存核对稿。'}],source:{kind:'user'}}));
      await handle.agent.whenIdle();
      const events=[...handle.agent.session.events];const firstDiagnostics=diagnostics.slice();
      handle.agent.followup(createUserMessage({content:[{type:'text',text:'这是另一次请求。'}],source:{kind:'user'}}));
      await handle.agent.whenIdle();
      const nextEvents=handle.agent.session.events.slice(events.length);
      const other=await ctx.agents.create({sessionId:'preset-second-session',
        meta:{cwd:process.env.FOUNDRY_TEST_WORKSPACE,agentPreset:'analysis'},
        agentOptions:{provider:'preset-final-fixture',model:'deterministic'},
        setup:async(agentCtx)=>{await ctx.agentPresets.mount(agentCtx,'analysis');}});
      let otherEvents;
      try {
        other.agent.followup(createUserMessage({content:[{type:'text',text:'独立请求。'}],source:{kind:'user'}}));
        await other.agent.whenIdle();otherEvents=other.agent.session.events;
      } finally {await other.dispose();}
      const publicTexts=(rows)=>rows.filter(e=>e.type==='assistant/message').map(e=>e.data.message.content
        .filter(b=>b.type==='text').map(b=>b.text).join(''));
      const report={count,saves,tools,audits:firstDiagnostics.filter(e=>e.type==='finance/final-delivery'),
        ends:events.filter(e=>e.type==='turn/end').map(e=>e.data.reason),
        blockTypes:events.filter(e=>e.type==='assistant/message').map(e=>e.data.message.content.map(b=>b.type)),
        texts:publicTexts(events),nextTexts:publicTexts(nextEvents),otherTexts:publicTexts(otherEvents),
        laterAudits:diagnostics.slice(firstDiagnostics.length).filter(e=>e.type==='finance/final-delivery')};
      process.stdout.write('FOUNDRY_FINAL_REPLY '+JSON.stringify(report)+'\n');
    } finally {await handle.dispose();}
  })().catch(e=>process.stdout.write('FOUNDRY_FINAL_REPLY_ERROR '+(e.stack??e.message)+'\n'));
}
'''
    home = tmp_path / "harness"
    real._prepare(home, real._probe_package(tmp_path / "probe", probe), "web")
    install_presets(home)
    argv, env, cwd = real._dsh_args(home, "--profile", "web", "--no-open", "--port", "0")
    launcher = tmp_path / "foundry"
    launcher.write_text(f'#!{ROOT / ".venv/bin/python"}\nimport runpy,sys\nsys.path.insert(0,{str(ROOT)!r})\n'
                        'runpy.run_module("foundry.cli",run_name="__main__")\n')
    launcher.chmod(0o700)
    env.update({"FOUNDRY_VAR": str(tmp_path / "var"), "FOUNDRY_BIN": str(launcher),
                "FOUNDRY_LLM_MODULE": (modules / "@deepseek-ai/dsh-llm/lib/index.js").as_uri(),
                "FOUNDRY_TEST_WORKSPACE": str(manager.task.root / "analysis"),
                "FOUNDRY_TEST_DRAFT": json.dumps(spec), "FOUNDRY_COMPLETION_MAX_REPAIRS": "0"})
    log = tmp_path / "runtime.log"
    with log.open("w") as sink:
        child = subprocess.Popen(argv, env=env, cwd=cwd, stdout=sink, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline:
                output = log.read_text()
                if "FOUNDRY_FINAL_REPLY " in output or "FOUNDRY_FINAL_REPLY_ERROR " in output:
                    break
                time.sleep(0.1)
        finally:
            child.terminate()
            child.wait(timeout=10)
    output = log.read_text()
    assert "FOUNDRY_FINAL_REPLY_ERROR " not in output, output[-6000:]
    rows = [line.split(" ", 1)[1] for line in output.splitlines() if line.startswith("FOUNDRY_FINAL_REPLY ")]
    assert rows, output[-6000:]
    report = json.loads(rows[-1])
    assert report["count"] == 2, report
    assert report["saves"][0]["operation_status"] == "needs_review", report
    assert report["saves"][0]["completion_status"] != "complete", report
    assert len(report["audits"]) == 1, report
    audit = report["audits"][0]["data"]
    assert audit["status"] == "replaced", report
    assert audit["raw_text"] == "全部步骤已完成，所有检查均已通过。"
    assert audit["delivered_text"] == report["saves"][0]["final_response"], report
    assert "仍待专业复核" in audit["delivered_text"], report
    assert report["texts"][-1] == audit["delivered_text"], report
    assert report["blockTypes"][-1] == ["reasoning", "text", "tool-call"], report
    assert report["tools"][-1] == {"callId": "tool-after-review", "name": "analysis-state", "isError": True}, report
    assert report["ends"][-1]["reason"]["reason"] == "finance completion needs_review", report
    assert "PRIVATE_SENTINEL" not in json.dumps(report["audits"]), report
    assert report["nextTexts"] == ["NEXT_REQUEST_NO_SAVE"], report
    assert report["otherTexts"] == ["SECOND_SESSION_NO_SAVE"], report
    assert report["laterAudits"] == [], report
