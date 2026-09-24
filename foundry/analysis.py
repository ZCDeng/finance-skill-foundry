"""Task-owned analysis snapshots, immutable revisions, execution and deliverables.

These objects are parallel to legacy closing windows. Creating an analysis never
creates a ledger, imports a chart of accounts, or grants a payment instruction.
"""

from __future__ import annotations

import hashlib
import io
import json
import platform
import re
import sys
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
from openpyxl import Workbook
from openpyxl.comments import Comment

from foundry.analysis_data import MAX_SOURCE_BYTES, SUPPORTED, json_value, parse_source
from foundry.analysis_sql import CONFIG, execute_sql, method_template, validate_relationship_contract
from foundry.analysis_parameters import normalize_parameter_metadata, method_parameters
from foundry.errors import FoundryError
from foundry.fsutil import write_json_atomic
from foundry.locking import exclusive
from foundry.task import Task, now_iso
from foundry.sheet import survives_a_cell, put_number
from foundry.report_documents import report_document_excel_rows

ID = re.compile(r"^[0-9a-f]{32}$")
ALIAS = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
KINDS = {"revisions", "runs", "drafts", "methods", "requirements", "evidence_checks", "completions"}
REPORT_EXPORT_FORMATS = {"md", "xlsx", "docx", "pdf", "html"}
RESULT_ROLES = {"business", "activity", "probe", "preanalysis", "calculation", "draft_support", "audit_check"}
REVIEW = {"unreviewed", "reviewed", "accepted"}
PUBLICATION = {"draft", "archived"}
SCRIPT_RESULT_PREVIEW_ROWS = 1000
BASIS = {
    "source_fact",
    "calculation",
    "external_reference",
    "user_assumption",
    "professional_judgment",
}


