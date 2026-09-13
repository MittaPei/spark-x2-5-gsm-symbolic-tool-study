#!/usr/bin/env python3
"""Write SHA256SUMS for all published evaluation evidence."""

from __future__ import annotations

import hashlib
from pathlib import Path

EVIDENCE_ROOTS = (
    Path("data"),
    Path("evidence"),
    Path("reasoning"),
    Path("results"),
    Path("runs"),
    Path("third_party"),
)
EXCLUDED_PARTS = {"live", "__pycache__"}


def evidence_files() -> list[Path]:
    return sorted(
        path
        for root in EVIDENCE_ROOTS
        for path in root.rglob("*")
        if path.is_file() and not set(path.parts).intersection(EXCLUDED_PARTS)
    )


def main() -> int:
    lines = []
    for path in evidence_files():
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.as_posix()}\n")
    Path("SHA256SUMS").write_text("".join(lines), encoding="utf-8")
    print(f"wrote SHA256SUMS for {len(lines)} evidence files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
