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

ID = re.compile(r"^[0-9a-f]{32}$")
ALIAS = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
KINDS = {"revisions", "runs", "drafts", "methods", "requirements", "evidence_checks", "completions"}
REVIEW = {"unreviewed", "reviewed", "accepted"}
PUBLICATION = {"draft", "archived"}
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
        self, path: Path, *, name: str, metadata: dict | None = None
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
        parsed = parse_source(data, suffix, metadata)
        source_hash = _hash_bytes(data)
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
        sql = _safe_text(spec.get("sql"), "SQL", required=True, maximum=100000)
        bindings = spec.get("bindings") or {}
        if not isinstance(bindings, dict) or not bindings or len(bindings) > 32:
            raise FoundryError("analysis needs 1–32 explicit snapshot bindings")
        if len({str(a).casefold() for a in bindings}) != len(bindings):
            raise FoundryError("binding aliases must be unique (case insensitive)")
        for alias, dataset_id in bindings.items():
            if not isinstance(alias, str) or not ALIAS.fullmatch(alias):
                raise FoundryError(f"invalid dataset alias: {alias}")
            self.read_dataset(dataset_id)
        parent_id = spec.get("parent_id")
        if parent_id:
            self.get_analysis(parent_id)
        parameters = spec.get("parameters") or []
        if not isinstance(parameters, (list, dict)):
            raise FoundryError("SQL parameters must be an array or object")
        parameter_metadata = normalize_parameter_metadata(
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
            question=question,
            sql=sql,
            bindings=bindings,
            parameters=parameters,
            parameter_metadata=parameter_metadata,
            parent_id=parent_id,
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

    def run_analysis(
        self,
        analysis_id: str,
        *,
        session_id: str | None = None,
        context_revision: int | None = None,
    ) -> dict:
        analysis = self.get_analysis(analysis_id)
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
                },
                session_id=session_id,
                context_revision=context_revision,
                analysis_id=analysis_id,
            )
        datasets = {
            alias: self.read_dataset(dataset_id)
            for alias, dataset_id in analysis["bindings"].items()
        }
        environment = {
            "python": platform.python_version(),
            "duckdb": duckdb.__version__,
            "platform": sys.platform,
            "runner": "snapshot-sql-v1",
            "settings": CONFIG,
            "configuration_locked": True,
        }
        code_hash = _hash(
            {"sql": analysis["sql"], "parameters": analysis["parameters"]}
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
                        raise FoundryError(
                            "claim value differs from execution result; save an explicit user_assumption override"
                        )
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
        explanation_check = validate_explanation(
            self,
            {
                "body": body,
                "run_ids": list(runs),
                "fact_ids": fact_ids,
                "claims": claims,
                "materiality": materiality,
            },
        )
        from foundry.finance_requirements import augment_quality, latest_requirements

        current_requirements = latest_requirements(self)
        requirements_id = spec.get("requirements_id", parent.get("requirements_id")) or (current_requirements or {}).get("id")
        explanation_check = augment_quality(self, {
            "body": body, "run_ids": list(runs), "claims": claims,
            "requirements_id": requirements_id,
            "source_read_failures": source_read_failures,
        }, explanation_check)
        record = _new(
            self.task,
            requirements_id=requirements_id,
            materiality=materiality,
            completion_request_key=spec.get("completion_request_key"),
            source_read_failures=source_read_failures,
            evidence_appendix=spec.get("evidence_appendix", parent.get("evidence_appendix", "")),
            title=title,
            body=body,
            **({"body_template": body_template} if body_template is not None else {}),
            run_ids=list(runs),
            fact_ids=fact_ids,
            claims=claims,
            explanation_check=explanation_check,
            quality=explanation_check,
            parent_id=parent.get("id"),
            execution_status="succeeded"
            if runs and all(r["execution_status"] == "succeeded" for r in runs.values())
            else "failed"
            if runs
            else "not_run",
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
                    "run_ids": list(runs),
                    "fact_ids": fact_ids,
                    "claims": claims,
                    "limitations": limitations,
                }
            ),
        )
        return self._write(self._object_path("drafts", record["id"]), record)

    def export_draft(self, draft_id: str, format: str = "md") -> dict:
        draft = self.get_draft(draft_id)
        if format not in {"md", "xlsx"}:
            raise FoundryError("draft export format must be md or xlsx")
        runs = [self.get_run(run_id) for run_id in draft["run_ids"]]
        path = self._inside(self.root / "exports" / (draft_id + "." + format))
        with exclusive(self.task.lock_path, timeout=10):
            self._inside(path)
            manifest_path = self._inside(path.with_suffix(path.suffix + ".meta.json"))
            if path.exists():
                manifest = self._read(manifest_path)
                if (
                    manifest.get("sha256") != _hash_bytes(path.read_bytes())
                    or manifest.get("content_hash") != draft["content_hash"]
                ):
                    raise FoundryError(
                        "export integrity check failed; archived bytes differ from their receipt"
                    )
            else:
                if format == "md":
                    lines = [
                        "# " + draft["title"],
                        "",
                        draft["body"],
                        "",
                        "---",
                        "",
                        f"Version: {draft_id}",
                        f"Status: {draft['publication_status']}; review: {draft['review_status']}",
                        f"Content SHA-256: {draft['content_hash']}",
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
                            run.get("sql") or run.get("code") or "",
                            "```",
                            "Inputs: "
                            + json.dumps(run["input_hashes"], ensure_ascii=False),
                        ]
                    for run in runs:
                        if run.get("engine"):
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
                        [draft["title"]],
                        [draft["body"]],
                        ["Version", draft_id],
                        ["Content SHA-256", draft["content_hash"]],
                        ["Publication", draft["publication_status"]],
                        ["Review", draft["review_status"]],
                        ["Reproducibility", draft["reproducibility_status"]],
                    ]:
                        _append_excel(sheet, row)
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
                                    number = Decimal(str(value))
                                except InvalidOperation:
                                    continue
                                cell = target.cell(row_start, column_index)
                                if number.is_finite() and survives_a_cell(number):
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
            "publication_status": draft["publication_status"],
        }

    def save_method(self, analysis_id: str, name: str) -> dict:
        analysis = self.get_analysis(analysis_id)
        if analysis.get("engine") in {"python", "shell"}:
            raise FoundryError(
                "script revisions can be rerun; saving a reusable method currently requires a SQL analysis"
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
        timeout = spec.get("timeout_seconds", 30)
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float, Decimal))
            or not 0 < timeout <= 300
        ):
            raise FoundryError("script timeout_seconds must be between 0 and 300")
        timeout = float(timeout)
        revision = _new(
            self.task,
            question=spec.get("question", "脚本分析"),
            engine=language,
            code=code,
            sql=None,
            bindings=bindings,
            parameters=[],
            assumptions=assumptions,
            parent_id=None,
            timeout_seconds=timeout,
            relationships=[],
            metrics=[],
            grain=[],
            missing_inputs=[],
        )
        if analysis_id:
            revision = self.get_analysis(analysis_id)
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
        output_hash = (
            _hash(
                {
                    "stdout": execution.get("stdout", ""),
                    "outputs": [
                        {k: v for k, v in item.items() if k != "artifact_path"}
                        for item in outputs
                    ],
                }
            )
            if succeeded
            else None
        )
        record = _new(
            self.task,
            analysis_id=revision["id"],
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
            result={"columns": [], "rows": [], "row_count": 0, "truncated": False},
            warnings=[
                "Script outputs are retained with code and inputs; reproducibility has not been verified."
            ],
        )
        record["id"] = run_id
        if not succeeded:
            record["error"] = execution.get("stderr") or execution["status"]
            record["error_code"] = execution["status"]
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
