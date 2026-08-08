from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from runtime.experiments.ea1.application import (
    EvidenceApplicationError,
    EvidenceApplicationService,
    InjectedApplicationCrash,
    PersistentAtomicityRequired,
    evidence_application_id,
)
from runtime.experiments.ea1.contracts import (
    Arm,
    BeliefRevision,
    EvidenceApplicationStatus,
    TheoryState,
)
from runtime.experiments.ea1.harness import CanonicalOutcomeResolver
from runtime.experiments.ea1.ledger import (
    ExperimentLedger,
    LedgerIntegrityError,
    StorageLedgerBackend,
)
from tests.experiments.ea1.test_selection_outcome_binding import (
    _commit_f1a,
    _selected,
    _storage,
)


def _prepared(root: Path, *, arm: Arm = Arm.EXPERIMENTAL, run_id: str = "run"):
    db = _storage(root)
    harness, ledger, receipt, authorization, action = _selected(
        db,
        arm=arm,
        run_id=run_id,
        organism_id=f"organism-{run_id}",
        episode_id=f"episode-{run_id}",
    )
    _commit_f1a(
        db,
        authorization=authorization,
        run_id=receipt.run_id,
        organism_id=receipt.organism_id,
        episode_id=receipt.episode_id,
        action_id=action.action_id,
    )
    resolver = CanonicalOutcomeResolver(db, ledger)
    reference = resolver.resolve(receipt)
    harness.attach_outcome(1, reference, resolver=resolver)
    prior = TheoryState("theory-1", 1, 0.49, 0.49, 0.02, "h1")
    draft = _draft(prior, reference.reference_id)
    return db, harness, ledger, receipt, reference, prior, draft


def _draft(
    prior: TheoryState,
    reference_id: str,
    *,
    posterior: tuple[float, float, float] = (0.80, 0.15, 0.05),
    rationale: str = "frozen Bayesian update",
) -> BeliefRevision:
    successor = TheoryState(
        "caller-draft-state",
        prior.epoch + 1,
        posterior[0],
        posterior[1],
        posterior[2],
        "h1",
        predecessor_state_id=prior.state_id,
        version=prior.version + 1,
        logical_time=prior.logical_time + 20,
    )
    return BeliefRevision(
        "caller-draft-revision",
        prior.epoch,
        prior.state_id,
        successor,
        reference_id,
        rationale,
    )


def _reload(db):
    ledger = ExperimentLedger(StorageLedgerBackend(db))
    return ledger, CanonicalOutcomeResolver(db, ledger)


def _counts(ledger: ExperimentLedger, run_id: str) -> dict[str, int]:
    entries = ledger.entries(run_id)
    return {
        "applications_reserved": sum(
            item.kind == "evidence_application_reserved" for item in entries
        ),
        "applications_committed": sum(
            item.kind == "evidence_application_committed" for item in entries
        ),
        "revisions": sum(item.kind == "revision" for item in entries),
        "selections": sum(item.kind == "selection" for item in entries),
    }


def test_t1_t2_t3_restart_and_same_process_replay_return_one_result(
    tmp_path: Path,
) -> None:
    db, harness, ledger, receipt, reference, prior, draft = _prepared(tmp_path)
    tokens_before = harness.budget.snapshot
    service = EvidenceApplicationService(
        ledger, CanonicalOutcomeResolver(db, ledger)
    )
    first = service.apply(receipt, reference, prior, draft)
    same_process = service.apply(receipt, reference, prior, draft)

    reloaded_ledger, reloaded_resolver = _reload(db)
    fresh_process = EvidenceApplicationService(
        reloaded_ledger, reloaded_resolver
    ).apply(receipt, reference, prior, draft)

    assert first.retry_result == "applied"
    assert same_process.retry_result == fresh_process.retry_result == "already_committed"
    assert first.application == same_process.application == fresh_process.application
    assert first.revision == same_process.revision == fresh_process.revision
    assert first.successor == same_process.successor == fresh_process.successor
    assert _counts(reloaded_ledger, receipt.run_id) == {
        "applications_reserved": 1,
        "applications_committed": 1,
        "revisions": 1,
        "selections": 1,
    }
    assert harness.budget.snapshot == tokens_before


