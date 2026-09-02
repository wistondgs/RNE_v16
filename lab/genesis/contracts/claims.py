"""Typed, immutable scientific claims."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from .serialization import canonical_sha256, freeze


class ClaimType(str, Enum):
    EXACT_FUNCTION = "EXACT_FUNCTION"
    PROGRAM_TRANSFORMATION = "PROGRAM_TRANSFORMATION"
    LOGICAL_THEOREM = "LOGICAL_THEOREM"
    STATISTICAL_PREDICTOR = "STATISTICAL_PREDICTOR"
    CAUSAL_HYPOTHESIS = "CAUSAL_HYPOTHESIS"
    PLANNING_POLICY = "PLANNING_POLICY"
    SKILL = "SKILL"
    REPRESENTATION = "REPRESENTATION"
    META_IMPROVER = "META_IMPROVER"
    LEARNING_RULE_PATCH = "LEARNING_RULE_PATCH"


class ChangeClass(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    LEARNING_RULE = "LEARNING_RULE"
    RUN_SIDE = "RUN_SIDE"
    MIXED = "MIXED"


@dataclass(frozen=True, slots=True)
class TypedClaim:
    claim_id: str
    schema_version: str
    claim_type: ClaimType
    properties: Mapping[str, Any]
    assumptions: tuple[str, ...]
    domain: Mapping[str, Any]
    budget: Mapping[str, Any]
    falsifiers: tuple[str, ...]
    obligations: tuple[str, ...]
    risk_class: str
    change_class: ChangeClass

    def __post_init__(self) -> None:
        object.__setattr__(self, "claim_type", ClaimType(self.claim_type))
        object.__setattr__(self, "change_class", ChangeClass(self.change_class))
        if self.claim_type is ClaimType.LEARNING_RULE_PATCH and self.change_class not in {ChangeClass.LEARNING_RULE, ChangeClass.MIXED}:
            raise ValueError("genesis_learning_rule_patch_requires_learning_rule_change")
        object.__setattr__(self, "properties", freeze(self.properties))
        object.__setattr__(self, "assumptions", tuple(self.assumptions))
        object.__setattr__(self, "domain", freeze(self.domain))
        object.__setattr__(self, "budget", freeze(self.budget))
        object.__setattr__(self, "falsifiers", tuple(self.falsifiers))
        object.__setattr__(self, "obligations", tuple(self.obligations))

    def canonical_payload(self) -> dict[str, Any]:
        return {"claim_id": self.claim_id, "schema_version": self.schema_version, "claim_type": self.claim_type.value, "properties": self.properties, "assumptions": self.assumptions, "domain": self.domain, "budget": self.budget, "falsifiers": self.falsifiers, "obligations": self.obligations, "risk_class": self.risk_class, "change_class": self.change_class.value}

    @property
    def claim_hash(self) -> str:
        return canonical_sha256(self.canonical_payload())
