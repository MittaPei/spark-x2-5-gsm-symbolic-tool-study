"""Small exact-arithmetic calculator with an explicit AST allowlist."""

from __future__ import annotations

import ast
from decimal import Decimal, localcontext
from fractions import Fraction

MAX_EXPRESSION_LENGTH = 200
MAX_NODES = 64
MAX_EXPONENT = 10
MAX_RESULT_BITS = 4096


class CalculatorError(ValueError):
    """A safe, expected calculator rejection."""


def _check_size(value: Fraction) -> Fraction:
    if value.numerator.bit_length() > MAX_RESULT_BITS:
        raise CalculatorError("result_too_large")
    if value.denominator.bit_length() > MAX_RESULT_BITS:
        raise CalculatorError("result_too_large")
    return value


def _number(node: ast.Constant) -> Fraction:
    if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
        raise CalculatorError("non_numeric_literal")
    if isinstance(node.value, int):
        return Fraction(node.value)
    return Fraction(str(node.value))


def _evaluate(node: ast.AST) -> Fraction:
    if isinstance(node, ast.Expression):
        return _evaluate(node.body)
    if isinstance(node, ast.Constant):
        return _number(node)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _evaluate(node.operand)
        return value if isinstance(node.op, ast.UAdd) else -value
    if not isinstance(node, ast.BinOp):
        raise CalculatorError(f"unsupported_syntax:{type(node).__name__}")
    left, right = _evaluate(node.left), _evaluate(node.right)
    try:
        if isinstance(node.op, ast.Add):
            result = left + right
        elif isinstance(node.op, ast.Sub):
            result = left - right
        elif isinstance(node.op, ast.Mult):
            result = left * right
        elif isinstance(node.op, ast.Div):
            result = left / right
        elif isinstance(node.op, ast.FloorDiv):
            result = Fraction(left // right)
        elif isinstance(node.op, ast.Mod):
            result = left % right
        elif isinstance(node.op, ast.Pow):
            if right.denominator != 1 or abs(right.numerator) > MAX_EXPONENT:
                raise CalculatorError("exponent_out_of_range")
            result = left**right.numerator
        else:
            raise CalculatorError(f"unsupported_operator:{type(node.op).__name__}")
    except ZeroDivisionError as exc:
        raise CalculatorError("division_by_zero") from exc
    return _check_size(result)


def calculate(expression: str) -> dict[str, str | bool]:
    if not isinstance(expression, str):
        raise CalculatorError("expression_must_be_string")
    if not expression or len(expression) > MAX_EXPRESSION_LENGTH:
        raise CalculatorError("expression_length_out_of_range")
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, ValueError) as exc:
        raise CalculatorError("invalid_expression") from exc
    if sum(1 for _ in ast.walk(tree)) > MAX_NODES:
        raise CalculatorError("too_many_ast_nodes")
    value = _evaluate(tree)
    with localcontext() as context:
        context.prec = 40
        decimal = Decimal(value.numerator) / Decimal(value.denominator)
    exact = str(value.numerator)
    if value.denominator != 1:
        exact += f"/{value.denominator}"
    return {"ok": True, "exact": exact, "decimal": format(decimal, "f")}
