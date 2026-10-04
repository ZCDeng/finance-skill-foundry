from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from foundry.analysis import AnalysisStore, _assert_id, _hash, _new
from foundry.analysis_data import archived_numeric_parser
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

COLLECTIONS = {
    "workbook_bindings",
    "workbook_patches",
    "workbook_outputs",
    "rollforward_plans",
    "rollforward_runs",
}


class FinanceFiles:
    """Task-scoped workbook file collaboration over authorized XLSX snapshots."""

    def __init__(
        self,
        task,
        *,
        snapshot_ids: list[str] | set[str] | None = None,
        session_id: str | None = None,
        actor: str | None = None,
    ):
        from foundry.structure_records import resolve_source

        self.task = task
        self.analysis = AnalysisStore(task)
        self.allowed = None if snapshot_ids is None else set(snapshot_ids)
        self.session_id = session_id
        # Stamped by the call layer; an unstamped call is the assistant.
        self.actor = resolve_source(actor)

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
            numeric_parser=archived_numeric_parser(dataset, source.read_bytes()),
        )

    def health(self, spec: dict[str, Any]) -> dict[str, Any]:
        """Formula health hints for a snapshot filed before import ran them.

        Read-only: the archived record is not rewritten, and nothing is stored.
        """
        from foundry.workbook_health import check_workbook

        dataset_id = str(spec.get("dataset_id") or "")
        dataset, source = self._source_path(dataset_id)
        data = source.read_bytes()
        if sha256_bytes(data) != dataset["source_hash"]:
            raise FoundryError("dataset source workbook integrity check failed")
        return {"dataset_id": dataset["id"], "source_hash": dataset["source_hash"], **check_workbook(data)}

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

    # ------------------------------------------------------------------
    # 滚动到下月: last month's workbook, this month's figures, a new copy.

    def _manager_only(self, action: str) -> None:
        from foundry.structure_records import MANAGER

        if self.actor != MANAGER:
            raise FoundryError(f"only the manager can {action}")

    def _refuse_child_session(self, action: str) -> None:
        if not self.session_id:
            return
        session = next((row for row in self.task.sessions() if row["session_id"] == self.session_id), None)
        if session and session.get("parent_session_id"):
            raise FoundryError(f"child sessions cannot {action}")

    def _widen_session(self, snapshot_ids: list[str]) -> None:
        """Keep a narrowed caller able to read the copy it just made."""
        if self.allowed is not None:
            self.allowed.update(snapshot_ids)
        if self.session_id:
            self.task.update_session_context(
                self.session_id,
                snapshot_ids=list(dict.fromkeys([*(self.allowed or []), *snapshot_ids])),
            )

    def _public_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        from foundry.workbook_rollforward import change_log

        return {
            "schema_version": 1,
            "plan_id": plan["id"],
            "dataset_id": plan["dataset_id"],
            "source_hash": plan["source_hash"],
            "dataset_name": plan["dataset_name"],
            "period": plan["period"],
            "workbook_supported": plan["workbook_supported"],
            "unsupported_features": plan["unsupported_features"],
            "sheet_pattern": plan["sheet_pattern"],
            "rows": plan["rows"],
            "counts": plan["counts"],
            "title_hints": plan["title_hints"],
            "change_log": change_log(
                plan["rows"], period=plan["period"], workbook=plan["dataset_name"], workbook_supported=plan["workbook_supported"]
            ),
        }

    def rollforward_preview(self, spec: dict[str, Any]) -> dict[str, Any]:
        """Classify every mapping against last month's workbook and file the plan; nothing is written."""
        import warnings

        from foundry.workbook_bindings import _unsupported_features, open_workbook_bytes
        from foundry.workbook_rollforward import (
            counts,
            extension_losses,
            normalize_mappings,
            period_of,
            plan_rows,
            sheet_pattern,
            title_hints,
        )

        if not isinstance(spec, dict):
            raise FoundryError("rollforward spec must be an object")
        dataset, source = self._source_path(str(spec.get("dataset_id") or ""))
        if spec.get("source_hash") != dataset["source_hash"]:
            raise FoundryError("rollforward workbook source_hash does not match the snapshot")
        period = period_of(spec.get("period"))
        mappings = normalize_mappings(spec.get("mappings"))
        data = source.read_bytes()
        if sha256_bytes(data) != dataset["source_hash"]:
            raise FoundryError("dataset source workbook integrity check failed")
        # openpyxl says what it is about to drop only as a warning while loading.
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            book = open_workbook_bytes(data, data_only=False)
        warned = tuple(str(item.message) for item in caught)
        features = sorted({*_unsupported_features(source), *extension_losses(data, warned)})
        sources = _MappingSources(self)
        try:
            rows = plan_rows(book, data, archived_numeric_parser(dataset, data), mappings, sources)
            hints = title_hints(book, rows, period)
            sheet_names = list(book.sheetnames)
        finally:
            book.close()
            sources.close()
        plan = self._write(
            "rollforward_plans",
            dataset_id=dataset["id"],
            source_hash=dataset["source_hash"],
            source_name=dataset["source_name"],
            dataset_name=dataset["name"],
            period=period,
            sheet_names=sheet_names,
            sheet_pattern=sheet_pattern(sheet_names),
            workbook_supported=not features,
            unsupported_features=features,
            mappings=mappings,
            rows=rows,
            counts=counts(rows),
            title_hints=hints,
        )
        return self._public_plan(plan)

    def _reverify_sources(self, plan: dict[str, Any]) -> None:
        """Every source still reads as it did in the preview.

        Not only the cells about to be written: a blocked row's figure goes into
        the change log as what to type by hand, so it must not be stale either.
        """
        from foundry.workbook_rollforward import SourceUnreadable, rendered

        sources = _MappingSources(self)
        try:
            for row in plan["rows"]:
                source = plan["mappings"][row["index"]]["source"]
                if source["kind"] == "value":
                    continue
                try:
                    now = rendered(sources(source)[0])[0]
                except SourceUnreadable:
                    now = None
                if now != row["new_value"]:
                    raise FoundryError("rollforward source changed since preview; preview again")
        finally:
            sources.close()

    def _filed_copy(self, plan_id: str) -> dict[str, Any] | None:
        """The snapshot an apply of this plan registered, if one did."""
        for row in self.analysis.state()["datasets"]:
            if ((row.get("metadata") or {}).get("rollforward") or {}).get("plan_id") == plan_id:
                return row
        return None

    def rollforward_apply(self, spec: dict[str, Any]) -> dict[str, Any]:
        """Write the previewed cells into a new copy and file it as this task's snapshot. Manager only."""
        import shutil

        from foundry.structure_records import MANAGER
        from foundry.workbook_rollforward import (
            BLOCKED,
            UNCHANGED,
            WRITE,
            change_log,
            output_filename,
            output_name,
            write_copy,
        )

        self._manager_only("apply a workbook roll-forward")
        self._refuse_child_session("apply a workbook roll-forward")
        if not isinstance(spec, dict):
            raise FoundryError("rollforward spec must be an object")
        plan = self._read("rollforward_plans", str(spec.get("plan_id") or ""))
        # One plan, one copy: the run record shares the plan's id, so a second
        # apply finds it filed and the immutable write refuses a race.
        record_path = self._path("rollforward_runs", plan["id"])
        if record_path.exists():
            raise FoundryError("rollforward plan was already applied; preview again for a new copy")
        if not plan["workbook_supported"]:
            raise FoundryError(
                "rollforward workbook has parts a copy would lose ("
                + ", ".join(plan["unsupported_features"])
                + "); no copy was made"
            )
        writes = [row for row in plan["rows"] if row["status"] == WRITE]
        if not writes:
            raise FoundryError("rollforward plan has no cells to write")
        dataset, source = self._source_path(plan["dataset_id"])
        data = source.read_bytes()
        if dataset["source_hash"] != plan["source_hash"] or sha256_bytes(data) != plan["source_hash"]:
            raise FoundryError("rollforward workbook changed since preview; preview again")
        self._reverify_sources(plan)
        staging = self.analysis._inside(self.analysis.root / ".rollforward-staging" / plan["id"])
        try:
            staging.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            raise FoundryError("rollforward plan is already being applied") from None
        # The staging folder is the claim on this plan. It is held until the run
        # record is filed, so a second apply cannot slip in between the copy
        # being registered and the record that says it was.
        try:
            # A copy filed by an earlier apply of this plan that failed before its
            # record was written is taken up again, not filed a second time.
            output = self._filed_copy(plan["id"])
            if output is None:
                path = self.analysis._inside(staging / output_filename(dataset["source_name"], plan["period"]))
                written = write_copy(data, path, plan["rows"])
                digest = sha256_bytes(path.read_bytes())
                # Not under the task lock: add_dataset takes it. No structure proposal
                # either: the copy's formulas have no cached results until Excel saves it.
                output = self.analysis.add_dataset(
                    path,
                    name=output_name(dataset["name"], plan["period"]),
                    metadata={
                        "mode": "workbook",
                        "period": plan["period"],
                        "rollforward": {
                            "plan_id": plan["id"],
                            "source_dataset_id": dataset["id"],
                            "source_hash": dataset["source_hash"],
                            "formula_cache_cleared": written["formula_cache_cleared"],
                        },
                    },
                    allow_duplicate=True,
                )
                if output["source_hash"] != digest:
                    raise FoundryError("rollforward copy changed before it was filed")
            else:
                digest = output["source_hash"]
                written = {"formula_cache_cleared": bool(output["metadata"]["rollforward"].get("formula_cache_cleared"))}
            self._widen_session([output["id"]])
            record = _new(
                self.task,
                domain="foundry.finance_files.rollforward_runs.v1",
                id=plan["id"],
                plan_id=plan["id"],
                dataset_id=dataset["id"],
                source_dataset_id=dataset["id"],
                source_hash=dataset["source_hash"],
                output_dataset_id=output["id"],
                output_name=output["name"],
                output_sha256=digest,
                period=plan["period"],
                written=writes,
                blocked=[row for row in plan["rows"] if row["status"] == BLOCKED],
                unchanged=[row for row in plan["rows"] if row["status"] == UNCHANGED],
                counts=plan["counts"],
                formula_cache_cleared=written["formula_cache_cleared"],
                applied_by=MANAGER,
            )
            record = self.analysis._write(record_path, record)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
            try:
                staging.parent.rmdir()
            except OSError:
                pass  # another apply is still staging its copy
        return {
            **record,
            "run_id": record["id"],
            "change_log": change_log(
                plan["rows"], period=plan["period"], workbook=dataset["name"], copy=output["name"]
            ),
        }

    def rollforward_export(self, spec: dict[str, Any]) -> dict[str, Any]:
        """Save the filed copy where the manager chose, so she can open it in Excel. Manager only.

        The archived copy itself is never handed to Excel: saving it there would
        change a snapshot this task has hashed. The destination comes from the
        desktop's save dialog, never from a session, and the bytes written are
        the ones just checked against the run record.
        """
        import os

        self._manager_only("export a roll-forward copy")
        if self.session_id:
            raise FoundryError("rollforward export requires the task editor")
        if not isinstance(spec, dict):
            raise FoundryError("rollforward spec must be an object")
        run = self._read("rollforward_runs", str(spec.get("run_id") or ""))
        destination = spec.get("destination")
        if not isinstance(destination, str) or not destination.strip():
            raise FoundryError("rollforward export needs a destination chosen in the save dialog")
        target = Path(destination)
        if not target.is_absolute() or target.suffix.lower() != ".xlsx":
            raise FoundryError("rollforward export destination must be an absolute .xlsx path")
        if target.resolve().is_relative_to(Path(self.task.store.var_root).resolve()):
            raise FoundryError("rollforward export destination cannot be inside the store")
        if not target.parent.is_dir():
            raise FoundryError("rollforward export destination folder does not exist")
        if target.is_dir():
            raise FoundryError("rollforward export destination is a folder")
        dataset, source = self._source_path(run["output_dataset_id"])
        data = source.read_bytes()
        if dataset["source_hash"] != run["output_sha256"] or sha256_bytes(data) != run["output_sha256"]:
            raise FoundryError("rollforward copy integrity check failed")
        partial = target.with_name(f".{target.name}.{uuid.uuid4().hex}.part")
        try:
            with open(partial, "xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(partial, target)
        except OSError:
            # Most often the file of that name is open in Excel. The path stays out of the message.
            raise FoundryError("rollforward export could not save the file") from None
        finally:
            partial.unlink(missing_ok=True)
        return {
            "schema_version": 1,
            "run_id": run["id"],
            "output_dataset_id": dataset["id"],
            "filename": target.name,
            "sha256": run["output_sha256"],
        }

    def rollforward_templates(self, spec: dict[str, Any]) -> dict[str, Any]:
        """Saved mappings, only those whose sheets match the chosen workbook when one is named."""
        from foundry.finance_controls import workbook_sheets
        from foundry.workbook_rollforward import RollforwardTemplates, matching_sheet, public_template, sheet_pattern

        spec = spec if isinstance(spec, dict) else {}
        pattern, current = None, None
        if spec.get("dataset_id"):
            _, source = self._source_path(str(spec["dataset_id"]))
            current = workbook_sheets(source.read_bytes())
            pattern = sheet_pattern(current)
        templates = []
        for record in RollforwardTemplates(self.task.store.var_root).list():
            if pattern is not None and record.get("sheet_pattern") != pattern:
                continue
            template = public_template(record)
            if current is not None:
                # Offered because the names match with digits masked; fill in this
                # month's names, or every target would point at last month's sheet.
                template["mappings"] = [
                    {**mapping, "target": {**mapping["target"], "sheet": matching_sheet(mapping["target"]["sheet"], record.get("sheet_names"), current)}}
                    for mapping in template["mappings"]
                ]
            templates.append(template)
        return {"schema_version": 1, "sheet_pattern": pattern, "templates": templates}

    def rollforward_template_save(self, spec: dict[str, Any]) -> dict[str, Any]:
        """Keep a previewed mapping for next month, without this month's snapshots. Manager only."""
        from foundry.workbook_rollforward import RollforwardTemplates, public_template, template_mappings

        self._manager_only("save a roll-forward template")
        if not isinstance(spec, dict):
            raise FoundryError("rollforward spec must be an object")
        plan = self._read("rollforward_plans", str(spec.get("plan_id") or ""))
        name = spec.get("name")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80 or any(ch in name for ch in "\r\n\t"):
            raise FoundryError("rollforward template name must be one line of 1 to 80 characters")
        record = RollforwardTemplates(self.task.store.var_root).create(
            name=name.strip(),
            sheet_pattern=plan["sheet_pattern"],
            sheet_count=len(plan["sheet_names"]),
            # Only to find each target's sheet by position next month.
            sheet_names=plan["sheet_names"],
            mappings=template_mappings(plan["rows"], plan["mappings"]),
        )
        return public_template(record)


class _MappingSources:
    """Reads mapping sources for one preview or apply, each workbook and sheet once."""

    def __init__(self, files: FinanceFiles):
        from foundry.finance_controls import superseded_snapshots

        self.files = files
        analysis = files.analysis
        # The published snapshots, as AnalysisStore.state() lists them, without
        # reading every run and draft in the task to get there.
        root = analysis._inside(analysis.root / "datasets")
        rows = [
            record
            for path in (root.glob("*/meta.json") if root.exists() else [])
            if analysis._dataset_published(record := analysis._read(path))
        ]
        self.published = {row["id"]: row for row in rows}
        self.superseded = superseded_snapshots(files.task, rows)
        self.books: dict[str, Any] = {}
        self.sheets: dict[tuple[str, str], Any] = {}

    def close(self) -> None:
        for entry in self.books.values():
            if not isinstance(entry, Exception):
                entry[1].close()

    def __call__(self, source: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
        from foundry.workbook_rollforward import SourceUnreadable, read_manager_value

        if source["kind"] == "dataset":
            reader, described = self._dataset, {**source, "name": ""}
        elif source["kind"] == "run":
            reader, described = self._run, dict(source)
        else:
            reader, described = (lambda _source, _described: read_manager_value(source["manager_value"])), dict(source)
        try:
            return reader(source, described), described
        except SourceUnreadable as exc:
            exc.described = described
            raise

    def _dataset(self, source: dict[str, Any], described: dict[str, Any]) -> Any:
        from foundry.analysis import ID
        from foundry.workbook_rollforward import (
            SourceUnreadable,
            missing_source_sheet,
            range_bounds,
            read_workbook_source,
            sheet_cells,
        )

        dataset_id = source["dataset_id"]
        if not dataset_id:
            raise SourceUnreadable("还没有选择来源资料")
        if ID.fullmatch(dataset_id) and self.files.allowed is not None and dataset_id not in self.files.allowed:
            raise FoundryError("finance file snapshot is outside this session context")
        row = self.published.get(dataset_id)
        if row is None:
            raise SourceUnreadable("来源资料不在当前任务里")
        described["name"] = row.get("name") or ""
        if dataset_id in self.superseded:
            raise SourceUnreadable("来源资料已被同名的新资料取代，请改选新版本")
        if source["source_hash"] != row.get("source_hash"):
            raise SourceUnreadable("来源资料与选择时的版本不一致，请重新选择")
        if row.get("source_file") != "source.xlsx":
            raise SourceUnreadable("来源资料不是 Excel 工作簿")
        bounds = range_bounds(source["range"])
        if not source["sheet"] or bounds is None:
            raise SourceUnreadable("来源区域要写成「工作表!B5」或「工作表!B5:B20」")
        dataset, value_book, parser, data = self._workbook(dataset_id)
        if source["sheet"] not in value_book.sheetnames:
            raise SourceUnreadable(missing_source_sheet(source["sheet"], source["range"], list(value_book.sheetnames)))
        if source["sheet"] not in {worksheet.title for worksheet in value_book.worksheets}:
            raise SourceUnreadable(f"来源工作簿里的「{source['sheet']}」是图表工作表，没有单元格可读")
        key = (dataset_id, source["sheet"])
        if key not in self.sheets:
            self.sheets[key] = sheet_cells(data, source["sheet"], parser)
        return read_workbook_source(value_book, self.sheets[key], source["sheet"], bounds)

    def _workbook(self, dataset_id: str) -> tuple[dict[str, Any], Any, str, bytes]:
        from foundry.workbook_bindings import open_workbook_bytes
        from foundry.workbook_rollforward import SourceUnreadable

        if dataset_id not in self.books:
            try:
                dataset = self.files.analysis.read_dataset(dataset_id)
                path = self.files.analysis._inside(
                    self.files.analysis.root / "datasets" / dataset_id / dataset["source_file"]
                )
                data = path.read_bytes()
                if sha256_bytes(data) != dataset["source_hash"]:
                    raise FoundryError("dataset source workbook integrity check failed")
                book = open_workbook_bytes(data, data_only=True)
                self.books[dataset_id] = (dataset, book, archived_numeric_parser(dataset, data), data)
            except (FoundryError, OSError) as exc:
                self.books[dataset_id] = exc
        entry = self.books[dataset_id]
        if isinstance(entry, Exception):
            raise SourceUnreadable("来源资料快照读不出或已损坏")
        return entry

    def _run(self, source: dict[str, Any], described: dict[str, Any]) -> Any:
        from foundry.analysis import ID
        from foundry.workbook_rollforward import SourceUnreadable, read_run_source

        run_id = source["run_id"]
        if not run_id:
            raise SourceUnreadable("还没有选择计算结果")
        if not ID.fullmatch(run_id):
            raise SourceUnreadable("计算结果不存在")
        try:
            run = self.files.analysis.get_run(run_id)
        except FoundryError:
            raise SourceUnreadable("计算结果不存在或已损坏") from None
        bindings = {value for value in (run.get("bindings") or {}).values() if isinstance(value, str)}
        if self.files.allowed is not None and not bindings <= self.files.allowed:
            raise FoundryError("run bindings are outside this session context")
        described["created_at"] = run.get("created_at")
        if bindings & self.superseded:
            raise SourceUnreadable("这次计算用的资料已被同名的新资料取代，请重新计算")
        return read_run_source(run, source["row"], source["column"])
