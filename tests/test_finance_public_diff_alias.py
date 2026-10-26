"""Finite diff aliases share current native, save, and actual SDK boundaries."""
from copy import deepcopy
import json
import os
import subprocess
import sys

import pytest

from foundry.finance_claim_semantics import CLAIM_SEMANTICS_VERSION, check_claim_semantics
from foundry.finance_explanations import saved_claim_semantic_issues
from test_finance_performance_semantics import performance_case
from test_finance_professional_protocol import _template_case
from test_finance_public_text_verification import public_proof as public_proof, tree, verify
from test_finance_runtime_payload import ROOT
from test_method_skill_runtime import _runtime_or_skip

CODE = 'model_check_difference_claim_mismatch'
LIVE_LINE = '**12 项 model_checks 全部 pass**（diff 均为 0）'
BARE_LINE = 'all model_checks（diff=0）'
CORRECT_LINE = ('Nine equality checks have diff=0; all 12 model checks pass, '
                'and the three threshold checks have positive margins.')
LIVE_MESSAGE = '''运行成功。核对要点：

- **run_id** `996073d08b78457e98a56f4c76971929`，`execution_status: succeeded`
- **requirements_id** `a9b27c88ba3d427c8016f087657d2cc5` 与语义指纹 `8aab239d...` 均与我的登记一致 ✓
- 16 项输入与 8 项边界全部 `source_verified`，13 项派生输出全部 `source_verified` 且 `check_status: pass`
- **12 项 model_checks 全部 pass**（diff 均为 0）

先记录进度，再准备事实引用。'''


@pytest.fixture(scope='module')
def native(tmp_path_factory):
    return performance_case(tmp_path_factory.mktemp('diff-native'))[-1]


@pytest.mark.parametrize('body', [
    LIVE_LINE, LIVE_MESSAGE, BARE_LINE, 'All model checks (diffs = 0).',
    'All model checks have DIFF = 0.00', 'All model checks have DIFF = 0.00.',
    'All model checks (diff=0.).', 'All model checks have differences=0.00.',
    'All model checks have differences=0.', 'All model checks pass with diffs are zero.',
    'All model checks pass with zero diffs.', 'All model checks have 0.00 diff.',
    '所有模型检查（DIFFS 均为零）。', '所有模型检查（DIFFS均为零）。',
    '所有模型检查均diff为零。', '所有模型检查（zero diffs即零差额）。',
])
def test_diff_alias_contradiction_retains_native_identity_and_span(native, body):
    checks = native['result']['model_checks']
    assert all(c['status'] == 'pass' for c in checks)
    assert [c['difference'] for c in checks[-3:]] == ['90', '197', '197']
    found = [i for i in check_claim_semantics(body, [], runs=[native]) if i['code'] == CODE]
    assert len(found) == 1
    issue = found[0]
    assert issue['run_id'] == native['id'] and issue['output_hash'] == native['output_hash']
    assert issue['all_checks_passed'] is True
    assert [c['difference'] for c in issue['nonzero_checks']] == ['90', '197', '197']
    assert body[issue['position']:].startswith(issue['text'])


@pytest.mark.parametrize('body', [
    'All model checks pass.', CORRECT_LINE,
    'All model checks pass; revenue has diff=0.',
    'All model checks pass; cash_sufficiency has diff=0.',
    'All model checks pass. Revenue has zero diffs.',
    'All model checks do not have zero diffs.',
    'If all model checks have diff=0, discuss the result.',
    'All model checks have diff=0?',
    'All model checks have diff=0, this statement is incorrect.',
    'All model checks have nonzero diffs.', 'All model checks have diff=0.01.',
    'All model checks have diff=0.001.', 'All model checks have diff=0.1.',
    'All model checks have diff=10.0.', 'All model checks have differences=0.01.',
    'All model checks have 0.001 diffs.',
    'All model checks have non**zero diffs**.',
    'All model checks have diffusion=0.', 'All model checks have different=0.',
    'All model checks have nondiff=0.', 'All model checks have diff_amount=0.',
    'All model checks have zero nondiffs.', 'All model checks have zero diffusion.',
    '```\nAll model checks have diff=0.\n```',
])
def test_diff_alias_does_not_expand_existing_subject_or_assertion_scope(native, body):
    assert check_claim_semantics(body, [], runs=[native]) == []


