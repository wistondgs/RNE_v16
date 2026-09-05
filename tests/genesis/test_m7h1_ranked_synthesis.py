"""M7-H1 proofs for versioned, rank-correct bounded synthesis search."""

from __future__ import annotations

import pytest

from lab.genesis.acquisition.benchmark import Example, LearnerTrainingView
from lab.genesis.acquisition.contracts import (
    AcquisitionCampaignManifest,
    CANDIDATE_RANKING_RULE,
    CapabilityManifest,
    HUMAN_INTERVENTION_POLICY,
    PROMOTION_RULE,
)
from lab.genesis.acquisition.dsl import DSLSpecification, _evaluate_canonical_expression
from lab.genesis.acquisition.ranked_synthesis import (
    RANKED_SYNTHESIZER_IMPLEMENTATION_HASH,
    SEARCH_SEMANTICS_V2_ID,
    RankCanonicalProgramSynthesizer,
    RankedSearchTermination,
    exhaustive_reference_search,
    ranked_search_policy,
    replay_ranked_synthesis,
)
from lab.genesis.acquisition.synthesis import (
    SEARCH_SEMANTICS_V1_ID,
    V1_SYNTHESIZER_IMPLEMENTATION_HASH,
    DeterministicProgramSynthesizer,
    _expressions,
    replay_v1_synthesis,
)
from lab.genesis.contracts.serialization import canonical_sha256


def h(value: object) -> str:
    return canonical_sha256({"m7h1": value})


def specification(
    constants: tuple[int, ...] = (-2, -1, 0, 1, 2, 3),
    *,
    max_depth: int = 4,
    max_nodes: int = 4,
) -> DSLSpecification:
    return DSLSpecification("m7h1", "genesis-m7-dsl-v1", constants, max_depth, max_nodes, 1_000)


def training(inputs: tuple[int, ...], outputs: tuple[int, ...], *, name: str) -> LearnerTrainingView:
    return LearnerTrainingView(
        name,
        tuple(Example(input_value, output_value) for input_value, output_value in zip(inputs, outputs)),
        h(("training", name, inputs, outputs)),
    )


def policy(definition: DSLSpecification, *, nodes: int, depth: int | None = None, raw: int | None = None, behaviors: int | None = None):
    return ranked_search_policy(
        specification=definition,
        policy_id=f"m7h1-{nodes}-{depth or definition.max_ast_depth}-{raw}-{behaviors}",
        max_ast_nodes=nodes,
        max_ast_depth=definition.max_ast_depth if depth is None else depth,
        max_raw_ast_evaluations=raw,
        max_distinct_behaviors=behaviors,
    )


def _program(definition: DSLSpecification, *, position: int):
    return next(expression for index, expression in enumerate(_expressions(definition, 4), start=1) if index == position)


def test_v2_hash_tiebreak_uses_minimum_hash_after_completing_level() -> None:
    definition = specification()
    view = training((-3, -2, -1, 0, 1, 2, 3), (6, 6, 6, 6, 6, 6, 6), name="constant-six")
    full_policy = policy(definition, nodes=2)
    first = _program(definition, position=43)
    canonical = _program(definition, position=48)
    assert canonical_sha256(canonical) < canonical_sha256(first)

    outcome = RankCanonicalProgramSynthesizer().synthesize(
        specification=definition, training=view, policy=full_policy,
    )
    permutations = tuple(
        RankCanonicalProgramSynthesizer().synthesize(
            specification=definition, training=view, policy=full_policy,
            test_enumeration_order=order,
        )
        for order in ("REVERSED", "OPERATOR_REVERSED", "CONSTANT_REVERSED")
    )

    assert outcome.receipt.completed_levels == (1, 2)
    assert outcome.receipt.termination_reason is RankedSearchTermination.EXACT_CANDIDATE_AFTER_COMPLETE_LEVEL
    assert outcome.selected_candidate is not None
    assert outcome.selected_candidate.program_hash == canonical_sha256(canonical)
    assert all(item.selected_candidate is not None for item in permutations)
    assert all(
        item.selected_candidate.program_hash == outcome.selected_candidate.program_hash
        for item in permutations
    )


def test_v2_lower_mdl_dominates_even_when_the_higher_mdl_hash_is_lower() -> None:
    definition = specification()
    identity = next(expression for expression in _expressions(definition, 1) if expression["op"] == "X")
    redundant_identity = next(
        expression
        for expression in _expressions(definition, 2)
        if expression["op"] == "MUL_CONST"
        and expression["args"][0]["op"] == "X"
        and expression["value"] == 1
    )
    assert canonical_sha256(redundant_identity) < canonical_sha256(identity)
    view = training((-2, -1, 0, 1, 2), (-2, -1, 0, 1, 2), name="identity")

    outcome = RankCanonicalProgramSynthesizer().synthesize(
        specification=definition, training=view, policy=policy(definition, nodes=2),
    )

    assert outcome.selected_candidate is not None
    assert outcome.selected_candidate.program_hash == canonical_sha256(identity)
    assert outcome.selected_candidate.mdl == 1