def test_t4_stale_successor_cannot_receive_the_same_outcome(tmp_path: Path) -> None:
    db, _, ledger, receipt, reference, prior, draft = _prepared(tmp_path)
    service = EvidenceApplicationService(ledger, CanonicalOutcomeResolver(db, ledger))
    first = service.apply(receipt, reference, prior, draft)
    stale_draft = _draft(first.successor, reference.reference_id)
    with pytest.raises(EvidenceApplicationError, match="predecessor_mismatch"):
        EvidenceApplicationService(*_reload(db)).apply(  # type: ignore[arg-type]
            receipt, reference, first.successor, stale_draft
        )
    forged_prior = replace(
        prior,
        posterior_h1=0.60,
        posterior_h2=0.38,
        posterior_unknown=0.02,
    )
    with pytest.raises(EvidenceApplicationError, match="persisted_predecessor_mismatch"):
        EvidenceApplicationService(*_reload(db)).apply(  # type: ignore[arg-type]
            receipt,
            reference,
            forged_prior,
            _draft(forged_prior, reference.reference_id),
        )
    assert _counts(ledger, receipt.run_id)["revisions"] == 1


def test_t5_application_identity_is_deterministic_and_forgery_fails(
    tmp_path: Path,
) -> None:
    db, _, ledger, receipt, reference, prior, draft = _prepared(tmp_path)
    service = EvidenceApplicationService(ledger, CanonicalOutcomeResolver(db, ledger))
    result = service.apply(receipt, reference, prior, draft)
    assert result.application.application_id == evidence_application_id(
        receipt, reference, prior
    )

    forged = replace(
        result.application,
        application_id="forged-application-id",
        status=EvidenceApplicationStatus.RESERVED,
        committed_logical_position=None,
    )
    ledger.append(
        run_id=receipt.run_id,
        arm=receipt.arm.value,
        logical_time=receipt.logical_time + 5,
        kind="evidence_application_reserved",
        artifact=forged,
    )
    with pytest.raises(EvidenceApplicationError, match="forged_application_id"):
        service.apply(receipt, reference, prior, draft)


def test_t6_persistent_uniqueness_and_distinct_applications_do_not_alias(
    tmp_path: Path,
) -> None:
    first = _prepared(tmp_path / "first", run_id="run-first")
    second = _prepared(tmp_path / "second", run_id="run-second")
    first_id = evidence_application_id(first[3], first[4], first[5])
    second_id = evidence_application_id(second[3], second[4], second[5])
    assert first_id != second_id

    for db, _, ledger, receipt, reference, prior, draft in (first, second):
        EvidenceApplicationService(
            ledger, CanonicalOutcomeResolver(db, ledger)
        ).apply(receipt, reference, prior, draft)
        reloaded, _ = _reload(db)
        assert _counts(reloaded, receipt.run_id)["applications_committed"] == 1


def test_t7_divergent_duplicate_fails_closed(tmp_path: Path) -> None:
    db, _, ledger, receipt, reference, prior, draft = _prepared(tmp_path)
    service = EvidenceApplicationService(ledger, CanonicalOutcomeResolver(db, ledger))
    with pytest.raises(InjectedApplicationCrash, match="after_reserve"):
        service.apply(
            receipt,
            reference,
            prior,
            draft,
            inject_failure=EvidenceApplicationService.AFTER_RESERVE,
        )
    divergent = _draft(
        prior,
        reference.reference_id,
        posterior=(0.70, 0.25, 0.05),
        rationale="divergent retry",
    )
    reloaded, resolver = _reload(db)
    with pytest.raises(LedgerIntegrityError, match="divergent_evidence_application"):
        EvidenceApplicationService(reloaded, resolver).apply(
            receipt, reference, prior, divergent
        )
    assert _counts(reloaded, receipt.run_id)["revisions"] == 0


@pytest.mark.parametrize(
    ("failure", "expected_retry"),
    (
        (EvidenceApplicationService.BEFORE_RESERVE, "applied"),
        (EvidenceApplicationService.AFTER_RESERVE, "recovered_reservation"),
        (EvidenceApplicationService.AFTER_REVISION, "recovered_revision"),
        (EvidenceApplicationService.BEFORE_COMMIT, "recovered_revision"),
    ),
)
def test_t8_t9_t10_t11_all_crash_windows_recover_exactly_once(
    tmp_path: Path, failure: str, expected_retry: str
) -> None:
    root = tmp_path / failure
    db, harness, ledger, receipt, reference, prior, draft = _prepared(root)
    before_budget = harness.budget.snapshot
    with pytest.raises(InjectedApplicationCrash, match=failure):
        EvidenceApplicationService(
            ledger, CanonicalOutcomeResolver(db, ledger)
        ).apply(receipt, reference, prior, draft, inject_failure=failure)

    reloaded, resolver = _reload(db)
    recovered = EvidenceApplicationService(reloaded, resolver).apply(
        receipt, reference, prior, draft
    )
    assert recovered.retry_result == expected_retry
    assert _counts(reloaded, receipt.run_id) == {
        "applications_reserved": 1,
        "applications_committed": 1,
        "revisions": 1,
        "selections": 1,
    }
    assert recovered.successor.evidence_ids.count(recovered.application.application_id) == 1
    assert harness.budget.snapshot == before_budget


