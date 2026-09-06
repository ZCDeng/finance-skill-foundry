from __future__ import annotations

import time

import foundry.analysis_sql as analysis_sql


def table(rows, schema):
    return {
        "kind": "table",
        "schema": schema,
        "rows": rows,
        "row_count": len(rows),
        "metadata": {},
    }


def test_snapshot_staging_preserves_decimal_null_text_and_leading_zeroes():
    datasets = {
        "actual": table(
            [
                {
                    "account_code": "00123",
                    "organization": "华东",
                    "amount": "900719925474099.99",
                    "optional": None,
                },
                {
                    "account_code": "00007",
                    "organization": "",
                    "amount": None,
                    "optional": "kept",
                },
            ],
            [
                {"name": "account_code", "type": "VARCHAR"},
                {"name": "organization", "type": "VARCHAR"},
                {"name": "amount", "type": "DECIMAL(38,2)"},
                {"name": "optional", "type": "VARCHAR"},
            ],
        )
    }
    result = analysis_sql.execute_sql(
        datasets,
        {
            "sql": """
SELECT account_code, organization, amount, optional
FROM actual
ORDER BY account_code DESC
""",
            "parameters": [],
            "max_rows": 10,
            "timeout_seconds": 5,
            "relationships": [],
        },
    )
    assert "error" not in result, result
    assert result["result"]["rows"] == [
        {
            "account_code": "00123",
            "organization": "华东",
            "amount": "900719925474099.99",
            "optional": None,
        },
        {
            "account_code": "00007",
            "organization": "",
            "amount": None,
            "optional": "kept",
        },
    ]


def test_snapshot_staging_keeps_relationship_and_sql_boundaries():
    datasets = {
        "actual": table(
            [{"id": "A", "amount": "10"}, {"id": "A", "amount": "20"}],
            [
                {"name": "id", "type": "VARCHAR"},
                {"name": "amount", "type": "DECIMAL(38,0)"},
            ],
        ),
        "mapping": table(
            [{"id": "A", "label": "收入"}],
            [
                {"name": "id", "type": "VARCHAR"},
                {"name": "label", "type": "VARCHAR"},
            ],
        ),
    }
    result = analysis_sql.execute_sql(
        datasets,
        {
            "sql": "SELECT SUM(a.amount) AS amount FROM actual a JOIN mapping m USING(id)",
            "parameters": [],
            "max_rows": 10,
            "timeout_seconds": 5,
            "relationships": [
                {
                    "left": "actual",
                    "right": "mapping",
                    "keys": ["id"],
                    "cardinality": "one-to-one",
                }
            ],
        },
    )
    assert result["error_code"] == "query_refused"
    assert "duplicate keys on left side" in result["error"]

    refused = analysis_sql.execute_sql(
        datasets,
        {
            "sql": "SELECT * FROM read_text('/etc/passwd')",
            "parameters": [],
            "max_rows": 10,
            "timeout_seconds": 5,
            "relationships": [],
        },
    )
    assert refused["error_code"] == "query_refused"


def test_timeout_timer_is_active_before_snapshot_staging(monkeypatch):
    def slow_stage(_connection, _alias, _dataset, expired):
        deadline = time.monotonic() + 3
        while not expired.is_set() and time.monotonic() < deadline:
            time.sleep(0.01)
        if expired.is_set():
            raise analysis_sql.FoundryError("SQL exceeded its execution time limit")

    monkeypatch.setattr(analysis_sql, "_stage_table", slow_stage)
    started = time.monotonic()
    result = analysis_sql.execute_sql(
        {
            "actual": table(
                [{"amount": "1"}],
                [{"name": "amount", "type": "DECIMAL(38,0)"}],
            )
        },
        {
            "sql": "SELECT SUM(amount) AS amount FROM actual",
            "parameters": [],
            "max_rows": 10,
            "timeout_seconds": 0.05,
            "relationships": [],
        },
    )
    elapsed = time.monotonic() - started
    assert result["error_code"] == "timeout"
    assert elapsed < 3


def test_timeout_timer_interrupts_large_relationship_checks(monkeypatch):
    rows = [{"id": str(index), "amount": "1"} for index in range(20_000)]
    datasets = {
        "actual": table(
            rows,
            [
                {"name": "id", "type": "VARCHAR"},
                {"name": "amount", "type": "DECIMAL(38,0)"},
            ],
        ),
        "mapping": table(
            rows,
            [
                {"name": "id", "type": "VARCHAR"},
                {"name": "amount", "type": "DECIMAL(38,0)"},
            ],
        ),
    }
    original = analysis_sql._raise_if_expired
    calls = 0

    def expire_after_first_check(expired):
        nonlocal calls
        calls += 1
        if expired is not None:
            expired.set()
        original(expired)

    monkeypatch.setattr(analysis_sql, "_raise_if_expired", expire_after_first_check)
    result = analysis_sql.execute_sql(
        datasets,
        {
            "sql": "SELECT SUM(a.amount) AS amount FROM actual a JOIN mapping m USING(id)",
            "parameters": [],
            "max_rows": 10,
            "timeout_seconds": 5,
            "relationships": [
                {
                    "left": "actual",
                    "right": "mapping",
                    "keys": ["id"],
                    "cardinality": "one-to-one",
                }
            ],
        },
    )
    assert calls >= 1
    assert result["error_code"] == "timeout"
