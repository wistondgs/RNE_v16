"""M7-G2: evaluator-side durable one-shot AUDIT consumption."""

from __future__ import annotations

from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Thread

import pytest

from lab.genesis.acquisition import audit as audit_module
from lab.genesis.acquisition.audit import AuditClaimReceipt, AuditSlot, DurableAuditClaimRegistry
from lab.genesis.acquisition.benchmark import DatasetSplit, TaskBenchmarkBinding, canonical_benchmark
from lab.genesis.acquisition.campaign import AutonomousAcquisitionCampaign
from lab.genesis.acquisition.confirmation import confirmatory_policy
from lab.genesis.acquisition.contracts import (
    AcquisitionCampaignManifest,
    CANDIDATE_RANKING_RULE,
    CapabilityManifest,
    HUMAN_INTERVENTION_POLICY,
    PROMOTION_RULE,
)
from lab.genesis.acquisition.dsl import DSLSpecification
from lab.genesis.acquisition.synthesis import DeterministicProgramSynthesizer
from lab.genesis.contracts.serialization import canonical_sha256


def h(value: object) -> str:
    return canonical_sha256({"m7g2": value})


def material():
    specification = DSLSpecification("m7", "genesis-m7-dsl-v1", (-2, -1, 0, 1, 2, 3), 5, 12, 10_000)
    benchmark = canonical_benchmark(specification, seed=17)
    baseline = CapabilityManifest("m7g2-g0", "m7", ())
    policy = confirmatory_policy(
        canonical_battery_manifest_hash=benchmark.manifest.manifest_hash,
        audit_policy_hash=h("audit-policy"),
        compositional_transfer_protocol_hash=h("composition-protocol"),
    )
    descriptor = next(item for item in benchmark.manifest.tasks if item.task_id == "affine-0")
    campaign = AcquisitionCampaignManifest(
        "m7g2-confirmatory-affine-0", "m7", h("snapshot"), baseline.manifest_hash,
        specification.dsl_hash, h("synthesizer"), descriptor.split_commitments,
        benchmark.manifest.generator_implementation_hash,
        {split: h(("seed", split)) for split in ("TRAIN", "AUDIT", "HIDDEN", "TRANSFER")},
        {"max_candidates": 256}, specification.max_ast_depth, specification.max_ast_nodes,
        specification.allowed_constants, tuple(item.value for item in specification.operators),
        CANDIDATE_RANKING_RULE, PROMOTION_RULE, h("cfi"), h("budget"), 30,
        HUMAN_INTERVENTION_POLICY, (h("obligation"),), policy.policy_hash, h("battery-run"),
        "CONFIRMATORY_GE_I_EVIDENCE",
    )
    binding = TaskBenchmarkBinding(
        "genesis-m7-task-benchmark-binding-v1", campaign.campaign_hash,
        benchmark.manifest.manifest_hash, "affine-0", descriptor.split_commitments,
    )
    outcome = DeterministicProgramSynthesizer().synthesize(
        campaign=campaign, specification=specification, training=benchmark.learner_view("affine-0")
    )
    from lab.genesis.acquisition.contracts import CandidateCommitment
    candidate = outcome.selected_skill
    assert candidate is not None
    commitment = CandidateCommitment(
        "genesis-m7-candidate-commitment-v1", candidate.skill_hash, campaign.campaign_hash,
        outcome.receipt.training_evidence_hash or "", outcome.receipt.synthesis_hash,
        outcome.receipt.ranking_evidence_hash or "",
    )
    return policy, campaign, binding, benchmark, candidate, commitment


def test_same_candidate_is_idempotent_across_handles_and_restart(tmp_path) -> None:
    policy, campaign, binding, benchmark, candidate, commitment = material()
    calls = 0

    def evaluate():
        nonlocal calls
        calls += 1
        return benchmark.commit_candidate("affine-0", candidate).evaluate_once()

    first = DurableAuditClaimRegistry(tmp_path, policy=policy).evaluate(
        campaign=campaign, task_binding=binding, commitment=commitment, evaluate_once=evaluate
    )
    second = DurableAuditClaimRegistry(tmp_path, policy=policy).evaluate(
        campaign=campaign, task_binding=binding, commitment=commitment, evaluate_once=evaluate
    )

    assert calls == 1
    assert first.evaluation.receipt_hash == second.evaluation.receipt_hash
    assert first.audit.result_hash == second.audit.result_hash


