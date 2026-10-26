import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { installFinalDeliveryRuntime, UNVERIFIED_REPLY } from '../dsh-plugin/final-delivery-runtime.js';

const hash = text => createHash('sha256').update(text).digest('hex');
export const rawRun = { id:'run', task_id:'task', requirements_id:'req', output_hash:'output',
  context_revision:3, session_id:'s1', result:{ template_id:'three_statement', scenario_id:'scenario' } };
export function proof(spec, delivered = spec.text) {
  return { schema_version:1, verified:true, status:delivered === spec.text ? 'unchanged' : 'contradicted',
    reason:'native_checks_current', raw_text_sha256:hash(spec.text), delivered_text:delivered,
    delivered_text_sha256:hash(delivered), issues:[], bindings:{ ...spec.capture,
      request_key:spec.request_key, nonce:spec.nonce, claim_semantics_version:19,
      authority:'server_current_native_checks', request_authority:'runtime_must_verify_current_request_and_capture' } };
}
export const textChunks = (text, index=0, reason='stop') => [
  {type:'block-start',index,blockType:'text'}, {type:'text-delta',index,text},
  {type:'block-end',index,block:{type:'text',text}},
  {type:'finish',reason:{kind:reason},replayState:{response:{opaque:'raw'},blocks:[{raw:text}]}} ];
function fixture(check = async spec => proof(spec, spec.text.replace('differences = 0','differences require verification')), finalCheck) {
  const events = [{seq:0,type:'user/message',data:{id:'user1',source:{kind:'user'}}}];
  const session = {events,append(type,data) { const e={seq:events.length,type,data:structuredClone(data)};events.push(e);return e; }};
  const agent={id:'s1',session}, handlers={}, checks=[];
  const ctx={on(name,fn){handlers[name]=fn;},emit(_name,event){events.push({...event,seq:events.length});},agents:{get:id=>id===agent.id?agent:undefined,currentInitiator:()=>agent}};
  const finalProof=async spec=>({verified:true,final_response:spec.saved_result.final_response,bindings:{session_id:'s1',
    task_id:'task',request_key:spec.request_key,call_id:'save',draft_id:'draft',draft_content_hash:'hash',receipt_id:'receipt',
    requirements_id:'req',completion_status:'complete',run_ids:['run'],deadline_at:new Date(Date.now()+30000).toISOString()}});
  installFinalDeliveryRuntime(ctx, finalCheck ?? finalProof, async (spec,exec)=>{checks.push(spec);return check(spec,exec);});
  const emit=(name='finance_scenario_run',value=rawRun,isError=false,callId='call')=>{
    session.append('tool/call',{name,callId});
    handlers['tools/result']({name,callId,agent},{isError,value:{tool:name,stdout:JSON.stringify(value)}});
  };
  const collect=async(chunks,options={})=>{
    const out=[];for await (const chunk of handlers['llm/stream']({sessionId:agent.id,...options},async function*(){yield*chunks;})) out.push(chunk);
    return out;
  };
  return {events,session,agent,ctx,handlers,checks,emit,collect};
}
const visible = chunks=>chunks.filter(c=>c.type==='text-delta').map(c=>c.text).join('');
const bad='All 12 model checks `pass` (differences = 0).';
const f=fixture();f.emit();const out=await f.collect(textChunks(bad));
assert.equal(visible(out),'All 12 model checks `pass` (differences require verification).');
assert.equal(out.at(-1).replayState,undefined);
assert.equal(f.events.find(e=>e.type==='finance/public-text-delivery').data.phase,'held');
assert.equal(f.checks[0].text,bad);
assert.equal(f.events.at(-1).data.raw_text_sha256,hash(bad));

// The exact historical public payload includes a tool after 265 actual chunks.
const historical=JSON.parse(await readFile(new URL('./fixtures/finance_public_stream_historical.json',import.meta.url),'utf8'));
for (const item of historical) {
  const g=fixture(async spec=>proof(spec,spec.text.replace('differences = 0','differences require verification')
    .replace('the last three are `alert` severity','the last three require severity verification')));
  g.emit();const chunks=item.chunks;
  const delivered=await g.collect(chunks);
  assert.notEqual(visible(delivered),item.text);
  assert.deepEqual(delivered.filter(c=>c.type.includes('tool-call')||c.block?.type==='tool-call'||c.blockType==='tool-call'),
    chunks.filter(c=>c.type.includes('tool-call')||c.block?.type==='tool-call'||c.blockType==='tool-call'));
  assert.equal(g.events.find(e=>e.data.phase==='held')?.data.raw_text,item.text);
  const no=fixture();assert.deepEqual(await no.collect(chunks),chunks);assert.equal(no.checks.length,0);
}

