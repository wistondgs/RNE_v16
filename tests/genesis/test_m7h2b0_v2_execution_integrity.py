"""M7-H2B0 falsification tests; no canonical V2 campaign is executed here."""

from __future__ import annotations

from dataclasses import replace

import pytest

from lab.genesis.acquisition.benchmark import Example, LearnerTrainingView
from lab.genesis.acquisition.contracts import (
    AcquisitionCampaignManifest,
    CANDIDATE_RANKING_RULE,
    CapabilityManifest,
    HUMAN_INTERVENTION_POLICY,
    PROMOTION_RULE,
)
from lab.genesis.acquisition.dsl import DSLSpecification
from lab.genesis.acquisition.ranked_synthesis import (
    RankCanonicalProgramSynthesizer,
    ranked_search_policy,
)
from lab.genesis.acquisition.synthesis import (
    V1_SYNTHESIZER_IMPLEMENTATION_HASH,
    DeterministicProgramSynthesizer,
    replay_v1_synthesis,
)
from lab.genesis.acquisition.v2_execution import (
    ResourceTerminationCause,
    V2ExecutionBinding,
    V2ExecutionOutcome,
    V2ExecutionTermination,
    V2LevelTranscript,
    V2SynthesisReceipt,
    replay_v2_toy_execution,
    run_v2_toy_execution,
)
from lab.genesis.contracts.serialization import canonical_sha256


def h(value: object) -> str:
    return canonical_sha256({"m7h2b0": value})


def toy_specification(*, constants: tuple[int, ...] = (-2, -1, 0, 1, 2)) -> DSLSpecification:
    return DSLSpecification("m7h2b0", "genesis-m7-toy-dsl-v1", constants, 3, 2, 1_000)


def toy_training(*, task_id: str = "toy-square", outputs: tuple[int, ...] | None = None) -> LearnerTrainingView:
    inputs = (-2, -1, 0, 1, 2)
    return LearnerTrainingView(
        task_id,
        tuple(Example(value, output) for value, output in zip(inputs, outputs or (4, 1, 0, 1, 4))),
        h(("training", task_id, outputs)),
    )


def toy_binding(
    specification: DSLSpecification,
    training: LearnerTrainingView,
    *,
    raw_cap: int = 100,
    behavior_cap: int = 100,
    wall_cap: int = 5,
    memory_mib: int = 256,
) -> V2ExecutionBinding:
    policy = ranked_search_policy(
        specification=specification,
        policy_id=f"toy-v2-{raw_cap}-{behavior_cap}-{wall_cap}",
        max_ast_nodes=2,
        max_ast_depth=specification.max_ast_depth,
        max_raw_ast_evaluations=raw_cap,
        max_distinct_behaviors=behavior_cap,
        wall_time_limit_seconds=wall_cap,
    )
    return V2ExecutionBinding(
        "genesis-m7-v2-execution-binding-h2b0", "toy-v2-campaign", training.task_id,
        h("campaign"), h(("task-binding", training.task_id)), h("acceptance"),
        h("battery"), h("complete-frontier-policy"), policy, specification.dsl_hash,
        "RANK_CANONICAL_BEHAVIOR_REPRESENTATIVE-v2",
        "genesis-m7-rank-canonical-enumerative-synthesizer-v2",
        canonical_sha256({"synthesizer": "genesis-m7-rank-canonical-enumerative-synthesizer-v2"}),
        2, specification.max_ast_depth, 2, raw_cap, behavior_cap, wall_cap, memory_mib,
    )


def successful_toy() -> tuple[V2ExecutionBinding, DSLSpecification, LearnerTrainingView, V2ExecutionOutcome]:
    specification = toy_specification()
    training = toy_training()
    binding = toy_binding(specification, training)
    return binding, specification, training, run_v2_toy_execution(
        binding=binding, specification=specification, training=training,
    )


