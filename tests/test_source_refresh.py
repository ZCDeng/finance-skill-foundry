from __future__ import annotations

import csv
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from foundry.analysis import AnalysisStore
from foundry.errors import FoundryError
from foundry.source_refresh import (
    SourceAuthError,
    SourceCapabilities,
    SourceDescription,
    SourcePage,
    SourceRateLimitError,
    SourceRefreshError,
    SourceRefreshService,
    SourceScope,
)
from foundry.task import TaskStore


def _scope(mode: str = "full_period") -> SourceScope:
    return SourceScope(
        source_id="synthetic-g6",
        tenant_id="tenant-a",
        ledger_id="ledger-a",
        organization_id="org-east",
        period="2026-08",
        currency="CNY",
        cutoff_at="2026-09-05T00:00:00Z",
        mode=mode,
    )


def _scope_with_cutoff(cutoff_at: str, mode: str = "full_period") -> SourceScope:
    return SourceScope(
        source_id="synthetic-g6",
        tenant_id="tenant-a",
        ledger_id="ledger-a",
        organization_id="org-east",
        period="2026-08",
        currency="CNY",
        cutoff_at=cutoff_at,
        mode=mode,
    )


def _task(tmp_path: Path):
    task = TaskStore(tmp_path / "var").create(title="source refresh")
    return task, SourceRefreshService(task), AnalysisStore(task)


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _rows(*amounts: str) -> list[dict[str, str]]:
    return [
        {
            "document_id": "JV-1",
            "line_id": str(index),
            "amount": amount,
            "memo": f"line {index}",
        }
        for index, amount in enumerate(amounts, start=1)
    ]


class FakeTransport:
    def __init__(
        self,
        pages: list[SourcePage],
        *,
        failures: dict[tuple[str | None, int], Exception] | None = None,
        capabilities: SourceCapabilities | None = None,
    ) -> None:
        self.pages = {page.cursor: page for page in pages}
        self.failures = failures or {}
        self.calls: list[str | None] = []
        self.capabilities = capabilities or SourceCapabilities(
            incremental_updates=True,
            deletions=True,
            voids=True,
        )

    def describe(self) -> SourceDescription:
        return SourceDescription("Synthetic ERP", "G6", self.capabilities)

    def discover(self, scope: SourceScope) -> dict:
        return {"ledgers": [scope.ledger_id], "organizations": [scope.organization_id]}

    def pull_page(self, scope: SourceScope, *, cursor: str | None, checkpoint: dict | None) -> SourcePage:
        attempt = sum(1 for call in self.calls if call == cursor) + 1
        self.calls.append(cursor)
        failure = self.failures.get((cursor, attempt))
        if failure:
            raise failure
        return self.pages[cursor]


def test_a16_same_file_duplicate_points_to_prior_snapshot_and_changed_file_is_new_snapshot(tmp_path: Path) -> None:
    task, refresh, store = _task(tmp_path)
    source = tmp_path / "ledger.csv"
    _write_csv(source, _rows("10", "20"))

    first = refresh.refresh_file(source, scope=_scope(), name="ledger")
    assert first["dataset_id"]
    first_dataset = store.read_dataset(first["dataset_id"])
    assert first_dataset["row_count"] == 2
    assert first_dataset["metadata"]["source_refresh"]["source_batch_id"] == first["id"]

    duplicate = refresh.refresh_file(source, scope=_scope(), name="ledger")
    assert duplicate["duplicate_of"] == first["id"]
    assert duplicate["prior_snapshot_id"] == first["dataset_id"]
    assert duplicate["dataset_id"] is None
    assert [row["id"] for row in store.state()["datasets"]] == [first["dataset_id"]]

    analysis = store.save_analysis(
        {
            "question": "sum first snapshot",
            "sql": "SELECT SUM(amount) AS total FROM ledger",
            "bindings": {"ledger": first["dataset_id"]},
        }
    )
    run = store.run_analysis(analysis["id"])
    assert run["bindings"] == {"ledger": first["dataset_id"]}
    assert first["source_hash"]
    assert run["source_hashes"]["ledger"] == store.read_dataset(first["dataset_id"])["source_hash"]

    _write_csv(source, _rows("10", "25"))
    changed = refresh.refresh_file(source, scope=_scope(), name="ledger")
    assert changed["dataset_id"] != first["dataset_id"]
    assert changed["prior_snapshot_id"] == first["dataset_id"]
    assert changed["change_counts"] == {
        "inserted": 0,
        "updated": 1,
        "deleted": 0,
        "voided": 0,
        "unchanged": 1,
    }
    assert store.get_run(run["id"])["bindings"] == {"ledger": first["dataset_id"]}


