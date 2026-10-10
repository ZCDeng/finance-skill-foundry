"""Finance domain services using task-owned immutable analysis records."""

from __future__ import annotations

import copy
import re
from decimal import localcontext
from time import perf_counter

from foundry.analysis import (DRAFT_UNAVAILABLE, PARENT_UNAVAILABLE, RUN_UNAVAILABLE, AnalysisStore, _assert_id, _default_materiality,
                             _hash, _hash_bytes, _new, _safe_text, _saved_by)
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

# 3: display strings (amount_change_display, profit_impact_display, *_display) read at two places with grouped
# thousands, so an earlier run's output hash cannot confirm or refute a rerun (it reads unverified).
FINANCE_CALCULATION_VERSION = 3
"""What the finance engine computes, recorded on each run beside (not in) its result.

2 marks an account with source rows on one side only as partial (缺项). Runs
from before carry no version and read as 1. The fingerprint's "finance-v1"
runner string stays, so a rerun still finds those runs; it compares strictly
only with runs of its own version (see _reproducibility_status).
"""
# Said to the model and shown on the failed run: what was bound, and the way to a readable table.
WORKBOOK_SHELL_MESSAGE = (
    "finance binding '{alias}' is a whole workbook whose table structure is not confirmed, "
    "so the finance engine has no rows to read; check finance_readiness, confirm the sheet with "
    "structure_proposal_list and structure_proposal_confirm, then bind the confirmed table"
)
SCENARIO_KINDS = frozenset({"receivables_aging", "cash_13_weeks", "driver_model", "collection_health"})

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
    "controls",
    "control_runs",
    "control_dispositions",
    "control_settings",
    "control_findings",
    "report_reviews",
    "dashboards",
    "month_briefs",
}


