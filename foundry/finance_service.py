"""Finance domain services using task-owned immutable analysis records."""

from __future__ import annotations

import copy
from decimal import localcontext

from foundry.analysis import AnalysisStore, _assert_id, _hash, _hash_bytes, _new, _safe_text
from foundry.errors import FoundryError
from foundry.structure_records import (
    ACKNOWLEDGED,
    ACTIVE_STATES,
    MANAGER,
    NOT_APPLICABLE,
    PENDING_ACKNOWLEDGEMENT,
    TEMPLATE,
    WITHDRAWN,
    assert_bindable,
    latest_proposal,
)
from foundry.finance_explanations import (
    background_applies,
    claims_for_facts,
    evidence_appendix_metadata,
    normalize_background,
    prepare_explanation as prepare_explanation_payload,
    render_fact_template,
    render_evidence_appendix,
    validate_explanation as validate_explanation_payload,
)
from foundry.finance_metrics import evaluate_metric
from foundry.finance_model import (
    normalize_finance_dataset,
    scoped_source_rows,
    voucher_reference,
)
from foundry.finance_variance import explain_variance, price_quantity_bridge

COLLECTIONS = {
    "contexts",
    "account_maps",
    "scenarios",
    "metric_definitions",
    "backgrounds",
    "adjustments",
    "charts",
    "structure_proposals",
    "structure_confirmations",
}


def _render_fact_template_in_document(document: dict, facts: list[dict]) -> tuple[dict, list[str]]:
    rendered = copy.deepcopy(document)
    used: list[str] = []

    def visit(node: dict) -> None:
        if node.get("type") == "text":
            text, fact_ids = render_fact_template(str(node.get("text", "")), facts)
            node["text"] = text
            used.extend(fact_ids)
        for child in node.get("content", []) or []:
            if isinstance(child, dict):
                visit(child)

    for item in rendered.get("content", []) or []:
        if isinstance(item, dict):
            visit(item)
    return rendered, used


