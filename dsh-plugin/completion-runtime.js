import { invokeFoundry } from "./index.js";

const SAVE_TOOL = "save_explanation_draft";
const CANCEL_AFTER_RESULT_STATUSES = new Set(["needs_review", "awaiting_input", "timed_out"]);
const TERMINAL_STATUSES = new Set(["complete", "needs_review", "awaiting_input", "timed_out", "cancelled", "failed"]);
const FORBIDDEN_AUTHORITY_FIELDS = new Set([
  "operation_id",
  "operation_revision",
  "operation_intent",
  "operation_payload_hash",
  "completion_operation_id",
  "completion_operation_revision",
  "completion_request_key",
  "completion_operation",
  "completion_revision",
  "completion_call_id",
  "intent",
  "revision",
  "call_id",
]);

function parseJson(output, command) {
  try {
    return JSON.parse(output);
  } catch (error) {
    throw new Error(`${command} returned non-JSON output: ${error.message}`);
  }
}

async function command(invoke, args, exec) {
  return parseJson(await invoke(args, exec), args[0]);
}

function sessionIdOf(exec) {
  const id = exec?.agent?.id;
  if (id === undefined || id === null || !String(id).trim()) {
    throw new Error("completion runtime requires a registered agent session");
  }
  return String(id);
}

function callIdOf(exec) {
  const id = exec?.callId;
  if (id === undefined || id === null || !String(id).trim()) {
    throw new Error("completion runtime requires a trusted exec.callId");
  }
  return String(id);
}

function latestUserRequestKey(exec) {
  const sessionId = sessionIdOf(exec);
  const requestIdentity = latestUserRequestIdentity(exec);
  if (!requestIdentity) throw new Error("save_explanation_draft completion requires a human user/message event");
  return `${sessionId}:${requestIdentity}`;
}

function latestUserRequestIdentity(exec) {
  const events = exec?.agent?.session?.events;
  if (!Array.isArray(events)) throw new Error("completion runtime requires session events");
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (event?.type !== "user/message" || event?.data?.source?.kind !== "user") continue;
    const messageId = event.data.id ?? event.data.messageId ?? event.data.message_id;
    const seq = event.seq;
    if ((messageId === undefined || messageId === null || !String(messageId).trim()) && !Number.isInteger(seq)) {
      throw new Error("user message event lacks stable id or seq");
    }
    return messageId !== undefined && messageId !== null && String(messageId).trim()
      ? `message:${String(messageId)}:seq:${String(seq)}`
      : `seq:${String(seq)}`;
  }
  return null;
}

function hasAuthorityField(key) {
  return FORBIDDEN_AUTHORITY_FIELDS.has(key) || key.startsWith("_completion") || key.startsWith("$completion");
}

function rejectAuthorityFields(input) {
  if (!input || typeof input !== "object" || Array.isArray(input)) {
    throw new Error(`${SAVE_TOOL} runtime input must be an object with spec`);
  }
  for (const key of Object.keys(input)) {
    if (hasAuthorityField(key)) throw new Error(`${SAVE_TOOL} authority field is runtime-owned: ${key}`);
  }
  const spec = input.spec;
  if (!spec || typeof spec !== "object" || Array.isArray(spec)) {
    throw new Error(`${SAVE_TOOL} runtime input must include a spec object`);
  }
  for (const key of Object.keys(spec)) {
    if (hasAuthorityField(key) || key.startsWith("_") || key.startsWith("$")) {
      throw new Error(`${SAVE_TOOL} spec authority field is runtime-owned: ${key}`);
    }
  }
}

function integerLikeEnv(name) {
  if (!(name in process.env)) return undefined;
  const raw = process.env[name];
  if (/^[0-9]+$/.test(raw ?? "")) return Number(raw);
  return raw;
}

function effectivePolicy(policy) {
  const result = {};
  if (policy && typeof policy === "object" && !Array.isArray(policy)) {
    if ("max_repairs" in policy) result.max_repairs = policy.max_repairs;
    if ("timeout_seconds" in policy) result.timeout_seconds = policy.timeout_seconds;
  }
  const maxRepairs = integerLikeEnv("FOUNDRY_COMPLETION_MAX_REPAIRS");
  const timeoutSeconds = integerLikeEnv("FOUNDRY_COMPLETION_TIMEOUT_SECONDS");
  if (maxRepairs !== undefined) result.max_repairs = maxRepairs;
  if (timeoutSeconds !== undefined) result.timeout_seconds = timeoutSeconds;
  return result;
}