def test_v2_blocks_promotion_when_a_winning_level_is_partial() -> None:
    definition = specification()
    view = training((-3, -2, -1, 0, 1, 2, 3), (6, 6, 6, 6, 6, 6, 6), name="partial-six")
    partial = RankCanonicalProgramSynthesizer().synthesize(
        specification=definition,
        training=view,
        policy=policy(definition, nodes=2, raw=43),
    )
    completed = RankCanonicalProgramSynthesizer().synthesize(
        specification=definition,
        training=view,
        policy=policy(definition, nodes=2),
    )

    assert partial.selected_candidate is None
    assert partial.receipt.termination_reason is RankedSearchTermination.RESOURCE_EXHAUSTED_INCOMPLETE_LEVEL
    assert partial.receipt.current_level == 2
    assert partial.receipt.current_level_complete is False
    assert partial.receipt.completed_levels == (1,)
    assert completed.selected_candidate is not None
    assert completed.selected_candidate.program_hash == canonical_sha256(_program(definition, position=48))


def test_v2_distinct_behavior_cap_is_safety_not_a_completed_frontier() -> None:
    definition = specification()
    view = training((0,), (0,), name="behavior-cap")
    outcome = RankCanonicalProgramSynthesizer().synthesize(
        specification=definition,
        training=view,
        policy=policy(definition, nodes=2, behaviors=1),
    )

    assert outcome.selected_candidate is None
    assert outcome.receipt.termination_reason is RankedSearchTermination.RESOURCE_EXHAUSTED_INCOMPLETE_LEVEL
    assert outcome.receipt.current_level == 1
    assert outcome.receipt.current_level_complete is False


def test_v2_search_receipt_and_candidate_fields_are_derived_not_resealable() -> None:
    definition = specification()
    outcome = RankCanonicalProgramSynthesizer().synthesize(
        specification=definition,
        training=training((0,), (0,), name="receipt-forgery"),
        policy=policy(definition, nodes=2),
    )

    assert outcome.selected_candidate is not None
    with pytest.raises(ValueError, match="counts_inconsistent"):
        type(outcome.receipt)(
            **{
                **outcome.receipt.canonical_payload(),
                "deduplicated_count": 0,
            }
        )
    with pytest.raises(ValueError, match="counts_inconsistent"):
        type(outcome.receipt)(
            **{
                **outcome.receipt.canonical_payload(),
                "behavior_class_count": 0,
            }
        )
    with pytest.raises(ValueError, match="program_hash_invalid"):
        type(outcome.selected_candidate)(
            outcome.selected_candidate.program_ast,
            "0" * 64,
            outcome.selected_candidate.mdl,
            outcome.selected_candidate.ast_depth,
            outcome.selected_candidate.behavior_key,
            outcome.selected_candidate.training_error,
        )


def test_v2_matches_exhaustive_reference_across_bounded_matrix() -> None:
    cases = (
        ((-1, 0, 1), 2, 2, (-1, 0, 1), (-1, 0, 1)),
        ((-1, 0, 1), 2, 2, (-1, 0, 1), (0, 0, 0)),
        ((0, 1, 2), 2, 2, (-1, 0, 1), (2, 2, 2)),
        ((-1, 0, 1, 2), 3, 3, (-1, 0, 1), (1, 1, 1)),
        ((-1, 0, 1, 2), 3, 3, (-1, 0, 1), (-1, 0, 1)),
        ((-2, -1, 0, 1, 2, 3), 3, 4, (-1, 0, 1), (-1, 1, 3)),
        ((-2, -1, 0, 1, 2, 3), 3, 4, (-2, 0, 2), (4, 0, 4)),
        ((-1, 0, 1), 3, 4, (-1, 0, 1), (7, 7, 7)),
        ((-1, 0, 1, 2, 3), 4, 4, (-1, 0, 1), (-1, 0, 1)),
        ((-1, 0, 1, 2, 3), 4, 4, (-1, 0, 1), (1, 1, 1)),
        ((-2, -1, 0, 1, 2, 3), 4, 4, (-1, 0, 1), (3, 1, 3)),
        ((-2, -1, 0, 1, 2, 3), 4, 4, (-1, 0, 1), (9, 9, 9)),
    )
    for index, (constants, max_depth, nodes, inputs, outputs) in enumerate(cases):
        definition = specification(constants, max_depth=max_depth, max_nodes=nodes)
        view = training(inputs, outputs, name=f"matrix-{index}")
        search_policy = policy(definition, nodes=nodes, depth=max_depth)
        ranked = RankCanonicalProgramSynthesizer().synthesize(
            specification=definition, training=view, policy=search_policy,
        )
        reference = exhaustive_reference_search(
            specification=definition, training=view, policy=search_policy,
        )
        assert ranked.receipt.termination_reason is reference.receipt.termination_reason
        assert (None if ranked.selected_candidate is None else ranked.selected_candidate.program_hash) == (
            None if reference.selected_candidate is None else reference.selected_candidate.program_hash
        )
        assert (None if ranked.selected_candidate is None else ranked.selected_candidate.mdl) == (
            None if reference.selected_candidate is None else reference.selected_candidate.mdl
        )
        assert (None if ranked.selected_candidate is None else ranked.selected_candidate.behavior_key) == (
            None if reference.selected_candidate is None else reference.selected_candidate.behavior_key
        )


