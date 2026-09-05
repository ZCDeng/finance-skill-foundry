import { invokeFoundry } from "./index.js";

/** Runtime-owned child provisioning: record a frozen context before admission. */
export function createAnalysisRuntime(ctx, childTools, invoke = invokeFoundry) {
  const active = new Map();
  const pendingSettlements = new Map();
  // Broker liveness belongs to this process, never to a model-supplied spec.
  const runtimeIdentity = ["--runtime-pid", String(process.pid)];
  const call = async (args, exec) => JSON.parse(await invoke(args, exec));

  async function settle(job, status, result) {
    const exec = { agent: { id: job.session_id } };
    const args = ["analysis-job-settle", "--job", job.id,
      "--child-session", job.child_session_id, "--status", status, "--result", JSON.stringify(result)];
    try {
      const output = await call(args, exec);
      pendingSettlements.delete(job.id);
      active.delete(job.child_session_id);
      return output;
    } catch (error) {
      pendingSettlements.set(job.id, { job, status, result });
      throw error;
    }
  }

  async function retrySettlements(exec) {
    for (const item of [...pendingSettlements.values()]) {
      if (item.job.session_id === exec?.agent?.id) await settle(item.job, item.status, item.result);
    }
  }

  ctx.on("subagent/end", (event) => {
    const job = active.get(event.id);
    if (!job) return;
    const status = event.stopReason === "completed" ? "completed"
      : event.stopReason === "aborted" ? "cancelled" : "failed";
    // The trusted service event is the completion evidence. Child-authored text
    // stays in result.output and cannot choose the recorded execution status.
    return settle(job, status, {
      stop_reason: event.stopReason, output: event.lastAssistantMessage ?? [], runtime_run_id: event.runId,
    }).catch((error) => {
      ctx.logger?.warn(`analysis child settlement not recorded: ${error.message}`);
    });
  });

  async function startChild(job, exec) {
    if (job.kind !== "child") return job; // script jobs already have a service-owned worker
    if (!exec?.agent || job.session_id !== exec.agent.id) throw new Error("child job owner mismatch");
    const provider = job.spec?.mode;
    if (!["spawn", "fork"].includes(provider)) throw new Error("unsupported analysis child mode");
    active.set(job.child_session_id, job);
    try {
      await ctx.subagents.startContinuable({
        provider, childId: job.child_session_id, label: job.spec.label,
        request: {
          parent: exec.agent, prompt: [{ type: "text", text: job.spec.prompt }],
          maxDepth: 1, toolFilter: { allow: [...childTools] },
        },
        signal: exec.signal,
      });
      return await call(["analysis-job-started", "--job", job.id,
        "--child-session", job.child_session_id, ...runtimeIdentity], exec);
    } catch (error) {
      // A failure after publication must not leave an unrecorded child running.
      await ctx.subagents.drainContinuableChildren(exec.agent, [job.child_session_id]);
      await settle(job, exec.signal?.aborted ? "cancelled" : "failed", { error: error.message });
      throw error;
    }
  }

  return async (tool, input, exec) => {
    if (!exec?.agent?.id) throw new Error("analysis jobs require a registered calling agent");
    await retrySettlements(exec);
    if (tool === "analysis-delegate") {
      const job = await call(["analysis-child-start", "--spec", JSON.stringify({
        prompt: input.prompt, label: input.label, mode: input.mode ?? "spawn",
      }), ...runtimeIdentity], exec);
      return JSON.stringify(await startChild(job, exec));
    }
    if (tool === "analysis-job-retry") {
      const job = await call(["analysis-job-retry", "--job", input.job, ...runtimeIdentity], exec);
      return JSON.stringify(await startChild(job, exec));
    }
    if (tool === "analysis-job-cancel") {
      const job = await call(["analysis-job-cancel", "--job", input.job], exec);
      if (job.kind !== "child" || ["completed", "failed", "cancelled"].includes(job.status)) {
        return JSON.stringify(job);
      }
      await ctx.subagents.drainContinuableChildren(exec.agent, [job.child_session_id]);
      return JSON.stringify(await settle(job, "cancelled", { reason: "cancelled by parent after runtime drained child" }));
    }
    throw new Error(`unknown analysis runtime operation ${tool}`);
  };
}