def test_changed_cutoff_uses_same_stable_source_identity_for_prior_comparison(tmp_path: Path) -> None:
    task, refresh, store = _task(tmp_path)
    source = tmp_path / "ledger.csv"
    _write_csv(source, _rows("10", "20"))
    first = refresh.refresh_file(
        source,
        scope=_scope_with_cutoff("2026-09-05T00:00:00Z"),
        name="ledger",
    )

    _write_csv(source, _rows("10", "25"))
    second = refresh.refresh_file(
        source,
        scope=_scope_with_cutoff("2026-09-06T00:00:00Z"),
        name="ledger",
    )

    assert second["prior_snapshot_id"] == first["dataset_id"]
    assert second["source_identity"] == first["source_identity"]
    assert second["scope"]["cutoff_at"] != first["scope"]["cutoff_at"]
    assert second["change_counts"]["updated"] == 1
    assert store.read_dataset(second["dataset_id"])["row_count"] == 2


def test_simultaneous_same_file_refresh_rechecks_duplicate_under_task_lock(tmp_path: Path) -> None:
    task = TaskStore(tmp_path / "var").create(title="source refresh")
    source = tmp_path / "ledger.csv"
    _write_csv(source, _rows("10", "20"))

    def refresh_once() -> dict:
        return SourceRefreshService(task).refresh_file(source, scope=_scope(), name="ledger")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: refresh_once(), range(2)))

    dataset_results = [row for row in results if row["dataset_id"]]
    duplicate_results = [row for row in results if row["dataset_id"] is None]
    assert len(dataset_results) == 1
    assert len(duplicate_results) == 1
    assert duplicate_results[0]["prior_snapshot_id"] == dataset_results[0]["dataset_id"]
    assert len(AnalysisStore(task).state()["datasets"]) == 1


def test_publish_failure_after_dataset_metadata_cleans_visible_snapshot(tmp_path: Path, monkeypatch) -> None:
    task, refresh, store = _task(tmp_path)
    source = tmp_path / "ledger.csv"
    _write_csv(source, _rows("10"))
    first = refresh.refresh_file(source, scope=_scope(), name="ledger")
    analysis = store.save_analysis(
        {
            "question": "sum first snapshot",
            "sql": "SELECT SUM(amount) AS total FROM ledger",
            "bindings": {"ledger": first["dataset_id"]},
        }
    )
    run = store.run_analysis(analysis["id"])
    _write_csv(source, _rows("20"))

    def fail_batch_write(record: dict) -> None:
        assert [row["id"] for row in store.state()["datasets"]] == [first["dataset_id"]]
        with pytest.raises(FoundryError, match="source batch is not published"):
            store.read_dataset(record["dataset_id"])
        raise SourceRefreshError("interrupted after dataset metadata")

    monkeypatch.setattr(refresh, "_write_batch_record", fail_batch_write)
    with pytest.raises(SourceRefreshError, match="interrupted"):
        refresh.refresh_file(source, scope=_scope(), name="ledger")

    assert [row["id"] for row in refresh.batches()] == [first["id"]]
    assert [row["id"] for row in store.state()["datasets"]] == [first["dataset_id"]]
    assert store.get_run(run["id"])["bindings"] == {"ledger": first["dataset_id"]}