def test_v2_native_execution_has_complete_levels_and_a_fresh_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    """The V1 path raises if touched; native V2 execution still succeeds."""

    def v1_must_not_run(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("V2 must never enter the V1 synthesizer")

    monkeypatch.setattr(DeterministicProgramSynthesizer, "synthesize", v1_must_not_run)
    specification = toy_specification()
    training = toy_training()
    binding = toy_binding(specification, training)
    outcome = run_v2_toy_execution(
        binding=binding, specification=specification, training=training,
        test_v1_synthesis_tripwire=True,
    )

    assert outcome.receipt.search_semantics_id == "RANK_CANONICAL_BEHAVIOR_REPRESENTATIVE-v2"
    assert outcome.receipt.termination_reason is V2ExecutionTermination.SELECTED_AFTER_COMPLETE_LEVEL
    assert outcome.selected_candidate is not None
    assert outcome.receipt.selected_candidate_hash == outcome.selected_candidate.program_hash
    assert outcome.receipt.completed_levels == (1, 2)
    assert tuple(item.mdl_level for item in outcome.level_transcripts) == (1, 2)
    assert all(item.level_complete for item in outcome.level_transcripts)
    assert outcome.level_transcripts[-1].event_status == "EXACT_CANDIDATE_AFTER_COMPLETE_LEVEL"

    replayed = replay_v2_toy_execution(
        binding=binding, specification=specification, training=training, outcome=outcome,
    )
    assert replayed.receipt.semantic_payload() == outcome.receipt.semantic_payload()
    assert replayed.selected_candidate is not None
    assert replayed.selected_candidate.program_hash == outcome.selected_candidate.program_hash


def test_raw_cap_mid_level_never_promotes_an_encountered_exact_candidate() -> None:
    """The historical level-two constant-six witness is intentionally partial."""

    specification = toy_specification(constants=(-2, -1, 0, 1, 2, 3))
    training = toy_training(task_id="toy-constant-six", outputs=(6, 6, 6, 6, 6))
    binding = toy_binding(specification, training, raw_cap=43)
    outcome = run_v2_toy_execution(binding=binding, specification=specification, training=training)

    assert outcome.receipt.termination_reason is V2ExecutionTermination.NOT_PROVEN_RESOURCE_EXHAUSTION
    assert outcome.receipt.completed_levels == (1,)
    assert outcome.receipt.current_level == 2
    assert outcome.receipt.current_level_complete is False
    assert outcome.selected_candidate is None
    assert outcome.level_transcripts[-1].level_complete is False
    assert outcome.level_transcripts[-1].exact_candidate_count >= 1
    assert outcome.resource_receipt.termination_cause is ResourceTerminationCause.RAW_AST_CAP_REACHED
    assert replay_v2_toy_execution(
        binding=binding, specification=specification, training=training, outcome=outcome,
    ).receipt.semantic_payload() == outcome.receipt.semantic_payload()


def test_external_wall_clock_cap_interrupts_a_current_level() -> None:
    binding, specification, training, _outcome = successful_toy()
    # This fixture isolates the wall-clock boundary with a deliberately ample
    # *toy* memory envelope; the next test independently exercises memory.
    binding = toy_binding(specification, training, wall_cap=1, memory_mib=16_384)
    outcome = run_v2_toy_execution(
        binding=binding, specification=specification, training=training,
        test_step_delay_seconds=0.15,
    )

    assert outcome.receipt.termination_reason is V2ExecutionTermination.NOT_PROVEN_RESOURCE_EXHAUSTION
    assert outcome.receipt.current_level_complete is False
    assert outcome.selected_candidate is None
    assert outcome.resource_receipt.termination_cause is ResourceTerminationCause.WALL_TIME_CAP_REACHED
    assert outcome.resource_receipt.wall_elapsed_milliseconds >= 1_000


def test_external_rss_watchdog_enforces_a_memory_breach() -> None:
    binding, specification, training, _outcome = successful_toy()
    binding = toy_binding(specification, training, memory_mib=1)
    outcome = run_v2_toy_execution(
        binding=binding, specification=specification, training=training,
        test_step_delay_seconds=0.15,
    )

    assert outcome.receipt.termination_reason is V2ExecutionTermination.NOT_PROVEN_RESOURCE_EXHAUSTION
    assert outcome.selected_candidate is None
    assert outcome.resource_receipt.termination_cause is ResourceTerminationCause.MEMORY_CAP_REACHED
    assert outcome.resource_receipt.peak_observed_memory_bytes > 1_024 * 1_024


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("raw_ast_count", lambda receipt: receipt.raw_ast_count + 1),
        ("behavior_class_count", lambda receipt: receipt.behavior_class_count + 1),
    ),
)
def test_resealed_counter_tampering_is_rederived_and_rejected(field: str, replacement) -> None:
    binding, specification, training, outcome = successful_toy()
    payload = outcome.receipt.canonical_payload()
    if field == "raw_ast_count":
        payload["raw_ast_count"] += 1
        payload["dedup_count"] += 1
    else:
        payload["behavior_class_count"] += 1
        payload["dedup_count"] -= 1
    tampered = V2SynthesisReceipt(**payload)
    altered = replace(outcome, receipt=tampered)

    with pytest.raises(ValueError, match="receipt_invalid"):
        replay_v2_toy_execution(
            binding=binding, specification=specification, training=training, outcome=altered,
        )


