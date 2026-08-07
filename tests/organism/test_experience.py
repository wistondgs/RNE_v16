"""Tests del sistema de Experiencia: recordar golpes, sabiduría ∝ daño, no repetir."""

from __future__ import annotations

import os
import tempfile

import pytest

from runtime.organism.experience import (
    ExperienceProvenance,
    ExperienceRecord,
    ExperienceStore,
    build_experience,
    compute_severity,
    experience_enabled,
    situation_key,
)
from runtime.organism.teacher import (
    BEHAVIORAL_AUTHORITY_NONE,
    LOCAL_7B_PRODUCER_TYPE,
    Teacher,
)


_MISSING = object()


def _store():
    os.environ["RNFE_STORAGE_MODE"] = "sqlite"
    os.environ["AEON_EVENT_DB"] = os.path.join(tempfile.mkdtemp(), "exp.db")
    os.environ["RNFE_ARTIFACT_ROOT"] = tempfile.mkdtemp()
    from runtime.storage import get_storage, reset_storage

    reset_storage()
    return ExperienceStore(storage=get_storage())


def _write_raw_experience(
    store,
    *,
    organism_id: str,
    episode_id: str,
    situation: str,
    intervention: str,
    severity: float,
    provenance=_MISSING,
    action: str = "act",
):
    structure = {
        "situation_key": situation,
        "scenario": "thermal",
        "regime": "alarm",
        "intervention": intervention,
        "severity": severity,
        "wound": severity >= 0.5,
        "viability_margin": 0.2,
        "ioc": 0.2,
        "risk": 0.7,
        "reward": -0.5,
        "action": action,
        "verdict": "uncertified",
        "failure_class": None,
    }
    if provenance is not _MISSING:
        structure["provenance"] = provenance
    store.storage.write_memory_record(
        run_id=organism_id,
        episode_id=episode_id,
        scale="experience",
        structure_json=structure,
        ioc_proxy=0.2,
        metadata={"origin": "historical_fixture"},
    )
    return structure


def _lesson(*, organism_id: str, situation: str):
    return {
        "organism_id": organism_id,
        "situation_key": situation,
        "scenario": "thermal",
        "regime": "alarm",
        "avoid": "deactivate_cooling",
        "prefer": "activate_cooling",
        "lesson": "Prefer cooling after an observed thermal wound.",
        "from_severity": 0.9,
    }


def test_flag_off_by_default(monkeypatch):
    monkeypatch.delenv("RNFE_EXPERIENCE", raising=False)
    assert experience_enabled() is False
    monkeypatch.setenv("RNFE_EXPERIENCE", "1")
    assert experience_enabled() is True


def test_severity_proportional_to_damage():
    # Cuanto más profundo el golpe, mayor la severidad (la sabiduría será ∝ a esto).
    deep = compute_severity(viability_margin=0.12, ioc=0.15, risk=0.72, action="quarantine", certified=False)
    mild = compute_severity(viability_margin=0.6, ioc=0.5, risk=0.4, action="act", certified=True)
    healthy = compute_severity(viability_margin=0.9, ioc=0.88, risk=0.14, action="act", certified=True)
    assert deep > mild > healthy
    assert deep >= 0.85  # cuarentena = herida grave
    assert healthy < 0.30  # buen episodio


def test_experience_record_rejects_non_observed_provenance():
    with pytest.raises(ValueError, match="experience_provenance_must_be_observed_outcome"):
        ExperienceRecord(
            organism_id="aeon-invalid",
            run_id="teacher",
            episode_id="synthetic-1",
            situation_key="situation",
            scenario="thermal",
            regime="alarm",
            intervention="activate_cooling",
            severity=0.0,
            wound=False,
            viability_margin=1.0,
            ioc=1.0,
            risk=0.0,
            reward=1.0,
            action="teacher_prefer",
            verdict="certified",
            provenance="teacher_prefer",  # type: ignore[arg-type]
        )


