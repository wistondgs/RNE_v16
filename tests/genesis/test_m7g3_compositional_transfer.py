"""M7-G3: compositional transfer is a distinct, replayable M6 observation."""

from __future__ import annotations

import pytest

from lab.genesis.acquisition.audit import DurableAuditClaimRegistry
from lab.genesis.acquisition.benchmark import TaskBenchmarkBinding, canonical_benchmark
from lab.genesis.acquisition.campaign import AutonomousAcquisitionCampaign
from lab.genesis.acquisition.composition import (
    CompositionalTransferProtocol,
    CompositionalWrapper,
    compositional_transfer_protocol_commitment,
    confirmatory_compositional_transfer_protocol,
    materialize_compositional_transfer_evidence,
    replay_compositional_transfer_evidence,
)
from lab.genesis.acquisition.confirmation import confirmatory_policy
from lab.genesis.acquisition.contracts import (
    AcquisitionCampaignManifest,
    CANDIDATE_RANKING_RULE,
    CapabilityManifest,
    HUMAN_INTERVENTION_POLICY,
    PROMOTION_RULE,
)
from lab.genesis.acquisition.dsl import DSLSpecification
from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.evidence.artifacts import ContentAddressedArtifactStore


def h(value: object) -> str:
    return canonical_sha256({"m7g3": value})


def prepared(tmp_path):
    specification = DSLSpecification(
        "m7", "genesis-m7-dsl-v1", (-2, -1, 0, 1, 2, 3), 5, 12, 10_000
    )
    benchmark = canonical_benchmark(specification, seed=17)
    baseline = CapabilityManifest("m7g3-g0", "m7", ())
    policy = confirmatory_policy(
        canonical_battery_manifest_hash=benchmark.manifest.manifest_hash,
        audit_policy_hash=h("audit-policy"),
        compositional_transfer_protocol_hash=compositional_transfer_protocol_commitment(),
    )
    protocol = confirmatory_compositional_transfer_protocol(
        policy=policy, evaluation_policy_hash=h("m6-compositional-evaluation-policy"),
    )
    descriptor = next(item for item in benchmark.manifest.tasks if item.task_id == "affine-0")
    campaign = AcquisitionCampaignManifest(
        "m7g3-confirmatory-affine-0", "m7", h("snapshot"), baseline.manifest_hash,
        specification.dsl_hash, h("synthesizer"), descriptor.split_commitments,
        benchmark.manifest.generator_implementation_hash,
        {split: h(("seed", split)) for split in ("TRAIN", "AUDIT", "HIDDEN", "TRANSFER")},
        {"max_candidates": 256}, specification.max_ast_depth, specification.max_ast_nodes,
        specification.allowed_constants, tuple(item.value for item in specification.operators),
        CANDIDATE_RANKING_RULE, PROMOTION_RULE, h("cfi"), h("budget"), 30,
        HUMAN_INTERVENTION_POLICY, (h("obligation"),), policy.policy_hash,
        benchmark.manifest.manifest_hash, "CONFIRMATORY_GE_I_EVIDENCE",
    )
    binding = TaskBenchmarkBinding(
        "genesis-m7-task-benchmark-binding-v1", campaign.campaign_hash,
        benchmark.manifest.manifest_hash, "affine-0", descriptor.split_commitments,
    )
    result = AutonomousAcquisitionCampaign().run(
        campaign=campaign, specification=specification, benchmark=benchmark,
        g0_manifest=baseline, task_id="affine-0", g1_manifest_id="m7g3-g1",
        task_benchmark_binding=binding,
        audit_registry=DurableAuditClaimRegistry(tmp_path / "audit", policy=policy),
    )
    return policy, protocol, campaign, baseline, benchmark, result


def test_two_predeclared_wrappers_are_certified_through_distinct_m6_scopes(tmp_path) -> None:
    policy, protocol, campaign, baseline, benchmark, result = prepared(tmp_path)

    evidence = materialize_compositional_transfer_evidence(
        policy=policy, protocol=protocol, campaign=campaign, baseline=baseline,
        benchmark=benchmark, task_id="affine-0", result=result,
    )

    assert evidence.validate()
    assert tuple(item.wrapper for item in evidence.bindings) == tuple(CompositionalWrapper)
    assert len({item.binding_hash for item in evidence.bindings}) == 2
    assert all(item.scope.measurement_mode == "COMPOSITIONAL" for item in evidence.measurements)
    assert all(
        item.scope.measurement_binding_hash == binding.binding_hash
        and item.scope.candidate_skill_hash == binding.binding_hash
        for binding, item in zip(evidence.bindings, evidence.measurements)
    )
    assert all(item.adjudication.verdict.value == "PASS" for item in evidence.measurements)
    assert all(
        binding.promoted_skill_hash == result.synthesis.selected_skill.skill_hash
        for binding in evidence.bindings
    )


def test_each_compositional_trace_replays_from_fresh_cas(tmp_path) -> None:
    policy, protocol, campaign, baseline, benchmark, result = prepared(tmp_path)
    evidence = materialize_compositional_transfer_evidence(
        policy=policy, protocol=protocol, campaign=campaign, baseline=baseline,
        benchmark=benchmark, task_id="affine-0", result=result,
    )
    store = ContentAddressedArtifactStore(tmp_path / "cas")
    persisted = evidence.persist_traces(store)

    assert len(persisted) == 2
    assert all(
        replay_compositional_transfer_evidence(
            ContentAddressedArtifactStore(tmp_path / "cas"), item.closure_hash
        ).admitted
        for item in persisted
    )


def test_protocol_rejects_a_wrapper_set_or_commitment_tamper() -> None:
    policy = confirmatory_policy(
        canonical_battery_manifest_hash=h("canonical-battery"),
        audit_policy_hash=h("audit-policy"),
        compositional_transfer_protocol_hash=compositional_transfer_protocol_commitment(),
    )
    with pytest.raises(ValueError, match="wrappers_invalid"):
        CompositionalTransferProtocol(
            "genesis-m7-compositional-transfer-protocol-v1", "tampered", policy.policy_hash,
            h("evaluation"), compositional_transfer_protocol_commitment(),
            tuple(reversed(tuple(CompositionalWrapper))),
        )
    with pytest.raises(ValueError, match="commitment_invalid"):
        CompositionalTransferProtocol(
            "genesis-m7-compositional-transfer-protocol-v1", "tampered", policy.policy_hash,
            h("evaluation"), h("different-protocol"), tuple(CompositionalWrapper),
        )
