"""Short native drafts and source-bound aging audit metadata.

These are authoring aids. The ordinary requirement, source, amount-eligibility
and save checks remain the authority for completion. No caller proof is read.
"""
from __future__ import annotations

from copy import deepcopy
from contextvars import ContextVar
from decimal import localcontext

from foundry.analysis import _hash
from foundry.errors import FoundryError

BRIDGE_COLUMNS = {
    "quantity_then_price": ("actual", "baseline", "total_variance", "quantity_contribution",
                            "price_contribution", "interaction", "residual"),
    "base_weights_with_interaction": ("actual", "baseline", "total_variance", "quantity_contribution",
                                      "price_contribution", "interaction", "residual"),
    "volume_mix_price": ("actual", "baseline", "total_variance", "volume_contribution",
                         "mix_contribution", "price_contribution", "residual"),
}
_LABELS = {"actual": "实际金额", "baseline": "基准金额", "total_variance": "总差异",
           "quantity_contribution": "数量贡献", "volume_contribution": "总量贡献",
           "mix_contribution": "结构贡献", "price_contribution": "价格贡献",
           "interaction": "交互贡献", "residual": "闭合余差"}
_DEFAULT_BUCKETS = [{"name": "0-30", "min": 0, "max": 30},
                    {"name": "31-60", "min": 31, "max": 60},
                    {"name": "61-90", "min": 61, "max": 90},
                    {"name": "90+", "min": 91, "max": None}]
_CHECKING_REQUIREMENTS = ContextVar("native_draft_checking_requirements", default=False)


class _AgingAuditMetadata(dict):
    """In-process provenance marker; JSON round trips deliberately lose it.

    Only the resolver below creates this after reading authorized persisted
    sources. The seal detects edits within a prepared payload. Saved appendix
    verification resolves fresh metadata; a model-supplied JSON dict is never
    promoted by a matching hash, marker field or claimed status.
    """
    def __init__(self, payload):
        super().__init__(payload)
        self._seal = _hash(payload)


def _current_run(analysis, runs, allowed):
    from foundry.finance_controls import superseded_snapshots
    from foundry.finance_professional import artifact_rules_match, requirement_rule_identity
    from foundry.finance_requirements import latest_requirements, requirements_readable, _run_inputs_match_requirement
    from foundry.finance_service import FinanceStore, FINANCE_CALCULATION_VERSION

    if len(runs) != 1:
        raise FoundryError("native draft requires one current run")
    service = FinanceStore(analysis.task, snapshot_ids=allowed)
    run = service._named_run(runs[0]["id"])
    current = latest_requirements(analysis)
    if (run != runs[0] or run.get("task_id") != analysis.task.id or run.get("engine") != "finance"
            or run.get("execution_status") != "succeeded" or run.get("deterministic") is not True
            or run.get("calculation_version") != FINANCE_CALCULATION_VERSION
            or run.get("reproducibility_status") == "non_reproducible"
            or run.get("output_hash") != _hash(run.get("result"))
            or not current or not requirements_readable(current, allowed)
            or current["id"] != run.get("requirements_id")):
        raise FoundryError("native draft run or requirements identity is not current")
    service._authorize_current(current)
    fingerprint = analysis.fingerprint_in_view(current, allowed)
    if not fingerprint or run.get("requirements_semantic_fingerprint") != fingerprint:
        raise FoundryError("native draft requirements fingerprint differs")
    identity = requirement_rule_identity(analysis, current, allowed=allowed)
    if identity and (identity.get("professional_status") != "supported"
                     or identity != (current.get("semantic_basis") or {}).get("professional_identity")
                     or not artifact_rules_match(run, identity)):
        raise FoundryError("native draft professional identity differs")
    context = service._read("contexts", run["finance_context_id"])
    revision = analysis.get_analysis(run["analysis_id"])
    service._authorize(revision["bindings"])
    if (context["bindings"] != run["bindings"] or revision["bindings"] != run["bindings"]
            or revision.get("finance_context_id") != context["id"]
            or run.get("finance_scope") != context.get("scopes")
            or run.get("code_hash") != _hash({"operation": revision["operation"],
                                              "spec": revision["finance_spec"], "context": context})
            or not _run_inputs_match_requirement(run, current)
            or set(run["bindings"].values()) & superseded_snapshots(
                analysis.task, analysis.published_datasets(), allowed=allowed)):
        raise FoundryError("native draft source context differs")
    datasets = {alias: analysis.read_dataset(key) for alias, key in run["bindings"].items()}
    if any(data["data_hash"] != run["input_hashes"].get(alias)
           or data["source_hash"] != run["source_hashes"].get(alias) for alias, data in datasets.items()):
        raise FoundryError("native draft source hashes differ")
    return service, run, current, context, revision, datasets


