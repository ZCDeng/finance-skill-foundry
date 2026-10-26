"""Deterministic explanation facts and draft checks for finance analysis."""

from __future__ import annotations

import re
import hashlib
from datetime import date
from calendar import monthrange
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from typing import Any

from foundry.analysis import BASIS, _hash, _safe_text
from foundry.analysis_data import json_value
from foundry.errors import FoundryError
from foundry.result_semantics import FRACTION_UNITS, PERCENT_UNITS, POINT_UNITS

FACT_TOKEN = re.compile(r"\{\{fact:([0-9a-f]{64})\}\}")
NUMBER = re.compile(r"(?<![A-Za-z0-9_.])[-+−－]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?[%％]?(?![A-Za-z0-9_.])")
CLOSURE_EXPR = re.compile(r"(?P<expr>[-+]?\d+(?:\.\d+)?(?:\s*[+\-−]\s*\d+(?:\.\d+)?)+\s*=\s*[-+]?\d+(?:\.\d+)?)")
_LABELED_CLOSURE_TERM = (
    r"(?P<label{index}>收入|成本|费用|利润)[^\S\r\n]*"
    r"(?P<value{index}>[-+−－]?[^\S\r\n]*\d+(?:\.\d+)?)[^\S\r\n]*"
    r"(?P<unit{index}>[A-Za-z\u4e00-\u9fff%％/]+)"
)
LABELED_PROFIT_CLOSURE_EXPR = re.compile(
    r"(?P<expr>利润(?:影响|贡献)合计[^\S\r\n]*[=＝][^\S\r\n]*"
    + r"[^\S\r\n]*[+＋][^\S\r\n]*".join(_LABELED_CLOSURE_TERM.format(index=i) for i in range(3))
    + r"[^\S\r\n]*[=＝][^\S\r\n]*" + _LABELED_CLOSURE_TERM.format(index=3) + r")"
)
DATE_SPAN = re.compile(r"\b\d{4}[-/年]\d{1,2}(?:[-/月]\d{1,2})?")
PERIOD_RANGE = re.compile(
    r"(?<![\d.,])\d+[ \u00a0\u2009\u202f\u3000]*[-–—~至到][ \u00a0\u2009\u202f\u3000]*\d+[ \u00a0\u2009\u202f\u3000]*[年月日]"
)
FACT_ID = re.compile(r"^[0-9a-f]{64}$")
PERIOD_OR_DATE = re.compile(r"^\d{4}-\d{2}(?:-\d{2})?$")
# A bare year, yyyymm or yyyymmdd written as a row's period.
PERIOD_IDENTIFIER = re.compile(r"(?:19|20)\d{2}(?:(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])?)?")
EVIDENCE_APPENDIX_RENDER_VERSION = 3
# A difference of two percentages and how its value reads (_points_display).
POINTS_UNIT = "百分点"
POINTS_SUFFIX = " 个百分点"
WRITING_GUIDANCE = {
    "schema_version": 1,
    "summary": (
        "管理层财务文稿应先给短结论，再用比较表或条列承接驱动；"
        "完整公式独立成段，来源定位用章节末附注。"
    ),
    "rules": [
        "每段只写一个主题，开头用一到两个短段说明结论和重大财务影响。",
        "把金额的 {{fact:FACT_ID}} 保留在对应金额、公式或表格位置；它是数值占位符，不是引用编号。",
        "多个驱动、条件或不确定性使用条列或比较表，条件贴近相关判断。",
        "完整公式、桥接计算和口径说明独立成段或小表，不塞进长句。",
        "来源定位使用章节末附注 [^n]；不得补造原因、行动、空值或未授权来源。",
        "全年数不用本年累计按已过月数线性外推（×12÷月数）：物业等行业的减值和亏损集中在年底，线性外推会高估全年利润。写全年时用按去年节奏的估计（本年累计 ÷ 上年同期占全年比重）或经理的 LE，并写明是估算。",
        "数字照三条写：手写的金额和数量加千分位（325,644.00 万元）；金额行用 {{fact:FACT_ID}} 占位符并原样保留，不因渲染出的小数位或缺千分位改成手写；比率行和 %、pct、「百分比」行不用占位符，正文手写百分数，对应 claim 写全 basis=calculation、run_id、row、column、value、fact_id 和 presentation（decimal_places，rounding 为 half_up；比率行 scale 用 percent，%、pct、「百分比」行 scale 用 identity），由服务复核；其他手写的舍入数同样带 presentation（scale 用 identity）；手写数等于事实原值或展示值时不需要 presentation；负值直接写负号（-6.85%）。",
        "结果行里「比率」或 ratio 是小数，正文写成百分数（94.53%）；单位为 %、pct 或「百分比」的行本身已是百分数，正文写展示值加 %（3.30%），不乘 100；单位为「百分点」的差值行写「3.30 个百分点」。不写「比率以小数表示」这类格式说明。正文、运行说明和假设里不写内部字段名（metric_key、scenario、currency/unit），改写成指标、情景、币种和单位。",
    ],
}

MONEY_COLUMNS = {
    "amount",
    "signed_amount",
    "revenue",
    "cost",
    "expense",
    "profit",
    "source_total",
    "adjusted_total",
    "actual",
    "baseline",
    "contribution",
    "numerator",
    "denominator",
    "quantity_contribution",
    "volume_contribution",
    "mix_contribution",
    "price_contribution",
    "interaction",
    "total_variance",
    "residual",
}
RATIO_COLUMNS = {"ratio", "ratio_exact", "cost_rate_pct", "gross_margin_pct"}
MONEY_UNIT_SEGMENTS = {"万元", "元", "亿元", "千元", "百万元"}
MONEY_TOKENS = {
    "amount", "revenue", "cost", "expense", "profit", "cash",
    "budget", "actual", "variance", "sales", "income",
}
EXACT_VALUE_COLUMNS = {"numerator_exact", "denominator_exact", "ratio_exact"}
COUNT_COLUMNS = {"row_count"}
QUANTITY_COLUMNS = {"quantity", "actual_quantity", "baseline_quantity", "quantity_change"}
UNIT_PRICE_COLUMNS = {"price", "unit_price", "actual_price", "baseline_price", "price_change"}
META_COLUMNS = {
    "ledger",
    "organization",
    "period",
    "account_id",
    "account_code",
    "management_account",
    "scenario",
    "currency",
    "unit",
    "metric",
    "basis",
    "favorability",
    "comparison_status",
    "ratio_status",
    "display_value",
    "ratio_display",
    "numerator_display",
    "denominator_display",
    "quantity_unit",
    "price_unit",
}
METRIC_LABELS = {
    "revenue": "收入",
    "cost": "成本",
    "expense": "费用",
    "profit": "利润",
}
POSITIVE_WORDS = ("增加", "增长", "提升", "上升", "超", "高", "有利", "改善")
NEGATIVE_WORDS = ("减少", "下降", "降低", "少", "不利", "恶化")


def refresh_saved_explanation(service, spec):
    """Judge an editable saved draft as written, without regenerating its evidence.

    Authoring and managed save remain different operations: this path preserves
    the stored prose, claims and appendix, then records the current validation's
    completion decision. A missing check therefore cannot be repaired merely by
    asking for its receipt. Runtime saves still require their prepared/full spec
    and operation budget; transaction review refresh keeps its existing path.
    """
    if not isinstance(spec, dict) or set(spec) != {"draft_id"}:
        raise FoundryError("saved explanation refresh requires only draft_id")
    draft = service._named_draft(spec["draft_id"])
    service._authorize_draft(draft)
    from foundry.finance_transaction_reviews import has_transaction, refresh_draft

    if has_transaction(service.analysis, draft, allowed=service.allowed):
        return refresh_draft(service, spec)
    if service.session_id:
        raise FoundryError("runtime draft refresh requires a prepared template or full draft spec")
    from foundry.finance_completion import record_completion
    from foundry.analysis import _quality_status_dimensions
    from foundry.locking import exclusive

    with exclusive(service.analysis._inside(service.analysis.root / "completion.lock")):
        quality = service.validate_explanation({"draft_id": draft["id"]})
        # save_draft builds dimensions after issue locations and requirement
        # checks are attached. Use that same representation for this fresh
        # validation; never substitute the stored draft's earlier verdict.
        quality = {**quality, "status_dimensions": _quality_status_dimensions(
            execution_status=draft.get("execution_status", "not_run"),
            review_status=draft.get("review_status", "unreviewed"),
            quality_issues=quality["issues"],
            evidence_report=quality["evidence_report"],
            consistency_report=quality["consistency_report"],
            numeric_configured=bool(draft.get("run_ids") or draft.get("claims")),
        )}
        receipt = record_completion(service.analysis, draft, quality, allowed=service.allowed)
    return {**draft, "quality": quality, "explanation_check": quality,
            "completion": service._readable_receipt(receipt),
            "validation_basis": "current_saved_explanation"}


def _service_recognition_basis(analysis, runs, *, requirements_id=None, allowed=None):
    """Qualitative source facts never come from caller claims or SQL labels."""
    from foundry.finance_recognition_basis import recognition_basis_report
    from foundry.finance_requirements import latest_requirements, requirements_readable

    bindings = {f"{run['id']}:{alias}": dataset_id for run in runs
                for alias, dataset_id in (run.get("bindings") or {}).items()}
    records = []
    current = latest_requirements(analysis, allowed)
    # With no requirements, the manager's legacy validation ignores an unused
    # version id. Sessions still resolve explicit ids within their own ceiling.
    if requirements_id and (current is not None or allowed is not None):
        requirements = analysis._get("requirements", requirements_id)
        if requirements_readable(requirements, allowed):
            records.append(requirements)
    if current and all(current["id"] != record["id"] for record in records):
        records.append(current)
    for record in records:
        bindings.update({f"{record['id']}:{alias}": dataset_id
                         for alias, dataset_id in (record.get("bindings") or {}).items()})
    return recognition_basis_report(analysis, bindings, allowed=allowed)


def prepare_explanation(
    analysis,
    runs: list[dict],
    backgrounds: list[dict] | None = None,
    materiality: dict | None = None,
    *, _allowed: set[str] | None = None,
) -> dict:
    facts: list[dict] = []
    materiality = _materiality(materiality or {})
    diagnostics: list[dict] = []
    evidence_groups: list[dict] = []
    for run in runs:
        if run.get("execution_status") != "succeeded":
            raise FoundryError("explanation facts require a referenced successful run")
        diagnostics.extend(_run_diagnostics(run))
        run_facts = _facts_for_run(run, materiality, analysis=analysis)
        facts.extend(run_facts)
        evidence_groups.extend(_evidence_groups_for_run(run, run_facts))
    required = _required_fact_ids(facts)
    prepared = {
        "schema_version": 1,
        "task_id": analysis.task.id,
        "facts": facts,
        "evidence_groups": evidence_groups,
        "required_fact_ids": required,
        "diagnostics": diagnostics,
        "business_contexts": backgrounds or [],
        "materiality": materiality,
        "writing_guidance": WRITING_GUIDANCE,
        "structure_counts": _structure_counts(analysis, runs, facts, allowed=_allowed),
        "forecast_performance": _forecast_performance_sources(analysis, runs, allowed=_allowed),
    }
    recognition_basis = _service_recognition_basis(analysis, runs, allowed=_allowed)
    if recognition_basis["status"] != "not_applicable":
        prepared["recognition_basis"] = recognition_basis
    prepared["draft_template"] = _statement_draft_template(analysis, runs, prepared, allowed=_allowed)
    from foundry.finance_native_drafts import prepare_aging_audit_metadata, prepare_native_draft

    aging_audit = prepare_aging_audit_metadata(analysis, runs, allowed=_allowed)
    if aging_audit is not None:
        prepared["aging_audit_metadata"] = aging_audit
    native_template = False
    if prepared["draft_template"] is None:
        native = prepare_native_draft(analysis, runs, prepared, allowed=_allowed)
        prepared["draft_template"] = native["draft_template"]
        prepared["diagnostics"].extend(native["diagnostics"])
        native_template = prepared["draft_template"] is not None
    if prepared["draft_template"] is None:
        from foundry.finance_non_numeric_outcomes import prepare_undefined_draft

        prepared["draft_template"] = prepare_undefined_draft(analysis, runs, allowed=_allowed)
        native_template = prepared["draft_template"] is not None
    if prepared["draft_template"] is not None:
        prepared["save_template_spec"] = {
            "use_prepared_template": True,
            "run_ids": prepared["draft_template"]["run_ids"],
            "requirements_id": prepared["draft_template"]["requirements_id"],
            "qualitative_note": "",
        }
        # These registered monetary outputs need no generic percentage or
        # annual-estimation examples. Keep the complete facts and provenance.
        prepared["writing_guidance"] = {
            "schema_version": 1,
            "summary": "直接保存 save_template_spec；qualitative_note 仅补模板未表达的必要说明，通常一两句；不重复模板已有的期间、范围、边界数字、金额、公式或计数，无补充可留空串；必要的额外事实或金额仍须通过原有引用与 claim 校验。",
            "rules": [
                "不传 body/claims/fact_ids；服务保留范围与合格引用，完整校验。",
                "通过不等于差额为零。检查 readability 的措辞建议，必要时在既有预算内局部改句并另存修订；"
                "建议不改变财务通过。最终回复原样采用保存回执 final_response，不扩写正文内容。",
                "收入按履约假设确认，勿把收款写成其确认对象；未收价款形成余额，对已识别债权的收款属于清偿，须写明清偿对象。来源追踪另述。"
                "不能假定所有收款都先形成赊销应收；汇总数不能证明交易分配。"
                "按来源核对同一债权的余额、收款归属及其他调整，只有足额清偿且无余额才称结清；"
                "部分清偿须保留未结清余额，归属不明不判断结清。",
                "标题与正文的履约状态均按 forecast_performance 的同合同、预测期来源说明；预测内已履约不等于现实已发生。"
                "未知状态不推为待履约。修复只依据本次 quality.issues 的 code/text/position，不增造其他数字或原因。",
            ],
        }
        if native_template:
            prepared["writing_guidance"] = {
                "schema_version": 1,
                "summary": "直接保存 save_template_spec；qualitative_note 通常留空，仅补必要定性说明。",
                "rules": [
                    "不传 body/claims/fact_ids，不手抄数字或公式；额外数字仍须原有引用与校验。",
                    "模板不代完成原要求或指定下钻。量价贡献不证明业务因果，账龄边界及发票审计明细见来源附录。",
                    "保存时重新准备并完整校验。最终回复原样采用保存回执 final_response，不扩写正文内容。",
                ],
            }
    return prepared


def _forecast_performance_sources(analysis, runs, *, allowed=None):
    """Read typed forecast assumptions from the current run's archived sources.

    This is qualitative evidence only. It neither changes the native output nor
    proves actual performance, amount eligibility, or professional signoff.
    Shared runs follow the service's existing snapshot authorization boundary;
    no SDK current-request or caller-session attestation is claimed here.
    """
    import json
    from foundry.finance_controls import superseded_snapshots
    from foundry.finance_driver_templates import TEMPLATE_ID
    from foundry.finance_professional import cell_evidence_eligibility, requirement_rule_identity
    from foundry.finance_requirements import latest_requirements, requirements_readable
    from foundry.finance_service import FinanceStore

    denied = {"status": "unverifiable", "facts": [], "counts_as_amount_evidence": False}
    if len(runs) != 1:
        return denied
    try:
        run = analysis.get_run(runs[0]["id"])
        result = run.get("result") or {}
        current = latest_requirements(analysis)
        if (run.get("task_id") != analysis.task.id or run.get("engine") != "finance"
                or run.get("execution_status") != "succeeded" or run.get("output_hash") != _hash(result)
                or result.get("template_id") != TEMPLATE_ID or not current
                or current["id"] != run.get("requirements_id")
                or not requirements_readable(current, allowed)
                or run.get("requirements_semantic_fingerprint") != analysis.fingerprint_in_view(current, allowed)):
            return denied
        service = FinanceStore(analysis.task, snapshot_ids=allowed)
        service._authorize(run["bindings"])
        service._authorize_current(current)
        context = service._read("contexts", run["finance_context_id"])
        scenario = service._read("scenarios", result["scenario_id"])
        inputs = scenario["inputs"]
        period, scope = inputs.get("period"), inputs.get("scope") or {}
        if (not isinstance(period, str) or not re.fullmatch(r"\d{4}-\d{2}", period)
                or scenario.get("kind") != "driver_model" or inputs.get("template_id") != TEMPLATE_ID
                or scenario.get("context_id") != context["id"] or current.get("context_id") != context["id"]
                or context["bindings"] != run["bindings"] or current.get("bindings") != run["bindings"]
                or scenario.get("input_hash") != _hash(inputs) or result.get("input_hash") != scenario["input_hash"]):
            return denied
        date.fromisoformat(period + "-01")
        identity = requirement_rule_identity(analysis, current, allowed=allowed)
        if (not identity or identity.get("professional_status") != "supported"
                or identity.get("rule_fingerprint") != (run.get("requirements_rule_identity") or {}).get("rule_fingerprint")
                or set(run["bindings"].values()) & superseded_snapshots(
                    analysis.task, analysis.published_datasets(), allowed=None)):
            return denied
        row = next(row for row in result["rows"] if row.get("template_id") == TEMPLATE_ID and row.get("metric_key"))
        if not cell_evidence_eligibility(run, row, "value", analysis=analysis)["counts_as_amount_evidence"]:
            return denied
        datasets = {}
        for alias, key in run["bindings"].items():
            data = analysis.read_dataset(key)
            if (data["source_hash"] != run["source_hashes"][alias]
                    or data["data_hash"] != run["input_hashes"][alias]):
                return denied
            datasets[alias] = data
        facts = []
        for alias, data in datasets.items():
            for index, raw in enumerate(data.get("rows") or [], 1):
                if raw.get("record_type") != "transaction_allocation" or not isinstance(raw.get("public_record_json"), str):
                    continue
                record = json.loads(raw["public_record_json"])
                # This registered envelope defines the field's forecast meaning.
                # Case IDs, titles, aliases and arbitrary prose never select it.
                if (not isinstance(record, dict) or record.get("schema_version") != "finance-independent-three-statement-v1"
                        or not isinstance(record.get("scope"), dict)
                        or any(record["scope"].get(k) != v for k, v in scope.items())):
                    continue
                for role in ("base_current_service", "additional_sale"):
                    item = record.get(role)
                    # This envelope's optional null denotes no role record,
                    # never an unknown state, a no-sale fact or amount evidence.
                    if item is None and (role not in record or role == "additional_sale"):
                        continue
                    if not isinstance(item, dict) or not isinstance(item.get("contract_id"), str) or not item["contract_id"].strip():
                        return denied
                    state = item.get("performed_in_forecast")
                    fields = {"contract_id", "customer_id", "performance_period", "performed_in_forecast",
                              "revenue", "receipt", "receipts", "no_incremental_cost_basis"}
                    known = (type(state) is bool and item.get("performance_period") == period
                             and not set(item) - fields)
                    facts.append({"contract_id": item["contract_id"], "role": role,
                        "period": period, "state": "performed" if known and state is True else "pending" if known else "unknown",
                        "status": "verified" if known else "unverifiable",
                        "authority": "source_defined_forecast_assumption", "counts_as_amount_evidence": False,
                        "run_id": run["id"], "requirements_id": current["id"], "output_hash": run["output_hash"],
                        "scenario_id": scenario["id"], "context_id": context["id"], "scope": scope,
                        "source": {"dataset_id": data["id"], "row_index": index, "column": "public_record_json",
                            "json_pointer": "/" + role + "/performed_in_forecast", "source_hash": data["source_hash"],
                            "data_hash": data["data_hash"]}})
        for fact in facts:
            peers = [other for other in facts if other["contract_id"] == fact["contract_id"]]
            if len({(p["state"], p["status"]) for p in peers}) > 1:
                for peer in peers:
                    peer["status"] = "source_conflict"
        # A proof is a point-in-time read, never a lease on mutable authority.
        if (current != latest_requirements(analysis) or identity != requirement_rule_identity(analysis, current, allowed=allowed)
                or run != analysis.get_run(run["id"]) or context != service._read("contexts", context["id"])
                or scenario != service._read("scenarios", scenario["id"])
                or set(run["bindings"].values()) & superseded_snapshots(analysis.task, analysis.published_datasets(), allowed=None)):
            return denied
        for data in datasets.values():
            fresh = analysis.read_dataset(data["id"])
            if any(fresh[key] != data[key] for key in ("source_hash", "data_hash")):
                return denied
        return {"status": "verified" if facts and all(f["status"] == "verified" for f in facts) else "unverifiable",
                "facts": facts, "counts_as_amount_evidence": False}
    except (FoundryError, OSError, KeyError, TypeError, ValueError, StopIteration):
        return denied


