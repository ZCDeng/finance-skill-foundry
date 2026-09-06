/* global Office, Excel */

const SETTINGS_WORKBOOK_ID = "foundryWorkbookId";

const state = {
  token: sessionStorage.getItem("foundryBridgeToken") || "",
  workbookId: "",
  context: null,
  preview: null,
  host: {},
  selectedBindingId: "",
  selectedRunId: "",
  previewGeneration: 0,
};

const $ = (id) => document.getElementById(id);

function setStatus(message, kind = "") {
  const node = $("status");
  node.textContent = message;
  node.className = `status${kind ? ` ${kind}` : ""}`;
}

function log(message, detail) {
  const suffix = detail === undefined ? "" : ` ${JSON.stringify(detail, null, 2)}`;
  $("log").textContent = `${new Date().toISOString()} ${message}${suffix}\n${$("log").textContent}`.slice(0, 16000);
}

function clearPreview(message = "") {
  state.preview = null;
  state.previewGeneration += 1;
  $("preview").replaceChildren();
  $("applyOutput").disabled = true;
  if (message) setStatus(message);
}

function safeId(text, fallback = "foundry") {
  const cleaned = String(text || fallback).trim().replace(/[^A-Za-z0-9_.-]/g, "_");
  return cleaned || fallback;
}

function safeAlias(text, fallback = "actual") {
  let cleaned = String(text || fallback).trim().replace(/[^A-Za-z0-9_]/g, "_");
  if (!/^[A-Za-z_]/.test(cleaned)) cleaned = fallback;
  return cleaned.slice(0, 64) || fallback;
}

function parseJson(id) {
  try {
    return JSON.parse($(id).value || "{}");
  } catch (error) {
    throw new Error(`${id} 不是有效 JSON: ${error.message}`);
  }
}

