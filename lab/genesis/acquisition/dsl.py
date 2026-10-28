"""A bounded, pure integer DSL for M7 program skills.

No AST node carries Python source, an import, a callable, or a capability to
access a process resource.  Evaluation is a total recursive interpretation of
the closed grammar below, with explicit size and integer bounds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from lab.genesis.contracts.serialization import canonical_sha256, freeze
from lab.genesis.acquisition.contracts import ProgramSkillArtifact


class ProgramOperator(str, Enum):
    X = "X"
    CONST = "CONST"
    ADD = "ADD"
    SUB = "SUB"
    MUL_CONST = "MUL_CONST"
    ABS = "ABS"
    SQUARE = "SQUARE"


_ARITIES = {
    ProgramOperator.X: 0,
    ProgramOperator.CONST: 0,
    ProgramOperator.ADD: 2,
    ProgramOperator.SUB: 2,
    ProgramOperator.MUL_CONST: 1,
    ProgramOperator.ABS: 1,
    ProgramOperator.SQUARE: 1,
}
_VALUE_OPERATORS = {ProgramOperator.CONST, ProgramOperator.MUL_CONST}


class DSLValidationError(ValueError):
    """A malformed or out-of-budget declarative program."""


class DSLEvaluationError(ValueError):
    """A pure evaluation that exceeded the declared integer bounds."""


@dataclass(frozen=True, slots=True)
class DSLSpecification:
    schema_version: str
    dsl_version: str
    allowed_constants: tuple[int, ...]
    max_ast_depth: int
    max_ast_nodes: int
    max_absolute_value: int
    operators: tuple[ProgramOperator, ...] = tuple(ProgramOperator)
    dsl_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.schema_version or not self.dsl_version:
            raise ValueError("genesis_dsl_identity_invalid")
        constants = tuple(sorted(self.allowed_constants))
        if not constants or len(constants) != len(set(constants)) or any(
            not isinstance(value, int) or isinstance(value, bool) for value in constants
        ):
            raise ValueError("genesis_dsl_constants_invalid")
        object.__setattr__(self, "allowed_constants", constants)
        operators = tuple(sorted((ProgramOperator(value) for value in self.operators), key=lambda item: item.value))
        if set(operators) != set(ProgramOperator) or len(operators) != len(set(operators)):
            raise ValueError("genesis_dsl_operator_set_invalid")
        object.__setattr__(self, "operators", operators)
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for value in (self.max_ast_depth, self.max_ast_nodes, self.max_absolute_value)
        ):
            raise ValueError("genesis_dsl_limits_invalid")
        object.__setattr__(self, "dsl_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "dsl_version": self.dsl_version,
            "allowed_constants": self.allowed_constants,
            "max_ast_depth": self.max_ast_depth,
            "max_ast_nodes": self.max_ast_nodes,
            "max_absolute_value": self.max_absolute_value,
            "operators": tuple(item.value for item in self.operators),
        }

    def validate(self) -> bool:
        try:
            return DSLSpecification(**self.canonical_payload()).dsl_hash == self.dsl_hash
        except (TypeError, ValueError):
            return False

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "DSLSpecification":
        return cls(**dict(payload))


def _canonical_node(node: Any, spec: DSLSpecification, *, depth: int = 1) -> tuple[Mapping[str, Any], int, int]:
    if not isinstance(node, Mapping) or set(node) - {"op", "args", "value"} or set(node) < {"op", "args"}:
        raise DSLValidationError("genesis_dsl_ast_shape_invalid")
    try:
        operator = ProgramOperator(node["op"])
    except (TypeError, ValueError) as error:
        raise DSLValidationError("genesis_dsl_unknown_operator") from error
    args = node["args"]
    if not isinstance(args, tuple):
        raise DSLValidationError("genesis_dsl_args_invalid")
    if len(args) != _ARITIES[operator]:
        raise DSLValidationError("genesis_dsl_arity_invalid")
    has_value = "value" in node
    if (operator in _VALUE_OPERATORS) != has_value:
        raise DSLValidationError("genesis_dsl_value_binding_invalid")
    result: dict[str, Any] = {"op": operator.value, "args": ()}
    if has_value:
        value = node["value"]
        if not isinstance(value, int) or isinstance(value, bool) or value not in spec.allowed_constants:
            raise DSLValidationError("genesis_dsl_constant_invalid")
        result["value"] = value
    children: list[Mapping[str, Any]] = []
    node_count = 1
    maximum_depth = depth
    for child in args:
        canonical_child, child_count, child_depth = _canonical_node(child, spec, depth=depth + 1)
        children.append(canonical_child)
        node_count += child_count
        maximum_depth = max(maximum_depth, child_depth)
    if maximum_depth > spec.max_ast_depth or node_count > spec.max_ast_nodes:
        raise DSLValidationError("genesis_dsl_ast_budget_exceeded")
    result["args"] = tuple(children)
    return freeze(result), node_count, maximum_depth


def canonical_expression(expression: Mapping[str, Any], spec: DSLSpecification) -> Mapping[str, Any]:
    """Validate and normalize a program without evaluating it."""

    if not spec.validate():
        raise DSLValidationError("genesis_dsl_spec_invalid")
    canonical, _nodes, _depth = _canonical_node(freeze(expression), spec)
    return canonical


def expression_metrics(expression: Mapping[str, Any], spec: DSLSpecification) -> Mapping[str, int]:
    """Return only derived structural metrics for a valid canonical expression."""

    _canonical, nodes, depth = _canonical_node(freeze(expression), spec)
    return freeze({"node_count": nodes, "ast_depth": depth})


def evaluate_expression(expression: Mapping[str, Any], value: int, spec: DSLSpecification) -> int:
    """Interpret a validated expression with bounded integer arithmetic only."""

    if not isinstance(value, int) or isinstance(value, bool) or abs(value) > spec.max_absolute_value:
        raise DSLEvaluationError("genesis_dsl_input_out_of_bounds")
    root = canonical_expression(expression, spec)
    return _evaluate_canonical_expression(root, value, spec)


def _evaluate_canonical_expression(expression: Mapping[str, Any], value: int, spec: DSLSpecification) -> int:
    """Evaluate an AST already produced by :func:`canonical_expression` once."""

    if not isinstance(value, int) or isinstance(value, bool) or abs(value) > spec.max_absolute_value:
        raise DSLEvaluationError("genesis_dsl_input_out_of_bounds")

    def bounded(result: int) -> int:
        if abs(result) > spec.max_absolute_value:
            raise DSLEvaluationError("genesis_dsl_output_out_of_bounds")
        return result

    def run(node: Mapping[str, Any]) -> int:
        operator = ProgramOperator(node["op"])
        args = tuple(run(child) for child in node["args"])
        if operator is ProgramOperator.X:
            return value
        if operator is ProgramOperator.CONST:
            return int(node["value"])
        if operator is ProgramOperator.ADD:
            return bounded(args[0] + args[1])
        if operator is ProgramOperator.SUB:
            return bounded(args[0] - args[1])
        if operator is ProgramOperator.MUL_CONST:
            return bounded(int(node["value"]) * args[0])
        if operator is ProgramOperator.ABS:
            return bounded(abs(args[0]))
        if operator is ProgramOperator.SQUARE:
            return bounded(args[0] * args[0])
        raise DSLValidationError("genesis_dsl_unknown_operator")

    return run(expression)


def validate_program_skill(skill: ProgramSkillArtifact, spec: DSLSpecification) -> bool:
    """Bind a sealed M7-A program artifact to the executable DSL semantics."""

    if not skill.validate() or not spec.validate() or skill.dsl_version != spec.dsl_version:
        return False
    try:
        return (
            canonical_expression(skill.program_ast, spec) == skill.program_ast
            and expression_metrics(skill.program_ast, spec) == skill.complexity
        )
    except DSLValidationError:
        return False