def prepare_aging_audit_metadata(analysis, runs, *, allowed=None):
    """Keep separate verified audit records for each distinct aging scope."""
    if len(runs) <= 1:
        return _prepare_single_aging_audit_metadata(analysis, runs, allowed=allowed)
    if len({run.get("id") for run in runs}) != len(runs):
        return None
    audits = [_prepare_single_aging_audit_metadata(analysis, [run], allowed=allowed) for run in runs]
    if any(audit is None for audit in audits):
        return None
    # A template may cover multiple currencies or cutoffs, but not silently
    # duplicate one same-scope calculation or mix requirements versions.
    if (len({audit["requirements_id"] for audit in audits}) != 1
            or len({_hash({"as_of": audit["as_of"], "scope": audit["scope"]})
                    for audit in audits}) != len(audits)):
        return None
    return _AgingAuditMetadata({"schema_version": 2, "authority": "source_bound_aging_audit_metadata",
        "counts_as_amount_evidence": False, "run_ids": [audit["run_id"] for audit in audits],
        "requirements_id": audits[0]["requirements_id"], "audits": [dict(audit) for audit in audits]})


def _prepare_single_aging_audit_metadata(analysis, runs, *, allowed=None):
    """Rebuild aging parameters and audit rows from persisted authorized sources.

    This proof contains no financial claims and confers no amount eligibility.
    In particular, detail amounts do not answer an aggregate obligation.
    """
    from foundry.finance_scenario_service import calculate_scenario, validate_receivables_aging_configuration

    # This verifier never prepares explanations or checks requirements itself.
    # It is also needed by a nested requirement check to resolve display labels;
    # the recursion guard remains on prepare_native_draft below.
    if len(runs) != 1:
        return None
    result = runs[0].get("result") or {}
    if (result.get("domain") != "foundry.finance.scenario_result.v1"
            or "open_amount" not in {column.get("name") if isinstance(column, dict) else column
                                     for column in result.get("columns", [])}):
        return None
    try:
        service, run, current, context, revision, datasets = _current_run(analysis, runs, allowed)
        scenario = service._read("scenarios", run["result"]["scenario_id"])
        if scenario.get("kind") != "receivables_aging":
            return None
        inputs = scenario["inputs"]
        if (revision["operation"] != "scenario" or revision["finance_spec"].get("scenario_id") != scenario["id"]
                or scenario["context_id"] != context["id"] or scenario["bindings"] != run["bindings"]
                or scenario["input_hash"] != _hash(inputs)
                or run["result"].get("input_hash") != scenario["input_hash"]):
            return None
        validate_receivables_aging_configuration(inputs)
        with localcontext() as decimal_context:
            decimal_context.prec = 80
            rebuilt = calculate_scenario(scenario, context, datasets)
        # The runner normalizes declared column types but not audit rows. Compare
        # every non-column result field, rather than just the desired bucket.
        comparable = {key: value for key, value in run["result"].items()
                      if key not in {"columns", "row_count", "truncated"}}
        if comparable != {key: value for key, value in rebuilt.items()
                          if key not in {"columns", "row_count", "truncated"}}:
            return None
        payload = {"schema_version": 1, "authority": "source_bound_aging_audit_metadata",
                   "counts_as_amount_evidence": False,
                   "run_id": run["id"], "output_hash": run["output_hash"],
                   "requirements_id": current["id"], "scenario_id": scenario["id"],
                   "scenario_input_hash": scenario["input_hash"],
                   "source_hashes": run["source_hashes"], "input_hashes": run["input_hashes"],
                   "as_of": inputs["as_of"], "scope": inputs.get("scope", {}),
                   "buckets": inputs.get("buckets") or _DEFAULT_BUCKETS,
                   "summary_rows": rebuilt["rows"], "detail_rows": rebuilt["detail_rows"],
                   "excluded_detail_rows": rebuilt["excluded_detail_rows"]}
        return _AgingAuditMetadata(deepcopy(payload))
    except (FoundryError, OSError, ValueError, KeyError, TypeError):
        return None


