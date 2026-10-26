"""Both zero word orders must share the saved and actual SDK native-check boundary."""
import json
import os
import subprocess
import sys
from copy import deepcopy

import pytest

from foundry.finance_claim_semantics import CLAIM_SEMANTICS_VERSION, check_claim_semantics
from foundry.finance_explanations import saved_claim_semantic_issues
from test_finance_performance_semantics import performance_case
from test_finance_professional_protocol import _template_case
from test_finance_runtime_payload import ROOT
from test_method_skill_runtime import _runtime_or_skip

CODE = 'model_check_difference_claim_mismatch'
CLAIM = 'All 12 model checks `pass` with zero differences.'


@pytest.fixture(scope='module')
def native(tmp_path_factory):
    return _template_case(tmp_path_factory.mktemp('zero-native'))[-1]


@pytest.mark.parametrize('body', [
    CLAIM,
    'All **12** model checks `pass` with **zero differences**.',
    'All model checks pass with 0 differences.',
    'All model checks have 0.00 differences.',
    '所有模型检查零差异。',
    '所有模型检查零差额。',
    'All model checks pass, with zero differences.',
    'All model checks pass with differences equal to zero.',
    'All model checks pass with zero differences; a separate unrelated claim is false.',
])
def test_universal_zero_word_orders_are_contradicted_by_passing_nonzero_margins(native, body):
    assert all(c['status'] == 'pass' for c in native['result']['model_checks'])
    assert any(c['difference'] != '0' for c in native['result']['model_checks'])
    issues = check_claim_semantics(body, [], runs=[native])
    found = [i for i in issues if i['code'] == CODE]
    assert len(found) == 1
    assert found[0]['run_id'] == native['id'] and found[0]['output_hash'] == native['output_hash']
    assert body[found[0]['position']:].startswith(found[0]['text'])


@pytest.mark.parametrize('body', [
    'All 12 model checks `pass`.',
    'Nine equality checks have zero differences; all 12 model checks pass, and the three threshold checks have positive margins.',
    'All model checks do not have zero differences.',
    'If all model checks pass with zero differences, discuss the result.',
    'All model checks pass with zero differences, this statement is incorrect.',
    'All model checks pass with zero differences?',
    'All model checks pass with nonzero differences.',
    'All model checks pass with 0.01 differences.',
    'All model checks pass with non**zero differences**.',
    '全部九项等式核查差额为零，三项阈值核查余量为正。',
    'All model checks pass; revenue has zero differences.',
    '```\nAll model checks pass with zero differences.\n```',
])
def test_scoped_refuted_or_nonzero_statements_are_not_contradictions(native, body):
    assert check_claim_semantics(body, [], runs=[native]) == []


@pytest.mark.parametrize('mode', ['all_zero', 'missing', 'malformed', 'hash', 'multiple'])
def test_zero_leading_phrase_requires_one_integrity_bound_nonzero_native_result(native, mode):
    from foundry.analysis import _hash
    run = deepcopy(native)
    runs = [run]
    if mode == 'all_zero':
        for check in run['result']['model_checks']:
            check['difference'] = '0'
        run['output_hash'] = _hash(run['result'])
    elif mode == 'missing':
        runs = []
    elif mode == 'malformed':
        run['result']['model_checks'][0]['difference'] = None
        run['output_hash'] = _hash(run['result'])
    elif mode == 'hash':
        run['output_hash'] = 'tampered'
    else:
        runs.append({**deepcopy(run), 'id': 'unresolved-second-run'})
    # Synthetic result shapes test disclosure authority only; they do not
    # assert that an engine run or a professional review produced these values.
    assert check_claim_semantics(CLAIM, [], runs=runs) == []


@pytest.mark.parametrize('short', [False, True])
def test_real_ordinary_and_short_save_report_the_zero_leading_issue(tmp_path, short):
    service, _, _, run = performance_case(tmp_path)
    old_run = deepcopy(service.analysis.get_run(run['id']))
    prepared = service.prepare_explanation({'run_ids': [run['id']]})
    spec = ({**prepared['save_template_spec'], 'qualitative_note': CLAIM} if short else
            {**prepared['draft_template'], 'body': prepared['draft_template']['body'] + '\n' + CLAIM})
    draft = service.save_explanation_draft(spec)
    issues = [i for i in draft['quality']['issues'] if i['code'] == CODE]
    assert issues
    stored = deepcopy(service.analysis.get_draft(draft['id']))
    fixed = service.save_explanation_draft({**prepared['save_template_spec'], 'parent_id': draft['id'],
        'qualitative_note': '模型检查按原生等式或阈值规则呈现；通过状态不表示所有差额为零。'})
    assert fixed['completion']['status'] == 'complete', fixed['quality']
    legacy = {**deepcopy(stored), 'explanation_check': {
        **stored['explanation_check'], 'claim_semantics_version': 13}}
    old_legacy = deepcopy(legacy)
    assert any(i['code'] == CODE for i in saved_claim_semantic_issues(service.analysis, legacy))
    assert legacy == old_legacy
    assert service.analysis.get_draft(draft['id']) == stored
    assert service.analysis.get_run(run['id']) == old_run
    (tmp_path / 'actual-zero-save.json').write_text(json.dumps({
        'short': short, 'claim': CLAIM, 'draft_id': draft['id'], 'run_id': run['id'],
        'output_hash': run['output_hash'], 'quality': draft['quality']['status'],
        'completion': draft['completion']['status'], 'issues': issues,
        'revision_id': fixed['id'], 'revision_parent_id': fixed['parent_id'],
        'revision_completion': fixed['completion'], 'legacy_epoch': 13,
        'legacy_readonly_recheck_detected': True, 'old_draft_and_run_unchanged': True,
        'claim_semantics_version': CLAIM_SEMANTICS_VERSION, 'provider_calls': 0,
    }, ensure_ascii=False, indent=2))
    assert len(issues) == 1
    assert draft['completion']['status'] != 'complete'


