import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import { join } from 'node:path';
import { installFinalDeliveryRuntime } from '../dsh-plugin/final-delivery-runtime.js';
import { toolDefinition } from '../dsh-plugin/index.js';
const base=process.argv[2];
const mod=async name=>import(pathToFileURL(join(base,'@deepseek-ai',name,'lib/index.js')));
const {Context}=await mod('cordis');
const modules=await Promise.all(['dsh-agent','dsh-session','dsh-llm','dsh-tools','dsh-system-prompt','dsh-agent-loop'].map(mod));
const {LlmAdapter,createUserMessage}=modules[2];
const {DeepSeekAdapter,resolveAdapterOptions}=await mod('dsh-llm-deepseek');
const hash=text=>createHash('sha256').update(text).digest('hex');
const bad='All 12 model checks `pass` (differences = 0).';
const safe='All 12 model checks `pass` (differences require verification).';
const toolChunks=(name,id,args)=>[{type:'block-start',index:2,blockType:'tool-call'},
  {type:'tool-call-delta',index:2,id,name,argumentsDelta:args},
  {type:'block-end',index:2,block:{type:'tool-call',id,name,arguments:args}}];
const textChunks=(text,index=0)=>[{type:'block-start',index,blockType:'text'},
  {type:'text-delta',index,text},{type:'block-end',index,block:{type:'text',text}}];
function proof(spec){return {schema_version:1,verified:true,status:spec.text===bad?'contradicted':'unchanged',
  reason:'native_checks_current',raw_text_sha256:hash(spec.text),delivered_text:spec.text===bad?safe:spec.text,
  delivered_text_sha256:hash(spec.text===bad?safe:spec.text),issues:[],bindings:{...spec.capture,
    request_key:spec.request_key,nonce:spec.nonce,claim_semantics_version:19,
    authority:'server_current_native_checks',request_authority:'runtime_must_verify_current_request_and_capture'}};}
async function setup(id, mode='normal') {
  const ctx=new Context(),diagnostics=[];
  ctx.on('finance/delivery-observation',event=>diagnostics.push(event));
  const [Agents,Sessions,Llm,Tools,Prompt,Loop]=modules.map(m=>m.default);
  await ctx.plugin(Agents,{});await ctx.plugin(Sessions,{});await ctx.plugin(Llm,{});
  await ctx.plugin(Prompt,{includeHarnessIdentity:false,includeRuntimeContext:false});
  await ctx.plugin(Tools,{});await ctx.plugin(Loop,{agents:[],maxParallelToolCalls:1});
  let calls=0, toolCalls=0, prepareCalls=0, started, release, captured;
  const pending=new Promise(r=>started=r), gate=new Promise(r=>release=r);
  const reasoning={type:'reasoning',text:'PRIVATE_SENTINEL_🙂'};
  const args='{"marker":"一😀","amount":"90"}';
  class Offline extends LlmAdapter {
    async *stream(options){
      calls++;
      if(calls===1){yield*toolChunks('finance_scenario_run','run-call','{}');yield{type:'finish',reason:{kind:'tool-calls'}};}
      else if(calls===2){
        yield{type:'block-start',index:7,blockType:'reasoning'};
        yield{type:'reasoning-delta',index:7,text:reasoning.text};
        yield{type:'block-end',index:7,block:reasoning};
        yield*textChunks(bad);yield*toolChunks('prepare_explanation','prepare-call',args);
        yield{type:'usage',usage:{inputTokens:4,outputTokens:5,totalTokens:9}};
        yield{type:'finish',reason:{kind:mode==='max-tokens'?'max-tokens':'tool-calls'},replayState:{response:{raw:bad},blocks:[{raw:reasoning.text},{raw:bad},{raw:args}]}};
      } else {captured=options.messages;yield*textChunks('已继续准备。');yield{type:'finish',reason:{kind:'stop'}};}
    }
  }
  ctx.llm.registerAdapter(['offline'],new Offline());
  const handle=await ctx.agents.create({sessionId:id,agentOptions:{provider:'offline',model:'offline'},setup(agentCtx){
    installFinalDeliveryRuntime(agentCtx,undefined,async(spec)=>{
      if(['pending-user','cancel-pending'].includes(mode)){started();await gate;}
      return proof(spec);
    });
    agentCtx.tools.register(toolDefinition('finance_scenario_run',{description:'offline fixture',
      parameters:{type:'object',properties:{},required:[],additionalProperties:false},execute:async(_args,exec)=>{
        toolCalls++;
        if(mode==='tool-pending-user'){started();await gate;}
        return JSON.stringify({id:'run',task_id:'task',requirements_id:'req',output_hash:'output',context_revision:3,
          session_id:exec.agent.id,result:{template_id:'three_statement',scenario_id:'scenario'}});
      }}));
    agentCtx.tools.register(toolDefinition('prepare_explanation',{description:'offline fixture',
      parameters:{type:'object',properties:{marker:{type:'string'},amount:{type:'string'}},required:['marker','amount']},
      execute:async(input)=>{prepareCalls++;assert.deepEqual(input,JSON.parse(args));return JSON.stringify({task_id:'task'});}}));
  }});
  const agent=handle.agent;
  agent.followup(createUserMessage({content:[{type:'text',text:'核验模型检查。'}],source:{kind:'user'}}));
  return {ctx,handle,agent,diagnostics,pending,release,counts:()=>({calls,toolCalls,prepareCalls}),captured:()=>captured,reasoning,args};
}
const normal=await setup('sdk-public');await normal.agent.whenIdle();
const events=normal.agent.session.events;
const message=events.find(e=>e.type==='assistant/message'&&e.data.message.content.some(b=>b.type==='text'&&b.text===safe));
assert.ok(message,'SDK assistant/message only sees selected text');
const chunks=events.filter(e=>e.type==='assistant/chunk'&&e.data.chunk.type==='text-delta');
assert.ok(!chunks.some(e=>e.data.chunk.text.includes('differences = 0')));
assert.ok(normal.agent.session.deriveMessages().some(m=>m.role==='assistant'&&m.content.some(b=>b.type==='text'&&b.text===safe)));
assert.ok(!JSON.stringify(normal.captured()).includes('differences = 0'));
const raw=normal.diagnostics.find(e=>e.type==='finance/public-text-delivery'&&e.data.phase==='held'&&e.data.raw_text===bad);
assert.ok(raw.observed_after_seq<chunks.find(e=>e.data.chunk.text===safe).seq);
assert.equal(message.data.message.source.replayState,undefined);
assert.deepEqual(message.data.message.content.find(b=>b.type==='reasoning'),normal.reasoning);
assert.ok(!JSON.stringify(normal.diagnostics.filter(e=>e.type==='finance/public-text-delivery')).includes(normal.reasoning.text));
assert.deepEqual(normal.counts(),{calls:3,toolCalls:1,prepareCalls:1});
assert.equal(events.find(e=>e.type==='tool/call'&&e.data.name==='prepare_explanation').data.arguments,normal.args);

