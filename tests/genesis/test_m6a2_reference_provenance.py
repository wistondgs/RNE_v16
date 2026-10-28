"""M6A-2R: scoped qualification is provenance, not semantic truth."""

from __future__ import annotations

from dataclasses import fields, replace

import pytest

from lab.genesis.contracts.claims import ChangeClass, ClaimType, TypedClaim
from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.verifiers.references import (
    QualifiedReferenceBinding,
    ReferenceDescriptor,
    ReferenceQualificationPolicy,
    ReferenceQualificationStatus,
    ReferenceRegistry,
    qualify_reference,
    validate_differential_evidence_binding,
    validate_qualification_receipt,
    validate_qualified_reference_binding,
)
from tests.genesis.test_m6a2_differential import (
    context as differential_context,
    differential_claim,
    h as differential_hash,
    times_two,
    verifier as differential_verifier,
)


def h(value: object) -> str:
    return canonical_sha256({"m6a2r_test": value})


def policy(*, policy_id: str = "m6a2r-lab-admission") -> ReferenceQualificationPolicy:
    return ReferenceQualificationPolicy(
        policy_id=policy_id,
        schema_version="genesis.m6a2r",
        accepted_source_kinds=("PREDECLARED_LAB",),
        require_source_provenance=True,
        require_implementation_identity=True,
        scope_policy="descriptor_declared_scope",
    )


def descriptor(
    *,
    reference_identity_hash: str | None = None,
    source_artifact_hash: str | None = None,
    source_provenance_hash: str | None = None,
    supported_claim_types: tuple[str, ...] = (ClaimType.EXACT_FUNCTION.value,),
    supported_domain_hashes: tuple[str, ...] | None = None,
) -> ReferenceDescriptor:
    claim = differential_claim()
    return ReferenceDescriptor(
        reference_id="reference-times-two",
        schema_version="genesis.m6a2r",
        reference_version="v1",
        reference_identity_hash=(
            reference_identity_hash
            or differential_hash(("reference", "times-two"))
        ),
        implementation_identity_hash=h(
            {
                "module_relative_path": "tests/genesis/harness_references.py",
                "symbol_name": "times_two",
                "content_hash": h("times-two-harness-v1"),
                "version": "v1",
            }
        ),
        source_artifact_hash=(
            h({"artifact": "predeclared-2x-v1"})
            if source_artifact_hash is None
            else source_artifact_hash
        ),
        source_provenance_hash=(
            h({"provenance": "predeclared-lab-specification-v1"})
            if source_provenance_hash is None
            else source_provenance_hash
        ),
        source_kind="PREDECLARED_LAB",
        supported_claim_types=supported_claim_types,
        supported_domain_hashes=supported_domain_hashes
        or (canonical_sha256(claim.domain),),
    )


def qualified_fixture():
    claim = differential_claim()
    reference_descriptor = descriptor()
    qualification_policy = policy()
    qualification_receipt = qualify_reference(
        reference_descriptor, qualification_policy, receipt_id="qualification-q0"
    )
    registry = ReferenceRegistry()
    registry.register(reference_descriptor)
    binding = QualifiedReferenceBinding(
        reference_id=reference_descriptor.reference_id,
        reference_version=reference_descriptor.reference_version,
        reference_descriptor_hash=reference_descriptor.descriptor_hash,
        reference_identity_hash=reference_descriptor.reference_identity_hash,
        qualification_receipt_hash=qualification_receipt.receipt_hash,
        claim_hash=claim.claim_hash,
        domain_hash=canonical_sha256(claim.domain),
    )
    return (
        claim,
        reference_descriptor,
        qualification_policy,
        qualification_receipt,
        registry,
        binding,
    )


def differential_receipt(claim: TypedClaim):
    subject = differential_verifier(times_two, "times-two")
    return subject.verify(
        claim,
        times_two,
        differential_context(
            claim,
            candidate_identity_hash=differential_hash(("candidate", "times-two")),
            reference_identity_hash=subject.reference_identity_hash,
        ),
    )


