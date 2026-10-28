"""M7-F2: CAS replay must rederive M7 semantics, not merely M6 hashes."""

from __future__ import annotations

from dataclasses import replace
import runpy

from lab.genesis.acquisition import replay_m7_federated_evidence
from lab.genesis.acquisition.benchmark import DatasetSplit
from lab.genesis.acquisition.federated_evidence import materialize_promoted_skill_evidence
from lab.genesis.evidence import (
    ContentAddressedArtifactStore,
    persist_m6_trace,
    replay_m6_trace,
)


support = runpy.run_path("tests/genesis/test_m7f_federated_evidence.py")


def material():
    campaign, baseline, benchmark, result = support["prepared"]()
    evidence = materialize_promoted_skill_evidence(
        campaign=campaign,
        baseline=baseline,
        benchmark=benchmark,
        task_id="affine-0",
        result=result,
        split=DatasetSplit.HIDDEN,
    )
    return evidence, result


def persist(store, evidence, history=None):
    return persist_m6_trace(
        store,
        router=evidence.router,
        federation_plan=evidence.federation_plan,
        subject=evidence.subject,
        records=evidence.records,
        bundle=evidence.bundle,
        adjudication=evidence.adjudication,
        historical_artifacts=evidence.historical_artifacts if history is None else history,
    )


def test_fresh_cas_replay_rederives_m7_and_m6_semantics(tmp_path) -> None:
    evidence, _result = material()
    persisted = evidence.persist_trace(ContentAddressedArtifactStore(tmp_path))

    replay = replay_m7_federated_evidence(
        ContentAddressedArtifactStore(tmp_path), persisted.closure_hash
    )

    assert replay.admitted


def test_resealed_false_audit_is_m6_valid_but_m7_semantically_rejected(tmp_path) -> None:
    evidence, result = material()
    false_audit = replace(result.audit, exact_pass=False, correct=0)
    history = dict(evidence.historical_artifacts)
    history["m7_audit_evaluation"] = (false_audit,)
    persisted = persist(ContentAddressedArtifactStore(tmp_path), evidence, history)

    assert replay_m6_trace(ContentAddressedArtifactStore(tmp_path), persisted.closure_hash).admitted
    assert not replay_m7_federated_evidence(
        ContentAddressedArtifactStore(tmp_path), persisted.closure_hash
    ).admitted


def test_resealed_false_target_witness_is_m6_valid_but_m7_semantically_rejected(tmp_path) -> None:
    evidence, _result = material()
    witness = evidence.historical_artifacts["m7_sealed_benchmark_replay_witness"][0]
    changed_task = replace(
        next(item for item in witness.tasks if item.task_id == "affine-0"),
        target_ast={"op": "X", "args": ()},
    )
    false_witness = replace(
        witness,
        tasks=tuple(
            changed_task if item.task_id == "affine-0" else item
            for item in witness.tasks
        ),
    )
    history = dict(evidence.historical_artifacts)
    history["m7_sealed_benchmark_replay_witness"] = (false_witness,)
    persisted = persist(ContentAddressedArtifactStore(tmp_path), evidence, history)

    assert replay_m6_trace(ContentAddressedArtifactStore(tmp_path), persisted.closure_hash).admitted
    assert not replay_m7_federated_evidence(
        ContentAddressedArtifactStore(tmp_path), persisted.closure_hash
    ).admitted


def test_ambiguous_m7_role_set_is_rejected_even_when_it_contains_one_valid_audit(tmp_path) -> None:
    evidence, result = material()
    false_audit = replace(result.audit, exact_pass=False, correct=0)
    history = dict(evidence.historical_artifacts)
    history["m7_audit_evaluation"] = (result.audit, false_audit)
    persisted = persist(ContentAddressedArtifactStore(tmp_path), evidence, history)

    assert replay_m6_trace(ContentAddressedArtifactStore(tmp_path), persisted.closure_hash).admitted
    assert not replay_m7_federated_evidence(
        ContentAddressedArtifactStore(tmp_path), persisted.closure_hash
    ).admitted
