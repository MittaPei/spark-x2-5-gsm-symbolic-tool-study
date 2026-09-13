#!/usr/bin/env python3
"""Offline integrity, reproducibility, privacy, and weight-upload checks."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from render_cases import render as render_cases
from update_checksums import evidence_files

from spark_math_eval.analysis import job_order, read_jsonl, sha256_text, summarize
from spark_math_eval.audit import build_review, summarize_review
from spark_math_eval.calculator import calculate

ROOT = Path(__file__).parents[1]
WEIGHT_SUFFIXES = {
    ".bin",
    ".ckpt",
    ".gguf",
    ".onnx",
    ".pt",
    ".pth",
    ".safetensors",
}
FORBIDDEN_TEXT = {
    "main-account handle": re.compile(r"\bwhy" + r"iug\b", re.IGNORECASE),
    "workspace path": re.compile(r"/data/" + r"ruiyang(?:/|\b)"),
    "home path": re.compile(r"/(?:home|root)/[^\s\"']+"),
    "GitHub token": re.compile(r"(?:ghp_|github_pat_)[A-Za-z0-9_]{20,}"),
    "Hugging Face token": re.compile(r"\bhf_[A-Za-z0-9]{30,}\b"),
    "generic API secret": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _public_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [ROOT / item.decode() for item in result.stdout.split(b"\0") if item]


def _verify_selection() -> None:
    manifest = read_jsonl(ROOT / "data/selection_manifest.jsonl")
    selected = read_jsonl(ROOT / "third_party/gsm_symbolic_selected.jsonl")
    if len(manifest) != 60 or len(selected) != 60:
        raise ValueError("selection artifacts must contain exactly 60 rows")
    manifest_by_id = {row["eval_id"]: row for row in manifest}
    selected_by_id = {row["eval_id"]: row for row in selected}
    if len(manifest_by_id) != 60 or set(manifest_by_id) != set(selected_by_id):
        raise ValueError("selection artifacts have duplicate or mismatched eval IDs")
    for eval_id, sample in selected_by_id.items():
        row = manifest_by_id[eval_id]
        for field in ("config", "id", "instance"):
            if sample[field] != row[field]:
                raise ValueError(f"{eval_id}: mismatched selection field {field}")
        if sha256_text(sample["question"]) != row["question_sha256"]:
            raise ValueError(f"{eval_id}: mismatched question hash")
        if sha256_text(sample["answer"]) != row["gold_record_sha256"]:
            raise ValueError(f"{eval_id}: mismatched gold-record hash")
        if "####" in sample["question"] or "canary" in sample["question"].lower():
            raise ValueError(f"{eval_id}: forbidden target material in question")


def _verify_generated_artifacts() -> None:
    raw = read_jsonl(ROOT / "runs/raw.jsonl")
    selected = read_jsonl(ROOT / "third_party/gsm_symbolic_selected.jsonl")
    scored, summary = summarize(raw, selected)
    if scored != read_jsonl(ROOT / "results/per_item.jsonl"):
        raise ValueError("results/per_item.jsonl is not a deterministic recomputation")
    if summary != _load_json(ROOT / "results/summary.json"):
        raise ValueError("results/summary.json is not a deterministic recomputation")
    environment = _load_json(ROOT / "evidence/environment.json")
    if summary["protocol_commit"] != environment.get("protocol_commit"):
        raise ValueError("protocol commit differs between results and environment")
    subprocess.run(
        ["git", "cat-file", "-e", f"{summary['protocol_commit']}^{{commit}}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    if any(record.get("runtime") != environment for record in raw):
        raise ValueError("raw runtime snapshots differ from evidence/environment.json")
    if raw != sorted(raw, key=lambda row: job_order(row["eval_id"], row["arm"])):
        raise ValueError("runs/raw.jsonl is not in the deterministic job order")
    scored_by_key = {(row["eval_id"], row["arm"]): row for row in scored}

    annotations = []
    for path in sorted((ROOT / "reasoning/annotations").glob("*.jsonl")):
        annotations.extend(read_jsonl(path))
    review = build_review(raw, scored, annotations)
    if review != read_jsonl(ROOT / "reasoning/review.jsonl"):
        raise ValueError("reasoning/review.jsonl is not a deterministic recomputation")
    if summarize_review(review) != _load_json(ROOT / "reasoning/summary.json"):
        raise ValueError("reasoning/summary.json is not a deterministic recomputation")
    if render_cases() != (ROOT / "reasoning/cases.md").read_text(encoding="utf-8"):
        raise ValueError("reasoning/cases.md is not a deterministic rendering")

    for record in raw:
        request = record.get("request", {})
        if set(request).intersection({"answer", "original_answer", "canary"}):
            raise ValueError(f"{record['eval_id']}: target data leaked into request")
        calls = record.get("tool_calls", [])
        if record["arm"] == "no_tool" and calls:
            raise ValueError(f"{record['eval_id']}: no-tool arm emitted a tool call")
        if len(calls) > 2:
            raise ValueError(f"{record['eval_id']}: tool-call limit exceeded")
        if [call.get("ordinal") for call in calls] != list(range(1, len(calls) + 1)):
            raise ValueError(f"{record['eval_id']}: invalid tool-call ordinals")
        for call in calls:
            if call.get("name") != "calculator":
                raise ValueError(f"{record['eval_id']}: unexpected tool name")
            arguments = json.loads(call["arguments"])
            if set(arguments) != {"expression"}:
                raise ValueError(f"{record['eval_id']}: unexpected tool arguments")
            replayed = calculate(arguments["expression"])
            if replayed != call["result"] or call.get("error") is not None:
                raise ValueError(f"{record['eval_id']}: tool result does not replay")
        score = scored_by_key[(record["eval_id"], record["arm"])]
        if score["parse_error"] is None:
            visible = str(record.get("terminal_content", "")).rsplit("</think>", 1)[-1]
            marker = re.search(r"(?im)^FINAL_ANSWER:\s*(.+?)\s*$", visible)
            if marker is None or visible[marker.end() :].strip():
                raise ValueError(f"{record['eval_id']}: final marker is not terminal")


def _verify_checksums() -> None:
    expected = {}
    paths = evidence_files()
    checksum_lines = (ROOT / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    checksum_paths = []
    for line in checksum_lines:
        digest, relative = line.split("  ", 1)
        if relative in expected:
            raise ValueError(f"duplicate checksum path: {relative}")
        expected[relative] = digest
        checksum_paths.append(relative)
    if checksum_paths != [path.as_posix() for path in paths]:
        raise ValueError("SHA256SUMS is not in canonical path order")
    actual_names = {path.as_posix() for path in paths}
    if set(expected) != actual_names:
        raise ValueError("SHA256SUMS does not cover exactly the public evidence files")
    for path in paths:
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if expected[path.as_posix()] != actual:
            raise ValueError(f"checksum mismatch: {path}")


def _verify_public_tree() -> None:
    for path in _public_files():
        relative = path.relative_to(ROOT)
        if path.suffix.lower() in WEIGHT_SUFFIXES:
            raise ValueError(f"model-weight-like file is forbidden: {relative}")
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for name, pattern in FORBIDDEN_TEXT.items():
            if pattern.search(text):
                raise ValueError(f"{name} found in public file: {relative}")


def main() -> int:
    _verify_selection()
    _verify_generated_artifacts()
    _verify_checksums()
    _verify_public_tree()
    print("artifact verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
