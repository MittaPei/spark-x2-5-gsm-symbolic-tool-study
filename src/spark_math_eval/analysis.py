"""Deterministically score and summarize a complete formal run."""

from __future__ import annotations

import json
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from . import DATASET_REVISION, MODEL_REVISION
from .runner import (
    CALCULATOR_POLICY,
    CALCULATOR_TOOL,
    DIRECT_POLICY,
    SYSTEM_PROMPT,
    episode_seed,
    job_order,
    sha256_text,
)
from .scoring import exact_mcnemar_p, extract_gold, extract_prediction, wilson_interval

ARMS = ("no_tool", "calculator")
CONFIGS = ("main", "p1", "p2")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _round(value: float) -> float:
    return round(value, 6)


def _binomial(successes: int, total: int) -> dict[str, Any]:
    low, high = wilson_interval(successes, total)
    return {
        "correct": successes,
        "total": total,
        "accuracy": _round(successes / total),
        "accuracy_percent": round(100 * successes / total, 2),
        "wilson_95": [_round(low), _round(high)],
    }


def score_record(record: dict[str, Any], sample: dict[str, Any]) -> dict[str, Any]:
    gold_raw, gold = extract_gold(str(sample["answer"]))
    prediction_raw, prediction, parse_error = extract_prediction(
        record.get("terminal_content")
    )
    status = str(record.get("status"))
    correct = status == "completed" and prediction is not None and prediction == gold
    tool_calls = list(record.get("tool_calls", []))
    terminal_content = record.get("terminal_content")
    executor_successful_calls = sum(
        bool(call.get("result", {}).get("ok")) for call in tool_calls
    )
    executor_errors = len(tool_calls) - executor_successful_calls
    return {
        "eval_id": record["eval_id"],
        "config": record["config"],
        "id": record["id"],
        "instance": record["instance"],
        "arm": record["arm"],
        "status": status,
        "correct": correct,
        "gold": gold_raw,
        "prediction": prediction_raw,
        "parse_error": parse_error,
        "finish_reason": record.get("turns", [{}])[-1].get("finish_reason"),
        "tool_calls": len(tool_calls),
        "executor_successful_calls": executor_successful_calls,
        "executor_errors": executor_errors,
        "terminal_tool_markup": bool(
            isinstance(terminal_content, str) and "<tool_call>" in terminal_content
        ),
        "required_calculator_call_adherence": (
            bool(tool_calls) if record["arm"] == "calculator" else None
        ),
        "completion_tokens": int(record.get("total_completion_tokens", 0)),
        "prompt_tokens": int(record.get("total_prompt_tokens", 0)),
        "total_tokens": int(record.get("total_completion_tokens", 0))
        + int(record.get("total_prompt_tokens", 0)),
        "wall_seconds": record.get("wall_seconds"),
        "infra_retries": len(record.get("infra_attempt_errors", [])),
        "raw_record_sha256": sha256_text(
            json.dumps(record, ensure_ascii=False, sort_keys=True)
        ),
    }


def holm_adjust(p_values: dict[str, float]) -> dict[str, float]:
    ordered = sorted(p_values.items(), key=lambda item: (item[1], item[0]))
    adjusted: dict[str, float] = {}
    running = 0.0
    total = len(ordered)
    for rank, (name, value) in enumerate(ordered):
        running = max(running, min(1.0, value * (total - rank)))
        adjusted[name] = _round(running)
    return adjusted


def paired_table(rows: list[dict[str, Any]]) -> dict[str, int]:
    by_eval: dict[str, dict[str, bool]] = {}
    for row in rows:
        by_eval.setdefault(row["eval_id"], {})[row["arm"]] = bool(row["correct"])
    if any(set(pair) != set(ARMS) for pair in by_eval.values()):
        raise ValueError("each eval_id must have both arms")
    table = {
        "both_correct": 0,
        "direct_policy_only_correct": 0,
        "calculator_policy_only_correct": 0,
        "both_wrong": 0,
    }
    for pair in by_eval.values():
        direct, tool = pair["no_tool"], pair["calculator"]
        if direct and tool:
            table["both_correct"] += 1
        elif direct:
            table["direct_policy_only_correct"] += 1
        elif tool:
            table["calculator_policy_only_correct"] += 1
        else:
            table["both_wrong"] += 1
    return table


