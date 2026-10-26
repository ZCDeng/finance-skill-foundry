"""Candidate-bound finance evaluations with isolated public inputs and private scoring.

No fixture is rewritten. No provider/model preference is changed. Runtime inputs
are constructed by allowlist; oracle bytes are read only by the trusted scorer.
The live command defaults to preflight and never silently selects the first 30.
"""
from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal, InvalidOperation
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SLOT_FIELDS = ("candidate", "suite", "family", "case", "variant", "repeat")
DIMENSIONS = ("numeric_basis", "coverage", "recognition_basis", "scope_period", "assumptions", "causality", "offsets_exceptions", "authority_completion")
CALC_TOOLS = {"run_metric", "explain_variance", "finance_scenario_run", "analysis-run", "analysis-script", "analysis-script-start"}
PUBLIC_FIELDS = {"id", "question", "datasets", "attachments", "family", "variant", "category", "runnable", "stage", "required_methods", "required_resources", "input_gap_expected"}
SOURCE_METADATA_FIELDS = {"currency", "ledger", "organization", "period", "scenario", "unit", "source"}
_legacy_spec = importlib.util.spec_from_file_location("_legacy_finance_eval", ROOT / "tools/verify_finance_evals.py")
legacy = importlib.util.module_from_spec(_legacy_spec)
_legacy_spec.loader.exec_module(legacy)
_adapter_spec = importlib.util.spec_from_file_location("_finance_public_adapters", ROOT / "tools/finance_professional_adapters.py")
adapters = importlib.util.module_from_spec(_adapter_spec)
_adapter_spec.loader.exec_module(adapters)
_bootstrap_spec = importlib.util.spec_from_file_location("_finance_state_bootstrap", ROOT / "tools/finance_professional_bootstrap.py")
bootstrap = importlib.util.module_from_spec(_bootstrap_spec)
_bootstrap_spec.loader.exec_module(bootstrap)
DEPENDENCY_FILES = {"scorer": "finance_professional_eval.py", "public_adapter": "finance_professional_adapters.py",
                    "state_bootstrap": "finance_professional_bootstrap.py", "adapter_probe": "finance_professional_adapter_probe.py",
                    "legacy_scorer": "verify_finance_evals.py", "observer": "verify_finance_evals.mjs"}


def freeze_dependencies(output: Path) -> dict:
    folder = output / "evaluator-dependencies"
    folder.mkdir(exist_ok=False)
    result = {}
    for name, filename in DEPENDENCY_FILES.items():
        destination = folder / filename
        shutil.copyfile(ROOT / "tools" / filename, destination)
        result[name] = {"path": str(destination.relative_to(output)), "sha256": file_hash(destination)}
    return result


def verify_runtime_evidence(output: Path, run: dict, seed: dict | None = None) -> bool:
    """Verify retained immutable dependencies and initial state, never current var."""
    def verify_files(records):
        for relative, expected in records.items():
            path = (output / relative).resolve()
            if not path.is_relative_to(output.resolve()) or file_hash(path) != expected:
                raise ValueError("runtime evidence hash mismatch")
    try:
        dependencies = run["evaluator_dependencies"]
        if set(dependencies) != set(DEPENDENCY_FILES):
            return False
        if any(run["identities"].get(name) != item["sha256"] for name, item in dependencies.items()):
            return False
        verify_files({v["path"]: v["sha256"] for v in dependencies.values()})
        if seed is not None:
            if canonical_hash(seed) not in run.get("seed_sha256", []):
                return False
            precondition = seed.get("precondition")
            if precondition:
                verify_files(precondition["files"])
        return True
    except (KeyError, OSError, ValueError, TypeError):
        return False


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def slot_key(slot: dict[str, Any]) -> tuple:
    if set(slot) != set(SLOT_FIELDS):
        raise ValueError("slot must contain exactly candidate/suite/family/case/variant/repeat")
    if isinstance(slot["repeat"], bool) or not isinstance(slot["repeat"], int) or slot["repeat"] < 1:
        raise ValueError("repeat must be a positive integer")
    if any(not isinstance(slot[k], str) or not slot[k] for k in SLOT_FIELDS[:-1]):
        raise ValueError("slot identities must be nonempty strings")
    return tuple(slot[k] for k in SLOT_FIELDS)


def public_case(case: dict[str, Any]) -> dict[str, Any]:
    """Project fields explicitly; recursive dataset copies exclude oracle metadata."""
    output = {k: case[k] for k in PUBLIC_FIELDS - {"datasets", "attachments"} if k in case}
    if not isinstance(output.get("id"), str) or not isinstance(output.get("question"), str):
        raise ValueError("public case requires id and question")
    output["datasets"] = []
    for dataset in case.get("datasets", []):
        if not isinstance(dataset.get("rows"), list) or not isinstance(dataset.get("metadata"), dict):
            raise ValueError("public dataset requires rows and metadata")
        # metadata is source data (e.g. currency), never a case/oracle object.
        output["datasets"].append({"name": dataset["name"], "rows": dataset["rows"],
                                   "metadata": {k: v for k, v in dataset["metadata"].items() if k in SOURCE_METADATA_FIELDS}})
    if "attachments" in case:
        output["attachments"] = []
        for attachment in case["attachments"]:
            if set(attachment) != {"name", "format", "text", "metadata"} or attachment["format"] != "md" or not isinstance(attachment["text"], str):
                raise ValueError("public attachment must be a Markdown source document")
            output["attachments"].append({**attachment, "metadata": {k: v for k, v in attachment["metadata"].items() if k in SOURCE_METADATA_FIELDS}})
    return json.loads(json.dumps(output, ensure_ascii=False, allow_nan=False))


def normalized_slot(slot: dict) -> dict:
    names = dict(zip(SLOT_FIELDS, ("candidate_id", "suite_id", "family_id", "case_id", "variant_id", "repeat_index")))
    value = {key: slot[name] for key, name in names.items()}
    slot_key(value)
    return value


def professional_public(case: dict) -> dict:
    if set(case) != {"schema_version", "case_id", "task", "context", "data"}:
        raise ValueError("professional public schema contains nonpublic fields")
    if set(case["context"]) != {"currency", "unit", "purpose", "assumptions"}:
        raise ValueError("professional public context is not allowlisted")
    if any(set(row) != {"name", "value"} or not all(isinstance(v, str) for v in row.values()) for row in case["data"]):
        raise ValueError("professional data must contain only name/value strings")
    return json.loads(json.dumps(case, ensure_ascii=False, allow_nan=False))


ADAPTER_VERSION = "public-input-normalization-v1"
ADAPTED_FAMILIES = {"E01", "E03", "E04", "E18", "E19"}