def test_generic_file_snapshot_only_allows_missing_business_ids_and_freezes_old_run(tmp_path: Path) -> None:
    task, refresh, store = _task(tmp_path)
    source = tmp_path / "budget.csv"
    _write_csv(
        source,
        [
            {"account_code": "6001", "department": "sales", "budget": "100"},
            {"account_code": "6401", "department": "ops", "budget": "60"},
        ],
    )

    first = refresh.refresh_file(
        source,
        scope=_scope(),
        name="budget",
        file_identity_policy="snapshot_only",
    )
    dataset = store.read_dataset(first["dataset_id"])
    assert dataset["metadata"]["source_refresh"]["source_batch_id"] == first["id"]
    assert dataset["metadata"]["source_refresh"]["identity_policy"] == "snapshot_only"
    assert first["business_key_count"] == 0
    assert first["change_counts"]["updated"] == "unknown_snapshot_only"
    assert dataset["transformation"]["business_key"] == []

    duplicate = refresh.refresh_file(
        source,
        scope=_scope(),
        name="budget",
        file_identity_policy="snapshot_only",
    )
    assert duplicate["duplicate_of"] == first["id"]
    assert duplicate["dataset_id"] is None
    assert [row["id"] for row in store.state()["datasets"]] == [first["dataset_id"]]

    analysis = store.save_analysis(
        {
            "question": "budget total",
            "sql": "SELECT SUM(budget) AS total FROM budget",
            "bindings": {"budget": first["dataset_id"]},
        }
    )
    run = store.run_analysis(analysis["id"])
    assert run["result"]["rows"][0]["total"] == "160"

    _write_csv(
        source,
        [
            {"account_code": "6001", "department": "sales", "budget": "120"},
            {"account_code": "6401", "department": "ops", "budget": "60"},
        ],
    )
    changed = refresh.refresh_file(
        source,
        scope=_scope(),
        name="budget",
        file_identity_policy="snapshot_only",
    )
    assert changed["dataset_id"] != first["dataset_id"]
    assert changed["prior_snapshot_id"] == first["dataset_id"]
    assert changed["change_counts"]["deleted"] == "unknown_snapshot_only"
    assert store.get_run(run["id"])["bindings"] == {"budget": first["dataset_id"]}


def test_reader_during_batch_write_gap_excludes_and_refuses_marked_dataset(tmp_path: Path, monkeypatch) -> None:
    task, refresh, store = _task(tmp_path)
    source = tmp_path / "ledger.csv"
    _write_csv(source, _rows("10"))
    original_write_batch = refresh._write_batch_record
    observed = {}

    def observe_gap(record: dict) -> None:
        observed["state_during_gap"] = store.state()["datasets"]
        with pytest.raises(FoundryError, match="source batch is not published"):
            store.read_dataset(record["dataset_id"])
        original_write_batch(record)

    monkeypatch.setattr(refresh, "_write_batch_record", observe_gap)
    batch = refresh.refresh_file(source, scope=_scope(), name="ledger")

    assert observed["state_during_gap"] == []
    dataset = store.read_dataset(batch["dataset_id"])
    assert dataset["metadata"]["source_refresh"]["source_batch_id"] == batch["id"]


def test_publish_failure_before_dataset_metadata_leaves_no_visible_batch_or_snapshot(tmp_path: Path, monkeypatch) -> None:
    task, refresh, store = _task(tmp_path)
    source = tmp_path / "ledger.csv"
    _write_csv(source, _rows("10"))

    def fail_dataset_write(*args, **kwargs) -> dict:
        raise SourceRefreshError("interrupted before dataset metadata")

    monkeypatch.setattr(refresh, "_write_dataset_snapshot", fail_dataset_write)
    with pytest.raises(SourceRefreshError, match="interrupted"):
        refresh.refresh_file(source, scope=_scope(), name="ledger")

    assert refresh.batches() == []
    assert store.state()["datasets"] == []


