"""M7-E2 causal attribution from three real M5 experiments and M6 closures.

The module is deliberately a composition layer.  It has no local CFI rule,
verdict engine, or verifier: M5 owns fork/isolation/sealing/CFI and M6 owns
the per-scope evidence closure.  The only M7-specific work here is to bind
those already-derived artifacts to the scientific C1/C2/C3 question and to
reject false re-sealings that M6 cannot interpret semantically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping, Sequence

from lab.genesis.acquisition.benchmark import DatasetSplit, SealedCapabilityBenchmark
from lab.genesis.acquisition.campaign import AcquisitionResult
from lab.genesis.acquisition.contracts import (
    AcquisitionCampaignManifest,
    CapabilityManifest,
    ProgramSkillArtifact,
    derive_successor_manifest,
    validate_manifest_successor,
)
from lab.genesis.acquisition.dsl import validate_program_skill
from lab.genesis.acquisition.federated_evidence import (
    M7FederatedEvidence,
    materialize_capability_arm_evidence,
)
from lab.genesis.acquisition.m5_capability_runtime import (
    CapabilityArmRuntime,
    CapabilityExecutionBinding,
    CapabilityMeasurementOracle,
    CapabilityOperation,
    CapabilityStateAction,
    capability_intervention_type,
    capability_root_state,
)
from lab.genesis.causal.cfi import CFIStatus
from lab.genesis.causal.fork import RootSnapshot, SyntheticForkableStateAdapter
from lab.genesis.contracts.serialization import canonical_sha256, freeze
from lab.genesis.intervention.kernel import GenericInterventionKernel, KernelResult
from lab.genesis.intervention.replay import CausalExperimentReplay
from lab.genesis.intervention.specs import (
    ArmRole,
    ArmSpec,
    CausalExperimentManifest,
    ComputeBudgetSpec,
    InterventionSpec,
    RNGPolicy,
)
from lab.genesis.verifiers.federation import FederationVerdict


_SCOPES = (DatasetSplit.HIDDEN, DatasetSplit.TRANSFER)
_CAPABILITY_PATHS = (
    "capabilities.manifest_hash",
    "capabilities.installed_skill_hashes",
    "capabilities.execution_skill_hash",
)


class CausalAttributionStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_PROVEN = "NOT_PROVEN"


def _require_hash(value: str, reason: str) -> None:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(reason)


def _inputs_for_scopes(benchmark: SealedCapabilityBenchmark, task_id: str) -> tuple[int, ...]:
    if task_id not in benchmark._tasks:
        raise ValueError("genesis_m7_causal_task_missing")
    return tuple(
        example.input_value
        for split in _SCOPES
        for example in benchmark._tasks[task_id].datasets[split]
    )


@dataclass(frozen=True, slots=True)
class PlaceboCommitment:
    """A pre-experiment commitment to the particular inert skill artifact."""

    schema_version: str
    campaign_hash: str
    task_benchmark_binding_hash: str
    placebo_skill_hash: str
    selection_policy: str
    commitment_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.schema_version or not self.selection_policy:
            raise ValueError("genesis_m7_causal_placebo_identity_invalid")
        for value in (
            self.campaign_hash,
            self.task_benchmark_binding_hash,
            self.placebo_skill_hash,
        ):
            _require_hash(value, "genesis_m7_causal_placebo_hash_invalid")
        object.__setattr__(self, "commitment_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, str]:
        return {
            "schema_version": self.schema_version,
            "campaign_hash": self.campaign_hash,
            "task_benchmark_binding_hash": self.task_benchmark_binding_hash,
            "placebo_skill_hash": self.placebo_skill_hash,
            "selection_policy": self.selection_policy,
        }

    def validate(self) -> bool:
        return self.commitment_hash == canonical_sha256(self.canonical_payload())


@dataclass(frozen=True, slots=True)
class FreshBaselineReceipt:
    """Re-derivable proof that C3 starts from a matched, z-free source."""

    schema_version: str
    baseline_manifest_hash: str
    fresh_manifest_hash: str
    baseline_skill_hashes: tuple[str, ...]
    fresh_skill_hashes: tuple[str, ...]
    excluded_skill_hash: str
    history_skill_hashes: tuple[str, ...]
    receipt_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "baseline_skill_hashes", tuple(sorted(self.baseline_skill_hashes)))
        object.__setattr__(self, "fresh_skill_hashes", tuple(sorted(self.fresh_skill_hashes)))
        object.__setattr__(self, "history_skill_hashes", tuple(sorted(self.history_skill_hashes)))
        if (
            self.baseline_manifest_hash == self.fresh_manifest_hash
            or self.baseline_skill_hashes != self.fresh_skill_hashes
            or self.excluded_skill_hash in self.fresh_skill_hashes
            or self.excluded_skill_hash in self.history_skill_hashes
        ):
            raise ValueError("genesis_m7_causal_fresh_baseline_invalid")
        for value in (
            self.baseline_manifest_hash,
            self.fresh_manifest_hash,
            self.excluded_skill_hash,
            *self.baseline_skill_hashes,
            *self.fresh_skill_hashes,
            *self.history_skill_hashes,
        ):
            _require_hash(value, "genesis_m7_causal_fresh_baseline_hash_invalid")
        object.__setattr__(self, "receipt_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "baseline_manifest_hash": self.baseline_manifest_hash,
            "fresh_manifest_hash": self.fresh_manifest_hash,
            "baseline_skill_hashes": self.baseline_skill_hashes,
            "fresh_skill_hashes": self.fresh_skill_hashes,
            "excluded_skill_hash": self.excluded_skill_hash,
            "history_skill_hashes": self.history_skill_hashes,
        }

    def validate(self) -> bool:
        try:
            return FreshBaselineReceipt(**self.canonical_payload()).receipt_hash == self.receipt_hash
        except (TypeError, ValueError):
            return False


@dataclass(frozen=True, slots=True)
class CausalArmClosure:
    """One visible state with its M5 observation and two M6 scope closures."""

    arm_id: str
    root: RootSnapshot
    execution_binding: CapabilityExecutionBinding
    m5_result: KernelResult
    hidden: M7FederatedEvidence
    transfer: M7FederatedEvidence
    closure_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.arm_id or not self.execution_binding.validate():
            raise ValueError("genesis_m7_causal_arm_identity_invalid")
        if self.root.root_hash != self.m5_result.root.root_hash:
            raise ValueError("genesis_m7_causal_arm_root_mismatch")
        object.__setattr__(self, "closure_hash", canonical_sha256(self.canonical_payload()))

    @property
    def m5_receipt(self) -> Any:
        return next((item for item in self.m5_result.receipts if item.arm_id == self.arm_id), None)

    @property
    def score(self) -> float:
        receipt = self.m5_receipt
        if receipt is None:
            raise ValueError("genesis_m7_causal_arm_receipt_missing")
        return receipt.score

    def canonical_payload(self) -> dict[str, Any]:
        receipt = self.m5_receipt
        return {
            "arm_id": self.arm_id,
            "root_hash": self.root.root_hash,
            "execution_binding_hash": self.execution_binding.execution_identity_hash,
            "m5_manifest_hash": self.m5_result.manifest.manifest_hash,
            "m5_cfi_report_hash": self.m5_result.cfi.report_hash,
            "m5_receipt_hash": None if receipt is None else receipt.receipt_hash,
            "hidden_scope_hash": self.hidden.scope.scope_hash,
            "hidden_adjudication_hash": self.hidden.adjudication.receipt_hash,
            "transfer_scope_hash": self.transfer.scope.scope_hash,
            "transfer_adjudication_hash": self.transfer.adjudication.receipt_hash,
        }

    def validate(self) -> bool:
        receipt = self.m5_receipt
        if (
            receipt is None
            or not self.execution_binding.validate()
            or self.execution_binding.arm_id != self.arm_id
            or self.root.root_hash != self.m5_result.root.root_hash
            or self.execution_binding.root_snapshot_hash != self.root.root_hash
            or CausalExperimentReplay.verify(self.m5_result).status != "PASS"
            or receipt.root_snapshot_hash != self.root.root_hash
            or self.hidden.scope.split is not DatasetSplit.HIDDEN
            or self.transfer.scope.split is not DatasetSplit.TRANSFER
        ):
            return False
        evidences = (self.hidden, self.transfer)
        expected_verdict = FederationVerdict.PASS if receipt.score == 1.0 else FederationVerdict.FAIL
        if any(
            evidence.scope.candidate_skill_hash != self.execution_binding.execution_identity_hash
            or evidence.adjudication.verdict is not expected_verdict
            for evidence in evidences
        ):
            return False
        return self.closure_hash == canonical_sha256(self.canonical_payload())


@dataclass(frozen=True, slots=True)
class CausalExperiment:
    """A registered C1, C2 or C3 experiment, never a loose collection of arms."""

    experiment_id: str
    root: RootSnapshot
    actions: tuple[CapabilityStateAction, ...]
    interventions: tuple[InterventionSpec, ...]
    result: KernelResult
    arms: tuple[CausalArmClosure, ...]
    experiment_hash: str = field(init=False)

    def __post_init__(self) -> None:
        actions = tuple(sorted(self.actions, key=lambda item: item.action_id))
        interventions = tuple(sorted(self.interventions, key=lambda item: item.intervention_id))
        arms = tuple(sorted(self.arms, key=lambda item: item.arm_id))
        object.__setattr__(self, "actions", actions)
        object.__setattr__(self, "interventions", interventions)
        object.__setattr__(self, "arms", arms)
        if (
            not self.experiment_id
            or self.root.root_hash != self.result.root.root_hash
            or len({item.action_id for item in actions}) != len(actions)
            or len({item.intervention_id for item in interventions}) != len(interventions)
            or len({item.arm_id for item in arms}) != len(arms)
        ):
            raise ValueError("genesis_m7_causal_experiment_identity_invalid")
        object.__setattr__(self, "experiment_hash", canonical_sha256(self.canonical_payload()))

    def arm(self, arm_id: str) -> CausalArmClosure:
        result = next((item for item in self.arms if item.arm_id == arm_id), None)
        if result is None:
            raise ValueError("genesis_m7_causal_arm_missing")
        return result

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "root_hash": self.root.root_hash,
            "m5_manifest_hash": self.result.manifest.manifest_hash,
            "m5_cfi_report_hash": self.result.cfi.report_hash,
            "m5_summary_hash": self.result.summary.summary_hash,
            "m5_trace_hash": self.result.trace.trace_hash,
            "actions": tuple(item.canonical_payload() for item in self.actions),
            "interventions": tuple(item.canonical_payload() for item in self.interventions),
            "arms": tuple(item.canonical_payload() for item in self.arms),
        }

    def validate(self) -> bool:
        m5_by_arm = {item.arm_id: item for item in self.result.receipts}
        expected_arms = {item.arm_id for item in self.result.manifest.arm_specs}
        if (
            self.result.manifest.experiment_id != self.experiment_id
            or self.root.root_hash != self.result.root.root_hash
            or self.result.cfi.status is not CFIStatus.PASS
            or CausalExperimentReplay.verify(self.result).status != "PASS"
            or set(m5_by_arm) != expected_arms
            or {item.arm_id for item in self.arms} != expected_arms
            or {item.action_id for item in self.actions} != expected_arms
            or {item.intervention_id for item in self.interventions} != expected_arms
        ):
            return False
        specs = {item.arm_id: item for item in self.result.manifest.arm_specs}
        interventions = {item.intervention_id: item for item in self.interventions}
        for arm in self.arms:
            spec = specs.get(arm.arm_id)
            action = next(
                (item for item in self.actions if item.action_id == arm.arm_id),
                None,
            )
            intervention = interventions.get(arm.arm_id)
            if (
                spec is None
                or action is None
                or intervention is None
                or not action.validate()
                or spec.intervention_spec_hash != intervention.spec_hash
                or intervention.parameters_hash != action.action_hash
                or intervention.intervention_type != capability_intervention_type(action.operation)
                or intervention.target_paths != (
                    _CAPABILITY_PATHS if action.operation is not CapabilityOperation.NONE else ()
                )
                or spec.allowed_delta_paths != intervention.target_paths
                or arm.execution_binding.manifest.manifest_hash != action.post_manifest.manifest_hash
                or not arm.validate()
            ):
                return False
        return self.experiment_hash == canonical_sha256(self.canonical_payload())


def _make_manifest_and_run(
    *,
    experiment_id: str,
    root_state: Mapping[str, Any],
    schema_version: str,
    campaign: AcquisitionCampaignManifest,
    benchmark: SealedCapabilityBenchmark,
    task_id: str,
    actions: Mapping[str, CapabilityStateAction],
    roles: Mapping[str, ArmRole],
    skills: Sequence[ProgramSkillArtifact],
    metadata_hashes: Mapping[str, str] | None = None,
) -> tuple[RootSnapshot, KernelResult, tuple[InterventionSpec, ...]]:
    """Use the unchanged M5 lifecycle to execute one registered experiment."""

    if set(actions) != set(roles):
        raise ValueError("genesis_m7_causal_arm_role_mismatch")
    adapter = SyntheticForkableStateAdapter(
        {
            "capability_runtime": "VERIFIED",
            "benchmark_binding": "VERIFIED",
            "environment": "VERIFIED",
        }
    )
    root = adapter.capture_root(root_state)
    budget = ComputeBudgetSpec(10, 1, 1, 0)
    oracle = CapabilityMeasurementOracle(
        benchmark=benchmark,
        task_id=task_id,
        inputs=tuple(root_state["inputs"]),
    )
    interventions = tuple(
        InterventionSpec(
            arm_id,
            schema_version,
            capability_intervention_type(action.operation),
            _CAPABILITY_PATHS if action.operation is not CapabilityOperation.NONE else (),
            action.action_hash,
            action.operation.value,
        )
        for arm_id, action in sorted(actions.items())
    )
    by_arm = {item.intervention_id: item for item in interventions}
    arm_specs = tuple(
        ArmSpec(
            arm_id,
            roles[arm_id],
            by_arm[arm_id].spec_hash,
            by_arm[arm_id].target_paths,
            tuple(adapter.required_surfaces),
            budget.budget_hash,
            RNGPolicy.ARM_DERIVED,
            (metadata_hashes or {}).get(
                arm_id,
                canonical_sha256(
                    {"experiment_id": experiment_id, "root_hash": root.root_hash, "action_hash": actions[arm_id].action_hash}
                ),
            ),
        )
        for arm_id in sorted(actions)
    )
    manifest = CausalExperimentManifest(
        experiment_id,
        schema_version,
        canonical_sha256({"campaign_hash": campaign.campaign_hash, "task_id": task_id, "experiment": experiment_id}),
        root.root_hash,
        campaign.cfi_policy_hash,
        arm_specs,
        budget.budget_hash,
        RNGPolicy.ARM_DERIVED,
        17,
        oracle.oracle_spec_hash,
        oracle.evaluator_version,
        tuple(adapter.required_surfaces),
    )
    runtime = CapabilityArmRuntime(
        specification=benchmark.specification,
        actions_by_spec_hash={by_arm[arm_id].spec_hash: action for arm_id, action in actions.items()},
        skills_by_hash={skill.skill_hash: skill for skill in skills},
    )
    result = GenericInterventionKernel().run(
        manifest, root, interventions, budget, adapter, oracle, runtime=runtime
    )
    return root, result, interventions


def _arm_closures(
    *,
    root: RootSnapshot,
    result: KernelResult,
    actions: Mapping[str, CapabilityStateAction],
    active_skills: Mapping[str, ProgramSkillArtifact | None],
    campaign: AcquisitionCampaignManifest,
    baseline: CapabilityManifest,
    benchmark: SealedCapabilityBenchmark,
    task_id: str,
    acquisition: AcquisitionResult,
    root_instance_id: str,
    arm_evidence_materializer: Callable[..., M7FederatedEvidence] = materialize_capability_arm_evidence,
) -> tuple[CausalArmClosure, ...]:
    closures: list[CausalArmClosure] = []
    for arm_id, action in sorted(actions.items()):
        binding = CapabilityExecutionBinding(
            "genesis-m7-causal-execution-binding-v1",
            arm_id,
            root_instance_id,
            root.root_hash,
            action.post_manifest,
            active_skills[arm_id],
        )
        evidence = {
            split: arm_evidence_materializer(
                campaign=campaign,
                baseline=baseline,
                benchmark=benchmark,
                task_id=task_id,
                result=acquisition,
                split=split,
                execution_binding=binding,
            )
            for split in _SCOPES
        }
        closures.append(CausalArmClosure(arm_id, root, binding, result, evidence[DatasetSplit.HIDDEN], evidence[DatasetSplit.TRANSFER]))
    return tuple(closures)


def _fresh_baseline(
    *,
    baseline: CapabilityManifest,
    promoted: ProgramSkillArtifact,
    campaign: AcquisitionCampaignManifest,
) -> tuple[CapabilityManifest, FreshBaselineReceipt]:
    fresh = CapabilityManifest(
        f"{campaign.campaign_id}-m7e2-fresh-g0",
        "genesis-m7-causal-v1",
        baseline.skill_hashes,
    )
    receipt = FreshBaselineReceipt(
        "genesis-m7-causal-fresh-baseline-v1",
        baseline.manifest_hash,
        fresh.manifest_hash,
        baseline.skill_hashes,
        fresh.skill_hashes,
        promoted.skill_hash,
        (),
    )
    return fresh, receipt


@dataclass(frozen=True, slots=True)
class CausalCapabilityAttribution:
    """Minimal derived certificate over C1 effect, C2 necessity and C3 sufficiency."""

    schema_version: str
    campaign_hash: str
    task_benchmark_binding_hash: str
    benchmark_manifest_hash: str
    task_id: str
    promoted_skill_hash: str
    placebo_commitment: PlaceboCommitment
    placebo_skill_hash: str
    fresh_baseline: FreshBaselineReceipt
    c1: CausalExperiment
    c2: CausalExperiment
    c3: CausalExperiment
    verdict: CausalAttributionStatus
    certificate_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "verdict", CausalAttributionStatus(self.verdict))
        derived = self.derived_status()
        if self.verdict is not derived:
            raise ValueError("genesis_m7_causal_verdict_not_derived")
        object.__setattr__(self, "certificate_hash", canonical_sha256(self.canonical_payload()))

    @property
    def treatment_effect(self) -> bool:
        return self.c1.arm("treatment").score > self.c1.arm("control").score

    @property
    def placebo_control(self) -> bool:
        return self.c1.arm("treatment").score > self.c1.arm("placebo").score

    @property
    def necessity(self) -> bool:
        return self.c2.arm("intact").score > self.c2.arm("ablation").score

    @property
    def sufficiency(self) -> bool:
        return self.c3.arm("transplant").score > self.c3.arm("fresh_control").score

    @property
    def exact_skill_identity(self) -> bool:
        return (
            self.c1.arm("treatment").execution_binding.active_skill_hash
            == self.c2.arm("intact").execution_binding.active_skill_hash
            == self.c3.arm("transplant").execution_binding.active_skill_hash
            == self.promoted_skill_hash
        )

    def derived_status(self) -> CausalAttributionStatus:
        try:
            experiments = (self.c1, self.c2, self.c3)
            if not all(experiment.validate() for experiment in experiments):
                return CausalAttributionStatus.NOT_PROVEN
            if not self.placebo_commitment.validate() or not self.fresh_baseline.validate():
                return CausalAttributionStatus.NOT_PROVEN
            cfi = tuple(experiment.result.cfi.status for experiment in experiments)
            if CFIStatus.FAIL in cfi:
                return CausalAttributionStatus.FAIL
            if CFIStatus.PASS not in cfi or any(status is not CFIStatus.PASS for status in cfi):
                return CausalAttributionStatus.NOT_PROVEN
            if (
                self.placebo_commitment.campaign_hash != self.campaign_hash
                or self.placebo_commitment.task_benchmark_binding_hash != self.task_benchmark_binding_hash
                or self.placebo_commitment.placebo_skill_hash != self.placebo_skill_hash
                or self.placebo_skill_hash == self.promoted_skill_hash
                or not self.exact_skill_identity
            ):
                return CausalAttributionStatus.FAIL
            if not (
                self.treatment_effect
                and self.placebo_control
                and self.necessity
                and self.sufficiency
            ):
                return CausalAttributionStatus.FAIL
            return CausalAttributionStatus.PASS
        except (TypeError, ValueError):
            return CausalAttributionStatus.NOT_PROVEN

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "campaign_hash": self.campaign_hash,
            "task_benchmark_binding_hash": self.task_benchmark_binding_hash,
            "benchmark_manifest_hash": self.benchmark_manifest_hash,
            "task_id": self.task_id,
            "promoted_skill_hash": self.promoted_skill_hash,
            "placebo_commitment": self.placebo_commitment.canonical_payload(),
            "placebo_skill_hash": self.placebo_skill_hash,
            "fresh_baseline": self.fresh_baseline.canonical_payload(),
            "c1": self.c1.canonical_payload(),
            "c2": self.c2.canonical_payload(),
            "c3": self.c3.canonical_payload(),
            "verdict": self.verdict.value,
        }

    def validate(self) -> bool:
        return (
            self.verdict is self.derived_status()
            and self.certificate_hash == canonical_sha256(self.canonical_payload())
        )


def materialize_causal_capability_attribution(
    *,
    campaign: AcquisitionCampaignManifest,
    baseline: CapabilityManifest,
    benchmark: SealedCapabilityBenchmark,
    task_id: str,
    acquisition: AcquisitionResult,
    placebo: ProgramSkillArtifact,
    placebo_commitment: PlaceboCommitment,
    arm_evidence_materializer: Callable[..., M7FederatedEvidence] = materialize_capability_arm_evidence,
) -> CausalCapabilityAttribution:
    """Execute and close C1/C2/C3 with the exact promoted artifact z.

    The function accepts a placebo commitment as an input before it runs any
    causal arm.  It performs no candidate search, no re-synthesis and no
    target-guided placebo selection.
    """

    promoted = acquisition.synthesis.selected_skill
    g1 = acquisition.g1_manifest
    binding = acquisition.task_benchmark_binding
    if (
        promoted is None
        or g1 is None
        or binding is None
        or not baseline.validate()
        or not benchmark.validate()
        or not validate_manifest_successor(g1, baseline, promoted)
        or not validate_program_skill(placebo, benchmark.specification)
        or placebo.skill_hash == promoted.skill_hash
        or placebo_commitment.campaign_hash != campaign.campaign_hash
        or placebo_commitment.task_benchmark_binding_hash != binding.binding_hash
        or placebo_commitment.placebo_skill_hash != placebo.skill_hash
        or not placebo_commitment.validate()
    ):
        raise ValueError("genesis_m7_causal_source_invalid")
    inputs = _inputs_for_scopes(benchmark, task_id)
    placebo_manifest = derive_successor_manifest(
        baseline,
        placebo,
        manifest_id=f"{campaign.campaign_id}-m7e2-placebo",
        schema_version="genesis-m7-causal-v1",
    )
    ablated = CapabilityManifest(
        f"{campaign.campaign_id}-m7e2-g1-minus-z",
        "genesis-m7-causal-v1",
        tuple(skill_hash for skill_hash in g1.skill_hashes if skill_hash != promoted.skill_hash),
    )
    fresh, fresh_receipt = _fresh_baseline(
        baseline=baseline, promoted=promoted, campaign=campaign
    )
    fresh_g1 = derive_successor_manifest(
        fresh,
        promoted,
        manifest_id=f"{campaign.campaign_id}-m7e2-fresh-plus-z",
        schema_version="genesis-m7-causal-v1",
    )

    c1_actions = {
        "control": CapabilityStateAction("control", "genesis-m7-causal-v1", CapabilityOperation.NONE, baseline, baseline),
        "treatment": CapabilityStateAction("treatment", "genesis-m7-causal-v1", CapabilityOperation.INSTALL, baseline, g1, promoted.skill_hash),
        "placebo": CapabilityStateAction("placebo", "genesis-m7-causal-v1", CapabilityOperation.INSTALL, baseline, placebo_manifest, placebo.skill_hash),
    }
    c1_root_instance = f"{campaign.campaign_hash}:c1:g0"
    c1_root, c1_result, c1_interventions = _make_manifest_and_run(
        experiment_id=f"m7e2-c1-{campaign.campaign_hash[:12]}",
        root_state=capability_root_state(manifest=baseline, execution_skill_hash=None, inputs=inputs, root_instance_id=c1_root_instance),
        schema_version="genesis-m7-causal-c1-v1",
        campaign=campaign,
        benchmark=benchmark,
        task_id=task_id,
        actions=c1_actions,
        roles={"control": ArmRole.CONTROL, "treatment": ArmRole.TREATMENT, "placebo": ArmRole.PLACEBO},
        skills=(promoted, placebo),
        metadata_hashes={"placebo": placebo_commitment.commitment_hash},
    )
    c1 = CausalExperiment(
        c1_result.manifest.experiment_id,
        c1_root,
        tuple(c1_actions.values()),
        c1_interventions,
        c1_result,
        _arm_closures(
            root=c1_root, result=c1_result, actions=c1_actions,
            active_skills={"control": None, "treatment": promoted, "placebo": placebo},
            campaign=campaign, baseline=baseline, benchmark=benchmark, task_id=task_id,
            acquisition=acquisition, root_instance_id=c1_root_instance,
            arm_evidence_materializer=arm_evidence_materializer,
        ),
    )

    c2_actions = {
        "intact": CapabilityStateAction("intact", "genesis-m7-causal-v1", CapabilityOperation.NONE, g1, g1),
        "ablation": CapabilityStateAction("ablation", "genesis-m7-causal-v1", CapabilityOperation.REMOVE, g1, ablated, promoted.skill_hash),
    }
    c2_root_instance = f"{campaign.campaign_hash}:c2:g1"
    c2_root, c2_result, c2_interventions = _make_manifest_and_run(
        experiment_id=f"m7e2-c2-{campaign.campaign_hash[:12]}",
        root_state=capability_root_state(manifest=g1, execution_skill_hash=promoted.skill_hash, inputs=inputs, root_instance_id=c2_root_instance),
        schema_version="genesis-m7-causal-c2-v1",
        campaign=campaign,
        benchmark=benchmark,
        task_id=task_id,
        actions=c2_actions,
        roles={"intact": ArmRole.CUSTOM, "ablation": ArmRole.ABLATION},
        skills=(promoted,),
    )
    c2 = CausalExperiment(
        c2_result.manifest.experiment_id,
        c2_root,
        tuple(c2_actions.values()),
        c2_interventions,
        c2_result,
        _arm_closures(
            root=c2_root, result=c2_result, actions=c2_actions,
            active_skills={"intact": promoted, "ablation": None},
            campaign=campaign, baseline=baseline, benchmark=benchmark, task_id=task_id,
            acquisition=acquisition, root_instance_id=c2_root_instance,
            arm_evidence_materializer=arm_evidence_materializer,
        ),
    )

    c3_actions = {
        "fresh_control": CapabilityStateAction("fresh_control", "genesis-m7-causal-v1", CapabilityOperation.NONE, fresh, fresh),
        "transplant": CapabilityStateAction("transplant", "genesis-m7-causal-v1", CapabilityOperation.INSTALL, fresh, fresh_g1, promoted.skill_hash),
    }
    c3_root_instance = f"{campaign.campaign_hash}:c3:fresh-g0"
    c3_root, c3_result, c3_interventions = _make_manifest_and_run(
        experiment_id=f"m7e2-c3-{campaign.campaign_hash[:12]}",
        root_state=capability_root_state(
            manifest=fresh, execution_skill_hash=None, inputs=inputs,
            root_instance_id=c3_root_instance, historical_skill_hashes=(),
        ),
        schema_version="genesis-m7-causal-c3-v1",
        campaign=campaign,
        benchmark=benchmark,
        task_id=task_id,
        actions=c3_actions,
        roles={"fresh_control": ArmRole.CONTROL, "transplant": ArmRole.CUSTOM},
        skills=(promoted,),
    )
    c3 = CausalExperiment(
        c3_result.manifest.experiment_id,
        c3_root,
        tuple(c3_actions.values()),
        c3_interventions,
        c3_result,
        _arm_closures(
            root=c3_root, result=c3_result, actions=c3_actions,
            active_skills={"fresh_control": None, "transplant": promoted},
            campaign=campaign, baseline=baseline, benchmark=benchmark, task_id=task_id,
            acquisition=acquisition, root_instance_id=c3_root_instance,
            arm_evidence_materializer=arm_evidence_materializer,
        ),
    )
    arguments = (
        "genesis-m7-causal-capability-attribution-v1",
        campaign.campaign_hash,
        binding.binding_hash,
        benchmark.manifest.manifest_hash,
        task_id,
        promoted.skill_hash,
        placebo_commitment,
        placebo.skill_hash,
        fresh_receipt,
        c1,
        c2,
        c3,
    )
    # The status is never supplied as an authority.  Trying the three finite
    # derived states lets the contract itself select the only admissible one.
    for status in CausalAttributionStatus:
        try:
            return CausalCapabilityAttribution(*arguments, status)
        except ValueError:
            continue
    raise ValueError("genesis_m7_causal_status_unrepresentable")