class FinanceStore:
    def __init__(
        self,
        task,
        *,
        snapshot_ids=None,
        session_id=None,
        context_revision=None,
        actor=None,
    ):
        self.analysis = AnalysisStore(task)
        self.task = task
        self.allowed = None if snapshot_ids is None else set(snapshot_ids)
        self.session_id = session_id
        self.context_revision = context_revision
        # Stamped by the call layer; an unstamped call is the lower trust level.
        from foundry.structure_records import resolve_source

        self.actor = resolve_source(actor)

    def _folder(self, kind):
        if kind not in COLLECTIONS:
            raise FoundryError("unknown finance collection")
        return "charts" if kind == "charts" else f"finance/{kind}"

    def _path(self, kind, object_id):
        return self.analysis._inside(
            self.analysis.root / self._folder(kind) / f"{_assert_id(object_id)}.json"
        )

    def _read(self, kind, object_id):
        record = self.analysis._read(self._path(kind, object_id))
        self._authorize(record.get("bindings", {}))
        return record

    def _write(self, collection, **fields):
        record = _new(self.task, domain=f"foundry.finance.{collection}.v1", **fields)
        return self.analysis._write(self._path(collection, record["id"]), record)

    def _list(self, kind):
        root = self.analysis._inside(self.analysis.root / self._folder(kind))
        records = [self.analysis._read(path) for path in root.glob("*.json")]
        visible = []
        for record in records:
            bindings = record.get("bindings", {})
            if kind == "charts" and not bindings:
                continue
            if self.allowed is None or set(bindings.values()) <= self.allowed:
                visible.append(record)
        return sorted(visible, key=lambda r: r["seq"])

    def _authorize(self, bindings):
        if not isinstance(bindings, dict) or any(
            not isinstance(v, str) for v in bindings.values()
        ):
            raise FoundryError("finance bindings must map aliases to snapshot IDs")
        if self.allowed is not None and not set(bindings.values()) <= self.allowed:
            raise FoundryError("finance snapshots are outside this session context")
        for dataset_id in bindings.values():
            _assert_id(dataset_id)

    def _authorize_evidence_recipes(self, recipes):
        from foundry.financial_evidence import recipe_dataset_ids

        for dataset_id in recipe_dataset_ids(recipes):
            self._authorize({"evidence": dataset_id})

    def _authorize_consistency_sources(self, sources):
        from foundry.financial_evidence import consistency_dataset_ids

        for dataset_id in consistency_dataset_ids(sources):
            self._authorize({"consistency": dataset_id})

    def list_finance_context(self):
        from foundry.finance_requirement_support import metric_catalog

        state = self.analysis.state()
        return {
            "task_id": self.task.id,
            "domain": "foundry.finance.context.v1",
            "datasets": [
                {**r, "structure_state": self.dataset_structure_state(r["id"])}
                for r in state["datasets"]
                if self.allowed is None or r["id"] in self.allowed
            ],
            "contexts": self._list("contexts"),
            "account_maps": self._list("account_maps"),
            "scenarios": self._list("scenarios"),
            "metric_definitions": self._list("metric_definitions"),
            "requirement_metric_catalog": metric_catalog(),
            "capabilities": [
                "metrics",
                "variance",
                "drilldown",
                "drafts",
                "scenarios",
                "sql",
                "python",
            ],
        }

    def finance_readiness(self, spec=None):
        from foundry.finance_readiness import build_readiness_report

        return build_readiness_report(self, spec)

    def save_account_map(self, spec):
        if not isinstance(spec.get("rows"), list) or not all(
            isinstance(r, dict) for r in spec["rows"]
        ):
            raise FoundryError("account map rows must be objects")
        parent = (
            self._read("account_maps", spec["parent_id"])
            if spec.get("parent_id")
            else {}
        )
        return self._write(
            "account_maps",
            name=_safe_text(
                spec.get("name", "管理科目映射"), "name", required=True, maximum=200
            ),
            rows=spec["rows"],
            scope=spec.get("scope", parent.get("scope", {})),
            parent_id=parent.get("id"),
            basis=spec.get("basis", "user_assumption"),
        )

    def save_context(self, spec):
        bindings = spec.get("bindings", {})
        self._authorize(bindings)
        if (
            not bindings
            or len(bindings) > 32
            or len(set(bindings.values())) != len(bindings)
        ):
            raise FoundryError("finance context requires 1–32 distinct snapshots")
        scopes, policies = spec.get("scopes", {}), spec.get("policies", {})
        if not isinstance(scopes, dict) or not isinstance(policies, dict):
            raise FoundryError(
                "scopes and policies must be objects keyed by binding alias"
            )
        if set(scopes) - set(bindings) or set(policies) - set(bindings):
            raise FoundryError("scope/policy alias is not bound")
        account_map = (
            self._read("account_maps", spec["account_map_id"])
            if spec.get("account_map_id")
            else None
        )
        parent = (
            self._read("contexts", spec["parent_id"]) if spec.get("parent_id") else {}
        )
        for alias, value in bindings.items():
            assert_bindable(
                value,
                self.dataset_structure_state(value),
                is_shell=self.analysis.read_dataset(value).get("kind") == "workbook",
            )
        source_hashes = {
            alias: self.analysis.read_dataset(value)["source_hash"]
            for alias, value in bindings.items()
        }
        for alias in bindings:
            if not isinstance(scopes.get(alias, {}), dict) or not isinstance(
                policies.get(alias, {}), dict
            ):
                raise FoundryError("each scope and policy must be an object")
        record = self._write(
            "contexts",
            name=_safe_text(
                spec.get("name", "财务分析口径"), "name", required=True, maximum=200
            ),
            bindings=bindings,
            scopes=scopes,
            policies=policies,
            account_map_id=account_map["id"] if account_map else None,
            source_hashes=source_hashes,
            parent_id=parent.get("id"),
        )
        return {**record, "diagnostics": self._normalize(record)["diagnostics"]}

    def _normalize(self, context):
        self._authorize(context["bindings"])
        account_map = (
            self._read("account_maps", context["account_map_id"])
            if context.get("account_map_id")
            else None
        )
        combined = {
            "rows": [],
            "diagnostics": [],
            "control_totals": [],
            "movement_checks": [],
        }
        for alias, dataset_id in context["bindings"].items():
            dataset = self.analysis.read_dataset(dataset_id)
            result = normalize_finance_dataset(
                dataset,
                context.get("scopes", {}).get(alias, {}),
                account_map,
                context.get("policies", {}).get(alias, {}),
            )
            for key in combined:
                combined[key].extend(result.get(key, []))
        return combined

    def save_metric_definition(self, spec):
        context = self._read("contexts", spec["context_id"])
        if not isinstance(spec.get("metric"), dict):
            raise FoundryError("metric definition must be an object")
        parent = (
            self._read("metric_definitions", spec["parent_id"])
            if spec.get("parent_id")
            else {}
        )
        return self._write(
            "metric_definitions",
            name=_safe_text(
                spec.get("name", "管理指标"), "name", required=True, maximum=200
            ),
            metric=spec["metric"],
            context_id=context["id"],
            bindings=context["bindings"],
            parent_id=parent.get("id"),
        )

    def _save_revision(self, context, operation, spec):
        if not isinstance(spec, dict):
            raise FoundryError("finance calculation spec must be an object")
        parent = (
            self.analysis.get_analysis(spec["parent_id"])
            if spec.get("parent_id")
            else {}
        )
        self._authorize(parent.get("bindings", {}))
        record = _new(
            self.task,
            engine="finance",
            question=spec.get("question") or "财务差异分析"
            if operation == "variance"
            else spec.get("question") or "财务指标分析",
            bindings=context["bindings"],
            finance_context_id=context["id"],
            operation=operation,
            finance_spec=spec,
            parent_id=parent.get("id"),
            parameters=[],
            parameter_metadata=[],
            assumptions=spec.get("assumptions", []),
            missing_inputs=[],
            relationships=[],
            metrics=[spec.get("metric", {"kind": operation})],
            grain=[],
            max_rows=10000,
            timeout_seconds=30,
        )
        return self.analysis._write(
            self.analysis._object_path("revisions", record["id"]), record
        )

    def run_metric(self, spec):
        if not isinstance(spec, dict):
            raise FoundryError("finance metric spec must be an object")
        if spec.get("definition_id"):
            definition = self._read("metric_definitions", spec["definition_id"])
            spec = {
                **spec,
                "context_id": definition["context_id"],
                "metric": definition["metric"],
            }
        if not spec.get("context_id"):
            raise FoundryError(
                "finance metric spec requires context_id or definition_id"
            )
        context = self._read("contexts", spec["context_id"])
        self._validate_adjustment_ids(spec, context)
        revision = self._save_revision(context, "metric", spec)
        return self.run_revision(revision)

    def explain_variance(self, spec):
        if not isinstance(spec, dict):
            raise FoundryError("finance variance spec must be an object")
        if not spec.get("context_id"):
            raise FoundryError("finance variance spec requires context_id")
        context = self._read("contexts", spec["context_id"])
        revision = self._save_revision(context, "variance", spec)
        return self.run_revision(revision)

    def save_scenario(self, spec):
        parent = (
            self._read("scenarios", spec["parent_id"])
            if spec.get("parent_id")
            else None
        )
        context = self._read(
            "contexts", spec.get("context_id") or (parent or {}).get("context_id")
        )
        kind = spec.get("kind", (parent or {}).get("kind"))
        if kind not in {"receivables_aging", "cash_13_weeks", "driver_model"}:
            raise FoundryError(
                "scenario kind must be receivables_aging, cash_13_weeks or driver_model"
            )
        label = _safe_text(
            spec.get("label", "财务情景"), "scenario label", required=True, maximum=200
        )
        if parent:
            if context["id"] != parent["context_id"] or kind != parent["kind"]:
                raise FoundryError(
                    "a child scenario retains its parent's context and kind"
                )
            from foundry.finance_scenarios import create_child_scenario

            child = create_child_scenario(parent, spec.get("changes", {}), label=label)
            inputs, diff = child["inputs"], child["diff"]
        else:
            inputs, diff = spec.get("inputs", {}), []
        if not isinstance(inputs, dict):
            raise FoundryError("scenario inputs must be an object")
        return self._write(
            "scenarios",
            label=label,
            kind=kind,
            context_id=context["id"],
            bindings=context["bindings"],
            inputs=inputs,
            input_hash=_hash(inputs),
            parent_id=parent["id"] if parent else None,
            parent_input_hash=parent["input_hash"] if parent else None,
            diff=diff,
            actual_cutoff=inputs.get("actual_cutoff", inputs.get("as_of")),
        )

    def run_scenario(self, spec):
        if not isinstance(spec, dict):
            raise FoundryError("finance scenario run spec must be an object")
        if not spec.get("scenario_id"):
            raise FoundryError("finance scenario run spec requires scenario_id")
        scenario = self._read("scenarios", spec["scenario_id"])
        context = self._read("contexts", scenario["context_id"])
        revision = self._save_revision(context, "scenario", spec)
        return self.run_revision(revision)

    def run_revision(self, revision):
        from foundry.finance_requirement_semantics import capture_requirements
        requirements_snapshot = capture_requirements(self.analysis, self._authorize)
        self._authorize(revision["bindings"])
        context = self._read("contexts", revision["finance_context_id"])
        if context["bindings"] != revision["bindings"]:
            raise FoundryError(
                "finance revision bindings differ from immutable context"
            )
        spec = revision["finance_spec"]
        datasets = {
            alias: self.analysis.read_dataset(value)
            for alias, value in context["bindings"].items()
        }
        input_hashes = {
            alias: dataset["data_hash"] for alias, dataset in datasets.items()
        }
        code_hash = _hash(
            {"operation": revision["operation"], "spec": spec, "context": context}
        )
        fingerprint = _hash(
            {"code": code_hash, "inputs": input_hashes, "runner": "finance-v1"}
        )
        previous = [
            r
            for r in self.analysis._list("runs")
            if r.get("fingerprint") == fingerprint
            and r.get("execution_status") == "succeeded"
        ]
        calculated = {}
        try:
            with localcontext() as decimal_context:
                decimal_context.prec = 80
                if revision["operation"] == "scenario":
                    from foundry.finance_scenario_service import calculate_scenario

                    scenario = self._read("scenarios", spec["scenario_id"])
                    calculated = calculate_scenario(scenario, context, datasets)
                elif (
                    revision["operation"] == "variance"
                    and spec.get("kind") == "price_quantity"
                ):
                    raw = []
                    for alias, dataset in datasets.items():
                        defaults = context.get("scopes", {}).get(alias, {})
                        raw.extend(
                            scoped_source_rows(
                                dataset,
                                defaults,
                                context.get("policies", {}).get(alias, {}),
                            )
                        )
                    calculated = price_quantity_bridge(raw, spec)
                else:
                    normalized = self._normalize(context)
                    calculated = (
                        explain_variance(normalized, spec)
                        if revision["operation"] == "variance"
                        else evaluate_metric(normalized, spec.get("metric", {}))
                    )
                    calculated = self._apply_named_adjustments(
                        calculated, spec, context, operation=revision["operation"]
                    )
            if (
                not isinstance(calculated, dict)
                or not isinstance(calculated.get("columns"), list)
                or not isinstance(calculated.get("rows"), list)
            ):
                raise FoundryError(
                    "finance calculation result must include columns and rows"
                )
            columns = [
                dict(name)
                if isinstance(name, dict)
                else {"name": name, "type": "VARCHAR"}
                for name in calculated["columns"]
            ]
            for column in columns:
                column["type"] = {
                    "string": "VARCHAR",
                    "decimal": "DECIMAL",
                    "integer": "BIGINT",
                    "date": "DATE",
                }.get(column.get("type"), column.get("type", "VARCHAR"))
                values = [
                    r.get(column["name"])
                    for r in calculated["rows"]
                    if r.get(column["name"]) is not None
                ]
                if (
                    column["name"]
                    in {
                        "amount",
                        "signed_amount",
                        "revenue",
                        "cost",
                        "expense",
                        "profit",
                        "actual",
                        "baseline",
                        "contribution",
                        "ratio",
                        "numerator",
                        "denominator",
                        "quantity_contribution",
                        "price_contribution",
                        "interaction",
                        "total_variance",
                        "residual",
                    }
                    and values
                ):
                    column["type"] = "DECIMAL"
            result = {
                **calculated,
                "columns": columns,
                "row_count": len(calculated["rows"]),
                "truncated": False,
            }
            output_hash = _hash(result)
            reproducibility_status = "unverified"
            if previous:
                reproducibility_status = (
                    "reproducible"
                    if all(r["output_hash"] == output_hash for r in previous)
                    else "non_reproducible"
                )
            execution_status = "succeeded"
            error_fields = {}
        except Exception as exc:
            error = (
                str(exc)
                if isinstance(exc, FoundryError)
                else f"finance calculation failed: {type(exc).__name__}: {exc}"
            )
            result = {"columns": [], "rows": [], "row_count": 0, "truncated": False}
            output_hash = None
            reproducibility_status = "unverified"
            execution_status = "failed"
            error_fields = {"error": error, "error_code": "finance_calculation_failed"}
        record = _new(
            self.task,
            engine="finance",
            **requirements_snapshot,
            analysis_id=revision["id"],
            finance_context_id=context["id"],
            session_id=self.session_id,
            context_revision=self.context_revision,
            bindings=context["bindings"],
            input_hashes=input_hashes,
            source_hashes={alias: d["source_hash"] for alias, d in datasets.items()},
            code_hash=code_hash,
            fingerprint=fingerprint,
            environment={"runner": "finance-v1", "decimal_precision": 80},
            parameters=[],
            parameter_metadata=[],
            assumptions=[
                *spec.get("assumptions", []),
                *calculated.get("assumptions", []),
            ],
            missing_inputs=[],
            execution_status=execution_status,
            reproducibility_status=reproducibility_status,
            review_status="unreviewed",
            publication_status="draft",
            deterministic=True,
            warnings=[],
            output_hash=output_hash,
            result=result,
            relationship_checks=[],
            finance_scope=context["scopes"],
            account_map_id=context.get("account_map_id"),
            completeness="incomplete"
            if execution_status == "failed"
            or any(d.get("severity") == "error" for d in result.get("diagnostics", []))
            else "not_reconciled",
            **error_fields,
        )
        return self.analysis._write(
            self.analysis._object_path("runs", record["id"]), record
        )

    def open_source_locator(self, spec):
        from foundry.finance_locators import open_source_locator as open_locator

        return open_locator(self, spec)

    def drilldown_fact(self, spec):
        run = self.analysis.get_run(spec["run_id"])
        self._authorize(run["bindings"])
        index = spec.get("row", 0)
        section = spec.get("section", "rows")
        if section not in {"rows", "detail_rows", "excluded_detail_rows"}:
            raise FoundryError("unsupported drilldown section")
        rows = run.get("result", {}).get(section, [])
        if (
            isinstance(index, bool)
            or not isinstance(index, int)
            or not 0 <= index < len(rows)
        ):
            raise FoundryError("result row is outside the run")
        row = rows[index]
        column = spec.get("column")
        fallback_refs = row.get("source_rows", [])
        if section == "excluded_detail_rows" and not fallback_refs:
            fallback_refs = row.get("excluded_source_rows", [])
        refs = row.get("evidence", {}).get(column, fallback_refs)
        offset, limit = spec.get("offset", 0), spec.get("limit", 100)
        if (
            any(isinstance(v, bool) or not isinstance(v, int) for v in (offset, limit))
            or offset < 0
            or not 1 <= limit <= 1000
        ):
            raise FoundryError("drilldown offset/limit are invalid")
        unique = {(r.get("dataset_id"), r.get("row_index")): r for r in refs}
        values = []
        snapshots = {}
        for (dataset_id, source_index), ref in list(unique.items())[
            offset : offset + limit
        ]:
            if dataset_id not in run["bindings"].values():
                raise FoundryError("source evidence is outside run bindings")
            if dataset_id not in snapshots:
                snapshots[dataset_id] = self.analysis.read_dataset(dataset_id)
            dataset = snapshots[dataset_id]
            if (
                isinstance(source_index, bool)
                or not isinstance(source_index, int)
                or not 1 <= source_index <= len(dataset["rows"])
            ):
                raise FoundryError("source evidence row is invalid")
            source = dataset["rows"][source_index - 1]
            voucher = voucher_reference(source)
            values.append(
                {
                    "source": ref,
                    "source_hash": dataset["source_hash"],
                    "data": source,
                    "voucher_detail_available": voucher is not None,
                    **({"voucher": voucher} if voucher else {}),
                }
            )
        location = {"run_id": run["id"], "row": index, "column": column, "output_hash": run.get("output_hash")}
        if section != "rows":
            location["section"] = section
        trusted_run = run.get("engine") == "finance" or self.analysis.aggregate_sources_verified(run)
        evidence_status = "verified" if values and trusted_run else "unverified" if values else "missing"
        evidence_key = _hash({"location": location, "status": evidence_status, "sources": [r["source"] for r in values]})
        existing = next((r for r in self.analysis._list("evidence_checks") if r.get("evidence_key") == evidence_key), None)
        if not existing:
            record = _new(self.task, location=location, status=evidence_status, evidence_key=evidence_key,
                          bindings=run["bindings"], sources=[r["source"] for r in values],
                          source_hashes={dataset_id: dataset["source_hash"] for dataset_id, dataset in snapshots.items()},
                          total=len(unique), offset=offset, read_count=len(values),
                          has_more=offset + len(values) < len(unique))
            self.analysis._write(self.analysis._object_path("evidence_checks", record["id"]), record)
        return {
            "run_id": run["id"],
            "row": index,
            "column": column,
            "provenance_status": evidence_status,
            "section": section,
            "rows": values,
            "total": len(unique),
            "total_occurrences": len(refs),
            "exclusion_reason": row.get("exclusion_reason") if section == "excluded_detail_rows" else None,
            "offset": offset,
            "has_more": offset + len(values) < len(unique),
            "message": "来源行可查看；仅有余额资料时不提供凭证分录链接。",
        }

    def analysis_requirements_save(self, spec):
        from foundry.finance_requirements import latest_requirements, save_requirements

        if not isinstance(spec, dict):
            raise FoundryError("analysis requirements spec must be an object")
        parent = latest_requirements(self.analysis)
        if parent:
            self._authorize(parent.get("bindings", {}))
        if spec.get("context_id"):
            context = self._read("contexts", spec["context_id"])
            spec = {**spec, "bindings": context["bindings"],
                    "scope": spec.get("scope", self._primary_scope(context.get("scopes", {})))}
        self._authorize(spec.get("bindings", {}))
        return save_requirements(self.analysis, spec)

    def analysis_requirements_list(self, spec):
        records = self.analysis._list("requirements")
        visible = [r for r in records if self.allowed is None or set(r.get("bindings", {}).values()) <= self.allowed]
        if spec.get("context_id"):
            self._read("contexts", spec["context_id"])
            visible = [r for r in visible if r.get("context_id") == spec["context_id"]]
        return {"requirements": visible, "current": visible[-1] if visible else None}

    def save_completion_draft(self, operation_id, call_id, spec):
        """Runtime-only automatic save; ordinary manager saves stay independent."""
        from foundry.finance_completion_operations import CompletionOperationStore, TERMINAL
        from foundry.finance_completion import record_completion
        from foundry.locking import exclusive

        if not self.session_id:
            raise FoundryError("completion saves require a runtime session")
        if not isinstance(spec, dict):
            raise FoundryError("explanation draft spec must be an object")
        self._reject_completion_authority(spec)
        # Authorize referenced records before persisting a recoverable payload.
        from foundry.finance_requirements import latest_requirements
        requirements = latest_requirements(self.analysis)
        if requirements:
            self._authorize(requirements.get("bindings", {}))
        if spec.get("requirements_id"):
            self._authorize(self.analysis._get("requirements", spec["requirements_id"]).get("bindings", {}))
        for claim in spec.get("claims", []):
            if isinstance(claim, dict) and claim.get("dataset_id"):
                self._authorize({"source": claim["dataset_id"]})
        for run_id in spec.get("run_ids", []):
            self._authorize(self.analysis.get_run(run_id)["bindings"])
        if spec.get("parent_id"):
            parent = self.analysis.get_draft(spec["parent_id"])
            if parent.get("requirements_id"):
                self._authorize(self.analysis._get("requirements", parent["requirements_id"]).get("bindings", {}))
            for claim in parent.get("claims", []):
                if isinstance(claim, dict) and claim.get("dataset_id"):
                    self._authorize({"source": claim["dataset_id"]})
            for run_id in parent.get("run_ids", []):
                self._authorize(self.analysis.get_run(run_id)["bindings"])
        operations = CompletionOperationStore(self.task, self.session_id, self.allowed)
        with exclusive(self.analysis._inside(self.analysis.root / "completion.lock"), timeout=10):
            reserved = operations.reserve(operation_id, payload=spec, call_id=call_id)
            attempt = reserved["attempt"]
            if attempt.get("status") == "rejected_validation":
                error = attempt.get("error") if isinstance(attempt.get("error"), dict) else {}
                message = error.get("message") if isinstance(error.get("message"), str) else "completion validation failed"
                raise FoundryError(message)
            key = _hash({"operation_id": operation_id, "call_id": call_id})
            previous = next((row for row in self.analysis._list("drafts")
                             if row.get("completion_request_key") == key), None)
            if previous:
                for run_id in previous.get("run_ids", []):
                    self._authorize(self.analysis.get_run(run_id)["bindings"])
                receipt = (self.analysis._get("completions", attempt["completion_id"])
                           if attempt.get("completion_id") else
                           record_completion(self.analysis, previous, previous["explanation_check"]))
                operation = operations.settle(operation_id, attempt["revision"], previous, receipt)
                return {**previous, "completion": receipt, "completion_operation": operation,
                        "replayed": True, "validation_basis": "saved_draft_version"}

            def check_deadline():
                operation = operations.get(operation_id)
                if operation["status"] in TERMINAL:
                    raise FoundryError("completion operation stopped: " + str(operation.get("stop_reason")))

            check_deadline()
            save_spec = {
                **spec,
                "completion_request_key": key,
                "completion_operation_id": operation_id,
                "completion_operation_revision": attempt["revision"],
            }
            try:
                result = self._save_explanation_draft(save_spec, check_deadline=check_deadline)
            except FoundryError as exc:
                saved_after_error = next((row for row in self.analysis._list("drafts")
                                          if row.get("completion_request_key") == key), None)
                if saved_after_error:
                    raise
                details = getattr(exc, "details", None)
                if isinstance(details, dict):
                    error_details = [details]
                    primary_detail = details
                elif isinstance(details, list):
                    error_details = [item for item in details if isinstance(item, dict)]
                    primary_detail = error_details[0] if error_details else {}
                else:
                    error_details = []
                    primary_detail = {}
                operations.reject_attempt(operation_id, attempt["revision"], {
                    "code": str(primary_detail.get("code") or "claim_value_mismatch") if primary_detail else "completion_validation_failed",
                    "message": str(exc),
                    "details": error_details,
                    "primary_detail": primary_detail,
                })
                raise
            operation = operations.settle(operation_id, attempt["revision"], result, result["completion"])
            return {**result, "completion_operation": operation}

    def recover_completion_draft(self, spec):
        """Manager-owned recovery of an explicitly selected completion attempt."""
        from foundry.analysis import _hash
        from foundry.finance_completion import record_completion
        from foundry.finance_completion_operations import (
            CompletionOperationStore,
            TERMINAL,
            get_completion_operation_for_recovery,
        )
        from foundry.locking import exclusive

        if self.session_id:
            raise FoundryError("completion recovery requires the task editor")
        if not isinstance(spec, dict):
            raise FoundryError("completion recovery spec must be an object")
        draft_spec = spec.get("draft")
        if not isinstance(draft_spec, dict):
            raise FoundryError("completion recovery draft must be an object")
        self._reject_completion_authority(draft_spec)
        operation = get_completion_operation_for_recovery(self.task, spec.get("operation_id"))
        revision = spec.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise FoundryError("operation revision must be a positive integer")
        if operation.get("status") == "running":
            raise FoundryError("live completion operation cannot be recovered")
        if operation.get("status") == "complete":
            raise FoundryError("completion operation is already complete")
        attempt = next((row for row in operation.get("revisions", []) if row.get("revision") == revision), None)
        if not attempt:
            raise FoundryError("operation revision has not been reserved")
        if attempt.get("status") == "reserved" and operation.get("status") not in TERMINAL:
            raise FoundryError("live completion attempt cannot be recovered")
        recovery_key = _hash({"operation_id": operation["id"], "revision": revision, "draft": draft_spec})
        operations = CompletionOperationStore(self.task, operation["session_id"])
        with exclusive(self.analysis._inside(self.analysis.root / "completion.lock"), timeout=10):
            operation = operations.get(operation["id"])
            attempt = next((row for row in operation.get("revisions", []) if row.get("revision") == revision), None)
            if operation.get("status") == "running":
                raise FoundryError("live completion operation cannot be recovered")
            if operation.get("status") == "complete":
                raise FoundryError("completion operation is already complete")
            if not attempt:
                raise FoundryError("operation revision has not been reserved")
            if attempt.get("status") == "reserved" and operation.get("status") not in TERMINAL:
                raise FoundryError("live completion attempt cannot be recovered")
            previous_by_revision = next((row for row in self.analysis._list("drafts")
                                         if row.get("completion_operation_id") == operation["id"]
                                         and row.get("completion_operation_revision") == revision), None)
            if previous_by_revision:
                if previous_by_revision.get("completion_request_key") != recovery_key:
                    raise FoundryError("completion recovery already saved with a different payload")
                receipt = (self.analysis._get("completions", attempt["completion_id"])
                           if attempt.get("completion_id") else
                           record_completion(self.analysis, previous_by_revision, previous_by_revision["explanation_check"]))
                settled = operations.settle(operation["id"], revision, previous_by_revision, receipt)
                return {**previous_by_revision, "completion": receipt, "completion_operation": settled,
                        "replayed": True, "validation_basis": "saved_draft_version"}
            if int(operation.get("current_revision", 0)) != revision:
                raise FoundryError("newer completion revision exists")
            if attempt.get("draft_id") or attempt.get("completion_id"):
                raise FoundryError("operation revision already saved")
            save_spec = {
                **draft_spec,
                "completion_request_key": recovery_key,
                "completion_operation_id": operation["id"],
                "completion_operation_revision": revision,
            }
            result = self._save_explanation_draft(save_spec)
            settled = operations.settle(operation["id"], revision, result, result["completion"])
            return {**result, "completion_operation": settled}

    @staticmethod
    def _reject_completion_authority(spec):
        forbidden = {"operation_id", "operation_revision", "operation_intent", "operation_payload_hash",
                     "completion_operation_id", "completion_operation_revision", "completion_request_key"}
        if forbidden.intersection(spec):
            raise FoundryError("completion authority must come from the runtime, not draft spec")

    def save_explanation_draft(self, spec):
        if not isinstance(spec, dict):
            raise FoundryError("explanation draft spec must be an object")
        self._reject_completion_authority(spec)
        from foundry.finance_requirements import latest_requirements
        from foundry.finance_completion import record_completion
        from foundry.locking import exclusive

        # Serialize retries separately from the short task-record write lock.
        # A committed draft also acts as recovery evidence if receipt writing fails.
        with exclusive(self.analysis._inside(self.analysis.root / "completion.lock"), timeout=10):
            requirements = latest_requirements(self.analysis)
            if requirements:
                self._authorize(requirements.get("bindings", {}))
            key = _hash({"request": spec, "requirements_id": (requirements or {}).get("id")})
            previous = next((row for row in self.analysis._list("drafts")
                             if row.get("completion_request_key") == key), None)
            if previous:
                self._authorize_evidence_recipes(previous.get("evidence_recipes", []))
                self._authorize_consistency_sources(previous.get("consistency_sources", {}))
                if previous.get("requirements_id"):
                    self._authorize(self.analysis._get("requirements", previous["requirements_id"]).get("bindings", {}))
                for run_id in previous.get("run_ids", []):
                    self._authorize(self.analysis.get_run(run_id)["bindings"])
                for claim in previous.get("claims", []):
                    if claim.get("run_id"):
                        self._authorize(self.analysis.get_run(claim["run_id"])["bindings"])
                    if claim.get("dataset_id"):
                        self._authorize({"source": claim["dataset_id"]})
                receipt = record_completion(self.analysis, previous, previous["explanation_check"])
                return {**previous, "completion": receipt, "replayed": True,
                        "validation_basis": "saved_draft_version"}
            return self._save_explanation_draft({**spec, "completion_request_key": key})

    def _save_explanation_draft(self, spec, *, check_deadline=lambda: None):
        check_deadline()
        parent = (
            self.analysis.get_draft(spec["parent_id"]) if spec.get("parent_id") else {}
        )
        self._authorize_evidence_recipes(spec.get("evidence_recipes", parent.get("evidence_recipes", [])))
        self._authorize_consistency_sources(spec.get("consistency_sources", parent.get("consistency_sources", {})))
        if self.session_id and spec.get("review_status", parent.get("review_status", "unreviewed")) != "unreviewed":
            raise FoundryError("runtime drafts cannot mark professional review complete")
        if parent.get("requirements_id"):
            self._authorize(self.analysis._get("requirements", parent["requirements_id"]).get("bindings", {}))
        run_ids = spec.get("run_ids", parent.get("run_ids", []))
        if not isinstance(run_ids, list):
            raise FoundryError("run_ids must be an array")
        for run_id in [*parent.get("run_ids", []), *run_ids]:
            self._authorize(self.analysis.get_run(run_id)["bindings"])
        prepared = (
            self.prepare_explanation({"run_ids": run_ids,
                                      "materiality": spec.get("materiality", parent.get("materiality", {}))})
            if run_ids
            else {"facts": []}
        )
        check_deadline()
        document = None
        if spec.get("document") is not None:
            from foundry.report_documents import report_document_markdown, validate_report_document

            document = validate_report_document(
                spec["document"],
                registered_source_ids=self.analysis._registered_report_source_ids(),
            )
            body = report_document_markdown(document)
        else:
            body = spec.get("body", parent.get("body", ""))
        previous_appendix = parent.get("evidence_appendix", "")
        if previous_appendix and body.endswith(previous_appendix):
            body = body[:-len(previous_appendix)].rstrip()
        if document is not None:
            from foundry.report_documents import report_document_markdown

            document, template_fact_ids = _render_fact_template_in_document(document, prepared["facts"])
            rendered = report_document_markdown(document)
        else:
            rendered, template_fact_ids = render_fact_template(body, prepared["facts"])
        explicit_fact_ids = spec.get("fact_ids", parent.get("fact_ids", []))
        if not isinstance(explicit_fact_ids, list):
            raise FoundryError("fact_ids must be an array")
        appendix = render_evidence_appendix(prepared)
        appendix_base_body = appendix["body"]
        fact_ids = list(dict.fromkeys([*explicit_fact_ids, *template_fact_ids, *appendix["fact_ids"]]))
        # Read actual requested evidence before evaluating the final draft.
        from foundry.finance_requirements import check_requirements
        from foundry.finance_requirement_support import with_input_gaps, input_gap_appendix
        provisional = check_requirements(self.analysis, {
            "run_ids": run_ids, "claims": claims_for_facts(prepared["facts"], fact_ids),
            "requirements_id": spec.get("requirements_id", parent.get("requirements_id")),
        })
        provisional = with_input_gaps(self.analysis, provisional)
        appendix["body"] += input_gap_appendix(provisional)
        appendix_meta = evidence_appendix_metadata(
            appendix["body"], base_body=appendix_base_body
        )
        if appendix["body"]:
            rendered = rendered.rstrip() + "\n\n" + appendix["body"].lstrip()
            if document is not None:
                from foundry.report_documents import (
                    append_markdown_blocks,
                    report_document_markdown,
                )

                document = append_markdown_blocks(document, appendix["body"])
                rendered = report_document_markdown(document)
        source_read_failures = []
        for item in provisional["items"]:
            if item["requires_drilldown"]:
                for location in item["locations"]:
                    try:
                        offset = 0
                        while True:
                            check_deadline()
                            result = self.drilldown_fact({**{key: location[key] for key in ("run_id", "row", "column")},
                                                         "offset": offset, "limit": 1000})
                            if not result.get("has_more"):
                                break
                            count = len(result.get("rows", []))
                            if not count:
                                raise FoundryError("source pagination made no progress")
                            offset += count
                    except FoundryError as exc:
                        source_read_failures.append({"requirement_item_id": item["id"],
                                                     "location": location, "message": str(exc)})
        auto_claims = claims_for_facts(prepared["facts"], fact_ids)
        claims = []
        for claim in _dedupe_explanation_claims(
            [*auto_claims, *spec.get("claims", parent.get("claims", []))]
        ):
            if not isinstance(claim, dict):
                raise FoundryError("claims must contain objects")
            claim = dict(claim)
            if claim.get("dataset_id"):
                self._authorize({"source": claim["dataset_id"]})
            if claim.get("basis") == "calculation" and claim.get("run_id"):
                run = self.analysis.get_run(claim["run_id"])
                self._authorize(run["bindings"])
                if run.get("engine") == "finance":
                    claim.update(
                        finance_context_id=run["finance_context_id"],
                        finance_scope=run["finance_scope"],
                        metric_id=claim.get("column"),
                        account_map_id=run.get("account_map_id"),
                    )
            claims.append(claim)
        check_deadline()
        save_spec = {
            **spec,
            "body": rendered,
            **({"document": document} if document is not None else {}),
            "evidence_appendix": appendix["body"],
            "evidence_appendix_meta": appendix_meta,
            "materiality": prepared.get("materiality", {}),
            "source_read_failures": source_read_failures,
            **({"body_template": body} if template_fact_ids else {}),
            "run_ids": run_ids,
            "fact_ids": fact_ids,
            "claims": claims,
        }
        draft = self.analysis.save_draft(save_spec)

        from foundry.finance_completion import record_completion

        completion = record_completion(self.analysis, draft, draft["explanation_check"])
        return {**draft, "completion": completion}

    def prepare_explanation(self, spec):
        if not isinstance(spec, dict):
            raise FoundryError("prepare explanation spec must be an object")
        run_ids = spec.get("run_ids", [])
        if not isinstance(run_ids, list) or not run_ids:
            raise FoundryError("prepare explanation requires run_ids")
        runs = []
        for run_id in dict.fromkeys(run_ids):
            run = self.analysis.get_run(run_id)
            self._authorize(run["bindings"])
            runs.append(run)
        self._authorize_evidence_recipes(spec.get("evidence_recipes", []))
        self._authorize_consistency_sources(spec.get("consistency_sources", {}))
        backgrounds = self._backgrounds_for_runs(runs)
        payload = prepare_explanation_payload(
            self.analysis,
            runs,
            backgrounds=backgrounds,
            materiality=spec.get("materiality") or {},
        )
        request_context = {
            "scope": spec.get("scope", {}),
            "result_role": spec.get("result_role"),
            "requirements_id": spec.get("requirements_id"),
        }
        payload["request_context"] = {key: value for key, value in request_context.items() if value not in (None, {}, "")}
        if spec.get("evidence_recipes") is not None or spec.get("consistency_rules") is not None or spec.get("consistency_sources") is not None:
            from foundry.financial_consistency import evaluate_consistency_rules
            from foundry.financial_evidence import evaluate_evidence_recipes, prepare_consistency_inputs

            evidence_report = evaluate_evidence_recipes(self.analysis, spec.get("evidence_recipes", []))
            resolved_rules, source_auth = prepare_consistency_inputs(
                self.analysis, spec.get("consistency_rules", []), spec.get("consistency_sources", {})
            )
            payload["evidence_report"] = evidence_report
            payload["consistency_report"] = evaluate_consistency_rules(
                resolved_rules, recipe_report=evidence_report, source_auth=source_auth
            )
        from foundry.finance_locators import record_fact_index

        record_fact_index(self, payload.get("facts") or [])
        return payload

    def validate_explanation(self, spec):
        if not isinstance(spec, dict):
            raise FoundryError("validate explanation spec must be an object")
        draft = (
            self.analysis.get_draft(spec["draft_id"]) if spec.get("draft_id") else {}
        )
        run_ids = spec.get("run_ids", draft.get("run_ids", []))
        if not isinstance(run_ids, list):
            raise FoundryError("run_ids must be an array")
        for run_id in dict.fromkeys(run_ids):
            self._authorize(self.analysis.get_run(run_id)["bindings"])
        for run_id in draft.get("run_ids", []):
            self._authorize(self.analysis.get_run(run_id)["bindings"])
        for claim in spec.get("claims", draft.get("claims", [])):
            if isinstance(claim, dict):
                if claim.get("run_id"):
                    self._authorize(self.analysis.get_run(claim["run_id"])["bindings"])
                if claim.get("dataset_id"):
                    self._authorize({"source": claim["dataset_id"]})
        self._authorize_evidence_recipes(spec.get("evidence_recipes", draft.get("evidence_recipes", [])))
        self._authorize_consistency_sources(spec.get("consistency_sources", draft.get("consistency_sources", {})))
        from foundry.finance_requirements import augment_quality, latest_requirements

        current = latest_requirements(self.analysis)
        if current:
            self._authorize(current.get("bindings", {}))
        merged = {**draft, **spec, "run_ids": run_ids}
        return augment_quality(self.analysis, merged, validate_explanation_payload(self.analysis, merged))

    def finance_background_save(self, spec):
        if not isinstance(spec, dict):
            raise FoundryError("finance background spec must be an object")
        parent = (
            self._read("backgrounds", spec["parent_id"]) if spec.get("parent_id") else {}
        )
        context = (
            self._read("contexts", spec["context_id"])
            if spec.get("context_id")
            else {}
        )
        if context and not spec.get("scope"):
            spec = {**spec, "scope": self._primary_scope(context.get("scopes", {}))}
        dataset = None
        parent_source = parent.get("source") if isinstance(parent.get("source"), dict) else {}
        dataset_id = spec.get("dataset_id", parent_source.get("dataset_id"))
        if dataset_id:
            self._authorize({"source": dataset_id})
            dataset = self.analysis.read_dataset(dataset_id)

        fields = normalize_background(spec, parent=parent, dataset=dataset)
        context_bindings = self._background_scope_bindings(fields["scope"], context)
        return self._write(
            "backgrounds", **fields,
            bindings={**parent.get("bindings", {}), **context_bindings, **({"source": dataset_id} if dataset_id else {})},
        )

    def finance_background_list(self, spec):
        if not isinstance(spec, dict):
            raise FoundryError("finance background list spec must be an object")
        scope = spec.get("scope", {})
        if spec.get("context_id"):
            context = self._read("contexts", spec["context_id"])
            scope = self._primary_scope(context.get("scopes", {})) or scope
        if not isinstance(scope, dict):
            raise FoundryError("background scope must be an object")
        if not scope:
            return {"schema_version": 1, "business_contexts": []}
        self._background_scope_bindings(scope)
        all_rows = self._list("backgrounds")
        rows = [row for row in all_rows if background_applies(row, scope=scope, as_of=spec.get("as_of") or scope.get("period"))]
        by_id = {row["id"]: row for row in all_rows}
        superseded = set()
        for row in rows:
            parent_id = row.get("parent_id")
            while parent_id in by_id and parent_id not in superseded:
                superseded.add(parent_id)
                parent_id = by_id[parent_id].get("parent_id")
        return {"schema_version": 1, "business_contexts": [r for r in rows if r["id"] not in superseded]}

    def finance_adjustment_save(self, spec):
        from foundry.finance_adjustments import normalize_adjustment, reject_overlapping_save

        if not isinstance(spec, dict):
            raise FoundryError("finance adjustment spec must be an object")
        context = self._read("contexts", spec["context_id"]) if spec.get("context_id") else None
        if context is None:
            raise FoundryError("finance adjustment spec requires context_id")
        if spec.get("bindings") is not None and spec.get("bindings") != context.get("bindings"):
            raise FoundryError("adjustment bindings must match the finance context")
        bindings = context["bindings"]
        if not isinstance(bindings, dict) or not bindings:
            raise FoundryError("adjustment bindings are required")
        self._authorize(bindings)
        fields = normalize_adjustment(spec, context=context, bindings=bindings)
        reject_overlapping_save(fields, [row for row in self._list("adjustments") if row.get("context_id") == context["id"]])
        return self._write("adjustments", **fields)

    def finance_adjustment_list(self, spec):
        if not isinstance(spec, dict):
            raise FoundryError("finance adjustment list spec must be an object")
        from foundry.finance_adjustments import mark_superseded

        context_id = spec.get("context_id")
        rows = [
            row
            for row in self._list("adjustments")
            if not context_id or row.get("context_id") == context_id
        ]
        return {"schema_version": 1, "adjustments": mark_superseded(rows)}

    def finance_adjustment_confirm(self, spec):
        from foundry.finance_adjustments import normalize_adjustment, reject_overlapping_save

        if not isinstance(spec, dict) or not spec.get("id"):
            raise FoundryError("finance adjustment confirm requires id")
        pending = self._read("adjustments", spec["id"])
        if pending.get("include_in_management_pnl") is True:
            return pending
        context = self._read("contexts", pending["context_id"])
        payload = {
            **pending,
            "context_id": pending["context_id"],
            "parent_id": pending["id"],
            "include_in_management_pnl": False,
        }
        fields = normalize_adjustment(payload, context=context, bindings=pending["bindings"])
        fields["include_in_management_pnl"] = True
        reject_overlapping_save(
            {**fields, "parent_id": pending["id"]},
            [row for row in self._list("adjustments") if row.get("context_id") == context["id"]],
        )
        return self._write("adjustments", **fields)

    def _validate_adjustment_ids(self, spec, context):
        """Refuse a bad adjustment request before a revision is recorded."""
        named = spec.get("adjustment_ids") or []
        if not isinstance(named, list) or any(not isinstance(item, str) for item in named):
            raise FoundryError("adjustment_ids must be a list of adjustment ids")
        if not named:
            return
        metric = spec.get("metric") if isinstance(spec.get("metric"), dict) else {}
        kind = metric.get("kind") or metric.get("type") or "management_pnl"
        if kind != "management_pnl":
            raise FoundryError("adjustment_ids apply only to run_metric(kind=management_pnl)")
        known = {row["id"] for row in self._list("adjustments") if row.get("context_id") == context["id"]}
        unknown = [item for item in named if item not in known]
        if unknown:
            raise FoundryError(f"unknown adjustment ids: {', '.join(unknown)}")

    def _apply_named_adjustments(self, calculated, spec, context, *, operation):
        from foundry.finance_adjustments import apply_to_metric, run_periods, select_applied

        named = spec.get("adjustment_ids") or []
        if not isinstance(named, list) or any(not isinstance(item, str) for item in named):
            raise FoundryError("adjustment_ids must be a list of adjustment ids")
        if not named:
            return calculated
        metric = spec.get("metric") if isinstance(spec.get("metric"), dict) else {}
        kind = metric.get("kind") or metric.get("type") or "management_pnl"
        if operation != "metric" or kind != "management_pnl":
            raise FoundryError("adjustment_ids apply only to run_metric(kind=management_pnl)")
        records = [row for row in self._list("adjustments") if row.get("context_id") == context["id"]]
        applied, ignored = select_applied(named, records, periods=run_periods(context, calculated))
        return apply_to_metric(calculated, applied, ignored)

    def _background_scope_bindings(self, scope, context=None):
        contexts = [context] if context else self._list("contexts")
        matching = [c for c in contexts if any(
            all(s.get(k) == scope.get(k) for k in ("ledger", "organization", "currency", "unit") if scope.get(k))
            for s in c.get("scopes", {}).values()
        )]
        if not matching and (self.allowed is not None or context):
            raise FoundryError("background scope is outside authorized finance contexts")
        return {f"context_{c['id']}_{alias}": value for c in matching for alias, value in c.get("bindings", {}).items()}


    def _backgrounds_for_runs(self, runs):
        contexts = []
        for run in runs:
            as_of = None
            for scope in (run.get("finance_scope") or {}).values():
                if isinstance(scope, dict) and scope.get("period"):
                    as_of = scope["period"]
                    break
            scope = self._primary_scope(run.get("finance_scope", {})) or {}
            contexts.extend(
                self.finance_background_list({"scope": scope, "as_of": as_of})[
                    "business_contexts"
                ]
            )
        by_id = {row["id"]: row for row in contexts}
        return sorted(by_id.values(), key=lambda row: row["seq"])

    def _primary_scope(self, scopes):
        if isinstance(scopes, dict):
            for value in scopes.values():
                if isinstance(value, dict):
                    return value
        return {}

    # ----- table structure: propose, confirm, acknowledge, reject, withdraw -----

    def _structure_proposals(self, dataset_id):
        return [
            row
            for row in self._list("structure_proposals")
            if row.get("dataset_id") == dataset_id
        ]

    def _structure_confirmations(self, dataset_id):
        return [
            row
            for row in self._list("structure_confirmations")
            if row.get("dataset_id") == dataset_id
        ]

    def _authorized_dataset(self, dataset_id):
        """A structure call may only reach a snapshot this session already holds."""
        if not isinstance(dataset_id, str) or not dataset_id:
            raise FoundryError("structure call requires a dataset_id")
        self._authorize({"source": dataset_id})
        return self.analysis.read_dataset(dataset_id)

    def dataset_structure_state(self, dataset_id):
        from foundry.structure_records import structure_state

        try:
            dataset = self.analysis.read_dataset(dataset_id)
        except FoundryError:
            return NOT_APPLICABLE
        derived = (dataset.get("transformation") or {}).get("structure")
        if derived:
            owning = [
                row
                for row in self._list("structure_confirmations")
                if dataset_id in (row.get("snapshot_ids") or {}).values()
            ]
            return structure_state(None, owning, is_snapshot=True)
        proposals = self._structure_proposals(dataset_id)
        return structure_state(
            latest_proposal(proposals), self._structure_confirmations(dataset_id)
        )

    def structure_propose(self, dataset_id, *, source=None):
        """Record what the engine reads in a freshly filed workbook."""
        from foundry.structure_proposal import propose_workbook_structure
        from foundry.structure_templates import apply_matching_templates

        dataset = self._authorized_dataset(dataset_id)
        if str(dataset.get("source_file") or "").lower() != "source.xlsx":
            return None
        if (dataset.get("transformation") or {}).get("structure"):
            # Already the product of a confirmed structure; there is nothing to read.
            return None
        folder = self.analysis._inside(self.analysis.root / "datasets" / dataset_id)
        data = (folder / dataset["source_file"]).read_bytes()
        if _hash_bytes(data) != dataset["source_hash"]:
            raise FoundryError("dataset integrity check failed")
        proposed = propose_workbook_structure(data)
        sheets, matches = apply_matching_templates(self, proposed["sheets"])
        existing = self._structure_proposals(dataset_id)
        revision = (latest_proposal(existing) or {}).get("revision", 0) + 1
        record = self._write(
            "structure_proposals",
            dataset_id=dataset_id,
            revision=revision,
            sheets=sheets,
            template_matches=matches,
            bindings={"source": dataset_id},
        )
        auto = [match for match in matches if match.get("auto_apply")]
        if auto:
            self._confirm_declaration(
                record,
                [sheet for sheet in sheets if sheet["sheet"] in {m["sheet"] for m in auto}],
                source=TEMPLATE,
                triggered_by=source or self.actor,
            )
        return record

    def structure_proposal_list(self, spec):
        if not isinstance(spec, dict):
            raise FoundryError("structure proposal list spec must be an object")
        dataset_id = spec.get("dataset_id")
        if dataset_id:
            self._authorized_dataset(dataset_id)
            proposals = self._structure_proposals(dataset_id)
            latest = latest_proposal(proposals)
            return {
                "schema_version": 1,
                "proposals": [self._public_proposal(latest)] if latest else [],
            }
        by_dataset = {}
        for row in self._list("structure_proposals"):
            current = by_dataset.get(row["dataset_id"])
            if current is None or row.get("revision", 0) > current.get("revision", 0):
                by_dataset[row["dataset_id"]] = row
        return {
            "schema_version": 1,
            "proposals": [self._public_proposal(row) for row in by_dataset.values()],
        }

    def _public_proposal(self, record):
        return {
            "id": record["id"],
            "dataset_id": record["dataset_id"],
            "revision": record["revision"],
            "structure_state": self.dataset_structure_state(record["dataset_id"]),
            "sheets": record["sheets"],
            "template_matches": record.get("template_matches") or [],
        }

    def structure_proposal_confirm(self, spec):
        from foundry.structure_records import (
            assert_confirmable,
            reject_forbidden_spec,
            strip_claimed_source,
        )

        spec = reject_forbidden_spec(spec)
        spec, claimed = strip_claimed_source(spec)
        self._refuse_child_session("confirm a table structure")
        dataset_id = spec.get("dataset_id")
        self._authorized_dataset(dataset_id)
        proposals = self._structure_proposals(dataset_id)
        latest = latest_proposal(proposals)
        if latest is None:
            raise FoundryError("no table structure proposal for this dataset")
        revision = spec.get("revision")
        if revision is not None and int(revision) != latest["revision"]:
            raise FoundryError(
                "table structure proposal has moved on; reload before confirming"
            )
        sheets = spec.get("sheets")
        if sheets is None:
            sheets = [
                sheet for sheet in latest["sheets"] if sheet.get("decision") == "table"
            ]
        if not isinstance(sheets, list):
            raise FoundryError("structure confirmation sheets must be a list")
        known = {sheet["sheet"] for sheet in latest["sheets"]}
        unknown = [item.get("sheet") for item in sheets if item.get("sheet") not in known]
        if unknown:
            raise FoundryError(f"sheet is not in the proposal: {unknown[0]}")
        assert_confirmable(sheets)
        record = self._confirm_declaration(
            latest, sheets, source=self.actor, triggered_by=self.actor
        )
        if claimed:
            record = {
                **record,
                "diagnostics": [
                    {
                        "severity": "warning",
                        "code": "claimed_source_stripped",
                        "message": "confirmation source comes from the call, not the request",
                    }
                ],
            }
        return record

    def _confirm_declaration(self, proposal, sheets, *, source, triggered_by):
        from foundry.locking import exclusive
        from foundry.structure_records import (
            active_confirmation,
            state_for_source,
        )
        from foundry.structure_templates import remember_declaration

        dataset_id = proposal["dataset_id"]
        with exclusive(self.task.lock_path, timeout=10):
            existing = self._structure_confirmations(dataset_id)
            if active_confirmation(existing) is not None:
                raise FoundryError(
                    "this dataset already has a confirmed table structure; "
                    "withdraw it before confirming again"
                )
        from foundry.structure_snapshot import undeclarable_reason

        wanted = [sheet for sheet in sheets if sheet.get("decision") == "table"]
        # Every sheet is checked before any is written. One confirmation is one
        # act: a refusal on the fourth sheet must not leave the first three
        # standing as snapshots nothing points at.
        for sheet in wanted:
            refusal = undeclarable_reason(sheet)
            if refusal:
                raise FoundryError(
                    f"cannot confirm {sheet.get('sheet') or 'this sheet'}: {refusal}"
                )
        snapshots = {}
        for sheet in wanted:
            snapshot = self.analysis.add_table_snapshot(
                dataset_id, sheet, name=sheet["sheet"]
            )
            snapshots[sheet["sheet"]] = snapshot["id"]
        if not snapshots:
            raise FoundryError("structure confirmation produced no table")
        record = self._write(
            "structure_confirmations",
            dataset_id=dataset_id,
            proposal_id=proposal["id"],
            proposal_revision=proposal["revision"],
            sheets=sheets,
            snapshot_ids=snapshots,
            source=source,
            triggered_by_actor=triggered_by,
            triggered_by_session=self.session_id,
            state=state_for_source(source),
            parent_id=None,
            bindings={"source": dataset_id},
        )
        if source == MANAGER:
            remember_declaration(self, sheets)
        self._widen_session(list(snapshots.values()))
        return record

    def _widen_session(self, snapshot_ids):
        """Keep a narrowed caller able to read the table it just confirmed."""
        if not snapshot_ids:
            return
        if self.allowed is not None:
            self.allowed.update(snapshot_ids)
        if not self.session_id:
            return
        row = self.task.update_session_context(
            self.session_id,
            snapshot_ids=list(dict.fromkeys([*(self.allowed or []), *snapshot_ids])),
        )
        self.context_revision = row.get("context_revision", self.context_revision)

    def _refuse_child_session(self, action):
        if not self.session_id:
            return
        session = next(
            (
                row
                for row in self.task.sessions()
                if row["session_id"] == self.session_id
            ),
            None,
        )
        if session and session.get("parent_session_id"):
            raise FoundryError(f"child sessions cannot {action}")

    def _manager_only(self, action):
        if self.actor != MANAGER:
            raise FoundryError(f"only the manager can {action}")

    def structure_acknowledge(self, spec):
        return self._settle_confirmation(spec, ACKNOWLEDGED, "acknowledge a structure")

    def structure_reject(self, spec):
        return self._settle_confirmation(spec, WITHDRAWN, "reject a structure")

    def structure_withdraw(self, spec):
        return self._settle_confirmation(spec, WITHDRAWN, "withdraw a structure")

    def _settle_confirmation(self, spec, state, action):
        from foundry.structure_templates import demote_declaration

        if not isinstance(spec, dict) or not spec.get("id"):
            raise FoundryError(f"{action} requires a confirmation id")
        self._manager_only(action)
        current = self._read("structure_confirmations", spec["id"])
        if current.get("state") not in ACTIVE_STATES:
            raise FoundryError("this confirmation is already settled")
        if state == ACKNOWLEDGED and current["state"] != PENDING_ACKNOWLEDGEMENT:
            raise FoundryError("only a pending confirmation can be acknowledged")
        record = self._write(
            "structure_confirmations",
            dataset_id=current["dataset_id"],
            proposal_id=current["proposal_id"],
            proposal_revision=current["proposal_revision"],
            sheets=current["sheets"],
            snapshot_ids=current["snapshot_ids"],
            source=current["source"],
            triggered_by_actor=self.actor,
            triggered_by_session=self.session_id,
            state=state,
            parent_id=current["id"],
            bindings=current["bindings"],
        )
        if state == ACKNOWLEDGED:
            from foundry.structure_templates import remember_declaration

            remember_declaration(self, current["sheets"])
        else:
            demote_declaration(self, current["sheets"])
        return record

    def structure_confirmation_list(self, spec):
        spec = spec or {}
        dataset_id = spec.get("dataset_id") if isinstance(spec, dict) else None
        rows = self._list("structure_confirmations")
        if dataset_id:
            rows = [row for row in rows if row.get("dataset_id") == dataset_id]
        return {"schema_version": 1, "confirmations": rows}

    def structure_template_list(self, spec):
        from foundry.structure_templates import public_template, registry_for

        del spec
        # Templates are the store's memory, not this task's: a period that has
        # confirmed nothing still sees what earlier periods settled.
        return {
            "schema_version": 1,
            "templates": [
                public_template(row) for row in registry_for(self).list()
            ],
        }

    def structure_template_disable(self, spec):
        from foundry.structure_templates import disable_template

        if not isinstance(spec, dict) or not spec.get("id"):
            raise FoundryError("disabling a structure template requires an id")
        self._manager_only("disable a structure template")
        return disable_template(self, spec["id"])

    def _template_root(self):
        return self.analysis._inside(self.analysis.root / "report_templates")

    def _published_templates(self):
        root = self._template_root()
        if not root.is_dir():
            return []
        records = []
        for path in sorted(root.glob("*.json")):
            record = self.analysis._read(path)
            if (root / f"{record['id']}.bin").is_file():
                records.append(record)
        return records

    def _template_record(self, template_id):
        from foundry.report_templates import bundled_templates

        for item in bundled_templates():
            if item["template_id"] == template_id:
                return {**item, "origin": "bundled"}
        for record in self._published_templates():
            if record.get("template_id") == template_id:
                return record
        raise FoundryError("unknown report template")

    def report_template_list(self, spec):
        from foundry.report_templates import bundled_templates, public_item

        items = bundled_templates()
        items.extend(public_item(record) for record in self._published_templates())
        return {"templates": items}

    def report_template_publish(self, spec):
        from pathlib import Path
        from foundry.report_templates import public_item, reject_pptx

        if not isinstance(spec, dict):
            raise FoundryError("template publish spec must be an object")
        from foundry.report_templates import TEMPLATE_MAX_BYTES

        source = Path(spec.get("path", ""))
        if not source.is_file() or source.is_symlink():
            raise FoundryError("company template must be a regular file")
        if source.stat().st_size > TEMPLATE_MAX_BYTES:
            raise FoundryError("company template exceeds the 25 MiB limit")
        data = source.read_bytes()
        kind = reject_pptx(source, data)
        label = _safe_text(spec.get("label") or source.stem, "template label", required=True, maximum=300)
        record = _new(
            self.task,
            domain="foundry.finance.report_templates.v1",
            template_id="pending",
            label=label,
            kind=kind,
            sha256=_hash_bytes(data),
            bindings={},
        )
        record["template_id"] = record["id"]
        root = self._template_root()
        root.mkdir(parents=True, exist_ok=True)
        (root / f"{record['id']}.bin").write_bytes(data)
        stored = self.analysis._write(root / f"{record['id']}.json", record)
        return public_item(stored)

    def _report_source_from_bytes(self, data: bytes, suffix: str, *, name: str = "") -> dict:
        """File bytes we built ourselves as a report source.

        The temporary file is how the bytes reach the archive, not what the
        manager applied: naming the source after it put tmppcj2w5jg.docx in her
        draft where 经营简报 belonged.
        """
        from pathlib import Path
        from tempfile import NamedTemporaryFile

        with NamedTemporaryFile(suffix=suffix, delete=False) as handle:
            handle.write(data)
            path = handle.name
        try:
            return self.analysis.add_report_source(
                path, name=f"{name}{suffix}" if name else None
            )["source"]
        finally:
            Path(path).unlink(missing_ok=True)

    def report_template_apply(self, spec):
        from foundry.report_documents import validate_report_document
        from foundry.report_templates import (
            apply_excel_named_ranges,
            bundled_document,
            bundled_excel_bytes,
            metadata_from_scope,
            named_range_names,
            values_from_run,
        )

        if not isinstance(spec, dict):
            raise FoundryError("template apply spec must be an object")
        template_id = spec.get("template_id")
        record = self._template_record(template_id)
        scope = spec.get("scope")
        if spec.get("context_id"):
            context = self._read("contexts", spec["context_id"])
            scope = self._primary_scope(context.get("scopes")) or scope
        metadata = metadata_from_scope(scope)
        filled: list[str] = []
        unfilled: list[str] = []
        if record.get("kind") == "excel":
            if "values" in spec:
                raise FoundryError("excel template values come from run_id, not the caller")
            data = bundled_excel_bytes(template_id) if record.get("origin") == "bundled" else (
                self._template_root() / f"{record['id']}.bin"
            ).read_bytes()
            applied = data
            if spec.get("run_id"):
                run = self.analysis.get_run(spec["run_id"])
                self._authorize(run.get("bindings") or {})
                values, unfilled = values_from_run(run, named_range_names(data))
                if values:
                    applied = apply_excel_named_ranges(data, values)
                    filled = sorted(values)
            source = self._report_source_from_bytes(
                applied, ".xlsx", name=record.get("label") or str(template_id)
            )
            document = validate_report_document(
                {
                    "schema_version": 1,
                    "template_version": "annual-v1",
                    "template_id": template_id,
                    "metadata": metadata,
                    "sources": [source],
                    "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": "已套用 Excel 公司模板。"}]}
                    ],
                },
                registered_source_ids={source["id"]},
            )
        elif record.get("origin") == "bundled":
            document = bundled_document(template_id)
            document = {**document, "template_id": template_id, "metadata": {**document.get("metadata", {}), **metadata}}
        else:
            source = self._report_source_from_bytes(
                (self._template_root() / f"{record['id']}.bin").read_bytes(),
                ".docx",
                name=record.get("label") or str(template_id),
            )
            document = validate_report_document(
                {
                    "schema_version": 1,
                    "template_version": "annual-v1",
                    "template_id": template_id,
                    "metadata": metadata,
                    "sources": [source],
                    "content": [
                        {"type": "heading", "attrs": {"level": 1}, "content": [{"type": "text", "text": record.get("label") or "本公司模板"}]},
                        {"type": "paragraph", "content": [{"type": "text", "text": "已套用已发布公司模板。"}]},
                    ],
                },
                registered_source_ids={source["id"]},
            )
        draft = self.analysis.save_draft({"title": record.get("label") or template_id, "document": document})
        return {
            "draft": draft,
            "template_id": template_id,
            "kind": record.get("kind"),
            "filled_named_ranges": filled,
            "unfilled_named_ranges": unfilled,
        }

    def chart_deliverable_save(self, spec):
        from foundry.chart_deliverables import normalize_chart

        if not isinstance(spec, dict) or not spec.get("run_id"):
            raise FoundryError("chart save requires run_id")
        run = self.analysis.get_run(spec["run_id"])
        self._authorize(run.get("bindings", {}))
        if spec.get("parent_id"):
            parent = self._read("charts", spec["parent_id"])
            self._authorize(parent.get("bindings", {}))
        return self._write("charts", **normalize_chart(spec, run=run))

    def chart_deliverable_open(self, spec):
        from foundry.chart_deliverables import verify_snapshots

        if not isinstance(spec, dict) or not spec.get("id"):
            raise FoundryError("chart open requires id")
        record = self._read("charts", spec["id"])
        if not record.get("bindings"):
            raise FoundryError("chart bindings are required")
        verify_snapshots(self, record)
        return record

    def chart_deliverable_list(self, spec):
        spec = spec or {}
        if spec and not isinstance(spec, dict):
            raise FoundryError("chart list spec must be an object")
        rows = self._list("charts")
        if isinstance(spec, dict) and spec.get("run_id"):
            rows = [row for row in rows if row.get("run_id") == spec["run_id"]]
        return {"charts": rows}

    def analysis_circle_select(self, spec):
        from foundry.circle_select import authorize_workbook, match_draft_table, reject_forbidden_spec
        from foundry.finance_requirements import latest_requirements

        reject_forbidden_spec(spec)
        kind = spec.get("kind")
        if kind not in {"draft_table", "workbook"}:
            raise FoundryError("circle-select kind must be draft_table or workbook")
        range_text = spec.get("range")
        if not isinstance(range_text, str) or not range_text.strip():
            raise FoundryError("circle-select requires a range")
        if not spec.get("context_id"):
            raise FoundryError("circle-select requires context_id")
        context = self._read("contexts", spec["context_id"])
        latest = latest_requirements(self.analysis)
        if spec.get("parent_id") and (not latest or spec["parent_id"] != latest["id"]):
            raise FoundryError("circle-select parent_id must be the latest requirements version")
        if kind == "draft_table":
            if not spec.get("draft_id"):
                raise FoundryError("draft table circle-select requires draft_id")
            match_draft_table(self.analysis.get_draft(spec["draft_id"]), spec)
        else:
            authorize_workbook(self, spec, context)
        instruction = _safe_text(
            spec.get("instruction"),
            "circle-select instruction",
            required=True,
            maximum=200,
        )
        selection = {"kind": kind, "range": range_text.strip()}
        if kind == "draft_table":
            selection["draft_id"] = str(spec["draft_id"])
            selection["block_id"] = str(spec["block_id"]).strip()
        else:
            selection["binding_id"] = str(spec["binding_id"])
        child = self.save_context(
            {
                "parent_id": context["id"],
                "name": context.get("name") or "财务分析口径",
                "bindings": context["bindings"],
                "scopes": context.get("scopes") or {},
                "policies": context.get("policies") or {},
                "account_map_id": context.get("account_map_id"),
            }
        )
        if not latest:
            # 改口径 revises a stated scope. With none on file the instruction
            # would be filed as the analytical question, and every later reader
            # would take 「按区域拆开」 for what was asked.
            raise FoundryError(
                "circle-select revises an existing analysis; none has been stated yet"
            )
        req_spec = {
            "context_id": child["id"],
            "question": latest.get("question") or instruction,
            "items": latest.get("items") or [],
            "change_reason": instruction,
            "selection": selection,
        }
        req_spec["parent_id"] = latest["id"]
        return {"requirements": self.analysis_requirements_save(req_spec), "context": child}



def _dedupe_explanation_claims(claims):
    seen = set()
    result = []
    for claim in claims:
        key = None
        if isinstance(claim, dict) and claim.get("basis") == "calculation":
            key = (
                "calculation",
                claim.get("fact_id"),
                claim.get("run_id"),
                claim.get("row"),
                claim.get("column"),
            )
        if key is not None:
            if key in seen:
                if isinstance(claim, dict) and "presentation" in claim:
                    for existing in result:
                        if (
                            isinstance(existing, dict)
                            and existing.get("basis") == "calculation"
                            and (
                                "calculation",
                                existing.get("fact_id"),
                                existing.get("run_id"),
                                existing.get("row"),
                                existing.get("column"),
                            ) == key
                        ):
                            existing["presentation"] = claim["presentation"]
                            break
                continue
            seen.add(key)
        result.append(claim)
    return result
