import { createHash } from "node:crypto";

const REF = "$foundry_ref";
const META = "_model_projection";

/** Public projection fingerprints for the SDK's native tool/result metadata. */
export function modelRenderObservation(tool, raw, content) {
  if (!["save_explanation_draft", "prepare_explanation"].includes(tool)
      || typeof raw !== "string" || !Array.isArray(content) || content.length === 0
      || !content.every(block => block.type === "text" && typeof block.text === "string")) return null;
  const hash = text => createHash("sha256").update(text, "utf8").digest("hex");
  const serialized = JSON.stringify(content);
  return { schema_version: 1, source: "output.render", authority: "none", tool_name: tool,
    raw_stdout_sha256: hash(raw), raw_stdout_bytes: Buffer.byteLength(raw, "utf8"),
    rendered_content_sha256: hash(serialized), rendered_content_bytes: Buffer.byteLength(serialized, "utf8"),
    content_serialization: "JSON.stringify(content)",
    rendered_text_bytes: content.reduce((total, block) => total + Buffer.byteLength(block.text, "utf8"), 0),
    blocks: content.map((block, index) => ({ index, type: "text",
      text_bytes: Buffer.byteLength(block.text, "utf8"), text_sha256: hash(block.text) })) };
}

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

function reserved(value) {
  if (!value || typeof value !== "object") return false;
  return Object.hasOwn(value, REF) || Object.hasOwn(value, META) || Object.values(value).some(reserved);
}

function parseExact(raw) {
  return JSON.parse(raw, (_key, value, context) => {
    if (typeof value === "number" && JSON.stringify(value) !== context?.source) {
      throw new Error("numeric representation would change");
    }
    return value;
  });
}

/** Lossless conversation projection. execute/value/stdout and persisted evidence stay untouched. */
export function compactModelResult(raw) {
  if (typeof raw !== "string" || raw.length < 4096) return raw;
  try {
    // Source-aware parsing preserves unsafe numbers as raw text, never rounded.
    const data = parseExact(raw);
    if (!data || typeof data !== "object" || Array.isArray(data) || reserved(data)) return raw;
    const seen = new Map();
    let references = 0;
    const walk = (value, pointer) => {
      if (!value || typeof value !== "object") return value;
      const signature = canonical(value);
      if (signature.length >= 160) {
        if (seen.has(signature)) {
          references += 1;
          return { [REF]: seen.get(signature) };
        }
        seen.set(signature, pointer);
      }
      if (Array.isArray(value)) return value.map((item, index) => walk(item, `${pointer}/${index}`));
      return Object.fromEntries(Object.entries(value).map(([key, item]) => [key,
        walk(item, `${pointer}/${key.replaceAll("~", "~0").replaceAll("/", "~1")}`)]));
    };
    const projected = walk(data, "#");
    projected[META] = {
      schema: "foundry.model-result.v1", lossless: true, references,
      instruction: "Objects containing only $foundry_ref repeat the exact value at that JSON pointer in this response. Resolve references before use. No facts, errors or failed checks were removed. Full original stdout is retained in the tool record.",
      raw_sha256: createHash("sha256").update(raw).digest("hex"), raw_chars: raw.length,
    };
    const text = JSON.stringify(projected);
    return text.length < raw.length ? text : raw;
  } catch {
    // A presentation problem must never turn a completed save into a tool failure.
    return raw;
  }
}

// Below the verified runtime's 50,000-byte spill threshold, with metadata headroom.
export const MODEL_INLINE_BYTES = 48000;
const bytes = value => Buffer.byteLength(value, "utf8");