def test_different_candidate_is_rejected_before_evaluation(tmp_path) -> None:
    policy, campaign, binding, benchmark, candidate, commitment = material()
    registry = DurableAuditClaimRegistry(tmp_path, policy=policy)
    registry.evaluate(
        campaign=campaign, task_binding=binding, commitment=commitment,
        evaluate_once=lambda: benchmark.commit_candidate("affine-0", candidate).evaluate_once(),
    )
    forged = replace(commitment, candidate_skill_hash=h("other-candidate"))
    with pytest.raises(ValueError, match="candidate_conflict"):
        registry.evaluate(
            campaign=campaign, task_binding=binding, commitment=forged,
            evaluate_once=lambda: (_ for _ in ()).throw(AssertionError("must_not_evaluate")),
        )


def test_concurrent_same_candidate_evaluates_once_and_failure_can_resume(tmp_path) -> None:
    policy, campaign, binding, benchmark, candidate, commitment = material()
    registry = DurableAuditClaimRegistry(tmp_path, policy=policy)
    calls = 0

    def flaky():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("simulated_pre_result_failure")
        return benchmark.commit_candidate("affine-0", candidate).evaluate_once()

    with pytest.raises(RuntimeError, match="simulated_pre_result_failure"):
        registry.evaluate(campaign=campaign, task_binding=binding, commitment=commitment, evaluate_once=flaky)

    def retry():
        return registry.evaluate(campaign=campaign, task_binding=binding, commitment=commitment, evaluate_once=flaky)

    with ThreadPoolExecutor(max_workers=2) as pool:
        left, right = tuple(pool.map(lambda _item: retry(), range(2)))
    assert calls == 2
    assert left.evaluation.receipt_hash == right.evaluation.receipt_hash


def test_write_once_never_exposes_an_empty_final_record(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A reader must see either no record or a fully fsynced JSON document."""

    policy, _campaign, _binding, _benchmark, _candidate, _commitment = material()
    registry = DurableAuditClaimRegistry(tmp_path, policy=policy)
    final_path = tmp_path / "atomic.result.json"
    payload = {"record": "complete", "value": 7}
    reached_publish = Event()
    release_publish = Event()
    original_link = audit_module.os.link

    def delayed_link(source, destination, *args, **kwargs):
        reached_publish.set()
        assert release_publish.wait(timeout=2)
        return original_link(source, destination, *args, **kwargs)

    monkeypatch.setattr(audit_module.os, "link", delayed_link)
    result: list[bool] = []
    writer = Thread(target=lambda: result.append(registry._write_once(final_path, payload)))
    writer.start()
    assert reached_publish.wait(timeout=2)
    # The private pending inode exists, but the final name is not observable.
    assert not final_path.exists()
    release_publish.set()
    writer.join(timeout=2)

    assert result == [True]
    assert registry._read(final_path) == payload


def test_confirmatory_campaign_requires_durable_registry(tmp_path) -> None:
    policy, campaign, binding, benchmark, _candidate, _commitment = material()
    baseline = CapabilityManifest("m7g2-run-g0", "m7", ())
    campaign = replace(campaign, g0_capability_manifest_hash=baseline.manifest_hash)
    binding = TaskBenchmarkBinding(
        binding.schema_version, campaign.campaign_hash, binding.benchmark_manifest_hash,
        binding.task_id, binding.split_commitment_hashes,
    )
    with pytest.raises(ValueError, match="audit_registry_required"):
        AutonomousAcquisitionCampaign().run(
            campaign=campaign, specification=benchmark.specification, benchmark=benchmark,
            g0_manifest=baseline, task_id="affine-0", g1_manifest_id="m7g2-run-g1",
            task_benchmark_binding=binding,
        )


def test_completed_claim_without_a_sealed_evaluation_is_rejected(tmp_path) -> None:
    policy, campaign, binding, _benchmark, _candidate, commitment = material()
    registry = DurableAuditClaimRegistry(tmp_path, policy=policy)
    slot = AuditSlot(
        policy.policy_hash, campaign.campaign_hash, binding.binding_hash,
        binding.split_commitment_hashes[DatasetSplit.AUDIT.value],
    )
    completed = AuditClaimReceipt(
        "genesis-m7-durable-audit-claim-v1", slot, commitment.commitment_hash, "COMPLETED"
    )
    assert registry._write_once(registry._path(slot, "claim"), completed.canonical_payload())
    with pytest.raises(ValueError, match="completed_without_result"):
        registry.evaluate(
            campaign=campaign, task_binding=binding, commitment=commitment,
            evaluate_once=lambda: (_ for _ in ()).throw(AssertionError("must_not_evaluate")),
        )
