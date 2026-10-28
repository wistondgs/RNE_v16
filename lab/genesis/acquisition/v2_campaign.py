"""M7-H2B1: native confirmatory orchestration for the frozen V2 battery.

The historical M7 campaign pipeline is intentionally V1-specific: its source
validator replays ``DeterministicProgramSynthesizer`` and its persistence
reader restores ``SynthesisReceipt``.  This module does not coerce a V2
receipt into either object.  Instead it binds the predeclared H2A frontier to
the supervised H2B0 executor and carries that V2 source identity through the
shared, version-neutral AUDIT, M5 and M6 infrastructure.

Only this module may create a binding with the H2B1 confirmatory scope.  The
H2B0 toy entrypoint remains incapable of running a canonical task.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from lab.genesis.acquisition.audit import DurableAuditClaimRegistry, DurableAuditResult
from lab.genesis.acquisition.battery import (
    ConfirmatoryCampaignRun,
    GEICampaignAssessment,
    GateStatus,
    _TAMPER_MATRIX_HASH,
    close_confirmatory_battery,
)
from lab.genesis.acquisition.benchmark import (
    BenchmarkManifest,
    DatasetSplit,
    LearnerTrainingView,
    SealedCapabilityBenchmark,
    SplitEvaluation,
    TaskBenchmarkBinding,
    _benchmark_replay_witness,
    _restore_benchmark_replay_witness,
    validate_task_benchmark_binding,
)
from lab.genesis.acquisition.campaign import PriorInsufficiencyReceipt
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
    CompositionalTransferBinding,
    CompositionalTransferEvidence,
    CompositionalTransferProtocol,
    _apply_wrapper,
    wrapper_implementation_hash,
)
from lab.genesis.acquisition.confirmation import CANONICAL_CONFIRMATORY_TASK_IDS, CampaignGate
from lab.genesis.acquisition.complete_frontier import (
    CompleteFrontierResourceEstimateV2,
    CompleteFrontierSearchPolicyV2,
    GEIAcceptancePolicyV2,
    GEIConfirmatoryBatteryManifestV2,
    TargetClassFrontierAudit,
)
from lab.genesis.acquisition.contracts import (
    CandidateCommitment,
    CapabilityManifest,
    ProgramSkillArtifact,
    PromotionReceipt,
    PromotionStatus,
    derive_successor_manifest,
    validate_manifest_successor,
)
from lab.genesis.acquisition.dsl import evaluate_expression, expression_metrics, validate_program_skill
from lab.genesis.acquisition.dsl import DSLSpecification
from lab.genesis.acquisition.federated_evidence import (
    M7FederatedEvidence,
    _materialize_federated_execution_evidence,
)
from lab.genesis.acquisition.replay import M7FederatedReplay
from lab.genesis.acquisition.m5_capability_runtime import CapabilityExecutionBinding
from lab.genesis.acquisition.ranked_synthesis import (
    RANKED_SYNTHESIZER_IMPLEMENTATION_HASH,
    SEARCH_SEMANTICS_V2_ID,
)
from lab.genesis.acquisition.v2_execution import (
    V2_EXECUTION_ADAPTER_IMPLEMENTATION_HASH,
    V2ExecutionBinding,
    V2ExecutionOutcome,
    V2ExecutionTermination,
    replay_v2_execution,
    replay_v2_confirmatory_execution,
    run_v2_confirmatory_execution,
    validate_v2_execution_outcome,
)
from lab.genesis.contracts.serialization import canonical_json_bytes, canonical_sha256, freeze
from lab.genesis.evidence.artifacts import ContentAddressedArtifactStore, is_artifact_hash
from lab.genesis.evidence.trace_persistence import PersistedTrace, replay_m6_trace
from lab.genesis.verifiers.federation import FederationVerdict


V2_CONFIRMATORY_ORCHESTRATOR_ID = "genesis-m7-v2-confirmatory-orchestrator-h2b1"
V2_CONFIRMATORY_ORCHESTRATOR_HASH = canonical_sha256({
    "implementation": V2_CONFIRMATORY_ORCHESTRATOR_ID,
    "source_receipt": "genesis-m7-v2-synthesis-execution-receipt-h2b0",
    "scope": "H2B1_CONFIRMATORY_FROZEN",
    "no_v1_receipt_coercion": True,
})
V2_CONFIRMATORY_REPLAY_ID = "genesis-m7-v2-confirmatory-replay-h2b1"
V2_CONFIRMATORY_REPLAY_HASH = canonical_sha256({
    "implementation": V2_CONFIRMATORY_REPLAY_ID,
    "search_replay": "native-v2-fresh-worker",
    "m6_replay": "fresh-cas-closures",
})
DURABLE_AUDIT_IMPLEMENTATION_ID = "genesis-m7-durable-audit-atomic-publication-h2b0"
DURABLE_AUDIT_IMPLEMENTATION_HASH = canonical_sha256({
    "implementation": DURABLE_AUDIT_IMPLEMENTATION_ID,
    "publication": "private-fsync-hardlink-write-once-v1",
})


def _require_hash(value: str, reason: str) -> None:
    if not isinstance(value, str) or not is_artifact_hash(value):
        raise ValueError(reason)


def _payload(value: Any) -> Any:
    return value.canonical_payload() if hasattr(value, "canonical_payload") else value


@dataclass(frozen=True, slots=True)
class V2ConfirmatoryCampaignManifest:
    """One H2A task slot materialized without a V1 campaign substitute."""

    schema_version: str
    campaign_id: str
    task_id: str
    g0_snapshot_hash: str
    baseline_manifest_hash: str
    benchmark_manifest_hash: str
    dsl_hash: str
    dataset_commitments: Mapping[str, str]
    dataset_seed_commitments: Mapping[str, str]
    acceptance_policy_hash: str
    battery_manifest_hash: str
    frontier_policy_hash: str
    frontier_audit_hash: str
    cfi_policy_hash: str
    search_implementation_hash: str
    search_semantics_id: str
    max_mdl: int
    max_depth: int
    max_nodes: int
    max_raw_ast_evaluations: int
    max_distinct_behaviors: int
    max_wall_time_seconds: int
    max_peak_memory_mib: int
    human_intervention_policy: str
    campaign_hash: str = field(init=False)

    def __post_init__(self) -> None:
        commits = freeze({str(key): str(value) for key, value in self.dataset_commitments.items()})
        seeds = freeze({str(key): str(value) for key, value in self.dataset_seed_commitments.items()})
        confirmatory = self.schema_version == "genesis-m7-v2-confirmatory-campaign-h2b1"
        fixture = self.schema_version == "genesis-m7-v2-confirmatory-campaign-h2b1-fixture"
        if (
            not (confirmatory or fixture)
            or (confirmatory and (
                self.task_id not in CANONICAL_CONFIRMATORY_TASK_IDS
                or self.campaign_id != f"m7h2-confirmatory-{self.task_id}"
            ))
            or (fixture and not self.campaign_id.startswith("fixture-v2-"))
            or self.search_semantics_id != SEARCH_SEMANTICS_V2_ID
            or self.search_implementation_hash != RANKED_SYNTHESIZER_IMPLEMENTATION_HASH
            or self.human_intervention_policy != "no_interactive_corrective_selection-v1"
            or set(commits) != {item.value for item in DatasetSplit}
            or set(seeds) != {item.value for item in DatasetSplit}
        ):
            raise ValueError("genesis_h2b1_campaign_identity_invalid")
        for value in (
            self.g0_snapshot_hash, self.baseline_manifest_hash, self.benchmark_manifest_hash,
            self.dsl_hash, self.acceptance_policy_hash, self.battery_manifest_hash,
            self.frontier_policy_hash, self.frontier_audit_hash, self.search_implementation_hash,
            self.cfi_policy_hash,
            *commits.values(), *seeds.values(),
        ):
            _require_hash(value, "genesis_h2b1_campaign_hash_invalid")
        limits = (
            self.max_mdl, self.max_depth, self.max_nodes, self.max_raw_ast_evaluations,
            self.max_distinct_behaviors, self.max_wall_time_seconds, self.max_peak_memory_mib,
        )
        if any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in limits):
            raise ValueError("genesis_h2b1_campaign_limits_invalid")
        if self.max_mdl != self.max_nodes:
            raise ValueError("genesis_h2b1_campaign_frontier_invalid")
        object.__setattr__(self, "dataset_commitments", commits)
        object.__setattr__(self, "dataset_seed_commitments", seeds)
        object.__setattr__(self, "campaign_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version, "campaign_id": self.campaign_id,
            "task_id": self.task_id, "g0_snapshot_hash": self.g0_snapshot_hash,
            "baseline_manifest_hash": self.baseline_manifest_hash,
            "benchmark_manifest_hash": self.benchmark_manifest_hash, "dsl_hash": self.dsl_hash,
            "dataset_commitments": self.dataset_commitments,
            "dataset_seed_commitments": self.dataset_seed_commitments,
            "acceptance_policy_hash": self.acceptance_policy_hash,
            "battery_manifest_hash": self.battery_manifest_hash,
            "frontier_policy_hash": self.frontier_policy_hash,
            "frontier_audit_hash": self.frontier_audit_hash,
            "cfi_policy_hash": self.cfi_policy_hash,
            "search_implementation_hash": self.search_implementation_hash,
            "search_semantics_id": self.search_semantics_id, "max_mdl": self.max_mdl,
            "max_depth": self.max_depth, "max_nodes": self.max_nodes,
            "max_raw_ast_evaluations": self.max_raw_ast_evaluations,
            "max_distinct_behaviors": self.max_distinct_behaviors,
            "max_wall_time_seconds": self.max_wall_time_seconds,
            "max_peak_memory_mib": self.max_peak_memory_mib,
            "human_intervention_policy": self.human_intervention_policy,
        }

    def validate(self) -> bool:
        try:
            return type(self)(**self.canonical_payload()).campaign_hash == self.campaign_hash
        except (TypeError, ValueError):
            return False

    # These compatibility views are intentionally structural only.  They let
    # the version-neutral benchmark/AUDIT boundary bind this V2 campaign; they
    # never expose a V1 synthesis receipt or ranking rule.
    @property
    def evidence_classification(self) -> str:
        return "CONFIRMATORY_GE_I_EVIDENCE"

    @property
    def gei_acceptance_policy_hash(self) -> str:
        return self.acceptance_policy_hash

    @property
    def g0_capability_manifest_hash(self) -> str:
        return self.baseline_manifest_hash

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "V2ConfirmatoryCampaignManifest":
        return cls(**dict(payload))


@dataclass(frozen=True, slots=True)
class V2ExecutionLaunch:
    """Frozen H2B1 launch identity, distinct from the scientific H2A policy."""

    schema_version: str
    code_snapshot_hash: str
    environment_commitment_hash: str
    acceptance_policy_hash: str
    battery_manifest_hash: str
    frontier_policy_hash: str
    v2_adapter_hash: str
    durable_audit_hash: str
    replay_implementation_hash: str
    execution_order: tuple[str, ...]
    artifact_root_hash: str
    launch_hash: str = field(init=False)

    def __post_init__(self) -> None:
        order = tuple(self.execution_order)
        if self.schema_version != "genesis-m7-v2-confirmatory-launch-h2b1" or order != CANONICAL_CONFIRMATORY_TASK_IDS:
            raise ValueError("genesis_h2b1_launch_identity_invalid")
        for value in (
            self.code_snapshot_hash, self.environment_commitment_hash, self.acceptance_policy_hash,
            self.battery_manifest_hash, self.frontier_policy_hash, self.v2_adapter_hash,
            self.durable_audit_hash, self.replay_implementation_hash, self.artifact_root_hash,
        ):
            _require_hash(value, "genesis_h2b1_launch_hash_invalid")
        if (
            self.v2_adapter_hash != V2_CONFIRMATORY_ORCHESTRATOR_HASH
            or self.durable_audit_hash != DURABLE_AUDIT_IMPLEMENTATION_HASH
            or self.replay_implementation_hash != V2_CONFIRMATORY_REPLAY_HASH
        ):
            raise ValueError("genesis_h2b1_launch_implementation_binding_invalid")
        object.__setattr__(self, "execution_order", order)
        object.__setattr__(self, "launch_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version, "code_snapshot_hash": self.code_snapshot_hash,
            "environment_commitment_hash": self.environment_commitment_hash,
            "acceptance_policy_hash": self.acceptance_policy_hash,
            "battery_manifest_hash": self.battery_manifest_hash,
            "frontier_policy_hash": self.frontier_policy_hash,
            "v2_adapter_hash": self.v2_adapter_hash, "durable_audit_hash": self.durable_audit_hash,
            "replay_implementation_hash": self.replay_implementation_hash,
            "execution_order": self.execution_order, "artifact_root_hash": self.artifact_root_hash,
        }

    def validate(self) -> bool:
        try:
            return type(self)(**self.canonical_payload()).launch_hash == self.launch_hash
        except (TypeError, ValueError):
            return False


def build_v2_confirmatory_campaign(
    *, policy: GEIAcceptancePolicyV2, battery: GEIConfirmatoryBatteryManifestV2,
    frontier_policy: CompleteFrontierSearchPolicyV2, benchmark: SealedCapabilityBenchmark,
    task_id: str,
) -> tuple[V2ConfirmatoryCampaignManifest, CapabilityManifest, TaskBenchmarkBinding, V2ExecutionBinding]:
    """Materialize exactly one already-declared task; no outcome is consulted."""

    if not (
        policy.validate() and battery.validate() and frontier_policy.validate()
        and benchmark.validate() and battery.acceptance_policy_hash == policy.policy_hash
        and battery.complete_frontier_policy_hash == frontier_policy.policy_hash
        and battery.canonical_benchmark_manifest_hash == benchmark.manifest.manifest_hash
        and task_id in battery.execution_order
    ):
        raise ValueError("genesis_h2b1_campaign_build_binding_invalid")
    plan = battery.plan_for(task_id)
    campaign = V2ConfirmatoryCampaignManifest(
        "genesis-m7-v2-confirmatory-campaign-h2b1", plan.campaign_id, task_id,
        plan.g0_snapshot_hash, plan.baseline.manifest_hash, benchmark.manifest.manifest_hash,
        benchmark.specification.dsl_hash, plan.split_commitment_hashes,
        plan.split_seed_commitment_hashes, policy.policy_hash, battery.battery_manifest_hash,
        frontier_policy.policy_hash, battery.target_frontier_audit_hash,
        battery.causal_protocol_hash,
        RANKED_SYNTHESIZER_IMPLEMENTATION_HASH, SEARCH_SEMANTICS_V2_ID,
        frontier_policy.max_mdl, frontier_policy.max_depth, frontier_policy.max_nodes,
        frontier_policy.max_raw_ast_evaluations, frontier_policy.max_distinct_behaviors,
        frontier_policy.max_wall_time_seconds, frontier_policy.max_peak_memory_mib,
        "no_interactive_corrective_selection-v1",
    )
    binding = TaskBenchmarkBinding(
        "genesis-m7-v2-confirmatory-task-binding-h2b1", campaign.campaign_hash,
        benchmark.manifest.manifest_hash, task_id, plan.split_commitment_hashes,
    )
    engine_policy = frontier_policy.ranked_engine_policy(benchmark.specification)
    execution = V2ExecutionBinding(
        "genesis-m7-v2-execution-binding-h2b1", campaign.campaign_id, task_id,
        campaign.campaign_hash, binding.binding_hash, policy.policy_hash,
        battery.battery_manifest_hash, frontier_policy.policy_hash, engine_policy,
        benchmark.specification.dsl_hash, SEARCH_SEMANTICS_V2_ID,
        "genesis-m7-rank-canonical-enumerative-synthesizer-v2",
        RANKED_SYNTHESIZER_IMPLEMENTATION_HASH, frontier_policy.max_mdl,
        frontier_policy.max_depth, frontier_policy.max_nodes,
        frontier_policy.max_raw_ast_evaluations, frontier_policy.max_distinct_behaviors,
        frontier_policy.max_wall_time_seconds, frontier_policy.max_peak_memory_mib,
        "H2B1_CONFIRMATORY_FROZEN",
    )
    return campaign, plan.baseline, binding, execution


def prepare_v2_confirmatory_launch(
    *, policy: GEIAcceptancePolicyV2, battery: GEIConfirmatoryBatteryManifestV2,
    frontier_policy: CompleteFrontierSearchPolicyV2, audit: TargetClassFrontierAudit,
    estimate: CompleteFrontierResourceEstimateV2, benchmark: SealedCapabilityBenchmark,
    predecessor_v1_policy: Any, predecessor_v1_battery: Any,
    code_snapshot_hash: str, environment_commitment_hash: str, artifact_root_hash: str,
) -> V2ExecutionLaunch:
    """Verify the frozen H2A universe and bind the actual H2B1 implementation."""

    if not (
        policy.validate_against(
            benchmark=benchmark, audit=audit, frontier_policy=frontier_policy, estimate=estimate,
            predecessor_v1_policy=predecessor_v1_policy, predecessor_v1_battery=predecessor_v1_battery,
        )
        and battery.validate_against(
            acceptance_policy=policy, frontier_policy=frontier_policy, estimate=estimate, audit=audit,
            benchmark=benchmark, predecessor_v1_policy=predecessor_v1_policy,
            predecessor_v1_battery=predecessor_v1_battery,
        )
    ):
        raise V2ExecutionIntegrityFailure("IMPLEMENTATION_BINDING_MISMATCH")
    return V2ExecutionLaunch(
        "genesis-m7-v2-confirmatory-launch-h2b1", code_snapshot_hash,
        environment_commitment_hash, policy.policy_hash, battery.battery_manifest_hash,
        frontier_policy.policy_hash, V2_CONFIRMATORY_ORCHESTRATOR_HASH,
        DURABLE_AUDIT_IMPLEMENTATION_HASH, V2_CONFIRMATORY_REPLAY_HASH,
        battery.execution_order, artifact_root_hash,
    )


def execute_v2_confirmatory_battery(
    *, launch: V2ExecutionLaunch, policy: GEIAcceptancePolicyV2,
    battery: GEIConfirmatoryBatteryManifestV2, frontier_policy: CompleteFrontierSearchPolicyV2,
    benchmark: SealedCapabilityBenchmark, protocol: CompositionalTransferProtocol,
    audit_root: str | Path, journal_root: str | Path, store: ContentAddressedArtifactStore,
) -> Any:
    """Execute and durably journal exactly the declared six slots in order.

    The caller must invoke this only after the source tree is clean and the
    launch receipt is persisted.  A pre-existing journal is never overwritten
    or silently treated as a retry; recovering an interrupted historical run
    requires a separately implemented journal reader and fresh validation.
    """

    if not (
        launch.validate() and policy.validate() and battery.validate() and frontier_policy.validate()
        and benchmark.validate() and launch.acceptance_policy_hash == policy.policy_hash
        and launch.battery_manifest_hash == battery.battery_manifest_hash
        and launch.frontier_policy_hash == frontier_policy.policy_hash
        and launch.execution_order == battery.execution_order
        and protocol.validate() and protocol.policy_hash == policy.policy_hash
    ):
        raise V2ExecutionIntegrityFailure("genesis_h2b1_battery_launch_invalid")
    journal_directory = Path(journal_root)
    journal_directory.mkdir(parents=True, exist_ok=True)
    runs: list[V2ConfirmatoryCampaignRun] = []
    for task_id in battery.execution_order:
        path = journal_directory / f"{task_id}.h2b1.json"
        if path.exists():
            raise V2ExecutionIntegrityFailure("genesis_h2b1_existing_journal_requires_recovery")
        run = execute_v2_confirmatory_campaign(
            policy=policy, battery=battery, frontier_policy=frontier_policy,
            benchmark=benchmark, task_id=task_id, audit_root=audit_root, store=store,
            protocol=protocol,
        )
        persist_v2_confirmatory_campaign_run(root=journal_directory, launch=launch, run=run)
        runs.append(run)
    # The historical all-six aggregator is deliberately reused: it accepts
    # versioned attestations by their validated public protocol, not receipt
    # class identity.  No V1 synthesis object enters this closure.
    return close_confirmatory_battery(policy=policy, battery=battery, runs=tuple(runs))


@dataclass(frozen=True, slots=True)
class V2SynthesisOutcome:
    receipt: Any
    selected_skill: ProgramSkillArtifact | None


@dataclass(frozen=True, slots=True)
class V2AcquisitionResult:
    prior: PriorInsufficiencyReceipt
    synthesis: V2SynthesisOutcome
    execution: V2ExecutionOutcome
    commitment: CandidateCommitment | None
    audit: SplitEvaluation | None
    promotion: PromotionReceipt | None
    g1_manifest: CapabilityManifest | None
    task_benchmark_binding: TaskBenchmarkBinding
    durable_audit: DurableAuditResult | None
    execution_binding: V2ExecutionBinding


def _skill_from_v2_outcome(
    *, campaign: V2ConfirmatoryCampaignManifest, benchmark: SealedCapabilityBenchmark,
    outcome: V2ExecutionOutcome,
) -> ProgramSkillArtifact | None:
    receipt = outcome.receipt
    candidate = outcome.selected_candidate
    if receipt.termination_reason is not V2ExecutionTermination.SELECTED_AFTER_COMPLETE_LEVEL:
        return None
    if candidate is None or receipt.selected_candidate_ast != candidate.program_ast:
        raise ValueError("genesis_h2b1_v2_candidate_missing")
    def primitives(node: Mapping[str, Any]) -> tuple[str, ...]:
        return tuple(sorted({str(node["op"]), *(
            primitive for child in node["args"] for primitive in primitives(child)
        )}))

    return ProgramSkillArtifact(
        "genesis-m7-v2-program-skill-h2b1", "FINITE_INTEGER_FUNCTION",
        benchmark.specification.dsl_version, {"kind": "integer"}, {"kind": "integer"},
        candidate.program_ast, expression_metrics(candidate.program_ast, benchmark.specification),
        primitives(candidate.program_ast),
        campaign.campaign_hash,
        (receipt.receipt_hash, receipt.level_transcript_root, receipt.execution_binding_hash),
    )


def _v2_commitment(
    *, campaign: V2ConfirmatoryCampaignManifest, training: LearnerTrainingView,
    outcome: V2ExecutionOutcome, candidate: ProgramSkillArtifact,
) -> CandidateCommitment:
    return CandidateCommitment(
        "genesis-m7-v2-candidate-commitment-h2b1", candidate.skill_hash, campaign.campaign_hash,
        training.training_commitment_hash, outcome.receipt.receipt_hash,
        outcome.receipt.level_transcript_root,
    )


def validate_v2_candidate_commitment(
    *, commitment: CandidateCommitment, campaign: V2ConfirmatoryCampaignManifest,
    training: LearnerTrainingView, outcome: V2ExecutionOutcome, candidate: ProgramSkillArtifact,
) -> bool:
    receipt = outcome.receipt
    return (
        commitment.validate() and campaign.validate() and candidate.validate()
        and receipt.termination_reason is V2ExecutionTermination.SELECTED_AFTER_COMPLETE_LEVEL
        and receipt.selected_candidate_hash == candidate.program_hash
        and receipt.selected_candidate_ast == candidate.program_ast
        and candidate.discovery_campaign_hash == campaign.campaign_hash
        and commitment.candidate_skill_hash == candidate.skill_hash
        and commitment.campaign_hash == campaign.campaign_hash
        and commitment.training_evidence_hash == training.training_commitment_hash
        and commitment.synthesis_receipt_hash == receipt.receipt_hash
        and commitment.ranking_evidence_hash == receipt.level_transcript_root
    )


def _validate_v2_source(
    *, campaign: V2ConfirmatoryCampaignManifest, baseline: CapabilityManifest,
    benchmark: SealedCapabilityBenchmark, task_id: str, binding: TaskBenchmarkBinding,
    execution_binding: V2ExecutionBinding, result: V2AcquisitionResult,
) -> ProgramSkillArtifact:
    candidate = result.synthesis.selected_skill
    if not (
        campaign.validate() and baseline.validate() and benchmark.validate() and binding.validate()
        and execution_binding.validate() and result.task_benchmark_binding == binding
        and result.execution_binding == execution_binding
        and task_id == campaign.task_id == binding.task_id
        and binding.campaign_hash == campaign.campaign_hash
        and binding.benchmark_manifest_hash == benchmark.manifest.manifest_hash
        and dict(binding.split_commitment_hashes) == dict(campaign.dataset_commitments)
        and execution_binding.campaign_hash == campaign.campaign_hash
        and execution_binding.task_binding_hash == binding.binding_hash
        and validate_v2_execution_outcome(binding=execution_binding, outcome=result.execution)
        and candidate is not None and result.commitment is not None and result.audit is not None
        and result.promotion is not None and result.g1_manifest is not None
        and validate_program_skill(candidate, benchmark.specification)
        and result.synthesis.receipt == result.execution.receipt
        and result.execution.receipt.selected_candidate_ast == candidate.program_ast
        and result.execution.receipt.selected_candidate_hash == candidate.program_hash
        and result.commitment.candidate_skill_hash == candidate.skill_hash
        and result.commitment.campaign_hash == campaign.campaign_hash
        and result.commitment.synthesis_receipt_hash == result.execution.receipt.receipt_hash
        and result.promotion.status is PromotionStatus.PROMOTED
        and result.promotion.campaign_hash == campaign.campaign_hash
        and result.promotion.candidate_commitment_hash == result.commitment.commitment_hash
        and result.promotion.synthesis_receipt_hash == result.execution.receipt.receipt_hash
        and result.promotion.candidate_skill_hash == candidate.skill_hash
        and result.promotion.audit_evidence_hash == result.audit.result_hash
        and validate_manifest_successor(result.g1_manifest, baseline, candidate)
        and result.durable_audit is not None and result.durable_audit.validate()
        and result.durable_audit.audit.result_hash == result.audit.result_hash
        and result.durable_audit.claim.slot.policy_hash == campaign.acceptance_policy_hash
        and result.durable_audit.claim.slot.campaign_hash == campaign.campaign_hash
        and result.durable_audit.claim.slot.task_benchmark_binding_hash == binding.binding_hash
        and result.durable_audit.evaluation.candidate_commitment_hash == result.commitment.commitment_hash
    ):
        raise ValueError("genesis_h2b1_v2_source_chain_invalid")
    return candidate


def _historical_artifacts(
    *, campaign: V2ConfirmatoryCampaignManifest, baseline: CapabilityManifest,
    benchmark: SealedCapabilityBenchmark, result: V2AcquisitionResult,
    execution_binding: V2ExecutionBinding,
) -> dict[str, tuple[Any, ...]]:
    candidate = result.synthesis.selected_skill
    assert candidate is not None and result.commitment is not None and result.audit is not None
    assert result.promotion is not None and result.g1_manifest is not None and result.durable_audit is not None
    return {
        "m7_v2_confirmatory_campaign": (campaign,),
        "m7_v2_execution_binding": (execution_binding,),
        "m7_v2_synthesis_receipt": (result.execution.receipt,),
        "m7_v2_resource_receipt": (result.execution.resource_receipt,),
        "m7_v2_level_transcripts": result.execution.level_transcripts,
        "m7_baseline_capability_manifest": (baseline,),
        "m7_benchmark_manifest": (benchmark.manifest,),
        "m7_sealed_benchmark_replay_witness": (_benchmark_replay_witness(benchmark),),
        "m7_dsl_specification": (benchmark.specification,),
        "m7_task_benchmark_binding": (result.task_benchmark_binding,),
        "m7_program_skill": (candidate,),
        "m7_v2_candidate_commitment": (result.commitment,),
        "m7_audit_evaluation": (result.audit,),
        "m7_v2_promotion_receipt": (result.promotion,),
        "m7_successor_capability_manifest": (result.g1_manifest,),
        "m7_durable_audit_claim": (result.durable_audit.claim,),
        "m7_durable_audit_evaluation": (result.durable_audit.evaluation,),
    }


def materialize_v2_promoted_skill_evidence(
    *, campaign: V2ConfirmatoryCampaignManifest, baseline: CapabilityManifest,
    benchmark: SealedCapabilityBenchmark, task_id: str, binding: TaskBenchmarkBinding,
    execution_binding: V2ExecutionBinding, result: V2AcquisitionResult, split: DatasetSplit,
) -> M7FederatedEvidence:
    candidate = _validate_v2_source(
        campaign=campaign, baseline=baseline, benchmark=benchmark, task_id=task_id,
        binding=binding, execution_binding=execution_binding, result=result,
    )
    return _materialize_federated_execution_evidence(
        campaign=campaign, baseline=baseline, benchmark=benchmark, task_id=task_id, split=split,
        task_binding=binding, candidate_identity_hash=candidate.skill_hash,
        candidate_callable=lambda value: evaluate_expression(candidate.program_ast, value, benchmark.specification),
        snapshot_hash=canonical_sha256({"m7_v2_scope": "promoted", "promotion_hash": result.promotion.promotion_hash}),
        historical_artifacts=_historical_artifacts(
            campaign=campaign, baseline=baseline, benchmark=benchmark, result=result,
            execution_binding=execution_binding,
        ),
    )


def materialize_v2_capability_arm_evidence(
    *, campaign: V2ConfirmatoryCampaignManifest, baseline: CapabilityManifest,
    benchmark: SealedCapabilityBenchmark, task_id: str, result: V2AcquisitionResult,
    split: DatasetSplit, execution_binding: CapabilityExecutionBinding,
) -> M7FederatedEvidence:
    # The causal API supplies only the M5 execution binding.  Its V2 source
    # chain was already authenticated before the experiment begins.
    if not execution_binding.validate():
        raise ValueError("genesis_h2b1_v2_causal_execution_invalid")
    candidate = result.synthesis.selected_skill
    if candidate is None or result.g1_manifest is None or result.promotion is None:
        raise ValueError("genesis_h2b1_v2_causal_source_missing")
    _validate_v2_source(
        campaign=campaign, baseline=baseline, benchmark=benchmark, task_id=task_id,
        binding=result.task_benchmark_binding, execution_binding=result.execution_binding,
        result=result,
    )
    historical = _historical_artifacts(
        campaign=campaign, baseline=baseline, benchmark=benchmark, result=result,
        execution_binding=result.execution_binding,
    )
    return _materialize_federated_execution_evidence(
        campaign=campaign, baseline=baseline, benchmark=benchmark, task_id=task_id, split=split,
        task_binding=result.task_benchmark_binding,
        candidate_identity_hash=execution_binding.execution_identity_hash,
        candidate_callable=lambda value: execution_binding.evaluate(value, benchmark.specification),
        snapshot_hash=canonical_sha256({
            "m7_v2_causal_execution_binding": execution_binding.execution_identity_hash,
            "promoted_skill_hash": candidate.skill_hash,
        }),
        historical_artifacts={
            **historical,
            "m7_causal_execution_binding": (execution_binding,),
            "m7_causal_execution_manifest": (execution_binding.manifest,),
            **({"m7_causal_active_program_skill": (execution_binding.active_skill,)} if execution_binding.active_skill else {}),
        },
    )


def materialize_v2_compositional_transfer_evidence(
    *, policy: GEIAcceptancePolicyV2, protocol: CompositionalTransferProtocol,
    campaign: V2ConfirmatoryCampaignManifest, baseline: CapabilityManifest,
    benchmark: SealedCapabilityBenchmark, task_id: str, binding: TaskBenchmarkBinding,
    execution_binding: V2ExecutionBinding, result: V2AcquisitionResult,
) -> CompositionalTransferEvidence:
    """Route the two frozen wrappers through M6 without the V1 source reader."""

    candidate = _validate_v2_source(
        campaign=campaign, baseline=baseline, benchmark=benchmark, task_id=task_id,
        binding=binding, execution_binding=execution_binding, result=result,
    )
    if (
        not policy.validate() or not protocol.validate() or protocol.policy_hash != policy.policy_hash
        or protocol.protocol_commitment_hash != policy.compositional_transfer_protocol_hash
    ):
        raise ValueError("genesis_h2b1_v2_composition_binding_invalid")
    transfer_commitment = binding.split_commitment_hashes[DatasetSplit.TRANSFER.value]
    bindings: list[CompositionalTransferBinding] = []
    measurements: list[M7FederatedEvidence] = []
    for wrapper in protocol.wrappers:
        composition_binding = CompositionalTransferBinding(
            "genesis-m7-v2-compositional-transfer-binding-h2b1", policy.policy_hash,
            protocol.protocol_hash, campaign.campaign_hash, binding.binding_hash,
            candidate.skill_hash, wrapper, wrapper_implementation_hash(wrapper),
            transfer_commitment, protocol.evaluation_policy_hash,
        )
        historical = _historical_artifacts(
            campaign=campaign, baseline=baseline, benchmark=benchmark, result=result,
            execution_binding=execution_binding,
        )
        historical.update({
            "m7_v2_gei_acceptance_policy": (policy,),
            "m7_compositional_transfer_protocol": (protocol,),
            "m7_compositional_transfer_binding": (composition_binding,),
        })
        measurements.append(_materialize_federated_execution_evidence(
            campaign=campaign, baseline=baseline, benchmark=benchmark, task_id=task_id,
            split=DatasetSplit.TRANSFER, task_binding=binding,
            candidate_identity_hash=composition_binding.binding_hash,
            candidate_callable=lambda value, current=wrapper: _apply_wrapper(
                current, evaluate_expression(candidate.program_ast, value, benchmark.specification),
            ),
            snapshot_hash=canonical_sha256({
                "m7_v2_compositional_protocol": protocol.protocol_hash,
                "m7_v2_compositional_binding": composition_binding.binding_hash,
            }),
            historical_artifacts=historical,
            reference_transform=lambda value, current=wrapper: _apply_wrapper(current, value),
            measurement_mode="COMPOSITIONAL",
            measurement_binding_hash=composition_binding.binding_hash,
        ))
        bindings.append(composition_binding)
    evidence = CompositionalTransferEvidence(policy, protocol, tuple(bindings), tuple(measurements))
    if not evidence.validate():
        raise ValueError("genesis_h2b1_v2_composition_materialization_invalid")
    return evidence


def replay_v2_causal_capability_attribution(
    store: ContentAddressedArtifactStore, manifest_hash: str,
) -> Any:
    """Replay M5 roots plus V2-origin M6 arm closures without a V1 restore.

    V2 source semantics are replayed separately from the original execution
    binding.  Here M5 owns the causal replay and M6 owns each persisted arm;
    asking the V1 source replayer to parse a V2 receipt would be laundering.
    """

    def replay_arm(current_store: ContentAddressedArtifactStore, trace_hash: str) -> M7FederatedReplay:
        replay = replay_m6_trace(current_store, trace_hash)
        return M7FederatedReplay(
            replay.admitted, tuple(f"m6:{item}" for item in replay.reasons), trace_hash,
        )

    return replay_causal_capability_attribution(
        store, manifest_hash, arm_evidence_replayer=replay_arm,
    )


def _placebo_for_v2(
    *, campaign: V2ConfirmatoryCampaignManifest, benchmark: SealedCapabilityBenchmark,
    binding: TaskBenchmarkBinding,
) -> tuple[ProgramSkillArtifact, PlaceboCommitment]:
    ast = {"op": "X", "args": ()}
    placebo = ProgramSkillArtifact(
        "genesis-m7-v2-confirmatory-placebo-h2b1", "FINITE_INTEGER_FUNCTION",
        benchmark.specification.dsl_version, {"kind": "integer"}, {"kind": "integer"},
        ast, expression_metrics(ast, benchmark.specification), ("X",), campaign.campaign_hash,
        (canonical_sha256({"placebo": "predeclared-x", "campaign": campaign.campaign_hash}),),
    )
    return placebo, PlaceboCommitment(
        "genesis-m7-v2-confirmatory-placebo-commitment-h2b1", campaign.campaign_hash,
        binding.binding_hash, placebo.skill_hash,
        "fixed_identity_program_predeclared_before_m5_execution-v1",
    )


def _promotion(
    *, campaign: V2ConfirmatoryCampaignManifest, baseline: CapabilityManifest,
    commitment: CandidateCommitment, receipt_hash: str, candidate: ProgramSkillArtifact,
    audit: SplitEvaluation,
) -> tuple[PromotionReceipt, CapabilityManifest | None]:
    if audit.exact_pass:
        successor = derive_successor_manifest(
            baseline, candidate, manifest_id=f"{campaign.campaign_id}-g1",
            schema_version="genesis-m7-v2-confirmatory-g1-h2b1",
        )
        return PromotionReceipt(
            "genesis-m7-v2-promotion-receipt-h2b1", campaign.campaign_hash,
            commitment.commitment_hash, receipt_hash, candidate.skill_hash, audit.result_hash,
            baseline.manifest_hash, successor.manifest_hash, PromotionStatus.PROMOTED,
            ("audit_exact_pass", "candidate_precommitted", "v2_receipt"),
        ), successor
    return PromotionReceipt(
        "genesis-m7-v2-promotion-receipt-h2b1", campaign.campaign_hash,
        commitment.commitment_hash, receipt_hash, candidate.skill_hash, audit.result_hash,
        baseline.manifest_hash, None, PromotionStatus.REJECTED,
        ("audit_not_exact", "v2_receipt"),
    ), None


class V2ExecutionIntegrityFailure(RuntimeError):
    """A condition that invalidates later H2B1 interpretation and must stop."""


def execute_v2_confirmatory_campaign(
    *, policy: GEIAcceptancePolicyV2, battery: GEIConfirmatoryBatteryManifestV2,
    frontier_policy: CompleteFrontierSearchPolicyV2, benchmark: SealedCapabilityBenchmark,
    task_id: str, audit_root: str | Path, store: ContentAddressedArtifactStore,
    protocol: CompositionalTransferProtocol,
    test_v1_synthesis_tripwire: bool = False,
) -> "V2ConfirmatoryCampaignRun":
    """Execute one canonical H2B1 slot once, preserving every terminal state."""

    campaign, baseline, binding, execution_binding = build_v2_confirmatory_campaign(
        policy=policy, battery=battery, frontier_policy=frontier_policy,
        benchmark=benchmark, task_id=task_id,
    )
    training = benchmark.learner_view(task_id)
    prior = PriorInsufficiencyReceipt(
        "genesis-m7-v2-prior-insufficiency-h2b1", campaign.campaign_hash, task_id,
        baseline.manifest_hash, None, 0, len(training.training_examples), "PASS",
        "no_target_skill_installed",
    )
    outcome = run_v2_confirmatory_execution(
        binding=execution_binding, specification=benchmark.specification, training=training,
        test_v1_synthesis_tripwire=test_v1_synthesis_tripwire,
    )
    if not validate_v2_execution_outcome(binding=execution_binding, outcome=outcome):
        raise V2ExecutionIntegrityFailure("genesis_h2b1_execution_outcome_invalid")
    if outcome.receipt.termination_reason is V2ExecutionTermination.FRONTIER_EXHAUSTED_NO_CANDIDATE:
        # H2A proved target membership before launch.  A complete no-candidate
        # result therefore contradicts search/benchmark integrity, not GE-I.
        raise V2ExecutionIntegrityFailure("SEARCH_OR_BENCHMARK_INTEGRITY_FAILURE")
    candidate = _skill_from_v2_outcome(campaign=campaign, benchmark=benchmark, outcome=outcome)
    if candidate is None:
        result = V2AcquisitionResult(
            prior, V2SynthesisOutcome(outcome.receipt, None), outcome, None, None, None,
            None, binding, None, execution_binding,
        )
        attestation = V2GEICampaignAttestation(
            policy, battery, campaign, baseline, benchmark, binding, execution_binding, result,
            None, None, None, None, (), None,
        )
        return V2ConfirmatoryCampaignRun(attestation, attestation.assess(store))
    commitment = _v2_commitment(
        campaign=campaign, training=training, outcome=outcome, candidate=candidate,
    )
    if not validate_v2_candidate_commitment(
        commitment=commitment, campaign=campaign, training=training,
        outcome=outcome, candidate=candidate,
    ):
        raise V2ExecutionIntegrityFailure("genesis_h2b1_candidate_commitment_invalid")
    durable = DurableAuditClaimRegistry(Path(audit_root) / task_id, policy=policy).evaluate(
        campaign=campaign, task_binding=binding, commitment=commitment,
        evaluate_once=lambda: benchmark.commit_candidate(task_id, candidate).evaluate_once(),
    )
    promotion, successor = _promotion(
        campaign=campaign, baseline=baseline, commitment=commitment,
        receipt_hash=outcome.receipt.receipt_hash, candidate=candidate, audit=durable.audit,
    )
    result = V2AcquisitionResult(
        prior, V2SynthesisOutcome(outcome.receipt, candidate), outcome, commitment,
        durable.audit, promotion, successor, binding, durable, execution_binding,
    )
    if successor is None:
        attestation = V2GEICampaignAttestation(
            policy, battery, campaign, baseline, benchmark, binding, execution_binding, result,
            None, None, None, None, (), None,
        )
        return V2ConfirmatoryCampaignRun(attestation, attestation.assess(store))
    _validate_v2_source(
        campaign=campaign, baseline=baseline, benchmark=benchmark, task_id=task_id,
        binding=binding, execution_binding=execution_binding, result=result,
    )
    hidden = materialize_v2_promoted_skill_evidence(
        campaign=campaign, baseline=baseline, benchmark=benchmark, task_id=task_id,
        binding=binding, execution_binding=execution_binding, result=result, split=DatasetSplit.HIDDEN,
    )
    transfer = materialize_v2_promoted_skill_evidence(
        campaign=campaign, baseline=baseline, benchmark=benchmark, task_id=task_id,
        binding=binding, execution_binding=execution_binding, result=result, split=DatasetSplit.TRANSFER,
    )
    composition = materialize_v2_compositional_transfer_evidence(
        policy=policy, protocol=protocol, campaign=campaign, baseline=baseline,
        benchmark=benchmark, task_id=task_id, binding=binding,
        execution_binding=execution_binding, result=result,
    )
    placebo, placebo_commitment = _placebo_for_v2(
        campaign=campaign, benchmark=benchmark, binding=binding,
    )
    causal = materialize_causal_capability_attribution(
        campaign=campaign, baseline=baseline, benchmark=benchmark, task_id=task_id,
        acquisition=result, placebo=placebo, placebo_commitment=placebo_commitment,
        arm_evidence_materializer=materialize_v2_capability_arm_evidence,
    )
    shared = {
        "m7_v2_gei_acceptance_policy": (policy,),
        "m7_v2_gei_battery_manifest": (battery,),
        "m7_v2_execution_binding": (execution_binding,),
    }
    hidden_trace = hidden.persist_trace(store, historical_artifacts=shared)
    transfer_trace = transfer.persist_trace(store, historical_artifacts=shared)
    composition_traces = tuple(
        item.persist_trace(store, historical_artifacts=shared) for item in composition.measurements
    )
    causal_persistence = (
        persist_causal_capability_attribution(store, causal, benchmark=benchmark)
        if causal.verdict is CausalAttributionStatus.PASS else None
    )
    attestation = V2GEICampaignAttestation(
        policy, battery, campaign, baseline, benchmark, binding, execution_binding, result, hidden, transfer,
        composition, causal, (hidden_trace, transfer_trace, *composition_traces), causal_persistence,
    )
    return V2ConfirmatoryCampaignRun(attestation, attestation.assess(store))


def _campaign_status(gates: Mapping[str, GateStatus]) -> Any:
    from lab.genesis.acquisition.battery import GEICampaignStatus

    values = tuple(gates.values())
    if all(item is GateStatus.PASS for item in values):
        return GEICampaignStatus.SUPPORTED
    if any(item is GateStatus.FAIL for item in values):
        return GEICampaignStatus.FAIL
    return GEICampaignStatus.NOT_PROVEN


@dataclass(frozen=True, slots=True)
class V2GEICampaignAttestation:
    """V2 source-chain attestation accepted by the existing six-run closure."""

    policy: GEIAcceptancePolicyV2
    battery: GEIConfirmatoryBatteryManifestV2
    campaign: V2ConfirmatoryCampaignManifest
    baseline: CapabilityManifest
    benchmark: SealedCapabilityBenchmark
    task_binding: TaskBenchmarkBinding
    execution_binding: V2ExecutionBinding
    result: V2AcquisitionResult
    hidden: M7FederatedEvidence | None
    transfer: M7FederatedEvidence | None
    composition: CompositionalTransferEvidence | None
    causal: CausalCapabilityAttribution | None
    traces: tuple[PersistedTrace, ...]
    causal_persistence: PersistedCausalEvidence | None
    attestation_hash: str = field(init=False)

    @property
    def is_confirmatory(self) -> bool:
        """Fixtures may exercise gates but must be ineligible for six-run closure."""

        return self.campaign.schema_version == "genesis-m7-v2-confirmatory-campaign-h2b1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "traces", tuple(self.traces))
        populated = (self.hidden, self.transfer, self.composition, self.causal, self.causal_persistence)
        if any(item is not None for item in populated) and (
            any(item is None for item in populated) or len(self.traces) != 4
        ):
            raise ValueError("genesis_h2b1_attestation_evidence_incomplete")
        if not any(item is not None for item in populated) and self.traces:
            raise ValueError("genesis_h2b1_attestation_partial_traces_invalid")
        if not (
            self.policy.validate() and self.battery.validate() and self.campaign.validate()
            and self.baseline.validate() and self.benchmark.validate() and self.task_binding.validate()
            and self.execution_binding.validate()
            and self.policy.policy_hash == self.battery.acceptance_policy_hash
            and self.campaign.acceptance_policy_hash == self.policy.policy_hash
            and self.campaign.battery_manifest_hash == self.battery.battery_manifest_hash
            and self.campaign.baseline_manifest_hash == self.baseline.manifest_hash
            and self.campaign.benchmark_manifest_hash == self.benchmark.manifest.manifest_hash
            and self.task_binding.campaign_hash == self.campaign.campaign_hash
            and self.result.task_benchmark_binding == self.task_binding
            and self.result.execution_binding == self.execution_binding
        ):
            raise ValueError("genesis_h2b1_attestation_binding_invalid")
        if self.is_confirmatory:
            plan = self.battery.plan_for(self.task_binding.task_id)
            if not (
                self.campaign.campaign_id == plan.campaign_id
                and self.campaign.g0_snapshot_hash == plan.g0_snapshot_hash
                and self.campaign.baseline_manifest_hash == plan.baseline.manifest_hash
                and dict(self.campaign.dataset_commitments) == dict(plan.split_commitment_hashes)
                and dict(self.campaign.dataset_seed_commitments) == dict(plan.split_seed_commitment_hashes)
                and self.campaign.frontier_policy_hash == self.battery.complete_frontier_policy_hash
            ):
                raise ValueError("genesis_h2b1_attestation_predeclaration_mismatch")
        object.__setattr__(self, "attestation_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        candidate = self.result.synthesis.selected_skill
        return {
            "schema_version": "genesis-m7-v2-gei-campaign-attestation-h2b1",
            "policy_hash": self.policy.policy_hash,
            "battery_manifest_hash": self.battery.battery_manifest_hash,
            "campaign_hash": self.campaign.campaign_hash,
            "baseline_manifest_hash": self.baseline.manifest_hash,
            "task_binding_hash": self.task_binding.binding_hash,
            "task_id": self.task_binding.task_id,
            "execution_binding_hash": self.execution_binding.binding_hash,
            "v2_synthesis_receipt_hash": self.result.execution.receipt.receipt_hash,
            "v2_resource_receipt_hash": self.result.execution.resource_receipt.receipt_hash,
            "promoted_skill_hash": None if candidate is None else candidate.skill_hash,
            "prior_hash": self.result.prior.receipt_hash,
            "candidate_commitment_hash": None if self.result.commitment is None else self.result.commitment.commitment_hash,
            "audit_claim_hash": None if self.result.durable_audit is None else self.result.durable_audit.claim.claim_hash,
            "audit_evaluation_hash": None if self.result.durable_audit is None else self.result.durable_audit.evaluation.receipt_hash,
            "promotion_hash": None if self.result.promotion is None else self.result.promotion.promotion_hash,
            "trace_closure_hashes": tuple(item.closure_hash for item in self.traces),
            "causal_evidence_manifest_hash": None if self.causal_persistence is None else self.causal_persistence.manifest_hash,
            "tamper_matrix_hash": self.battery.tamper_matrix_hash,
        }

    def validate(self) -> bool:
        return (
            self.policy.validate() and self.battery.validate() and self.campaign.validate()
            and self.baseline.validate() and self.benchmark.validate() and self.task_binding.validate()
            and self.execution_binding.validate()
            and self.attestation_hash == canonical_sha256(self.canonical_payload())
        )

    def _base_gates(self) -> dict[str, GateStatus]:
        gates = {item.value: GateStatus.NOT_PROVEN for item in CampaignGate}
        outcome = self.result.execution
        candidate = self.result.synthesis.selected_skill
        resource = outcome.resource_receipt
        execution_ok = validate_v2_execution_outcome(
            binding=self.execution_binding, outcome=outcome,
        )
        selected = (
            execution_ok and candidate is not None and self.result.commitment is not None
            and outcome.receipt.termination_reason is V2ExecutionTermination.SELECTED_AFTER_COMPLETE_LEVEL
            and outcome.receipt.selected_candidate_hash == candidate.program_hash
            and outcome.receipt.selected_candidate_ast == candidate.program_ast
        )
        gates[CampaignGate.PRIOR_STRUCTURAL_ABSENCE.value] = (
            GateStatus.PASS if not self.baseline.skill_hashes else GateStatus.FAIL
        )
        gates[CampaignGate.PRIOR_BEHAVIORAL_INSUFFICIENCY.value] = (
            GateStatus.PASS if self.result.prior.verdict == "PASS" and self.result.prior.correct == 0 else GateStatus.FAIL
        )
        gates[CampaignGate.CAMPAIGN_FROZEN.value] = GateStatus.PASS if self.campaign.validate() else GateStatus.NOT_PROVEN
        gates[CampaignGate.TRAIN_ONLY_LEARNER_VIEW.value] = GateStatus.PASS if selected else GateStatus.NOT_PROVEN
        gates[CampaignGate.DETERMINISTIC_SYNTHESIS.value] = GateStatus.PASS if selected else GateStatus.NOT_PROVEN
        gates[CampaignGate.DETERMINISTIC_SELECTION.value] = GateStatus.PASS if selected else GateStatus.NOT_PROVEN
        limits_ok = (
            execution_ok
            and resource.configured_raw_ast_cap == self.campaign.max_raw_ast_evaluations
            and resource.configured_behavior_cap == self.campaign.max_distinct_behaviors
            and resource.configured_wall_time_seconds == self.campaign.max_wall_time_seconds
            and resource.configured_peak_memory_mib == self.campaign.max_peak_memory_mib
            and outcome.receipt.raw_ast_count <= self.campaign.max_raw_ast_evaluations
            and outcome.receipt.behavior_class_count <= self.campaign.max_distinct_behaviors
        )
        gates[CampaignGate.SEARCH_BUDGET_RESPECTED.value] = GateStatus.PASS if limits_ok else GateStatus.NOT_PROVEN
        gates[CampaignGate.CANDIDATE_COMMITMENT.value] = GateStatus.PASS if selected else GateStatus.NOT_PROVEN
        durable = self.result.durable_audit
        audit_ok = (
            selected and durable is not None and durable.validate() and self.result.audit is not None
            and durable.audit.result_hash == self.result.audit.result_hash
            and durable.claim.slot.policy_hash == self.policy.policy_hash
            and durable.claim.slot.campaign_hash == self.campaign.campaign_hash
            and durable.claim.slot.task_benchmark_binding_hash == self.task_binding.binding_hash
            and durable.evaluation.candidate_commitment_hash == self.result.commitment.commitment_hash
        )
        gates[CampaignGate.AUDIT_ONE_SHOT.value] = GateStatus.PASS if audit_ok else GateStatus.NOT_PROVEN
        gates[CampaignGate.AUDIT_PASS.value] = (
            GateStatus.NOT_PROVEN if self.result.audit is None
            else GateStatus.PASS if audit_ok and self.result.audit.exact_pass else GateStatus.FAIL
        )
        promoted = (
            selected and self.result.promotion is not None and self.result.g1_manifest is not None
            and self.result.promotion.status is PromotionStatus.PROMOTED
            and validate_manifest_successor(self.result.g1_manifest, self.baseline, candidate)
        )
        gates[CampaignGate.PROMOTION_PASS.value] = GateStatus.PASS if promoted else (
            GateStatus.NOT_PROVEN if self.result.promotion is None else GateStatus.FAIL
        )
        gates[CampaignGate.G1_DELTA_EXACTLY_Z.value] = GateStatus.PASS if promoted else GateStatus.NOT_PROVEN
        hidden_ok = self.hidden is not None and candidate is not None and (
            self.hidden.scope.split is DatasetSplit.HIDDEN
            and self.hidden.scope.candidate_skill_hash == candidate.skill_hash
            and self.hidden.adjudication.verdict is FederationVerdict.PASS
        )
        transfer_ok = self.transfer is not None and candidate is not None and (
            self.transfer.scope.split is DatasetSplit.TRANSFER
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
        causal_gate = lambda verdict: GateStatus.NOT_PROVEN if self.causal is None else GateStatus.PASS if causal_valid and verdict else GateStatus.FAIL
        gates[CampaignGate.C1_TREATMENT_EFFECT.value] = causal_gate(False if self.causal is None else self.causal.treatment_effect)
        gates[CampaignGate.C1_PLACEBO_CONTROL.value] = causal_gate(False if self.causal is None else self.causal.placebo_control)
        gates[CampaignGate.C1_CFI.value] = GateStatus.NOT_PROVEN if self.causal is None else GateStatus.PASS if causal_valid else GateStatus.FAIL
        gates[CampaignGate.C2_ABLATION_NECESSITY.value] = causal_gate(False if self.causal is None else self.causal.necessity)
        gates[CampaignGate.C2_CFI.value] = GateStatus.NOT_PROVEN if self.causal is None else GateStatus.PASS if causal_valid else GateStatus.FAIL
        gates[CampaignGate.C3_TRANSPLANT_SUFFICIENCY.value] = causal_gate(False if self.causal is None else self.causal.sufficiency)
        gates[CampaignGate.C3_CFI.value] = GateStatus.NOT_PROVEN if self.causal is None else GateStatus.PASS if causal_valid else GateStatus.FAIL
        gates[CampaignGate.EXACT_SKILL_IDENTITY.value] = causal_gate(False if self.causal is None else self.causal.exact_skill_identity)
        gates[CampaignGate.TAMPER_MATRIX.value] = (
            GateStatus.PASS if self.battery.tamper_matrix_hash == _TAMPER_MATRIX_HASH else GateStatus.NOT_PROVEN
        )
        return gates

    def assess(self, store: ContentAddressedArtifactStore) -> GEICampaignAssessment:
        """Run fresh V2 semantic replay plus the persisted M5/M6 replay gates."""

        gates = self._base_gates()
        replay_ok = False
        if self.hidden is not None and self.transfer is not None and self.causal_persistence is not None and len(self.traces) == 4:
            try:
                fresh = _fresh_benchmark(self.benchmark)
                training = fresh.learner_view(self.task_binding.task_id)
                v2 = replay_v2_execution(
                    binding=self.execution_binding, specification=fresh.specification,
                    training=training, outcome=self.result.execution,
                )
                m6_ok = all(replay_m6_trace(store, trace.closure_hash).admitted for trace in self.traces)
                causal = replay_v2_causal_capability_attribution(store, self.causal_persistence.manifest_hash)
                replay_ok = (
                    v2.receipt.semantic_payload() == self.result.execution.receipt.semantic_payload()
                    and m6_ok and causal.admitted
                )
            except (KeyError, TypeError, ValueError):
                replay_ok = False
        gates[CampaignGate.PERSISTENCE.value] = GateStatus.PASS if replay_ok else GateStatus.NOT_PROVEN
        gates[CampaignGate.FRESH_REPLAY.value] = GateStatus.PASS if replay_ok else GateStatus.NOT_PROVEN
        gates[CampaignGate.TEMPORAL_REPLAY.value] = GateStatus.PASS if replay_ok else GateStatus.NOT_PROVEN
        return GEICampaignAssessment(
            self.attestation_hash, self.policy.policy_hash, self.battery.battery_manifest_hash,
            self.task_binding.task_id, self.campaign.campaign_hash, gates, _campaign_status(gates),
        )


def _fresh_benchmark(benchmark: SealedCapabilityBenchmark) -> SealedCapabilityBenchmark:
    """Reconstruct evaluator state from serializable sealed sources, not live objects."""

    specification = DSLSpecification.from_payload(benchmark.specification.canonical_payload())
    manifest = BenchmarkManifest.from_payload(benchmark.manifest.canonical_payload())
    witness = type(_benchmark_replay_witness(benchmark)).from_payload(
        _benchmark_replay_witness(benchmark).canonical_payload()
    )
    return _restore_benchmark_replay_witness(
        specification=specification, manifest=manifest, witness=witness,
    )


@dataclass(frozen=True, slots=True)
class V2ConfirmatoryCampaignRun:
    attestation: V2GEICampaignAttestation
    assessment: GEICampaignAssessment


def _result_payload(run: V2ConfirmatoryCampaignRun) -> dict[str, Any]:
    result = run.attestation.result
    return {
        "attestation": run.attestation.canonical_payload(),
        "assessment": run.assessment.canonical_payload(),
        "campaign": run.attestation.campaign.canonical_payload(),
        "task_binding": run.attestation.task_binding.canonical_payload(),
        "execution_binding": run.attestation.execution_binding.canonical_payload(),
        "v2_synthesis_receipt": result.execution.receipt.canonical_payload(),
        "v2_resource_receipt": result.execution.resource_receipt.canonical_payload(),
        "v2_level_transcripts": tuple(item.canonical_payload() for item in result.execution.level_transcripts),
        "candidate": None if result.synthesis.selected_skill is None else result.synthesis.selected_skill.canonical_payload(),
        "candidate_commitment": None if result.commitment is None else result.commitment.canonical_payload(),
        "audit": None if result.audit is None else result.audit.canonical_payload(),
        "durable_audit": None if result.durable_audit is None else result.durable_audit.canonical_payload(),
        "promotion": None if result.promotion is None else result.promotion.canonical_payload(),
        "g1_manifest": None if result.g1_manifest is None else result.g1_manifest.canonical_payload(),
    }


def persist_v2_confirmatory_campaign_run(
    *, root: str | Path, launch: V2ExecutionLaunch, run: V2ConfirmatoryCampaignRun,
) -> Path:
    """Publish one terminal campaign journal atomically, without overwrite/retry."""

    if not launch.validate() or not run.attestation.validate() or not run.assessment.validate():
        raise ValueError("genesis_h2b1_campaign_journal_source_invalid")
    directory = Path(root)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{run.attestation.task_binding.task_id}.h2b1.json"
    payload = {
        "schema_version": "genesis-m7-v2-confirmatory-run-journal-h2b1",
        "launch": launch.canonical_payload(),
        "run": _result_payload(run),
    }
    data = canonical_json_bytes(payload)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("genesis_h2b1_campaign_journal_conflict")
        return path
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.pending")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != data:
                raise ValueError("genesis_h2b1_campaign_journal_conflict")
        return path
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
