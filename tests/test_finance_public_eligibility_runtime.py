"""Exercise qualification prose through the installed SDK and actual native CLI."""
import json
import os
import subprocess
import sys

import pytest

from foundry.finance_claim_semantics import CLAIM_SEMANTICS_VERSION
from test_finance_performance_semantics import performance_case
from test_finance_public_eligibility_claims import CLAIM, CODE, ROOT
from test_method_skill_runtime import _runtime_or_skip


@pytest.mark.parametrize('body,expected', [
    pytest.param(CLAIM, 'contradicted', id='archived-mixed'),
    pytest.param('来源绑定输入不具备金额证据资格。', 'unchanged', id='literal-negative'),
    pytest.param('Input_facts are model_verified for period=1900-01.', 'unverifiable', id='post-period'),
    pytest.param('Input_facts are model_verified for scenario_id=FOREIGN-SCENARIO.', 'unverifiable', id='post-scenario'),
    pytest.param('Input_facts are model_verified for run_id=FOREIGN-RUN.', 'unverifiable', id='post-run'),
])
def test_production_sdk_native_prepare_cannot_publish_input_qualification_promotion(tmp_path, body, expected):
    manager, context, _, initial = performance_case(tmp_path)
    session_id = 'native-sdk-qualification'
    manager.task.record_session(session_id, role='analysis')
    modules = _runtime_or_skip() / '@deepseek-ai'
    driver = tmp_path / 'native-qualification-loop.mjs'
    imports = '\n'.join(f"import {name} from {(modules / package / 'lib/index.js').as_uri()!r};"
        for name, package in [('Agents', 'dsh-agent'), ('Sessions', 'dsh-session'), ('Llm', 'dsh-llm'),
                              ('Tools', 'dsh-tools'), ('Prompt', 'dsh-system-prompt'), ('Loop', 'dsh-agent-loop')])
    driver.write_text(imports + f'''
import assert from 'node:assert/strict';
import {{writeFileSync}} from 'node:fs';
import {{Context}} from {(modules / 'cordis/lib/index.js').as_uri()!r};
import {{LlmAdapter,createUserMessage}} from {(modules / 'dsh-llm/lib/index.js').as_uri()!r};
import {{apply}} from {(ROOT / 'dsh-plugin/analysis.js').as_uri()!r};
const ctx=new Context();const diagnostics=[];
ctx.on('finance/delivery-observation',event=>diagnostics.push(event));
await ctx.plugin(Agents,{{}});await ctx.plugin(Sessions,{{}});await ctx.plugin(Llm,{{}});
await ctx.plugin(Prompt,{{includeHarnessIdentity:false,includeRuntimeContext:false}});
await ctx.plugin(Tools,{{}});await ctx.plugin(Loop,{{agents:[],maxParallelToolCalls:1}});ctx.provide('subagents',{{}});
let calls=0,runId,prepared,nextMessages;
const raw='普通进度🙂。\\r\\n'+{json.dumps(body, ensure_ascii=False)}+'\\r\\n现在继续保存。';
const toolResults=[];
function* tool(name,id,spec){{const args=JSON.stringify({{spec}});
yield{{type:'block-start',index:1,blockType:'tool-call'}};
yield{{type:'tool-call-delta',index:1,id,name,argumentsDelta:args}};
yield{{type:'block-end',index:1,block:{{type:'tool-call',id,name,arguments:args}}}};}}
class Offline extends LlmAdapter{{async *stream(options){{calls++;
if(calls===1)yield*tool('finance_scenario_run','qualification-run',{{scenario_id:{initial['result']['scenario_id']!r}}});
else if(calls===2)yield*tool('prepare_explanation','qualification-prepare',{{run_ids:[runId]}});
else if(calls===3){{
 yield{{type:'block-start',index:0,blockType:'text'}};
 for(const text of raw)yield{{type:'text-delta',index:0,text}};
 yield{{type:'block-end',index:0,block:{{type:'text',text:raw}}}};
 yield*tool('finance_profile_status','qualification-status',{{context_id:{context['id']!r}}});
}}else{{nextMessages=options.messages;
 yield{{type:'block-start',index:0,blockType:'text'}};
 yield{{type:'text-delta',index:0,text:'已继续处理。'}};
 yield{{type:'block-end',index:0,block:{{type:'text',text:'已继续处理。'}}}};
}}
yield{{type:'finish',reason:{{kind:calls<4?'tool-calls':'stop'}}}};
}}}}
ctx.llm.registerAdapter(['offline'],new Offline());
const handle=await ctx.agents.create({{sessionId:{session_id!r},agentOptions:{{provider:'offline',model:'fake'}},setup(agentCtx){{
apply(agentCtx);agentCtx.on('tools/result',(exec,result)=>{{
toolResults.push({{name:exec.name,call_id:exec.callId,isError:result.isError}});
if(!result.isError&&exec.name==='finance_scenario_run')runId=JSON.parse(result.value.stdout).id;
if(!result.isError&&exec.name==='prepare_explanation')prepared=JSON.parse(result.value.stdout);
}});}}}});
handle.agent.followup(createUserMessage({{content:[{{type:'text',text:'核对输入和输出资格。'}}],source:{{kind:'user'}}}}));
await handle.agent.whenIdle();
const events=handle.agent.session.events;
const held=diagnostics.find(e=>e.type==='finance/public-text-delivery'&&e.data.phase==='held'&&e.data.raw_text===raw);
const selected=diagnostics.find(e=>e.type==='finance/public-text-delivery'&&e.data.phase==='selected'&&e.data.raw_text===raw);
const deltas=events.filter(e=>e.type==='assistant/chunk'&&e.data.chunk.type==='text-delta');
const ends=events.filter(e=>e.type==='assistant/chunk'&&e.data.chunk.type==='block-end'&&e.data.chunk.block.type==='text');
const messages=events.filter(e=>e.type==='assistant/message').flatMap(e=>e.data.message.content)
 .filter(b=>b.type==='text').map(b=>b.text);
const derived=handle.agent.session.deriveMessages().flatMap(m=>m.content??[]).filter(b=>b.type==='text').map(b=>b.text);
const meta=f=>({{id:f.id,run_id:f.run_id,row:f.row,column:f.column,evidence_eligibility:{{
 status:f.evidence_eligibility?.status,counts_as_amount_evidence:f.evidence_eligibility?.counts_as_amount_evidence}}}});
const observation={{raw,run_id:runId,held,selected,actual_deltas:deltas.map(e=>({{seq:e.seq,text:e.data.chunk.text}})),
 actual_block_ends:ends.map(e=>({{seq:e.seq,text:e.data.chunk.block.text}})),actual_message_texts:messages,
 derived_texts:derived,next_round_public_texts:(nextMessages??[]).flatMap(m=>m.content??[])
 .filter(b=>b.type==='text').map(b=>b.text),toolResults,
 actual_tool_calls:events.filter(e=>e.type==='tool/call').map(e=>({{seq:e.seq,name:e.data.name,
 call_id:e.data.callId,arguments:e.data.arguments}})),
 actual_prepare:prepared?{{fact_view_contract:prepared.fact_view_contract,outputs:prepared.facts.map(meta),
 inputs:prepared.input_facts.map(meta)}}:null,calls,provider_calls:0,private_reasoning_extracted:false}};
const {{DeepSeekAdapter,resolveAdapterOptions}}=await import({(modules / 'dsh-llm-deepseek/lib/index.js').as_uri()!r});
const originalFetch=globalThis.fetch;let wire;
globalThis.fetch=async(_url,options)=>{{wire=JSON.parse(options.body);return new Response(
 'data: {{"choices":[{{"delta":{{"content":"ok"}},"finish_reason":"stop"}}]}}\\n\\ndata: [DONE]\\n\\n',
 {{status:200,headers:{{'content-type':'text/event-stream'}}}});}};
try{{const connection=resolveAdapterOptions({{baseURL:'https://offline.invalid',models:[{{id:'fake'}}]}},undefined);
 const adapter=new DeepSeekAdapter({{options:()=>connection,resolveApiKey:async()=> 'offline-stub',resolveUserId:()=> 'offline'}});
 for await(const _chunk of adapter.stream({{model:'fake',messages:nextMessages}})){{}}
 observation.adapter_serialized_public_texts=wire.messages.map(m=>m.content).filter(t=>typeof t==='string');
}}finally{{globalThis.fetch=originalFetch;}}
writeFileSync({str(tmp_path / 'actual-native-sdk-qualification.json')!r},JSON.stringify(observation,null,2));
await handle.dispose();
assert.ok(held&&selected,JSON.stringify({{calls,toolResults}}));
assert.equal(calls,4);
for(const name of ['finance_scenario_run','prepare_explanation','finance_profile_status']){{
 assert.equal(toolResults.filter(r=>r.name===name&&!r.isError).length,1);
}}
assert.deepEqual(JSON.parse(observation.actual_tool_calls[0].arguments),
 {{spec:{{scenario_id:{initial['result']['scenario_id']!r}}}}});
assert.deepEqual(JSON.parse(observation.actual_tool_calls[1].arguments),{{spec:{{run_ids:[runId]}}}});
assert.ok(observation.actual_prepare.inputs.every(f=>f.evidence_eligibility.status==='unverified'
 &&f.evidence_eligibility.counts_as_amount_evidence===false));
assert.ok(observation.actual_prepare.outputs.every(f=>f.evidence_eligibility.status==='model_verified'
 &&f.evidence_eligibility.counts_as_amount_evidence===true));
assert.ok(diagnostics.indexOf(held)<diagnostics.indexOf(selected)&&selected.observed_after_seq<deltas[0].seq);
if({expected!r}==='unverifiable')assert.equal(selected.data.server_source_binding,null);
else assert.equal(selected.data.server_source_binding.claim_semantics_version,{CLAIM_SEMANTICS_VERSION});
assert.equal(selected.data.runtime_request_binding.capture.tool_name,'prepare_explanation');
assert.equal(selected.data.status,{expected!r});
assert.equal(selected.data.issues.some(i=>i.code==={CODE!r}),{expected!r}==='contradicted');
assert.ok(selected.data.delivered_text.startsWith('普通进度🙂。\\r\\n'));
assert.ok(selected.data.delivered_text.endsWith('\\r\\n现在继续保存。'));
assert.equal(messages[0],selected.data.delivered_text);
assert.equal(ends[0].data.chunk.block.text,selected.data.delivered_text);
assert.equal(deltas.filter(e=>e.seq<ends[0].seq).map(e=>e.data.chunk.text).join(''),selected.data.delivered_text);
for(const surface of [messages,derived,observation.next_round_public_texts,observation.adapter_serialized_public_texts]){{
 assert.ok(surface.includes(selected.data.delivered_text));
 if({expected!r}!=='unchanged')assert.ok(!surface.includes(raw));
}}
console.log(JSON.stringify({{passed:true,calls,toolResults,provider_calls:0}}));
''')
    launcher = tmp_path / 'foundry'
    launcher.write_text(f'#!{sys.executable}\nimport runpy,sys\nsys.path.insert(0,{str(ROOT)!r})\n'
                        'runpy.run_module("foundry.cli",run_name="__main__")\n')
    launcher.chmod(0o700)
    observed = subprocess.run(['node', str(driver)], cwd=ROOT, text=True, capture_output=True,
        env=os.environ | {'FOUNDRY_BIN': str(launcher), 'FOUNDRY_VAR': str(tmp_path / 'var')}, timeout=60)
    (tmp_path / 'actual-native-sdk-qualification-process.json').write_text(json.dumps({
        'exit_code': observed.returncode, 'stdout': observed.stdout, 'stderr': observed.stderr,
        'provider_calls': 0,
    }, ensure_ascii=False, indent=2))
    assert observed.returncode == 0, observed.stderr
    assert json.loads(observed.stdout)['passed']


