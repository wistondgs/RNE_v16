"""Structural, per-requirement evidence bundles; no verdict interpretation."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

from lab.genesis.contracts.serialization import canonical_sha256
from .descriptor import VerifierDescriptor
from .execution import (ExecutionSubjectBinding, PlannedExecutionRequest, VerifierExecutionRecord,
                        validate_execution_record)
from .plan import FederationPlan, SelectedVerifierBinding
from .references import QualifiedReferenceBinding
from .router import VerifierRouter, validate_federation_plan
from lab.genesis.contracts.receipts import VerifierReceipt


class EvidenceBundleStatus(str, Enum):
    COMPLETE = "COMPLETE"
    INCOMPLETE_MISSING_RECORDS = "INCOMPLETE_MISSING_RECORDS"
    INVALID_EXTRA_RECORDS = "INVALID_EXTRA_RECORDS"
    INVALID_DUPLICATE_RECORDS = "INVALID_DUPLICATE_RECORDS"
    INVALID_MIXED_PLAN = "INVALID_MIXED_PLAN"
    INVALID_MIXED_REQUIREMENT = "INVALID_MIXED_REQUIREMENT"
    INVALID_MIXED_SUBJECT = "INVALID_MIXED_SUBJECT"
    ERROR_INVALID_RECORD = "ERROR_INVALID_RECORD"


@dataclass(frozen=True, slots=True)
class RequirementEvidenceBundle:
    schema_version: str
    federation_plan_hash: str
    requirement_id: str
    requirement_hash: str
    execution_subject_hash: str
    expected_selected_binding_hashes: tuple[str, ...]
    execution_record_hashes: tuple[str, ...]
    bundle_status: EvidenceBundleStatus
    reason_codes: tuple[str, ...]
    bundle_hash: str = field(init=False)
    def __post_init__(self):
        object.__setattr__(self, "expected_selected_binding_hashes", tuple(self.expected_selected_binding_hashes))
        object.__setattr__(self, "execution_record_hashes", tuple(self.execution_record_hashes))
        object.__setattr__(self, "bundle_status", EvidenceBundleStatus(self.bundle_status))
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))
        object.__setattr__(self, "bundle_hash", canonical_sha256(self.canonical_payload()))
    def canonical_payload(self):
        return {"schema_version": self.schema_version, "federation_plan_hash": self.federation_plan_hash,
                "requirement_id": self.requirement_id, "requirement_hash": self.requirement_hash,
                "execution_subject_hash": self.execution_subject_hash,
                "expected_selected_binding_hashes": self.expected_selected_binding_hashes,
                "execution_record_hashes": self.execution_record_hashes,
                "bundle_status": self.bundle_status.value, "reason_codes": self.reason_codes}
    def validate(self):
        return (self.bundle_hash == canonical_sha256(self.canonical_payload())
                and self.expected_selected_binding_hashes == tuple(sorted(self.expected_selected_binding_hashes))
                and self.execution_record_hashes == tuple(sorted(self.execution_record_hashes))
                and self.reason_codes == tuple(sorted(self.reason_codes)))


@dataclass(frozen=True, slots=True)
class ExecutionRecordMaterial:
    """External source material needed to semantically validate a record."""
    record: VerifierExecutionRecord
    receipt: VerifierReceipt
    request: PlannedExecutionRequest
    descriptor: VerifierDescriptor
    qualified_reference_binding: QualifiedReferenceBinding | None = None


def _expected(plan: FederationPlan, requirement_id: str):
    result = next((x for x in plan.routing_results if x.requirement_id == requirement_id), None)
    if result is None: return None, ()
    return result, tuple(sorted(result.selected_binding_hashes))


def _derive(*, router: VerifierRouter, plan: FederationPlan, subject: ExecutionSubjectBinding,
            requirement_id: str, records: Iterable[ExecutionRecordMaterial]):
    records = tuple(records); result, expected = _expected(plan, requirement_id)
    if not validate_federation_plan(plan, router): return None, (), EvidenceBundleStatus.ERROR_INVALID_RECORD, ("federation_plan_invalid",)
    if result is None: return None, (), EvidenceBundleStatus.ERROR_INVALID_RECORD, ("requirement_missing",)
    supplied_hashes = tuple(sorted(x.record.record_hash for x in records))
    for item in records:
        record = item.record
        if record.federation_plan_hash != plan.plan_hash: return result, expected, EvidenceBundleStatus.INVALID_MIXED_PLAN, ("cross_plan_record",)
        if record.requirement_hash != result.requirement_hash: return result, expected, EvidenceBundleStatus.INVALID_MIXED_REQUIREMENT, ("cross_requirement_record",)
        if record.execution_subject_hash != subject.subject_hash: return result, expected, EvidenceBundleStatus.INVALID_MIXED_SUBJECT, ("cross_subject_record",)
    bindings = [x.record.selected_verifier_binding_hash for x in records]
    if any(x not in expected for x in bindings): return result, expected, EvidenceBundleStatus.INVALID_EXTRA_RECORDS, ("unplanned_record",)
    if len(bindings) != len(set(bindings)): return result, expected, EvidenceBundleStatus.INVALID_DUPLICATE_RECORDS, ("duplicate_planned_binding",)
    selected = {x.binding_hash: x for x in plan.selected_bindings}
    for item in records:
        binding = selected.get(item.record.selected_verifier_binding_hash)
        if binding is None or not validate_execution_record(item.record, receipt=item.receipt, subject=subject,
                request=item.request, binding=binding, descriptor=item.descriptor,
                qualified_reference_binding=item.qualified_reference_binding):
            return result, expected, EvidenceBundleStatus.ERROR_INVALID_RECORD, ("execution_record_invalid",)
    if set(bindings) != set(expected): return result, expected, EvidenceBundleStatus.INCOMPLETE_MISSING_RECORDS, ("planned_record_missing",)
    return result, expected, EvidenceBundleStatus.COMPLETE, ()


def build_requirement_evidence_bundle(*, router: VerifierRouter, federation_plan: FederationPlan,
                                      subject: ExecutionSubjectBinding, requirement_id: str,
                                      records: Iterable[ExecutionRecordMaterial]) -> RequirementEvidenceBundle:
    records = tuple(records); result, expected, status, reasons = _derive(router=router, plan=federation_plan,
        subject=subject, requirement_id=requirement_id, records=records)
    return RequirementEvidenceBundle("genesis-requirement-evidence-bundle-v1", federation_plan.plan_hash,
        requirement_id, result.requirement_hash if result else "", subject.subject_hash, expected,
        tuple(sorted(x.record.record_hash for x in records)), status, tuple(sorted(reasons)))


def validate_requirement_evidence_bundle(bundle: RequirementEvidenceBundle, *, router: VerifierRouter,
                                         federation_plan: FederationPlan, subject: ExecutionSubjectBinding,
                                         records: Iterable[ExecutionRecordMaterial]) -> bool:
    if not bundle.validate() or bundle.federation_plan_hash != federation_plan.plan_hash or bundle.execution_subject_hash != subject.subject_hash:
        return False
    records = tuple(records); result, expected, status, reasons = _derive(router=router, plan=federation_plan,
        subject=subject, requirement_id=bundle.requirement_id, records=records)
    return (result is not None and bundle.requirement_hash == result.requirement_hash
            and bundle.expected_selected_binding_hashes == expected
            and bundle.execution_record_hashes == tuple(sorted(x.record.record_hash for x in records))
            and bundle.bundle_status is status and bundle.reason_codes == tuple(sorted(reasons)))
