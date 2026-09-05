/** Observation-only probe: the configured provider owns every model response. */
import { readFileSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { execFileSync } from 'node:child_process';

const config = JSON.parse(readFileSync(new URL('./config.json', import.meta.url), 'utf8'));
export const name = 'foundry-method-session-verifier';
export const inject = ['agents', 'agentPresets', 'agentDefaultModel', 'tools', 'skills'];

export function apply(ctx) {
  // Cordis can reapply a consumer as its injected services settle. Only one
  // observer may own these session IDs within this harness process.
  const started = globalThis[Symbol.for('foundry.methodVerifier.started')] ??= new Set();
  if (started.has(config.report)) return;
  started.add(config.report);
  // Test isolation only. The product, not this probe, must set the bundled root.
  if (config.agentsHome) process.env.DSH_AGENTS_HOME = config.agentsHome;
  const report = {status: 'running', model: null, explicit_loads: [], cases: [], runtime: {
    pid: process.pid, ppid: process.ppid, executable: process.execPath,
    bundled_root: process.env.DSH_BUNDLED_SKILL_DIR,
    harness_home: process.env.DSH_HOME, agents_home: process.env.DSH_AGENTS_HOME,
  }};
  const save = () => writeFileSync(config.report, `${JSON.stringify(report, null, 2)}\n`);
  const sha = (text) => createHash('sha256').update(text).digest('hex');
  const run = async () => {
    const {createUserMessage} = await import(pathToFileURL(join(config.dshRoot, 'node_modules/@deepseek-ai/dsh-llm/lib/index.js')).href);
    await ctx.agentPresets.standingKeyFor('analysis');
    const model = ctx.agentDefaultModel.currentSelection();
    report.model = model;
    save();
    for (const item of config.cases) {
      const row = {id: item.id, session_id: item.sessionId, task_id: item.taskId, started_at: new Date().toISOString(), calls: [], catalog: []};
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
        // Register only after this observer owns the real DSH agent. Publishing
        // a future session beforehand lets the desktop restore it concurrently.
        execFileSync(process.env.FOUNDRY_BIN, ['--var', process.env.FOUNDRY_VAR,
          '--task', item.taskId, '--session', item.sessionId, 'record-session',
          '--role', 'analysis', '--workspace', item.workspace], {encoding: 'utf8'});
        const catalog = await ctx.skills.snapshot({cwd: item.workspace, scope: handle.agent});
        row.catalog = catalog.skills.map(s => ({name: s.name, provider: s.provider}));
        row.catalog_complete = catalog.complete;
        // Explicit loader checks are separate from the natural-language cases.
        if (item.explicit) {
          for (const name of config.ids) {
            const result = await ctx.tools.execute({name: 'skill', callId: `explicit-${name}`,
              arguments: {name}, agent: handle.agent, signal: new AbortController().signal});
            if (result.isError) throw new Error(`skill ${name} failed: ${JSON.stringify(result.error)}`);
            const resources = [];
            for (const resource of ['FOUNDRY.md', 'CONNECTORS.md']) {
              const read = await ctx.tools.execute({name: 'method-resource', callId: `resource-${name}-${resource}`,
                arguments: {skill: name, resource}, agent: handle.agent, signal: new AbortController().signal});
              if (read.isError) throw new Error(`resource ${resource} failed: ${JSON.stringify(read.error)}`);
              resources.push(JSON.parse(read.value.stdout));
            }
            report.explicit_loads.push({name, provider: result.value.provider,
              resourceBase: result.value.resourceBase, content_sha256: sha(result.value.content), resources});
          }
        } else {
          handle.agent.followup(createUserMessage({content: [{type: 'text', text: item.question}], source: {kind: 'user'}}));
          let timer;
          try {
            // Observe a complete turn, including genuine model error recovery.
            // A first tool failure or a first saved draft is not the end of a turn.
            await Promise.race([handle.agent.whenIdle(), new Promise((_, reject) => {
              timer = setTimeout(() => reject(new Error(`case ${item.id} exceeded ${config.timeoutSeconds}s`)), config.timeoutSeconds * 1000);
            })]);
          } finally { clearTimeout(timer); }
          row.events = handle.agent.session.events;
          row.messages = handle.agent.session.deriveMessages();
        }
        row.completed = true;
        row.completed_at = new Date().toISOString();
        save();
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
