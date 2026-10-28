"""M7-G4: one predeclared six-task GE-I confirmatory campaign battery."""

from __future__ import annotations

import pytest

from lab.genesis.acquisition.battery import (
    GEIBatteryStatus,
    GEICampaignAssessment,
    GEICampaignStatus,
    GateStatus,
    M7Status,
    build_confirmatory_campaign,
    close_confirmatory_battery,
    execute_confirmatory_campaign,
    predeclare_confirmatory_battery,
)
from lab.genesis.acquisition.composition import (
    compositional_transfer_protocol_commitment,
    confirmatory_compositional_transfer_protocol,
)
from lab.genesis.acquisition.confirmation import (
    CANONICAL_CONFIRMATORY_TASK_IDS,
    CampaignGate,
    confirmatory_policy,
)
from lab.genesis.acquisition.benchmark import canonical_benchmark
from lab.genesis.acquisition.dsl import DSLSpecification
from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.evidence.artifacts import ContentAddressedArtifactStore


def h(value: object) -> str:
    return canonical_sha256({"m7g4": value})


def predeclared():
    specification = DSLSpecification(
        "m7", "genesis-m7-dsl-v1", (-2, -1, 0, 1, 2, 3), 5, 12, 10_000
    )
    benchmark = canonical_benchmark(specification, seed=17)
    policy = confirmatory_policy(
        canonical_battery_manifest_hash=benchmark.manifest.manifest_hash,
        audit_policy_hash=h("audit-policy"),
        compositional_transfer_protocol_hash=compositional_transfer_protocol_commitment(),
    )
    protocol = confirmatory_compositional_transfer_protocol(
        policy=policy, evaluation_policy_hash=h("composition-evaluation-policy"),
    )
    battery = predeclare_confirmatory_battery(
        policy=policy, protocol=protocol, benchmark=benchmark,
        code_snapshot_hash=h("code-snapshot"), environment_commitment_hash=h("environment"),
    )
    return policy, protocol, benchmark, battery


def test_predeclaration_fixes_exact_task_slots_before_campaign_hashes_exist() -> None:
    policy, _protocol, benchmark, battery = predeclared()

    assert battery.validate()
    assert tuple(item.task_id for item in battery.task_plans) == CANONICAL_CONFIRMATORY_TASK_IDS
    assert len({item.campaign_id for item in battery.task_plans}) == 6
    assert len({item.baseline.manifest_hash for item in battery.task_plans}) == 6
    campaign, baseline, binding = build_confirmatory_campaign(
        policy=policy, battery=battery, benchmark=benchmark, task_id="affine-0",
    )
    assert campaign.confirmatory_battery_manifest_hash == battery.battery_manifest_hash
    assert baseline.manifest_hash == campaign.g0_capability_manifest_hash
    assert binding.campaign_hash == campaign.campaign_hash


def test_closure_rejects_a_missing_or_substituted_campaign_attestation(tmp_path) -> None:
    policy, protocol, benchmark, battery = predeclared()
    store = ContentAddressedArtifactStore(tmp_path / "cas")
    run = execute_confirmatory_campaign(
        policy=policy, battery=battery, protocol=protocol, benchmark=benchmark,
        task_id="affine-0", audit_root=tmp_path / "audit", store=store,
    )
    assert run.assessment.status is GEICampaignStatus.SUPPORTED
    with pytest.raises(ValueError, match="closure_invalid"):
        close_confirmatory_battery(policy=policy, battery=battery, runs=(run,))


def test_campaign_assessment_rejects_a_resealed_supported_status_with_missing_gate() -> None:
    gates = {item.value: GateStatus.PASS for item in CampaignGate}
    gates[CampaignGate.COMPOSITIONAL_TRANSFER.value] = GateStatus.NOT_PROVEN
    with pytest.raises(ValueError, match="status_not_derived"):
        GEICampaignAssessment(
            h("attestation"), h("policy"), h("battery"), "affine-0", h("campaign"),
            gates, GEICampaignStatus.SUPPORTED,
        )


def test_execute_complete_predeclared_confirmatory_battery_and_close(tmp_path) -> None:
    policy, protocol, benchmark, battery = predeclared()
    store = ContentAddressedArtifactStore(tmp_path / "cas")
    runs = tuple(
        execute_confirmatory_campaign(
            policy=policy, battery=battery, protocol=protocol, benchmark=benchmark,
            task_id=task_id, audit_root=tmp_path / "audit", store=store,
        )
        for task_id in CANONICAL_CONFIRMATORY_TASK_IDS
    )
    closure = close_confirmatory_battery(policy=policy, battery=battery, runs=runs)

    assert tuple(item.attestation.task_binding.task_id for item in runs) == CANONICAL_CONFIRMATORY_TASK_IDS
    assert next(
        item.assessment.status for item in runs
        if item.attestation.task_binding.task_id == "abs_affine-1"
    ) is GEICampaignStatus.NOT_PROVEN
    assert closure.status is GEIBatteryStatus.NOT_PROVEN
    assert closure.m7_status is M7Status.NOT_READY
    assert closure.validate()
