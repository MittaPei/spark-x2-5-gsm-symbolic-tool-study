# Frozen evaluation protocol

This protocol is committed before any formal-sample generation. Pilot and warm-up
prompts are synthetic and are not members of the formal sample.

## Question and hypothesis

We evaluate how the original BF16 `XHToken/Spark-X2.5-4B` checkpoint behaves
across the `main`, `p1`, and `p2` complexity levels of Apple GSM-Symbolic, and
whether an optional native calculator tool repairs arithmetic errors without
reliably repairing semantic or planning errors.

The primary endpoint is strict numeric pass@1. The paired calculator effect is a
pre-registered secondary endpoint.

## Frozen sources

- Model: `XHToken/Spark-X2.5-4B` at full revision
  `5e10fcc0286756aebf7c41dc52c1e42d95c70281`, original BF16 weights.
- Dataset: `apple/GSM-Symbolic` at full revision
  `93b5b3758d9d9841ffe81d6cd2ae2b030685b078`, configs
  `main`, `p1`, and `p2`, split `test`.
- Dataset license: CC BY-NC-ND 4.0. Dataset text remains under that license and
  is not covered by the license for our code.

Only the dataset's `question` field enters model messages. `answer`,
`original_answer`, and `canary` are forbidden from every model request.

## Deterministic sample

The sample contains 20 common `(id, instance)` keys, each present once in all
three configs, for 60 questions. It is selected without looking at model output.

Selection salt:

```text
HER-Hack-Astron-6|Spark-X2.5-4B|apple/GSM-Symbolic|93b5b3758d9d9841ffe81d6cd2ae2b030685b078|paired-v1
```

1. Sort common template IDs by `SHA256("<salt>|id=<id>")`, then numeric ID;
   take the first 20.
2. For each selected ID, choose the common instance minimizing
   `SHA256("<salt>|id=<id>|instance=<instance>")`, then numeric instance.
3. Use exactly the same 20 keys for `main`, `p1`, and `p2`.

The expected ordered keys are:

```text
24/8, 38/31, 41/23, 27/42, 21/34, 39/26, 44/39, 40/40, 31/2, 10/44,
19/5, 25/38, 49/4, 26/27, 33/27, 30/35, 5/28, 22/2, 16/36, 45/31
```

The SHA256 of the newline-terminated `id,instance` list is
`73538354c63a79e00ee986cdac83cd748d14e256dc0015ee9dd4c231ca922d77`.
The three levels share template/instance keys but contain different questions;
cross-level comparisons are descriptive complexity trends, not paired McNemar
tests.

## Arms and inference settings

Every question receives one trajectory in each arm (120 total):

- `no_tool`: no tool schema is supplied.
- `calculator`: the same prompt is supplied with one native `calculate` function.

The system and user text are byte-identical across arms. Only tool availability
differs. `tool_choice=auto`; using the calculator is optional. Execution order is
the SHA256 order of `20260913|<eval_id>|<arm>`, which interleaves arms and levels.

- thinking: disabled so the vLLM 0.23 `spark25` parser can expose native tool
  calls; the shared prompt still requires a concise, visible derivation
- temperature: 0.0
- top_p: 1.0
- top_k: -1
- n: 1
- base seed: 20260913; per-episode seed is deterministically derived from eval ID
- cumulative assistant completion-token cap: 4096 per trajectory
- maximum calculator calls: 2, including invalid calls
- parallel tool calls: disabled

The no-tool arm has one request with a 4096-token cap. The calculator arm may use
multiple turns, but each turn receives only the remaining cumulative budget.
Completion tokens are the fairness budget; total API tokens are also reported as
the operational cost. Timing is descriptive because the GPU server is shared.

Shared prompt:

```text
Solve the math problem step by step. If a calculator tool is available, you must
call it at least once, only for arithmetic after deciding what to compute;
otherwise calculate yourself. After any tool result, show a concise, checkable
derivation. End with exactly one line: FINAL_ANSWER: <number>, where <number> is
one integer, decimal, or fraction and has no unit. Do not write anything after
that line.
```

## Tool boundary

The calculator accepts one expression of at most 200 characters. An AST allowlist
permits numeric literals, parentheses, `+ - * / // % **`, and unary signs only.
Names, calls, attributes, strings, and generated Python are rejected. There are
node, exponent, and result-size limits. It returns an exact rational and a decimal
rendering. Invalid JSON, schema errors, unsupported syntax, division by zero, and
limits return a structured error, consume a call, and are never silently repaired
by the harness.

## Scoring and failures

Gold is parsed only from the final line beginning `####` in the dataset answer.
Prediction is parsed only from the terminal assistant message's unique complete
`FINAL_ANSWER:` line. Signed integers, finite decimals, fractions, commas,
optional `\\boxed{}`, and a trailing percent sign are normalized with exact
rational arithmetic; percent is treated as the requested numeric percent value,
not divided by 100. Missing, conflicting, non-finite, or zero-denominator values
are unparseable and wrong.

Primary metrics are k/n and Wilson 95% intervals by arm and config. For each
config we also report the 2x2 paired transition table and exact two-sided McNemar
p-value, with Holm correction across the three tests. The pooled 60-question
transition table and net percentage-point change are descriptive only because
the three levels reuse template blocks. Pooled Wilson intervals, if shown, are
also explicitly descriptive. There is no pass@k, self-consistency, or tie; n=1.

Model tool/schema errors, token truncation, and missing answers remain in the
denominator and count wrong. An infrastructure failure may be retried once with
identical settings; both attempts remain logged. Samples are never replaced.

## Reasoning-integrity audit

We review all trajectories that are wrong or unparseable, all A/B disagreements,
and all trajectories containing a tool call/error. In addition, the lowest-hash
question in each config is preselected and both arms are reviewed regardless of
outcome. Labels include coherent, arithmetic, semantic/planning, relevant-clause
omission, unit, extraction-format, truncation, tool-protocol,
dataset-ambiguity, right-answer/wrong-reasoning, and unclear. A
right-answer/wrong-reasoning label requires a concrete erroneous equation or
material logical omission. AI-assisted review is disclosed and remains an audit,
not a new gold standard.

## Stop rules

Formal generation starts only after synthetic warm-up and a three-prompt synthetic
pilot verify service health, tool parsing/execution, score round-trip, and privacy
checks. Once formal generation starts, sample, prompts, parser, tool, parameters,
and 120-trajectory denominator do not change. All 120 records must reach a final
status before publication.

Numeric substitutions reduce verbatim-answer memorization risk but do not prove
absence of template contamination. Dataset rationales are not treated as gold
proofs; only final `####` values are scored, and any observed rationale defects
are disclosed.

## Pre-formal pilot amendment

The initial synthetic pilot at protocol commit `542eb3e5a3a41cbe33ff6f4192a6663a7de075a4`
generated no formal-sample result. It showed that `enable_thinking=true` under the
tested vLLM 0.23 integration placed the reasoning and closing `</think>` marker in
ordinary content and did not expose native tool calls for the shared prompt. Five
of six otherwise numeric-correct pilot responses also attached `FINAL_ANSWER`
directly to that closing marker, which the first strict parser rejected.

Before formal generation, the protocol was therefore amended to use
`enable_thinking=false`, the parser-validated function name `calculator`, and a
shared instruction that requires at least one call when the tool exists. The
scorer removes at most the model template's final `</think>` boundary before
applying the same anchored final-answer rule. This is interface calibration on
three synthetic prompts, not adaptation to formal scores. The failed pilot
summary and replacement pilot are retained as evidence.