def test_a17_transport_pagination_retries_dedupe_replay_and_failed_attempts_do_not_publish(tmp_path: Path) -> None:
    task, refresh, store = _task(tmp_path)
    pages = [
        SourcePage(
            sequence=1,
            cursor=None,
            next_cursor="p2",
            rows=[
                {"document_id": "JV-1", "line_id": "1", "amount": "10"},
                {"document_id": "JV-1", "line_id": "1", "amount": "10"},
            ],
        ),
        SourcePage(
            sequence=2,
            cursor="p2",
            rows=[{"document_id": "JV-1", "line_id": "2", "amount": "20"}],
            checkpoint={"cursor": "done"},
            is_last=True,
        ),
    ]
    transport = FakeTransport(
        pages,
        failures={(None, 1): SourceRateLimitError("slow down")},
    )

    first = refresh.refresh_transport(transport, _scope(mode="incremental"))
    assert first["duplicate_row_count"] == 1
    assert first["business_key_count"] == 2
    assert len(store.read_dataset(first["dataset_id"])["rows"]) == 2
    assert transport.calls == [None, None, "p2"]

    replay = refresh.refresh_transport(FakeTransport(pages), _scope(mode="incremental"))
    assert replay["duplicate_of"] == first["id"]
    assert replay["prior_snapshot_id"] == first["dataset_id"]
    assert [row["id"] for row in store.state()["datasets"]] == [first["dataset_id"]]

    before_batches = refresh.batches()
    before_datasets = store.state()["datasets"]
    with pytest.raises(SourceRefreshError, match="sequence"):
        refresh.refresh_transport(
            FakeTransport(
                [
                    SourcePage(
                        sequence=2,
                        cursor=None,
                        rows=[{"document_id": "JV-X", "line_id": "1"}],
                        is_last=True,
                    )
                ]
            ),
            _scope(mode="incremental"),
        )
    assert refresh.batches() == before_batches
    assert store.state()["datasets"] == before_datasets

    with pytest.raises(SourceRefreshError, match="bounded retries"):
        refresh.refresh_transport(
            FakeTransport(
                pages,
                failures={
                    ("p2", 1): TimeoutError("timeout"),
                    ("p2", 2): TimeoutError("timeout"),
                    ("p2", 3): TimeoutError("timeout"),
                },
            ),
            _scope(mode="incremental"),
        )
    assert refresh.batches() == before_batches
    assert store.state()["datasets"] == before_datasets

    auth = FakeTransport(pages, failures={(None, 1): SourceAuthError("expired")})
    with pytest.raises(SourceAuthError):
        refresh.refresh_transport(auth, _scope(mode="incremental"))
    assert auth.calls == [None]


def test_pagination_cursor_cycle_is_refused_before_publish(tmp_path: Path) -> None:
    task, refresh, store = _task(tmp_path)
    with pytest.raises(SourceRefreshError, match="cycle"):
        refresh.refresh_transport(
            FakeTransport(
                [
                    SourcePage(sequence=1, cursor=None, next_cursor="a", rows=[]),
                    SourcePage(sequence=2, cursor="a", next_cursor="b", rows=[]),
                    SourcePage(sequence=3, cursor="b", next_cursor="a", rows=[]),
                ]
            ),
            _scope(mode="incremental"),
        )
    assert refresh.batches() == []
    assert store.state()["datasets"] == []


def test_a18_updates_voids_deletes_and_unsupported_incremental_deletion_policy(tmp_path: Path) -> None:
    task, refresh, store = _task(tmp_path)
    first = refresh.refresh_transport(
        FakeTransport(
            [
                SourcePage(
                    sequence=1,
                    cursor=None,
                    rows=[
                        {"document_id": "JV-1", "line_id": "1", "amount": "10", "memo": "old"},
                        {"document_id": "JV-1", "line_id": "2", "amount": "20"},
                    ],
                    is_last=True,
                )
            ]
        ),
        _scope(),
    )
    second = refresh.refresh_transport(
        FakeTransport(
            [
                SourcePage(
                    sequence=1,
                    cursor=None,
                    rows=[
                        {"document_id": "JV-1", "line_id": "1", "amount": "15", "memo": "changed"},
                        {"document_id": "JV-2", "line_id": "1", "amount": "5", "status": "voided"},
                    ],
                    is_last=True,
                )
            ]
        ),
        _scope(),
    )

    assert second["prior_snapshot_id"] == first["dataset_id"]
    assert second["change_counts"] == {
        "inserted": 0,
        "updated": 1,
        "deleted": 1,
        "voided": 1,
        "unchanged": 0,
    }
    rows = store.read_dataset(second["dataset_id"])["rows"]
    states = {(row["document_id"], row["line_id"]): row["_source_row_state"] for row in rows}
    assert states == {("JV-1", "1"): "active", ("JV-1", "2"): "deleted", ("JV-2", "1"): "void"}
    assert any(row.get("_source_deleted_by_reconciliation") == "True" for row in rows)
    assert second["capability_statement"]["real_erp_integration"] == "unverified_without_tenant_control_totals"

    incremental = refresh.refresh_transport(
        FakeTransport(
            [
                SourcePage(
                    sequence=1,
                    cursor=None,
                    rows=[{"document_id": "JV-1", "line_id": "1", "amount": "30"}],
                    is_last=True,
                )
            ],
            capabilities=SourceCapabilities(incremental_updates=True, deletions=False),
        ),
        _scope(mode="incremental"),
    )
    assert incremental["capability_statement"]["deletion_strategy"] == "period_full_reconciliation_required"
    rows = store.read_dataset(incremental["dataset_id"])["rows"]
    assert any(
        row.get("_source_deletion_strategy") == "period_full_reconciliation_required"
        for row in rows
    )