def verified_aging_audit_metadata(value):
    return (isinstance(value, _AgingAuditMetadata)
            and value.get("authority") == "source_bound_aging_audit_metadata"
            and value.get("counts_as_amount_evidence") is False
            and value._seal == _hash(dict(value)))


def _cell(value):
    return str(value if value is not None else "未提供").replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def render_aging_audit_appendix(value):
    """Render only freshly resolved in-process metadata, never JSON claims."""
    if not verified_aging_audit_metadata(value):
        return ""
    if value.get("schema_version") == 2:
        return "\n\n".join(_render_single_aging_audit_appendix(audit) for audit in value["audits"])
    return _render_single_aging_audit_appendix(value)


def _render_single_aging_audit_appendix(value):
    lines = ["### 账龄边界与逐发票审计明细", "",
             "以下参数与明细由已授权运行及归档来源重建；边界和天数为非金额元数据。"
             "逐发票金额只作同源审计明细，不替代可引用汇总事实，不新增确认依据或专业审批。",
             "截止日：" + _cell(value["as_of"]) + "。", "",
             "| 分桶 | 含首日 | 含末日 |", "| --- | --- | --- |"]
    for bucket in value["buckets"]:
        lines.append("| " + " | ".join((_cell(bucket["name"]), _cell(bucket["min"]),
                     "无上限" if bucket.get("max") is None else _cell(bucket["max"]))) + " |")
    lines.extend(["", "| 账套 | 组织 | 币种 | 单位 | 分桶 | 汇总余额 |", "| --- | --- | --- | --- | --- | --- |"])
    for row in value["summary_rows"]:
        lines.append("| " + " | ".join(_cell(row.get('bucket_label', row.get(key)) if key == 'bucket' else row.get(key)) for key in
                     ("ledger", "organization", "currency", "unit", "bucket", "open_amount")) + " |")
    for label, key in (("纳入的发票", "detail_rows"), ("排除的发票", "excluded_detail_rows")):
        lines.extend(["", label + "：", "",
                      "| 发票 | 到期日 | 逾期天数 | 分桶 | 未清金额 | 币种 | 单位 | 排除原因 |",
                      "| --- | --- | --- | --- | --- | --- | --- | --- |"])
        for row in value[key]:
            lines.append("| " + " | ".join(_cell(row.get('bucket_label', row.get(field)) if field == 'bucket' else row.get(field)) for field in
                         ("invoice_id", "due_date", "overdue_days", "bucket", "open_amount",
                          "currency", "unit", "exclusion_reason")) + " |")
    return "\n".join(lines)