def test_transport_failure_masks_only_bounded_qualification_assertions(tmp_path):
    """Actual runtime hook fallback cannot revive metadata when native CLI fails."""
    driver = tmp_path / 'qualification-transport.mjs'
    bad = [CLAIM, 'All `input_facts` are `model_verified`.',
           'All input_facts have counts_as_amount_evidence=true.',
           'Input_facts have evidence_eligibility.status=source_verified.',
           'Do not call output facts unverified, input_facts are model_verified.']
    good = ['普通进度🙂。', 'Network error; continue retry diagnostics.',
            'Source-bound inputs are traceable to archived rows.',
            'All source-bound inputs are source-verified in source_binding_status.',
            'Do not say all input_facts are model_verified.',
            'All input_facts are model_verified, this statement is incorrect.',
            'All input_facts are model_verified?',
            'If all input_facts are model_verified, discuss their scope.',
            '字段代码示例：`input_facts.evidence_eligibility.status = "model_verified"`。',
            '```json\n{"input_facts":{"status":"model_verified"}}\n```']
    driver.write_text(f'''
import assert from 'node:assert/strict';
import {{writeFileSync}} from 'node:fs';
import {{installFinalDeliveryRuntime}} from {(ROOT / 'dsh-plugin/final-delivery-runtime.js').as_uri()!r};
const bad={json.dumps(bad, ensure_ascii=False)};
const good={json.dumps(good, ensure_ascii=False)};
const results=[];
for(const [expected,items] of [[false,bad],[true,good]])for(const body of items){{
 const events=[{{seq:0,type:'user/message',data:{{id:'u1',source:{{kind:'user'}}}}}}];
 const session={{events,append(type,data){{const e={{seq:events.length,type,data:structuredClone(data)}};events.push(e);return e;}}}};
 const agent={{id:'s1',session}},handlers={{}};
 const ctx={{on(name,fn){{handlers[name]=fn;}},emit(_name,event){{events.push({{...event,seq:events.length}});}},agents:{{get:id=>id==='s1'?agent:undefined,currentInitiator:()=>agent}}}};
 installFinalDeliveryRuntime(ctx,async()=>{{throw Error('not a save');}},async()=>{{throw Error('native CLI unavailable');}});
 const rawRun={{id:'run',task_id:'task',requirements_id:'req',output_hash:'output',session_id:'s1',context_revision:3,
  result:{{template_id:'three_statement',scenario_id:'scenario'}}}};
 session.append('tool/call',{{name:'finance_scenario_run',callId:'once'}});
 handlers['tools/result']({{name:'finance_scenario_run',callId:'once',agent}},
  {{isError:false,value:{{tool:'finance_scenario_run',stdout:JSON.stringify(rawRun)}}}});
 const raw='普通进度🙂。\\r\\n'+body+'\\r\\n继续保存。';
 const input=[{{type:'block-start',index:0,blockType:'text'}},...Array.from(raw,text=>({{type:'text-delta',index:0,text}})),
  {{type:'block-end',index:0,block:{{type:'text',text:raw}}}},{{type:'finish',reason:{{kind:'stop'}}}}];
 const out=[];for await(const c of handlers['llm/stream']({{sessionId:'s1'}},async function*(){{yield*input;}}))out.push(c);
 const delivered=out.filter(c=>c.type==='text-delta').map(c=>c.text).join('');
 results.push({{body,expected_exact:expected,raw,delivered,audits:events.filter(e=>e.type==='finance/public-text-delivery')}});
 assert.equal(delivered===raw,expected,body);
 assert.ok(delivered.startsWith('普通进度🙂。\\r\\n')&&delivered.endsWith('\\r\\n继续保存。'));
}}
writeFileSync({str(tmp_path / 'actual-qualification-transport.json')!r},JSON.stringify(results,null,2));
console.log(JSON.stringify({{passed:true,cases:results.length,provider_calls:0}}));
''')
    result = subprocess.run(['node', str(driver)], cwd=ROOT, text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('body,requires_source_read', [
    pytest.param('会话稿甲：Falcon 收入 100。', False, id='ordinary-finance-prose'),
    pytest.param('查看已保存的结果。', False, id='ordinary-receipt-prose'),
    pytest.param('Input_facts are model_verified.', True, id='qualification-reloads-source'),
    pytest.param('本期待履约收款。', True, id='performance-reloads-source'),
])
def test_current_saved_reads_skip_source_io_only_without_mutable_assertions(body, requires_source_read):
    from foundry.finance_explanations import saved_claim_semantic_issues

    class SourceReadRequired(RuntimeError):
        pass

    class Analysis:
        def get_run(self, run_id):
            raise SourceReadRequired(run_id)

    draft = {'body': body, 'run_ids': ['current-run'],
             'explanation_check': {'claim_semantics_version': CLAIM_SEMANTICS_VERSION}}
    if requires_source_read:
        with pytest.raises(SourceReadRequired, match='current-run'):
            saved_claim_semantic_issues(Analysis(), draft)
    else:
        assert saved_claim_semantic_issues(Analysis(), draft) == []
