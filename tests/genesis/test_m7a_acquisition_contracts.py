"""M7-A contracts: immutable capability identity and pre-audit commitment."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from lab.genesis.acquisition.contracts import (
    CANDIDATE_RANKING_RULE,
    HUMAN_INTERVENTION_POLICY,
    PROMOTION_RULE,
    AcquisitionCampaignManifest,
    CandidateCommitment,
    CapabilityManifest,
    ProgramSkillArtifact,
    PromotionReceipt,
    PromotionStatus,
    SynthesisReceipt,
    SynthesisTermination,
    derive_successor_manifest,
    validate_campaign_binding,
    validate_candidate_commitment,
    validate_manifest_successor,
    validate_promotion_receipt,
    validate_synthesis_receipt,
)
from lab.genesis.contracts.serialization import canonical_sha256, freeze


def h(label: str) -> str:
    return canonical_sha256({"m7a": label})


def program() -> dict[str, object]:
    return {
        "op": "ADD",
        "args": (
            {
                "op": "MUL_CONST",
                "args": ({"op": "X", "args": ()},),
                "value": 2,
            },
            {"op": "CONST", "args": (), "value": 3},
        ),
    }


def campaign(g0: CapabilityManifest) -> AcquisitionCampaignManifest:
    return AcquisitionCampaignManifest(
        campaign_id="m7a-affine-1",
        schema_version="genesis-m7-acquisition-campaign-v1",
        g0_snapshot_hash=h("g0-snapshot"),
        g0_capability_manifest_hash=g0.manifest_hash,
        dsl_hash=h("dsl"),
        synthesizer_implementation_hash=h("synthesizer"),
        dataset_commitments={
            "TRAIN": h("train"), "AUDIT": h("audit"),
            "HIDDEN": h("hidden"), "TRANSFER": h("transfer"),
        },
        task_generator_implementation_hash=h("generator"),
        dataset_seed_commitments={
            "TRAIN": h("train-seed"), "AUDIT": h("audit-seed"),
            "HIDDEN": h("hidden-seed"), "TRANSFER": h("transfer-seed"),
        },
        search_budget={"max_candidates": 64},
        max_ast_depth=4,
        max_ast_nodes=12,
        allowed_constants=(-2, -1, 0, 1, 2, 3),
        allowed_operators=("ADD", "CONST", "MUL_CONST", "X"),
        candidate_ranking_rule=CANDIDATE_RANKING_RULE,
        promotion_rule=PROMOTION_RULE,
        cfi_policy_hash=h("cfi-policy"),
        resource_budget_hash=h("resource-budget"),
        timeout_seconds=30,
        human_intervention_policy=HUMAN_INTERVENTION_POLICY,
        verifier_obligation_hashes=(h("audit-obligation"), h("hidden-obligation")),
    )


def skill(campaign_hash: str) -> ProgramSkillArtifact:
    ast = program()
    return ProgramSkillArtifact(
        schema_version="genesis-m7-program-skill-v1",
        skill_kind="FINITE_INTEGER_FUNCTION",
        dsl_version="genesis-m7-dsl-v1",
        input_contract={"kind": "integer"},
        output_contract={"kind": "integer"},
        program_ast=ast,
        complexity={"node_count": 4, "ast_depth": 3},
        required_primitives=("ADD", "CONST", "MUL_CONST", "X"),
        discovery_campaign_hash=campaign_hash,
        provenance_hashes=(h("train-experience"), h("synthesis-search")),
    )


def material() -> tuple[CapabilityManifest, AcquisitionCampaignManifest, ProgramSkillArtifact, SynthesisReceipt, CandidateCommitment]:
    g0 = CapabilityManifest("g0", "genesis-m7-capability-manifest-v1", ())
    manifest = campaign(g0)
    candidate = skill(manifest.campaign_hash)
    synthesis = SynthesisReceipt(
        schema_version="genesis-m7-synthesis-receipt-v1",
        campaign_hash=manifest.campaign_hash,
        search_space_hash=h("search-space"),
        search_budget_hash=canonical_sha256(manifest.search_budget),
        candidates_examined=17,
        termination=SynthesisTermination.SELECTED,
        selected_skill_hash=candidate.skill_hash,
        training_evidence_hash=h("training-evidence"),
        ranking_evidence_hash=h("ranking-evidence"),
    )
    commitment = CandidateCommitment(
        schema_version="genesis-m7-candidate-commitment-v1",
        candidate_skill_hash=candidate.skill_hash,
        campaign_hash=manifest.campaign_hash,
        training_evidence_hash=synthesis.training_evidence_hash or "",
        synthesis_receipt_hash=synthesis.synthesis_hash,
        ranking_evidence_hash=synthesis.ranking_evidence_hash or "",
    )
    return g0, manifest, candidate, synthesis, commitment


def test_contracts_are_canonical_and_field_order_invariant() -> None:
    g0, manifest, candidate, synthesis, commitment = material()
    g0_reordered = CapabilityManifest("g0", "genesis-m7-capability-manifest-v1", ())
    manifest_reordered = AcquisitionCampaignManifest(
        **{
            **manifest.canonical_payload(),
            "dataset_commitments": dict(reversed(tuple(manifest.dataset_commitments.items()))),
            "dataset_seed_commitments": dict(reversed(tuple(manifest.dataset_seed_commitments.items()))),
        }
    )
    candidate_reordered = ProgramSkillArtifact(
        schema_version=candidate.schema_version,
        skill_kind=candidate.skill_kind,
        dsl_version=candidate.dsl_version,
        input_contract={"kind": "integer"},
        output_contract={"kind": "integer"},
        program_ast={
            "args": candidate.program_ast["args"],
            "op": candidate.program_ast["op"],
        },
        complexity={"ast_depth": 3, "node_count": 4},
        required_primitives=tuple(reversed(candidate.required_primitives)),
        discovery_campaign_hash=candidate.discovery_campaign_hash,
        provenance_hashes=tuple(reversed(candidate.provenance_hashes)),
    )
    assert g0_reordered.manifest_hash == g0.manifest_hash
    assert manifest_reordered.campaign_hash == manifest.campaign_hash
    assert candidate_reordered.skill_hash == candidate.skill_hash
    assert synthesis.validate() and commitment.validate()


def test_contract_payloads_rehydrate_without_process_state_and_reject_false_derivation() -> None:
    g0, manifest, candidate, synthesis, commitment = material()
    g1 = derive_successor_manifest(g0, candidate, manifest_id="g1", schema_version=g0.schema_version)
    receipt = PromotionReceipt(
        schema_version="genesis-m7-promotion-receipt-v1",
        campaign_hash=manifest.campaign_hash,
        candidate_commitment_hash=commitment.commitment_hash,
        synthesis_receipt_hash=synthesis.synthesis_hash,
        candidate_skill_hash=candidate.skill_hash,
        audit_evidence_hash=h("audit-evidence"),
        g0_capability_manifest_hash=g0.manifest_hash,
        g1_capability_manifest_hash=g1.manifest_hash,
        status=PromotionStatus.PROMOTED,
        reason_codes=("audit_exact_pass",),
    )
    assert ProgramSkillArtifact.from_payload(candidate.canonical_payload()).skill_hash == candidate.skill_hash
    assert CapabilityManifest.from_payload(g1.canonical_payload()).manifest_hash == g1.manifest_hash
    assert AcquisitionCampaignManifest.from_payload(manifest.canonical_payload()).campaign_hash == manifest.campaign_hash
    assert SynthesisReceipt.from_payload(synthesis.canonical_payload()).synthesis_hash == synthesis.synthesis_hash
    assert CandidateCommitment.from_payload(commitment.canonical_payload()).commitment_hash == commitment.commitment_hash
    assert PromotionReceipt.from_payload(receipt.canonical_payload()).promotion_hash == receipt.promotion_hash
    forged = dict(candidate.canonical_payload())
    forged["program_hash"] = h("forged-program")
    with pytest.raises(ValueError, match="program_hash"):
        ProgramSkillArtifact.from_payload(forged)


def test_skill_rejects_resealed_false_derived_fields() -> None:
    _, manifest, candidate, _, _ = material()
    object.__setattr__(candidate, "complexity", freeze({"node_count": 99, "ast_depth": 99}))
    object.__setattr__(candidate, "skill_hash", canonical_sha256(candidate.canonical_payload()))
    assert candidate.skill_hash != h("irrelevant")
    assert not candidate.validate()
    assert manifest.validate()


def test_g0_is_immutable_and_g1_is_exactly_one_skill_delta() -> None:
    g0, manifest, candidate, synthesis, commitment = material()
    g1 = derive_successor_manifest(
        g0, candidate, manifest_id="g1", schema_version=g0.schema_version
    )
    assert g0.skill_hashes == ()
    assert validate_campaign_binding(manifest, g0, g0_snapshot_hash=manifest.g0_snapshot_hash)
    assert validate_synthesis_receipt(synthesis, manifest, candidate)
    assert validate_candidate_commitment(commitment, manifest, synthesis, candidate)
    assert validate_manifest_successor(g1, g0, candidate)
    with pytest.raises(FrozenInstanceError):
        g0.skill_hashes = (candidate.skill_hash,)  # type: ignore[misc]
    with pytest.raises(TypeError):
        manifest.dataset_commitments["TRAIN"] = h("tampered")  # type: ignore[index]


def test_resealed_manifest_with_a_false_delta_is_rejected_semantically() -> None:
    g0, _, candidate, _, _ = material()
    g1 = derive_successor_manifest(g0, candidate, manifest_id="g1", schema_version=g0.schema_version)
    forged = replace(
        g1,
        skill_hashes=(candidate.skill_hash, h("invented-skill")),
        added_skill_hashes=(candidate.skill_hash, h("invented-skill")),
    )
    assert forged.validate()  # internally consistent but not the declared G0 + z derivation
    assert not validate_manifest_successor(forged, g0, candidate)


def test_campaign_and_candidate_commitment_are_frozen_and_bound_to_train_selection() -> None:
    _, manifest, candidate, synthesis, commitment = material()
    with pytest.raises(FrozenInstanceError):
        manifest.timeout_seconds = 99  # type: ignore[misc]
    forged = replace(commitment, candidate_skill_hash=h("other-skill"))
    assert forged.validate()
    assert not validate_candidate_commitment(forged, manifest, synthesis, candidate)


def test_campaign_rejects_overlapping_splits_and_missing_verifier_obligations() -> None:
    g0, manifest, _, _, _ = material()
    with pytest.raises(ValueError, match="split_overlap"):
        replace(manifest, dataset_commitments={split: h("same") for split in manifest.dataset_commitments})
    with pytest.raises(ValueError, match="verifier_obligations_missing"):
        replace(manifest, verifier_obligation_hashes=())
    with pytest.raises(ValueError, match="provenance_missing"):
        ProgramSkillArtifact(
            schema_version="genesis-m7-program-skill-v1",
            skill_kind="FINITE_INTEGER_FUNCTION",
            dsl_version="genesis-m7-dsl-v1",
            input_contract={"kind": "integer"},
            output_contract={"kind": "integer"},
            program_ast={"op": "X", "args": ()},
            complexity={"node_count": 1, "ast_depth": 1},
            required_primitives=("X",),
            discovery_campaign_hash=campaign(g0).campaign_hash,
            provenance_hashes=(),
        )


def test_selected_candidate_must_stay_within_the_sealed_campaign_language() -> None:
    _, manifest, candidate, synthesis, _ = material()
    out_of_language = ProgramSkillArtifact(
        schema_version=candidate.schema_version,
        skill_kind=candidate.skill_kind,
        dsl_version=candidate.dsl_version,
        input_contract=candidate.input_contract,
        output_contract=candidate.output_contract,
        program_ast={"op": "CONST", "args": (), "value": 99},
        complexity={"node_count": 1, "ast_depth": 1},
        required_primitives=("CONST",),
        discovery_campaign_hash=manifest.campaign_hash,
        provenance_hashes=candidate.provenance_hashes,
    )
    forged_selection = replace(synthesis, selected_skill_hash=out_of_language.skill_hash)
    assert forged_selection.validate()
    assert not validate_synthesis_receipt(forged_selection, manifest, out_of_language)


def test_promotion_requires_the_committed_candidate_and_exact_g1_delta() -> None:
    g0, manifest, candidate, synthesis, commitment = material()
    g1 = derive_successor_manifest(g0, candidate, manifest_id="g1", schema_version=g0.schema_version)
    receipt = PromotionReceipt(
        schema_version="genesis-m7-promotion-receipt-v1",
        campaign_hash=manifest.campaign_hash,
        candidate_commitment_hash=commitment.commitment_hash,
        synthesis_receipt_hash=synthesis.synthesis_hash,
        candidate_skill_hash=candidate.skill_hash,
        audit_evidence_hash=h("audit-evidence"),
        g0_capability_manifest_hash=g0.manifest_hash,
        g1_capability_manifest_hash=g1.manifest_hash,
        status=PromotionStatus.PROMOTED,
        reason_codes=("audit_exact_pass", "candidate_precommitted"),
    )
    assert validate_promotion_receipt(
        receipt,
        campaign=manifest,
        commitment=commitment,
        synthesis=synthesis,
        candidate=candidate,
        g0_manifest=g0,
        g1_manifest=g1,
    )
    false_pass = replace(receipt, candidate_skill_hash=h("other-skill"))
    assert false_pass.validate()
    assert not validate_promotion_receipt(
        false_pass,
        campaign=manifest,
        commitment=commitment,
        synthesis=synthesis,
        candidate=candidate,
        g0_manifest=g0,
        g1_manifest=g1,
    )