def test_v2_audit_consequence_is_determined_before_and_without_audit() -> None:
    definition = specification((-1, 0, 1, 2, 3), max_nodes=3)
    view = training((0,), (0,), name="audit-consequence")
    search_policy = policy(definition, nodes=2)
    normal = RankCanonicalProgramSynthesizer().synthesize(
        specification=definition, training=view, policy=search_policy,
    )
    reversed_outcome = RankCanonicalProgramSynthesizer().synthesize(
        specification=definition, training=view, policy=search_policy,
        test_enumeration_order="REVERSED",
    )
    square = next(
        expression for expression in _expressions(definition, 2)
        if expression["op"] == "SQUARE" and expression["args"][0]["op"] == "X"
    )

    assert normal.selected_candidate is not None
    assert reversed_outcome.selected_candidate is not None
    assert normal.selected_candidate.program_hash == reversed_outcome.selected_candidate.program_hash
    assert normal.selected_candidate.program_hash != canonical_sha256(square)
    # AUDIT is intentionally outside the search.  The canonical ranked choice
    # is wrong for this held-out target, while a TRAIN-equivalent alternative
    # would pass it; search still cannot inspect or substitute on that basis.
    selected_audit = _evaluate_canonical_expression(
        normal.selected_candidate.program_ast, 2, definition,
    )
    square_audit = _evaluate_canonical_expression(square, 2, definition)
    assert selected_audit != 4
    assert square_audit == 4


def _v1_campaign(definition: DSLSpecification) -> AcquisitionCampaignManifest:
    baseline = CapabilityManifest("m7h1-v1-g0", "m7", ())
    splits = ("TRAIN", "AUDIT", "HIDDEN", "TRANSFER")
    return AcquisitionCampaignManifest(
        "m7h1-v1-replay", "m7", h("snapshot"), baseline.manifest_hash,
        definition.dsl_hash, V1_SYNTHESIZER_IMPLEMENTATION_HASH,
        {split: h(("commitment", split)) for split in splits}, h("generator"),
        {split: h(("seed", split)) for split in splits}, {"max_candidates": 64},
        definition.max_ast_depth, definition.max_ast_nodes, definition.allowed_constants,
        tuple(item.value for item in definition.operators), CANDIDATE_RANKING_RULE,
        PROMOTION_RULE, h("cfi"), h("resource"), 30, HUMAN_INTERVENTION_POLICY,
        (h("obligation"),),
    )


def test_v1_v2_replay_is_explicitly_version_separated() -> None:
    definition = specification(max_nodes=3)
    view = training((-1, 0, 1), (-1, 0, 1), name="replay")
    v1_campaign = _v1_campaign(definition)
    v1 = DeterministicProgramSynthesizer().synthesize(
        campaign=v1_campaign, specification=definition, training=view,
    )
    v2_policy = policy(definition, nodes=3)
    v2 = RankCanonicalProgramSynthesizer().synthesize(
        specification=definition, training=view, policy=v2_policy,
    )

    assert SEARCH_SEMANTICS_V1_ID != SEARCH_SEMANTICS_V2_ID
    assert V1_SYNTHESIZER_IMPLEMENTATION_HASH != RANKED_SYNTHESIZER_IMPLEMENTATION_HASH
    assert replay_v1_synthesis(
        campaign=v1_campaign, specification=definition, training=view, receipt=v1.receipt,
    ).receipt.synthesis_hash == v1.receipt.synthesis_hash
    assert replay_ranked_synthesis(
        specification=definition, training=view, policy=v2_policy, receipt=v2.receipt,
    ).receipt.semantic_payload() == v2.receipt.semantic_payload()
    with pytest.raises(ValueError, match="version_mismatch"):
        replay_ranked_synthesis(
            specification=definition, training=view, policy=v2_policy, receipt=v1.receipt,  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="version_mismatch"):
        replay_v1_synthesis(
            campaign=v1_campaign, specification=definition, training=view, receipt=v2.receipt,  # type: ignore[arg-type]
        )