@pytest.mark.parametrize('mode', ['all_zero', 'missing', 'missing_difference', 'nonnumeric', 'hash', 'multiple'])
def test_alias_needs_one_integrity_bound_native_result(native, mode):
    from foundry.analysis import _hash
    run = deepcopy(native)
    runs = [run]
    if mode == 'all_zero':
        for check in run['result']['model_checks']:
            check['difference'] = '0'
        run['output_hash'] = _hash(run['result'])
    elif mode == 'missing':
        runs = []
    elif mode in {'missing_difference', 'nonnumeric'}:
        run['result']['model_checks'][0]['difference'] = None if mode == 'missing_difference' else 'unknown'
        run['output_hash'] = _hash(run['result'])
    elif mode == 'hash':
        run['output_hash'] = 'wrong'
    else:
        runs.append({**deepcopy(run), 'id': 'unresolved-second-run'})
    # Synthetic mutations are authority controls, never engine-produced facts.
    assert check_claim_semantics(LIVE_LINE, [], runs=runs) == []


@pytest.mark.parametrize('short', [False, True])
def test_diff_ordinary_short_save_and_legacy_readonly_recheck(tmp_path, short):
    service, _, _, run = performance_case(tmp_path)
    old_run = deepcopy(service.analysis.get_run(run['id']))
    prepared = service.prepare_explanation({'run_ids': [run['id']]})
    spec = ({**prepared['save_template_spec'], 'qualitative_note': LIVE_LINE} if short else
            {**prepared['draft_template'], 'body': prepared['draft_template']['body'] + '\n' + LIVE_LINE})
    draft = service.save_explanation_draft(spec)
    stored = deepcopy(service.analysis.get_draft(draft['id']))
    issues = [i for i in draft['quality']['issues'] if i['code'] == CODE]
    # Persist observations before RED assertions, retaining actual old behavior.
    observation = {'short': short, 'run_id': run['id'], 'output_hash': run['output_hash'],
                   'draft_id': draft['id'], 'quality': draft['quality'], 'completion': draft['completion'],
                   'claim_semantics_version': CLAIM_SEMANTICS_VERSION, 'provider_calls': 0}
    (tmp_path / 'actual-diff-save.json').write_text(json.dumps(observation, ensure_ascii=False, indent=2))
    assert len(issues) == 1
    assert draft['completion']['status'] != 'complete'
    fixed = service.save_explanation_draft({**prepared['save_template_spec'], 'parent_id': draft['id'],
        'qualitative_note': '模型检查按原生等式或阈值规则呈现；通过状态不表示所有差额为零。'})
    assert fixed['completion']['status'] == 'complete', fixed['quality']
    legacy = {**deepcopy(stored), 'explanation_check': {
        **stored['explanation_check'], 'claim_semantics_version': 15}}
    before_legacy = deepcopy(legacy)
    assert any(i['code'] == CODE for i in saved_claim_semantic_issues(service.analysis, legacy))
    assert legacy == before_legacy
    assert service.analysis.get_draft(draft['id']) == stored
    assert service.analysis.get_run(run['id']) == old_run
    observation.update(revision_id=fixed['id'], revision_parent_id=fixed['parent_id'],
                       revision_completion=fixed['completion'], legacy_epoch=15,
                       legacy_readonly_recheck_detected=True, old_draft_and_run_unchanged=True)
    (tmp_path / 'actual-diff-save.json').write_text(json.dumps(observation, ensure_ascii=False, indent=2))


@pytest.mark.parametrize('text', [LIVE_LINE, BARE_LINE])
def test_current_public_proof_projects_only_diff_line_and_does_not_write(public_proof, text):
    service, _, _, run, spec = public_proof
    raw = '普通进度🙂。\r\n' + text + '\r\n继续准备。'
    before = tree(service.task)
    proof = verify(service, {**spec, 'text': raw})
    assert tree(service.task) == before
    assert proof['verified'] and proof['status'] == 'contradicted', proof
    assert proof['bindings']['output_hash'] == run['output_hash']
    assert proof['bindings']['claim_semantics_version'] == CLAIM_SEMANTICS_VERSION
    assert proof['delivered_text'].startswith('普通进度🙂。\r\n')
    assert proof['delivered_text'].endswith('\r\n继续准备。')
    assert text not in proof['delivered_text']


