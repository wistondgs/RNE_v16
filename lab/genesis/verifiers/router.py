"""Deterministic admission and feasible-subset selection for M6 verifier plans.

The router never invokes a verifier and deliberately has no verdict vocabulary.
"""
from __future__ import annotations

from itertools import combinations
from typing import Iterable
from enum import Enum

from lab.genesis.causal.cfi import CFIReport, CFIStatus
from lab.genesis.contracts.claims import TypedClaim
from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.contracts.verification import VerificationPlan
from .descriptor import VerifierDescriptor, VerifierKind, VerifierSovereignty
from .federation import (FederatedVerificationRequirement, IndependenceStatus, IntegrityStatus,
                         VerifierDependencyGraph, VerifierIntegrityReceipt, VerifierRegistry)
from .plan import FederationPlan, RequirementRoutingResult, RoutingStatus, SelectedVerifierBinding
from .references import (QualifiedReferenceBinding, ReferenceQualificationPolicy, ReferenceQualificationReceipt,
                         ReferenceRegistry, validate_qualified_reference_binding)
from .reliability import ReliabilityStatus, VerifierReliabilityProfile
from .reliability_campaign import ReliabilityCampaignReceipt, validate_profile_binding

SELECTION_POLICY_HASH = canonical_sha256({"policy": "m6a3-exhaustive-smallest-lexical-v1"})


class PresentedVerifierStatus(str, Enum):
    ADMISSIBLE = "ADMISSIBLE"
    INADMISSIBLE_FOR_PLAN = "INADMISSIBLE_FOR_PLAN"


def validate_presented_verifier_against_binding(descriptor: VerifierDescriptor, binding: SelectedVerifierBinding,
                                                qualified_reference_binding_hash: str | None = None) -> str:
    if not binding.validate():
        return PresentedVerifierStatus.INADMISSIBLE_FOR_PLAN
    exact = (descriptor.verifier_id == binding.verifier_id and descriptor.verifier_version == binding.verifier_version
             and descriptor.descriptor_hash == binding.verifier_descriptor_hash
             and descriptor.implementation_identity_hash == binding.implementation_identity_hash)
    ref = binding.qualified_reference_binding_hash == qualified_reference_binding_hash
    return PresentedVerifierStatus.ADMISSIBLE if exact and ref else PresentedVerifierStatus.INADMISSIBLE_FOR_PLAN


