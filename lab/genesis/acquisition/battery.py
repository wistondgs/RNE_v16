"""Predeclared M7-G4 campaign battery and rederivable GE-I closure contracts.

This is deliberately an orchestration and attestation layer.  It does not
change M5 causality or M6 verification: every observation used below is made
by the already-existing acquisition, M5, M6, audit, composition, and replay
components.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from lab.genesis.acquisition.audit import DurableAuditClaimRegistry, DurableAuditResult
from lab.genesis.acquisition.benchmark import (
    DatasetSplit,
    SealedCapabilityBenchmark,
    TaskBenchmarkBinding,
)
from lab.genesis.acquisition.campaign import AcquisitionResult, AutonomousAcquisitionCampaign
from lab.genesis.acquisition.causal_experiments import (
    CausalAttributionStatus,
    CausalCapabilityAttribution,
    PlaceboCommitment,
    materialize_causal_capability_attribution,
)
from lab.genesis.acquisition.causal_replay import (
    PersistedCausalEvidence,
    persist_causal_capability_attribution,
    replay_causal_capability_attribution,
)
from lab.genesis.acquisition.composition import (
    CompositionalTransferEvidence,
    CompositionalTransferProtocol,
    materialize_compositional_transfer_evidence,
    replay_compositional_transfer_evidence,
)
from lab.genesis.acquisition.confirmation import (
    CANONICAL_CONFIRMATORY_TASK_IDS,
    CampaignGate,
    GEIAcceptancePolicy,
)
from lab.genesis.acquisition.contracts import (
    AcquisitionCampaignManifest,
    CANDIDATE_RANKING_RULE,
    CapabilityManifest,
    HUMAN_INTERVENTION_POLICY,
    PROMOTION_RULE,
    ProgramSkillArtifact,
)
from lab.genesis.acquisition.dsl import DSLSpecification, expression_metrics
from lab.genesis.acquisition.federated_evidence import (
    M7FederatedEvidence,
    materialize_promoted_skill_evidence,
)
from lab.genesis.acquisition.replay import replay_m7_federated_evidence
from lab.genesis.contracts.serialization import canonical_sha256, freeze
from lab.genesis.evidence.artifacts import ContentAddressedArtifactStore, is_artifact_hash
from lab.genesis.evidence.trace_persistence import PersistedTrace
from lab.genesis.evidence.trace_persistence import replay_m6_trace
from lab.genesis.verifiers.federation import FederationVerdict


_SPLITS = tuple(item.value for item in DatasetSplit)
_CAUSAL_PROTOCOL_HASH = canonical_sha256(
    {"protocol": "genesis-m7-e2-c1-c2-c3-v1", "cfi": "m5-owned"}
)
_M6_POLICY_HASH = canonical_sha256(
    {"policy": "genesis-m6-finite-differential-supporting-v1"}
)
_TAMPER_MATRIX_HASH = canonical_sha256(
    {
        "matrix": "genesis-m7-g4-attestation-tamper-v1",
        "cases": (
            "missing_gate", "skill_substitution", "campaign_substitution",
            "task_substitution", "composition_absent", "cfi_incomplete",
            "replay_false", "pilot_substitution", "unsupported_status",
        ),
    }
)


def _require_hash(value: str, reason: str) -> None:
    if not isinstance(value, str) or not is_artifact_hash(value):
        raise ValueError(reason)


def _canonical_task_ids(values: tuple[str, ...]) -> tuple[str, ...]:
    ordered = tuple(sorted(str(item) for item in values))
    if ordered != CANONICAL_CONFIRMATORY_TASK_IDS:
        raise ValueError("genesis_gei_battery_task_set_invalid")
    return ordered


@dataclass(frozen=True, slots=True)
class ConfirmatoryTaskPlan:
    """Pre-campaign slot; deliberately does not contain a later campaign hash.

    A campaign needs the final battery-manifest hash and a task binding needs
    the final campaign hash.  This plan commits all other task inputs first,
    breaking that otherwise artificial hash cycle without permitting a target
    or budget to move after results are known.
    """

    task_id: str
    campaign_id: str
    g0_snapshot_hash: str
    baseline: CapabilityManifest
    split_commitment_hashes: Mapping[str, str]
    split_seed_commitment_hashes: Mapping[str, str]
    search_budget: Mapping[str, int]
    plan_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.task_id or not self.campaign_id or not self.baseline.validate():
            raise ValueError("genesis_gei_task_plan_identity_invalid")
        _require_hash(self.g0_snapshot_hash, "genesis_gei_task_plan_snapshot_invalid")
        splits = freeze({str(key): str(value) for key, value in self.split_commitment_hashes.items()})
        seeds = freeze({str(key): str(value) for key, value in self.split_seed_commitment_hashes.items()})
        if (
            set(splits) != set(_SPLITS)
            or set(seeds) != set(_SPLITS)
            or any(not is_artifact_hash(item) for item in (*splits.values(), *seeds.values()))
            or not isinstance(self.search_budget, Mapping)
            or set(self.search_budget) != {"max_candidates"}
            or not isinstance(self.search_budget["max_candidates"], int)
            or self.search_budget["max_candidates"] <= 0
        ):
            raise ValueError("genesis_gei_task_plan_inputs_invalid")
        object.__setattr__(self, "split_commitment_hashes", splits)
        object.__setattr__(self, "split_seed_commitment_hashes", seeds)
        object.__setattr__(self, "search_budget", freeze(self.search_budget))
        object.__setattr__(self, "plan_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "campaign_id": self.campaign_id,
            "g0_snapshot_hash": self.g0_snapshot_hash,
            "baseline": self.baseline.canonical_payload(),
            "split_commitment_hashes": self.split_commitment_hashes,
            "split_seed_commitment_hashes": self.split_seed_commitment_hashes,
            "search_budget": self.search_budget,
        }

    def validate(self) -> bool:
        try:
            return ConfirmatoryTaskPlan(
                self.task_id, self.campaign_id, self.g0_snapshot_hash, self.baseline,
                self.split_commitment_hashes, self.split_seed_commitment_hashes,
                self.search_budget,
            ).plan_hash == self.plan_hash
        except (TypeError, ValueError):
            return False

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "ConfirmatoryTaskPlan":
        values = dict(payload)
        values["baseline"] = CapabilityManifest.from_payload(values["baseline"])
        return cls(**values)


@dataclass(frozen=True, slots=True)
class GEIConfirmatoryBatteryManifest:
    """The entire experimental universe frozen before confirmatory execution."""

    schema_version: str
    acceptance_policy_hash: str
    canonical_battery_manifest_hash: str
    task_plans: tuple[ConfirmatoryTaskPlan, ...]
    dsl_version: str
    dsl_hash: str
    synthesizer_implementation_hash: str
    audit_policy_hash: str
    compositional_protocol_hash: str
    causal_protocol_hash: str
    m6_verification_policy_hash: str
    code_snapshot_hash: str
    environment_commitment_hash: str
    tamper_matrix_hash: str
    battery_manifest_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.schema_version or not self.dsl_version:
            raise ValueError("genesis_gei_battery_identity_invalid")
        for value in (
            self.acceptance_policy_hash, self.canonical_battery_manifest_hash,
            self.dsl_hash, self.synthesizer_implementation_hash, self.audit_policy_hash,
            self.compositional_protocol_hash, self.causal_protocol_hash,
            self.m6_verification_policy_hash, self.code_snapshot_hash,
            self.environment_commitment_hash, self.tamper_matrix_hash,
        ):
            _require_hash(value, "genesis_gei_battery_hash_invalid")
        plans = tuple(sorted(self.task_plans, key=lambda item: item.task_id))
        if (
            _canonical_task_ids(tuple(item.task_id for item in plans))
            != tuple(item.task_id for item in plans)
            or not all(item.validate() for item in plans)
            or len({item.campaign_id for item in plans}) != len(plans)
            or len({item.baseline.manifest_hash for item in plans}) != len(plans)
            or self.tamper_matrix_hash != _TAMPER_MATRIX_HASH
        ):
            raise ValueError("genesis_gei_battery_plans_invalid")
        object.__setattr__(self, "task_plans", plans)
        object.__setattr__(self, "battery_manifest_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "acceptance_policy_hash": self.acceptance_policy_hash,
            "canonical_battery_manifest_hash": self.canonical_battery_manifest_hash,
            "task_plans": tuple(item.canonical_payload() for item in self.task_plans),
            "dsl_version": self.dsl_version,
            "dsl_hash": self.dsl_hash,
            "synthesizer_implementation_hash": self.synthesizer_implementation_hash,
            "audit_policy_hash": self.audit_policy_hash,
            "compositional_protocol_hash": self.compositional_protocol_hash,
            "causal_protocol_hash": self.causal_protocol_hash,
            "m6_verification_policy_hash": self.m6_verification_policy_hash,
            "code_snapshot_hash": self.code_snapshot_hash,
            "environment_commitment_hash": self.environment_commitment_hash,
            "tamper_matrix_hash": self.tamper_matrix_hash,
        }

    def validate(self) -> bool:
        try:
            return GEIConfirmatoryBatteryManifest.from_payload(
                self.canonical_payload()
            ).battery_manifest_hash == self.battery_manifest_hash
        except (TypeError, ValueError):
            return False

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "GEIConfirmatoryBatteryManifest":
        values = dict(payload)
        values["task_plans"] = tuple(
            ConfirmatoryTaskPlan.from_payload(item) for item in values["task_plans"]
        )
        return cls(**values)

    def plan_for(self, task_id: str) -> ConfirmatoryTaskPlan:
        plan = next((item for item in self.task_plans if item.task_id == task_id), None)
        if plan is None:
            raise ValueError("genesis_gei_battery_task_plan_missing")
        return plan


def predeclare_confirmatory_battery(
    *,
    policy: GEIAcceptancePolicy,
    protocol: CompositionalTransferProtocol,
    benchmark: SealedCapabilityBenchmark,
    code_snapshot_hash: str,
    environment_commitment_hash: str,
) -> GEIConfirmatoryBatteryManifest:
    """Create the only six-slot manifest before the first campaign runs."""

    if (
        not policy.validate()
        or not protocol.validate()
        or protocol.policy_hash != policy.policy_hash
        or protocol.protocol_commitment_hash != policy.compositional_transfer_protocol_hash
        or benchmark.manifest.manifest_hash != policy.canonical_battery_manifest_hash
    ):
        raise ValueError("genesis_gei_battery_predeclaration_invalid")
    _require_hash(code_snapshot_hash, "genesis_gei_battery_code_snapshot_invalid")
    _require_hash(environment_commitment_hash, "genesis_gei_battery_environment_invalid")
    descriptors = {item.task_id: item for item in benchmark.manifest.tasks}
    plans: list[ConfirmatoryTaskPlan] = []
    for task_id in CANONICAL_CONFIRMATORY_TASK_IDS:
        descriptor = descriptors.get(task_id)
        if descriptor is None:
            raise ValueError("genesis_gei_battery_task_missing")
        baseline = CapabilityManifest(
            f"m7g4-confirmatory-{task_id}-g0", "genesis-m7-confirmatory-g0-v1", ()
        )
        plans.append(
            ConfirmatoryTaskPlan(
                task_id,
                f"m7g4-confirmatory-{task_id}",
                canonical_sha256({"g0": baseline.manifest_hash, "task_id": task_id}),
                baseline,
                descriptor.split_commitments,
                {
                    split: canonical_sha256(
                        {"m7g4_seed": task_id, "split": split, "policy": policy.policy_hash}
                    )
                    for split in _SPLITS
                },
                {"max_candidates": 256},
            )
        )
    return GEIConfirmatoryBatteryManifest(
        "genesis-m7-gei-confirmatory-battery-v1",
        policy.policy_hash,
        benchmark.manifest.manifest_hash,
        tuple(plans),
        benchmark.specification.dsl_version,
        benchmark.specification.dsl_hash,
        canonical_sha256({"synthesizer": "genesis-m7-deterministic-enumerative-synthesizer-v1"}),
        policy.audit_policy_hash,
        protocol.protocol_hash,
        _CAUSAL_PROTOCOL_HASH,
        _M6_POLICY_HASH,
        code_snapshot_hash,
        environment_commitment_hash,
        _TAMPER_MATRIX_HASH,
    )


def build_confirmatory_campaign(
    *,
    policy: GEIAcceptancePolicy,
    battery: GEIConfirmatoryBatteryManifest,
    benchmark: SealedCapabilityBenchmark,
    task_id: str,
) -> tuple[AcquisitionCampaignManifest, CapabilityManifest, TaskBenchmarkBinding]:
    """Materialize one predeclared campaign identity; no outcome is consulted."""

    if (
        not policy.validate()
        or not battery.validate()
        or battery.acceptance_policy_hash != policy.policy_hash
        or battery.canonical_battery_manifest_hash != benchmark.manifest.manifest_hash
        or battery.dsl_hash != benchmark.specification.dsl_hash
    ):
        raise ValueError("genesis_gei_campaign_build_binding_invalid")
    plan = battery.plan_for(task_id)
    campaign = AcquisitionCampaignManifest(
        plan.campaign_id,
        "genesis-m7-confirmatory-campaign-v1",
        plan.g0_snapshot_hash,
        plan.baseline.manifest_hash,
        benchmark.specification.dsl_hash,
        battery.synthesizer_implementation_hash,
        plan.split_commitment_hashes,
        benchmark.manifest.generator_implementation_hash,
        plan.split_seed_commitment_hashes,
        plan.search_budget,
        benchmark.specification.max_ast_depth,
        benchmark.specification.max_ast_nodes,
        benchmark.specification.allowed_constants,
        tuple(item.value for item in benchmark.specification.operators),
        CANDIDATE_RANKING_RULE,
        PROMOTION_RULE,
        canonical_sha256({"cfi": _CAUSAL_PROTOCOL_HASH, "task": task_id}),
        canonical_sha256({"resource": plan.search_budget, "task": task_id}),
        30,
        HUMAN_INTERVENTION_POLICY,
        (_M6_POLICY_HASH,),
        policy.policy_hash,
        battery.battery_manifest_hash,
        "CONFIRMATORY_GE_I_EVIDENCE",
    )
    binding = TaskBenchmarkBinding(
        "genesis-m7-confirmatory-task-binding-v1",
        campaign.campaign_hash,
        benchmark.manifest.manifest_hash,
        task_id,
        plan.split_commitment_hashes,
    )
    return campaign, plan.baseline, binding


class GateStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_PROVEN = "NOT_PROVEN"


class GEICampaignStatus(str, Enum):
    SUPPORTED = "GE_I_CAMPAIGN_SUPPORTED"
    FAIL = "GE_I_CAMPAIGN_FAIL"
    NOT_PROVEN = "GE_I_CAMPAIGN_NOT_PROVEN"


def _aggregate_campaign(gates: Mapping[str, GateStatus]) -> GEICampaignStatus:
    if all(item is GateStatus.PASS for item in gates.values()):
        return GEICampaignStatus.SUPPORTED
    if any(item is GateStatus.FAIL for item in gates.values()):
        return GEICampaignStatus.FAIL
    return GEICampaignStatus.NOT_PROVEN


@dataclass(frozen=True, slots=True)
class GEICampaignAssessment:
    """A status derived from the complete named gate vector, never a boolean."""

    attestation_hash: str
    policy_hash: str
    battery_manifest_hash: str
    task_id: str
    campaign_hash: str
    gates: Mapping[str, GateStatus]
    status: GEICampaignStatus
    assessment_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for value in (self.attestation_hash, self.policy_hash, self.battery_manifest_hash, self.campaign_hash):
            _require_hash(value, "genesis_gei_campaign_assessment_hash_invalid")
        values = {str(key): GateStatus(value) for key, value in self.gates.items()}
        required = tuple(sorted(item.value for item in CampaignGate))
        if tuple(sorted(values)) != required or not self.task_id:
            raise ValueError("genesis_gei_campaign_assessment_gates_invalid")
        object.__setattr__(self, "gates", freeze(values))
        object.__setattr__(self, "status", GEICampaignStatus(self.status))
        if self.status is not _aggregate_campaign(values):
            raise ValueError("genesis_gei_campaign_assessment_status_not_derived")
        object.__setattr__(self, "assessment_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "attestation_hash": self.attestation_hash,
            "policy_hash": self.policy_hash,
            "battery_manifest_hash": self.battery_manifest_hash,
            "task_id": self.task_id,
            "campaign_hash": self.campaign_hash,
            "gates": {key: value.value for key, value in self.gates.items()},
            "status": self.status.value,
        }

    def validate(self) -> bool:
        try:
            return GEICampaignAssessment(**self.canonical_payload()).assessment_hash == self.assessment_hash
        except (TypeError, ValueError):
            return False


@dataclass(frozen=True, slots=True)
class GEICampaignAttestation:
    """All source evidence required to rederive one GE-I campaign assessment."""

    policy: GEIAcceptancePolicy
    battery: GEIConfirmatoryBatteryManifest
    campaign: AcquisitionCampaignManifest
    baseline: CapabilityManifest
    task_binding: TaskBenchmarkBinding
    result: AcquisitionResult
    durable_audit: DurableAuditResult | None
    hidden: M7FederatedEvidence | None
    transfer: M7FederatedEvidence | None
    composition: CompositionalTransferEvidence | None
    causal: CausalCapabilityAttribution | None
    hidden_trace: PersistedTrace | None
    transfer_trace: PersistedTrace | None
    composition_traces: tuple[PersistedTrace, ...]
    causal_persistence: PersistedCausalEvidence | None
    attestation_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "composition_traces", tuple(self.composition_traces))
        if (
            not self.policy.validate()
            or not self.battery.validate()
            or not self.campaign.validate()
            or not self.baseline.validate()
            or not self.task_binding.validate()
            or self.campaign.evidence_classification != "CONFIRMATORY_GE_I_EVIDENCE"
            or self.campaign.gei_acceptance_policy_hash != self.policy.policy_hash
            or self.campaign.confirmatory_battery_manifest_hash != self.battery.battery_manifest_hash
            or self.battery.acceptance_policy_hash != self.policy.policy_hash
            or self.task_binding.campaign_hash != self.campaign.campaign_hash
            or self.baseline.manifest_hash != self.campaign.g0_capability_manifest_hash
            or self.task_binding.task_id not in CANONICAL_CONFIRMATORY_TASK_IDS
        ):
            raise ValueError("genesis_gei_campaign_attestation_binding_invalid")
        populated = (
            self.durable_audit, self.hidden, self.transfer, self.composition,
            self.causal, self.hidden_trace, self.transfer_trace, self.causal_persistence,
        )
        if any(item is not None for item in populated) and (
            any(item is None for item in populated)
            or len(self.composition_traces) != 2
            or not self.durable_audit.validate()
        ):
            raise ValueError("genesis_gei_campaign_attestation_evidence_incomplete")
        if not any(item is not None for item in populated) and self.composition_traces:
            raise ValueError("genesis_gei_campaign_attestation_partial_traces_invalid")
        object.__setattr__(self, "attestation_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        skill = self.result.synthesis.selected_skill
        return {
            "policy_hash": self.policy.policy_hash,
            "battery_manifest_hash": self.battery.battery_manifest_hash,
            "campaign_hash": self.campaign.campaign_hash,
            "baseline_manifest_hash": self.baseline.manifest_hash,
            "task_binding_hash": self.task_binding.binding_hash,
            "task_id": self.task_binding.task_id,
            "promoted_skill_hash": None if skill is None else skill.skill_hash,
            "prior_hash": self.result.prior.receipt_hash,
            "synthesis_hash": self.result.synthesis.receipt.synthesis_hash,
            "candidate_commitment_hash": None if self.result.commitment is None else self.result.commitment.commitment_hash,
            "audit_claim_hash": None if self.durable_audit is None else self.durable_audit.claim.claim_hash,
            "audit_evaluation_hash": None if self.durable_audit is None else self.durable_audit.evaluation.receipt_hash,
            "promotion_hash": self.result.promotion.promotion_hash,
            "hidden_trace_closure_hash": None if self.hidden_trace is None else self.hidden_trace.closure_hash,
            "transfer_trace_closure_hash": None if self.transfer_trace is None else self.transfer_trace.closure_hash,
            "composition_trace_closure_hashes": tuple(item.closure_hash for item in self.composition_traces),
            "causal_evidence_manifest_hash": None if self.causal_persistence is None else self.causal_persistence.manifest_hash,
            "tamper_matrix_hash": _TAMPER_MATRIX_HASH,
        }

    def validate(self) -> bool:
        return (
            self.policy.validate()
            and self.battery.validate()
            and self.campaign.validate()
            and self.baseline.validate()
            and self.task_binding.validate()
            and (self.durable_audit is None or self.durable_audit.validate())
            and self.attestation_hash == canonical_sha256(self.canonical_payload())
        )

    def _base_gates(self) -> dict[str, GateStatus]:
        gates = {item.value: GateStatus.NOT_PROVEN for item in CampaignGate}
        candidate = self.result.synthesis.selected_skill
        binding = self.result.task_benchmark_binding
        direct_common = (
            candidate is not None
            and binding is not None
            and binding.binding_hash == self.task_binding.binding_hash
            and self.result.commitment is not None
            and self.result.audit is not None
            and self.result.g1_manifest is not None
            and self.result.promotion.status.value == "PROMOTED"
        )
        gates[CampaignGate.PRIOR_STRUCTURAL_ABSENCE.value] = (
            GateStatus.PASS if not self.baseline.skill_hashes else GateStatus.FAIL
        )
        gates[CampaignGate.PRIOR_BEHAVIORAL_INSUFFICIENCY.value] = (
            GateStatus.PASS if self.result.prior.verdict == "PASS" and self.result.prior.correct == 0 else GateStatus.FAIL
        )
        gates[CampaignGate.CAMPAIGN_FROZEN.value] = GateStatus.PASS if self.campaign.validate() else GateStatus.NOT_PROVEN
        gates[CampaignGate.TRAIN_ONLY_LEARNER_VIEW.value] = GateStatus.PASS if direct_common else GateStatus.NOT_PROVEN
        gates[CampaignGate.DETERMINISTIC_SYNTHESIS.value] = GateStatus.PASS if direct_common else GateStatus.NOT_PROVEN
        gates[CampaignGate.DETERMINISTIC_SELECTION.value] = GateStatus.PASS if direct_common else GateStatus.NOT_PROVEN
        gates[CampaignGate.SEARCH_BUDGET_RESPECTED.value] = GateStatus.PASS if direct_common else GateStatus.NOT_PROVEN
        gates[CampaignGate.CANDIDATE_COMMITMENT.value] = GateStatus.PASS if direct_common else GateStatus.NOT_PROVEN
        audit_ok = (
            direct_common
            and self.durable_audit is not None
            and self.durable_audit.audit.result_hash == self.result.audit.result_hash
            and self.durable_audit.claim.slot.policy_hash == self.policy.policy_hash
            and self.durable_audit.claim.slot.campaign_hash == self.campaign.campaign_hash
            and self.durable_audit.claim.slot.task_benchmark_binding_hash == self.task_binding.binding_hash
            and self.durable_audit.evaluation.candidate_commitment_hash == self.result.commitment.commitment_hash
        )
        gates[CampaignGate.AUDIT_ONE_SHOT.value] = GateStatus.PASS if audit_ok else GateStatus.NOT_PROVEN
        gates[CampaignGate.AUDIT_PASS.value] = (
            GateStatus.NOT_PROVEN if self.result.audit is None
            else GateStatus.PASS if audit_ok and self.result.audit.exact_pass else GateStatus.FAIL
        )
        gates[CampaignGate.PROMOTION_PASS.value] = (
            GateStatus.NOT_PROVEN if self.result.commitment is None
            else GateStatus.PASS if direct_common else GateStatus.FAIL
        )
        gates[CampaignGate.G1_DELTA_EXACTLY_Z.value] = GateStatus.PASS if direct_common else GateStatus.NOT_PROVEN
        hidden_ok = (
            self.hidden is not None and candidate is not None and self.hidden.scope.split is DatasetSplit.HIDDEN
            and self.hidden.scope.candidate_skill_hash == candidate.skill_hash
            and self.hidden.adjudication.verdict is FederationVerdict.PASS
        )
        transfer_ok = (
            self.transfer is not None and candidate is not None and self.transfer.scope.split is DatasetSplit.TRANSFER
            and self.transfer.scope.measurement_mode == "DIRECT"
            and self.transfer.scope.candidate_skill_hash == candidate.skill_hash
            and self.transfer.adjudication.verdict is FederationVerdict.PASS
        )
        gates[CampaignGate.HIDDEN_EXACTNESS.value] = GateStatus.PASS if hidden_ok else GateStatus.NOT_PROVEN
        gates[CampaignGate.OOD_TRANSFER.value] = GateStatus.PASS if transfer_ok else GateStatus.NOT_PROVEN
        gates[CampaignGate.COMPOSITIONAL_TRANSFER.value] = (
            GateStatus.NOT_PROVEN if self.composition is None
            else GateStatus.PASS if self.composition.validate() else GateStatus.FAIL
        )
        causal_valid = self.causal is not None and self.causal.validate() and self.causal.verdict is CausalAttributionStatus.PASS
        causal_gate = lambda outcome: (
            GateStatus.NOT_PROVEN if self.causal is None
            else GateStatus.PASS if causal_valid and outcome else GateStatus.FAIL
        )
        gates[CampaignGate.C1_TREATMENT_EFFECT.value] = causal_gate(False if self.causal is None else self.causal.treatment_effect)
        gates[CampaignGate.C1_PLACEBO_CONTROL.value] = causal_gate(False if self.causal is None else self.causal.placebo_control)
        gates[CampaignGate.C1_CFI.value] = GateStatus.NOT_PROVEN if self.causal is None else GateStatus.PASS if causal_valid else GateStatus.FAIL
        gates[CampaignGate.C2_ABLATION_NECESSITY.value] = causal_gate(False if self.causal is None else self.causal.necessity)
        gates[CampaignGate.C2_CFI.value] = GateStatus.NOT_PROVEN if self.causal is None else GateStatus.PASS if causal_valid else GateStatus.FAIL
        gates[CampaignGate.C3_TRANSPLANT_SUFFICIENCY.value] = causal_gate(False if self.causal is None else self.causal.sufficiency)
        gates[CampaignGate.C3_CFI.value] = GateStatus.NOT_PROVEN if self.causal is None else GateStatus.PASS if causal_valid else GateStatus.FAIL
        gates[CampaignGate.EXACT_SKILL_IDENTITY.value] = causal_gate(False if self.causal is None else self.causal.exact_skill_identity)
        gates[CampaignGate.TAMPER_MATRIX.value] = GateStatus.PASS if self.battery.tamper_matrix_hash == _TAMPER_MATRIX_HASH else GateStatus.NOT_PROVEN
        return gates

    def assess(self, store: ContentAddressedArtifactStore) -> GEICampaignAssessment:
        """Re-execute all fresh and temporal replay gates from persisted sources."""

        gates = self._base_gates()
        if (
            self.hidden_trace is None
            or self.transfer_trace is None
            or self.causal_persistence is None
        ):
            gates[CampaignGate.PERSISTENCE.value] = GateStatus.NOT_PROVEN
            gates[CampaignGate.FRESH_REPLAY.value] = GateStatus.NOT_PROVEN
            gates[CampaignGate.TEMPORAL_REPLAY.value] = GateStatus.NOT_PROVEN
            status = _aggregate_campaign(gates)
            return GEICampaignAssessment(
                self.attestation_hash, self.policy.policy_hash, self.battery.battery_manifest_hash,
                self.task_binding.task_id, self.campaign.campaign_hash, gates, status,
            )
        hidden_replay = replay_m7_federated_evidence(store, self.hidden_trace.closure_hash)
        transfer_replay = replay_m7_federated_evidence(store, self.transfer_trace.closure_hash)
        composition_replays = tuple(
            replay_compositional_transfer_evidence(store, item.closure_hash)
            for item in self.composition_traces
        )
        causal_replay = replay_causal_capability_attribution(
            store, self.causal_persistence.manifest_hash
        )
        replay_ok = (
            hidden_replay.admitted and transfer_replay.admitted
            and all(item.admitted for item in composition_replays)
            and causal_replay.admitted
        )
        gates[CampaignGate.PERSISTENCE.value] = GateStatus.PASS if replay_ok else GateStatus.NOT_PROVEN
        gates[CampaignGate.FRESH_REPLAY.value] = GateStatus.PASS if replay_ok else GateStatus.NOT_PROVEN
        # A later temporal read replays every immutable M6 closure again.  The
        # fresh semantic replay above already rematerializes the sealed M7/M5
        # sources; this second pass checks that all persisted records remain
        # independently replayable without multiplying acquisition execution.
        temporal_trace_hashes = (
            self.hidden_trace.closure_hash,
            self.transfer_trace.closure_hash,
            *(item.closure_hash for item in self.composition_traces),
            *self.causal_persistence.manifest.arm_trace_closures.values(),
        )
        temporal_ok = (
            all(replay_m6_trace(store, item).admitted for item in temporal_trace_hashes)
        )
        gates[CampaignGate.TEMPORAL_REPLAY.value] = GateStatus.PASS if temporal_ok else GateStatus.NOT_PROVEN
        status = _aggregate_campaign(gates)
        return GEICampaignAssessment(
            self.attestation_hash, self.policy.policy_hash, self.battery.battery_manifest_hash,
            self.task_binding.task_id, self.campaign.campaign_hash, gates, status,
        )


@dataclass(frozen=True, slots=True)
class ConfirmatoryCampaignRun:
    attestation: GEICampaignAttestation
    assessment: GEICampaignAssessment


def _placebo_for(
    campaign: AcquisitionCampaignManifest,
    benchmark: SealedCapabilityBenchmark,
    binding: TaskBenchmarkBinding,
) -> tuple[ProgramSkillArtifact, PlaceboCommitment]:
    ast = {"op": "X", "args": ()}
    placebo = ProgramSkillArtifact(
        "genesis-m7-confirmatory-placebo-v1", "FINITE_INTEGER_FUNCTION",
        benchmark.specification.dsl_version, {"kind": "integer"}, {"kind": "integer"},
        ast, expression_metrics(ast, benchmark.specification), ("X",), campaign.campaign_hash,
        (canonical_sha256({"placebo": "predeclared-x", "campaign": campaign.campaign_hash}),),
    )
    return placebo, PlaceboCommitment(
        "genesis-m7-confirmatory-placebo-commitment-v1", campaign.campaign_hash,
        binding.binding_hash, placebo.skill_hash,
        "fixed_identity_program_predeclared_before_m5_execution-v1",
    )


def execute_confirmatory_campaign(
    *,
    policy: GEIAcceptancePolicy,
    battery: GEIConfirmatoryBatteryManifest,
    protocol: CompositionalTransferProtocol,
    benchmark: SealedCapabilityBenchmark,
    task_id: str,
    audit_root: str | Path,
    store: ContentAddressedArtifactStore,
) -> ConfirmatoryCampaignRun:
    """Run one frozen task slot from fresh G0 through all M7 evidence gates."""

    campaign, baseline, binding = build_confirmatory_campaign(
        policy=policy, battery=battery, benchmark=benchmark, task_id=task_id,
    )
    result = AutonomousAcquisitionCampaign().run(
        campaign=campaign, specification=benchmark.specification, benchmark=benchmark,
        g0_manifest=baseline, task_id=task_id, g1_manifest_id=f"{campaign.campaign_id}-g1",
        task_benchmark_binding=binding,
        audit_registry=DurableAuditClaimRegistry(Path(audit_root) / task_id, policy=policy),
    )
    if result.durable_audit is None or result.g1_manifest is None:
        # The slot is still represented in the immutable battery.  A bounded
        # synthesis miss or rejected audit is evidence of incompleteness, not
        # permission to tune the budget or replace the campaign/task.
        attestation = GEICampaignAttestation(
            policy, battery, campaign, baseline, binding, result, result.durable_audit,
            None, None, None, None, None, None, (), None,
        )
        return ConfirmatoryCampaignRun(attestation, attestation.assess(store))
    shared_history = {
        "m7_gei_acceptance_policy": (policy,),
        "m7_gei_battery_manifest": (battery,),
    }
    hidden = materialize_promoted_skill_evidence(
        campaign=campaign, baseline=baseline, benchmark=benchmark, task_id=task_id,
        result=result, split=DatasetSplit.HIDDEN,
    )
    transfer = materialize_promoted_skill_evidence(
        campaign=campaign, baseline=baseline, benchmark=benchmark, task_id=task_id,
        result=result, split=DatasetSplit.TRANSFER,
    )
    composition = materialize_compositional_transfer_evidence(
        policy=policy, protocol=protocol, campaign=campaign, baseline=baseline,
        benchmark=benchmark, task_id=task_id, result=result,
    )
    placebo, placebo_commitment = _placebo_for(campaign, benchmark, binding)
    causal = materialize_causal_capability_attribution(
        campaign=campaign, baseline=baseline, benchmark=benchmark, task_id=task_id,
        acquisition=result, placebo=placebo, placebo_commitment=placebo_commitment,
    )
    hidden_trace = hidden.persist_trace(store, historical_artifacts=shared_history)
    transfer_trace = transfer.persist_trace(store, historical_artifacts=shared_history)
    composition_traces = tuple(
        measurement.persist_trace(store, historical_artifacts=shared_history)
        for measurement in composition.measurements
    )
    causal_persistence = persist_causal_capability_attribution(store, causal, benchmark=benchmark)
    attestation = GEICampaignAttestation(
        policy, battery, campaign, baseline, binding, result, result.durable_audit,
        hidden, transfer, composition, causal, hidden_trace, transfer_trace,
        composition_traces, causal_persistence,
    )
    return ConfirmatoryCampaignRun(attestation, attestation.assess(store))


class GEIBatteryStatus(str, Enum):
    SUPPORTED = "GE_I_BATTERY_SUPPORTED"
    FAIL = "GE_I_BATTERY_FAIL"
    NOT_PROVEN = "GE_I_BATTERY_NOT_PROVEN"


class M7Status(str, Enum):
    """Claim boundary for this unit; it deliberately says nothing about GE-R/M."""

    CLOSED = "CLOSED"
    NOT_READY = "NOT_READY"
    FAIL = "FAIL"


def _aggregate_battery(assessments: tuple[GEICampaignAssessment, ...]) -> GEIBatteryStatus:
    statuses = tuple(item.status for item in assessments)
    if all(item is GEICampaignStatus.SUPPORTED for item in statuses):
        return GEIBatteryStatus.SUPPORTED
    if any(item is GEICampaignStatus.FAIL for item in statuses):
        return GEIBatteryStatus.FAIL
    return GEIBatteryStatus.NOT_PROVEN


@dataclass(frozen=True, slots=True)
class GEIBatteryClosure:
    """All-required-campaigns closure; it cannot substitute or omit a task."""

    policy: GEIAcceptancePolicy
    battery: GEIConfirmatoryBatteryManifest
    attestations: tuple[GEICampaignAttestation, ...]
    assessments: tuple[GEICampaignAssessment, ...]
    status: GEIBatteryStatus
    reason_codes: tuple[str, ...]
    closure_hash: str = field(init=False)

    def __post_init__(self) -> None:
        attestations = tuple(sorted(self.attestations, key=lambda item: item.task_binding.task_id))
        assessments = tuple(sorted(self.assessments, key=lambda item: item.task_id))
        object.__setattr__(self, "attestations", attestations)
        object.__setattr__(self, "assessments", assessments)
        object.__setattr__(self, "status", GEIBatteryStatus(self.status))
        object.__setattr__(self, "reason_codes", tuple(sorted(set(self.reason_codes))))
        tasks = tuple(item.task_binding.task_id for item in attestations)
        if (
            not self.policy.validate()
            or not self.battery.validate()
            or self.policy.policy_hash != self.battery.acceptance_policy_hash
            or tasks != CANONICAL_CONFIRMATORY_TASK_IDS
            or tuple(item.task_id for item in assessments) != CANONICAL_CONFIRMATORY_TASK_IDS
            or len({item.campaign.campaign_hash for item in attestations}) != 6
            or any(getattr(item, "is_confirmatory", True) is not True for item in attestations)
            or any(not item.validate() for item in assessments)
            or any(
                assessment.attestation_hash != attestation.attestation_hash
                or assessment.policy_hash != self.policy.policy_hash
                or assessment.battery_manifest_hash != self.battery.battery_manifest_hash
                or assessment.campaign_hash != attestation.campaign.campaign_hash
                for assessment, attestation in zip(assessments, attestations)
            )
            or self.status is not _aggregate_battery(assessments)
        ):
            raise ValueError("genesis_gei_battery_closure_invalid")
        object.__setattr__(self, "closure_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "acceptance_policy_hash": self.policy.policy_hash,
            "battery_manifest_hash": self.battery.battery_manifest_hash,
            "required_task_ids": CANONICAL_CONFIRMATORY_TASK_IDS,
            "campaign_attestation_hashes": tuple(item.attestation_hash for item in self.attestations),
            "campaign_assessment_hashes": tuple(item.assessment_hash for item in self.assessments),
            "aggregate_status": self.status.value,
            "reason_codes": self.reason_codes,
        }

    @property
    def m7_status(self) -> M7Status:
        if self.status is GEIBatteryStatus.SUPPORTED:
            return M7Status.CLOSED
        if self.status is GEIBatteryStatus.FAIL:
            return M7Status.FAIL
        return M7Status.NOT_READY

    def validate(self, store: ContentAddressedArtifactStore | None = None) -> bool:
        try:
            rebuilt = GEIBatteryClosure(
                self.policy, self.battery, self.attestations, self.assessments,
                self.status, self.reason_codes,
            )
            if rebuilt.closure_hash != self.closure_hash:
                return False
            if store is not None:
                observed = tuple(item.assess(store) for item in self.attestations)
                return observed == self.assessments
            return True
        except (TypeError, ValueError):
            return False


def close_confirmatory_battery(
    *,
    policy: GEIAcceptancePolicy,
    battery: GEIConfirmatoryBatteryManifest,
    runs: tuple[ConfirmatoryCampaignRun, ...],
) -> GEIBatteryClosure:
    """Construct the closure only from the complete exact six-run result set."""

    attestations = tuple(item.attestation for item in runs)
    assessments = tuple(item.assessment for item in runs)
    aggregate = _aggregate_battery(assessments)
    reasons = tuple(
        f"{item.task_id}:{item.status.value}" for item in assessments
        if item.status is not GEICampaignStatus.SUPPORTED
    ) or ("all_required_campaigns_supported",)
    return GEIBatteryClosure(policy, battery, attestations, assessments, aggregate, reasons)
