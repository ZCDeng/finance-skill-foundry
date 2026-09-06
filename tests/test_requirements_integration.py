import json

import pytest

from foundry.analysis import AnalysisStore
from foundry.errors import FoundryError
from foundry.finance_service import FinanceStore
from foundry.task import TaskStore


@pytest.fixture
def finance(tmp_path):
    task = TaskStore(tmp_path / "var").create(title="管理利润")
    store = AnalysisStore(task)
    bindings = {}
    for scenario, amounts in (("actual", [120, 70, 20]), ("budget", [100, 60, 15])):
        path = tmp_path / f"{scenario}.json"
        path.write_text(
            json.dumps(
                [
                    {
                        "account_code": code,
                        "management_account": account,
                        "amount": amount,
                    }
                    for code, account, amount in zip(
                        ("001", "002", "003"),
                        ("revenue", "cost", "expense"),
                        amounts,
                    )
                ]
            )
        )
        bindings[scenario] = store.add_dataset(path, name=scenario)["id"]
    service = FinanceStore(task)
    context = service.save_context(
        {
            "bindings": bindings,
            "scopes": {
                alias: {
                    "ledger": "L1",
                    "organization": "O1",
                    "period": "2026-09",
                    "currency": "CNY",
                    "unit": "万元",
                    "scenario": alias,
                }
                for alias in bindings
            },
        }
    )
    return service, context


def test_requirements_cover_context_variance_and_source_failures(finance, monkeypatch):
    service, context = finance
    service.analysis_requirements_save(
        {
            "context_id": context["id"],
            "question": "解释利润并下钻利润",
            "items": [
                {"id": "profit", "metric": "profit", "requires_drilldown": True}
            ],
        }
    )
    run = service.explain_variance({"context_id": context["id"]})
    ok_draft = service.save_explanation_draft(
        {"body": "请查看计算依据。", "run_ids": [run["id"]]}
    )

    assert ok_draft["quality"]["checks"]["coverage"]["status"] == "pass"
    assert ok_draft["quality"]["checks"]["provenance"]["status"] == "pass"
    assert ok_draft["source_read_failures"] == []

    def unavailable(spec):
        raise FoundryError("source temporarily unavailable")

    monkeypatch.setattr(service, "drilldown_fact", unavailable)
    failed_draft = service.save_explanation_draft(
        {"body": "重新查看计算依据。", "run_ids": [run["id"]]}
    )

    assert failed_draft["quality"]["checks"]["coverage"]["status"] == "pass"
    assert failed_draft["quality"]["checks"]["provenance"]["status"] == "needs_attention"
    assert failed_draft["source_read_failures"]
    assert failed_draft["quality"]["requirements"]["items"][0]["provenance_status"] == "failed"