// Normal text, legitimate metadata, Unicode and zero equations stay byte exact.
for (const good of ['普通进度🙂\u{20000}。','All 12 model checks pass.','Nine model checks have differences = 0.',
  'cash_sufficiency has alert severity.','The user asked: "Are all model checks differences = 0?"',
  'I do not claim all model checks have differences = 0.']) {
  const g=fixture(async spec=>proof(spec));g.emit();const chunks=textChunks(good);
  assert.deepEqual(await g.collect(chunks),chunks);
}
const mixed=fixture();mixed.emit();
const parts=[{type:'block-start',index:0,blockType:'text'},{type:'text-delta',index:0,text:'All 12 model '},
  {type:'block-start',index:9,blockType:'tool-call'},{type:'tool-call-delta',index:9,id:'once',name:'prepare_explanation',argumentsDelta:'{"spec":{}'},
  {type:'block-start',index:8,blockType:'reasoning'},{type:'reasoning-delta',index:8,text:'PRIVATE_SENTINEL'},
  {type:'block-end',index:8,block:{type:'reasoning',text:'PRIVATE_SENTINEL'}},
  {type:'text-delta',index:0,text:'checks `pass` (differences = 0).'},
  {type:'block-end',index:0,block:{type:'text',text:bad}},
  {type:'tool-call-delta',index:9,argumentsDelta:'}'},
  {type:'block-end',index:9,block:{type:'tool-call',id:'once',name:'prepare_explanation',arguments:'{"spec":{}}'}},
  ...textChunks('下一块🙂。',4,'tool-calls')];
const mixedOut=await mixed.collect(parts);
assert.deepEqual(mixedOut.filter(c=>c.type!=='text-delta'&&c.block?.type!=='text'&&c.type!=='finish'),
  parts.filter(c=>c.type!=='text-delta'&&c.block?.type!=='text'&&c.type!=='finish'));
assert.ok(!JSON.stringify(mixed.events.filter(e=>e.type==='finance/public-text-delivery')).includes('PRIVATE_SENTINEL'));
assert.equal(mixed.checks.length,2);

// Response correlation errors cannot revive an assertion, but progress remains.
for (const field of ['raw','delivered','nonce','session_id','task_id','run_id','requirements_id','output_hash',
  'template_id','scenario_id','context_revision','authority','request_authority','claim_semantics_version']) {
  const g=fixture(async spec=>{const p=proof(spec);if(field==='raw')p.raw_text_sha256='bad';
    else if(field==='delivered')p.delivered_text_sha256='bad';else p.bindings[field]='bad';return p;});
  g.emit();const delivered=await g.collect(textChunks(`进度保留。\n${bad}\n继续准备。`));
  assert.equal(visible(delivered),'进度保留。\n该模型检查摘要暂未核验，请以当前运行记录为准。\n继续准备。',field);
}
// Strict protocol epoch: stale, unknown future, and string epochs cannot authorize delivery.
for (const epoch of [18,17,16,20,'19','18','17',null,'missing']) {
  const g=fixture(async spec=>{const p=proof(spec);
    if(epoch==='missing')delete p.bindings.claim_semantics_version;
    else p.bindings.claim_semantics_version=epoch;return p;});
  g.emit();const delivered=await g.collect(textChunks(`进度保留。\n${bad}\n继续准备。`));
  assert.equal(visible(delivered),'进度保留。\n该模型检查摘要暂未核验，请以当前运行记录为准。\n继续准备。');
  assert.equal(g.events.findLast(e=>e.type==='finance/public-text-delivery').data.status,'unverifiable');
}
for (const mutate of [
  g=>g.session.append('agent/inbox/spliced',{inserted:[{id:'u2',source:{kind:'user'}}]}),
  g=>g.session.append('user/message',{id:'u2',source:{kind:'user'}}),
  g=>g.emit(),g=>g.emit('finance_scenario_run',null,true),
  g=>g.session.append('tool/call',{name:'finance_context_save',callId:'new-context'}),
]) {
  let release,started;const gate=new Promise(r=>release=r), ready=new Promise(r=>started=r);
  const g=fixture(async spec=>{started();await gate;return proof(spec);});g.emit();
  const pending=g.collect(textChunks(bad));await ready;mutate(g);release();
  await assert.rejects(pending,{name:'AbortError'});
}
const context=fixture(async spec=>proof(spec));context.emit();
context.session.append('agent/inbox/spliced',{inserted:[{source:{kind:'plugin'},content:[]}]});
assert.equal(visible(await context.collect(textChunks(bad))),bad);

