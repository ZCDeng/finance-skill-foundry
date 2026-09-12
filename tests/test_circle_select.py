from __future__ import annotations

import json
from pathlib import Path

import pytest
from openpyxl import Workbook

from foundry.errors import FoundryError
from foundry.finance_files import FinanceFiles
from foundry.finance_service import FinanceStore
from foundry.task import TaskStore

SCOPE = {
    "ledger": "service-co",
    "organization": "华东",
    "period": "2026-08",
    "currency": "CNY",
    "unit": "万元",
    "scenario": "actual",
}


def _service(tmp_path: Path):
    task = TaskStore(tmp_path / "var").create(title="圈选")
    service = FinanceStore(task)
    rows = [
        {
            "ledger": "service-co",
            "organization": "华东",
            "period": "2026-08",
            "currency": "CNY",
            "unit": "万元",
            "scenario": "actual",
            "management_account": "expense",
            "amount": "20",
        }
    ]
    path = tmp_path / "g1.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    dataset = service.analysis.add_dataset(path, name="g1")
    context = service.save_context({"bindings": {"actual": dataset["id"]}, "scopes": {"actual": SCOPE}})
    requirements = service.analysis_requirements_save(
        {
            "context_id": context["id"],
            "question": "解释费用",
            "items": [{"id": "expense", "metric": "expense"}],
        }
    )
    return service, context, dataset, requirements


def test_cf30_draft_table_circle_select_writes_new_requirements(tmp_path: Path) -> None:
    service, context, _dataset, original = _service(tmp_path)
    draft = service.analysis.save_draft(
        {
            "title": "经营简报",
            "document": {
                "schema_version": 1,
                "template_version": "annual-v1",
                "content": [
                    {
                        "type": "table",
                        "attrs": {"caption": "tbl-expense"},
                        "content": [
                            {
                                "type": "tableRow",
                                "content": [
                                    {"type": "tableHeader", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "费用"}]}]},
                                ],
                            }
                        ],
                    }
                ],
            },
        }
    )
    revised = service.analysis_circle_select(
        {
            "kind": "draft_table",
            "draft_id": draft["id"],
            "block_id": "tbl-expense",
            "range": "A:A",
            "instruction": "改成开票口径",
            "context_id": context["id"],
        }
    )
    assert revised["requirements"]["parent_id"] == original["id"]
    assert revised["requirements"]["change_reason"] == "改成开票口径"
    assert revised["requirements"]["selection"] == {
        "kind": "draft_table",
        "range": "A:A",
        "draft_id": draft["id"],
        "block_id": "tbl-expense",
    }
    with pytest.raises(FoundryError, match="instruction"):
        service.analysis_circle_select(
            {
                "kind": "draft_table",
                "draft_id": draft["id"],
                "block_id": "tbl-expense",
                "range": "A:A",
                "context_id": revised["context"]["id"],
                "parent_id": revised["requirements"]["id"],
            }
        )
    assert revised["context"]["parent_id"] == context["id"]
    assert revised["context"]["bindings"] == context["bindings"]
    assert revised["context"]["id"] != context["id"]
    assert service.analysis_requirements_list({})["current"]["id"] == revised["requirements"]["id"]
    assert service._read("contexts", context["id"])["bindings"] == context["bindings"]


def test_cf30f_rejects_path_foreign_parent_and_unauthorized_range(tmp_path: Path) -> None:
    service, context, _dataset, original = _service(tmp_path)
    draft = service.analysis.save_draft({"title": "简报", "body": "费用表"})
    with pytest.raises(FoundryError, match="path|dataset|forbidden"):
        service.analysis_circle_select(
            {
                "kind": "draft_table",
                "draft_id": draft["id"],
                "path": "/tmp/secret.xlsx",
                "instruction": "改成开票口径",
                "context_id": context["id"],
            }
        )
    foreign = FinanceStore(TaskStore(tmp_path / "other").create(title="外任务"))
    with pytest.raises(FoundryError):
        foreign.analysis_circle_select(
            {
                "kind": "draft_table",
                "draft_id": draft["id"],
                "block_id": "tbl-expense",
                "range": "A:A",
                "parent_id": original["id"],
                "instruction": "改成开票口径",
            }
        )
    with pytest.raises(FoundryError, match="parent"):
        service.analysis_circle_select(
            {
                "kind": "draft_table",
                "draft_id": draft["id"],
                "block_id": "missing-block",
                "range": "A:A",
                "parent_id": "not-this-task",
                "instruction": "改成开票口径",
                "context_id": context["id"],
            }
        )
    assert service.analysis_requirements_list({})["current"]["id"] == original["id"]


