import { createHash, randomUUID } from "node:crypto";
import { mkdtemp, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { guardFinalDelivery, invokeFoundry } from "./index.js";
import { modelRenderObservation } from "./model-result.js";

const SAVE = "save_explanation_draft";
export const UNVERIFIED_REPLY = "当前财务完成状态未能验证，请重新核验并保存。";
const hash = (text) => createHash("sha256").update(text, "utf8").digest("hex");
const CAPTURE_TOOLS = new Set(["finance_scenario_run", "prepare_explanation"]);
const INVALIDATING_TOOLS = new Set(["analysis_requirements_save", "finance_context_save",
  "finance_source_refresh", "analysis-refresh", "analysis_refresh", "finance_scenario_save",
  "finance_profile_revoke", "finance_profile_approve", "finance_rules_publish", "workbook_bind",
  "workbook_apply", "finance_adjustment_save", "structure_proposal_confirm", "finance_map_save",
  "finance_controls_save", "finance_control_finding_save", "run_metric", "explain_variance",
  "analysis-run", "analysis-script", "analysis_run", "analysis_script", "collection_run"]);
const CHECK_UNVERIFIED = "该模型检查摘要暂未核验，请以当前运行记录为准。";
// Disclosure vocabulary of the existing native linked-statements checks. These
// names select text lacking authority; only the Python proof judges truth.
const NATIVE_CHECK_IDS = ["opening_balance_sheet", "revenue_receivables_cash", "ppe_rollforward",
  "payables_rollforward", "debt_financing", "equity_rollforward", "cash_reconciliation",
  "cash_flow_indirect_bridge", "closing_balance_sheet", "nonnegative_operating_balances",
  "restricted_cash_bounds", "cash_sufficiency"];
const NAMED_CHECK = new RegExp(`\\b(?:${NATIVE_CHECK_IDS.join("|")})\\b`, "iu");
const CHECK_STATE = /\b(?:error|alert|pass|passed|passing|fail|failed|failing|status|severity|difference|differences|diff|diffs)\b|通过|失败|差异|差额|等级/iu;

function requestKey(agent, events = agent?.session?.events) {
  if (!Array.isArray(events)) return null;
  const event = events.findLast((item) => item.type === "user/message" && item.data?.source?.kind === "user");
  if (!event || !Number.isInteger(event.seq)) return null;
  const id = event.data.id ?? event.data.messageId ?? event.data.message_id;
  return `${agent.id}:${id ? `message:${id}:seq:${event.seq}` : `seq:${event.seq}`}`;
}

function requestAnchor(agent, events = agent?.session?.events) {
  const key = requestKey(agent, events);
  // followup/steer first persist an Inbox insertion. A newer user can already
  // be pending while user/message still describes the preceding request.
  const inbox = events?.findLast((event) => event.type === "agent/inbox/spliced"
    && event.data?.inserted?.some((message) => message.source?.kind === "user"));
  return key === null ? null : `${key}:inbox:${inbox?.seq ?? -1}`;
}

function observeModelRender(exec, result, observe) {
  // The SDK has already rendered and frozen this public tool content. This is
  // boundary observability, not provider acknowledgement or delivery authority.
  if (![SAVE, "prepare_explanation"].includes(exec.name) || !exec.agent || result.isError !== false
      || result.value?.tool !== exec.name || typeof result.value?.stdout !== "string"
      || !Array.isArray(result.content) || result.content.length === 0
      || !result.content.every(block => block.type === "text" && typeof block.text === "string")) return;
  try {
    const agent = exec.agent, key = requestKey(agent), anchor = requestAnchor(agent);
    const events = agent.session.events;
    const call = events?.findLast(event => event.type === "tool/call"
      && event.data?.callId === exec.callId && event.data.name === exec.name);
    if (!key || !call || requestAnchor(agent, events.filter(event => event.seq <= call.seq)) !== anchor) return;
    observe({ type: "finance/model-result-render", data: {
      ...modelRenderObservation(exec.name, result.value.stdout, result.content), source: "tools/result.content",
      session_id: agent.id, request_key: key, request_anchor: anchor, call_id: exec.callId,
    } }, agent);
  } catch { /* Observation must never turn a valid tool result into a failure. */ }
}

async function verifyCurrent(spec, exec) {
  return verifyFile("finance-delivery-verify", spec, exec);
}

async function verifyPublicText(spec, exec) {
  return verifyFile("finance-public-text-verify", spec, exec);
}

async function verifyFile(command, spec, exec) {
  // A full public save can exceed argv limits. The private temporary request is
  // removed even on cancellation; the CLI only reads task evidence.
  const directory = await mkdtemp(join(tmpdir(), "foundry-delivery-"));
  try {
    const path = join(directory, "proof.json");
    await writeFile(path, JSON.stringify(spec), { mode: 0o600 });
    exec.signal?.throwIfAborted();
    return JSON.parse(await invokeFoundry([command, "--spec-file", path], exec));
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
}

function publicText(chunks) {
  return textBlocks(chunks).map((block) => block.raw).join("\n");
}

function finalAuditRecord(agent, record, chunks, status, delivered, bindings = null, reason = null) {
  const raw = publicText(chunks);
  return { type: "finance/final-delivery", data: {
    schema_version: 1, status, reason, session_id: agent.id,
    request_key: record.requestKey, save_call_id: record.callId,
    raw_text: raw, raw_text_sha256: hash(raw), delivered_text: delivered,
    raw_block_ends: textBlocks(chunks).map((block) => ({ index: block.index, text: block.endText,
      text_sha256: block.endText === null ? null : hash(block.endText) })),
    delivered_text_sha256: delivered === null ? null : hash(delivered),
    delivery_status: delivered === null ? "not_delivered" : "selected_for_delivery", bindings,
  } };
}

function verifiedBinding(result, record, agent) {
  const b = result?.bindings;
  const s = record.saved;
  return s !== null && result?.verified === true && typeof result.final_response === "string"
    && result.final_response === s.final_response && b?.session_id === agent.id
    && b.task_id === s.task_id && b.request_key === record.requestKey && b.call_id === record.callId
    && b.draft_id === s.id && b.draft_content_hash === s.content_hash
    && b.receipt_id === s.completion?.id && b.requirements_id === s.requirements_id
    && b.completion_status === s.delivery_contract?.completion_status
    && Number.isFinite(Date.parse(b.deadline_at)) && Date.now() < Date.parse(b.deadline_at)
    && JSON.stringify(b.run_ids) === JSON.stringify(s.run_ids);
}

function terminalSave(saved, agent) {
  const c = saved?.completion, op = saved?.completion_operation, d = saved?.delivery_contract;
  if (!c || !op || !d || c.repair_allowed !== false
      || ![saved.id, saved.task_id, saved.requirements_id, saved.content_hash, c.id, op.id]
        .every(value => typeof value === "string" && value.length > 0)
      || typeof saved.body !== "string" || typeof saved.final_response !== "string" || !saved.final_response
      || c.draft_id !== saved.id || c.task_id !== saved.task_id || c.requirements_id !== saved.requirements_id
      || c.draft_content_hash !== saved.content_hash || d.draft_id !== saved.id || d.receipt_id !== c.id
      || d.completion_status !== c.status || op.session_id !== agent.id || op.task_id !== saved.task_id
      || op.id !== saved.completion_operation_id || !Number.isInteger(op.current_revision)
      || op.current_revision !== saved.completion_operation_revision
      || !Number.isFinite(Date.parse(op.deadline_at)) || Date.now() >= Date.parse(op.deadline_at)) return false;
  if (c.status === "complete") return op.status === "complete" && c.response_status === "complete"
    && c.original_requirements_completed === true && c.stop_reason === "complete" && saved.quality?.status === "pass";
  if (c.original_requirements_completed !== false) return false;
  if (c.status === "awaiting_input") return op.status === "awaiting_input"
    && c.response_status === "ended_with_limitations" && c.stop_reason === "verified_input_gap";
  return op.status === "needs_review" && ["needs_review", "awaiting_manager", "needs_requirements"].includes(c.status);
}

function* replaced(chunks, text) {
  const indexes = new Set(chunks.filter((c) => c.type === "block-start" && c.blockType === "text").map((c) => c.index));
  let written = false;
  for (const chunk of chunks) {
    if (indexes.has(chunk.index)) {
      if (!written) {
        written = true;
        yield { type: "block-start", index: chunk.index, blockType: "text" };
        yield { type: "text-delta", index: chunk.index, text };
        yield { type: "block-end", index: chunk.index, block: { type: "text", text } };
      }
      continue;
    }
    // Provider replay metadata describes the original block content, so it must
    // not be attached to the substituted public text. Usage is unchanged.
    if (chunk.type === "finish") {
      const { replayState: _replayState, ...finish } = chunk;
      yield finish;
    } else yield chunk;
  }
}

function captureResult(exec, result) {
  if (result.isError !== false || result.value?.tool !== exec.name || typeof exec.callId !== "string") return null;
  try {
    const output = JSON.parse(result.value.stdout);
    let identity;
    if (exec.name === "finance_scenario_run") {
      identity = { run_id: output.id, requirements_id: output.requirements_id, output_hash: output.output_hash,
        template_id: output.result?.template_id, scenario_id: output.result?.scenario_id,
        context_revision: output.context_revision };
      if (output.session_id !== exec.agent.id || !Number.isInteger(identity.context_revision)) return null;
    } else {
      const counts = output.structure_counts?.filter((item) => item.kind === "model_checks");
      if (counts?.length !== 1) return null;
      const count = counts[0], spec = output.save_template_spec;
      if (spec?.run_ids?.length !== 1 || spec.run_ids[0] !== count.run_id
          || spec.requirements_id !== count.requirements_id) return null;
      identity = { run_id: count.run_id, requirements_id: count.requirements_id, output_hash: count.output_hash,
        template_id: count.template_id, scenario_id: count.scenario_id, context_revision: null };
    }
    if (![output.task_id, ...Object.entries(identity).filter(([key]) => key !== "context_revision")
      .map(([, value]) => value)].every((value) => typeof value === "string" && value.length > 0)) return null;
    return Object.freeze({ session_id: exec.agent.id, tool_name: exec.name, call_id: exec.callId,
      task_id: output.task_id, ...identity });
  } catch { return null; }
}

function textBlocks(chunks) {
  const blocks = new Map();
  for (const chunk of chunks) {
    if (chunk.type === "block-start" && chunk.blockType === "text") {
      blocks.set(chunk.index, { index: chunk.index, raw: "", complete: false, hasDelta: false, endText: null });
    }
    const block = blocks.get(chunk.index);
    if (!block) continue;
    if (chunk.type === "text-delta") { block.raw += chunk.text; block.hasDelta = true; }
    if (chunk.type === "block-end" && chunk.block?.type === "text") {
      block.endText = chunk.block.text;
      if (!block.hasDelta) block.raw = chunk.block.text;
      block.complete = true;
    }
  }
  return [...blocks.values()];
}

function qualificationDisclosure(line) {
  // Finite disclosure grammar, not source authority. An independent subject
  // after a comma can assert a qualification even if the prior clause denies it.
  const parts = line.split(/[,，;]/u);
  return parts.some((part, index) => {
    if (/代码示例|字段示例|字段代码示例|\b(?:code\s+example|example\s+code|do\s+not|cannot|must\s+not|never|not|incorrect|wrong|if|assuming)\b|不得|不能|不应|不可|并非|不是|不等于|不代表|假设|如果|假如|倘若/iu.test(part)
        || /[?？]\s*$/u.test(part)
        || /^\s*this\s+(?:statement|claim)\s+is\s+(?:incorrect|wrong|false)\b/iu.test(parts[index + 1] ?? "")) return false;
    if (/\bsource_binding_status\b/iu.test(part) && !/\bevidence_eligibility\b/iu.test(part)) return false;
    return /\b(?:input_facts|inputs?|outputs?|output\s+facts?|required_metrics)\b|来源(?:绑定)?输入|输入事实|输出事实|输出指标/iu.test(part)
      && (/\b(?:model_verified|unverified|counts_as_amount_evidence)\b|具[备有]金额证据资格|金额证据资格(?:全部|均)?(?:为|是)?\s*(?:true|合格)/iu.test(part)
        || /\bevidence_eligibility\b/iu.test(part) && /\bsource_verified\b/iu.test(part));
  });
}

function unavailableText(text) {
  // No financial inference is made without the native proof. Only finite
  // assertion families lose authority; examples and unrelated bytes survive.
  let fence = null;
  return text.split(/(\r?\n)/u).map((line) => {
    const marker = line.match(/^\s*(```|~~~)/u)?.[1];
    if (marker) fence = fence === marker ? null : fence ?? marker;
    if (/model[_ ]checks?|模型(?:联动)?(?:检查|核查)|blocks_evidence|\bseverity\b/iu.test(line)
        || (NAMED_CHECK.test(line) && CHECK_STATE.test(line))) return CHECK_UNVERIFIED;
    return !fence && !marker && qualificationDisclosure(line)
      ? "事实资格摘要尚未核实，正在依据当前运行继续核对。" : line;
  }).join("");
}

function publicAuditRecord(agent, record, block, phase, delivered = null, proof = null, reason = null) {
  return { type: "finance/public-text-delivery", data: {
    schema_version: 1, phase, session_id: agent.id, request_key: record.requestKey,
    runtime_request_binding: { anchor: record.anchor, tool_call_event_seq: record.callSeq, capture: record.capture },
    block_index: block.index, raw_text: block.raw, raw_text_sha256: hash(block.raw),
    raw_block_end_text: block.endText, raw_block_end_text_sha256: block.endText === null ? null : hash(block.endText),
    delivered_text: delivered, delivered_text_sha256: delivered === null ? null : hash(delivered),
    delivery_status: delivered === null ? "not_delivered" : "selected_for_delivery",
    status: proof?.status ?? "unverifiable", reason: reason ?? proof?.reason ?? "native_check_proof_not_current",
    server_source_binding: proof?.bindings ?? null, issues: proof?.issues ?? [],
  } };
}

function publicBinding(proof, spec, agent) {
  const b = proof?.bindings, c = spec.capture;
  if (proof?.schema_version !== 1 || proof.verified !== true
      || !["unchanged", "contradicted"].includes(proof.status)
      || typeof proof.delivered_text !== "string" || proof.raw_text_sha256 !== hash(spec.text)
      || proof.delivered_text_sha256 !== hash(proof.delivered_text) || !Array.isArray(proof.issues)
      || b?.session_id !== agent.id || b.request_key !== spec.request_key || b.nonce !== spec.nonce
      || b.call_id !== c.call_id || b.authority !== "server_current_native_checks"
      || b.request_authority !== "runtime_must_verify_current_request_and_capture"
      || b.claim_semantics_version !== 19) return false;
  return ["task_id", "run_id", "requirements_id", "output_hash", "template_id", "scenario_id"]
    .every((key) => b[key] === c[key])
    && (c.context_revision === null || b.context_revision === c.context_revision)
    && (proof.status !== "unchanged" || proof.delivered_text === spec.text);
}

function unavailableBinding(proof, spec) {
  // This carries no positive authority. The directly invoked server may still
  // return its bounded neutral projection when source/qualification is revoked.
  return proof?.schema_version === 1 && proof.verified === false && proof.status === "unverifiable"
    && proof.reason === "native_check_proof_not_current" && proof.bindings === null
    && Array.isArray(proof.issues) && proof.issues.length === 0
    && proof.raw_text_sha256 === hash(spec.text) && typeof proof.delivered_text === "string"
    && proof.delivered_text_sha256 === hash(proof.delivered_text);
}

function* projectBlocks(chunks, selections) {
  const emitted = new Set();
  const changed = [...selections.values()].some((item) => item.reconcile || item.delivered !== item.raw);
  for (const chunk of chunks) {
    const selection = selections.get(chunk.index);
    if (selection) {
      if (selection.delivered === null) continue; // unfinished text never escapes
      if (selection.reconcile || selection.delivered !== selection.raw) {
        if (chunk.type === "text-delta") {
          if (!emitted.has(chunk.index)) {
            emitted.add(chunk.index);
            yield { ...chunk, text: selection.delivered };
          }
          continue;
        }
        if (chunk.type === "block-end" && chunk.block?.type === "text") {
          yield { ...chunk, block: { ...chunk.block, text: selection.delivered } };
          continue;
        }
      }
    }
    if (changed && chunk.type === "finish") {
      const { replayState: _replayState, ...finish } = chunk;
      yield finish;
    } else yield chunk;
  }
}

/** Install on the actual analysis preset before any assistant chunks are logged. */
export function installFinalDeliveryRuntime(ctx, verify = verifyCurrent, verifyText = verifyPublicText) {
  // Cordis diagnostics are deliberately outside the session event vocabulary.
  // They preserve public audit bytes for observers, but are not durable session
  // authority. Only native tool/result metadata is cold-restorable proof.
  const observe = (record, agent) => {
    const observation = { ...record, observed_after_seq: agent.session.events.at(-1)?.seq ?? -1 };
    try { ctx.emit?.("finance/delivery-observation", observation); } catch { /* Diagnostics cannot break delivery. */ }
    try { ctx.logger?.debug?.("finance delivery observation %s", JSON.stringify(observation)); } catch { /* Same boundary. */ }
  };
  const audit = (...args) => observe(finalAuditRecord(...args), args[0]);
  const publicAudit = (...args) => observe(publicAuditRecord(...args), args[0]);
  const saves = new WeakMap();
  const captures = new WeakMap();
  const terminal = new WeakMap();
  const pending = new WeakMap();
  const current = (agent, record) => ctx.agents?.get(agent.id)?.session === agent.session
    && requestKey(agent) === record.requestKey && requestAnchor(agent) === record.anchor;
  // concludeTurn ends the next model step, not the remaining calls in this
  // step. A committed terminal save must also fence those later mutations.
  ctx.tools?.guard?.(exec => {
    const record = exec.agent && terminal.get(exec.agent.session);
    return record && current(exec.agent, record) ? "Verified financial delivery already ended this request." : undefined;
  });
  ctx.on("tools/post-execute", async (exec, result, next) => {
    const decision = await next();
    if (exec.name !== SAVE || !exec.agent || exec.parent !== undefined || result.isError !== false
        || decision.kind !== "accept" || Object.hasOwn(decision, "value") || Object.hasOwn(decision, "content")
        || result.value?.tool !== SAVE || typeof exec.concludeTurn !== "function") return decision;
    let saved;
    try { saved = JSON.parse(result.value.stdout); } catch { return decision; }
    if (!terminalSave(saved, exec.agent)) return decision;
    const agent = exec.agent, events = agent.session.events;
    const call = events.findLast(event => event.type === "tool/call" && event.data?.name === SAVE
      && event.data.callId === exec.callId);
    const record = { requestKey: requestKey(agent), anchor: requestAnchor(agent), callId: exec.callId, saved };
    if (!call || !record.requestKey || !current(agent, record)
        || requestAnchor(agent, events.filter(event => event.seq <= call.seq)) !== record.anchor) return decision;
    let proof;
    try {
      exec.signal?.throwIfAborted();
      proof = await verify({ request_key: record.requestKey, call_id: record.callId, saved_result: saved }, exec);
      exec.signal?.throwIfAborted();
    } catch (error) {
      if (exec.signal?.aborted) throw error;
      audit(agent, record, [], "verification_failed", null, null, "terminal_verification_unavailable");
      return decision;
    }
    if (!current(agent, record) || !verifiedBinding(proof, record, agent)
        || proof.bindings.deadline_at !== saved.completion_operation.deadline_at) {
      audit(agent, record, [], "verification_failed", null, null, "terminal_proof_not_current");
      return decision;
    }
    const delivery = { schema_version: 1, status: "verified", channel: "tool/result",
      final_response: proof.final_response, final_response_sha256: hash(proof.final_response), bindings: proof.bindings };
    const check = finalized => {
      exec.signal?.throwIfAborted();
      if (!current(agent, record)) throw new DOMException("Financial final request changed", "AbortError");
      if (Date.now() >= Date.parse(proof.bindings.deadline_at)) {
        throw new DOMException("Financial delivery deadline elapsed", "TimeoutError");
      }
      if (finalized.concludesTurn !== true
          || JSON.stringify(finalized.meta?.final_delivery) !== JSON.stringify(delivery)
          || JSON.stringify(finalized.content) !== JSON.stringify([{ type: "text", text: proof.final_response }])) {
        throw new Error("Financial terminal result projection changed");
      }
    };
    guardFinalDelivery(exec, check);
    pending.set(exec, { record, delivery });
    exec.concludeTurn();
    return { ...decision, value: { ...result.value, final_delivery: delivery } };
  });
  ctx.on("tools/result", (exec, result) => {
    const entry = pending.get(exec);
    pending.delete(exec);
    if (entry && result.isError === false && result.concludesTurn === true
        && result.meta?.final_delivery?.final_response_sha256 === entry.delivery.final_response_sha256) {
      terminal.set(exec.agent.session, entry.record);
      // The native tool/result metadata is the durable delivery proof. No
      // invented assistant event or out-of-vocabulary audit is needed here.
      return;
    }
    observeModelRender(exec, result, observe);
    if (exec.agent && (CAPTURE_TOOLS.has(exec.name) || INVALIDATING_TOOLS.has(exec.name))) {
      const key = requestKey(exec.agent), anchor = requestAnchor(exec.agent);
      const events = exec.agent.session.events;
      const call = events?.findLast((event) => event.type === "tool/call"
        && event.data?.callId === exec.callId && event.data.name === exec.name);
      const sameRequest = call && requestAnchor(exec.agent, events.filter((event) => event.seq <= call.seq)) === anchor;
      captures.set(exec.agent.session, { requestKey: key, anchor, callSeq: call?.seq ?? -1,
        capture: CAPTURE_TOOLS.has(exec.name) && sameRequest ? captureResult(exec, result) : null });
    }
    if (exec.name !== SAVE || !exec.agent) return;
    // Every newer save, including a failure, invalidates the prior candidate.
    saves.delete(exec.agent.session);
    const key = requestKey(exec.agent);
    if (!key || typeof exec.callId !== "string") return;
    const anchor = requestAnchor(exec.agent);
    saves.set(exec.agent.session, { requestKey: key, anchor, callId: exec.callId, saved: null });
    const events = exec.agent.session.events;
    const call = events.findLast((event) => event.type === "tool/call" && event.data?.name === SAVE
      && event.data.callId === exec.callId);
    if (call && requestAnchor(exec.agent, events.filter((event) => event.seq <= call.seq)) !== anchor) return;
    if (result.isError !== false) return;
    try {
      const saved = JSON.parse(result.value.stdout);
      if (result.value.tool !== SAVE || typeof saved.final_response !== "string" || !saved.delivery_contract) return;
      saves.set(exec.agent.session, { requestKey: key, anchor, callId: exec.callId, saved });
    } catch { /* A malformed/non-save result has no substitution authority. */ }
  });
  ctx.on("llm/stream", async function* (options, next) {
    const agent = ctx.agents?.currentInitiator?.();
    const record = agent && saves.get(agent.session);
    let publicRecord = agent && captures.get(agent.session);
    const current = (item) => item && ctx.agents.get(agent.id)?.session === agent.session
      && requestKey(agent) === item.requestKey && requestAnchor(agent) === item.anchor
      && (item.callSeq === undefined || !agent.session.events.some((event) => event.seq > item.callSeq
        && event.type === "tool/call"
        && (CAPTURE_TOOLS.has(event.data?.name) || INVALIDATING_TOOLS.has(event.data?.name))));
    const publishFinal = function* (stream, deadline = null) {
      for (const chunk of stream) {
        options.signal?.throwIfAborted();
        if (!current(record) || saves.get(agent.session) !== record) {
          throw new DOMException("Financial final request changed", "AbortError");
        }
        if (deadline !== null && Date.now() >= deadline) {
          throw new DOMException("Financial delivery deadline elapsed", "TimeoutError");
        }
        yield chunk;
      }
    };
    if (!options.purpose && publicRecord && options.sessionId === agent.id
        && ctx.agents.get(agent.id)?.session === agent.session && !current(publicRecord)) {
      // A later request may discuss a prior run, but cannot borrow its proof.
      // Retain only a no-authority marker so explicit check assertions are held;
      // unrelated ordinary progress still passes byte for byte.
      publicRecord = { requestKey: requestKey(agent), anchor: requestAnchor(agent),
        callSeq: agent.session.events.at(-1)?.seq ?? -1, capture: null };
      captures.set(agent.session, publicRecord);
    }
    if (options.purpose || !agent || options.sessionId !== agent.id
        || (!current(record) && !current(publicRecord))) {
      yield* next();
      return;
    }
    const chunks = [];
    let hasTool = false;
    try {
      for await (const chunk of next()) {
        if (chunk.type === "tool-call-delta"
            || (chunk.type === "block-start" && chunk.blockType === "tool-call")
            || (chunk.type === "block-end" && chunk.block?.type === "tool-call")) hasTool = true;
        // Buffer the model step so text and interleaved tools/reasoning retain
        // global order. No tool arrival can flush an unchecked public prefix.
        chunks.push(chunk);
      }
    } catch (error) {
      if (record && !hasTool) audit(agent, record, chunks, "stream_failed", null, null, "stream_failed");
      if (publicRecord) for (const block of textBlocks(chunks)) {
        publicAudit(agent, publicRecord, block, "held", null, null, "stream_failed");
      }
      throw error;
    }
    const raw = publicText(chunks);
    const finish = chunks.at(-1);
    const textStarted = chunks.some((c) => c.type === "block-start" && c.blockType === "text");
    // A pending completion can refuse the next tool and end this turn after
    // this public prefix has already been persisted. Its saved receipt must
    // also govern text in a well-formed tool step; keep all tool/reasoning
    // chunks intact so normal execution and cancellation retain their order.
    const successfulStep = finish?.type === "finish" && (hasTool
      ? finish.reason?.kind === "tool-calls" : finish.reason?.kind === "stop");
    if (!current(record) || !raw || !textStarted || !successfulStep) {
      if (publicRecord) {
        const selections = new Map();
        for (const block of textBlocks(chunks)) {
          publicAudit(agent, publicRecord, block, "held");
          let proof, delivered = block.complete ? unavailableText(block.raw) : null;
          if (block.complete && publicRecord.capture && current(publicRecord)
              && captures.get(agent.session) === publicRecord) {
            const spec = { request_key: publicRecord.requestKey, nonce: randomUUID(),
              text: block.raw, capture: publicRecord.capture };
            try {
              options.signal?.throwIfAborted();
              proof = await verifyText(spec, { agent, signal: options.signal });
              options.signal?.throwIfAborted();
              if (current(publicRecord) && captures.get(agent.session) === publicRecord
                  && (publicBinding(proof, spec, agent) || unavailableBinding(proof, spec))) delivered = proof.delivered_text;
              else proof = null;
            } catch (error) {
              if (options.signal?.aborted) throw error;
              proof = null;
            }
          }
          publicAudit(agent, publicRecord, block, "selected", delivered, proof,
            block.complete ? null : "incomplete_public_block");
          selections.set(block.index, { raw: block.raw, delivered,
            reconcile: block.complete && block.endText !== block.raw });
        }
        options.signal?.throwIfAborted();
        // A request can be inserted during an async generator yield as well.
        // Check again at each publication, not just after the proof await.
        for (const chunk of projectBlocks(chunks, selections)) {
          options.signal?.throwIfAborted();
          if (!current(publicRecord) || captures.get(agent.session) !== publicRecord) {
            throw new DOMException("Financial public request changed", "AbortError");
          }
          yield chunk;
        }
      } else {
        if (record) audit(agent, record, chunks, "unchanged", raw, null, "not_a_successful_text_final");
        yield* chunks;
      }
      return;
    }
    let proof;
    try {
      options.signal?.throwIfAborted();
      proof = record.saved === null ? null : await verify({ request_key: record.requestKey,
        call_id: record.callId, saved_result: record.saved }, { agent, signal: options.signal });
      options.signal?.throwIfAborted();
    } catch (error) {
      audit(agent, record, chunks, "verification_failed", options.signal?.aborted ? null : UNVERIFIED_REPLY, null,
        options.signal?.aborted ? "cancelled" : "verification_unavailable");
      if (options.signal?.aborted) throw error;
      yield* publishFinal(replaced(chunks, UNVERIFIED_REPLY));
      return;
    }
    if (saves.get(agent.session) !== record || !current(record)
        || !verifiedBinding(proof, record, agent)) {
      audit(agent, record, chunks, "verification_failed", UNVERIFIED_REPLY, null, "delivery_proof_not_current");
      options.signal?.throwIfAborted();
      yield* publishFinal(replaced(chunks, UNVERIFIED_REPLY));
      return;
    }
    audit(agent, record, chunks, raw === proof.final_response ? "already_exact" : "replaced",
      proof.final_response, proof.bindings);
    options.signal?.throwIfAborted();
    if (Date.now() >= Date.parse(proof.bindings.deadline_at)) {
      throw new DOMException("Financial delivery deadline elapsed", "TimeoutError");
    }
    yield* publishFinal(replaced(chunks, proof.final_response), Date.parse(proof.bindings.deadline_at));
  });
}