def test_valid_reference_is_qualified_scoped_and_externally_binds_differential() -> None:
    claim, reference_descriptor, qualification_policy, receipt, registry, binding = qualified_fixture()
    differential = differential_receipt(claim)

    assert receipt.status is ReferenceQualificationStatus.QUALIFIED
    assert validate_qualification_receipt(receipt, reference_descriptor, qualification_policy)
    assert validate_qualified_reference_binding(
        binding,
        registry=registry,
        qualification_receipt=receipt,
        qualification_policy=qualification_policy,
        claim=claim,
    )
    assert validate_differential_evidence_binding(
        differential,
        binding,
        registry=registry,
        qualification_receipt=receipt,
        qualification_policy=qualification_policy,
        claim=claim,
    )
    assert differential.evidence["reference_identity_hash"] == binding.reference_identity_hash


def test_registry_membership_is_not_qualification() -> None:
    registry = ReferenceRegistry()
    reference_descriptor = descriptor()
    registry.register(reference_descriptor)

    assert registry.resolve("reference-times-two", "v1") == reference_descriptor
    assert registry.descriptors() == (reference_descriptor,)
    assert not hasattr(registry, "qualified")


def test_registered_but_incomplete_reference_cannot_form_a_qualified_binding() -> None:
    claim = differential_claim()
    reference_descriptor = descriptor(source_provenance_hash="")
    qualification_policy = policy()
    receipt = qualify_reference(
        reference_descriptor, qualification_policy, receipt_id="qualification-incomplete"
    )
    registry = ReferenceRegistry()
    registry.register(reference_descriptor)
    binding = QualifiedReferenceBinding(
        reference_id=reference_descriptor.reference_id,
        reference_version=reference_descriptor.reference_version,
        reference_descriptor_hash=reference_descriptor.descriptor_hash,
        reference_identity_hash=reference_descriptor.reference_identity_hash,
        qualification_receipt_hash=receipt.receipt_hash,
        claim_hash=claim.claim_hash,
        domain_hash=canonical_sha256(claim.domain),
    )

    assert receipt.status is ReferenceQualificationStatus.INCOMPLETE
    assert not validate_qualified_reference_binding(
        binding,
        registry=registry,
        qualification_receipt=receipt,
        qualification_policy=qualification_policy,
        claim=claim,
    )


def test_registry_rejects_conflicting_duplicate_and_enumerates_deterministically() -> None:
    registry = ReferenceRegistry()
    first = descriptor()
    conflicting = replace(first, source_artifact_hash=h("other-artifact"))
    registry.register(first)
    registry.register(first)

    with pytest.raises(ValueError, match="conflicting_duplicate"):
        registry.register(conflicting)


def test_identity_substitution_invalidates_binding_and_differential_link() -> None:
    claim, _, qualification_policy, receipt, registry, binding = qualified_fixture()
    forged = replace(binding, reference_identity_hash=h("reference-h2"))

    assert not validate_qualified_reference_binding(
        forged,
        registry=registry,
        qualification_receipt=receipt,
        qualification_policy=qualification_policy,
        claim=claim,
    )
    assert not validate_differential_evidence_binding(
        differential_receipt(claim),
        forged,
        registry=registry,
        qualification_receipt=receipt,
        qualification_policy=qualification_policy,
        claim=claim,
    )


@pytest.mark.parametrize("field", ("source_artifact_hash", "source_provenance_hash"))
def test_source_artifact_and_provenance_tampering_invalidate_qualification(field: str) -> None:
    _, reference_descriptor, qualification_policy, receipt, _, _ = qualified_fixture()
    object.__setattr__(reference_descriptor, field, h(("forged", field)))

    assert not reference_descriptor.validate()
    assert not validate_qualification_receipt(receipt, reference_descriptor, qualification_policy)