def adapt_public(case: dict) -> tuple[dict, dict]:
    """Normalize business facts only. The function never accepts an oracle."""
    case = professional_public(case)
    family = case["case_id"].split("--")[0]
    if family in adapters.FAMILIES:
        return adapters.adapt(case)
    if family not in ADAPTED_FAMILIES:
        raise ValueError("blocked_backend_adapter: " + family)
    values = {row["name"]: row["value"] for row in case["data"]}
    if len(values) != len(case["data"]):
        raise ValueError("duplicate public input name")
    metadata = {"currency": case["context"]["currency"], "unit": case["context"]["unit"], "source": "synthetic frozen public fixture"}
    rows = list(case["data"])
    datasets = [{"name": "public_facts", "metadata": metadata, "rows": rows}]
    if family == "E01":
        basket = []
        for side in ("budget", "actual"):
            prices = values[side + "_prices"].split(",")
            mixes = values[side + "_mix"].split(",")
            if len(prices) != len(mixes):
                raise ValueError("public product vectors have different lengths")
            for i, (price, mix) in enumerate(zip(prices, mixes)):
                quantity = Decimal(values[side + "_volume"]) * Decimal(mix)
                basket.append({"product": f"product-{i + 1}", "scenario": side, "quantity": str(quantity),
                               "price": price, "amount": str(quantity * Decimal(price)),
                               "quantity_unit": values["quantity_unit"], "currency": metadata["currency"], "unit": metadata["unit"]})
        datasets.append({"name": "price_quantity", "metadata": metadata, "rows": basket})
    elif family == "E04" and "vat_factors" in values:
        nets, factors, receipts = (values[k].split(",") for k in ("net_revenues", "vat_factors", "cash_receipts"))
        if not len(nets) == len(factors) == len(receipts):
            raise ValueError("public tax vectors have different lengths")
        datasets.append({"name": "billing", "metadata": metadata, "rows": [
            {"business": str(i + 1), "net_revenue": n, "vat_factor": f, "cash_receipts": r, **{k: metadata[k] for k in ("currency", "unit")}}
            for i, (n, f, r) in enumerate(zip(nets, factors, receipts))]})
    elif family in {"E18", "E19"}:
        # Keep every supplied numeric input, including perturbations, as a source
        # fact. The model must decide its accounting effect; adapter adds no zero
        # assumptions, profile approvals, template outputs, or balance plugs.
        amounts = []
        for name, value in values.items():
            try:
                number = Decimal(value)
            except InvalidOperation:
                continue
            if number.is_finite():
                amounts.append({"account": name, "amount": value, "currency": metadata["currency"], "unit": metadata["unit"]})
        datasets.append({"name": "model_inputs", "metadata": metadata, "rows": amounts})
    result = {"id": case["case_id"], "question": case["task"] + "\n已提供的业务事实与限制：\n" + json.dumps({"context": case["context"], "data": case["data"]}, ensure_ascii=False)
              + "\n请先读取相关内置财务方法和配套资源，再计算并保存可追溯草稿；不要代替经理确认口径。", "datasets": datasets, "runnable": True}
    return result, {"version": ADAPTER_VERSION, "public_sha256": canonical_hash(case), "output_sha256": canonical_hash(result), "family": family}


def seed_public_cases(foundry: Path, var: Path, output: Path, selections: list[dict], *, runtime_preconditions=False) -> list[dict]:
    seeded = []
    for selected in selections:
        case = public_case(selected["public"])
        slot = selected["slot"]
        slot_key(slot)
        attempt = selected.get("attempt", 1)
        token = canonical_hash({"slot": slot, "attempt": attempt})[:20]
        task = legacy._call(foundry, var, "task-new", "--title", f"finance candidate {token}", raw=True)
        workspace = var / "tasks" / task / "analysis"
        uploads = workspace / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)
        dataset_ids = {}
        for index, dataset in enumerate(case["datasets"]):
            source = uploads / f"input-{index}.json"
            source.write_text(json.dumps(dataset["rows"], ensure_ascii=False, sort_keys=True), encoding="utf-8")
            added = legacy._call(foundry, var, "dataset-add", "--path", source, "--name", dataset["name"],
                                 "--meta", json.dumps(dataset["metadata"], ensure_ascii=False), task=task)
            dataset_ids[dataset["name"]] = added["id"]
        for index, attachment in enumerate(case.get("attachments", [])):
            source = uploads / f"document-{index}.md"
            source.write_text(attachment["text"], encoding="utf-8")
            added = legacy._call(foundry, var, "dataset-add", "--path", source, "--name", attachment["name"],
                                 "--meta", json.dumps(attachment["metadata"], ensure_ascii=False), task=task)
            dataset_ids[attachment["name"]] = added["id"]
        digest = canonical_hash(case)
        # x prevents a retry or duplicate slot from overwriting a previous input.
        with (output / f"{token}-public.json").open("x", encoding="utf-8") as sink:
            json.dump({"public": case, "slot": slot, "attempt": attempt, "public_sha256": digest}, sink, ensure_ascii=False)
        seed = {"id": token, "slot": slot, "attempt": attempt, "taskId": task,
                       "sessionId": f"finance-candidate-{token}-{task}", "workspace": str(workspace),
                       "question": case["question"], "inputSha256": digest, "datasetIds": dataset_ids}
        if runtime_preconditions and slot["case"] in bootstrap.LIVE_CASES:
            folder = output / "state-preconditions" / token
            proof = bootstrap.prepare_runtime(foundry, var, task, folder, slot["case"], dataset_ids)
            proof["files"] = {str(folder.relative_to(output) / p): h for p, h in proof["files"].items()}
            seed["precondition"] = proof
            seed["question"] += "\n工程运行前提：任务中另有明确标记的合成状态资料，用于检验状态变化和权限；它们不是原题新增业务事实或人工财务签收。请读取真实当前任务状态和来源记录。"
        seeded.append(seed)
    return seeded


def coverage(planned: list[dict], attempts: list[dict], *, fixture_hashes: dict[tuple, str] | None = None) -> dict:
    expected = [slot_key(slot) for slot in planned]
    if len(set(expected)) != len(expected):
        raise ValueError("duplicate planned slot")
    count = Counter(slot_key(row["slot"]) for row in attempts)
    extras = sorted(set(count) - set(expected))
    missing = sorted(set(expected) - set(count))
    duplicate_attempts, invalid_retries = [], []
    for key, number in count.items():
        rows = [r for r in attempts if slot_key(r["slot"]) == key]
        indices = [r.get("attempt") for r in rows]
        if len(indices) != len(set(indices)):
            duplicate_attempts.append(key)
        if indices != list(range(1, number + 1)) or number > 2:
            invalid_retries.append(key)
        elif number == 2 and not eligible_retry(rows[0]):
            invalid_retries.append(key)
    fixture_mismatches = [slot_key(row["slot"]) for row in attempts
                          if fixture_hashes is not None and (not fixture_hashes.get(slot_key(row["slot"]))
                          or row.get("fixture_sha256") != fixture_hashes[slot_key(row["slot"])])]
    valid = not (missing or extras or duplicate_attempts or invalid_retries or fixture_mismatches)
    return {"status": "passed" if valid else "failed", "planned": len(expected), "observed_slots": len(count),
            "attempts": len(attempts), "missing": missing, "extra": extras,
            "duplicate_attempts": duplicate_attempts, "invalid_retries": invalid_retries,
            "fixture_mismatches": fixture_mismatches,
            "planned_coverage": (len(set(expected) & set(count)) / len(expected)) if expected else None}


def eligible_retry(attempt: dict) -> bool:
    failure = attempt.get("failure", {})
    return attempt.get("attempt") == 1 and failure.get("category") == "infrastructure" and failure.get("confirmed") is True and bool(failure.get("evidence_sha256")) and failure.get("code") in {"transport_unavailable", "provider_5xx", "runtime_crash"}


def classify_failure(code: str, *, evidence_sha256: str | None = None) -> dict:
    if code in {"missing_credentials", "missing_runtime", "model_mismatch", "isolation_failed", "invalid_manifest"}:
        category = "preflight"
    elif code in {"transport_unavailable", "provider_5xx", "runtime_crash"} and evidence_sha256:
        category = "infrastructure"
    else:
        category = "model_or_workflow"
    return {"code": code, "category": category, "confirmed": category == "infrastructure", "evidence_sha256": evidence_sha256}