def _statement_draft_template(analysis, runs: list[dict], prepared: dict, *, allowed=None) -> dict | None:
    """Suggest concise prose from current qualified outputs; save still validates it.

    This is ordinary editable draft input, not a completion verdict. Empty
    explicit reference arrays prevent a repair from inheriting obsolete claims;
    the existing save path derives exact claims from the retained body tokens.
    """
    counts = prepared.get("structure_counts", [])
    required = [item for item in counts if item.get("kind") == "required_metrics"]
    checks = [item for item in counts if item.get("kind") == "model_checks"]
    if (len(runs) != 1 or len(required) != 1 or len(checks) != 1
            or not required[0].get("source_bound") or checks[0].get("all_pass") is not True):
        return None
    run, proof = runs[0], required[0]
    from foundry.finance_requirements import latest_requirements, requirements_readable
    from foundry.finance_professional import requirement_rule_identity

    current = latest_requirements(analysis)
    if (not current or current.get("id") != proof.get("requirements_id")
            or not requirements_readable(current, allowed)):
        return None
    fingerprint = analysis.fingerprint_in_view(current, allowed)
    if (not fingerprint or run.get("requirements_semantic_fingerprint") != fingerprint
            or requirement_rule_identity(analysis, current, allowed=allowed)
            != (current.get("semantic_basis") or {}).get("professional_identity")):
        return None
    fact_ids = proof.get("fact_ids", [])
    facts = [fact for fact in prepared["facts"] if fact["id"] in fact_ids]
    if (len(facts) != len(fact_ids) or len({fact["id"] for fact in facts}) != len(facts)
            or any(fact.get("evidence_eligibility", {}).get("counts_as_amount_evidence") is not True
                   or fact.get("metric_identity", {}).get("metric_key") != fact.get("semantics", {}).get("metric")
                   or fact.get("metric_identity", {}).get("template_id") != proof["template_id"]
                   or fact.get("metric_identity", {}).get("scenario_id") != proof["scenario_id"]
                   for fact in facts)):
        return None
    # Keep scope and units next to values, without importing unqualified inputs,
    # formulas or assertions that every passing inequality has a zero difference.
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")

    scope_parts = []
    for key in ("organization", "ledger", "period", "scenario", "currency", "unit"):
        values = [fact["metric_identity"].get(key) for fact in facts]
        if any(value != values[0] for value in values):
            return None
        if values[0] is not None:
            scope_parts.append(cell(values[0]))
    lines = ["## 管理预测结果", "", "口径：" + "；".join(scope_parts) + "。",
             "流量为期间数，存量为期末数。",
             "本模型按收入与收款滚动应收；收入确认依履约假设，对已识别债权的收款属于清偿。"
             "汇总数本身不能证明具体交易分配。同一债权须有来源证明足额清偿且无余额才称结清；"
             "部分清偿仍有未结清债权。", "",
             "| 指标 | 金额 |", "| --- | --- |"]
    by_id = {fact["id"]: fact for fact in facts}
    for fact_id in fact_ids:
        fact = by_id[fact_id]
        identity = fact["metric_identity"]
        lines.append("| " + " | ".join((cell(identity["metric_key"]),
                     fact["reference_template"]["body_token"])) + " |")
    lines.extend(["", checks[0]["body_template"] + "。全部通过。",
                  "限当前来源及已确认模型边界，仍需专业复核；不作为审定或过账授权。"])
    return {"title": "管理预测结果与核查", "body": "\n".join(lines),
            "run_ids": [run["id"]], "requirements_id": current["id"], "claims": [], "fact_ids": []}


def _structure_counts(analysis, runs: list[dict], facts: list[dict], *, allowed=None) -> list[dict]:
    """Counts describe one actual native result, never amounts or caller-supplied summaries.

    Multiple runs have no implicit combined count. A requirement count also needs
    the run's persisted requirement and a distinct fact for each exact metric.
    These observations do not change any fact's evidence eligibility.
    """
    if len(runs) != 1:
        return []
    run = runs[0]
    if run.get("engine") != "finance":
        return []
    if allowed is not None and not set((run.get("bindings") or {}).values()) <= set(allowed):
        return []
    from foundry.finance_requirements import requirements_readable

    # The run's own sources can be readable while its captured requirement also
    # binds private sources. Authorize that original record before exposing any
    # requirement metadata; a visible predecessor is not its count authority.
    requirement = None
    if run.get("requirements_id"):
        try:
            record = analysis._get("requirements", run["requirements_id"])
            if record.get("id") == run["requirements_id"] and requirements_readable(record, allowed):
                requirement = record
        except FoundryError:
            pass
    if allowed is not None:
        run = analysis.run_in_view(run, allowed)
    result = run.get("result") or {}
    if (run.get("engine") != "finance" or run.get("execution_status") != "succeeded"
            or not result.get("template_id") or not result.get("scenario_id")
            or run.get("output_hash") != _hash(result)):
        return []
    binding = {"run_id": run["id"], "output_hash": run["output_hash"],
               "requirements_id": requirement["id"] if requirement and requirement["id"] == run.get("requirements_id") else None,
               "template_id": result["template_id"], "scenario_id": result["scenario_id"]}
    counts = []
    checks = result.get("model_checks")
    if (isinstance(checks, list) and checks
            and all(isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]
                    and item.get("status") in {"pass", "fail"} for item in checks)
            and len({item["id"] for item in checks}) == len(checks)):
        counts.append({**binding, "kind": "model_checks", "count": len(checks),
                       "member_ids": [item["id"] for item in checks],
                       "all_pass": all(item["status"] == "pass" for item in checks),
                       "body_template": f"{len(checks)} 项 model_checks 核查结果"})
    if requirement is None or binding["requirements_id"] is None:
        return counts
    items = requirement.get("items")
    if (requirement.get("id") != run["requirements_id"] or not isinstance(items, list) or not items
            or not all(isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]
                       and isinstance(item.get("metric"), str) and item["metric"] for item in items)):
        return counts
    # A semantic pin can constrain the requirement's metric, not rename it.
    # Otherwise an unanswered unknown metric could borrow a known output's count.
    metrics = [item["metric"] for item in items]
    if (len(set(metrics)) != len(items) or len({item["id"] for item in items}) != len(items)
            or any("metric_key" in item.get("dimensions", {})
                   and item["dimensions"]["metric_key"] != item["metric"] for item in items)
            or any(item.get("dimensions", {}).get(key) != binding[key]
                   for item in items for key in ("template_id", "scenario_id"))):
        return counts
    selected = [fact for fact in facts if fact.get("run_id") == run["id"] and fact.get("column") == "value"
                and fact.get("semantics", {}).get("metric") in metrics]
    if (len(selected) != len(metrics)
            or {fact["semantics"]["metric"] for fact in selected} != set(metrics)):
        return counts
    from foundry.finance_requirements import (
        _dimensions_match, _requested_grains, _requirement_scope_matches, _row_grain,
    )

    rows = result.get("rows")
    if not isinstance(rows, list):
        return counts
    scopes = run.get("finance_scope") or {}
    scenarios = [scope.get("scenario") if isinstance(scope, dict) else None
                 for scope in scopes.values()] if isinstance(scopes, dict) else []
    uniform_scenario = (scenarios[0] if scenarios and all(
        isinstance(value, str) and value and value == scenarios[0] for value in scenarios) else None)
    by_metric = {fact["semantics"]["metric"]: fact for fact in selected}
    for item in items:
        fact = by_metric[item["metric"]]
        index = fact.get("row")
        if type(index) is not int or not 0 <= index < len(rows) or not isinstance(rows[index], dict):
            return counts
        row = rows[index]
        # Native template rows can omit scenario; their captured source scopes
        # provide it only when every scope declares the same explicit identity.
        # This local view never mutates the result or qualifies an amount.
        if row.get("scenario") in (None, "") and uniform_scenario is not None:
            row = {**row, "scenario": uniform_scenario}
        elif row.get("scenario") not in (None, "") and any(
                value not in (None, "", row["scenario"]) for value in scenarios):
            return counts
        grains = _requested_grains(item)
        # As at the native single-model entry, the shared comparison matcher
        # needs an explicit flat scenario check (it otherwise ignores that key).
        scenario = (requirement.get("scope") or {}).get("scenario")
        if (row.get("metric_key") != item["metric"] or not _dimensions_match(item, row, run)
                or not _requirement_scope_matches(run, row, item, requirement)
                or (scenario is not None and scenario != row.get("scenario"))
                or (grains is not None and {_row_grain(item, run, row)} != set(grains))):
            return counts
    counts.append({**binding, "kind": "required_metrics", "count": len(items),
                   "member_ids": [item["id"] for item in items], "metrics": metrics,
                   "fact_ids": [fact["id"] for fact in selected],
                   "source_bound": result.get("source_binding_status", {}).get("all_sources_verified") is True,
                   "body_template": f"{len(items)} 项 required_metrics 结果"})
    input_count = _source_bound_input_count(run, binding, counts)
    if input_count is not None:
        counts.append(input_count)
    return counts


def _source_bound_input_count(run: dict, binding: dict, counts: list[dict]) -> dict | None:
    """Count verified template inputs, without qualifying their financial values."""
    from foundry.finance_driver_templates import TEMPLATE_ID, TEMPLATE_INPUTS, TEMPLATE_VERSION, previous_month

    result = run["result"]
    required = [proof for proof in counts if proof["kind"] == "required_metrics"]
    checks = [proof for proof in counts if proof["kind"] == "model_checks"]
    if (result.get("template_id") != TEMPLATE_ID or result.get("template_version") != TEMPLATE_VERSION
            or len(required) != 1 or required[0].get("source_bound") is not True
            or len(checks) != 1 or checks[0].get("all_pass") is not True
            or result.get("model_checks") != result.get("driver_model", {}).get("model_checks")):
        return None
    if any(not isinstance(row, dict) for row in result["rows"]):
        return None
    output_rows = [row for row in result["rows"] if row.get("metric_key") in required[0]["metrics"]]
    output_scope = {}
    for key in ("period", "organization", "currency", "unit"):
        values = [row.get(key) for row in output_rows]
        if not values or any(not isinstance(value, str) or not value or value != values[0] for value in values):
            return None
        output_scope[key] = values[0]
    rows = [row for row in result["rows"] if row.get("source") == "input"]
    if (len(rows) != len(TEMPLATE_INPUTS) or any(not isinstance(row.get("driver"), str) for row in rows)
            or {row["driver"] for row in rows} != set(TEMPLATE_INPUTS)):
        return None
    source_state = result.get("source_binding_status") or {}
    proofs, drivers = source_state.get("bindings"), source_state.get("drivers")
    if not isinstance(proofs, dict) or not isinstance(drivers, dict):
        return None
    scopes, datasets = run.get("finance_scope") or {}, run.get("bindings") or {}
    used_datasets = set()
    for row in rows:
        name = row["driver"]
        proof, driver = proofs.get(name), drivers.get(name)
        if (not isinstance(proof, dict) or not isinstance(driver, dict)
                or row.get("check_status") != "pass" or row.get("value") != proof.get("value")
                or any(row.get(key) != value for key, value in output_scope.items())
                or any(part.get("status") != "source_verified" for part in (row, proof, driver))
                or any(part.get("source_binding_ids") != [name] or part.get("assumption_ids")
                       or part.get("unverified_inputs") for part in (row, driver))):
            return None
        refs = proof.get("source_rows")
        if (not isinstance(refs, list) or not refs
                or any(not isinstance(ref, dict) or not isinstance(ref.get("dataset_id"), str)
                       or type(ref.get("row_index")) is not int or ref["row_index"] < 0
                       or not isinstance(ref.get("column"), str) or not ref["column"] for ref in refs)
                or len({_hash(ref) for ref in refs}) != len(refs)
                or any(sorted(part.get("source_rows") or [], key=_hash) != sorted(refs, key=_hash)
                       for part in (row, driver))):
            return None
        try:
            expected_period = previous_month(row["period"]) if name.startswith("opening_") else row["period"]
        except (KeyError, FoundryError):
            return None
        if proof.get("period") != expected_period:
            return None
        for ref in refs:
            aliases = [alias for alias, dataset_id in datasets.items() if dataset_id == ref["dataset_id"]]
            if not aliases:
                return None
            for alias in aliases:
                scope = scopes.get(alias)
                if (not isinstance(scope, dict)
                        or any(not scope.get(key) or proof.get(key) != scope[key]
                               for key in ("organization", "currency", "unit", "scenario"))
                        or proof.get("ledger") != scope.get("ledger")
                        or any(row.get(key) != scope[key] for key in ("organization", "currency", "unit"))):
                    return None
            used_datasets.add(ref["dataset_id"])
    return {**binding, "kind": "source_bound_inputs", "count": len(rows),
            "member_ids": [row["driver"] for row in rows], "source_bound": True,
            "source_dataset_ids": sorted(used_datasets), "counts_as_amount_evidence": False,
            "body_template": f"{len(rows)} 项来源绑定输入有效"}


def _structure_count_spans(body: str, prepared: dict, requirements_id: str | None) -> tuple[list, list]:
    """Validate a small count grammar and exempt only its integer token.

    Unsupported wording and mismatched counts are issues even when that integer
    happens to equal a cited financial amount. Surrounding numbers are untouched.
    """
    number = r"[-+−－]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?[%％]?"
    kinds = r"required_metrics|model_checks|来源绑定输入|模型(?:联动)?(?:核查|检查)|需求|必答指标|指标|核查|检查"
    reverse = re.compile(r"(?P<kind>" + kinds + r")\s*(?P<opening>[（(])\s*(?P<count>" + number + r")\s*项")
    forward = re.compile(r"(?<![A-Za-z0-9_.+%％−－-])(?P<count>" + number
                         + r")\s*项\s*(?:(?P<kind>" + kinds + r")(?![A-Za-z_]))?")
    matches = [(match, True) for match in reverse.finditer(body)]
    covered = [match.span("count") for match, _ in matches]
    matches.extend((match, False) for match in forward.finditer(body) if match.span("count") not in covered)
    spans, issues = [], []
    for match, reversed_order in sorted(matches, key=lambda item: item[0].start("count")):
        tail = body[match.end():]
        implicit = match["kind"] is None
        if implicit and not re.match(r"(?:全部|均)?通过|(?:全部为|均返回)\s*pass", tail):
            continue  # Unknown collections, including inputs/boundaries, gain no exemption.
        kind = ("source_bound_inputs" if match["kind"] == "来源绑定输入" else
                "required_metrics" if match["kind"] in {"required_metrics", "需求", "必答指标", "指标"} else "model_checks")
        proofs = [item for item in prepared.get("structure_counts", []) if item.get("kind") == kind]
        proof = proofs[0] if len(proofs) == 1 else None
        # Count statements start a clause/title. '现金为12项模型检查' is not a count statement.
        prefix = re.split(r"[\n。！？；，]", body[:match.start()])[-1].strip()
        if not prefix.startswith("#"):
            prefix = prefix.rsplit("、", 1)[-1].strip()
        wrapper = next((mark for mark in ("**", "__", "`") if prefix.endswith(mark)), "")
        if wrapper:
            prefix = prefix[:-len(wrapper)].rstrip()
        closing = {"(": ")", "（": "）"}.get(match["opening"]) if reversed_order else None
        if not reversed_order and re.fullmatch(r"#{1,6}\s+[^\n。！？]*结果[（(]", prefix):
            closing = {"(": ")", "（": "）"}[prefix[-1]]
            prefix = ""
        if reversed_order:
            prefix = re.sub(r"^(#{1,6})\s*[一二三四五六七八九十]+、\s*", r"\1", prefix)
        valid = (prefix in {"", "以下", "共", "合计", "全部"} or re.fullmatch(r"#{1,6}", prefix)
                 or re.fullmatch(r"#{1,6}[ \t]+[A-Za-z\u4e00-\u9fff][A-Za-z\u4e00-\u9fff _-]*(?:与|及|和| and)", prefix)
                 or re.fullmatch(r"[^：:\n]*(?:需求|模型|核查|检查)[^：:\n]*[：:]", prefix))
        if kind == "source_bound_inputs":
            valid = bool((valid or re.fullmatch(r"仅限已确认的(?:[一二三四五六七八九十]+项零边界与)?", prefix))
                         and proof and proof.get("source_bound") is True
                         and proof.get("counts_as_amount_evidence") is False)
        if match["kind"] == "指标":
            # Generic metrics need an explicit heading or a bounded completion label.
            valid = bool(re.fullmatch(r"#{1,6}", prefix) or (
                prefix in {"", "以下", "共", "合计", "全部"}
                and re.match(r"\s*全部(?:取得结果|得出)", tail)))
        if match["kind"] in {"指标", "必答指标"}:
            valid = bool(valid and proof and proof.get("source_bound") is True)
        if implicit:
            # A bare "N 项通过" only belongs to an immediately preceding check heading.
            prior_lines = body[:body.rfind("\n", 0, match.start())].rstrip().splitlines() if "\n" in body[:match.start()] else []
            heading = prior_lines[-1].strip() if prior_lines else ""
            valid = valid and bool(re.fullmatch(
                r"(?:#{1,6}\s+|\*\*)(?:\d+\s*项\s*)?(?:model_checks|模型(?:联动)?(?:检查|核查))(?:\s*核查结果)?(?:\*\*)?", heading))
        valid = bool(valid and proof and re.fullmatch(r"[1-9]\d*", match["count"])
                     and int(match["count"]) == proof["count"]
                     and (requirements_id is None or proof.get("requirements_id") == requirements_id))
        valid = valid and _structure_count_tail(tail, proof, kind, closing, wrapper)
        if valid:
            spans.append(match.span("count"))
        else:
            issues.append({"code": "unverified_structure_count", "severity": "warning",
                           "message": "结构计数或其状态描述未与当前运行及需求逐项核对；金额仍须单独引用。",
                           "text": match["count"], "position": match.start("count"), "kind": kind})
    return spans, issues


def _structure_count_tail(tail: str, proof: dict, kind: str, closing: str | None, wrapper: str) -> bool:
    """Only count/status labels and bounded caption metadata; never financial claims."""
    titles = (["有效", ""] if kind == "source_bound_inputs" else
              ["结果", ""] if kind == "required_metrics" else ["核查结果", "核查", "结果", ""])
    states = []
    if kind == "model_checks" and proof.get("all_pass") is True:
        states = ["均通过不替代经理认可", "全部通过", "均通过", "通过", "全部为 pass", "均返回 pass",
                  "均来自同一运行（run_id " + proof["run_id"] + "）的 model_checks 数组，状态全部为 pass"]
    computed = []
    if kind == "required_metrics" and proof.get("source_bound") is True:
        computed = ["全部由 finance 引擎模型验证输出回答", "全部由已登记三表模板原生计算得出",
                    "全部由来源绑定模板算得", "全部有引擎输出且来源可追溯", "全部取得结果", "全部得出"] + [
            "全部由来源绑定的已登记管理三表模板（" + proof["template_id"] + "，" + label + " "
            + proof["scenario_id"] + "）计算得出" for label in ("场景", "情景")]
    if closing:
        tail = re.sub(r"^\s*[，,]\s*", "", tail)
    for label in states + computed + titles:
        match = re.match(r"[ \t]*" + re.escape(label), tail)
        if not match:
            continue
        rest = tail[match.end():]
        status = label in states
        if status:
            rest = re.sub(r"^[ \t]*(?:\((?:status=)?pass\)|（(?:status=)?pass）)", "", rest)
            # A bounded non-implication qualifies the pass statement, not its count
            # or any numeric difference. The same all-pass proof is still required.
            rest = re.sub(r"^[ \t]*(?:不等于|不表示|不代表|不意味着)(?:所有|全部|各(?:项)?|每(?:项)?)"
                          r"(?:检查|核查)?(?:的)?(?:差额|差异)(?:一定|必然)?(?:全部|均|都)?为(?:零|0(?![\d.]))", "", rest)
        if closing:
            if not rest.lstrip().startswith(closing):
                continue
            rest = rest.lstrip()[1:]
        if wrapper:
            if not rest.lstrip().startswith(wrapper):
                continue
            rest = rest.lstrip()[len(wrapper):]
        if label in titles:
            # Units/periods label a result table; only the count's integer is exempt.
            rest = re.sub(r"^[ \t]*[（(]单位[：:]\s*(?:人民币元|万元|千元|亿元|元|美元|CNY|USD)"
                          r"(?:[，,]\s*\d{4}-\d{2}\s*(?:整期|期间))?[）)]", "", rest)
            if kind == "model_checks" and re.match(r"^\s*[：:，,]", rest):
                # A result label followed by approval must still pass the same status gate.
                continuation = re.sub(r"^\s*[：:，,]\s*", "", rest)
                if any(continuation.startswith(state) for state in states):
                    if _structure_count_tail(continuation, proof, kind, None, ""):
                        return True
                continue
        boundary = r"^[ \t]*(?=$|[\n。！？；，：、])" if status or label in computed else r"^[ \t]*(?=$|[\n。！？；])"
        if re.match(boundary, rest):
            return True
    return False


def _table_ordinal_spans(body: str) -> list[tuple[int, int]]:
    """Recognize only complete Markdown ordinal columns, never their other cells.

    The column declares its formatting role with an exact header and every row
    must contain the next bare integer. This does not certify the table's data,
    its claimed number of metrics, or a model check's status.
    """
    lines = body.splitlines(keepends=True)
    offsets, position = [], 0
    for line in lines:
        offsets.append(position)
        position += len(line)

    def cells(line):
        if not line.strip().startswith("|") or not line.strip().endswith("|") or "\\|" in line:
            return []
        return list(re.finditer(r"(?<=\|)[^|\r\n]*(?=\|)", line))

    spans, index = [], 0
    while index + 2 < len(lines):
        headers = cells(lines[index])
        ordinals = [column for column, cell in enumerate(headers)
                    if cell.group().strip().casefold() in {"#", "序号", "no.", "no"}]
        separators = cells(lines[index + 1])
        if (len(headers) < 2 or len(ordinals) != 1 or len(headers) != len(separators)
                or not all(re.fullmatch(r"\s*:?-{3,}:?\s*", cell.group()) for cell in separators)):
            index += 1
            continue
        end = index + 2
        while end < len(lines) and lines[end].lstrip().startswith("|"):
            end += 1
        candidate = []
        for number, row_index in enumerate(range(index + 2, end), 1):
            row = cells(lines[row_index])
            if len(row) != len(headers):
                break
            cell = row[ordinals[0]]
            match = re.fullmatch(r"[ \t]*(?P<ordinal>[1-9]\d*)[ \t]*", cell.group())
            if not match or match["ordinal"] != str(number):
                break
            base = offsets[row_index] + cell.start()
            candidate.append((base + match.start("ordinal"), base + match.end("ordinal")))
        else:
            spans.extend(candidate)
        index = end
    return spans


