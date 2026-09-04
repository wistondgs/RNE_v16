"""M7-B safety gates for the bounded declarative program DSL."""

from __future__ import annotations

import pytest

from lab.genesis.acquisition.contracts import ProgramSkillArtifact
from lab.genesis.acquisition.dsl import (
    DSLEvaluationError,
    DSLSpecification,
    DSLValidationError,
    canonical_expression,
    evaluate_expression,
    expression_metrics,
    validate_program_skill,
)
from lab.genesis.contracts.serialization import canonical_sha256


def h(label: str) -> str:
    return canonical_sha256({"m7b": label})


def spec() -> DSLSpecification:
    return DSLSpecification(
        schema_version="genesis-m7-dsl-spec-v1",
        dsl_version="genesis-m7-dsl-v1",
        allowed_constants=(-2, -1, 0, 1, 2, 3),
        max_ast_depth=4,
        max_ast_nodes=12,
        max_absolute_value=100,
    )


def affine() -> dict[str, object]:
    return {
        "op": "ADD",
        "args": (
            {"op": "MUL_CONST", "args": ({"op": "X", "args": ()},), "value": 2},
            {"op": "CONST", "args": (), "value": 3},
        ),
    }


def test_dsl_is_canonical_and_executes_deterministically_without_callbacks() -> None:
    definition = spec()
    left = canonical_expression(affine(), definition)
    right = canonical_expression({"args": affine()["args"], "op": "ADD"}, definition)
    assert left == right
    assert expression_metrics(left, definition) == {"node_count": 4, "ast_depth": 3}
    assert tuple(evaluate_expression(left, value, definition) for value in range(-3, 4)) == (-3, -1, 1, 3, 5, 7, 9)


@pytest.mark.parametrize(
    "expression, reason",
    [
        ({"op": "__import__", "args": ()}, "unknown_operator"),
        ({"op": "ADD", "args": ({"op": "X", "args": ()},)}, "arity"),
        ({"op": "X", "args": (), "value": 1}, "value_binding"),
        ({"op": "CONST", "args": (), "value": 99}, "constant"),
        ({"op": "X"}, "shape"),
    ],
)
def test_dsl_rejects_invalid_or_non_declarative_ast(expression: dict[str, object], reason: str) -> None:
    with pytest.raises(DSLValidationError, match=reason):
        canonical_expression(expression, spec())


def test_dsl_rejects_depth_and_numeric_overflow() -> None:
    definition = spec()
    deep: dict[str, object] = {"op": "X", "args": ()}
    for _ in range(4):
        deep = {"op": "ABS", "args": (deep,)}
    with pytest.raises(DSLValidationError, match="budget"):
        canonical_expression(deep, definition)
    overflowing = {"op": "SQUARE", "args": ({"op": "X", "args": ()},)}
    with pytest.raises(DSLEvaluationError, match="output_out_of_bounds"):
        evaluate_expression(overflowing, 11, definition)


def test_program_skill_requires_the_same_dsl_semantics_as_its_identity_contract() -> None:
    definition = spec()
    skill = ProgramSkillArtifact(
        schema_version="genesis-m7-program-skill-v1",
        skill_kind="FINITE_INTEGER_FUNCTION",
        dsl_version=definition.dsl_version,
        input_contract={"kind": "integer"},
        output_contract={"kind": "integer"},
        program_ast=affine(),
        complexity={"node_count": 4, "ast_depth": 3},
        required_primitives=("ADD", "CONST", "MUL_CONST", "X"),
        discovery_campaign_hash=h("campaign"),
        provenance_hashes=(h("train"),),
    )
    assert validate_program_skill(skill, definition)
    different_language = DSLSpecification(
        schema_version=definition.schema_version,
        dsl_version="different",
        allowed_constants=definition.allowed_constants,
        max_ast_depth=definition.max_ast_depth,
        max_ast_nodes=definition.max_ast_nodes,
        max_absolute_value=definition.max_absolute_value,
    )
    assert not validate_program_skill(skill, different_language)
