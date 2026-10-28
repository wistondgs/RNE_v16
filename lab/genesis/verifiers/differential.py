"""Deterministic verification against a trusted finite-domain reference.

This verifier deliberately has a different competence boundary from
``ExactVerifier``.  It checks only a finite, declarative integer domain and
only by comparing a candidate with a reference supplied by the trusted
evaluator.  The candidate is called with an input value alone: it is never
given the execution context, reference callable, or reference outputs.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Callable, Mapping

from lab.genesis.contracts.claims import ClaimType, TypedClaim
from lab.genesis.contracts.receipts import ReceiptStatus, VerifierReceipt
from lab.genesis.contracts.serialization import canonical_json_bytes, canonical_sha256
from lab.genesis.verifiers.bindings import canonical_execution_context_hash
from lab.genesis.verifiers.descriptor import VerifierImplementationIdentity


class DifferentialVerifier:
    """Compare a candidate and trusted reference over a sealed finite domain."""

    verifier_id = "genesis.differential_function"
    verifier_version = "v1"
    deterministic = True
    _supported_relation = "reference_equivalence"

    def __init__(
        self,
        trusted_reference: Callable[[int], Any],
        *,
        reference_identity_hash: str,
    ) -> None:
        if not callable(trusted_reference):
            raise ValueError("genesis_differential_reference_not_callable")
        if not isinstance(reference_identity_hash, str) or not reference_identity_hash:
            raise ValueError("genesis_differential_reference_identity_invalid")
        self._trusted_reference = trusted_reference
        self.reference_identity_hash = reference_identity_hash

    @classmethod
    def implementation_identity(cls) -> VerifierImplementationIdentity:
        """Return a stable identity for this implementation, not a callable address."""

        module_path = Path(__file__)
        return VerifierImplementationIdentity(
            module_relative_path="lab/genesis/verifiers/differential.py",
            symbol_name=cls.__name__,
            module_content_hash=hashlib.sha256(module_path.read_bytes()).hexdigest(),
            declared_version=cls.verifier_version,
        )

    def verify(
        self,
        claim: TypedClaim,
        candidate: Any,
        context: Mapping[str, Any],
    ) -> VerifierReceipt:
        plan_hash = str(context.get("plan_hash", ""))
        snapshot_hash = str(context.get("snapshot_hash", ""))
        bindings = self._bindings(claim, context)

        if claim.claim_type is not ClaimType.EXACT_FUNCTION:
            return self._receipt(
                claim,
                plan_hash,
                snapshot_hash,
                ReceiptStatus.UNKNOWN,
                bindings,
                (),
                {"evaluated_inputs": 0, "declared_inputs": 0},
                "unsupported_claim_type",
            )
        if claim.properties.get("relation") != self._supported_relation:
            return self._receipt(
                claim,
                plan_hash,
                snapshot_hash,
                ReceiptStatus.UNKNOWN,
                bindings,
                (),
                {"evaluated_inputs": 0, "declared_inputs": 0},
                "unsupported_differential_specification",
            )

        domain = self._integer_domain(claim.domain)
        if domain is None:
            return self._receipt(
                claim,
                plan_hash,
                snapshot_hash,
                ReceiptStatus.UNKNOWN,
                bindings,
                (),
                {"evaluated_inputs": 0, "declared_inputs": 0},
                "unsupported_finite_domain",
            )
        if not callable(candidate):
            return self._receipt(
                claim,
                plan_hash,
                snapshot_hash,
                ReceiptStatus.ERROR,
                bindings,
                (),
                {"evaluated_inputs": 0, "declared_inputs": len(domain)},
                "candidate_not_callable",
            )
        missing_binding = self._missing_binding(claim, context)
        if missing_binding is not None:
            return self._receipt(
                claim,
                plan_hash,
                snapshot_hash,
                ReceiptStatus.ERROR,
                bindings,
                (),
                {"evaluated_inputs": 0, "declared_inputs": len(domain)},
                missing_binding,
            )

        counterexamples: list[Mapping[str, Any]] = []
        evaluated = 0
        try:
            for value in domain:
                # The candidate's entire visible interface is this one input.
                candidate_output = candidate(value)
                reference_output = self._trusted_reference(value)
                evaluated += 1
                if canonical_json_bytes(candidate_output) != canonical_json_bytes(
                    reference_output
                ):
                    counterexamples.append(
                        {
                            "input": value,
                            "candidate_output": candidate_output,
                            "reference_output": reference_output,
                        }
                    )
        except Exception as exc:
            return self._receipt(
                claim,
                plan_hash,
                snapshot_hash,
                ReceiptStatus.ERROR,
                bindings,
                tuple(counterexamples),
                {"evaluated_inputs": evaluated, "declared_inputs": len(domain)},
                f"execution_error:{type(exc).__name__}",
            )

        return self._receipt(
            claim,
            plan_hash,
            snapshot_hash,
            ReceiptStatus.PASS if not counterexamples else ReceiptStatus.FAIL,
            bindings,
            tuple(counterexamples),
            {"evaluated_inputs": evaluated, "declared_inputs": len(domain)},
            None,
        )

    def _bindings(self, claim: TypedClaim, context: Mapping[str, Any]) -> dict[str, str]:
        return {
            "relation": self._supported_relation,
            "candidate_identity_hash": str(context.get("candidate_identity_hash", "")),
            "reference_identity_hash": self.reference_identity_hash,
            "domain_hash": canonical_sha256(claim.domain),
            "context_hash": str(context.get("context_hash", "")),
        }

    def _missing_binding(
        self, claim: TypedClaim, context: Mapping[str, Any]
    ) -> str | None:
        if not isinstance(context.get("candidate_identity_hash"), str) or not context[
            "candidate_identity_hash"
        ]:
            return "candidate_identity_hash_missing"
        if context.get("reference_identity_hash") != self.reference_identity_hash:
            return "reference_identity_hash_mismatch"
        if not isinstance(context.get("context_hash"), str) or not context["context_hash"]:
            return "context_hash_missing"
        context_claim = context.get("claim")
        if (
            not isinstance(context_claim, TypedClaim)
            or context_claim.claim_hash != claim.claim_hash
        ):
            return "claim_context_mismatch"
        if canonical_execution_context_hash(
            claim.claim_hash, context["candidate_identity_hash"], context
        ) != context["context_hash"]:
            return "context_hash_invalid"
        return None

    @staticmethod
    def _integer_domain(domain: Mapping[str, Any]) -> range | None:
        if domain.get("kind") != "integer_range":
            return None
        lower = domain.get("min")
        upper = domain.get("max")
        if (
            not isinstance(lower, int)
            or isinstance(lower, bool)
            or not isinstance(upper, int)
            or isinstance(upper, bool)
            or lower > upper
        ):
            return None
        return range(lower, upper + 1)

    def _receipt(
        self,
        claim: TypedClaim,
        plan_hash: str,
        snapshot_hash: str,
        status: ReceiptStatus,
        bindings: Mapping[str, str],
        counterexamples: tuple[Mapping[str, Any], ...],
        coverage: Mapping[str, int],
        reason: str | None,
    ) -> VerifierReceipt:
        return VerifierReceipt(
            receipt_id=f"differential-receipt-{claim.claim_hash}",
            schema_version="genesis-differential-receipt-v1",
            claim_hash=claim.claim_hash,
            plan_hash=plan_hash,
            snapshot_hash=snapshot_hash,
            verifier_id=self.verifier_id,
            verifier_version=self.verifier_version,
            status=status,
            evidence={**dict(bindings), "reason": reason},
            counterexamples=counterexamples,
            coverage=coverage,
            assumptions_active=claim.assumptions,
            cost={"evaluations": coverage["evaluated_inputs"]},
        )