def render_fact_template(body: str, facts: list[dict]) -> tuple[str, list[str]]:
    by_id = {fact["id"]: fact for fact in facts}
    used: list[str] = []

    def replace(match: re.Match) -> str:
        fact_id = match.group(1)
        fact = by_id.get(fact_id)
        if not fact:
            return match.group(0)
        used.append(fact_id)
        display = fact["display_value"]
        unit = str(fact.get("unit") or "")
        # The manager writes 「期间费用 {{fact:…}} 元」 because that is how the
        # sentence reads, and the fact already carries 元. Appending it again
        # printed 「53,262,500 元 元」. Where the prose says the unit, the prose
        # keeps it.
        if unit and display.endswith(f" {unit}") and _unit_follows(body, match.end(), unit):
            return display[: -len(unit)].rstrip()
        # 「缺口 {{fact:…}} 个百分点」 or 「… 百分点」: the prose says the unit, so 「3.30 个百分点」 drops its own.
        if display.endswith(POINTS_SUFFIX) and re.match(r"\s*个?\s*百分点", body[match.end():]):
            return display[: -len(POINTS_SUFFIX)]
        return display

    return FACT_TOKEN.sub(replace, body), used


def _unit_follows(body: str, position: int, unit: str) -> bool:
    """Whether the prose right after the token writes this unit as a word.

    「元」 is a prefix of 「元币」 and 「元旦」, so the unit only counts when what
    follows it is not more of a word.
    """
    return re.match(rf"\s*{re.escape(unit)}(?![\w\u4e00-\u9fff])", body[position:]) is not None


def claims_for_facts(facts: list[dict], fact_ids: list[str]) -> list[dict]:
    by_id = {fact["id"]: fact for fact in facts}
    claims = []
    for fact_id in dict.fromkeys(fact_ids):
        fact = by_id.get(fact_id)
        if not fact:
            continue
        claims.append(
            {
                "basis": "calculation",
                "fact_id": fact["id"],
                "run_id": fact["run_id"],
                "row": fact["row"],
                "column": fact["column"],
                "value": fact["value"],
                "display_value": fact["display_value"],
            }
        )
    return claims


def render_evidence_appendix(prepared: dict) -> dict:
    """Render readable calculation evidence without changing manager prose."""
    from foundry.finance_native_drafts import verified_aging_audit_metadata

    version = 4 if verified_aging_audit_metadata(prepared.get("aging_audit_metadata")) else EVIDENCE_APPENDIX_RENDER_VERSION
    return _render_evidence_appendix(prepared, render_version=version)


def _render_evidence_appendix(prepared: dict, *, render_version: int) -> dict:
    """Versioned reconstruction verifies saved appendices without rewriting them."""
    if not isinstance(prepared, dict):
        raise FoundryError("prepared explanation payload must be an object")
    groups = prepared.get("evidence_groups", [])
    if not isinstance(groups, list):
        raise FoundryError("prepared evidence_groups must be an array")
    facts_by_id = {
        fact["id"]: fact
        for fact in prepared.get("facts", [])
        if isinstance(fact, dict)
        and isinstance(fact.get("id"), str)
        and FACT_ID.fullmatch(fact["id"])
    }
    lines = ["## 计算依据"]
    fact_ids: list[str] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        title = group.get("label") or group.get("group_type") or group.get("id")
        lines.append(f"\n### {title}")
        members = group.get("members", [])
        if not isinstance(members, list):
            continue
        for member in members:
            if not isinstance(member, dict):
                continue
            fact = _appendix_member_fact(group, member, facts_by_id, render_version=render_version)
            state = fact.get("state") if fact else member.get("state", "missing")
            label = member.get("label") or member.get("semantic_role") or member.get("column")
            native = fact is not None and _appendix_native_identity(fact)
            eligible = fact is not None and fact.get("evidence_eligibility", {}).get("counts_as_amount_evidence") is True
            adjustment_unavailable = _adjustment_fact_unavailable(fact)
            # An existing input fact is not automatically qualified as a report
            # amount. Show its status/source without citing its numeric value.
            value = fact.get("display_value") if fact and not adjustment_unavailable and (render_version == 1 or not native or eligible) else None
            suffix = f"：{value}" if value not in (None, "") else ""
            if fact and not adjustment_unavailable and (render_version == 1 or not native or eligible):
                fact_ids.append(fact["id"])
            source_count = (
                fact.get("source_trace", {}).get("source_row_count")
                if fact
                else member.get("source_row_count")
            )
            source = (
                "；有来源行"
                if fact and isinstance(source_count, int) and source_count > 0
                else ""
            )
            status = _appendix_member_label(state, fact)
            if adjustment_unavailable:
                status += "；当前批准不支持引用此调整后金额"
            if render_version >= 2 and native:
                status += "；可引用金额" if eligible else "；不具金额引用资格"
            lines.append(f"- {label}{suffix}（{status}{source}）")
        closure = group.get("closure")
        if isinstance(closure, dict) and closure.get("status") != "unsupported":
            lines.append(f"- 闭合核对：{_closure_label(closure)}")
    if render_version == 4:
        from foundry.finance_native_drafts import render_aging_audit_appendix

        audit = render_aging_audit_appendix(prepared.get("aging_audit_metadata"))
        if audit:
            lines.append("\n" + audit)
    unique_fact_ids = list(dict.fromkeys(fact_ids))
    return {
        "schema_version": render_version,
        "body": "\n".join(lines).strip() if len(lines) > 1 else "",
        "fact_ids": unique_fact_ids,
        "claims": claims_for_facts(
            prepared.get("facts", []), unique_fact_ids
        ),
    }


def evidence_appendix_metadata(body: str, *, base_body: str | None = None,
                               render_version: int = EVIDENCE_APPENDIX_RENDER_VERSION) -> dict:
    if not isinstance(body, str):
        raise FoundryError("evidence appendix body must be text")
    base = body if base_body is None else base_body
    if not isinstance(base, str):
        raise FoundryError("evidence appendix base body must be text")
    if type(render_version) is not int or render_version not in {1, 2, 3, 4}:
        raise FoundryError("unsupported evidence appendix render version")
    return {
        "schema_version": 1,
        "render_version": render_version,
        "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "base_body_sha256": hashlib.sha256(base.encode("utf-8")).hexdigest(),
        "body_chars": len(body),
    }


def _appendix_member_fact(
    group: dict, member: dict, facts_by_id: dict[str, dict], *, render_version: int = EVIDENCE_APPENDIX_RENDER_VERSION
) -> dict | None:
    fact_id = member.get("fact_id")
    if not isinstance(fact_id, str):
        return None
    fact = facts_by_id.get(fact_id)
    if not fact:
        return None
    if group.get("run_id") is not None and fact.get("run_id") != group.get("run_id"):
        return None
    for key in ("row", "column"):
        if member.get(key) is not None and member.get(key) != fact.get(key):
            return None
    if member.get("value") is not None and not _decimal_equal(member.get("value"), fact.get("value")):
        return None
    if member.get("unit") is not None and member.get("unit") != fact.get("unit"):
        return None
    if member.get("state") is not None and member.get("state") != fact.get("state"):
        return None
    if render_version >= 3:
        identity, semantics = fact.get("metric_identity", {}), fact.get("semantics", {})
        if (("template_id" in identity or semantics.get("model_scope") == "management_forecast")
                and not _appendix_native_identity(fact)):
            # A damaged native identity must not become an ordinary fact: that would let result_scope
            # restore its period and the generic rendering path cite even unqualified template inputs.
            return None
    scope = fact.get("scope")
    if render_version >= 2 and isinstance(scope, dict) and _appendix_native_identity(fact):
        # The native output period belongs to its server-generated metric identity.
        # Its source scope may combine opening and flow inputs and have no period.
        # Never override an explicit source-scope period or relax other dimensions.
        if "period" not in scope and not any(isinstance(value, dict) and "period" in value for value in scope.values()):
            scope = {**scope, "period": fact["metric_identity"].get("period")}
    if render_version >= 3 and isinstance(fact.get("result_scope"), dict):
        # Group members and facts share the server's result-row identity. Source binding aliases need not
        # be named actual/budget (a single pq input can contain both sides). Retain explicit source-scope
        # conflicts rather than letting the result identity overwrite them.
        result_scope = fact["result_scope"]
        for key, value in result_scope.items():
            declared = _appendix_scope_value(scope, key) if isinstance(scope, dict) else None
            if declared is None and "." in key and isinstance(scope, dict):
                declared = _appendix_scope_value(scope, key.split(".", 1)[1])
            if declared is not None and declared != value:
                return None
        scope = {**(scope if isinstance(scope, dict) else {}), **result_scope}
    if not _appendix_scope_matches(member.get("scope"), scope):
        return None
    if (
        member.get("display_value") is not None
        and member.get("display_value") != fact.get("display_value")
    ):
        return None
    return fact


def _appendix_native_identity(fact: dict) -> bool:
    from foundry.finance_driver_templates import TEMPLATE_ID

    identity = fact.get("metric_identity", {})
    semantics = fact.get("semantics", {})
    return (identity.get("template_id") == TEMPLATE_ID
            and semantics.get("model_scope") == "management_forecast"
            and identity.get("metric_key") == semantics.get("metric"))


def _appendix_scope_matches(member_scope: Any, fact_scope: Any) -> bool:
    if not isinstance(member_scope, dict) or not member_scope:
        return True
    if not isinstance(fact_scope, dict) or not fact_scope:
        return False
    for key, value in member_scope.items():
        if value in (None, ""):
            continue
        if _appendix_scope_value(fact_scope, key) != value:
            return False
    return True


def _appendix_scope_value(fact_scope: dict, key: str) -> Any:
    if key in fact_scope:
        return fact_scope.get(key)
    if key.startswith("actual_scope."):
        return _appendix_nested_scope_value(
            fact_scope, ("actual",), key.removeprefix("actual_scope.")
        )
    if key.startswith("baseline_scope."):
        return _appendix_nested_scope_value(
            fact_scope, ("baseline", "budget"), key.removeprefix("baseline_scope.")
        )
    nested_values = [
        scope.get(key)
        for scope in fact_scope.values()
        if isinstance(scope, dict) and key in scope
    ]
    if nested_values and all(value == nested_values[0] for value in nested_values):
        return nested_values[0]
    return None


def _appendix_nested_scope_value(fact_scope: dict, aliases: tuple[str, ...], key: str) -> Any:
    for alias in aliases:
        scope = fact_scope.get(alias)
        if isinstance(scope, dict) and key in scope:
            return scope.get(key)
    return None


def _appendix_member_label(state: str, fact: dict | None) -> str:
    if fact:
        return _state_label(state)
    if state in {"missing", "not_applicable"}:
        return _state_label(state)
    return "非可引用：未生成可核验事实"


def validate_explanation(analysis, spec: dict, *, _requirement_recipe_report: dict | None = None,
                         _required_check_authorship: dict | None = None,
                         _allowed: set[str] | None = None) -> dict:
    """Check a draft; evidence recipes are evaluated here, never read from a caller's evidence_report.

    `_requirement_recipe_report` lets save_draft hand over the report it computed for its own recipes so
    the generated appendix is rebuilt from the same requirement check without a second evaluation.
    """
    if not isinstance(spec, dict):
        raise FoundryError("explanation spec must be an object")
    if {"required_check_authorship", "_required_check_authorship"}.intersection(spec):
        raise FoundryError("required_check_authorship is service-owned evidence")
    draft = analysis.get_draft(spec["draft_id"]) if spec.get("draft_id") else {}
    body = _safe_text(spec.get("body", draft.get("body", "")), "draft body")
    run_ids = spec.get("run_ids", draft.get("run_ids", []))
    fact_ids = spec.get("fact_ids", draft.get("fact_ids", []))
    claims = json_value(spec.get("claims", draft.get("claims", [])))
    if not isinstance(run_ids, list) or not isinstance(fact_ids, list):
        raise FoundryError("run_ids and fact_ids must be arrays")
    if not isinstance(claims, list):
        raise FoundryError("claims must be an array")
    runs = [analysis.get_run(run_id) for run_id in dict.fromkeys(run_ids)]
    prepared = prepare_explanation(
        analysis,
        [r for r in runs if r.get("execution_status") == "succeeded"],
        materiality=spec.get("materiality", draft.get("materiality", {})),
        _allowed=_allowed,
    )
    from foundry.financial_evidence import evaluate_evidence_recipes

    evidence_report = evaluate_evidence_recipes(analysis, {**draft, **spec}.get("evidence_recipes", []))
    generated_regions = _trusted_generated_appendix_regions(
        analysis, body, {**draft, **spec}, prepared,
        recipe_report=_requirement_recipe_report if _requirement_recipe_report is not None else evidence_report,
    )
    from foundry.finance_recognition_basis import VERSION as RECOGNITION_BASIS_VERSION, recognition_claim_issues

    recognition_basis = _service_recognition_basis(
        analysis, runs, requirements_id=spec.get("requirements_id", draft.get("requirements_id")), allowed=_allowed)
    facts = prepared["facts"]
    by_id = {fact["id"]: fact for fact in facts}
    by_location = {(fact["run_id"], fact["row"], fact["column"]): fact for fact in facts}
    native_run_ids = _native_template_run_ids(runs)
    from foundry.finance_adjustments import current_reference_issues

    # save_draft supplies its server-evaluated recipes through this report.
    # Their claim cells remain dependencies even without direct run citations.
    dependency_spec = {**draft, **spec}
    if _requirement_recipe_report is not None:
        dependency_spec["evidence_recipes"] = _requirement_recipe_report.get("results") or []
    issues: list[dict] = [*transaction_review_issues(runs, analysis=analysis, spec={**draft, **spec}),
                          *recognition_claim_issues(body, recognition_basis),
                          *current_reference_issues(analysis, dependency_spec, allowed=_allowed, facts=facts)]
    # Cited order, not a set: which of two same-valued facts an issue names must not follow PYTHONHASHSEED
    # (the completion issue_fingerprint hashes these issues).
    referenced: dict[str, None] = {}
    for fact_id in fact_ids:
        if (
            not isinstance(fact_id, str)
            or not FACT_ID.fullmatch(fact_id)
            or fact_id not in by_id
        ):
            issues.append(
                {
                    "code": "unknown_fact",
                    "severity": "error",
                    "message": "引用的事实不存在于当前成功运行结果。",
                    "fact_id": fact_id,
                }
            )
        else:
            referenced.setdefault(fact_id)
    for claim in claims:
        if not isinstance(claim, dict) or claim.get("basis") not in BASIS:
            issues.append(
                {
                    "code": "invalid_claim",
                    "severity": "error",
                    "message": "claim requires an explicit supported basis.",
                }
            )
            continue
        fact = by_id.get(claim.get("fact_id")) if claim.get("fact_id") else None
        if not fact and claim.get("basis") != "calculation" and claim.get("run_id") in native_run_ids:
            # A caller category or omitted/forged ID cannot erase an explicit
            # native cell location. Resolve identity before checking its value.
            fact = by_location.get((claim.get("run_id"), claim.get("row"), claim.get("column")))
            if not fact or claim.get("fact_id"):
                issues.append({"code": "unknown_fact", "severity": "error",
                               "message": "引用的事实或位置不存在于当前成功运行结果。"})
        if fact:
            referenced.setdefault(fact["id"])
            if any(
                claim.get(key) != fact[key]
                for key in ("run_id", "row", "column", "value")
            ):
                issues.append(
                    {
                        "code": "fact_claim_mismatch",
                        "severity": "error",
                        "message": "事实引用与 claim 的 run/row/column/value 不一致。",
                        "fact_id": fact["id"],
                    }
                )
        elif claim.get("basis") == "calculation":
            issue = _validate_calculation_claim(analysis, claim, run_ids)
            if issue:
                issues.append(issue)
            else:
                bound_fact = by_location.get((claim.get("run_id"), claim.get("row"), claim.get("column")))
                if bound_fact:
                    referenced.setdefault(bound_fact["id"])
                else:
                    issues.append({"code": "unknown_fact", "severity": "error", "message": "引用位置没有可核验的数值事实。"})
            if claim.get("fact_id"):
                issues.append({"code": "unknown_fact", "severity": "error", "message": "引用的事实不存在于当前成功运行结果。"})
    body_template = _validated_fact_template(
        body, spec.get("body_template", draft.get("body_template")), facts, generated_regions,
    )
    issues.extend(
        _fact_context_issues(
            body,
            [by_id[f] for f in referenced if f in by_id],
            prepared.get("evidence_groups", []),
            runs=runs,
            performance_facts=prepared.get("forecast_performance", {}).get("facts", []),
            qualification_facts=facts,
            body_template=body_template,
            trusted_fact_ids=_trusted_recipe_fact_ids(
                analysis, facts, runs,
                _requirement_recipe_report if _requirement_recipe_report is not None else evidence_report,
            ),
        )
    )
    presentation = _presentation_allowed_numbers_and_issues(claims, by_id)
    issues.extend(presentation["issues"])
    base_allowed_numbers = _allowed_numbers(
        [by_id[fact_id] for fact_id in referenced if fact_id in by_id]
    )
    percent_values = _percent_number_values(
        [by_id[fact_id] for fact_id in referenced if fact_id in by_id]
    )
    # A number written with % is a percentage of a fraction the run stored (a ratio fact), a %/pct row's own value,
    # or a presentation: never an amount, a 百分点 or a %/pct value read again as a fraction (330% for 3.3).
    percent_token_allowed_numbers = _allowed_numbers(
        [by_id[fact_id] for fact_id in referenced if fact_id in by_id and _fact_is_ratio(by_id[fact_id])]
    )
    count_spans, count_issues = _structure_count_spans(
        body, prepared, spec.get("requirements_id", draft.get("requirements_id")),
    )
    issues.extend(count_issues)
    ignored_number_spans = [
        *count_spans,
        *_table_ordinal_spans(body),
        *_generated_appendix_heading_number_spans(body, prepared),
        *_generated_appendix_label_number_spans(body, generated_regions, prepared),
        *_generated_appendix_reference_spans(body, generated_regions),
        *_generated_aging_audit_number_spans(body, generated_regions, prepared),
    ]
    for token in _body_numbers(body, ignored_spans=ignored_number_spans):
        normalized = _normalize_number(token["text"])
        if _is_percent_text(token["text"]):
            if normalized in percent_token_allowed_numbers or _is_cited_percent_number(token["text"], percent_values):
                continue
        elif normalized in base_allowed_numbers:
            continue
        if normalized in presentation["numbers"] and _presentation_token_unit_matches(body, token, presentation["numbers"][normalized]):
            continue
        issues.append(
                {
                    "code": "uncited_number",
                    "severity": "warning",
                    "message": "正文包含未绑定到当前事实或 claim 的数字。",
                    "text": token["text"],
                    "position": token["start"],
                }
            )
    required = set(_required_fact_ids(facts))
    missing_required = required - referenced.keys()
    authorship = draft.get("required_check_authorship", _required_check_authorship)
    if authorship is not None:
        required_checks = {fact["id"] for fact in facts if fact["id"] in required and fact["column"] == "residual"}
        if (not isinstance(authorship, dict) or authorship.get("schema_version") != 1
                or authorship.get("run_output_hashes") != {run["id"]: run.get("output_hash") for run in runs}
                or not isinstance(authorship.get("required_fact_ids"), list)
                or not isinstance(authorship.get("authored_fact_ids"), list)
                or any(not isinstance(value, str) for value in
                       [*authorship["required_fact_ids"], *authorship["authored_fact_ids"]])
                or set(authorship["required_fact_ids"]) != required_checks
                or not set(authorship["authored_fact_ids"]) <= by_id.keys()):
            raise FoundryError("required check authorship does not match the current facts and runs")
        missing_required |= required_checks - set(authorship["authored_fact_ids"])
    missing_required = sorted(missing_required)
    for fact_id in missing_required:
        issues.append(
            {
                "code": "missing_required_fact",
                "severity": "warning",
                "message": "重要结果事实尚未在说明中引用。",
                "fact_id": fact_id,
            }
        )
    for group in prepared.get("evidence_groups", []):
        if not isinstance(group, dict):
            continue
        closure = group.get("closure", {})
        if isinstance(closure, dict) and closure.get("status") in {
            "closure_mismatch",
            "scope_mismatch",
            "unit_mismatch",
        }:
            issues.append(
                {
                    "code": "evidence_group_not_closed",
                    "severity": "warning",
                    "message": "计算依据组未通过同范围同单位闭合核对。",
                    "group_id": group.get("id"),
                    "closure_status": closure.get("status"),
                }
            )
        if group.get("status") == "partial":
            issues.append(
                {
                    "code": "evidence_group_partial",
                    "severity": "warning",
                    "message": "计算依据组含缺项：有科目只在一侧有来源行，这一组不算完整比较。",
                    "group_id": group.get("id"),
                }
            )
    merged = {**draft, **spec, "run_ids": run_ids}
    consistency_rules = merged.get("consistency_rules", [])
    consistency_sources = merged.get("consistency_sources", {})
    from foundry.analysis import _quality_status_dimensions, _revision_quality_issues
    from foundry.finance_revision import compare_draft_runs
    from foundry.financial_consistency import consistency_quality_issues, evaluate_consistency_rules
    from foundry.financial_evidence import prepare_consistency_inputs

    parent = analysis.get_draft(merged["parent_id"]) if merged.get("parent_id") else {}
    revision_comparison = compare_draft_runs(analysis, parent, {"run_ids": run_ids})
    resolved_rules, consistency_source_auth = prepare_consistency_inputs(
        analysis, consistency_rules, consistency_sources
    )
    consistency_report = evaluate_consistency_rules(
        resolved_rules,
        recipe_report=evidence_report,
        source_auth=consistency_source_auth,
    )
    issues.extend(_revision_quality_issues(revision_comparison))
    issues.extend(evidence_report.get("issues", []))
    issues.extend(consistency_quality_issues(consistency_report))
    execution_status = (
        "succeeded"
        if runs and all(run.get("execution_status") == "succeeded" for run in runs)
        else "failed"
        if runs
        else "not_run"
    )
    stored_review = draft.get("review_status", "unreviewed") if draft else "unreviewed"
    effective_review = stored_review if draft and body == draft.get("body") and claims == draft.get("claims", []) else "unreviewed"
    status_dimensions = _quality_status_dimensions(
        execution_status=execution_status,
        review_status=effective_review,
        quality_issues=issues,
        evidence_report=evidence_report,
        consistency_report=consistency_report,
        numeric_configured=bool(run_ids or claims or fact_ids),
    )
    status = "pass" if not issues else "needs_attention"
    issues = _locate_issues(issues, generated_regions)
    readability = _readability_suggestions(body, generated_regions)
    from foundry.finance_claim_semantics import CLAIM_SEMANTICS_VERSION

    from foundry.finance_transaction_reviews import decision_for_spec, QUALIFICATION
    review_state = (decision_for_spec(analysis, {**draft, **spec}) if any(
        (run.get("result") or {}).get("qualification") == QUALIFICATION for run in runs) else None)
    return {
        **({"transaction_review": {key: review_state.get(key) for key in
                                  ("current_status", "decision", "basis_fingerprint")}} if review_state else {}),
        "schema_version": 1,
        "claim_semantics_version": CLAIM_SEMANTICS_VERSION,
        "recognition_basis_version": RECOGNITION_BASIS_VERSION,
        **({"recognition_basis": recognition_basis} if recognition_basis["status"] != "not_applicable" else {}),
        "status": status,
        "issues": [issue for issue in issues if issue],
        "status_dimensions": status_dimensions,
        "evidence_report": evidence_report,
        "consistency_report": consistency_report,
        "revision_comparison": revision_comparison,
        "readability": readability,
        "coverage": {
            "referenced_fact_count": len(referenced),
            "available_fact_count": len(facts),
            "missing_required_fact_ids": missing_required,
            "fact_states": _fact_state_counts(facts),
            "evidence_group_statuses": _evidence_group_statuses(
                prepared.get("evidence_groups", [])
            ),
        },
        "facts": facts,
        "evidence_groups": prepared.get("evidence_groups", []),
    }