def validate_formal_records(
    records: list[dict[str, Any]], selected: list[dict[str, Any]]
) -> dict[str, str]:
    sample_map = {row["eval_id"]: row for row in selected}
    if len(selected) != 60 or len(sample_map) != 60:
        raise ValueError("selected excerpt must contain 60 unique eval_id values")
    if Counter(str(row.get("config")) for row in selected) != Counter(
        {config: 20 for config in CONFIGS}
    ):
        raise ValueError("selected excerpt must contain 20 rows per config")
    expected = {(eval_id, arm) for eval_id in sample_map for arm in ARMS}
    observed = [(row.get("eval_id"), row.get("arm")) for row in records]
    if len(records) != 120 or set(observed) != expected or len(set(observed)) != 120:
        raise ValueError(
            f"formal run must contain exact 120 unique jobs; got {len(records)} "
            f"missing={len(expected - set(observed))} "
            f"extra={len(set(observed) - expected)}"
        )

    protocol_commits = {str(row.get("protocol_commit")) for row in records}
    if len(protocol_commits) != 1 or protocol_commits == {"None"}:
        raise ValueError("formal records must share one protocol commit")
    for record in records:
        sample = sample_map[record["eval_id"]]
        arm = record["arm"]
        expected_policy = CALCULATOR_POLICY if arm == "calculator" else DIRECT_POLICY
        expected_settings = {
            "thinking": False,
            "temperature": 0.0,
            "top_p": 1.0,
            "top_k": -1,
            "n": 1,
            "max_cumulative_completion_tokens": 4096,
            "max_tool_calls": 2 if arm == "calculator" else 0,
            "parallel_tool_calls": False,
        }
        expected_values = {
            "config": sample["config"],
            "id": sample["id"],
            "instance": sample["instance"],
            "model": "XHToken/Spark-X2.5-4B",
            "model_revision": MODEL_REVISION,
            "dataset": "apple/GSM-Symbolic",
            "dataset_revision": DATASET_REVISION,
        }
        for field, expected_value in expected_values.items():
            if record.get(field) != expected_value:
                raise ValueError(f"{record['eval_id']}/{arm}: mismatched {field}")
        if record.get("settings") != expected_settings:
            raise ValueError(f"{record['eval_id']}/{arm}: mismatched settings")
        if record.get("seed") != episode_seed(record["eval_id"]):
            raise ValueError(f"{record['eval_id']}/{arm}: mismatched seed")
        request = record.get("request", {})
        if request.get("system_prompt") != SYSTEM_PROMPT:
            raise ValueError(f"{record['eval_id']}/{arm}: mismatched system prompt")
        if request.get("system_prompt_sha256") != sha256_text(SYSTEM_PROMPT):
            raise ValueError(f"{record['eval_id']}/{arm}: mismatched system prompt")
        if request.get("policy_sha256") != sha256_text(expected_policy):
            raise ValueError(f"{record['eval_id']}/{arm}: mismatched policy")
        if request.get("policy") != expected_policy:
            raise ValueError(f"{record['eval_id']}/{arm}: mismatched policy text")
        if request.get("user_prompt_sha256") != sha256_text(str(sample["question"])):
            raise ValueError(f"{record['eval_id']}/{arm}: mismatched question")
        expected_tool_schema = CALCULATOR_TOOL if arm == "calculator" else None
        if request.get("tool_schema") != expected_tool_schema:
            raise ValueError(f"{record['eval_id']}/{arm}: mismatched tool schema")
        expected_ref = f"third_party/gsm_symbolic_selected.jsonl#{record['eval_id']}"
        if request.get("user_prompt_ref") != expected_ref:
            raise ValueError(f"{record['eval_id']}/{arm}: mismatched prompt reference")
        rendered = f"{expected_policy}\n\n题目（原文）：\n{sample['question']}"
        if request.get("rendered_user_message_sha256") != sha256_text(rendered):
            raise ValueError(f"{record['eval_id']}/{arm}: mismatched rendered prompt")
        turns = record.get("turns", [])
        if not turns or [turn.get("turn") for turn in turns] != list(
            range(1, len(turns) + 1)
        ):
            raise ValueError(f"{record['eval_id']}/{arm}: invalid turn sequence")
        expected_turn_seeds = [record["seed"] + index for index in range(len(turns))]
        if [turn.get("seed") for turn in turns] != expected_turn_seeds:
            raise ValueError(f"{record['eval_id']}/{arm}: mismatched turn seeds")
        usage = [turn.get("usage") or {} for turn in turns]
        if record.get("total_prompt_tokens") != sum(
            int(item.get("prompt_tokens", 0)) for item in usage
        ):
            raise ValueError(f"{record['eval_id']}/{arm}: mismatched prompt usage")
        if record.get("total_completion_tokens") != sum(
            int(item.get("completion_tokens", 0)) for item in usage
        ):
            raise ValueError(f"{record['eval_id']}/{arm}: mismatched completion usage")
        if record.get("tool_call_count") != len(record.get("tool_calls", [])):
            raise ValueError(f"{record['eval_id']}/{arm}: mismatched tool-call count")
        emitted_calls = [
            {
                "id": call.get("id"),
                "name": call.get("function", {}).get("name"),
                "arguments": call.get("function", {}).get("arguments"),
            }
            for turn in turns
            for call in turn.get("message", {}).get("tool_calls", [])
        ]
        recorded_calls = [
            {
                "id": call.get("id"),
                "name": call.get("name"),
                "arguments": call.get("arguments"),
            }
            for call in record.get("tool_calls", [])
        ]
        if emitted_calls != recorded_calls:
            raise ValueError(f"{record['eval_id']}/{arm}: tool transcript mismatch")
        if arm == "no_tool" and recorded_calls:
            raise ValueError(f"{record['eval_id']}/{arm}: unexpected tool call")
        if record.get("status") == "completed":
            final_turn = turns[-1]
            if final_turn.get("message", {}).get("tool_calls"):
                raise ValueError(f"{record['eval_id']}/{arm}: terminal turn has calls")
            if record.get("terminal_content") != final_turn.get("message", {}).get(
                "content"
            ):
                raise ValueError(
                    f"{record['eval_id']}/{arm}: terminal content mismatch"
                )
            if record.get("terminal_finish_reason") != final_turn.get("finish_reason"):
                raise ValueError(
                    f"{record['eval_id']}/{arm}: terminal finish reason mismatch"
                )
    return {"protocol_commit": protocol_commits.pop()}


