"""Refreshable source batches for task-owned analysis snapshots.

This module is deliberately transport-neutral. A real ERP adapter supplies a
small pull-page interface and keeps credentials inside that transport object;
the records persisted here contain only product/version/capability metadata,
source scope, checkpoints, immutable source batches, and AnalysisStore dataset
snapshots.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
import uuid

from foundry.analysis import AnalysisStore, _bytes, _hash, _hash_bytes, _new
from foundry.analysis_data import (
    MAX_ROWS,
    MAX_SOURCE_BYTES,
    XLSX_ORIGINAL_DECIMAL,
    parse_source,
)
from foundry.errors import FoundryError
from foundry.fsutil import write_json_atomic
from foundry.locking import exclusive
from foundry.task import Task, now_iso


BUSINESS_KEY_FIELDS = (
    "source_system",
    "ledger_id",
    "organization_id",
    "document_id",
    "line_id",
)
SECRET_KEY_FRAGMENTS = (
    "api_key",
    "authorization",
    "credential",
    "password",
    "secret",
    "token",
)
STATE_ACTIVE = "active"
STATE_DELETED = "deleted"
STATE_VOID = "void"
MAX_SOURCE_PAGES = 1000
FILE_IDENTITY_POLICIES = {"business_key", "snapshot_only"}


class SourceRefreshError(FoundryError):
    pass


class SourceAuthError(SourceRefreshError):
    pass


class SourceRateLimitError(SourceRefreshError):
    pass


class SourceTransientError(SourceRefreshError):
    pass


@dataclass(frozen=True)
class SourceCapabilities:
    pagination: bool = True
    incremental_updates: bool = False
    deletions: bool = False
    voids: bool = False
    full_period_reconciliation: bool = True

    def as_record(self) -> dict[str, Any]:
        return {
            "pagination": self.pagination,
            "incremental_updates": self.incremental_updates,
            "deletions": self.deletions,
            "voids": self.voids,
            "full_period_reconciliation": self.full_period_reconciliation,
        }


@dataclass(frozen=True)
class SourceDescription:
    product: str
    version: str
    capabilities: SourceCapabilities = field(default_factory=SourceCapabilities)

    def as_record(self) -> dict[str, Any]:
        _reject_secrets({"product": self.product, "version": self.version})
        return {
            "product": _required_text(self.product, "source product"),
            "version": _required_text(self.version, "source version"),
            "capabilities": self.capabilities.as_record(),
        }


@dataclass(frozen=True)
class SourceScope:
    source_id: str
    tenant_id: str
    ledger_id: str
    organization_id: str
    period: str
    currency: str
    cutoff_at: str
    calendar: str = "standard"
    mode: str = "full_period"

    def as_record(self) -> dict[str, Any]:
        if self.mode not in {"full_period", "incremental"}:
            raise SourceRefreshError("source scope mode must be full_period or incremental")
        record = {
            "source_id": _required_text(self.source_id, "source id"),
            "tenant_id": _required_text(self.tenant_id, "tenant id"),
            "ledger_id": _required_text(self.ledger_id, "ledger id"),
            "organization_id": _required_text(self.organization_id, "organization id"),
            "period": _required_text(self.period, "period"),
            "currency": _required_text(self.currency, "currency"),
            "cutoff_at": _required_text(self.cutoff_at, "cutoff"),
            "calendar": _required_text(self.calendar, "calendar"),
            "mode": self.mode,
        }
        _reject_secrets(record)
        return record


@dataclass(frozen=True)
class SourcePage:
    sequence: int
    rows: tuple[dict[str, Any], ...] | list[dict[str, Any]]
    cursor: str | None = None
    next_cursor: str | None = None
    checkpoint: dict[str, Any] | None = None
    is_last: bool = False


class SourceTransport(Protocol):
    def describe(self) -> SourceDescription:
        ...

    def discover(self, scope: SourceScope) -> dict[str, Any]:
        ...

    def pull_page(
        self,
        scope: SourceScope,
        *,
        cursor: str | None,
        checkpoint: dict[str, Any] | None,
    ) -> SourcePage:
        ...


class SourceRefreshService:
    def __init__(self, task: Task, *, allowed: set[str] | None = None):
        """``allowed`` is a session's snapshot ceiling (FinanceStore.allowed): a refresh it files compares with,
        dedupes against and replaces only batches whose snapshot it may read, so it files what it would have
        filed had the others never been published. The manager (None) reads every batch."""
        self.task = task
        self.allowed = None if allowed is None else set(allowed)
        self.store = AnalysisStore(task)
        self.root = self.store._inside(self.store.root / "source_batches")
        self.checkpoint_root = self.store._inside(self.store.root / "source_checkpoints")

    def discover(self, transport: SourceTransport, scope: SourceScope) -> dict[str, Any]:
        description = transport.describe().as_record()
        scope_record = scope.as_record()
        discovered = transport.discover(scope)
        if not isinstance(discovered, dict):
            raise SourceRefreshError("source discovery must return an object")
        _reject_secrets(discovered)
        return {
            "schema_version": 1,
            "source": description,
            "scope": scope_record,
            "discovered": discovered,
            "capability_statement": _capability_statement(
                description["capabilities"], scope_record
            ),
        }

    def refresh_file(
        self,
        path: Path,
        *,
        scope: SourceScope,
        product: str = "file",
        version: str = "export",
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
        file_identity_policy: str = "business_key",
    ) -> dict[str, Any]:
        if file_identity_policy not in FILE_IDENTITY_POLICIES:
            raise SourceRefreshError(
                "file_identity_policy must be business_key or snapshot_only"
            )
        source_path = Path(path)
        scope_record = scope.as_record()
        description = SourceDescription(
            product=product,
            version=version,
            capabilities=SourceCapabilities(
                pagination=False,
                full_period_reconciliation=True,
            ),
        ).as_record()
        try:
            if not source_path.is_file() or source_path.stat().st_size > MAX_SOURCE_BYTES:
                raise SourceRefreshError("source file must be at most 32 MiB")
            data = source_path.read_bytes()
        except OSError as exc:
            raise SourceRefreshError(f"cannot read source file: {exc}") from exc
        suffix = source_path.suffix.lower()
        parsed = parse_source(data, suffix, metadata or {})
        if parsed["kind"] != "table":
            raise SourceRefreshError("source refresh requires a tabular file")
        rows = (
            [
                _normalize_source_row(row, scope_record, ordinal=index)
                for index, row in enumerate(parsed["rows"], start=1)
            ]
            if file_identity_policy == "business_key"
            else _normalize_snapshot_rows(parsed["rows"], scope_record)
        )
        literal_rows = (
            _literal_xlsx_rows(data, metadata or {}, scope_record)
            if suffix == ".xlsx" and file_identity_policy == "business_key"
            else None
        )
        source_hash = _hash_bytes(data)
        return self._publish_rows(
            rows,
            description=description,
            scope_record=scope_record,
            source_kind="file",
            source_name=source_path.name,
            source_hash=source_hash,
            source_bytes=len(data),
            dataset_name=name or source_path.stem,
            checkpoint=None,
            identity_policy=file_identity_policy,
            literal_rows=literal_rows,
        )

    def refresh_transport(
        self,
        transport: SourceTransport,
        scope: SourceScope,
        *,
        name: str | None = None,
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        if max_attempts < 1 or max_attempts > 5:
            raise SourceRefreshError("max_attempts must be between 1 and 5")
        description = transport.describe().as_record()
        scope_record = scope.as_record()
        checkpoint = self._read_checkpoint(scope_record)
        pages = self._pull_pages(
            transport,
            scope,
            checkpoint=checkpoint,
            max_attempts=max_attempts,
        )
        rows = [
            _normalize_source_row(row, scope_record, ordinal=index)
            for index, row in enumerate(
                [row for page in pages for row in page.rows],
                start=1,
            )
        ]
        source_hash = _hash(
            {
                "pages": [
                    {
                        "sequence": page.sequence,
                        "cursor": page.cursor,
                        "next_cursor": page.next_cursor,
                        "rows": list(page.rows),
                    }
                    for page in pages
                ]
            }
        )
        return self._publish_rows(
            rows,
            description=description,
            scope_record=scope_record,
            source_kind="transport",
            source_name=f"{description['product']} {description['version']}",
            source_hash=source_hash,
            source_bytes=len(_bytes(rows)),
            dataset_name=name or f"{description['product']} {scope.period}",
            checkpoint=pages[-1].checkpoint if pages else checkpoint,
            identity_policy="business_key",
        )

    def _readable(self, row: dict[str, Any]) -> bool:
        return self.allowed is None or row.get("dataset_id") in self.allowed

    def batches(self) -> list[dict[str, Any]]:
        return sorted(
            [self.store._read(path) for path in self.root.glob("*.json")]
            if self.root.exists()
            else [],
            key=lambda row: (row.get("seq", 0), row["created_at"], row["id"]),
        )

    def batches_in_view(self) -> list[dict[str, Any]]:
        """Every batch as a reader whose snapshot ceiling is ``allowed`` reads it; the manager (None) reads them as
        stored.

        A refresh compares with the latest batch of its source its filer may read (_latest_published_for_identity).
        One a session filed before that rule, or one filed by a reader that may read more (the manager's P, H, S read
        by a session granted P and S), can name a prior this reader may not read. It reads with the prior it would
        have named had no batch outside the reader been published: the nearest snapshot back along the batches'
        priors that the reader may read, or none, under the integrity hash of the record so read. Its counts, its
        changes and its snapshot's rows stay as filed: a business_key refresh merged its upload with the prior's rows
        (incremental) or wrote off those it lacked (full_period) without keeping the two apart, so it reads with
        counts taken against a prior it no longer names. A batch whose prior the reader may read, and a duplicate,
        read as stored.
        """
        rows = self.batches()
        if self.allowed is None:
            return rows
        filed = {row["dataset_id"]: row for row in rows if row.get("dataset_id") and row.get("duplicate_of") is None}
        shown = []
        for row in rows:
            prior = row.get("prior_snapshot_id")
            if row.get("dataset_id") and row.get("duplicate_of") is None and prior and prior not in self.allowed:
                seen = set()
                while prior and prior not in self.allowed and prior not in seen:
                    seen.add(prior)
                    prior = (filed.get(prior) or {}).get("prior_snapshot_id")
                # Keyed as the stored record reads back, so the view reads as one.
                row = {**row, "prior_snapshot_id": prior if prior in self.allowed else None}
                row["_integrity_hash"] = _hash({key: value for key, value in row.items() if key != "_integrity_hash"})
            shown.append(row)
        return shown

    def _pull_pages(
        self,
        transport: SourceTransport,
        scope: SourceScope,
        *,
        checkpoint: dict[str, Any] | None,
        max_attempts: int,
    ) -> list[SourcePage]:
        pages: list[SourcePage] = []
        cursor = None
        expected_sequence = 1
        seen_cursors: set[str | None] = {None}
        total_rows = 0
        while True:
            if expected_sequence > MAX_SOURCE_PAGES:
                raise SourceRefreshError("source pagination exceeded the page limit")
            page = self._pull_page_with_retry(
                transport,
                scope,
                cursor=cursor,
                checkpoint=checkpoint,
                max_attempts=max_attempts,
            )
            if page.sequence != expected_sequence:
                raise SourceRefreshError(
                    f"source page sequence {page.sequence} arrived while {expected_sequence} was expected"
                )
            if page.cursor != cursor:
                raise SourceRefreshError("source page cursor does not match the requested cursor")
            if not isinstance(page.rows, (list, tuple)) or not all(
                isinstance(row, dict) for row in page.rows
            ):
                raise SourceRefreshError("source page rows must be objects")
            total_rows += len(page.rows)
            if total_rows > MAX_ROWS:
                raise SourceRefreshError("source refresh exceeds the row limit")
            pages.append(page)
            if page.is_last:
                break
            if not page.next_cursor or page.next_cursor == cursor:
                raise SourceRefreshError("source pagination did not advance")
            if page.next_cursor in seen_cursors:
                raise SourceRefreshError("source pagination cursor cycle detected")
            cursor = page.next_cursor
            seen_cursors.add(cursor)
            expected_sequence += 1
        return pages

    def _pull_page_with_retry(
        self,
        transport: SourceTransport,
        scope: SourceScope,
        *,
        cursor: str | None,
        checkpoint: dict[str, Any] | None,
        max_attempts: int,
    ) -> SourcePage:
        attempt = 0
        while True:
            attempt += 1
            try:
                return transport.pull_page(scope, cursor=cursor, checkpoint=checkpoint)
            except SourceAuthError:
                raise
            except (
                SourceRateLimitError,
                SourceTransientError,
                TimeoutError,
                ConnectionError,
            ) as exc:
                if attempt >= max_attempts:
                    raise SourceRefreshError("source pull failed after bounded retries") from exc

    def _latest_published(self, scope_record: dict[str, Any]) -> dict[str, Any] | None:
        return self._latest_published_for_identity(_scope_identity(scope_record))

    def _latest_published_for_identity(
        self, source_identity: dict[str, Any]
    ) -> dict[str, Any] | None:
        candidates = [
            row
            for row in self.batches()
            if row.get("publication_status") == "published"
            and row.get("duplicate_of") is None
            and _record_identity(row) == source_identity
            and row.get("dataset_id")
            and self._readable(row)
        ]
        return candidates[-1] if candidates else None

    def _prior_rows(self, prior: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not prior or not prior.get("dataset_id"):
            return []
        return self.store.read_dataset(prior["dataset_id"])["rows"]

    def _duplicate_for_source(
        self, scope_record: dict[str, Any], source_kind: str, source_hash: str
    ) -> dict[str, Any] | None:
        return self._duplicate_for_source_identity(
            _scope_identity(scope_record), source_kind, source_hash
        )

    def _duplicate_for_source_identity(
        self, source_identity: dict[str, Any], source_kind: str, source_hash: str
    ) -> dict[str, Any] | None:
        candidates = [
            row
            for row in self.batches()
            if row.get("publication_status") == "published"
            and row.get("duplicate_of") is None
            and _record_identity(row) == source_identity
            and row.get("source_kind") == source_kind
            and row.get("source_hash") == source_hash
            and row.get("dataset_id")
            and self._readable(row)
        ]
        return candidates[-1] if candidates else None

    def _duplicate_for_data(
        self, scope_record: dict[str, Any], data_hash: str
    ) -> dict[str, Any] | None:
        return self._duplicate_for_data_identity(_scope_identity(scope_record), data_hash)

    def _duplicate_for_data_identity(
        self, source_identity: dict[str, Any], data_hash: str
    ) -> dict[str, Any] | None:
        candidates = [
            row
            for row in self.batches()
            if row.get("publication_status") == "published"
            and row.get("duplicate_of") is None
            and _record_identity(row) == source_identity
            and row.get("data_hash") == data_hash
            and row.get("dataset_id")
            and self._readable(row)
        ]
        return candidates[-1] if candidates else None

    def _record_duplicate(
        self,
        prior: dict[str, Any],
        *,
        description: dict[str, Any],
        scope_record: dict[str, Any],
        source_kind: str,
        source_name: str,
        source_hash: str,
        checkpoint: dict[str, Any] | None,
    ) -> dict[str, Any]:
        record = _new(
            self.task,
            source=description,
            scope=scope_record,
            source_kind=source_kind,
            source_name=source_name,
            source_hash=source_hash,
            duplicate_of=prior["id"],
            prior_snapshot_id=prior["dataset_id"],
            dataset_id=None,
            row_count=prior["row_count"],
            business_key_count=prior["business_key_count"],
            duplicate_row_count=0,
            change_counts={"inserted": 0, "updated": 0, "deleted": 0, "voided": 0, "unchanged": prior["business_key_count"]},
            checkpoint=checkpoint,
            publication_status="published",
            published_at=now_iso(),
            capability_statement=_capability_statement(
                description["capabilities"], scope_record
            ),
        )
        with exclusive(self.task.lock_path, timeout=10):
            record["seq"] = self.store._next_seq()
            record["_integrity_hash"] = _hash(record)
            write_json_atomic(self._batch_path(record["id"]), record)
        return record

    def _publish_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        description: dict[str, Any],
        scope_record: dict[str, Any],
        source_kind: str,
        source_name: str,
        source_hash: str,
        source_bytes: int,
        dataset_name: str,
        checkpoint: dict[str, Any] | None,
        identity_policy: str,
        literal_rows: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        _reject_secrets(rows)
        _reject_secrets(checkpoint or {})
        with exclusive(self.task.lock_path, timeout=10):
            source_identity = _scope_identity(scope_record)
            prior = self._latest_published_for_identity(source_identity)
            batch_input = (
                _prepare_snapshot_batch(
                    rows,
                    source_hash=source_hash,
                    prior=prior,
                )
                if identity_policy == "snapshot_only"
                else _prepare_batch(
                    rows,
                    description=description,
                    scope_record=scope_record,
                    prior=prior,
                    prior_rows=self._prior_rows(prior),
                    literal_rows=literal_rows,
                )
            )
            duplicate = (
                self._duplicate_for_source_identity(
                    source_identity, source_kind, source_hash
                )
                if source_kind == "file"
                else self._duplicate_for_data_identity(
                    source_identity, batch_input["data_hash"]
                )
            )
            if duplicate:
                return self._record_duplicate_locked(
                    duplicate,
                    description=description,
                    scope_record=scope_record,
                    source_kind=source_kind,
                    source_name=source_name,
                    source_hash=source_hash,
                    checkpoint=checkpoint,
                )
            batch_id = uuid.uuid4().hex
            dataset = None
            try:
                dataset = self._write_dataset_snapshot(
                    batch_input,
                    batch_id=batch_id,
                    name=dataset_name,
                    source_name=source_name,
                    original_source_hash=source_hash,
                    source_bytes=source_bytes,
                    scope_record=scope_record,
                    identity_policy=identity_policy,
                )
                record = _new(
                    self.task,
                    id=batch_id,
                    source=description,
                    scope=scope_record,
                    source_identity=source_identity,
                    source_kind=source_kind,
                    identity_policy=identity_policy,
                    source_name=source_name,
                    source_hash=source_hash,
                    source_bytes=source_bytes,
                    data_hash=batch_input["data_hash"],
                    duplicate_of=None,
                    prior_snapshot_id=batch_input.get("prior_snapshot_id"),
                    dataset_id=dataset["id"],
                    row_count=len(batch_input["rows"]),
                    business_key_count=batch_input["business_key_count"],
                    duplicate_row_count=batch_input["duplicate_row_count"],
                    change_counts=batch_input["change_counts"],
                    changes=batch_input["changes"],
                    # Says the counts above could not be computed against the
                    # prior batch, rather than leaving them to be read as zeros.
                    identity_rebaselined=bool(batch_input.get("identity_rebaselined")),
                    checkpoint=checkpoint,
                    publication_status="published",
                    published_at=now_iso(),
                    capability_statement=_capability_statement(
                        description["capabilities"], scope_record
                    ),
                )
                self._write_batch_record(record)
            except Exception:
                if dataset and dataset.get("id"):
                    shutil.rmtree(
                        self.store._inside(
                            self.store.root / "datasets" / dataset["id"]
                        ),
                        ignore_errors=True,
                    )
                raise
        return record

    def _record_duplicate_locked(
        self,
        prior: dict[str, Any],
        *,
        description: dict[str, Any],
        scope_record: dict[str, Any],
        source_kind: str,
        source_name: str,
        source_hash: str,
        checkpoint: dict[str, Any] | None,
    ) -> dict[str, Any]:
        record = _new(
            self.task,
            source=description,
            scope=scope_record,
            source_identity=_scope_identity(scope_record),
            source_kind=source_kind,
            source_name=source_name,
            source_hash=source_hash,
            duplicate_of=prior["id"],
            prior_snapshot_id=prior["dataset_id"],
            dataset_id=None,
            row_count=prior["row_count"],
            business_key_count=prior["business_key_count"],
            duplicate_row_count=0,
            change_counts={
                "inserted": 0,
                "updated": 0,
                "deleted": 0,
                "voided": 0,
                "unchanged": prior["business_key_count"],
            },
            checkpoint=checkpoint,
            publication_status="published",
            published_at=now_iso(),
            capability_statement=_capability_statement(
                description["capabilities"], scope_record
            ),
        )
        self._write_batch_record(record)
        return record

    def _write_batch_record(self, record: dict[str, Any]) -> None:
        record["seq"] = self.store._next_seq()
        record["_integrity_hash"] = _hash(record)
        write_json_atomic(self._batch_path(record["id"]), record)

    def _write_dataset_snapshot(
        self,
        batch_input: dict[str, Any],
        *,
        batch_id: str,
        name: str,
        source_name: str,
        original_source_hash: str,
        source_bytes: int,
        scope_record: dict[str, Any],
        identity_policy: str,
    ) -> dict[str, Any]:
        encoded_source = _bytes({"rows": batch_input["rows"]})
        grain = [] if identity_policy == "snapshot_only" else list(BUSINESS_KEY_FIELDS)
        parsed = parse_source(
            encoded_source,
            ".json",
            {
                "grain": grain,
                "source_refresh": {
                    "source_batch_id": batch_id,
                    "scope": scope_record,
                    "published_at": now_iso(),
                },
            },
        )
        parsed["transformation"]["business_key"] = grain
        parsed["transformation"]["identity_policy"] = identity_policy
        encoded_data = _bytes(parsed)
        record = _new(
            self.task,
            name=name,
            kind=parsed["kind"],
            source_name=source_name,
            source_hash=_hash_bytes(encoded_source),
            source_bytes=source_bytes,
            data_hash=_hash_bytes(encoded_data),
            schema=parsed["schema"],
            row_count=parsed["row_count"],
            metadata={
                "source_refresh": {
                    "source_batch_id": batch_id,
                    "scope": scope_record,
                    "identity_policy": identity_policy,
                    "change_counts": batch_input["change_counts"],
                    "prior_snapshot_id": batch_input.get("prior_snapshot_id"),
                    "original_source_hash": original_source_hash,
                    "publication_gate": "source_batch_published_dataset_match",
                }
            },
            transformation={
                **parsed["transformation"],
                "basis": "source_refresh_batch",
                "business_key": grain,
            },
            source_file="source.json",
        )
        folder = self.store._inside(self.store.root / "datasets" / record["id"])
        folder.mkdir(parents=True, exist_ok=False)
        (folder / record["source_file"]).write_bytes(encoded_source)
        (folder / "data.json").write_bytes(encoded_data)
        record["seq"] = self.store._next_seq()
        record["_integrity_hash"] = _hash(record)
        write_json_atomic(folder / "meta.json", record)
        return record

    def _batch_path(self, batch_id: str) -> Path:
        return self.store._inside(self.root / f"{batch_id}.json")

    def _checkpoint_path(self, scope_record: dict[str, Any]) -> Path:
        return self.store._inside(
            self.checkpoint_root / f"{_hash(_scope_identity(scope_record))}.json"
        )

    def _read_checkpoint(self, scope_record: dict[str, Any]) -> dict[str, Any] | None:
        latest = self._latest_published(scope_record)
        return latest.get("checkpoint") if latest else None

    def _write_checkpoint(self, scope_record: dict[str, Any], checkpoint: dict[str, Any]) -> None:
        record = _new(self.task, scope=scope_record, checkpoint=checkpoint)
        record["seq"] = self.store._next_seq()
        record["_integrity_hash"] = _hash(record)
        write_json_atomic(self._checkpoint_path(scope_record), record)


def snapshots_in_view(store: AnalysisStore, records: list[dict[str, Any]],
                      allowed: set[str] | None, *, cache: dict | None = None) -> list[dict[str, Any]]:
    """Snapshot records as a reader whose snapshot ceiling is ``allowed`` reads them; the manager (None) reads them as
    stored. A refreshed snapshot records its batch's prior (metadata.source_refresh.prior_snapshot_id) and reads with
    the prior its batch reads with (SourceRefreshService.batches_in_view), under the integrity hash of its record
    (meta.json) so read. Its rows and counts stay as filed. ``cache`` as for AnalysisStore.run_in_view, so the drafts
    of the same read list the batches no more."""
    if allowed is None:
        return records
    batches: dict[str, dict[str, Any]] | None = None
    shown = []
    for record in records:
        refresh = (record.get("metadata") or {}).get("source_refresh")
        prior = refresh.get("prior_snapshot_id") if isinstance(refresh, dict) else None
        if not prior or prior in allowed:
            shown.append(record)
            continue
        if batches is None:
            batches = {row["id"]: row for row in store._batches_in_view(allowed, {} if cache is None else cache)}
        batch = batches.get(refresh.get("source_batch_id")) or {}
        # A dataset read carries its rows too: the hash is over the record alone, as it was filed.
        meta = store._read(store._inside(store.root / "datasets" / record["id"] / "meta.json"))
        meta["metadata"] = {**meta["metadata"], "source_refresh": {
            **meta["metadata"]["source_refresh"], "prior_snapshot_id": batch.get("prior_snapshot_id")}}
        meta.pop("_integrity_hash", None)
        shown.append({**record, "metadata": meta["metadata"], "_integrity_hash": _hash(meta)})
    return shown


def _prepare_batch(
    rows: list[dict[str, Any]],
    *,
    description: dict[str, Any],
    scope_record: dict[str, Any],
    prior: dict[str, Any] | None,
    prior_rows: list[dict[str, Any]],
    literal_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    _reject_secrets(rows)
    # A batch published under snapshot_only filed its rows without business
    # keys, so nothing here can be matched against it. Indexing it by a key it
    # never had raised a bare KeyError out of the refresh; diffing against an
    # empty prior would be worse, because it would report a whole unchanged
    # period as newly inserted. The first keyed batch after a snapshot is a new
    # baseline, and the counts say so.
    rebaselined = bool(prior_rows) and any(
        "_source_business_key" not in row for row in prior_rows
    )
    prior_by_key = (
        {}
        if rebaselined
        else {row["_source_business_key"]: row for row in prior_rows}
    )
    literal_by_key = {row["_source_business_key"]: row for row in literal_rows or []}
    deduped: dict[str, dict[str, Any]] = {}
    duplicate_count = 0
    for row in rows:
        key = row["_source_business_key"]
        if key in deduped:
            if _comparable_row(row) == _comparable_row(deduped[key]):
                duplicate_count += 1
                continue
            raise SourceRefreshError(f"conflicting rows for business key {key}")
        deduped[key] = row

    mode = scope_record["mode"]
    capabilities = description["capabilities"]
    final_by_key = dict(prior_by_key) if mode == "incremental" and not rebaselined else {}
    changes: list[dict[str, Any]] = []
    counts = {"inserted": 0, "updated": 0, "deleted": 0, "voided": 0, "unchanged": 0}

    for key, row in deduped.items():
        state = row["_source_row_state"]
        previous = prior_by_key.get(key)
        if state == STATE_DELETED:
            counts["deleted"] += 1
            final_by_key[key] = row
            changes.append(_change("deleted", key, row, previous))
        elif state == STATE_VOID:
            counts["voided"] += 1
            final_by_key[key] = row
            changes.append(_change("voided", key, row, previous))
        elif previous is None:
            counts["inserted"] += 1
            final_by_key[key] = row
            changes.append(_change("inserted", key, row, None))
        elif _comparable_row(previous) not in (
            _comparable_row(row),
            # A batch filed before the shortest-double rule kept each XLSX
            # literal's digits; read that way, the line may be the one it filed.
            _comparable_row(literal_by_key.get(key)),
        ):
            counts["updated"] += 1
            final_by_key[key] = row
            changes.append(_change("updated", key, row, previous))
        else:
            counts["unchanged"] += 1
            final_by_key[key] = row

    if mode == "full_period":
        missing = set(prior_by_key) - set(deduped)
        for key in sorted(missing):
            tombstone = {
                **prior_by_key[key],
                "_source_row_state": STATE_DELETED,
                "_source_deleted_by_reconciliation": True,
            }
            final_by_key[key] = tombstone
            counts["deleted"] += 1
            changes.append(_change("deleted", key, tombstone, prior_by_key[key]))
    elif not capabilities.get("deletions"):
        for row in final_by_key.values():
            row.setdefault(
                "_source_deletion_strategy",
                "period_full_reconciliation_required",
            )

    final_rows = [final_by_key[key] for key in sorted(final_by_key)]
    data_hash = _hash({"rows": final_rows})
    if rebaselined:
        counts = {name: "unknown_identity_change" for name in counts}
        changes = []
    return {
        "rows": final_rows,
        "data_hash": data_hash,
        "business_key_count": len(final_by_key),
        "duplicate_row_count": duplicate_count,
        "change_counts": counts,
        "changes": changes,
        "prior_snapshot_id": prior.get("dataset_id") if prior else None,
        **({"identity_rebaselined": True} if rebaselined else {}),
    }


def _literal_xlsx_rows(
    data: bytes, metadata: dict[str, Any], scope_record: dict[str, Any]
) -> list[dict[str, Any]] | None:
    """The same XLSX export read with each numeric literal's own digits.

    A batch filed before the shortest-double rule stored those digits, so an
    unchanged re-export matches it only when read the same way. The rows filed
    now still use the current rule. When the literal reading cannot be built
    (the old reader refused one of its values), comparison uses the current
    reading alone.
    """
    try:
        parsed = parse_source(data, ".xlsx", metadata, xlsx_numeric_parser=XLSX_ORIGINAL_DECIMAL)
        return [
            _normalize_source_row(row, scope_record, ordinal=index)
            for index, row in enumerate(parsed["rows"], start=1)
        ]
    except FoundryError:
        # A literal spelling can fail a scope check the current reading passes (2026.0799999999999 vs 2026.08).
        return None


def _prepare_snapshot_batch(
    rows: list[dict[str, Any]],
    *,
    source_hash: str,
    prior: dict[str, Any] | None,
) -> dict[str, Any]:
    data_hash = _hash({"rows": rows})
    prior_snapshot_id = prior.get("dataset_id") if prior else None
    return {
        "rows": rows,
        "data_hash": data_hash,
        "business_key_count": 0,
        "duplicate_row_count": 0,
        "change_counts": {
            "inserted": "unknown_snapshot_only",
            "updated": "unknown_snapshot_only",
            "deleted": "unknown_snapshot_only",
            "voided": "unknown_snapshot_only",
            "unchanged": "unknown_snapshot_only",
        },
        "changes": [],
        "prior_snapshot_id": prior_snapshot_id,
        "row_identity": "none",
        "source_hash": source_hash,
    }


def _change(
    kind: str,
    key: str,
    row: dict[str, Any],
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "business_key": key,
        "document_id": row["document_id"],
        "line_id": row["line_id"],
        "previous_hash": _hash(_comparable_row(previous)) if previous else None,
        "current_hash": _hash(_comparable_row(row)),
    }


def _scope_identity(scope_record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: scope_record[key]
        for key in (
            "source_id",
            "tenant_id",
            "ledger_id",
            "organization_id",
            "period",
            "currency",
            "calendar",
        )
    }


def _record_identity(record: dict[str, Any]) -> dict[str, Any]:
    identity = record.get("source_identity")
    if isinstance(identity, dict):
        return identity
    scope = record.get("scope") or {}
    return _scope_identity(scope)


def _normalize_source_row(
    row: dict[str, Any], scope_record: dict[str, Any], *, ordinal: int
) -> dict[str, Any]:
    _reject_secrets(row)
    normalized = {str(key): value for key, value in row.items()}
    _apply_scope_value(
        normalized,
        field="source_system",
        scope_value=scope_record["source_id"],
        aliases=("source",),
    )
    _apply_scope_value(
        normalized,
        field="ledger_id",
        scope_value=scope_record["ledger_id"],
        aliases=("ledger",),
    )
    normalized.setdefault(
        "organization_id",
        normalized.get("organization") or normalized.get("org") or scope_record["organization_id"],
    )
    _apply_scope_value(
        normalized,
        field="organization_id",
        scope_value=scope_record["organization_id"],
        aliases=("organization", "org"),
    )
    _apply_scope_value(
        normalized,
        field="currency",
        scope_value=scope_record["currency"],
        aliases=(),
    )
    if "period" in normalized and str(normalized["period"]) != scope_record["period"]:
        raise SourceRefreshError("source row period does not match refresh scope")
    normalized.setdefault("document_id", normalized.get("doc_id") or normalized.get("doc"))
    normalized.setdefault("line_id", normalized.get("line") or normalized.get("source_line"))
    missing = [field for field in BUSINESS_KEY_FIELDS if normalized.get(field) in {None, ""}]
    if missing:
        raise SourceRefreshError(f"source row missing business key fields: {', '.join(missing)}")
    key_parts = [str(normalized[field]) for field in BUSINESS_KEY_FIELDS]
    normalized["_source_business_key"] = "\x1f".join(key_parts)
    normalized["_source_row_state"] = _row_state(normalized)
    return normalized


def _normalize_snapshot_rows(
    rows: list[dict[str, Any]], scope_record: dict[str, Any]
) -> list[dict[str, Any]]:
    normalized_rows = []
    for row in rows:
        _reject_secrets(row)
        normalized = {str(key): value for key, value in row.items()}
        _validate_optional_scope_value(
            normalized,
            field="source_system",
            scope_value=scope_record["source_id"],
            aliases=("source",),
        )
        _validate_optional_scope_value(
            normalized,
            field="ledger_id",
            scope_value=scope_record["ledger_id"],
            aliases=("ledger",),
        )
        _validate_optional_scope_value(
            normalized,
            field="organization_id",
            scope_value=scope_record["organization_id"],
            aliases=("organization", "org"),
        )
        _validate_optional_scope_value(
            normalized,
            field="currency",
            scope_value=scope_record["currency"],
            aliases=(),
        )
        if "period" in normalized and str(normalized["period"]) != scope_record["period"]:
            raise SourceRefreshError("source row period does not match refresh scope")
        normalized_rows.append(normalized)
    return normalized_rows


def _apply_scope_value(
    row: dict[str, Any],
    *,
    field: str,
    scope_value: str,
    aliases: tuple[str, ...],
) -> None:
    values = [row[key] for key in (field, *aliases) if key in row and row[key] not in {None, ""}]
    if values and any(str(value) != scope_value for value in values):
        raise SourceRefreshError(f"source row {field} does not match refresh scope")
    row[field] = scope_value


def _validate_optional_scope_value(
    row: dict[str, Any],
    *,
    field: str,
    scope_value: str,
    aliases: tuple[str, ...],
) -> None:
    values = [
        row[key]
        for key in (field, *aliases)
        if key in row and row[key] not in {None, ""}
    ]
    if values and any(str(value) != scope_value for value in values):
        raise SourceRefreshError(f"source row {field} does not match refresh scope")


def _row_state(row: dict[str, Any]) -> str:
    status = str(row.get("status") or row.get("state") or "").strip().casefold()
    if row.get("_deleted") is True or status in {"deleted", "delete"}:
        return STATE_DELETED
    if row.get("_void") is True or status in {"void", "voided", "作废"}:
        return STATE_VOID
    return STATE_ACTIVE


def _comparable_row(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}
    ignored = {"_source_deleted_by_reconciliation", "_source_deletion_strategy"}
    return {key: row[key] for key in sorted(row) if key not in ignored}


def _capability_statement(capabilities: dict[str, Any], scope_record: dict[str, Any]) -> dict[str, Any]:
    statement = {
        "product_claim": "adapter-declared",
        "mode": scope_record["mode"],
        "deletion_strategy": "explicit_source_deletes"
        if capabilities.get("deletions")
        else "period_full_reconciliation_required",
        "real_erp_integration": "unverified_without_tenant_control_totals",
    }
    if scope_record["mode"] == "full_period":
        statement["deletion_strategy"] = "full_period_reconciliation"
    return statement


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SourceRefreshError(f"{label} is required")
    return value.strip()


def _reject_secrets(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).casefold()
            if any(fragment in lowered for fragment in SECRET_KEY_FRAGMENTS):
                raise SourceRefreshError("source refresh records must not contain credentials")
            _reject_secrets(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_secrets(item)
