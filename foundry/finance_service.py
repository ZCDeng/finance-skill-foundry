"""Finance domain services using task-owned immutable analysis records."""

from __future__ import annotations

from decimal import localcontext

from foundry.analysis import AnalysisStore, _assert_id, _hash, _new, _safe_text
from foundry.errors import FoundryError
from foundry.finance_metrics import evaluate_metric
from foundry.finance_model import normalize_finance_dataset, scoped_source_rows
from foundry.finance_variance import explain_variance, price_quantity_bridge

COLLECTIONS = {"contexts", "account_maps", "scenarios", "metric_definitions"}


class FinanceStore:
    def __init__(
        self, task, *, snapshot_ids=None, session_id=None, context_revision=None
    ):
        self.analysis = AnalysisStore(task)
        self.task = task
        self.allowed = None if snapshot_ids is None else set(snapshot_ids)
        self.session_id = session_id
        self.context_revision = context_revision

    def _path(self, kind, object_id):
        if kind not in COLLECTIONS:
            raise FoundryError("unknown finance collection")
        return self.analysis._inside(
            self.analysis.root / "finance" / kind / f"{_assert_id(object_id)}.json"
        )

    def _read(self, kind, object_id):
        record = self.analysis._read(self._path(kind, object_id))
        self._authorize(record.get("bindings", {}))
        return record

    def _write(self, collection, **fields):
        record = _new(self.task, domain=f"foundry.finance.{collection}.v1", **fields)
        return self.analysis._write(self._path(collection, record["id"]), record)

    def _list(self, kind):
        root = self.analysis._inside(self.analysis.root / "finance" / kind)
        records = [self.analysis._read(path) for path in root.glob("*.json")]
        return sorted(
            [
                r
                for r in records
                if self.allowed is None
                or set(r.get("bindings", {}).values()) <= self.allowed
            ],
            key=lambda r: r["seq"],
        )

    def _authorize(self, bindings):
        if not isinstance(bindings, dict) or any(
            not isinstance(v, str) for v in bindings.values()
        ):
            raise FoundryError("finance bindings must map aliases to snapshot IDs")
        if self.allowed is not None and not set(bindings.values()) <= self.allowed:
            raise FoundryError("finance snapshots are outside this session context")
        for dataset_id in bindings.values():
            _assert_id(dataset_id)

    def list_finance_context(self):
        state = self.analysis.state()
        return {
            "task_id": self.task.id,
            "domain": "foundry.finance.context.v1",
            "datasets": [
                r
                for r in state["datasets"]
                if self.allowed is None or r["id"] in self.allowed
            ],
            "contexts": self._list("contexts"),
            "account_maps": self._list("account_maps"),
            "scenarios": self._list("scenarios"),
            "metric_definitions": self._list("metric_definitions"),
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

    def drilldown_fact(self, spec):
        run = self.analysis.get_run(spec["run_id"])
        self._authorize(run["bindings"])
        index = spec.get("row", 0)
        rows = run.get("result", {}).get("rows", [])
        if (
            isinstance(index, bool)
            or not isinstance(index, int)
            or not 0 <= index < len(rows)
        ):
            raise FoundryError("result row is outside the run")
        row = rows[index]
        column = spec.get("column")
        refs = row.get("evidence", {}).get(column, row.get("source_rows", []))
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
            values.append(
                {
                    "source": ref,
                    "source_hash": dataset["source_hash"],
                    "data": source,
                    "voucher_detail_available": bool(
                        source.get("doc_id") and source.get("line_id")
                    ),
                }
            )
        return {
            "run_id": run["id"],
            "row": index,
            "column": column,
            "rows": values,
            "total": len(unique),
            "offset": offset,
            "has_more": offset + len(values) < len(unique),
            "message": "来源行可查看；仅有余额资料时不提供凭证分录链接。",
        }

    def save_explanation_draft(self, spec):
        parent = (
            self.analysis.get_draft(spec["parent_id"]) if spec.get("parent_id") else {}
        )
        for run_id in [
            *parent.get("run_ids", []),
            *spec.get("run_ids", parent.get("run_ids", [])),
        ]:
            self._authorize(self.analysis.get_run(run_id)["bindings"])
        claims = []
        for claim in spec.get("claims", parent.get("claims", [])):
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
        return self.analysis.save_draft({**spec, "claims": claims})