def test_t12_two_ordinary_consumers_share_one_official_effect(tmp_path: Path) -> None:
    db, _, _, receipt, reference, prior, draft = _prepared(tmp_path)

    def consume(_index: int):
        local_db = _storage(tmp_path)
        ledger = ExperimentLedger(StorageLedgerBackend(local_db))
        resolver = CanonicalOutcomeResolver(local_db, ledger)
        return EvidenceApplicationService(ledger, resolver).apply(
            receipt, reference, prior, draft
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(consume, (1, 2)))
    final_ledger, _ = _reload(db)
    assert results[0].revision == results[1].revision
    assert results[0].successor == results[1].successor
    assert _counts(final_ledger, receipt.run_id) == {
        "applications_reserved": 1,
        "applications_committed": 1,
        "revisions": 1,
        "selections": 1,
    }


def test_t13_t14_evidence_history_once_and_retry_has_token_parity(
    tmp_path: Path,
) -> None:
    db, harness, ledger, receipt, reference, prior, draft = _prepared(tmp_path)
    before = harness.budget.snapshot
    service = EvidenceApplicationService(ledger, CanonicalOutcomeResolver(db, ledger))
    first = service.apply(receipt, reference, prior, draft)
    replay = service.apply(receipt, reference, prior, draft)
    application_id = first.application.application_id
    assert first.successor.evidence_ids.count(application_id) == 1
    assert replay.successor.evidence_ids.count(application_id) == 1
    assert harness.budget.snapshot == before
    assert receipt.budget_after.tokens_used - receipt.budget_before.tokens_used == 1


def test_h3_refuses_in_memory_dedup_as_authority(tmp_path: Path) -> None:
    db, _, _, _, _, _, _ = _prepared(tmp_path)
    in_memory = ExperimentLedger()
    with pytest.raises(PersistentAtomicityRequired, match="persistent_atomic"):
        EvidenceApplicationService(
            in_memory, CanonicalOutcomeResolver(db, in_memory)
        )


def test_official_harness_revision_requires_persistent_service(tmp_path: Path) -> None:
    db, harness, ledger, receipt, reference, prior, draft = _prepared(tmp_path)
    with pytest.raises(ValueError, match="persistent_evidence_application_service"):
        harness.revise(draft)
    canonical = harness.revise(
        draft,
        application_service=EvidenceApplicationService(
            ledger, CanonicalOutcomeResolver(db, ledger)
        ),
    )
    assert canonical.theory_before_id == prior.state_id
    assert canonical.outcome_reference_id == reference.reference_id


@pytest.mark.parametrize(
    "arm", (Arm.EXPERIMENTAL, Arm.C1_GREEDY, Arm.C2_RANDOM, Arm.C5_ORACLE)
)
def test_application_service_is_arm_neutral(tmp_path: Path, arm: Arm) -> None:
    run_id = f"run-{arm.value}"
    db, _, ledger, receipt, reference, prior, draft = _prepared(
        tmp_path / arm.value, arm=arm, run_id=run_id
    )
    result = EvidenceApplicationService(
        ledger, CanonicalOutcomeResolver(db, ledger)
    ).apply(receipt, reference, prior, draft)
    assert result.application.arm is arm


def test_t15_h2_reference_authenticity_still_precedes_h3(tmp_path: Path) -> None:
    db, _, ledger, receipt, reference, prior, draft = _prepared(tmp_path)
    forged = replace(reference, reference_id="forged-reference")
    with pytest.raises(Exception, match="canonical_reference_id_mismatch"):
        EvidenceApplicationService(
            ledger, CanonicalOutcomeResolver(db, ledger)
        ).apply(receipt, forged, prior, draft)
    assert _counts(ledger, receipt.run_id)["applications_reserved"] == 0
