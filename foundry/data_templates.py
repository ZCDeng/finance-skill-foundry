"""The 补充数据模板: three small workbooks for data a finance pack often lacks and no ERP exports.

在管面积台账, 物业服务合同台账 and 人数, in ``foundry/resources/data_templates`` (written by
``tests/fixtures/templates/build_templates.py``). They are optional: a manager who already keeps these
ledgers imports their own and confirms the structure; a template is only for one who has nothing to
start from. Nothing here files them into a task: the manager fills one in and adds it like any file.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from foundry.errors import FoundryError


def templates_dir() -> Path:
    from foundry.resources import resource_dir

    return resource_dir("data_templates")


def template_names() -> list[str]:
    names = sorted(path.name for path in templates_dir().glob("*.xlsx"))
    if not names:
        raise FoundryError("the data templates are missing from this installation")
    return names


def export_templates(destination: Path) -> dict:
    """Copy the templates into a new or empty folder; an export never overwrites a file."""
    destination = Path(destination).expanduser()
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise FoundryError("choose a new or empty folder for the templates")
    names = template_names()
    destination.mkdir(parents=True, exist_ok=True)
    for name in names:
        shutil.copy2(templates_dir() / name, destination / name)
    return {"folder": str(destination), "files": names}
