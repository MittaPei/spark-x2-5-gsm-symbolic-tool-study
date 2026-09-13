"""Build and validate the frozen reasoning-integrity audit."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .analysis import ARMS, CONFIGS

PRIMARY_LABELS = {
    "coherent",
    "arithmetic",
    "semantic_planning",
    "relevant_clause_omission",
    "unit",
    "extraction_format",
    "truncation",
    "tool_protocol",
    "dataset_ambiguity",
    "unclear",
}
FLAGS = {
    "right_answer_wrong_reasoning",
    "calculator_policy_noncompliance",
    "tool_call",
    "tool_error",
    "self_corrected",
}
REASON_ORDER = (
    "wrong_or_unparseable",
    "paired_disagreement",
    "tool_call_or_error",
    "preselected_lowest_question_hash",
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def pair_transition(direct: dict[str, Any], calculator: dict[str, Any]) -> str:
    if direct["correct"] and calculator["correct"]:
        return "both_correct"
    if direct["correct"]:
        return "direct_policy_only_correct"
    if calculator["correct"]:
        return "calculator_policy_only_correct"
    return "both_wrong"


def select_for_audit(
    records: list[dict[str, Any]], scored: list[dict[str, Any]]
) -> dict[tuple[str, str], list[str]]:
    scored_by_key = {(row["eval_id"], row["arm"]): row for row in scored}
    record_by_key = {(row["eval_id"], row["arm"]): row for row in records}
    if (
        len(records) != 120
        or len(scored) != 120
        or len(scored_by_key) != 120
        or len(record_by_key) != 120
        or set(scored_by_key) != set(record_by_key)
    ):
        raise ValueError("raw and per-item artifacts must contain the same 120 jobs")

    selected: dict[tuple[str, str], set[str]] = {}

    def add(key: tuple[str, str], reason: str) -> None:
        selected.setdefault(key, set()).add(reason)

    for key, row in scored_by_key.items():
        if not row["correct"]:
            add(key, "wrong_or_unparseable")
        if row["tool_calls"] or row["executor_errors"]:
            add(key, "tool_call_or_error")

    eval_ids = {row["eval_id"] for row in scored}
    for eval_id in eval_ids:
        direct = scored_by_key[(eval_id, "no_tool")]
        calculator = scored_by_key[(eval_id, "calculator")]
        if direct["correct"] != calculator["correct"]:
            add((eval_id, "no_tool"), "paired_disagreement")
            add((eval_id, "calculator"), "paired_disagreement")

    for config in CONFIGS:
        candidates = [
            row
            for row in records
            if row["config"] == config and row["arm"] == "no_tool"
        ]
        preselected = min(
            candidates, key=lambda row: row["request"]["user_prompt_sha256"]
        )
        for arm in ARMS:
            add(
                (preselected["eval_id"], arm),
                "preselected_lowest_question_hash",
            )

    return {
        key: [reason for reason in REASON_ORDER if reason in reasons]
        for key, reasons in selected.items()
    }


def _objective_flags(row: dict[str, Any]) -> set[str]:
    flags = set()
    if row["tool_calls"]:
        flags.add("tool_call")
    if row["executor_errors"]:
        flags.add("tool_error")
    if row["arm"] == "calculator" and not row["tool_calls"]:
        flags.add("calculator_policy_noncompliance")
    return flags


def build_review(
    records: list[dict[str, Any]],
    scored: list[dict[str, Any]],
    annotations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    record_by_key = {(row["eval_id"], row["arm"]): row for row in records}
    scored_by_key = {(row["eval_id"], row["arm"]): row for row in scored}
    selection = select_for_audit(records, scored)
    annotation_by_key = {(row["eval_id"], row["arm"]): row for row in annotations}
    if len(annotation_by_key) != len(annotations):
        raise ValueError("duplicate audit annotation")
    if set(annotation_by_key) != set(selection):
        raise ValueError(
            "annotations must exactly cover frozen audit selection: "
            f"missing={len(set(selection) - set(annotation_by_key))} "
            f"extra={len(set(annotation_by_key) - set(selection))}"
        )

    review = []
    for key in sorted(selection):
        eval_id, arm = key
        annotation = annotation_by_key[key]
        primary_label = annotation.get("primary_label")
        if primary_label not in PRIMARY_LABELS:
            raise ValueError(f"{eval_id}/{arm}: invalid primary label")
        curated_flags = set(annotation.get("flags", []))
        if not curated_flags <= FLAGS:
            raise ValueError(f"{eval_id}/{arm}: invalid flags")
        evidence = " ".join(str(annotation.get("evidence", "")).split())
        if len(evidence) < 12:
            raise ValueError(f"{eval_id}/{arm}: evidence is too short")

        score = scored_by_key[key]
        record = record_by_key[key]
        if primary_label == "coherent" and not score["correct"]:
            raise ValueError(f"{eval_id}/{arm}: an incorrect result cannot be coherent")
        if "right_answer_wrong_reasoning" in curated_flags and not score["correct"]:
            raise ValueError(f"{eval_id}/{arm}: RWRA requires a correct strict answer")
        flags = sorted(curated_flags | _objective_flags(score))
        direct = scored_by_key[(eval_id, "no_tool")]
        calculator = scored_by_key[(eval_id, "calculator")]
        review.append(
            {
                "eval_id": eval_id,
                "config": score["config"],
                "id": score["id"],
                "instance": score["instance"],
                "arm": arm,
                "selection_reasons": selection[key],
                "pair_transition": pair_transition(direct, calculator),
                "correct": score["correct"],
                "gold": score["gold"],
                "prediction": score["prediction"],
                "parse_error": score["parse_error"],
                "finish_reason": score["finish_reason"],
                "tool_calls": score["tool_calls"],
                "executor_errors": score["executor_errors"],
                "raw_record_sha256": score["raw_record_sha256"],
                "primary_label": primary_label,
                "flags": flags,
                "evidence": evidence,
                "review_scope": (
                    "full question, turns, tool transcript, and terminal output"
                ),
                "raw_record_ref": f"runs/raw.jsonl#{eval_id}/{arm}",
                "question_sha256": record["request"]["user_prompt_sha256"],
            }
        )
    return review


def summarize_review(review: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "reviewed_trajectories": len(review),
        "reviewed_questions": len({row["eval_id"] for row in review}),
        "by_config": dict(sorted(Counter(row["config"] for row in review).items())),
        "by_arm": dict(sorted(Counter(row["arm"] for row in review).items())),
        "primary_labels": dict(
            sorted(Counter(row["primary_label"] for row in review).items())
        ),
        "flags": dict(
            sorted(Counter(flag for row in review for flag in row["flags"]).items())
        ),
        "selection_reason_occurrences": dict(
            sorted(
                Counter(
                    reason for row in review for reason in row["selection_reasons"]
                ).items()
            )
        ),
        "method": (
            "Deterministic selection followed by AI-assisted full-trajectory review; "
            "objective facts are regenerated and annotations are schema-checked."
        ),
        "rwra_definition": (
            "A strict correct answer with a concrete, uncorrected equation error or "
            "material logical omission in the visible derivation."
        ),
    }
