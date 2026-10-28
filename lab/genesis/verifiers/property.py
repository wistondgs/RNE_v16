"""Finite, declarative property verification without a reference function."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping

from lab.genesis.contracts.claims import ClaimType, TypedClaim
from lab.genesis.contracts.receipts import ReceiptStatus, VerifierReceipt
from lab.genesis.contracts.serialization import canonical_sha256, freeze
from lab.genesis.verifiers.bindings import canonical_execution_context_hash
from lab.genesis.verifiers.descriptor import VerifierImplementationIdentity


class PropertyKind(str, Enum):
    NON_NEGATIVE = "NON_NEGATIVE"
    MONOTONIC_NON_DECREASING = "MONOTONIC_NON_DECREASING"
    BOUNDED_RANGE = "BOUNDED_RANGE"


@dataclass(frozen=True, slots=True)
class PropertySpec:
    """A sealed, non-executable property declaration for one finite domain."""

    property_id: str
    schema_version: str
    property_kind: PropertyKind
    parameters: Mapping[str, Any]
    domain_hash: str
    parameters_hash: str = field(init=False)
    spec_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "property_kind", PropertyKind(self.property_kind))
        object.__setattr__(self, "parameters", freeze(self.parameters))
        object.__setattr__(
            self, "parameters_hash", canonical_sha256(self.parameters)
        )
        object.__setattr__(self, "spec_hash", canonical_sha256(self.canonical_payload()))

    @classmethod
    def for_domain(
        cls,
        *,
        property_id: str,
        schema_version: str,
        property_kind: PropertyKind,
        parameters: Mapping[str, Any],
        domain: Mapping[str, Any],
    ) -> "PropertySpec":
        return cls(
            property_id=property_id,
            schema_version=schema_version,
            property_kind=property_kind,
            parameters=parameters,
            domain_hash=canonical_sha256(domain),
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "property_id": self.property_id,
            "schema_version": self.schema_version,
            "property_kind": self.property_kind.value,
            "parameters_hash": self.parameters_hash,
            "domain_hash": self.domain_hash,
        }

    def validate(self) -> bool:
        return (
            self.parameters_hash == canonical_sha256(self.parameters)
            and self.spec_hash == canonical_sha256(self.canonical_payload())
        )


class PropertyVerifier:
    """Exhaustively evaluate one sealed property over a finite integer domain."""

    verifier_id = "genesis.property_function"
    verifier_version = "v1"
    deterministic = True
    _supported_relation = "property_check"

    def __init__(self, property_spec: PropertySpec) -> None:
        self.property_spec = property_spec

    @classmethod
    def implementation_identity(cls) -> VerifierImplementationIdentity:
        module_path = Path(__file__)
        return VerifierImplementationIdentity(
            module_relative_path="lab/genesis/verifiers/property.py",
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
                self._coverage(0, 0),
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
                self._coverage(0, 0),
                "unsupported_property_specification",
            )
        binding_error = self._binding_error(claim, context)
        if binding_error is not None:
            return self._receipt(
                claim,
                plan_hash,
                snapshot_hash,
                ReceiptStatus.ERROR,
                bindings,
                (),
                self._coverage(0, 0),
                binding_error,
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
                self._coverage(0, 0),
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
                self._coverage(0, len(domain)),
                "candidate_not_callable",
            )

        parameter_error = self._parameter_error()
        if parameter_error is not None:
            return self._receipt(
                claim,
                plan_hash,
                snapshot_hash,
                ReceiptStatus.ERROR,
                bindings,
                (),
                self._coverage(0, len(domain)),
                parameter_error,
            )

        try:
            outputs = self._evaluate(candidate, domain)
            counterexamples = self._counterexamples(domain, outputs)
        except Exception as exc:
            evaluated = getattr(exc, "evaluated_inputs", 0)
            return self._receipt(
                claim,
                plan_hash,
                snapshot_hash,
                ReceiptStatus.ERROR,
                bindings,
                (),
                self._coverage(evaluated, len(domain)),
                f"execution_error:{type(exc).__name__}",
            )

        return self._receipt(
            claim,
            plan_hash,
            snapshot_hash,
            ReceiptStatus.PASS if not counterexamples else ReceiptStatus.FAIL,
            bindings,
            tuple(counterexamples),
            self._coverage(len(outputs), len(domain)),
            None,
        )

    def _bindings(self, claim: TypedClaim, context: Mapping[str, Any]) -> dict[str, str]:
        return {
            "relation": self._supported_relation,
            "property_kind": self.property_spec.property_kind.value,
            "property_spec_hash": self.property_spec.spec_hash,
            "parameters_hash": self.property_spec.parameters_hash,
            "candidate_identity_hash": str(context.get("candidate_identity_hash", "")),
            "domain_hash": canonical_sha256(claim.domain),
            "context_hash": str(context.get("context_hash", "")),
        }

    def _binding_error(self, claim: TypedClaim, context: Mapping[str, Any]) -> str | None:
        if not self.property_spec.validate():
            return "property_spec_invalid"
        if claim.properties.get("property_spec_hash") != self.property_spec.spec_hash:
            return "claim_property_spec_mismatch"
        if canonical_sha256(claim.domain) != self.property_spec.domain_hash:
            return "property_domain_mismatch"
        candidate_identity_hash = context.get("candidate_identity_hash")
        if not isinstance(candidate_identity_hash, str) or not candidate_identity_hash:
            return "candidate_identity_hash_missing"
        if context.get("property_spec_hash") != self.property_spec.spec_hash:
            return "context_property_spec_mismatch"
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

    def _parameter_error(self) -> str | None:
        if self.property_spec.property_kind is not PropertyKind.BOUNDED_RANGE:
            return None
        lower = self.property_spec.parameters.get("lower")
        upper = self.property_spec.parameters.get("upper")
        if not self._is_finite_number(lower) or not self._is_finite_number(upper):
            return "bounded_range_parameters_invalid"
        if lower > upper:
            return "bounded_range_parameters_invalid"
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
    def _is_finite_number(value: Any) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and (
            not isinstance(value, float) or math.isfinite(value)
        )

    def _evaluate(
        self, candidate: Callable[[int], Any], domain: range
    ) -> tuple[Any, ...]:
        outputs: list[Any] = []
        for value in domain:
            try:
                output = candidate(value)
            except Exception as exc:
                setattr(exc, "evaluated_inputs", len(outputs))
                raise
            if not self._is_finite_number(output):
                error = TypeError("property_output_not_finite_number")
                setattr(error, "evaluated_inputs", len(outputs) + 1)
                raise error
            outputs.append(output)
        return tuple(outputs)

    def _counterexamples(
        self, domain: range, outputs: tuple[Any, ...]
    ) -> list[Mapping[str, Any]]:
        if self.property_spec.property_kind is PropertyKind.NON_NEGATIVE:
            return [
                {"input": value, "output": output}
                for value, output in zip(domain, outputs)
                if output < 0
            ]
        if self.property_spec.property_kind is PropertyKind.MONOTONIC_NON_DECREASING:
            # In a totally ordered finite domain, adjacent non-decreasing pairs
            # imply the same relation for every earlier/later pair by transitivity.
            return [
                {
                    "left_input": domain[index - 1],
                    "left_output": outputs[index - 1],
                    "right_input": domain[index],
                    "right_output": outputs[index],
                }
                for index in range(1, len(outputs))
                if outputs[index - 1] > outputs[index]
            ]
        if self.property_spec.property_kind is PropertyKind.BOUNDED_RANGE:
            lower = self.property_spec.parameters["lower"]
            upper = self.property_spec.parameters["upper"]
            return [
                {
                    "input": value,
                    "output": output,
                    "lower": lower,
                    "upper": upper,
                }
                for value, output in zip(domain, outputs)
                if output < lower or output > upper
            ]
        raise ValueError("unsupported_property_kind")

    @staticmethod
    def _coverage(evaluated_inputs: int, declared_inputs: int) -> dict[str, int]:
        return {
            "evaluated_inputs": evaluated_inputs,
            "declared_inputs": declared_inputs,
        }

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
            receipt_id=f"property-receipt-{claim.claim_hash}-{self.property_spec.spec_hash}",
            schema_version="genesis-property-receipt-v1",
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