def _validated_fact_template(body, template, facts, generated_regions):
    if not isinstance(template, str):
        return None
    try:
        rendered, _ = render_fact_template(template, facts)
        prose = body
        for region in sorted(generated_regions, key=lambda item: item["start"], reverse=True):
            prose = prose[:region["start"]] + prose[region["end"]:]
        return template if rendered.strip() == prose.strip() else None
    except FoundryError:
        return None


def _native_template_run_ids(runs):
    from foundry.finance_driver_templates import TEMPLATE_ID

    return {run["id"] for run in runs if run.get("execution_status") == "succeeded"
            and run.get("engine") == "finance"
            and (run.get("result") or {}).get("template_id") == TEMPLATE_ID}


def saved_claim_semantic_issues(analysis, draft, allowed=None):
    """Recheck earlier semantic verdicts in a current read, without rewriting history."""
    from foundry.finance_claim_semantics import CLAIM_SEMANTICS_VERSION, check_claim_semantics
    from foundry.finance_recognition_basis import _ASSERTION, recognition_claim_issues

    check = draft.get("explanation_check") or draft.get("quality") or {}
    current = check.get("claim_semantics_version") == CLAIM_SEMANTICS_VERSION
    body = draft.get("body") or ""
    # This is only a syntax prefilter for whether source-bound recognition
    # validation is needed. A matching assertion never supplies its own basis.
    refresh_recognition = bool(_ASSERTION.search(body))
    if current:
        from foundry.finance_claim_semantics import _PERFORMANCE_STATE, qualification_assertion_lines
        refresh_performance = bool(_PERFORMANCE_STATE.search(body))
        refresh_qualification = bool(qualification_assertion_lines(body))
        if not refresh_performance and not refresh_qualification and not refresh_recognition:
            return []
    # Preserve filed verdicts. Current reads refresh relevant mutable source and
    # qualification metadata without adding uncited facts to amount authority.
    runs = [analysis.get_run(run_id) for run_id in dict.fromkeys(draft.get("run_ids") or [])]
    if allowed is not None and any(not set((run.get("bindings") or {}).values()) <= set(allowed) for run in runs):
        return []  # The caller's existing visibility gate owns inaccessible drafts.
    recognition_issues = (recognition_claim_issues(
        body, _service_recognition_basis(
            analysis, runs, requirements_id=draft.get("requirements_id"), allowed=allowed))
        if refresh_recognition else [])
    if current and not refresh_performance and not refresh_qualification:
        return recognition_issues
    if current:
        from foundry.finance_claim_semantics import forecast_performance_issues, qualification_claim_report
        issues = []
        if refresh_performance:
            proof = _forecast_performance_sources(analysis, runs, allowed=allowed)
            issues = forecast_performance_issues(body, performance_facts=proof["facts"])
        if refresh_qualification:
            catalog = [fact for run in runs if run.get("execution_status") == "succeeded"
                       for fact in _facts_for_run(run, _materiality(draft.get("materiality") or {}), analysis=analysis)]
            issues += qualification_claim_report(body, facts=catalog, runs=runs)["issues"]
        return [*recognition_issues, *issues]
    runs = [run for run in runs if run.get("execution_status") == "succeeded"]
    transaction_issues = transaction_review_issues(runs, analysis=analysis, spec=draft, allowed=allowed)
    if not runs:
        return recognition_issues
    prepared = prepare_explanation(analysis, runs, materiality=draft.get("materiality"), _allowed=allowed)
    facts = prepared["facts"]
    referenced = set(draft.get("fact_ids") or [])
    native_run_ids = _native_template_run_ids(runs)
    locations = set()
    for claim in draft.get("claims") or []:
        if isinstance(claim, dict):
            if claim.get("fact_id"):
                referenced.add(claim["fact_id"])
            if claim.get("basis") == "calculation" or claim.get("run_id") in native_run_ids:
                locations.add((claim.get("run_id"), claim.get("row"), claim.get("column")))
    cited = [fact for fact in facts if fact["id"] in referenced
             or (fact["run_id"], fact["row"], fact["column"]) in locations]
    body = draft.get("body") or ""
    regions = _trusted_generated_appendix_regions(analysis, body, draft, prepared)
    template = _validated_fact_template(body, draft.get("body_template"), facts, regions)
    from foundry.financial_evidence import evaluate_evidence_recipes
    recipe_report = evaluate_evidence_recipes(analysis, draft.get("evidence_recipes") or [])
    issues = check_claim_semantics(body, cited, runs=runs, body_template=template, qualification_facts=facts,
                                  performance_facts=prepared.get("forecast_performance", {}).get("facts", []),
                                  referenced_fact_ids=[fact["id"] for fact in cited],
                                  trusted_fact_ids=_trusted_recipe_fact_ids(analysis, facts, runs, recipe_report))
    prose = body
    for region in sorted(regions, key=lambda item: item["start"], reverse=True):
        prose = prose[:region["start"]] + prose[region["end"]:]
    # Recheck earlier signed-bridge and token-unit verdicts without editing
    # the archived draft. Only a template verified against its body can bind units.
    issues.extend(issue for issue in _fact_context_issues(
        prose, cited, prepared.get("evidence_groups", []), body_template=template)
                  if issue.get("code") in {"fact_direction_mismatch", "body_closure_mismatch", "fact_unit_mismatch"})
    if any(((run.get("result") or {}).get("evidence") or {}).get("status_filter") for run in runs):
        from foundry.finance_requirements import check_requirements

        requirements = check_requirements(analysis, draft, _allowed=allowed)
        for item in requirements["items"]:
            if item["status"] != "answered" and any(
                location.get("evidence", {}).get("not_counted_reason") == "receivables_population_filtered"
                for location in item.get("locations", [])
            ):
                issues.append({"code": "fact_population_scope_mismatch", "severity": "error",
                               "requirement_item_id": item["id"],
                               "message": "完整应收要求不能仅由筛选后的应收子集回答。"})
    return [*transaction_issues, *recognition_issues, *issues]


def transaction_review_issues(runs, *, analysis=None, spec=None, allowed=None):
    """A transaction check is a review artifact, never an approved accounting amount."""
    from foundry.finance_transaction_reviews import decision_for_spec, QUALIFICATION
    runs = [run for run in runs if (run.get("result") or {}).get("qualification") == QUALIFICATION]
    if not runs:
        return []
    state = decision_for_spec(analysis, spec, allowed) if analysis is not None and spec is not None else {}
    issues = []
    for run in runs:
        blockers = [issue for issue in _run_diagnostics(run) if issue.get("severity") == "error"]
        if not blockers and state.get("approved"):
            continue
        issues.extend(blockers or [{
            **({"requirement_item_id": state["obligation_ids"][0]} if state.get("obligation_ids") else {}),
            "code": "transaction_review_requires_professional_review", "severity": "warning",
            "run_id": run["id"], "message": "来源约束的交易检查已通过，仍需专业复核；检查结果不授予金额证据或过账资格。",
        }])
    return issues


def _trusted_recipe_fact_ids(analysis, facts, runs, report):
    """Preserve a source metric's identity through verified direct/sum recipes.

    Numeric equality alone cannot rename a source metric. This deliberately
    accepts only explicit typed workbook rows at the same scope and unit.
    The report is computed by the server; no caller trust flags are read.
    """
    from openpyxl.utils import range_boundaries

    by_cell = {(fact["run_id"], fact["row"], fact["column"]): fact for fact in facts}
    by_run = {run["id"]: run for run in runs}
    trusted = set()
    for result in report.get("results") or []:
        if (result.get("status") != "pass" or result.get("kind") not in {"direct", "sum"}
                or result.get("evidence_class") not in {"source_value", "source_calculation"}
                or result.get("scale") != "1" or result.get("factor")):
            continue
        claim = result.get("claim") or {}
        fact = by_cell.get((claim.get("run_id"), claim.get("row"), claim.get("column")))
        refs = result.get("source_refs") or []
        if not fact or len(refs) != 1:
            continue
        metric = fact.get("semantics", {}).get("metric")
        source = refs[0]
        run = by_run.get(fact["run_id"], {})
        if not metric or source.get("dataset_id") not in (run.get("bindings") or {}).values():
            continue
        try:
            dataset = analysis.read_dataset(source["dataset_id"])
            transform = dataset.get("transformation") or {}
            if dataset.get("source_hash") != source.get("source_hash") or transform.get("sheet") != source.get("sheet"):
                continue
            left, first, right, last = range_boundaries(source["range"])
            if left != right:
                continue
            headers = transform.get("header_columns") or {}
            source_column = next((name for name, letter in headers.items()
                                  if range_boundaries(f"{letter}1")[0] == left), None)
            if source_column not in {"amount", "value", metric}:
                continue
            indexed = dict(zip(transform.get("source_row_numbers") or [], dataset.get("rows") or []))
            rows = [indexed.get(number) for number in range(first, last + 1)]
            output = run["result"]["rows"][fact["row"]]
            scope = {**(fact.get("scope") or {}), **_row_scope(output), "scenario": output.get("scenario")}
            if not rows or any(not row or row.get("metric_key") != metric or row.get("unit") != fact.get("unit")
                               or any(row.get(key) != scope.get(key) for key in ("ledger", "organization", "currency", "period", "scenario")
                                      if row.get(key) not in (None, "") or scope.get(key) not in (None, ""))
                               for row in rows):
                continue
            trusted.add(fact["id"])
        except (FoundryError, KeyError, TypeError, ValueError):
            continue
    return trusted


def normalize_background(
    spec: dict,
    *,
    parent: dict | None = None,
    dataset: dict | None = None,
    context: dict | None = None,
) -> dict:
    if not isinstance(spec, dict):
        raise FoundryError("finance background spec must be an object")
    parent = parent or {}
    basis = spec.get("basis", parent.get("basis", "professional_judgment"))
    if basis not in BASIS:
        raise FoundryError("background basis is unsupported")
    scope = spec.get("scope", parent.get("scope", {}))
    if not isinstance(scope, dict):
        raise FoundryError("background scope must be an object")
    # A note saved against a finance context takes that context's ledger and
    # organization, blank ones included: files from one company often name neither,
    # and the note then reaches only scopes that leave them blank too.
    # A revision inherits what its parent was saved with, blank ledger included.
    if context or parent:
        scope = {**scope, **{
            key: scope.get(key)
            or (_context_scope_value(context, key) if context else "")
            or (parent.get("scope") or {}).get(key)
            or ""
            for key in ("ledger", "organization")
        }}
    elif not scope.get("ledger") or not scope.get("organization"):
        raise FoundryError(
            "background scope requires ledger and organization, or a context_id whose scope supplies them"
        )
    effective_from = _date_key(
        spec.get("effective_from", parent.get("effective_from")), "effective_from"
    )
    effective_to = spec.get("effective_to", parent.get("effective_to"))
    if effective_to is not None:
        effective_to = _date_key(effective_to, "effective_to")
        if _date_end_key(effective_to) < effective_from:
            raise FoundryError("effective_to cannot be earlier than effective_from")
    paragraph = spec.get("paragraph", (parent.get("source") or {}).get("paragraph"))
    if paragraph is not None and (
        isinstance(paragraph, bool) or not isinstance(paragraph, int) or paragraph < 1
    ):
        raise FoundryError("background paragraph must be a positive integer")
    paragraph_text = None
    if dataset and paragraph:
        paragraph_record = next(
            (p for p in dataset.get("paragraphs", []) if p["paragraph"] == paragraph),
            None,
        )
        if not paragraph_record:
            raise FoundryError("background paragraph does not exist")
        paragraph_text = paragraph_record.get("text", "")
    if basis == "source_fact":
        if not dataset or not paragraph:
            raise FoundryError("source_fact background requires dataset_id and paragraph")
        text = _safe_text(spec.get("text", parent.get("text", "")), "background text", required=True)
        if text not in paragraph_text:
            raise FoundryError("background text must come from paragraph")
    external_reference = _external_reference(spec, parent, basis)
    source = None
    if dataset:
        source = {
            "dataset_id": dataset["id"],
            "source_hash": dataset["source_hash"],
            "paragraph": paragraph,
            "paragraph_text": paragraph_text,
        }
    return {
        "label": _safe_text(
            spec.get("label", parent.get("label", "业务背景")),
            "background label",
            required=True,
            maximum=200,
        ),
        "text": _safe_text(
            spec.get("text", parent.get("text", "")), "background text", required=True
        ),
        "basis": basis,
        "scope": json_value({k: v for k, v in scope.items() if k not in {"period", "scenario"}}),
        "effective_from": effective_from,
        "effective_to": effective_to,
        "source": source,
        "external_reference": external_reference,
        "parent_id": parent.get("id"),
    }


def _context_scope_value(context: dict, key: str) -> str:
    """The context's value for ``key`` from its primary (first) scope, blank when it names none."""
    for scope in (context.get("scopes") or {}).values():
        if isinstance(scope, dict):
            return str(scope.get(key) or "")
    return ""


def background_applies(record: dict, *, scope: dict, as_of: str | None = None) -> bool:
    candidate = record.get("scope", {})
    # Ledger and organization are the boundary a note may not cross, checked whether or not
    # the record carries the keys: a note for a context that names neither stays with scopes
    # that name neither.
    for key in ("ledger", "organization"):
        if (scope.get(key) or "") != (candidate.get(key) or ""):
            return False
    for key, value in candidate.items():
        if key in ("ledger", "organization"):
            continue
        if key == "scenario" or value in (None, ""):
            continue
        if scope.get(key) != value:
            return False
    # Without the task's own period, applicability cannot be judged; the machine
    # clock is never a substitute (an August close must not pick up October notes).
    if not as_of:
        return False
    as_of = _date_key(as_of, "as_of")
    if str(record.get("effective_from", "")) > _date_end_key(as_of):
        return False
    if record.get("effective_to") and _date_end_key(str(record["effective_to"])) < as_of:
        return False
    return True


def _date_key(value: Any, label: str) -> str:
    text = _safe_text(value, label, required=True, maximum=40)
    if not PERIOD_OR_DATE.fullmatch(text):
        raise FoundryError(f"{label} must be YYYY-MM or YYYY-MM-DD")
    try:
        date.fromisoformat(text + '-01' if len(text) == 7 else text)
    except ValueError as exc:
        raise FoundryError(f"{label} must be a valid YYYY-MM or YYYY-MM-DD date") from exc
    return text


def _date_end_key(value: str) -> str:
    return f"{value}-{monthrange(int(value[:4]), int(value[5:7]))[1]:02d}" if len(value) == 7 else value


def _external_reference(spec: dict, parent: dict, basis: str) -> dict | None:
    value = spec.get("external_reference", parent.get("external_reference"))
    if basis != "external_reference":
        return json_value(value) if isinstance(value, dict) else None
    if not isinstance(value, dict):
        raise FoundryError("external_reference requires reference metadata")
    title = value.get("title")
    url = value.get("url")
    if not (
        isinstance(title, str)
        and title.strip()
        or isinstance(url, str)
        and url.strip()
    ):
        raise FoundryError("external_reference requires title or url")
    source_date = value.get("source_date")
    retrieved_at = value.get("retrieved_at")
    if not source_date and not retrieved_at:
        raise FoundryError("external_reference requires source_date or retrieved_at")
    cleaned = dict(value)
    for key in ("source_date", "retrieved_at"):
        if cleaned.get(key):
            try:
                cleaned[key] = _date_key(cleaned[key], f"external_reference {key}")
            except FoundryError as exc:
                raise FoundryError("external_reference date must be YYYY-MM or YYYY-MM-DD") from exc
    return json_value(cleaned)


def _facts_for_run(run: dict, materiality: dict, *, analysis=None) -> list[dict]:
    result = run.get("result", {})
    rows = result.get("rows", [])
    column_defs = _column_defs(result)
    columns = list(column_defs)
    facts: list[dict] = []
    for row_index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        for column in columns:
            if not _include_fact_column(row, column, column_defs):
                continue
            value = row.get(column)
            if not _is_fact_value(value, column):
                continue
            fact = _make_fact(run, row_index, row, column, value, materiality, column_defs, analysis=analysis)
            facts.append(fact)
    return facts


def _materiality(materiality: dict) -> dict:
    if not isinstance(materiality, dict):
        raise FoundryError("materiality must be an object")
    cleaned = {"absolute": str(materiality.get("absolute", "0"))}
    try:
        Decimal(cleaned["absolute"])
    except InvalidOperation as exc:
        raise FoundryError("materiality.absolute must be a decimal string") from exc
    relative = materiality.get("relative")
    if relative is None:
        return cleaned
    if isinstance(relative, dict):
        threshold = relative.get("threshold", relative.get("value"))
        denominator = relative.get("denominator", "baseline_abs")
        negative_policy = relative.get("negative_policy", "absolute")
    else:
        threshold = relative
        denominator = "baseline_abs"
        negative_policy = "absolute"
    try:
        threshold_text = str(threshold)
        threshold_value = Decimal(threshold_text)
    except (InvalidOperation, TypeError) as exc:
        raise FoundryError("materiality.relative threshold must be a decimal string") from exc
    if threshold_value < 0:
        raise FoundryError("materiality.relative threshold cannot be negative")
    if denominator not in {"baseline_abs", "actual_abs", "max_abs"}:
        raise FoundryError("materiality.relative denominator is unsupported")
    if negative_policy not in {"absolute", "signed"}:
        raise FoundryError("materiality.relative negative_policy is unsupported")
    return {
        **cleaned,
        "relative": {
            "threshold": threshold_text,
            "denominator": denominator,
            "negative_policy": negative_policy,
        },
    }


def _run_diagnostics(run: dict) -> list[dict]:
    rows = []
    for item in [
        *run.get("warnings", []),
        *run.get("result", {}).get("diagnostics", []),
        *run.get("diagnostics", []),
    ]:
        if isinstance(item, dict):
            rows.append({**item, "run_id": run["id"]})
    return rows


def _adjustment_fact_unavailable(fact: dict | None) -> bool:
    return bool(fact and fact.get("column") == "adjusted_total" and
                {"adjustment_approval_superseded", "adjustment_dependency_unavailable"}
                & set(fact.get("evidence_eligibility", {}).get("reason_codes", [])))


def _required_fact_ids(facts: list[dict]) -> list[str]:
    selected = {}
    for fact in facts:
        if fact["semantics"].get("required_for_explanation") is not True:
            continue
        if _adjustment_fact_unavailable(fact):
            continue
        key = (
            fact["run_id"],
            fact["row"],
            fact["semantics"].get("metric"),
        )
        current = selected.get(key)
        if current is None or _fact_priority(fact) < _fact_priority(current):
            selected[key] = fact
    return [fact["id"] for fact in selected.values()]


def _fact_priority(fact: dict) -> int:
    column = fact.get("column")
    if column == "contribution":
        return 0
    if column == "profit_impact":
        return 1
    if column in RATIO_COLUMNS:
        return 1
    if column in {"actual", "baseline"}:
        return 2
    return 3



def _locator_trace(refs) -> dict:
    if not isinstance(refs, list):
        return {"preview_available": False}
    for ref in refs:
        if isinstance(ref, dict) and isinstance(ref.get("source_locator"), dict):
            locator = {
                key: value
                for key, value in ref["source_locator"].items()
                if key not in {"path", "url", "file"}
                and not (isinstance(value, str) and ("/" in value or "\\" in value or "file://" in value))
            }
            return {
                "source_locator": locator,
                "preview_available": bool(locator.get("preview_available")),
            }
    return {"preview_available": False}


