#!/usr/bin/env python3
"""Run excluded synthetic prompts through both evaluation arms."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from spark_math_eval.runner import atomic_json, run_episode
from spark_math_eval.scoring import extract_prediction, parse_number

PILOTS = (
    {
        "eval_id": "synthetic-pilot-01",
        "config": "synthetic",
        "id": -1,
        "instance": 1,
        "question": (
            "If a calculator tool is available, use it. A warehouse has 137 boxes "
            "with 29 bolts each and then receives 46 more bolts. How many bolts "
            "does it have?"
        ),
        "gold": "4019",
    },
    {
        "eval_id": "synthetic-pilot-02",
        "config": "synthetic",
        "id": -1,
        "instance": 2,
        "question": (
            "A printer makes 84 labels per minute for 17 minutes, then 138 labels "
            "are discarded. How many usable labels remain?"
        ),
        "gold": "1290",
    },
    {
        "eval_id": "synthetic-pilot-03",
        "config": "synthetic",
        "id": -1,
        "instance": 3,
        "question": (
            "A tank is 3/5 full. After 24 liters are added it is 9/10 full. "
            "What is the tank capacity in liters?"
        ),
        "gold": "80",
    },
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", default="spark-x2.5-4b")
    parser.add_argument("--protocol-commit", required=True)
    parser.add_argument("--runtime-json", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("evidence/pilot-v2"))
    args = parser.parse_args()
    runtime = json.loads(args.runtime_json.read_text(encoding="utf-8"))
    failures: list[str] = []
    tool_calls = 0
    for sample in PILOTS:
        for arm in ("no_tool", "calculator"):
            record = run_episode(
                base_url=args.base_url,
                served_model=args.model,
                sample=sample,
                arm=arm,
                protocol_commit=args.protocol_commit,
                runtime=runtime,
            )
            record["pilot_excluded_from_formal_results"] = True
            record["dataset"] = "synthetic_pilot"
            record["dataset_revision"] = None
            record["request"]["user_prompt_ref"] = "embedded_synthetic_pilot"
            record["request"]["user_prompt"] = sample["question"]
            raw, value, error = extract_prediction(record.get("terminal_content"))
            expected = parse_number(sample["gold"])
            record["pilot_score"] = {
                "gold": sample["gold"],
                "prediction": raw,
                "parse_error": error,
                "correct": value == expected,
            }
            tool_calls += len(record["tool_calls"])
            if record["status"] != "completed" or value != expected:
                failures.append(f"{sample['eval_id']}:{arm}")
            atomic_json(args.output_dir / f"{sample['eval_id']}--{arm}.json", record)
    summary = {
        "status": "PASS" if not failures and tool_calls else "FAIL",
        "formal_sample_overlap": 0,
        "trajectories": len(PILOTS) * 2,
        "correct": len(PILOTS) * 2 - len(failures),
        "native_tool_calls": tool_calls,
        "failures": failures,
    }
    atomic_json(args.output_dir / "summary.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
