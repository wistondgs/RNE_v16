"""M7-G1 freezes the all-required-campaigns confirmatory policy."""

from dataclasses import replace

import pytest

from lab.genesis.acquisition.confirmation import (
    CANONICAL_CONFIRMATORY_TASK_IDS,
    CampaignGate,
    confirmatory_policy,
)
from lab.genesis.contracts.serialization import canonical_sha256


def h(value: object) -> str:
    return canonical_sha256({"m7g1": value})


def policy():
    return confirmatory_policy(
        canonical_battery_manifest_hash=h("canonical-battery"),
        audit_policy_hash=h("audit-policy"),
        compositional_transfer_protocol_hash=h("composition-protocol"),
    )


def test_policy_is_canonical_rehydratable_and_requires_all_six_tasks() -> None:
    first = policy()
    second = policy()

    assert first.validate()
    assert first.policy_hash == second.policy_hash
    assert first.required_task_ids == CANONICAL_CONFIRMATORY_TASK_IDS
    assert first.aggregate_rule.value == "ALL_REQUIRED_CAMPAIGNS"
    assert len(first.required_per_campaign_gates) == len(CampaignGate)
    assert type(first).from_payload(first.canonical_payload()).policy_hash == first.policy_hash


def test_policy_rejects_post_hoc_subset_and_failure_semantic_relaxation() -> None:
    frozen = policy()

    with pytest.raises(ValueError, match="task_set_invalid"):
        replace(frozen, required_task_ids=("affine-0",))
    with pytest.raises(ValueError, match="failure_semantics_invalid"):
        replace(frozen, failure_semantics={"all_pass": "GE_I_CAMPAIGN_SUPPORTED"})
