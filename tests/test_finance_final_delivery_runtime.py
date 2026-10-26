"""The real stream boundary, not an evaluation observation, owns delivery text."""
import json
import os
import subprocess

from test_finance_runtime_payload import ROOT
from test_finance_completion_fingerprint import ratio_case
from test_finance_saved_delivery import ratio_spec
from test_method_skill_runtime import _runtime_or_skip


def test_output_hook_preserves_raw_and_refuses_unproven_replacements():
    script = r'''
import assert from 'node:assert/strict';
import {installFinalDeliveryRuntime,UNVERIFIED_REPLY} from './dsh-plugin/final-delivery-runtime.js';
const saved = {id:'draft',task_id:'task',requirements_id:'req',run_ids:['run'],
 content_hash:'hash',completion:{id:'receipt',status:'complete'},
 final_response:'已保存完成；仍待专业复核。',delivery_contract:{draft_id:'draft',receipt_id:'receipt',completion_status:'complete'}};
const text = (s) => [{type:'block-start',index:0,blockType:'text'},
 {type:'text-delta',index:0,text:s},{type:'block-end',index:0,block:{type:'text',text:s}},
 {type:'usage',usage:{inputTokens:3,outputTokens:4,totalTokens:7}},
 {type:'finish',reason:{kind:'stop'}}];
function fixture(savedResult=saved) {
 const events=[{seq:0,type:'user/message',data:{id:'u1',source:{kind:'user'},content:[]}}];
 const session={events,append(type,data){const e={seq:events.length,type,data:structuredClone(data)};events.push(e);return e;}};
 const agent={id:'s1',session};const handlers={};const checks=[];
 const ctx={on(n,f){handlers[n]=f;},emit(_name,event){events.push({...event,seq:events.length});},agents:{get:id=>id==='s1'?agent:undefined,currentInitiator:()=>agent}};
 let valid=true;
 installFinalDeliveryRuntime(ctx,async(spec,exec)=>{
   checks.push({spec,session:exec.agent.id});
   return valid?{verified:true,final_response:savedResult.final_response,bindings:{session_id:'s1',task_id:'task',
   request_key:spec.request_key,call_id:'save',draft_id:'draft',receipt_id:'receipt',requirements_id:'req',run_ids:['run'],
   draft_content_hash:'hash',completion_status:savedResult.delivery_contract.completion_status,
   deadline_at:new Date(Date.now()+30000).toISOString()}}:
   {verified:false,reason:'delivery_proof_not_current'};
 });
 const emit=(value=savedResult,isError=false)=>handlers['tools/result']({name:'save_explanation_draft',callId:'save',agent},
   isError?{isError:true}:{isError:false,value:{tool:'save_explanation_draft',stdout:JSON.stringify(value)}});
 const run=async(chunks=text('模型额外扩写。'),options={})=>{
   const result=[];for await(const c of handlers['llm/stream']({sessionId:'s1',signal:new AbortController().signal,...options},
     async function*(){yield* chunks;}))result.push(c);return result;};
 return {agent,events,emit,run,checks,setValid(v){valid=v;}};
}
const f=fixture();f.emit();const original=text('模型额外扩写。');
const out=await f.run(original);
assert.equal(out.find(x=>x.type==='text-delta').text,saved.final_response);
assert.deepEqual(out.find(x=>x.type==='usage'),original.find(x=>x.type==='usage'));
const audit=f.events.find(x=>x.type==='finance/final-delivery');
assert.equal(audit.data.raw_text,'模型额外扩写。');assert.equal(audit.data.delivered_text,saved.final_response);
assert.equal(audit.data.status,'replaced');assert.equal(audit.surfaceOp,undefined);
assert.equal(f.checks.length,1);
for(const kind of ['no-save','failed-save','new-user','invalid-proof','auxiliary','wrong-session','empty','error','max-tokens','tools']){
 const g=fixture();if(kind!=='no-save')g.emit();
 if(kind==='failed-save')g.emit(null,true);
 if(kind==='new-user')g.events.push({seq:1,type:'user/message',data:{id:'u2',source:{kind:'user'},content:[]}});
 if(kind==='invalid-proof')g.setValid(false);
 let chunks=text('不得伪造完成。'),options={};
 if(kind==='auxiliary')options.purpose='session-title';
 if(kind==='wrong-session')options.sessionId='other';
 if(kind==='empty')chunks=[{type:'finish',reason:{kind:'stop'}}];
 if(['error','max-tokens'].includes(kind))chunks[chunks.length-1]={type:'finish',reason:{kind, failure:{message:'failed',code:'TEST'}}};
 if(kind==='tools')chunks.splice(0,0,{type:'block-start',index:1,blockType:'tool-call'},
   {type:'tool-call-delta',index:1,id:'call',name:'x',argumentsDelta:'{}'},
   {type:'block-end',index:1,block:{type:'tool-call',id:'call',name:'x',arguments:{}}});
 const delivered=await g.run(chunks,options);
 if(['failed-save','invalid-proof'].includes(kind)) {
  assert.equal(delivered.find(x=>x.type==='text-delta').text,UNVERIFIED_REPLY,kind);
  assert.equal(g.events.at(-1).data.raw_text,'不得伪造完成。');
 } else assert.deepEqual(delivered,chunks,kind);
}
const h=fixture();h.emit();const reasoning=[{type:'block-start',index:7,blockType:'reasoning'},
 {type:'reasoning-delta',index:7,text:'PRIVATE_SENTINEL'},
 {type:'block-end',index:7,block:{type:'reasoning',text:'PRIVATE_SENTINEL'}}];
await h.run([...reasoning,...text('public')]);
assert.ok(!JSON.stringify(h.events.filter(x=>x.type==='finance/final-delivery')).includes('PRIVATE_SENTINEL'));
const toolChunks=[{type:'block-start',index:8,blockType:'tool-call'},
 {type:'tool-call-delta',index:8,id:'after-save',name:'answer_cards',argumentsDelta:'{}'},
 {type:'block-end',index:8,block:{type:'tool-call',id:'after-save',name:'answer_cards',arguments:'{}'}}];
const mixed=[...reasoning,...text('全部步骤完成，检查全部通过。').slice(0,-1),...toolChunks,
 {type:'finish',reason:{kind:'tool-calls'},replayState:{untrusted:'original-provider-content'}}];
for(const status of ['complete','needs_review','awaiting_manager']) {
 const pending={...saved,final_response:status==='complete'?saved.final_response:'草稿已保存，仍待经理专业复核。',
   delivery_contract:{...saved.delivery_contract,completion_status:status}};
 const g=fixture(pending);g.emit();const delivered=await g.run(mixed);
 assert.equal(delivered.find(x=>x.type==='text-delta').text,pending.final_response,status);
 assert.deepEqual(delivered.filter(x=>x.index===8),toolChunks,status);
 assert.deepEqual(delivered.filter(x=>x.index===7),reasoning,status);
 assert.equal(delivered.at(-1).reason.kind,'tool-calls');
 assert.equal(delivered.at(-1).replayState,undefined);
 const audit=g.events.find(x=>x.type==='finance/final-delivery').data;
 assert.equal(audit.raw_text,'全部步骤完成，检查全部通过。');
 assert.equal(audit.status,'replaced');assert.equal(audit.bindings.completion_status,status);
 assert.ok(!JSON.stringify(audit).includes('PRIVATE_SENTINEL'));
}
for(const kind of ['no-save','failed-save','new-user','auxiliary','wrong-session']) {
 const g=fixture();if(kind!=='no-save')g.emit();
 if(kind==='failed-save')g.emit(null,true);
 if(kind==='new-user')g.events.push({seq:1,type:'user/message',data:{id:'u2',source:{kind:'user'},content:[]}});
 const options=kind==='auxiliary'?{purpose:'session-title'}:kind==='wrong-session'?{sessionId:'other'}:{};
 const delivered=await g.run(mixed,options);
 if(kind==='failed-save') assert.equal(delivered.find(x=>x.type==='text-delta').text,UNVERIFIED_REPLY);
 else assert.deepEqual(delivered,mixed,kind);
}
console.log(JSON.stringify({passed:true,cases:21}));
'''
    result = subprocess.run(['node', '--input-type=module', '-e', script], cwd=ROOT,
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['passed']


def test_real_analysis_plugin_agent_loop_delivers_verified_text_before_persistence(tmp_path):
    manager, _, run, _ = ratio_case(tmp_path)
    manager.task.record_session('delivery-loop', role='analysis')
    spec = ratio_spec(manager, run)
    modules = _runtime_or_skip() / '@deepseek-ai'
    driver = tmp_path / 'real-loop.mjs'
    imports = '\n'.join(f"import {name} from {(modules / package / 'lib/index.js').as_uri()!r};"
                        for name, package in [('Agents', 'dsh-agent'), ('Sessions', 'dsh-session'),
                                              ('Llm', 'dsh-llm'), ('Tools', 'dsh-tools'),
                                              ('Prompt', 'dsh-system-prompt'), ('Loop', 'dsh-agent-loop')])
    driver.write_text(imports + f'''
import {{Context}} from {(modules / 'cordis/lib/index.js').as_uri()!r};
import {{LlmAdapter,createUserMessage}} from {(modules / 'dsh-llm/lib/index.js').as_uri()!r};
import {{apply}} from {(ROOT / 'dsh-plugin/analysis.js').as_uri()!r};
const ctx=new Context();
await ctx.plugin(Agents,{{}});await ctx.plugin(Sessions,{{}});await ctx.plugin(Llm,{{}});
await ctx.plugin(Prompt,{{includeHarnessIdentity:false,includeRuntimeContext:false}});
await ctx.plugin(Tools,{{}});await ctx.plugin(Loop,{{agents:[],maxParallelToolCalls:1}});
ctx.provide('subagents',{{}});
let calls=0;
class Fake extends LlmAdapter {{
 async *stream(options) {{
  calls++;
  if(calls===1) {{
   const args=JSON.stringify({{spec:{json.dumps(spec, ensure_ascii=False)}}});
   yield {{type:'block-start',index:0,blockType:'tool-call'}};
   yield {{type:'tool-call-delta',index:0,id:'save-call',name:'save_explanation_draft',argumentsDelta:args}};
   yield {{type:'block-end',index:0,block:{{type:'tool-call',id:'save-call',name:'save_explanation_draft',arguments:args}}}};
   yield {{type:'finish',reason:{{kind:'tool-calls'}}}};
  }} else {{
   const text='模型额外扩写了正文不存在的检查明细。';
   yield {{type:'block-start',index:0,blockType:'text'}};
   yield {{type:'text-delta',index:0,text}};
   yield {{type:'block-end',index:0,block:{{type:'text',text}}}};
   yield {{type:'usage',usage:{{inputTokens:11,outputTokens:12,totalTokens:23}}}};
   yield {{type:'finish',reason:{{kind:'stop'}}}};
  }}
 }}
}}
ctx.llm.registerAdapter(['offline'],new Fake());
const handle=await ctx.agents.create({{sessionId:'delivery-loop',agentOptions:{{provider:'offline',model:'fake'}},
 setup(agentCtx){{apply(agentCtx);}}}});
handle.agent.followup(createUserMessage({{content:[{{type:'text',text:'请保存核对稿。'}}],source:{{kind:'user'}}}}));
await handle.agent.whenIdle();
const events=handle.agent.session.events;
const delivery=events.find(e=>e.type==='tool/result'&&e.data.meta?.final_delivery);
const texts=events.filter(e=>e.type==='assistant/message').map(e=>e.data.message.content.filter(b=>b.type==='text').map(b=>b.text).join(''));
const chunks=events.filter(e=>e.type==='assistant/chunk'&&e.data.chunk.type==='text-delta').map(e=>e.data.chunk.text);
const ends=events.filter(e=>e.type==='turn/end').map(e=>e.data.reason);
const toolResults=events.filter(e=>e.type==='tool/result').map(e=>({{isError:e.data.message.isError,error:e.data.error}}));
process.stdout.write(JSON.stringify({{calls,delivery,texts,chunks,ends,toolResults}}));
await handle.dispose();
''')
    foundry = tmp_path / 'foundry'
    foundry.write_text(f'#!{ROOT / ".venv/bin/python"}\nimport runpy,sys\nsys.path.insert(0,{str(ROOT)!r})\n'
                       'runpy.run_module("foundry.cli",run_name="__main__")\n')
    foundry.chmod(0o700)
    env = os.environ | {'FOUNDRY_BIN': str(foundry), 'FOUNDRY_VAR': str(tmp_path / 'var')}
    result = subprocess.run(['node', str(driver)], cwd=ROOT, env=env, text=True,
                            capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout)
    assert observed['calls'] == 1, observed
    delivery = observed['delivery']
    marker = delivery['data']['meta']['final_delivery']
    assert marker['status'] == 'verified' and marker['channel'] == 'tool/result'
    assert delivery['data']['message']['source']['kind'] == 'tool'
    assert delivery['data']['message']['content'][0]['content'] == [
        {'type': 'text', 'text': marker['final_response']}]
    assert marker['bindings']['session_id'] == 'delivery-loop'
    assert marker['bindings']['completion_status'] == 'complete'
    assert observed['texts'] == [''] and observed['chunks'] == []
    assert observed['ends'][-1]['kind'] == 'completed'
