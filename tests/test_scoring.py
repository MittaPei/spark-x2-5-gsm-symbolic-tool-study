import pytest

from spark_math_eval.scoring import (
    exact_mcnemar_p,
    extract_gold,
    extract_prediction,
    parse_number,
    wilson_interval,
)


@pytest.mark.parametrize(
    ("raw", "numerator", "denominator"),
    [
        ("1,024", 1024, 1),
        ("-0.25", -1, 4),
        ("3/4", 3, 4),
        (r"\boxed{20%}", 20, 1),
    ],
)
def test_parse_number(raw: str, numerator: int, denominator: int) -> None:
    result = parse_number(raw)
    assert (result.numerator, result.denominator) == (numerator, denominator)


def test_extract_gold_and_prediction() -> None:
    _, gold = extract_gold("reasoning\n#### 20")
    _, predicted, error = extract_prediction("work\nFINAL_ANSWER: 20%")
    assert error is None
    assert predicted == gold


def test_prediction_requires_one_marker() -> None:
    assert extract_prediction("20")[2] is not None
    assert extract_prediction("FINAL_ANSWER: 2\nFINAL_ANSWER: 2")[2] is not None


def test_statistics_known_values() -> None:
    low, high = wilson_interval(10, 20)
    assert low == pytest.approx(0.299298, abs=1e-6)
    assert high == pytest.approx(0.700702, abs=1e-6)
    assert exact_mcnemar_p(0, 0) == 1.0
    assert exact_mcnemar_p(0, 5) == pytest.approx(0.0625)
