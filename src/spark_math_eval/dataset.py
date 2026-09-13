"""Load a pinned GSM-Symbolic snapshot and select the frozen sample."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from . import DATASET_REVISION
from .scoring import extract_gold

CONFIGS = ("main", "p1", "p2")
SALT = (
    f"HER-Hack-Astron-6|Spark-X2.5-4B|apple/GSM-Symbolic|{DATASET_REVISION}|paired-v1"
)
EXPECTED_KEYS = (
    (24, 8),
    (38, 31),
    (41, 23),
    (27, 42),
    (21, 34),
    (39, 26),
    (44, 39),
    (40, 40),
    (31, 2),
    (10, 44),
    (19, 5),
    (25, 38),
    (49, 4),
    (26, 27),
    (33, 27),
    (30, 35),
    (5, 28),
    (22, 2),
    (16, 36),
    (45, 31),
)
EXPECTED_KEY_LIST_SHA256 = (
    "73538354c63a79e00ee986cdac83cd748d14e256dc0015ee9dd4c231ca922d77"
)
ALLOWED_SOURCE_FIELDS = {
    "id",
    "instance",
    "question",
    "answer",
    "original_id",
    "original_question",
    "original_answer",
    "canary",
}


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def read_config(root: Path, config: str) -> dict[tuple[int, int], dict[str, Any]]:
    if config not in CONFIGS:
        raise ValueError(f"unknown config: {config}")
    path = root / config / "test.jsonl"
    records: dict[tuple[int, int], dict[str, Any]] = {}
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            record = json.loads(line)
            if set(record) != ALLOWED_SOURCE_FIELDS:
                raise ValueError(f"unexpected fields at {path}:{line_number}")
            key = (int(record["id"]), int(record["instance"]))
            if key in records:
                raise ValueError(f"duplicate key {key} in {config}")
            records[key] = record
    return records


def selected_keys(
    config_records: dict[str, dict[tuple[int, int], Any]],
) -> list[tuple[int, int]]:
    common = set.intersection(*(set(config_records[name]) for name in CONFIGS))
    common_ids = sorted({item_id for item_id, _ in common})
    ordered_ids = sorted(
        common_ids, key=lambda item_id: (sha256_text(f"{SALT}|id={item_id}"), item_id)
    )[:20]
    selected: list[tuple[int, int]] = []
    for item_id in ordered_ids:
        instances = sorted(instance for key_id, instance in common if key_id == item_id)
        instance = min(
            instances,
            key=lambda value: (
                sha256_text(f"{SALT}|id={item_id}|instance={value}"),
                value,
            ),
        )
        selected.append((item_id, instance))
    rendered = "".join(f"{item_id},{instance}\n" for item_id, instance in selected)
    if sha256_text(rendered) != EXPECTED_KEY_LIST_SHA256:
        raise ValueError("selected-key checksum does not match frozen protocol")
    if tuple(selected) != EXPECTED_KEYS:
        raise ValueError("selected keys do not match frozen protocol")
    return selected


def build_manifest(root: Path) -> list[dict[str, Any]]:
    configs = {name: read_config(root, name) for name in CONFIGS}
    keys = selected_keys(configs)
    output: list[dict[str, Any]] = []
    for template_order, key in enumerate(keys):
        original_ids = {configs[name][key]["original_id"] for name in CONFIGS}
        if len(original_ids) != 1:
            raise ValueError(f"inconsistent original_id for {key}")
        for config in CONFIGS:
            record = configs[config][key]
            answer = str(record["answer"])
            marker_lines = [
                line for line in answer.splitlines() if line.startswith("####")
            ]
            if len(marker_lines) != 1:
                raise ValueError(f"unexpected gold marker count for {config}/{key}")
            output.append(
                {
                    "eval_id": f"{config}-id{key[0]:02d}-i{key[1]:02d}",
                    "config": config,
                    "template_order": template_order,
                    "id": key[0],
                    "instance": key[1],
                    "original_id": int(record["original_id"]),
                    "question_sha256": sha256_text(str(record["question"])),
                    "gold_record_sha256": sha256_text(answer),
                }
            )
    if len(output) != 60 or len({row["eval_id"] for row in output}) != 60:
        raise ValueError("manifest must contain 60 unique evaluations")
    return output


def build_selected_excerpt(
    root: Path, manifest: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Return only the unmodified source fields needed to reproduce evaluation."""
    configs = {name: read_config(root, name) for name in CONFIGS}
    output: list[dict[str, Any]] = []
    for row in manifest:
        key = (int(row["id"]), int(row["instance"]))
        record = configs[str(row["config"])][key]
        raw_gold, _ = extract_gold(str(record["answer"]))
        output.append(
            {
                "eval_id": row["eval_id"],
                "config": row["config"],
                "id": row["id"],
                "instance": row["instance"],
                "question": record["question"],
                "answer": record["answer"],
                "gold_final": raw_gold,
            }
        )
    return output


def source_record(root: Path, manifest_row: dict[str, Any]) -> dict[str, Any]:
    records = read_config(root, str(manifest_row["config"]))
    key = (int(manifest_row["id"]), int(manifest_row["instance"]))
    record = records[key]
    if sha256_text(str(record["question"])) != manifest_row["question_sha256"]:
        raise ValueError(f"question checksum changed for {manifest_row['eval_id']}")
    if sha256_text(str(record["answer"])) != manifest_row["gold_record_sha256"]:
        raise ValueError(f"answer checksum changed for {manifest_row['eval_id']}")
    return record
