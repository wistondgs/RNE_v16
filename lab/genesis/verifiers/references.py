"""Qualified, scoped provenance for references used by differential evidence.

Qualification records protocol admission under a declared policy.  It is not
a proof that a reference is semantically correct, and registry membership is
not qualification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping

from lab.genesis.contracts.claims import TypedClaim
from lab.genesis.contracts.receipts import VerifierReceipt
from lab.genesis.contracts.serialization import canonical_sha256


class ReferenceQualificationStatus(str, Enum):
    QUALIFIED = "QUALIFIED"
    REJECTED = "REJECTED"
    INCOMPLETE = "INCOMPLETE"


@dataclass(frozen=True, slots=True)
class ReferenceDescriptor:
    reference_id: str
    schema_version: str
    reference_version: str
    reference_identity_hash: str
    implementation_identity_hash: str
    source_artifact_hash: str
    source_provenance_hash: str
    source_kind: str
    supported_claim_types: tuple[str, ...]
    supported_domain_hashes: tuple[str, ...]
    descriptor_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "supported_claim_types", tuple(self.supported_claim_types))
        object.__setattr__(self, "supported_domain_hashes", tuple(self.supported_domain_hashes))
        object.__setattr__(self, "descriptor_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, object]:
        return {
            "reference_id": self.reference_id,
            "schema_version": self.schema_version,
            "reference_version": self.reference_version,
            "reference_identity_hash": self.reference_identity_hash,
            "implementation_identity_hash": self.implementation_identity_hash,
            "source_artifact_hash": self.source_artifact_hash,
            "source_provenance_hash": self.source_provenance_hash,
            "source_kind": self.source_kind,
            "supported_claim_types": self.supported_claim_types,
            "supported_domain_hashes": self.supported_domain_hashes,
        }

    def validate(self) -> bool:
        return self.descriptor_hash == canonical_sha256(self.canonical_payload())


@dataclass(frozen=True, slots=True)
class ReferenceQualificationPolicy:
    policy_id: str
    schema_version: str
    accepted_source_kinds: tuple[str, ...]
    require_source_provenance: bool
    require_implementation_identity: bool
    scope_policy: str
    policy_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "accepted_source_kinds", tuple(self.accepted_source_kinds))
        object.__setattr__(self, "policy_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "schema_version": self.schema_version,
            "accepted_source_kinds": self.accepted_source_kinds,
            "require_source_provenance": self.require_source_provenance,
            "require_implementation_identity": self.require_implementation_identity,
            "scope_policy": self.scope_policy,
        }

    def validate(self) -> bool:
        return self.policy_hash == canonical_sha256(self.canonical_payload())


@dataclass(frozen=True, slots=True)
class ReferenceQualificationReceipt:
    receipt_id: str
    schema_version: str
    reference_descriptor_hash: str
    qualification_policy_hash: str
    implementation_identity_hash: str
    source_artifact_hash: str
    source_provenance_hash: str
    qualified_claim_types: tuple[str, ...]
    qualified_domain_hashes: tuple[str, ...]
    status: ReferenceQualificationStatus
    evidence_hashes: tuple[str, ...]
    reason_codes: tuple[str, ...]
    receipt_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", ReferenceQualificationStatus(self.status))
        object.__setattr__(self, "qualified_claim_types", tuple(self.qualified_claim_types))
        object.__setattr__(self, "qualified_domain_hashes", tuple(self.qualified_domain_hashes))
        object.__setattr__(self, "evidence_hashes", tuple(self.evidence_hashes))
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))
        object.__setattr__(self, "receipt_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, object]:
        return {
            "receipt_id": self.receipt_id,
            "schema_version": self.schema_version,
            "reference_descriptor_hash": self.reference_descriptor_hash,
            "qualification_policy_hash": self.qualification_policy_hash,
            "implementation_identity_hash": self.implementation_identity_hash,
            "source_artifact_hash": self.source_artifact_hash,
            "source_provenance_hash": self.source_provenance_hash,
            "qualified_claim_types": self.qualified_claim_types,
            "qualified_domain_hashes": self.qualified_domain_hashes,
            "status": self.status.value,
            "evidence_hashes": self.evidence_hashes,
            "reason_codes": self.reason_codes,
        }

    def validate(self) -> bool:
        return self.receipt_hash == canonical_sha256(self.canonical_payload())


def qualify_reference(
    descriptor: ReferenceDescriptor,
    policy: ReferenceQualificationPolicy,
    *,
    receipt_id: str,
) -> ReferenceQualificationReceipt:
    """Derive admission status from descriptor and policy, never a trust flag."""

    rejected: list[str] = []
    incomplete: list[str] = []
    if not descriptor.validate():
        rejected.append("reference_descriptor_invalid")
    if not policy.validate():
        rejected.append("qualification_policy_invalid")
    if descriptor.source_kind not in policy.accepted_source_kinds:
        rejected.append("source_kind_not_accepted")
    if policy.require_source_provenance and not descriptor.source_provenance_hash:
        incomplete.append("source_provenance_missing")
    if policy.require_implementation_identity and not descriptor.implementation_identity_hash:
        incomplete.append("implementation_identity_missing")
    if not descriptor.source_artifact_hash:
        incomplete.append("source_artifact_missing")
    if not descriptor.supported_claim_types:
        incomplete.append("qualified_claim_scope_missing")
    if not descriptor.supported_domain_hashes:
        incomplete.append("qualified_domain_scope_missing")

    status = (
        ReferenceQualificationStatus.REJECTED
        if rejected
        else ReferenceQualificationStatus.INCOMPLETE
        if incomplete
        else ReferenceQualificationStatus.QUALIFIED
    )
    reasons = tuple(rejected + incomplete)
    qualified = status is ReferenceQualificationStatus.QUALIFIED
    evidence_hashes = tuple(
        value
        for value in (
            descriptor.source_artifact_hash,
            descriptor.source_provenance_hash,
        )
        if value
    )
    return ReferenceQualificationReceipt(
        receipt_id=receipt_id,
        schema_version="genesis-reference-qualification-v1",
        reference_descriptor_hash=descriptor.descriptor_hash,
        qualification_policy_hash=policy.policy_hash,
        implementation_identity_hash=descriptor.implementation_identity_hash,
        source_artifact_hash=descriptor.source_artifact_hash,
        source_provenance_hash=descriptor.source_provenance_hash,
        qualified_claim_types=descriptor.supported_claim_types if qualified else (),
        qualified_domain_hashes=descriptor.supported_domain_hashes if qualified else (),
        status=status,
        evidence_hashes=evidence_hashes,
        reason_codes=reasons,
    )


def validate_qualification_receipt(
    receipt: ReferenceQualificationReceipt,
    descriptor: ReferenceDescriptor,
    policy: ReferenceQualificationPolicy,
) -> bool:
    """Reject resealed receipt fields that cannot be rederived from admission."""

    if not receipt.validate():
        return False
    expected = qualify_reference(descriptor, policy, receipt_id=receipt.receipt_id)
    return receipt.receipt_hash == expected.receipt_hash


class ReferenceRegistry:
    """An instance-local deterministic catalogue; registration grants no status."""

    def __init__(self) -> None:
        self._descriptors: dict[tuple[str, str], ReferenceDescriptor] = {}

    def register(self, descriptor: ReferenceDescriptor) -> None:
        if not descriptor.validate():
            raise ValueError("genesis_reference_descriptor_invalid")
        key = (descriptor.reference_id, descriptor.reference_version)
        existing = self._descriptors.get(key)
        if existing is not None and existing.descriptor_hash != descriptor.descriptor_hash:
            raise ValueError("genesis_reference_registry_conflicting_duplicate")
        self._descriptors[key] = descriptor

    def resolve(self, reference_id: str, reference_version: str) -> ReferenceDescriptor | None:
        return self._descriptors.get((reference_id, reference_version))

    def descriptors(self) -> tuple[ReferenceDescriptor, ...]:
        return tuple(self._descriptors[key] for key in sorted(self._descriptors))


@dataclass(frozen=True, slots=True)
class QualifiedReferenceBinding:
    reference_id: str
    reference_version: str
    reference_descriptor_hash: str
    reference_identity_hash: str
    qualification_receipt_hash: str
    claim_hash: str
    domain_hash: str
    binding_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "binding_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, str]:
        return {
            "reference_id": self.reference_id,
            "reference_version": self.reference_version,
            "reference_descriptor_hash": self.reference_descriptor_hash,
            "reference_identity_hash": self.reference_identity_hash,
            "qualification_receipt_hash": self.qualification_receipt_hash,
            "claim_hash": self.claim_hash,
            "domain_hash": self.domain_hash,
        }

    def validate(self) -> bool:
        return self.binding_hash == canonical_sha256(self.canonical_payload())


def validate_qualified_reference_binding(
    binding: QualifiedReferenceBinding,
    *,
    registry: ReferenceRegistry,
    qualification_receipt: ReferenceQualificationReceipt,
    qualification_policy: ReferenceQualificationPolicy,
    claim: TypedClaim,
) -> bool:
    """Validate descriptor, admission, scope, and exact reference identity."""

    if not binding.validate() or binding.claim_hash != claim.claim_hash:
        return False
    descriptor = registry.resolve(binding.reference_id, binding.reference_version)
    if descriptor is None or not descriptor.validate():
        return False
    if (
        binding.reference_descriptor_hash != descriptor.descriptor_hash
        or binding.reference_identity_hash != descriptor.reference_identity_hash
        or binding.qualification_receipt_hash != qualification_receipt.receipt_hash
        or binding.domain_hash != canonical_sha256(claim.domain)
    ):
        return False
    if not validate_qualification_receipt(
        qualification_receipt, descriptor, qualification_policy
    ):
        return False
    if qualification_receipt.status is not ReferenceQualificationStatus.QUALIFIED:
        return False
    if qualification_receipt.implementation_identity_hash != descriptor.implementation_identity_hash:
        return False
    if claim.claim_type.value not in qualification_receipt.qualified_claim_types:
        return False
    if binding.domain_hash not in qualification_receipt.qualified_domain_hashes:
        return False
    if (
        qualification_policy.require_source_provenance
        and not qualification_receipt.source_provenance_hash
    ):
        return False
    return True


def validate_differential_evidence_binding(
    differential_receipt: VerifierReceipt,
    binding: QualifiedReferenceBinding,
    *,
    registry: ReferenceRegistry,
    qualification_receipt: ReferenceQualificationReceipt,
    qualification_policy: ReferenceQualificationPolicy,
    claim: TypedClaim,
) -> bool:
    """Externally bind an immutable Differential receipt to qualified provenance."""

    return (
        differential_receipt.evidence.get("reference_identity_hash")
        == binding.reference_identity_hash
        and validate_qualified_reference_binding(
            binding,
            registry=registry,
            qualification_receipt=qualification_receipt,
            qualification_policy=qualification_policy,
            claim=claim,
        )
    )