def _control_summary(results, total=None):
    confirmed = [row for row in results if row.get("state") == "confirmed"]
    counts = {status: sum(1 for row in confirmed if row.get("status") == status) for status in ("pass", "break", "stale", "error")}
    # Breaks a display rounding could explain are still breaks; this only says how many of them there are.
    counts["break_within_rounding"] = sum(1 for row in confirmed if row.get("status") == "break" and row.get("within_rounding"))
    return {
        "controls": len(results) if total is None else total,
        "confirmed": len(confirmed),
        "proposed_results": sum(1 for row in results if row.get("state") == "proposed"),
        **counts,
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


def _closing_month(period):
    """The month a scope period closes, as YYYY-MM: the month itself, or the last month of a span.

    None when the scope names no single closing month it can be read from (a year, free text).
    """
    from foundry.evidence_labels import period_span

    if isinstance(period, (list, tuple)):
        months = [_closing_month(item) for item in period]
        return max(months) if months and all(months) else None
    if not isinstance(period, str):
        return None
    text = period.strip()
    parts = re.split(r"\s*(?:至|到|~|～|—|–)\s*", text)
    span = period_span(text) or (period_span(f"{parts[0]}:{parts[1]}") if len(parts) == 2 else None)
    return span[1][:7] if span and span[2] in {"month", "range", "as_of"} else None


def _other_month_workbooks(rows, current, period):
    """Workbooks a roll-forward places in another month than the task's, by source hash.

    A copy made for this month comes from last month's workbook, its template. A copy made for
    another month is that month's, and so is the file it was saved as in Excel and added again
    under its name; when that month is earlier than the task's, so is its template. A copy whose
    month is unknown here, or a task whose closing month is, counts as this month's.
    """
    closing = _closing_month(period)
    found: set[str] = set()
    elsewhere: set[str] = set()
    for row in rows:
        metadata = row.get("metadata") or {}
        rolled = metadata.get("rollforward") or {}
        if not rolled.get("source_hash"):
            continue
        month = metadata.get("period")
        if closing and month and month != closing:
            found.add(row.get("source_hash") or row["id"])
            elsewhere.add(str(row.get("name") or ""))
            if month < closing:
                found.add(rolled["source_hash"])
        else:
            found.add(rolled["source_hash"])
    found.update(row.get("source_hash") or row["id"] for row in current if row.get("name") and row["name"] in elsewhere)
    return found


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

    def _authorize_current(self, current):
        """The task's current requirements version, which a save is checked against. A session is refused one it may
        not read (finance_requirements.requirements_readable), one with malformed bindings as one on files outside it;
        the manager as before (_authorize)."""
        if not current:
            return
        if self.allowed is not None:
            from foundry.finance_requirements import requirements_readable

            if not requirements_readable(current, self.allowed):
                raise FoundryError("finance snapshots are outside this session context")
        self._authorize(current.get("bindings", {}))

    def _authorize_evidence_recipes(self, recipes):
        from foundry.financial_evidence import recipe_dataset_ids, recipe_run_ids

        for dataset_id in recipe_dataset_ids(recipes):
            self._authorize({"evidence": dataset_id})
        # A recipe's claim cites a run cell, whose value the recipe's result shows: a session may cite only a run it
        # may read (analysis_cli._bound_evidence). The manager's recipes report a run that does not read as an issue.
        if self.allowed is not None:
            for run_id in recipe_run_ids(recipes):
                self._named_run(run_id)

    def _authorize_consistency_sources(self, sources):
        from foundry.financial_evidence import consistency_dataset_ids

        for dataset_id in consistency_dataset_ids(sources):
            self._authorize({"consistency": dataset_id})

    def _authorize_draft(self, draft):
        """Every snapshot a saved draft rests on (AnalysisStore.draft_snapshots), as analysis_cli._bound_draft checks it.
        The manager reads a draft whose own runs and records read."""
        if self.allowed is not None:
            self._authorize({f"source{index}": dataset_id
                             for index, dataset_id in enumerate(sorted(self.analysis.draft_snapshots(draft)))})
            return
        for run_id in draft.get("run_ids", []):
            self._authorize(self.analysis.get_run(run_id)["bindings"])
        for claim in draft.get("claims", []):
            if isinstance(claim, dict):
                if claim.get("dataset_id"):
                    self._authorize({"source": claim["dataset_id"]})
                if claim.get("run_id"):
                    self._authorize(self.analysis.get_run(claim["run_id"])["bindings"])
        recipes = draft.get("evidence_recipes", [])
        self._authorize_evidence_recipes(recipes)
        for recipe in recipes:
            claim = recipe.get("claim") if isinstance(recipe, dict) else None
            if isinstance(claim, dict) and claim.get("run_id"):
                self._authorize(self.analysis.get_run(claim["run_id"])["bindings"])
        self._authorize_consistency_sources(draft.get("consistency_sources", {}))
        if draft.get("requirements_id"):
            self._authorize(self.analysis._get("requirements", draft["requirements_id"]).get("bindings", {}))

    def _named_draft(self, draft_id):
        """A saved draft a call names by id. A session is refused one it may not read (_authorize_draft) exactly as an
        unknown id; the manager reads it as stored."""
        if self.allowed is None:
            return self.analysis.get_draft(draft_id)
        try:
            draft = self.analysis.get_draft(draft_id)
            self._authorize_draft(draft)
        except FoundryError:
            raise FoundryError(DRAFT_UNAVAILABLE) from None
        return draft

    def _parent_draft(self, parent_id):
        """The draft a revision names as its parent. A session is refused one it may not read exactly as an unknown id."""
        if not parent_id:
            return {}
        if self.allowed is None:
            return self.analysis.get_draft(parent_id)
        try:
            parent = self.analysis.get_draft(parent_id)
            self._authorize_draft(parent)
        except FoundryError:
            raise FoundryError(PARENT_UNAVAILABLE) from None
        return parent

    def _named_requirements(self, requirements_id):
        """A requirements version a call names by id. A session is refused one it may not read exactly as an unknown
        or malformed id (AnalysisStore.named_requirements); the manager reads it as stored."""
        if self.allowed is None:
            self._authorize(self.analysis._get("requirements", requirements_id).get("bindings", {}))
            return
        self.analysis.named_requirements(requirements_id, self.allowed)

    def _named_run(self, run_id):
        """A run a call names by id (an explanation's run_ids, a claim's or a recipe's run). A session is refused one it
        may not read exactly as an unknown or malformed id; the manager reads it as stored."""
        if self.allowed is None:
            run = self.analysis.get_run(run_id)
            self._authorize(run["bindings"])
            return run
        try:
            run = self.analysis.get_run(run_id)
            self._authorize(run["bindings"])
        except FoundryError:
            raise FoundryError(RUN_UNAVAILABLE) from None
        return run

    def list_finance_context(self):
        from foundry.finance_requirement_support import metric_catalog
        from foundry.source_refresh import snapshots_in_view

        state = self.analysis.state()
        return {
            "task_id": self.task.id,
            "domain": "foundry.finance.context.v1",
            # A refreshed snapshot names the prior its batch reads with to this reader (snapshots_in_view).
            "datasets": [
                {**r, "structure_state": self.dataset_structure_state(r["id"])}
                for r in snapshots_in_view(self.analysis, [r for r in state["datasets"]
                                                           if self.allowed is None or r["id"] in self.allowed],
                                           self.allowed)
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
        from foundry.finance_readiness import _is_workbook_shell

        for alias, dataset_id in context["bindings"].items():
            dataset = self.analysis.read_dataset(dataset_id)
            if _is_workbook_shell(dataset):
                # A warning, not an error: beside a table the engine reads, the workbook is only
                # kept for recipes and must not mark that run incomplete. run_revision fails the
                # run when nothing at all was read.
                combined["diagnostics"].append({
                    "severity": "warning",
                    "code": "workbook_structure_unconfirmed",
                    "message": WORKBOOK_SHELL_MESSAGE.format(alias=alias),
                    "alias": alias,
                })
                continue
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
            **_saved_by(self.session_id, self.context_revision),
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
        if kind not in SCENARIO_KINDS:
            raise FoundryError(
                "scenario kind must be receivables_aging, cash_13_weeks, driver_model or collection_health"
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
        started = perf_counter()
        requirements_snapshot = capture_requirements(self.analysis, self._authorize, allowed=self.allowed)
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
            # The fingerprint hashes the context, so these rest on its files; stated as for run_analysis all the same.
            and (self.allowed is None or set((r.get("bindings") or {}).values()) <= self.allowed)
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
                    # Reading nothing because the only rows sit in whole workbooks is not a zero result.
                    # A workbook bound beside a table the engine reads (kept for recipes) is fine.
                    unread = [d["message"] for d in normalized["diagnostics"] if d.get("code") == "workbook_structure_unconfirmed"]
                    if unread and not normalized["rows"]:
                        raise FoundryError(unread[0])
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
            reproducibility_status = _reproducibility_status(previous, output_hash)
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
        # Engine time, beside the result like calculation_version: a slower run of the same output keeps its hash.
        duration_seconds = round(perf_counter() - started, 3)
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
            calculation_version=FINANCE_CALCULATION_VERSION,
            duration_seconds=duration_seconds,
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
        self._authorize_current(parent)
        context_scopes = None
        if spec.get("context_id"):
            context = self._read("contexts", spec["context_id"])
            spec = {**spec, "bindings": context["bindings"],
                    "scope": spec.get("scope", self._primary_scope(context.get("scopes", {})))}
            # A hierarchy level the context's own scope holds is carried over into the requirement scope
            # (the panel seeds from it), so save drops it instead of refusing it as newly written.
            context_scopes = [scope for scope in (context.get("scopes") or {}).values() if isinstance(scope, dict)]
        self._authorize(spec.get("bindings", {}))
        saved = save_requirements(self.analysis, spec, _context_scopes=context_scopes, _allowed=self.allowed)
        if self.allowed is None:
            return saved
        from foundry.finance_requirements import requirements_version_view

        # A session reads the version it saved as its listing reads it (circle-select returns it too).
        return requirements_version_view(self.analysis, saved, self.allowed)

    def analysis_requirements_list(self, spec):
        from foundry.finance_requirements import requirements_readable

        records = self.analysis._list("requirements")
        visible = [r for r in records if requirements_readable(r, self.allowed)]
        if spec.get("context_id"):
            self._read("contexts", spec["context_id"])
            visible = [r for r in visible if r.get("context_id") == spec["context_id"]]
        if self.allowed is not None:
            from foundry.finance_requirements import requirements_version_view

            # Each as the session reads it, reading every version and every draft a selection names once.
            versions, drafts = {r.get("id"): r for r in records}, {}
            visible = [requirements_version_view(self.analysis, r, self.allowed, versions=versions, drafts=drafts)
                       for r in visible]
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
        self._authorize_current(requirements)
        if spec.get("requirements_id"):
            self._named_requirements(spec["requirements_id"])
        for claim in spec.get("claims", []):
            if isinstance(claim, dict) and claim.get("dataset_id"):
                self._authorize({"source": claim["dataset_id"]})
            if isinstance(claim, dict) and claim.get("run_id"):
                # Whatever its basis, the draft rests on the run a claim names (AnalysisStore.draft_snapshots).
                self._named_run(claim["run_id"])
        for run_id in spec.get("run_ids", []):
            self._named_run(run_id)
        self._authorize_evidence_recipes(spec.get("evidence_recipes", []))
        self._authorize_consistency_sources(spec.get("consistency_sources", {}))
        self._parent_draft(spec.get("parent_id"))
        operations = CompletionOperationStore(self.task, self.session_id, self.allowed)
        # Whether the session may read each receipt its operation is settled on is read before completion.lock, as
        # before the task lock (CompletionOperationStore._prime): reserve, get and settle under it only look it up.
        operations._prime(operation_id)
        with exclusive(self.analysis._inside(self.analysis.root / "completion.lock"), timeout=10):
            reserved = operations.reserve(operation_id, payload=spec, call_id=call_id)
            attempt = reserved["attempt"]
            if attempt.get("status") == "rejected_validation":
                error = attempt.get("error") if isinstance(attempt.get("error"), dict) else {}
                message = error.get("message") if isinstance(error.get("message"), str) else "completion validation failed"
                raise FoundryError(message)
            key = _hash({"operation_id": operation_id, "call_id": call_id})
            previous = _replayable_draft([row for row in self.analysis._list("drafts")
                                          if row.get("completion_request_key") == key], attempt)
            # The save, its receipt and the draft and receipt it returns are one read (AnalysisStore.save_draft).
            cache: dict = {}
            if previous:
                self._authorize_draft(previous)
                receipt = self._settled_receipt(
                    self.analysis._get("completions", attempt["completion_id"]) if attempt.get("completion_id") else
                    record_completion(self.analysis, previous, previous["explanation_check"], allowed=self.allowed,
                                      cache=cache), cache=cache, operations=operations)
                operation = operations.settle(operation_id, attempt["revision"], previous, receipt)
                return {**self._readable_draft(previous, cache=cache), "completion": receipt,
                        "completion_operation": operation, "replayed": True, "validation_basis": "saved_draft_version"}

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
                result = self._save_explanation_draft(save_spec, check_deadline=check_deadline, cache=cache)
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
            # The session's operation goes on as its own saves would have spent the budget (completion_in_view).
            receipt = self._settled_receipt(result["completion"], cache=cache, operations=operations)
            operation = operations.settle(operation_id, attempt["revision"], result, receipt)
            return {**result, "completion": receipt, "completion_operation": operation}

    def recover_completion_draft(self, spec):
        """Manager-owned recovery of an explicitly selected completion attempt.

        The receipt returned is the one stored; a session's operation settles on that receipt as the session reads it
        (_operation_receipt), so where earlier drafts it may not read spent repairs the two can differ."""
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
            saved_by_revision = [row for row in self.analysis._list("drafts")
                                 if row.get("completion_operation_id") == operation["id"]
                                 and row.get("completion_operation_revision") == revision]
            if any(row.get("completion_request_key") != recovery_key for row in saved_by_revision):
                raise FoundryError("completion recovery already saved with a different payload")
            previous_by_revision = _replayable_draft(saved_by_revision, attempt)
            if previous_by_revision:
                receipt = (self.analysis._get("completions", attempt["completion_id"])
                           if attempt.get("completion_id") else
                           record_completion(self.analysis, previous_by_revision, previous_by_revision["explanation_check"]))
                view = self._operation_receipt(operation, receipt)
                # A receipt its session may not read settles nothing of the session's operation (_operation_receipt), and
                # a revision left unsettled so is not settled later behind a newer one, over that revision's verdict. A
                # session's files only widen, so a receipt it could read by those it began with was never held back: an
                # interrupted recovery of it settles late, as on main.
                behind = (operation.get("snapshot_ids") is not None and not attempt.get("completion_id")
                          and int(operation.get("current_revision", 0)) != revision
                          and self.analysis.completion_in_view(receipt, set(operation["snapshot_ids"])) is None)
                settled = (operation if view is None or behind
                           else operations.settle(operation["id"], revision, previous_by_revision, view))
                return {**self._readable_draft(previous_by_revision), "completion": receipt, "completion_operation": settled,
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
            view = self._operation_receipt(operation, result["completion"])
            settled = operation if view is None else operations.settle(operation["id"], revision, result, view)
            return {**result, "completion_operation": settled}

    def _operation_receipt(self, operation, receipt):
        """A receipt as the session that owns a completion operation now reads it, which its operation settles on; None
        when that session may not read it at all (completion_in_view): the operation then stays as the session left it,
        as it would read had the draft never been saved, so neither its ids, its hash nor its verdict reach the session.
        A session's files only ever widen, so it reads by its current ones, and by those it began with when it is no
        longer registered."""
        if operation.get("snapshot_ids") is None:
            return receipt
        owner = next((row for row in self.task.sessions() if row.get("session_id") == operation.get("session_id")), {})
        ceiling = owner.get("snapshot_ids") if isinstance(owner.get("snapshot_ids"), list) else operation["snapshot_ids"]
        return self.analysis.completion_in_view(receipt, set(ceiling))

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
            self._authorize_current(requirements)
            key = _hash({"request": spec, "requirements_id": (requirements or {}).get("id")})
            # A session replays only a save it may read: one it may not read is refused as a fresh save would be.
            previous = _replayable_draft([row for row in self.analysis._list("drafts")
                                          if row.get("completion_request_key") == key
                                          and self.analysis.draft_readable(row, self.allowed)])
            # The save, its receipt and the draft and receipt it returns are one read (AnalysisStore.save_draft).
            cache: dict = {}
            if previous:
                # A retry is refused whatever the fresh save would refuse: the stored draft and the parent it names.
                self._parent_draft(spec.get("parent_id"))
                self._authorize_draft(previous)
                receipt = record_completion(self.analysis, previous, previous["explanation_check"], allowed=self.allowed,
                                            cache=cache)
                return {**self._readable_draft(previous, cache=cache),
                        "completion": self._readable_receipt(receipt, cache=cache), "replayed": True,
                        "validation_basis": "saved_draft_version"}
            result = self._save_explanation_draft({**spec, "completion_request_key": key}, cache=cache)
            return {**result, "completion": self._readable_receipt(result["completion"], cache=cache)}

    def _save_explanation_draft(self, spec, *, check_deadline=lambda: None, cache=None):
        check_deadline()
        parent = self._parent_draft(spec.get("parent_id"))
        self._authorize_evidence_recipes(spec.get("evidence_recipes", parent.get("evidence_recipes", [])))
        self._authorize_consistency_sources(spec.get("consistency_sources", parent.get("consistency_sources", {})))
        if self.session_id and spec.get("review_status", parent.get("review_status", "unreviewed")) != "unreviewed":
            raise FoundryError("runtime drafts cannot mark professional review complete")
        if parent.get("requirements_id"):
            self._authorize(self.analysis._get("requirements", parent["requirements_id"]).get("bindings", {}))
        if spec.get("requirements_id"):
            # The tools expose requirements_id so a revision can name the current version (repin_requirements).
            self._named_requirements(spec["requirements_id"])
        run_ids = spec.get("run_ids", parent.get("run_ids", []))
        if not isinstance(run_ids, list):
            raise FoundryError("run_ids must be an array")
        from foundry.report_visuals import materialize_document

        # What this revision takes over from its parent before save_draft sees the spec, decided as each is composed
        # (the appendix and the read failures are composed again from this revision's own runs).
        inherited = set()
        parent_prose = bool(parent) and "body" not in spec and spec.get("document") is None
        took_document = parent_prose and parent.get("document") is not None
        visual_claims = []
        visual_document = spec.get("document")
        if visual_document is None and "body" not in spec:
            visual_document = parent.get("document")
        if visual_document is not None:
            visual_document, visual_runs, visual_claims = materialize_document(
                self.analysis, visual_document, authorize=self._authorize)
            run_ids = list(dict.fromkeys([*run_ids, *visual_runs]))
            spec = {**spec, "document": visual_document, "run_ids": run_ids}
        for run_id in [*parent.get("run_ids", []), *run_ids]:
            self._named_run(run_id)
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
        if took_document or (parent_prose and body.strip()):
            inherited.add("body")
        if parent and "materiality" not in spec and not _default_materiality(parent.get("materiality")):
            inherited.add("materiality")
        if document is not None:
            from foundry.report_documents import report_document_markdown

            document, template_fact_ids = _render_fact_template_in_document(document, prepared["facts"])
            rendered = report_document_markdown(document)
        else:
            rendered, template_fact_ids = render_fact_template(body, prepared["facts"])
        explicit_fact_ids = spec.get("fact_ids", parent.get("fact_ids", []))
        if not isinstance(explicit_fact_ids, list):
            raise FoundryError("fact_ids must be an array")
        if "fact_ids" not in spec and set(run_ids) != set(parent.get("run_ids", [])):
            # Same rule as AnalysisStore.save_draft: swapped runs must not carry the parent's facts.
            available = {fact["id"] for fact in prepared["facts"]}
            explicit_fact_ids = [fact_id for fact_id in explicit_fact_ids
                                 if not isinstance(fact_id, str) or fact_id in available]
        appendix = render_evidence_appendix(prepared)
        appendix_base_body = appendix["body"]
        fact_ids = list(dict.fromkeys([*explicit_fact_ids, *template_fact_ids, *appendix["fact_ids"]]))
        generated = [*template_fact_ids, *appendix["fact_ids"]]
        if parent and "fact_ids" not in spec and any(fact_id not in generated for fact_id in explicit_fact_ids):
            inherited.add("fact_ids")
        auto_claims = claims_for_facts(prepared["facts"], fact_ids)
        for visual_claim in visual_claims:
            if not any(all(claim.get(key) == visual_claim[key] for key in ("run_id", "row", "column")) for claim in auto_claims):
                auto_claims.append(visual_claim)
        # A parent claim the revision would cite on its own (one of its runs' generated claims) is not taken over.
        if parent and "claims" not in spec and parent.get("claims") and _dedupe_explanation_claims(
                copy.deepcopy([*auto_claims, *parent["claims"]])) != _dedupe_explanation_claims(copy.deepcopy(auto_claims)):
            inherited.add("claims")
        claims = []
        for claim in _dedupe_explanation_claims(
            [*auto_claims, *spec.get("claims", parent.get("claims", []))]
        ):
            if not isinstance(claim, dict):
                raise FoundryError("claims must contain objects")
            claim = dict(claim)
            if claim.get("dataset_id"):
                self._authorize({"source": claim["dataset_id"]})
            if claim.get("run_id") and claim.get("basis") != "calculation" and self.allowed is not None:
                # Whatever its basis, the draft rests on the run a claim names (AnalysisStore.draft_snapshots).
                self._named_run(claim["run_id"])
            if claim.get("basis") == "calculation" and claim.get("run_id"):
                run = self._named_run(claim["run_id"])
                if run.get("engine") == "finance":
                    claim.update(
                        finance_context_id=run["finance_context_id"],
                        finance_scope=run["finance_scope"],
                        metric_id=claim.get("column"),
                        account_map_id=run.get("account_map_id"),
                    )
            claims.append(claim)
        # Read actual requested evidence before evaluating the final draft. The draft's recipes are
        # evaluated once here; the same server-computed report reaches save_draft. The provisional
        # check sees the same claims as the final one, so a cell cited through claims (not fact_ids)
        # still reaches the generated appendix and its 估算 label.
        from foundry.finance_requirements import check_requirements
        from foundry.finance_requirement_support import evidence_basis_appendix, with_input_gaps, input_gap_appendix
        from foundry.financial_evidence import evaluate_evidence_recipes
        evidence_recipes = spec.get("evidence_recipes", parent.get("evidence_recipes", []))
        recipe_report = evaluate_evidence_recipes(self.analysis, evidence_recipes)
        provisional = check_requirements(self.analysis, {
            "run_ids": run_ids, "claims": claims,
            "requirements_id": spec.get("requirements_id", parent.get("requirements_id")),
            "evidence_recipes": evidence_recipes,
        }, _recipe_report=recipe_report)
        provisional = with_input_gaps(self.analysis, provisional)
        appendix["body"] += input_gap_appendix(provisional) + evidence_basis_appendix(provisional)
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
        # The draft, its receipt and the draft returned are one read, and the caller's (AnalysisStore.save_draft).
        cache = {} if cache is None else cache
        draft = self.analysis.save_draft(save_spec, _recipe_report=recipe_report, _allowed=self.allowed,
                                         _inherited=inherited, _cache=cache)

        from foundry.finance_completion import record_completion

        # A session judges the runs it cites on the versions it reads them pinned to (AnalysisStore.run_in_view).
        completion = record_completion(self.analysis, draft, draft["explanation_check"], allowed=self.allowed,
                                       cache=cache)
        # The stored receipt: the public saves and a session's operation read it through _readable_receipt.
        return {**self._readable_draft(draft, cache=cache), "completion": completion}

    def _readable_draft(self, draft, *, cache=None):
        """A stored draft as this store's session reads it (AnalysisStore.draft_in_view; ``cache`` as for run_in_view)."""
        return self.analysis.draft_in_view(draft, self.allowed, cache=cache)

    def _readable_receipt(self, receipt, *, cache=None):
        """A completion receipt as this store's session reads it (AnalysisStore.completion_in_view; ``cache`` as for
        run_in_view)."""
        return self.analysis.completion_in_view(receipt, self.allowed, cache=cache)

    def _settled_receipt(self, receipt, *, cache=None, operations=None):
        """The receipt this store's session settles its own completion operation on: as it reads it. Its saves cite only
        what it may read, so it reads every receipt of its own; the receipt as stored if one ever does not, so the
        operation never stops unsettled. ``operations``, the store that settles it, is told the session reads it, so
        settle reads it no more under completion.lock (CompletionOperationStore._readable)."""
        view = self._readable_receipt(receipt, cache=cache)
        if view is not None and operations is not None and isinstance(receipt.get("id"), str):
            operations._readable_receipts[receipt["id"]] = True
        return receipt if view is None else view

    def prepare_explanation(self, spec):
        if not isinstance(spec, dict):
            raise FoundryError("prepare explanation spec must be an object")
        run_ids = spec.get("run_ids", [])
        if not isinstance(run_ids, list) or not run_ids:
            raise FoundryError("prepare explanation requires run_ids")
        runs = []
        for run_id in dict.fromkeys(run_ids):
            runs.append(self._named_run(run_id))
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
        # A session names only a draft it may read; one it may not read is refused as an unknown id.
        draft = self._named_draft(spec["draft_id"]) if spec.get("draft_id") else {}
        if self.allowed is not None:
            if spec.get("requirements_id"):
                self._named_requirements(spec["requirements_id"])
            # A revision is compared with its parent's runs: a parent named here must be one this session may read,
            # and a stored draft's parent it may not read is left out, as the draft reads to it (draft_in_view).
            self._parent_draft(spec.get("parent_id"))
        orphaned = (not spec.get("parent_id") and bool(draft.get("parent_id")) and self.allowed is not None
                    and not self.analysis._parent_readable(draft["parent_id"], self.allowed))
        run_ids = spec.get("run_ids", draft.get("run_ids", []))
        if not isinstance(run_ids, list):
            raise FoundryError("run_ids must be an array")
        for run_id in dict.fromkeys(run_ids):
            self._named_run(run_id)
        if self.allowed is None:
            for run_id in draft.get("run_ids", []):
                self._authorize(self.analysis.get_run(run_id)["bindings"])
        for claim in spec.get("claims", draft.get("claims", [])):
            if isinstance(claim, dict):
                if claim.get("run_id"):
                    self._named_run(claim["run_id"])
                if claim.get("dataset_id"):
                    self._authorize({"source": claim["dataset_id"]})
        self._authorize_evidence_recipes(spec.get("evidence_recipes", draft.get("evidence_recipes", [])))
        self._authorize_consistency_sources(spec.get("consistency_sources", draft.get("consistency_sources", {})))
        from foundry.finance_requirements import augment_quality, latest_requirements

        current = latest_requirements(self.analysis)
        self._authorize_current(current)
        # A caller's evidence_report, or the one stored on the draft, is never evidence: the recipes are
        # evaluated again by validate_explanation and only that fresh report reaches coverage.
        merged = {key: value for key, value in {**draft, **spec, "run_ids": run_ids}.items() if key != "evidence_report"}
        if orphaned:
            merged["parent_id"] = None
        quality = validate_explanation_payload(self.analysis, merged)
        checked = augment_quality(self.analysis, merged, quality, _recipe_report=quality["evidence_report"],
                                  _allowed=self.allowed)
        from foundry.analysis_data import json_value
        from foundry.evidence_labels import draft_evidence

        # The same labeler save_draft runs, over the same records, so the preview and the saved draft agree.
        # Labels or a posture in the spec or on the stored draft are never read.
        return {**checked, **draft_evidence(
            self.analysis, checked, claims=json_value(merged.get("claims", [])), fact_ids=merged.get("fact_ids", []),
            runs={run_id: self.analysis.get_run(run_id) for run_id in dict.fromkeys(run_ids)},
            evidence_report=quality["evidence_report"], consistency_report=quality["consistency_report"],
            source_read_failures=merged.get("source_read_failures", []), allowed=self.allowed,
        )}

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

        fields = normalize_background(spec, parent=parent, dataset=dataset, context=context or None)
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
        as_of = spec.get("as_of") or scope.get("period")
        if not scope:
            return {"schema_version": 1, "business_contexts": [], **({} if as_of else {"missing": ["as_of"]})}
        self._background_scope_bindings(scope)
        if not as_of:
            return {"schema_version": 1, "business_contexts": [], "missing": ["as_of"]}
        all_rows = self._list("backgrounds")
        rows = [row for row in all_rows if background_applies(row, scope=scope, as_of=as_of)]
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

    # ---- Tie-out controls (finance_controls) -------------------------------------------------

    def _control_heads(self, *, include_retired=False):
        """The latest version of each control; a version some later one names as parent is history."""
        rows = self._list("controls")
        replaced = {row.get("parent_id") for row in rows if row.get("parent_id")}
        heads = [row for row in rows if row["id"] not in replaced]
        return heads if include_retired else [row for row in heads if row.get("state") != "retired"]

    def _workbook_datasets(self, dataset_ids=None):
        """One snapshot per workbook: a table derived from a sheet shares its workbook's bytes, so it adds nothing."""
        from foundry.finance_controls import superseded_snapshots
        from foundry.finance_readiness import _is_workbook_shell

        rows = self.analysis.state()["datasets"]
        replaced = superseded_snapshots(self.task, rows, allowed=self.allowed)
        by_bytes = {}
        for dataset in rows:
            if dataset["id"] in replaced:
                continue
            if dataset_ids is not None and dataset["id"] not in dataset_ids:
                continue
            if self.allowed is not None and dataset["id"] not in self.allowed:
                continue
            if dataset.get("source_file") != "source.xlsx":
                continue
            held = by_bytes.get(dataset["source_hash"])
            if held is None or (_is_workbook_shell(dataset) and not _is_workbook_shell(held)):
                by_bytes[dataset["source_hash"]] = dataset
        return list(by_bytes.values())

    def finance_controls_propose(self, spec):
        """Suggested subtotal controls with a preview result each. Nothing is saved."""
        from foundry.finance_controls import clean_control, control_key, evaluate_control, snapshot_bytes, suggest_controls

        spec = spec if isinstance(spec, dict) else {}
        wanted = spec.get("dataset_ids")
        if wanted is not None and (not isinstance(wanted, list) or not all(isinstance(item, str) for item in wanted)):
            raise FoundryError("dataset_ids must be an array of snapshot ids")
        saved = {control_key(row["control"]): row["id"] for row in self._control_heads()}
        cache: dict = {}
        suggestions = []
        for dataset in self._workbook_datasets(set(wanted) if wanted is not None else None):
            data = snapshot_bytes(self.analysis, dataset)
            for raw in suggest_controls(self.analysis, dataset, data):
                control = clean_control(raw)
                suggestions.append({
                    "control": control,
                    "preview": evaluate_control(self.analysis, control, cache=cache, allowed=self.allowed),
                    **({"saved_id": saved[control_key(control)]} if control_key(control) in saved else {}),
                })
        return {"schema_version": 1, "suggestions": suggestions}

    def finance_controls_sources(self, spec):
        """The workbooks a control can read, with their sheet names, for choosing two places to compare."""
        from foundry.finance_controls import snapshot_bytes, workbook_sheets

        del spec
        sources = []
        for dataset in self._workbook_datasets():
            sources.append({
                "dataset_id": dataset["id"],
                "source_hash": dataset["source_hash"],
                "name": dataset.get("name") or dataset["id"],
                "sheets": workbook_sheets(snapshot_bytes(self.analysis, dataset)),
            })
        return {"schema_version": 1, "sources": sources}

    def finance_controls_preview(self, spec):
        """Sum both sides of one control the manager is drafting and say the difference. Nothing is saved."""
        from foundry.finance_controls import clean_control, dataset_ids, evaluate_control

        if not isinstance(spec, dict):
            raise FoundryError("control preview spec must be an object")
        control = clean_control(spec.get("control", spec))
        ids = dataset_ids(control)
        self._authorize({f"source{index}": dataset_id for index, dataset_id in enumerate(ids)})
        self._assert_current_snapshots(ids)
        return {"schema_version": 1, "control": control,
                "preview": evaluate_control(self.analysis, control, allowed=self.allowed)}

    def _assert_current_snapshots(self, ids):
        """A control is declared on the task's current files: one on a replaced snapshot would be stale from birth."""
        from foundry.finance_controls import superseded_snapshots

        rows = self.analysis.state()["datasets"]
        published = {row["id"] for row in rows}
        if any(dataset_id not in published for dataset_id in ids):
            raise FoundryError("control refers to a snapshot that is not in this task")
        if set(ids) & superseded_snapshots(self.task, rows, allowed=self.allowed):
            raise FoundryError("control refers to a snapshot a newer upload has replaced")

    def finance_controls_save(self, spec):
        """Save controls as proposed; the manager may confirm in the same call. A repeat of a live control returns it."""
        from foundry.finance_controls import clean_control, control_key, dataset_ids

        if not isinstance(spec, dict):
            raise FoundryError("control save spec must be an object")
        items = spec.get("controls") if "controls" in spec else [spec.get("control", spec)]
        if not isinstance(items, list) or not items or len(items) > 400:
            raise FoundryError("controls must be a non-empty array of at most 400")
        origin = spec.get("origin") or "declared"
        if origin not in {"suggested", "declared"}:
            raise FoundryError("control origin must be suggested or declared")
        confirm = spec.get("confirm") is True
        if confirm:
            self._manager_only("confirm a control")
        # Every lineage, retired ones too: a check the manager retired is revived in its own
        # lineage, never started again beside it.
        lineages = {control_key(row["control"]): row for row in self._control_heads(include_retired=True)}
        published = {row["id"] for row in self.analysis.state()["datasets"]}
        saved = []
        for item in items:
            control = clean_control(item)
            ids = dataset_ids(control)
            self._authorize({f"source{index}": dataset_id for index, dataset_id in enumerate(ids)})
            for dataset_id in ids:
                if dataset_id not in published:
                    raise FoundryError("control refers to a snapshot that is not in this task")
            if confirm:
                self._assert_current_snapshots(ids)
            existing = lineages.get(control_key(control))
            state = "confirmed" if confirm else "proposed"
            if existing and existing.get("state") != "retired" and existing["control"] == control and (
                not confirm or existing.get("state") == "confirmed"
            ):
                saved.append(existing)
                continue
            if existing and existing.get("state") == "confirmed" and not confirm:
                # Re-saving a confirmed check would take it out of the close until someone noticed.
                if self.actor != MANAGER:
                    raise FoundryError("a confirmed control can only be changed by the manager")
                state = "confirmed"
            record = self._write(
                "controls",
                control=control,
                origin=origin if not existing else existing.get("origin", origin),
                state=state,
                bindings={f"source{index}": dataset_id for index, dataset_id in enumerate(ids)},
                saved_by=self.actor,
                **({"parent_id": existing["id"]} if existing else {}),
            )
            lineages[control_key(control)] = record
            saved.append(record)
        return {"schema_version": 1, "controls": saved}

    def _control_successor(self, spec, state, action):
        self._manager_only(action)
        if not isinstance(spec, dict) or not spec.get("id"):
            raise FoundryError("control id is required")
        head = next((row for row in self._control_heads(include_retired=True) if row["id"] == spec["id"]), None)
        if head is None:
            raise FoundryError("control is not the latest version or does not exist")
        if head.get("state") == state:
            return head
        reason = _safe_text(spec.get("reason") or "", "control reason", maximum=2000)
        if state == "retired" and not reason:
            raise FoundryError("retiring a control requires a reason")
        return self._write(
            "controls",
            control=head["control"],
            origin=head.get("origin", "declared"),
            state=state,
            bindings=head["bindings"],
            saved_by=self.actor,
            parent_id=head["id"],
            **({"reason": reason} if reason else {}),
        )

    def finance_controls_confirm(self, spec):
        return self._control_successor(spec, "confirmed", "confirm a control")

    def finance_controls_retire(self, spec):
        return self._control_successor(spec, "retired", "retire a control")

    def finance_controls_run(self, spec):
        """Evaluate the live controls (or the named ones) and keep the run as a record."""
        from foundry.finance_controls import evaluate_control

        spec = spec if isinstance(spec, dict) else {}
        heads = self._control_heads()
        wanted = spec.get("ids")
        if wanted is not None:
            if not isinstance(wanted, list):
                raise FoundryError("ids must be an array of control ids")
            known = {row["id"] for row in heads}
            missing = [item for item in wanted if item not in known]
            if missing:
                raise FoundryError("control is not the latest version or does not exist")
            heads = [row for row in heads if row["id"] in set(wanted)]
        cache: dict = {}
        results = [
            {
                "control_id": row["id"],
                "label": row["control"]["label"],
                "state": row.get("state"),
                **evaluate_control(self.analysis, row["control"], cache=cache, allowed=self.allowed),
            }
            for row in heads
        ]
        read = dict.fromkeys(dataset_id for row in heads for dataset_id in row["bindings"].values())
        bindings = {f"source{index}": dataset_id for index, dataset_id in enumerate(read)}
        return self._write("control_runs", results=results, summary=_control_summary(results), bindings=bindings, run_by=self.actor)

    def finance_controls_list(self, spec):
        """Live controls, each with its latest result; a result read from a snapshot that changed since is stale."""
        import json

        from foundry.analysis_data import json_value
        from foundry.finance_controls import STALE, evaluate_control, superseded_snapshots

        spec = spec if isinstance(spec, dict) else {}
        heads = self._control_heads(include_retired=spec.get("include_retired") is True)
        visible = {head["id"] for head in heads}
        latest = {}
        # A run keeps one result per control, read from that control's own files: a session reads the result of
        # every control it may read, whatever else the run read (_list would drop the run as a whole).
        root = self.analysis._inside(self.analysis.root / self._folder("control_runs"))
        for run in sorted((self.analysis._read(path) for path in root.glob("*.json")), key=lambda r: r["seq"]):
            for result in run.get("results") or []:
                if result.get("control_id") in visible:
                    latest[result["control_id"]] = {**result, "run_id": run["id"], "run_at": run["created_at"]}

        current = {row["id"]: row.get("source_hash") for row in self.analysis.state()["datasets"]}
        replaced = superseded_snapshots(self.task, allowed=self.allowed)
        cache: dict = {}
        rows = []
        for head in heads:
            result = latest.get(head["id"])
            hashes = (result or {}).get("source_hashes") or {}
            if (self.allowed is not None and result and result.get("status") == STALE
                    and result.get("reason") == "资料已有更新的版本" and not set(hashes) & replaced):
                # Judged stale by a newer file this session may not read: judge it by the files it may read, and read
                # the result as a stored one reads (keys sorted as written, then the run it came with).
                fresh = {**{key: result[key] for key in ("control_id", "label", "state") if key in result},
                         **evaluate_control(self.analysis, head["control"], cache=cache, allowed=self.allowed)}
                result = {**json.loads(json.dumps(json_value(fresh), sort_keys=True)),
                          **{key: result[key] for key in ("run_id", "run_at") if key in result}}
                hashes = result.get("source_hashes") or {}
            if result and any(current.get(dataset_id) != digest or dataset_id in replaced for dataset_id, digest in hashes.items()):
                result = {**result, "status": "stale", "reason": "资料快照在这次运行之后已变化"}
            rows.append({**head, "result": result})
        from foundry.finance_controls import control_finding, control_issue, lineage

        settings = self._control_settings()
        decided = self._latest_dispositions()
        findings = self._findings_by_lineage()
        for row in rows:
            row["issue"] = control_issue(row, decided.get(row["id"]), require_second_review=settings["require_second_review"])
            row["finding"] = control_finding(row, findings.get(lineage(row["control"]), []))
        results = [row["result"] | {"state": row.get("state")} for row in rows if row.get("result")]
        summary = _control_summary(results, total=len(rows))
        summary["blocking"] = sum(1 for row in rows if (row.get("issue") or {}).get("blocking"))
        return {"schema_version": 1, "controls": rows, "summary": summary, "settings": settings}

    def _control_settings(self):
        rows = self._list("control_settings")
        latest = rows[-1] if rows else {}
        return {"require_second_review": latest.get("require_second_review") is True}

    def _latest_dispositions(self):
        latest = {}
        for row in self._list("control_dispositions"):
            latest[row["control_id"]] = row
        return latest

    def _findings_by_lineage(self):
        """Every finding kept for each check, oldest first, whichever version of it was current then."""
        kept = {}
        for row in self._list("control_findings"):
            kept.setdefault(row["control_key"], []).append(row)
        return kept

    def finance_control_finding_save(self, spec):
        """问题类型 for one difference. The assistant's record is a suggestion; the manager's is the decision.

        Bound to the exact difference, like a disposition, but kept by the check's lineage rather
        than its version id, so confirming or editing the control does not lose it.
        """
        from foundry.finance_controls import applies_to, clean_finding, lineage

        if not isinstance(spec, dict) or not isinstance(spec.get("control_id"), str) or not spec["control_id"]:
            raise FoundryError("finding requires control_id")
        fields = clean_finding(spec)
        listed = {row["id"]: row for row in self.finance_controls_list({})["controls"]}
        row = listed.get(spec["control_id"])
        if row is None:
            raise FoundryError("control is not the latest version or does not exist")
        result = row.get("result") or {}
        if result.get("status") not in {"break", "error"}:
            raise FoundryError("only a current difference can be given a finding type; this control passes, reads a replaced snapshot, or has not run")
        key = lineage(row["control"])
        kept = self._findings_by_lineage().get(key, [])
        last = kept[-1] if kept else None
        # Saying the same thing again, with nothing said in between, is not a new record.
        if last and last.get("set_by") == self.actor and applies_to(last, result) and (
            last["finding_type"], last.get("note", "")) == (fields["finding_type"], fields["note"]):
            return last
        return self._write(
            "control_findings",
            control_key=key,
            control_id=row["id"],
            run_id=result.get("run_id"),
            status=result.get("status"),
            difference=result.get("difference"),
            source_hashes=result.get("source_hashes"),
            bindings=row["bindings"],
            set_by=self.actor,
            **fields,
            **({"parent_id": last["id"]} if last else {}),
        )

    def finance_control_settings_save(self, spec):
        self._manager_only("change control settings")
        if not isinstance(spec, dict) or not isinstance(spec.get("require_second_review"), bool):
            raise FoundryError("require_second_review must be true or false")
        return self._write("control_settings", require_second_review=spec["require_second_review"], bindings={}, saved_by=self.actor)

    def finance_control_disposition_save(self, spec):
        """The manager's decision on one difference, bound to the exact result it was made about."""
        from foundry.finance_controls import clean_disposition

        self._manager_only("decide on a control difference")
        if not isinstance(spec, dict) or not spec.get("control_id"):
            raise FoundryError("disposition requires control_id")
        listed = {row["id"]: row for row in self.finance_controls_list({})["controls"]}
        row = listed.get(spec["control_id"])
        if row is None:
            raise FoundryError("control is not the latest version or does not exist")
        if row.get("state") != "confirmed":
            raise FoundryError("only a confirmed control's difference can be decided")
        result = row.get("result") or {}
        if result.get("status") not in {"break", "error"}:
            raise FoundryError("this control has no difference to decide; run it first")
        fields = clean_disposition(spec)
        if result.get("status") == "error" and fields["decision"] != "corrected":
            # A range that cannot be read is not a difference anyone can accept; the file has to be fixed.
            raise FoundryError("a control that could not be read can only be corrected and re-imported")
        review_required = self._control_settings()["require_second_review"]
        if fields["decision"] == "waived" and review_required and not fields["decided_by_name"]:
            raise FoundryError("with second review on, accepting a difference must name who accepts it")
        previous = self._latest_dispositions().get(row["id"])
        return self._write(
            "control_dispositions",
            control_id=row["id"],
            run_id=result.get("run_id"),
            status=result.get("status"),
            difference=result.get("difference"),
            source_hashes=result.get("source_hashes"),
            bindings=row["bindings"],
            decided_by=self.actor,
            review_required=fields["decision"] == "waived" and review_required,
            **fields,
            **({"parent_id": previous["id"]} if previous else {}),
        )

    def finance_control_disposition_review(self, spec):
        """A second person's sign-off on an accepted difference, where the task requires one."""
        self._manager_only("review a control decision")
        if not isinstance(spec, dict) or not spec.get("id"):
            raise FoundryError("review requires the disposition id")
        reviewer = _safe_text(spec.get("reviewer") or "", "reviewer", maximum=80).strip()
        if not reviewer:
            raise FoundryError("a review must name the reviewer")
        current = self._latest_dispositions()
        disposition = next((row for row in current.values() if row["id"] == spec["id"]), None)
        if disposition is None:
            raise FoundryError("disposition is not the latest decision for its control")
        if disposition["decision"] != "waived":
            raise FoundryError("only an accepted difference is reviewed")
        if disposition.get("reviewed_at"):
            return disposition
        from foundry.finance_controls import same_person

        if not (disposition.get("decided_by_name") or "").strip():
            raise FoundryError("this acceptance names no one; decide it again with a name before it can be reviewed")
        if same_person(disposition["decided_by_name"], reviewer):
            raise FoundryError("the reviewer must be someone other than the person who accepted the difference")
        from foundry.analysis import now_iso

        fields = {key: value for key, value in disposition.items() if key not in {"id", "task_id", "schema_version", "created_at", "seq", "domain", "parent_id"} and not key.startswith("_")}
        return self._write("control_dispositions", **{**fields, "parent_id": disposition["id"], "reviewer": reviewer, "reviewed_at": now_iso()})

    def finance_close_status(self, spec=None):
        """The month-close control center's six blocks and its one headline (finance_close_status)."""
        from foundry.finance_close_status import close_status
        from foundry.finance_controls import superseded_snapshots
        from foundry.structure_records import PENDING_ACKNOWLEDGEMENT, PENDING_CONFIRMATION

        # The versions and runs the listing reads, read once for the draft it shows too (AnalysisStore.run_in_view).
        cache: dict = {}
        state = self.analysis.state(self.allowed, cache=cache)
        rows = [row for row in state["datasets"] if self.allowed is None or row["id"] in self.allowed]
        # A session's close status is the one its own files give: a newer file outside it replaces nothing here.
        replaced = superseded_snapshots(self.task, state["datasets"], allowed=self.allowed)
        current = [row for row in rows if row["id"] not in replaced]
        # The newest requirements version this reader may read, as analysis_requirements_list names its current one.
        requirements = state["requirements"][-1] if state["requirements"] else None
        other_months = _other_month_workbooks(rows, current, ((requirements or {}).get("scope") or {}).get("period"))
        from foundry.finance_readiness import _is_workbook_shell
        from foundry.structure_records import NO_TABLE, WITHDRAWN

        pending = []
        for row in current:
            if (row.get("source_hash") or row["id"]) in other_months:
                continue  # its table structure is that month's to confirm
            structure = self.dataset_structure_state(row["id"])
            # The readiness report's rules: a workbook nothing was derived from, or a withdrawn table, is not confirmed.
            if structure in {PENDING_CONFIRMATION, PENDING_ACKNOWLEDGEMENT, WITHDRAWN} or (structure == NO_TABLE and _is_workbook_shell(row)):
                pending.append(row.get("name") or "资料")
        drafts = sorted((row for row in state.get("drafts") or [] if row.get("publication_status") != "archived"),
                        key=lambda row: row.get("seq", 0), reverse=True)
        # The newest draft this reader may read (the manager: the newest), as this reader reads it.
        read: dict = {}
        draft = next((row for row in drafts if self.analysis.draft_readable(row, self.allowed, cache=read)), None)
        runs = [row for row in state.get("runs") or [] if self.allowed is None or set((row.get("bindings") or {}).values()) <= self.allowed]
        readiness = self.finance_readiness({})
        organizations = [row for row in readiness.get("datasets") or [] if (row.get("scope") or {}).get("organization")]
        return close_status(
            archived=self.task.lifecycle_status() in {"archived", "trashed"},
            replaced=replaced,
            other_months=other_months,
            organization_required=bool(organizations),
            scope=(requirements or {}).get("scope"),
            scope_seq=(requirements or {}).get("seq"),
            datasets=current,
            superseded=len(rows) - len(current),
            pending_structures=pending,
            controls=self.finance_controls_list({})["controls"],
            runs=runs,
            draft=draft if draft is None or self.allowed is None else self._readable_draft(draft, cache=cache),
        )

    def finance_control_confirmation_sheet(self, spec):
        """The open and out-for-confirmation differences as a sheet to send."""
        from foundry.finance_controls import confirmation_sheet

        spec = spec if isinstance(spec, dict) else {}
        wanted = spec.get("control_ids")
        rows = [
            row for row in self.finance_controls_list({})["controls"]
            # What the preparer has to answer: open and out-for-confirmation differences, and ranges
            # that cannot be read. An acceptance waiting on internal review stays inside.
            if (row.get("issue") or {}).get("state") in {"open", "pending_external", "awaiting_reimport"}
            and (row.get("result") or {}).get("status") in {"break", "error"}
            and (wanted is None or row["id"] in wanted)
        ]
        names = {row["id"]: row.get("name") or "资料" for row in self.analysis.state()["datasets"]}
        return {"schema_version": 1, "count": len(rows), **confirmation_sheet(rows, names)}

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
            try:
                self._confirm_declaration(
                    record,
                    [sheet for sheet in sheets if sheet["sheet"] in {m["sheet"] for m in auto}],
                    source=TEMPLATE,
                    triggered_by=source or self.actor,
                )
            except FoundryError:
                # A remembered shape that this file cannot fill (a sheet of the same shape holding #REF!,
                # say) leaves the proposal to the manager, who sees the reason on confirming; the import
                # itself stands.
                pass
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
        known = {sheet["sheet"]: sheet for sheet in latest["sheets"]}
        unknown = [item.get("sheet") for item in sheets if item.get("sheet") not in known]
        if unknown:
            raise FoundryError(f"sheet is not in the proposal: {unknown[0]}")
        sheets = [self._adopted_sheet(item, known[item["sheet"]]) for item in sheets]
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

    @staticmethod
    def _adopted_sheet(item, proposed):
        """A sheet the proposal set aside may come back as a table only if it was a presentation page with a table on it."""
        if item.get("decision") != "table" or proposed.get("decision") == "table":
            return item
        if proposed.get("reason") == "presentation_sheet" and proposed.get("adoptable"):
            return {**item, "reason": "adopted_presentation_sheet", "blocked_reason": None}
        raise FoundryError(f"sheet {item['sheet']} was set aside ({proposed.get('reason')}) and cannot be confirmed as a table")

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
        # Read every sheet before filing any, for the same reason: a sheet holding #REF! refuses here.
        derived = [self.analysis.derive_table_snapshot(dataset_id, sheet) for sheet in wanted]
        snapshots = {}
        for sheet, reading in zip(wanted, derived):
            snapshot = self.analysis.add_table_snapshot(
                dataset_id, sheet, name=sheet["sheet"], derived=reading
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
        # The save and the draft it returns are one read (AnalysisStore.save_draft).
        cache: dict = {}
        draft = self.analysis.save_draft({"title": record.get("label") or template_id, "document": document},
                                         _allowed=self.allowed, _cache=cache)
        return {
            "draft": self._readable_draft(draft, cache=cache),
            "template_id": template_id,
            "kind": record.get("kind"),
            "filled_named_ranges": filled,
            "unfilled_named_ranges": unfilled,
        }

    def report_review(self, spec):
        """Check the numbers of an imported report against the task's current workbooks and calculations.

        `{draft_id}` reviews a saved draft's document; `{document}` an import not yet adopted. The
        result is filed as its own immutable record: the draft, its review status and the report's
        text stay as they were, and a matching number only says where the same value was found.
        """
        from pathlib import Path

        from foundry.report_documents import validate_report_document
        from foundry.report_review import gather_candidates, review_report

        if not isinstance(spec, dict):
            raise FoundryError("report review spec must be an object")
        draft_id, document = spec.get("draft_id"), spec.get("document")
        if (draft_id in (None, "")) == (document is None):
            raise FoundryError("report review requires either a draft_id or a document")
        if draft_id not in (None, ""):
            draft = self._named_draft(draft_id)
            self._authorize_draft(draft)
            if draft.get("document") is None:
                raise FoundryError("report review requires a draft saved with a structured document")
            document = draft["document"]
            origin = {"origin": "draft", "draft_id": draft["id"], "draft_content_hash": draft.get("content_hash")}
        else:
            # The PDF converter numbers pages; the document contract keeps every location as text.
            document = _text_pages(document)
            origin = {"origin": "import"}
        registry = self.analysis._registered_report_sources()
        clean = validate_report_document(document, registered_source_ids=set(registry))
        # A source's name, format and hash come from the registry, never from the caller (as save_draft does).
        if clean.get("sources"):
            clean["sources"] = [registry[source["id"]] for source in clean["sources"]]
        candidates, notes = gather_candidates(self)
        result = review_report(clean, candidates, notes)
        cited = sorted({candidate["dataset_id"] for item in result["items"] for candidate in item["candidates"]
                        if candidate.get("dataset_id")})
        return self._write(
            "report_reviews",
            **origin,
            document_hash=_hash(clean),
            sources=[{"id": source["id"], "name": Path(source["name"]).name, "format": source["format"],
                      "sha256": source["sha256"]} for source in clean.get("sources", [])],
            bindings={f"source{index}": dataset_id for index, dataset_id in enumerate(cited)},
            review_schema_version=result["schema_version"],
            summary=result["summary"],
            items=result["items"],
            issues=result["issues"],
            notes=result["notes"],
            closing_note=result["closing_note"],
        )

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
        from foundry.report_visuals import series_for_report

        if not isinstance(spec, dict) or not spec.get("id"):
            raise FoundryError("chart open requires id")
        record = self._read("charts", spec["id"])
        if not record.get("bindings"):
            raise FoundryError("chart bindings are required")
        verify_snapshots(self, record)
        return {**record, "report_series": series_for_report(record["series"])}

    def chart_deliverable_list(self, spec):
        spec = spec or {}
        if spec and not isinstance(spec, dict):
            raise FoundryError("chart list spec must be an object")
        rows = self._list("charts")
        if isinstance(spec, dict) and spec.get("run_id"):
            rows = [row for row in rows if row.get("run_id") == spec["run_id"]]
        return {"charts": rows}

    def _dashboard(self):
        """The task's board as last saved, or None before the first card."""
        versions = self._list("dashboards")
        return versions[-1] if versions else None

    def _dashboard_runs(self):
        """A run reader for one call: each run read (and its outputs checked) once, however many cards show it."""
        cache = {}

        def run_of(run_id):
            if run_id not in cache:
                cache[run_id] = self._named_run(run_id)
            return cache[run_id]

        return run_of

    def dashboard_read(self, spec):
        if spec and not isinstance(spec, dict):
            raise FoundryError("dashboard read spec must be an object")
        current = self._dashboard()
        if current is None:
            return {"dashboard": None}
        if self.allowed is not None:
            return {"dashboard": self._dashboard_in_view(current)}
        # The manager's read says how many cards have newer files to be recomputed on (dashboard_recompute).
        plans = self._dashboard_plans(current.get("cards", []), self._dashboard_runs())
        return {"dashboard": current, "recompute": {"ready": sum(len(ids) for _, ids in plans.values())}}

    def _dashboard_in_view(self, board):
        """The board as a session sees it: the cards on runs it may read; the board itself names no files."""
        run_of = self._dashboard_runs()
        readable = []
        for card in board.get("cards", []):
            try:
                run_of(card["run_id"])
            except FoundryError:
                continue
            readable.append(card)
        return {**board, "cards": readable}

    def _dashboard_lock(self):
        """Held from reading the board's head to writing the next version, so two saves never both build on one head.
        Its own file: _write takes task.lock inside it."""
        from foundry.locking import exclusive

        return exclusive(self.analysis._inside(self.analysis.root / "dashboards.lock"), timeout=10)

    def _dashboard_plans(self, cards, run_of):
        """The cards whose files have newer versions, by the run they read: {run id: (new bindings, card ids)}. A card
        whose last recompute on those same files failed is left until its files change again."""
        from foundry.dashboard_recompute import newest_versions

        newest = newest_versions(self)
        plans = {}
        for card in cards:
            try:
                run = run_of(card["run_id"])
            except FoundryError:
                continue
            bindings = {alias: newest(value) or value for alias, value in (run.get("bindings") or {}).items()}
            if bindings == run.get("bindings") or (card.get("recompute_failed") or {}).get("bindings") == dict(sorted(bindings.items())):
                continue
            plans.setdefault(run["id"], (bindings, set()))[1].add(card["id"])
        return plans

    def dashboard_recompute(self, spec):
        """Every card whose files have newer versions, on the same calculation run again on them (dashboard_recompute)."""
        from foundry import dashboard_recompute as rc

        if spec and not isinstance(spec, dict):
            raise FoundryError("dashboard recompute spec must be an object")
        self._manager_only("recompute the dashboard")
        current = self._dashboard()
        if current is None:
            return {"dashboard": None, "recomputed": [], "failed": []}
        if "parent_id" in (spec or {}) and (spec.get("parent_id") or None) != current["id"]:
            raise FoundryError("the dashboard changed since it was read; read it again")
        run_of = self._dashboard_runs()
        plans = self._dashboard_plans(current["cards"], run_of)
        if not plans:
            return {"dashboard": current, "recomputed": [], "failed": []}
        outcomes = {}
        for run_id, (bindings, _cards) in plans.items():
            run = run_of(run_id)
            try:
                recipe = rc.recipe_of(self, run, elsewhere=False)
                new = rc.new_month(self, [value for alias, value in bindings.items() if value != run["bindings"][alias]])
                # Only some files are next month's yet: run once the rest are too, not on two months at once.
                behind = rc.other_months(self, [value for alias, value in bindings.items() if value == run["bindings"][alias]], new) if new else []
                if behind:
                    raise rc.NotRerun(f"还有资料不是 {new} 的：{'、'.join(behind)}，换成同一个月的再重算")
                move = rc.month_move(recipe, new)
                again, said = rc.run_again(self, recipe, bindings, move, elsewhere=False)
                if again.get("execution_status") not in {"succeeded", "success"}:
                    raise rc.NotRerun(f"重算没有算完：{again.get('error') or '计算失败'}")
                outcomes[run_id] = (again, said, rc.manual_inputs((recipe.get("scenario") or {}).get("inputs")), move)
            except rc.NotRerun as exc:
                outcomes[run_id] = str(exc)
            except FoundryError as exc:
                outcomes[run_id] = f"重算没有算完：{exc}"
        cards, recomputed, failed = [], [], []
        for card in current["cards"]:
            plan = plans.get(card["run_id"])
            if not plan or card["id"] not in plan[1]:
                cards.append(card)
                continue
            outcome = outcomes[card["run_id"]]
            try:
                if isinstance(outcome, str):
                    raise rc.NotRerun(outcome)
                again, said, manual, move = outcome
                cards.append(rc.moved_card(card, run_of(card["run_id"]), again, move, before=None, said=said,
                                           manual=manual, carried=None))
                recomputed.append(card["id"])
            except rc.NotRerun as exc:
                cards.append(rc.failed(card, str(exc), plan[0]))
                failed.append({"card_id": card["id"], "title": card["title"], "reason": str(exc)})
        with self._dashboard_lock():
            if (self._dashboard() or {}).get("id") != current["id"]:
                raise FoundryError("the dashboard changed since it was read; read it again")
            board = self._write("dashboards", parent_id=current["id"], bindings={}, cards=cards)
        return {"dashboard": board, "recomputed": recomputed, "failed": failed}

    def dashboard_carry(self, spec, *, tasks):
        """Last month's board on this task: each card's calculation run on this task's files of the same names.

        Without ``from_task_id``, the boards that could come here: each other task's board, how many of its cards
        have every file they read here under the same name, and the names still missing. With it, those cards are
        carried onto this task's empty board, waiting for the manager; the rest are said and left behind.
        """
        from foundry import dashboard_recompute as rc
        from foundry.finance_readiness import _task_period

        if spec and not isinstance(spec, dict):
            raise FoundryError("dashboard carry spec must be an object")
        spec = spec or {}
        self._manager_only("carry a dashboard over")
        if self.allowed is not None:
            raise FoundryError("only the manager carries a dashboard over")
        current = self._dashboard()
        if current and current.get("cards"):
            raise FoundryError("this task's dashboard already has cards; carry a board onto an empty one")
        find = rc.same_names(self)

        def runs_of(source, board):
            run_of = source._dashboard_runs()
            plans = {}
            for card in board["cards"]:
                try:
                    run = run_of(card["run_id"])
                except FoundryError:
                    continue
                if run["id"] not in plans:
                    plans[run["id"]] = (run, *rc.rebind(run["bindings"], source.analysis.read_dataset, self.analysis.read_dataset, find))
            return plans

        if not spec.get("from_task_id"):
            offers = []
            for task in tasks.list("all"):
                if task.id == self.task.id or task.lifecycle_status() == "trashed":
                    continue
                source = FinanceStore(task, actor="manager")
                board = source._dashboard()
                cards = [card for card in (board or {}).get("cards", []) if card.get("state") != "explore"]
                if not cards:
                    continue
                plans = runs_of(source, {"cards": cards})
                ready = [card for card in cards if card["run_id"] in plans and not plans[card["run_id"]][2]]
                missing = sorted({name for run, _bindings, names in plans.values() for name in names})
                meta = task.meta()
                offers.append({"task_id": task.id, "title": meta.get("title"), "period": meta.get("period"),
                               "created_at": meta.get("created_at"), "cards": len(cards), "ready": len(ready), "missing": missing})
            offers.sort(key=lambda row: (str(row.get("period") or ""), str(row.get("created_at") or "")), reverse=True)
            return {"offers": offers[:5]}
        source_task = tasks.get(str(spec["from_task_id"]))
        if source_task.id == self.task.id or source_task.lifecycle_status() == "trashed":
            raise FoundryError("carry a dashboard from another task")
        source = FinanceStore(source_task, actor="manager")
        board = source._dashboard()
        cards = [card for card in (board or {}).get("cards", []) if card.get("state") != "explore"]
        if not cards:
            raise FoundryError("that task has no dashboard to carry over")
        plans = runs_of(source, {"cards": cards})
        fallback = self.task.meta().get("period") or _task_period(self.analysis)
        carried_from = {"task_id": source_task.id, "title": source_task.meta().get("title")}
        outcomes = {}
        for run_id, (run, bindings, missing) in plans.items():
            try:
                if missing:
                    raise rc.NotRerun("这个任务里还没有：" + "、".join(missing))
                recipe = rc.recipe_of(source, run, elsewhere=True)
                new = rc.new_month(self, list(bindings.values()), fallback)
                if rc.recipe_month(recipe) and not new:
                    raise rc.NotRerun("看不出这个任务的资料是哪个月的，先在「分析范围」填上期间")
                move = rc.month_move(recipe, new)
                again, said = rc.run_again(self, recipe, bindings, move, elsewhere=True)
                if again.get("execution_status") not in {"succeeded", "success"}:
                    raise rc.NotRerun(f"重算没有算完：{again.get('error') or '计算失败'}")
                outcomes[run_id] = (again, said, rc.manual_inputs((recipe.get("scenario") or {}).get("inputs")), move)
            except rc.NotRerun as exc:
                outcomes[run_id] = str(exc)
            except FoundryError as exc:
                outcomes[run_id] = f"重算没有算完：{exc}"
        stored, failed = [], []
        for card in cards:
            outcome = outcomes.get(card["run_id"], "原来的结果读不到了")
            try:
                if isinstance(outcome, str):
                    raise rc.NotRerun(outcome)
                again, said, manual, move = outcome
                before = rc.shown(card, plans[card["run_id"]][0])
                stored.append(rc.moved_card(card, None, again, move, before=before, said=said, manual=manual,
                                            carried=carried_from))
            except rc.NotRerun as exc:
                failed.append({"card_id": card["id"], "title": card["title"], "reason": str(exc)})
        if not stored:
            return {"dashboard": current, "carried": [], "failed": failed}
        with self._dashboard_lock():
            if (self._dashboard() or {}).get("id") != (current or {}).get("id"):
                raise FoundryError("the dashboard changed since it was read; read it again")
            written = self._write("dashboards", parent_id=current["id"] if current else None, bindings={}, cards=stored)
        return {"dashboard": written, "carried": [card["id"] for card in stored], "failed": failed}

    def dashboard_save(self, spec):
        from foundry.dashboards import arrange

        if not isinstance(spec, dict) or not isinstance(spec.get("cards"), list):
            raise FoundryError("dashboard save requires cards")
        self._manager_only("arrange the dashboard")
        with self._dashboard_lock():
            current = self._dashboard()
            if (spec.get("parent_id") or None) != (current["id"] if current else None):
                raise FoundryError("the dashboard changed since it was read; read it again")
            cards = arrange(spec["cards"], current.get("cards", []) if current else [], run_of=self._dashboard_runs())
            return self._write("dashboards", parent_id=current["id"] if current else None, bindings={}, cards=cards)

    def dashboard_propose(self, spec):
        from foundry.answer_cards import proposed_card
        from foundry.dashboards import propose

        if not isinstance(spec, dict) or not isinstance(spec.get("card"), dict):
            raise FoundryError("dashboard propose requires a card")
        with self._dashboard_lock():
            current = self._dashboard()
            cards = propose(spec["card"], current.get("cards", []) if current else [], run_of=self._dashboard_runs())
            written = self._write("dashboards", parent_id=current["id"] if current else None, bindings={}, cards=cards)
        # A session is answered with what it may read, as dashboard_read answers it; the stored board keeps every card.
        board = self._dashboard_in_view(written) if self.allowed is not None else written
        # The proposed card as the conversation draws it under the call (dsh-plugin/client.js).
        return {**board, "presented": {"task_id": self.task.id, "proposed": proposed_card(self, cards[-1])}}

    def answer_cards(self, spec):
        from foundry.answer_cards import answer_cards

        return answer_cards(self, spec)

    def month_brief(self, spec=None):
        """本月三句话: the rule's three lines from the task's results, and the assistant's wording of them while it holds."""
        from foundry.month_brief import brief

        return brief(self)

    def month_brief_word(self, spec):
        from foundry.month_brief import word

        return word(self, spec)

    def analysis_circle_select(self, spec):
        from foundry.circle_select import authorize_workbook, match_draft_table, reject_forbidden_spec
        from foundry.finance_requirements import (
            SCOPE_REFUSED_HIERARCHY_KEYS, _without_hierarchy, latest_requirements, prepare_requirements,
        )

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
        if self.allowed is not None:
            # A session revises only a current version it may read, refused as analysis_requirements_save refuses it:
            # before anything is taken from that version or a child context is written.
            self._authorize_current(latest)
        if spec.get("parent_id") and (not latest or spec["parent_id"] != latest["id"]):
            raise FoundryError("circle-select parent_id must be the latest requirements version")
        if kind == "draft_table":
            if not spec.get("draft_id"):
                raise FoundryError("draft table circle-select requires draft_id")
            # A session circles a table only in a draft it may read; one it may not read is refused as an unknown
            # id, before its tables say anything.
            match_draft_table(self._named_draft(spec["draft_id"]), spec)
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
        if not latest:
            # 改口径 revises a stated scope. With none on file the instruction
            # would be filed as the analytical question, and every later reader
            # would take 「按区域拆开」 for what was asked. Refused before the
            # child context is written, so nothing is left behind.
            raise FoundryError(
                "circle-select revises an existing analysis; none has been stated yet"
            )
        # The items carry over unchanged, except that a record saved before phase 1 may still hold a
        # hierarchy level (dimensions.drilldown, PR #17). Save refuses those keys and suggests the same
        # items without them; the carry-over applies that suggestion so 改口径 does not fail on a key
        # that no longer matched any row.
        items = [_without_hierarchy(item) if isinstance(item, dict) and isinstance(item.get("dimensions"), dict) else item
                 for item in latest.get("items") or []]
        # The requirement scope comes from the context, and a context saved before phase 1 may still hold a
        # drilldown level (finance_context_save accepts any key; the engine ignores it). Save refuses a scope
        # level no earlier version had, so the carried scope leaves those keys behind, as the items do.
        scope = {key: value for key, value in self._primary_scope(context.get("scopes", {})).items()
                 if str(key).strip().lower() not in SCOPE_REFUSED_HIERARCHY_KEYS}
        req_spec = {
            "question": latest.get("question") or instruction,
            "scope": scope,
            "items": items,
            "change_reason": instruction,
            "selection": selection,
            "parent_id": latest["id"],
        }
        # Every refusal of the requirement save must come before the child context is written, or each
        # refused click leaves a context no requirement references.
        self._authorize(context["bindings"])
        prepare_requirements(self.analysis, {**req_spec, "bindings": context["bindings"]}, _allowed=self.allowed)
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
        req_spec["context_id"] = child["id"]
        return {"requirements": self.analysis_requirements_save(req_spec), "context": child}



def _reproducibility_status(previous, output_hash):
    """Compare a rerun with earlier succeeded runs of the same fingerprint.

    Runs of the current calculation version decide first: all equal is
    reproducible, any difference non_reproducible. With none of those, runs
    of another version (no version recorded reads as 1) can confirm an equal
    output, but a different one only shows the calculation changed, so it is
    unverified rather than non_reproducible.
    """
    same = [
        r
        for r in previous
        if r.get("calculation_version", 1) == FINANCE_CALCULATION_VERSION
    ]
    if same:
        return (
            "reproducible"
            if all(r["output_hash"] == output_hash for r in same)
            else "non_reproducible"
        )
    if previous:
        return (
            "reproducible"
            if all(r["output_hash"] == output_hash for r in previous)
            else "unverified"
        )
    return "unverified"


def _replayable_draft(drafts, attempt=None):
    """The saved draft a retry of the same request may return instead of saving again.

    A settled attempt returns the draft it settled with (its receipt is already written). Otherwise only
    a draft whose check was computed under the current completion policy is replayed: a verdict from
    older rules must not be stamped into a current-policy receipt, so such a request is checked again.
    """
    from foundry.finance_completion import COMPLETION_POLICY_VERSION

    if attempt and attempt.get("completion_id"):
        return next((row for row in drafts if row.get("id") == attempt.get("draft_id")), drafts[0] if drafts else None)
    return next((row for row in reversed(drafts) if row.get("check_policy_version") == COMPLETION_POLICY_VERSION), None)


def _text_pages(node):
    """A copy with every node's numeric `page` written as text, as the document contract requires."""
    from decimal import Decimal

    if isinstance(node, list):
        return [_text_pages(child) for child in node]
    if not isinstance(node, dict):
        return node
    copy = {key: _text_pages(value) for key, value in node.items()}
    attrs = copy.get("attrs")
    page = attrs.get("page") if isinstance(attrs, dict) else None
    if isinstance(page, (int, Decimal)) and not isinstance(page, bool) and page == int(page):
        copy["attrs"] = {**attrs, "page": str(int(page))}
    return copy


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
