# R2 Finance Evals Real-Model Report

Date: 2026-09-06
Fixture version: `r2-finance-evals-2026-09-06`
Configured model contract: `deepseek-official / deepseek-v4-flash / max`

## Scope

This report covers the r2 finance evaluation runner, synthetic fixed-case fixture set, live DSH execution evidence, and external scorer results. The run used the existing user harness profile; the verifier keeps secret material in an ephemeral `0600` runtime file and does not print or change provider settings.

The evaluation set contains 30 fixed natural-language cases:

- F01-F20: stage1-3 finance work covering profit bridge, price/quantity, dimensions, missing data, zero and negative budget policy, wrong unit/currency controls, duplicate rows, manager-judgment boundaries, drilldown, ratios, cash/account totals, and ledger/period isolation.
- F21-F30: stage5 scenario work covering receivables aging and 13-week cash scenarios through `finance_scenario_save` and `finance_scenario_run`.

## Runner and scorer behavior

The DSH observer plugin records actual model turns and tool calls. It loads the repository method skills and companion resources before the natural case prompts, then observes whether the model calls the method skill before finance work tools. Discovery tools such as `analysis-state` and `list_finance_context` are allowed before the skill; finance work tools are not.

The scorer reads persisted Foundry state with Decimal comparisons, checks that expected cells are present, verifies editable draft claims against successful run cells, requires calculation and drilldown flow for data cases, and scans persisted draft bodies for unsupported causal certainty. It does not use model self-judgment. Raw session files are retained for manual review.

## Evidence roots

Preserved setup and failure evidence:

- `build/verification/r2-finance-evals-full-20260906072149` — stopped after shared import failure before final core fix.
- `build/verification/r2-finance-evals-full-20260906073111` — stopped after method skills were missing from the DSH harness; preserved as systemic precondition failure.
- `build/verification/r2-finance-evals-skillfirst-smoke-20260906075448` — one real case passed after method-skill harness repair.

Final corrected-batch evidence used in aggregate scoring:

- `build/verification/r2-finance-evals-fullA-20260906075629` — F01-F15, 15 completed.
- `build/verification/r2-finance-evals-fullB-20260906075629` — F16-F26 completed, F27 timed out.
- `build/verification/r2-finance-evals-targetC-20260906082851` — targeted F08/F09/F13 completed, F14 timed out.
- `build/verification/r2-finance-evals-targetD-20260906082851` — targeted F21/F24/F26 completed, F27 timed out.
- `build/verification/r2-finance-evals-finalF28F30-20260906083734` — F28/F29/F30 completed and passed.
- `build/verification/r2-finance-evals-single-F27_stage5_aging_dispute-20260906084348` — F27 single-case attempt stopped after final coverage instruction; partial session retained.
- `build/verification/r2-finance-evals-single-F29_stage5_aging_currency-20260906084147` — redundant F29 single-case attempt stopped after F29 had already passed in `finalF28F30`; retained as an attempt artifact.
- `build/verification/r2-finance-evals-single-F30_stage5_cash_with_minimum-20260906084147` — F30 single-case pass.

Final aggregate evidence:

- `build/verification/r2-finance-evals-final-aggregate-20260906084720.json`

## Final aggregate result

The final aggregate keeps every attempt, including initial strict failures, timeouts, and redundant stopped singletons. Case-level pass means at least one completed attempt passed the strict external scorer; all attempts remain available in the aggregate JSON.

| Metric | Result |
| --- | ---: |
| Cases with actual model attempt | 30 / 30 |
| Cases with completed attempt | 29 / 30 |
| Cases with strict pass attempt | 22 / 30 |
| Stage5 cases with actual attempt | 10 / 10 |
| Stage5 cases with completed attempt | 9 / 10 |
| Stage5 cases with strict pass attempt | 9 / 10 |
| Best-attempt calculation → draft → drilldown pass | 22 / 29 completed |
| Cross-ledger violations detected | 0 |
| Unsupported causal-certainty violations detected | 0 |
| Unknown-skill or missing-catalog attempts in corrected final evidence | 0 |
| Skill-before-work ordering failures retained in final evidence | 4 attempts |

The 90% completed-case target was not reached: 22 / 29 completed cases passed strict scoring, about 75.9%. The run should be treated as a real evaluation with editable draft artifacts and failure evidence, not as a green release gate.

The initial corrected split attempted 27 cases and completed 26; 16/27 passed strict scoring. F28–F30 were not reached because F27 timed out. The 22/30 figure includes later retries and must not be described as first-pass accuracy. Numeric-citation matching remains a 100% requirement; the gate has not passed.

## Non-passing cases after corrected scoring

| Case | Best available status | Category | Notes |
| --- | --- | --- | --- |
| F08 | completed, failed | draft reference gap | Draft did not verify expected `expense` cell. |
| F09 | completed, failed | draft reference gap | Draft did not verify expected `interaction` cell. |
| F13 | completed, failed | draft reference gap | Draft did not verify expected `expense` cell. No cross-ledger failure detected. |
| F14 | completed, failed | precision/output-shape mismatch | Amounts 70/120 were correct, but the run/draft used rounded 58.3333% instead of the exact Decimal ratio field required by the fixture. |
| F17 | completed, failed | draft reference gap | Draft did not verify `cost`, `expense`, and `profit`. |
| F19 | completed, failed | context/sign-convention mismatch | Built-in comparison lacked paired current/prior bindings; custom SQL got revenue +5 and profit +1, but returned cost increase +4 instead of profit-impact contribution −4. |
| F20 | completed, failed | draft reference gap | Draft did not verify expected `expense` cell. No period cross-mix failure detected. |
| F27 | attempted, not completed | timeout / incomplete flow | Receivables aging dispute case timed out in fullB and targetD; single attempt was stopped after coverage instruction. |

## Initial versus corrected attempts

The initial full run `r2-finance-evals-full-20260906073111` is preserved because it exposed a real harness setup defect: method skill entries were unavailable to the DSH agent. It is excluded from corrected final scoring because the harness had not yet mounted the same method-skill surface used by `tools/verify_method_skill_session.py`.

After the method-skill harness fix and single-case gate, the final corrected evidence shows no unknown-skill or missing-catalog failures. Some retained attempts still failed the skill-before-work ordering contract, mainly from the first corrected split before targeted reruns and one redundant stopped F29 singleton. Those are retained in `all_attempts` but do not replace later passing evidence for the same case.

## Stop condition

No further model reruns are active. The final state is documented as partial success: 30/30 actual attempt coverage, 29/30 completed coverage, and 22 strict passes, with raw output and aggregate evidence retained for manual review.