def test_cf31_workbook_binding_circle_select_copies_parent_bindings(tmp_path: Path) -> None:
    service, context, dataset, original = _service(tmp_path)
    source = tmp_path / "model.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Model"
    ws["A1"] = "费用"
    ws["A2"] = 20
    wb.save(source)
    wb.close()
    xlsx = service.analysis.add_dataset(source, name="model")
    files = FinanceFiles(service.task)
    binding = files.bind(
        {
            "dataset_id": xlsx["id"],
            "source": {"kind": "range", "sheet": "Model", "range": "A1:A2"},
            "fields": [{"name": "amount", "policy": "amount"}],
            "role": "output",
        }
    )
    widened = service.save_context(
        {
            "parent_id": context["id"],
            "bindings": {**context["bindings"], "workbook": xlsx["id"]},
            "scopes": {**context["scopes"], "workbook": SCOPE},
        }
    )
    revised = service.analysis_circle_select(
        {
            "kind": "workbook",
            "binding_id": binding["id"],
            "range": "A:A",
            "instruction": "改成开票口径",
            "context_id": widened["id"],
        }
    )
    assert revised["requirements"]["parent_id"] == original["id"]
    assert revised["requirements"]["selection"] == {"kind": "workbook", "range": "A:A", "binding_id": binding["id"]}
    assert revised["context"]["bindings"] == widened["bindings"]
    assert set(revised["context"]["bindings"].values()) == set(widened["bindings"].values())
    outsider = service.save_context(
        {
            "bindings": {"other": dataset["id"]},
            "scopes": {"other": SCOPE},
        }
    )
    with pytest.raises(FoundryError, match="授权|unauthorized|bindings"):
        service.analysis_circle_select(
            {
                "kind": "workbook",
                "binding_id": binding["id"],
                "range": "A:A",
                "instruction": "改成开票口径",
                "context_id": outsider["id"],
            }
        )


def test_an_uncaptioned_table_cannot_be_reached_by_position(tmp_path: Path) -> None:
    """block_id "0" must not address the second, unnamed table.

    A table with no caption has no handle, and answering to an index would let
    a caller circle whatever happened to sit there.
    """
    service, context, _dataset, _original = _service(tmp_path)
    draft = service.analysis.save_draft(
        {
            "title": "经营简报",
            "document": {
                "schema_version": 1,
                "template_version": "annual-v1",
                "content": [
                    {
                        "type": "table",
                        "attrs": {"caption": "第一张"},
                        "content": [
                            {"type": "tableRow", "content": [{"type": "tableHeader", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "A"}]}]}]}
                        ],
                    },
                    {
                        "type": "table",
                        "content": [
                            {"type": "tableRow", "content": [{"type": "tableHeader", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "B"}]}]}]}
                        ],
                    },
                ],
            },
        }
    )
    # And the refusal says what happened: the name matches no table, which is
    # not the same thing as the caller lacking permission.
    with pytest.raises(FoundryError, match="no table in this draft is called 0"):
        service.analysis_circle_select(
            {
                "kind": "draft_table",
                "draft_id": draft["id"],
                "block_id": "0",
                "range": "selection",
                "instruction": "改成开票口径",
                "context_id": context["id"],
            }
        )


def test_a_missing_table_is_reported_as_missing_not_as_a_permission_problem(
    tmp_path: Path,
) -> None:
    service, context, _dataset, _original = _service(tmp_path)
    draft = service.analysis.save_draft(
        {
            "title": "经营简报",
            "document": {
                "schema_version": 1,
                "template_version": "annual-v1",
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "本月经营情况。"}]}
                ],
            },
        }
    )
    base = {
        "kind": "draft_table",
        "draft_id": draft["id"],
        "range": "A:A",
        "instruction": "改成开票口径",
        "context_id": context["id"],
    }
    with pytest.raises(FoundryError, match="this draft has no table to circle"):
        service.analysis_circle_select({**base, "block_id": "tbl-expense"})
    with pytest.raises(FoundryError, match="needs the caption or id"):
        service.analysis_circle_select({**base, "block_id": "   "})


def test_circle_select_needs_something_to_revise(tmp_path: Path) -> None:
    """改口径 revises a stated scope; the instruction is not the question.

    With no requirements on file, 「改成开票口径」 was filed as the analytical
    question, and every later reader took it for what had been asked.
    """
    fresh = FinanceStore(TaskStore(tmp_path / "other").create(title="没有历史需求"))
    rows = [{"ledger": "service-co", "organization": "华东", "period": "2026-08",
             "currency": "CNY", "unit": "万元", "scenario": "actual",
             "management_account": "expense", "amount": "20"}]
    path = tmp_path / "fresh.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    dataset = fresh.analysis.add_dataset(path, name="fresh")
    blank_context = fresh.save_context(
        {"name": "口径", "bindings": {"actual": dataset["id"]}, "scopes": {"actual": SCOPE}}
    )
    draft = fresh.analysis.save_draft(
        {
            "title": "经营简报",
            "document": {
                "schema_version": 1,
                "template_version": "annual-v1",
                "content": [
                    {
                        "type": "table",
                        "attrs": {"caption": "tbl-expense"},
                        "content": [
                            {"type": "tableRow", "content": [{"type": "tableHeader",
                             "content": [{"type": "paragraph", "content": [{"type": "text", "text": "费用"}]}]}]}
                        ],
                    }
                ],
            },
        }
    )
    with pytest.raises(FoundryError, match="revises an existing analysis"):
        fresh.analysis_circle_select(
            {
                "kind": "draft_table",
                "draft_id": draft["id"],
                "block_id": "tbl-expense",
                "range": "A:A",
                "instruction": "改成开票口径",
                "context_id": blank_context["id"],
            }
        )
