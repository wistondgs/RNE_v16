"""A safe exhaustive verifier for finite EXACT_FUNCTION claims."""

from __future__ import annotations

from typing import Any, Mapping

from lab.genesis.contracts.claims import ClaimType, TypedClaim
from lab.genesis.contracts.receipts import ReceiptStatus, VerifierReceipt


class ExactVerifier:
    verifier_id = "genesis.exact_function"
    verifier_version = "v1"

    def verify(self, claim: TypedClaim, candidate: Any, context: Mapping[str, Any]) -> VerifierReceipt:
        plan_hash = str(context.get("plan_hash", ""))
        snapshot_hash = str(context.get("snapshot_hash", ""))
        if claim.claim_type is not ClaimType.EXACT_FUNCTION:
            return self._receipt(claim, plan_hash, snapshot_hash, ReceiptStatus.UNKNOWN, {}, (), {"checked": 0, "total": 0}, "unsupported_claim_type")
        if not callable(candidate):
            return self._receipt(claim, plan_hash, snapshot_hash, ReceiptStatus.ERROR, {}, (), {"checked": 0, "total": 0}, "candidate_not_callable")
        domain = claim.domain
        properties = claim.properties
        if domain.get("kind") != "integer_range" or properties.get("relation") != "output_eq_input_plus":
            return self._receipt(claim, plan_hash, snapshot_hash, ReceiptStatus.UNKNOWN, {}, (), {"checked": 0, "total": 0}, "unsupported_exact_specification")
        lower, upper, delta = int(domain["min"]), int(domain["max"]), int(properties.get("delta", 1))
        counterexamples: list[Mapping[str, Any]] = []
        checked = 0
        try:
            for value in range(lower, upper + 1):
                output = candidate(value)
                checked += 1
                expected = value + delta
                if output != expected:
                    counterexamples.append({"input": value, "expected": expected, "actual": output})
        except Exception as exc:
            return self._receipt(claim, plan_hash, snapshot_hash, ReceiptStatus.ERROR, {}, tuple(counterexamples), {"checked": checked, "total": upper - lower + 1}, type(exc).__name__)
        status = ReceiptStatus.PASS if not counterexamples else ReceiptStatus.FAIL
        return self._receipt(claim, plan_hash, snapshot_hash, status, {"domain": [lower, upper], "relation": "output_eq_input_plus", "delta": delta}, tuple(counterexamples), {"checked": checked, "total": upper - lower + 1}, None)

    def _receipt(self, claim: TypedClaim, plan_hash: str, snapshot_hash: str, status: ReceiptStatus, evidence: Mapping[str, Any], counterexamples: tuple[Mapping[str, Any], ...], coverage: Mapping[str, Any], reason: str | None) -> VerifierReceipt:
        return VerifierReceipt(receipt_id=f"receipt-{claim.claim_id}", schema_version="genesis-verifier-receipt-v1", claim_hash=claim.claim_hash, plan_hash=plan_hash, snapshot_hash=snapshot_hash, verifier_id=self.verifier_id, verifier_version=self.verifier_version, status=status, evidence={**dict(evidence), "reason": reason}, counterexamples=counterexamples, coverage=coverage, assumptions_active=claim.assumptions, cost={"evaluations": coverage.get("checked", 0)})