// A user inserted during the tool body makes the returning old run ineligible.
const late=fixture();late.session.append('tool/call',{name:'finance_scenario_run',callId:'late'});
late.session.append('agent/inbox/spliced',{inserted:[{id:'new',source:{kind:'user'}}]});
late.handlers['tools/result']({name:'finance_scenario_run',callId:'late',agent:late.agent},
  {isError:false,value:{tool:'finance_scenario_run',stdout:JSON.stringify(rawRun)}});
assert.ok(!visible(await late.collect(textChunks(bad))).includes('differences = 0'));assert.equal(late.checks.length,0);

for(const kind of ['cancel','audit-failure','verifier-failure','incomplete','max-tokens']){
  const controller=new AbortController();
  const g=fixture(async spec=>{if(kind==='cancel')controller.abort();if(kind==='verifier-failure')throw Error('offline');return proof(spec);});
  g.emit();if(kind==='audit-failure')g.ctx.emit=()=>{throw Error('diagnostic sink unavailable');};
  const chunks=kind==='incomplete'?textChunks(bad).slice(0,2):textChunks(bad,0,kind==='max-tokens'?kind:'stop');
  if(kind==='cancel')await assert.rejects(g.collect(chunks,{signal:controller.signal}));
  else {const result=await g.collect(chunks);if(kind==='incomplete')assert.equal(visible(result),'');
    if(kind==='verifier-failure')assert.ok(!visible(result).includes('differences = 0'));
    if(kind==='max-tokens')assert.equal(result.at(-1).reason.kind,'max-tokens');
    if(kind==='audit-failure')assert.equal(visible(result),bad); // The verified projection survives a diagnostic outage.
  }
}
const saved={id:'draft',task_id:'task',requirements_id:'req',run_ids:['run'],content_hash:'hash',
  completion:{id:'receipt'},delivery_contract:{completion_status:'complete'},final_response:'保存回执。'};
const final=fixture();final.emit();final.emit('save_explanation_draft',saved,false,'save');
assert.equal(visible(await final.collect(textChunks(bad))),saved.final_response);assert.equal(final.checks.length,0);
final.emit('save_explanation_draft',null,true,'save');
assert.equal(visible(await final.collect(textChunks(bad))),UNVERIFIED_REPLY);
const finalAudit=fixture();finalAudit.emit('save_explanation_draft',saved,false,'save');
const alternate=textChunks(bad);alternate[2].block.text='不同的结束文本。';await finalAudit.collect(alternate);
const exactAudit=finalAudit.events.find(e=>e.type==='finance/final-delivery');
assert.equal(exactAudit.data.raw_text,bad);assert.equal(exactAudit.data.raw_block_ends[0].text,'不同的结束文本。');
const finalRace=fixture();finalRace.emit('save_explanation_draft',saved,false,'save');
const iterator=finalRace.handlers['llm/stream']({sessionId:'s1'},async function*(){yield*textChunks('扩写。');});
assert.equal((await iterator.next()).value.type,'block-start');
finalRace.session.append('agent/inbox/spliced',{inserted:[{source:{kind:'user'},id:'next'}]});
await assert.rejects(iterator.next(),{name:'AbortError'});
for(const metadata of ['cash_sufficiency is error severity.','cash_sufficiency blocks_evidence=false.','模型联动核查全部差额为零。',
  'cash_sufficiency is error.','restricted_cash_bounds is alert.']){
  const g=fixture(async()=>{throw Error('unavailable');});g.emit();
  const result=await g.collect(textChunks(`普通进度。\n${metadata}\n继续。`));
  assert.ok(!visible(result).includes(metadata));assert.ok(visible(result).startsWith('普通进度。\n'));
}
for(const ordinary of ['I will inspect cash_sufficiency next.','Error while reading the report.','正在准备 restricted_cash_bounds 的说明。']){
  const g=fixture(async()=>{throw Error('unavailable');});g.emit();assert.equal(visible(await g.collect(textChunks(ordinary))),ordinary);
}
{
  let deadline;
  const g=fixture(undefined,async spec=>({verified:true,final_response:saved.final_response,bindings:{session_id:'s1',task_id:'task',
    request_key:spec.request_key,call_id:'save',draft_id:'draft',draft_content_hash:'hash',receipt_id:'receipt',requirements_id:'req',
    completion_status:'complete',run_ids:['run'],deadline_at:deadline=new Date(Date.now()+25).toISOString()}}));
  g.emit('save_explanation_draft',saved,false,'save');
  const stream=g.handlers['llm/stream']({sessionId:'s1'},async function*(){yield*textChunks('扩写。');});
  assert.equal((await stream.next()).value.type,'block-start');
  await new Promise(r=>setTimeout(r,45));assert.ok(Date.now()>Date.parse(deadline));
  await assert.rejects(stream.next(),{name:'TimeoutError'});
}
for(const [delta,end] of [[bad,'All 12 model checks pass.'],['All 12 model checks pass.',bad]]){
  const g=fixture();g.emit();const chunks=textChunks(delta);chunks[2].block.text=end;
  const result=await g.collect(chunks);
  assert.ok(!visible(result).includes('differences = 0'));
  assert.equal(result.find(c=>c.type==='block-end').block.text,visible(result));
  const audit=g.events.find(e=>e.data.phase==='held');assert.equal(audit.data.raw_text,delta);assert.equal(audit.data.raw_block_end_text,end);
}
const prepared={task_id:'task',structure_counts:[{kind:'model_checks',run_id:'run',requirements_id:'req',output_hash:'output',
  template_id:'three_statement',scenario_id:'scenario'}],save_template_spec:{run_ids:['run'],requirements_id:'req'}};