def _bytes(value: Any) -> bytes:
    return json.dumps(
        json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf8")


def _hash(value: Any) -> str:
    return hashlib.sha256(_bytes(value)).hexdigest()


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()






def _quality_status_dimensions(
    *,
    execution_status: str,
    review_status: str,
    quality_issues: list[dict],
    evidence_report: dict,
    consistency_report: dict,
    numeric_configured: bool = True,
) -> dict[str, dict]:
    evidence_issues = [item for item in quality_issues if str(item.get("code", "")).startswith("evidence_recipe_")]
    consistency_issues = [item for item in quality_issues if str(item.get("code", "")).startswith("financial_consistency_")]
    revision_issues = [item for item in quality_issues if str(item.get("code", "")).startswith("revision_")]
    numeric_issues = [
        item
        for item in quality_issues
        if item not in evidence_issues and item not in consistency_issues and item not in revision_issues
    ]
    evidence_status = (evidence_report.get("summary") or {}).get("status") or "not_configured"
    consistency_status = (consistency_report.get("summary") or {}).get("status") or "pass"
    source_status = "needs_attention" if consistency_status == "needs_attention" else evidence_status
    source_issues = [*evidence_issues, *consistency_issues]
    return {
        "execution": {
            "label": "执行状态",
            "status": "pass" if execution_status == "succeeded" else execution_status,
            "issues": [],
        },
        "numeric_citation": {
            "label": "数值引用",
            "status": (
                "needs_attention"
                if numeric_issues or revision_issues
                else "pass"
                if numeric_configured
                else "not_configured"
            ),
            "issues": [*numeric_issues, *revision_issues],
        },
        "source_validation": {
            "label": "来源核验",
            "status": source_status,
            "issues": source_issues,
        },
        "professional_review": {
            "label": "专业复核",
            "status": "pass" if review_status in {"reviewed", "accepted"} else "unreviewed",
            "issues": [],
        },
    }

def _fact_ids_in_runs(analysis: Any, fact_ids: list, runs: dict[str, dict], materiality: Any) -> list:
    from foundry.finance_explanations import prepare_explanation

    succeeded = [run for run in runs.values() if run.get("execution_status") == "succeeded"]
    available = {fact["id"] for fact in prepare_explanation(analysis, succeeded, materiality=materiality)["facts"]}
    return [fact_id for fact_id in fact_ids if fact_id in available]


def _revision_quality_issues(comparison: dict) -> list[dict]:
    issues = []
    for item in comparison.get("issues", []):
        code = item.get("code")
        if code == "revision_numeric_regression":
            issues.append({
                **item,
                "severity": item.get("severity", "error"),
                "message": item.get("message") or "同源同口径业务数值发生变化，需要解释或修正。",
            })
        elif code in {"revision_basis_changed", "revision_comparison_ambiguous"}:
            issues.append({
                **item,
                "severity": item.get("severity", "warning"),
                "message": item.get("message") or "修订比较口径发生变化，需要复核。",
            })
    return issues


def _new(task: Task, **fields) -> dict:
    return {
        "id": uuid.uuid4().hex,
        "task_id": task.id,
        "schema_version": 1,
        "created_at": now_iso(),
        **json_value(fields),
    }


def _assert_id(value: str) -> str:
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise FoundryError(f"invalid analysis object id: {value}")
    return value


def _safe_text(value: Any, label: str, *, required=False, maximum=1_000_000) -> str:
    if (
        not isinstance(value, str)
        or (required and not value.strip())
        or len(value) > maximum
    ):
        raise FoundryError(
            f"{label} must be {'nonempty ' if required else ''}text (at most {maximum} characters)"
        )
    return value




def _result_role(value: Any, *, default: str = "business") -> str:
    if value in (None, ""):
        return default
    if not isinstance(value, str) or value not in RESULT_ROLES:
        raise FoundryError("result_role is unsupported")
    return value


def _scope_metadata(value: Any) -> dict:
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise FoundryError("scope must be an object")
    return json_value(value)


def _requirements_id(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return _assert_id(value)

def _append_excel(sheet, row):
    parts = [
        (
            [value[i : i + 32000] for i in range(0, len(value), 32000)]
            if isinstance(value, str) and len(value) > 32000
            else [value]
        )
        for value in row
    ]
    for index in range(max((len(part) for part in parts), default=1)):
        sheet.append([part[index] if index < len(part) else None for part in parts])


def _script_result_path(value: Any) -> str | None:
    if value is None:
        return None
    path = _safe_text(value, "script result_file", required=True, maximum=1000)
    relative = Path(path)
    if relative.is_absolute() or ".." in relative.parts:
        raise FoundryError("script result_file must be a relative output path")
    if relative.suffix.casefold() not in {".csv", ".json"}:
        raise FoundryError("script result_file must be a CSV or JSON table")
    return relative.as_posix()


def _empty_script_result() -> dict:
    return {"columns": [], "rows": [], "row_count": 0, "truncated": False}


class AnalysisStore:
    def __init__(self, task: Task):
        self.task = task
        self.root = task.root / "analysis"
        if self.root.is_symlink():
            raise FoundryError("analysis root cannot use symbolic links")
        if task.root.is_symlink() or not task.root.resolve().is_relative_to(
            task.store.tasks_dir.resolve()
        ):
            raise FoundryError("analysis task path escapes task store")
        self._inside(self.root)

    def _inside(self, path: Path) -> Path:
        if not path.resolve().is_relative_to(self.task.root.resolve()):
            raise FoundryError("analysis path escapes this task")
        current = path
        while True:
            if current.is_symlink():
                raise FoundryError("analysis paths cannot use symbolic links")
            if current.resolve() == self.task.root.resolve():
                break
            if current == current.parent:
                raise FoundryError("analysis path has no task ancestor")
            current = current.parent
        return path

    def _object_path(self, kind: str, object_id: str) -> Path:
        _assert_id(object_id)
        if kind not in KINDS:
            raise FoundryError("unknown analysis object kind")
        return self._inside(self.root / kind / (object_id + ".json"))

    def _read(self, path: Path) -> dict:
        self._inside(path)
        try:
            record = json.loads(path.read_text(encoding="utf8"))
        except (OSError, ValueError) as exc:
            raise FoundryError(f"analysis object is unavailable: {path.name}") from exc
        check = dict(record)
        digest = check.pop("_integrity_hash", None)
        if (
            not digest
            or digest != _hash(check)
            or record.get("task_id") != self.task.id
        ):
            raise FoundryError("analysis object integrity check failed")
        return record

    def _write(self, path: Path, record: dict) -> dict:
        self._inside(path)
        record = json_value(record)
        with exclusive(self.task.lock_path, timeout=10):
            return self._write_locked(path, record)

    def _write_locked(self, path: Path, record: dict) -> dict:
        """Commit an immutable object while the caller holds the task lock."""
        self._inside(path)
        if path.exists():
            raise FoundryError("immutable analysis object already exists")
        record = json_value(record)
        record["seq"] = self._next_seq()
        record["_integrity_hash"] = _hash(record)
        write_json_atomic(path, record)
        return record

    def _next_seq(self) -> int:
        # Called only while holding the task lock; gaps after interruption are
        # acceptable, duplicate/reordered committed versions are not.
        path = self._inside(self.root / "sequence.json")
        if path.exists():
            try:
                value = json.loads(path.read_text())["seq"]
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise ValueError("invalid sequence")
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise FoundryError("analysis sequence record is invalid") from exc
        else:
            value = 0
        value += 1
        write_json_atomic(path, {"task_id": self.task.id, "seq": value})
        return value

    def _get(self, kind: str, object_id: str) -> dict:
        return self._read(self._object_path(kind, object_id))

    def _list(self, kind: str) -> list[dict]:
        root = self._inside(self.root / kind)
        paths = root.glob("*.json") if root.exists() else []
        return sorted(
            [self._read(path) for path in paths],
            key=lambda r: (r.get("seq", 0), r["created_at"], r["id"]),
        )

    def _get_method(self, method_id: str) -> dict:
        _assert_id(method_id)
        for task in [
            self.task,
            *[task for task in self.task.store.list() if task.id != self.task.id],
        ]:
            source = AnalysisStore(task)
            path = source._object_path("methods", method_id)
            if path.exists():
                return source._read(path)
        raise FoundryError("saved analysis method does not exist")

    def _methods(self) -> list[dict]:
        # Only explicitly saved, sanitized methods cross task boundaries. This
        # lookup never reads another task's snapshots, revisions, or run outputs.
        methods = [
            method
            for task in self.task.store.list()
            for method in AnalysisStore(task)._list("methods")
        ]
        return sorted(
            methods,
            key=lambda row: (row["created_at"], row["task_id"], row.get("seq", 0)),
        )

    def state(self) -> dict:
        root = self._inside(self.root / "datasets")
        datasets = (
            [record for path in root.glob("*/meta.json")
             if self._dataset_published(record := self._read(path))]
            if root.exists()
            else []
        )
        return {
            "schema_version": 1,
            "task_id": self.task.id,
            "datasets": sorted(
                datasets, key=lambda r: (r.get("seq", 0), r["created_at"], r["id"])
            ),
            "analyses": self._list("revisions"),
            "runs": self._list("runs"),
            "drafts": self._list("drafts"),
            "requirements": self._list("requirements"),
            "evidence_checks": self._list("evidence_checks"),
            "completions": self._list("completions"),
            "methods": self._methods(),
        }

    def add_dataset(
        self,
        path: Path,
        *,
        name: str,
        metadata: dict | None = None,
        allow_duplicate: bool = False,
    ) -> dict:
        path = Path(path)
        _safe_text(name, "dataset name", required=True, maximum=200)
        if metadata is not None and not isinstance(metadata, dict):
            raise FoundryError("dataset metadata must be an object")
        metadata = json_value(metadata or {})
        suffix = path.suffix.lower()
        if suffix not in SUPPORTED:
            raise FoundryError(
                f"unsupported format {suffix}; supported: CSV, XLSX, JSON, Markdown and TXT"
            )
        try:
            if not path.is_file() or path.stat().st_size > MAX_SOURCE_BYTES:
                raise FoundryError("dataset source must be a file of at most 32 MiB")
            with path.open("rb") as handle:
                data = handle.read(MAX_SOURCE_BYTES + 1)
        except OSError as exc:
            raise FoundryError(f"cannot read dataset source: {exc}") from exc
        source_hash = _hash_bytes(data)
        if not allow_duplicate:
            existing = self._same_source(source_hash)
            if existing is not None:
                # The manager already has these bytes. Hand back the copy she has,
                # marked as the same upload, rather than filing a second one she
                # then has to tell apart.
                return {**existing, "duplicate_of": existing["id"]}
        parsed = parse_source(data, suffix, metadata)
        for paragraph in parsed.get("paragraphs", []):
            paragraph["source_hash"] = source_hash
        encoded = _bytes(parsed)
        record = _new(
            self.task,
            name=name,
            kind=parsed["kind"],
            source_name=path.name,
            source_hash=source_hash,
            source_bytes=len(data),
            data_hash=_hash_bytes(encoded),
            schema=parsed["schema"],
            row_count=parsed["row_count"],
            metadata=metadata,
            transformation=parsed["transformation"],
            source_file="source" + suffix,
        )
        folder = self._inside(self.root / "datasets" / record["id"])
        with exclusive(self.task.lock_path, timeout=10):
            self._inside(folder)
            folder.mkdir(parents=True, exist_ok=False)
            (folder / record["source_file"]).write_bytes(data)
            (folder / "data.json").write_bytes(encoded)
            # Commit metadata last: readers never observe a partially imported dataset.
            record["seq"] = self._next_seq()
            record["_integrity_hash"] = _hash(record)
            write_json_atomic(folder / "meta.json", record)
        return record

    def _same_source(self, source_hash: str) -> dict | None:
        """An earlier upload of exactly these bytes, if the task has one.

        A table derived from a confirmed structure carries its original's bytes
        too, so it is skipped here: it is the same file seen through a structure,
        not a second upload of it.
        """
        for row in self.state()["datasets"]:
            if row.get("source_hash") != source_hash:
                continue
            if (row.get("transformation") or {}).get("structure"):
                continue
            return row
        return None

    def add_table_snapshot(
        self, source_dataset_id: str, declaration: dict, *, name: str
    ) -> dict:
        """File the calculable table a confirmed structure declaration describes.

        The original workbook bytes are stored again, so the snapshot answers for
        its own source and a located figure can still be opened in the file the
        manager uploaded.
        """
        from foundry.structure_snapshot import derive_table

        _safe_text(name, "dataset name", required=True, maximum=200)
        if not isinstance(declaration, dict):
            raise FoundryError("structure declaration must be an object")
        shell = self.read_dataset(source_dataset_id)
        folder = self._inside(self.root / "datasets" / source_dataset_id)
        data = (folder / shell["source_file"]).read_bytes()
        if _hash_bytes(data) != shell["source_hash"]:
            raise FoundryError("dataset integrity check failed")
        declaration = json_value({**declaration, "derived_from": source_dataset_id})
        parsed = derive_table(data, declaration)
        encoded = _bytes(
            {
                "kind": parsed["kind"],
                "schema": parsed["schema"],
                "rows": parsed["rows"],
                "row_count": parsed["row_count"],
                "transformation": parsed["transformation"],
            }
        )
        record = _new(
            self.task,
            name=name,
            kind="table",
            source_name=shell["source_name"],
            source_hash=shell["source_hash"],
            source_bytes=len(data),
            data_hash=_hash_bytes(encoded),
            schema=parsed["schema"],
            row_count=parsed["row_count"],
            metadata={"derived_from": source_dataset_id, "sheet": declaration["sheet"]},
            transformation=parsed["transformation"],
            source_file=shell["source_file"],
        )
        destination = self._inside(self.root / "datasets" / record["id"])
        with exclusive(self.task.lock_path, timeout=10):
            self._inside(destination)
            destination.mkdir(parents=True, exist_ok=False)
            (destination / record["source_file"]).write_bytes(data)
            (destination / "data.json").write_bytes(encoded)
            record["seq"] = self._next_seq()
            record["_integrity_hash"] = _hash(record)
            write_json_atomic(destination / "meta.json", record)
        return record

    def read_dataset(self, dataset_id: str) -> dict:
        _assert_id(dataset_id)
        folder = self._inside(self.root / "datasets" / dataset_id)
        metadata = self._read(folder / "meta.json")
        if not self._dataset_published(metadata):
            raise FoundryError("source batch is not published; snapshot is unavailable")
        data_path = self._inside(folder / "data.json")
        source_path = self._inside(folder / metadata["source_file"])
        try:
            data = data_path.read_bytes()
            source = source_path.read_bytes()
            if (
                _hash_bytes(data) != metadata["data_hash"]
                or _hash_bytes(source) != metadata["source_hash"]
            ):
                raise FoundryError("dataset integrity check failed")
            return {**metadata, **json.loads(data)}
        except (OSError, ValueError) as exc:
            raise FoundryError(
                "dataset integrity check failed: missing or invalid snapshot"
            ) from exc

    def _dataset_published(self, metadata: dict) -> bool:
        batch_id = metadata.get("metadata", {}).get("source_refresh", {}).get("source_batch_id")
        if not batch_id:
            return True
        batch_path = self._inside(self.root / "source_batches" / f"{_assert_id(batch_id)}.json")
        if not batch_path.exists():
            return False
        batch = self._read(batch_path)
        if batch.get("publication_status") != "published" or batch.get("dataset_id") != metadata["id"]:
            raise FoundryError("source batch publication does not match snapshot")
        return True

    def save_analysis(self, spec: dict) -> dict:
        if not isinstance(spec, dict):
            raise FoundryError("analysis spec must be an object")
        question = _safe_text(
            spec.get("question"), "question", required=True, maximum=20000
        )
        engine = spec.get("engine", "sql")
        if not isinstance(engine, str) or engine not in {"sql", "structured_aggregate"}:
            raise FoundryError("analysis engine must be sql or structured_aggregate")
        structured = engine == "structured_aggregate"
        sql = _safe_text(spec.get("sql", ""), "SQL", required=not structured, maximum=100000)
        bindings = spec.get("bindings") or {}
        if not isinstance(bindings, dict) or not bindings or len(bindings) > 32:
            raise FoundryError("analysis needs 1–32 explicit snapshot bindings")
        if len({str(a).casefold() for a in bindings}) != len(bindings):
            raise FoundryError("binding aliases must be unique (case insensitive)")
        for alias, dataset_id in bindings.items():
            if not isinstance(alias, str) or not ALIAS.fullmatch(alias):
                raise FoundryError(f"invalid dataset alias: {alias}")
            self.read_dataset(dataset_id)
        aggregate_plan = None
        if structured:
            from foundry.analysis_aggregate import validate_aggregate_plan
            plan = spec.get("aggregate_plan")
            if (not isinstance(plan, dict) or len(bindings) != 1
                    or not isinstance(plan.get("dataset_alias"), str)
                    or plan["dataset_alias"] not in bindings):
                raise FoundryError("structured aggregate needs exactly its single snapshot binding")
            if sql or spec.get("parameters") or spec.get("parameter_metadata") or spec.get("relationships"):
                raise FoundryError("structured aggregate uses its plan, not SQL, parameters or relationships")
            aggregate_plan = validate_aggregate_plan(plan, self.read_dataset(bindings[plan['dataset_alias']]))
        elif spec.get("aggregate_plan") is not None:
            raise FoundryError("aggregate_plan requires structured_aggregate engine")
        parent_id = spec.get("parent_id")
        if parent_id:
            self.get_analysis(parent_id)
        requirements_id = _requirements_id(spec.get("requirements_id"))
        if requirements_id:
            self._get("requirements", requirements_id)
        result_role = _result_role(spec.get("result_role"))
        scope = _scope_metadata(spec.get("scope"))
        parameters = spec.get("parameters") or []
        if not isinstance(parameters, (list, dict)):
            raise FoundryError("SQL parameters must be an array or object")
        parameter_metadata = [] if structured else normalize_parameter_metadata(
            sql, parameters, spec.get("parameter_metadata")
        )
        timeout = spec.get("timeout_seconds", 15)
        max_rows = spec.get("max_rows", 1000)
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float, Decimal))
            or not 0.01 <= timeout <= 60
        ):
            raise FoundryError("timeout_seconds must be between 0.01 and 60")
        if (
            isinstance(max_rows, bool)
            or not isinstance(max_rows, int)
            or not 1 <= max_rows <= 10000
        ):
            raise FoundryError("max_rows must be between 1 and 10000")
        timeout = float(timeout)
        fields = {}
        for key in [
            "assumptions",
            "relationships",
            "metrics",
            "grain",
            "missing_inputs",
            "conversion_rules",
        ]:
            value = spec.get(key, [])
            if not isinstance(value, list):
                raise FoundryError(f"{key} must be an array")
            fields[key] = value
        fields["relationships"] = validate_relationship_contract(
            fields["relationships"], set(bindings)
        )
        record = _new(
            self.task,
            **({"engine": engine, "aggregate_plan": aggregate_plan} if structured else {}),
            question=question,
            sql=sql,
            bindings=bindings,
            parameters=parameters,
            parameter_metadata=parameter_metadata,
            parent_id=parent_id,
            requirements_id=requirements_id,
            result_role=result_role,
            scope=scope,
            max_rows=max_rows,
            timeout_seconds=timeout,
            method_id=spec.get("method_id"),
            **fields,
        )
        if record["method_id"]:
            self._get_method(record["method_id"])
        return self._write(self._object_path("revisions", record["id"]), record)

    def get_analysis(self, analysis_id: str) -> dict:
        return self._get("revisions", analysis_id)

    def get_run(self, run_id: str) -> dict:
        run = self._get("runs", run_id)
        for output in run.get("outputs", []):
            path = self._inside(self.root / output["artifact_path"])
            if not path.is_file() or _hash_bytes(path.read_bytes()) != output["sha256"]:
                raise FoundryError("run output integrity check failed")
        return run

    def aggregate_sources_verified(self, run: dict) -> bool:
        """Validate the persisted executor boundary, never caller source claims."""
        if run.get("engine") != "structured_aggregate" or run.get("execution_status") != "succeeded":
            return False
        definition = self.get_analysis(run["analysis_id"])
        result = run.get("result", {})
        provenance = result.get("provenance", {})
        if (definition.get("engine") != "structured_aggregate"
                or definition.get("aggregate_plan") != run.get("aggregate_plan")
                or definition.get("bindings") != run.get("bindings")
                or _hash(result) != run.get("output_hash")
                or provenance.get("mode") != "executor_verified_source_map"
                or provenance.get("status") != "verified"):
            return False
        for alias, dataset_id in run["bindings"].items():
            data = self.read_dataset(dataset_id)
            if (run.get("input_hashes", {}).get(alias) != data["data_hash"]
                    or run.get("source_hashes", {}).get(alias) != data["source_hash"]):
                return False
        return True

    def run_analysis(
        self,
        analysis_id: str,
        *,
        session_id: str | None = None,
        context_revision: int | None = None,
    ) -> dict:
        from foundry.finance_requirement_semantics import capture_requirements
        requirements_snapshot = capture_requirements(self)
        analysis = self.get_analysis(analysis_id)
        requirements_snapshot = {
            **requirements_snapshot,
            "requirements_id": analysis.get("requirements_id") or requirements_snapshot.get("requirements_id"),
        }
        if analysis.get("engine") == "finance":
            from foundry.finance_service import FinanceStore

            return FinanceStore(
                self.task, session_id=session_id, context_revision=context_revision
            ).run_revision(analysis)
        if analysis.get("engine") in {"python", "shell"}:
            return self.run_script(
                {
                    "code": analysis["code"],
                    "language": analysis["engine"],
                    "bindings": analysis["bindings"],
                    "question": analysis["question"],
                    "timeout_seconds": analysis["timeout_seconds"],
                    "assumptions": analysis["assumptions"],
                    "result_file": analysis.get("result_file"),
                    "requirements_id": analysis.get("requirements_id"),
                    "result_role": analysis.get("result_role"),
                    "scope": analysis.get("scope", {}),
                },
                session_id=session_id,
                context_revision=context_revision,
                analysis_id=analysis_id,
            )
        datasets = {
            alias: self.read_dataset(dataset_id)
            for alias, dataset_id in analysis["bindings"].items()
        }
        structured = analysis.get("engine") == "structured_aggregate"
        environment = {
            "python": platform.python_version(),
            "duckdb": duckdb.__version__,
            "platform": sys.platform,
            "runner": "snapshot-aggregate-v1" if structured else "snapshot-sql-v1",
            "settings": CONFIG,
            "configuration_locked": True,
        }
        code_hash = _hash(
            {"aggregate_plan": analysis["aggregate_plan"]} if structured
            else {"sql": analysis["sql"], "parameters": analysis["parameters"]}
        )
        input_hashes = {alias: data["data_hash"] for alias, data in datasets.items()}
        fingerprint = _hash(
            {
                "code_hash": code_hash,
                "inputs": input_hashes,
                "environment": environment,
                "relationships": analysis["relationships"],
                "max_rows": analysis["max_rows"],
            }
        )
        if structured:
            from foundry.analysis_aggregate import execute_aggregate
            import time
            started = time.monotonic()
            try:
                aggregate = execute_aggregate(
                    datasets[analysis["aggregate_plan"]["dataset_alias"]],
                    analysis["aggregate_plan"], max_rows=analysis["max_rows"],
                    timeout_seconds=analysis["timeout_seconds"],
                )
                result = {"result": aggregate, "deterministic": True,
                          "duration_seconds": time.monotonic() - started}
            except FoundryError as exc:
                result = {"error": str(exc), "deterministic": True,
                          "duration_seconds": time.monotonic() - started}
        else:
            result = execute_sql(datasets, analysis)
        succeeded = "error" not in result
        output_hash = _hash(result["result"]) if succeeded else None
        previous = [
            r
            for r in self._list("runs")
            if r.get("fingerprint") == fingerprint
            and r["execution_status"] == "succeeded"
        ]
        reproducibility = "unverified"
        if succeeded and not result["deterministic"]:
            reproducibility = "non_reproducible"
        elif succeeded and previous:
            reproducibility = (
                "reproducible"
                if all(r["output_hash"] == output_hash for r in previous)
                else "non_reproducible"
            )
        record = _new(
            self.task,
            analysis_id=analysis_id,
            **({"engine": "structured_aggregate", "aggregate_plan": analysis["aggregate_plan"],
                "finance_scope": analysis["aggregate_plan"].get("scope", {})}
               if structured else {}),
            **requirements_snapshot,
            result_role=analysis.get("result_role", "business"),
            scope=analysis.get("scope", {}),
            session_id=session_id,
            context_revision=context_revision,
            sql=analysis["sql"],
            parameters=analysis["parameters"],
            parameter_metadata=analysis.get("parameter_metadata", []),
            bindings=analysis["bindings"],
            input_hashes=input_hashes,
            source_hashes={
                alias: data["source_hash"] for alias, data in datasets.items()
            },
            code_hash=code_hash,
            fingerprint=fingerprint,
            environment=environment,
            execution_status="succeeded" if succeeded else "failed",
            reproducibility_status=reproducibility,
            review_status="unreviewed",
            publication_status="draft",
            output_hash=output_hash,
            missing_inputs=analysis["missing_inputs"],
            assumptions=analysis["assumptions"],
            **result,
        )
        return self._write(self._object_path("runs", record["id"]), record)

    def get_draft(self, draft_id: str) -> dict:
        return self._get("drafts", draft_id)

    def _registered_report_source_ids(self) -> set[str]:
        return set(self._registered_report_sources())

    def _registered_report_sources(self) -> dict[str, dict]:
        root = self._inside(self.root / "report_sources")
        sources = {}
        for path in root.glob("*.json"):
            if ID.fullmatch(path.stem):
                try:
                    record = self._read(path)
                except FoundryError:
                    continue
                sources[record["id"]] = self._report_source_public(record)
        return sources

    def save_draft(self, spec: dict) -> dict:
        if not isinstance(spec, dict):
            raise FoundryError("draft spec must be an object")
        parent = self.get_draft(spec["parent_id"]) if spec.get("parent_id") else {}
        title = _safe_text(
            spec.get("title", parent.get("title", "分析报告")),
            "draft title",
            required=True,
            maximum=1000,
        )
        document = None
        if spec.get("document") is not None:
            from foundry.report_documents import report_document_markdown, validate_report_document

            report_sources = self._registered_report_sources()
            document = validate_report_document(
                spec["document"],
                registered_source_ids=set(report_sources),
            )
            if document.get("sources"):
                document["sources"] = [report_sources[source["id"]] for source in document["sources"]]
            projected = report_document_markdown(document)
            body = _safe_text(projected, "draft body")
        elif "body" not in spec and parent.get("document") is not None:
            document = parent["document"]
            body = _safe_text(parent.get("body", ""), "draft body")
        else:
            body = _safe_text(spec.get("body", parent.get("body", "")), "draft body")
        body_template = spec.get("body_template")
        if body_template is not None:
            body_template = _safe_text(body_template, "draft body_template")
        run_ids = spec.get("run_ids", parent.get("run_ids", []))
        if not isinstance(run_ids, list):
            raise FoundryError("run_ids must be an array")
        runs = {run_id: self.get_run(run_id) for run_id in dict.fromkeys(run_ids)}
        fact_ids = spec.get("fact_ids", parent.get("fact_ids", []))
        if not isinstance(fact_ids, list):
            raise FoundryError("fact_ids must be an array")
        claims = json_value(spec.get("claims", parent.get("claims", [])))
        if not isinstance(claims, list):
            raise FoundryError("claims must be an array")
        for claim in claims:
            if not isinstance(claim, dict) or claim.get("basis") not in BASIS:
                raise FoundryError("claim requires an explicit basis")
            if claim["basis"] == "calculation":
                run = runs.get(claim.get("run_id"))
                if not run or run["execution_status"] != "succeeded":
                    raise FoundryError(
                        "calculation claim requires a referenced successful run"
                    )
                try:
                    row = claim["row"]
                    if isinstance(row, bool) or not isinstance(row, int) or row < 0:
                        raise KeyError("row")
                    actual = run["result"]["rows"][row][claim["column"]]
                    expected = claim["value"]
                    matches = actual == expected
                    if not matches and actual is not None and expected is not None:
                        from decimal import Decimal, InvalidOperation

                        try:
                            matches = Decimal(str(actual)) == Decimal(str(expected))
                        except InvalidOperation:
                            pass
                    if not matches:
                        error = FoundryError(
                            "claim value differs from execution result "
                            f"(run_id={run['id']}, row={row}, column={claim['column']}, "
                            f"expected={expected}, actual={actual})"
                        )
                        error.details = {
                            "code": "claim_value_mismatch",
                            "run_id": run["id"],
                            "row": row,
                            "column": claim["column"],
                            "expected": str(expected),
                            "actual": str(actual),
                        }
                        raise error
                except (KeyError, IndexError, TypeError) as exc:
                    raise FoundryError("claim has an invalid output location") from exc
                claim["verification_status"] = "matches_run"
                claim["dependencies"] = {
                    "snapshot_ids": list(run["bindings"].values()),
                    "assumptions": run["assumptions"],
                }
            else:
                claim["verification_status"] = "unverified"
                if claim.get("dataset_id"):
                    data = self.read_dataset(claim["dataset_id"])
                    if claim.get("paragraph"):
                        if not any(
                            p["paragraph"] == claim["paragraph"]
                            for p in data.get("paragraphs", [])
                        ):
                            raise FoundryError(
                                "claim background paragraph does not exist"
                            )
                    claim["source_hash"] = data["source_hash"]
        publication = spec.get("publication_status", "draft")
        review = spec.get("review_status", "unreviewed")
        limitations = spec.get("limitations", parent.get("limitations", []))
        if (
            publication not in PUBLICATION
            or review not in REVIEW
            or not isinstance(limitations, list)
        ):
            raise FoundryError("invalid draft status or limitations")
        if (
            publication == "archived"
            and any(r["execution_status"] != "succeeded" for r in runs.values())
            and not limitations
        ):
            raise FoundryError(
                "archiving failed execution references requires explicit limitations"
            )
        changed = bool(parent) and (
            body != parent.get("body") or claims != parent.get("claims")
        )
        if changed:
            review = "unreviewed"
        reproducibility = (
            "reproducible"
            if claims
            and runs
            and all(
                r["reproducibility_status"] == "reproducible" for r in runs.values()
            )
            and not changed
            and all(c["basis"] == "calculation" for c in claims)
            else "unverified"
        )
        from foundry.finance_explanations import validate_explanation

        materiality = spec.get("materiality", parent.get("materiality", {}))
        source_read_failures = spec.get("source_read_failures", parent.get("source_read_failures", []))
        evidence_appendix = spec.get("evidence_appendix", parent.get("evidence_appendix", ""))
        evidence_appendix_meta = spec.get(
            "evidence_appendix_meta", parent.get("evidence_appendix_meta", {})
        )
        from foundry.finance_requirements import augment_quality, latest_requirements

        current_requirements = latest_requirements(self)
        requirements_id = spec.get("requirements_id", parent.get("requirements_id")) or (current_requirements or {}).get("id")
        if "fact_ids" not in spec and fact_ids and set(runs) != set(parent.get("run_ids", [])):
            # A revision that swaps its runs must not carry the parent's facts from runs it no longer cites.
            fact_ids = _fact_ids_in_runs(self, fact_ids, runs, materiality)
        explanation_check = validate_explanation(
            self,
            {
                "requirements_id": requirements_id,
                "body": body,
                "run_ids": list(runs),
                "fact_ids": fact_ids,
                "claims": claims,
                "materiality": materiality,
                "evidence_appendix": evidence_appendix,
                "evidence_appendix_meta": evidence_appendix_meta,
            },
        )
        evidence_recipes = spec.get("evidence_recipes", parent.get("evidence_recipes", []))
        explanation_check = augment_quality(self, {
            "body": body, "run_ids": list(runs), "claims": claims,
            "requirements_id": requirements_id,
            "source_read_failures": source_read_failures,
            "evidence_recipes": evidence_recipes,
        }, explanation_check)
        consistency_rules = spec.get("consistency_rules", parent.get("consistency_rules", []))
        consistency_sources = spec.get("consistency_sources", parent.get("consistency_sources", {}))
        from foundry.finance_revision import compare_draft_runs
        from foundry.financial_consistency import consistency_quality_issues, evaluate_consistency_rules
        from foundry.financial_evidence import evaluate_evidence_recipes, prepare_consistency_inputs

        revision_comparison = compare_draft_runs(self, parent, {"run_ids": list(runs)})
        evidence_report = evaluate_evidence_recipes(self, evidence_recipes)
        resolved_rules, consistency_source_auth = prepare_consistency_inputs(self, consistency_rules, consistency_sources)
        consistency_report = evaluate_consistency_rules(
            resolved_rules,
            recipe_report=evidence_report,
            source_auth=consistency_source_auth,
        )
        quality_issues = list(explanation_check.get("issues", []))
        quality_issues.extend(_revision_quality_issues(revision_comparison))
        quality_issues.extend(evidence_report.get("issues", []))
        quality_issues.extend(consistency_quality_issues(consistency_report))
        execution_status = (
            "succeeded"
            if runs and all(r["execution_status"] == "succeeded" for r in runs.values())
            else "failed"
            if runs
            else "not_run"
        )
        status_dimensions = _quality_status_dimensions(
            execution_status=execution_status,
            review_status=review,
            quality_issues=quality_issues,
            evidence_report=evidence_report,
            consistency_report=consistency_report,
            numeric_configured=bool(runs or claims),
        )
        explanation_check = {
            **explanation_check,
            "issues": quality_issues,
            "status": "needs_attention" if quality_issues else explanation_check.get("status", "pass"),
            "status_dimensions": status_dimensions,
        }
        record = _new(
            self.task,
            requirements_id=requirements_id,
            materiality=materiality,
            completion_request_key=spec.get("completion_request_key"),
            completion_operation_id=spec.get("completion_operation_id"),
            completion_operation_revision=spec.get("completion_operation_revision"),
            source_read_failures=source_read_failures,
            evidence_appendix=evidence_appendix,
            evidence_appendix_meta=evidence_appendix_meta,
            evidence_recipes=evidence_recipes,
            evidence_report=evidence_report,
            consistency_rules=consistency_rules,
            consistency_sources=consistency_sources,
            consistency_report=consistency_report,
            title=title,
            body=body,
            **({"document": document} if document is not None else {}),
            **({"body_template": body_template} if body_template is not None else {}),
            run_ids=list(runs),
            fact_ids=fact_ids,
            claims=claims,
            revision_comparison=revision_comparison,
            explanation_check=explanation_check,
            quality=explanation_check,
            parent_id=parent.get("id"),
            execution_status=execution_status,
            reproducibility_status=reproducibility,
            review_status=review,
            publication_status=publication,
            limitations=limitations,
            content_hash=_hash(
                {
                    "title": title,
                    "requirements_id": requirements_id,
                    "materiality": materiality,
                    "body": body,
                    "body_template": body_template,
                    "document": document,
                    "run_ids": list(runs),
                    "fact_ids": fact_ids,
                    "claims": claims,
                    "limitations": limitations,
                }
            ),
        )
        return self._write(self._object_path("drafts", record["id"]), record)

    def add_report_source(self, path: Path, *, name: str | None = None) -> dict:
        from foundry.report_documents import check_report_source_bytes, report_format_for_path

        source = Path(path).expanduser()
        if not source.is_file() or source.is_symlink():
            raise FoundryError("report source must be a regular file")
        fmt = report_format_for_path(source)
        data = source.read_bytes()
        check_report_source_bytes(data, fmt)
        digest = _hash_bytes(data)
        record = _new(
            self.task,
            # A caller that built the bytes itself passes the name the manager
            # would recognise; otherwise the file on disk is the name.
            name=str(name).strip() if str(name or "").strip() else source.name,
            format=fmt,
            sha256=digest,
            bytes=len(data),
            source_file="source" + source.suffix.casefold(),
            imported_review_trust="not_trusted",
        )
        with exclusive(self.task.lock_path, timeout=10):
            root = self._inside(self.root / "report_sources" / record["id"])
            root.mkdir(parents=True, exist_ok=False)
            archived = self._inside(root / record["source_file"])
            archived.write_bytes(data)
            written = self._write_locked(self._inside(self.root / "report_sources" / (record["id"] + ".json")), record)
        return {"source": self._report_source_public(written), "path": str(archived.resolve())}

    def _report_source_path(self, source_id: str) -> Path:
        return self._inside(self.root / "report_sources" / (_assert_id(source_id) + ".json"))

    def _report_source_public(self, record: dict) -> dict:
        return {
            "id": record["id"],
            "name": record["name"],
            "sha256": record["sha256"],
            "format": record["format"],
        }

    def read_report_source(self, source_id: str) -> dict:
        record = self._read(self._report_source_path(source_id))
        path = self._inside(self.root / "report_sources" / record["id"] / record["source_file"])
        data = path.read_bytes()
        if _hash_bytes(data) != record["sha256"]:
            raise FoundryError("report source integrity check failed")
        return {"source": self._report_source_public(record), "path": str(path.resolve())}

    def read_report_xlsx(self, source_id: str, *, sheet: str | None = None, range_ref: str | None = None) -> dict:
        from foundry.report_documents import report_document_from_xlsx

        resolved = self.read_report_source(source_id)
        if resolved["source"]["format"] != "xlsx":
            raise FoundryError("report xlsx read requires an XLSX source")
        return report_document_from_xlsx(
            Path(resolved["path"]).read_bytes(),
            resolved["source"],
            sheet=sheet,
            range_ref=range_ref,
        )

    def register_report_export(
        self,
        draft_id: str,
        format: str,
        path: Path,
        *,
        content_mode: str | None = None,
        projection_hash: str | None = None,
    ) -> dict:
        if format not in REPORT_EXPORT_FORMATS:
            raise FoundryError("report export format must be md, xlsx, docx, pdf or html")
        draft = self.get_draft(draft_id)
        if projection_hash is not None and not re.fullmatch(r"[0-9a-f]{64}", projection_hash):
            raise FoundryError("report export projection_hash must be a sha256")
        if projection_hash is None:
            content_mode = None
        elif content_mode not in {"management", "audit"}:
            raise FoundryError("report export mode must be management or audit")
        template_version = (draft.get("document") or {}).get("template_version")
        source = Path(path).expanduser()
        if not source.is_file() or source.is_symlink():
            raise FoundryError("report export source must be a regular file")
        data = source.read_bytes()
        if len(data) > MAX_SOURCE_BYTES:
            raise FoundryError("report export exceeds 32 MiB limit")
        digest = _hash_bytes(data)
        filename = (
            f"{draft_id}-{content_mode}-{projection_hash[:12]}.{format}"
            if content_mode and projection_hash
            else f"{draft_id}.{format}"
        )
        target = self._inside(self.root / "exports" / "registered" / filename)
        manifest_path = self._inside(target.with_suffix(target.suffix + ".meta.json"))
        with exclusive(self.task.lock_path, timeout=10):
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                manifest = self._read(manifest_path)
                if (
                    manifest.get("sha256") != _hash_bytes(target.read_bytes())
                    or manifest.get("content_hash") != draft["content_hash"]
                    or manifest.get("content_mode") != content_mode
                    or manifest.get("projection_hash") != projection_hash
                ):
                    raise FoundryError("report export integrity check failed; archived bytes differ from their receipt")
                if manifest.get("format") != format or manifest.get("template_version") != template_version:
                    raise FoundryError("report export receipt does not match the requested format/template")
                digest = manifest["sha256"]
            else:
                temporary = self._inside(target.with_name("." + uuid.uuid4().hex + ".tmp"))
                try:
                    temporary.write_bytes(data)
                    temporary.replace(target)
                    manifest = _new(
                        self.task,
                        draft_id=draft_id,
                        format=format,
                        sha256=digest,
                        bytes=len(data),
                        content_hash=draft["content_hash"],
                        content_mode=content_mode,
                        projection_hash=projection_hash,
                        template_version=template_version,
                        source_sha256=digest,
                    )
                    manifest["_integrity_hash"] = _hash(manifest)
                    write_json_atomic(manifest_path, manifest)
                finally:
                    temporary.unlink(missing_ok=True)
        return {
            "task_id": self.task.id,
            "draft_id": draft_id,
            "format": format,
            "path": str(target.resolve()),
            "sha256": digest,
            "content_hash": draft["content_hash"],
            **({"content_mode": content_mode, "projection_hash": projection_hash} if content_mode and projection_hash else {}),
            "publication_status": draft["publication_status"],
        }

    def projection_for_draft(self, draft_id: str, mode: str = "management") -> dict:
        from foundry.financial_evidence import consistency_dataset_ids, recipe_dataset_ids
        from foundry.report_projection import build_report_projection

        draft = self.get_draft(draft_id)
        dataset_ids: set[str] = set()
        for run_id in draft.get("run_ids", []) or []:
            try:
                run = self.get_run(run_id)
            except FoundryError:
                continue
            bindings = run.get("bindings", {})
            if isinstance(bindings, dict):
                dataset_ids.update(value for value in bindings.values() if isinstance(value, str))
        for claim in draft.get("claims", []) or []:
            if not isinstance(claim, dict):
                continue
            if isinstance(claim.get("dataset_id"), str):
                dataset_ids.add(claim["dataset_id"])
            if isinstance(claim.get("run_id"), str):
                try:
                    run = self.get_run(claim["run_id"])
                except FoundryError:
                    continue
                bindings = run.get("bindings", {})
                if isinstance(bindings, dict):
                    dataset_ids.update(value for value in bindings.values() if isinstance(value, str))
        dataset_ids.update(recipe_dataset_ids(draft.get("evidence_recipes", [])))
        dataset_ids.update(consistency_dataset_ids(draft.get("consistency_sources", {})))
        resolved = []
        for dataset_id in sorted(dataset_ids):
            try:
                dataset = self.read_dataset(dataset_id)
            except FoundryError:
                continue
            resolved.append({
                "id": dataset["id"],
                "name": dataset.get("name") or dataset.get("source_name") or dataset["id"],
                "kind": dataset.get("kind") or dataset.get("metadata", {}).get("mode") or "dataset",
                "source_hash": dataset.get("source_hash"),
            })
        return build_report_projection(draft, mode=mode, resolved_datasets=resolved)

    def report_projection(self, draft_id: str, mode: str = "management") -> dict:
        return self.projection_for_draft(draft_id, mode)

    def export_draft(self, draft_id: str, format: str = "md", *, mode: str = "management") -> dict:
        draft = self.get_draft(draft_id)
        if format not in {"md", "xlsx"}:
            raise FoundryError("draft export format must be md or xlsx")
        projection = self.report_projection(draft_id, mode=mode)
        runs = [self.get_run(run_id) for run_id in draft["run_ids"]]
        path = self._inside(self.root / "exports" / f"{draft_id}-{mode}-{projection['projection_hash'][:12]}.{format}")
        with exclusive(self.task.lock_path, timeout=10):
            self._inside(path)
            manifest_path = self._inside(path.with_suffix(path.suffix + ".meta.json"))
            if path.exists():
                manifest = self._read(manifest_path)
                if (
                    manifest.get("sha256") != _hash_bytes(path.read_bytes())
                    or manifest.get("content_hash") != draft["content_hash"]
                    or manifest.get("projection_hash") != projection["projection_hash"]
                ):
                    raise FoundryError(
                        "export integrity check failed; archived bytes differ from their receipt"
                    )
            else:
                if format == "md":
                    lines = [
                        projection["body"].rstrip(),
                        "",
                        "---",
                        "",
                        f"Version: {draft_id}",
                        f"Projection: {projection['content_mode']}; SHA-256: {projection['projection_hash']}",
                        f"Status: {projection['publication_status']}; review: {projection['review_status']}",
                        f"Content SHA-256: {projection['content_hash']}",
                    ]
                    if draft["limitations"]:
                        lines += [
                            "",
                            "局限：",
                            *["- " + str(v) for v in draft["limitations"]],
                        ]
                    for run in runs:
                        lines += [
                            "",
                            f"Run: {run['id']}; execution: {run['execution_status']}; reproducibility: {run['reproducibility_status']}",
                            f"Output SHA-256: {run.get('output_hash')}",
                            "```" + (run.get("engine") or "sql"),
                            run.get("sql") or run.get("code") or (
                                json.dumps(run["aggregate_plan"], ensure_ascii=False, indent=2)
                                if run.get("aggregate_plan") else ""
                            ),
                            "```",
                            "Inputs: "
                            + json.dumps(run["input_hashes"], ensure_ascii=False),
                            "Sources: " + json.dumps(run.get("source_hashes", {}), ensure_ascii=False),
                        ]
                        if run.get("engine") == "structured_aggregate":
                            result = run.get("result", {})
                            lines += ["来源核验：" + str(result.get("provenance", {}).get("status", "unverified")),
                                      "```json", json.dumps({key: result.get(key) for key in (
                                          "provenance", "detail_rows", "excluded_detail_rows")},
                                          ensure_ascii=False, indent=2), "```"]
                    for run in runs:
                        if run.get("engine") in {"python", "shell"}:
                            lines += [
                                "",
                                "Script stdout:",
                                "```text",
                                run.get("stdout", ""),
                                "```",
                                "Script stderr:",
                                "```text",
                                run.get("stderr", ""),
                                "```",
                            ]
                            for artifact in run.get("outputs", []):
                                lines.append(
                                    "Artifact: "
                                    + artifact["artifact_path"]
                                    + "; SHA-256: "
                                    + artifact["sha256"]
                                )
                    data = ("\n".join(lines) + "\n").encode("utf8")
                else:
                    workbook = Workbook()
                    sheet = workbook.active
                    sheet.title = "Report"
                    for row in [
                        [projection["title"]],
                        [projection["marker"]],
                        [projection["body"]],
                        ["Version", draft_id],
                        ["Projection", projection["content_mode"]],
                        ["Projection SHA-256", projection["projection_hash"]],
                        ["Content SHA-256", projection["content_hash"]],
                        ["Publication", projection["publication_status"]],
                        ["Review", projection["review_status"]],
                        ["Reproducibility", projection["reproducibility_status"]],
                    ]:
                        _append_excel(sheet, row)
                    if projection.get("document"):
                        for sheet_name, rows in report_document_excel_rows(projection["document"], projection).items():
                            structured_sheet = workbook.create_sheet(sheet_name)
                            for row in rows:
                                _append_excel(structured_sheet, row)
                    for number, run in enumerate(runs, start=1):
                        target = workbook.create_sheet("Result " + str(number))
                        result = run.get("result") or {"columns": [], "rows": []}
                        columns = [c["name"] for c in result["columns"]]
                        _append_excel(target, columns)
                        for row in result["rows"]:
                            row_start = target.max_row + 1
                            _append_excel(
                                target,
                                [
                                    str(row.get(c)) if row.get(c) is not None else None
                                    for c in columns
                                ],
                            )
                            for column_index, column in enumerate(result["columns"], start=1):
                                value = row.get(column["name"])
                                numeric_type = str(column.get("type", "")).upper()
                                if value is None or not numeric_type.startswith(("DECIMAL", "NUMERIC", "INTEGER", "BIGINT", "SMALLINT", "HUGEINT", "DOUBLE", "FLOAT")):
                                    continue
                                from decimal import InvalidOperation

                                try:
                                    amount_value = Decimal(str(value))
                                except InvalidOperation:
                                    continue
                                cell = target.cell(row_start, column_index)
                                if amount_value.is_finite() and survives_a_cell(amount_value):
                                    put_number(cell, value)
                                else:
                                    cell.comment = Comment("超过 Excel 可安全保留的数值精度，按精确文本保存。", "Foundry")
                        evidence = workbook.create_sheet("Evidence " + str(number))
                        for key in [
                            "id",
                            "engine",
                            "sql",
                            "code",
                            "stdout",
                            "stderr",
                            "outputs",
                            "parameters",
                            "bindings",
                            "input_hashes",
                            "source_hashes",
                            "aggregate_plan",
                            "output_hash",
                            "execution_status",
                            "reproducibility_status",
                            "assumptions",
                        ]:
                            _append_excel(
                                evidence,
                                [
                                    key,
                                    json.dumps(run.get(key), ensure_ascii=False)
                                    if isinstance(run.get(key), (list, dict))
                                    else str(run.get(key)),
                                ],
                            )
                        if run.get("engine") == "structured_aggregate":
                            _append_excel(evidence, ["provenance", json.dumps(result.get("provenance", {}), ensure_ascii=False)])
                            for section, label in (("detail_rows", "Sources "), ("excluded_detail_rows", "Excluded ")):
                                source_sheet = workbook.create_sheet(label + str(number))
                                fields = ["result_key", "included", "exclusion_reason", "source", "measure_values"]
                                _append_excel(source_sheet, fields)
                                for detail in result.get(section, []):
                                    _append_excel(source_sheet, [
                                        json.dumps(detail.get(key), ensure_ascii=False)
                                        if isinstance(detail.get(key), (dict, list)) else detail.get(key)
                                        for key in fields
                                    ])
                    # Keep text literal, including identifiers and amounts that
                    # exceed Excel precision. Safe typed amounts stay numeric.
                    for sheet in workbook:
                        for row in sheet:
                            for cell in row:
                                if isinstance(cell.value, str):
                                    cell.data_type = "s"
                    output = io.BytesIO()
                    workbook.save(output)
                    data = output.getvalue()
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self._inside(
                    path.with_name("." + uuid.uuid4().hex + ".tmp")
                )
                try:
                    temporary.write_bytes(data)
                    temporary.replace(path)
                    manifest = _new(
                        self.task,
                        draft_id=draft_id,
                        format=format,
                        sha256=_hash_bytes(data),
                        content_hash=draft["content_hash"],
                        content_mode=projection["content_mode"],
                        projection_hash=projection["projection_hash"],
                    )
                    manifest["_integrity_hash"] = _hash(manifest)
                    write_json_atomic(manifest_path, manifest)
                finally:
                    temporary.unlink(missing_ok=True)
            digest = _hash_bytes(path.read_bytes())
        return {
            "task_id": self.task.id,
            "draft_id": draft_id,
            "format": format,
            "path": str(path.resolve()),
            "sha256": digest,
            "content_hash": draft["content_hash"],
            "content_mode": projection["content_mode"],
            "projection_hash": projection["projection_hash"],
            "publication_status": draft["publication_status"],
        }

    def save_method(self, analysis_id: str, name: str) -> dict:
        analysis = self.get_analysis(analysis_id)
        if analysis.get("engine") in {"python", "shell", "structured_aggregate"}:
            raise FoundryError(
                "non-SQL revisions can be rerun; saving a reusable method currently requires a SQL analysis"
            )
        _safe_text(name, "method name", required=True, maximum=200)
        # Values in WHERE clauses are data too. Replace SQL string literals with
        # caller-supplied parameters and omit original question/values/assumptions.
        sql, parameter_contract = method_template(
            analysis["sql"], analysis.get("parameter_metadata", [])
        )
        contracts = {
            alias: {
                "schema": self.read_dataset(dataset_id)["schema"],
                "grain": self.read_dataset(dataset_id)["metadata"].get("grain", []),
            }
            for alias, dataset_id in analysis["bindings"].items()
        }
        record = _new(
            self.task,
            name=name,
            source_task_id=self.task.id,
            sql=sql,
            input_contracts=contracts,
            relationships=analysis["relationships"],
            metrics=analysis["metrics"],
            parameter_contract=parameter_contract,
            parameter_metadata=[
                entry["metadata"] for entry in parameter_contract if "metadata" in entry
            ],
            parameter_policy_version=1,
            parameters_required=any(
                entry["role"] != "formula_constant" for entry in parameter_contract
            ),
            parameter_note="Supply new values by canonical parameter key. Only declared formula constants have defaults; original business values, business defaults and choice lists are not retained.",
            method_kind="financial-analysis",
            max_rows=analysis["max_rows"],
            timeout_seconds=analysis["timeout_seconds"],
        )
        return self._write(self._object_path("methods", record["id"]), record)

    def apply_method(
        self,
        method_id: str,
        bindings: dict,
        *,
        question: str | None = None,
        parameters: Any = None,
    ) -> dict:
        method = self._get_method(method_id)
        if not isinstance(bindings, dict) or set(bindings) != set(
            method["input_contracts"]
        ):
            raise FoundryError("method bindings must match its input aliases")
        for alias, dataset_id in bindings.items():
            data = self.read_dataset(dataset_id)
            columns = {c["name"]: c["type"] for c in data["schema"]}
            for expected in method["input_contracts"][alias]["schema"]:
                actual = columns.get(expected["name"])
                if actual is None or (
                    expected["type"].startswith("DECIMAL")
                    != actual.startswith("DECIMAL")
                ):
                    raise FoundryError(
                        f"method input {alias} is missing compatible column {expected['name']}"
                    )
        return self.save_analysis(
            {
                "question": question or method["name"],
                "sql": method["sql"],
                "bindings": bindings,
                "parameters": method_parameters(method, parameters),
                "parameter_metadata": method.get("parameter_metadata", []),
                "relationships": method["relationships"],
                "metrics": method["metrics"],
                "method_id": method_id,
                "max_rows": method["max_rows"],
                "timeout_seconds": method["timeout_seconds"],
            }
        )

    def run_script(
        self,
        spec: dict,
        *,
        session_id: str | None = None,
        context_revision: int | None = None,
        cancel_check=None,
        analysis_id: str | None = None,
    ) -> dict:
        """Broker explicit snapshots to one isolated workspace and archive outputs.

        A job may pass a cancellation callback and frozen call context. The
        caller validates authorization before dispatch; this service validates
        ownership/hashes again and never silently rebinds inputs during a run.
        """
        from foundry.runner import run_script
        from foundry.finance_requirement_semantics import capture_requirements
        requirements_snapshot = capture_requirements(self)

        if not isinstance(spec, dict):
            raise FoundryError("script spec must be an object")
        code = _safe_text(
            spec.get("code"), "script code", required=True, maximum=256 * 1024
        )
        language = spec.get("language", "python")
        if language not in {"python", "shell"}:
            raise FoundryError("script language must be python or shell")
        bindings = spec.get("bindings") or {}
        if not isinstance(bindings, dict) or len(bindings) > 32:
            raise FoundryError("script bindings must be a map of at most 32 snapshots")
        if any(
            not isinstance(alias, str) or not ALIAS.fullmatch(alias)
            for alias in bindings
        ):
            raise FoundryError("script binding aliases must be simple identifiers")
        if len({alias.casefold() for alias in bindings}) != len(bindings):
            raise FoundryError("script aliases must be unique")
        datasets = {
            alias: self.read_dataset(dataset_id)
            for alias, dataset_id in bindings.items()
        }
        assumptions = spec.get("assumptions", [])
        if not isinstance(assumptions, list):
            raise FoundryError("script assumptions must be an array")
        result_file = _script_result_path(spec.get("result_file"))
        timeout = spec.get("timeout_seconds", 30)
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float, Decimal))
            or not 0 < timeout <= 300
        ):
            raise FoundryError("script timeout_seconds must be between 0 and 300")
        timeout = float(timeout)
        requirements_id = _requirements_id(spec.get("requirements_id"))
        if requirements_id:
            self._get("requirements", requirements_id)
        default_result_role = "business" if result_file else "activity"
        result_role = _result_role(spec.get("result_role"), default=default_result_role)
        scope = _scope_metadata(spec.get("scope"))
        revision = _new(
            self.task,
            question=spec.get("question", "脚本分析"),
            engine=language,
            code=code,
            sql=None,
            bindings=bindings,
            parameters=[],
            assumptions=assumptions,
            result_file=result_file,
            parent_id=None,
            requirements_id=requirements_id,
            result_role=result_role,
            scope=scope,
            timeout_seconds=timeout,
            relationships=[],
            metrics=[],
            grain=[],
            missing_inputs=[],
        )
        if analysis_id:
            revision = self.get_analysis(analysis_id)
            requirements_id = revision.get("requirements_id")
            result_role = revision.get("result_role", "business")
            scope = revision.get("scope", {})
        else:
            self._write(self._object_path("revisions", revision["id"]), revision)
        run_id = uuid.uuid4().hex
        workspace = self._inside(self.root / "run_workspaces" / run_id)
        inputs = self._inside(workspace / "inputs")
        inputs.mkdir(parents=True, exist_ok=False)
        for alias, dataset in datasets.items():
            # Numeric JSON fields are strings intentionally; scripts can convert
            # them with Decimal and have schema/metadata alongside the rows.
            (inputs / (alias + ".json")).write_bytes(_bytes(dataset))
            canonical = self._inside(
                self.root / "datasets" / dataset["id"] / dataset["source_file"]
            )
            (
                inputs / (alias + ".source" + Path(dataset["source_file"]).suffix)
            ).write_bytes(canonical.read_bytes())
        options = {"language": language, "timeout": timeout}
        if cancel_check is not None:
            options["cancel_check"] = cancel_check
        execution = run_script(workspace, code, **options)
        succeeded = execution["status"] == "succeeded"
        outputs = []
        output_root = self._inside(self.root / "run_outputs" / run_id)
        for item in execution.get("outputs", []):
            relative = Path(item["path"])
            if relative.is_absolute() or ".." in relative.parts:
                raise FoundryError("runner output escapes its run workspace")
            source = self._inside(Path(execution["workspace"]) / relative)
            if (
                source.is_symlink()
                or not source.is_file()
                or source.stat().st_nlink != 1
            ):
                raise FoundryError("runner output must be a regular nonlinked file")
            data = source.read_bytes()
            if _hash_bytes(data) != item["sha256"]:
                raise FoundryError("runner output integrity check failed")
            destination = self._inside(output_root / relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as handle:
                handle.write(data)
            outputs.append(
                {**item, "artifact_path": str(destination.relative_to(self.root))}
            )
        result = _empty_script_result()
        result_error = None
        if succeeded and result_file:
            try:
                item = next(
                    (item for item in outputs if item["path"] == result_file),
                    None,
                )
                if item is None:
                    raise FoundryError(
                        "script result_file is not in this run output manifest"
                    )
                archived = self._inside(output_root / result_file)
                data = archived.read_bytes()
                if _hash_bytes(data) != item["sha256"]:
                    raise FoundryError("script result_file integrity check failed")
                parsed = parse_source(data, Path(result_file).suffix.casefold(), {})
                if parsed.get("kind") != "table":
                    raise FoundryError("script result_file must be a CSV or JSON table")
                row_count = parsed["row_count"]
                rows = parsed["rows"][:SCRIPT_RESULT_PREVIEW_ROWS]
                result = {
                    "columns": parsed["schema"],
                    "rows": rows,
                    "row_count": row_count,
                    "truncated": row_count > len(rows),
                    "result_source": {
                        "path": result_file,
                        "sha256": item["sha256"],
                        "format": Path(result_file).suffix.lstrip(".").casefold(),
                        "basis": "script_output",
                        "reproducibility_status": "unverified",
                    },
                }
            except FoundryError as exc:
                result_error = str(exc)
                succeeded = False
        output_hash = (
            _hash(
                {
                    "stdout": execution.get("stdout", ""),
                    "outputs": [
                        {k: v for k, v in item.items() if k != "artifact_path"}
                        for item in outputs
                    ],
                    "result": result,
                }
            )
            if succeeded
            else None
        )
        requirements_snapshot = {
            **requirements_snapshot,
            "requirements_id": requirements_id or requirements_snapshot.get("requirements_id"),
        }
        record = _new(
            self.task,
            analysis_id=revision["id"],
            **requirements_snapshot,
            result_role=result_role,
            scope=scope,
            session_id=session_id,
            context_revision=context_revision,
            engine=language,
            code=code,
            sql=None,
            parameters=[],
            bindings=bindings,
            input_hashes={
                alias: dataset["data_hash"] for alias, dataset in datasets.items()
            },
            source_hashes={
                alias: dataset["source_hash"] for alias, dataset in datasets.items()
            },
            code_hash=_hash_bytes(code.encode("utf8")),
            environment=execution.get("environment", {}),
            execution_status="succeeded" if succeeded else "failed",
            runner_status=execution["status"],
            reproducibility_status="unverified",
            review_status="unreviewed",
            publication_status="draft",
            output_hash=output_hash,
            stdout=execution.get("stdout", ""),
            stderr=execution.get("stderr", ""),
            exit_code=execution.get("exit_code"),
            outputs=outputs,
            assumptions=assumptions,
            missing_inputs=[],
            result=result,
            warnings=[
                "Script outputs are retained with code and inputs; reproducibility has not been verified."
            ],
        )
        record["id"] = run_id
        if not succeeded:
            record["error"] = (
                result_error or execution.get("stderr") or execution["status"]
            )
            record["error_code"] = (
                "result_file_invalid" if result_error else execution["status"]
            )
        return self._write(self._object_path("runs", run_id), record)

    def output_path(self, run_id: str, output: str) -> dict:
        """Resolve a recorded artifact name; never accept a renderer host path."""
        run = self.get_run(run_id)
        if not isinstance(output, str):
            raise FoundryError("output must be a recorded artifact name")
        item = next(
            (item for item in run.get("outputs", []) if item["path"] == output), None
        )
        if item is None:
            raise FoundryError("output is not in this run manifest")
        path = self._inside(self.root / item["artifact_path"])
        return {
            "task_id": self.task.id,
            "run_id": run_id,
            "output": output,
            "path": str(path.resolve()),
            "sha256": item["sha256"],
            "size": item["size"],
        }
