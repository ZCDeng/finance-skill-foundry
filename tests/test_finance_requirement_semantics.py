"""Semantic requirement fingerprints control when older finance runs can be reused."""
import json

import pytest

from foundry.finance_completion import record_completion
from foundry.finance_requirements import latest_requirements
from foundry.finance_service import FinanceStore
from foundry.task import TaskStore


def _management_service(tmp_path, *, dirname="var", period="2026-09", unit="万元"):
    service = FinanceStore(TaskStore(tmp_path / dirname).create(title="语义复用"))
    bindings = {}
    for scenario, amounts in (("actual", [120, 70, 20]), ("budget", [100, 60, 15])):
        path = tmp_path / f"{dirname}-{scenario}.json"
        path.write_text(
            json.dumps(
                [
                    {"account_code": code, "management_account": account, "amount": amount}
                    for code, account, amount in zip(
                        ("001", "002", "003"),
                        ("revenue", "cost", "expense"),
                        amounts,
                    )
                ],
                ensure_ascii=False,
            )
        )
        bindings[scenario] = service.analysis.add_dataset(path, name=scenario)["id"]
    context = service.save_context(
        {
            "bindings": bindings,
            "scopes": {
                alias: {
                    "ledger": "L1",
                    "organization": "O1",
                    "period": period,
                    "currency": "CNY",
                    "unit": unit,
                    "scenario": alias,
                }
                for alias in bindings
            },
        }
    )
    return service, context


def _ratio_requirement(service, context, *, metric="variance_ratio", item_id="margin", label="成本率", parent_id=None, question="解释成本率变化"):
    spec = {
        "question": question,
        "context_id": context["id"],
        "items": [
            {
                "id": item_id,
                "metric": metric,
                "label": label,
                "requires_drilldown": False,
            }
        ],
    }
    if parent_id:
        spec["parent_id"] = parent_id
    return service.analysis_requirements_save(spec)


def _run_ratio(service, context):
    return service.run_metric(
        {
            "context_id": context["id"],
            "metric": {
                "kind": "ratio",
                "numerator_accounts": ["cost"],
                "denominator_accounts": ["revenue"],
                "filters": {"scenario": "actual"},
            },
        }
    )


def _quality(requirement):
    return {
        "status": "pass",
        "issues": [],
        "checks": {"numbers": {"status": "pass"}},
        "requirements": {
            "requirements_id": requirement["id"],
            "coverage": {"status": "pass"},
            "provenance": {"status": "pass"},
            "items": [{"id": item["id"], "status": "answered"} for item in requirement["items"]],
            "original_requirements_completed": True,
        },
    }


def _completion_for(service, requirement, run, *, draft_id="a"):
    return record_completion(
        service.analysis,
        {"id": draft_id * 32, "content_hash": f"draft-{draft_id}", "run_ids": [run["id"]]},
        _quality(requirement),
    )


def _assert_bound_to_requirements(run, requirement):
    assert requirement["semantic_basis"]
    assert requirement["semantic_fingerprint"]
    assert run["requirements_id"] == requirement["id"]
    assert run["requirements_semantic_fingerprint"] == requirement["semantic_fingerprint"]


def test_metric_alias_and_label_edit_can_reuse_semantically_equivalent_finance_run(tmp_path):
    service, context = _management_service(tmp_path)
    original = _ratio_requirement(service, context, metric="variance_ratio", label="模型字段名")
    old_run = _run_ratio(service, context)
    revised = _ratio_requirement(
        service,
        context,
        metric="ratio",
        label="财务经理可读名称",
        parent_id=original["id"],
    )

    _assert_bound_to_requirements(old_run, original)
    assert revised["semantic_fingerprint"] == original["semantic_fingerprint"]

    completion = _completion_for(service, revised, old_run)

    assert completion["status"] == "complete"
    assert completion["stop_reason"] == "complete"
    assert completion["reused_run_ids"] == [old_run["id"]]
    assert not completion["actions"]


def test_required_organization_set_changes_semantic_fingerprint(tmp_path):
    from foundry.finance_requirement_semantics import run_has_equivalent_requirements

    service, context = _management_service(tmp_path)
    base = {
        "question": "逐组织核对成本率",
        "context_id": context["id"],
        "scope": {"ledger": "L1"},
        "items": [{"id": "margin", "metric": "ratio", "requires_drilldown": False}],
    }
    original = service.analysis_requirements_save(base)
    run = _run_ratio(service, context)
    revised = service.analysis_requirements_save({
        **base,
        "parent_id": original["id"],
        "items": [{**base["items"][0], "organizations": ["O1", "O2"]}],
    })

    assert original["semantic_fingerprint"] != revised["semantic_fingerprint"]
    assert revised["semantic_basis"]["items"][0]["organizations"] == ["O1", "O2"]
    assert not run_has_equivalent_requirements(service.analysis, run, revised)


