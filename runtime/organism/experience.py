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
from typing import Any, Dict, List, Optional

from runtime.storage import StorageFacade

_TRUE = {"1", "true", "yes", "on"}

EXPERIENCE_SCALE = "experience"
WOUND_THRESHOLD = 0.5   # severidad ≥ esto = golpe
GAIN_THRESHOLD = 0.30   # severidad ≤ esto = buen episodio


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
    failure_class: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_structure(self) -> Dict[str, Any]:
        return {
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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "situation_key": self.situation_key,
            "n": self.n,
            "scar": self.scar,
            "avoid": self.avoid,
            "prefer": self.prefer,
            "max_severity": self.max_severity,
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
        failure_class=failure_class,
    )


class ExperienceStore:
    """Escribe y recuerda experiencias en el namespace del organismo (cross-vida)."""

    def __init__(self, *, storage: StorageFacade):
        self.storage = storage

    def record(self, exp: ExperienceRecord) -> None:
        """Persiste una experiencia. TTL largo para golpes graves (las cicatrices duran)."""
        # Las heridas profundas se recuerdan más tiempo; las triviales se olvidan.
        ttl = None if exp.severity >= 0.75 else (60 * 24 * 3600 if exp.severity >= WOUND_THRESHOLD else 14 * 24 * 3600)
        try:
            self.storage.write_memory_record(
                run_id=exp.organism_id,          # namespace por organismo, no por corrida
                episode_id=exp.episode_id,
                scale=EXPERIENCE_SCALE,
                structure_json=exp.to_structure(),
                certificate_id=None,
                ioc_proxy=exp.ioc,
                ttl_seconds=ttl,
                # B24: campo NO computado; se escribe True por default de schema
                # (columna NOT NULL). No confiar en este valor: nadie verificó que
                # esta experiencia no interfiera con otras memorias, y no hay
                # consumidor. Ver runtime/storage/records.py.
                no_interference=True,
                support_count=1,
                metadata={"origin": "experience", "run_id": exp.run_id, "wound": exp.wound},
            )
        except Exception:
            # La experiencia es best-effort; nunca debe romper la vida.
            pass

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
        """Sabiduría acumulada de una situación: qué evitar / qué preferir, ∝ daño."""
        exps = self.recall(organism_id=organism_id, situation=situation, limit=300)
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
        )