def _make_fact(
    run: dict,
    row_index: int,
    row: dict,
    column: str,
    value: Any,
    materiality: dict,
    column_defs: dict[str, dict],
    *, analysis=None,
) -> dict:
    exact = _exact(value)
    fact_id = _hash(
        {
            "kind": "finance-explanation-fact-v1",
            "run_id": run["id"],
            "output_hash": run.get("output_hash"),
            "row": row_index,
            "column": column,
            "value": exact,
        }
    )
    unit = _fact_unit(row, column, column_defs, run)
    display = _display_value(exact, column, unit)
    semantics = _semantics(row, column, exact, materiality)
    if (run.get('result') or {}).get('template_id'):
        semantics['model_scope'] = 'management_forecast'
        semantics['metric'] = row.get('metric_key') or row.get('driver')
        semantics['required_for_explanation'] = bool(row.get('template_id') and semantics.get('required_for_explanation'))
    refs = row.get("evidence", {}).get(column, row.get("source_rows", []))
    scope = run.get("finance_scope", {})
    if run.get("engine") == "structured_aggregate":
        dimensions = [*run.get("aggregate_plan", {}).get("group_by", []), "currency", "unit"]
        scope = {**scope, **{key: row[key] for key in dimensions if key in row}}
    from foundry.finance_professional import cell_evidence_eligibility
    eligibility = cell_evidence_eligibility(run, row, column, analysis=analysis)
    identity = {"metric_key": semantics["metric"], "role": semantics["role"], "unit": unit}
    for key in ("organization", "ledger", "period", "scenario", "currency", "statement", "statement_line",
                "value_kind", "template_id", "template_version", "scenario_id"):
        identity_value = row.get(key)
        if identity_value is None and key in {"template_id", "template_version", "scenario_id"}:
            identity_value = (run.get("result") or {}).get(key)
        if identity_value is None and isinstance(scope, dict):
            values = [entry[key] for entry in scope.values() if isinstance(entry, dict) and entry.get(key) is not None]
            if values and all(item == values[0] for item in values):
                identity_value = values[0]
        if identity_value is not None:
            identity[key] = identity_value
    return {
        "id": fact_id,
        "run_id": run["id"],
        "analysis_id": run.get("analysis_id"),
        "row": row_index,
        "column": column,
        "value": exact,
        "display_value": display,
        "label": _label(row, column),
        "unit": unit,
        "scope": scope,
        # Script row labels alone must not auto-cite values the draft did not claim.
        # The deterministic finance engine establishes this canonical result scope.
        "result_scope": _row_scope(row) if run.get("engine") == "finance" else {},
        "semantics": semantics,
        "metric_identity": identity,
        "reference_template": {
            "body_token": "{{fact:" + fact_id + "}}",
            "claim": {"basis": "calculation", "fact_id": fact_id, "run_id": run["id"],
                      "row": row_index, "column": column, "value": exact},
        },
        "state": _fact_state(value),
        "evidence_eligibility": eligibility,
        "source_trace": {
            "output_hash": run.get("output_hash"),
            "input_hashes": run.get("input_hashes", {}),
            "source_hashes": run.get("source_hashes", {}),
            "source_rows": refs,
            "source_row_count": len(refs) if isinstance(refs, list) else 0,
            **_locator_trace(refs),
            "provenance_status": (
                run.get("result", {}).get("provenance", {}).get("status", "unverified")
                if run.get("engine") == "structured_aggregate" else
                "available_for_verification" if eligibility["counts_as_amount_evidence"] else "unverified"
            ),
        },
    }


def _semantics(row: dict, column: str, exact: str, materiality: dict) -> dict:
    role = _fact_role(column)
    if column in {"contribution", "profit_impact"}:
        role = "profit_impact"
    try:
        signed_value = Decimal(exact.rstrip("%"))
        magnitude = abs(signed_value)
    except InvalidOperation:
        signed_value = Decimal(0)
        magnitude = Decimal(0)
    threshold = materiality.get("absolute", "0") if isinstance(materiality, dict) else "0"
    try:
        absolute_material = magnitude >= Decimal(str(threshold))
    except InvalidOperation:
        absolute_material = magnitude != 0
    relative = _relative_materiality(row, column, signed_value, magnitude, materiality)
    material = absolute_material or relative["is_material"]
    return {
        "role": role,
        "metric": _row_metric(row, column),
        "direction": "positive" if not exact.startswith("-") else "negative",
        "state": "observed_zero" if magnitude == 0 else "nonzero",
        "materiality": {
            "absolute": {
                "threshold": str(threshold),
                "is_material": absolute_material,
            },
            "relative": relative,
        },
        "required_for_explanation": (
            column not in {"actual", "baseline"}
            and material
            and magnitude != 0
            and role in {
                "amount",
                "ratio",
                "profit_impact",
                "count",
                "quantity",
                "unit_price",
                "value",
            }
        ) or (magnitude == 0 and column in {
            "contribution",
            "profit_impact",
            "total_variance",
            "interaction",
            "residual",
        }),
    }


def _fact_role(column: str) -> str:
    if _is_ratio_column(column):
        return "ratio"
    if _is_count_column(column):
        return "count"
    if column in QUANTITY_COLUMNS:
        return "quantity"
    if column in UNIT_PRICE_COLUMNS:
        return "unit_price"
    if _is_amount_column(column):
        return "amount"
    return "value"