def test_profit_bridge_method_alias_reuses_same_semantic_fingerprint_and_run(tmp_path):
    service, context = _management_service(tmp_path, dirname="profit-method")
    original = service.analysis_requirements_save({
        "question": "解释利润桥",
        "context_id": context["id"],
        "items": [{
            "id": "profit",
            "metric": "profit",
            "label": "利润桥",
            "dimensions": {"method": "利润桥"},
            "requires_drilldown": False,
        }],
    })
    old_run = service.explain_variance({"context_id": context["id"]})
    revised = service.analysis_requirements_save({
        "parent_id": original["id"],
        "question": "解释利润桥",
        "context_id": context["id"],
        "items": [{
            "id": "profit",
            "metric": "profit",
            "label": "利润桥展示名",
            "dimensions": {"method": "profit_bridge"},
            "requires_drilldown": False,
        }],
    })

    _assert_bound_to_requirements(old_run, original)
    assert old_run["result"]["method"] == "revenue_minus_cost_minus_expense"
    assert revised["semantic_fingerprint"] == original["semantic_fingerprint"]

    completion = _completion_for(service, revised, old_run, draft_id="p")

    assert completion["status"] == "complete"
    assert completion["reused_run_ids"] == [old_run["id"]]


@pytest.mark.parametrize(
    ("name", "revised_context_kwargs"),
    [
        ("period", {"period": "2026-10"}),
        ("unit", {"unit": "元"}),
    ],
)
def test_scope_period_or_unit_change_cannot_reuse_old_run(tmp_path, name, revised_context_kwargs):
    service, original_context = _management_service(tmp_path, dirname=f"scope-{name}")
    original = _ratio_requirement(service, original_context)
    old_run = _run_ratio(service, original_context)
    _assert_bound_to_requirements(old_run, original)

    revised_context = service.save_context(
        {
            "bindings": original_context["bindings"],
            "scopes": {
                alias: {**scope, **revised_context_kwargs}
                for alias, scope in original_context["scopes"].items()
            },
        }
    )
    revised = _ratio_requirement(service, revised_context, metric="ratio", parent_id=original["id"])

    assert revised["semantic_fingerprint"] != original["semantic_fingerprint"]

    completion = _completion_for(service, revised, old_run, draft_id=name[0])

    assert completion["status"] != "complete"
    assert old_run["id"] not in completion.get("reused_run_ids", [])
    assert any(action["code"] == "requirements_run_outdated" for action in completion["actions"])


def _price_quantity_service(tmp_path):
    service = FinanceStore(TaskStore(tmp_path / "pq-var").create(title="量价语义"))
    path = tmp_path / "pq.json"
    path.write_text(
        json.dumps(
            [
                {"ledger": "commerce", "organization": "电商部", "period": "2026-08", "currency": "CNY", "unit": "元", "scenario": "budget", "product": "商品B", "quantity": "20", "price": "5"},
                {"ledger": "commerce", "organization": "电商部", "period": "2026-08", "currency": "CNY", "unit": "元", "scenario": "actual", "product": "商品B", "quantity": "18", "price": "7"},
            ],
            ensure_ascii=False,
        )
    )
    dataset = service.analysis.add_dataset(path, name="pq")
    context = service.save_context(
        {
            "bindings": {"pq": dataset["id"]},
            "scopes": {
                "pq": {
                    "ledger": "commerce",
                    "organization": "电商部",
                    "period": "2026-08",
                    "currency": "CNY",
                    "unit": "元",
                }
            },
        }
    )
    return service, context


def _pq_requirement(service, context, *, method, parent_id=None):
    spec = {
        "question": "解释商品B收入量价变化",
        "context_id": context["id"],
        "scope": {
            "ledger": "commerce",
            "organization": "电商部",
            "period": "2026-08",
            "currency": "CNY",
            "unit": "元",
        },
        "items": [
            {
                "id": "revenue_pq",
                "metric": "price_quantity",
                "dimensions": {"product": "商品B", "method": method},
                "requires_drilldown": False,
            }
        ],
    }
    if parent_id:
        spec["parent_id"] = parent_id
    return service.analysis_requirements_save(spec)