def append_attempt(path: Path, row: dict) -> None:
    existing = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    key = slot_key(row["slot"])
    same = [r for r in existing if slot_key(r["slot"]) == key]
    if row.get("attempt") != len(same) + 1 or len(same) > 1 or (same and not eligible_retry(same[0])):
        raise ValueError("attempt is duplicate, out of order, or not an eligible single infrastructure retry")
    with path.open("a", encoding="utf-8") as sink:
        sink.write(json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
        sink.flush()
        os.fsync(sink.fileno())


def skill_first(events: list[dict], *, session: str, resources: list[dict], negative: bool = False) -> dict:
    """A successful resource END must precede the first dependent calculation START."""
    selected = [e for e in events if e.get("session_id") == session]
    seqs = [e.get("seq") for e in selected]
    failures = []
    if any(type(s) is not int for s in seqs) or seqs != sorted(set(seqs)):
        return {"status": "failed", "failures": ["invalid_sequence"], "negative_case": negative, "calculation_count": 0}
    if seqs != sorted(set(seqs)):
        failures.append("invalid_sequence")
    starts = {e.get("call_id"): e for e in selected if e.get("phase") == "start"}
    if None in starts or len(starts) != len([e for e in selected if e.get("phase") == "start"]):
        failures.append("invalid_call_identity")
    for event in selected:
        if event.get("phase") == "end":
            start = starts.get(event.get("call_id"))
            if not start or start.get("name") != event.get("name") or start.get("arguments_sha256") != event.get("arguments_sha256") or start["seq"] >= event["seq"]:
                failures.append("unmatched_tool_end")
    calculations = [e for e in selected if e.get("phase") == "start" and e.get("name") in CALC_TOOLS]
    if not calculations:
        if not negative:
            failures.append("no_calculation")
    else:
        first = min(e["seq"] for e in calculations)
        for resource in resources:
            matches = [e for e in selected if e.get("phase") == "end" and not e.get("is_error")
                       and e.get("seq", first) < first and e.get("name") == resource["tool"]
                       and all(e.get("arguments", {}).get(k) == v for k, v in resource["arguments"].items())
                       and e.get("content_sha256") == resource["sha256"]]
            if not matches:
                failures.append("resource_not_read_before_calculation:" + resource["tool"])
    return {"status": "passed" if not failures else "failed", "failures": failures,
            "negative_case": negative, "calculation_count": len(calculations)}


def exact_decimal(actual: Any, expected: Any) -> bool:
    try:
        a, b = Decimal(str(actual)), Decimal(str(expected))
        return a.is_finite() and b.is_finite() and a == b
    except (InvalidOperation, ValueError):
        return False


def score_contract(observed: dict, oracle: dict) -> dict:
    """Deterministic gates; semantic/human dimensions remain separate and unscored."""
    errors = []
    for name, value in oracle.get("amounts", {}).items():
        if not exact_decimal(observed.get("amounts", {}).get(name), value):
            errors.append("amount:" + name)
    for name, value in oracle.get("assertions", {}).items():
        if observed.get("assertions", {}).get(name) != value:
            errors.append("assertion:" + name)
    for field in ("invalid_references", "fabricated_citations", "unauthorized_actions", "missing_required_checks", "false_completion", "critical_errors"):
        if observed.get(field):
            errors.append(field)
    # Missing verification is never the same as a clean output.
    if observed.get("verification_complete") is not True:
        errors.append("verification_incomplete")
    if oracle.get("input_gap_expected") is False and observed.get("input_gap_reported"):
        errors.append("false_input_gap")
    if oracle.get("input_gap_expected") is True and not observed.get("input_gap_reported"):
        errors.append("missing_input_gap")
    return {"status": "passed" if not errors else "failed", "errors": errors,
            "human_dimensions": {d: None for d in DIMENSIONS}}


def isolation_probe(foundry: Path, plugin: Path, output: Path) -> dict:
    """Exercise real model-facing tools and OS sandbox without invoking a model."""
    node = shutil.which("node")
    if not node or not foundry.is_file() or not (plugin / "analysis.js").is_file():
        return {"status": "failed", "reason": "missing_runtime"}
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="finance-oracle-isolation-") as temp:
        root = Path(temp).resolve()
        private = root / "private"
        private.mkdir(mode=0o700)
        canary = private / "oracle.json"
        canary.write_text(json.dumps({"secret": uuid.uuid4().hex}), encoding="utf-8")
        var = root / "var"
        task = legacy._call(foundry, var, "task-new", "--title", "oracle isolation probe", raw=True)
        workspace = var / "tasks" / task / "analysis"
        upload = workspace / "uploads" / "public.json"
        upload.parent.mkdir(parents=True)
        upload.write_text('[{"amount":"7"}]', encoding="utf-8")
        session = "finance-isolation-" + uuid.uuid4().hex
        legacy._call(foundry, var, "record-session", "--role", "analysis", "--workspace", workspace, task=task, session=session)
        # The canary's location is known to this trusted probe, never live config.
        code = "import json\nfrom pathlib import Path\ntry:\n Path(" + repr(str(canary)) + ").read_text()\n print('ORACLE_READABLE')\nexcept PermissionError:\n print('ORACLE_DENIED')\n"
        repository_oracle = ROOT / "tests/fixtures/finance_evals/professional/private/oracles/E18--base.json"
        if not repository_oracle.is_file():
            return {"status": "failed", "reason": "actual_repository_oracle_probe_target_missing"}
        repository_code = code.replace(repr(str(canary)), repr(str(repository_oracle)))
        script = """import {{definitions}} from __PLUGIN__;
const tools = Object.fromEntries(definitions().map(d => [d.name,d]));
const exec = {{agent: {{id: __SESSION__}}}};
const call = async (name,args) => {{ try {{ return {{ok:true,value:JSON.parse((await tools[name].execute(args,exec)).stdout)}}; }} catch {{return {{ok:false}};}} }};
const legalResource = await call('method-resource',{{skill:'variance-analysis',resource:'FOUNDRY.md'}});
const forbiddenResource = await call('method-resource',{{skill:'variance-analysis',resource:__PRIVATE__}});
const forbiddenDataset = await call('dataset-add',{{path:__PRIVATE__,name:'forbidden'}});
const repositoryResource = await call('method-resource',{{skill:'variance-analysis',resource:__REPOSITORY_ORACLE__}});
const repositoryDataset = await call('dataset-add',{{path:__REPOSITORY_ORACLE__,name:'forbidden_repository'}});
const legalDataset = await call('dataset-add',{{path:__UPLOAD__,name:'public'}});
const scriptResult = legalDataset.ok ? await call('analysis-script',{{spec:{{bindings:{{public:legalDataset.value.id}},code:__CODE__}}}}) : {{ok:false}};
const repositoryScript = legalDataset.ok ? await call('analysis-script',{{spec:{{bindings:{{public:legalDataset.value.id}},code:__REPOSITORY_CODE__}}}}) : {{ok:false}};
const legalScript = legalDataset.ok ? await call('analysis-script',{{spec:{{bindings:{{public:legalDataset.value.id}},code:"import os,json\\nfrom pathlib import Path\\nprint(json.loads((Path(os.environ['FOUNDRY_INPUTS'])/'public.json').read_text())['rows'][0]['amount'])"}}}}) : {{ok:false}};
const checks = {{method_resource_allowed:legalResource.ok,method_resource_denied:!forbiddenResource.ok,
dataset_allowed:legalDataset.ok,dataset_denied:!forbiddenDataset.ok,
repository_method_resource_denied:!repositoryResource.ok,repository_dataset_denied:!repositoryDataset.ok,
repository_script_denied:repositoryScript.ok && repositoryScript.value.execution_status==='succeeded' && repositoryScript.value.stdout.trim()==='ORACLE_DENIED',
script_denied:scriptResult.ok && scriptResult.value.execution_status==='succeeded' && scriptResult.value.stdout.trim()==='ORACLE_DENIED',
script_allowed:legalScript.ok && legalScript.value.execution_status==='succeeded' && legalScript.value.stdout.trim()==='7'}};
console.log(JSON.stringify({{checks,runner_status:scriptResult.value?.runner_status??null}}));"""
        script = script.replace("{{", "{").replace("}}", "}")
        for marker, value in {"__PLUGIN__": (plugin / "analysis.js").resolve().as_uri(), "__SESSION__": session,
                              "__PRIVATE__": str(canary), "__UPLOAD__": str(upload), "__CODE__": code,
                              "__REPOSITORY_ORACLE__": str(repository_oracle), "__REPOSITORY_CODE__": repository_code}.items():
            script = script.replace(marker, json.dumps(value))
        result = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True,
                                timeout=90, env=legacy._clean_env({"FOUNDRY_VAR": str(var), "FOUNDRY_BIN": str(foundry.resolve())}))
        try:
            evidence = json.loads(result.stdout)
        except json.JSONDecodeError:
            evidence = {"checks": {}, "reason": "probe_execution_failed", "exit_code": result.returncode,
                        "diagnostic": result.stderr[-2000:].replace(str(root), "<probe-root>")}
        evidence["status"] = "passed" if len(evidence.get("checks", {})) == 9 and all(evidence["checks"].values()) else "failed"
        evidence["probe_sha256"] = hashlib.sha256(script.encode()).hexdigest()
        evidence["scope"] = "actual plugin tool wrappers to CLI and OS sandbox; temporary canary plus actual repository private oracle; no provider call"
        (output / "isolation.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        return evidence


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_hash(path: Path, *, suffixes: set[str] | None = None) -> str:
    files = sorted(p for p in path.rglob("*") if p.is_file() and "__pycache__" not in p.parts
                   and (suffixes is None or p.suffix in suffixes))
    return canonical_hash({str(p.relative_to(path)): file_hash(p) for p in files})


def load_selections(manifest_path: Path, *, cases: list[str], repeat: int | None, smoke: bool) -> tuple[dict, list[dict]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    base = manifest_path.parent
    for relative, digest in manifest["artifact_hashes"].items():
        if file_hash(base / relative) != digest:
            raise ValueError("frozen artifact hash mismatch: " + relative)
    legacy_suites = {}
    for suite in manifest["legacy_suites"]:
        path = ROOT / suite["path"]
        if file_hash(path) != suite["sha256"]:
            raise ValueError("legacy fixture was changed: " + suite["suite_id"])
        legacy_suites[suite["suite_id"]] = (suite, json.loads(path.read_text(encoding="utf-8")))
    slots = manifest["planned_slots"]
    if smoke and not cases:
        raise ValueError("--smoke requires explicit --case-id; never defaults to the first cases")
    if (cases or repeat is not None) and not smoke:
        raise ValueError("partial selection requires --smoke")
    selected = [s for s in slots if (not cases or s["case_id"] in cases) and (repeat is None or s["repeat_index"] == repeat)]
    if not selected or set(cases) - {s["case_id"] for s in selected}:
        raise ValueError("selection is empty or contains unknown case IDs")
    variants = {v["case_id"]: v for v in json.loads((base / "variant_manifest.json").read_text())["variants"]}
    result = []
    for row in selected:
        slot = normalized_slot(row)
        item = {"slot": slot, "fixture_sha256": row["fixture_sha256"], "status": "ready"}
        if slot["suite"] == "professional_development":
            variant = variants[slot["case"]]
            public = professional_public(json.loads((base / variant["public_input"]).read_text()))
            # Oracle stays in this scorer's memory and never enters runtime config.
            item["oracle"] = json.loads((base / variant["private_oracle"]).read_text())
            item["oracle_sha256"] = variant["private_oracle_sha256"]
            item["high_risk"] = variant["high_risk"]
            try:
                item["public"], item["adapter"] = adapt_public(public)
                readiness = item["adapter"].get("readiness", {})
                if readiness.get("runtime_readiness", "candidate").startswith("blocked_"):
                    item.update(status=readiness["runtime_readiness"], reason="; ".join(readiness["blockers"]))
            except ValueError as exc:
                item.update(status="blocked_backend_adapter", reason=str(exc))
        else:
            suite, fixture = legacy_suites[slot["suite"]]
            case = next(c for c in fixture["cases"] if c["id"] == slot["case"])
            item.update(public=public_case(case), legacy_case=case, original_model=suite["fixture_model_contract"],
                        interpretation="compatibility_regression")
        result.append(item)
    return manifest, result


def model_selection(contract: dict) -> dict:
    return {"provider": contract.get("provider"), "model": contract.get("model"), "reasoningEffort": contract.get("reasoning_effort", contract.get("reasoningEffort"))}


def load_engineering(path: Path, candidate: str, cases: list[str]) -> list[dict]:
    """Read new, explicitly bounded source attachments without changing formal slots."""
    manifest = json.loads(path.read_text())
    base = path.parent
    for relative, digest in manifest["artifact_hashes"].items():
        if file_hash(base / relative) != digest:
            raise ValueError("engineering artifact hash mismatch")
    selected = [c for c in manifest["cases"] if not cases or c["case_id"] in cases]
    if not selected or set(cases) - {c["case_id"] for c in selected}:
        raise ValueError("unknown engineering case")
    results = []
    for item in selected:
        public = base / "public" / item["case_id"]
        request = json.loads((public / "request.json").read_text())
        if set(request) != {"case_id", "context", "schema_version", "synthetic_scenario_declarations", "task"}:
            raise ValueError("engineering public request not allowlisted")
        datasets = []
        for filename in ("template_inputs.json", "model_boundary.json"):
            content = json.loads((public / filename).read_text())
            datasets.append({"name": content["dataset_alias"], "metadata": content["metadata"], "rows": content["rows"]})
        private = item["original_private_oracle"]
        if file_hash(ROOT / private["path"]) != private["sha256"]:
            raise ValueError("original oracle hash mismatch")
        case = public_case({"id": item["case_id"], "datasets": datasets,
                            "question": request["task"] + "\n" + json.dumps({"context": request["context"], "synthetic_scenario_declarations": request["synthetic_scenario_declarations"]}, ensure_ascii=False)
                            + "\n先读取内置financial-statements方法和FOUNDRY.md再分析。边界声明是合成来源，不是经理确认。"})
        results.append({"slot": {"candidate": candidate, "suite": "engineering_smoke", "family": item["original_case_id"].split("--")[0],
                                  "case": item["case_id"], "variant": "closed_template", "repeat": 1},
                        "public": case, "oracle": json.loads((ROOT / private["path"]).read_text()),
                        "fixture_sha256": canonical_hash({p: manifest["artifact_hashes"][p] for p in item["public_files"]}),
                        "oracle_sha256": private["sha256"], "status": "ready", "high_risk": True,
                        "interpretation": "engineering_augmentation_not_formal_283_or_blind",
                        "adapter": {"version": manifest["schema_version"], "output_sha256": canonical_hash(case)}})
    return results


def required_resources(selection: dict, root: Path) -> list[dict]:
    family = selection["slot"]["family"]
    skill = adapters.METHODS.get(family, {"E04": "cash"}.get(family))
    if not skill:
        return []
    skill_text = (root / skill / "SKILL.md").read_text(encoding="utf-8")
    # DSH exposes skill body after frontmatter, while method manifest hashes the
    # complete file. Bind both instead of comparing unlike byte sequences.
    body = skill_text.split("---", 2)[2].strip() if skill_text.startswith("---") else skill_text.strip()
    resources = [{"tool": "skill", "arguments": {"name": skill}, "sha256": hashlib.sha256(body.encode()).hexdigest(),
                  "file_sha256": file_hash(root / skill / "SKILL.md")}]
    for resource in adapters.RESOURCES.get(family, []):
        resources.append({"tool": "method-resource", "arguments": {"skill": skill, "resource": resource}, "sha256": file_hash(root / resource)})
    return resources


def launch_runtime(args: argparse.Namespace, selections: list[dict], model: dict, methods: dict, *, seeded=None) -> dict:
    """Launch the installed DSH runtime with only the allowlisted public seeds."""
    import yaml
    settings = yaml.safe_load((args.credentials_home / "settings.yaml").read_text()) or {}
    configured = settings.get("agent-default-model")
    if configured != model:
        raise ValueError("model_mismatch: candidate override must equal the current user selection; no provider changed")
    credentials = yaml.safe_load((args.credentials_home / ".credentials.yaml").read_text()) or {}
    reference = settings.get("llm-deepseek", {}).get("apiKeyEnv", "DEEPSEEK_API_KEY")
    refs = credentials.get("refs", credentials)
    if not refs.get(reference):
        raise ValueError("missing_credentials")
    if seeded is None:
        raise ValueError("live requires initial state frozen in the run manifest before launch")
    # Controller state files and hashes are retained outside model-readable roots.
    runtime_cases = [{k: v for k, v in row.items() if k != "precondition"} for row in seeded]
    config = {"dshRoot": str(args.dsh_root.resolve()), "report": str(args.output / "session.json"),
              "timeoutSeconds": args.timeout_seconds, "maxToolTurns": args.max_tool_turns,
              "expectedModel": model, "ids": methods["ids"], "cases": runtime_cases}
    # Explicit projection above means even future oracle fields cannot cross.
    child = None
    with tempfile.TemporaryDirectory(prefix="finance-professional-runtime-") as text:
        scratch = Path(text).resolve()
        home = scratch / "harness"
        home.mkdir()
        config["agentsHome"] = str(scratch / "agents")
        credential = home / ".credentials.yaml"
        with os.fdopen(os.open(credential, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
            yaml.safe_dump({"version": credentials.get("version", 1), "refs": {reference: refs[reference]}}, stream)
        selected_settings = {"agent-default-model": configured, "agent-presets": {"default": "analysis"}}
        if "llm-deepseek" in settings:
            selected_settings["llm-deepseek"] = settings["llm-deepseek"]
        (home / "settings.yaml").write_text(yaml.safe_dump(selected_settings))
        env = legacy._clean_env({"DSH_HOME": str(home), "DSH_AGENTS_HOME": config["agentsHome"],
                                 "DSH_BUNDLED_SKILL_DIR": methods["root"], "FOUNDRY_VAR": str(args.output / "var"),
                                 "FOUNDRY_BIN": str(args.foundry)})
        node = shutil.which("node")
        dsh = args.dsh_root / "node_modules/@deepseek-ai/dsh/lib/bin.js"
        legacy._call(args.foundry, args.output / "var", "install-presets", "--dsh-home", home, raw=True)
        subprocess.run([node, str(dsh), "--profile", "web", "--dump-config"], env=env, cwd=scratch, capture_output=True, check=True, timeout=60)
        probe = scratch / "probe"
        probe.mkdir()
        shutil.copyfile(ROOT / "tools/verify_finance_evals.mjs", probe / "index.mjs")
        (probe / "config.json").write_text(json.dumps(config, ensure_ascii=False))
        # Retain only the public configuration hash, not a private fixture path.
        (args.output / "runtime-public-config.sha256").write_text(canonical_hash(config) + "\n")
        profile = home / "profiles/web"
        package_path = profile / "package.json"
        package = json.loads(package_path.read_text())
        package.setdefault("dependencies", {})["finance-skill-foundry-dsh"] = f"link:{args.plugin}"
        bundles = package.setdefault("dsh", {}).setdefault("profile", {}).setdefault("bundles", [])
        if "finance-skill-foundry-dsh" not in bundles:
            bundles.append("finance-skill-foundry-dsh")
        package_path.write_text(json.dumps(package))
        modules = profile / "node_modules"
        modules.mkdir(exist_ok=True)
        plugin_link = modules / "finance-skill-foundry-dsh"
        if not plugin_link.exists():
            plugin_link.symlink_to(args.plugin, target_is_directory=True)
        (profile / "cordis.patch.yml").write_text(yaml.safe_dump([{"insert": [{"id": "foundry-finance-evals-verifier", "name": str(probe / "index.mjs")}]}]))
        try:
            with (args.output / "runtime.log").open("x") as stream:
                child = subprocess.Popen([node, str(dsh), "--profile", "web", "--no-open", "--port", "0"], cwd=scratch,
                                         env=env, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    observed = legacy._wait_report(child, args.output / "session.json", args.batch_timeout_seconds, cases=runtime_cases)
                except (RuntimeError, TimeoutError) as exc:
                    session_path = args.output / "session.json"
                    observed = json.loads(session_path.read_text()) if session_path.exists() else {"cases": [], "model": configured}
                    observed["runner_failure"] = {"category": "unclassified", "message": str(exc)}
        finally:
            legacy._stop(child)
    if observed["model"] != configured:
        raise ValueError("runtime changed the user model")
    return {"observation": observed, "seeded": seeded}


METRIC_ALIASES = {"volume": ["volume_contribution"], "mix": ["mix_contribution"], "price": ["price_contribution"], "total": ["total_variance"],
                  "current": ["collection_rate_current", "current_year_collection_rate", "current_collection_rate"],
                  "comprehensive": ["collection_rate_total", "comprehensive_collection_rate"],
                  "CFO": ["cfo", "operating_cash_flow", "cash_flow_operating"], "CFI": ["cfi", "investing_cash_flow", "cash_flow_investing"], "CFF": ["cff", "financing_cash_flow", "cash_flow_financing"],
                  "cash": ["closing_cash"], "ar": ["closing_ar", "closing_receivables"], "ppe": ["closing_ppe"], "ap": ["closing_ap", "closing_payables"],
                  "debt": ["closing_debt"], "equity": ["closing_equity"], "assets": ["total_assets"], "liabilities_equity": ["total_liabilities_equity"]}


GAP_CASES = {"E03--zero_denominator", "E04--missing_tax_basis"}


def expected_gap(oracle: dict) -> bool:
    # expected_trigger describes the fixture's rule trigger, not whether a
    # calculation is appropriate. Only reviewed case-specific routes apply.
    return oracle.get("case_id") in GAP_CASES


def legal_workflow(state: dict, row: dict, *, allow_gap: bool = False) -> dict:
    draft = row.get("final_draft") or {}
    try:
        if not legacy._case_completed(row):
            raise AssertionError("runtime turn did not complete normally")
        if not draft or draft != legacy._latest_draft(state):
            raise AssertionError("observed final draft differs from the frozen state")
        content = {k: draft.get(k) for k in ("title", "requirements_id", "materiality", "body", "body_template", "document", "run_ids", "fact_ids", "claims", "limitations")}
        if legacy._sha(content) != draft.get("content_hash"):
            raise AssertionError("final draft content hash does not bind its body and claims")
        current = state.get("requirements", [{}])[-1]
        if current.get("semantic_version") == 2:
            verify_professional_v2(state, draft, current)
        else:
            legacy._verify_r4_contract(state, draft, {}, allow_missing_data=allow_gap)
        quality = draft.get("explanation_check", draft.get("quality", {}))
        if quality.get("status") != "pass":
            raise AssertionError("final draft quality is not pass")
    except (AssertionError, KeyError, IndexError, TypeError, ValueError) as exc:
        return {"completed": False, "reason": str(exc)}
    return {"completed": True, "reason": "bound latest requirements, quality and persistent completion receipt"}


def verify_professional_v2(state: dict, draft: dict, current: dict) -> None:
    """Verify the frozen server-authored v2 chain without weakening legacy R4."""
    datasets = legacy._datasets_by_id(state)
    requirements = {r["id"]: r for r in state.get("requirements", [])}
    def fingerprint(record):
        identity = (record.get("semantic_basis") or {}).get("professional_identity") or {}
        rule_hash = legacy._sha({"version": 1, "dependencies": identity.get("rule_dependencies"), "basis": identity.get("rule_basis")})
        if not identity.get("rule_dependencies") or rule_hash != identity.get("rule_fingerprint"):
            raise AssertionError("invalid professional rule identity")
        basis = legacy._r4_canonical_requirement_basis(record, datasets)
        basis.update(version=2, professional_identity=identity)
        if basis != record.get("semantic_basis") or legacy._sha(basis) != record.get("semantic_fingerprint"):
            raise AssertionError("professional requirement fields or sources do not match fingerprint")
        return record["semantic_fingerprint"]
    current_fp = fingerprint(current)
    if draft.get("requirements_id") != current.get("id") or current.get("seq", 0) >= draft.get("seq", 0):
        raise AssertionError("professional draft is not bound to prior latest requirements")
    runs = {r["id"]: r for r in state.get("runs", [])}
    for run_id in draft.get("run_ids", []):
        run = runs[run_id]
        original = requirements[run["requirements_id"]]
        if (fingerprint(original) != current_fp or run.get("requirements_semantic_fingerprint") != current_fp
                or original.get("seq", 0) >= run.get("seq", 0) or not legacy._r4_run_inputs_match_requirement(run, original)):
            raise AssertionError("professional run is not bound to current semantic sources")
        identity = run.get("professional_identity") or run.get("requirements_rule_identity") or {}
        if identity.get("rule_fingerprint") != current["semantic_basis"]["professional_identity"]["rule_fingerprint"]:
            raise AssertionError("professional run rule identity differs from requirement")
    quality = draft.get("explanation_check", {})
    required = quality.get("requirements", {})
    if (required.get("requirements_id") != current["id"] or required.get("coverage", {}).get("status") != "pass"
            or required.get("provenance", {}).get("status") != "pass"):
        raise AssertionError("professional requirement coverage or provenance is not pass")
    receipts = [r for r in state.get("completions", []) if r.get("draft_id") == draft["id"]]
    receipt = receipts[-1] if receipts else {}
    if (receipt.get("status") != "complete" or receipt.get("requirements_id") != current["id"]
            or receipt.get("draft_content_hash") != draft["content_hash"] or receipt.get("requirements_semantic_fingerprint") != current_fp):
        raise AssertionError("professional completion receipt is not complete and bound")


def read_snapshot(source: Path, row: dict) -> dict:
    ref = row.get("state_snapshot") or {}
    name = ref.get("path", "")
    if not name or Path(name).name != name:
        raise ValueError("original state snapshot is absent or unsafe")
    path = source / name
    if file_hash(path) != ref.get("sha256"):
        raise ValueError("original state snapshot hash mismatch")
    return json.loads(path.read_text())


def score_professional_artifact(state: dict, oracle: dict, row: dict) -> dict:
    """Check named, cited result cells; never accept a number merely appearing somewhere."""
    draft = row.get("final_draft") or {}
    claims = draft.get("claims", [])
    runs = {r["id"]: r for r in state.get("runs", []) if r.get("execution_status") == "succeeded"}
    failures, cells = [], {}
    for claim in claims:
        if claim.get("basis") not in (None, "calculation"):
            continue
        run = runs.get(claim.get("run_id"))
        try:
            if type(claim["row"]) is not int or claim["row"] < 0:
                raise ValueError("invalid row index")
            value = run["result"]["rows"][claim["row"]][claim["column"]]
            if not exact_decimal(claim.get("value"), value):
                raise ValueError("claim mismatch")
        except (KeyError, TypeError, IndexError, ValueError):
            failures.append("invalid_calculation_reference")
    for check in oracle.get("numeric_checks", []):
        metric = check["metric"]
        names = {metric, *METRIC_ALIASES.get(metric, [])}
        candidates = []
        for claim in claims:
            if claim.get("basis") != "calculation":
                continue
            run = runs.get(claim.get("run_id"))
            try:
                result_row = run["result"]["rows"][claim["row"]]
                column = claim["column"]
                value = result_row[column]
            except (KeyError, TypeError, IndexError):
                continue
            named = column in names or (column == "value" and any(result_row.get(k) in names for k in ("metric", "metric_key", "driver", "name")))
            if named and exact_decimal(claim.get("value"), value):
                candidates.append((claim, value))
        if not candidates:
            failures.append("missing_cited_metric:" + metric)
            continue
        if not all(exact_decimal(value, check["expected"]) for _, value in candidates):
            failures.append("wrong_metric:" + metric)
        cells[metric] = [{k: claim.get(k) for k in ("run_id", "row", "column", "value")} for claim, _ in candidates]
    if not row.get("completed"):
        failures.append("turn_incomplete")
    if not draft:
        failures.append("no_saved_draft")
    workflow = legal_workflow(state, row, allow_gap=expected_gap(oracle))
    # Behavioral oracles are intentionally not inferred from prose keywords.
    # Until a backend gap adapter exists, even a plausible refusal needs review.
    behavior_unknown = not oracle.get("numeric_checks")
    contract = score_contract({"verification_complete": not behavior_unknown and workflow["completed"],
                               "invalid_references": [x for x in failures if x == "invalid_calculation_reference"]}, {})
    status = "failed" if failures else "needs_review" if behavior_unknown else "passed" if contract["status"] == "passed" else "failed"
    return {"status": status, "numeric_errors": failures, "cited_cells": cells,
            "workflow": workflow, "legal_workflow_completed": workflow["completed"], "deterministic_contract": contract,
            "behavioral_verification": "not_implemented_needs_review" if behavior_unknown else "requires_human_semantic_review",
            "check_scope": "named_cited_numeric_cells_and_reference_integrity; recognition and business semantics require human review",
            "professional_semantics": "requires_independent_review", "human_dimensions": {d: None for d in DIMENSIONS},
            "oracle_knowledge_status": oracle.get("knowledge_status"), "oracle_human_review_status": oracle.get("human_review_status")}


def rescore(source: Path, output: Path, *, foundry: Path, reason: str, manifest_path: Path,
            engineering_manifest: Path | None = None) -> dict:
    """Re-score immutable observations without a provider call or attempt rewrite."""
    if not reason.strip():
        raise ValueError("an explicit rescore reason is required")
    source = source.resolve()
    previous = json.loads((source / "run-manifest.json").read_text())
    if file_hash(foundry) != previous["identities"]["foundry_entry"]:
        raise ValueError("rescore must read state with the same frozen Foundry executable")
    if file_hash(manifest_path) != previous["identities"]["frozen_manifest"]:
        raise ValueError("rescore must use the original frozen fixture manifest")
    identities = previous["identities"]
    if identities.get("candidate_source_manifest"):
        candidate_path = foundry.parent / "candidate-source.json"
        if file_hash(candidate_path) != identities["candidate_source_manifest"]:
            raise ValueError("candidate source manifest changed")
        for relative, digest in json.loads(candidate_path.read_text())["files"].items():
            if file_hash(candidate_path.parent / relative) != digest:
                raise ValueError("candidate implementation changed: " + relative)
    elif identities.get("foundry_source") != tree_hash(ROOT / "foundry", suffixes={".py"}):
        raise ValueError("rescore candidate source identity is missing or changed")
    observed = json.loads((source / "session.json").read_text())
    if observed.get("status") == "running":
        raise ValueError("cannot rescore a running observation")
    _, all_selections = load_selections(manifest_path, cases=[], repeat=None, smoke=False)
    if previous["mode"] == "engineering_smoke":
        if engineering_manifest is None:
            raise ValueError("engineering rescore requires the original engineering manifest")
        all_selections = load_engineering(engineering_manifest.resolve(), previous["candidate"], [])
    selections = {slot_key(s["slot"]): s for s in all_selections}
    runtime_method_root = Path(observed["runtime"]["bundled_root"])
    if tree_hash(runtime_method_root) != previous["identities"]["methods"]:
        raise ValueError("candidate method resources changed after observation")
    by_slot = {slot_key(r["slot"]): r for r in observed.get("cases", [])}
    attempts = [json.loads(line) for line in (source / "attempts.jsonl").read_text().splitlines() if line.strip()]
    output_rows = []
    for slot in previous["selected_slots"]:
        selection = selections[slot_key(slot)]
        row = by_slot.get(slot_key(slot))
        if row is None:
            score = {"status": "failed", "errors": ["missing_observation"]}
        else:
            original_attempt = next((a for a in attempts if a.get("slot") == slot and a.get("attempt") == row.get("attempt", 1)), {})
            if original_attempt.get("evidence_sha256") != canonical_hash(row):
                raise ValueError("original observation does not match the recorded attempt hash")
            if not row.get("state_snapshot") or original_attempt.get("state_snapshot_sha256") != row["state_snapshot"]["sha256"]:
                score = {"status": "unsupported", "errors": ["no_original_bound_state_snapshot"],
                         "evidence_limit": "current mutable state was not read; same-evidence numeric rescore is unsupported"}
            else:
                state = read_snapshot(source, row)
                if "legacy_case" in selection:
                    case = {**selection["legacy_case"], "id": row["id"], "taskId": row["task_id"],
                            "sessionId": row["session_id"], "inputSha256": row["input_sha256"]}
                    score = legacy.score_observation(foundry, source / "var", [case], {"cases": [row]},
                        scoring_contract=legacy.SCORING_CONTRACT_R4, state_snapshots={row["task_id"]: state})
                else:
                    score = score_professional_artifact(state, selection["oracle"], row)
            if "oracle" in selection:
                score["skill_first"] = skill_first(row.get("tool_events", []), session=row["session_id"],
                                                   resources=required_resources(selection, runtime_method_root), negative=expected_gap(selection["oracle"]))
                if score["skill_first"]["status"] != "passed" and score["status"] == "passed":
                    score["status"] = "failed"
        output_rows.append({"slot": slot, "attempt": (row or {}).get("attempt", 1), "new_score": score,
                            "original_observation_sha256": canonical_hash(row) if row else None})
    result = {"kind": "offline_rescore_not_new_model_attempt", "reason": reason,
              "previous_scorer_sha256": previous["identities"]["scorer"], "new_scorer_sha256": file_hash(Path(__file__)),
              "original_run_manifest_sha256": file_hash(source / "run-manifest.json"),
              "original_session_sha256": file_hash(source / "session.json"),
              "original_attempts_sha256": file_hash(source / "attempts.jsonl") if (source / "attempts.jsonl").exists() else None,
              "previous_results_unchanged": True, "provider_calls": 0, "rows": output_rows,
              "passed_automated": sum(r["new_score"]["status"] == "passed" for r in output_rows),
              "professional_acceptance": "not_accepted_without_release_gates"}
    with (output / "rescore.json").open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "tests/fixtures/finance_evals/professional/release_manifest.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("prepare", "isolation", "adapter-probe", "state-probe", "live"), default="prepare")
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--repeat-index", type=int)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--engineering-manifest", type=Path, help="separate public augmentation; never counts toward formal frozen slots")
    parser.add_argument("--candidate-source", type=Path, help="frozen candidate-source.json with hashes of every packaged source file")
    parser.add_argument("--rescore", type=Path, help="offline rescore of a completed run; preserves original attempts and scores")
    parser.add_argument("--rescore-reason", default="")
    parser.add_argument("--foundry", type=Path, default=legacy.DEFAULT_FOUNDRY)
    parser.add_argument("--plugin", type=Path, default=legacy.DEFAULT_PLUGIN)
    parser.add_argument("--dsh-root", type=Path, default=legacy.DEFAULT_DSH_ROOT)
    parser.add_argument("--credentials-home", type=Path, default=legacy.DEFAULT_CREDENTIALS_HOME)
    parser.add_argument("--timeout-seconds", type=int, default=420)
    parser.add_argument("--max-tool-turns", type=int, default=80)
    parser.add_argument("--max-tasks", type=int, default=300)
    parser.add_argument("--batch-timeout-seconds", type=int, default=7200)
    args = parser.parse_args()
    for name in ("foundry", "plugin", "dsh_root", "credentials_home", "manifest", "output"):
        setattr(args, name, getattr(args, name).resolve())
    if not all(getattr(args, name) > 0 for name in ("timeout_seconds", "max_tool_turns", "max_tasks", "batch_timeout_seconds")):
        parser.error("all limits must be positive")
    args.output.mkdir(parents=True, exist_ok=False)
    if args.rescore:
        result = rescore(args.rescore, args.output, foundry=args.foundry, reason=args.rescore_reason,
                         manifest_path=args.manifest, engineering_manifest=args.engineering_manifest)
        print(json.dumps({"kind": result["kind"], "passed_automated": result["passed_automated"], "rows": len(result["rows"]),
                          "provider_calls": 0, "output": str(args.output)}, ensure_ascii=False))
        return 0 if result["passed_automated"] == len(result["rows"]) else 1
    if args.mode == "isolation":
        result = isolation_probe(args.foundry, args.plugin, args.output)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["status"] == "passed" else 1
    manifest, selections = load_selections(args.manifest, cases=[] if args.engineering_manifest else args.case_id,
                                           repeat=None if args.engineering_manifest else args.repeat_index,
                                           smoke=False if args.engineering_manifest else args.smoke)
    if args.engineering_manifest:
        if not args.smoke or args.repeat_index is not None:
            parser.error("engineering runs require --smoke and keep repeat 1")
        selections = load_engineering(args.engineering_manifest.resolve(), manifest["candidate_id"], args.case_id)
    if len(selections) > args.max_tasks:
        raise ValueError("selected slots exceed frozen task limit")
    methods = legacy._call(args.foundry, args.output / "var", "method-skills", "--json")
    model = model_selection(manifest["actual_model_contract"])
    dependencies = freeze_dependencies(args.output)
    identities = {"foundry_entry": file_hash(args.foundry), "plugin": tree_hash(args.plugin, suffixes={".js", ".json", ".yml"}),
                  "dsh_lock": file_hash(args.dsh_root / "package-lock.json"), "dsh_pin": file_hash(args.dsh_root / "PIN"),
                  "methods": tree_hash(Path(methods["root"])), "observer": file_hash(ROOT / "tools/verify_finance_evals.mjs"),
                  "scorer": file_hash(Path(__file__)), "public_adapter": file_hash(ROOT / "tools/finance_professional_adapters.py"),
                  "frozen_manifest": file_hash(args.manifest)}
    identities.update({name: value["sha256"] for name, value in dependencies.items()})
    if args.candidate_source:
        candidate_source = args.candidate_source.resolve()
        source_manifest = json.loads(candidate_source.read_text())
        for relative, digest in source_manifest["files"].items():
            if file_hash(candidate_source.parent / relative) != digest:
                raise ValueError("candidate source changed: " + relative)
        identities["candidate_source_manifest"] = file_hash(candidate_source)
    # Development CLI depends on Python source beyond its tiny entry script.
    if args.foundry == legacy.DEFAULT_FOUNDRY.resolve():
        identities["foundry_source"] = tree_hash(ROOT / "foundry", suffixes={".py"})
    for selected in selections:
        selected["required_resources"] = required_resources(selected, Path(methods["root"]))
    seeded = None
    if args.mode in {"live", "state-probe"}:
        blocked = [s["slot"] for s in selections if s["status"] != "ready"]
        if blocked:
            raise ValueError(f"blocked_backend_adapter: {len(blocked)} selected slots; use an explicit supported smoke subset")
        if args.mode == "live":
            isolated = isolation_probe(args.foundry, args.plugin, args.output)
            if isolated["status"] != "passed":
                raise ValueError("isolation_failed: live invocation refused")
        seeded = seed_public_cases(args.foundry, args.output / "var", args.output, selections, runtime_preconditions=True)
        with (args.output / "initial-seeds.json").open("x") as stream:
            json.dump(seeded, stream, ensure_ascii=False, indent=2)
    run_manifest = {"version": 2, "candidate": manifest["candidate_id"], "mode": "engineering_smoke" if args.engineering_manifest else "smoke_subset" if args.smoke else "full_planned",
                    "planned_slots": [normalized_slot(s) for s in manifest["planned_slots"]],
                    "selected_slots": [s["slot"] for s in selections], "identities": identities,
                    "evaluator_dependencies": dependencies, "seed_sha256": [canonical_hash(s) for s in seeded or []],
                    "initial_seeds_sha256": file_hash(args.output / "initial-seeds.json") if seeded else None,
                    "model": model, "legacy_model_contracts": manifest["legacy_suites"],
                    "limits": {"timeout_seconds": args.timeout_seconds, "max_tool_turns": args.max_tool_turns,
                               "max_tasks": args.max_tasks, "batch_timeout_seconds": args.batch_timeout_seconds,
                               "max_confirmed_infrastructure_retry": 1, "request_token_cost_limit": None,
                               "request_token_cost_limit_reason": "not exposed by verified runtime; elapsed time and tool/task caps enforced"},
                    "adapters": [{"slot": s["slot"], "status": s["status"], "adapter": s.get("adapter"), "required_resources": s["required_resources"]} for s in selections],
                    "human_review": "not_started", "unseen20": "not_created"}
    (args.output / "run-manifest.json").write_text(json.dumps(run_manifest, ensure_ascii=False, indent=2) + "\n")
    if args.mode == "state-probe":
        checked = [verify_runtime_evidence(args.output, run_manifest, seed) for seed in seeded]
        result = {"kind": "initial_runtime_state_probe", "status": "passed" if all(checked) else "failed",
                  "provider_calls": 0, "formal_attempts": 0, "selected": len(seeded), "verified_initial_states": sum(checked)}
        (args.output / "state-probe.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result))
        return 0 if all(checked) else 1
    if args.mode == "adapter-probe":
        probe_spec = importlib.util.spec_from_file_location("_finance_adapter_probe", ROOT / "tools/finance_professional_adapter_probe.py")
        probe_module = importlib.util.module_from_spec(probe_spec)
        probe_spec.loader.exec_module(probe_module)
        # Explicit controller helpers only; no credential read or launch_runtime.
        from types import SimpleNamespace
        result = probe_module.probe(SimpleNamespace(seed_public_cases=seed_public_cases), args.foundry, args.output, selections)
        print(json.dumps({"kind": result["kind"], "cases": len(result["cases"]), "passed_capability_probes": result["passed_capability_probes"], "provider_calls": 0}))
        return 0 if result["passed_capability_probes"] == len(result["cases"]) else 1
    if args.mode == "prepare":
        print(json.dumps({"status": "prepared", "selected": len(selections), "planned": len(manifest["planned_slots"]),
                          "adapter_ready": sum(s["status"] == "ready" for s in selections), "output": str(args.output)}, ensure_ascii=False))
        return 0
    if not all(verify_runtime_evidence(args.output, run_manifest, seed) for seed in seeded or []):
        raise ValueError("runtime initial state or dependency changed before provider launch")
    result = launch_runtime(args, selections, model, methods, seeded=seeded)
    observed = result["observation"]
    observed_by_id = {r["id"]: r for r in observed["cases"]}
    for selection, seed in zip(selections, result["seeded"]):
        row = observed_by_id.get(seed["id"], {})
        try:
            state = read_snapshot(args.output, row)
        except (ValueError, OSError) as exc:
            state = None
            score = {"status": "failed", "errors": ["missing_or_invalid_state_snapshot:" + str(exc)]}
        if state is not None and "legacy_case" in selection:
            scored_case = {**selection["legacy_case"], **seed}
            score = legacy.score_observation(args.foundry, args.output / "var", [scored_case], {"cases": [row]}, scoring_contract=legacy.SCORING_CONTRACT_R4,
                                             state_snapshots={seed["taskId"]: state})
        elif state is not None:
            score = score_professional_artifact(state, selection["oracle"], row)
            timing = skill_first(row.get("tool_events", []), session=seed["sessionId"], resources=selection["required_resources"],
                                 negative=expected_gap(selection["oracle"]))
            score["skill_first"] = timing
            if timing["status"] != "passed":
                score["status"] = "failed"
        attempt = {"slot": selection["slot"], "attempt": 1, "completed": legacy._case_completed(row),
                   "session_id": seed["sessionId"], "task_id": seed["taskId"], "fixture_sha256": selection["fixture_sha256"],
                   "public_sha256": seed["inputSha256"], "score": score, "usage": row.get("usage"),
                   "seed_sha256": canonical_hash(seed), "precondition_sha256": canonical_hash(seed["precondition"]) if seed.get("precondition") else None,
                   "evidence_sha256": canonical_hash(row), "critical_error_count": None,
                   "legal_workflow_completed": legal_workflow(state, row, allow_gap=expected_gap(selection.get("oracle", {})))["completed"] if state is not None else False,
                   "state_snapshot_sha256": (row.get("state_snapshot") or {}).get("sha256"),
                   "run_manifest_sha256": canonical_hash(run_manifest), "identities": identities,
                   "human_review": "not_reviewed", "interpretation": selection.get("interpretation", "development_professional_smoke")}
        if not attempt["completed"]:
            attempt["failure"] = classify_failure("model_timeout_or_workflow_error")
        append_attempt(args.output / "attempts.jsonl", attempt)
    attempts = [json.loads(line) for line in (args.output / "attempts.jsonl").read_text().splitlines()]
    summary = {"status": "observed_not_professionally_accepted", "mode": run_manifest["mode"],
               "selected_coverage": coverage(run_manifest["selected_slots"], attempts, fixture_hashes={slot_key(s["slot"]): s["fixture_sha256"] for s in selections}),
               "release_coverage": coverage(run_manifest["planned_slots"], [a for a in attempts if a["slot"]["suite"] != "engineering_smoke"],
                                            fixture_hashes={slot_key(normalized_slot(s)): s["fixture_sha256"] for s in manifest["planned_slots"]}),
               "passed_automated": sum(a["score"]["status"] == "passed" for a in attempts),
               "attempts": len(attempts), "human_review": "not_reviewed", "unseen20": "not_created"}
    (args.output / "verification.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "release_coverage"}, ensure_ascii=False))
    return 0 if summary["passed_automated"] == len(attempts) else 1


if __name__ == "__main__":
    raise SystemExit(main())