function statusOf(operation) {
  return String(operation?.status ?? "").toLowerCase();
}

function parseDeadline(operation) {
  const deadline = operation?.deadline_at;
  if (!deadline) throw new Error("finance-completion-begin did not return deadline_at");
  const timestamp = Date.parse(deadline);
  if (!Number.isFinite(timestamp)) throw new Error("finance-completion-begin returned invalid deadline_at");
  return timestamp;
}

function clearTimer(record) {
  if (record?.timer) clearTimeout(record.timer);
  if (record) record.timer = null;
}

function cancelCause(reason) {
  return { kind: "hook", reason };
}

function stopExec(exec) {
  const clone = { ...exec };
  delete clone.signal;
  return clone;
}

async function bestEffortStop(ctx, invoke, exec, operationId, reason) {
  try {
    await command(invoke, ["finance-completion-stop", "--spec", JSON.stringify({ operation_id: operationId, reason })], stopExec(exec));
  } catch (error) {
    ctx?.logger?.warn?.(`finance completion stop failed: ${error.message}`);
  }
}

function registryKey(sessionId, requestKey) {
  return `${sessionId}\n${requestKey}`;
}

function controllerAbort(controller, reason) {
  if (!controller.signal.aborted) controller.abort(reason);
}

function registerController(record, controller) {
  record.controllers.add(controller);
  return () => record.controllers.delete(controller);
}

function shouldStopCurrentTurn(status) {
  return CANCEL_AFTER_RESULT_STATUSES.has(statusOf(status));
}

/*
 * A draft that ends needs_review (or awaiting_input, timed_out) closes the request's tool
 * work, but not its reply. The turn used to be cancelled the moment the save result landed,
 * so the manager saw a save card and no sentence. Now the model gets the result and can say
 * in a line or two what the draft is waiting on; the first tool call it tries after that,
 * for the same request, cancels the turn instead of running. A new user message lifts it.
 */
function haltAfterResult(halted, record, requestKey, status) {
  if (!shouldStopCurrentTurn(status)) return;
  halted.set(registryKey(record.sessionId, requestKey), cancelCause(`finance completion ${statusOf(status)}`));
}

function refuseIfHalted(halted, exec) {
  if (!halted.size || !exec?.agent?.id) return;
  const identity = latestUserRequestIdentity(exec);
  if (!identity) return;
  const sessionId = String(exec.agent.id);
  const key = registryKey(sessionId, `${sessionId}:${identity}`);
  for (const stale of [...halted.keys()]) {
    if (stale.startsWith(`${sessionId}\n`) && stale !== key) halted.delete(stale);
  }
  const cause = halted.get(key);
  if (!cause) return;
  exec.agent.cancel?.(cause, { keepInbox: true });
  throw new Error(`${cause.reason}: this request's draft is waiting on the manager; reply without further tools`);
}

async function timeoutOperation(ctx, invoke, exec, record) {
  if (record.closed) return;
  record.closed = true;
  clearTimer(record);
  for (const controller of record.controllers) {
    controllerAbort(controller, new DOMException("finance completion timed out", "TimeoutError"));
  }
  let status;
  try {
    status = await command(invoke, ["finance-completion-status", "--spec", JSON.stringify({ operation_id: record.operationId })], stopExec(exec));
  } catch (error) {
    ctx?.logger?.warn?.(`finance completion timeout status failed: ${error.message}`);
  }
  if (!TERMINAL_STATUSES.has(statusOf(status))) {
    await bestEffortStop(ctx, invoke, exec, record.operationId, "timeout");
  }
  try {
    if (latestUserRequestKey(exec) === record.requestKey) {
      exec?.agent?.cancel?.(cancelCause("finance completion timeout"), { keepInbox: true });
    }
  } catch (error) {
    ctx?.logger?.warn?.(`finance completion timeout cancel failed: ${error.message}`);
  }
}

