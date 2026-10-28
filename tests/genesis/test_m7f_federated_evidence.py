"""M7-F1: promoted skills must enter M6 through real, replayable evidence."""

from __future__ import annotations

from dataclasses import replace

import pytest

from lab.genesis.acquisition.benchmark import (
    DatasetSplit,
    TaskBenchmarkBinding,
    canonical_benchmark,
)
from lab.genesis.acquisition.campaign import AutonomousAcquisitionCampaign
from lab.genesis.acquisition.contracts import (
    AcquisitionCampaignManifest,
    CANDIDATE_RANKING_RULE,
    CapabilityManifest,
    HUMAN_INTERVENTION_POLICY,
    PROMOTION_RULE,
)
from lab.genesis.acquisition.dsl import DSLSpecification
from lab.genesis.acquisition.federated_evidence import (
    materialize_promoted_skill_evidence,
)
from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.evidence import ContentAddressedArtifactStore, replay_m6_trace
from lab.genesis.verifiers import FederationVerdict, VerifierSovereignty


def h(value: object) -> str:
    return canonical_sha256({"m7f": value})


def prepared(*, bind: bool = True):
    specification = DSLSpecification(
        "m7", "genesis-m7-dsl-v1", (-2, -1, 0, 1, 2, 3), 5, 12, 10_000
    )
    benchmark = canonical_benchmark(specification, seed=17)
    baseline = CapabilityManifest("m7f-g0", "m7", ())
    descriptor = next(item for item in benchmark.manifest.tasks if item.task_id == "affine-0")
    campaign = AcquisitionCampaignManifest(
        "m7f-campaign",
        "m7",
        h("snapshot"),
        baseline.manifest_hash,
        specification.dsl_hash,
        h("synthesizer"),
        descriptor.split_commitments,
        benchmark.manifest.generator_implementation_hash,
        {split: h(("seed", split)) for split in ("TRAIN", "AUDIT", "HIDDEN", "TRANSFER")},
        {"max_candidates": 256},
        specification.max_ast_depth,
        specification.max_ast_nodes,
        specification.allowed_constants,
        tuple(item.value for item in specification.operators),
        CANDIDATE_RANKING_RULE,
        PROMOTION_RULE,
        h("cfi-policy"),
        h("resource-budget"),
        30,
        HUMAN_INTERVENTION_POLICY,
        (h("obligation"),),
    )
    binding = TaskBenchmarkBinding(
        "genesis-m7-task-benchmark-binding-v1",
        campaign.campaign_hash,
        benchmark.manifest.manifest_hash,
        "affine-0",
        descriptor.split_commitments,
    )
    result = AutonomousAcquisitionCampaign().run(
        campaign=campaign,
        specification=specification,
        benchmark=benchmark,
        g0_manifest=baseline,
        task_id="affine-0",
        g1_manifest_id="m7f-g1",
        task_benchmark_binding=binding if bind else None,
    )
    return campaign, baseline, benchmark, result


def test_promoted_hidden_skill_is_materialized_by_real_m6_pipeline(tmp_path) -> None:
    campaign, baseline, benchmark, result = prepared()

    evidence = materialize_promoted_skill_evidence(
        campaign=campaign,
        baseline=baseline,
        benchmark=benchmark,
        task_id="affine-0",
        result=result,
        split=DatasetSplit.HIDDEN,
    )

    assert evidence.adjudication.verdict is FederationVerdict.PASS
    assert evidence.material.receipt.status.value == "PASS"
    assert evidence.descriptor.sovereignty is VerifierSovereignty.SUPPORTING
    assert evidence.router.requirements[0].sovereign_required is False
    assert evidence.scope.split is DatasetSplit.HIDDEN
    assert evidence.scope.candidate_skill_hash == result.synthesis.selected_skill.skill_hash
    assert evidence.scope.reference_target_commitment_hash == evidence.target_commitment.commitment_hash

    persisted = evidence.persist_trace(ContentAddressedArtifactStore(tmp_path))
    replay = replay_m6_trace(ContentAddressedArtifactStore(tmp_path), persisted.closure_hash)
    roles = {group.role for group in persisted.closure.artifact_groups}
    assert replay.admitted
    assert {
        "m7_task_benchmark_binding",
        "m7_sealed_benchmark_replay_witness",
        "m7_reference_target_commitment",
        "m7_measurement_scope",
        "m7_program_skill",
        "m7_promotion_receipt",
    } <= roles


def test_certifiable_materialization_refuses_a_promoted_but_unbound_run() -> None:
    campaign, baseline, benchmark, result = prepared(bind=False)

    with pytest.raises(ValueError, match="acquisition_chain_invalid"):
        materialize_promoted_skill_evidence(
            campaign=campaign,
            baseline=baseline,
            benchmark=benchmark,
            task_id="affine-0",
            result=result,
            split=DatasetSplit.HIDDEN,
        )


def test_train_and_audit_cannot_be_relabelled_as_certifiable_measurements() -> None:
    campaign, baseline, benchmark, result = prepared()

    with pytest.raises(ValueError, match="split_not_certifiable"):
        materialize_promoted_skill_evidence(
            campaign=campaign,
            baseline=baseline,
            benchmark=benchmark,
            task_id="affine-0",
            result=result,
            split=DatasetSplit.AUDIT,
        )


def test_task_binding_cannot_point_to_a_task_with_other_predeclared_splits() -> None:
    campaign, baseline, benchmark, _result = prepared()
    other = next(item for item in benchmark.manifest.tasks if item.task_id == "affine-1")
    mismatched_binding = TaskBenchmarkBinding(
        "genesis-m7-task-benchmark-binding-v1",
        campaign.campaign_hash,
        benchmark.manifest.manifest_hash,
        "affine-1",
        other.split_commitments,
    )

    with pytest.raises(ValueError, match="task_benchmark_binding_invalid"):
        AutonomousAcquisitionCampaign().run(
            campaign=campaign,
            specification=benchmark.specification,
            benchmark=benchmark,
            g0_manifest=baseline,
            task_id="affine-1",
            g1_manifest_id="m7f-other-g1",
            task_benchmark_binding=mismatched_binding,
        )


def test_resealed_false_audit_cannot_enter_federated_evidence() -> None:
    campaign, baseline, benchmark, result = prepared()
    false_audit = replace(result.audit, exact_pass=False, correct=0)
    false_result = replace(result, audit=false_audit)

    with pytest.raises(ValueError, match="federated_audit_invalid"):
        materialize_promoted_skill_evidence(
            campaign=campaign,
            baseline=baseline,
            benchmark=benchmark,
            task_id="affine-0",
            result=false_result,
            split=DatasetSplit.HIDDEN,
        )
