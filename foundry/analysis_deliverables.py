"""The analysis half of 成果库: the newest draft of each revision chain, and every filed export.

Read-only. The drafts and export receipts already carry the review and
publication state this listing shows (KTD11); nothing here writes a status of
its own, and nothing here names a file to the caller except the one export
path it resolves from a digest the task itself filed.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from foundry.analysis import REPORT_EXPORT_FORMATS, AnalysisStore
from foundry.errors import FoundryError
from foundry.report_projection import _review_marker

SHA256 = re.compile(r"^[0-9a-f]{64}$")
MANIFEST_SUFFIX = ".meta.json"


def _manifests(store: AnalysisStore) -> list[tuple[Path, dict]]:
    """Every export receipt: `analysis-export` files md and xlsx beside `registered/`, the register files the rest."""
    found = []
    for folder in (store.root / "exports" / "registered", store.root / "exports"):
        folder = store._inside(folder)
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*" + MANIFEST_SUFFIX)):
            found.append((path, store._read(path)))
    return found


def _exported_file(store: AnalysisStore, manifest_path: Path) -> Path:
    return store._inside(manifest_path.with_name(manifest_path.name[: -len(MANIFEST_SUFFIX)]))


def list_analysis_deliverables(store: AnalysisStore) -> dict:
    drafts = store._list("drafts")
    # The number the 文稿 tab shows as 修订 N: position among all of this task's drafts.
    position = {draft["id"]: index + 1 for index, draft in enumerate(drafts)}
    by_id = {draft["id"]: draft for draft in drafts}

    def root(draft: dict) -> str:
        seen = set()
        while draft.get("parent_id") in by_id and draft["id"] not in seen:
            seen.add(draft["id"])
            draft = by_id[draft["parent_id"]]
        return draft["id"]

    chains: dict[str, list[dict]] = {}
    for draft in drafts:
        chains.setdefault(root(draft), []).append(draft)
    # Only the newest version of each chain; `chains` holds them in position order.
    newest = [(chain[-1], len(chain)) for chain in chains.values()]
    listed = [
        {
            "draft_id": draft["id"],
            "revision": position[draft["id"]],
            "versions": versions,
            "title": draft.get("title", ""),
            "created_at": draft["created_at"],
            "seq": draft.get("seq", 0),
            "review_status": draft["review_status"],
            "publication_status": draft["publication_status"],
        }
        for draft, versions in sorted(newest, key=lambda pair: position[pair[0]["id"]])
    ]

    exports = []
    for _path, manifest in _manifests(store):
        source = by_id.get(manifest.get("draft_id"))
        if source is None:
            raise FoundryError(f"export receipt {manifest.get('id')} names a draft this task does not hold")
        if manifest.get("format") not in REPORT_EXPORT_FORMATS:
            raise FoundryError(f"export receipt {manifest.get('id')} has an unknown format")
        exports.append(
            {
                "export_id": manifest["id"],
                "draft_id": source["id"],
                "revision": position[source["id"]],
                "title": source.get("title", ""),
                "format": manifest["format"],
                "content_mode": manifest.get("content_mode"),
                "sha256": manifest["sha256"],
                "created_at": manifest["created_at"],
                # The state of the revision it was exported from, which is immutable.
                "review_status": source["review_status"],
                "publication_status": source["publication_status"],
                "review_marker": _review_marker(source),
            }
        )
    return {"task_id": store.task.id, "drafts": listed, "exports": exports}


def export_path(store: AnalysisStore, sha256: str, format: str) -> Path:
    """Where this task filed one export, from its digest and format and nothing else.

    The caller never names a path. A digest this task did not file, or one filed
    under a different format, reaches nothing; a file whose bytes no longer match
    their receipt is refused rather than handed to the operator's software.
    """
    if not isinstance(sha256, str) or not SHA256.fullmatch(sha256):
        raise FoundryError(f"not a sha256: {sha256}")
    if format not in REPORT_EXPORT_FORMATS:
        raise FoundryError(f"not an export format: {format}")
    for manifest_path, manifest in _manifests(store):
        if manifest.get("sha256") != sha256 or manifest.get("format") != format:
            continue
        target = _exported_file(store, manifest_path)
        if target.suffix != "." + format or not target.is_file() or target.is_symlink():
            raise FoundryError(f"export {sha256}.{format} is missing from task {store.task.id}")
        if hashlib.sha256(target.read_bytes()).hexdigest() != sha256:
            raise FoundryError("report export integrity check failed; archived bytes differ from their receipt")
        return target.resolve()
    raise FoundryError(f"no registered export {sha256}.{format} on task {store.task.id}")