def summarize(
    records: list[dict[str, Any]], selected: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    validation = validate_formal_records(records, selected)
    sample_map = {row["eval_id"]: row for row in selected}
    if any(row.get("status") in {None, "running", "infra_failed"} for row in records):
        raise ValueError("formal run contains unfinished infrastructure states")

    scored = [score_record(row, sample_map[row["eval_id"]]) for row in records]
    scored.sort(key=lambda row: (row["config"], row["id"], row["arm"]))
    accuracy: dict[str, Any] = {}
    for arm in ARMS:
        accuracy[arm] = {}
        for config in CONFIGS:
            group = [r for r in scored if r["arm"] == arm and r["config"] == config]
            accuracy[arm][config] = _binomial(
                sum(bool(r["correct"]) for r in group), len(group)
            )
        group = [r for r in scored if r["arm"] == arm]
        accuracy[arm]["overall_descriptive"] = _binomial(
            sum(bool(r["correct"]) for r in group), len(group)
        )

    paired: dict[str, Any] = {}
    raw_p_values: dict[str, float] = {}
    for config in CONFIGS:
        table = paired_table([r for r in scored if r["config"] == config])
        direct_only = table["direct_policy_only_correct"]
        calculator_only = table["calculator_policy_only_correct"]
        p_value = exact_mcnemar_p(direct_only, calculator_only)
        raw_p_values[config] = p_value
        paired[config] = {
            **table,
            "net_change_percentage_points": round(
                100 * (calculator_only - direct_only) / 20, 2
            ),
            "mcnemar_exact_two_sided_p": _round(p_value),
        }
    adjusted = holm_adjust(raw_p_values)
    for config in CONFIGS:
        paired[config]["holm_adjusted_p_across_three_configs"] = adjusted[config]
    overall_table = paired_table(scored)
    overall_direct_only = overall_table["direct_policy_only_correct"]
    overall_calculator_only = overall_table["calculator_policy_only_correct"]
    paired["overall_descriptive"] = {
        **overall_table,
        "net_change_percentage_points": round(
            100 * (overall_calculator_only - overall_direct_only) / 60, 2
        ),
        "note": "No pooled significance test: configs reuse template blocks.",
    }

    calculator_rows = [row for row in scored if row["arm"] == "calculator"]
    scored_by_key = {(row["eval_id"], row["arm"]): row for row in scored}
    direct_only_calculator_rows = [
        scored_by_key[(eval_id, "calculator")]
        for eval_id in sample_map
        if scored_by_key[(eval_id, "no_tool")]["correct"]
        and not scored_by_key[(eval_id, "calculator")]["correct"]
    ]
    calculator_only_rows = [
        scored_by_key[(eval_id, "calculator")]
        for eval_id in sample_map
        if not scored_by_key[(eval_id, "no_tool")]["correct"]
        and scored_by_key[(eval_id, "calculator")]["correct"]
    ]
    outcome_by_call_count = {}
    for call_count in range(3):
        group = [row for row in calculator_rows if row["tool_calls"] == call_count]
        outcome_by_call_count[str(call_count)] = {
            **_binomial(sum(bool(row["correct"]) for row in group), len(group)),
            "parseable": sum(row["parse_error"] is None for row in group),
        }
    adoption_by_config = {}
    for config in CONFIGS:
        group = [row for row in calculator_rows if row["config"] == config]
        adoption_by_config[config] = {
            "trajectories_with_any_call": sum(row["tool_calls"] > 0 for row in group),
            "total": len(group),
        }
    status_counts = Counter(row["status"] for row in scored)
    parse_errors = Counter(row["parse_error"] or "parsed" for row in scored)
    finish_reasons = Counter(str(row["finish_reason"]) for row in scored)
    started = min(datetime.fromisoformat(row["started_at"]) for row in records)
    finished = max(datetime.fromisoformat(row["finished_at"]) for row in records)
    summary = {
        "schema_version": 1,
        "protocol_commit": validation["protocol_commit"],
        "denominator": {
            "questions": 60,
            "arms": 2,
            "formal_trajectories": 120,
            "samples_per_config": 20,
            "pass_at": 1,
            "self_consistency": False,
            "ties": "not_applicable",
        },
        "accuracy": accuracy,
        "paired_policy_comparison": paired,
        "paired_condition_diagnostics_descriptive": {
            "direct_policy_only_by_calculator_call_count": dict(
                sorted(
                    Counter(
                        str(row["tool_calls"]) for row in direct_only_calculator_rows
                    ).items()
                )
            ),
            "calculator_policy_only_by_calculator_call_count": dict(
                sorted(
                    Counter(
                        str(row["tool_calls"]) for row in calculator_only_rows
                    ).items()
                )
            ),
            "direct_policy_only_with_two_calls_and_terminal_tool_markup": sum(
                row["tool_calls"] == 2 and row["terminal_tool_markup"]
                for row in direct_only_calculator_rows
            ),
            "note": (
                "Post-treatment decomposition only; differences belong to the "
                "combined policy-prefix-plus-tool condition, not the tool alone."
            ),
        },
        "calculator_behavior": {
            "required_call_adherence": sum(
                bool(r["required_calculator_call_adherence"]) for r in calculator_rows
            ),
            "required_call_total": len(calculator_rows),
            "trajectories_with_any_call": sum(
                r["tool_calls"] > 0 for r in calculator_rows
            ),
            "total_calls": sum(r["tool_calls"] for r in calculator_rows),
            "executor_successful_calls": sum(
                r["executor_successful_calls"] for r in calculator_rows
            ),
            "executor_errors": sum(r["executor_errors"] for r in calculator_rows),
            "adoption_by_config": adoption_by_config,
            "outcome_by_call_count_descriptive": outcome_by_call_count,
            "trajectories_reaching_two_call_limit": sum(
                r["tool_calls"] == 2 for r in calculator_rows
            ),
            "terminal_tool_markup_after_two_calls": sum(
                r["tool_calls"] == 2 and r["terminal_tool_markup"]
                for r in calculator_rows
            ),
            "note": (
                "Call-count outcome groups are post-treatment and descriptive; "
                "they do not estimate a causal tool effect."
            ),
        },
        "answer_format": {
            arm: {
                "parseable": sum(
                    r["parse_error"] is None for r in scored if r["arm"] == arm
                ),
                "total": sum(r["arm"] == arm for r in scored),
                "truncated": sum(
                    r["finish_reason"] == "length" for r in scored if r["arm"] == arm
                ),
            }
            for arm in ARMS
        },
        "failure_accounting": {
            "status_counts": dict(sorted(status_counts.items())),
            "prediction_parse": dict(sorted(parse_errors.items())),
            "finish_reasons": dict(sorted(finish_reasons.items())),
            "infra_retries": sum(r["infra_retries"] for r in scored),
        },
        "resource_observations": {
            "note": "Descriptive only; shared GPU, no throughput claim.",
            "api_tokens": {
                arm: {
                    "prompt_total": sum(
                        r["prompt_tokens"] for r in scored if r["arm"] == arm
                    ),
                    "completion_total": sum(
                        r["completion_tokens"] for r in scored if r["arm"] == arm
                    ),
                    "total": sum(r["total_tokens"] for r in scored if r["arm"] == arm),
                    "completion_median": statistics.median(
                        r["completion_tokens"] for r in scored if r["arm"] == arm
                    ),
                }
                for arm in ARMS
            },
            "episode_wall_seconds": {
                arm: {
                    "sum": _round(
                        sum(
                            float(r["wall_seconds"] or 0)
                            for r in scored
                            if r["arm"] == arm
                        )
                    ),
                    "median": _round(
                        statistics.median(
                            float(r["wall_seconds"] or 0)
                            for r in scored
                            if r["arm"] == arm
                        )
                    ),
                }
                for arm in ARMS
            },
            "formal_run_window": {
                "started_at": started.isoformat(),
                "finished_at": finished.isoformat(),
                "end_to_end_seconds": _round((finished - started).total_seconds()),
            },
        },
        "interpretation_limits": [
            "The 20 templates are an audit sample, not a leaderboard estimate.",
            "Cross-config trends are not same-question causal comparisons.",
            "The paired intervention combines a policy prefix and tool access.",
            "Numeric substitution reduces verbatim memorization risk but cannot "
            "rule out template contamination.",
        ],
    }
    return scored, summary


def load_live_records(directory: Path) -> list[dict[str, Any]]:
    records = []
    for path in directory.glob("*.json"):
        records.append(json.loads(path.read_text(encoding="utf-8")))
    return sorted(records, key=lambda row: job_order(row["eval_id"], row["arm"]))