def _column_tokens(column: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", column.lower()) if token}


def _is_ratio_column(column: str) -> bool:
    lowered = column.lower()
    tokens = _column_tokens(column)
    return (
        column in RATIO_COLUMNS
        or lowered.endswith("_pct")
        or bool(tokens & {"ratio", "rate", "pct", "percent", "percentage"})
        or "比率" in column
        or "达成率" in column
        or "完成率" in column
        or column.endswith("率")
        # 汇率_影响_万元 names a 率 driver but holds money; the money word wins.
        or (
            any(segment.endswith("率") for segment in _column_segments(column))
            and not _names_money(column)
        )
    )


def _column_segments(column: str) -> list[str]:
    """营业利润_差异率_同口径 -> [营业利润, 差异率, 同口径]; the unit word can sit mid-name."""
    return [segment for segment in re.split(r"[_\-\s/]+", column) if segment]


def _names_money(column: str) -> bool:
    """A money unit segment (…_万元) or an English amount word (revenue_…) says the column is money."""
    return bool(_column_tokens(column) & MONEY_TOKENS) or any(
        segment in MONEY_UNIT_SEGMENTS for segment in _column_segments(column)
    )


def _is_day_column(column: str) -> bool:
    if _names_money(column):
        return False  # revenue_last_30_days, 应收_逾期_90_天_万元: money over a day window
    segments = _column_segments(column)
    return bool(_column_tokens(column) & {"days", "dso"}) or any(
        "天数" in segment or segment == "天" for segment in segments
    )


def _is_amount_column(column: str) -> bool:
    if column in MONEY_COLUMNS or column in {"numerator_exact", "denominator_exact"}:
        return True
    if _is_ratio_column(column) or _is_count_column(column) or _is_day_column(column):
        return False
    tokens = _column_tokens(column)
    if tokens & {"amount", "revenue", "cost", "expense", "profit", "cash", "budget", "actual", "variance"}:
        return True
    if any(segment in MONEY_UNIT_SEGMENTS for segment in _column_segments(column)):
        return True
    return any(
        token in column
        for token in (
            "收入",
            "成本",
            "费用",
            "利润",
            "毛利",
            "减值",
            "损益",
            "收益",
            "现金",
            "应收",
            "预算",
            "实际",
            "差异",
            "缺口",
        )
    )


def _row_unit(row: dict) -> Any:
    for key in ("unit", "单位"):
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _run_scope_unit(run: dict | None) -> Any:
    if not isinstance(run, dict):
        return None
    for scope_key in ("scope", "finance_scope"):
        scope = run.get(scope_key)
        if not isinstance(scope, dict):
            continue
        direct = scope.get("unit") or scope.get("单位")
        if direct not in (None, ""):
            return direct
        nested_units = [
            item.get("unit") or item.get("单位")
            for item in scope.values()
            if isinstance(item, dict) and (item.get("unit") or item.get("单位")) not in (None, "")
        ]
        if nested_units and all(unit == nested_units[0] for unit in nested_units):
            return nested_units[0]
    return None


def _named_money_unit(column: str) -> str | None:
    """单方物业费_元 in a 万元 run is still 元: a unit the column name states beats the row/scope unit."""
    named = [segment for segment in _column_segments(column) if segment in MONEY_UNIT_SEGMENTS]
    return named[-1] if named else None


def _amount_unit(row: dict, column: str, column_defs: dict[str, dict], run: dict | None) -> Any:
    row_unit = _row_unit(row)
    if str(row_unit or "").strip().lower() in FRACTION_UNITS | PERCENT_UNITS | POINT_UNITS:
        # In long-form rate results, row.unit describes value, not its money
        # numerator/denominator. Their explicit units or the run's money scope
        # remain authoritative; an unknown amount unit stays unknown.
        row_unit = None
    return (
        row.get(f"{column}_unit")
        or _named_money_unit(column)
        or row.get("amount_unit")
        or row_unit
        or column_defs.get(column, {}).get("unit")
        or _run_scope_unit(run)
    )


def _fact_unit(row: dict, column: str, column_defs: dict[str, dict], run: dict | None = None) -> Any:
    if _is_ratio_column(column):
        return "%"
    if _is_count_column(column):
        return row.get(f"{column}_unit") or "条"
    if _is_day_column(column):
        return row.get(f"{column}_unit") or "天"
    if column in QUANTITY_COLUMNS:
        return (
            row.get(f"{column}_unit")
            or row.get("quantity_unit")
            or column_defs.get(column, {}).get("unit")
        )
    if column in UNIT_PRICE_COLUMNS:
        return (
            row.get(f"{column}_unit")
            or row.get("price_unit")
            or column_defs.get(column, {}).get("unit")
        )
    if _is_amount_column(column):
        return _amount_unit(row, column, column_defs, run)
    if column == "value" and _row_unit(row) not in (None, ""):
        return _row_unit(row)
    return column_defs.get(column, {}).get("unit")


def _is_points(column: Any, unit: Any) -> bool:
    """A long-form value in 百分点 (result_semantics.POINT_UNITS): a difference of two percentages."""
    return column == "value" and str(unit or "").strip() == POINTS_UNIT


def _points_display(exact: str) -> str:
    """3.3 as 「3.30 个百分点」, as the result area shows it (businessResults.ts decimalToFixed): written as it is,
    never ×100, two places rounded half away from zero, thousands grouped, and never -0.00."""
    try:
        with localcontext() as context:
            context.prec = 100
            value = Decimal(exact).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return exact
    if not value.is_finite():
        return exact
    return f"{value.copy_abs() if value == 0 else value:,f}{POINTS_SUFFIX}"


def _display_value(exact: str, column: str, unit: Any) -> str:
    if _is_points(column, unit):
        return _points_display(exact)
    if _is_ratio_column(column):
        try:
            percent = (
                Decimal(exact)
                if column.endswith("_pct")
                else Decimal(exact) * Decimal(100)
            )
            return f"{percent.quantize(Decimal('0.01'))}%"
        except InvalidOperation:
            return exact
    suffix = f" {unit}" if unit else ""
    return f"{_grouped(exact, column)}{suffix}"


def _grouped(exact: str, column: str) -> str:
    """Money with thousands separators. 53,262,500 is read; 53262500 is counted.

    The exact value is what every check compares against, so the separators are
    a display choice and nothing else reads this string as a number.
    """
    if not _is_amount_column(column):
        return exact
    try:
        value = Decimal(exact)
    except InvalidOperation:
        return exact
    whole, _, fraction = exact.partition(".")
    del whole
    grouped = f"{value:,f}" if fraction else f"{value:,}"
    return grouped


def _label(row: dict, column: str) -> str:
    parts = [str(_row_metric(row, column))]
    if column != parts[0]:
        parts.append(column)
    for key in ("scenario", "period"):
        if row.get(key):
            parts.append(str(row[key]))
    return " / ".join(parts)


def _row_metric(row: dict, column: str) -> str:
    metric = row.get("metric")
    if metric not in (None, ""):
        return str(metric)
    metric_key = row.get("metric_key")
    if metric_key not in (None, ""):
        return str(metric_key)
    return column


def _is_fact_value(value: Any, column: str) -> bool:
    if (
        column in MONEY_COLUMNS
        or column in RATIO_COLUMNS
        or column in EXACT_VALUE_COLUMNS
        or _is_count_column(column)
        or column in QUANTITY_COLUMNS
        or column in UNIT_PRICE_COLUMNS
    ):
        return True
    try:
        return not isinstance(value, bool) and Decimal(str(value)).is_finite()
    except InvalidOperation:
        return False


def _relative_materiality(
    row: dict, column: str, signed_value: Decimal, magnitude: Decimal, materiality: dict
) -> dict:
    configured = materiality.get("relative") if isinstance(materiality, dict) else None
    if not configured:
        return {"enabled": False, "is_material": False, "status": "not_configured"}
    denominator = configured["denominator"]
    denominator_value = _relative_denominator(row, column, denominator)
    threshold = Decimal(configured["threshold"])
    payload = {
        "enabled": True,
        "threshold": configured["threshold"],
        "denominator": denominator,
        "negative_policy": configured["negative_policy"],
        "denominator_value": None,
        "ratio": None,
        "absolute_ratio": None,
        "is_material": False,
        "status": "not_applicable",
    }
    if denominator_value is None:
        return payload
    if denominator_value == 0:
        payload["denominator_value"] = "0"
        payload["status"] = "denominator_zero"
        return payload
    signed_denominator = denominator_value
    display_denominator = abs(denominator_value) if configured["negative_policy"] == "absolute" else denominator_value
    signed_ratio = signed_value / signed_denominator
    absolute_ratio = abs(magnitude) / abs(signed_denominator)
    ratio = absolute_ratio if configured["negative_policy"] == "absolute" else signed_ratio
    payload["denominator_value"] = format(display_denominator, "f")
    payload["ratio"] = format(ratio.normalize(), "f")
    payload["absolute_ratio"] = format(absolute_ratio.normalize(), "f")
    payload["is_material"] = absolute_ratio >= threshold
    payload["status"] = (
        "negative_denominator"
        if configured["negative_policy"] == "signed" and signed_denominator < 0
        else "complete"
    )
    return payload


def _relative_denominator(row: dict, column: str, denominator: str) -> Decimal | None:
    candidates: list[Decimal] = []
    for key in ("baseline", "actual"):
        value = row.get(key)
        if value is None:
            candidates.append(None)  # type: ignore[arg-type]
            continue
        try:
            candidates.append(Decimal(str(value)))
        except InvalidOperation:
            candidates.append(None)  # type: ignore[arg-type]
    baseline, actual = candidates if len(candidates) == 2 else (None, None)
    if denominator == "baseline_abs":
        return baseline
    if denominator == "actual_abs":
        return actual
    if denominator == "max_abs":
        values = [abs(v) for v in (baseline, actual) if v is not None]
        return max(values) if values else None
    return None


def _column_defs(result: dict) -> dict[str, dict]:
    definitions = {}
    for item in result.get("columns", []):
        if isinstance(item, dict):
            name = str(item.get("name", ""))
            if name:
                definitions[name] = item
        else:
            definitions[str(item)] = {"name": str(item)}
    return definitions


def _column_type(column_defs: dict[str, dict], column: str) -> str:
    return str(column_defs.get(column, {}).get("type") or "").upper()


def _is_decimal_column_type(column_type: str) -> bool:
    normalized = column_type.split("(", 1)[0].strip().upper()
    first = normalized.split()[0] if normalized else ""
    return normalized == "DOUBLE PRECISION" or first in {
        "BIGINT",
        "DECIMAL",
        "DOUBLE",
        "FLOAT",
        "HUGEINT",
        "INT",
        "INTEGER",
        "NUMERIC",
        "REAL",
        "SMALLINT",
        "TINYINT",
        "UBIGINT",
        "UHUGEINT",
        "UINTEGER",
        "USMALLINT",
        "UTINYINT",
    }


def _is_count_column(column: str) -> bool:
    return column in COUNT_COLUMNS or column.endswith("_count")


def _include_generic_member(row: dict, column: str, column_defs: dict[str, dict]) -> bool:
    if column in META_COLUMNS or column not in row:
        return False
    column_type = _column_type(column_defs, column)
    if column_type:
        return _is_decimal_column_type(column_type) or _is_count_column(column)
    value = row.get(column)
    if value is None:
        return column in MONEY_COLUMNS or column in RATIO_COLUMNS or _is_count_column(column)
    return _is_fact_value(value, column)


def _include_fact_column(row: dict, column: str, column_defs: dict[str, dict]) -> bool:
    if column in META_COLUMNS or column not in row or row.get(column) is None:
        return False
    column_type = _column_type(column_defs, column)
    if not column_type:
        return _is_fact_value(row.get(column), column)
    if _is_decimal_column_type(column_type):
        return True
    return (
        column
        in (
            MONEY_COLUMNS
            | RATIO_COLUMNS
            | EXACT_VALUE_COLUMNS
            | QUANTITY_COLUMNS
            | UNIT_PRICE_COLUMNS
        )
        or _is_count_column(column)
    ) and _is_fact_value(row.get(column), column)


def _is_ratio_result(columns: list[str]) -> bool:
    return {"numerator", "denominator", "ratio"} <= set(columns)


def _evidence_groups_for_run(run: dict, facts: list[dict]) -> list[dict]:
    result = run.get("result", {})
    rows = result.get("rows", [])
    column_defs = _column_defs(result)
    columns = list(column_defs)
    if not isinstance(rows, list):
        return []
    by_cell = {(fact["row"], fact["column"]): fact for fact in facts}
    method = result.get("method")
    if method == "revenue_minus_cost_minus_expense" or (
        {"contribution", "profit_impact"} & set(columns)
        and any(isinstance(row, dict) and row.get("metric") for row in rows)
    ):
        return _profit_bridge_groups(run, rows, columns, by_cell)
    if _is_ratio_result(columns):
        return [
            _row_evidence_group(
                run,
                index,
                row,
                columns,
                by_cell,
                group_type="ratio",
                member_columns=["numerator", "denominator", "ratio"],
            )
            for index, row in enumerate(rows)
            if isinstance(row, dict)
        ]
    if method in {"quantity_then_price", "base_weights_with_interaction", "volume_mix_price"}:
        return [
            _row_evidence_group(
                run,
                index,
                row,
                columns,
                by_cell,
                group_type="price_quantity_bridge",
                member_columns=([
                    "total_variance", "volume_contribution", "mix_contribution", "price_contribution", "residual", "actual", "baseline"
                ] if method == "volume_mix_price" else [
                    "total_variance",
                    "quantity_contribution",
                    "price_contribution",
                    "interaction",
                    "residual",
                    "actual",
                    "baseline",
                ]),
            )
            for index, row in enumerate(rows)
            if isinstance(row, dict)
        ]
    return [
        _row_evidence_group(
            run,
            index,
            row,
            columns,
            by_cell,
            group_type="calculation_row",
            member_columns=[
                column
                for column in columns
                if _include_generic_member(row, column, column_defs)
            ],
        )
        for index, row in enumerate(rows)
        if isinstance(row, dict)
    ]


def _profit_bridge_groups(
    run: dict, rows: list[dict], columns: list[str], by_cell: dict
) -> list[dict]:
    grouped: dict[tuple, list[tuple[int, dict]]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        grouped.setdefault(_bridge_scope_key(row), []).append((index, row))
    groups = []
    for key, items in grouped.items():
        members = []
        for index, row in items:
            metric = row.get("metric", f"row_{index}")
            for column in (
                "contribution",
                "profit_impact",
                "amount_change",
                "actual",
                "baseline",
            ):
                members.append(
                    _evidence_member(
                        index,
                        row,
                        column,
                        columns,
                        by_cell,
                        semantic_role=f"{metric}.{column}",
                    )
                )
        label = "利润桥闭合依据"
        if key:
            label = f"{label} / " + " / ".join(f"{k}={v}" for k, v in key)
        groups.append(
            _group_payload(
                run,
                group_type="profit_bridge",
                label=label,
                members=members,
                row=None,
            )
        )
    return groups


def _row_evidence_group(
    run: dict,
    index: int,
    row: dict,
    columns: list[str],
    by_cell: dict,
    *,
    group_type: str,
    member_columns: list[str],
) -> dict:
    label = row.get("metric") or row.get("product") or f"结果行 {index + 1}"
    return _group_payload(
        run,
        group_type=group_type,
        label=str(label),
        members=[
            _evidence_member(index, row, column, columns, by_cell)
            for column in member_columns
        ],
        row=index,
    )


def _group_payload(
    run: dict, *, group_type: str, label: str, members: list[dict], row: int | None
) -> dict:
    factual = [m for m in members if m.get("fact_id")]
    missing = [m for m in members if m.get("state") == "missing"]
    closure = _closure_check(group_type, members)
    status = closure["status"] if closure["status"] != "passed" else "complete"
    if missing:
        status = "missing_data"
    elif status == "complete" and any(m.get("comparison_status") == "partial" for m in members):
        # The lines add up, but one of them compares an account only one side books (缺项).
        status = "partial"
    return {
        "id": _hash(
            {
                "kind": "finance-evidence-group-v1",
                "run_id": run["id"],
                "output_hash": run.get("output_hash"),
                "group_type": group_type,
                "row": row,
                "label": label,
            }
        ),
        "run_id": run["id"],
        "group_type": group_type,
        "label": label,
        "row": row,
        "status": status,
        "closure": closure,
        "members": members,
        "fact_ids": [m["fact_id"] for m in factual],
    }


def _evidence_member(
    row_index: int,
    row: dict,
    column: str,
    columns: list[str],
    by_cell: dict,
    *,
    semantic_role: str | None = None,
) -> dict:
    fact = by_cell.get((row_index, column))
    state = _cell_state(row, column, columns)
    payload = {
        "row": row_index,
        "column": column,
        "semantic_role": semantic_role or (fact.get("semantics", {}).get("role") if fact else _fact_role(column)),
        "label": _label(row, column),
        "state": state,
        "fact_id": fact["id"] if fact else None,
        "value": fact["value"] if fact else None,
        "display_value": fact["display_value"] if fact else None,
        "unit": fact.get("unit") if fact else _row_unit(row),
        "scope": _row_scope(row),
        "source_row_count": (
            fact.get("source_trace", {}).get("source_row_count") if fact else 0
        ),
        "evidence_eligibility": fact.get("evidence_eligibility", {}) if fact else {},
    }
    if state in {"missing", "not_applicable"}:
        payload["reason"] = (
            "结果列存在但本行未产生可核验数值"
            if state == "missing"
            else "当前计算方法未定义该分项"
        )
    if row.get("comparison_status") == "partial":
        payload["comparison_status"] = "partial"
    return payload


def _cell_state(row: dict, column: str, columns: list[str]) -> str:
    if column not in columns:
        return "not_applicable"
    value = row.get(column)
    if value is None:
        if column == "ratio" and row.get("numerator") is not None and _is_zero(row.get("denominator")):
            return "not_applicable"
        return "missing"
    return _fact_state(value)


def _is_zero(value: Any) -> bool:
    try:
        return Decimal(str(value)) == 0
    except InvalidOperation:
        return False


def _fact_state(value: Any) -> str:
    try:
        return "observed_zero" if Decimal(str(value)) == 0 else "nonzero"
    except InvalidOperation:
        return "missing"


def _state_label(state: str) -> str:
    return {
        "observed_zero": "已计算为零",
        "nonzero": "已计算",
        "missing": "缺少数据",
        "not_applicable": "不适用",
    }.get(state, str(state))


def _fact_state_counts(facts: list[dict]) -> dict:
    counts = {"nonzero": 0, "observed_zero": 0}
    for fact in facts:
        state = fact.get("state", fact.get("semantics", {}).get("state", "nonzero"))
        counts[state] = counts.get(state, 0) + 1
    return counts


def _evidence_group_statuses(groups: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for group in groups:
        if not isinstance(group, dict):
            continue
        status = str(group.get("status", "unknown"))
        counts[status] = counts.get(status, 0) + 1
    return counts


def _closure_check(group_type: str, members: list[dict]) -> dict:
    if group_type == "profit_bridge":
        return _profit_bridge_closure(members)
    if group_type == "price_quantity_bridge":
        return _price_quantity_closure(members)
    if group_type == "ratio":
        return _ratio_closure(members)
    return {"status": "unsupported", "equation": None, "message": "未声明可复算闭合规则"}


def _profit_bridge_closure(members: list[dict]) -> dict:
    contribution = {
        str(member.get("semantic_role", "")).split(".", 1)[0]: member
        for member in members
        if member.get("column") == "contribution"
    }
    required = ("revenue", "cost", "expense", "profit")
    missing = [
        metric
        for metric in required
        if contribution.get(metric, {}).get("value") is None
    ]
    if missing:
        return {
            "status": "missing_data",
            "equation": "profit = revenue + cost + expense",
            "missing": missing,
        }
    consistency = _member_consistency([contribution[metric] for metric in required])
    if consistency:
        return consistency
    values = {metric: Decimal(str(contribution[metric]["value"])) for metric in required}
    expected = values["revenue"] + values["cost"] + values["expense"]
    difference = values["profit"] - expected
    return {
        "status": "passed" if difference == 0 else "closure_mismatch",
        "equation": "profit = revenue + cost + expense",
        "expected": format(expected, "f"),
        "actual": format(values["profit"], "f"),
        "difference": format(difference, "f"),
        "inputs": {metric: format(value, "f") for metric, value in values.items()},
    }


def _ratio_closure(members: list[dict]) -> dict:
    by_column = {member.get("column"): member for member in members}
    numerator = by_column.get("numerator")
    denominator = by_column.get("denominator")
    ratio = by_column.get("ratio")
    missing = [
        column
        for column, member in (("numerator", numerator), ("denominator", denominator))
        if not member or member.get("value") is None
    ]
    if missing:
        return {
            "status": "missing_data",
            "equation": "ratio = numerator / denominator",
            "missing": missing,
        }
    amount_consistency = _member_consistency([numerator, denominator])
    if amount_consistency:
        return amount_consistency
    scope_consistency = _scope_consistency([m for m in (numerator, denominator, ratio) if m])
    if scope_consistency:
        return scope_consistency
    numerator_value = Decimal(str(numerator["value"]))
    denominator_value = Decimal(str(denominator["value"]))
    inputs = {
        "numerator": format(numerator_value, "f"),
        "denominator": format(denominator_value, "f"),
    }
    if denominator_value == 0:
        if ratio and ratio.get("value") is not None:
            return {
                "status": "closure_mismatch",
                "equation": "ratio = numerator / denominator",
                "expected": None,
                "actual": str(ratio.get("value")),
                "difference": None,
                "inputs": inputs,
                "denominator_status": "zero",
            }
        return {
            "status": "not_applicable",
            "equation": "ratio = numerator / denominator",
            "expected": None,
            "actual": None,
            "difference": None,
            "inputs": inputs,
            "denominator_status": "zero",
        }
    if not ratio or ratio.get("value") is None:
        return {
            "status": "missing_data",
            "equation": "ratio = numerator / denominator",
            "missing": ["ratio"],
            "inputs": inputs,
        }
    actual = Decimal(str(ratio["value"]))
    with localcontext() as context:
        context.prec = max(28, len(actual.as_tuple().digits))
        expected = numerator_value / denominator_value
        difference = actual - expected
    return {
        "status": "passed" if difference == 0 else "closure_mismatch",
        "equation": "ratio = numerator / denominator",
        "expected": format(expected, "f"),
        "actual": format(actual, "f"),
        "difference": format(difference, "f"),
        "inputs": inputs,
        "denominator_status": "negative" if denominator_value < 0 else "positive",
    }


def _price_quantity_closure(members: list[dict]) -> dict:
    by_column = {member.get("column"): member for member in members}
    if "volume_contribution" in by_column:
        required = ("volume_contribution", "mix_contribution", "price_contribution", "residual", "total_variance")
        if any(by_column.get(key, {}).get("value") is None for key in required):
            return {"status": "missing_data", "equation": "total_variance = volume + mix + price; residual = 0"}
        consistency = _member_consistency([by_column[key] for key in required])
        if consistency:
            return consistency
        values = {key: Decimal(str(by_column[key]["value"])) for key in required}
        expected = sum(values[key] for key in required[:3])
        passed = expected == values["total_variance"] and values["residual"] == 0
        return {"status": "passed" if passed else "closure_mismatch",
                "equation": "total_variance = volume + mix + price; residual = 0",
                "expected": format(expected, "f"), "actual": format(values["total_variance"], "f"),
                "difference": format(values["total_variance"] - expected, "f"),
                "inputs": {key: format(value, "f") for key, value in values.items()}}
    required = ("quantity_contribution", "price_contribution", "interaction", "residual", "total_variance")
    missing = [
        column for column in required if by_column.get(column, {}).get("value") is None
    ]
    if missing:
        return {
            "status": "missing_data",
            "equation": "total_variance = quantity_contribution + price_contribution + interaction + residual",
            "missing": missing,
        }
    consistency = _member_consistency([by_column[column] for column in required])
    if consistency:
        return consistency
    values = {column: Decimal(str(by_column[column]["value"])) for column in required}
    expected = (
        values["quantity_contribution"]
        + values["price_contribution"]
        + values["interaction"]
        + values["residual"]
    )
    difference = values["total_variance"] - expected
    return {
        "status": "passed" if difference == 0 else "closure_mismatch",
        "equation": "total_variance = quantity_contribution + price_contribution + interaction + residual",
        "expected": format(expected, "f"),
        "actual": format(values["total_variance"], "f"),
        "difference": format(difference, "f"),
        "inputs": {column: format(value, "f") for column, value in values.items()},
    }


def _member_consistency(members: list[dict]) -> dict | None:
    units = {member.get("unit") for member in members if member.get("unit")}
    if len(units) > 1:
        return {
            "status": "unit_mismatch",
            "equation": None,
            "units": sorted(str(unit) for unit in units),
        }
    return _scope_consistency(members)


def _scope_consistency(members: list[dict]) -> dict | None:
    scopes = {
        tuple(sorted((member.get("scope") or {}).items()))
        for member in members
        if member.get("scope")
    }
    if len(scopes) > 1:
        return {
            "status": "scope_mismatch",
            "equation": None,
            "scopes": [dict(scope) for scope in sorted(scopes, key=repr)],
        }
    return None


def _bridge_scope_key(row: dict) -> tuple:
    skip = (
        MONEY_COLUMNS
        | RATIO_COLUMNS
        | META_COLUMNS
        | {
            "profit_impact",
            "quantity_contribution",
            "price_contribution",
            "amount_change",
            "amount_change_display",
            "profit_impact_display",
            "total_variance",
            "interaction",
            "residual",
            "display_value",
            "evidence",
            "source_rows",
            "semantics",
            "actual_scope",
            "baseline_scope",
        }
    )
    return tuple(
        sorted(
            (key, str(value))
            for key, value in row.items()
            if key not in skip and value not in (None, "")
        )
    )


def _row_scope(row: dict) -> dict:
    scope = {}
    for key in ("ledger", "organization", "period", "currency"):
        if row.get(key) not in (None, ""):
            scope[key] = str(row[key])
    for side in ("actual_scope", "baseline_scope"):
        if isinstance(row.get(side), dict):
            for key in ("ledger", "organization", "period", "currency"):
                value = row[side].get(key)
                if value not in (None, ""):
                    scope[f"{side}.{key}"] = str(value)
    return scope


def _closure_label(closure: dict) -> str:
    status = closure.get("status")
    if status == "passed":
        return (
            f"通过，{closure.get('equation')}，"
            f"实际 {closure.get('actual')}，复算 {closure.get('expected')}，差额为零"
        )
    return {
        "closure_mismatch": (
            f"不匹配，{closure.get('equation')}，实际 {closure.get('actual')}，"
            f"复算 {closure.get('expected')}，差额 {closure.get('difference')}"
        ),
        "scope_mismatch": "范围不一致",
        "unit_mismatch": "单位不一致",
        "missing_data": "缺少闭合所需数据",
    }.get(str(status), str(status))


def _currency_context_issue(prefix: str, candidates: list[dict], facts: list[dict], position: int,
                            *, monetary_unit=False, after=""):
    """Bind explicit amount currency labels, including aggregate scope, to facts."""
    aggregate = r"(?:合计|总计|共计|加总|总额|合并金额|合并余额)"
    is_aggregate = bool(re.search(aggregate, prefix))
    caution = re.search(
        rf"(?:不能|不应|不得|不可|不宜|不要|禁止|并非|不是)\s*(?:直接|简单)?\s*{aggregate}", prefix)
    if caution and not re.search(
        r"不是|并非|并不|未必", prefix[:caution.start()]
    ):
        return None
    currencies = {str(fact.get("metric_identity", {}).get("currency", "")).upper()
                  for fact in facts if fact.get("unit") in MONEY_UNIT_SEGMENTS} - {""}
    aliases = {"CNY": ("人民币", "RMB"), "USD": ("美元", "美金"), "HKD": ("港元", "港币"),
               "EUR": ("欧元",), "GBP": ("英镑",), "JPY": ("日元",), "AUD": ("澳元",),
               "CAD": ("加元",), "CHF": ("瑞郎",)}
    named = {currency for currency in currencies | aliases.keys() if any(
        re.search(r"(?<![A-Za-z])" + re.escape(label) + r"(?![A-Za-z])", prefix, re.I)
        for label in (currency, *aliases.get(currency, ())))}
    named.update(currency for currency in currencies | aliases.keys() if any(
        re.match(r"\s*(?:亿元|万元|元)?\s*" + re.escape(label) + r"(?![A-Za-z])", after, re.I)
        for label in (currency, *aliases.get(currency, ()))))
    matched = {str(fact.get("metric_identity", {}).get("currency", "")).upper() for fact in candidates}
    multi_scope = re.search(r"(?:跨|多|两|各|全部|所有)(?:个|种)?币种", prefix)
    if not named and not multi_scope and (not is_aggregate or not monetary_unit or len(currencies) < 2):
        return None
    if not multi_scope and len(named) == 1 and named <= matched:
        return None
    return {"code": "fact_currency_mismatch", "severity": "warning", "position": position,
            "message": "正文金额的币种必须匹配引用事实；其他币种的同值金额不能替代，也不能证明跨币种总额。",
            "referenced_currencies": sorted(currencies), "named_currencies": sorted(named)}


def _fact_context_issues(
    body: str, facts: list[dict], evidence_groups: list[dict] | None = None, *, runs=(), body_template=None,
    trusted_fact_ids=(), performance_facts=(), qualification_facts=(),
) -> list[dict]:
    """Match complete numeric tokens to a compatible fact within their clause.

    A shared number is not an identity: select by the nearest financial label,
    then validate its unit and change semantics. Never match 5 inside 15.
    """
    from foundry.finance_claim_semantics import check_claim_semantics

    issues = check_claim_semantics(body, facts, runs=runs, body_template=body_template, trusted_fact_ids=trusted_fact_ids,
                                   performance_facts=performance_facts, qualification_facts=qualification_facts,
                                   referenced_fact_ids=[fact["id"] for fact in facts])
    closure_check = _body_closure_check(body, facts, evidence_groups or [])
    issues.extend(closure_check["issues"])
    closure_token_positions = closure_check["token_positions"]
    unit_pattern = (r"(?:百万元|亿元|万元|千元|元)(?:\s*[/／·⋅×*]\s*\w+)*(?:\s*人民币)?"
                    r"|[%％]|个?\s*百分点|百分比|pct|条|件")
    # A verified template occurrence binds one exact fact, even when another
    # currency has the same number. Handwritten numbers keep candidate matching.
    bound_currency_facts = {}
    if isinstance(body_template, str):
        rendered, _ = render_fact_template(body_template, facts)
        offset = body.find(rendered.strip())
        leading = len(rendered) - len(rendered.lstrip())
        by_id = {fact["id"]: fact for fact in facts}
        if offset >= 0:
            for match in FACT_TOKEN.finditer(body_template):
                fact = by_id.get(match[1])
                if fact:
                    before, _ = render_fact_template(body_template[:match.start()], facts)
                    position = offset + len(before) - leading
                    bound_currency_facts[position] = fact
                    # Rendering inserts the fact's own unit before a conflicting
                    # suffix. Check the authored suffix against this exact token.
                    # A complete word boundary keeps 元旦/元素 out of unit syntax.
                    written = re.match(
                        rf"\s*(?:人民币\s*)?([%％](?![/／·⋅×*])|(?:{unit_pattern})(?![\w/／·⋅×*]))",
                        body_template[match.end():], re.I,
                    )
                    if written and not _body_unit_fits_fact(written[1], fact):
                        issues.append({"code": "fact_unit_mismatch", "severity": "warning",
                                       "message": "正文单位与引用事实单位不一致。",
                                       "fact_id": fact["id"], "position": position})
    for token in _body_numbers(body):
        if token["start"] in closure_token_positions:
            continue
        value = Decimal(_normalize_number(token["text"]))
        candidates = [f for f in facts if _token_matches_fact(token["text"], f)]
        if not candidates:
            continue
        start = token["start"]
        end = start + len(token["text"])
        clause_prefix = re.split(r"[，,；;。\n|]", body[:start])[-1]
        unit_match = re.match(rf"\s*(?:人民币\s*)?({unit_pattern})", body[end:], re.I)
        if (not unit_match and not re.match(r"\s*(项|行|种|天|日|年|月)", body[end:])) or (
            unit_match and unit_match[1] in MONEY_UNIT_SEGMENTS
        ):
            currency_issue = _currency_context_issue(
                clause_prefix, [bound_currency_facts[start]] if start in bound_currency_facts else candidates,
                facts, start, after=body[end:],
                monetary_unit=bool(unit_match and unit_match[1] in MONEY_UNIT_SEGMENTS))
            if currency_issue:
                issues.append(currency_issue)
        prefix = clause_prefix[-60:]
        equation_parts = re.split(r"[=＝]", clause_prefix)
        is_equation_total = len(equation_parts) > 2 and not equation_parts[-1].strip()
        if is_equation_total:
            # In "利润差异 = 收入影响 20 + ... 费用影响 -5 = 5",
            # the final value belongs to the left-hand target, not the last
            # component. Keep checking each intermediate component normally.
            prefix = equation_parts[0][-60:]
        metric_matches = [(prefix.rfind(label), key) for key, label in METRIC_LABELS.items() if label in prefix]
        metric = max(metric_matches)[1] if metric_matches else None
        # '成本贡献'/'费用贡献' also name the profit effect, rather than the
        # underlying cost/expense change whose sign is reversed below.
        last_metric_position = max((at for at, _ in metric_matches), default=-1)
        impact = any(match.end() > last_metric_position for match in re.finditer(
            r"利润.{0,3}(?:影响|贡献|拖累|拉动)|(?:成本|费用)\s*贡献|profit.{0,3}(?:impact|effect)", prefix, re.I))
        # An explicitly labelled profit bridge/effect equation scopes every
        # component. Its last cost label must not flip that component into a
        # cost movement or steal the final profit-total label.
        bridge_impact = bool(re.search(
            r"利润(?:差异)?桥[^:：=＝]{0,12}[:：]|利润(?:影响|贡献)(?:合计)?\s*[=＝]",
            re.split(r"[；;。\n|]", body[:start])[-1]))
        # A bridge title supplies context only when the local component has
        # no explicit movement verb. "成本减少" still describes cost movement,
        # whose sign is opposite to its profit impact.
        movement = r"(?:增加|增长|上升|提升|减少|下降|降低)"
        local_movement = metric in {"cost", "expense"} and (
            bool(re.search(movement, prefix[last_metric_position:])) or
            bool(re.search(movement + r"(?:了)?\s*" + re.escape(METRIC_LABELS[metric]), prefix)))
        impact = impact or (bridge_impact and not local_movement)
        if impact:
            non_profit = [(at, key) for at, key in metric_matches if key != 'profit']
            metric = max(non_profit)[1] if non_profit else 'profit' if is_equation_total else None
        labelled = [f for f in candidates if not metric or f['semantics'].get('metric') == metric or f['semantics'].get('metric') not in METRIC_LABELS]
        if not labelled:
            issues.append({
                'code': 'fact_label_mismatch',
                'severity': 'warning',
                'message': '正文指标与同值引用事实不一致。',
                'position': start,
                'text': token['text'],
                'body_excerpt': _body_excerpt(body, start),
                'expected_metric': metric,
                'matched_fact_labels': [str(f.get('label')) for f in candidates],
                'matched_semantic_roles': [str(f.get('semantics', {}).get('role')) for f in candidates],
                'matched_fact_metrics': [str(f.get('semantics', {}).get('metric')) for f in candidates],
            })
            labelled = candidates
        alternatives = []
        for fact in labelled:
            found = []
            if start not in bound_currency_facts and unit_match and not _body_unit_fits_fact(unit_match[1], fact):
                found.append({'code': 'fact_unit_mismatch', 'severity': 'warning', 'message': '正文单位与引用事实单位不一致。'})
            semantic = fact['semantics']
            if semantic.get('role') == 'profit_impact' or fact['column'] in {'amount_change', 'total_variance', 'quantity_contribution', 'price_contribution', 'interaction'}:
                exact = Decimal(str(fact['value']))
                if semantic.get('role') == 'profit_impact' and semantic.get('metric') in {'cost', 'expense'} and metric in {'cost', 'expense'} and not impact:
                    exact = -exact
                positive_words = (*POSITIVE_WORDS, "拉动") if impact else POSITIVE_WORDS
                sign_words = [(prefix.rfind(w), -1) for w in NEGATIVE_WORDS if w in prefix] + [(prefix.rfind(w), 1) for w in positive_words if w in prefix]
                direction = max(sign_words)[1] if sign_words else None
                stated = abs(value) * direction if direction else value
                if (direction == 1 and value < 0) or (stated and exact and (stated > 0) != (exact > 0)):
                    found.append({'code': 'fact_direction_mismatch', 'severity': 'warning', 'message': '正文增减方向与所引用财务影响不一致。'})
            alternatives.append([{**issue, 'fact_id': fact['id'], 'position': start} for issue in found])
        # Another fact with the same value and matching label may be the correct reference.
        issues.extend(min(alternatives, key=len) if alternatives else [])
    return issues


def _body_unit_fits_fact(written: str, fact: dict) -> bool:
    """Whether the unit written after a number fits the fact: 个百分点 only a 百分点 fact, % any percentage unit
    (%, ％, pct, 百分比; a ratio column's facts read % too), anything else the fact's own unit."""
    unit = re.sub(r"\s+", "", str(fact.get("unit") or "")).lower().replace("／", "/")
    written = re.sub(r"\s+", "", written).lower().replace("／", "/")
    unit = unit.removeprefix("人民币").removesuffix("人民币")
    written = written.removeprefix("人民币").removesuffix("人民币")
    if written in {POINTS_UNIT, "个百分点"}:
        return unit == POINTS_UNIT
    if written in PERCENT_UNITS:
        return unit in PERCENT_UNITS
    return written == unit


def _body_closure_check(body: str, facts: list[dict], evidence_groups: list[dict]) -> dict:
    token_positions: set[int] = set()
    issues: list[dict] = []
    if not facts:
        return {"token_positions": token_positions, "issues": issues}
    labelled = _labeled_profit_closure_check(body, facts, evidence_groups)
    token_positions.update(labelled["token_positions"])
    issues.extend(labelled["issues"])
    for match in CLOSURE_EXPR.finditer(body):
        span_start, span_end = match.span("expr")
        context = body[max(0, span_start - 40): min(len(body), span_end + 30)]
        if not any(marker in context for marker in ("闭合", "合计", "等式", "一致")):
            continue
        if not _has_closure_expression_boundaries(body, span_start, span_end):
            continue
        target_group_types = _closure_target_group_types(body, span_start)
        if not target_group_types:
            prefix = re.split(r"[。；;\n]", body[max(0, span_start - 80):span_start])[-1]
            # An unlabelled closure may borrow identity from exactly one
            # complete referenced group. Never override an explicit metric.
            if not any(label in prefix for label in METRIC_LABELS.values()):
                referenced = {fact.get("id") for fact in facts}
                eligible = [group for group in evidence_groups
                            if group.get("status") == "complete"
                            and group.get("closure", {}).get("status") == "passed"
                            and _ordered_closure_members(group)
                            and all(member.get("fact_id") in referenced
                                    for member in _ordered_closure_members(group))]
                if len(eligible) == 1:
                    target_group_types = {eligible[0]["group_type"]}
        if not target_group_types:
            continue
        parsed = _parse_signed_closure_expression(match.group("expr"))
        if not parsed:
            continue
        matching_group = (
            _matching_body_closure_group(parsed, facts, evidence_groups, target_group_types)
            if parsed["balanced"]
            else None
        )
        if matching_group:
            for token in _body_numbers(body[span_start:span_end]):
                token_positions.add(span_start + token["start"])
            continue
        issues.append({
            "code": "body_closure_mismatch",
            "severity": "warning",
            "message": "正文闭合算式未能匹配同一完整且已闭合的证据组。",
            "position": span_start,
            "text": match.group("expr"),
            "body_excerpt": _body_excerpt(body, span_start),
            "target_group_types": sorted(target_group_types),
        })
    return {"token_positions": token_positions, "issues": issues}


def _labeled_profit_closure_check(body: str, facts: list[dict], evidence_groups: list[dict]) -> dict:
    """Bind a same-clause labelled equation to one fully cited source bridge.

    Only the four signed contributions gain profit-impact meaning. Actual or
    budget prose, another sentence and other arithmetic remain ordinary claims.
    """
    positions: set[int] = set()
    issues: list[dict] = []
    by_id = {fact.get("id"): fact for fact in facts}
    for match in LABELED_PROFIT_CLOSURE_EXPR.finditer(body):
        start, end = match.span("expr")
        if not _has_closure_expression_boundaries(body, start, end, preserve_lines=True):
            continue
        labels = [match.group(f"label{i}") for i in range(4)]
        values = [re.sub(r"\s+", "", match.group(f"value{i}")) for i in range(4)]
        parsed = _parse_signed_closure_expression("+".join(values[:3]) + "=" + values[3])
        matching = []
        if labels == ["收入", "成本", "费用", "利润"] and parsed and parsed["balanced"]:
            for group in evidence_groups:
                if not _matching_body_closure_group(parsed, facts, [group], {"profit_bridge"}):
                    continue
                members = _ordered_closure_members(group)
                if len([member for member in group.get("members", [])
                        if member.get("column") == "contribution"]) != 4:
                    continue
                if all(
                    by_id[member["fact_id"]].get("evidence_eligibility", {}).get("counts_as_amount_evidence")
                    and by_id[member["fact_id"]].get("column") == "contribution"
                    and by_id[member["fact_id"]].get("semantics", {}).get("metric") == metric
                    and _body_unit_fits_fact(match.group(f"unit{i}"), by_id[member["fact_id"]])
                    for i, (member, metric) in enumerate(zip(members, ("revenue", "cost", "expense", "profit")))
                ):
                    matching.append(group)
        if len(matching) == 1:
            positions.update(start + token["start"] for token in _body_numbers(body[start:end]))
        else:
            issues.append({
                "code": "body_closure_mismatch", "severity": "warning",
                "message": "带科目与单位的利润闭合算式必须匹配唯一完整且已引用的来源证据组。",
                "position": start, "text": match.group("expr"),
                "body_excerpt": _body_excerpt(body, start), "target_group_types": ["profit_bridge"],
            })
    return {"token_positions": positions, "issues": issues}


def _has_closure_expression_boundaries(body: str, start: int, end: int, *, preserve_lines=False) -> bool:
    whitespace = " \t\r\u00a0\u2009\u202f\u3000" if preserve_lines else None
    before = body[:start].rstrip(whitespace)[-1:]
    after = body[end:].lstrip(whitespace)[:1]
    valid_before = before in {"", "（", "(", "[", ":", "：", " ", "，", ",", "；", ";", "。", "\n"}
    valid_after = after in {"", "）", ")", "]", "，", ",", "；", ";", "。", "\n"}
    return valid_before and valid_after


def _closure_target_group_types(body: str, start: int) -> set[str]:
    prefix = re.split(r"[。；;\n]", body[max(0, start - 80):start])[-1]
    metric_matches = [
        (prefix.rfind(label), key)
        for key, label in METRIC_LABELS.items()
        if label in prefix
    ]
    metric = max(metric_matches)[1] if metric_matches else None
    if metric in {None, "revenue"} and re.search(r"量价|price[-_ ]?quantity", prefix, re.I):
        return {"price_quantity_bridge"}
    if metric == "profit":
        return {"profit_bridge"}
    return set()


def _parse_signed_closure_expression(expr: str) -> dict | None:
    normalized = expr.replace("−", "-").replace("－", "-")
    if re.search(r"[^0-9+\-=.\s]", normalized) or normalized.count("=") != 1:
        return None
    left, right = [part.strip() for part in normalized.split("=", 1)]
    if not left or not right:
        return None
    try:
        rhs = Decimal(right)
        terms = [
            Decimal(term.replace(" ", ""))
            for term in re.findall(r"[+-]?\s*\d+(?:\.\d+)?", left)
        ]
    except InvalidOperation:
        return None
    if len(terms) < 2:
        return None
    with localcontext() as context:
        # Preserve small fractional terms beside large integers during addition.
        values = [*terms, rhs]
        context.prec = max(28, max(v.adjusted() for v in values)
                           - min(v.as_tuple().exponent for v in values)
                           + len(str(len(terms))) + 2)
        balanced = sum(terms) == rhs
    return {"terms": terms, "rhs": rhs, "balanced": balanced}


def _matching_body_closure_group(
    parsed: dict, facts: list[dict], evidence_groups: list[dict], target_group_types: set[str]
) -> dict | None:
    if not target_group_types:
        return None
    referenced_ids = {fact.get("id") for fact in facts}
    for group in evidence_groups:
        if not isinstance(group, dict) or group.get("status") != "complete":
            continue
        if group.get("group_type") not in target_group_types:
            continue
        closure = group.get("closure") or {}
        if closure.get("status") != "passed":
            continue
        members = _ordered_closure_members(group)
        if not members or any(member.get("fact_id") not in referenced_ids for member in members):
            continue
        expected_len = 5 if group.get("group_type") == "price_quantity_bridge" else 4
        if len(members) != expected_len:
            continue
        values = [Decimal(str(member["value"])) for member in members]
        if values[:-1] != parsed["terms"] or values[-1] != parsed["rhs"]:
            continue
        return group
    return None


def _ordered_closure_members(group: dict) -> list[dict]:
    members = group.get("members") or []
    if group.get("group_type") == "profit_bridge":
        by_metric = {
            str(member.get("semantic_role", "")).split(".", 1)[0]: member
            for member in members
            if isinstance(member, dict) and member.get("column") == "contribution"
        }
        order = ("revenue", "cost", "expense", "profit")
        return [by_metric[key] for key in order if key in by_metric]
    if group.get("group_type") == "price_quantity_bridge":
        by_column = {
            member.get("column"): member
            for member in members
            if isinstance(member, dict)
        }
        order = (("volume_contribution", "mix_contribution", "price_contribution", "residual", "total_variance")
                 if "mix_contribution" in by_column else
                 ("quantity_contribution", "price_contribution", "interaction", "residual", "total_variance"))
        return [by_column[key] for key in order if key in by_column]
    return []


def _body_excerpt(body: str, start: int, radius: int = 24) -> str:
    left = max(0, start - radius)
    right = min(len(body), start + radius)
    return body[left:right]


def _token_matches_fact(text: str, fact: dict) -> bool:
    value = Decimal(_normalize_number(text))
    options = _numbers_from_text(str(fact.get('display_value', ''))) | {_fact_number(fact)}
    if any(value == Decimal(option) for option in options):
        return True
    return fact['semantics'].get('role') == 'profit_impact' and any(abs(value) == abs(Decimal(option)) for option in options)


def _presentation_allowed_numbers_and_issues(claims: list[dict], by_id: dict[str, dict]) -> dict:
    numbers: dict[str, set[str]] = {}
    issues: list[dict] = []
    for claim in claims:
        if not isinstance(claim, dict) or "presentation" not in claim:
            continue
        fact_id = claim.get("fact_id")
        fact = by_id.get(fact_id) if isinstance(fact_id, str) else None
        result, issue = _presentation_number(claim, fact)
        if issue:
            issues.append(issue)
        elif result:
            numbers.setdefault(result["number"], set()).add(result["unit"])
    return {"numbers": numbers, "issues": issues}


def _presentation_number(claim: dict, fact: dict | None) -> tuple[dict | None, dict | None]:
    presentation = claim.get("presentation")
    base_issue = {
        "code": "invalid_presentation",
        "severity": "error",
        "message": "claim presentation must be derived from the bound calculation fact.",
        "fact_id": claim.get("fact_id"),
    }
    if claim.get("basis") != "calculation" or not fact:
        return None, {**base_issue, "reason": "presentation_requires_bound_fact"}
    if not _claim_matches_fact(claim, fact):
        return None, {**base_issue, "reason": "claim_does_not_match_fact"}
    if not isinstance(presentation, dict):
        return None, {**base_issue, "reason": "presentation_must_be_object"}
    if set(presentation) != {"decimal_places", "scale", "rounding"}:
        return None, {**base_issue, "reason": "unsupported_presentation_fields"}
    decimal_places = presentation.get("decimal_places")
    scale = presentation.get("scale")
    rounding = presentation.get("rounding")
    if isinstance(decimal_places, bool) or not isinstance(decimal_places, int) or not 0 <= decimal_places <= 6:
        return None, {**base_issue, "reason": "decimal_places_out_of_range"}
    if scale not in {"identity", "percent"} or rounding != "half_up":
        return None, {**base_issue, "reason": "unsupported_presentation_policy"}
    try:
        value = Decimal(str(fact["value"]))
    except (InvalidOperation, KeyError):
        return None, {**base_issue, "reason": "fact_value_not_decimal"}
    if not value.is_finite():
        return None, {**base_issue, "reason": "fact_value_not_finite"}
    if scale == "percent":
        if not _fact_is_ratio(fact):
            return None, {**base_issue, "reason": "percent_requires_ratio_fact"}
        value = _fact_percent_value(fact, value)
    quant = Decimal("1") if decimal_places == 0 else Decimal("1").scaleb(-decimal_places)
    try:
        with localcontext() as ctx:
            ctx.prec = max(28, len(value.as_tuple().digits) + decimal_places + 4)
            rounded = value.quantize(quant, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None, {**base_issue, "reason": "presentation_rounding_failed"}
    rendered = format(rounded, f".{decimal_places}f")
    # A %/pct row is already a percentage: identity rounds it and writes it with %, as a ratio's percent scale does.
    column = str(fact.get("column") or "")
    # A *_pct ratio column also holds a percentage (3.3 is 3.3%), so identity writes it with % as well.
    percent_row = scale == "identity" and (_fact_has_percent_unit(fact) or (_is_ratio_column(column) and column.endswith("_pct")))
    unit = "%" if scale == "percent" else PERCENT_ROW_UNIT if percent_row else str(fact.get("unit") or "").strip()
    if scale == "percent" or percent_row:
        rendered += "%"
    return {"number": _normalize_number(rendered), "unit": unit}, None


def _claim_matches_fact(claim: dict, fact: dict) -> bool:
    return (
        claim.get("run_id") == fact.get("run_id")
        and claim.get("row") == fact.get("row")
        and claim.get("column") == fact.get("column")
        and _decimal_equal(claim.get("value"), fact.get("value"))
    )


def _fact_is_ratio(fact: dict) -> bool:
    """A fact that stores a fraction and so may be written as a percentage. A %, ％, pct or 百分比 row already is one."""
    if _fact_has_percent_unit(fact):
        return False
    unit = str(fact.get("unit") or "").strip().lower()
    semantics = fact.get("semantics") if isinstance(fact.get("semantics"), dict) else {}
    return unit in {"%", "比率", "ratio"} or semantics.get("role") == "ratio"


def _fact_percent_value(fact: dict, value: Decimal) -> Decimal:
    if str(fact.get("column") or "").endswith("_pct"):
        return value
    return value * Decimal(100)


EXPLICIT_PRESENTATION_UNITS = ("亿元", "万元", "千元", "元", "%", "比率")
# The unit a %/pct row's identity presentation allows: only a number written with %. A ratio's percent presentation
# keeps the older leniency of also passing its bare decimal (0.9453 for 94.53%); that is left as it was.
PERCENT_ROW_UNIT = "%（百分数行）"


def _is_percent_text(text: str) -> bool:
    return str(text).endswith(("%", "％"))


def _presentation_token_unit_matches(body: str, token: dict, allowed_units: set[str]) -> bool:
    explicit = _explicit_unit_for_token(body, token)
    if explicit is None:
        return any(unit != PERCENT_ROW_UNIT for unit in allowed_units)
    return any(_units_compatible(explicit, unit) for unit in allowed_units)


def _explicit_unit_for_token(body: str, token: dict) -> str | None:
    text = str(token.get("text") or "")
    if _is_percent_text(text):
        return "%"
    start = token.get("start")
    if not isinstance(start, int):
        return None
    end = token.get("end", start + len(text))
    suffix = body[end:]
    match = re.match(r"\s*(" + "|".join(map(re.escape, EXPLICIT_PRESENTATION_UNITS)) + r")", suffix)
    return match.group(1) if match else None


def _units_compatible(explicit: str, expected: str) -> bool:
    if explicit == expected:
        return True
    return explicit == "%" and expected in {"%", "比率", "ratio", PERCENT_ROW_UNIT}


def _validate_calculation_claim(analysis, claim: dict, run_ids: list[str]) -> dict | None:
    run_id = claim.get("run_id")
    row = claim.get("row")
    column = claim.get("column")
    expected = claim.get("value")
    try:
        run = analysis.get_run(run_id)
        if run["id"] not in run_ids or run.get("execution_status") != "succeeded":
            raise ValueError("claim requires a referenced successful run")
        if isinstance(row, bool) or not isinstance(row, int) or row < 0:
            raise ValueError("claim row must be a non-negative integer")
        actual = run["result"]["rows"][row][column]
        matches = _decimal_equal(actual, expected)
    except Exception:
        return {
            "code": "invalid_claim_location",
            "severity": "error",
            "message": "calculation claim has an invalid output location.",
            "run_id": run_id,
            "row": row,
            "column": column,
        }
    if not matches:
        return {
            "code": "claim_value_mismatch",
            "severity": "error",
            "message": (
                "claim value differs from execution result "
                f"(run_id={run['id']}, row={row}, column={column}, "
                f"expected={expected}, actual={actual})."
            ),
            "run_id": run["id"],
            "row": row,
            "column": column,
            "expected": str(expected),
            "actual": str(actual),
        }
    return None


def _fact_number(fact: dict) -> str:
    value = Decimal(str(fact["value"]))
    column = str(fact.get("column") or "")
    # A *_pct ratio column holds a percentage (3.3 is 3.3%), as _fact_percent_value reads it.
    if _is_ratio_column(column) and column.endswith("_pct"):
        value /= 100
    return _normalize_number(str(value))


def _fact_has_percent_unit(fact: dict) -> bool:
    """A value whose row unit is %, ％, pct or 百分比 already holds a percentage (result_semantics.PERCENT_UNITS): 3.3 is
    written 3.3%. A ratio column's facts also read unit % (_fact_unit), but that % is how its fraction is shown."""
    if _is_ratio_column(str(fact.get("column") or "")):
        return False
    return re.sub(r"\s+", "", str(fact.get("unit") or "")).lower() in PERCENT_UNITS


def _percent_number_values(facts: list[dict]) -> set[Decimal]:
    values = set()
    for fact in facts:
        if not _fact_has_percent_unit(fact):
            continue
        try:
            values.add(Decimal(str(fact["value"])))
        except (InvalidOperation, KeyError, TypeError):
            continue
    return values


def _is_cited_percent_number(text: str, values: set[Decimal]) -> bool:
    """A body number written with % that equals a cited %, pct or 百分比 value as written (3.3 is 3.30%)."""
    if not values or not _is_percent_text(text):
        return False
    try:
        return Decimal(text[:-1].replace(",", "")) in values
    except InvalidOperation:
        return False


def _allowed_numbers(facts: list[dict]) -> set[str]:
    allowed = set()
    for fact in facts:
        allowed.add(_fact_number(fact))
        if fact["semantics"].get("role") == "profit_impact":
            allowed.add(_normalize_number(str(abs(Decimal(fact["value"])))))
        allowed.update(_numbers_from_text(fact["display_value"]))
    return {item for item in allowed if item}


def _trusted_generated_appendix_regions(
    analysis, body: str, spec: dict, prepared: dict, *, recipe_report: dict | None = None
) -> list[dict]:
    appendix = spec.get("evidence_appendix")
    meta = spec.get("evidence_appendix_meta")
    if not isinstance(appendix, str) or not appendix:
        return []
    if not isinstance(meta, dict):
        return []
    # An appendix saved before 百分点 had its own display wrote 「3.3000 百分点」; it is the same evidence, so it is
    # rebuilt that way too rather than under a new render version that would distrust every other appendix.
    for candidate in (prepared, _legacy_points_prepared(prepared)):
        if candidate is None:
            continue
        regions = _trusted_appendix_regions_as(analysis, body, spec, appendix, meta, candidate, recipe_report)
        if regions:
            return regions
    return []


def _legacy_points_prepared(prepared: dict) -> dict | None:
    """`prepared` with each 百分点 fact displayed as before _points_display (exact value, a space, the unit as
    written), or None when no fact is in 百分点."""
    legacy = {
        fact["id"]: f"{_grouped(fact['value'], 'value')} {fact['unit']}"
        for fact in prepared.get("facts", [])
        if isinstance(fact, dict) and isinstance(fact.get("value"), str)
        and _is_points(fact.get("column"), fact.get("unit"))
    }
    if not legacy:
        return None

    def shown(item: Any, key: str) -> Any:
        if isinstance(item, dict) and item.get(key) in legacy:
            return {**item, "display_value": legacy[item[key]]}
        return item

    groups = [
        {**group, "members": [shown(member, "fact_id") for member in group["members"]]}
        if isinstance(group, dict) and isinstance(group.get("members"), list) else group
        for group in prepared.get("evidence_groups", [])
    ]
    return {**prepared, "facts": [shown(fact, "id") for fact in prepared.get("facts", [])], "evidence_groups": groups}


def _trusted_appendix_regions_as(
    analysis, body: str, spec: dict, appendix: str, meta: dict, prepared: dict, recipe_report: dict | None
) -> list[dict]:
    render_version = meta.get("render_version")
    if meta.get("schema_version") != 1 or type(render_version) is not int or render_version not in {1, 2, 3, 4}:
        return []
    rebuilt_base = _render_evidence_appendix(prepared, render_version=render_version).get("body", "")
    if not isinstance(rebuilt_base, str) or not rebuilt_base:
        return []
    rebuilt_requirement = _rebuilt_input_gap_appendix(analysis, spec, prepared, recipe_report)
    if rebuilt_requirement is None:
        return []
    rebuilt_gap, references = rebuilt_requirement
    rebuilt = rebuilt_base + rebuilt_gap
    expected = evidence_appendix_metadata(rebuilt, base_body=rebuilt_base, render_version=render_version)
    if any(meta.get(key) != expected[key] for key in ("body_sha256", "base_body_sha256")):
        return []
    if appendix != rebuilt:
        return []
    rendered = rebuilt
    start = body.rfind(rendered)
    if start < 0:
        canonical = _canonical_report_markdown(rebuilt)
        if not canonical:
            return []
        rendered = canonical
        start = body.rfind(rendered)
        if start < 0:
            return []
    return [
        {
            "section": "generated_appendix",
            "start": start,
            "end": start + len(rendered),
            # Item headings and sheet!range formulas the server wrote in 来源复算依据 (no values).
            "references": references,
        }
    ]


def _canonical_report_markdown(markdown: str) -> str | None:
    try:
        from foundry.report_documents import (
            report_document_from_markdown_body,
            report_document_markdown,
        )

        return report_document_markdown(report_document_from_markdown_body(markdown))
    except FoundryError:
        return None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _rebuilt_input_gap_appendix(
    analysis, spec: dict, prepared: dict, recipe_report: dict | None = None
) -> tuple[str, list[str]] | None:
    """The requirement part of the generated appendix (待补资料 and 来源复算依据) and the references the
    来源复算依据 section writes; None when the requirement check itself fails."""
    requirements_id = spec.get("requirements_id")
    if not requirements_id:
        return "", []
    try:
        requirements = analysis._get("requirements", requirements_id)
        from foundry.finance_requirement_support import (
            evidence_basis_appendix,
            evidence_basis_references,
            input_gap_appendix,
            with_input_gaps,
        )
        from foundry.finance_requirements import check_requirements

        # The same claims the save path's provisional check saw: fact claims plus the draft's own claims.
        claims = [
            *claims_for_facts(prepared.get("facts", []), spec.get("fact_ids", [])),
            *[claim for claim in spec.get("claims") or [] if isinstance(claim, dict)],
        ]
        checked = check_requirements(
            analysis,
            {
                "run_ids": spec.get("run_ids", []),
                "claims": claims,
                "requirements_id": requirements_id,
                "source_read_failures": spec.get("source_read_failures", []),
                # The draft's own recipes, so the rebuilt appendix matches the quality verdict.
                "evidence_recipes": spec.get("evidence_recipes", []),
            },
            _requirements_record=requirements,
            _recipe_report=recipe_report,
        )
        checked = with_input_gaps(analysis, checked)
        return input_gap_appendix(checked) + evidence_basis_appendix(checked), evidence_basis_references(checked)
    except FoundryError:
        return None
    except (OSError, ValueError, KeyError, TypeError):
        return "", []


def _readability_suggestions(body: str, generated_regions: list[dict]) -> dict:
    issues: list[dict] = _ar_wording_suggestions(body, generated_regions)
    for block in _manager_readability_blocks(body, generated_regions):
        text = block["text"]
        stripped = text.strip()
        if _is_dense_finance_paragraph(stripped):
            issues.append({
                "code": "dense_paragraph",
                "severity": "suggestion",
                "message": "这一段同时承载结论、多个数据或条件，建议拆成短结论、条列/比较表和独立附注。",
                "position": block["start"] + text.find(stripped),
            })
        if _has_inline_formula_stack(stripped):
            match = CLOSURE_EXPR.search(stripped)
            position = block["start"] + (
                match.start("expr") if match else text.find(stripped)
            )
            issues.append({
                "code": "inline_formula",
                "severity": "suggestion",
                "message": "完整公式与叙述挤在同一段，建议把公式独立成段或小表，并把条件贴近相关判断。",
                "position": position,
            })
    located = _locate_issues(issues, generated_regions)
    return {
        "status": "suggestions" if located else "clear",
        "issues": located,
    }


def _ar_wording_suggestions(body: str, generated_regions: list[dict]) -> list[dict]:
    """Advise on bounded ambiguous relations, without asserting an accounting error.

    Unlike paragraph density, these relations also matter in bullets and table
    cells. Mask code and trusted generated text with spaces to retain offsets.
    """
    masked = list(body)
    in_code = False
    offset = 0
    for line in body.splitlines(keepends=True):
        fence = line.strip().startswith(("```", "~~~"))
        if fence or in_code:
            masked[offset:offset + len(line)] = " " * len(line)
        if fence:
            in_code = not in_code
        offset += len(line)
    for match in re.finditer(r"(`+)[^\n]*?\1", body):
        masked[match.start():match.end()] = " " * len(match.group())
    for region in generated_regions:
        masked[region["start"]:region["end"]] = " " * (region["end"] - region["start"])

    patterns = (
        ("receipt_recognition_pairing_ambiguous", re.compile(
            r"收入(?:与|和|及)(?:其)?(?:对应)?收款分别按履约(?:条件)?确认"
            r"(?:与|和|及)债权形成(?:追踪|说明|确认)|"
            r"(?P<receipt_subject>(?<![应预未])收款(?:按|依据|依)履约(?:假设|条件)?确认)"
            r"(?![ \t*_~]*的)(?=$|[，,。；;！？!?、）)」”\"\s*_~])"
        ), "收入与收款的确认依据配对不清。建议分开写：收入按履约假设确认；"
           "对已识别债权的收款属于清偿并写明对象；部分清偿不能写成结清。"
           "来源追踪另述，不从汇总数推定交易分配。"),
        ("receipt_offset_object_ambiguous", re.compile(
            r"(?<![应预未])收款(?:用于)?冲抵[^，,。；;！？!?\n|]{0,64}?"
            r"(?<![应预未])收款(?=$|[，,。；;！？!?、）)」”\"\s])"
        ), "收款与冲抵对象重复，清偿对象不清。建议按来源写明被清偿的已识别债权；"
           "部分清偿不能写成结清。若来源只给汇总数，保留分配缺口，不假定所有收款都经过赊销应收。"),
        ("receipt_balance_modifier_ambiguous", re.compile(
            r"(?<![应预未])收款[ \t]*(?:（[ \t]*(?:形成|产生)(?:了)?未收(?:款)?余额[ \t]*）|"
            r"\([ \t]*(?:形成|产生)(?:了)?未收(?:款)?余额[ \t]*\))"
        ), "括号中余额形成的主语不清。建议按来源写明未收价款形成余额；"
           "对已识别债权的收款属于清偿或冲减，不从汇总数推定具体收款归属。"),
    )
    issues = []
    for segment in re.finditer(r"[^。！？!?；;\n|]+[。！？!?；;]?", "".join(masked)):
        text = segment.group()
        for code, pattern, message in patterns:
            for match in pattern.finditer(text):
                if not _ar_wording_asserted(
                    text, match.start(), match.end(),
                    receipt_subject=bool(match.groupdict().get("receipt_subject")),
                ):
                    continue
                position = segment.start() + match.start()
                issues.append({"code": code, "severity": "suggestion", "message": message,
                               "position": position, "text": body[position:position + len(match.group())]})
    return issues


def _ar_wording_asserted(text: str, start: int, end: int, *, receipt_subject: bool = False) -> bool:
    """Only local denial, questions and explicit editorial context exempt a match."""
    prefix, suffix = text[:start], text[end:]
    if text.endswith(("?", "？")):
        return False
    local = re.split(r"[，,]", prefix)[-1]
    if receipt_subject:
        # Only the new collection-subject relation opts into these qualifiers.
        if re.search(r"(?:如果|若(?!干))", local):
            return False
        if re.search(
            r"(?:并非|不是)[\s“「『\"]*(?:本期|当期|本月)?(?:履约)?(?:服务)?$", local,
        ):
            return False
    if re.search(r"(?:是否|能否|可否|若出现|如果出现|假设|假如)", local):
        return False
    if re.search(r"(?:不能|不应|不要|不得|不可|避免)(?:把|将|说|写|表述|描述)", local):
        return False
    if re.search(r"(?:并非|不是)[\s“「『\"]*(?:本期|当期)?(?:履约)?$", local):
        return False
    # A quoted example may include commas after the matched relation. Its own
    # explicit correction/denial applies; an endorsed quotation still advises.
    for opening, closing in (("“", "”"), ("「", "」"), ("『", "』"), ('"', '"')):
        quoted = (prefix.count(opening) % 2 == 1 if opening == closing else
                  prefix.rfind(opening) > prefix.rfind(closing))
        if quoted and closing in suffix:
            suffix = suffix.split(closing, 1)[1]
            break
    return not re.match(
        r"[\s”」』\"]*(?:[，,]与(?:本期|当期)?收入确认分别对应)?"
        r"(?:[，,]\s*(?:这一|该)(?:说法|表述)|(?:的|这一)?(?:说法|表述)?)"
        r"(?:是)?(?:并)?(?:不成立|不正确|不准确|非正确|错误|有歧义|不清|只是(?:假设|示例))",
        suffix,
    )


def _manager_readability_blocks(body: str, generated_regions: list[dict]) -> list[dict]:
    blocks: list[dict] = []
    in_code = False
    index = 0
    current: list[str] = []
    current_start: int | None = None
    for line in body.splitlines(keepends=True):
        raw = line.rstrip("\n")
        stripped = raw.strip()
        line_start = index
        line_end = index + len(line)
        index = line_end
        if stripped.startswith("```") or stripped.startswith("~~~"):
            if current and current_start is not None:
                blocks.append({"text": "".join(current), "start": current_start})
                current = []
                current_start = None
            in_code = not in_code
            continue
        if in_code or _span_in_generated_region(
            (line_start, line_end), generated_regions
        ):
            if current and current_start is not None:
                blocks.append({"text": "".join(current), "start": current_start})
                current = []
                current_start = None
            continue
        if not stripped:
            if current and current_start is not None:
                blocks.append({"text": "".join(current), "start": current_start})
                current = []
                current_start = None
            continue
        if _is_readability_exempt_line(stripped):
            if current and current_start is not None:
                blocks.append({"text": "".join(current), "start": current_start})
                current = []
                current_start = None
            continue
        if current_start is None:
            current_start = line_start
        current.append(line)
    if current and current_start is not None:
        blocks.append({"text": "".join(current), "start": current_start})
    return blocks


def _span_in_generated_region(
    span: tuple[int, int], generated_regions: list[dict]
) -> bool:
    return any(
        _overlaps(span, (region["start"], region["end"]))
        for region in generated_regions
    )


def _is_readability_exempt_line(stripped: str) -> bool:
    return (
        stripped.startswith(("|", ">", "#", "[^"))
        or bool(re.match(r"^(?:[-*+] |\d+[.)] )", stripped))
    )


def _is_dense_finance_paragraph(text: str) -> bool:
    if len(text) < 160:
        return False
    if not re.search(r"[\u4e00-\u9fff]", text):
        return False
    sentence_boundaries = len(re.findall(r"[。；;！!？?]", text))
    if sentence_boundaries < 2:
        return False
    number_count = len(_body_numbers(text))
    fact_count = len(FACT_TOKEN.findall(text))
    finance_markers = sum(
        1
        for marker in (
            "结论",
            "收入",
            "成本",
            "费用",
            "利润",
            "现金",
            "预算",
            "同比",
            "环比",
            "公式",
            "原因",
            "行动",
            "证据",
        )
        if marker in text
    )
    return (number_count + fact_count) >= 3 and finance_markers >= 3


def _has_inline_formula_stack(text: str) -> bool:
    match = CLOSURE_EXPR.search(text)
    if not match:
        return False
    before = text[:match.start("expr")].strip()
    after = text[match.end("expr"):].strip()
    prose_chars = len(re.findall(r"[\u4e00-\u9fffA-Za-z]", before + after))
    return len(text) >= 80 and prose_chars >= 24


def _locate_issues(issues: list[dict], generated_regions: list[dict]) -> list[dict]:
    return [
        _locate_issue(issue, generated_regions)
        for issue in issues
        if isinstance(issue, dict)
    ]


def _locate_issue(issue: dict, generated_regions: list[dict]) -> dict:
    located = dict(issue)
    position = located.get("position")
    if isinstance(position, int):
        origin = _origin_for_position(position, generated_regions)
        location = {"section": origin, "position": position}
        if origin == "generated_appendix":
            region = _region_for_position(position, generated_regions)
            if region:
                location["offset"] = position - region["start"]
    else:
        origin = _non_body_issue_origin(located)
        location = {"section": origin}
    located.setdefault("origin", origin)
    located.setdefault("location", location)
    return located


def _origin_for_position(position: int, generated_regions: list[dict]) -> str:
    return (
        "generated_appendix"
        if _region_for_position(position, generated_regions)
        else "manager_body"
    )


def _region_for_position(position: int, generated_regions: list[dict]) -> dict | None:
    for region in generated_regions:
        if region["start"] <= position < region["end"]:
            return region
    return None


def _non_body_issue_origin(issue: dict) -> str:
    if issue.get("code") in {
        "invalid_claim",
        "invalid_claim_location",
        "claim_value_mismatch",
        "fact_claim_mismatch",
        "unknown_fact",
        "missing_required_fact",
    }:
        return "claim_binding"
    return "manager_body"


def _generated_aging_audit_number_spans(
    body: str, generated_regions: list[dict], prepared: dict
) -> list[tuple[int, int]]:
    """Only exact source-rebuilt audit metadata inside a trusted appendix.

    This does not bind a financial claim or qualify detail amounts. Manager
    prose and notes keep the ordinary citation and claim checks.
    """
    from foundry.finance_native_drafts import render_aging_audit_appendix

    audit = render_aging_audit_appendix(prepared.get("aging_audit_metadata"))
    if not audit:
        return []
    for region in generated_regions:
        for candidate in (audit, _canonical_report_markdown(audit)):
            if not candidate:
                continue
            start = body.find(candidate, region["start"], region["end"])
            if start >= 0:
                return [(start, start + len(candidate))]
    return []


def _generated_appendix_heading_number_spans(body: str, prepared: dict) -> list[tuple[int, int]]:
    # An appendix saved before 百分点 had its own display is found as it was written (_legacy_points_prepared).
    for candidate in (prepared, _legacy_points_prepared(prepared)):
        if candidate is not None:
            for render_version in (4, EVIDENCE_APPENDIX_RENDER_VERSION, 2, 1):
                spans = _heading_number_spans_as(body, candidate, render_version=render_version)
                if spans:
                    return spans
    return []


def _heading_number_spans_as(body: str, prepared: dict, *, render_version: int) -> list[tuple[int, int]]:
    appendix = _render_evidence_appendix(prepared, render_version=render_version).get("body", "")
    if not appendix:
        return []
    rendered = appendix
    start = body.rfind(rendered)
    if start < 0:
        canonical = _canonical_report_markdown(appendix)
        if not canonical:
            return []
        rendered = canonical
        start = body.rfind(rendered)
        if start < 0:
            return []
    spans = []
    for match in re.finditer(r"(?m)^### 结果行 (?P<number>\d+)$", rendered):
        number_span = match.span("number")
        spans.append((start + number_span[0], start + number_span[1]))
    return spans


def _generated_appendix_label_number_spans(
    body: str, generated_regions: list[dict], prepared: dict
) -> list[tuple[int, int]]:
    """Bare period identifiers (2026, 202608) that name a row or a group in the server's own, trusted
    计算依据 appendix.

    A member line is '- metric / column / scenario / period：value（…）' and a group title may end in
    key=value segments; those segments name the row and state no value, and the writer cannot edit them.
    Row names come from the run's own rows, so only a later segment shaped like a period is exempt: the
    metric name never is, values keep their fact binding, and the same number written anywhere outside a
    trusted appendix name is still checked.
    """
    labels = sorted(
        {
            str(label)
            for group in prepared.get("evidence_groups", [])
            if isinstance(group, dict) and isinstance(group.get("members"), list)
            for member in group["members"]
            if isinstance(member, dict)
            for label in [member.get("label") or member.get("semantic_role") or member.get("column")]
            if label not in (None, "")
        },
        key=len,
        reverse=True,
    )
    spans = []
    for region in generated_regions:
        text = body[region["start"] : region["end"]]
        for line in re.finditer(r"(?m)^(?:- (?P<member>.*)|### (?P<title>.*))$", text):
            if line.group("title") is not None:
                name, start = line.group("title"), line.start("title")
            else:
                rest = line.group("member")
                name = next(
                    (label for label in labels if rest.startswith(label) and rest[len(label) : len(label) + 1] in {"：", "（"}),
                    None,
                )
                start = line.start("member")
            if name is not None:
                spans.extend(_period_segment_spans(name, region["start"] + start))
    return spans


def _generated_appendix_reference_spans(body: str, generated_regions: list[dict]) -> list[tuple[int, int]]:
    """Where the trusted appendix writes a 来源复算依据 reference (an item heading or a sheet!range formula).

    Those texts name archived cells and requirement keys, never values, but a sheet name can hold a year
    (2026预算!B5) the number scan would read. Only occurrences inside a trusted region are exempt; the same
    reference in the writer's prose is still checked.
    """
    spans = []
    for region in generated_regions:
        text = body[region["start"] : region["end"]]
        for reference in region.get("references") or []:
            if not reference:
                continue
            position = text.find(reference)
            while position >= 0:
                start = region["start"] + position
                spans.append((start, start + len(reference)))
                position = text.find(reference, position + len(reference))
    return spans


def _period_segment_spans(name: str, base: int) -> list[tuple[int, int]]:
    spans = []
    position = 0
    for index, segment in enumerate(name.split(" / ")):
        start = base + position
        position += len(segment) + len(" / ")
        key, _, value = segment.rpartition("=")
        offset = len(key) + 1 if key else 0
        if index and PERIOD_IDENTIFIER.fullmatch(value):
            spans.append((start + offset, start + offset + len(value)))
    return spans


def _inline_ordinal_heading(prose: str) -> bool:
    """A prose section label is positive role evidence, not an arbitrary unit."""
    heading = re.match(r"([^：:\n。；;！？!?]{1,64})[：:][ \t]*(\S)", prose)
    if not heading:
        return False
    title = heading[1].strip()
    return bool(re.fullmatch(
        r"[\u4e00-\u9fff]*(?:范围|说明|区别|背景|概况|摘要|目的|目标|原则|方法|步骤|条件|限制|"
        r"假设|风险|提示|结论|建议|事项|依据|来源|口径|对照|比较|差异|边界|结果|顺序)", title)
        or re.fullmatch(r"(?:[A-Za-z]+[ -]+)*(?:scope|notes?|background|summary|purpose|method|steps?|"
                        r"conditions?|limitations?|assumptions?|risks?|conclusions?|comparison|results?)",
                        title, re.IGNORECASE))


def _inline_ordinal_quantified_clause(prose: str) -> bool:
    """A quantified subject with its own predicate can continue a headed list."""
    return bool(re.match(
        r"(?:[一二三四五六七八九十百千万零〇两]+|[1-9]\d*|各|每|若干|数|多)"
        r"(?:项|条|类|组|个)[\u4e00-\u9fff]{1,32}?(?:均|都|皆)"
        r"(?:有|需|须|应|可|已|是|为|不)[^\s。；;！？!?]", prose))


def _inline_ordinal_spans(body: str) -> list[tuple[int, int]]:
    """Only consecutive, prefixed prose enumeration markers have an ordinal role."""
    marker = re.compile(r"(?P<opening>[（(])(?P<number>[1-9]\d?)(?P<closing>[）)])")
    spans, offset = [], 0
    for paragraph in re.split(r"(\n[ \t]*\n)", body):
        matches = list(marker.finditer(paragraph))
        if len(matches) >= 2 and [m['number'] for m in matches] == [str(i) for i in range(1, len(matches) + 1)]:
            prose_items = [paragraph[m.end():matches[i + 1].start() if i + 1 < len(matches)
                                     else len(paragraph)].lstrip(' \t') for i, m in enumerate(matches)]
            headings = [_inline_ordinal_heading(prose) for prose in prose_items]
            prefix = paragraph[:matches[0].start()].strip()
            valid = not prefix or re.fullmatch(
                r"(?:定性)?(?:说明|范围|限制|风险|注意事项|要点|事项|步骤|建议|结论|核查|检查|复核)"
                r"(?:(?:与|及|和)(?:说明|范围|限制|风险|要点|事项|建议|结论))*[：:]", prefix)
            if not valid and headings[0] and re.search(r"\n[ \t]*$", paragraph[:matches[0].start()]):
                valid = True
            for index, match in enumerate(matches):
                if {"(": ")", "（": "）"}[match['opening']] != match['closing']:
                    valid = False
                if index and not re.search(r"[。；;！？!?\n][ \t]*$", paragraph[:match.start()]):
                    valid = False
                prose = prose_items[index]
                # Require an explicit prose/action opening. Arbitrary nouns may
                # be units or currencies; their spelling is not an exemption.
                if not re.match(
                    r"(?:(?:本|该)(?:期|次|例|结果|模型|项)|"
                    r"(?:先|再|随后|最后)?(?:核对|复核|检查|核查|确认|记录|说明|完成|保留)|"
                    r"(?:现金|应收|检查差额|收入|成本|利润|金额|边界|范围|风险)(?:为|是|有|需|应|须)|"
                    r"(?:Review|Check|Confirm|Record|First|Next)\b)", prose
                ) and not headings[index] and not (
                    any(headings[:index]) and _inline_ordinal_quantified_clause(prose)
                ):
                    valid = False
            if valid:
                spans.extend((offset + m.start('number'), offset + m.end('number')) for m in matches)
        offset += len(paragraph)
    return spans


def _body_numbers(body: str, *, ignored_spans: list[tuple[int, int]] | None = None) -> list[dict]:
    ignored_spans = ignored_spans or []
    footnote_spans = [
        match.span() for match in re.finditer(r"\[\^\d+\]", body)
    ]
    footnote_definition_spans = [
        match.span("number")
        for match in re.finditer(r"(?m)^\[\^(?P<number>\d+)\]:", body)
    ]
    ignored_spans = ignored_spans + footnote_spans + footnote_definition_spans + _inline_ordinal_spans(body)
    date_spans = [match.span() for match in DATE_SPAN.finditer(body)]
    # 「1–8 月」「1 至 8 月」是期间；「差异–500」「5–8 亿元」「——21086」仍是金额。
    date_spans += [match.span() for match in PERIOD_RANGE.finditer(body)]
    values = []
    for match in NUMBER.finditer(body):
        if any(_overlaps(match.span(), span) for span in ignored_spans):
            continue
        if any(_overlaps(match.span(), span) for span in date_spans):
            continue
        before = body[match.start() - 1 : match.start()]
        after = body[match.end() : match.end() + 1]
        if (before and before in "-/年月日") or (after and after in "-/年月日"):
            continue
        # 中文排版常在数字与年/月/日之间加空格：「8 月」「2026 年 08 月」。只有写在年/月/日前面的
        # 整数是年月日本身；「本月 120 万元」「75% 年度预算」里的数字仍要核对。
        spaced_after = body[match.end() :].lstrip(" \u00a0\u2009\u202f\u3000")[:1]
        if spaced_after and spaced_after in "年月日" and match.group(0).isdigit():
            continue
        if _is_spreadsheet_reference_number(body, match):
            continue
        values.append({"text": match.group(0), "start": match.start(), "end": match.end()})
    return values


def _is_spreadsheet_reference_number(body: str, match: re.Match[str]) -> bool:
    token = match.group(0)
    if not re.fullmatch(r"\d{1,3}", token):
        return False
    after = body[match.end() : match.end() + 1]
    tail = body[match.end() + 1 :]
    if after == "!":
        return bool(re.match(r"\$?[A-Za-z]{1,3}\$?[1-9]\d*\b", tail))
    if after == "·":
        return bool(re.match(r"[\u4e00-\u9fff]+", tail))
    # 「09 表的」是表号；「500 表明」「850表示」是金额后面接动词。
    return bool(re.match(r"[ \u00a0\u3000]?表(?![示明现达述态彰])", body[match.end() :]))


def _numbers_from_text(text: str) -> set[str]:
    return {_normalize_number(match["text"]) for match in _body_numbers(text)}


def _normalize_number(text: str) -> str:
    text = str(text).strip().replace(",", "").replace("％", "%").replace("−", "-").replace("－", "-")
    if text.endswith("%"):
        try:
            return format((Decimal(text[:-1]) / Decimal(100)).normalize(), "f")
        except InvalidOperation:
            return text
    try:
        value = Decimal(text)
        return format(value.normalize(), "f")
    except InvalidOperation:
        return text


def _decimal_equal(left: Any, right: Any) -> bool:
    if left == right:
        return True
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except InvalidOperation:
        return False


def _exact(value: Any) -> str:
    return str(value)


def _overlaps(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return left[0] < right[1] and right[0] < left[1]
