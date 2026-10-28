"""Failure atlas constitucional (RNFE-T4)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Literal, Sequence


FailureSeverity = Literal["low", "medium", "high", "critical"]


@dataclass(frozen=True)
class FailureSignature:
    metrics: Dict[str, float]
    trigger: str


@dataclass(frozen=True)
class FailureClass:
    name: str
    severity: FailureSeverity
    reversible: bool
    recovery_protocol: str
    signature: FailureSignature


@dataclass(frozen=True)
class FailureAtlas:
    events: tuple[FailureClass, ...]

    # B26.2 — ejes que NO se pudieron evaluar porque la evidencia era `None`
    # (NO MEDIDO). Un atlas sin eventos pero con `unmeasured_axes` no vacío NO es
    # un certificado de salud: es un certificado con agujeros declarados.
    # Patrón: `checks_applied` (certification/trace_integrity.py), `unmeasured_vitals`
    # (control/homeostasis/life_monitor.py), `unmeasured_fields`
    # (certification/transfer_assessment.py).
    unmeasured_axes: tuple[str, ...] = ()

    @property
    def critical_count(self) -> int:
        return sum(1 for event in self.events if event.severity == "critical")

    @property
    def is_complete(self) -> bool:
        """True si TODOS los ejes pudieron evaluarse. Falso => hay abstenciones."""
        return not self.unmeasured_axes

    @property
    def total_risk(self) -> float:
        if not self.events:
            return 0.0
        weight = {"low": 0.2, "medium": 0.45, "high": 0.70, "critical": 1.0}
        return min(1.0, sum(weight[event.severity] for event in self.events) / len(self.events))


def detect_failure_atlas(
    *,
    drift_identity: float,
    drift_policy: float,
    delta_viability: float,
    memory_purity: float,
    modification_impact: float,
    erosion: float,
    renorm_residual: float | None,
    # B85 — TERCER estado. `renorm_residual=None` no alcanza: hay que decir POR QUÉ.
    # `True` = el eje NO TIENE SUJETO (no hubo cruce de régimen ⇒ no había nada que
    # renormalizar) ⇒ NO es un agujero y NO cuenta como no medido.
    # `False` = hubo un cruce real y no se pudo medir ⇒ agujero verdadero, se declara.
    renorm_not_applicable: bool = False,
) -> FailureAtlas:
    """Detecta clases de falla constitucional.

    B26.2: ``renorm_residual`` puede ser ``None`` = NO MEDIDO (el cruce de régimen
    no era renormalizable porque alguno de los dos escenarios no tiene régimen
    latente conocido). Ante ``None`` el detector **se abstiene**: no dispara
    `renorm_residual_spike` (sería una falsa alarma: "no sé renormalizar esto" no
    es "la renormalización falló catastróficamente") y **tampoco** lo lee como
    residual 0.0 (que era la mentira vieja: ausencia de dato = evidencia
    favorable). La abstención queda declarada en ``FailureAtlas.unmeasured_axes``.
    """
    events: list[FailureClass] = []
    unmeasured: list[str] = []

    if erosion > 0.55:
        events.append(
            FailureClass(
                name="constitutional_erosion",
                severity="critical" if erosion > 0.75 else "high",
                reversible=erosion <= 0.75,
                recovery_protocol="enforce_flow_quarantine_and_rebuild_trace",
                signature=FailureSignature(metrics={"erosion": round(erosion, 4)}, trigger="erosion_threshold"),
            )
        )

    if drift_policy > 0.50:
        events.append(
            FailureClass(
                name="policy_bifurcation",
                severity="high" if drift_policy < 0.75 else "critical",
                reversible=drift_policy < 0.80,
                recovery_protocol="phase_lock_policy_and_recalibrate_regime",
                signature=FailureSignature(metrics={"drift_policy": round(drift_policy, 4)}, trigger="policy_phase_jump"),
            )
        )

    if delta_viability > 0 and memory_purity < 0.5:
        events.append(
            FailureClass(
                name="false_recovery",
                severity="high",
                reversible=True,
                recovery_protocol="rollback_to_clean_window_and_recompute_viability",
                signature=FailureSignature(
                    metrics={"delta_viability": round(delta_viability, 4), "memory_purity": round(memory_purity, 4)},
                    trigger="recovery_without_purity",
                ),
            )
        )

    if memory_purity < 0.45:
        events.append(
            FailureClass(
                name="latent_contamination",
                severity="critical" if memory_purity < 0.30 else "high",
                reversible=memory_purity >= 0.30,
                recovery_protocol="memory_isolation_and_lineage_revalidation",
                signature=FailureSignature(metrics={"memory_purity": round(memory_purity, 4)}, trigger="purity_integral_breach"),
            )
        )

    # B26.2 — ABSTENCIÓN. `None` no entra a la comparación: no dispara la falla
    # (falso pánico) ni la descarta (falsa salud). Se declara y se sigue.
    #
    # PERO `None` significa DOS cosas distintas, y confundirlas rompe la señal (es la
    # distinción de B85, `runtime/certification/transfer_assessment.py`):
    #   - NO APLICABLE  : no hubo cruce de régimen ⇒ el eje **no tiene sujeto**. No es un
    #                     agujero: no había nada que renormalizar. NO cuenta como no medido.
    #   - NO MEDIDO     : hubo un cruce real pero el régimen no está mapeado ⇒ **agujero
    #                     verdadero**, y hay que declararlo.
    # Sin esta distinción, el episodio intra-escenario (el 99%) marcaría el atlas como
    # INCOMPLETO para siempre, y un agujero real quedaría indistinguible del caso trivial:
    # "atlas incompleto" pasaría a ser la norma permanente y dejaría de significar nada.
    if renorm_residual is None:
        if not renorm_not_applicable:
            unmeasured.append("renorm_residual")
    elif renorm_residual > 0.55:
        events.append(
            FailureClass(
                name="adversarial_transfer_illusion",
                severity="high" if renorm_residual < 0.75 else "critical",
                reversible=renorm_residual < 0.75,
                recovery_protocol="disable_edge_and_relearn_renormalization_map",
                signature=FailureSignature(metrics={"renorm_residual": round(renorm_residual, 4)}, trigger="renorm_residual_spike"),
            )
        )

    if drift_identity > 0.45:
        events.append(
            FailureClass(
                name="identity_fracture",
                severity="critical" if drift_identity > 0.70 else "high",
                reversible=drift_identity <= 0.70,
                recovery_protocol="lineage_anchor_restore_and_constitution_reset",
                signature=FailureSignature(metrics={"drift_identity": round(drift_identity, 4)}, trigger="identity_curvature_breach"),
            )
        )

    if modification_impact > 0.60:
        events.append(
            FailureClass(
                name="inheritance_corruption",
                severity="high" if modification_impact <= 0.80 else "critical",
                reversible=modification_impact <= 0.80,
                recovery_protocol="freeze_inheritance_and_recertify_modification_chain",
                signature=FailureSignature(metrics={"modification_impact": round(modification_impact, 4)}, trigger="modification_risk_peak"),
            )
        )

    return FailureAtlas(events=tuple(events), unmeasured_axes=tuple(unmeasured))
