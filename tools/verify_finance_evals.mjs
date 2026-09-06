/** Observation-only r2 finance eval probe: the configured provider owns every model response. */
import { readFileSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { execFileSync } from 'node:child_process';

const config = JSON.parse(readFileSync(new URL('./config.json', import.meta.url), 'utf8'));
export const name = 'foundry-finance-evals-verifier';
export const inject = ['agents', 'agentPresets', 'agentDefaultModel', 'tools', 'skills'];

export function apply(ctx) {
  const started = globalThis[Symbol.for('foundry.financeEvals.started')] ??= new Set();
  if (started.has(config.report)) return;
  started.add(config.report);
  if (config.agentsHome) process.env.DSH_AGENTS_HOME = config.agentsHome;
  const report = {status: 'running', model: null, explicit_loads: [], cases: [], runtime: {
    pid: process.pid, ppid: process.ppid, executable: process.execPath,
    bundled_root: process.env.DSH_BUNDLED_SKILL_DIR,
    harness_home: process.env.DSH_HOME, agents_home: process.env.DSH_AGENTS_HOME,
  }};
  const checkpoint = `${config.report}.checkpoint.jsonl`;
  const save = () => writeFileSync(config.report, `${JSON.stringify(report, null, 2)}\n`);
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
        execFileSync(process.env.FOUNDRY_BIN, ['--var', process.env.FOUNDRY_VAR,
          '--task', taskId, '--session', methodSessionId, 'record-session',
          '--role', 'analysis', '--workspace', workspace], {encoding: 'utf8'});
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
      const row = {id: item.id, session_id: item.sessionId, task_id: item.taskId, input_sha256: item.inputSha256, started_at: new Date().toISOString(), calls: [], catalog: []};
      const startedMs = Date.now();
      report.cases.push(row);
      const handle = await ctx.agents.create({
        sessionId: item.sessionId,
        meta: {cwd: item.workspace, agentPreset: 'analysis'},
        agentOptions: {...model},
        setup: async (agentCtx) => {
          await ctx.agentPresets.mount(agentCtx, 'analysis');
          agentCtx.on('tools/result', (exec, result) => {
            if (exec.agent.id !== item.sessionId) return;
            const call = {name: exec.name, arguments: exec.arguments, isError: result.isError === true};
            if (result.isError) call.error = result.error;
            else call.value = result.value;
            if (exec.name === 'skill' && result.value?.content) call.content_sha256 = sha(result.value.content);
            row.calls.push(call);
            save();
          });
        },
      });
      try {
        try {
          execFileSync(process.env.FOUNDRY_BIN, ['--var', process.env.FOUNDRY_VAR,
            '--task', item.taskId, '--session', item.sessionId, 'record-session',
            '--role', 'analysis', '--workspace', item.workspace, '--verbatim', item.question], {encoding: 'utf8'});
          const catalog = await ctx.skills.snapshot({cwd: item.workspace, scope: handle.agent});
          row.catalog = catalog.skills.map(s => ({name: s.name, provider: s.provider}));
          row.catalog_complete = catalog.complete;
          handle.agent.followup(createUserMessage({content: [{type: 'text', text: item.question}], source: {kind: 'user'}}));
          let timer;
          try {
            await Promise.race([handle.agent.whenIdle(), new Promise((_, reject) => {
              timer = setTimeout(() => reject(new Error(`case ${item.id} exceeded ${config.timeoutSeconds}s`)), config.timeoutSeconds * 1000);
            })]);
          } finally { clearTimeout(timer); }
          row.completed = true;
          row.completed_at = new Date().toISOString();
        } catch (error) {
          row.completed = false;
          row.error = error.message;
          row.completed_at = new Date().toISOString();
        } finally {
          row.duration_ms = Date.now() - startedMs;
          row.events = handle.agent.session.events;
          row.messages = handle.agent.session.deriveMessages();
          row.turn_errors = eventErrors(row.events);
          row.provider_retries = row.events.filter(event => event.type === 'llm/retry');
          if (row.turn_errors.length) {
            row.completed = false;
            row.error = row.error ?? 'agent turn ended with error';
          }
          try {
            const state = JSON.parse(execFileSync(process.env.FOUNDRY_BIN, ['--var', process.env.FOUNDRY_VAR,
              '--task', item.taskId, 'analysis-state'], {encoding: 'utf8'}));
            row.final_draft = state.drafts?.at(-1) ?? null;
            row.runs_seen = state.runs?.length ?? 0;
          } catch (error) {
            row.state_error = error.message;
          }
          saveCheckpoint(row);
          save();
        }
      } finally { await handle.dispose(); }
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
