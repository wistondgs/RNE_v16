"""Tests del sistema de Experiencia: recordar golpes, sabiduría ∝ daño, no repetir."""

from __future__ import annotations

import os
import tempfile
from dataclasses import replace
from uuid import uuid4

import pytest

from runtime.organism.experience import (
    ExperienceProvenance,
    ExperienceIntegrityError,
    ExperienceRecord,
    ExperienceStore,
    ObservedOutcomeWitness,
    build_experience,
    compute_severity,
    experience_enabled,
    _experience_hash_from_facts,
    outcome_witness_from_event,
    situation_key,
)
from runtime.organism.teacher import (
    BEHAVIORAL_AUTHORITY_NONE,
    LOCAL_7B_PRODUCER_TYPE,
    Teacher,
)
from runtime.organism.dynamic_state import OrganismDynamicState
from runtime.organism.life_transition import DynamicLifeChain
from runtime.storage.records import MemoryRecord, utc_now_iso
from runtime.storage.canonical_outcomes import (
    ACTING_OWNER,
    _issue_canonical_outcome_authority,
)


_MISSING = object()


def _store():
    os.environ["RNFE_STORAGE_MODE"] = "sqlite"
    os.environ["AEON_EVENT_DB"] = os.path.join(tempfile.mkdtemp(), "exp.db")
    os.environ["RNFE_ARTIFACT_ROOT"] = tempfile.mkdtemp()
    from runtime.storage import get_storage, reset_storage

    reset_storage()
    return ExperienceStore(storage=get_storage())


def _outcome_witness(
    store,
    *,
    organism_id: str,
    run_id: str,
    episode_id: str,
    intervention: str,
    viability_margin: float = 0.12,
    ioc: float = 0.15,
    risk: float = 0.72,
    reward: float = -0.5,
    certified: bool = False,
    closure_passed: bool = False,
    viability_delta: float = -0.4,
):
    lineage_id = f"lineage-{organism_id}"
    chains = getattr(store, "_test_dynamic_chains", None)
    if chains is None:
        chains = {}
        store._test_dynamic_chains = chains
    chain_key = (organism_id, run_id)
    chain = chains.get(chain_key)
    if chain is None:
        chain = DynamicLifeChain(
            organism_id=organism_id, lineage_id=lineage_id, run_id=run_id
        )
        chains[chain_key] = chain
    previous_state = chain.last_state
    logical_time = chain.transition_index * 2 + 1
    before = OrganismDynamicState.create(
        organism_id=organism_id, lineage_id=lineage_id, run_id=run_id,
        episode_id=episode_id, life_step=chain.transition_index * 2,
        logical_time=logical_time,
        previous_state_hash=(previous_state.state_hash if previous_state else None),
        world={}, regime={}, organism={}, memory={},
        neural={}, policy={}, resources={}, homeostasis={},
    )
    after = OrganismDynamicState.create(
        organism_id=organism_id, lineage_id=lineage_id, run_id=run_id,
        episode_id=episode_id, life_step=chain.transition_index * 2 + 1,
        logical_time=logical_time + 1,
        previous_state_hash=before.state_hash, world={}, regime={}, organism={},
        memory={}, neural={}, policy={}, resources={}, homeostasis={},
    )
    facts = {
        "organism_id": organism_id, "run_id": run_id, "episode_id": episode_id,
        "scenario": "thermal", "regime": "alarm", "main_variable": "temp",
        "causal_status": "", "intervention": intervention,
        "viability_margin": viability_margin, "ioc": ioc, "risk": risk,
        "reward": reward, "action": "act", "certified": certified,
        "closure_passed": closure_passed, "viability_delta": viability_delta,
    }
    authority = _issue_canonical_outcome_authority(
        storage=store.storage, owner=ACTING_OWNER
    )
    transition = chain.commit(
        state_before=before, state_after=after, trace_group_id=f"trace-{episode_id}",
        action_proposals=(), authoritative_decision={},
        committed_intervention={"intervention": intervention}, external_input=0.0,
        factual_outcome={"world_state_hash": "world", "experience_facts": facts},
        counterfactual_evidence={}, certificate={}, reward={"reward": reward},
        memory_delta={}, neural_state_delta={}, policy_delta={}, resource_delta={},
        viability_delta={}, regime_before={}, regime_after={},
        rollback_refuge_result={}, outcome_authority=authority,
    )
    assert transition.status == "committed"
    event = store.storage.list_events(
        run_id=run_id, event_types=["organism.life_transition.committed"], limit=10
    )[-1]
    return outcome_witness_from_event(event)


