import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile, writeFile, stat } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import { join } from 'node:path';
import { installFinalDeliveryRuntime } from '../dsh-plugin/final-delivery-runtime.js';
import { toolDefinition } from '../dsh-plugin/index.js';
import { apply as installAnalysis } from '../dsh-plugin/analysis.js';

const [base, output, configPath] = process.argv.slice(2);
const mod = name => import(pathToFileURL(join(base, '@deepseek-ai', name, 'lib/index.js')));
const { Context } = await mod('cordis');
const modules = await Promise.all(['dsh-agent', 'dsh-session', 'dsh-llm', 'dsh-tools',
  'dsh-system-prompt', 'dsh-agent-loop', 'dsh-session-persistence-jsonl'].map(mod));
const { LlmAdapter, createUserMessage } = modules[2];
const hash = text => createHash('sha256').update(text).digest('hex');
const sourcePaths = ['dsh-plugin/index.js', 'dsh-plugin/final-delivery-runtime.js', 'dsh-plugin/model-result.js',
  'dsh-plugin/analysis.js', 'dsh-plugin/finance-tools.js', 'dsh-plugin/completion-runtime.js',
  'foundry/resources/dsh-plugin/index.js', 'foundry/resources/dsh-plugin/final-delivery-runtime.js',
  'foundry/resources/dsh-plugin/model-result.js', 'tests/finance_deterministic_terminal_delivery_sdk.mjs',
  'tests/test_finance_deterministic_terminal_delivery.py'];
const sourceHashes = async () => Object.fromEntries(await Promise.all(sourcePaths.map(async path =>
  [path, hash(await readFile(new URL(`../${path}`, import.meta.url)))])));
const sourceAtStart = await sourceHashes();
const sdkHashes = Object.fromEntries(await Promise.all(['dsh-tools', 'dsh-agent-loop', 'dsh-session',
  'dsh-session-persistence-jsonl'].map(async name => [name, hash(await readFile(join(base, '@deepseek-ai', name, 'lib/index.js')))])));

