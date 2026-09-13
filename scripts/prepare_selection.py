#!/usr/bin/env python3
"""Materialize the frozen selection manifest and required licensed excerpts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from spark_math_eval.dataset import build_manifest, build_selected_excerpt


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
        for record in records
    )
    path.write_text(body, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument(
        "--manifest", type=Path, default=Path("data/selection_manifest.jsonl")
    )
    parser.add_argument(
        "--excerpt",
        type=Path,
        default=Path("third_party/gsm_symbolic_selected.jsonl"),
    )
    args = parser.parse_args()
    manifest = build_manifest(args.dataset_root)
    excerpt = build_selected_excerpt(args.dataset_root, manifest)
    write_jsonl(args.manifest, manifest)
    write_jsonl(args.excerpt, excerpt)
    print(f"wrote {len(manifest)} manifest rows and {len(excerpt)} excerpts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
