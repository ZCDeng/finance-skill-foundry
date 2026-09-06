# Explanation Eval Contract

`tools/verify_finance_evals.py` now emits `scoring_contract:
r3-final-draft-text-bound-v3`. This contract differs from the r2 completion
evidence in four ways:

1. Score the latest saved draft as the canonical final explanation. If no draft
   exists, score the final assistant answer, but citation coverage still remains
   independent. The assistant answer can add context; it cannot complete missing
   numbers or citations for a saved draft.
2. Require every expected zero to appear in a real successful run row. The
   verifier no longer synthesizes zero-value facts.
3. Check financial numbers in canonical prose against referenced run cells, with
   display rounding accepted only where it is derived from the exact value. The
   prose must contain the expected financial conclusions; claims alone do not
   satisfy the text check.
4. For ordinary cases, require at least one `drilldown_fact` call to point at a
   referenced expected run row and column. When the prompt asks for a specific
   object such as profit, cost rate, voucher, or a named cell, the drilldown must
   hit that requested object.

Unsupported causal language is scanned in both the canonical explanation and the
final assistant answer. Cases that require manager judgment allow causal wording
only when the same sentence clearly labels it as manager judgment, manager
assumption, professional judgment, `user_assumption`, or
`professional_judgment`.

`whenIdle()` is not treated as proof of success. Only explicit terminal errors
(`turn/end` with error reason, `turn.failed`, or top-level `error`) count as
`turn_errors` and `hard_error_count`. Transient provider retries are reported
separately; a later explicit completed turn can recover from them. Timeouts remain
failures even if a completion event arrives later, and cancelled turns do not
count as completed. Rescoring uses the raw terminal events to correct older
observers that mistakenly treated retry chunks as final failure. The workflow numerator is `passed`; the denominator is every
selected attempted case, reported as `attempted` and `workflow_pass_rate`.
`hard_errors_status` is reported separately from `workflow_status`.

The main 30-case fixture remains `tests/fixtures/finance_evals/cases.json`.
The holdout suite is `tests/fixtures/finance_evals/holdout_cases.json`; it uses
different periods, dimensions, signs, currencies, and scenario shapes and should
be run separately from the tuned r2 fixture.

Suggested live commands:

```sh
.venv/bin/python tools/verify_finance_evals.py \
  --fixture tests/fixtures/finance_evals/cases.json \
  --output build/verification/explanation-quality-30-run-1 \
  --cases-limit 30 \
  --timeout-seconds 420 \
  --live

.venv/bin/python tools/verify_finance_evals.py \
  --fixture tests/fixtures/finance_evals/holdout_cases.json \
  --output build/verification/explanation-quality-holdout-run-1 \
  --timeout-seconds 420 \
  --live
```

For repeated independent runs, use a fresh output directory per run. The harness
also writes `session.json.checkpoint.jsonl` next to the full session report so
timeouts can be reviewed without re-reading a large JSON file.

Suggested comparison command:

```sh
.venv/bin/python tools/verify_finance_evals.py \
  --output build/verification/explanation-quality-comparison \
  --compare-verification build/verification/explanation-quality-30-run-1/verification.json \
  --compare-verification build/verification/explanation-quality-30-run-2/verification.json
```

Only compare repeated runs of the same fixture under the same
`scoring_contract` and identical per-case `input_sha256` values. The 30-case
fixture and the holdout suite should be compared in separate reports; combining
them is a portfolio summary, not a model comparison.

复评分保留原始观察目录，使用 `--rescore-observation ORIGINAL_DIR --output NEW_DIR`；留出集需另传 `--fixture tests/fixtures/finance_evals/holdout_cases.json`。核心答案仍必须在最终正文出现；其他数字仅在该稿的精确 claim 经成功 run 原值重新验证后才允许。支持千分位和明确声明单位的 Markdown 数值表格，金额按元/万元换算比较；不会把 0.58 误认成 0.58%。桥的 contribution/profit_impact 等值列按当前文稿引用解析。因果扫描排除明确的否定和待验证假设；这是规则检查，不等于专家因果判断。