def test_situation_key_stable_and_discriminates():
    a = situation_key(scenario="thermal", regime="alarm", main_variable="temp")
    b = situation_key(scenario="thermal", regime="alarm", main_variable="temp")
    c = situation_key(scenario="thermal", regime="calm", main_variable="temp")
    assert a == b
    assert a != c


def test_record_and_recall_wound():
    store = _store()
    sig = situation_key(scenario="thermal", regime="alarm", main_variable="temp")
    exp = build_experience(
        organism_id="aeon-test", run_id="life-1", episode_id="e1",
        scenario="thermal", regime="alarm", main_variable="temp", causal_status="",
        intervention="deactivate_cooling", viability_margin=0.12, ioc=0.15, risk=0.72,
        reward=-0.5, action="act", certified=False, closure_passed=False, viability_delta=-0.4,
    )
    assert exp.wound is True
    assert exp.severity >= 0.5
    store.record(exp)
    recalled = store.recall(organism_id="aeon-test", situation=sig)
    assert len(recalled) == 1
    assert recalled[0]["intervention"] == "deactivate_cooling"
    assert recalled[0]["provenance"] == ExperienceProvenance.OBSERVED_OUTCOME.value


def test_wisdom_avoids_what_hurt_prefers_what_relieved():
    store = _store()
    sig = situation_key(scenario="thermal", regime="alarm", main_variable="temp")
    # Un golpe profundo con 'deactivate_cooling'
    store.record(build_experience(
        organism_id="aeon-w", run_id="l1", episode_id="e1", scenario="thermal", regime="alarm",
        main_variable="temp", causal_status="", intervention="deactivate_cooling",
        viability_margin=0.12, ioc=0.15, risk=0.72, reward=-0.5, action="act",
        certified=False, closure_passed=False, viability_delta=-0.4))
    # Un buen episodio con 'activate_cooling'
    store.record(build_experience(
        organism_id="aeon-w", run_id="l1", episode_id="e2", scenario="thermal", regime="alarm",
        main_variable="temp", causal_status="", intervention="activate_cooling",
        viability_margin=0.9, ioc=0.88, risk=0.14, reward=0.5, action="act",
        certified=True, closure_passed=True, viability_delta=0.05))
    w = store.wisdom(organism_id="aeon-w", situation=sig)
    assert w.avoid == "deactivate_cooling"
    assert w.prefer == "activate_cooling"
    assert w.scar["deactivate_cooling"] > w.scar.get("activate_cooling", 0.0)
    assert w.max_severity >= 0.5
    assert w.n == 2
    assert w.retrieved_n == 2
    assert w.rejected_missing_provenance == 0
    assert w.rejected_unknown_provenance == 0
    assert w.rejected_non_observed_provenance == 0


def test_cross_life_recall_same_organism_id():
    """Vidas distintas (run_id distinto) comparten experiencia bajo el mismo organism_id."""
    store = _store()
    sig = situation_key(scenario="thermal", regime="alarm", main_variable="temp")
    store.record(build_experience(
        organism_id="aeon-x", run_id="vida-1", episode_id="e1", scenario="thermal", regime="alarm",
        main_variable="temp", causal_status="", intervention="deactivate_cooling",
        viability_margin=0.12, ioc=0.15, risk=0.72, reward=-0.5, action="act",
        certified=False, closure_passed=False, viability_delta=-0.4))
    # "Nueva vida": otro run_id, mismo organism_id -> debe recordar el golpe de la vida anterior
    recalled = store.recall(organism_id="aeon-x", situation=sig)
    assert len(recalled) == 1
    assert recalled[0]["intervention"] == "deactivate_cooling"


