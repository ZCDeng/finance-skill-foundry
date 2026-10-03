"""A practice task built from synthetic data, so a first run never has to touch real books.

``create_sample_task`` makes (or reuses) one task titled ``SAMPLE_TITLE`` holding one
generated workbook. The workbook is small and fictitious, dated 2026-06 so it can
never pass for the current month, and carries one deliberate tie-out break (the
bad-debt column of the aging table does not add up to its 合计 row) so the 月结 tab
and the 勾稽控制 panel have something real to show. It lives in its own task; nothing
here reads or writes any other task.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from openpyxl import Workbook

from foundry.analysis import AnalysisStore
from foundry.finance_service import FinanceStore
from foundry.locking import exclusive
from foundry.task import TaskStore

SAMPLE_TITLE = "示例：月结练习（合成数据）"
SAMPLE_DATASET = "示例集团_2026年06月_月结套表"
SAMPLE_PERIOD = "2026-06"


def build_sample_workbook(path: Path) -> Path:
    book = Workbook()
    cover = book.active
    cover.title = "00·封面"
    cover.append(["示例集团（虚构）"])
    cover.append(["示例集团  |  2026年06月  |  月结练习套表"])
    cover.append([])
    cover.append(["说明", "全部数字为合成数据，不对应任何真实企业。应收账龄表的坏账准备分项故意与合计相差 50 万元，供练习勾稽控制与差异处置。"])

    regions = book.create_sheet("01·区域收入")
    regions.append(["区域收入"])
    regions.append(["示例集团  |  2026年06月  |  单位：万元  |  币种：人民币"])
    regions.append([])
    regions.append(["区域", "本月收入", "本月成本", "毛利率"])
    for name, revenue, cost in (("华东", 1200, 950), ("华南", 860, 700), ("华北", 640, 530)):
        regions.append([name, revenue, cost, round(1 - cost / revenue, 4)])
    regions.append(["合计", 2700, 2180, round(1 - 2180 / 2700, 4)])

    aging = book.create_sheet("02·应收账龄")
    aging.append(["应收账款账龄与坏账准备"])
    aging.append(["示例集团  |  2026年06月  |  单位：万元  |  币种：人民币"])
    aging.append([])
    aging.append(["账龄", "账面余额", "坏账准备", "计提比例"])
    for bucket, balance, provision in (("1年以内", 3000, 150), ("1至2年", 1200, 180), ("2至3年", 500, 175), ("3年以上", 300, 300)):
        aging.append([bucket, balance, provision, round(provision / balance, 4)])
    # The deliberate break: the details provide 805, the total says 755.
    aging.append(["合计", 5000, 755, round(755 / 5000, 4)])
    book.save(path)
    return path


def create_sample_task(var: Path) -> dict:
    """The practice task, created once and reused after; returns its id and whether it was new.

    The task is recognised by a marker file it carries, never by its title, so a real task that
    happens to share the title is never reused. The check and the creation hold one store lock,
    so two quick clicks make one task; a failed creation leaves no marked, half-made task behind.
    """
    tasks = TaskStore(var)
    var.mkdir(parents=True, exist_ok=True)
    with exclusive(var / "sample-task.lock"):
        for task in tasks.list("active"):
            if _marker(task).exists():
                return {"id": task.id, "created": False}
        task = tasks.create(title=SAMPLE_TITLE, period=SAMPLE_PERIOD)
        with tempfile.TemporaryDirectory() as folder:
            dataset = AnalysisStore(task).add_dataset(build_sample_workbook(Path(folder) / f"{SAMPLE_DATASET}.xlsx"), name=SAMPLE_DATASET)
        # The same reading a real import gets, so the practice run asks for the structure too.
        service = FinanceStore(task)
        service.structure_propose(dataset["id"], source=service.actor)
        _marker(task).write_text(json.dumps({"sample": True, "dataset": SAMPLE_DATASET}, ensure_ascii=False), encoding="utf-8")
    return {"id": task.id, "created": True}


def _marker(task) -> Path:
    return task.meta_path.parent / "sample-task.json"
