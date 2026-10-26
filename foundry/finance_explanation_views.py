"""Versioned writing and inspection views over the same authorized fact catalog.

This presentation boundary does not grant evidence eligibility. Validators,
source locators and saved appendices continue to use the complete catalog.
"""

from foundry.errors import FoundryError
from foundry.finance_driver_templates import TEMPLATE_ID, TEMPLATE_INPUTS, TEMPLATE_VERSION


def validate_fact_view(view):
    if not isinstance(view, str) or view not in {"writing", "inspection"}:
        raise FoundryError("fact_view must be writing or inspection")
    return view


def _native_input_fact(fact, runs):
    run = runs.get(fact.get("run_id"), {})
    result = run.get("result") or {}
    if (run.get("engine") != "finance" or run.get("execution_status") != "succeeded"
            or result.get("template_id") != TEMPLATE_ID
            or result.get("template_version") != TEMPLATE_VERSION
            or fact.get("column") != "value"):
        return False
    index = fact.get("row")
    rows = result.get("rows") or []
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(rows):
        return False
    row = rows[index]
    # Only registered input rows move into the source-inspection collection.
    # Unknown rows and unapproved outputs stay visible in the writing collection;
    # neither client labels nor eligibility flags decide membership.
    return (isinstance(row, dict) and row.get("driver") in TEMPLATE_INPUTS
            and row.get("depends_on") == [] and not row.get("metric_key"))


def explanation_fact_view(prepared, runs, view="writing"):
    view = validate_fact_view(view)
    by_run = {run["id"]: run for run in runs}
    writing_facts, input_facts = [], []
    for fact in prepared.get("facts", []):
        (input_facts if _native_input_fact(fact, by_run) else writing_facts).append(fact)
    return {
        **prepared,
        "schema_version": 2,
        "fact_view": view,
        "facts": prepared["facts"] if view == "inspection" else writing_facts,
        "input_facts": input_facts,
        "fact_view_contract": {
            "partition_basis": "registered_native_row_role",
            "all_fact_count": len(prepared["facts"]),
            "writing_fact_count": len(writing_facts),
            "input_fact_count": len(input_facts),
            "eligibility_unchanged": True,
        },
    }