function splitCsv(text) {
  return String(text || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function hostInfo(readyInfo) {
  const requirements = Office.context.requirements;
  return {
    host: (readyInfo && readyInfo.host) || Office.context.host || "Excel",
    platform: (readyInfo && readyInfo.platform) || Office.context.platform || "unknown",
    version: (Office.context.diagnostics || {}).version || "",
    excelApi11: requirements.isSetSupported("ExcelApi", "1.1"),
    excelApi111: requirements.isSetSupported("ExcelApi", "1.11"),
  };
}

async function rememberWorkbookId() {
  const settings = Office.context.document.settings;
  let id = settings.get(SETTINGS_WORKBOOK_ID);
  if (!id) {
    const bytes = new Uint32Array(2);
    if (globalThis.crypto && globalThis.crypto.getRandomValues) globalThis.crypto.getRandomValues(bytes);
    id = `foundry_wb_${Date.now()}_${Array.from(bytes).map((n) => n.toString(16)).join("")}`;
    settings.set(SETTINGS_WORKBOOK_ID, id);
    await new Promise((resolve, reject) => {
      settings.saveAsync((result) => (
        result.status === Office.AsyncResultStatus.Succeeded ? resolve() : reject(result.error)
      ));
    });
  }
  state.workbookId = id;
  return id;
}

async function api(path, payload, method = "POST") {
  const response = await fetch(path, {
    method,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${state.token}`,
    },
    body: method === "GET" ? undefined : JSON.stringify({ workbook_id: state.workbookId, ...(payload || {}) }),
  });
  const data = await response.json();
  if (!response.ok || data.error) throw new Error((data.error && data.error.message) || response.statusText);
  return data;
}

async function telemetry(event, details = {}) {
  if (!state.token || !state.workbookId) return;
  try {
    await api("/api/telemetry", { event, host: state.host, details });
  } catch (error) {
    log("遥测记录未保存", { event, message: error.message || String(error) });
  }
}

function currentWorkbook() {
  const books = (state.context && state.context.workbooks) || [];
  return books.find((book) => book.id === state.workbookId) || { bindings: {}, previews: {} };
}

function bindings() {
  return Object.values(currentWorkbook().bindings || {});
}

function selectedBindingId() {
  const id = $("bindingList").value || state.selectedBindingId;
  if (!id) throw new Error("请先选择绑定区域");
  state.selectedBindingId = id;
  return id;
}

function bindingOption(binding) {
  const option = document.createElement("option");
  option.value = binding.id;
  const role = binding.role === "input" ? "输入区" : "输出区";
  option.textContent = `${role} · ${binding.name} · ${binding.address}`;
  return option;
}

function chooseSelectValue(select, options, preferredValue, emptyText) {
  select.replaceChildren(...options);
  if (!options.length) {
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = emptyText;
    placeholder.disabled = true;
    placeholder.selected = true;
    select.append(placeholder);
    return "";
  }
  const values = new Set(options.map((option) => option.value));
  const chosen = values.has(preferredValue) ? preferredValue : options[0].value;
  select.value = chosen;
  return chosen;
}

function renderContext() {
  const list = bindings().sort((a, b) => a.id.localeCompare(b.id));
  state.selectedBindingId = chooseSelectValue(
    $("bindingList"),
    list.map(bindingOption),
    state.selectedBindingId || $("bindingList").value,
    "尚未绑定 Excel 选区",
  );
  const runs = ((((state.context || {}).finance || {}).runs) || []).filter((run) => run.engine === "finance");
  state.selectedRunId = chooseSelectValue(
    $("runList"),
    runs.map((run) => {
      const option = document.createElement("option");
      option.value = run.id;
      const count = ((run.result || {}).rows || []).length;
      option.textContent = `${run.operation === "metric" ? "指标结果" : "财务结果"} · ${count} 行`;
      option.title = "技术标识已收在运行日志中";
      return option;
    }),
    state.selectedRunId || $("runList").value,
    "暂无财务运行结果",
  );
  $("workbookId").textContent = state.workbookId || "尚未注册";
}

async function registerWorkbook() {
  await api("/api/register-workbook", {
    name: Office.context.document.url ? Office.context.document.url.split(/[\\/]/).pop() : "",
    url: Office.context.document.url || "",
    host: state.host,
  });
  await telemetry("workbook_registered", { workbook_id: state.workbookId });
}

async function refreshContext() {
  state.context = await api("/api/context", {}, "GET");
  renderContext();
  await telemetry("context_refreshed", {
    snapshots: state.context.snapshot_ids.length,
    bindings: bindings().length,
    runs: ((state.context.finance || {}).runs || []).length,
  });
  log("上下文已刷新", { snapshots: state.context.snapshot_ids.length, bindings: bindings().length });
}

function managementFieldCatalog() {
  return [
    { name: "management_account", policy: "text" },
    { name: "amount", policy: "amount", unit: $("scopeUnit").value || "yuan" },
    { name: "organization", policy: "text" },
    { name: "period", policy: "text" },
    { name: "currency", policy: "text" },
    { name: "unit", policy: "text" },
    { name: "scenario", policy: "text" },
  ];
}

function visibleFields() {
  const kind = $("fieldPreset").value;
  if (kind === "advanced") return parseJson("fieldsJson");
  if (kind === "management") return managementFieldCatalog();
  return [
    { name: "amount", policy: "amount", unit: $("scopeUnit").value || "yuan" },
    { name: "comment", policy: "text" },
  ];
}

function fieldsForHeaders(fields, headers) {
  const cleanedHeaders = headers.map((header) => String(header || "").trim()).filter(Boolean);
  if ($("fieldPreset").value === "output") {
    return cleanedHeaders.map((name) => ({
      name: safeAlias(name, "amount"),
      policy: /comment|note|说明|备注/i.test(name) ? "text" : "amount",
      unit: $("scopeUnit").value || "yuan",
    }));
  }
  if ($("fieldPreset").value !== "management") return fields;
  const seen = new Set(cleanedHeaders.map((header) => header.toLowerCase()));
  const matched = fields.filter((field) => seen.has(field.name.toLowerCase()));
  const required = ["management_account", "amount"];
  for (const name of required) {
    if (!matched.some((field) => field.name === name)) throw new Error(`管理数据选区缺少表头：${name}`);
  }
  return matched;
}

function scopePayload() {
  return {
    ledger: $("scopeLedger").value.trim(),
    organization: $("scopeOrg").value.trim(),
    period: $("scopePeriod").value.trim(),
    currency: $("scopeCurrency").value.trim() || "CNY",
    unit: $("scopeUnit").value.trim() || "yuan",
    scenario: $("scopeScenario").value.trim() || "actual",
  };
}

function headersFromValues(values, fields) {
  if (values.length && Array.isArray(values[0])) return values[0].map((value) => String(value || "").trim());
  return fields.map((field) => field.name);
}

function addressAt(baseAddress, rowOffset, colOffset) {
  const cellRef = baseAddress.split("!").pop().split(":")[0].replace(/\$/g, "");
  const [, letters, rowText] = /^([A-Z]+)([0-9]+)$/i.exec(cellRef);
  let col = 0;
  for (const ch of letters.toUpperCase()) col = col * 26 + ch.charCodeAt(0) - 64;
  const toLetters = (number) => {
    let out = "";
    while (number) {
      const mod = (number - 1) % 26;
      out = String.fromCharCode(65 + mod) + out;
      number = Math.floor((number - mod) / 26);
    }
    return out;
  };
  return `${toLetters(col + colOffset)}${Number(rowText) + rowOffset}`;
}

function cellColumn(address) {
  return address.match(/[A-Z]+/i)[0].toUpperCase().split("").reduce((acc, ch) => acc * 26 + ch.charCodeAt(0) - 64, 0);
}

function cellRow(address) {
  return Number(address.match(/[0-9]+/)[0]);
}

function cellsFromRange(range) {
  const cells = {};
  for (let r = 0; r < range.values.length; r += 1) {
    for (let c = 0; c < range.values[r].length; c += 1) {
      const address = addressAt(range.address, r, c);
      cells[address] = {
        address,
        value: range.values[r][c],
        valueType: (range.valueTypes[r] || [])[c] || "unknown",
        numberFormat: (range.numberFormat[r] || [])[c] || "",
        formula: (range.formulas[r] || [])[c] || "",
      };
    }
  }
  return cells;
}

async function rangeForBinding(bindingId) {
  if (!state.host.excelApi11) throw new Error("此 Excel 宿主需要支持 ExcelApi 1.1 才能读取绑定区域");
  return Excel.run(async (context) => {
    const binding = context.workbook.bindings.getItem(bindingId);
    const range = binding.getRange();
    range.load(["address", "values", "formulas", "rowCount", "columnCount", "numberFormat", "valueTypes"]);
    const sheet = range.worksheet;
    sheet.load("name");
    await context.sync();
    return {
      worksheet: sheet.name,
      address: range.address,
      values: range.values,
      formulas: range.formulas,
      numberFormat: range.numberFormat,
      valueTypes: range.valueTypes,
      rowCount: range.rowCount,
      columnCount: range.columnCount,
    };
  });
}

async function bindSelection() {
  const requestedFields = visibleFields();
  const name = $("bindingName").value.trim() || `foundry_${Date.now()}`;
  const role = $("role").value;
  const id = `foundry_${role}_${safeId(name)}_${Date.now()}`;
  await new Promise((resolve, reject) => {
    Office.context.document.bindings.addFromSelectionAsync(
      Office.BindingType.Matrix,
      { id },
      (result) => (result.status === Office.AsyncResultStatus.Succeeded ? resolve(result.value) : reject(result.error)),
    );
  });
  const range = await rangeForBinding(id);
  const headers = headersFromValues(range.values, requestedFields);
  const fields = fieldsForHeaders(requestedFields, headers);
  const binding = {
    id,
    name,
    role,
    writable: role === "output",
    dedicated_area: role === "output",
    binding_type: "matrix",
    worksheet: range.worksheet,
    address: range.address,
    headers,
    fields,
    header: true,
    baseline_cells: cellsFromRange(range),
  };
  await api("/api/register-bindings", { bindings: [binding] });
  state.selectedBindingId = id;
  clearPreview();
  await refreshContext();
  setStatus(`已绑定当前选区：${binding.name}（${binding.address}）`, "ok");
  await telemetry("binding_registered", { binding_id: id, role, address: range.address });
  log("绑定已登记", { id, role, address: range.address });
}

async function importBinding() {
  const bindingId = selectedBindingId();
  const binding = bindings().find((item) => item.id === bindingId);
  if (!binding || binding.role !== "input") throw new Error("请选择输入区域");
  const range = await rangeForBinding(bindingId);
  const result = await api("/api/import-binding", {
    binding_id: bindingId,
    values: range.values,
    alias: safeAlias($("bindingAlias").value || binding.name || binding.id),
    scope: scopePayload(),
    policy: { source_binding: binding.id, source: "officejs-binding" },
  });
  clearPreview();
  await refreshContext();
  setStatus(`已导入输入快照：${binding.name || binding.id}`, "ok");
  await telemetry("input_imported", { dataset_id: result.dataset.id, binding_id: bindingId, context_id: result.finance_context.id });
  log("输入快照已导入", { dataset: result.dataset.id, context: result.finance_context.id });
}

function updateMetricControls() {
  const simple = $("metricMode").value === "simple";
  const accountTotal = $("metricKind").value === "account_total";
  $("metricAccountsWrap").hidden = !simple || !accountTotal;
}

function metricSpec() {
  if ($("metricMode").value === "advanced") return parseJson("metricJson");
  const spec = {
    metric: {
      kind: $("metricKind").value,
      dimensions: splitCsv($("metricDimensions").value),
    },
  };
  if (spec.metric.kind === "account_total") {
    spec.metric.accounts = splitCsv($("metricAccounts").value);
  }
  return spec;
}

async function runMetric() {
  clearPreview();
  const result = await api("/api/run-metric", { spec: metricSpec() });
  state.selectedRunId = result.run.id;
  await refreshContext();
  setStatus("指标已运行，结果已可预览写入。", "ok");
  await telemetry("metric_run", { run_id: result.run.id, output_hash: result.run.output_hash });
  log("指标已运行", { run: result.run.id, output_hash: result.run.output_hash });
}

async function previewOutput() {
  clearPreview();
  const generation = state.previewGeneration;
  const bindingId = selectedBindingId();
  const binding = bindings().find((item) => item.id === bindingId);
  if (!binding || binding.role !== "output") throw new Error("请选择输出区域");
  const runId = $("runList").value;
  const run = (((state.context || {}).finance || {}).runs || []).find((item) => item.id === runId);
  if (!run) throw new Error("请选择一条财务运行结果");
  const range = await rangeForBinding(bindingId);
  const row = ((run.result || {}).rows || [])[0] || {};
  const missing = binding.fields.filter((field) => !Object.prototype.hasOwnProperty.call(row, field.name)).map((field) => field.name);
  if (missing.length) throw new Error(`运行结果缺少输出列：${missing.join(", ")}`);
  const writes = binding.fields.map((field, index) => ({
    address: addressAt(range.address, 1, index),
    field: field.name,
    value: row[field.name],
  }));
  const preview = (await api("/api/preview-output", {
    binding_id: bindingId,
    writes,
    current_cells: cellsFromRange(range),
    output_hash: run.output_hash,
  })).preview;
  if (generation !== state.previewGeneration) {
    log("已忽略过期写入预览", { preview: preview.id });
    return;
  }
  state.preview = preview;
  renderPreview();
  setStatus(state.preview.conflicts.length ? `写入预览已生成：${state.preview.conflicts.length} 个冲突需选择。` : "写入预览已生成，可以应用选中单元格。", "ok");
  await telemetry("output_previewed", { preview_id: state.preview.id, conflicts: state.preview.conflicts.length });
  log("写入预览已生成", { conflicts: state.preview.conflicts.length });
}

function renderPreview() {
  if (!state.preview) {
    $("preview").replaceChildren();
    $("applyOutput").disabled = true;
    return;
  }
  $("applyOutput").disabled = false;
  $("preview").replaceChildren(
    ...state.preview.cells.map((cell) => {
      const row = document.createElement("label");
      row.className = `cell${cell.conflict ? " conflict" : ""}`;
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = !cell.conflict;
      checkbox.dataset.address = cell.address;
      const value = document.createElement("span");
      value.textContent = `${cell.address} ${cell.field}: ${cell.old_value ?? ""} → ${cell.new_value ?? ""}`;
      const tag = document.createElement("strong");
      tag.textContent = cell.conflict ? "冲突" : "待写入";
      row.append(checkbox, value, tag);
      return row;
    }),
  );
}

async function applyOutput() {
  if (!state.preview) throw new Error("请先预览写入结果");
  const resolutions = {};
  const selectedAddresses = [];
  for (const item of $("preview").querySelectorAll("input[type=checkbox]")) {
    const cell = state.preview.cells.find((candidate) => candidate.address === item.dataset.address);
    if (!cell) continue;
    if (item.checked) selectedAddresses.push(cell.address);
    if (cell.conflict) resolutions[cell.address] = item.checked ? "apply" : "keep";
  }
  const range = await rangeForBinding(state.preview.binding_id);
  const result = await api("/api/apply-output", {
    binding_id: state.preview.binding_id,
    preview_id: state.preview.id,
    current_cells: cellsFromRange(range),
    selected_addresses: selectedAddresses,
    resolutions,
  });
  const ackCells = await Excel.run(async (context) => {
    const binding = context.workbook.bindings.getItem(result.binding.id);
    const bound = binding.getRange();
    bound.load(["address", "rowCount", "columnCount"]);
    await context.sync();
    const start = bound.address.split("!").pop().split(":")[0].replace(/\$/g, "");
    const startRow = cellRow(start);
    const startCol = cellColumn(start);
    const targets = [];
    for (const cell of result.applied) {
      const r = cellRow(cell.address) - startRow;
      const c = cellColumn(cell.address) - startCol;
      if (r < 0 || c < 0 || r >= bound.rowCount || c >= bound.columnCount) throw new Error(`本地桥返回了绑定区域外单元格: ${cell.address}`);
      const target = bound.getCell(r, c);
      target.numberFormat = [[cell.number_format || "General"]];
      target.values = [[cell.value]];
      targets.push({ source: cell, target });
    }
    await context.sync();
    for (const item of targets) {
      item.target.load(["values", "formulas", "numberFormat", "valueTypes"]);
    }
    await context.sync();
    return targets.map((item) => ({
      address: item.source.address,
      value: item.target.values[0][0],
      valueType: (item.target.valueTypes[0] || [])[0] || "unknown",
      numberFormat: (item.target.numberFormat[0] || [])[0] || "",
      formula: (item.target.formulas[0] || [])[0] || "",
    }));
  });
  await api("/api/ack-output", {
    binding_id: result.binding.id,
    preview_id: result.preview_id,
    cells: ackCells,
  });
  setStatus(`已应用 ${result.applied.length} 个单元格，保留 ${result.kept.length} 个。`, "ok");
  clearPreview();
  await telemetry("output_applied", { preview_id: result.preview_id, applied: result.applied.length, kept: result.kept.length });
  log("已应用选中单元格", { applied: result.applied.length, kept: result.kept.length });
}

async function recalculate() {
  await Excel.run(async (context) => {
    context.application.calculate(Excel.CalculationType.full);
    await context.sync();
  });
  setStatus("已请求 Excel 全量重算。", "ok");
  await telemetry("full_recalc", {});
  log("已请求全量重算");
}

async function saveWorkbook() {
  if (!state.host.excelApi111) throw new Error("保存工作簿需要当前 Excel 宿主支持 ExcelApi 1.11");
  await Excel.run(async (context) => {
    context.workbook.save(Excel.SaveBehavior.save);
    await context.sync();
  });
  setStatus("已请求保存工作簿。", "ok");
  await telemetry("workbook_saved", {});
  log("已请求保存工作簿");
}

async function guard(action) {
  try {
    await action();
  } catch (error) {
    const message = error.message || String(error);
    setStatus(message, "error");
    log("错误", { message });
  }
}

Office.onReady((info) => {
  state.host = hostInfo(info);
  $("host").textContent = `${state.host.host} ${state.host.version} · 绑定读取 ${state.host.excelApi11 ? "可用" : "不可用"} · 保存 ${state.host.excelApi111 ? "可用" : "不可用"}`;
  $("token").value = state.token;
  $("fieldPreset").onchange = () => { $("advancedFields").hidden = $("fieldPreset").value !== "advanced"; };
  $("metricKind").onchange = updateMetricControls;
  $("metricMode").onchange = () => { $("advancedMetric").hidden = $("metricMode").value !== "advanced"; updateMetricControls(); };
  updateMetricControls();
  $("saveToken").onclick = () => guard(async () => {
    state.token = $("token").value.trim();
    sessionStorage.setItem("foundryBridgeToken", state.token);
    await rememberWorkbookId();
    await registerWorkbook();
    await refreshContext();
    setStatus("已连接本地桥，工作簿已注册。", "ok");
  });
  $("refreshContext").onclick = () => guard(async () => { await refreshContext(); setStatus("上下文已刷新。", "ok"); });
  $("bindingList").onchange = () => { state.selectedBindingId = $("bindingList").value; clearPreview("绑定区域已切换，请重新预览写入。"); };
  $("runList").onchange = () => { state.selectedRunId = $("runList").value; clearPreview("运行结果已切换，请重新预览写入。"); };
  clearPreview();
  $("bindSelection").onclick = () => guard(bindSelection);
  $("importBinding").onclick = () => guard(importBinding);
  $("runMetric").onclick = () => guard(runMetric);
  $("previewOutput").onclick = () => guard(previewOutput);
  $("applyOutput").onclick = () => guard(applyOutput);
  $("recalculate").onclick = () => guard(recalculate);
  $("saveWorkbook").onclick = () => guard(saveWorkbook);
  guard(async () => {
    await rememberWorkbookId();
    if (state.token) {
      await registerWorkbook();
      await refreshContext();
    }
  });
});
