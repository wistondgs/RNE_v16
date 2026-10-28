from __future__ import annotations

import inspect
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from runtime.neural.integration import (
    AuthorityEffect,
    ConsumerReceipt,
    ConsumerVerdictClass,
    OrganTrace,
    SYMBIOSIS_TRACE_SCHEMA_VERSION,
    SymbiosisIdentity,
    SymbiosisTrace,
    SymbioticNeuralCoordinator,
    integration_census,
    validate_active_census,
    validate_consumer_receipt,
)
from runtime.neural.integration.contracts import canonical_json_bytes, canonical_sha256


def test_symbiosis_contract_is_versioned_and_active_census_has_no_stub() -> None:
    assert SYMBIOSIS_TRACE_SCHEMA_VERSION == "neural-symbiosis-trace-v2"
    assert validate_active_census() == []
    matrix = {row["organ"]: row for row in integration_census()}
    for organ in ("N0", "N1", "N2", "N3", "N4", "N5", "N6"):
        assert matrix[organ]["caller_count"] > 0
        assert matrix[organ]["consumer_count"] > 0
        assert matrix[organ]["stub_detected"] is False
    assert matrix["N4"]["shadow_consumed"] is True
    assert matrix["N5"]["live"] is True
    assert matrix["EVO_SEARCH"]["reference_only"] is True
    assert matrix["IMAGINATION/A11"]["reference_only"] is True


def test_live_coordinator_source_has_no_stub_control_flow() -> None:
    source = inspect.getsource(SymbioticNeuralCoordinator)
    assert "if False" not in source
    assert "NotImplemented" not in source
    assert "return idle" not in source
    assert "pass\n" not in source


def test_scenario_runner_is_the_non_test_live_caller() -> None:
    from runtime.world import scenario_runner

    source = inspect.getsource(scenario_runner.ScenarioEpisodeRunner.run_episode)
    assert ".begin_episode(" in source
    assert ".consume_reasoning(" in source
    assert ".prepare_certification(" in source
    assert ".finalize_episode(" in source


def _receipt_fixture() -> tuple[SymbiosisIdentity, OrganTrace, ConsumerReceipt]:
    identity = SymbiosisIdentity(
        trace_group_id="trace-receipt",
        organism_id="organism-receipt",
        lineage_id="lineage-receipt",
        run_id="run-receipt",
        episode_id="episode-receipt",
        scenario_id="scenario@1",
    )
    generated_at = datetime.now(timezone.utc).isoformat()
    organ = OrganTrace(
        identity=identity,
        organ="N1",
        capability="family_routing_proposal",
        requested_mode="shadow",
        effective_mode="shadow",
        authority_ceiling="shadow",
        input_hash="input-hash",
        candidate_hash="candidate-hash",
        consumer="decorative",
        consumer_verdict="agreement",
        latency_ms=0.1,
        candidate={"proposal": []},
        generated_at=generated_at,
    )
    receipt = ConsumerReceipt(
        receipt_id="receipt-1",
        identity=identity,
        organ="N1",
        candidate_hash="candidate-hash",
        consumer_id="scheduler_comparison",
        consumer_contract_version="scheduler-comparison-v1",
        consumer_input_hash="input",
        consumer_output_hash="output",
        verdict_class=ConsumerVerdictClass.COMPARED,
        verdict_detail="compared",
        evidence_refs=("scheduler",),
        authority_effect=AuthorityEffect.EVIDENCE_ONLY,
        persisted=True,
        generated_at=generated_at,
    )
    return identity, organ, receipt


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        ({"candidate_hash": "wrong"}, "candidate_hash_mismatch"),
        ({"consumer_id": "imaginary_consumer"}, "consumer_unknown"),
        ({"authority_effect": AuthorityEffect.AUTHORITATIVE}, "authority_exceeds_ceiling"),
    ],
)
def test_consumer_receipt_rejects_invalid_consumption(mutation, error) -> None:
    identity, organ, receipt = _receipt_fixture()
    with pytest.raises(ValueError, match=error):
        validate_consumer_receipt(
            replace(receipt, **mutation), trace_identity=identity, organ_trace=organ
        )


def test_consumer_receipt_rejects_identity_and_pre_candidate_fabrication() -> None:
    identity, organ, receipt = _receipt_fixture()
    foreign = replace(identity, organism_id="other-organism")
    with pytest.raises(ValueError, match="identity_mismatch"):
        validate_consumer_receipt(
            replace(receipt, identity=foreign), trace_identity=identity, organ_trace=organ
        )
    earlier = (datetime.fromisoformat(organ.generated_at) - timedelta(seconds=1)).isoformat()
    with pytest.raises(ValueError, match="predates_candidate"):
        validate_consumer_receipt(
            replace(receipt, generated_at=earlier),
            trace_identity=identity,
            organ_trace=organ,
        )


def test_trace_v2_does_not_count_decorative_consumer_strings() -> None:
    identity, organ, _receipt = _receipt_fixture()
    trace = SymbiosisTrace(
        identity=identity,
        organs=[replace(organ, organ=f"N{index}") for index in range(1, 7)],
        life_transition_id="transition-1",
        previous_transition_hash="genesis",
    )
    assert trace.is_complete is False


def test_trace_v1_remains_readable_but_cannot_claim_v2_completeness() -> None:
    identity, _organ, _receipt = _receipt_fixture()
    restored = SymbiosisTrace.from_dict(
        {
            "schema_version": "neural-symbiosis-trace-v1",
            **identity.to_dict(),
            "organs": [],
        }
    )
    assert restored.identity == identity
    assert restored.consumer_receipts == []
    assert restored.is_complete is False


def test_legacy_unknown_verdict_is_never_mapped_to_acceptance() -> None:
    identity, organ, receipt = _receipt_fixture()
    raw = receipt.to_dict()
    raw.pop("verdict_class")
    raw.pop("verdict_detail")
    raw["verdict"] = "looks_fine_probably"
    restored = ConsumerReceipt.from_dict(raw)
    assert restored.verdict_class is ConsumerVerdictClass.INVALID
    with pytest.raises(ValueError, match="verdict_invalid"):
        validate_consumer_receipt(
            restored, trace_identity=identity, organ_trace=organ
        )


def test_strict_canonical_hash_accepts_only_explicit_json_domain() -> None:
    left = {"b": [1, 2.0, None], "a": "ñ"}
    right = {"a": "ñ", "b": (1, 2.0, None)}
    assert canonical_json_bytes(left) == canonical_json_bytes(right)
    assert canonical_sha256(left) == canonical_sha256(right)
    assert canonical_sha256({"value": 1}) != canonical_sha256({"value": 2})

    for invalid in (
        float("nan"),
        float("inf"),
        {"values": {1, 2}},
        {"payload": object()},
        {1: "non-string-key"},
        b"raw-bytes",
    ):
        with pytest.raises(ValueError, match="canonical_"):
            canonical_sha256(invalid)