for(const valid of [true,false]){
  const g=fixture();g.emit('prepare_explanation',valid?prepared:{...prepared,save_template_spec:{run_ids:['other'],requirements_id:'req'}});
  await g.collect(textChunks(bad));assert.equal(g.checks.length,valid?1:0);
  if(valid)assert.equal(g.checks[0].capture.context_revision,null);
}
const newRequest=fixture();newRequest.emit();newRequest.session.append('user/message',{id:'u2',source:{kind:'user'}});
assert.equal(visible(await newRequest.collect(textChunks('普通新请求。'))),'普通新请求。');
assert.ok(!visible(await newRequest.collect(textChunks(bad))).includes('differences = 0'));assert.equal(newRequest.checks.length,0);

// One runtime, two concurrent sessions, reversed proof completion.
{
  const agents=new Map(), handlers={}, gates=new Map(), started=new Map();let initiator;
  const ctx={on(name,fn){handlers[name]=fn;},emit(_name,event){const events=agents.get(event.data.session_id).session.events;events.push({...event,seq:events.length});},agents:{get:id=>agents.get(id),currentInitiator:()=>initiator}};
  installFinalDeliveryRuntime(ctx,undefined,async spec=>{started.get(spec.capture.session_id)();
    await new Promise(r=>gates.set(spec.capture.session_id,r));return proof(spec,spec.text.replace('differences = 0','differences require verification'));});
  const waiting=[];
  for(const id of ['concurrent-a','concurrent-b']){
    const events=[{seq:0,type:'user/message',data:{id:'user',source:{kind:'user'}}}];
    const session={events,append(type,data){const e={type,data,seq:events.length};events.push(e);return e;}};
    const agent={id,session};agents.set(id,agent);initiator=agent;
    session.append('tool/call',{name:'finance_scenario_run',callId:'call'});
    handlers['tools/result']({name:'finance_scenario_run',callId:'call',agent},{isError:false,
      value:{tool:'finance_scenario_run',stdout:JSON.stringify({...rawRun,session_id:id,id:`run-${id}`,task_id:`task-${id}`})}});
    let ready;const begun=new Promise(r=>ready=r);started.set(id,ready);
    const result=(async()=>{const out=[];for await(const c of handlers['llm/stream']({sessionId:id},async function*(){yield*textChunks(bad);}))out.push(c);return out;})();
    waiting.push(result);await begun;
  }
  gates.get('concurrent-b')();gates.get('concurrent-a')();
  for(const chunks of await Promise.all(waiting))assert.ok(visible(chunks).includes('require verification'));
  for(const [id,agent] of agents){const selected=agent.session.events.find(e=>e.data.phase==='selected');
    assert.equal(selected.data.server_source_binding.session_id,id);assert.equal(selected.data.server_source_binding.run_id,`run-${id}`);}
}
console.log(JSON.stringify({passed:true,historical_chunks:historical[0].chunks.length,concurrent_sessions:2,provider_calls:0}));