def prepare_native_draft(analysis, runs, prepared, *, allowed=None):
    """Offer a short draft only after the complete original obligations pass."""
    from foundry.finance_explanations import _facts_for_run, _evidence_groups_for_run, _body_numbers
    from foundry.finance_requirements import check_requirements

    denied = {"draft_template": None, "diagnostics": []}
    # The existing requirement evaluator prepares evidence itself. Its nested
    # preparation must return facts, rather than recursively suggest a draft.
    if _CHECKING_REQUIREMENTS.get() or not runs:
        return denied
    if len(runs) > 1:
        return _prepare_multi_aging_draft(analysis, runs, prepared, allowed=allowed)
    result = runs[0].get("result") or {}
    method = result.get("method")
    is_bridge = result.get("domain") == "foundry.finance.variance.v1" and method in BRIDGE_COLUMNS
    is_aging = result.get("domain") == "foundry.finance.scenario_result.v1" and "open_amount" in {
        column.get("name") if isinstance(column, dict) else column for column in result.get("columns", [])}
    if not is_bridge and not is_aging:
        return denied

    def refuse(code, message):
        return {"draft_template": None, "diagnostics": [{"code": code, "severity": "warning", "message": message}]}

    try:
        _, run, current, _, _, _ = _current_run(analysis, runs, allowed)
        facts = _facts_for_run(run, prepared.get("materiality", {}), analysis=analysis)
        groups = _evidence_groups_for_run(run, facts)
        if prepared.get("facts") != facts or prepared.get("evidence_groups") != groups:
            return refuse("native_prepared_identity_differs", "准备事实与当前来源绑定结果不一致。")
        columns = BRIDGE_COLUMNS[method] if is_bridge else ("open_amount",)
        selected = [fact for fact in facts if fact["column"] in columns]
        if (not selected or len(selected) != len(run["result"]["rows"]) * len(columns)
                or any(fact.get("evidence_eligibility", {}).get("counts_as_amount_evidence") is not True
                       for fact in selected)
                or (is_bridge and any(group.get("group_type") != "price_quantity_bridge"
                                      or group.get("status") != "complete"
                                      or group.get("closure", {}).get("status") != "passed" for group in groups))):
            return refuse("native_facts_unqualified", "原生结果缺少完整合格事实或闭合，不能提供模板。")
        guard = _CHECKING_REQUIREMENTS.set(True)
        try:
            checked = check_requirements(analysis, {"requirements_id": current["id"], "run_ids": [run["id"]],
                "claims": [fact["reference_template"]["claim"] for fact in selected]}, _allowed=allowed)
        finally:
            _CHECKING_REQUIREMENTS.reset(guard)
        if (checked["coverage"]["status"] != "pass" or checked["provenance"]["status"] != "pass"
                or checked["original_requirements_completed"] is not True):
            return refuse("native_requirements_pending", "完整原要求或指定来源下钻尚未满足；模板不能代为完成。")
        rows = run["result"]["rows"]
        scope = []
        for key in ("ledger", "organization", "period", "currency", "unit"):
            values = [row.get(key) for row in rows]
            if any(value != values[0] for value in values):
                return refuse("native_scope_mixed", "模板只支持范围一致的原生结果。")
            if values[0] is not None:
                scope.append(_cell(values[0]))
        lines = ["## 量价差异草稿" if is_bridge else "## 应收账龄草稿", "", "口径：" + "；".join(scope) + "。"]
        if _body_numbers("；".join(scope)):
            return refuse("native_scope_label_citation_unsupported", "范围标签包含尚无合法引用的数值。")
        if is_bridge:
            # Do not place uncited identifier digits or formula inputs in prose.
            lines.extend(["", "| 对象 | 指标 | 金额 |", "| --- | --- | --- |"])
            for fact in selected:
                row = rows[fact["row"]]
                label = _cell(row.get("product", "可比篮子"))
                if _body_numbers(label):
                    return refuse("native_scope_label_citation_unsupported", "对象标签包含尚无合法引用的数值。")
                lines.append("| " + " | ".join((label, _LABELS[fact["column"]],
                             fact["reference_template"]["body_token"])) + " |")
            lines.extend(["", "算术贡献不证明业务因果。"])
        else:
            audit = prepared.get("aging_audit_metadata")
            if not verified_aging_audit_metadata(audit) or audit.get("run_id") != run["id"]:
                return refuse("native_aging_boundary_citation_unsupported", "账龄边界及逐发票数字尚无完整合法引用；保留原要求，不能省略。")
            lines.extend(["", "账龄分组金额、截止口径、边界及发票明细见附录。"])
        lines.extend(["", "限当前来源及已确认方法边界，仍需专业复核；不作为审定或过账授权。"])
        return {"draft_template": {"title": "量价差异与来源限制" if is_bridge else "应收账龄与边界核验",
                "body": "\n".join(lines), "run_ids": [run["id"]], "requirements_id": current["id"],
                "claims": [], "fact_ids": []}, "diagnostics": []}
    except (FoundryError, OSError, ValueError, KeyError, TypeError):
        return refuse("native_current_identity_unverified", "当前授权、来源快照或要求身份未核实，不能提供模板。")


