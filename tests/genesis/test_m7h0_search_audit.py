"""Read-only H0 characterization of the historical M7 v1 search result.

This test intentionally exercises the v1 synthesizer without modifying it.
It is a gate for any future M7-H resource-policy experiment: expanding a
frontier is not valid while the enumerator can disagree with its declared
ranking within a TRAIN-behavior equivalence class.
"""

from __future__ import annotations

from lab.genesis.acquisition.benchmark import canonical_benchmark
from lab.genesis.acquisition.contracts import (
    CapabilityManifest,
    ProgramSkillArtifact,
    SynthesisTermination,
)
from lab.genesis.acquisition.dsl import (
    DSLSpecification,
    _evaluate_canonical_expression,
    expression_metrics,
    validate_program_skill,
)
from lab.genesis.acquisition.synthesis import DeterministicProgramSynthesizer, _expressions
from lab.genesis.contracts.serialization import canonical_sha256


def _specification() -> DSLSpecification:
    return DSLSpecification(
        "m7", "genesis-m7-dsl-v1", (-2, -1, 0, 1, 2, 3), 5, 12, 10_000
    )


def _campaign(specification: DSLSpecification):
    from lab.genesis.acquisition.contracts import (
        AcquisitionCampaignManifest,
        CANDIDATE_RANKING_RULE,
        HUMAN_INTERVENTION_POLICY,
        PROMOTION_RULE,
    )

    h = lambda value: canonical_sha256({"m7h0": value})
    baseline = CapabilityManifest("m7h0-g0", "genesis-m7-confirmatory-g0-v1", ())
    splits = ("TRAIN", "AUDIT", "HIDDEN", "TRANSFER")
    return AcquisitionCampaignManifest(
        "m7h0-historical-v1-abs-affine-1",
        "genesis-m7-confirmatory-campaign-v1",
        h("snapshot"),
        baseline.manifest_hash,
        specification.dsl_hash,
        h("synthesizer"),
        {split: h(("commitment", split)) for split in splits},
        h("generator"),
        {split: h(("seed", split)) for split in splits},
        {"max_candidates": 256},
        specification.max_ast_depth,
        specification.max_ast_nodes,
        specification.allowed_constants,
        tuple(item.value for item in specification.operators),
        CANDIDATE_RANKING_RULE,
        PROMOTION_RULE,
        h("cfi"),
        h("resource"),
        30,
        HUMAN_INTERVENTION_POLICY,
        (h("m6"),),
    )


def test_h0_authority_confirms_every_canonical_target_is_representable() -> None:
    specification = _specification()
    benchmark = canonical_benchmark(specification, seed=17)
    expected = {
        "abs_affine-0": {"node_count": 7, "ast_depth": 5},
        "abs_affine-1": {"node_count": 7, "ast_depth": 5},
        "affine-0": {"node_count": 4, "ast_depth": 3},
        "affine-1": {"node_count": 4, "ast_depth": 3},
        "quadratic_simple-0": {"node_count": 5, "ast_depth": 4},
        "quadratic_simple-1": {"node_count": 5, "ast_depth": 4},
    }

    # This is benchmark-authority inspection only.  The target AST is never
    # passed through LearnerTrainingView or into DeterministicProgramSynthesizer.
    observed = {
        task_id: expression_metrics(task.target_ast, specification)
        for task_id, task in benchmark._tasks.items()
    }
    assert observed == expected
    assert all(
        validate_program_skill(
            # The authority-side target is structurally a valid program skill
            # once bound to a synthetic immutable identity.
            ProgramSkillArtifact(
                "m7h0-authority-target", "FINITE_INTEGER_FUNCTION", specification.dsl_version,
                {"kind": "integer"}, {"kind": "integer"}, task.target_ast,
                expression_metrics(task.target_ast, specification),
                tuple(sorted({node["op"] for node in _nodes(task.target_ast)})),
                canonical_sha256({"authority": task_id}),
                (canonical_sha256({"authority-target": task_id}),),
            ),
            specification,
        )
        for task_id, task in benchmark._tasks.items()
    )


def _nodes(ast):
    return (ast, *(node for child in ast["args"] for node in _nodes(child)))


def test_h0_v1_abs_affine_1_exhausts_mid_level_five_before_target_complexity() -> None:
    specification = _specification()
    benchmark = canonical_benchmark(specification, seed=17)
    campaign = _campaign(specification)
    outcome = DeterministicProgramSynthesizer().synthesize(
        campaign=campaign,
        specification=specification,
        training=benchmark.learner_view("abs_affine-1"),
    )

    assert outcome.selected_skill is None
    assert outcome.receipt.termination is SynthesisTermination.BUDGET_EXHAUSTED
    assert outcome.receipt.candidates_examined == 256

    # Re-derive the exact observed resource frontier without accessing the
    # sealed target.  Levels 1--4 complete; the 256th unique TRAIN behavior is
    # found in level 5, while the authority-side target has seven nodes.
    seen: set[tuple[int, ...]] = set()
    accepted_per_level: dict[int, int] = {}
    last_level = None
    for expression in _expressions(specification, specification.max_ast_nodes):
        if len(seen) >= campaign.search_budget["max_candidates"]:
            break
        try:
            outputs = tuple(
                _evaluate_canonical_expression(
                    expression, item.input_value, specification
                )
                for item in benchmark.learner_view("abs_affine-1").training_examples
            )
        except ValueError:
            continue
        if outputs in seen:
            continue
        seen.add(outputs)
        last_level = expression_metrics(expression, specification)["node_count"]
        accepted_per_level[last_level] = accepted_per_level.get(last_level, 0) + 1

    assert accepted_per_level == {1: 7, 2: 12, 3: 41, 4: 159, 5: 37}
    assert last_level == 5


def test_h0_v1_train_dedup_does_not_preserve_declared_hash_tie_break() -> None:
    """A later canonical AST can outrank the retained representative.

    Both programs below have identical behavior on every integer input, not
    merely on TRAIN.  The v1 loop nevertheless retains the first program and
    discards the later program even though its canonical hash is lower.  This
    establishes ``ENUMERATION_COMPLETE_BY_LEVEL = NO`` for the declared
    ``training_error_then_mdl_then_canonical_program_hash-v1`` ranking.
    """

    specification = _specification()
    inputs = (-3, -2, -1, 0, 1, 2, 3)
    first_by_behavior = {}
    counterexample = None
    for position, expression in enumerate(_expressions(specification, 4), start=1):
        try:
            behavior = tuple(
                _evaluate_canonical_expression(expression, value, specification)
                for value in inputs
            )
        except ValueError:
            continue
        rank = (
            expression_metrics(expression, specification)["node_count"],
            canonical_sha256(expression),
        )
        prior = first_by_behavior.get(behavior)
        if prior is not None and rank < prior[0]:
            counterexample = prior, (rank, position, expression)
            break
        first_by_behavior.setdefault(behavior, (rank, position, expression))

    assert counterexample is not None
    retained, later = counterexample
    assert retained[1:] == (
        43,
        {"op": "MUL_CONST", "args": ({"op": "CONST", "args": (), "value": 2},), "value": 3},
    )
    assert later[1:] == (
        48,
        {"op": "MUL_CONST", "args": ({"op": "CONST", "args": (), "value": 3},), "value": 2},
    )
    assert later[0] < retained[0]