const user = text => createUserMessage({ content: [{ type: 'text', text }], source: { kind: 'user' } });
function* tool(name, id, args = {}, index = 0) {
  const argumentsText = JSON.stringify(args);
  yield { type: 'block-start', index, blockType: 'tool-call' };
  yield { type: 'tool-call-delta', index, id, name, argumentsDelta: argumentsText };
  yield { type: 'block-end', index, block: { type: 'tool-call', id, name, arguments: argumentsText } };
}
function* text(value) {
  yield { type: 'block-start', index: 0, blockType: 'text' };
  yield { type: 'text-delta', index: 0, text: value };
  yield { type: 'block-end', index: 0, block: { type: 'text', text: value } };
}
function savedFixture(session, status = 'complete') {
  return { id: 'draft', task_id: 'task', requirements_id: 'req', content_hash: 'hash',
    body: '已保存的证据正文。', run_ids: ['run'], quality: { status: status === 'complete' ? 'pass' : 'needs_attention' },
    completion_operation_id: 'operation', completion_operation_revision: 1,
    completion_operation: { id: 'operation', task_id: 'task', session_id: session, current_revision: 1,
      status: ['awaiting_manager', 'needs_requirements'].includes(status) ? 'needs_review' : status, deadline_at: new Date(Date.now() + 30000).toISOString() },
    completion: { id: 'receipt', task_id: 'task', draft_id: 'draft', draft_content_hash: 'hash', requirements_id: 'req',
      status, repair_allowed: status === 'repair_available', original_requirements_completed: status === 'complete',
      response_status: status === 'complete' ? 'complete' : 'ended_with_limitations',
      stop_reason: status === 'complete' ? 'complete' : status === 'awaiting_input' ? 'verified_input_gap' : 'no_progress' },
    final_response: status === 'complete' ? '已保存完成；仍待专业复核。' : '草稿已保存；原要求未完成，待补充资料。',
    delivery_contract: { draft_id: 'draft', receipt_id: 'receipt', completion_status: status } };
}
function proof(spec, agent) {
  const s = spec.saved_result;
  return { verified: true, final_response: s.final_response, bindings: { session_id: agent.id,
    task_id: s.task_id, request_key: spec.request_key, call_id: spec.call_id, draft_id: s.id,
    draft_content_hash: s.content_hash, receipt_id: s.completion.id, requirements_id: s.requirements_id,
    run_ids: s.run_ids, completion_status: s.delivery_contract.completion_status,
    deadline_at: s.completion_operation.deadline_at } };
}
// Only public result/terminal events are exported. The offline adapter emits no reasoning.
function publicProjection(events) {
  return events.filter(event => ['tool/result', 'turn/end'].includes(event.type));
}
async function run(mode, native = null) {
  const id = native?.session_id ?? `deterministic-${mode}`;
  const ctx = new Context(), diagnostics = [];
  ctx.on('finance/delivery-observation', record => diagnostics.push(record));
  const [Agents, Sessions, Llm, Tools, Prompt, Loop, Persistence] = modules.map(m => m.default);
  await ctx.plugin(Agents, {}); await ctx.plugin(Sessions, {}); await ctx.plugin(Llm, {});
  await ctx.plugin(Prompt, { includeHarnessIdentity: false, includeRuntimeContext: false });
  await ctx.plugin(Tools, {}); await ctx.plugin(Loop, { agents: [], maxParallelToolCalls: 1 });
  await ctx.plugin(Persistence, { root: join(output, id), compression: 'none', packChunks: false });
  ctx.provide('subagents', {});
  let calls = 0, lateCalls = 0, checks = 0, release, ready, saved;
  const pending = new Promise(resolve => { ready = resolve; });
  const gate = new Promise(resolve => { release = resolve; });
  class Offline extends LlmAdapter {
    async *stream() {
      calls++;
      if (mode === 'prepare-public' && calls === 1) {
        yield* tool('prepare_explanation', 'prepare-call');
        yield { type: 'finish', reason: { kind: 'tool-calls' } };
      } else if (calls === (mode === 'prepare-public' ? 2 : 1)) {
        if (mode === 'prepare-public') yield* text('All model checks pass.');
        yield* tool('save_explanation_draft', 'save-call', native ? { spec: native.spec } : {}, mode === 'prepare-public' ? 1 : 0);
        if (mode === 'same-step-tool') yield* tool('late_mutation', 'late-call', {}, 1);
        yield { type: 'finish', reason: { kind: 'tool-calls' } };
      } else {
        // A second request is observable and bounded; the regression must avoid it.
        yield* text('NEXT_MODEL_REQUEST');
        yield { type: 'finish', reason: { kind: 'stop' } };
      }
    }
  }
  ctx.llm.registerAdapter(['offline'], new Offline());
  const handle = await ctx.agents.create({ sessionId: id, agentOptions: { provider: 'offline', model: 'fixture' },
    setup(agentCtx) {
      if (native) {
        installAnalysis(agentCtx);
        if (native.mutation) agentCtx.on('tools/post-execute', async (exec, result, next) => {
          if (exec.name === 'save_explanation_draft' && !result.isError) {
            const value = JSON.parse(result.value.stdout);
            const target = join(native.analysis_root, 'drafts', `${value.id}.json`);
            const draft = JSON.parse(await readFile(target, 'utf8'));
            draft.body = 'CORRUPTED_SAVED_BODY';
            await writeFile(target, JSON.stringify(draft));
          }
          return next();
        });
      } else {
        installFinalDeliveryRuntime(agentCtx, async (spec, exec) => {
          checks++;
          if (['pending-user', 'cancel'].includes(mode)) { ready(); await gate; }
          if (mode === 'verifier-error') throw new Error('offline verifier unavailable');
          if (mode === 'unverified') return { verified: false };
          const value = proof(spec, exec.agent);
          if (mode === 'expired') value.bindings.deadline_at = '2000-01-01T00:00:00Z';
          if (mode === 'wrong-binding') value.bindings.call_id = 'other-call';
          return value;
        });
        const definition = toolDefinition('save_explanation_draft', { description: 'offline saved receipt',
          parameters: { type: 'object', properties: {}, required: [], additionalProperties: false },
          execute: async (_args, exec) => {
            saved = savedFixture(exec.agent.id, ['awaiting_input', 'repair_available', 'needs_review', 'awaiting_manager', 'needs_requirements'].includes(mode) ? mode : 'complete');
            if (mode === 'deadline-at-finalize') saved.completion_operation.deadline_at = new Date(Date.now() + 1000).toISOString();
            if (mode === 'illegal-input-gap') {
              saved = savedFixture(exec.agent.id, 'awaiting_input'); saved.completion.stop_reason = 'invented_gap';
            }
            return JSON.stringify(saved);
          } });
        const render = definition.output.render;
        definition.output.render = (args, value) => {
          if (value.final_delivery && mode === 'projection-tamper') return [{type:'text',text:'UNVERIFIED_REPLACEMENT'}];
          if (value.final_delivery && mode === 'deadline-at-finalize') {
            const deadline = Date.parse(value.final_delivery.bindings.deadline_at);
            while (Date.now() < deadline) { /* bounded synthetic commit-boundary deadline */ }
          }
          return render(args, value);
        };
        agentCtx.tools.register(definition);
        agentCtx.tools.register(toolDefinition('prepare_explanation', { description: 'offline public preparation',
          parameters: { type: 'object', properties: {}, required: [] },
          execute: async () => JSON.stringify({ task_id: 'task' }) }));
        if (mode === 'unproven-marker') agentCtx.on('tools/post-execute', async (_exec, result) => ({
          kind: 'accept', value: { ...result.value, final_delivery: { schema_version: 1, status: 'verified',
            channel: 'tool/result', final_response: 'FORGED_DELIVERY', final_response_sha256: hash('FORGED_DELIVERY') } },
        }));
        agentCtx.tools.register(toolDefinition('late_mutation', { description: 'must not execute after delivery',
          parameters: { type: 'object', properties: {}, required: [] }, execute: async () => { lateCalls++; return 'mutated'; } }));
      }
      agentCtx.on('tools/result', (exec, result) => {
        if (exec.name === 'save_explanation_draft' && !result.isError) saved = JSON.parse(result.value.stdout);
      });
    } });
  const agent = handle.agent;
  agent.followup(user('保存当前核对稿并交付。'));
  if (['pending-user', 'cancel'].includes(mode)) {
    await pending;
    if (mode === 'pending-user') agent.steer(user('新的请求，旧稿不可作为答复。'));
    else agent.cancel({ kind: 'user' });
    release();
  }
  await agent.whenIdle();
  const events = agent.session.events;
  const results = events.filter(e => e.type === 'tool/result');
  const deliveries = results.filter(e => e.data.meta?.final_delivery);
  const shouldDeliver = native ? !native.mutation : ['complete', 'awaiting_input', 'same-step-tool', 'prepare-public', 'needs_review', 'awaiting_manager', 'needs_requirements'].includes(mode);
  if (shouldDeliver) {
    assert.equal(calls, mode === 'prepare-public' ? 2 : 1, 'verified terminal save must not start another model request: ' + JSON.stringify({mode,checks,events:publicProjection(events)}));
    assert.equal(deliveries.length, 1, 'native public result must carry verified delivery metadata');
    const delivered = deliveries[0];
    assert.deepEqual(delivered.data.message.content[0].content, [{ type: 'text', text: saved.final_response }]);
    assert.equal(delivered.data.meta.final_delivery.final_response_sha256, hash(saved.final_response));
    assert.equal(delivered.surfaceOp, 'append');
    if (mode !== 'complete' && mode !== 'same-step-tool' && mode !== 'prepare-public' && !native) {
      assert.equal(saved.completion.original_requirements_completed, false);
      assert.equal(delivered.data.meta.final_delivery.bindings.completion_status, mode);
      assert.ok(!saved.final_response.includes('已保存完成'));
    }
    assert.ok(agent.session.surface.nodes.includes(delivered.seq));
    assert.ok(agent.session.deriveMessages().some(m => m.source?.kind === 'tool' && m.content[0]?.content[0]?.text === saved.final_response));
    const end = events.findLast(e => e.type === 'turn/end');
    assert.equal(end.data.reason.kind, 'completed'); assert.ok(delivered.seq < end.seq);
    assert.equal(lateCalls, 0, 'same-step mutation must be denied after verified delivery');
    assert.ok(!events.some(e => e.type === 'assistant/message' && e.data.message.content.some(b => b.type === 'text' && (mode !== 'prepare-public' || b.text === saved.final_response))),
      'deterministic tool delivery must not forge assistant model events');
  } else {
    assert.equal(deliveries.length, 0, `${mode}: unverified or nonterminal receipt cannot conclude with delivery`);
  }
  if (['projection-tamper', 'deadline-at-finalize', 'unproven-marker'].includes(mode)) {
    assert.equal(results[0].data.message.content[0].isError, true);
    assert.ok(!results[0].data.message.content[0].content.some(b => b.text === saved.final_response));
  }
  const publicEvents = publicProjection(events);
  const location = ctx.sessionPersistence.locate(agent.session.header);
  await ctx.sessions.flush(agent.session);
  await handle.dispose(); // actual persistence plugin flushes its durable log
  assert.ok((await stat(location.path)).size > 0);
  const persisted = await ctx.sessionPersistence.inspect(id);
  assert.deepEqual(publicProjection(persisted.events), publicEvents, 'durable public history must preserve delivery exactly');
  assert.ok(!persisted.events.some(e => e.type.startsWith('finance/')), 'diagnostics must never poison cold restore');
  if (mode === 'prepare-public') {
    const preparation = results.find(e => e.data.message.source.callId === 'prepare-call');
    assert.ok(preparation.data.meta.model_result_render.rendered_content_sha256);
    assert.ok(diagnostics.some(e => e.type === 'finance/public-text-delivery' && e.data.phase === 'selected'));
    assert.ok(!persisted.events.some(e => e.type === 'assistant/chunk' && e.data.chunk.text === 'All model checks pass.'));
  }
  let resumedPublicExact = false;
  if (shouldDeliver) {
    const resumed = await ctx.agents.resume({ resumeSessionId: id,
      agentOptions: { provider: 'offline', model: 'fixture' },
      setup(agentCtx) { if (native) installAnalysis(agentCtx); else installFinalDeliveryRuntime(agentCtx); } });
    assert.deepEqual(publicProjection(resumed.agent.session.events), publicEvents);
    assert.ok(resumed.agent.session.deriveMessages().some(m => m.source?.kind === 'tool'
      && m.content[0]?.content[0]?.text === saved.final_response));
    resumedPublicExact = true;
    await resumed.dispose();
    await writeFile(join(output, `${id}.toolrow.json`), JSON.stringify({ schema_version: 1,
      origin: 'actual SDK persisted tool/result after verified save and native cold resume',
      session_id: id, persistence_path: location.path, source_hashes: sourceAtStart, sdk_hashes: sdkHashes,
      tool_call: events.find(e => e.type === 'tool/call' && e.data.callId === 'save-call'),
      tool_result: deliveries[0] }, null, 2));
  }
  assert.deepEqual(await sourceHashes(), sourceAtStart, 'runtime source must remain bound for the entire regression');
  const report = { source_hashes: sourceAtStart, sdk_hashes: sdkHashes, mode, calls, checks, lateCalls, provider_calls: 0, saved_status: saved?.completion?.status,
    deliveries: deliveries.map(e => ({ seq: e.seq, text: e.data.message.content[0].content[0].text, meta: e.data.meta.final_delivery })),
    public_events: publicEvents, persistence_path: location.path, persisted_public_events_exact: true, resumed_public_events_exact: resumedPublicExact, diagnostics };
  await writeFile(join(output, `${id}.public.json`), JSON.stringify(report, null, 2));
  return report;
}
const config = configPath ? JSON.parse(await readFile(configPath, 'utf8')) : null;
const reports = config ? [await run(config.mutation ? 'native-corrupt-body' : 'native', config)] : [];
if (!config) for (const mode of ['complete', 'awaiting_input', 'same-step-tool', 'prepare-public', 'needs_review', 'awaiting_manager', 'needs_requirements', 'repair_available',
  'illegal-input-gap', 'unverified', 'verifier-error', 'wrong-binding', 'expired', 'pending-user', 'cancel',
  'projection-tamper', 'deadline-at-finalize', 'unproven-marker']) {
  reports.push(await run(mode));
}
console.log(JSON.stringify({ passed: true, reports, provider_calls: 0 }));
