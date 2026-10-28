"""Predeclared M7 confirmatory GE-I policy contracts.

The policy is deliberately separate from an individual acquisition campaign:
it fixes the whole battery before any confirmatory candidate is synthesized.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from lab.genesis.contracts.serialization import canonical_sha256, freeze
from lab.genesis.evidence.artifacts import is_artifact_hash


CANONICAL_CONFIRMATORY_TASK_IDS = (
    "abs_affine-0",
    "abs_affine-1",
    "affine-0",
    "affine-1",
    "quadratic_simple-0",
    "quadratic_simple-1",
)


class AggregateRule(str, Enum):
    ALL_REQUIRED_CAMPAIGNS = "ALL_REQUIRED_CAMPAIGNS"


class CampaignStateMode(str, Enum):
    INDEPENDENT_FRESH_BASELINE_PER_TASK = "INDEPENDENT_FRESH_BASELINE_PER_TASK"


class PilotEvidencePolicy(str, Enum):
    EXCLUDED_FROM_CONFIRMATORY_RESULT = "EXCLUDED_FROM_CONFIRMATORY_RESULT"


class RetentionPolicy(str, Enum):
    NOT_APPLICABLE_SINGLE_CAPABILITY_RUN = "NOT_APPLICABLE_SINGLE_CAPABILITY_RUN"


class CampaignGate(str, Enum):
    PRIOR_STRUCTURAL_ABSENCE = "PRIOR_STRUCTURAL_ABSENCE"
    PRIOR_BEHAVIORAL_INSUFFICIENCY = "PRIOR_BEHAVIORAL_INSUFFICIENCY"
    CAMPAIGN_FROZEN = "CAMPAIGN_FROZEN"
    TRAIN_ONLY_LEARNER_VIEW = "TRAIN_ONLY_LEARNER_VIEW"
    DETERMINISTIC_SYNTHESIS = "DETERMINISTIC_SYNTHESIS"
    DETERMINISTIC_SELECTION = "DETERMINISTIC_SELECTION"
    SEARCH_BUDGET_RESPECTED = "SEARCH_BUDGET_RESPECTED"
    CANDIDATE_COMMITMENT = "CANDIDATE_COMMITMENT"
    AUDIT_ONE_SHOT = "AUDIT_ONE_SHOT"
    AUDIT_PASS = "AUDIT_PASS"
    PROMOTION_PASS = "PROMOTION_PASS"
    G1_DELTA_EXACTLY_Z = "G1_DELTA_EXACTLY_Z"
    HIDDEN_EXACTNESS = "HIDDEN_EXACTNESS"
    OOD_TRANSFER = "OOD_TRANSFER"
    COMPOSITIONAL_TRANSFER = "COMPOSITIONAL_TRANSFER"
    C1_TREATMENT_EFFECT = "C1_TREATMENT_EFFECT"
    C1_PLACEBO_CONTROL = "C1_PLACEBO_CONTROL"
    C1_CFI = "C1_CFI"
    C2_ABLATION_NECESSITY = "C2_ABLATION_NECESSITY"
    C2_CFI = "C2_CFI"
    C3_TRANSPLANT_SUFFICIENCY = "C3_TRANSPLANT_SUFFICIENCY"
    C3_CFI = "C3_CFI"
    EXACT_SKILL_IDENTITY = "EXACT_SKILL_IDENTITY"
    PERSISTENCE = "PERSISTENCE"
    FRESH_REPLAY = "FRESH_REPLAY"
    TEMPORAL_REPLAY = "TEMPORAL_REPLAY"
    TAMPER_MATRIX = "TAMPER_MATRIX"


REQUIRED_PER_CAMPAIGN_GATES = tuple(sorted(item.value for item in CampaignGate))


def _require_hash(value: str, reason: str) -> None:
    if not isinstance(value, str) or not is_artifact_hash(value):
        raise ValueError(reason)


def _canonical_task_ids(values: Sequence[str]) -> tuple[str, ...]:
    result = tuple(sorted(str(item) for item in values))
    if result != CANONICAL_CONFIRMATORY_TASK_IDS:
        raise ValueError("genesis_gei_policy_task_set_invalid")
    return result


@dataclass(frozen=True, slots=True)
class GEIAcceptancePolicy:
    """Immutable all-campaigns rule, frozen before confirmatory execution."""

    schema_version: str
    policy_id: str
    policy_version: str
    canonical_battery_manifest_hash: str
    required_task_ids: tuple[str, ...]
    aggregate_rule: AggregateRule
    campaign_state_mode: CampaignStateMode
    pilot_evidence_policy: PilotEvidencePolicy
    audit_policy_hash: str
    compositional_transfer_protocol_hash: str
    required_per_campaign_gates: tuple[str, ...]
    retention_policy: RetentionPolicy
    failure_semantics: Mapping[str, str]
    policy_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.schema_version or not self.policy_id or not self.policy_version:
            raise ValueError("genesis_gei_policy_identity_invalid")
        for value in (
            self.canonical_battery_manifest_hash,
            self.audit_policy_hash,
            self.compositional_transfer_protocol_hash,
        ):
            _require_hash(value, "genesis_gei_policy_hash_invalid")
        object.__setattr__(self, "required_task_ids", _canonical_task_ids(self.required_task_ids))
        object.__setattr__(self, "aggregate_rule", AggregateRule(self.aggregate_rule))
        object.__setattr__(self, "campaign_state_mode", CampaignStateMode(self.campaign_state_mode))
        object.__setattr__(self, "pilot_evidence_policy", PilotEvidencePolicy(self.pilot_evidence_policy))
        object.__setattr__(self, "retention_policy", RetentionPolicy(self.retention_policy))
        gates = tuple(sorted(str(item) for item in self.required_per_campaign_gates))
        if gates != REQUIRED_PER_CAMPAIGN_GATES:
            raise ValueError("genesis_gei_policy_gates_invalid")
        object.__setattr__(self, "required_per_campaign_gates", gates)
        semantics = freeze({str(key): str(value) for key, value in self.failure_semantics.items()})
        if semantics != freeze({
            "all_pass": "GE_I_CAMPAIGN_SUPPORTED",
            "any_fail": "GE_I_CAMPAIGN_FAIL",
            "otherwise": "GE_I_CAMPAIGN_NOT_PROVEN",
            "battery_all_supported": "GE_I_BATTERY_SUPPORTED",
            "battery_any_fail": "GE_I_BATTERY_FAIL",
            "battery_otherwise": "GE_I_BATTERY_NOT_PROVEN",
        }):
            raise ValueError("genesis_gei_policy_failure_semantics_invalid")
        object.__setattr__(self, "failure_semantics", semantics)
        object.__setattr__(self, "policy_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "canonical_battery_manifest_hash": self.canonical_battery_manifest_hash,
            "required_task_ids": self.required_task_ids,
            "aggregate_rule": self.aggregate_rule.value,
            "campaign_state_mode": self.campaign_state_mode.value,
            "pilot_evidence_policy": self.pilot_evidence_policy.value,
            "audit_policy_hash": self.audit_policy_hash,
            "compositional_transfer_protocol_hash": self.compositional_transfer_protocol_hash,
            "required_per_campaign_gates": self.required_per_campaign_gates,
            "retention_policy": self.retention_policy.value,
            "failure_semantics": self.failure_semantics,
        }

    def validate(self) -> bool:
        try:
            return GEIAcceptancePolicy(**self.canonical_payload()).policy_hash == self.policy_hash
        except (TypeError, ValueError):
            return False

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "GEIAcceptancePolicy":
        return cls(**dict(payload))


def confirmatory_policy(
    *,
    canonical_battery_manifest_hash: str,
    audit_policy_hash: str,
    compositional_transfer_protocol_hash: str,
) -> GEIAcceptancePolicy:
    """Construct the sole supported M7-v1 all-required-campaigns policy."""

    return GEIAcceptancePolicy(
        "genesis-m7-gei-acceptance-policy-v1",
        "GEI_CONFIRMATORY_BATTERY_V1",
        "v1",
        canonical_battery_manifest_hash,
        CANONICAL_CONFIRMATORY_TASK_IDS,
        AggregateRule.ALL_REQUIRED_CAMPAIGNS,
        CampaignStateMode.INDEPENDENT_FRESH_BASELINE_PER_TASK,
        PilotEvidencePolicy.EXCLUDED_FROM_CONFIRMATORY_RESULT,
        audit_policy_hash,
        compositional_transfer_protocol_hash,
        REQUIRED_PER_CAMPAIGN_GATES,
        RetentionPolicy.NOT_APPLICABLE_SINGLE_CAPABILITY_RUN,
        {
            "all_pass": "GE_I_CAMPAIGN_SUPPORTED",
            "any_fail": "GE_I_CAMPAIGN_FAIL",
            "otherwise": "GE_I_CAMPAIGN_NOT_PROVEN",
            "battery_all_supported": "GE_I_BATTERY_SUPPORTED",
            "battery_any_fail": "GE_I_BATTERY_FAIL",
            "battery_otherwise": "GE_I_BATTERY_NOT_PROVEN",
        },
    )