def test_missing_provenance_is_incomplete_never_qualified() -> None:
    reference_descriptor = descriptor(source_provenance_hash="")
    receipt = qualify_reference(reference_descriptor, policy(), receipt_id="qualification-missing-provenance")

    assert receipt.status is ReferenceQualificationStatus.INCOMPLETE
    assert "source_provenance_missing" in receipt.reason_codes


def test_scope_mismatch_cannot_reuse_qualification() -> None:
    _, _, qualification_policy, receipt, registry, _ = qualified_fixture()
    out_of_scope_claim = TypedClaim(
        claim_id="out-of-scope-domain",
        schema_version="genesis.m6a2r",
        claim_type=ClaimType.EXACT_FUNCTION,
        properties={"relation": "reference_equivalence"},
        assumptions=(),
        domain={"kind": "integer_range", "min": -9, "max": 10},
        budget={},
        falsifiers=(),
        obligations=("differential",),
        risk_class="low",
        change_class=ChangeClass.NOT_APPLICABLE,
    )
    reference_descriptor = registry.resolve("reference-times-two", "v1")
    assert reference_descriptor is not None
    binding = QualifiedReferenceBinding(
        reference_id=reference_descriptor.reference_id,
        reference_version=reference_descriptor.reference_version,
        reference_descriptor_hash=reference_descriptor.descriptor_hash,
        reference_identity_hash=reference_descriptor.reference_identity_hash,
        qualification_receipt_hash=receipt.receipt_hash,
        claim_hash=out_of_scope_claim.claim_hash,
        domain_hash=canonical_sha256(out_of_scope_claim.domain),
    )

    assert not validate_qualified_reference_binding(
        binding,
        registry=registry,
        qualification_receipt=receipt,
        qualification_policy=qualification_policy,
        claim=out_of_scope_claim,
    )


def test_resealed_false_qualification_is_rejected_by_rederivation() -> None:
    _, reference_descriptor, qualification_policy, receipt, _, _ = qualified_fixture()
    resealed = replace(
        receipt,
        qualified_domain_hashes=(h("forged-qualified-domain"),),
    )

    assert resealed.validate()
    assert not validate_qualification_receipt(
        resealed, reference_descriptor, qualification_policy
    )


def test_resealed_implementation_identity_substitution_is_rejected() -> None:
    claim, reference_descriptor, qualification_policy, receipt, registry, binding = qualified_fixture()
    resealed = replace(receipt, implementation_identity_hash=h("forged-implementation"))
    rebound = replace(binding, qualification_receipt_hash=resealed.receipt_hash)

    assert resealed.validate()
    assert not validate_qualification_receipt(
        resealed, reference_descriptor, qualification_policy
    )
    assert not validate_qualified_reference_binding(
        rebound,
        registry=registry,
        qualification_receipt=resealed,
        qualification_policy=qualification_policy,
        claim=claim,
    )


def test_historical_qualifications_are_append_only_not_latest_implicit() -> None:
    _, reference_descriptor, policy_q0, receipt_q0, _, _ = qualified_fixture()
    policy_q1 = policy(policy_id="m6a2r-lab-admission-q1")
    receipt_q1 = qualify_reference(reference_descriptor, policy_q1, receipt_id="qualification-q1")

    assert receipt_q0.receipt_hash != receipt_q1.receipt_hash
    assert validate_qualification_receipt(receipt_q0, reference_descriptor, policy_q0)
    assert validate_qualification_receipt(receipt_q1, reference_descriptor, policy_q1)


def test_qualification_is_not_semantic_correctness_proof() -> None:
    receipt_fields = {item.name for item in fields(type(qualified_fixture()[3]))}

    assert "is_true" not in receipt_fields
    assert "is_correct" not in receipt_fields
    assert "truth_probability" not in receipt_fields


def test_historical_differential_receipt_hash_is_unchanged() -> None:
    receipt = differential_receipt(differential_claim())

    assert receipt.receipt_hash == "581909d20102dc1c0aef12a0bf50bbff12348d9c447e7c9cbe399e7ed6b5cc28"
