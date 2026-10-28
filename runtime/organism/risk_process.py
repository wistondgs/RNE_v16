"""Proceso secuencial de riesgo constitucional (RNFE-T4)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Literal

from .failure_atlas import FailureAtlas, detect_failure_atlas


RiskScopeType = Literal["organism", "edge", "modification", "inheritance"]


@dataclass(frozen=True)
class EdgeRiskProfile:
    edge_id: str
    risk_score: float
    residual: float
    uncertainty: float
    expected_recovery_cost: float


@dataclass(frozen=True)
class ModificationRiskProfile:
    proposal_id: str
    risk_score: float
    impact_score: float


@dataclass(frozen=True)
class InheritanceRiskProfile:
    lineage_id: str
    risk_score: float
    consistency_score: float


@dataclass(frozen=True)
class RiskState:
    scope_type: RiskScopeType
    scope_key: str
    risk_score: float
    drift_identity: float
    drift_policy: float
    delta_viability: float
    delta_purity: float
    delta_modification: float
    failure_atlas: FailureAtlas


@dataclass(frozen=True)
class RiskUpdate:
    previous_risk: float
    updated_risk: float
    delta_risk: float
    decay_applied: float
    failure_atlas: FailureAtlas


class ConstitutionalRiskProcess:
    """R_{t+1} = Gamma(R_t, dI, dPi, dV, dP, dM)."""

    def __init__(self, *, decay: float = 0.92):
        self.decay = decay
        self._state: Dict[tuple[str, str], RiskState] = {}

    def get(self, *, scope_type: RiskScopeType, scope_key: str) -> RiskState | None:
        return self._state.get((scope_type, scope_key))

    def seed_score(
        self,
        *,
        scope_type: RiskScopeType,
        scope_key: str,
        risk_score: float,
    ) -> None:
        key = (scope_type, scope_key)
        if key in self._state:
            return
        self._state[key] = RiskState(
            scope_type=scope_type,
            scope_key=scope_key,
            risk_score=max(0.0, min(1.0, float(risk_score))),
            drift_identity=0.0,
            drift_policy=0.0,
            delta_viability=0.0,
            delta_purity=0.0,
            delta_modification=0.0,
            failure_atlas=FailureAtlas(events=()),
        )

    def update(
        self,
        *,
        scope_type: RiskScopeType,
        scope_key: str,
        drift_identity: float,
        drift_policy: float,
        delta_viability: float,
        delta_purity: float,
        delta_modification: float,
        erosion: float,
        renorm_residual: float | None,
        # B85 — distingue "el eje no tiene sujeto" (no hubo cruce) de "hubo cruce y no lo
        # pude medir". Sin esto, el episodio intra-escenario (el 99%) marcaría el atlas
        # como incompleto para siempre, y un agujero real sería indistinguible del trivial.
        renorm_not_applicable: bool = False,
    ) -> RiskUpdate:
        """Actualiza el riesgo del scope.

        B26.2: ``renorm_residual`` puede ser ``None`` = NO MEDIDO. En ese caso el
        término de riesgo de renormalización **se omite** (no se suma nada) en vez
        de sumar ``0.12 * 0.0``. Numéricamente es lo mismo, pero el significado no:
        el `None` queda declarado en ``atlas.unmeasured_axes``, de modo que ningún
        consumidor pueda leer este riesgo como "renormalización sin residual".
        El riesgo así calculado es un riesgo **incompleto**, no un riesgo bajo — y
        el veredicto (court_runtime._scope_from_risk) tiene prohibido certificar
        transferencia sobre un cruce con este eje sin medir.
        """
        key = (scope_type, scope_key)
        prev = self._state.get(key)
        prev_risk = prev.risk_score if prev is not None else 0.15

        atlas = detect_failure_atlas(
            drift_identity=drift_identity,
            drift_policy=drift_policy,
            delta_viability=delta_viability,
            memory_purity=max(0.0, 1.0 - delta_purity),
            modification_impact=delta_modification,
            erosion=erosion,
            renorm_residual=renorm_residual,
            renorm_not_applicable=renorm_not_applicable,
        )

        # Sequential update with decayed memory + structured increments.
        updated = (
            self.decay * prev_risk
            + 0.18 * max(0.0, drift_identity)
            + 0.16 * max(0.0, drift_policy)
            + 0.14 * max(0.0, -delta_viability)
            + 0.16 * max(0.0, delta_purity)
            + 0.12 * max(0.0, delta_modification)
            + 0.10 * atlas.total_risk
            + 0.14 * max(0.0, erosion)
        )
        if renorm_residual is not None:
            updated += 0.12 * max(0.0, renorm_residual)
        updated = max(0.0, min(1.0, updated))

        new_state = RiskState(
            scope_type=scope_type,
            scope_key=scope_key,
            risk_score=round(updated, 4),
            drift_identity=round(drift_identity, 4),
            drift_policy=round(drift_policy, 4),
            delta_viability=round(delta_viability, 4),
            delta_purity=round(delta_purity, 4),
            delta_modification=round(delta_modification, 4),
            failure_atlas=atlas,
        )
        self._state[key] = new_state

        return RiskUpdate(
            previous_risk=round(prev_risk, 4),
            updated_risk=round(updated, 4),
            delta_risk=round(updated - prev_risk, 4),
            decay_applied=self.decay,
            failure_atlas=atlas,
        )

    def to_profiles(self) -> tuple[list[EdgeRiskProfile], list[ModificationRiskProfile], list[InheritanceRiskProfile]]:
        edges: list[EdgeRiskProfile] = []
        mods: list[ModificationRiskProfile] = []
        inheritance: list[InheritanceRiskProfile] = []
        for (scope_type, scope_key), state in self._state.items():
            if scope_type == "edge":
                edges.append(
                    EdgeRiskProfile(
                        edge_id=scope_key,
                        risk_score=state.risk_score,
                        residual=max(0.0, state.delta_purity),
                        uncertainty=max(0.0, state.drift_policy),
                        expected_recovery_cost=max(0.0, state.delta_modification),
                    )
                )
            elif scope_type == "modification":
                mods.append(
                    ModificationRiskProfile(
                        proposal_id=scope_key,
                        risk_score=state.risk_score,
                        impact_score=max(0.0, state.delta_modification),
                    )
                )
            elif scope_type == "inheritance":
                inheritance.append(
                    InheritanceRiskProfile(
                        lineage_id=scope_key,
                        risk_score=state.risk_score,
                        consistency_score=max(0.0, 1.0 - state.drift_identity),
                    )
                )
        return edges, mods, inheritance
