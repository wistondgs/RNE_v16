"""Deterministic, explicitly partial heuristic verification for Genesis."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from lab.genesis.contracts.claims import ClaimType, TypedClaim
from lab.genesis.contracts.receipts import ReceiptStatus, VerifierReceipt
from lab.genesis.contracts.serialization import canonical_sha256, freeze
from lab.genesis.verifiers.bindings import canonical_execution_context_hash
from lab.genesis.verifiers.descriptor import VerifierImplementationIdentity


class HeuristicPolicyKind(str, Enum):
    DETERMINISTIC_PROBES = "DETERMINISTIC_PROBES"


@dataclass(frozen=True, slots=True)
class HeuristicPolicySpec:
    """Sealed, non-executable policy for deterministic probe selection."""

    policy_id: str
    schema_version: str
    policy_kind: HeuristicPolicyKind
    parameters: Mapping[str, Any]
    domain_hash: str
    parameters_hash: str = field(init=False)
    policy_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_kind", HeuristicPolicyKind(self.policy_kind))
        object.__setattr__(self, "parameters", freeze(self.parameters))
        object.__setattr__(self, "parameters_hash", canonical_sha256(self.parameters))
        object.__setattr__(self, "policy_hash", canonical_sha256(self.canonical_payload()))

    @classmethod
    def for_domain(
        cls,
        *,
        policy_id: str,
        schema_version: str,
        domain: Mapping[str, Any],
        parameters: Mapping[str, Any] | None = None,
    ) -> "HeuristicPolicySpec":
        return cls(
            policy_id=policy_id,
            schema_version=schema_version,
            policy_kind=HeuristicPolicyKind.DETERMINISTIC_PROBES,
            parameters=parameters or {"selection": "first_middle_last"},
            domain_hash=canonical_sha256(domain),
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "schema_version": self.schema_version,
            "policy_kind": (
                self.policy_kind.value
                if isinstance(self.policy_kind, HeuristicPolicyKind)
                else str(self.policy_kind)
            ),
            "parameters_hash": self.parameters_hash,
            "domain_hash": self.domain_hash,
        }

    def validate(self) -> bool:
        return (
            self.parameters_hash == canonical_sha256(self.parameters)
            and self.policy_hash == canonical_sha256(self.canonical_payload())
        )


class HeuristicVerifier:
    """Check ``output_eq_input_plus`` only at deterministically chosen probes.

    A PASS means no violation was found in the selected probes, not that the
    relation was proven over the declared domain.  This deliberately partial
    competence is why this verifier must remain non-sovereign.
    """

    verifier_id = "genesis.heuristic_probe"
    verifier_version = "v1"
    deterministic = True
    _supported_relation = "output_eq_input_plus"

    def __init__(self, policy: HeuristicPolicySpec) -> None:
        self.policy = policy

    @classmethod
    def implementation_identity(cls) -> VerifierImplementationIdentity:
        module_path = Path(__file__)
        return VerifierImplementationIdentity(
            module_relative_path="lab/genesis/verifiers/heuristic.py",
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
                claim, plan_hash, snapshot_hash, ReceiptStatus.UNKNOWN, bindings, (), self._coverage((), 0), "unsupported_claim_type"
            )
        delta = claim.properties.get("delta")
        if (
            claim.properties.get("relation") != self._supported_relation
            or not isinstance(delta, int)
            or isinstance(delta, bool)
        ):
            return self._receipt(
                claim, plan_hash, snapshot_hash, ReceiptStatus.UNKNOWN, bindings, (), self._coverage((), 0), "unsupported_heuristic_specification"
            )
        binding_error = self._binding_error(claim, context)
        if binding_error is not None:
            return self._receipt(
                claim, plan_hash, snapshot_hash, ReceiptStatus.ERROR, bindings, (), self._coverage((), 0), binding_error
            )
        domain = self._integer_domain(claim.domain)
        if domain is None:
            return self._receipt(
                claim, plan_hash, snapshot_hash, ReceiptStatus.UNKNOWN, bindings, (), self._coverage((), 0), "unsupported_finite_domain"
            )
        if not callable(candidate):
            return self._receipt(
                claim, plan_hash, snapshot_hash, ReceiptStatus.ERROR, bindings, (), self._coverage((), len(domain)), "candidate_not_callable"
            )
        if self._policy_error() is not None:
            return self._receipt(
                claim, plan_hash, snapshot_hash, ReceiptStatus.ERROR, bindings, (), self._coverage((), len(domain)), self._policy_error()
            )

        probes = self.probe_inputs(claim.domain)
        counterexamples: list[Mapping[str, Any]] = []
        evaluated = 0
        try:
            for value in probes:
                actual = candidate(value)
                evaluated += 1
                expected = value + delta
                if actual != expected:
                    counterexamples.append(
                        {"input": value, "expected": expected, "actual": actual}
                    )
        except Exception as exc:
            return self._receipt(
                claim,
                plan_hash,
                snapshot_hash,
                ReceiptStatus.ERROR,
                bindings,
                tuple(counterexamples),
                self._coverage(probes[:evaluated], len(domain)),
                f"execution_error:{type(exc).__name__}",
            )

        return self._receipt(
            claim,
            plan_hash,
            snapshot_hash,
            ReceiptStatus.PASS if not counterexamples else ReceiptStatus.FAIL,
            bindings,
            tuple(counterexamples),
            self._coverage(probes, len(domain)),
            None,
        )

    def probe_inputs(self, domain: Mapping[str, Any]) -> tuple[int, ...]:
        """Derive canonical first/middle/last probes from the finite domain."""

        values = self._integer_domain(domain)
        if values is None or self._policy_error() is not None:
            return ()
        candidates = (values[0], values[len(values) // 2], values[-1])
        return tuple(dict.fromkeys(candidates))

    def _bindings(self, claim: TypedClaim, context: Mapping[str, Any]) -> dict[str, str]:
        return {
            "relation": self._supported_relation,
            "policy_kind": (
                self.policy.policy_kind.value
                if isinstance(self.policy.policy_kind, HeuristicPolicyKind)
                else str(self.policy.policy_kind)
            ),
            "policy_hash": self.policy.policy_hash,
            "parameters_hash": self.policy.parameters_hash,
            "candidate_identity_hash": str(context.get("candidate_identity_hash", "")),
            "domain_hash": canonical_sha256(claim.domain),
            "context_hash": str(context.get("context_hash", "")),
            "full_domain_verified": "false",
        }

    def _binding_error(self, claim: TypedClaim, context: Mapping[str, Any]) -> str | None:
        if not self.policy.validate():
            return "heuristic_policy_invalid"
        if claim.properties.get("heuristic_policy_hash") != self.policy.policy_hash:
            return "claim_policy_mismatch"
        if canonical_sha256(claim.domain) != self.policy.domain_hash:
            return "policy_domain_mismatch"
        candidate_identity_hash = context.get("candidate_identity_hash")
        if not isinstance(candidate_identity_hash, str) or not candidate_identity_hash:
            return "candidate_identity_hash_missing"
        if context.get("heuristic_policy_hash") != self.policy.policy_hash:
            return "context_policy_mismatch"
        context_hash = context.get("context_hash")
        if not isinstance(context_hash, str) or not context_hash:
            return "context_hash_missing"
        context_claim = context.get("claim")
        if (
            not isinstance(context_claim, TypedClaim)
            or context_claim.claim_hash != claim.claim_hash
        ):
            return "claim_context_mismatch"
        if (
            canonical_execution_context_hash(claim.claim_hash, candidate_identity_hash, context)
            != context_hash
        ):
            return "context_hash_invalid"
        return None

    def _policy_error(self) -> str | None:
        if self.policy.policy_kind is not HeuristicPolicyKind.DETERMINISTIC_PROBES:
            return "unsupported_heuristic_policy"
        if self.policy.parameters.get("selection") != "first_middle_last":
            return "heuristic_policy_parameters_invalid"
        return None

    @staticmethod
    def _integer_domain(domain: Mapping[str, Any]) -> range | None:
        if domain.get("kind") != "integer_range":
            return None
        lower, upper = domain.get("min"), domain.get("max")
        if (
            not isinstance(lower, int)
            or isinstance(lower, bool)
            or not isinstance(upper, int)
            or isinstance(upper, bool)
            or lower > upper
        ):
            return None
        return range(lower, upper + 1)

    @staticmethod
    def _coverage(probes: tuple[int, ...], declared_domain_size: int) -> dict[str, Any]:
        return {
            "declared_domain_size": declared_domain_size,
            "probes_evaluated": len(probes),
            "probe_inputs_hash": canonical_sha256(probes),
            "probe_coverage": {
                "numerator": len(probes),
                "denominator": declared_domain_size,
            },
        }

    def _receipt(
        self,
        claim: TypedClaim,
        plan_hash: str,
        snapshot_hash: str,
        status: ReceiptStatus,
        bindings: Mapping[str, str],
        counterexamples: tuple[Mapping[str, Any], ...],
        coverage: Mapping[str, Any],
        reason: str | None,
    ) -> VerifierReceipt:
        return VerifierReceipt(
            receipt_id=f"heuristic-receipt-{claim.claim_hash}-{self.policy.policy_hash}",
            schema_version="genesis-heuristic-receipt-v1",
            claim_hash=claim.claim_hash,
            plan_hash=plan_hash,
            snapshot_hash=snapshot_hash,
            verifier_id=self.verifier_id,
            verifier_version=self.verifier_version,
            status=status,
            evidence={
                **dict(bindings),
                "full_domain_verified": False,
                "probe_coverage": coverage["probe_coverage"],
                "reason": reason,
            },
            counterexamples=counterexamples,
            coverage=coverage,
            assumptions_active=claim.assumptions,
            cost={"evaluations": coverage["probes_evaluated"]},
        )
