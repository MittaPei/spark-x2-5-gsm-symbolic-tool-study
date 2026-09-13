#!/usr/bin/env python3
"""Score all formal records and write deterministic public artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from spark_math_eval.analysis import load_live_records, read_jsonl, summarize


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
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--live-dir",
        type=Path,
        help="directory of individual formal records after a new model run",
    )
    source.add_argument(
        "--raw-input",
        type=Path,
        help="published aggregate raw JSONL (default: runs/raw.jsonl)",
    )
    parser.add_argument(
        "--selected",
        type=Path,
        default=Path("third_party/gsm_symbolic_selected.jsonl"),
    )
    parser.add_argument("--raw-output", type=Path, default=Path("runs/raw.jsonl"))
    parser.add_argument(
        "--per-item-output", type=Path, default=Path("results/per_item.jsonl")
    )
    parser.add_argument(
        "--summary-output", type=Path, default=Path("results/summary.json")
    )
    args = parser.parse_args()
    records = (
        load_live_records(args.live_dir)
        if args.live_dir is not None
        else read_jsonl(args.raw_input or Path("runs/raw.jsonl"))
    )
    selected = read_jsonl(args.selected)
    scored, summary = summarize(records, selected)
    write_jsonl(args.raw_output, records)
    write_jsonl(args.per_item_output, scored)
    write_json(args.summary_output, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
