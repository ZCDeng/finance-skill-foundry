---
name: bva
description: Route budget variance analysis. Use when the manager asks why profit moved versus budget or last period. Load variance-analysis and call explain_variance; do not invent IB research skills or treat this pack as a run_metric gate.
---

# /bva

Use this pack to **route** variance work onto existing tools.

## When to load

- The manager asks for a profit bridge or price-quantity bridge.
- Actual vs budget (or actual vs last period) needs a closed arithmetic story.

Do **not** refuse `run_metric` or `variance-analysis` because this pack was not loaded.

Read [forecast-models.md](../forecast-models.md) with
`method-resource {skill: "bva", resource: "forecast-models.md"}` for the F06 fixed
decomposition order and applicability, and [model-checks.md](../model-checks.md) with
`method-resource {skill: "bva", resource: "model-checks.md"}` for K09 closure and
source/period checks. Read before the dependent calculation; capability comes from
the current tool contract and verified support, not from a formula appearing here.

## Suggested path

1. Load `variance-analysis`.
2. Call `explain_variance` with explicit actual and baseline sides.
3. Keep the bridge closed, including zero contribution rows.

## Standard output

A closed profit bridge or price-quantity bridge with source-backed contributions. Not a seller tearsheet or DCF.
