"""Expresiones booleanas acotadas para guardas de efectos MCI."""

from __future__ import annotations

import ast
from typing import Any, Mapping

from z3 import And, BoolVal, Not, Or, RealVal


_COMPARE = {
    ast.Gt: lambda left, right: left > right,
    ast.GtE: lambda left, right: left >= right,
    ast.Lt: lambda left, right: left < right,
    ast.LtE: lambda left, right: left <= right,
    ast.Eq: lambda left, right: left == right,
    ast.NotEq: lambda left, right: left != right,
}


def parse_condition(expression: str, allowed_names: set[str]) -> ast.Expression:
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Precondición inválida: {expression}") from exc
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id not in allowed_names:
            raise ValueError(f"Variable no permitida en precondición: {node.id}")
        if not isinstance(
            node,
            (
                ast.Expression,
                ast.BoolOp,
                ast.UnaryOp,
                ast.Compare,
                ast.Name,
                ast.Load,
                ast.Constant,
                ast.And,
                ast.Or,
                ast.Not,
                ast.Gt,
                ast.GtE,
                ast.Lt,
                ast.LtE,
                ast.Eq,
                ast.NotEq,
            ),
        ):
            raise ValueError(f"Operador no permitido: {type(node).__name__}")
    return tree


def evaluate_condition(expression: str | None, state: Mapping[str, Any]) -> bool:
    if not expression:
        return True
    tree = parse_condition(expression, set(state))
    return bool(_evaluate(tree.body, state, symbolic=False))


def compile_condition(expression: str | None, values: Mapping[str, Any]):
    if not expression:
        return BoolVal(True)
    tree = parse_condition(expression, set(values))
    return _evaluate(tree.body, values, symbolic=True)


def _evaluate(node: ast.AST, values: Mapping[str, Any], *, symbolic: bool):
    if isinstance(node, ast.Name):
        return values[node.id]
    if isinstance(node, ast.Constant):
        if symbolic and isinstance(node.value, bool):
            return BoolVal(node.value)
        if symbolic and isinstance(node.value, (int, float)):
            return RealVal(str(node.value))
        return node.value
    if isinstance(node, ast.BoolOp):
        parts = [_evaluate(item, values, symbolic=symbolic) for item in node.values]
        if symbolic:
            return And(*parts) if isinstance(node.op, ast.And) else Or(*parts)
        return all(parts) if isinstance(node.op, ast.And) else any(parts)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        value = _evaluate(node.operand, values, symbolic=symbolic)
        return Not(value) if symbolic else not value
    if isinstance(node, ast.Compare) and len(node.ops) == len(node.comparators) == 1:
        left = _evaluate(node.left, values, symbolic=symbolic)
        right = _evaluate(node.comparators[0], values, symbolic=symbolic)
        return _COMPARE[type(node.ops[0])](left, right)
    raise ValueError(f"Expresión no soportada: {ast.dump(node)}")