def test_missing_provenance_is_readable_but_fails_closed():
    store = _store()
    sig = situation_key(scenario="thermal", regime="alarm", main_variable="temp")
    historical = _write_raw_experience(
        store,
        organism_id="aeon-historical",
        episode_id="legacy-1",
        situation=sig,
        intervention="deactivate_cooling",
        severity=0.9,
    )

    assert store.recall(organism_id="aeon-historical", situation=sig) == [historical]
    wisdom = store.wisdom(organism_id="aeon-historical", situation=sig)
    assert wisdom.n == 0
    assert wisdom.retrieved_n == 1
    assert wisdom.scar == {}
    assert wisdom.avoid is None
    assert wisdom.prefer is None
    assert wisdom.max_severity == 0.0
    assert wisdom.rejected_missing_provenance == 1
    assert store.recall(organism_id="aeon-historical", situation=sig) == [historical]


def test_unknown_provenance_fails_closed():
    store = _store()
    sig = situation_key(scenario="thermal", regime="alarm", main_variable="temp")
    _write_raw_experience(
        store,
        organism_id="aeon-unknown",
        episode_id="unknown-1",
        situation=sig,
        intervention="deactivate_cooling",
        severity=0.9,
        provenance="unrecognized_origin",
    )

    wisdom = store.wisdom(organism_id="aeon-unknown", situation=sig)
    assert wisdom.n == 0
    assert wisdom.scar == {}
    assert wisdom.rejected_unknown_provenance == 1


@pytest.mark.parametrize("action", ["teacher_scar", "teacher_prefer"])
def test_historical_teacher_artifacts_cannot_influence_wisdom(action):
    store = _store()
    sig = situation_key(scenario="thermal", regime="alarm", main_variable="temp")
    _write_raw_experience(
        store,
        organism_id="aeon-teacher-history",
        episode_id=f"historical-{action}",
        situation=sig,
        intervention="deactivate_cooling",
        severity=1.0,
        provenance=action,
        action=action,
    )

    wisdom = store.wisdom(organism_id="aeon-teacher-history", situation=sig)
    assert wisdom.n == 0
    assert wisdom.scar == {}
    assert wisdom.avoid is None
    assert wisdom.prefer is None
    assert wisdom.max_severity == 0.0
    assert wisdom.rejected_non_observed_provenance == 1


def test_teacher_lesson_creates_no_scar_or_prefer_experience():
    store = _store()
    sig = situation_key(scenario="thermal", regime="alarm", main_variable="temp")
    teacher = Teacher(storage=store.storage, experience=store)

    teacher._persist_lesson(_lesson(organism_id="aeon-proposal", situation=sig))

    assert store.recall(organism_id="aeon-proposal", situation=sig) == []
    assert store.storage.retrieve_memory_records(
        run_id="aeon-proposal", scales=["experience"], limit=20
    ) == []


def test_local_7b_proposal_is_auditable_and_non_authoritative():
    store = _store()
    sig = situation_key(scenario="thermal", regime="alarm", main_variable="temp")
    store.record(build_experience(
        organism_id="aeon-proposal-audit", run_id="life-1", episode_id="e1",
        scenario="thermal", regime="alarm", main_variable="temp", causal_status="",
        intervention="deactivate_cooling", viability_margin=0.12, ioc=0.15, risk=0.72,
        reward=-0.5, action="act", certified=False, closure_passed=False,
        viability_delta=-0.4,
    ))
    before = store.wisdom(organism_id="aeon-proposal-audit", situation=sig).to_dict()
    teacher = Teacher(storage=store.storage, experience=store)

    teacher._persist_lesson(_lesson(organism_id="aeon-proposal-audit", situation=sig))

    after = store.wisdom(organism_id="aeon-proposal-audit", situation=sig).to_dict()
    assert after == before
    events = store.storage.list_events(
        run_id=LOCAL_7B_PRODUCER_TYPE,
        event_types=["experience.lesson"],
        limit=10,
    )
    assert len(events) == 1
    assert events[0].source == LOCAL_7B_PRODUCER_TYPE
    assert events[0].payload["producer_type"] == LOCAL_7B_PRODUCER_TYPE
    assert events[0].payload["behavioral_authority"] == BEHAVIORAL_AUTHORITY_NONE