function tabularResult(data, raw, fullResult = true, omitted = [], dictionaryMinLength = 64) {
  const counts = new Map();
  const count = value => {
    if (value && typeof value === "object" && (Object.hasOwn(value, "$r") || Object.hasOwn(value, "$v")))
      throw new Error("reserved tabular key");
    const key = JSON.stringify(value);
    if (key.length > dictionaryMinLength) counts.set(key, (counts.get(key) || 0) + 1);
    if (value && typeof value === "object") Object.values(value).forEach(count);
  };
  count(data);
  const columns = [], values = [], schemas = new Map(), seen = new Map();
  const walk = (value, defining = false) => {
    const key = JSON.stringify(value);
    if (!defining && key.length > dictionaryMinLength && counts.get(key) > 1) {
      if (seen.has(key)) return { $v: seen.get(key) };
      const index = values.length;
      seen.set(key, index); values.push(null);
      values[index] = walk(value, true);
      return { $v: index };
    }
    if (Array.isArray(value)) return value.map(item => walk(item));
    if (value && typeof value === "object") {
      const keys = Object.keys(value);
      if (keys.length >= 3) {
        const schema = JSON.stringify(keys);
        let index = schemas.get(schema);
        if (index === undefined) { index = columns.length; schemas.set(schema, index); columns.push(keys); }
        return { $r: [index, keys.map(name => walk(value[name]))] };
      }
      return Object.fromEntries(Object.entries(value).map(([name, item]) => [name, walk(item)]));
    }
    return value;
  };
  const result = walk(data);
  return JSON.stringify({
    _model_projection: {
      schema: "foundry.model-result.v2", lossless: fullResult, full_result: fullResult,
      raw_sha256: createHash("sha256").update(raw).digest("hex"), raw_chars: raw.length,
      omitted_paths: omitted,
      instruction: "Decode result before use: {$r:[n,items]} is an object pairing columns[n] with items; {$v:n} is the exact recursively decoded values[n]. Other arrays/objects retain their normal meaning. Numeric strings stay strings. Full raw stdout remains archived. Omitted detail is never evidence of success; obtain facts with prepare_explanation and provenance with drilldown_fact. For facts use reference_template and include their run IDs in top-level run_ids when saving.",
    }, columns, values, result,
  });
}

// Snapshot consistency only: the native delivery verifier still owns current
// request/session/save/operation/deadline authority. This view grants none.
function stoppedSave(data) {
  const c = data?.completion, op = data?.completion_operation, d = data?.delivery_contract;
  return c?.repair_allowed === false
    && ["complete", "needs_review", "awaiting_input", "timed_out", "cancelled", "failed"].includes(c.status)
    && typeof data.final_response === "string" && data.final_response.length > 0
    && [data.id, data.task_id, data.requirements_id, data.content_hash, c.id, op?.id, op?.session_id]
      .every(value => typeof value === "string" && value.length > 0)
    && c.draft_id === data.id && c.task_id === data.task_id && c.requirements_id === data.requirements_id
    && c.draft_content_hash === data.content_hash && d?.draft_id === data.id && d.receipt_id === c.id
    && d.completion_status === c.status && op.status === c.status && op.task_id === data.task_id
    && op.id === data.completion_operation_id && op.current_revision === data.completion_operation_revision
    && Number.isInteger(op.current_revision) && Number.isFinite(Date.parse(op.deadline_at));
}

// Like the stopped view, this only describes one consistent returned snapshot.
// It cannot authorize a tool, extend a deadline or make an old run current.
function repairSave(data) {
  const c = data?.completion, op = data?.completion_operation, d = data?.delivery_contract;
  return c?.status === "repair_available" && c.repair_allowed === true
    && c.original_requirements_completed === false
    && [data.id, data.task_id, data.requirements_id, data.content_hash, c.id, op?.id, op?.session_id,
      data.quality?.requirements?.requirements_id].every(value => typeof value === "string" && value.length > 0)
    && c.draft_id === data.id && c.task_id === data.task_id && c.requirements_id === data.requirements_id
    && c.draft_content_hash === data.content_hash && d?.draft_id === data.id && d.receipt_id === c.id
    && d.completion_status === c.status && op.status === c.status && op.task_id === data.task_id
    && op.id === data.completion_operation_id && op.current_revision === data.completion_operation_revision
    && Number.isInteger(op.current_revision) && op.current_revision > 0
    && Number.isFinite(Date.parse(op.deadline_at))
    && Number.isInteger(c.repair_attempts) && Number.isInteger(c.max_repairs)
    && c.repair_attempts >= 0 && c.repair_attempts < c.max_repairs && op.policy?.max_repairs === c.max_repairs;
}

