#!/usr/bin/env python3
"""Validate annotations and build the reasoning-integrity audit artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from spark_math_eval.audit import build_review, read_jsonl, summarize_review


def read_annotations(path: Path) -> list[dict[str, Any]]:
    if path.is_dir():
        rows = []
        for child in sorted(path.glob("*.jsonl")):
            rows.extend(read_jsonl(child))
        return rows
    return read_jsonl(path)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
        ),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=Path("runs/raw.jsonl"))
    parser.add_argument("--per-item", type=Path, default=Path("results/per_item.jsonl"))
    parser.add_argument(
        "--annotations", type=Path, default=Path("reasoning/annotations")
    )
    parser.add_argument(
        "--review-output", type=Path, default=Path("reasoning/review.jsonl")
    )
    parser.add_argument(
        "--summary-output", type=Path, default=Path("reasoning/summary.json")
    )
    args = parser.parse_args()
    review = build_review(
        read_jsonl(args.raw),
        read_jsonl(args.per_item),
        read_annotations(args.annotations),
    )
    write_jsonl(args.review_output, review)
    summary = summarize_review(review)
    write_json(args.summary_output, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
