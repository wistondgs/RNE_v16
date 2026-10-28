"""Taxonomía de modos de fallo del organismo.

Define los modos de fallo que pueden ocurrir:
- memory_contamination: memoria cross-scenario contamina decisiones  [LOCAL]
- policy_drift: la política de intervención se desvía sin soporte     [LOCAL]
- belief_collapse: el estado de creencia pierde coherencia            [LOCAL]
- trace_discontinuity: la traza de razonamiento se rompe              [LOCAL]
- causal_inversion: la polaridad causal se invierte sin compensación  [TRANSFERENCIA]
- morphism_failure: el morfismo dirigido no alcanza umbral mínimo     [TRANSFERENCIA]

Cada modo tiene severidad, evidencia requerida y mitigación sugerida.

## P9.6 — dos ejes que este módulo tenía cruzados

**1. LOCAL vs TRANSFERENCIA (paso 2).** El módulo entero se llamaba "de transferencia" y
`detect_failure_modes` solo se alcanzaba desde `compute_transfer_posterior`, que corría
únicamente dentro de `if is_cross:` (`transfer_assessment.py`). Pero cuatro de los seis
modos NO son de transferencia: contaminarse la memoria, derivar la política, colapsar las
creencias y romperse la traza son cosas que le pasan al organismo **en su propia casa**,
en un episodio intra-escenario. Estaban archivados detrás de un gate de transferencia que
en la vida real (memoria limpia, un solo escenario) **casi nunca se abre**: el organismo
no podía detectar sus patologías locales. Ahora ``scope`` separa los dos conjuntos: lo
local se evalúa SIEMPRE que haya datos; lo de transferencia sigue exigiendo transferencia
(necesita un morfismo, que en un episodio local no existe).

**2. AUSENCIA vs SALUD.** Las evidencias son ``float | None``. ``None`` = **no medido**, y
un detector sin insumo **se ABSTIENE**: no dispara. Abstenerse tampoco es aprobar — el
chequeo simplemente no corrió, y se dice por nombre en ``checks_applied`` /
``unmeasured_inputs`` (mismo patrón que ``trace_integrity.checks_applied`` y que
``life_monitor.unmeasured_vitals``). Antes el llamador rellenaba los huecos con valores
favorables (``purity=1.0``, ``kl=0.0``) y el detector los leía como evidencia de salud:
la ausencia de dato se volvía evidencia a favor. Ahora la ausencia no es evidencia de
nada, ni a favor ni en contra.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Sequence

FailureSeverity = Literal["critical", "high", "medium", "low"]

FailureModeName = Literal[
    "memory_contamination",
    "causal_inversion",
    "policy_drift",
    "belief_collapse",
    "trace_discontinuity",
    "morphism_failure",
]

DetectionScope = Literal["all", "local", "transfer"]

# Patologías del organismo en su propia casa: no necesitan que haya transferencia para
# ocurrir NI para detectarse. Evaluarlas solo `if is_cross` era archivarlas.
LOCAL_MODES: tuple[FailureModeName, ...] = (
    "memory_contamination",
    "policy_drift",
    "belief_collapse",
    "trace_discontinuity",
)
# Patologías que solo existen SI hay transferencia: ambas requieren un morfismo dirigido
# entre escenarios (polaridad transportada / score del morfismo). En un episodio local no
# hay morfismo, así que no hay nada que medir — y por eso NO se fuerzan.
TRANSFER_MODES: tuple[FailureModeName, ...] = (
    "causal_inversion",
    "morphism_failure",
)


def modes_in_scope(scope: DetectionScope) -> tuple[FailureModeName, ...]:
    """Modos que corresponden evaluar bajo un scope dado."""
    if scope == "local":
        return LOCAL_MODES
    if scope == "transfer":
        return TRANSFER_MODES
    return LOCAL_MODES + TRANSFER_MODES


@dataclass(frozen=True)
class TransferFailureMode:
    """Modo de fallo detectado en una transferencia."""

    mode: FailureModeName
    severity: FailureSeverity
    evidence_score: float       # [0, 1] strength of evidence for this failure
    description: str
    mitigation: str


@dataclass(frozen=True)
class FailureModeAssessment:
    """Evaluación completa de modos de fallo.

    Attributes:
        detected_modes: Patologías efectivamente detectadas.
        total_risk: Riesgo agregado [0, 1].
        critical_count: Cuántas críticas.
        high_count: Cuántas altas.
        has_blocking_failure: Alguna crítica → bloquea transferencia.
        checks_applied: Detectores que SÍ pudieron correr (tenían insumo). Los que no
            corrieron NO cuentan como aprobados: ver ``unmeasured_inputs``.
        unmeasured_inputs: Evidencias que no se midieron. Un detector sin insumo se
            abstiene; su silencio NO es un "está sano".
    """

    detected_modes: tuple[TransferFailureMode, ...]
    total_risk: float           # Aggregate risk [0, 1]
    critical_count: int
    high_count: int
    has_blocking_failure: bool   # Any critical mode → blocks transfer
    checks_applied: tuple[FailureModeName, ...] = ()
    unmeasured_inputs: tuple[str, ...] = ()

    @property
    def detected_mode_names(self) -> tuple[str, ...]:
        return tuple(m.mode for m in self.detected_modes)


# ── Severity weights for risk aggregation ────────────────────────────────────

_SEVERITY_WEIGHTS = {
    "critical": 1.0,
    "high": 0.6,
    "medium": 0.3,
    "low": 0.1,
}


# ── Detection functions ──────────────────────────────────────────────────────

def detect_failure_modes(
    *,
    memory_purity: float | None = None,
    morphism_score: float | None = None,
    belief_shift_kl: float | None = None,
    policy_confidence: float | None = None,
    causal_support: float | None = None,
    trace_integrity: bool | None = None,
    polarity_inversion: bool = False,
    scope: DetectionScope = "all",
) -> FailureModeAssessment:
    """Detecta modos de fallo a partir de las evidencias REALMENTE medidas.

    P9.6: cada evidencia puede venir en ``None`` = **no medida**. El detector que depende
    de ella **se abstiene** (no dispara) y queda fuera de ``checks_applied``. Ausencia de
    dato no es evidencia de salud (el defecto que este paquete desarma) ni de enfermedad
    (el defecto simétrico, que sería igual de deshonesto).

    Args:
        memory_purity: Pureza de memoria [0, 1], o None si no se midió.
        morphism_score: Score del morfismo dirigido [0, 1], o None si no hay morfismo.
        belief_shift_kl: KL approx del belief shift [0, 1], o None si no hay prior.
        policy_confidence: Confianza en la política [0, 1], o None si no se midió.
        causal_support: Confianza en soporte causal [0, 1], o None si no se midió.
        trace_integrity: Si la traza es íntegra, o None si no se verificó.
        polarity_inversion: Si hay inversión de polaridad causal (solo con morfismo).
        scope: Qué familia evaluar — ``local`` (patologías propias del organismo),
            ``transfer`` (las que exigen transferencia) o ``all``.

    Returns:
        FailureModeAssessment con modos detectados, chequeos aplicados y evidencias
        no medidas.
    """
    modes: list[TransferFailureMode] = []
    checks: list[FailureModeName] = []
    unmeasured: list[str] = []
    selected = modes_in_scope(scope)

    # ── Memory contamination [LOCAL] ─────────────────────────────────────────
    if "memory_contamination" in selected:
        if memory_purity is None:
            unmeasured.append("memory_purity")
        else:
            checks.append("memory_contamination")
            if memory_purity < 0.70:
                severity: FailureSeverity = "critical" if memory_purity < 0.40 else "high"
                modes.append(TransferFailureMode(
                    mode="memory_contamination",
                    severity=severity,
                    evidence_score=round(1.0 - memory_purity, 4),
                    description=f"Memory purity {memory_purity:.2f} below safety threshold",
                    mitigation="Restrict to strict_same_scenario mode or flush cross-scenario cache",
                ))

    # ── Policy drift [LOCAL] ─────────────────────────────────────────────────
    # Umbral < 0.50. P9.6 paso 3: el productor (`build_belief_state`) tenía piso 0.5 y solo
    # subía ⇒ este detector era INALCANZABLE por aritmética. Se arregló el productor (que
    # ahora resta ante evidencia de contradicción), no el umbral.
    if "policy_drift" in selected:
        if policy_confidence is None:
            unmeasured.append("policy_confidence")
        else:
            checks.append("policy_drift")
            if policy_confidence < 0.50:
                severity = "high" if policy_confidence < 0.30 else "medium"
                modes.append(TransferFailureMode(
                    mode="policy_drift",
                    severity=severity,
                    evidence_score=round(1.0 - policy_confidence, 4),
                    description=f"Policy confidence {policy_confidence:.2f} indicates drift",
                    mitigation="Reset to default policy for target scenario",
                ))

    # ── Belief collapse [LOCAL] ──────────────────────────────────────────────
    if "belief_collapse" in selected:
        if belief_shift_kl is None:
            unmeasured.append("belief_shift_kl")
        else:
            checks.append("belief_collapse")
            if belief_shift_kl > 0.40:
                severity = "critical" if belief_shift_kl > 0.60 else "high"
                modes.append(TransferFailureMode(
                    mode="belief_collapse",
                    severity=severity,
                    evidence_score=round(belief_shift_kl, 4),
                    description=f"Belief shift KL={belief_shift_kl:.3f} indicates potential collapse",
                    mitigation="Increase warmup episodes in target scenario before trusting beliefs",
                ))

    # ── Trace discontinuity [LOCAL] ──────────────────────────────────────────
    if "trace_discontinuity" in selected:
        if trace_integrity is None:
            unmeasured.append("trace_integrity")
        else:
            checks.append("trace_discontinuity")
            if not trace_integrity:
                modes.append(TransferFailureMode(
                    mode="trace_discontinuity",
                    severity="high",
                    evidence_score=1.0,
                    description="Reasoning trace integrity broken during transition",
                    mitigation="Re-derive trace in target scenario context",
                ))

    # ── Causal inversion [TRANSFERENCIA] ─────────────────────────────────────
    # Requiere polaridad transportada por un morfismo: sin morfismo no hay inversión que
    # medir (no es que "no haya inversión": es que la pregunta no aplica).
    if "causal_inversion" in selected:
        if causal_support is None:
            unmeasured.append("causal_support")
        else:
            checks.append("causal_inversion")
            if polarity_inversion and causal_support < 0.60:
                severity = "critical" if causal_support < 0.30 else "high"
                modes.append(TransferFailureMode(
                    mode="causal_inversion",
                    severity=severity,
                    evidence_score=round(1.0 - causal_support, 4),
                    description="Causal polarity inverted without compensating support",
                    mitigation="Apply polarity correction in transport operator or block transfer",
                ))

    # ── Morphism failure [TRANSFERENCIA] ─────────────────────────────────────
    if "morphism_failure" in selected:
        if morphism_score is None:
            unmeasured.append("morphism_score")
        else:
            checks.append("morphism_failure")
            if morphism_score < 0.35:
                severity = "critical" if morphism_score < 0.15 else "medium"
                modes.append(TransferFailureMode(
                    mode="morphism_failure",
                    severity=severity,
                    evidence_score=round(1.0 - morphism_score, 4),
                    description=f"Morphism score {morphism_score:.3f} below transfer threshold",
                    mitigation="Restrict to local certification only",
                ))

    # Aggregate risk
    total_risk = 0.0
    for m in modes:
        total_risk += _SEVERITY_WEIGHTS[m.severity] * m.evidence_score
    total_risk = min(1.0, total_risk / max(len(modes), 1)) if modes else 0.0

    critical_count = sum(1 for m in modes if m.severity == "critical")
    high_count = sum(1 for m in modes if m.severity == "high")
    has_blocking = critical_count > 0

    return FailureModeAssessment(
        detected_modes=tuple(modes),
        total_risk=round(total_risk, 4),
        critical_count=critical_count,
        high_count=high_count,
        has_blocking_failure=has_blocking,
        checks_applied=tuple(checks),
        unmeasured_inputs=tuple(unmeasured),
    )