// Exercise the actual DeepSeek serializer with a local fetch stub: no provider.
const fetchOriginal=globalThis.fetch;let wire;
globalThis.fetch=async(_url,options)=>{wire=JSON.parse(options.body);return new Response(
  'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n',
  {status:200,headers:{'content-type':'text/event-stream'}});};
try{
  const connection=resolveAdapterOptions({baseURL:'https://offline.invalid',models:[{id:'fake'}]},undefined);
  const adapter=new DeepSeekAdapter({options:()=>connection,resolveApiKey:async()=> 'offline-stub',resolveUserId:()=> 'offline'});
  for await(const _chunk of adapter.stream({model:'fake',messages:normal.agent.session.deriveMessages()})){}
  const assistant=wire.messages.find(m=>m.role==='assistant'&&m.content===safe);
  assert.ok(assistant);assert.equal(assistant.reasoning_content,normal.reasoning.text);
  assert.deepEqual(assistant.tool_calls,[{id:'prepare-call',type:'function',function:{name:'prepare_explanation',arguments:normal.args}}]);
  assert.ok(!JSON.stringify(wire).includes('differences = 0'));
}finally{globalThis.fetch=fetchOriginal;await normal.handle.dispose();}

for(const method of ['steer','followup']){
  const f=await setup(`sdk-pending-${method}`,'pending-user');await f.pending;
  const before=f.agent.session.events.findLast(e=>e.type==='user/message').seq;
  f.agent[method](createUserMessage({content:[{type:'text',text:'新请求。'}],source:{kind:'user'}}));
  assert.equal(f.agent.session.events.findLast(e=>e.type==='user/message').seq,before);
  f.release();await f.agent.whenIdle();
  assert.ok(!f.agent.session.events.some(e=>e.type==='assistant/chunk'&&e.data.chunk.type==='text-delta'&&e.data.chunk.text.includes('differences')));
  assert.equal(f.counts().prepareCalls,0);
  await f.handle.dispose();
}
const toolPending=await setup('sdk-tool-pending','tool-pending-user');await toolPending.pending;
toolPending.agent.steer(createUserMessage({content:[{type:'text',text:'新的请求。'}],source:{kind:'user'}}));
toolPending.release();await toolPending.agent.whenIdle();
assert.ok(!toolPending.agent.session.events.some(e=>e.type==='assistant/chunk'&&e.data.chunk.type==='text-delta'
  &&e.data.chunk.text.includes('differences = 0')));
await toolPending.handle.dispose();
const cancelled=await setup('sdk-cancel-pending','cancel-pending');await cancelled.pending;
cancelled.agent.cancel({kind:'user'});cancelled.release();await cancelled.agent.whenIdle();
assert.ok(!cancelled.agent.session.events.some(e=>e.type==='assistant/chunk'&&e.data.chunk.type==='text-delta'));
assert.equal(cancelled.counts().prepareCalls,0);await cancelled.handle.dispose();
const truncated=await setup('sdk-max-tokens','max-tokens');await truncated.agent.whenIdle();
assert.ok(truncated.agent.session.events.some(e=>e.type==='assistant/message'&&e.data.message.content.some(b=>b.type==='text'&&b.text===safe)));
assert.equal(truncated.counts().prepareCalls,0);
assert.equal(truncated.agent.session.events.findLast(e=>e.type==='turn/end').data.reason.kind,'max-tokens');
await truncated.handle.dispose();
console.log(JSON.stringify({passed:true,sdk_loops:6,adapter_serialization:true,provider_calls:0}));
