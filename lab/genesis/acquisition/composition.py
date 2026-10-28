"""Certified compositional-transfer observations for confirmatory M7.

The old M7 capability receipt records local benchmark composition checks.  It
is intentionally not reused here.  This module predeclares two executable
wrappers and sends each resulting ``wrapper(z)`` computation through the
normal M6 differential route with an independent scope and replay closure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from lab.genesis.acquisition.benchmark import (
    DatasetSplit,
    SealedCapabilityBenchmark,
    _benchmark_replay_witness,
)
from lab.genesis.acquisition.campaign import AcquisitionResult
from lab.genesis.acquisition.confirmation import GEIAcceptancePolicy
from lab.genesis.acquisition.contracts import AcquisitionCampaignManifest, CapabilityManifest
from lab.genesis.acquisition.dsl import evaluate_expression
from lab.genesis.acquisition.federated_evidence import (
    M7FederatedEvidence,
    _materialize_federated_execution_evidence,
    _validate_acquisition_chain,
)
from lab.genesis.acquisition.replay import _one_payload, _restore_material
from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.evidence.artifacts import ContentAddressedArtifactStore, is_artifact_hash
from lab.genesis.evidence.trace_closure import TraceClosureManifest
from lab.genesis.evidence.trace_persistence import PersistedTrace, replay_m6_trace


class CompositionalWrapper(str, Enum):
    """The complete, predeclared confirmatory wrapper set."""

    ADD_CONST_1 = "ADD_CONST_1"
    MUL_CONST_NEGATIVE_ONE = "MUL_CONST_NEGATIVE_ONE"


_WRAPPER_IMPLEMENTATIONS = {
    CompositionalWrapper.ADD_CONST_1: {
        "implementation": "integer_output_plus_constant-v1",
        "constant": 1,
    },
    CompositionalWrapper.MUL_CONST_NEGATIVE_ONE: {
        "implementation": "integer_output_times_constant-v1",
        "constant": -1,
    },
}


def _require_hash(value: str, reason: str) -> None:
    if not isinstance(value, str) or not is_artifact_hash(value):
        raise ValueError(reason)


def wrapper_implementation_hash(wrapper: CompositionalWrapper) -> str:
    """Canonical identity of the tiny, evaluator-owned wrapper implementation."""

    wrapper = CompositionalWrapper(wrapper)
    return canonical_sha256(
        {"wrapper": wrapper.value, **_WRAPPER_IMPLEMENTATIONS[wrapper]}
    )


def _apply_wrapper(wrapper: CompositionalWrapper, value: int) -> int:
    wrapper = CompositionalWrapper(wrapper)
    if wrapper is CompositionalWrapper.ADD_CONST_1:
        return value + 1
    if wrapper is CompositionalWrapper.MUL_CONST_NEGATIVE_ONE:
        return value * -1
    raise ValueError("genesis_compositional_wrapper_invalid")


def compositional_transfer_protocol_commitment() -> str:
    """Pre-policy commitment, deliberately independent of a later campaign."""

    return canonical_sha256(
        {
            "schema_version": "genesis-m7-compositional-transfer-protocol-v1",
            "wrappers": tuple(
                {
                    "wrapper": wrapper.value,
                    "implementation_hash": wrapper_implementation_hash(wrapper),
                }
                for wrapper in CompositionalWrapper
            ),
            "same_promoted_z_as_subcomponent": True,
            "evaluation_split": DatasetSplit.TRANSFER.value,
            "m6_measurement_mode": "COMPOSITIONAL",
        }
    )


@dataclass(frozen=True, slots=True)
class CompositionalTransferProtocol:
    """Frozen execution protocol bound to the GE-I policy before any run."""

    schema_version: str
    protocol_id: str
    policy_hash: str
    evaluation_policy_hash: str
    protocol_commitment_hash: str
    wrappers: tuple[CompositionalWrapper, ...]
    protocol_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.schema_version or not self.protocol_id:
            raise ValueError("genesis_compositional_protocol_identity_invalid")
        for value in (
            self.policy_hash,
            self.evaluation_policy_hash,
            self.protocol_commitment_hash,
        ):
            _require_hash(value, "genesis_compositional_protocol_hash_invalid")
        wrappers = tuple(CompositionalWrapper(item) for item in self.wrappers)
        if wrappers != tuple(CompositionalWrapper):
            raise ValueError("genesis_compositional_protocol_wrappers_invalid")
        if self.protocol_commitment_hash != compositional_transfer_protocol_commitment():
            raise ValueError("genesis_compositional_protocol_commitment_invalid")
        object.__setattr__(self, "wrappers", wrappers)
        object.__setattr__(self, "protocol_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "protocol_id": self.protocol_id,
            "policy_hash": self.policy_hash,
            "evaluation_policy_hash": self.evaluation_policy_hash,
            "protocol_commitment_hash": self.protocol_commitment_hash,
            "wrappers": tuple(item.value for item in self.wrappers),
        }

    def validate(self) -> bool:
        try:
            return CompositionalTransferProtocol(**self.canonical_payload()).protocol_hash == self.protocol_hash
        except (TypeError, ValueError):
            return False

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "CompositionalTransferProtocol":
        return cls(**dict(payload))


def confirmatory_compositional_transfer_protocol(
    *, policy: GEIAcceptancePolicy, evaluation_policy_hash: str,
) -> CompositionalTransferProtocol:
    """Create the only supported M7-G3 protocol from a frozen policy."""

    if (
        not policy.validate()
        or policy.compositional_transfer_protocol_hash
        != compositional_transfer_protocol_commitment()
    ):
        raise ValueError("genesis_compositional_policy_binding_invalid")
    return CompositionalTransferProtocol(
        "genesis-m7-compositional-transfer-protocol-v1",
        "GEI_COMPOSITIONAL_TRANSFER_V1",
        policy.policy_hash,
        evaluation_policy_hash,
        compositional_transfer_protocol_commitment(),
        tuple(CompositionalWrapper),
    )


@dataclass(frozen=True, slots=True)
class CompositionalTransferBinding:
    """Bind one wrapper execution to its exact policy, z, and transfer split."""

    schema_version: str
    policy_hash: str
    protocol_hash: str
    campaign_hash: str
    task_benchmark_binding_hash: str
    promoted_skill_hash: str
    wrapper: CompositionalWrapper
    wrapper_implementation_hash: str
    transfer_input_commitment_hash: str
    evaluation_policy_hash: str
    binding_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for value in (
            self.policy_hash,
            self.protocol_hash,
            self.campaign_hash,
            self.task_benchmark_binding_hash,
            self.promoted_skill_hash,
            self.wrapper_implementation_hash,
            self.transfer_input_commitment_hash,
            self.evaluation_policy_hash,
        ):
            _require_hash(value, "genesis_compositional_binding_hash_invalid")
        wrapper = CompositionalWrapper(self.wrapper)
        if self.wrapper_implementation_hash != wrapper_implementation_hash(wrapper):
            raise ValueError("genesis_compositional_binding_implementation_invalid")
        object.__setattr__(self, "wrapper", wrapper)
        object.__setattr__(self, "binding_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, str]:
        return {
            "schema_version": self.schema_version,
            "policy_hash": self.policy_hash,
            "protocol_hash": self.protocol_hash,
            "campaign_hash": self.campaign_hash,
            "task_benchmark_binding_hash": self.task_benchmark_binding_hash,
            "promoted_skill_hash": self.promoted_skill_hash,
            "wrapper": self.wrapper.value,
            "wrapper_implementation_hash": self.wrapper_implementation_hash,
            "transfer_input_commitment_hash": self.transfer_input_commitment_hash,
            "evaluation_policy_hash": self.evaluation_policy_hash,
        }

    def validate(self) -> bool:
        try:
            return CompositionalTransferBinding(**self.canonical_payload()).binding_hash == self.binding_hash
        except (TypeError, ValueError):
            return False

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "CompositionalTransferBinding":
        return cls(**dict(payload))


@dataclass(frozen=True, slots=True)
class CompositionalTransferEvidence:
    """The two M6-certified wrapper executions for one promoted z."""

    policy: GEIAcceptancePolicy
    protocol: CompositionalTransferProtocol
    bindings: tuple[CompositionalTransferBinding, ...]
    measurements: tuple[M7FederatedEvidence, ...]

    def validate(self) -> bool:
        if (
            not self.policy.validate()
            or not self.protocol.validate()
            or self.protocol.policy_hash != self.policy.policy_hash
            or len(self.bindings) != len(CompositionalWrapper)
            or len(self.measurements) != len(CompositionalWrapper)
        ):
            return False
        for binding, measurement, wrapper in zip(
            self.bindings, self.measurements, CompositionalWrapper
        ):
            if (
                not binding.validate()
                or binding.wrapper is not wrapper
                or binding.protocol_hash != self.protocol.protocol_hash
                or measurement.scope.measurement_mode != "COMPOSITIONAL"
                or measurement.scope.measurement_binding_hash != binding.binding_hash
                or measurement.scope.candidate_skill_hash != binding.binding_hash
                or measurement.adjudication.verdict.value != "PASS"
            ):
                return False
        return True

    def persist_traces(
        self, store: ContentAddressedArtifactStore
    ) -> tuple[PersistedTrace, ...]:
        if not self.validate():
            raise ValueError("genesis_compositional_evidence_invalid")
        return tuple(item.persist_trace(store) for item in self.measurements)


def _validate_confirmatory_inputs(
    *,
    policy: GEIAcceptancePolicy,
    protocol: CompositionalTransferProtocol,
    campaign: AcquisitionCampaignManifest,
    benchmark: SealedCapabilityBenchmark,
) -> None:
    if (
        not policy.validate()
        or not protocol.validate()
        or protocol.policy_hash != policy.policy_hash
        or protocol.protocol_commitment_hash != policy.compositional_transfer_protocol_hash
        or campaign.evidence_classification != "CONFIRMATORY_GE_I_EVIDENCE"
        or campaign.gei_acceptance_policy_hash != policy.policy_hash
        or benchmark.manifest.manifest_hash != policy.canonical_battery_manifest_hash
    ):
        raise ValueError("genesis_compositional_confirmatory_binding_invalid")


def materialize_compositional_transfer_evidence(
    *,
    policy: GEIAcceptancePolicy,
    protocol: CompositionalTransferProtocol,
    campaign: AcquisitionCampaignManifest,
    baseline: CapabilityManifest,
    benchmark: SealedCapabilityBenchmark,
    task_id: str,
    result: AcquisitionResult,
) -> CompositionalTransferEvidence:
    """Certify both declared ``wrapper(z)`` executions over TRANSFER via M6."""

    _validate_confirmatory_inputs(
        policy=policy, protocol=protocol, campaign=campaign, benchmark=benchmark,
    )
    task_binding, candidate = _validate_acquisition_chain(
        campaign=campaign,
        baseline=baseline,
        benchmark=benchmark,
        task_id=task_id,
        result=result,
    )
    transfer_commitment = task_binding.split_commitment_hashes[DatasetSplit.TRANSFER.value]
    bindings: list[CompositionalTransferBinding] = []
    measurements: list[M7FederatedEvidence] = []
    for wrapper in protocol.wrappers:
        binding = CompositionalTransferBinding(
            "genesis-m7-compositional-transfer-binding-v1",
            policy.policy_hash,
            protocol.protocol_hash,
            campaign.campaign_hash,
            task_binding.binding_hash,
            candidate.skill_hash,
            wrapper,
            wrapper_implementation_hash(wrapper),
            transfer_commitment,
            protocol.evaluation_policy_hash,
        )
        historical_artifacts = {
            "m7_acquisition_campaign": (campaign,),
            "m7_baseline_capability_manifest": (baseline,),
            "m7_benchmark_manifest": (benchmark.manifest,),
            "m7_sealed_benchmark_replay_witness": (_benchmark_replay_witness(benchmark),),
            "m7_dsl_specification": (benchmark.specification,),
            "m7_task_benchmark_binding": (task_binding,),
            "m7_prior_insufficiency_receipt": (result.prior,),
            "m7_synthesis_receipt": (result.synthesis.receipt,),
            "m7_program_skill": (candidate,),
            "m7_candidate_commitment": (result.commitment,),
            "m7_audit_evaluation": (result.audit,),
            "m7_promotion_receipt": (result.promotion,),
            "m7_successor_capability_manifest": (result.g1_manifest,),
            "m7_gei_acceptance_policy": (policy,),
            "m7_compositional_transfer_protocol": (protocol,),
            "m7_compositional_transfer_binding": (binding,),
        }
        if result.durable_audit is not None:
            historical_artifacts["m7_durable_audit_claim"] = (result.durable_audit.claim,)
            historical_artifacts["m7_durable_audit_evaluation"] = (result.durable_audit.evaluation,)
        measurements.append(
            _materialize_federated_execution_evidence(
                campaign=campaign,
                baseline=baseline,
                benchmark=benchmark,
                task_id=task_id,
                split=DatasetSplit.TRANSFER,
                task_binding=task_binding,
                candidate_identity_hash=binding.binding_hash,
                candidate_callable=lambda value, current=wrapper: _apply_wrapper(
                    current,
                    evaluate_expression(candidate.program_ast, value, benchmark.specification),
                ),
                snapshot_hash=canonical_sha256(
                    {
                        "m7_compositional_protocol": protocol.protocol_hash,
                        "m7_compositional_binding": binding.binding_hash,
                    }
                ),
                historical_artifacts=historical_artifacts,
                reference_transform=lambda value, current=wrapper: _apply_wrapper(current, value),
                measurement_mode="COMPOSITIONAL",
                measurement_binding_hash=binding.binding_hash,
            )
        )
        bindings.append(binding)
    evidence = CompositionalTransferEvidence(policy, protocol, tuple(bindings), tuple(measurements))
    if not evidence.validate():
        raise ValueError("genesis_compositional_materialization_invalid")
    return evidence


@dataclass(frozen=True, slots=True)
class M7CompositionalReplay:
    admitted: bool
    reasons: tuple[str, ...]
    trace_closure_hash: str


def replay_compositional_transfer_evidence(
    store: ContentAddressedArtifactStore,
    trace_closure_hash: str,
) -> M7CompositionalReplay:
    """Replay an individual compositional closure from fresh CAS objects."""

    m6 = replay_m6_trace(store, trace_closure_hash)
    if not m6.admitted:
        return M7CompositionalReplay(
            False, tuple(f"m6:{item}" for item in m6.reasons), trace_closure_hash
        )
    try:
        closure = TraceClosureManifest.from_payload(store.get(trace_closure_hash))
        policy = GEIAcceptancePolicy.from_payload(
            _one_payload(store, closure, "m7_gei_acceptance_policy")
        )
        protocol = CompositionalTransferProtocol.from_payload(
            _one_payload(store, closure, "m7_compositional_transfer_protocol")
        )
        binding = CompositionalTransferBinding.from_payload(
            _one_payload(store, closure, "m7_compositional_transfer_binding")
        )
        campaign, baseline, benchmark, task_id, result, scope, _target, task_binding = _restore_material(
            store, closure
        )
        rebuilt = materialize_compositional_transfer_evidence(
            policy=policy,
            protocol=protocol,
            campaign=campaign,
            baseline=baseline,
            benchmark=benchmark,
            task_id=task_id,
            result=result,
        )
        measurement = next(
            item for item in rebuilt.measurements
            if item.scope.measurement_binding_hash == binding.binding_hash
        )
        if (
            binding.task_benchmark_binding_hash != task_binding.binding_hash
            or scope.scope_hash != measurement.scope.scope_hash
            or scope.measurement_mode != "COMPOSITIONAL"
            or m6.adjudication is None
            or m6.adjudication.receipt_hash != measurement.adjudication.receipt_hash
        ):
            return M7CompositionalReplay(
                False, ("genesis_compositional_replay_derivation_mismatch",), trace_closure_hash
            )
    except (KeyError, StopIteration, TypeError, ValueError):
        return M7CompositionalReplay(
            False, ("genesis_compositional_replay_historical_material_invalid",), trace_closure_hash
        )
    return M7CompositionalReplay(True, (), trace_closure_hash)
