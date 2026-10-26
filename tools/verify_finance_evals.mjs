/** Observation-only r2 finance eval probe: the configured provider owns every model response. */
import { readFileSync, writeFileSync, renameSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { join, dirname } from 'node:path';
import { pathToFileURL } from 'node:url';
import { execFileSync } from 'node:child_process';

const config = JSON.parse(readFileSync(new URL('./config.json', import.meta.url), 'utf8'));
export const name = 'foundry-finance-evals-verifier';
export const inject = ['agents', 'agentPresets', 'agentDefaultModel', 'tools', 'skills'];

const DEFAULT_FOUNDRY_MAX_BUFFER_BYTES = 16 * 1024 * 1024;
const CONFIGURED_FOUNDRY_MAX_BUFFER_BYTES = Number(process.env.FOUNDRY_OBSERVER_MAX_BUFFER_BYTES ?? DEFAULT_FOUNDRY_MAX_BUFFER_BYTES);
const FOUNDRY_MAX_BUFFER_BYTES = Number.isInteger(CONFIGURED_FOUNDRY_MAX_BUFFER_BYTES)
  && CONFIGURED_FOUNDRY_MAX_BUFFER_BYTES > 0
  && CONFIGURED_FOUNDRY_MAX_BUFFER_BYTES <= DEFAULT_FOUNDRY_MAX_BUFFER_BYTES
  ? CONFIGURED_FOUNDRY_MAX_BUFFER_BYTES
  : DEFAULT_FOUNDRY_MAX_BUFFER_BYTES;

function foundryOutput(args, timeoutMs = 30_000) {
  return execFileSync(process.env.FOUNDRY_BIN, ['--var', process.env.FOUNDRY_VAR, ...args], {
    encoding: 'utf8',
    maxBuffer: FOUNDRY_MAX_BUFFER_BYTES,
    timeout: Math.max(1, Math.ceil(timeoutMs)), killSignal: 'SIGKILL',
  });
}

function foundryJson(args) {
  return JSON.parse(foundryOutput(args));
}

export function apply(ctx) {
  const started = globalThis[Symbol.for('foundry.financeEvals.started')] ??= new Set();
  if (started.has(config.report)) return;
  started.add(config.report);
  if (config.agentsHome) process.env.DSH_AGENTS_HOME = config.agentsHome;
  const report = {status: 'running', deadline_policy: 'absolute-case-v1', model: null, explicit_loads: [], cases: [], runtime: {
    pid: process.pid, ppid: process.ppid, executable: process.execPath,
    bundled_root: process.env.DSH_BUNDLED_SKILL_DIR,
    harness_home: process.env.DSH_HOME, agents_home: process.env.DSH_AGENTS_HOME,
  }};
  const checkpoint = `${config.report}.checkpoint.jsonl`;
  const save = () => {
    const temporary = `${config.report}.tmp-${process.pid}`;
    writeFileSync(temporary, `${JSON.stringify(report, null, 2)}\n`);
    renameSync(temporary, config.report);
  };
  const active = new Map();
  ctx.on?.('llm/stream', async function* (options, next) {
    const deadline = active.get(options.sessionId);
    if (!deadline) { yield* next(); return; }
    deadline.check('model_admission');
    // DSH freezes model options. agent.cancel aborts their existing loop signal.
    const identity = {call_id: deadline.modelCallId(), session_id: options.sessionId,
      provider: options.provider, model: options.model, purpose: options.purpose ?? null};
    deadline.mark('model_start', identity);
    save();
    try {
      deadline.check('model_dispatch');
      for await (const chunk of next()) {
        deadline.check('model_stream');
        yield chunk;
      }
    } finally { deadline.mark('model_end', identity); save(); }
  }, {global: true, prepend: true});
  const sha = (text) => createHash('sha256').update(text).digest('hex');
  const assistantText = (messages) => {
    const texts = [];
    for (const message of messages ?? []) {
      if (message?.role !== 'assistant') continue;
      for (const part of message.content ?? []) {
        if (part?.type === 'text') texts.push(String(part.text ?? ''));
      }
    }
    return texts.at(-1) ?? '';
  };
  const eventErrors = (events) => {
    const errors = [];
    for (const [index, event] of (events ?? []).entries()) {
      if ((event.type === 'turn/end' && event.data?.reason?.kind === 'error')
          || event.type === 'turn.failed' || event.type === 'error') {
        errors.push({index, event});
      }
    }
    return errors;
  };
  const saveCheckpoint = (row) => {
    const finalAnswer = assistantText(row.messages);
    const toolErrors = row.calls.filter(call => call.isError).map((call, index) => ({
      index, tool: call.name, error: call.error,
    }));
    const compact = {
      id: row.id,
      session_id: row.session_id,
      task_id: row.task_id,
      input_sha256: row.input_sha256,
      started_at: row.started_at,
      completed_at: row.completed_at,
      completed: row.completed === true,
      duration_ms: row.duration_ms,
      deadline: row.deadline,
      error: row.error,
      calls: row.calls.length,
      tool_errors: toolErrors,
      turn_errors: row.turn_errors ?? [],
      final_answer_sha256: finalAnswer ? sha(finalAnswer) : null,
      final_draft: row.final_draft ? {
        id: row.final_draft.id,
        run_ids: row.final_draft.run_ids ?? [],
        claims: (row.final_draft.claims ?? []).length,
        body_sha256: row.final_draft.body ? sha(row.final_draft.body) : null,
      } : null,
    };
    writeFileSync(checkpoint, `${JSON.stringify(compact)}\n`, {flag: 'a'});
  };
  const run = async () => {
    const {createUserMessage} = await import(pathToFileURL(join(config.dshRoot, 'node_modules/@deepseek-ai/dsh-llm/lib/index.js')).href);
    await ctx.agentPresets.standingKeyFor('analysis');
    const model = ctx.agentDefaultModel.currentSelection();
    report.model = model;
    if (config.expectedModel && ['provider', 'model', 'reasoningEffort'].some(key => model[key] !== config.expectedModel[key])) {
      throw new Error('actual model does not match the explicit candidate contract');
    }
    save();
    {
      const taskId = config.cases[0]?.taskId ?? 'finance-evals-explicit-load';
      const workspace = config.cases[0]?.workspace ?? process.cwd();
      const methodSessionId = `r2-finance-eval-method-load-${taskId}`;
      const handle = await ctx.agents.create({
        sessionId: methodSessionId,
        meta: {cwd: workspace, agentPreset: 'analysis'},
        agentOptions: {...model},
        setup: async (agentCtx) => { await ctx.agentPresets.mount(agentCtx, 'analysis'); },
      });
      try {
        foundryOutput(['--task', taskId, '--session', methodSessionId, 'record-session',
          '--role', 'analysis', '--workspace', workspace]);
        for (const methodName of (config.ids ?? [])) {
          const result = await ctx.tools.execute({name: 'skill', callId: `explicit-${methodName}`,
            arguments: {name: methodName}, agent: handle.agent, signal: new AbortController().signal});
          if (result.isError) throw new Error(`skill ${methodName} failed: ${JSON.stringify(result.error)}`);
          const resources = [];
          for (const resource of ['FOUNDRY.md', 'CONNECTORS.md']) {
            const read = await ctx.tools.execute({name: 'method-resource', callId: `resource-${methodName}-${resource}`,
              arguments: {skill: methodName, resource}, agent: handle.agent, signal: new AbortController().signal});
            if (read.isError) throw new Error(`resource ${resource} for ${methodName} failed: ${JSON.stringify(read.error)}`);
            resources.push(JSON.parse(read.value.stdout));
          }
          report.explicit_loads.push({name: methodName, provider: result.value.provider,
            resourceBase: result.value.resourceBase, content_sha256: sha(result.value.content), resources});
          save();
        }
      } finally { await handle.dispose(); }
    }
    for (const item of config.cases) {
      const row = {id: item.id, slot: item.slot, attempt: item.attempt ?? 1, session_id: item.sessionId, task_id: item.taskId, input_sha256: item.inputSha256, started_at: new Date().toISOString(), calls: [], tool_events: [], catalog: []};
      let sequence = 0;
      let toolTurns = 0;
      let modelTurns = 0;
      const maxToolTurns = config.maxToolTurns ?? 80;
      if (!Number.isInteger(maxToolTurns) || maxToolTurns < 1 || maxToolTurns > 80) {
        throw new Error('finance tool turn limit must be an integer from 1 to 80');
      }
      const identity = (exec) => ({call_id: exec.callId, name: exec.name,
        session_id: item.sessionId, seq: ++sequence, monotonic_ns: process.hrtime.bigint().toString(),
        arguments_sha256: sha(JSON.stringify(exec.arguments)), arguments: exec.arguments});
      const startedNs = process.hrtime.bigint();
      const limitMs = config.timeoutSeconds * 1000;
      const controller = new AbortController();
      let handle, timer, rejectDeadline;
      let executionSettled = false;
      let handleDisposed = false;
      const elapsed = () => Number(process.hrtime.bigint() - startedNs) / 1e6;
      row.deadline = {schema_version: 1, limit_ms: limitMs, max_tool_turns: maxToolTurns, started_monotonic_ns: startedNs.toString(),
        expires_at_epoch_ms: Date.now() + limitMs, exceeded: false, events: []};
      const mark = (phase, details = {}) => {
        row.deadline.current_phase = phase;
        row.deadline.events.push({phase, elapsed_ms: elapsed(), monotonic_ns: process.hrtime.bigint().toString(), ...details});
      };
      const expire = (phase) => {
        if (row.deadline.exceeded) return;
        row.deadline.exceeded = true;
        row.deadline.phase = phase;
        mark('deadline_fired');
        const error = new Error(`case ${item.id} exceeded ${config.timeoutSeconds}s`);
        controller.abort(error);
        if (handle?.agent.cancel) {
          mark('cancel_requested');
          handle.agent.cancel({kind: 'timeout', reason: 'finance case absolute deadline'}, {keepInbox: true});
        }
        rejectDeadline(error);
        save();
      };
      const check = (phase) => {
        if (row.deadline.budget_closed && ['model_admission', 'model_dispatch', 'tool_admission', 'tool_dispatch'].includes(phase)) {
          mark('admission_rejected', {requested_phase: phase, reason: 'budget_closed'});
          save();
          throw new DOMException('finance case budget is closed', 'AbortError');
        }
        if (elapsed() >= limitMs) expire(phase);
        controller.signal.throwIfAborted();
      };
      const expired = new Promise((_, reject) => { rejectDeadline = reject; });
      // A losing race still has a rejection handler, including creation failures.
      expired.catch(() => {});
      const deadline = {check, mark, modelCallId: () => `${item.sessionId}:model:${++modelTurns}`};
      active.set(item.sessionId, deadline);
      report.cases.push(row);
      mark('deadline_armed');
      timer = setTimeout(() => expire('timer'), limitMs);
      save(); // Publish before creating an agent so the independent supervisor can act.
      try {
        const execution = async () => {
          check('agent_create');
          mark('agent_create_start');
          save();
          handle = await ctx.agents.create({
            sessionId: item.sessionId,
            meta: {cwd: item.workspace, agentPreset: 'analysis'},
            agentOptions: {...model},
            setup: async (agentCtx) => {
              await ctx.agentPresets.mount(agentCtx, 'analysis');
              agentCtx.on('tools/execute', async (exec, next) => {
                if (exec.agent.id !== item.sessionId) return next();
                check('tool_admission');
                if (toolTurns >= maxToolTurns) {
                  mark('admission_rejected', {requested_phase: 'tool_admission', reason: 'tool_limit',
                    call_id: exec.callId, name: exec.name, max_tool_turns: maxToolTurns});
                  save();
                  throw new Error(`candidate tool turn limit exceeded: ${maxToolTurns}`);
                }
                exec.signal = exec.signal ? AbortSignal.any([exec.signal, controller.signal]) : controller.signal;
                row.tool_events.push({...identity(exec), phase: 'start'});
                toolTurns += 1;
                mark('tool_start', {call_id: exec.callId, name: exec.name, session_id: item.sessionId});
                save();
                check('tool_dispatch');
                const result = await next();
                check('tool_return');
                return result;
              });
              agentCtx.on('tools/result', (exec, result) => {
                if (exec.agent.id !== item.sessionId) return;
                const call = {name: exec.name, call_id: exec.callId, arguments: exec.arguments, isError: result.isError === true};
                if (result.isError) call.error = result.error;
                else call.value = result.value;
                if (exec.name === 'skill' && result.value?.content) call.content_sha256 = sha(result.value.content);
                if (exec.name === 'method-resource' && result.value?.stdout) {
                  try { call.content_sha256 = JSON.parse(result.value.stdout).sha256; } catch {}
                }
                row.tool_events.push({...identity(exec), phase: 'end', is_error: result.isError === true,
                  result_sha256: sha(JSON.stringify(result)), content_sha256: call.content_sha256});
                row.calls.push(call);
                mark('tool_end', {call_id: exec.callId, name: exec.name, session_id: item.sessionId});
                save();
              });
            },
          });
          mark('agent_create_end');
          if (controller.signal.aborted) {
            mark('cancel_requested');
            handle.agent.cancel?.({kind: 'timeout', reason: 'finance case absolute deadline'}, {keepInbox: true});
            save();
            await handle.dispose();
            handleDisposed = true;
          }
          check('record_session');
          mark('record_session_start');
          save();
          foundryOutput(['--task', item.taskId, '--session', item.sessionId, 'record-session',
            '--role', 'analysis', '--workspace', item.workspace, '--verbatim', item.question], limitMs - elapsed());
          check('catalog');
          mark('catalog_start');
          save();
          const catalog = await ctx.skills.snapshot({cwd: item.workspace, scope: handle.agent});
          row.catalog = catalog.skills.map(s => ({name: s.name, provider: s.provider}));
          row.catalog_complete = catalog.complete;
          check('followup');
          mark('followup');
          save();
          handle.agent.followup(createUserMessage({content: [{type: 'text', text: item.question}], source: {kind: 'user'}}));
          await handle.agent.whenIdle();
          check('completion');
        };
        try {
          const executionPromise = execution().finally(() => {
            executionSettled = true;
            row.deadline.execution_ended = true;
            if (handleDisposed) row.deadline.runtime_terminated = true;
            mark('execution_end');
            save();
          });
          await Promise.race([executionPromise, expired]);
          check('completion');
          row.completed = true;
          row.completed_at = new Date().toISOString();
        } catch (error) {
          if (elapsed() >= limitMs) expire('execution_error');
          row.completed = false;
          row.error = row.deadline.exceeded ? `case ${item.id} exceeded ${config.timeoutSeconds}s` : error.message;
          row.completed_at = new Date().toISOString();
        } finally {
          clearTimeout(timer);
          row.duration_ms = Math.ceil(elapsed());
          mark('budget_closed');
          row.deadline.budget_closed = true;
          row.deadline.budget_closed_ms = row.duration_ms;
          row.deadline.execution_ended = executionSettled;
          save(); // Publish terminal timing before deriving evidence or collecting state.
          const evidenceStarted = process.hrtime.bigint();
          row.events = handle?.agent.session.events ?? [];
          row.messages = handle?.agent.session.deriveMessages() ?? [];
          row.turn_errors = eventErrors(row.events);
          row.provider_retries = row.events.filter(event => event.type === 'llm/retry');
          row.usage = {requests: null, input_tokens: null, output_tokens: null, status: 'unavailable',
            reason: 'raw provider events retained; no verified usage adapter'};
          if (row.turn_errors.length) {
            row.completed = false;
            row.error = row.error ?? 'agent turn ended with error';
          }
          save();
          try {
            const state = foundryJson(['--task', item.taskId, 'analysis-state']);
            const snapshot = JSON.stringify(state);
            const snapshotName = `state-${sha(item.id).slice(0, 20)}.json`;
            writeFileSync(join(dirname(config.report), snapshotName), snapshot, {flag: 'wx'});
            row.state_snapshot = {path: snapshotName, sha256: sha(snapshot)};
            row.final_draft = state.drafts?.at(-1) ?? null;
            row.runs_seen = state.runs?.length ?? 0;
          } catch (error) {
            row.state_error = error.message;
          }
          row.evidence_collection_ms = Number(process.hrtime.bigint() - evidenceStarted) / 1e6;
          saveCheckpoint(row);
          save();
        }
      } finally {
        clearTimeout(timer);
        if (handle && !handleDisposed) await handle.dispose();
        row.deadline.runtime_terminated = executionSettled;
        if (executionSettled) mark('runtime_terminated');
        if (!row.deadline.exceeded) active.delete(item.sessionId);
        save();
      }
    }
    report.status = 'completed';
    save();
  };
  run().catch(error => {
    report.status = 'failed';
    report.error = error.message;
    save();
  });
}
