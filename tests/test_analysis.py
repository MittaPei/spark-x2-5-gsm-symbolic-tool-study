import json
from pathlib import Path

import pytest

from spark_math_eval.analysis import (
    holm_adjust,
    paired_table,
    read_jsonl,
    summarize,
)


def test_paired_table() -> None:
    rows = [
        {"eval_id": "a", "arm": "no_tool", "correct": True},
        {"eval_id": "a", "arm": "calculator", "correct": False},
        {"eval_id": "b", "arm": "no_tool", "correct": False},
        {"eval_id": "b", "arm": "calculator", "correct": True},
        {"eval_id": "c", "arm": "no_tool", "correct": True},
        {"eval_id": "c", "arm": "calculator", "correct": True},
        {"eval_id": "d", "arm": "no_tool", "correct": False},
        {"eval_id": "d", "arm": "calculator", "correct": False},
    ]
    assert paired_table(rows) == {
        "both_correct": 1,
        "direct_policy_only_correct": 1,
        "calculator_policy_only_correct": 1,
        "both_wrong": 1,
    }


def test_holm_adjustment_is_monotone_in_sorted_order() -> None:
    adjusted = holm_adjust({"main": 0.01, "p1": 0.03, "p2": 0.5})
    assert adjusted == {"main": 0.03, "p1": 0.06, "p2": 0.5}


def test_published_formal_artifacts_recompute_exactly() -> None:
    root = Path(__file__).parents[1]
    records = read_jsonl(root / "runs/raw.jsonl")
    selected = read_jsonl(root / "third_party/gsm_symbolic_selected.jsonl")
    expected_items = read_jsonl(root / "results/per_item.jsonl")
    expected_summary = json.loads(
        (root / "results/summary.json").read_text(encoding="utf-8")
    )
    items, summary = summarize(records, selected)
    assert items == expected_items
    assert summary == expected_summary


def test_formal_artifact_validation_rejects_duplicate_job() -> None:
    root = Path(__file__).parents[1]
    records = read_jsonl(root / "runs/raw.jsonl")
    selected = read_jsonl(root / "third_party/gsm_symbolic_selected.jsonl")
    records[1] = records[0]
    with pytest.raises(ValueError, match="120 unique jobs"):
        summarize(records, selected)