def _run_pq(service, context, *, method):
    return service.explain_variance(
        {
            "context_id": context["id"],
            "kind": "price_quantity",
            "method": method,
            "field_map": {"quantity": "quantity", "price": "price"},
            "dimensions": ["product"],
            "actual_scenario": "actual",
            "baseline_scenario": "budget",
            "actual_filters": {"product": "商品B", "period": "2026-08"},
            "baseline_filters": {"product": "商品B", "period": "2026-08"},
        }
    )


def test_price_quantity_method_change_cannot_reuse_old_bridge_run(tmp_path):
    service, context = _price_quantity_service(tmp_path)
    original = _pq_requirement(service, context, method="quantity_then_price")
    old_run = _run_pq(service, context, method="quantity_then_price")
    revised = _pq_requirement(
        service,
        context,
        method="base_weights_with_interaction",
        parent_id=original["id"],
    )

    _assert_bound_to_requirements(old_run, original)
    assert old_run["result"]["method"] == "quantity_then_price"
    assert revised["semantic_fingerprint"] != original["semantic_fingerprint"]

    completion = _completion_for(service, revised, old_run, draft_id="m")

    assert completion["status"] != "complete"
    assert old_run["id"] not in completion.get("reused_run_ids", [])
    assert any(action["code"] == "requirements_run_outdated" for action in completion["actions"])


def test_source_and_context_change_cannot_reuse_old_run(tmp_path):
    service, original_context = _management_service(tmp_path, dirname="source-original")
    original = _ratio_requirement(service, original_context)
    old_run = _run_ratio(service, original_context)
    _assert_bound_to_requirements(old_run, original)

    same_service, revised_context = _management_service(tmp_path, dirname="source-revised")
    # Keep one task/history so the parent chain and old run are comparable; copy the new
    # context into the original service by rebuilding it there with fresh dataset ids.
    revised_paths = []
    for alias in ("actual", "budget"):
        dataset_id = revised_context["bindings"][alias]
        dataset = same_service.analysis.read_dataset(dataset_id)
        path = tmp_path / f"copied-{alias}.json"
        path.write_text(json.dumps(dataset["rows"], ensure_ascii=False))
        revised_paths.append((alias, service.analysis.add_dataset(path, name=f"copied-{alias}")["id"]))
    revised_context = service.save_context(
        {
            "bindings": dict(revised_paths),
            "scopes": original_context["scopes"],
        }
    )
    revised = _ratio_requirement(service, revised_context, metric="ratio", parent_id=original["id"])

    assert revised["semantic_fingerprint"] != original["semantic_fingerprint"]

    completion = _completion_for(service, revised, old_run, draft_id="s")

    assert completion["status"] != "complete"
    assert old_run["id"] not in completion.get("reused_run_ids", [])
    assert any(action["code"] == "requirements_run_outdated" for action in completion["actions"])


def test_removed_requirement_item_changes_semantics_and_blocks_old_run_reuse(tmp_path):
    service, context = _management_service(tmp_path)
    original = _ratio_requirement(service, context)
    old_run = _run_ratio(service, context)
    revised = service.analysis_requirements_save(
        {
            "question": original["question"],
            "context_id": context["id"],
            "parent_id": original["id"],
            "items": [],
            "change_reason": "经理改为另行确认该指标",
        }
    )

    _assert_bound_to_requirements(old_run, original)
    assert revised["removed_item_ids"] == ["margin"]
    assert revised["semantic_fingerprint"] != original["semantic_fingerprint"]

    completion = _completion_for(service, revised, old_run, draft_id="r")

    assert completion["status"] != "complete"
    assert old_run["id"] not in completion.get("reused_run_ids", [])


def test_run_without_captured_requirements_cannot_be_reused_after_equivalent_revision(tmp_path):
    service, context = _management_service(tmp_path)
    unbound_run = _run_ratio(service, context)
    original = _ratio_requirement(service, context, metric="variance_ratio")
    revised = _ratio_requirement(service, context, metric="ratio", parent_id=original["id"])

    assert "requirements_id" not in unbound_run or unbound_run["requirements_id"] is None
    assert revised["semantic_fingerprint"] == original["semantic_fingerprint"]

    completion = _completion_for(service, revised, unbound_run, draft_id="u")

    assert completion["status"] != "complete"
    assert unbound_run["id"] not in completion.get("reused_run_ids", [])
    assert any(action["code"] == "requirements_run_outdated" for action in completion["actions"])


