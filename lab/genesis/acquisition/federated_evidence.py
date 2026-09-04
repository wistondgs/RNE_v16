"""Materialize M7 skill measurements through the real M6 evidence pipeline.

This module intentionally does not add a second verifier, trace format, or
adjudication rule.  It converts a promoted, benchmark-bound M7 program into a
finite-domain differential claim and lets M6 route, execute, bundle,
adjudicate, and persist it.  Differential authority remains supporting: this
is exact evidence over its declared finite domain, not a sovereign claim.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from lab.genesis.acquisition.benchmark import (
    DatasetSplit,
    SealedCapabilityBenchmark,
    TaskBenchmarkBinding,
    _benchmark_replay_witness,
    validate_task_benchmark_binding,
)
from lab.genesis.acquisition.campaign import (
    AcquisitionResult,
    PriorInsufficiencyReceipt,
)
from lab.genesis.acquisition.contracts import (
    AcquisitionCampaignManifest,
    CapabilityManifest,
    ProgramSkillArtifact,
    PromotionStatus,
    validate_candidate_commitment,
    validate_manifest_successor,
    validate_promotion_receipt,
    validate_synthesis_receipt,
)
from lab.genesis.acquisition.dsl import evaluate_expression, validate_program_skill
from lab.genesis.acquisition.synthesis import DeterministicProgramSynthesizer
from lab.genesis.contracts.claims import ChangeClass, ClaimType, TypedClaim
from lab.genesis.contracts.serialization import canonical_sha256, freeze
from lab.genesis.contracts.verification import VerificationObligation, VerificationPlan
from lab.genesis.evidence.artifacts import ContentAddressedArtifactStore, is_artifact_hash
from lab.genesis.evidence.trace_persistence import (
    PersistedTrace,
    persist_m6_trace,
    stage_m6_trace,
)
from lab.genesis.verifiers.adjudication import (
    RequirementAdjudicationReceipt,
    adjudicate_requirement,
)
from lab.genesis.verifiers.bindings import canonical_execution_context_hash
from lab.genesis.verifiers.descriptor import (
    AuthorityClass,
    VerifierDescriptor,
    VerifierKind,
    VerifierSovereignty,
)
from lab.genesis.verifiers.differential import DifferentialVerifier
from lab.genesis.verifiers.evidence import (
    ExecutionRecordMaterial,
    RequirementEvidenceBundle,
    build_requirement_evidence_bundle,
)
from lab.genesis.verifiers.execution import (
    ExecutionAdmissionStatus,
    ExecutionSubjectBinding,
    PlanBoundExecutionKernel,
    PlannedExecutionRequest,
)
from lab.genesis.verifiers.federation import (
    FederatedVerificationRequirement,
    IntegrityStatus,
    VerifierDependencyGraph,
    VerifierIntegrityReceipt,
    VerifierRegistry,
)
from lab.genesis.verifiers.plan import FederationPlan
from lab.genesis.verifiers.references import (
    QualifiedReferenceBinding,
    ReferenceDescriptor,
    ReferenceQualificationPolicy,
    ReferenceQualificationReceipt,
    ReferenceRegistry,
    qualify_reference,
)
from lab.genesis.verifiers.reliability import VerifierReliabilityProfile
from lab.genesis.verifiers.reliability_campaign import (
    ReliabilityCampaignReceipt,
    ReliabilityCase,
    ReliabilityCaseClass,
    VerifierReliabilityCampaign,
)
from lab.genesis.verifiers.router import VerifierRouter


_CERTIFIABLE_SPLITS = frozenset({DatasetSplit.HIDDEN, DatasetSplit.TRANSFER})


def _require_hash(value: str, reason: str) -> None:
    if not isinstance(value, str) or not is_artifact_hash(value):
        raise ValueError(reason)


def _integer_domain(domain: Mapping[str, Any]) -> tuple[int, int]:
    if set(domain) != {"kind", "min", "max"} or domain.get("kind") != "integer_range":
        raise ValueError("genesis_m7_evidence_domain_invalid")
    lower, upper = domain["min"], domain["max"]
    if (
        not isinstance(lower, int)
        or isinstance(lower, bool)
        or not isinstance(upper, int)
        or isinstance(upper, bool)
        or lower > upper
    ):
        raise ValueError("genesis_m7_evidence_domain_invalid")
    return lower, upper


@dataclass(frozen=True, slots=True)
class ReferenceTargetCommitment:
    """A non-revealing commitment to the benchmark-side trusted target."""

    schema_version: str
    benchmark_manifest_hash: str
    task_id: str
    target_program_hash: str
    generator_implementation_hash: str
    seed_commitment_hash: str
    commitment_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.schema_version or not self.task_id:
            raise ValueError("genesis_m7_reference_target_identity_invalid")
        for value in (
            self.benchmark_manifest_hash,
            self.target_program_hash,
            self.generator_implementation_hash,
            self.seed_commitment_hash,
        ):
            _require_hash(value, "genesis_m7_reference_target_hash_invalid")
        object.__setattr__(self, "commitment_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, str]:
        return {
            "schema_version": self.schema_version,
            "benchmark_manifest_hash": self.benchmark_manifest_hash,
            "task_id": self.task_id,
            "target_program_hash": self.target_program_hash,
            "generator_implementation_hash": self.generator_implementation_hash,
            "seed_commitment_hash": self.seed_commitment_hash,
        }

    def validate(self) -> bool:
        return self.commitment_hash == canonical_sha256(self.canonical_payload())


@dataclass(frozen=True, slots=True)
class FederatedMeasurementScope:
    """The M7 observation domain which an M6 differential record certifies."""

    schema_version: str
    benchmark_manifest_hash: str
    task_benchmark_binding_hash: str
    task_id: str
    split: DatasetSplit
    split_commitment_hash: str
    candidate_skill_hash: str
    reference_target_commitment_hash: str
    domain: Mapping[str, Any]
    scope_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "split", DatasetSplit(self.split))
        if not self.schema_version or not self.task_id or self.split not in _CERTIFIABLE_SPLITS:
            raise ValueError("genesis_m7_measurement_scope_invalid")
        for value in (
            self.benchmark_manifest_hash,
            self.task_benchmark_binding_hash,
            self.split_commitment_hash,
            self.candidate_skill_hash,
            self.reference_target_commitment_hash,
        ):
            _require_hash(value, "genesis_m7_measurement_scope_hash_invalid")
        object.__setattr__(self, "domain", freeze(self.domain))
        _integer_domain(self.domain)
        object.__setattr__(self, "scope_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "benchmark_manifest_hash": self.benchmark_manifest_hash,
            "task_benchmark_binding_hash": self.task_benchmark_binding_hash,
            "task_id": self.task_id,
            "split": self.split.value,
            "split_commitment_hash": self.split_commitment_hash,
            "candidate_skill_hash": self.candidate_skill_hash,
            "reference_target_commitment_hash": self.reference_target_commitment_hash,
            "domain": self.domain,
        }

    def validate(self) -> bool:
        try:
            _integer_domain(self.domain)
            return self.scope_hash == canonical_sha256(self.canonical_payload())
        except (TypeError, ValueError):
            return False


@dataclass(frozen=True, slots=True)
class M7FederatedEvidence:
    """Validated M7 source chain plus the actual M6 material it produced."""

    scope: FederatedMeasurementScope
    task_binding: TaskBenchmarkBinding
    target_commitment: ReferenceTargetCommitment
    claim: TypedClaim
    descriptor: VerifierDescriptor
    campaign: ReliabilityCampaignReceipt
    profile: VerifierReliabilityProfile
    reference_descriptor: ReferenceDescriptor
    qualification_policy: ReferenceQualificationPolicy
    qualification_receipt: ReferenceQualificationReceipt
    reference_binding: QualifiedReferenceBinding
    router: VerifierRouter
    federation_plan: FederationPlan
    subject: ExecutionSubjectBinding
    material: ExecutionRecordMaterial
    bundle: RequirementEvidenceBundle
    adjudication: RequirementAdjudicationReceipt
    historical_artifacts: Mapping[str, tuple[Any, ...]]

    @property
    def records(self) -> tuple[ExecutionRecordMaterial, ...]:
        return (self.material,)

    def stage_trace(self, *, historical_artifacts: Mapping[str, tuple[Any, ...]] | None = None) -> Any:
        return stage_m6_trace(
            router=self.router,
            federation_plan=self.federation_plan,
            subject=self.subject,
            records=self.records,
            bundle=self.bundle,
            adjudication=self.adjudication,
            historical_artifacts=_merge_artifacts(self.historical_artifacts, historical_artifacts),
        )

    def persist_trace(
        self,
        store: ContentAddressedArtifactStore,
        *,
        historical_artifacts: Mapping[str, tuple[Any, ...]] | None = None,
    ) -> PersistedTrace:
        return persist_m6_trace(
            store,
            router=self.router,
            federation_plan=self.federation_plan,
            subject=self.subject,
            records=self.records,
            bundle=self.bundle,
            adjudication=self.adjudication,
            historical_artifacts=_merge_artifacts(self.historical_artifacts, historical_artifacts),
        )


def _merge_artifacts(
    base: Mapping[str, tuple[Any, ...]], extra: Mapping[str, tuple[Any, ...]] | None,
) -> Mapping[str, tuple[Any, ...]]:
    merged = {role: tuple(items) for role, items in base.items()}
    for role, items in (extra or {}).items():
        merged[role] = (*merged.get(role, ()), *tuple(items))
    return merged


def _task_descriptor(benchmark: SealedCapabilityBenchmark, task_id: str) -> Any:
    return next((item for item in benchmark.manifest.tasks if item.task_id == task_id), None)


def _trusted_target_commitment(
    benchmark: SealedCapabilityBenchmark, task_id: str,
) -> ReferenceTargetCommitment:
    task = benchmark._tasks.get(task_id)  # Trusted evaluator boundary; never learner-facing.
    if task is None:
        raise ValueError("genesis_m7_evidence_task_missing")
    return ReferenceTargetCommitment(
        schema_version="genesis-m7-reference-target-v1",
        benchmark_manifest_hash=benchmark.manifest.manifest_hash,
        task_id=task_id,
        target_program_hash=canonical_sha256(task.target_ast),
        generator_implementation_hash=benchmark.manifest.generator_implementation_hash,
        seed_commitment_hash=benchmark.manifest.seed_commitment_hash,
    )


def _validate_target_commitment(
    commitment: ReferenceTargetCommitment,
    benchmark: SealedCapabilityBenchmark,
) -> bool:
    task = benchmark._tasks.get(commitment.task_id)
    return (
        commitment.validate()
        and benchmark.validate()
        and task is not None
        and commitment.benchmark_manifest_hash == benchmark.manifest.manifest_hash
        and commitment.target_program_hash == canonical_sha256(task.target_ast)
        and commitment.generator_implementation_hash
        == benchmark.manifest.generator_implementation_hash
        and commitment.seed_commitment_hash == benchmark.manifest.seed_commitment_hash
    )


def _scope_for(
    *,
    benchmark: SealedCapabilityBenchmark,
    binding: TaskBenchmarkBinding,
    candidate: ProgramSkillArtifact,
    target: ReferenceTargetCommitment,
    split: DatasetSplit,
) -> FederatedMeasurementScope:
    task = benchmark._tasks[binding.task_id]
    values = tuple(example.input_value for example in task.datasets[split])
    domain = {"kind": "integer_range", "min": min(values), "max": max(values)}
    return FederatedMeasurementScope(
        schema_version="genesis-m7-federated-measurement-scope-v1",
        benchmark_manifest_hash=benchmark.manifest.manifest_hash,
        task_benchmark_binding_hash=binding.binding_hash,
        task_id=binding.task_id,
        split=split,
        split_commitment_hash=binding.split_commitment_hashes[split.value],
        candidate_skill_hash=candidate.skill_hash,
        reference_target_commitment_hash=target.commitment_hash,
        domain=domain,
    )


def _validate_scope(
    scope: FederatedMeasurementScope,
    *,
    benchmark: SealedCapabilityBenchmark,
    binding: TaskBenchmarkBinding,
    candidate: ProgramSkillArtifact,
    target: ReferenceTargetCommitment,
) -> bool:
    descriptor = _task_descriptor(benchmark, scope.task_id)
    if (
        not scope.validate()
        or descriptor is None
        or scope.benchmark_manifest_hash != benchmark.manifest.manifest_hash
        or scope.task_benchmark_binding_hash != binding.binding_hash
        or scope.task_id != binding.task_id
        or scope.candidate_skill_hash != candidate.skill_hash
        or scope.reference_target_commitment_hash != target.commitment_hash
        or scope.split_commitment_hash != descriptor.split_commitments[scope.split.value]
    ):
        return False
    lower, upper = _integer_domain(scope.domain)
    inputs = tuple(example.input_value for example in benchmark._tasks[scope.task_id].datasets[scope.split])
    return min(inputs) >= lower and max(inputs) <= upper


def _differential_descriptor() -> VerifierDescriptor:
    identity = DifferentialVerifier.implementation_identity()
    return VerifierDescriptor(
        verifier_id=DifferentialVerifier.verifier_id,
        schema_version="genesis-m7-federated-evidence-v1",
        verifier_version=DifferentialVerifier.verifier_version,
        verifier_kind=VerifierKind.DIFFERENTIAL,
        authority_class=AuthorityClass.DIFFERENTIAL,
        sovereignty=VerifierSovereignty.SUPPORTING,
        supported_claim_types=(ClaimType.EXACT_FUNCTION.value,),
        supported_obligation_kinds=("differential",),
        implementation_identity_hash=identity.identity_hash,
        dependency_manifest_hash=canonical_sha256(
            {"component": "m7-finite-dsl-differential-adapter-v1"}
        ),
        cost_class="finite-exhaustive",
        deterministic=True,
    )


def _context(
    claim: TypedClaim,
    candidate_identity_hash: str,
    reference_identity_hash: str,
    *,
    plan_hash: str,
    snapshot_hash: str,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "claim": claim,
        "candidate_identity_hash": candidate_identity_hash,
        "reference_identity_hash": reference_identity_hash,
        "plan_hash": plan_hash,
        "snapshot_hash": snapshot_hash,
    }
    value["context_hash"] = canonical_execution_context_hash(
        claim.claim_hash, candidate_identity_hash, value
    )
    return value


def _reliability_material(
    *,
    claim: TypedClaim,
    descriptor: VerifierDescriptor,
    reference: Any,
    reference_identity_hash: str,
    provenance_hash: str,
) -> tuple[ReliabilityCampaignReceipt, VerifierReliabilityProfile]:
    calibration_plan_hash = canonical_sha256(
        {"m7_calibration": descriptor.descriptor_hash, "claim": claim.claim_hash}
    )
    snapshot_hash = canonical_sha256(
        {"m7_calibration_reference": reference_identity_hash}
    )

    def matching(value: int) -> Any:
        return reference(value)

    def mutant(value: int) -> Any:
        return reference(value) + 1

    cases: list[ReliabilityCase] = []
    executions: dict[str, tuple[Any, Any, Mapping[str, Any]]] = {}
    for case_id, case_class, expected, candidate in (
        ("truth", ReliabilityCaseClass.TRUE_CASE, "PASS", matching),
        ("mutant", ReliabilityCaseClass.MUTANT, "FAIL", mutant),
        ("replay", ReliabilityCaseClass.REPLAY, "PASS", matching),
    ):
        candidate_identity = canonical_sha256(
            {"m7_differential_calibration": case_id, "reference": reference_identity_hash}
        )
        context = _context(
            claim,
            candidate_identity,
            reference_identity_hash,
            plan_hash=calibration_plan_hash,
            snapshot_hash=snapshot_hash,
        )
        case = ReliabilityCase(
            case_id=f"m7-differential-{case_id}",
            schema_version="genesis-m7-federated-evidence-v1",
            claim_hash=claim.claim_hash,
            case_class=case_class,
            expected_verdict=expected,
            candidate_identity_hash=candidate_identity,
            reference_identity_hash=reference_identity_hash,
            domain_hash=canonical_sha256(claim.domain),
            context_hash=context["context_hash"],
            source_provenance_hash=provenance_hash,
        )
        cases.append(case)
        executions[case.case_hash] = (
            DifferentialVerifier(reference, reference_identity_hash=reference_identity_hash),
            candidate,
            context,
        )
    receipt, profile = VerifierReliabilityCampaign().run(
        receipt_id=f"m7-differential-campaign-{claim.claim_hash}",
        descriptor=descriptor,
        implementation_identity_hash=descriptor.implementation_identity_hash,
        cases=tuple(cases),
        executions=executions,
        campaign_policy_hash=canonical_sha256(
            {"policy": "m7-finite-differential-characterization-v1"}
        ),
    )
    return receipt, profile


def _validate_acquisition_chain(
    *,
    campaign: AcquisitionCampaignManifest,
    baseline: CapabilityManifest,
    benchmark: SealedCapabilityBenchmark,
    task_id: str,
    result: AcquisitionResult,
) -> tuple[TaskBenchmarkBinding, ProgramSkillArtifact]:
    binding = result.task_benchmark_binding
    candidate = result.synthesis.selected_skill
    if (
        binding is None
        or candidate is None
        or result.commitment is None
        or result.audit is None
        or result.g1_manifest is None
        or result.promotion.status is not PromotionStatus.PROMOTED
        or task_id != binding.task_id
        or campaign.g0_capability_manifest_hash != baseline.manifest_hash
        or not validate_task_benchmark_binding(binding, campaign=campaign, benchmark=benchmark)
        or not validate_program_skill(candidate, benchmark.specification)
        or not validate_synthesis_receipt(result.synthesis.receipt, campaign, candidate)
        or not validate_candidate_commitment(
            result.commitment, campaign, result.synthesis.receipt, candidate
        )
        or not validate_manifest_successor(result.g1_manifest, baseline, candidate)
        or not validate_promotion_receipt(
            result.promotion,
            campaign=campaign,
            commitment=result.commitment,
            synthesis=result.synthesis.receipt,
            candidate=candidate,
            g0_manifest=baseline,
            g1_manifest=result.g1_manifest,
        )
    ):
        raise ValueError("genesis_m7_federated_acquisition_chain_invalid")
    expected_prior = PriorInsufficiencyReceipt(
        "genesis-m7-prior-insufficiency-v1",
        campaign.campaign_hash,
        task_id,
        baseline.manifest_hash,
        None,
        0,
        len(benchmark.learner_view(task_id).training_examples),
        "PASS" if not baseline.skill_hashes else "NOT_PROVEN",
        "no_target_skill_installed" if not baseline.skill_hashes else "baseline_capabilities_present",
    )
    if result.prior.receipt_hash != expected_prior.receipt_hash:
        raise ValueError("genesis_m7_federated_prior_invalid")

    # Rerunning the sealed deterministic synthesizer checks semantic source
    # evidence without exposing AUDIT/HIDDEN/TRANSFER data to the learner.
    replay = DeterministicProgramSynthesizer().synthesize(
        campaign=campaign,
        specification=benchmark.specification,
        training=benchmark.learner_view(task_id),
    )
    if (
        replay.receipt.synthesis_hash != result.synthesis.receipt.synthesis_hash
        or replay.selected_skill is None
        or replay.selected_skill.skill_hash != candidate.skill_hash
    ):
        raise ValueError("genesis_m7_federated_synthesis_replay_invalid")

    # This is evaluator-side validation of the already committed candidate,
    # not a second learner audit or a chance to change its selection.
    expected_audit = benchmark._evaluate(task_id, DatasetSplit.AUDIT, candidate)
    if (
        expected_audit.result_hash != result.audit.result_hash
        or not expected_audit.exact_pass
        or result.promotion.audit_evidence_hash != result.audit.result_hash
    ):
        raise ValueError("genesis_m7_federated_audit_invalid")
    return binding, candidate


def materialize_promoted_skill_evidence(
    *,
    campaign: AcquisitionCampaignManifest,
    baseline: CapabilityManifest,
    benchmark: SealedCapabilityBenchmark,
    task_id: str,
    result: AcquisitionResult,
    split: DatasetSplit,
) -> M7FederatedEvidence:
    """Create an M6 trace-ready exact observation for a promoted M7 skill.

    Only sealed HIDDEN or TRANSFER data may become a certifiable scope.  TRAIN
    and AUDIT remain acquisition controls and are deliberately rejected here.
    """

    split = DatasetSplit(split)
    if split not in _CERTIFIABLE_SPLITS:
        raise ValueError("genesis_m7_federated_split_not_certifiable")
    task_binding, candidate = _validate_acquisition_chain(
        campaign=campaign,
        baseline=baseline,
        benchmark=benchmark,
        task_id=task_id,
        result=result,
    )
    target = _trusted_target_commitment(benchmark, task_id)
    if not _validate_target_commitment(target, benchmark):
        raise ValueError("genesis_m7_federated_target_invalid")
    scope = _scope_for(
        benchmark=benchmark,
        binding=task_binding,
        candidate=candidate,
        target=target,
        split=split,
    )
    if not _validate_scope(
        scope,
        benchmark=benchmark,
        binding=task_binding,
        candidate=candidate,
        target=target,
    ):
        raise ValueError("genesis_m7_federated_scope_invalid")

    claim = TypedClaim(
        claim_id=f"m7-{task_id}-{split.value.lower()}-reference-equivalence",
        schema_version="genesis-m7-federated-evidence-v1",
        claim_type=ClaimType.EXACT_FUNCTION,
        properties={"relation": "reference_equivalence", "m7_scope_hash": scope.scope_hash},
        assumptions=(),
        domain=scope.domain,
        budget={},
        falsifiers=("finite_differential_counterexample",),
        obligations=("m7_differential",),
        risk_class="low",
        change_class=ChangeClass.NOT_APPLICABLE,
    )
    descriptor = _differential_descriptor()
    task = benchmark._tasks[task_id]

    def trusted_reference(value: int) -> int:
        return evaluate_expression(task.target_ast, value, benchmark.specification)

    def candidate_callable(value: int) -> int:
        return evaluate_expression(candidate.program_ast, value, benchmark.specification)

    reliability_campaign, profile = _reliability_material(
        claim=claim,
        descriptor=descriptor,
        reference=trusted_reference,
        reference_identity_hash=target.commitment_hash,
        provenance_hash=target.commitment_hash,
    )
    registry = VerifierRegistry()
    registry.register(descriptor)
    graph = VerifierDependencyGraph()
    graph.add(descriptor)
    requirement = FederatedVerificationRequirement(
        "m7-differential",
        "m7_differential",
        (AuthorityClass.DIFFERENTIAL,),
        (VerifierKind.DIFFERENTIAL,),
        1,
        1,
        False,
    )
    verification_plan = VerificationPlan(
        f"m7-federated-plan-{scope.scope_hash}",
        claim.claim_hash,
        (
            VerificationObligation(
                "m7_differential",
                "differential",
                "program_skill",
                AuthorityClass.DIFFERENTIAL.value,
                (descriptor.verifier_id,),
                "fail",
            ),
        ),
        {},
        {},
    )
    integrity = VerifierIntegrityReceipt(
        f"m7-differential-integrity-{scope.scope_hash}",
        descriptor.descriptor_hash,
        descriptor.implementation_identity_hash,
        descriptor.implementation_identity_hash,
        descriptor.dependency_manifest_hash,
        profile.profile_hash,
        IntegrityStatus.PASS,
        (),
    )
    reference_descriptor = ReferenceDescriptor(
        f"m7-target-{task_id}",
        "genesis-m7-federated-evidence-v1",
        "v1",
        target.commitment_hash,
        canonical_sha256(
            {"component": "m7-sealed-dsl-reference-evaluator-v1", "dsl_hash": benchmark.specification.dsl_hash}
        ),
        target.commitment_hash,
        benchmark.manifest.manifest_hash,
        "sealed_m7_benchmark",
        (claim.claim_type.value,),
        (canonical_sha256(claim.domain),),
    )
    qualification_policy = ReferenceQualificationPolicy(
        "m7-sealed-benchmark-reference-policy",
        "genesis-m7-federated-evidence-v1",
        ("sealed_m7_benchmark",),
        True,
        True,
        "exact-domain",
    )
    reference_registry = ReferenceRegistry()
    reference_registry.register(reference_descriptor)
    qualification_receipt = qualify_reference(
        reference_descriptor,
        qualification_policy,
        receipt_id=f"m7-reference-qualification-{scope.scope_hash}",
    )
    reference_binding = QualifiedReferenceBinding(
        reference_descriptor.reference_id,
        reference_descriptor.reference_version,
        reference_descriptor.descriptor_hash,
        target.commitment_hash,
        qualification_receipt.receipt_hash,
        claim.claim_hash,
        canonical_sha256(claim.domain),
    )
    router = VerifierRouter(
        claim=claim,
        verification_plan=verification_plan,
        requirements=(requirement,),
        registry=registry,
        dependency_graph=graph,
        reliability_profiles=(profile,),
        campaign_receipts=(reliability_campaign,),
        integrity_receipts=(integrity,),
        qualified_reference_bindings=(reference_binding,),
        reference_registry=reference_registry,
        qualification_receipts=(qualification_receipt,),
        qualification_policies=(qualification_policy,),
    )
    federation_plan = router.route()
    selected_binding = federation_plan.selected_bindings[0]
    execution_context = _context(
        claim,
        candidate.skill_hash,
        target.commitment_hash,
        plan_hash=federation_plan.plan_hash,
        snapshot_hash=canonical_sha256(
            {"m7_scope_hash": scope.scope_hash, "promotion_hash": result.promotion.promotion_hash}
        ),
    )
    subject = ExecutionSubjectBinding(
        claim.claim_hash,
        candidate.skill_hash,
        canonical_sha256(claim.domain),
        execution_context["context_hash"],
    )
    request = PlannedExecutionRequest(
        federation_plan.plan_hash,
        requirement.requirement_id,
        requirement.requirement_hash,
        selected_binding.binding_hash,
        subject.subject_hash,
    )
    outcome = PlanBoundExecutionKernel(router).execute(
        federation_plan=federation_plan,
        request=request,
        subject=subject,
        descriptor=descriptor,
        verifier=DifferentialVerifier(
            trusted_reference, reference_identity_hash=target.commitment_hash
        ),
        claim=claim,
        candidate=candidate_callable,
        context=execution_context,
        qualified_reference_binding=reference_binding,
    )
    if (
        outcome.admission.status is not ExecutionAdmissionStatus.ADMITTED
        or outcome.record is None
        or outcome.receipt is None
    ):
        raise ValueError("genesis_m7_federated_execution_not_admitted")
    material = ExecutionRecordMaterial(
        outcome.record,
        outcome.receipt,
        request,
        descriptor,
        reference_binding,
    )
    bundle = build_requirement_evidence_bundle(
        router=router,
        federation_plan=federation_plan,
        subject=subject,
        requirement_id=requirement.requirement_id,
        records=(material,),
    )
    adjudication = adjudicate_requirement(
        router=router,
        federation_plan=federation_plan,
        bundle=bundle,
        subject=subject,
        records=(material,),
    )
    historical_artifacts = {
        "m7_acquisition_campaign": (campaign,),
        "m7_baseline_capability_manifest": (baseline,),
        "m7_benchmark_manifest": (benchmark.manifest,),
        "m7_sealed_benchmark_replay_witness": (_benchmark_replay_witness(benchmark),),
        "m7_dsl_specification": (benchmark.specification,),
        "m7_task_benchmark_binding": (task_binding,),
        "m7_reference_target_commitment": (target,),
        "m7_measurement_scope": (scope,),
        "m7_prior_insufficiency_receipt": (result.prior,),
        "m7_synthesis_receipt": (result.synthesis.receipt,),
        "m7_program_skill": (candidate,),
        "m7_candidate_commitment": (result.commitment,),
        "m7_audit_evaluation": (result.audit,),
        "m7_promotion_receipt": (result.promotion,),
        "m7_successor_capability_manifest": (result.g1_manifest,),
    }
    return M7FederatedEvidence(
        scope,
        task_binding,
        target,
        claim,
        descriptor,
        reliability_campaign,
        profile,
        reference_descriptor,
        qualification_policy,
        qualification_receipt,
        reference_binding,
        router,
        federation_plan,
        subject,
        material,
        bundle,
        adjudication,
        historical_artifacts,
    )
