#!/usr/bin/env python3
"""Seed a synthetic reportVisual task through the packaged Foundry CLI.

The fixture intentionally creates real datasets, analysis runs, chart deliverables,
and a saved draft whose reportVisual nodes are materialized by the server. It does
not call any model/provider surface and only writes inside the caller-provided
work/evidence roots.
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
from hashlib import sha256
from pathlib import Path
from typing import Any


def run_json(bin_path: str, prefix: list[str], var_root: Path, task_id: str | None, command: str, args: list[str]) -> Any:
    cmd = [bin_path, *prefix, "--var", str(var_root)]
    if task_id:
        cmd += ["--task", task_id]
    cmd += [command, *args]
    completed = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if completed.returncode != 0:
        raise RuntimeError(f"Foundry command failed ({completed.returncode}): {cmd}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}")
    out = completed.stdout.strip()
    if command == "task-new":
        return {"id": out}
    return json.loads(out)


def node_text(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def paragraph(text: str) -> dict[str, Any]:
    return {"type": "paragraph", "content": [node_text(text)]}


def heading(level: int, text: str) -> dict[str, Any]:
    return {"type": "heading", "attrs": {"level": level}, "content": [node_text(text)]}


def visual_node(visual: dict[str, Any]) -> dict[str, Any]:
    return {"type": "reportVisual", "attrs": {"visual": visual}}


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--foundry-bin", required=True)
    parser.add_argument("--var-root", required=True)
    parser.add_argument("--foundry-prefix", default="[]", help="JSON array inserted after foundry-bin, e.g. [\"run\",\"python\",\"-m\",\"foundry.cli\"]")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--title", default="reportVisual 桌面验收")
    ns = parser.parse_args()

    foundry = ns.foundry_bin
    prefix = json.loads(ns.foundry_prefix)
    if not isinstance(prefix, list) or not all(isinstance(item, str) for item in prefix):
        raise SystemExit("--foundry-prefix must be a JSON string array")
    var_root = Path(ns.var_root).resolve()
    out_dir = Path(ns.out_dir).resolve()
    fixtures = out_dir / "fixtures"
    var_root.mkdir(parents=True, exist_ok=True)
    fixtures.mkdir(parents=True, exist_ok=True)

    task = run_json(foundry, prefix, var_root, None, "task-new", ["--title", ns.title, "--period", "2026-09"])
    task_id = task["id"]

    rows = [
        {"sort": "1", "item": "华东", "month": "2026-01", "actual": "120.123456", "budget": "100", "delta": "20.123456", "cash": "120.123456"},
        {"sort": "2", "item": "华南", "month": "2026-02", "actual": "0", "budget": "88.5000", "delta": "-88.5000", "cash": "0"},
        {"sort": "3", "item": "华北", "month": "2026-03", "actual": "-45.6700", "budget": "20", "delta": "-65.6700", "cash": "-45.6700"},
        {"sort": "4", "item": "西部", "month": "2026-04", "actual": "", "budget": "30.0001", "delta": "", "cash": ""},
        {"sort": "5", "item": "总部共享", "month": "2026-05", "actual": "123456789.987654", "budget": "123456700.123456", "delta": "89.864198", "cash": "123456789.987654"},
    ]
    source = fixtures / "report-visual-values.csv"
    write_csv(source, rows)
    source_hash = sha256(source.read_bytes()).hexdigest()

    dataset = run_json(foundry, prefix, var_root, task_id, "dataset-add", [
        "--path", str(source),
        "--name", "reportVisual 合成数值",
        "--meta", json.dumps({"period": "2026-H1", "unit": "万元", "currency": "CNY", "scenario": "actual"}, ensure_ascii=False),
    ])

    bar_analysis = run_json(foundry, prefix, var_root, task_id, "analysis-save", ["--spec", json.dumps({
        "question": "区域预算差异条形图验收",
        "sql": "SELECT item AS \"项目\", actual AS \"本期\", budget AS \"预算\", delta AS \"差异\" FROM actual ORDER BY CAST(sort AS INTEGER)",
        "parameters": [],
        "bindings": {"actual": dataset["id"]},
        "metrics": [{"name": "本期", "currency": "CNY"}],
        "result_role": "business",
        "scope": {"period": "2026-H1", "currency": "CNY", "unit": "万元"},
    }, ensure_ascii=False)])
    bar_run = run_json(foundry, prefix, var_root, task_id, "analysis-run", ["--analysis", bar_analysis["id"]])
    bar_chart = run_json(foundry, prefix, var_root, task_id, "chart-deliverable-save", ["--spec", json.dumps({
        "run_id": bar_run["id"],
        "label": "区域预算差异验收图",
    }, ensure_ascii=False)])

    line_analysis = run_json(foundry, prefix, var_root, task_id, "analysis-save", ["--spec", json.dumps({
        "question": "月度现金流折线图验收",
        "sql": "SELECT month AS \"月份\", cash AS \"现金流\", budget AS \"预算线\" FROM actual ORDER BY CAST(sort AS INTEGER)",
        "parameters": [],
        "bindings": {"actual": dataset["id"]},
        "metrics": [{"name": "现金流", "currency": "CNY"}],
        "result_role": "business",
        "scope": {"period": "2026-H1", "currency": "CNY", "unit": "万元"},
    }, ensure_ascii=False)])
    line_run = run_json(foundry, prefix, var_root, task_id, "analysis-run", ["--analysis", line_analysis["id"]])
    line_chart = run_json(foundry, prefix, var_root, task_id, "chart-deliverable-save", ["--spec", json.dumps({
        "run_id": line_run["id"],
        "label": "月度现金流缺失值验收图",
    }, ensure_ascii=False)])

    forged_series = {
        "columns": [{"name": "项目"}, {"name": "本期"}],
        "rows": [{"项目": "伪造", "本期": "999999"}],
    }
    document = {
        "schema_version": 1,
        "template_version": "annual-v1",
        "metadata": {"company": "华宸物业", "period": "2026-H1", "currency": "CNY", "unit": "万元"},
        "content": [
            heading(1, "reportVisual 验收报告"),
            paragraph("REPORT-VISUAL-MARKER-001：本稿由合成 fixture 通过真实 CLI 保存，不调用模型。"),
            visual_node({
                "version": 1, "kind": "bar", "title": "区域预算差异（含负数零值缺失）", "takeaway": "负数、零值、缺失和高精度金额必须在图表与降级数据中一致。",
                "chart_id": bar_chart["id"], "category": "项目", "value_columns": ["本期", "预算"], "unit": "万元",
                "series": forged_series, "run_id": "0" * 32, "snapshot_hash": "f" * 64, "source_label": "伪造来源必须被覆盖",
            }),
            visual_node({
                "version": 1, "kind": "line", "title": "月度现金流趋势（含缺失点）", "takeaway": "缺失值应作为空点，不得变成 0。",
                "chart_id": line_chart["id"], "category": "月份", "value_columns": ["现金流", "预算线"], "unit": "万元",
            }),
            visual_node({
                "version": 1, "kind": "flow", "title": "预算复核流程", "takeaway": "流程图为作者分析，不作为计算事实。", "source_label": "作者分析",
                "steps": [
                    {"label": "读取资料", "detail": "登记合成 CSV 并冻结快照", "connector": "形成计算口径"},
                    {"label": "生成结果", "detail": "固化 run 与 chart_id", "connector": "写入文稿图表"},
                    {"label": "经理阅读", "detail": "导出五格式并核对", "connector": ""},
                ],
            }),
            paragraph("REPORT-VISUAL-END-MARKER-001"),
        ],
    }
    draft_spec = {
        "title": "reportVisual 验收草稿",
        "body": "reportVisual 验收草稿",
        "document": document,
        "run_ids": [bar_run["id"], line_run["id"]],
        "claims": [],
        "limitations": ["合成 fixture，仅用于桌面验收。"],
    }
    spec_path = fixtures / "draft-spec.json"
    spec_path.write_text(json.dumps(draft_spec, ensure_ascii=False, indent=2), encoding="utf-8")
    draft = run_json(foundry, prefix, var_root, task_id, "analysis-draft", ["--spec-file", str(spec_path)])
    saved_visuals = [node["attrs"]["visual"] for node in draft["document"]["content"] if node.get("type") == "reportVisual"]

    manifest = {
        "task_id": task_id,
        "task_title": ns.title,
        "draft_id": draft["id"],
        "draft_title": draft["title"],
        "dataset": {"id": dataset["id"], "path": str(source), "sha256": source_hash},
        "bar": {"analysis_id": bar_analysis["id"], "run_id": bar_run["id"], "chart_id": bar_chart["id"], "rows": bar_run["result"]["rows"]},
        "line": {"analysis_id": line_analysis["id"], "run_id": line_run["id"], "chart_id": line_chart["id"], "rows": line_run["result"]["rows"]},
        "draft": {"id": draft["id"], "title": draft["title"], "content_hash": draft.get("content_hash"), "document": draft["document"]},
        "expected_text": [
            "REPORT-VISUAL-MARKER-001", "REPORT-VISUAL-END-MARKER-001", "区域预算差异（含负数零值缺失）", "月度现金流趋势（含缺失点）", "预算复核流程",
            "华东", "华南", "华北", "西部", "总部共享", "120.123456", "-45.6700", "0", "123456789.987654", "缺失",
        ],
        "forbidden_text": ["伪造来源必须被覆盖", "999999"],
        "saved_visuals": saved_visuals,
    }
    manifest_path = out_dir / "fixture-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"manifest": str(manifest_path), **{k: manifest[k] for k in ("task_id", "draft_id", "task_title", "draft_title")}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
