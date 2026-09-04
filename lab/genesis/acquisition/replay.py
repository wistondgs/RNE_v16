"""Fresh-CAS semantic replay for M7 evidence materialized through M6."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from lab.genesis.acquisition.benchmark import (
    BenchmarkManifest,
    SealedBenchmarkReplayWitness,
    SplitEvaluation,
    TaskBenchmarkBinding,
    _restore_benchmark_replay_witness,
)
from lab.genesis.acquisition.campaign import (
    AcquisitionResult,
    PriorInsufficiencyReceipt,
)
from lab.genesis.acquisition.contracts import (
    AcquisitionCampaignManifest,
    CandidateCommitment,
    CapabilityManifest,
    ProgramSkillArtifact,
    PromotionReceipt,
    SynthesisReceipt,
)
from lab.genesis.acquisition.dsl import DSLSpecification
from lab.genesis.acquisition.federated_evidence import (
    FederatedMeasurementScope,
    ReferenceTargetCommitment,
    materialize_capability_arm_evidence,
    materialize_promoted_skill_evidence,
)
from lab.genesis.acquisition.m5_capability_runtime import CapabilityExecutionBinding
from lab.genesis.acquisition.synthesis import SynthesisOutcome
from lab.genesis.evidence.artifacts import ContentAddressedArtifactStore
from lab.genesis.evidence.trace_closure import TraceClosureManifest
from lab.genesis.evidence.trace_persistence import replay_m6_trace


_REQUIRED_M7_ROLES = (
    "m7_acquisition_campaign",
    "m7_baseline_capability_manifest",
    "m7_benchmark_manifest",
    "m7_sealed_benchmark_replay_witness",
    "m7_dsl_specification",
    "m7_task_benchmark_binding",
    "m7_reference_target_commitment",
    "m7_measurement_scope",
    "m7_prior_insufficiency_receipt",
    "m7_synthesis_receipt",
    "m7_program_skill",
    "m7_candidate_commitment",
    "m7_audit_evaluation",
    "m7_promotion_receipt",
    "m7_successor_capability_manifest",
)


@dataclass(frozen=True, slots=True)
class M7FederatedReplay:
    """Admission result after replaying M6 and rederiving the M7 source chain."""

    admitted: bool
    reasons: tuple[str, ...]
    trace_closure_hash: str


def _one_payload(
    store: ContentAddressedArtifactStore,
    closure: TraceClosureManifest,
    role: str,
) -> Mapping[str, Any]:
    group = next((item for item in closure.artifact_groups if item.role == role), None)
    if group is None:
        raise ValueError(f"genesis_m7_replay_role_missing:{role}")
    if len(group.artifact_hashes) != 1:
        raise ValueError(f"genesis_m7_replay_role_cardinality_invalid:{role}")
    payload = store.get(group.artifact_hashes[0])
    if not isinstance(payload, Mapping):
        raise ValueError(f"genesis_m7_replay_role_payload_invalid:{role}")
    return payload


def _restore_material(
    store: ContentAddressedArtifactStore,
    closure: TraceClosureManifest,
) -> tuple[
    AcquisitionCampaignManifest,
    CapabilityManifest,
    Any,
    str,
    AcquisitionResult,
    FederatedMeasurementScope,
    ReferenceTargetCommitment,
    TaskBenchmarkBinding,
]:
    payload = lambda role: _one_payload(store, closure, role)
    campaign = AcquisitionCampaignManifest.from_payload(payload("m7_acquisition_campaign"))
    baseline = CapabilityManifest.from_payload(payload("m7_baseline_capability_manifest"))
    manifest = BenchmarkManifest.from_payload(payload("m7_benchmark_manifest"))
    specification = DSLSpecification.from_payload(payload("m7_dsl_specification"))
    witness = SealedBenchmarkReplayWitness.from_payload(
        payload("m7_sealed_benchmark_replay_witness")
    )
    benchmark = _restore_benchmark_replay_witness(
        specification=specification,
        manifest=manifest,
        witness=witness,
    )
    task_binding = TaskBenchmarkBinding(**payload("m7_task_benchmark_binding"))
    target = ReferenceTargetCommitment(**payload("m7_reference_target_commitment"))
    scope = FederatedMeasurementScope(**payload("m7_measurement_scope"))
    prior = PriorInsufficiencyReceipt(**payload("m7_prior_insufficiency_receipt"))
    synthesis = SynthesisReceipt.from_payload(payload("m7_synthesis_receipt"))
    candidate = ProgramSkillArtifact.from_payload(payload("m7_program_skill"))
    commitment = CandidateCommitment.from_payload(payload("m7_candidate_commitment"))
    audit = SplitEvaluation.from_payload(payload("m7_audit_evaluation"))
    promotion = PromotionReceipt.from_payload(payload("m7_promotion_receipt"))
    successor = CapabilityManifest.from_payload(
        payload("m7_successor_capability_manifest")
    )
    result = AcquisitionResult(
        prior,
        SynthesisOutcome(synthesis, candidate, None),
        commitment,
        audit,
        promotion,
        successor,
        task_binding,
    )
    return campaign, baseline, benchmark, scope.task_id, result, scope, target, task_binding


def replay_m7_federated_evidence(
    store: ContentAddressedArtifactStore,
    trace_closure_hash: str,
) -> M7FederatedReplay:
    """Rebuild M7 and M6 evidence from a closure root and fresh CAS objects.

    M6 replay is a prerequisite, never a substitute: after M6 accepts its
    historical trace, this function restores the sealed evaluator benchmark,
    replays TRAIN synthesis, revalidates the committed audit candidate, and
    regenerates the exact same M6 adjudication receipt.
    """

    m6 = replay_m6_trace(store, trace_closure_hash)
    if not m6.admitted:
        return M7FederatedReplay(
            False,
            tuple(f"m6:{reason}" for reason in m6.reasons),
            trace_closure_hash,
        )
    try:
        closure = TraceClosureManifest.from_payload(store.get(trace_closure_hash))
        for role in _REQUIRED_M7_ROLES:
            _one_payload(store, closure, role)
        campaign, baseline, benchmark, task_id, result, scope, target, task_binding = _restore_material(
            store, closure
        )
        rebuilt = materialize_promoted_skill_evidence(
            campaign=campaign,
            baseline=baseline,
            benchmark=benchmark,
            task_id=task_id,
            result=result,
            split=scope.split,
        )
        if (
            rebuilt.scope.scope_hash != scope.scope_hash
            or rebuilt.target_commitment.commitment_hash != target.commitment_hash
            or rebuilt.task_binding.binding_hash != task_binding.binding_hash
            or m6.adjudication is None
            or rebuilt.adjudication.receipt_hash != m6.adjudication.receipt_hash
        ):
            return M7FederatedReplay(
                False,
                ("genesis_m7_replay_derivation_mismatch",),
                trace_closure_hash,
            )
    except (KeyError, TypeError, ValueError):
        return M7FederatedReplay(
            False,
            ("genesis_m7_replay_historical_material_invalid",),
            trace_closure_hash,
        )
    return M7FederatedReplay(True, (), trace_closure_hash)


def replay_m7_capability_arm_evidence(
    store: ContentAddressedArtifactStore,
    trace_closure_hash: str,
) -> M7FederatedReplay:
    """Re-derive an M6 closure for one M7-E2 executable causal arm.

    Generic M6 replay establishes the sealed trace's structural consistency.
    This second step restores the M7 acquisition sources and the declared
    executable arm state, then reruns the same M6 materializer.  In
    particular, a no-capability baseline is not reconstructed as a fictitious
    zero-valued program skill.
    """

    m6 = replay_m6_trace(store, trace_closure_hash)
    if not m6.admitted:
        return M7FederatedReplay(
            False,
            tuple(f"m6:{reason}" for reason in m6.reasons),
            trace_closure_hash,
        )
    try:
        closure = TraceClosureManifest.from_payload(store.get(trace_closure_hash))
        campaign, baseline, benchmark, task_id, result, scope, target, task_binding = _restore_material(
            store, closure
        )
        manifest = CapabilityManifest.from_payload(
            _one_payload(store, closure, "m7_causal_execution_manifest")
        )
        active_group = next(
            (item for item in closure.artifact_groups if item.role == "m7_causal_active_program_skill"),
            None,
        )
        if active_group is None:
            active = None
        else:
            active = ProgramSkillArtifact.from_payload(
                _one_payload(store, closure, "m7_causal_active_program_skill")
            )
        execution = CapabilityExecutionBinding.from_payload(
            _one_payload(store, closure, "m7_causal_execution_binding"),
            manifest=manifest,
            active_skill=active,
        )
        rebuilt = materialize_capability_arm_evidence(
            campaign=campaign,
            baseline=baseline,
            benchmark=benchmark,
            task_id=task_id,
            result=result,
            split=scope.split,
            execution_binding=execution,
        )
        if (
            rebuilt.scope.scope_hash != scope.scope_hash
            or rebuilt.target_commitment.commitment_hash != target.commitment_hash
            or rebuilt.task_binding.binding_hash != task_binding.binding_hash
            or rebuilt.scope.candidate_skill_hash != execution.execution_identity_hash
            or m6.adjudication is None
            or rebuilt.adjudication.receipt_hash != m6.adjudication.receipt_hash
        ):
            return M7FederatedReplay(
                False,
                ("genesis_m7_causal_arm_replay_derivation_mismatch",),
                trace_closure_hash,
            )
    except (KeyError, TypeError, ValueError):
        return M7FederatedReplay(
            False,
            ("genesis_m7_causal_arm_replay_historical_material_invalid",),
            trace_closure_hash,
        )
    return M7FederatedReplay(True, (), trace_closure_hash)
