"""Sealed, deterministic routing artifacts.  These artifacts plan work only."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from lab.genesis.contracts.serialization import canonical_sha256


class RoutingStatus(str, Enum):
    PLANNABLE = "PLANNABLE"
    UNPLANNABLE_NO_COMPATIBLE = "UNPLANNABLE_NO_COMPATIBLE"
    INCOMPLETE_INTEGRITY = "INCOMPLETE_INTEGRITY"
    INCOMPLETE_RELIABILITY = "INCOMPLETE_RELIABILITY"
    INCOMPLETE_INDEPENDENCE = "INCOMPLETE_INDEPENDENCE"
    INCOMPLETE_CFI = "INCOMPLETE_CFI"
    INCOMPLETE_REFERENCE = "INCOMPLETE_REFERENCE"
    ERROR_REFERENCE_INVALID = "ERROR_REFERENCE_INVALID"


@dataclass(frozen=True, slots=True)
class SelectedVerifierBinding:
    requirement_id: str
    verifier_id: str
    verifier_version: str
    verifier_kind: str
    authority_class: str
    sovereignty: str
    verifier_descriptor_hash: str
    implementation_identity_hash: str
    integrity_receipt_hash: str
    reliability_profile_hash: str
    qualified_reference_binding_hash: str | None = None
    binding_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "binding_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, object]:
        return {key: getattr(self, key) for key in (
            "requirement_id", "verifier_id", "verifier_version", "verifier_kind",
            "authority_class", "sovereignty", "verifier_descriptor_hash",
            "implementation_identity_hash", "integrity_receipt_hash",
            "reliability_profile_hash", "qualified_reference_binding_hash",
        )}

    def validate(self) -> bool:
        return self.binding_hash == canonical_sha256(self.canonical_payload())


@dataclass(frozen=True, slots=True)
class RequirementRoutingResult:
    requirement_id: str
    requirement_hash: str
    status: RoutingStatus
    selected_binding_hashes: tuple[str, ...]
    reason_codes: tuple[str, ...]
    dependency_evidence_hashes: tuple[str, ...]
    result_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", RoutingStatus(self.status))
        object.__setattr__(self, "selected_binding_hashes", tuple(self.selected_binding_hashes))
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))
        object.__setattr__(self, "dependency_evidence_hashes", tuple(self.dependency_evidence_hashes))
        object.__setattr__(self, "result_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, object]:
        return {"requirement_id": self.requirement_id, "requirement_hash": self.requirement_hash,
                "status": self.status.value, "selected_binding_hashes": self.selected_binding_hashes,
                "reason_codes": self.reason_codes, "dependency_evidence_hashes": self.dependency_evidence_hashes}

    def validate(self) -> bool:
        return (self.result_hash == canonical_sha256(self.canonical_payload())
                and self.selected_binding_hashes == tuple(sorted(self.selected_binding_hashes))
                and self.reason_codes == tuple(sorted(self.reason_codes))
                and self.dependency_evidence_hashes == tuple(sorted(self.dependency_evidence_hashes)))


@dataclass(frozen=True, slots=True)
class FederationPlan:
    schema_version: str
    claim_hash: str
    verification_plan_hash: str
    requirement_hashes: tuple[str, ...]
    routing_results: tuple[RequirementRoutingResult, ...]
    selected_bindings: tuple[SelectedVerifierBinding, ...]
    dependency_graph_hash: str
    reliability_profile_hashes: tuple[str, ...]
    integrity_receipt_hashes: tuple[str, ...]
    qualified_reference_binding_hashes: tuple[str, ...]
    cfi_report_hashes: tuple[str, ...]
    selection_policy_hash: str
    plan_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ("requirement_hashes", "routing_results", "selected_bindings", "reliability_profile_hashes",
                     "integrity_receipt_hashes", "qualified_reference_binding_hashes", "cfi_report_hashes"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        object.__setattr__(self, "plan_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, object]:
        return {"schema_version": self.schema_version, "claim_hash": self.claim_hash,
                "verification_plan_hash": self.verification_plan_hash, "requirement_hashes": self.requirement_hashes,
                "routing_results": tuple(x.canonical_payload() | {"result_hash": x.result_hash} for x in self.routing_results),
                "selected_bindings": tuple(x.canonical_payload() | {"binding_hash": x.binding_hash} for x in self.selected_bindings),
                "dependency_graph_hash": self.dependency_graph_hash,
                "reliability_profile_hashes": self.reliability_profile_hashes,
                "integrity_receipt_hashes": self.integrity_receipt_hashes,
                "qualified_reference_binding_hashes": self.qualified_reference_binding_hashes,
                "cfi_report_hashes": self.cfi_report_hashes, "selection_policy_hash": self.selection_policy_hash}

    def validate(self) -> bool:
        groups = (self.requirement_hashes, self.reliability_profile_hashes, self.integrity_receipt_hashes,
                  self.qualified_reference_binding_hashes, self.cfi_report_hashes)
        return (self.plan_hash == canonical_sha256(self.canonical_payload()) and all(x == tuple(sorted(x)) for x in groups)
                and self.routing_results == tuple(sorted(self.routing_results, key=lambda x: x.requirement_id))
                and self.selected_bindings == tuple(sorted(self.selected_bindings, key=lambda x: x.binding_hash))
                and all(x.validate() for x in self.routing_results) and all(x.validate() for x in self.selected_bindings))