def test_actual_sdk_with_native_cli_holds_zero_leading_claim_before_delivery(tmp_path):
    manager, _, _, initial = _template_case(tmp_path)
    session_id = 'native-sdk-zero-word-order'
    manager.task.record_session(session_id, role='analysis')
    modules = _runtime_or_skip() / '@deepseek-ai'
    driver = tmp_path / 'native-zero-loop.mjs'
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
let calls=0,runId,raw,toolCalls=[],nextMessages;
function* tool(name,id,spec){{const args=JSON.stringify({{spec}});
yield{{type:'block-start',index:1,blockType:'tool-call'}};yield{{type:'tool-call-delta',index:1,id,name,argumentsDelta:args}};
yield{{type:'block-end',index:1,block:{{type:'tool-call',id,name,arguments:args}}}};}}
class Offline extends LlmAdapter{{async *stream(options){{calls++;
if(calls===1){{yield*tool('finance_scenario_run','zero-native-run',{{scenario_id:{initial['result']['scenario_id']!r}}});}}
else if(calls===2){{
raw='普通进度🙂。\\r\\nThe scenario run succeeded (run id `'+runId+'`), all 13 metrics derived and `source_verified`, all 12 model checks `pass` with zero differences. Let me prepare the explanation facts.\\r\\n现在准备说明。';
yield{{type:'block-start',index:0,blockType:'text'}};for(const text of raw)yield{{type:'text-delta',index:0,text}};
yield{{type:'block-end',index:0,block:{{type:'text',text:raw}}}};yield*tool('prepare_explanation','zero-prepare',{{run_ids:[runId]}});}}
else{{nextMessages=options.messages;yield{{type:'block-start',index:0,blockType:'text'}};yield{{type:'text-delta',index:0,text:'已继续准备。'}};
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
actual_block_ends:ends.map(e=>({{seq:e.seq,text:e.data.chunk.block.text}})),
actual_message_texts:messages,derived_texts:derived,next_round_public_texts:(nextMessages??[]).flatMap(m=>m.content??[]).filter(b=>b.type==='text').map(b=>b.text),
calls,toolCalls,provider_calls:0,private_reasoning_extracted:false}};
writeFileSync({str(tmp_path / 'actual-native-sdk-zero.json')!r},JSON.stringify(observation,null,2));
await handle.dispose();
assert.ok(held&&selected,JSON.stringify({{calls,toolCalls}}));assert.equal(selected.data.status,'contradicted');
assert.equal(selected.data.server_source_binding.run_id,runId);assert.equal(selected.data.server_source_binding.claim_semantics_version,{CLAIM_SEMANTICS_VERSION});
assert.ok(selected.data.delivered_text.startsWith('普通进度🙂。\\r\\n'));assert.ok(selected.data.delivered_text.endsWith('\\r\\n现在准备说明。'));
assert.ok(diagnostics.indexOf(held)<diagnostics.indexOf(selected)&&selected.observed_after_seq<chunks[0].seq);
assert.equal(messages[0],selected.data.delivered_text);
assert.equal(ends[0].data.chunk.block.text,selected.data.delivered_text);
assert.equal(chunks[0].data.chunk.text,selected.data.delivered_text);
assert.ok(!chunks.some(e=>e.data.chunk.text.includes('zero differences')));
assert.ok(!derived.some(text=>text.includes('zero differences')));
assert.ok(!JSON.stringify(nextMessages).includes('zero differences'));
const {{DeepSeekAdapter,resolveAdapterOptions}}=await import({(modules / 'dsh-llm-deepseek/lib/index.js').as_uri()!r});
const fetchOriginal=globalThis.fetch;let wire;
globalThis.fetch=async(_url,options)=>{{wire=JSON.parse(options.body);return new Response(
  'data: {{"choices":[{{"delta":{{"content":"ok"}},"finish_reason":"stop"}}]}}\\n\\ndata: [DONE]\\n\\n',
  {{status:200,headers:{{'content-type':'text/event-stream'}}}});}};
try{{
  const connection=resolveAdapterOptions({{baseURL:'https://offline.invalid',models:[{{id:'fake'}}]}},undefined);
  const adapter=new DeepSeekAdapter({{options:()=>connection,resolveApiKey:async()=> 'offline-stub',resolveUserId:()=> 'offline'}});
  for await(const _chunk of adapter.stream({{model:'fake',messages:nextMessages}})){{}}
  assert.ok(wire.messages.some(m=>m.role==='assistant'&&m.content===selected.data.delivered_text));
  assert.ok(!JSON.stringify(wire).includes('zero differences'));
  observation.adapter_serialized_public_texts=wire.messages.map(m=>m.content).filter(t=>typeof t==='string');
  writeFileSync({str(tmp_path / 'actual-native-sdk-zero.json')!r},JSON.stringify(observation,null,2));
}}finally{{globalThis.fetch=fetchOriginal;}}
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
    (tmp_path / 'actual-native-sdk-zero-process.json').write_text(json.dumps({
        'exit_code': observed.returncode, 'stdout': observed.stdout, 'stderr': observed.stderr,
        'provider_calls': 0,
    }, ensure_ascii=False, indent=2))
    assert observed.returncode == 0, observed.stderr
    assert json.loads(observed.stdout)['passed']