function saveReceiptResult(data, raw, terminal = false, repair = false) {
  if (data.id && data.quality?.status_dimensions
      && data.completion && Array.isArray(data.run_ids)) {
    const omitted = [];
    const drop = (object, key, path) => {
      if (object && typeof object === "object" && Object.hasOwn(object, key)) {
        delete object[key]; omitted.push(path);
      }
    };
    // This is a receipt/repair view, explicitly not a copy of the saved document.
    // All current issues, statuses, requirement items and completion state remain.
    for (const key of ["body", "body_template", "claims"]) drop(data, key, `/${key}`);
    for (const key of ["quality", "explanation_check"]) {
      for (const detail of ["facts", "evidence_groups", "evidence_labels"])
        drop(data[key], detail, `/${key}/${detail}`);
      drop(data[key]?.requirements?.support, "supported_metrics", `/${key}/requirements/support/supported_metrics`);
    }
    if (Array.isArray(data.completion_operation?.revisions))
      data.completion_operation.revisions.forEach((revision, index) =>
        drop(revision, "payload", `/completion_operation/revisions/${index}/payload`));
    const decorate = (text) => {
      if (!terminal && !repair) return text;
      const packet = JSON.parse(text);
      if (repair) {
        const c = data.completion;
        packet[META].next_action = {
          kind: "repair_current_draft", parent_id: data.id, receipt_id: c.id,
          saved_requirements_id: data.requirements_id,
          requirements_id: data.quality.requirements.requirements_id, saved_run_ids: data.run_ids,
          operation_id: data.completion_operation_id, operation_revision: data.completion_operation_revision,
          repair_budget: { used: c.repair_attempts, limit: c.max_repairs, remaining: c.max_repairs - c.repair_attempts },
          deadline_at: data.completion_operation.deadline_at,
          instruction: "Read completion.actions and decoded quality.requirements for this failed save. Preserve every original requirement and source binding; correct valid requirements before diagnostics or calculation. Follow support.preflight and items[].execution_specs using an actual context_id covering all required_bindings, including public_facts. Never invent context_id or rename an account metric. Rerun only runs identified as incompatible with current requirements; saved_run_ids are history, not proof of current coverage. Complete requested available drilldown_fact checks. Call prepare_explanation for the intended current run_ids, then save its short template with the same run_ids, this parent_id and current requirements_id. Do not reattach an outdated diagnostic run. Recheck the new receipt; a successful repair tool alone is not delivery. Missing inputs stay unanswered. This snapshot grants no authority or additional time; native request, deadline and repair limits still apply.",
        };
        const directed = JSON.stringify(packet);
        return bytes(directed) <= MODEL_INLINE_BYTES ? directed : null;
      }
      packet[META].instruction = "Decode result before use: {$r:[n,items]} pairs columns[n] with items; {$v:n} is the exact recursively decoded values[n]. Numeric strings stay strings. Full raw stdout remains archived. This stopped-save view omits only the listed document/provenance echoes; omitted detail is never evidence of success. All returned current diagnostics, requirement gaps, qualifications and completion limits remain in result. Follow next_action for the current reply; no further tools are authorized by this projection.";
      packet[META].next_action = { kind: "final_response_only", text: data.final_response,
        instruction: "Reply now with this exact final_response as plain text. Do not call todo_write, goal, answer_cards, skills or any other tool after this stopped save. Bookkeeping and requested available drilldowns belong before the final save. This is a returned snapshot, not renewed authority; original requirements and review limits remain exactly as recorded." };
      const directed = JSON.stringify(packet);
      return bytes(directed) <= MODEL_INLINE_BYTES ? directed : null;
    };
    const receipt = tabularResult(data, raw, false, omitted, 32);
    if (bytes(receipt) <= MODEL_INLINE_BYTES) {
      // Plain fields duplicate this response only; the encoded result and raw
      // evidence retain all requirements, source detail and current authority.
      if (!Object.hasOwn(data, "receipt")
          && [data.id, data.task_id, data.requirements_id, data.content_hash,
            data.completion.id, data.completion.status, data.quality.status]
            .every(value => typeof value === "string" && value.length > 0)
          && data.run_ids.length > 0 && data.run_ids.every(value => typeof value === "string" && value.length > 0)
          && typeof data.quality.status_dimensions === "object" && !Array.isArray(data.quality.status_dimensions)
          && Object.hasOwn(data.quality, "claim_semantics_version")
          && typeof data.final_response === "string" && data.delivery_contract
          && typeof data.delivery_contract === "object" && !Array.isArray(data.delivery_contract)
          && Array.isArray(data.quality.issues) && Array.isArray(data.quality.readability?.issues)) {
        const packet = JSON.parse(receipt);
        packet.receipt = Object.fromEntries(["id", "task_id", "requirements_id", "run_ids", "content_hash"]
          .map(key => [key, data[key]]));
        packet.receipt.quality = Object.fromEntries(["status", "issues", "readability", "status_dimensions",
          "claim_semantics_version"].map(key => [key, data.quality[key]]));
        for (const key of ["completion", "final_response", "delivery_contract"]) packet.receipt[key] = data[key];
        packet[META].readable_receipt = { kind: "convenience_duplicate", source: "decoded result",
          instruction: "receipt exactly duplicates fields of this returned result for readability; it adds no authority, currentness, qualification or approval. Decode result for all requirements, source detail and operation history. Original omissions still apply." };
        const readable = JSON.stringify(packet);
        if (bytes(readable) <= MODEL_INLINE_BYTES) {
          const directed = decorate(readable);
          if (directed !== null) return directed;
        }
      }
      return decorate(receipt);
    }
  }
  return null;
}

