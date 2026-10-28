"""Estado de creencia (belief state) para transferencia inter-escenario.

Captura un estado compacto de creencia del organismo tras cada episodio:
- Estimación de la variable principal
- Probabilidad de alarma
- Confianza en la política elegida
- Confianza en el soporte causal
- Confianza en la traza de razonamiento
- Confianza en la pureza de memoria

El belief state permite medir:
- BeliefShift: cuánto cambia la creencia en una transición
- Recovery: cuántos pasos necesita para estabilizarse
- Hysteresis: distancia residual tras retorno A→B→A
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Sequence


@dataclass(frozen=True)
class BeliefState:
    """Estado compacto de creencia del organismo tras un episodio.

    Cada componente es una probabilidad / confianza en [0, 1].
    """

    scenario_name: str
    episode_id: str
    main_variable_estimate: float
    alarm_probability: float
    policy_confidence: float
    causal_support_confidence: float
    trace_confidence: float
    memory_purity_confidence: float
    timestamp: str = ""

    @property
    def composite_confidence(self) -> float:
        """Confianza compuesta ponderada."""
        return min(1.0, (
            0.20 * self.policy_confidence
            + 0.25 * self.causal_support_confidence
            + 0.20 * self.trace_confidence
            + 0.15 * self.memory_purity_confidence
            + 0.20 * (1.0 - self.alarm_probability)  # Low alarm → high confidence
        ))


@dataclass(frozen=True)
class BeliefShift:
    """Shift de creencia entre dos estados consecutivos.

    Mide cuánto cambió cada componente y produce un score de estabilidad.
    """

    source_scenario: str
    target_scenario: str
    delta_main_variable: float
    delta_alarm: float
    delta_policy: float
    delta_causal_support: float
    delta_trace: float
    delta_memory_purity: float
    kl_divergence_approx: float
    stability_score: float
    recovery_needed: bool

    @property
    def is_large_shift(self) -> bool:
        return self.kl_divergence_approx > 0.30


@dataclass(frozen=True)
class TransitionEvidenceVector:
    """Vector de evidencia para una transición, más rico que TransitionContinuityVector.

    Incluye señales específicas de transferencia basadas en el belief state.
    """

    source_scenario: str
    target_scenario: str
    semantic_retention: float
    effect_retention: float
    policy_retention: float
    counterfactual_consistency: float
    memory_purity: float
    trace_integrity: float
    composite_evidence: float
    transition_type: str


# ── Builders ─────────────────────────────────────────────────────────────────

def build_belief_state(
    *,
    episode_result: Dict[str, Any],
) -> BeliefState:
    """Construye BeliefState a partir del resultado de un episodio.

    Args:
        episode_result: Resultado completo del episodio del runner.

    Returns:
        BeliefState con todas las componentes estimadas.
    """
    episode = episode_result.get("episode", {})
    context = episode.get("context", {})
    result_data = episode.get("result", {})
    scenario_metadata = episode.get("scenario_metadata", {})
    scenario_name = scenario_metadata.get("scenario_name", episode.get("scenario", "unknown"))
    episode_id = episode.get("episode_id", "unknown")
    main_var = scenario_metadata.get("main_variable", "temperature")

    # Main variable estimate
    observation = context.get("observation", {})
    main_val = float(observation.get(main_var, 0.5))

    # Alarm probability
    alarm = observation.get("alarm", False)
    alarm_prob = 0.9 if alarm else 0.1

    # Policy confidence: cuánta evidencia de memoria respalda —o CONTRADICE— la política.
    #
    # P9.6 paso 3 — DETECTOR MUERTO POR ARITMÉTICA.
    # Antes:
    #     policy_conf = 0.5                                    # base
    #     if memory_hits:
    #         support_count = <hits con relation_kind == "support">
    #         policy_conf = min(1.0, 0.5 + 0.2 * support_count)  # solo SUBE
    #
    # El piso del productor era 0.5 y el umbral de `policy_drift` es `< 0.50`
    # (`failure_modes.py`): el productor NO PODÍA EMITIR UN VALOR QUE DISPARARA SU PROPIO
    # DETECTOR. `policy_drift` era inalcanzable por construcción, no por buena salud.
    #
    # Se arregla el PRODUCTOR, no el umbral. Por qué:
    #   - El umbral 0.50 significa algo: "confianza por debajo de una moneda al aire = deriva".
    #     Subirlo (p.ej. a 0.70) haría que el detector disparara con el valor BASE del
    #     productor, es decir con CERO evidencia: la ausencia de memoria se leería como
    #     deriva. Ese es el error simétrico del que este paquete viene a desarmar.
    #   - El defecto real estaba en el productor: los hits cuya `relation_kind` es
    #     "contradiction" —memorias donde la intervención NO produjo el efecto esperado—
    #     no contaban para NADA. "La evidencia dice que mi política no funciona" y "no tengo
    #     evidencia" daban el mismo 0.5. Al no existir camino descendente, la confianza solo
    #     podía subir. La evidencia en contra existía en la memoria (el condensador la guarda:
    #     `mfm_lite/condenser.py:65`) y el productor la tiraba a la basura.
    #
    # Ahora la evidencia es SIMÉTRICA: el soporte sube la confianza, la contradicción la baja,
    # con el mismo peso. Sin memoria, sigue valiendo 0.5 = "no sé" (ni sano ni enfermo), que
    # NO dispara el detector. Con memoria contradictoria, la confianza cae por debajo de 0.5
    # y `policy_drift` puede disparar — que era exactamente lo imposible.
    memory_hits = context.get("retrieved_memory", [])
    policy_conf = 0.5  # base: sin evidencia, "no sé" (no dispara el detector)
    if memory_hits:
        support_count = 0
        contradiction_count = 0
        for h in memory_hits:
            if not isinstance(h, dict):
                continue
            kind = h.get("structure", {}).get("relation_kind")
            if kind == "support":
                support_count += 1
            elif kind == "contradiction":
                contradiction_count += 1
        policy_conf = max(
            0.0,
            min(1.0, 0.5 + 0.2 * support_count - 0.2 * contradiction_count),
        )

    # Causal support confidence
    relation_kind = result_data.get("relation_kind")
    if relation_kind == "support":
        causal_conf = 0.90
    elif relation_kind == "contradiction":
        causal_conf = 0.20
    else:
        causal_conf = 0.50

    # Trace confidence
    trace = episode.get("trace", [])
    trace_conf = 0.80 if trace else 0.40

    # Memory purity confidence
    purity_conf = 1.0
    for hit in (memory_hits if isinstance(memory_hits, list) else []):
        if isinstance(hit, dict) and hit.get("analogical_source"):
            purity_conf = max(0.5, purity_conf - 0.15)
        metrics = hit.get("retrieval_metrics", {}) if isinstance(hit, dict) else {}
        cross = metrics.get("retrieved_cross_scenario_count", 0)
        if cross > 0:
            purity_conf = max(0.3, purity_conf - 0.10 * cross)

    # Certification boost
    cert = episode_result.get("certification", {})
    if cert.get("verdict") == "certified":
        trace_conf = min(1.0, trace_conf + 0.10)

    ts = episode.get("timestamp", "")

    return BeliefState(
        scenario_name=scenario_name,
        episode_id=episode_id,
        main_variable_estimate=round(main_val, 4),
        alarm_probability=round(alarm_prob, 4),
        policy_confidence=round(policy_conf, 4),
        causal_support_confidence=round(causal_conf, 4),
        trace_confidence=round(trace_conf, 4),
        memory_purity_confidence=round(purity_conf, 4),
        timestamp=ts,
    )


def compute_belief_shift(
    *,
    prior: BeliefState,
    posterior: BeliefState,
) -> BeliefShift:
    """Computa el shift de creencia entre prior y posterior.

    Incluye una aproximación de KL divergence como distancia
    entre los dos estados de creencia.

    Args:
        prior: Estado de creencia previo.
        posterior: Estado de creencia actual.

    Returns:
        BeliefShift con deltas, KL approximation y stability score.
    """
    d_main = abs(posterior.main_variable_estimate - prior.main_variable_estimate)
    d_alarm = abs(posterior.alarm_probability - prior.alarm_probability)
    d_policy = abs(posterior.policy_confidence - prior.policy_confidence)
    d_causal = abs(posterior.causal_support_confidence - prior.causal_support_confidence)
    d_trace = abs(posterior.trace_confidence - prior.trace_confidence)
    d_purity = abs(posterior.memory_purity_confidence - prior.memory_purity_confidence)

    # Approximation of KL divergence using component-wise differences
    # KL ≈ sum of |p_i - q_i| * log(max(p_i, ε) / max(q_i, ε))
    # Simplified to a weighted L1 distance for stability
    components = [d_main, d_alarm, d_policy, d_causal, d_trace, d_purity]
    kl_approx = sum(components) / len(components)

    # Stability score: 1 - normalized shift
    stability = max(0.0, 1.0 - kl_approx)

    # Recovery needed if shift is substantial
    recovery_needed = kl_approx > 0.20

    return BeliefShift(
        source_scenario=prior.scenario_name,
        target_scenario=posterior.scenario_name,
        delta_main_variable=round(d_main, 4),
        delta_alarm=round(d_alarm, 4),
        delta_policy=round(d_policy, 4),
        delta_causal_support=round(d_causal, 4),
        delta_trace=round(d_trace, 4),
        delta_memory_purity=round(d_purity, 4),
        kl_divergence_approx=round(kl_approx, 4),
        stability_score=round(stability, 4),
        recovery_needed=recovery_needed,
    )


def compute_transition_evidence(
    *,
    prior: BeliefState,
    posterior: BeliefState,
    morphism_score: float = 1.0,
    trace_integrity: bool = True,
) -> TransitionEvidenceVector:
    """Computa vector de evidencia de transición basado en belief states.

    Combina el shift de creencia con señales de morfismo y traza.

    Args:
        prior: BeliefState previo.
        posterior: BeliefState actual.
        morphism_score: Score del morfismo dirigido entre escenarios.
        trace_integrity: Si la traza de razonamiento es íntegra.

    Returns:
        TransitionEvidenceVector con evidencia compuesta.
    """
    shift = compute_belief_shift(prior=prior, posterior=posterior)

    # Semantic retention: based on policy stability
    semantic = max(0.0, 1.0 - shift.delta_policy)

    # Effect retention: based on causal support stability
    effect = max(0.0, 1.0 - shift.delta_causal_support)

    # Policy retention: direct from belief
    policy = posterior.policy_confidence

    # Counterfactual consistency: based on causal support confidence
    cf_consistency = posterior.causal_support_confidence

    # Memory purity
    purity = posterior.memory_purity_confidence

    # Trace integrity
    trace = 1.0 if trace_integrity else 0.0

    # Composite evidence
    composite = (
        0.15 * semantic
        + 0.20 * effect
        + 0.20 * policy
        + 0.15 * cf_consistency
        + 0.15 * purity
        + 0.15 * trace
    ) * (0.5 + 0.5 * morphism_score)  # Morphism modulates overall evidence

    transition_type = "intra" if prior.scenario_name == posterior.scenario_name else "cross"

    return TransitionEvidenceVector(
        source_scenario=prior.scenario_name,
        target_scenario=posterior.scenario_name,
        semantic_retention=round(semantic, 4),
        effect_retention=round(effect, 4),
        policy_retention=round(policy, 4),
        counterfactual_consistency=round(cf_consistency, 4),
        memory_purity=round(purity, 4),
        trace_integrity=round(trace, 4),
        composite_evidence=round(composite, 4),
        transition_type=transition_type,
    )
