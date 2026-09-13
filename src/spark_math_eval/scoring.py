"""Strict, deterministic numeric answer extraction and statistics."""

from __future__ import annotations

import math
import re
from fractions import Fraction

GOLD_RE = re.compile(r"(?m)^####\s*(.+?)\s*$")
PREDICTION_RE = re.compile(r"(?im)^FINAL_ANSWER:\s*(.+?)\s*$")
NUMBER_RE = re.compile(
    r"^[+$]?\s*(?P<number>[+-]?(?:\d[\d,]*)(?:\.\d+)?(?:/[+-]?\d[\d,]*)?)\s*%?$"
)


def _unwrap_boxed(value: str) -> str:
    value = value.strip()
    if value.startswith(r"\boxed{") and value.endswith("}"):
        return value[7:-1].strip()
    return value


def parse_number(value: str) -> Fraction:
    value = _unwrap_boxed(value).replace("$", "").strip()
    match = NUMBER_RE.fullmatch(value)
    if not match:
        raise ValueError("not_a_supported_number")
    number = match.group("number").replace(",", "")
    if "/" in number:
        numerator, denominator = number.split("/", 1)
        if int(denominator) == 0:
            raise ValueError("zero_denominator")
        return Fraction(int(numerator), int(denominator))
    return Fraction(number)


def extract_gold(answer: str) -> tuple[str, Fraction]:
    matches = GOLD_RE.findall(answer)
    if len(matches) != 1:
        raise ValueError("gold_must_have_one_marker")
    raw = matches[0].strip()
    return raw, parse_number(raw)


def extract_prediction(
    content: str | None,
) -> tuple[str | None, Fraction | None, str | None]:
    if not content:
        return None, None, "missing_content"
    visible_content = content.rsplit("</think>", 1)[-1].lstrip()
    matches = PREDICTION_RE.findall(visible_content)
    if len(matches) != 1:
        return None, None, "missing_or_multiple_final_answer_markers"
    raw = matches[0].strip()
    try:
        return raw, parse_number(raw), None
    except ValueError as exc:
        return raw, None, str(exc)


def wilson_interval(
    successes: int, total: int, z: float = 1.959963984540054
) -> tuple[float, float]:
    if total <= 0 or successes < 0 or successes > total:
        raise ValueError("invalid binomial counts")
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total**2))
        / denominator
    )
    return center - margin, center + margin


def exact_mcnemar_p(first_only: int, second_only: int) -> float:
    discordant = first_only + second_only
    if discordant == 0:
        return 1.0
    tail = sum(
        math.comb(discordant, k) for k in range(min(first_only, second_only) + 1)
    )
    return min(1.0, 2 * tail / (2**discordant))