def test_client_supplied_semantic_fingerprint_does_not_bind_run(tmp_path):
    service, context = _management_service(tmp_path)
    fake = "f" * 64
    unbound_run = service.run_metric(
        {
            "context_id": context["id"],
            "requirements_semantic_fingerprint": fake,
            "metric": {
                "kind": "ratio",
                "numerator_accounts": ["cost"],
                "denominator_accounts": ["revenue"],
                "filters": {"scenario": "actual"},
            },
        }
    )
    original = _ratio_requirement(service, context, metric="variance_ratio")
    revised = _ratio_requirement(service, context, metric="ratio", parent_id=original["id"])

    assert unbound_run.get("requirements_semantic_fingerprint") != fake
    assert unbound_run.get("requirements_id") is None

    completion = _completion_for(service, revised, unbound_run, draft_id="f")

    assert completion["status"] != "complete"
    assert unbound_run["id"] not in completion.get("reused_run_ids", [])
    assert any(action["code"] == "requirements_run_outdated" for action in completion["actions"])


def test_run_started_before_concurrent_requirement_revision_needs_semantic_proof_even_if_seq_is_newer(tmp_path, monkeypatch):
    import foundry.finance_service as finance_service_module

    service, context = _management_service(tmp_path)
    original = _ratio_requirement(service, context, metric="variance_ratio")
    original_explain_variance = finance_service_module.explain_variance

    def revise_requirements_during_calculation(normalized, spec):
        if latest_requirements(service.analysis)["id"] == original["id"]:
            _ratio_requirement(
                service,
                context,
                metric="ratio",
                parent_id=original["id"],
                question="改为解释下月成本率变化",
            )
        return original_explain_variance(normalized, spec)

    monkeypatch.setattr(finance_service_module, "explain_variance", revise_requirements_during_calculation)

    run = service.explain_variance({"context_id": context["id"]})
    revised = latest_requirements(service.analysis)

    _assert_bound_to_requirements(run, original)
    assert run["seq"] > revised["seq"]
    assert revised["semantic_fingerprint"] != original["semantic_fingerprint"]

    completion = _completion_for(service, revised, run, draft_id="c")

    assert completion["status"] != "complete"
    assert run["id"] not in completion.get("reused_run_ids", [])
    assert any(action["code"] == "requirements_run_outdated" for action in completion["actions"])


def _failing_quality(requirement):
    return {
        "status": "needs_attention",
        "issues": [
            {
                "code": "requirement_unanswered",
                "requirement_item_id": requirement["items"][0]["id"],
                "message": "仍需补充解释。",
            }
        ],
        "checks": {"numbers": {"status": "pass"}},
        "requirements": {
            "requirements_id": requirement["id"],
            "coverage": {"status": "needs_attention"},
            "provenance": {"status": "pass"},
            "items": [{"id": requirement["items"][0]["id"], "status": "pending"}],
            "original_requirements_completed": False,
        },
    }


def test_semantically_equivalent_label_edits_keep_same_completion_chain_and_repair_budget(tmp_path):
    service, context = _management_service(tmp_path)
    original = _ratio_requirement(service, context, metric="variance_ratio", label="首版名称")
    run = _run_ratio(service, context)
    first_label_edit = _ratio_requirement(
        service,
        context,
        metric="ratio",
        label="第二版名称",
        parent_id=original["id"],
    )
    second_label_edit = _ratio_requirement(
        service,
        context,
        metric="ratio",
        label="第三版名称",
        parent_id=first_label_edit["id"],
    )

    assert original["semantic_fingerprint"] == first_label_edit["semantic_fingerprint"]
    assert first_label_edit["semantic_fingerprint"] == second_label_edit["semantic_fingerprint"]

    first = record_completion(
        service.analysis,
        {"id": "1" * 32, "content_hash": "same-problem-1", "run_ids": [run["id"]]},
        _failing_quality(first_label_edit),
    )
    second = record_completion(
        service.analysis,
        {"id": "2" * 32, "content_hash": "same-problem-2", "run_ids": [run["id"]]},
        _failing_quality(second_label_edit),
    )

    assert first["chain_key"] == second["chain_key"]
    assert first["requirements_semantic_fingerprint"] == second["requirements_semantic_fingerprint"]
    assert first["status"] == "repair_available"
    assert second["status"] == "needs_review"
    assert first["repair_allowed"] is True
    assert second["repair_allowed"] is False
    assert second["stop_reason"] == "no_progress"


