"""Public check assertions are held at the real SDK delivery boundary."""
import json
import os
import subprocess
import sys

from test_finance_runtime_payload import ROOT
from test_method_skill_runtime import _runtime_or_skip


def test_public_text_runtime_order_identity_and_fail_closed():
    observed = subprocess.run(['node', str(ROOT / 'tests/finance_public_stream_runtime.mjs')],
                              cwd=ROOT, text=True, capture_output=True, timeout=30)
    assert observed.returncode == 0, observed.stderr
    assert json.loads(observed.stdout)['passed']


def test_public_text_real_sdk_delivery_and_pending_user(tmp_path):
    modules = _runtime_or_skip()
    observed = subprocess.run(['node', str(ROOT / 'tests/finance_public_stream_sdk.mjs'),
                               str(modules), str(tmp_path)], cwd=ROOT, text=True,
                              capture_output=True, timeout=60)
    assert observed.returncode == 0, observed.stderr
    assert json.loads(observed.stdout)['passed']


def test_production_sdk_guard_uses_actual_native_cli_and_result(tmp_path):
    from test_finance_professional_protocol import _template_case
    from foundry.finance_claim_semantics import CLAIM_SEMANTICS_VERSION
    manager, _, _, initial = _template_case(tmp_path)
    session_id = 'native-sdk-public'
    manager.task.record_session(session_id, role='analysis')
    modules = _runtime_or_skip() / '@deepseek-ai'
    driver = tmp_path / 'native-public-loop.mjs'
    imports = '\n'.join(f"import {name} from {(modules / package / 'lib/index.js').as_uri()!r};"
        for name, package in [('Agents', 'dsh-agent'), ('Sessions', 'dsh-session'), ('Llm', 'dsh-llm'),
                              ('Tools', 'dsh-tools'), ('Prompt', 'dsh-system-prompt'), ('Loop', 'dsh-agent-loop')])
    driver.write_text(imports + f'''
import assert from 'node:assert/strict';
import {{Context}} from {(modules / 'cordis/lib/index.js').as_uri()!r};
import {{LlmAdapter,createUserMessage}} from {(modules / 'dsh-llm/lib/index.js').as_uri()!r};
import {{apply}} from {(ROOT / 'dsh-plugin/analysis.js').as_uri()!r};
const ctx=new Context();const diagnostics=[];
ctx.on('finance/delivery-observation',event=>diagnostics.push(event));
await ctx.plugin(Agents,{{}});await ctx.plugin(Sessions,{{}});await ctx.plugin(Llm,{{}});
await ctx.plugin(Prompt,{{includeHarnessIdentity:false,includeRuntimeContext:false}});
await ctx.plugin(Tools,{{}});await ctx.plugin(Loop,{{agents:[],maxParallelToolCalls:1}});ctx.provide('subagents',{{}});
let calls=0,runId,toolCalls=[];
const raw='普通进度🙂。\\nAll 12 model checks `pass` (differences = 0).\\n现在准备说明。';
function* tool(name,id,spec){{const args=JSON.stringify({{spec}});
yield{{type:'block-start',index:1,blockType:'tool-call'}};yield{{type:'tool-call-delta',index:1,id,name,argumentsDelta:args}};
yield{{type:'block-end',index:1,block:{{type:'tool-call',id,name,arguments:args}}}};}}
class Offline extends LlmAdapter{{async *stream(){{calls++;
if(calls===1){{yield*tool('finance_scenario_run','native-run',{{scenario_id:{initial['result']['scenario_id']!r}}});}}
else if(calls===2){{yield{{type:'block-start',index:0,blockType:'text'}};for(const text of raw)yield{{type:'text-delta',index:0,text}};
yield{{type:'block-end',index:0,block:{{type:'text',text:raw}}}};yield*tool('prepare_explanation','prepare',{{run_ids:[runId]}});}}
else{{yield{{type:'block-start',index:0,blockType:'text'}};yield{{type:'text-delta',index:0,text:'已继续准备。'}};
yield{{type:'block-end',index:0,block:{{type:'text',text:'已继续准备。'}}}};}}
yield{{type:'finish',reason:{{kind:calls<3?'tool-calls':'stop'}}}};}}}}
ctx.llm.registerAdapter(['offline'],new Offline());
const handle=await ctx.agents.create({{sessionId:{session_id!r},agentOptions:{{provider:'offline',model:'fake'}},setup(agentCtx){{
apply(agentCtx);agentCtx.on('tools/result',(exec,result)=>{{toolCalls.push({{name:exec.name,isError:result.isError}});
if(exec.name==='finance_scenario_run'&&!result.isError)runId=JSON.parse(result.value.stdout).id;}});}}}});
handle.agent.followup(createUserMessage({{content:[{{type:'text',text:'核对三表。'}}],source:{{kind:'user'}}}}));
await handle.agent.whenIdle();const events=handle.agent.session.events;
const held=diagnostics.find(e=>e.type==='finance/public-text-delivery'&&e.data.phase==='held'&&e.data.raw_text===raw);
const selected=diagnostics.find(e=>e.type==='finance/public-text-delivery'&&e.data.phase==='selected'&&e.data.raw_text===raw);
assert.ok(held&&selected,JSON.stringify({{calls,toolCalls}}));assert.equal(selected.data.status,'contradicted');
assert.equal(selected.data.server_source_binding.run_id,runId);assert.equal(selected.data.server_source_binding.claim_semantics_version,{CLAIM_SEMANTICS_VERSION});
assert.ok(selected.data.delivered_text.startsWith('普通进度🙂。\\n'));assert.ok(selected.data.delivered_text.endsWith('\\n现在准备说明。'));
const first=events.find(e=>e.type==='assistant/chunk'&&e.data.chunk.type==='text-delta');
assert.ok(diagnostics.indexOf(held)<diagnostics.indexOf(selected)&&selected.observed_after_seq<first.seq);
assert.equal(events.filter(e=>e.type==='assistant/message').flatMap(e=>e.data.message.content).filter(b=>b.type==='text')[0].text,selected.data.delivered_text);
assert.ok(!events.filter(e=>e.type==='assistant/chunk'&&e.data.chunk.type==='text-delta').some(e=>e.data.chunk.text.includes('differences = 0')));
assert.ok(!JSON.stringify(handle.agent.session.deriveMessages()).includes('differences = 0'));
assert.equal(toolCalls.filter(c=>c.name==='finance_scenario_run'&&!c.isError).length,1);
assert.equal(toolCalls.filter(c=>c.name==='prepare_explanation'&&!c.isError).length,1);
await handle.dispose();console.log(JSON.stringify({{passed:true,calls,toolCalls,provider_calls:0}}));
''')
    launcher = tmp_path / 'foundry'
    launcher.write_text(f'#!{sys.executable}\nimport runpy,sys\nsys.path.insert(0,{str(ROOT)!r})\n'
                        'runpy.run_module("foundry.cli",run_name="__main__")\n')
    launcher.chmod(0o700)
    observed = subprocess.run(['node', str(driver)], cwd=ROOT, text=True, capture_output=True,
        env=os.environ | {'FOUNDRY_BIN': str(launcher), 'FOUNDRY_VAR': str(tmp_path / 'var')}, timeout=60)
    assert observed.returncode == 0, observed.stderr
    assert json.loads(observed.stdout)['passed']