@pytest.mark.parametrize('text,affected', [
    (BARE_LINE, True), ('cash_sufficiency diff=0', True), ('cash_sufficiency diffs=0', True),
    ('cash_sufficiency diff均为0', True),
    ('cash_sufficiency difference=0', True), ('cash_sufficiency diffusion=0', False),
    ('cash_sufficiency nondiff=0', False), ('普通业务 diff=0', False),
])
def test_python_missing_authority_named_alias_fallback_is_finite(public_proof, text, affected):
    _, manager, _, _, spec = public_proof
    raw = '普通进度。\n' + text + '\n继续。'
    before = tree(manager.task)
    proof = verify(manager, {**spec, 'text': raw})
    assert tree(manager.task) == before
    assert not proof['verified'] and proof['status'] == 'unverifiable'
    assert proof['bindings'] is None and proof['issues'] == []
    assert proof['delivered_text'] == ('普通进度。\n模型检查摘要尚未核实，正在依据当前运行继续核对。\n继续。'
                                        if affected else raw)


def test_runtime_diff_fallback_and_strict_current_epoch_without_new_routes(tmp_path):
    driver = tmp_path / 'diff-runtime.mjs'
    driver.write_text('''
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {writeFileSync} from 'node:fs';
import {installFinalDeliveryRuntime} from RUNTIME;
const hash=t=>createHash('sha256').update(t).digest('hex');
async function probe(text,epoch) {
 const events=[{seq:0,type:'user/message',data:{id:'u',source:{kind:'user'}}}];
 const session={events,append(type,data){const e={seq:events.length,type,data:structuredClone(data)};events.push(e);return e;}};
 const agent={id:'s1',session},handlers={};let checks=0;
 const ctx={on(n,f){handlers[n]=f;},emit(_name,event){events.push({...event,seq:events.length});},agents:{get:id=>id==='s1'?agent:undefined,currentInitiator:()=>agent}};
 installFinalDeliveryRuntime(ctx,async()=>({verified:false}),async spec=>{
  checks++;if(epoch==='unavailable')throw Error('unavailable');
  const bindings={...spec.capture,request_key:spec.request_key,nonce:spec.nonce,
   authority:'server_current_native_checks',request_authority:'runtime_must_verify_current_request_and_capture'};
  if(epoch!=='missing')bindings.claim_semantics_version=epoch;
  return {schema_version:1,verified:true,status:'unchanged',raw_text_sha256:hash(spec.text),delivered_text:spec.text,
   delivered_text_sha256:hash(spec.text),issues:[],bindings};
 });
 session.append('tool/call',{name:'finance_scenario_run',callId:'call'});
 handlers['tools/result']({name:'finance_scenario_run',callId:'call',agent},{isError:false,value:{tool:'finance_scenario_run',stdout:JSON.stringify({
  id:'run',task_id:'task',requirements_id:'req',output_hash:'output',context_revision:3,session_id:'s1',
  result:{template_id:'three_statement',scenario_id:'scenario'}})}});
 const chunks=[{type:'block-start',index:0,blockType:'text'},{type:'text-delta',index:0,text},
  {type:'block-end',index:0,block:{type:'text',text}},{type:'finish',reason:{kind:'stop'}}];
 const out=[];for await(const c of handlers['llm/stream']({sessionId:'s1'},async function*(){yield*chunks;}))out.push(c);
 return {raw:text,epoch,checks,delivered:out.filter(c=>c.type==='text-delta').map(c=>c.text).join(''),events};
}
const rows=[];const neutral='该模型检查摘要暂未核验，请以当前运行记录为准。';
const currentEpoch=CURRENT_EPOCH;
for(const [line,affected] of MATRIX){const raw='普通进度。\\n'+line+'\\n继续。';
 const row=await probe(raw,'unavailable');rows.push(row);
 row.expected=affected?'普通进度。\\n'+neutral+'\\n继续。':raw;
}
for(const epoch of [currentEpoch,currentEpoch-1,17,16,currentEpoch+1,String(currentEpoch),'17',null,'missing']){
 const row=await probe('all model_checks（diff=0）',epoch);
 row.expected=epoch===currentEpoch?row.raw:neutral;rows.push(row);}
writeFileSync(OBSERVATION,JSON.stringify({rows,external_provider_calls:0},null,2));
for(const row of rows){assert.equal(row.checks,1);assert.equal(row.delivered,row.expected,JSON.stringify(row));}
'''.replace('RUNTIME', repr((ROOT / 'dsh-plugin/final-delivery-runtime.js').as_uri()))
        .replace('CURRENT_EPOCH', str(CLAIM_SEMANTICS_VERSION))
        .replace('MATRIX', json.dumps([[BARE_LINE, True], ['cash_sufficiency diff=0', True],
            ['cash_sufficiency diffs=0', True], ['cash_sufficiency diff均为0', True],
            ['cash_sufficiency difference=0', True],
            ['cash_sufficiency diffusion=0', False], ['cash_sufficiency nondiff=0', False],
            ['普通业务 diff=0', False]], ensure_ascii=False))
        .replace('OBSERVATION', repr(str(tmp_path / 'actual-diff-runtime.json'))))
    result = subprocess.run(['node', str(driver)], cwd=ROOT, text=True, capture_output=True, timeout=30)
    (tmp_path / 'runtime-process.json').write_text(json.dumps({'exit': result.returncode,
        'stdout': result.stdout, 'stderr': result.stderr}, indent=2))
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('line,contradicted', [(LIVE_LINE, True), (BARE_LINE, True), (CORRECT_LINE, False)])
def test_actual_sdk_cli_diff_alias_across_next_messages_and_deepseek_wire(tmp_path, line, contradicted):
    manager, _, _, initial = _template_case(tmp_path)
    session_id = 'native-sdk-diff-alias'
    manager.task.record_session(session_id, role='analysis')
    modules = _runtime_or_skip() / '@deepseek-ai'
    driver = tmp_path / 'native-diff-loop.mjs'
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
let calls=0,runId,toolCalls=[],nextMessages;
const line={json.dumps(line, ensure_ascii=False)},raw='普通进度🙂。\\r\\n'+line+'\\r\\n现在准备说明。';
function* tool(name,id,spec){{const args=JSON.stringify({{spec}});
yield{{type:'block-start',index:1,blockType:'tool-call'}};yield{{type:'tool-call-delta',index:1,id,name,argumentsDelta:args}};
yield{{type:'block-end',index:1,block:{{type:'tool-call',id,name,arguments:args}}}};}}
class Offline extends LlmAdapter{{async *stream(options){{calls++;
if(calls===1){{yield*tool('finance_scenario_run','diff-native-run',{{scenario_id:{initial['result']['scenario_id']!r}}});}}
else if(calls===2){{yield{{type:'block-start',index:0,blockType:'text'}};
for(const text of raw)yield{{type:'text-delta',index:0,text}};
yield{{type:'block-end',index:0,block:{{type:'text',text:raw}}}};
yield*tool('prepare_explanation','diff-prepare',{{run_ids:[runId]}});}}
else{{nextMessages=options.messages;yield{{type:'block-start',index:0,blockType:'text'}};
yield{{type:'text-delta',index:0,text:'已继续准备。'}};
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
const chunks=events.filter(e=>e.type==='assistant/chunk'&&e.data.chunk.type==='text-delta');
const ends=events.filter(e=>e.type==='assistant/chunk'&&e.data.chunk.type==='block-end'&&e.data.chunk.block.type==='text');
const messages=events.filter(e=>e.type==='assistant/message').flatMap(e=>e.data.message.content).filter(b=>b.type==='text').map(b=>b.text);
const derived=handle.agent.session.deriveMessages().flatMap(m=>m.content??[]).filter(b=>b.type==='text').map(b=>b.text);
const observation={{raw,run_id:runId,held,selected,actual_text_deltas:chunks.map(e=>({{seq:e.seq,text:e.data.chunk.text}})),
actual_block_ends:ends.map(e=>({{seq:e.seq,text:e.data.chunk.block.text}})),actual_message_texts:messages,
derived_texts:derived,next_round_public_texts:(nextMessages??[]).flatMap(m=>m.content??[]).filter(b=>b.type==='text').map(b=>b.text),
calls,toolCalls,provider_calls:0,private_reasoning_extracted:false}};
const {{DeepSeekAdapter,resolveAdapterOptions}}=await import({(modules / 'dsh-llm-deepseek/lib/index.js').as_uri()!r});
const fetchOriginal=globalThis.fetch;let wire;
globalThis.fetch=async(_url,options)=>{{wire=JSON.parse(options.body);return new Response(
 'data: {{"choices":[{{"delta":{{"content":"ok"}},"finish_reason":"stop"}}]}}\\n\\ndata: [DONE]\\n\\n',
 {{status:200,headers:{{'content-type':'text/event-stream'}}}});}};
try{{const connection=resolveAdapterOptions({{baseURL:'https://offline.invalid',models:[{{id:'fake'}}]}},undefined);
 const adapter=new DeepSeekAdapter({{options:()=>connection,resolveApiKey:async()=> 'offline-stub',resolveUserId:()=> 'offline'}});
 for await(const _chunk of adapter.stream({{model:'fake',messages:nextMessages}})){{}}
 observation.adapter_serialized_public_texts=wire.messages.map(m=>m.content).filter(t=>typeof t==='string');
}}finally{{globalThis.fetch=fetchOriginal;}}
writeFileSync({str(tmp_path / 'actual-native-sdk-diff.json')!r},JSON.stringify(observation,null,2));
await handle.dispose();
assert.ok(held&&selected,JSON.stringify({{calls,toolCalls}}));
assert.equal(selected.data.status,{json.dumps('contradicted' if contradicted else 'unchanged')});
assert.equal(selected.data.server_source_binding.run_id,runId);
assert.equal(selected.data.server_source_binding.claim_semantics_version,{CLAIM_SEMANTICS_VERSION});
assert.ok(diagnostics.indexOf(held)<diagnostics.indexOf(selected)&&selected.observed_after_seq<chunks[0].seq);
const chosen=selected.data.delivered_text;
assert.ok(chosen.startsWith('普通进度🙂。\\r\\n'));assert.ok(chosen.endsWith('\\r\\n现在准备说明。'));
const firstBlockDeltas=chunks.filter(e=>e.seq<ends[0].seq).map(e=>e.data.chunk.text);
assert.equal(firstBlockDeltas.join(''),chosen);assert.equal(ends[0].data.chunk.block.text,chosen);assert.equal(messages[0],chosen);
assert.ok(derived.includes(chosen));assert.ok(observation.next_round_public_texts.includes(chosen));
assert.ok(wire.messages.some(m=>m.role==='assistant'&&m.content===chosen));
for(const surface of [[firstBlockDeltas.join('')],ends.map(e=>e.data.chunk.block.text),messages,derived,
 observation.next_round_public_texts,observation.adapter_serialized_public_texts]){{
 assert.equal(surface.some(text=>text.includes(line)),{json.dumps(not contradicted)});
}}
if({json.dumps(not contradicted)}){{assert.equal(chosen,raw);assert.deepEqual(firstBlockDeltas,[...raw]);}}
else assert.deepEqual(firstBlockDeltas,[chosen]);
assert.equal(toolCalls.filter(c=>c.name==='finance_scenario_run'&&!c.isError).length,1);
assert.equal(toolCalls.filter(c=>c.name==='prepare_explanation'&&!c.isError).length,1);
console.log(JSON.stringify({{passed:true,calls,toolCalls,provider_calls:0}}));
''')
    launcher = tmp_path / 'foundry'
    launcher.write_text(f'#!{sys.executable}\nimport runpy,sys\nsys.path.insert(0,{str(ROOT)!r})\n'
                        'runpy.run_module("foundry.cli",run_name="__main__")\n')
    launcher.chmod(0o700)
    observed = subprocess.run(['node', str(driver)], cwd=ROOT, text=True, capture_output=True,
        env=os.environ | {'FOUNDRY_BIN': str(launcher), 'FOUNDRY_VAR': str(tmp_path / 'var')}, timeout=60)
    (tmp_path / 'actual-native-sdk-diff-process.json').write_text(json.dumps({
        'exit_code': observed.returncode, 'stdout': observed.stdout, 'stderr': observed.stderr,
        'provider_calls': 0}, ensure_ascii=False, indent=2))
    assert observed.returncode == 0, observed.stderr
    assert json.loads(observed.stdout)['passed']