def test_source_refresh_rejects_credentials_in_persisted_scope_rows_and_discovery(tmp_path: Path) -> None:
    task, refresh, store = _task(tmp_path)
    source = tmp_path / "secret.csv"
    _write_csv(
        source,
        [{"document_id": "JV-1", "line_id": "1", "amount": "10", "access_token": "secret"}],
    )

    with pytest.raises(FoundryError, match="credentials"):
        refresh.refresh_file(source, scope=_scope())
    assert refresh.batches() == []
    assert store.state()["datasets"] == []


def test_rows_must_match_scope_and_provide_explicit_business_line_id(tmp_path: Path) -> None:
    task, refresh, store = _task(tmp_path)
    source = tmp_path / "bad.csv"
    _write_csv(
        source,
        [
            {
                "ledger_id": "other-ledger",
                "document_id": "JV-1",
                "line_id": "1",
                "amount": "10",
            }
        ],
    )

    with pytest.raises(SourceRefreshError, match="ledger_id"):
        refresh.refresh_file(source, scope=_scope())

    _write_csv(source, [{"document_id": "JV-1", "amount": "10"}])
    with pytest.raises(SourceRefreshError, match="line_id"):
        refresh.refresh_file(source, scope=_scope())

    with pytest.raises(SourceRefreshError, match="line_id"):
        refresh.refresh_transport(
            FakeTransport(
                [
                    SourcePage(
                        sequence=1,
                        cursor=None,
                        rows=[{"document_id": "JV-1", "amount": "10"}],
                        is_last=True,
                    )
                ]
            ),
            _scope(),
        )

    assert refresh.batches() == []
    assert store.state()["datasets"] == []


def test_switching_a_source_from_snapshot_only_to_business_key_rebaselines(
    tmp_path: Path,
) -> None:
    """The manager gets a proper export after months of plain file drops.

    The snapshot batch filed its rows without business keys, so nothing in the
    keyed batch can be matched against it. Indexing the old rows by a key they
    never had raised a bare KeyError out of the refresh.
    """
    task, refresh, store = _task(tmp_path)
    source = tmp_path / "ledger.csv"
    rows = [
        {"document_id": "V-1", "line_id": "1", "account_code": "6001", "amount": "100"},
        {"document_id": "V-1", "line_id": "2", "account_code": "6401", "amount": "60"},
    ]
    _write_csv(source, rows)

    snapshot = refresh.refresh_file(
        source, scope=_scope(), name="ledger", file_identity_policy="snapshot_only"
    )
    assert snapshot["business_key_count"] == 0

    # Same rows, now claimed to carry business keys. The bytes differ so this is
    # not answered as a duplicate.
    _write_csv(source, [*rows, {"document_id": "V-2", "line_id": "1",
                                "account_code": "6602", "amount": "40"}])
    keyed = refresh.refresh_file(
        source, scope=_scope(), name="ledger", file_identity_policy="business_key"
    )
    assert keyed["business_key_count"] == 3
    assert keyed["identity_rebaselined"] is True
    # Not "3 inserted": the first two rows are not new, they are unmatchable.
    assert set(keyed["change_counts"].values()) == {"unknown_identity_change"}
    assert store.read_dataset(keyed["dataset_id"])["row_count"] == 3