function armDeadline(ctx, invoke, exec, operations, record, operation) {
  clearTimer(record);
  const deadline = parseDeadline(operation);
  const delay = Math.max(0, deadline - Date.now());
  record.timer = setTimeout(() => {
    timeoutOperation(ctx, invoke, exec, record).finally(() => operations.delete(registryKey(record.sessionId, record.requestKey)));
  }, delay);
  // This runtime can keep a harness process alive for minutes; the persisted
  // backend operation is authoritative across restarts, so the JS timer should
  // not be a process liveness anchor.
  record.timer.unref?.();
}

async function stopSupersededOperations(ctx, invoke, exec, operations, sessionId, requestKey) {
  for (const [key, record] of [...operations.entries()]) {
    if (record.sessionId !== sessionId || record.requestKey === requestKey || record.closed) continue;
    record.closed = true;
    clearTimer(record);
    operations.delete(key);
    await bestEffortStop(ctx, invoke, exec, record.operationId, "superseded");
  }
}

function linkRunExec(exec, controller) {
  const onAbort = () => controllerAbort(controller, exec.signal.reason);
  if (exec?.signal?.aborted) onAbort();
  else exec?.signal?.addEventListener?.("abort", onAbort, { once: true });
  return {
    exec: { ...exec, signal: controller.signal },
    release: () => exec?.signal?.removeEventListener?.("abort", onAbort),
  };
}

async function stopSupersededForCurrentUser(ctx, invoke, exec, operations) {
  if (!exec?.agent?.id || !Array.isArray(exec?.agent?.session?.events)) return;
  const requestIdentity = latestUserRequestIdentity(exec);
  if (!requestIdentity) return;
  const sessionId = sessionIdOf(exec);
  const requestKey = `${sessionId}:${requestIdentity}`;
  await stopSupersededOperations(ctx, invoke, exec, operations, sessionId, requestKey);
}

export function createCompletionRuntime(ctx = {}, invoke = invokeFoundry, policy = {}) {
  const operations = new Map();
  const halted = new Map();
  const call = (args, exec) => command(invoke, args, exec);

  return async function completionRuntime(tool, input, exec, run) {
    if (typeof run !== "function") throw new Error("completion runtime requires a tool runner");
    refuseIfHalted(halted, exec);
    if (tool !== SAVE_TOOL) {
      await stopSupersededForCurrentUser(ctx, invoke, exec, operations);
      return run(input, exec);
    }
    rejectAuthorityFields(input);

    const sessionId = sessionIdOf(exec);
    const callId = callIdOf(exec);
    const requestKey = latestUserRequestKey(exec);
    await stopSupersededOperations(ctx, invoke, exec, operations, sessionId, requestKey);

    const begin = await call(["finance-completion-begin", "--spec", JSON.stringify({
      request_key: requestKey,
      policy: effectivePolicy(policy),
    })], exec);
    const operationId = String(begin.id ?? "");
    if (!operationId) throw new Error("finance-completion-begin did not return an operation id");

    const key = registryKey(sessionId, requestKey);
    const record = operations.get(key) ?? {
      sessionId,
      requestKey,
      operationId,
      controllers: new Set(),
      timer: null,
      closed: false,
    };
    record.operationId = operationId;
    record.closed = false;
    operations.set(key, record);
    if (TERMINAL_STATUSES.has(statusOf(begin))) {
      record.closed = true;
      clearTimer(record);
      operations.delete(key);
    } else {
      armDeadline(ctx, invoke, exec, operations, record, begin);
    }

    const controller = new AbortController();
    const releaseController = registerController(record, controller);
    const linked = linkRunExec(exec, controller);
    const runExec = linked.exec;
    try {
      const raw = await run({
        ...input,
        _completion_operation: operationId,
        _completion_call_id: callId,
      }, runExec);
      const status = await call(["finance-completion-status", "--spec", JSON.stringify({ operation_id: operationId })], exec);
      if (TERMINAL_STATUSES.has(statusOf(status))) {
        record.closed = true;
        clearTimer(record);
        operations.delete(key);
      }
      haltAfterResult(halted, record, requestKey, status);
      return raw;
    } catch (error) {
      if (exec?.signal?.aborted) await bestEffortStop(ctx, invoke, exec, operationId, "cancelled");
      throw error;
    } finally {
      linked.release();
      releaseController();
    }
  };
}
