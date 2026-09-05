"""Benchmark finance baseline import and fixed profit query.

This is an r2 stage 0 sample-preparation benchmark. It uses the existing
AnalysisStore and snapshot SQL path only; it does not implement future finance
domain objects.

Run:
  python3 tools/benchmark_finance_baseline.py --output /tmp/foundry-finance-baseline.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import resource
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from foundry.analysis import AnalysisStore  # noqa: E402
from foundry.task import TaskStore  # noqa: E402

FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "finance_baseline"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture_hashes() -> dict[str, str]:
    return {
        str(path.relative_to(FIXTURE_ROOT)): sha256(path)
        for path in sorted(FIXTURE_ROOT.rglob("*"))
        if path.is_file()
    }


def write_large_ledger(path: Path, rows: int) -> None:
    headers = [
        "source_system",
        "tenant",
        "ledger",
        "organization",
        "period",
        "currency",
        "unit",
        "scenario",
        "management_account",
        "amount",
        "source_row",
    ]
    accounts = ("revenue", "cost", "expense")
    amounts = {"revenue": "120", "cost": "70", "expense": "20"}
    orgs = ("华东", "西南", "华北", "华南")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for index in range(rows):
            account = accounts[index % len(accounts)]
            writer.writerow(
                {
                    "source_system": "benchmark",
                    "tenant": "tenant-bench",
                    "ledger": "service-co",
                    "organization": orgs[index % len(orgs)],
                    "period": "2026-08" if index % 2 == 0 else "2026-07",
                    "currency": "CNY",
                    "unit": "元",
                    "scenario": "actual",
                    "management_account": account,
                    "amount": amounts[account],
                    "source_row": index + 1,
                }
            )


def median(values: list[float]) -> float:
    return float(statistics.median(values))


def peak_rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return int(value)
    return int(value) * 1024


def physical_memory_bytes() -> int | None:
    if sys.platform == "darwin":
        try:
            return int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip())
        except (OSError, subprocess.SubprocessError, ValueError):
            return None
    pages = getattr(os, "sysconf", lambda _name: None)("SC_PHYS_PAGES")
    page_size = getattr(os, "sysconf", lambda _name: None)("SC_PAGE_SIZE")
    if isinstance(pages, int) and isinstance(page_size, int):
        return pages * page_size
    return None


def expected_profit(rows: int) -> int:
    total = 0
    for index in range(rows):
        if index % 4 != 0:
            continue
        account = index % 3
        if account == 0:
            total += 120
        elif account == 1:
            total -= 70
        else:
            total -= 20
    return total


def run_once(root: Path, rows: int, iteration: int) -> dict[str, Any]:
    var = root / f"var-{iteration}"
    upload = root / f"ledger-{iteration}.csv"
    write_large_ledger(upload, rows)

    task = TaskStore(var).create(title=f"finance baseline benchmark {iteration}")
    store = AnalysisStore(task)

    started = time.perf_counter()
    dataset = store.add_dataset(
        upload,
        name="large-ledger",
        metadata={
            "currency": "CNY",
            "unit": "元",
            "ledger": "service-co",
            "rows": rows,
            "fixture": "generated benchmark ledger",
        },
    )
    import_seconds = time.perf_counter() - started
    import_peak = peak_rss_bytes()

    analysis = store.save_analysis(
        {
            "question": "固定利润查询：华东 2026-08",
            "bindings": {"ledger": dataset["id"]},
            "sql": """
SELECT
  SUM(CASE WHEN management_account='revenue' THEN amount ELSE 0 END)
  - SUM(CASE WHEN management_account='cost' THEN amount ELSE 0 END)
  - SUM(CASE WHEN management_account='expense' THEN amount ELSE 0 END) AS profit
FROM ledger
WHERE organization='华东'
  AND period='2026-08'
  AND currency='CNY'
  AND unit='元'
""",
            "metrics": [
                {
                    "name": "profit",
                    "currency": "CNY",
                    "unit": "元",
                    "period": "2026-08",
                }
            ],
        }
    )

    query_started = time.perf_counter()
    run = store.run_analysis(analysis["id"])
    query_seconds = time.perf_counter() - query_started
    query_peak = peak_rss_bytes()
    expected = str(expected_profit(rows))
    actual = run["result"]["rows"][0]["profit"]
    if run["execution_status"] != "succeeded" or actual != expected:
        raise SystemExit(
            "benchmark query truth check failed: "
            f"status={run['execution_status']} actual={actual} expected={expected}"
        )

    return {
        "iteration": iteration,
        "rows": rows,
        "source_bytes": upload.stat().st_size,
        "dataset_id": dataset["id"],
        "analysis_id": analysis["id"],
        "run_id": run["id"],
        "execution_status": run["execution_status"],
        "profit": actual,
        "expected_profit": expected,
        "import_seconds": import_seconds,
        "cold_query_seconds": query_seconds,
        "process_high_water_mark_rss_bytes_after_import": import_peak,
        "process_high_water_mark_rss_bytes_after_cold_query": query_peak,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=100_000)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.rows < 1 or args.rows > 100_000:
        raise SystemExit("--rows must be between 1 and 100000")
    if args.iterations < 1:
        raise SystemExit("--iterations must be positive")

    with tempfile.TemporaryDirectory(prefix="foundry-finance-baseline-") as temp:
        root = Path(temp)
        runs = [run_once(root, args.rows, index + 1) for index in range(args.iterations)]

    result = {
        "schema_version": 1,
        "benchmark": "A25 finance baseline import and fixed profit query",
        "rows": args.rows,
        "iterations": args.iterations,
        "machine": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "processor": platform.processor(),
            "machine": platform.machine(),
            "cpu_count": os.cpu_count(),
            "physical_memory_bytes": physical_memory_bytes(),
        },
        "measurement": {
            "import_seconds": "AnalysisStore.add_dataset wall time for a generated CSV source",
            "cold_query_seconds": "first AnalysisStore.run_analysis call for each newly imported dataset",
            "rss": "process high-water mark from resource.getrusage(RUSAGE_SELF). In a 5-iteration run this is cumulative for the benchmark process; use separate processes for independent per-run RSS peaks.",
            "truth": "expected_profit is computed independently from the generated row pattern for 华东 / 2026-08 / CNY / 元",
        },
        "expected_profit": str(expected_profit(args.rows)),
        "fixture_hashes": fixture_hashes(),
        "runs": runs,
        "median": {
            "import_seconds": median([row["import_seconds"] for row in runs]),
            "cold_query_seconds": median([row["cold_query_seconds"] for row in runs]),
            "process_high_water_mark_rss_bytes_after_import": int(
                median([row["process_high_water_mark_rss_bytes_after_import"] for row in runs])
            ),
            "process_high_water_mark_rss_bytes_after_cold_query": int(
                median([row["process_high_water_mark_rss_bytes_after_cold_query"] for row in runs])
            ),
        },
    }
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