def _observed_experience(
    store,
    *,
    organism_id: str = "aeon-adversarial",
    run_id: str = "run-adversarial",
    episode_id: str = "episode-real",
    intervention: str = "activate_cooling",
):
    witness = _outcome_witness(
        store,
        organism_id=organism_id,
        run_id=run_id,
        episode_id=episode_id,
        intervention=intervention,
    )
    return build_experience(
        organism_id=organism_id,
        run_id=run_id,
        episode_id=episode_id,
        scenario="thermal",
        regime="alarm",
        main_variable="temp",
        causal_status="",
        intervention=intervention,
        viability_margin=0.12,
        ioc=0.15,
        risk=0.72,
        reward=-0.5,
        action="act",
        outcome_witness=witness,
        certified=False,
        closure_passed=False,
        viability_delta=-0.4,
    )


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
    _write_structure_raw(
        store,
        organism_id=organism_id,
        episode_id=episode_id,
        structure=structure,
    )
    return structure


def _write_structure_raw(store, *, organism_id: str, episode_id: str, structure):
    store.storage.backend.write_memory_record(
        MemoryRecord(
            memory_id=str(uuid4()),
            run_id=organism_id,
            episode_id=episode_id,
            scale="experience",
            structure_json=dict(structure),
            ioc_proxy=0.2,
            metadata={"origin": "historical_fixture"},
            created_at=utc_now_iso(),
        )
    )


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
    witness = ObservedOutcomeWitness.create(
        source_event_type="episode.closed",
        source_record_id="episode.closed:teacher:synthetic-1",
        source_run_id="teacher",
        organism_id="aeon-invalid",
        episode_id="synthetic-1",
        action="teacher_prefer",
        committed_intervention="activate_cooling",
        outcome_hash="f" * 64,
        experience_hash="e" * 64,
    )
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
            outcome_hash=witness.outcome_hash,
            outcome_witness=witness,
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
    witness = _outcome_witness(
        store, organism_id="aeon-test", run_id="life-1", episode_id="e1",
        intervention="deactivate_cooling",
    )
    exp = build_experience(
        organism_id="aeon-test", run_id="life-1", episode_id="e1",
        scenario="thermal", regime="alarm", main_variable="temp", causal_status="",
        intervention="deactivate_cooling", viability_margin=0.12, ioc=0.15, risk=0.72,
        reward=-0.5, action="act", certified=False, closure_passed=False, viability_delta=-0.4,
        outcome_witness=witness,
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
    wound_witness = _outcome_witness(
        store, organism_id="aeon-w", run_id="l1", episode_id="e1",
        intervention="deactivate_cooling",
    )
    store.record(build_experience(
        organism_id="aeon-w", run_id="l1", episode_id="e1", scenario="thermal", regime="alarm",
        main_variable="temp", causal_status="", intervention="deactivate_cooling",
        viability_margin=0.12, ioc=0.15, risk=0.72, reward=-0.5, action="act",
        certified=False, closure_passed=False, viability_delta=-0.4,
        outcome_witness=wound_witness))
    # Un buen episodio con 'activate_cooling'
    relief_witness = _outcome_witness(
        store, organism_id="aeon-w", run_id="l1", episode_id="e2",
        intervention="activate_cooling",
        viability_margin=0.9, ioc=0.88, risk=0.14, reward=0.5,
        certified=True, closure_passed=True, viability_delta=0.05,
    )
    store.record(build_experience(
        organism_id="aeon-w", run_id="l1", episode_id="e2", scenario="thermal", regime="alarm",
        main_variable="temp", causal_status="", intervention="activate_cooling",
        viability_margin=0.9, ioc=0.88, risk=0.14, reward=0.5, action="act",
        certified=True, closure_passed=True, viability_delta=0.05,
        outcome_witness=relief_witness))
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
    witness = _outcome_witness(
        store, organism_id="aeon-x", run_id="vida-1", episode_id="e1",
        intervention="deactivate_cooling",
    )
    store.record(build_experience(
        organism_id="aeon-x", run_id="vida-1", episode_id="e1", scenario="thermal", regime="alarm",
        main_variable="temp", causal_status="", intervention="deactivate_cooling",
        viability_margin=0.12, ioc=0.15, risk=0.72, reward=-0.5, action="act",
        certified=False, closure_passed=False, viability_delta=-0.4,
        outcome_witness=witness))
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


def test_historical_observed_label_without_witness_is_readable_but_ineligible():
    store = _store()
    sig = situation_key(scenario="thermal", regime="alarm", main_variable="temp")
    historical = _write_raw_experience(
        store,
        organism_id="aeon-f1a-history",
        episode_id="f1a-observed-label-only",
        situation=sig,
        intervention="deactivate_cooling",
        severity=1.0,
        provenance="observed_outcome",
    )
    assert store.recall(organism_id="aeon-f1a-history", situation=sig) == [historical]
    wisdom = store.wisdom(organism_id="aeon-f1a-history", situation=sig)
    assert wisdom.n == 0
    assert wisdom.provenance_eligible_n == 1
    assert wisdom.rejected_missing_witness == 1


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


def test_generic_storage_cannot_write_reserved_experience_scale():
    store = _store()
    with pytest.raises(ValueError, match="experience_scale_is_reserved"):
        store.storage.write_memory_record(
            run_id="aeon-spoof",
            episode_id="not-lived",
            scale="experience",
            structure_json={"provenance": "observed_outcome", "severity": 1.0},
        )


def test_experience_store_rejects_duck_typed_forgery():
    store = _store()

    class Forged:
        organism_id = "aeon-spoof"
        run_id = "teacher"
        episode_id = "not-lived"
        severity = 1.0
        ioc = 0.0
        wound = True

        def to_structure(self):
            return {
                "provenance": "observed_outcome",
                "intervention": "deactivate_cooling",
                "severity": 1.0,
            }

    with pytest.raises(ExperienceIntegrityError, match="invalid_type"):
        store.record(Forged())  # type: ignore[arg-type]
    assert store.write_rejections["invalid_type"] == 1


def test_fake_witness_id_is_unresolved_and_ineligible():
    store = _store()
    facts = {
        "organism_id": "aeon-spoof", "run_id": "missing-run",
        "episode_id": "missing-episode", "scenario": "thermal",
        "regime": "alarm", "main_variable": "temp", "causal_status": "",
        "intervention": "deactivate_cooling", "viability_margin": 0.0,
        "ioc": 0.0, "risk": 1.0, "reward": -1.0, "action": "act",
        "certified": False, "closure_passed": True, "viability_delta": 0.0,
    }
    witness = ObservedOutcomeWitness.create(
        source_event_type="episode.closed",
        source_record_id="episode.closed:missing-run:missing-episode",
        source_run_id="missing-run",
        organism_id="aeon-spoof",
        episode_id="missing-episode",
        action="act",
        committed_intervention="deactivate_cooling",
        outcome_hash="a" * 64,
        experience_hash=_experience_hash_from_facts(facts),
    )
    exp = build_experience(
        organism_id="aeon-spoof", run_id="missing-run", episode_id="missing-episode",
        scenario="thermal", regime="alarm", main_variable="temp", causal_status="",
        intervention="deactivate_cooling", viability_margin=0.0, ioc=0.0, risk=1.0,
        reward=-1.0, action="act", outcome_witness=witness, certified=False,
    )
    with pytest.raises(ExperienceIntegrityError, match="unresolved_witness"):
        store.record(exp)
    _write_structure_raw(
        store, organism_id=exp.organism_id, episode_id=exp.episode_id,
        structure=exp.to_structure(),
    )
    wisdom = store.wisdom(organism_id=exp.organism_id, situation=exp.situation_key)
    assert wisdom.n == 0
    assert wisdom.rejected_unresolved_witness == 1


@pytest.mark.parametrize(
    ("field", "value", "counter"),
    [
        ("episode_id", "wrong-episode", "rejected_episode_mismatch"),
        ("intervention", "wrong-intervention", "rejected_intervention_mismatch"),
    ],
)
def test_copied_witness_mismatch_is_ineligible(field, value, counter):
    store = _store()
    exp = _observed_experience(store)
    structure = exp.to_structure()
    structure[field] = value
    _write_structure_raw(
        store, organism_id=exp.organism_id, episode_id=exp.episode_id,
        structure=structure,
    )
    wisdom = store.wisdom(organism_id=exp.organism_id, situation=exp.situation_key)
    assert wisdom.n == 0
    assert getattr(wisdom, counter) == 1


def test_forged_outcome_hash_is_ineligible():
    store = _store()
    exp = _observed_experience(store)
    valid = exp.outcome_witness
    forged = ObservedOutcomeWitness.create(
        source_event_type=valid.source_event_type,
        source_record_id=valid.source_record_id,
        source_run_id=valid.source_run_id,
        organism_id=valid.organism_id,
        episode_id=valid.episode_id,
        action=valid.action,
        committed_intervention=valid.committed_intervention,
        outcome_hash="b" * 64,
        experience_hash=valid.experience_hash,
    )
    structure = exp.to_structure()
    structure["outcome_hash"] = forged.outcome_hash
    structure["outcome_witness"] = forged.to_structure()
    _write_structure_raw(
        store, organism_id=exp.organism_id, episode_id=exp.episode_id,
        structure=structure,
    )
    wisdom = store.wisdom(organism_id=exp.organism_id, situation=exp.situation_key)
    assert wisdom.n == 0
    assert wisdom.rejected_outcome_hash_mismatch == 1


def test_copied_witness_is_idempotent_and_never_doubles_authority():
    store = _store()
    exp = _observed_experience(store)
    assert store.record(exp) is True
    assert store.record(exp) is False
    _write_structure_raw(
        store, organism_id=exp.organism_id, episode_id=exp.episode_id,
        structure=exp.to_structure(),
    )
    forged_structure = exp.to_structure()
    forged_structure["severity"] = 0.0
    forged_structure["wound"] = False
    _write_structure_raw(
        store, organism_id=exp.organism_id, episode_id="forged-severity",
        structure=forged_structure,
    )
    wisdom = store.wisdom(organism_id=exp.organism_id, situation=exp.situation_key)
    assert wisdom.n == 1
    assert wisdom.rejected_witness_replay == 1
    assert wisdom.rejected_experience_hash_mismatch == 1
    with pytest.raises(ExperienceIntegrityError, match="experience_fields_hash_mismatch"):
        store.record(replace(exp, severity=0.0, wound=False))


def test_mixed_corpus_only_verified_outcome_can_shape_wisdom():
    store = _store()
    exp = _observed_experience(store, intervention="activate_cooling")
    assert store.record(exp) is True
    for index, provenance in enumerate(
        (None, "teacher_scar", "teacher_prefer", "unknown", "observed_outcome")
    ):
        structure = {
            "situation_key": exp.situation_key,
            "intervention": "deactivate_cooling",
            "severity": 1.0,
            "action": "teacher_scar",
            "verdict": "certified",
        }
        if provenance is not None:
            structure["provenance"] = provenance
        _write_structure_raw(
            store, organism_id=exp.organism_id, episode_id=f"spoof-{index}",
            structure=structure,
        )
    wisdom = store.wisdom(organism_id=exp.organism_id, situation=exp.situation_key)
    assert wisdom.n == 1
    assert wisdom.avoid == "activate_cooling"
    assert wisdom.scar == {"activate_cooling": exp.severity}
    assert wisdom.rejected_missing_witness == 1


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
    witness = _outcome_witness(
        store, organism_id="aeon-proposal-audit", run_id="life-1", episode_id="e1",
        intervention="deactivate_cooling",
    )
    store.record(build_experience(
        organism_id="aeon-proposal-audit", run_id="life-1", episode_id="e1",
        scenario="thermal", regime="alarm", main_variable="temp", causal_status="",
        intervention="deactivate_cooling", viability_margin=0.12, ioc=0.15, risk=0.72,
        reward=-0.5, action="act", certified=False, closure_passed=False,
        viability_delta=-0.4,
        outcome_witness=witness,
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
