from __future__ import annotations

from pathlib import Path
from typing import Any

from foundry.brief import emit_brief
from foundry.errors import FoundryError, QueryRefused
from foundry.launch_formulator import launch_formulator
from foundry.probe import run_probe
from foundry.query import query_locked
from foundry.questions import record_questions
from foundry.window import Window, WindowStore

REQUIRED_TOOLS = (
    "import",
    "lock",
    "record-questions",
    "emit-brief",
    "launch-formulator",
    "query-locked",
    "re-import",
)
HOST_WRITERS = frozenset({"bash", "dsh-tool-fs", "str-replace-editor"})
F3_TOOLS = frozenset({"query-locked"})
STATE_TOOLS = {
    "Open": frozenset({"import", "lock"}),
    "Imported": frozenset({"import", "lock"}),
    "Locked": frozenset({"record-questions", "emit-brief", "launch-formulator", "re-import"}),
    "Briefed": frozenset({"query-locked", "re-import"}),
    "FollowUp": frozenset({"query-locked", "re-import"}),
}


class HostProfile:
    def __init__(self, name: str, tools: list[str] | tuple[str, ...]) -> None:
        self.name = name
        self.tools = set(tools)
        writers = self.tools & HOST_WRITERS
        if writers:
            raise FoundryError(f"period profile must omit host writers: {sorted(writers)}")
        if name == "period":
            missing = [tool for tool in REQUIRED_TOOLS if tool not in self.tools]
            if missing:
                raise FoundryError(f"foundry plugin startup failed; missing tools: {','.join(missing)}")
        if name == "f3" and self.tools != F3_TOOLS:
            raise FoundryError("F3 allowlist is query-locked only")

    @classmethod
    def period(cls) -> HostProfile:
        return cls("period", REQUIRED_TOOLS)

    @classmethod
    def f3(cls) -> HostProfile:
        return cls("f3", tuple(F3_TOOLS))

    def deny_path(self, path: Path) -> bool:
        if self.name != "f3":
            return False
        text = str(path)
        return "catalog.duckdb" in text or "/formulator/" in text or text.endswith("/formulator")

    def execute(self, window: Window, tool: str, **payload: Any) -> Any:
        if tool not in self.tools:
            raise QueryRefused(f"{self.name} cannot execute {tool}")
        if self.name == "f3" and tool != "query-locked":
            raise QueryRefused(f"F3 cannot execute {tool}")
        allowed = STATE_TOOLS.get(window.state, frozenset())
        if self.name == "period" and tool not in allowed:
            raise QueryRefused(f"{tool} refused in state {window.state}")
        if tool == "import":
            return window.import_tables(
                coa=Path(payload["coa"]),
                units=Path(payload["units"]),
                named=payload["named"],
                drop_dir=Path(payload["drop_dir"]) if payload.get("drop_dir") else None,
            )
        if tool == "lock":
            return window.lock()
        if tool == "record-questions":
            record_questions(window, payload["questions"])
            return None
        if tool == "emit-brief":
            return emit_brief(window)
        if tool == "launch-formulator":
            return launch_formulator(window)
        if tool == "query-locked":
            return query_locked(
                window,
                payload["text"],
                required_table_ids=payload["required_table_ids"],
                split_by=payload.get("split_by"),
                brief_window_id=payload.get("brief_window_id"),
            )
        if tool == "re-import":
            return window.reimport(
                coa=Path(payload["coa"]),
                units=Path(payload["units"]),
                named=payload["named"],
                drop_dir=Path(payload["drop_dir"]) if payload.get("drop_dir") else None,
            )
        raise FoundryError(f"unknown tool {tool}")


def host_smoke(var_root: Path, fixtures: Path) -> int:
    HostProfile.period()
    return run_probe(var_root, fixtures)
