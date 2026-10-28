"""Fresh-object semantic replay for the M7-E2 C1/C2/C3 attribution evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from lab.genesis.acquisition.benchmark import (
    BenchmarkManifest,
    SealedBenchmarkReplayWitness,
    _benchmark_replay_witness,
    _restore_benchmark_replay_witness,
)
from lab.genesis.acquisition.causal_experiments import (
    CausalAttributionStatus,
    CausalCapabilityAttribution,
    FreshBaselineReceipt,
    PlaceboCommitment,
)
from lab.genesis.acquisition.contracts import CapabilityManifest, ProgramSkillArtifact
from lab.genesis.acquisition.dsl import DSLSpecification
from lab.genesis.acquisition.m5_capability_runtime import (
    CapabilityArmRuntime,
    CapabilityExecutionBinding,
    CapabilityMeasurementOracle,
    CapabilityStateAction,
)
from lab.genesis.acquisition.replay import (
    _one_payload,
    replay_m7_capability_arm_evidence,
)
from lab.genesis.causal.cfi import CFIStatus
from lab.genesis.causal.fork import RootSnapshot, SyntheticForkableStateAdapter
from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.evidence.artifacts import ContentAddressedArtifactStore
from lab.genesis.evidence.trace_closure import TraceClosureManifest
from lab.genesis.evidence.trace_persistence import replay_m6_trace
from lab.genesis.intervention.kernel import GenericInterventionKernel, KernelResult
from lab.genesis.intervention.specs import (
    ArmSpec,
    CausalExperimentManifest,
    ComputeBudgetSpec,
    InterventionSpec,
)
from lab.genesis.verifiers.federation import FederationVerdict


_SCOPES = ("HIDDEN", "TRANSFER")


def _payload(item: Any) -> Any:
    return item.canonical_payload() if hasattr(item, "canonical_payload") else item


def _kernel_fingerprint(result: KernelResult) -> dict[str, Any]:
    """All M5 outputs whose equality proves semantic replay, not just a hash."""

    return {
        "root_hash": result.root.root_hash,
        "manifest_hash": result.manifest.manifest_hash,
        "cfi_hash": result.cfi.report_hash,
        "summary_hash": result.summary.summary_hash,
        "trace_hash": result.trace.trace_hash,
        "receipt_hashes": tuple((item.arm_id, item.receipt_hash) for item in result.receipts),
        "delta_hashes": tuple((item.arm_id, item.receipt_hash) for item in result.delta_receipts),
        "isolation_hashes": tuple((item.arm_id, item.receipt_hash) for item in result.isolation_receipts),
        "seal_hashes": tuple((item.arm_id, item.seal_hash) for item in result.seals),
        "oracle_hashes": tuple((item.arm_id, item.receipt_hash) for item in result.oracles),
        "budget_hashes": tuple((item.arm_id, item.receipt_hash) for item in result.budgets),
    }


@dataclass(frozen=True, slots=True)
class CausalReplayPlan:
    experiment_id: str
    root: RootSnapshot
    manifest: CausalExperimentManifest
    interventions: tuple[InterventionSpec, ...]
    actions: tuple[CapabilityStateAction, ...]
    execution_bindings: tuple[CapabilityExecutionBinding, ...]
    budget: ComputeBudgetSpec
    expected_kernel: Mapping[str, Any]
    certificate_experiment: Mapping[str, Any]
    plan_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "interventions", tuple(sorted(self.interventions, key=lambda item: item.intervention_id)))
        object.__setattr__(self, "actions", tuple(sorted(self.actions, key=lambda item: item.action_id)))
        object.__setattr__(self, "execution_bindings", tuple(sorted(self.execution_bindings, key=lambda item: item.arm_id)))
        object.__setattr__(self, "expected_kernel", dict(self.expected_kernel))
        object.__setattr__(self, "certificate_experiment", dict(self.certificate_experiment))
        if (
            not self.experiment_id
            or self.root.root_hash != self.manifest.root_snapshot_hash
            or {item.intervention_id for item in self.interventions} != {item.arm_id for item in self.manifest.arm_specs}
            or {item.action_id for item in self.actions} != {item.arm_id for item in self.manifest.arm_specs}
            or {item.arm_id for item in self.execution_bindings} != {item.arm_id for item in self.manifest.arm_specs}
        ):
            raise ValueError("genesis_m7_causal_replay_plan_invalid")
        object.__setattr__(self, "plan_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "root": self.root.canonical_payload(),
            "manifest": self.manifest.canonical_payload(),
            "interventions": tuple(item.canonical_payload() for item in self.interventions),
            "actions": tuple(item.canonical_payload() for item in self.actions),
            "execution_bindings": tuple(item.canonical_payload() for item in self.execution_bindings),
            "budget": self.budget.canonical_payload(),
            "expected_kernel": self.expected_kernel,
            "certificate_experiment": self.certificate_experiment,
        }

    def validate(self) -> bool:
        return self.plan_hash == canonical_sha256(self.canonical_payload())


@dataclass(frozen=True, slots=True)
class CausalEvidenceManifest:
    """An index over M5/M6 evidence; it never issues causal authority itself."""

    schema_version: str
    certificate_payload: Mapping[str, Any]
    certificate_hash: str
    dsl: DSLSpecification
    benchmark_manifest: BenchmarkManifest
    benchmark_witness: SealedBenchmarkReplayWitness
    capability_manifests: tuple[CapabilityManifest, ...]
    skills: tuple[ProgramSkillArtifact, ...]
    plans: tuple[CausalReplayPlan, ...]
    arm_trace_closures: Mapping[str, str]
    manifest_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "certificate_payload", dict(self.certificate_payload))
        object.__setattr__(self, "capability_manifests", tuple(sorted(self.capability_manifests, key=lambda item: item.manifest_hash)))
        object.__setattr__(self, "skills", tuple(sorted(self.skills, key=lambda item: item.skill_hash)))
        object.__setattr__(self, "plans", tuple(sorted(self.plans, key=lambda item: item.experiment_id)))
        object.__setattr__(self, "arm_trace_closures", dict(sorted(self.arm_trace_closures.items())))
        if (
            not self.schema_version
            or canonical_sha256(self.certificate_payload) != self.certificate_hash
            or not self.dsl.validate()
            or not self.benchmark_manifest.validate()
            or not self.benchmark_witness.validate()
            or self.benchmark_manifest.dsl_hash != self.dsl.dsl_hash
            or self.benchmark_witness.benchmark_manifest_hash != self.benchmark_manifest.manifest_hash
            or len({item.manifest_hash for item in self.capability_manifests}) != len(self.capability_manifests)
            or not all(item.validate() for item in self.capability_manifests)
            or len({item.skill_hash for item in self.skills}) != len(self.skills)
            or not all(item.validate() for item in self.skills)
            or {item.experiment_id for item in self.plans} != {"c1", "c2", "c3"}
            or not all(item.validate() for item in self.plans)
            or len(self.arm_trace_closures) != 14
            or any(not key or len(value) != 64 for key, value in self.arm_trace_closures.items())
        ):
            raise ValueError("genesis_m7_causal_evidence_manifest_invalid")
        object.__setattr__(self, "manifest_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "certificate_payload": self.certificate_payload,
            "certificate_hash": self.certificate_hash,
            "dsl": self.dsl.canonical_payload(),
            "benchmark_manifest": self.benchmark_manifest.canonical_payload(),
            "benchmark_witness": self.benchmark_witness.canonical_payload(),
            "capability_manifests": tuple(item.canonical_payload() for item in self.capability_manifests),
            "skills": tuple(item.canonical_payload() for item in self.skills),
            "plans": tuple(item.canonical_payload() for item in self.plans),
            "arm_trace_closures": self.arm_trace_closures,
        }

    def validate(self) -> bool:
        try:
            return self.manifest_hash == canonical_sha256(self.canonical_payload())
        except (TypeError, ValueError):
            return False


@dataclass(frozen=True, slots=True)
class PersistedCausalEvidence:
    manifest_hash: str
    manifest: CausalEvidenceManifest


@dataclass(frozen=True, slots=True)
class M7CausalReplay:
    admitted: bool
    reasons: tuple[str, ...]
    manifest_hash: str


def _plan(experiment: Any, label: str) -> CausalReplayPlan:
    budget = ComputeBudgetSpec(10, 1, 1, 0)
    if budget.budget_hash != experiment.result.manifest.budget_spec_hash:
        raise ValueError("genesis_m7_causal_replay_budget_unknown")
    return CausalReplayPlan(
        label,
        experiment.root,
        experiment.result.manifest,
        experiment.interventions,
        experiment.actions,
        tuple(arm.execution_binding for arm in experiment.arms),
        budget,
        _kernel_fingerprint(experiment.result),
        experiment.canonical_payload(),
    )


def persist_causal_capability_attribution(
    store: ContentAddressedArtifactStore,
    attribution: CausalCapabilityAttribution,
    *,
    benchmark: Any,
) -> PersistedCausalEvidence:
    """Persist seven arm closures plus enough source to rerun all three M5 roots."""

    if not attribution.validate() or attribution.verdict is not CausalAttributionStatus.PASS:
        raise ValueError("genesis_m7_causal_persistence_source_invalid")
    traces: dict[str, str] = {}
    manifests: dict[str, CapabilityManifest] = {}
    skills: dict[str, ProgramSkillArtifact] = {}
    for label, experiment in (("c1", attribution.c1), ("c2", attribution.c2), ("c3", attribution.c3)):
        for action in experiment.actions:
            manifests[action.pre_manifest.manifest_hash] = action.pre_manifest
            manifests[action.post_manifest.manifest_hash] = action.post_manifest
        for arm in experiment.arms:
            manifests[arm.execution_binding.manifest.manifest_hash] = arm.execution_binding.manifest
            if arm.execution_binding.active_skill is not None:
                skills[arm.execution_binding.active_skill.skill_hash] = arm.execution_binding.active_skill
            for split, evidence in (("HIDDEN", arm.hidden), ("TRANSFER", arm.transfer)):
                persisted = evidence.persist_trace(store)
                traces[f"{label}:{arm.arm_id}:{split}"] = persisted.closure_hash
    witness = _benchmark_replay_witness(benchmark)
    manifest = CausalEvidenceManifest(
        "genesis-m7-causal-evidence-manifest-v1",
        attribution.canonical_payload(),
        attribution.certificate_hash,
        benchmark.specification,
        benchmark.manifest,
        witness,
        tuple(manifests.values()),
        tuple(skills.values()),
        (_plan(attribution.c1, "c1"), _plan(attribution.c2, "c2"), _plan(attribution.c3, "c3")),
        traces,
    )
    manifest_hash = store.put(manifest.canonical_payload())
    if manifest_hash != manifest.manifest_hash:
        raise ValueError("genesis_m7_causal_persistence_identity_invalid")
    return PersistedCausalEvidence(manifest_hash, manifest)


def _restore_manifest(payload: Mapping[str, Any]) -> CausalEvidenceManifest:
    dsl = DSLSpecification.from_payload(payload["dsl"])
    benchmark_manifest = BenchmarkManifest.from_payload(payload["benchmark_manifest"])
    witness = SealedBenchmarkReplayWitness.from_payload(payload["benchmark_witness"])
    manifests = tuple(CapabilityManifest.from_payload(item) for item in payload["capability_manifests"])
    manifest_by_hash = {item.manifest_hash: item for item in manifests}
    skills = tuple(ProgramSkillArtifact.from_payload(item) for item in payload["skills"])
    skill_by_hash = {item.skill_hash: item for item in skills}
    plans: list[CausalReplayPlan] = []
    for raw in payload["plans"]:
        root = RootSnapshot(**raw["root"])
        manifest_values = dict(raw["manifest"])
        manifest_values["arm_specs"] = tuple(ArmSpec(**item) for item in manifest_values["arm_specs"])
        m5_manifest = CausalExperimentManifest(**manifest_values)
        actions = tuple(
            CapabilityStateAction.from_payload(item, manifests_by_hash=manifest_by_hash)
            for item in raw["actions"]
        )
        bindings: list[CapabilityExecutionBinding] = []
        for item in raw["execution_bindings"]:
            state_manifest = manifest_by_hash.get(item["manifest_hash"])
            active_hash = item.get("active_skill_hash")
            if state_manifest is None or (active_hash is not None and active_hash not in skill_by_hash):
                raise ValueError("genesis_m7_causal_replay_binding_source_missing")
            bindings.append(
                CapabilityExecutionBinding.from_payload(
                    item, manifest=state_manifest, active_skill=skill_by_hash.get(active_hash)
                )
            )
        plans.append(
            CausalReplayPlan(
                raw["experiment_id"],
                root,
                m5_manifest,
                tuple(InterventionSpec(**item) for item in raw["interventions"]),
                actions,
                tuple(bindings),
                ComputeBudgetSpec(**raw["budget"]),
                raw["expected_kernel"],
                raw["certificate_experiment"],
            )
        )
    return CausalEvidenceManifest(
        payload["schema_version"],
        payload["certificate_payload"],
        payload["certificate_hash"],
        dsl,
        benchmark_manifest,
        witness,
        manifests,
        skills,
        tuple(plans),
        payload["arm_trace_closures"],
    )


def _rerun(
    plan: CausalReplayPlan,
    benchmark: Any,
    task_id: str,
    skills: Mapping[str, ProgramSkillArtifact],
) -> KernelResult:
    adapter = SyntheticForkableStateAdapter({surface: "VERIFIED" for surface in plan.manifest.required_surfaces})
    oracle = CapabilityMeasurementOracle(
        benchmark=benchmark,
        task_id=task_id,
        inputs=tuple(plan.root.state["inputs"]),
    )
    if (
        plan.manifest.root_snapshot_hash != plan.root.root_hash
        or plan.manifest.oracle_spec_hash != oracle.oracle_spec_hash
        or plan.manifest.evaluator_version != oracle.evaluator_version
        or plan.manifest.budget_spec_hash != plan.budget.budget_hash
    ):
        raise ValueError("genesis_m7_causal_replay_m5_binding_invalid")
    intervention_by_arm = {item.intervention_id: item for item in plan.interventions}
    actions_by_spec = {
        intervention_by_arm[action.action_id].spec_hash: action for action in plan.actions
    }
    runtime = CapabilityArmRuntime(
        specification=benchmark.specification,
        actions_by_spec_hash=actions_by_spec,
        skills_by_hash=skills,
    )
    return GenericInterventionKernel().run(
        plan.manifest,
        plan.root,
        plan.interventions,
        plan.budget,
        adapter,
        oracle,
        runtime=runtime,
    )


def _trace_binding_matches(
    store: ContentAddressedArtifactStore,
    trace_hash: str,
    binding: CapabilityExecutionBinding,
) -> bool:
    closure = TraceClosureManifest.from_payload(store.get(trace_hash))
    payload = _one_payload(store, closure, "m7_causal_execution_binding")
    return canonical_sha256(payload) == canonical_sha256(binding.canonical_payload())


def _certificate_gate(
    manifest: CausalEvidenceManifest,
    results: Mapping[str, KernelResult],
) -> CausalAttributionStatus:
    """Re-derive the small M7 causal formula from replayed, not stored, outcomes."""

    try:
        certificate = manifest.certificate_payload
        if canonical_sha256(certificate) != manifest.certificate_hash:
            return CausalAttributionStatus.NOT_PROVEN
        placebo = PlaceboCommitment(**certificate["placebo_commitment"])
        fresh = FreshBaselineReceipt(**certificate["fresh_baseline"])
        c1, c2, c3 = (results[label] for label in ("c1", "c2", "c3"))
        statuses = (c1.cfi.status, c2.cfi.status, c3.cfi.status)
        if CFIStatus.FAIL in statuses:
            return CausalAttributionStatus.FAIL
        if any(status is not CFIStatus.PASS for status in statuses):
            return CausalAttributionStatus.NOT_PROVEN
        score = lambda result, arm: next(item.score for item in result.receipts if item.arm_id == arm)
        plans = {plan.experiment_id: plan for plan in manifest.plans}
        binding = lambda experiment, arm: next(
            item for item in plans[experiment].execution_bindings if item.arm_id == arm
        )
        promoted = certificate["promoted_skill_hash"]
        if (
            certificate["verdict"] not in {item.value for item in CausalAttributionStatus}
            or placebo.campaign_hash != certificate["campaign_hash"]
            or placebo.task_benchmark_binding_hash != certificate["task_benchmark_binding_hash"]
            or placebo.placebo_skill_hash != certificate["placebo_skill_hash"]
            or certificate["placebo_skill_hash"] == promoted
            or binding("c1", "treatment").active_skill_hash != promoted
            or binding("c2", "intact").active_skill_hash != promoted
            or binding("c3", "transplant").active_skill_hash != promoted
            or binding("c3", "fresh_control").manifest.manifest_hash != fresh.fresh_manifest_hash
            or binding("c3", "fresh_control").active_skill_hash is not None
            or promoted in tuple(c3.root.state["capabilities"]["historical_skill_hashes"])
        ):
            return CausalAttributionStatus.FAIL
        actual = (
            CausalAttributionStatus.PASS
            if (
                score(c1, "treatment") > score(c1, "control")
                and score(c1, "treatment") > score(c1, "placebo")
                and score(c2, "intact") > score(c2, "ablation")
                and score(c3, "transplant") > score(c3, "fresh_control")
            )
            else CausalAttributionStatus.FAIL
        )
        return actual
    except (KeyError, StopIteration, TypeError, ValueError):
        return CausalAttributionStatus.NOT_PROVEN


def _certificate_static_bindings_valid(manifest: CausalEvidenceManifest) -> bool:
    """Reject re-sealed role/identity substitutions before expensive replay."""

    try:
        certificate = manifest.certificate_payload
        plans = {plan.experiment_id: plan for plan in manifest.plans}
        if any(plans[label].certificate_experiment != certificate[label] for label in plans):
            return False
        placebo = PlaceboCommitment(**certificate["placebo_commitment"])
        fresh = FreshBaselineReceipt(**certificate["fresh_baseline"])
        binding = lambda experiment, arm: next(
            item for item in plans[experiment].execution_bindings if item.arm_id == arm
        )
        promoted = certificate["promoted_skill_hash"]
        return (
            placebo.validate()
            and fresh.validate()
            and placebo.campaign_hash == certificate["campaign_hash"]
            and placebo.task_benchmark_binding_hash == certificate["task_benchmark_binding_hash"]
            and placebo.placebo_skill_hash == certificate["placebo_skill_hash"]
            and certificate["placebo_skill_hash"] != promoted
            and binding("c1", "treatment").active_skill_hash == promoted
            and binding("c2", "intact").active_skill_hash == promoted
            and binding("c3", "transplant").active_skill_hash == promoted
            and binding("c1", "placebo").active_skill_hash == certificate["placebo_skill_hash"]
            and binding("c2", "ablation").active_skill_hash is None
            and binding("c3", "fresh_control").active_skill_hash is None
            and binding("c3", "fresh_control").manifest.manifest_hash == fresh.fresh_manifest_hash
        )
    except (KeyError, StopIteration, TypeError, ValueError):
        return False


def replay_causal_capability_attribution(
    store: ContentAddressedArtifactStore,
    manifest_hash: str,
    arm_evidence_replayer: Callable[[ContentAddressedArtifactStore, str], Any] = replay_m7_capability_arm_evidence,
) -> M7CausalReplay:
    """Replay all C1/C2/C3 roots and all fourteen M6 scope closures from CAS."""

    try:
        raw = store.get(manifest_hash)
        manifest = _restore_manifest(raw)
        if manifest.manifest_hash != manifest_hash or not manifest.validate():
            return M7CausalReplay(False, ("genesis_m7_causal_replay_manifest_invalid",), manifest_hash)
        if not _certificate_static_bindings_valid(manifest):
            return M7CausalReplay(False, ("genesis_m7_causal_replay_certificate_binding_invalid",), manifest_hash)
        benchmark = _restore_benchmark_replay_witness(
            specification=manifest.dsl,
            manifest=manifest.benchmark_manifest,
            witness=manifest.benchmark_witness,
        )
        task_id = manifest.certificate_payload["task_id"]
        skills = {item.skill_hash: item for item in manifest.skills}
        results: dict[str, KernelResult] = {}
        for plan in manifest.plans:
            result = _rerun(plan, benchmark, task_id, skills)
            if canonical_sha256(_kernel_fingerprint(result)) != canonical_sha256(plan.expected_kernel):
                return M7CausalReplay(
                    False,
                    (f"genesis_m7_causal_replay_m5_mismatch:{plan.experiment_id}",),
                    manifest_hash,
                )
            if plan.certificate_experiment != manifest.certificate_payload[plan.experiment_id]:
                return M7CausalReplay(
                    False,
                    (f"genesis_m7_causal_replay_certificate_plan_mismatch:{plan.experiment_id}",),
                    manifest_hash,
                )
            results[plan.experiment_id] = result
        for plan in manifest.plans:
            for binding in plan.execution_bindings:
                for split in _SCOPES:
                    key = f"{plan.experiment_id}:{binding.arm_id}:{split}"
                    trace_hash = manifest.arm_trace_closures.get(key)
                    if trace_hash is None or not _trace_binding_matches(store, trace_hash, binding):
                        return M7CausalReplay(
                            False,
                            (f"genesis_m7_causal_replay_arm_binding_mismatch:{key}",),
                            manifest_hash,
                        )
                    m6 = replay_m6_trace(store, trace_hash)
                    arm = arm_evidence_replayer(store, trace_hash)
                    expected = (
                        FederationVerdict.PASS
                        if binding.active_skill_hash == manifest.certificate_payload["promoted_skill_hash"]
                        else FederationVerdict.FAIL
                    )
                    certificate_arm = next(
                        (item for item in plan.certificate_experiment["arms"] if item["arm_id"] == binding.arm_id),
                        None,
                    )
                    receipt_key = "hidden_adjudication_hash" if split == "HIDDEN" else "transfer_adjudication_hash"
                    if (
                        certificate_arm is None
                        or not arm.admitted
                        or not m6.admitted
                        or m6.adjudication is None
                        or m6.adjudication.verdict is not expected
                        or m6.adjudication.receipt_hash != certificate_arm[receipt_key]
                    ):
                        return M7CausalReplay(
                            False,
                            (f"genesis_m7_causal_replay_arm_closure_invalid:{key}",),
                            manifest_hash,
                        )
        status = _certificate_gate(manifest, results)
        if status.value != manifest.certificate_payload["verdict"]:
            return M7CausalReplay(
                False,
                ("genesis_m7_causal_replay_verdict_mismatch",),
                manifest_hash,
            )
        return M7CausalReplay(True, (), manifest_hash)
    except (KeyError, TypeError, ValueError):
        return M7CausalReplay(False, ("genesis_m7_causal_replay_historical_material_invalid",), manifest_hash)