def _prepare_multi_aging_draft(analysis, runs, prepared, *, allowed=None):
    """Compose independent aging scopes without merging their financial amounts."""
    from foundry.finance_explanations import _facts_for_run, _evidence_groups_for_run
    from foundry.finance_requirements import check_requirements

    denied = {"draft_template": None, "diagnostics": []}
    audit = prepared.get("aging_audit_metadata")
    if (not verified_aging_audit_metadata(audit) or audit.get("schema_version") != 2
            or audit.get("run_ids") != [run.get("id") for run in runs]):
        return denied
    try:
        current_runs = [_current_run(analysis, [run], allowed) for run in runs]
        current = current_runs[0][2]
        if any(entry[2]["id"] != current["id"] for entry in current_runs):
            return denied
        facts, groups = [], []
        for _, run, _, _, _, _ in current_runs:
            run_facts = _facts_for_run(run, prepared.get("materiality", {}), analysis=analysis)
            facts.extend(run_facts)
            groups.extend(_evidence_groups_for_run(run, run_facts))
        if facts != prepared.get("facts") or groups != prepared.get("evidence_groups"):
            return denied
        selected = [fact for fact in facts if fact["column"] == "open_amount"]
        if (not selected or len(selected) != sum(len(run["result"]["rows"]) for run in runs)
                or any(fact.get("evidence_eligibility", {}).get("counts_as_amount_evidence") is not True
                       for fact in selected)):
            return denied
        run_ids = [run["id"] for run in runs]
        guard = _CHECKING_REQUIREMENTS.set(True)
        try:
            checked = check_requirements(analysis, {"requirements_id": current["id"], "run_ids": run_ids,
                "claims": [fact["reference_template"]["claim"] for fact in selected]}, _allowed=allowed)
        finally:
            _CHECKING_REQUIREMENTS.reset(guard)
        if (checked["coverage"]["status"] != "pass" or checked["provenance"]["status"] != "pass"
                or checked["original_requirements_completed"] is not True):
            return {"draft_template": None, "diagnostics": [{"code": "native_requirements_pending",
                "severity": "warning", "message": "完整原要求或指定来源下钻尚未满足；模板不能代为完成。"}]}
        return {"draft_template": {"title": "应收账龄与边界核验",
            "body": ("## 应收账龄草稿\n\n各运行按各自账套、组织、币种及截止口径分别列示，金额不跨币种合并。\n\n"
                     "账龄分组金额、截止口径、边界及发票明细见附录。\n\n"
                     "限当前来源及已确认方法边界，仍需专业复核；不作为审定或过账授权。"),
            "requirements_id": current["id"], "run_ids": run_ids, "claims": [], "fact_ids": []},
                "diagnostics": []}
    except (FoundryError, OSError, ValueError, KeyError, TypeError):
        return denied