class VerifierRouter:
    def __init__(self, *, claim: TypedClaim, verification_plan: VerificationPlan,
                 requirements: Iterable[FederatedVerificationRequirement], registry: VerifierRegistry,
                 dependency_graph: VerifierDependencyGraph, reliability_profiles: Iterable[VerifierReliabilityProfile],
                 campaign_receipts: Iterable[ReliabilityCampaignReceipt], integrity_receipts: Iterable[VerifierIntegrityReceipt],
                 qualified_reference_bindings: Iterable[QualifiedReferenceBinding] = (),
                 reference_registry: ReferenceRegistry | None = None,
                 qualification_receipts: Iterable[ReferenceQualificationReceipt] = (),
                 qualification_policies: Iterable[ReferenceQualificationPolicy] = (),
                 cfi_reports: Iterable[CFIReport] = ()) -> None:
        self.claim, self.verification_plan, self.requirements, self.registry, self.graph = claim, verification_plan, tuple(requirements), registry, dependency_graph
        self.profiles = tuple(reliability_profiles); self.campaigns = tuple(campaign_receipts); self.integrities = tuple(integrity_receipts)
        self.ref_bindings = tuple(qualified_reference_bindings); self.reference_registry = reference_registry
        self.qualification_receipts = tuple(qualification_receipts); self.qualification_policies = tuple(qualification_policies); self.cfi_reports = tuple(cfi_reports)

    def _integrity(self, d: VerifierDescriptor, p: VerifierReliabilityProfile):
        for r in self.integrities:
            if (r.receipt_hash == canonical_sha256(r.canonical_payload()) and r.status is IntegrityStatus.PASS
                    and r.verifier_descriptor_hash == d.descriptor_hash and r.expected_implementation_hash == d.implementation_identity_hash
                    and r.observed_implementation_hash == d.implementation_identity_hash and r.dependency_manifest_hash == d.dependency_manifest_hash
                    and r.reliability_profile_hash == p.profile_hash): return r
        return None

    def _profile(self, d: VerifierDescriptor):
        for p in self.profiles:
            if p.status is not ReliabilityStatus.CHARACTERIZED: continue
            for receipt in self.campaigns:
                if validate_profile_binding(p, receipt, d.descriptor_hash, d.implementation_identity_hash): return p
        return None

    def _reference(self, d: VerifierDescriptor):
        if d.verifier_kind is not VerifierKind.DIFFERENTIAL: return None, None
        if self.reference_registry is None: return None, "reference_registry_missing"
        seen = False
        for b in self.ref_bindings:
            for r in self.qualification_receipts:
                for p in self.qualification_policies:
                    if b.qualification_receipt_hash == r.receipt_hash:
                        seen = True
                        if validate_qualified_reference_binding(b, registry=self.reference_registry, qualification_receipt=r, qualification_policy=p, claim=self.claim): return b, None
        return None, "reference_invalid" if seen else "reference_missing"

    def _candidates(self, req):
        obligations = {x.obligation_id: x for x in self.verification_plan.obligations}
        obligation = obligations.get(req.obligation_id)
        if obligation is None or obligation.obligation_id not in self.claim.obligations:
            return (), "obligation_missing"
        raw = []
        for d in self.registry.compatible(req):
            if (self.claim.claim_type.value not in d.supported_claim_types or obligation.kind not in d.supported_obligation_kinds
                    or d.authority_class.value != obligation.required_authority
                    or (obligation.allowed_verifiers and d.verifier_id not in obligation.allowed_verifiers)
                    or (req.sovereign_required and d.sovereignty is not VerifierSovereignty.SOVEREIGN)): continue
            raw.append(d)
        return tuple(raw), None

    def _select(self, req, candidates):
        needed = max(req.min_qualifying_passes, req.min_independent_passes)
        for size in range(needed, len(candidates) + 1):
            for subset in combinations(candidates, size):
                independent = max((len(group) for n in range(1, len(subset)+1) for group in combinations(subset, n)
                                   if all(self._independent(a, b) for a, b in combinations(group, 2))), default=0)
                if len(subset) >= req.min_qualifying_passes and independent >= req.min_independent_passes: return subset
        return ()

    def _independent(self, a, b):
        if a[3] and b[3] and a[3].reference_identity_hash == b[3].reference_identity_hash: return False
        return self.graph.independence(a[0], b[0]) is IndependenceStatus.VERIFIED_INDEPENDENT

    def route(self) -> FederationPlan:
        results, bindings = [], []
        if self.verification_plan.claim_hash != self.claim.claim_hash: raise ValueError("genesis_router_claim_plan_mismatch")
        for req in sorted(self.requirements, key=lambda x: x.requirement_id):
            if req.requirement_hash != canonical_sha256(req.canonical_payload()): raise ValueError("genesis_router_requirement_invalid")
            if req.requires_cfi_pass and not any(x.status is CFIStatus.PASS and x.report_hash == canonical_sha256(x.canonical_payload()) for x in self.cfi_reports):
                results.append(self._result(req, RoutingStatus.INCOMPLETE_CFI, (), ("cfi_pass_missing",))); continue
            raw, error = self._candidates(req)
            if error: results.append(self._result(req, RoutingStatus.UNPLANNABLE_NO_COMPATIBLE, (), (error,))); continue
            if not raw: results.append(self._result(req, RoutingStatus.UNPLANNABLE_NO_COMPATIBLE, (), ("no_compatible_descriptor",))); continue
            admitted=[]; problems=[]
            for d in raw:
                p=self._profile(d)
                if not p: problems.append("reliability_missing"); continue
                i=self._integrity(d,p)
                if not i: problems.append("integrity_missing"); continue
                ref, err=self._reference(d)
                if err: problems.append(err); continue
                admitted.append((d,p,i,ref))
            if not admitted:
                status = RoutingStatus.ERROR_REFERENCE_INVALID if "reference_invalid" in problems else (RoutingStatus.INCOMPLETE_REFERENCE if any(x.startswith("reference_") for x in problems) else (RoutingStatus.INCOMPLETE_RELIABILITY if "reliability_missing" in problems else RoutingStatus.INCOMPLETE_INTEGRITY))
                results.append(self._result(req,status,(),tuple(sorted(set(problems))))); continue
            admitted.sort(key=lambda x:(x[0].descriptor_hash,x[0].implementation_identity_hash,x[3].binding_hash if x[3] else ""))
            selected=self._select(req,admitted)
            if not selected: results.append(self._result(req,RoutingStatus.INCOMPLETE_INDEPENDENCE,(),("independent_subset_unavailable",))); continue
            built=[]
            for d,p,i,ref in selected:
                b=SelectedVerifierBinding(req.requirement_id,d.verifier_id,d.verifier_version,d.verifier_kind.value,d.authority_class.value,d.sovereignty.value,d.descriptor_hash,d.implementation_identity_hash,i.receipt_hash,p.profile_hash,ref.binding_hash if ref else None)
                built.append(b); bindings.append(b)
            results.append(self._result(req,RoutingStatus.PLANNABLE,built,()))
        results=tuple(sorted(results,key=lambda x:x.requirement_id)); bindings=tuple(sorted(bindings,key=lambda x:x.binding_hash))
        selected_profile_hashes = tuple(sorted({x.reliability_profile_hash for x in bindings}))
        selected_integrity_hashes = tuple(sorted({x.integrity_receipt_hash for x in bindings}))
        selected_reference_hashes = tuple(sorted({x.qualified_reference_binding_hash for x in bindings if x.qualified_reference_binding_hash}))
        return FederationPlan("genesis-federation-plan-v1",self.claim.claim_hash,self.verification_plan.plan_hash,
                              tuple(sorted(x.requirement_hash for x in self.requirements)),results,bindings,self.graph.graph_hash,
                              selected_profile_hashes,selected_integrity_hashes,
                              selected_reference_hashes,tuple(sorted(x.report_hash for x in self.cfi_reports)),SELECTION_POLICY_HASH)

    def _result(self, req, status, selected, reasons):
        deps = [self.graph.graph_hash]
        for b in selected:
            if b.qualified_reference_binding_hash: deps.append(b.qualified_reference_binding_hash)
        return RequirementRoutingResult(req.requirement_id,req.requirement_hash,status,tuple(sorted(x.binding_hash for x in selected)),tuple(sorted(reasons)),tuple(sorted(deps)))


def validate_federation_plan(plan: FederationPlan, router: VerifierRouter) -> bool:
    """Re-derive the complete plan, rejecting a resealed but false selection."""
    if not plan.validate(): return False
    try: expected = router.route()
    except ValueError: return False
    return plan.plan_hash == expected.plan_hash and all(x.status is RoutingStatus.PLANNABLE for x in plan.routing_results)
