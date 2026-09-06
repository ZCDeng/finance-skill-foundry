# R2 UI bridge and first-screen fix

## Problem

The installed 0.1.3 desktop check showed two user-visible regressions in the finance manager workflow:

1. The budget bridge action sends `management_account` as a comparison dimension. The finance variance engine already emits revenue, cost, expense, and profit as metrics, so grouping by account expands a simple 120/70/20 versus 100/60/15 comparison into account-sliced rows and hides the expected four-line profit bridge.
2. On a 1280-wide first screen, the finance setup form and the open scenario section push the actual run result below the fold. The default reading order should put results first after a successful run while keeping setup and scenario controls one click away.

## Minimal fix

- Use `organization` and `period` as the default UI budget-bridge dimensions for both newly saved contexts and existing-context reruns.
- Keep the finance setup available as a collapsible details panel, open only while the manager is preparing inputs; collapse it after successful P&L, bridge, or scenario runs.
- Keep scenario controls collapsed by default so existing results occupy the first screen.
- Add regressions that prove the UI does not request account-sliced variance output and that the finance setup collapses after a successful run.

## Validation

- App UI tests for bridge dimensions and collapsed finance controls.
- App IPC test decodes the `explain-variance` spec and verifies the runnable command carries the intended dimensions.
- Full app test suite and production build/typecheck.
