#!/usr/bin/env python3
"""Run the frozen 120-trajectory paired evaluation with bounded concurrency."""

from __future__ import annotations

import argparse
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from spark_math_eval.runner import atomic_json, job_order, run_episode

_LOG_LOCK = threading.Lock()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def log(path: Path, message: str) -> None:
    clean = " ".join(message.replace("\n", " ").split())
    line = f"{datetime.now(UTC).isoformat()} {clean}\n"
    with _LOG_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
        print(line, end="", flush=True)


def output_path(root: Path, eval_id: str, arm: str) -> Path:
    return root / f"{eval_id}--{arm}.json"


def is_final(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    return record.get("status") not in {None, "running", "infra_failed"}


def execute_job(
    *,
    args: argparse.Namespace,
    sample: dict[str, Any],
    arm: str,
    runtime: dict[str, Any],
) -> tuple[str, str]:
    eval_id = str(sample["eval_id"])
    destination = output_path(args.output_dir, eval_id, arm)
    if is_final(destination):
        return destination.name, "skipped_existing"
    errors: list[dict[str, str]] = []
    for attempt in (1, 2):
        try:
            record = run_episode(
                base_url=args.base_url,
                served_model=args.model,
                sample=sample,
                arm=arm,
                protocol_commit=args.protocol_commit,
                runtime=runtime,
            )
            record["attempt"] = attempt
            record["infra_attempt_errors"] = errors
            atomic_json(destination, record)
            return destination.name, str(record["status"])
        except Exception as exc:  # noqa: BLE001 - preserve bounded infra retry
            errors.append({"type": type(exc).__name__, "message": str(exc)[:500]})
    failure = {
        "schema_version": 1,
        "eval_id": eval_id,
        "config": sample["config"],
        "id": sample["id"],
        "instance": sample["instance"],
        "arm": arm,
        "protocol_commit": args.protocol_commit,
        "status": "infra_failed",
        "attempt": 2,
        "infra_attempt_errors": errors,
        "finished_at": datetime.now(UTC).isoformat(),
    }
    atomic_json(destination, failure)
    return destination.name, "infra_failed"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", default="Spark2_5")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--excerpt", type=Path, required=True)
    parser.add_argument("--runtime-json", type=Path, required=True)
    parser.add_argument("--protocol-commit", required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("runs/live"))
    parser.add_argument("--log", type=Path, default=Path("runs/run.log"))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--arms", choices=("both", "no_tool", "calculator"), default="both"
    )
    args = parser.parse_args()
    if not 1 <= args.workers <= 8:
        parser.error("workers must be in [1, 8]")

    manifest = read_jsonl(args.manifest)
    excerpts = {row["eval_id"]: row for row in read_jsonl(args.excerpt)}
    if len(manifest) != 60 or set(excerpts) != {row["eval_id"] for row in manifest}:
        raise ValueError("selection inputs do not contain the frozen 60 samples")
    runtime = json.loads(args.runtime_json.read_text(encoding="utf-8"))
    arms = ("no_tool", "calculator") if args.arms == "both" else (args.arms,)
    jobs = []
    for row in manifest:
        sample = dict(excerpts[row["eval_id"]])
        if sample["question"] and "canary" not in sample["question"].lower():
            for arm in arms:
                jobs.append((job_order(sample["eval_id"], arm), sample, arm))
        else:
            raise ValueError(f"forbidden or empty question: {sample['eval_id']}")
    jobs.sort(key=lambda item: item[0])
    log(args.log, f"start jobs={len(jobs)} workers={args.workers}")
    counts: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(
                execute_job, args=args, sample=sample, arm=arm, runtime=runtime
            ): (sample["eval_id"], arm)
            for _, sample, arm in jobs
        }
        for future in as_completed(futures):
            eval_id, arm = futures[future]
            filename, status = future.result()
            counts[status] = counts.get(status, 0) + 1
            log(
                args.log,
                f"done eval_id={eval_id} arm={arm} status={status} file={filename}",
            )
    log(args.log, f"finish counts={json.dumps(counts, sort_keys=True)}")
    return 1 if counts.get("infra_failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