def test_tampered_snapshot_prevents_old_and_new_requirement_fingerprint_verification(tmp_path):
    from foundry.finance_requirement_semantics import verified_requirement_fingerprint

    service, context = _management_service(tmp_path)
    original = _ratio_requirement(service, context, metric="variance_ratio")
    run = _run_ratio(service, context)
    revised = _ratio_requirement(service, context, metric="ratio", parent_id=original["id"])

    assert original["semantic_fingerprint"] == revised["semantic_fingerprint"]
    _assert_bound_to_requirements(run, original)

    actual_dataset_id = context["bindings"]["actual"]
    tampered = service.analysis.root / "datasets" / actual_dataset_id / "data.json"
    tampered.write_text(json.dumps({"rows": [], "schema": []}, ensure_ascii=False))

    assert verified_requirement_fingerprint(service.analysis, original) is None
    assert verified_requirement_fingerprint(service.analysis, revised) is None

    completion = _completion_for(service, revised, run, draft_id="t")

    assert completion["status"] != "complete"
    assert completion["requirements_semantic_fingerprint"] is None
    assert run["id"] not in completion.get("reused_run_ids", [])
    assert any(action["code"] == "requirements_run_outdated" for action in completion["actions"])


def test_sql_run_captures_current_requirements_id_and_server_verified_fingerprint(tmp_path):
    service, context = _management_service(tmp_path)
    requirement = _ratio_requirement(service, context, metric="ratio")
    analysis = service.analysis.save_analysis(
        {
            "question": "计算成本率",
            "bindings": context["bindings"],
            "sql": "SELECT SUM(cost.amount) / SUM(revenue.amount) AS ratio FROM actual cost, actual revenue WHERE cost.management_account = 'cost' AND revenue.management_account = 'revenue'",
            "metrics": [{"kind": "ratio"}],
        }
    )

    run = service.analysis.run_analysis(analysis["id"])

    _assert_bound_to_requirements(run, requirement)
    assert "SELECT SUM(cost.amount)" in run["sql"]
    assert run["requirements_semantic_fingerprint"] != "f" * 64


def test_script_run_captures_current_requirements_with_mocked_runner(tmp_path, monkeypatch):
    import foundry.runner as runner_module

    service, context = _management_service(tmp_path)
    requirement = _ratio_requirement(service, context, metric="ratio")

    def fake_run_script(workspace, code, **options):
        return {
            "status": "succeeded",
            "stdout": "ok\n",
            "stderr": "",
            "exit_code": 0,
            "outputs": [],
            "workspace": str(workspace),
            "environment": {"mocked": True, "language": options.get("language")},
        }

    monkeypatch.setattr(runner_module, "run_script", fake_run_script)

    run = service.analysis.run_script(
        {
            "question": "脚本计算成本率",
            "language": "python",
            "code": "print('ok')",
            "bindings": context["bindings"],
        }
    )

    _assert_bound_to_requirements(run, requirement)
    assert run["engine"] == "python"
    assert run["runner_status"] == "succeeded"
    assert run["environment"] == {"mocked": True, "language": "python"}


def test_restricted_finance_run_does_not_capture_unauthorized_latest_requirements(tmp_path):
    service, allowed_context = _management_service(tmp_path, dirname="allowed")
    _other_service, other_context = _management_service(tmp_path, dirname="unauthorized")
    copied = []
    for alias in ("actual", "budget"):
        dataset = _other_service.analysis.read_dataset(other_context["bindings"][alias])
        path = tmp_path / f"unauthorized-copy-{alias}.json"
        path.write_text(json.dumps(dataset["rows"], ensure_ascii=False))
        copied.append((alias, service.analysis.add_dataset(path, name=f"unauthorized-{alias}")["id"]))
    unauthorized_context = service.save_context(
        {
            "bindings": dict(copied),
            "scopes": other_context["scopes"],
        }
    )
    latest = _ratio_requirement(service, unauthorized_context, metric="ratio")
    restricted = FinanceStore(service.task, snapshot_ids=list(allowed_context["bindings"].values()))

    run = restricted.run_metric(
        {
            "context_id": allowed_context["id"],
            "metric": {
                "kind": "ratio",
                "numerator_accounts": ["cost"],
                "denominator_accounts": ["revenue"],
                "filters": {"scenario": "actual"},
            },
        }
    )

    assert latest["bindings"] == unauthorized_context["bindings"]
    assert run["execution_status"] == "succeeded"
    assert run.get("requirements_id") is None
    assert run.get("requirements_semantic_fingerprint") is None
