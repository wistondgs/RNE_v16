"""Experiencia — el organismo recuerda sus golpes y aprende de ellos.

Hoy el organismo registra sus heridas en ledgers que nunca vuelve a leer al
actuar, y su memoria solo guarda éxitos certificados. Este módulo cierra ese
lazo: destila CADA episodio (éxito y golpe) en un ``ExperienceRecord`` con una
firma de situación y una **severidad** ∈ [0,1] (cuánto daño le hizo), lo persiste
en un namespace por ``organism_id`` (recall cross-vida — no olvida entre vidas),
y ofrece la sabiduría acumulada de una situación para sesgar decisiones futuras.

Principio del usuario: *la sabiduría es proporcional al daño* — un roce deja una
lección tenue; una herida profunda, una lección fuerte. Y *la reflexión es parte
de su vida en todo momento* — el recall es continuo y barato.

Gated por ``RNFE_EXPERIENCE`` (off por defecto ⇒ conducta byte-idéntica).
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional
from uuid import uuid4

from runtime.storage import StorageFacade
from runtime.storage.records import MemoryRecord, StoredEvent, utc_now_iso
from runtime.organism.dynamic_state import canonical_hash

_TRUE = {"1", "true", "yes", "on"}

EXPERIENCE_SCALE = "experience"
WOUND_THRESHOLD = 0.5   # severidad ≥ esto = golpe
GAIN_THRESHOLD = 0.30   # severidad ≤ esto = buen episodio
OUTCOME_WITNESS_SCHEMA_VERSION = "observed-outcome-witness-v1"
_SCENARIO_OUTCOME_EVENT = "organism.life_transition.committed"
_LIFE_OUTCOME_EVENTS = frozenset(
    {"life.shutdown", "life.sleep", "life.quarantine", "life.rollback"}
)


class ExperienceIntegrityError(ValueError):
    """An experience attempted to gain authority without verified evidence."""


class ExperienceProvenance(str, Enum):
    """Procedencia admitida por la memoria de experiencia canónica."""

    OBSERVED_OUTCOME = "observed_outcome"


# Estos valores siguen siendo legibles/auditables, pero nunca son experiencia
# vivida. La elegibilidad no depende de esta lista: sólo OBSERVED_OUTCOME admite.
_KNOWN_NON_OBSERVED_PROVENANCE = frozenset(
    {
        "codex_proposal",
        "local_7b_proposal",
        "teacher_scar",
        "teacher_prefer",
        "validated_lesson",
    }
)


@dataclass(frozen=True, slots=True)
class ObservedOutcomeWitness:
    """Reference to an outcome already persisted by an execution path."""

    witness_id: str
    source_event_type: str
    source_record_id: str
    source_run_id: str
    organism_id: str
    episode_id: str
    action: str
    committed_intervention: str
    outcome_hash: str
    experience_hash: str
    schema_version: str = OUTCOME_WITNESS_SCHEMA_VERSION

    @classmethod
    def create(
        cls,
        *,
        source_event_type: str,
        source_record_id: str,
        source_run_id: str,
        organism_id: str,
        episode_id: str,
        action: str,
        committed_intervention: str,
        outcome_hash: str,
        experience_hash: str,
    ) -> "ObservedOutcomeWitness":
        payload = {
            "schema_version": OUTCOME_WITNESS_SCHEMA_VERSION,
            "source_event_type": str(source_event_type),
            "source_record_id": str(source_record_id),
            "source_run_id": str(source_run_id),
            "organism_id": str(organism_id),
            "episode_id": str(episode_id),
            "action": str(action),
            "committed_intervention": str(committed_intervention),
            "outcome_hash": str(outcome_hash),
            "experience_hash": str(experience_hash),
        }
        required = (
            "source_event_type",
            "source_record_id",
            "source_run_id",
            "organism_id",
            "episode_id",
            "action",
                "outcome_hash",
                "experience_hash",
        )
        if not all(payload[name] for name in required):
            raise ExperienceIntegrityError("outcome_witness_identity_required")
        return cls(witness_id=f"ow-{canonical_hash(payload)}", **payload)

    @classmethod
    def from_structure(cls, raw: Mapping[str, Any]) -> "ObservedOutcomeWitness":
        if not isinstance(raw, Mapping):
            raise ExperienceIntegrityError("outcome_witness_mapping_required")
        if raw.get("schema_version") != OUTCOME_WITNESS_SCHEMA_VERSION:
            raise ExperienceIntegrityError("outcome_witness_schema_mismatch")
        rebuilt = cls.create(
            source_event_type=str(raw.get("source_event_type") or ""),
            source_record_id=str(raw.get("source_record_id") or ""),
            source_run_id=str(raw.get("source_run_id") or ""),
            organism_id=str(raw.get("organism_id") or ""),
            episode_id=str(raw.get("episode_id") or ""),
            action=str(raw.get("action") or ""),
            committed_intervention=str(raw.get("committed_intervention") or ""),
            outcome_hash=str(raw.get("outcome_hash") or ""),
            experience_hash=str(raw.get("experience_hash") or ""),
        )
        if rebuilt.witness_id != raw.get("witness_id"):
            raise ExperienceIntegrityError("outcome_witness_id_mismatch")
        return rebuilt

    def to_structure(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "witness_id": self.witness_id,
            "source_event_type": self.source_event_type,
            "source_record_id": self.source_record_id,
            "source_run_id": self.source_run_id,
            "organism_id": self.organism_id,
            "episode_id": self.episode_id,
            "action": self.action,
            "committed_intervention": self.committed_intervention,
            "outcome_hash": self.outcome_hash,
            "experience_hash": self.experience_hash,
        }


def outcome_witness_from_event(event: StoredEvent) -> ObservedOutcomeWitness:
    """Derive a witness from an event already emitted by an execution path."""
    if not isinstance(event, StoredEvent):
        raise ExperienceIntegrityError("stored_outcome_event_required")
    payload = event.payload if isinstance(event.payload, Mapping) else {}
    run_id = str(event.run_id or payload.get("run_id") or "")
    event_type = str(event.event_type or "")
    source = str(event.source or payload.get("source") or "")

    if event_type == _SCENARIO_OUTCOME_EVENT:
        if source != "scenario_episode_runner":
            raise ExperienceIntegrityError("scenario_outcome_source_invalid")
        from runtime.organism.life_transition import LifeTransition

        try:
            transition = LifeTransition.from_dict(payload)
        except (TypeError, ValueError) as exc:
            raise ExperienceIntegrityError("scenario_outcome_transition_invalid") from exc
        facts = transition.factual_outcome.get("experience_facts")
        if not isinstance(facts, Mapping):
            raise ExperienceIntegrityError("scenario_experience_facts_missing")
        episode_id = transition.state_after.episode_id
        organism_id = transition.state_after.organism_id
        intervention = str(transition.committed_intervention.get("intervention") or "")
        if (
            str(facts.get("episode_id") or "") != episode_id
            or str(facts.get("organism_id") or "") != organism_id
            or str(facts.get("run_id") or "") != run_id
            or str(facts.get("intervention") or "") != intervention
        ):
            raise ExperienceIntegrityError("scenario_experience_facts_identity_mismatch")
        outcome = {
            "schema_version": "scenario-observed-outcome-v1",
            "transition_id": transition.transition_id,
            "transition_hash": transition.transition_hash,
            "state_before_hash": transition.state_before.state_hash,
            "state_after_hash": transition.state_after.state_hash,
            "committed_intervention": dict(transition.committed_intervention),
            "factual_outcome": dict(transition.factual_outcome),
        }
        return ObservedOutcomeWitness.create(
            source_event_type=event_type,
            source_record_id=transition.transition_id,
            source_run_id=run_id,
            organism_id=organism_id,
            episode_id=episode_id,
            action="act",
            committed_intervention=intervention,
            outcome_hash=canonical_hash(outcome),
            experience_hash=_experience_hash_from_facts(facts),
        )

    if event_type in _LIFE_OUTCOME_EVENTS:
        if source != "life_kernel":
            raise ExperienceIntegrityError("life_outcome_source_invalid")
        decision = payload.get("decision") if isinstance(payload.get("decision"), Mapping) else {}
        vitals = payload.get("vital_signs") if isinstance(payload.get("vital_signs"), Mapping) else {}
        action = event_type.removeprefix("life.")
        episode_id = str(payload.get("episode_id") or "")
        organism_id = str(payload.get("organism_id") or "")
        checkpoint_id = str(payload.get("checkpoint_artifact_id") or "")
        facts = payload.get("experience_facts")
        if (
            not episode_id
            or not organism_id
            or not checkpoint_id
            or not vitals
            or not isinstance(facts, Mapping)
            or str(decision.get("action") or "") != action
        ):
            raise ExperienceIntegrityError("life_outcome_incomplete")
        outcome = {
            "schema_version": "life-nonacting-observed-outcome-v1",
            "episode_id": episode_id,
            "action": action,
            "committed_intervention": "",
            "vital_signs": dict(vitals),
            "checkpoint_artifact_id": checkpoint_id,
        }
        return ObservedOutcomeWitness.create(
            source_event_type=event_type,
            source_record_id=f"{event_type}:{run_id}:{episode_id}",
            source_run_id=run_id,
            organism_id=organism_id,
            episode_id=episode_id,
            action=action,
            committed_intervention="",
            outcome_hash=canonical_hash(outcome),
            experience_hash=_experience_hash_from_facts(facts),
        )

    raise ExperienceIntegrityError("unsupported_outcome_event")


def experience_enabled() -> bool:
    """True si el organismo recuerda y aprende de su experiencia."""
    return os.environ.get("RNFE_EXPERIENCE", "").strip().lower() in _TRUE


def _clamp01(value: Any) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(max(v, 0.0), 1.0)


def situation_key(
    *,
    scenario: str | None,
    regime: str | None,
    main_variable: str | None,
    causal_status: str | None = None,
) -> str:
    """Firma estable y compacta de una situación (para relacionar presente↔pasado)."""
    raw = "|".join(
        str(x or "").strip().lower()
        for x in (scenario, regime, main_variable, causal_status)
    )
    digest = hashlib.blake2b(raw.encode("utf-8"), digest_size=8).hexdigest()
    return f"{str(scenario or 'na').strip().lower()}:{str(regime or 'na').strip().lower()}:{digest}"


def compute_severity(
    *,
    viability_margin: float,
    ioc: float,
    risk: float,
    action: str,
    certified: bool,
    closure_passed: bool = True,
    viability_delta: float = 0.0,
) -> float:
    """Cuánto dolió el episodio ∈ [0,1]. Alto = herida profunda.

    Compone baja viabilidad, colapso de cierre (IoC), riesgo y fallo de cierre;
    y aplica pisos por acción (cuarentena/rollback = herida grave). Una caída
    abrupta de viabilidad (viability_delta muy negativo) también duele.
    """
    vm = _clamp01(viability_margin)
    io = _clamp01(ioc)
    rk = _clamp01(risk)
    severity = (
        0.40 * (1.0 - vm)
        + 0.25 * (1.0 - io)
        + 0.20 * rk
        + 0.15 * (0.0 if closure_passed else 1.0)
    )
    # Golpe abrupto: una caída fuerte de viabilidad duele aunque el nivel no sea 0.
    drop = max(0.0, -float(viability_delta))
    severity = max(severity, _clamp01(2.0 * drop))
    act = str(action or "").strip().lower()
    if act == "rollback":
        severity = max(severity, 1.0)
    elif act == "quarantine":
        severity = max(severity, 0.85)
    elif act == "recovery" or act == "sleep":
        severity = max(severity, 0.35)
    if not certified:
        severity = max(severity, 0.40)
    return round(_clamp01(severity), 4)


def _experience_hash_from_facts(facts: Mapping[str, Any]) -> str:
    """Hash the exact fields that can shape canonical SituationWisdom."""
    required = (
        "organism_id",
        "run_id",
        "episode_id",
        "scenario",
        "regime",
        "main_variable",
        "intervention",
        "viability_margin",
        "ioc",
        "risk",
        "reward",
        "action",
        "certified",
        "closure_passed",
        "viability_delta",
    )
    if any(name not in facts for name in required):
        raise ExperienceIntegrityError("experience_facts_incomplete")
    severity = compute_severity(
        viability_margin=float(facts["viability_margin"]),
        ioc=float(facts["ioc"]),
        risk=float(facts["risk"]),
        action=str(facts["action"]),
        certified=bool(facts["certified"]),
        closure_passed=bool(facts["closure_passed"]),
        viability_delta=float(facts["viability_delta"]),
    )
    projection = {
        "organism_id": str(facts["organism_id"]),
        "run_id": str(facts["run_id"]),
        "episode_id": str(facts["episode_id"]),
        "situation_key": situation_key(
            scenario=str(facts["scenario"]),
            regime=str(facts["regime"]),
            main_variable=str(facts["main_variable"]),
            causal_status=str(facts.get("causal_status") or ""),
        ),
        "intervention": str(facts["intervention"]),
        "severity": severity,
        "wound": severity >= WOUND_THRESHOLD,
        "viability_margin": round(_clamp01(facts["viability_margin"]), 4),
        "ioc": round(_clamp01(facts["ioc"]), 4),
        "risk": round(_clamp01(facts["risk"]), 4),
        "reward": round(float(facts["reward"]), 4),
        "action": str(facts["action"]),
        "verdict": "certified" if bool(facts["certified"]) else "uncertified",
    }
    return canonical_hash(projection)


def _experience_hash_from_structure(structure: Mapping[str, Any]) -> str:
    fields = (
        "organism_id",
        "run_id",
        "episode_id",
        "situation_key",
        "intervention",
        "severity",
        "wound",
        "viability_margin",
        "ioc",
        "risk",
        "reward",
        "action",
        "verdict",
    )
    return canonical_hash({name: structure.get(name) for name in fields})


@dataclass(frozen=True, slots=True)
class ExperienceRecord:
    organism_id: str
    run_id: str
    episode_id: str
    situation_key: str
    scenario: str
    regime: str
    intervention: str
    severity: float
    wound: bool
    viability_margin: float
    ioc: float
    risk: float
    reward: float
    action: str
    verdict: str
    provenance: ExperienceProvenance
    outcome_hash: str
    outcome_witness: ObservedOutcomeWitness
    failure_class: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.provenance is not ExperienceProvenance.OBSERVED_OUTCOME:
            raise ValueError("experience_provenance_must_be_observed_outcome")
        if not isinstance(self.outcome_witness, ObservedOutcomeWitness):
            raise ExperienceIntegrityError("experience_outcome_witness_required")
        if self.outcome_hash != self.outcome_witness.outcome_hash:
            raise ExperienceIntegrityError("experience_outcome_hash_mismatch")
        if self.organism_id != self.outcome_witness.organism_id:
            raise ExperienceIntegrityError("experience_organism_mismatch")
        if self.run_id != self.outcome_witness.source_run_id:
            raise ExperienceIntegrityError("experience_run_mismatch")
        if self.episode_id != self.outcome_witness.episode_id:
            raise ExperienceIntegrityError("experience_episode_mismatch")
        if self.action != self.outcome_witness.action:
            raise ExperienceIntegrityError("experience_action_mismatch")
        if self.intervention != self.outcome_witness.committed_intervention:
            raise ExperienceIntegrityError("experience_intervention_mismatch")
        if _experience_hash_from_structure(self.to_structure()) != self.outcome_witness.experience_hash:
            raise ExperienceIntegrityError("experience_fields_hash_mismatch")

    def to_structure(self) -> Dict[str, Any]:
        return {
            "organism_id": self.organism_id,
            "run_id": self.run_id,
            "episode_id": self.episode_id,
            "situation_key": self.situation_key,
            "scenario": self.scenario,
            "regime": self.regime,
            "intervention": self.intervention,
            "severity": self.severity,
            "wound": self.wound,
            "viability_margin": self.viability_margin,
            "ioc": self.ioc,
            "risk": self.risk,
            "reward": self.reward,
            "action": self.action,
            "verdict": self.verdict,
            "provenance": self.provenance.value,
            "outcome_hash": self.outcome_hash,
            "outcome_witness": self.outcome_witness.to_structure(),
            "failure_class": self.failure_class,
        }


@dataclass(frozen=True, slots=True)
class SituationWisdom:
    """Lo que el organismo aprendió de una situación (sabiduría ∝ daño)."""

    situation_key: str
    n: int
    scar: Dict[str, float]            # intervención -> dolor acumulado (severidad media·frecuencia)
    avoid: Optional[str]             # la intervención que más lo hirió
    prefer: Optional[str]            # la que mejor le fue (menor severidad)
    max_severity: float              # el golpe más profundo recordado en esta situación
    retrieved_n: int = 0
    rejected_missing_provenance: int = 0
    rejected_unknown_provenance: int = 0
    rejected_non_observed_provenance: int = 0
    provenance_eligible_n: int = 0
    witness_verified_n: int = 0
    rejected_missing_witness: int = 0
    rejected_invalid_witness: int = 0
    rejected_unresolved_witness: int = 0
    rejected_episode_mismatch: int = 0
    rejected_intervention_mismatch: int = 0
    rejected_action_mismatch: int = 0
    rejected_outcome_hash_mismatch: int = 0
    rejected_experience_hash_mismatch: int = 0
    rejected_witness_replay: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "situation_key": self.situation_key,
            "n": self.n,
            "scar": self.scar,
            "avoid": self.avoid,
            "prefer": self.prefer,
            "max_severity": self.max_severity,
            "retrieved_n": self.retrieved_n,
            "rejected_missing_provenance": self.rejected_missing_provenance,
            "rejected_unknown_provenance": self.rejected_unknown_provenance,
            "rejected_non_observed_provenance": self.rejected_non_observed_provenance,
            "provenance_eligible_n": self.provenance_eligible_n,
            "witness_verified_n": self.witness_verified_n,
            "rejected_missing_witness": self.rejected_missing_witness,
            "rejected_invalid_witness": self.rejected_invalid_witness,
            "rejected_unresolved_witness": self.rejected_unresolved_witness,
            "rejected_episode_mismatch": self.rejected_episode_mismatch,
            "rejected_intervention_mismatch": self.rejected_intervention_mismatch,
            "rejected_action_mismatch": self.rejected_action_mismatch,
            "rejected_outcome_hash_mismatch": self.rejected_outcome_hash_mismatch,
            "rejected_experience_hash_mismatch": self.rejected_experience_hash_mismatch,
            "rejected_witness_replay": self.rejected_witness_replay,
        }


def build_experience(
    *,
    organism_id: str,
    run_id: str,
    episode_id: str,
    scenario: str,
    regime: str,
    main_variable: str,
    causal_status: str,
    intervention: str,
    viability_margin: float,
    ioc: float,
    risk: float,
    reward: float,
    action: str,
    outcome_witness: ObservedOutcomeWitness,
    certified: bool,
    closure_passed: bool = True,
    viability_delta: float = 0.0,
    failure_class: str | None = None,
) -> ExperienceRecord:
    """Destila un episodio en una experiencia con firma de situación y severidad."""
    sk = situation_key(
        scenario=scenario, regime=regime, main_variable=main_variable, causal_status=causal_status
    )
    severity = compute_severity(
        viability_margin=viability_margin, ioc=ioc, risk=risk, action=action,
        certified=certified, closure_passed=closure_passed, viability_delta=viability_delta,
    )
    return ExperienceRecord(
        organism_id=organism_id, run_id=run_id, episode_id=episode_id,
        situation_key=sk, scenario=str(scenario or ""), regime=str(regime or ""),
        intervention=str(intervention or ""), severity=severity,
        wound=severity >= WOUND_THRESHOLD,
        viability_margin=round(_clamp01(viability_margin), 4), ioc=round(_clamp01(ioc), 4),
        risk=round(_clamp01(risk), 4), reward=round(float(reward), 4),
        action=str(action or ""), verdict="certified" if certified else "uncertified",
        provenance=ExperienceProvenance.OBSERVED_OUTCOME,
        outcome_hash=outcome_witness.outcome_hash,
        outcome_witness=outcome_witness,
        failure_class=failure_class,
    )


class ExperienceStore:
    """Escribe y recuerda experiencias en el namespace del organismo (cross-vida)."""

    def __init__(self, *, storage: StorageFacade):
        self.storage = storage
        self.write_rejections: Dict[str, int] = {}

    def _reject_write(self, reason: str) -> None:
        self.write_rejections[reason] = self.write_rejections.get(reason, 0) + 1
        raise ExperienceIntegrityError(reason)

    @staticmethod
    def _empty_verification_counts() -> Dict[str, int]:
        return {
            "missing_witness": 0,
            "invalid_witness": 0,
            "unresolved_witness": 0,
            "episode_mismatch": 0,
            "intervention_mismatch": 0,
            "action_mismatch": 0,
            "outcome_hash_mismatch": 0,
            "experience_hash_mismatch": 0,
            "witness_replay": 0,
        }

    def _resolve_witness(
        self,
        witness: ObservedOutcomeWitness,
        cache: Dict[tuple[str, str], List[ObservedOutcomeWitness]] | None = None,
    ) -> tuple[bool, str]:
        key = (witness.source_run_id, witness.source_event_type)
        anchors = cache.get(key) if cache is not None else None
        if anchors is None:
            anchors = []
            try:
                events = self.storage.list_events(
                    run_id=witness.source_run_id,
                    event_types=[witness.source_event_type],
                    limit=5000,
                )
            except Exception:
                events = []
            for event in events:
                try:
                    anchors.append(outcome_witness_from_event(event))
                except ExperienceIntegrityError:
                    continue
            if cache is not None:
                cache[key] = anchors
        matches = [item for item in anchors if item.source_record_id == witness.source_record_id]
        if not matches:
            return False, "unresolved_witness"
        if len({item.witness_id for item in matches}) != 1:
            return False, "invalid_witness"
        anchor = matches[0]
        if anchor.episode_id != witness.episode_id:
            return False, "episode_mismatch"
        if anchor.committed_intervention != witness.committed_intervention:
            return False, "intervention_mismatch"
        if anchor.action != witness.action:
            return False, "action_mismatch"
        if anchor.outcome_hash != witness.outcome_hash:
            return False, "outcome_hash_mismatch"
        if anchor.organism_id != witness.organism_id:
            return False, "invalid_witness"
        if anchor.witness_id != witness.witness_id:
            return False, "invalid_witness"
        return True, "verified"

    def _verify_structure(
        self,
        exp: Mapping[str, Any],
        *,
        organism_id: str,
        cache: Dict[tuple[str, str], List[ObservedOutcomeWitness]] | None = None,
    ) -> tuple[bool, str, ObservedOutcomeWitness | None]:
        raw_witness = exp.get("outcome_witness")
        if raw_witness is None:
            return False, "missing_witness", None
        try:
            witness = ObservedOutcomeWitness.from_structure(raw_witness)
        except (ExperienceIntegrityError, TypeError, ValueError):
            return False, "invalid_witness", None
        if str(exp.get("organism_id") or "") != organism_id or witness.organism_id != organism_id:
            return False, "invalid_witness", witness
        if str(exp.get("run_id") or "") != witness.source_run_id:
            return False, "invalid_witness", witness
        if str(exp.get("episode_id") or "") != witness.episode_id:
            return False, "episode_mismatch", witness
        if str(exp.get("intervention") or "") != witness.committed_intervention:
            return False, "intervention_mismatch", witness
        if str(exp.get("action") or "") != witness.action:
            return False, "action_mismatch", witness
        if str(exp.get("outcome_hash") or "") != witness.outcome_hash:
            return False, "outcome_hash_mismatch", witness
        if _experience_hash_from_structure(exp) != witness.experience_hash:
            return False, "experience_hash_mismatch", witness
        resolved, reason = self._resolve_witness(witness, cache)
        return resolved, reason, witness

    def _verified_from_recalled(
        self,
        recalled: List[Dict[str, Any]],
        *,
        organism_id: str,
    ) -> tuple[List[Dict[str, Any]], Dict[str, int], int, int, int]:
        counts = self._empty_verification_counts()
        missing_provenance = 0
        unknown_provenance = 0
        non_observed_provenance = 0
        provenance_candidates: List[Dict[str, Any]] = []
        for exp in recalled:
            provenance = exp.get("provenance")
            if provenance == ExperienceProvenance.OBSERVED_OUTCOME.value:
                provenance_candidates.append(exp)
            elif provenance is None or not str(provenance).strip():
                missing_provenance += 1
            elif provenance in _KNOWN_NON_OBSERVED_PROVENANCE:
                non_observed_provenance += 1
            else:
                unknown_provenance += 1

        cache: Dict[tuple[str, str], List[ObservedOutcomeWitness]] = {}
        verified: List[tuple[Dict[str, Any], ObservedOutcomeWitness]] = []
        for exp in provenance_candidates:
            ok, reason, witness = self._verify_structure(
                exp, organism_id=organism_id, cache=cache
            )
            if ok and witness is not None:
                verified.append((exp, witness))
            else:
                counts[reason] = counts.get(reason, 0) + 1

        by_witness: Dict[str, List[Dict[str, Any]]] = {}
        for exp, witness in verified:
            by_witness.setdefault(witness.witness_id, []).append(exp)
        eligible: List[Dict[str, Any]] = []
        for records in by_witness.values():
            if len(records) == 1:
                eligible.append(records[0])
                continue
            hashes = {canonical_hash(item) for item in records}
            if len(hashes) == 1:
                eligible.append(records[0])
                counts["witness_replay"] += len(records) - 1
            else:
                counts["witness_replay"] += len(records)
        return (
            eligible,
            counts,
            missing_provenance,
            unknown_provenance,
            non_observed_provenance,
        )

    def record(self, exp: ExperienceRecord) -> bool:
        """Persist only a typed experience bound to a stored observed outcome."""
        if type(exp) is not ExperienceRecord:
            self._reject_write("invalid_type")
        if exp.provenance is not ExperienceProvenance.OBSERVED_OUTCOME:
            self._reject_write("invalid_provenance")
        structure = exp.to_structure()
        verified, reason, witness = self._verify_structure(
            structure, organism_id=exp.organism_id
        )
        if not verified or witness is None:
            self._reject_write(reason)

        for existing in self.recall(organism_id=exp.organism_id, limit=500):
            existing_witness = existing.get("outcome_witness")
            if not isinstance(existing_witness, Mapping):
                continue
            if existing_witness.get("witness_id") != witness.witness_id:
                continue
            if canonical_hash(existing) == canonical_hash(structure):
                return False
            self._reject_write("witness_replay")

        # Las heridas profundas se recuerdan más tiempo; las triviales se olvidan.
        ttl = None if exp.severity >= 0.75 else (60 * 24 * 3600 if exp.severity >= WOUND_THRESHOLD else 14 * 24 * 3600)
        record = MemoryRecord(
            memory_id=str(uuid4()),
            run_id=exp.organism_id,
            episode_id=exp.episode_id,
            scale=EXPERIENCE_SCALE,
            structure_json=structure,
            certificate_id=None,
            ioc_proxy=exp.ioc,
            ttl_seconds=ttl,
            # B24: valor NO COMPUTADO, impuesto sólo por el schema. NO CONFIAR
            # en él como medición de no-interferencia ni como fuente de autoridad.
            no_interference=True,
            support_count=1,
            metadata={
                "origin": "experience",
                "run_id": exp.run_id,
                "wound": exp.wound,
                "witness_id": witness.witness_id,
                "no_interference_computed": False,
            },
            created_at=utc_now_iso(),
        )
        try:
            self.storage.write_canonical_experience_record(record)
        except Exception:
            # A backend outage is non-authoritative: no memory was admitted.
            return False
        return True

    def recall(
        self,
        *,
        organism_id: str,
        situation: str | None = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        """Recupera experiencias del organismo (cross-vida), opcionalmente de una situación."""
        try:
            rows = self.storage.retrieve_memory_records(
                run_id=organism_id,
                scales=[EXPERIENCE_SCALE],
                limit=limit,
            )
        except Exception:
            return []
        out: List[Dict[str, Any]] = []
        for item in rows:
            struct = getattr(item, "structure_json", None) or {}
            if situation is not None and struct.get("situation_key") != situation:
                continue
            out.append(struct)
        return out

    def wisdom(self, *, organism_id: str, situation: str) -> SituationWisdom:
        """Sabiduría canónica: sólo outcomes vividos con witness verificado."""
        recalled = self.recall(organism_id=organism_id, situation=situation, limit=300)
        (
            exps,
            verification,
            rejected_missing,
            rejected_unknown,
            rejected_non_observed,
        ) = self._verified_from_recalled(recalled, organism_id=organism_id)
        scar: Dict[str, float] = {}
        relief: Dict[str, List[float]] = {}
        max_sev = 0.0
        for e in exps:
            iv = str(e.get("intervention") or "")
            sev = _clamp01(e.get("severity"))
            max_sev = max(max_sev, sev)
            if iv:
                scar[iv] = round(scar.get(iv, 0.0) + sev, 4)      # dolor acumulado (∝ daño y repetición)
                relief.setdefault(iv, []).append(sev)
        avoid = max(scar, key=scar.get) if scar else None
        prefer = None
        if relief:
            # la intervención con menor severidad media = la que mejor le fue
            prefer = min(relief, key=lambda k: sum(relief[k]) / len(relief[k]))
        return SituationWisdom(
            situation_key=situation, n=len(exps), scar=scar,
            avoid=avoid, prefer=prefer, max_severity=round(max_sev, 4),
            retrieved_n=len(recalled),
            rejected_missing_provenance=rejected_missing,
            rejected_unknown_provenance=rejected_unknown,
            rejected_non_observed_provenance=rejected_non_observed,
            provenance_eligible_n=(
                len(recalled)
                - rejected_missing
                - rejected_unknown
                - rejected_non_observed
            ),
            witness_verified_n=len(exps),
            rejected_missing_witness=verification["missing_witness"],
            rejected_invalid_witness=verification["invalid_witness"],
            rejected_unresolved_witness=verification["unresolved_witness"],
            rejected_episode_mismatch=verification["episode_mismatch"],
            rejected_intervention_mismatch=verification["intervention_mismatch"],
            rejected_action_mismatch=verification["action_mismatch"],
            rejected_outcome_hash_mismatch=verification["outcome_hash_mismatch"],
            rejected_experience_hash_mismatch=verification["experience_hash_mismatch"],
            rejected_witness_replay=verification["witness_replay"],
        )

    def verified_recall(
        self, *, organism_id: str, situation: str | None = None, limit: int = 200
    ) -> List[Dict[str, Any]]:
        """Return only records whose outcome witnesses still resolve."""
        recalled = self.recall(organism_id=organism_id, situation=situation, limit=limit)
        verified, _, _, _, _ = self._verified_from_recalled(
            recalled, organism_id=organism_id
        )
        return verified