@pytest.mark.parametrize(
    "mutate",
    (
        lambda payload: payload.update({"enumeration_digest": h("bad-enumeration")}),
        lambda payload: payload.update({"representative_set_digest": h("bad-representatives")}),
        lambda payload: payload.update({"exact_candidate_set_digest": h("bad-exact")}),
        lambda payload: payload.update({"mdl_level": 3}),
        lambda payload: payload.update({
            "level_complete": False,
            "event_status": "RESOURCE_EXHAUSTED_INCOMPLETE_LEVEL",
            "selected_candidate_hash": None,
        }),
    ),
)
def test_resealed_level_transcript_tampering_is_rejected(mutate) -> None:
    binding, specification, training, outcome = successful_toy()
    payload = outcome.level_transcripts[-1].canonical_payload()
    mutate(payload)
    tampered = V2LevelTranscript(**payload)
    altered = replace(outcome, level_transcripts=(*outcome.level_transcripts[:-1], tampered))

    with pytest.raises(ValueError, match="receipt_invalid"):
        replay_v2_toy_execution(
            binding=binding, specification=specification, training=training, outcome=altered,
        )


def _v1_campaign(specification: DSLSpecification) -> AcquisitionCampaignManifest:
    baseline = CapabilityManifest("h2b0-v1-g0", "m7", ())
    splits = ("TRAIN", "AUDIT", "HIDDEN", "TRANSFER")
    return AcquisitionCampaignManifest(
        "h2b0-v1-replay", "m7", h("snapshot"), baseline.manifest_hash,
        specification.dsl_hash, V1_SYNTHESIZER_IMPLEMENTATION_HASH,
        {split: h(("commitment", split)) for split in splits}, h("generator"),
        {split: h(("seed", split)) for split in splits}, {"max_candidates": 64},
        specification.max_ast_depth, specification.max_ast_nodes, specification.allowed_constants,
        tuple(item.value for item in specification.operators), CANDIDATE_RANKING_RULE,
        PROMOTION_RULE, h("cfi"), h("resource"), 30, HUMAN_INTERVENTION_POLICY,
        (h("obligation"),),
    )


def test_v1_v2_laundering_matrix_rejects_cross_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    binding, specification, training, v2 = successful_toy()
    campaign = _v1_campaign(specification)
    v1 = DeterministicProgramSynthesizer().synthesize(
        campaign=campaign, specification=specification, training=training,
    )

    def v2_must_not_run(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("historical V1 replay must not enter V2")

    monkeypatch.setattr(RankCanonicalProgramSynthesizer, "synthesize", v2_must_not_run)
    assert replay_v1_synthesis(
        campaign=campaign, specification=specification, training=training, receipt=v1.receipt,
    ).receipt.synthesis_hash == v1.receipt.synthesis_hash
    with pytest.raises(ValueError, match="version_mismatch"):
        replay_v2_toy_execution(
            binding=binding, specification=specification, training=training, outcome=v1,  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="version_mismatch"):
        replay_v1_synthesis(
            campaign=campaign, specification=specification, training=training,
            receipt=v2.receipt,  # type: ignore[arg-type]
        )


def test_policy_identity_and_canonical_campaign_guard_cannot_be_resealed() -> None:
    binding, specification, training, outcome = successful_toy()
    with pytest.raises(ValueError, match="policy_limits_invalid"):
        replace(binding, max_raw_ast_evaluations=99)
    with pytest.raises(ValueError, match="identity_invalid"):
        replace(binding, campaign_id="m7h2-confirmatory-affine-0")
    with pytest.raises(ValueError, match="identity_invalid"):
        replace(binding, search_implementation_hash=h("not-v2"))

    forged = replace(binding, campaign_hash=h("other-campaign"))
    with pytest.raises(ValueError, match="receipt_invalid"):
        replay_v2_toy_execution(
            binding=forged, specification=specification, training=training, outcome=outcome,
        )


def test_h2b0_adapter_never_consumes_a_canonical_audit_slot() -> None:
    """The H2B0 public entrypoint rejects every predeclared campaign identifier."""

    specification = toy_specification()
    training = toy_training()
    policy = ranked_search_policy(
        specification=specification, policy_id="canonical-rejected", max_ast_nodes=2,
        max_ast_depth=3, max_raw_ast_evaluations=100, max_distinct_behaviors=100,
        wall_time_limit_seconds=5,
    )
    for campaign_id in (
        "m7h2-confirmatory-abs_affine-0",
        "m7h2-confirmatory-abs_affine-1",
        "m7h2-confirmatory-affine-0",
        "m7h2-confirmatory-affine-1",
        "m7h2-confirmatory-quadratic_simple-0",
        "m7h2-confirmatory-quadratic_simple-1",
    ):
        with pytest.raises(ValueError, match="identity_invalid"):
            V2ExecutionBinding(
                "genesis-m7-v2-execution-binding-h2b0", campaign_id, training.task_id,
                h("campaign"), h("task"), h("accept"), h("battery"), h("policy"), policy,
                specification.dsl_hash, "RANK_CANONICAL_BEHAVIOR_REPRESENTATIVE-v2",
                "genesis-m7-rank-canonical-enumerative-synthesizer-v2",
                canonical_sha256({"synthesizer": "genesis-m7-rank-canonical-enumerative-synthesizer-v2"}),
                2, 3, 2, 100, 100, 5, 256,
            )
