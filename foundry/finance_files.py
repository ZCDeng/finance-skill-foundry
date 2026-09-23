from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from foundry.analysis import AnalysisStore, _assert_id, _hash, _new
from foundry.errors import FoundryError
from foundry.fsutil import write_json_atomic
from foundry.locking import exclusive
from foundry.task import sha256_bytes
from foundry.workbook_bindings import (
    apply_output_patch,
    create_binding_contract,
    inspect_workbook,
    preview_output_patch,
    read_input,
)

COLLECTIONS = {"workbook_bindings", "workbook_patches", "workbook_outputs"}


class FinanceFiles:
    """Task-scoped workbook file collaboration over authorized XLSX snapshots."""

    def __init__(self, task, *, snapshot_ids: list[str] | set[str] | None = None):
        self.task = task
        self.analysis = AnalysisStore(task)
        self.allowed = None if snapshot_ids is None else set(snapshot_ids)

    def _path(self, kind: str, object_id: str) -> Path:
        if kind not in COLLECTIONS:
            raise FoundryError("unknown finance file collection")
        return self.analysis._inside(
            self.analysis.root / "finance" / kind / f"{_assert_id(object_id)}.json"
        )

    def _read(self, kind: str, object_id: str) -> dict[str, Any]:
        record = self.analysis._read(self._path(kind, object_id))
        dataset_id = record.get("dataset_id")
        if isinstance(dataset_id, str):
            self._authorize_dataset(dataset_id)
        return record

    def _write(self, kind: str, **fields: Any) -> dict[str, Any]:
        record = _new(self.task, domain=f"foundry.finance_files.{kind}.v1", **fields)
        return self.analysis._write(self._path(kind, record["id"]), record)

    def _authorize_dataset(self, dataset_id: str) -> dict[str, Any]:
        _assert_id(dataset_id)
        if self.allowed is not None and dataset_id not in self.allowed:
            raise FoundryError("finance file snapshot is outside this session context")
        dataset = self.analysis.read_dataset(dataset_id)
        if dataset.get("source_file") != "source.xlsx":
            raise FoundryError("finance file bindings require an XLSX snapshot")
        return dataset

    def _source_path(self, dataset_id: str) -> tuple[dict[str, Any], Path]:
        dataset = self._authorize_dataset(dataset_id)
        source = self.analysis._inside(
            self.analysis.root / "datasets" / dataset_id / dataset["source_file"]
        )
        if not source.is_file() or sha256_bytes(source.read_bytes()) != dataset["source_hash"]:
            raise FoundryError("dataset source workbook integrity check failed")
        return dataset, source

    def _binding(self, binding_id: str) -> dict[str, Any]:
        return self._read("workbook_bindings", binding_id)

    def _patch(self, patch_id: str) -> dict[str, Any]:
        patch = self._read("workbook_patches", patch_id)
        self._binding(patch["binding_id"])
        return patch

    def inspect(self, spec: dict[str, Any]) -> dict[str, Any]:
        dataset_id = str(spec.get("dataset_id") or "")
        dataset, source = self._source_path(dataset_id)
        inspection = inspect_workbook(source)
        return {
            "dataset_id": dataset["id"],
            "source_hash": dataset["source_hash"],
            "source_name": dataset["source_name"],
            **inspection,
        }

    def bind(self, spec: dict[str, Any]) -> dict[str, Any]:
        dataset_id = str(spec.get("dataset_id") or "")
        dataset, source = self._source_path(dataset_id)
        parent = self._binding(spec["parent_id"]) if spec.get("parent_id") else {}
        role = spec.get("role", parent.get("role", "input"))
        writable = bool(spec.get("writable", parent.get("writable", False)))
        header = bool(spec.get("header", parent.get("header", True)))
        source_spec = spec.get("source", parent.get("source"))
        fields = spec.get("fields", parent.get("fields"))
        if not isinstance(source_spec, dict) or not isinstance(fields, list):
            raise FoundryError("workbook binding requires source and fields")
        contract = create_binding_contract(
            source,
            source_spec,
            fields,
            role=role,
            writable=writable,
            header=header,
        )
        return self._write(
            "workbook_bindings",
            dataset_id=dataset["id"],
            source_hash=dataset["source_hash"],
            source_name=dataset["source_name"],
            source=source_spec,
            fields=contract["fields"],
            role=role,
            writable=writable,
            header=header,
            parent_id=parent.get("id"),
            contract=contract,
        )

    def read(self, spec: dict[str, Any]) -> dict[str, Any]:
        binding = self._binding(str(spec.get("binding_id") or ""))
        dataset_id = str(spec.get("dataset_id") or binding["dataset_id"])
        dataset, source = self._source_path(dataset_id)
        result = read_input(source, binding["contract"])
        return {
            "binding_id": binding["id"],
            "dataset_id": dataset["id"],
            "source_hash": dataset["source_hash"],
            **result,
        }

    def range_preview(self, spec: dict[str, Any]) -> dict[str, Any]:
        from foundry.workbook_preview import preview_workbook_range

        dataset_id = str(spec.get("dataset_id") or "")
        dataset, source = self._source_path(dataset_id)
        sheet = str(spec.get("sheet") or "").strip()
        if not sheet:
            raise FoundryError("workbook range preview requires a sheet")
        range_ref = spec.get("range")
        if range_ref is not None and not isinstance(range_ref, str):
            raise FoundryError("workbook range preview range must be text")
        return preview_workbook_range(
            source,
            dataset_id=dataset["id"],
            source_hash=dataset["source_hash"],
            source_name=dataset["source_name"],
            sheet_name=sheet,
            range_ref=range_ref,
        )

    def _verify_run_writes(
        self,
        run_id: str | None,
        writes: list[dict[str, Any]],
        dataset_id: str,
    ) -> list[dict[str, Any]]:
        if not run_id:
            return [
                {
                    "write_index": index,
                    "status": "manager_write_unverified",
                    "reason": "no run_id supplied",
                }
                for index, _ in enumerate(writes)
            ]
        run = self.analysis.get_run(run_id)
        run_bindings = run.get("bindings") or {}
        if dataset_id not in run_bindings.values():
            raise FoundryError("workbook target snapshot is outside run bindings")
        if self.allowed is not None and not set(run_bindings.values()) <= self.allowed:
            raise FoundryError("run bindings are outside this session context")
        rows = run.get("result", {}).get("rows", [])
        verification = []
        for index, write in enumerate(writes):
            if "result_row" not in write or "result_column" not in write:
                verification.append(
                    {
                        "write_index": index,
                        "status": "manager_write_unverified",
                        "reason": "write does not reference a run result cell",
                    }
                )
                continue
            row_index = write["result_row"]
            column = write["result_column"]
            if (
                isinstance(row_index, bool)
                or not isinstance(row_index, int)
                or not 0 <= row_index < len(rows)
                or not isinstance(column, str)
                or column not in rows[row_index]
            ):
                raise FoundryError("write references a result cell outside the run")
            actual = rows[row_index][column]
            expected = write.get("value")
            if str(actual) != str(expected):
                raise FoundryError("write value differs from referenced run result")
            verification.append(
                {
                    "write_index": index,
                    "status": "matches_run",
                    "run_id": run["id"],
                    "result_row": row_index,
                    "result_column": column,
                    "value": expected,
                }
            )
        return verification

    def preview(self, spec: dict[str, Any]) -> dict[str, Any]:
        binding = self._binding(str(spec.get("binding_id") or ""))
        dataset_id = str(spec.get("dataset_id") or binding["dataset_id"])
        dataset, source = self._source_path(dataset_id)
        writes = spec.get("writes")
        if not isinstance(writes, list) or not all(isinstance(write, dict) for write in writes):
            raise FoundryError("workbook preview requires write objects")
        run_id = spec.get("run_id")
        if run_id is not None:
            _assert_id(str(run_id))
        patch = preview_output_patch(
            source,
            binding["contract"],
            writes,
            baseline_hashes=binding["contract"]["baseline_hashes"],
        )
        verification = self._verify_run_writes(str(run_id) if run_id else None, writes, dataset["id"])
        record = self._write(
            "workbook_patches",
            binding_id=binding["id"],
            dataset_id=dataset["id"],
            source_hash=dataset["source_hash"],
            binding_source_hash=binding["source_hash"],
            run_id=str(run_id) if run_id else None,
            writes=writes,
            patch=patch,
            verification=verification,
        )
        return {**record, "patch_id": record["id"]}

    def apply(self, spec: dict[str, Any]) -> dict[str, Any]:
        patch_record = self._patch(str(spec.get("patch_id") or ""))
        resolutions = spec.get("resolutions") or {}
        if not isinstance(resolutions, dict):
            raise FoundryError("workbook patch resolutions must be an object")
        dataset, source = self._source_path(patch_record["dataset_id"])
        if dataset["source_hash"] != patch_record["source_hash"]:
            raise FoundryError("workbook source changed since saved patch")
        output_id = uuid.uuid4().hex
        relative = Path("finance") / "workbook_outputs" / "files" / f"{output_id}.xlsx"
        output_path = self.analysis._inside(self.analysis.root / relative)
        record_path = self._path("workbook_outputs", output_id)
        with exclusive(self.task.lock_path, timeout=10):
            if record_path.exists() or output_path.exists():
                raise FoundryError("workbook output already exists")
            result = apply_output_patch(source, output_path, patch_record["patch"], resolutions)
            data = output_path.read_bytes()
            digest = sha256_bytes(data)
            if digest != result["sha256"]:
                raise FoundryError("workbook output hash changed before recording")
            record = _new(
                self.task,
                domain="foundry.finance_files.workbook_outputs.v1",
                id=output_id,
                patch_id=patch_record["id"],
                binding_id=patch_record["binding_id"],
                dataset_id=dataset["id"],
                source_hash=dataset["source_hash"],
                filename=output_path.name,
                path=str(output_path),
                artifact_path=str(relative),
                sha256=digest,
                mode=result["mode"],
                applied=result["applied"],
                kept=result["kept"],
                diagnostics=result.get("diagnostics", []),
                verification=patch_record.get("verification", []),
            )
            record["seq"] = self.analysis._next_seq()
            record["_integrity_hash"] = _hash(record)
            write_json_atomic(record_path, record)
        return record
