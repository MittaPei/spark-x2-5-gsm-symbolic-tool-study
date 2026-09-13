from fractions import Fraction

import pytest

from spark_math_eval.calculator import CalculatorError, calculate


@pytest.mark.parametrize(
    ("expression", "exact"),
    [
        ("72 * 7 / 12 / 210 * 100", "20"),
        ("1 / 3", "1/3"),
        ("2 ** 10", "1024"),
        ("-7 // 3", "-3"),
        ("11 % 4", "3"),
    ],
)
def test_calculate_exact(expression: str, exact: str) -> None:
    assert calculate(expression)["exact"] == exact


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('id')",
        "open('/etc/passwd').read()",
        "x + 1",
        "[1, 2]",
        "1 / 0",
        "2 ** 11",
        "'1'",
    ],
)
def test_calculate_rejects_unsafe_or_out_of_bounds(expression: str) -> None:
    with pytest.raises(CalculatorError):
        calculate(expression)


def test_calculator_returns_exact_fraction() -> None:
    result = calculate("0.1 + 0.2")
    assert Fraction(result["exact"]) == Fraction(3, 10)