/** Keep model text below the runtime spill limit without cutting a JSON document. */
export function workflowModelResult(tool, raw) {
  const first = compactModelResult(raw);
  // A stopped operation has no further repair work. Show its exact reply and
  // current diagnostics before the large document/provenance echo, even when
  // the lossless projection would fit below the runtime spill threshold.
  if (tool === "save_explanation_draft" && typeof raw === "string") {
    try {
      const data = parseExact(raw);
      if (!reserved(data) && stoppedSave(data)) {
        const receipt = saveReceiptResult(data, raw, true);
        if (receipt !== null && bytes(receipt) < bytes(first)) return receipt;
      } else if (!reserved(data) && repairSave(data)) {
        const receipt = saveReceiptResult(data, raw, false, true);
        // A small consistent failed save still needs recovery direction; the
        // inline bound, not a size-saving requirement, controls this view.
        if (receipt !== null) return receipt;
      }
    } catch { /* Keep unsafe numbers and malformed/reserved results on the original path. */ }
  }
  if (typeof first !== "string" || bytes(first) <= MODEL_INLINE_BYTES) return first;
  try {
    const data = parseExact(raw);
    if (!data || typeof data !== "object" || Array.isArray(data) || reserved(data))
      throw new Error("unsupported large result");
    const full = tabularResult(data, raw);
    if (bytes(full) <= MODEL_INLINE_BYTES) return full;
    // Reuse shorter repeated identities before falling back to an incomplete view.
    // This is the same lossless schema; every fact, failure and qualification stays.
    const dense = tabularResult(data, raw, true, [], 32);
    if (bytes(dense) <= MODEL_INLINE_BYTES) return dense;
    if (tool === "save_explanation_draft") {
      const receipt = saveReceiptResult(data, raw);
      if (receipt !== null) return receipt;
    }
  } catch { /* Do not risk numeric conversion, reserved-key confusion or incomplete JSON. */ }
  return JSON.stringify({
    code: "FOUNDRY_MODEL_RESULT_TOO_LARGE", tool, model_view_complete: false,
    raw_sha256: createHash("sha256").update(raw).digest("hex"), raw_bytes: bytes(raw),
    message: "The tool result is archived but cannot be delivered completely within the model view budget. This is not evidence that the tool failed or that the task completed. Do not infer any omitted amount, qualification or receipt. Request a narrower result; use drilldown_fact for one known fact, or read persisted state before retrying a save.",
  });
}
