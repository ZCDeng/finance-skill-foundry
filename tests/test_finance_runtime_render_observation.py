"""Observe actual SDK tool content without recording reasoning or granting authority."""
import json
import subprocess

from test_finance_runtime_payload import ROOT


def test_render_observation_is_bound_to_public_content_and_cannot_affect_delivery():
    script = r'''
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {installFinalDeliveryRuntime} from './dsh-plugin/final-delivery-runtime.js';
const digest=s=>createHash('sha256').update(s,'utf8').digest('hex');
const events=[{seq:0,type:'user/message',data:{id:'u1',source:{kind:'user'},content:[]}},
 {seq:1,type:'tool/call',data:{callId:'p1',name:'prepare_explanation'}}];
const agent={id:'session-1',session:{events,append(type,data){events.push({seq:events.length,type,data});}}};
const handlers={},diagnostics=[];
const ctx={on(n,f){handlers[n]=f;},emit(_name,event){diagnostics.push(event);},agents:{get:()=>agent}};
installFinalDeliveryRuntime(ctx);
const raw='{"facts":[],"status":"unverified"}';
const content=Object.freeze([{type:'text',text:'公开结果：仍未完成。'}]);
const emit=(name='prepare_explanation',extra={},execExtra={})=>handlers['tools/result'](
 {name,callId:'p1',agent,...execExtra},
 {isError:false,value:{tool:name,stdout:raw},content,privateReasoning:'PRIVATE_SENTINEL',...extra});
emit();
const audit=diagnostics.filter(e=>e.type==='finance/model-result-render');
assert.equal(audit.length,1);
const observed=audit[0].data;
assert.equal(observed.session_id,'session-1');assert.equal(observed.call_id,'p1');
assert.equal(observed.request_key,'session-1:message:u1:seq:0');
assert.equal(observed.raw_stdout_sha256,digest(raw));assert.equal(observed.raw_stdout_bytes,Buffer.byteLength(raw));
assert.equal(observed.rendered_content_sha256,digest(JSON.stringify(content)));
assert.equal(observed.rendered_text_bytes,Buffer.byteLength(content[0].text));
assert.equal(observed.blocks[0].text_sha256,digest(content[0].text));
assert.equal(observed.source,'tools/result.content');assert.equal(observed.authority,'none');
assert.ok(!JSON.stringify(observed).includes('PRIVATE_SENTINEL'));
assert.ok(!JSON.stringify(observed).includes(content[0].text));
for(const args of [ ['prepare_explanation',{isError:true}], ['analysis-state',{}],
 ['prepare_explanation',{content:[{type:'reasoning',text:'PRIVATE_SENTINEL'}]}],
 ['prepare_explanation',{}, {callId:'unknown-call'}] ]) emit(...args);
assert.equal(diagnostics.filter(e=>e.type==='finance/model-result-render').length,1);
assert.equal(events.length,2);
ctx.emit=()=>{throw Error('recording unavailable');};
assert.doesNotThrow(()=>emit());
console.log(JSON.stringify({passed:true,provider_calls:0,cases:7}));
'''
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT,
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["provider_calls"] == 0
