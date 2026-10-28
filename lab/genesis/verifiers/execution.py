"""Plan-bound verifier execution, deliberately separate from adjudication."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from lab.genesis.contracts.claims import TypedClaim
from lab.genesis.contracts.receipts import ReceiptStatus, VerifierReceipt
from lab.genesis.contracts.serialization import canonical_sha256
from .bindings import canonical_execution_context_hash
from .descriptor import VerifierDescriptor, VerifierKind
from .plan import FederationPlan, SelectedVerifierBinding
from .references import QualifiedReferenceBinding
from .router import VerifierRouter, validate_federation_plan, validate_presented_verifier_against_binding


class ExecutionAdmissionStatus(str, Enum):
    ADMITTED = "ADMITTED"
    REJECTED_PLAN_INVALID = "REJECTED_PLAN_INVALID"
    REJECTED_BINDING_MISMATCH = "REJECTED_BINDING_MISMATCH"
    REJECTED_SUBJECT_INVALID = "REJECTED_SUBJECT_INVALID"
    REJECTED_REFERENCE_MISMATCH = "REJECTED_REFERENCE_MISMATCH"
    ERROR_PRE_EXECUTION = "ERROR_PRE_EXECUTION"
    ERROR_EXECUTION_EXCEPTION = "ERROR_EXECUTION_EXCEPTION"


class ExecutionStatus(str, Enum):
    EXECUTED = "EXECUTED"


@dataclass(frozen=True, slots=True)
class ExecutionSubjectBinding:
    claim_hash: str
    candidate_identity_hash: str
    domain_hash: str
    context_hash: str
    subject_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, str]:
        return {"claim_hash": self.claim_hash, "candidate_identity_hash": self.candidate_identity_hash,
                "domain_hash": self.domain_hash, "context_hash": self.context_hash}

    def validate(self) -> bool:
        return self.subject_hash == canonical_sha256(self.canonical_payload())


@dataclass(frozen=True, slots=True)
class PlannedExecutionRequest:
    federation_plan_hash: str
    requirement_id: str
    requirement_hash: str
    selected_verifier_binding_hash: str
    execution_subject_hash: str
    request_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, str]:
        return {"federation_plan_hash": self.federation_plan_hash, "requirement_id": self.requirement_id,
                "requirement_hash": self.requirement_hash, "selected_verifier_binding_hash": self.selected_verifier_binding_hash,
                "execution_subject_hash": self.execution_subject_hash}

    def validate(self) -> bool:
        return self.request_hash == canonical_sha256(self.canonical_payload())


@dataclass(frozen=True, slots=True)
class VerifierExecutionRecord:
    schema_version: str
    federation_plan_hash: str
    requirement_hash: str
    selected_verifier_binding_hash: str
    execution_subject_hash: str
    verifier_id: str
    verifier_version: str
    descriptor_hash: str
    implementation_identity_hash: str
    qualified_reference_binding_hash: str | None
    verifier_receipt_hash: str
    observed_verdict: ReceiptStatus
    semantic_result_hash: str
    execution_status: ExecutionStatus
    reason_codes: tuple[str, ...]
    record_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_verdict", ReceiptStatus(self.observed_verdict))
        object.__setattr__(self, "execution_status", ExecutionStatus(self.execution_status))
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))
        object.__setattr__(self, "record_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, object]:
        return {key: getattr(self, key).value if hasattr(getattr(self, key), "value") else getattr(self, key)
                for key in ("schema_version", "federation_plan_hash", "requirement_hash",
                            "selected_verifier_binding_hash", "execution_subject_hash", "verifier_id",
                            "verifier_version", "descriptor_hash", "implementation_identity_hash",
                            "qualified_reference_binding_hash", "verifier_receipt_hash", "observed_verdict",
                            "semantic_result_hash", "execution_status", "reason_codes")}

    def validate(self) -> bool:
        return (self.record_hash == canonical_sha256(self.canonical_payload())
                and self.execution_status is ExecutionStatus.EXECUTED
                and self.reason_codes == tuple(sorted(self.reason_codes)))


@dataclass(frozen=True, slots=True)
class ExecutionAdmission:
    status: ExecutionAdmissionStatus
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", ExecutionAdmissionStatus(self.status))
        object.__setattr__(self, "reason_codes", tuple(sorted(self.reason_codes)))


@dataclass(frozen=True, slots=True)
class PlannedExecutionResult:
    admission: ExecutionAdmission
    record: VerifierExecutionRecord | None = None
    receipt: VerifierReceipt | None = None


def semantic_result_hash(receipt: VerifierReceipt) -> str:
    """Scientific result only; receipt IDs are operational provenance, not outcome."""
    return canonical_sha256({"status": receipt.status.value, "evidence": receipt.evidence,
                             "counterexamples": receipt.counterexamples, "coverage": receipt.coverage,
                             "assumptions_active": receipt.assumptions_active})


def validate_execution_record(record: VerifierExecutionRecord, *, receipt: VerifierReceipt,
                              subject: ExecutionSubjectBinding, request: PlannedExecutionRequest,
                              binding: SelectedVerifierBinding, descriptor: VerifierDescriptor,
                              qualified_reference_binding: QualifiedReferenceBinding | None = None) -> bool:
    """Validate seal plus semantic receipt/binding derivation."""
    if not (record.validate() and receipt.receipt_hash == canonical_sha256(receipt.canonical_payload())
            and subject.validate() and request.validate() and binding.validate()): return False
    if (record.federation_plan_hash != request.federation_plan_hash or record.requirement_hash != request.requirement_hash
            or record.selected_verifier_binding_hash != binding.binding_hash
            or record.execution_subject_hash != subject.subject_hash or record.verifier_receipt_hash != receipt.receipt_hash
            or record.observed_verdict is not receipt.status or record.semantic_result_hash != semantic_result_hash(receipt)):
        return False
    if (receipt.claim_hash != subject.claim_hash or receipt.plan_hash != request.federation_plan_hash
            or receipt.verifier_id != binding.verifier_id or receipt.verifier_version != binding.verifier_version): return False
    if (record.descriptor_hash != binding.verifier_descriptor_hash
            or record.implementation_identity_hash != binding.implementation_identity_hash
            or record.verifier_id != binding.verifier_id or record.verifier_version != binding.verifier_version): return False
    if validate_presented_verifier_against_binding(descriptor, binding,
            qualified_reference_binding.binding_hash if qualified_reference_binding else None).value != "ADMISSIBLE": return False
    if record.qualified_reference_binding_hash != binding.qualified_reference_binding_hash: return False
    if binding.qualified_reference_binding_hash:
        if qualified_reference_binding is None or qualified_reference_binding.binding_hash != binding.qualified_reference_binding_hash:
            return False
        if receipt.evidence.get("reference_identity_hash") != qualified_reference_binding.reference_identity_hash:
            return False
    evidence = receipt.evidence
    for key, value in (("candidate_identity_hash", subject.candidate_identity_hash), ("domain_hash", subject.domain_hash),
                       ("context_hash", subject.context_hash)):
        if key in evidence and evidence[key] != value: return False
    return True


class PlanBoundExecutionKernel:
    """Executes one preselected binding exactly once after complete admission."""
    def __init__(self, router: VerifierRouter) -> None:
        self.router = router

    def execute(self, *, federation_plan: FederationPlan, request: PlannedExecutionRequest,
                subject: ExecutionSubjectBinding, descriptor: VerifierDescriptor, verifier: Any,
                claim: TypedClaim, candidate: Any, context: Mapping[str, Any],
                qualified_reference_binding: QualifiedReferenceBinding | None = None) -> PlannedExecutionResult:
        # Everything through this point is pre-execution: no verifier access.
        if not validate_federation_plan(federation_plan, self.router):
            return self._reject(ExecutionAdmissionStatus.REJECTED_PLAN_INVALID, "federation_plan_invalid")
        if not request.validate() or request.federation_plan_hash != federation_plan.plan_hash:
            return self._reject(ExecutionAdmissionStatus.REJECTED_BINDING_MISMATCH, "request_plan_mismatch")
        if not subject.validate() or request.execution_subject_hash != subject.subject_hash:
            return self._reject(ExecutionAdmissionStatus.REJECTED_SUBJECT_INVALID, "subject_request_mismatch")
        if not self._subject_matches(subject, claim, context):
            return self._reject(ExecutionAdmissionStatus.REJECTED_SUBJECT_INVALID, "subject_context_mismatch")
        binding = next((x for x in federation_plan.selected_bindings if x.binding_hash == request.selected_verifier_binding_hash), None)
        result = next((x for x in federation_plan.routing_results if x.requirement_id == request.requirement_id), None)
        if binding is None or result is None or result.requirement_hash != request.requirement_hash or binding.requirement_id != request.requirement_id:
            return self._reject(ExecutionAdmissionStatus.REJECTED_BINDING_MISMATCH, "selected_binding_missing")
        if validate_presented_verifier_against_binding(descriptor, binding,
                qualified_reference_binding.binding_hash if qualified_reference_binding else None).value != "ADMISSIBLE":
            return self._reject(ExecutionAdmissionStatus.REJECTED_BINDING_MISMATCH, "presented_verifier_mismatch")
        if (getattr(verifier, "verifier_id", None) != binding.verifier_id
                or getattr(verifier, "verifier_version", None) != binding.verifier_version):
            return self._reject(ExecutionAdmissionStatus.REJECTED_BINDING_MISMATCH, "runtime_verifier_identity_mismatch")
        if not self._reference_matches(binding, descriptor, verifier, qualified_reference_binding):
            return self._reject(ExecutionAdmissionStatus.REJECTED_REFERENCE_MISMATCH, "reference_binding_mismatch")
        try:
            receipt = verifier.verify(claim, candidate, context)
        except Exception as exc:
            return self._reject(ExecutionAdmissionStatus.ERROR_EXECUTION_EXCEPTION, f"verifier_exception:{type(exc).__name__}")
        record = VerifierExecutionRecord("genesis-verifier-execution-v1", federation_plan.plan_hash,
            request.requirement_hash, binding.binding_hash, subject.subject_hash, descriptor.verifier_id,
            descriptor.verifier_version, descriptor.descriptor_hash, descriptor.implementation_identity_hash,
            binding.qualified_reference_binding_hash, receipt.receipt_hash, receipt.status, semantic_result_hash(receipt),
            ExecutionStatus.EXECUTED, ())
        if not validate_execution_record(record, receipt=receipt, subject=subject, request=request,
                binding=binding, descriptor=descriptor, qualified_reference_binding=qualified_reference_binding):
            return self._reject(ExecutionAdmissionStatus.ERROR_PRE_EXECUTION, "receipt_binding_invalid")
        return PlannedExecutionResult(ExecutionAdmission(ExecutionAdmissionStatus.ADMITTED), record, receipt)

    @staticmethod
    def _reject(status: ExecutionAdmissionStatus, reason: str) -> PlannedExecutionResult:
        return PlannedExecutionResult(ExecutionAdmission(status, (reason,)))

    @staticmethod
    def _subject_matches(subject: ExecutionSubjectBinding, claim: TypedClaim, context: Mapping[str, Any]) -> bool:
        candidate_identity = context.get("candidate_identity_hash")
        return (claim.claim_hash == subject.claim_hash and canonical_sha256(claim.domain) == subject.domain_hash
                and candidate_identity == subject.candidate_identity_hash
                and canonical_execution_context_hash(claim.claim_hash, str(candidate_identity), context) == subject.context_hash
                and context.get("context_hash") == subject.context_hash)

    @staticmethod
    def _reference_matches(binding: SelectedVerifierBinding, descriptor: VerifierDescriptor, verifier: Any,
                           reference: QualifiedReferenceBinding | None) -> bool:
        if binding.qualified_reference_binding_hash is None:
            return reference is None
        return (descriptor.verifier_kind is VerifierKind.DIFFERENTIAL and reference is not None
                and reference.validate() and reference.binding_hash == binding.qualified_reference_binding_hash
                and getattr(verifier, "reference_identity_hash", None) == reference.reference_identity_hash)
