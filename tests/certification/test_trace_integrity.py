"""B1: `trace_integrity` deja de ser tautológico y `trace_discontinuity` es alcanzable.

Antes (`transfer_assessment.py:151-152`)::

    trace = episode.get("trace", [])
    trace_integrity = len(trace) > 0 if trace else True   # True en AMBAS ramas

Una constante disfrazada de medición: el término de traza siempre aportaba su
máximo y el failure mode `trace_discontinuity` era **inalcanzable por
construcción**. Estos tests fijan la verificación real.
"""

import ast
from pathlib import Path

from runtime.certification.failure_modes import detect_failure_modes
from runtime.certification.ioc_proxy import IoCProxy
from runtime.certification.trace_integrity import (
    SEQUENCE_MISMATCH,
    STEP_MALFORMED,
    TIMESTAMP_REGRESSION,
    TRACE_EMPTY,
    TRACE_MALFORMED,
    TRACE_MISSING,
    assess_trace_integrity,
)
from runtime.certification.transfer_assessment import assess_transfer
from runtime.certification.transfer_posterior import compute_transfer_posterior
from runtime.reality.transition_analysis import TransitionContinuityVector
from runtime.world.compatibility import CompatibilityAssessment

_SEQUENCE = ["ABD", "ANA", "CAU", "CTF", "DED", "PROB"]


def _steps(families, *, base_ts=1000.0):
    """Pasos con la forma real de `ReasoningTraceStep.__dict__` (meta_scheduler)."""
    return [
        {
            "family": family,
            "status": "ok",
            "detail": {"selected_family": family},
            "timestamp": base_ts + index,
        }
        for index, family in enumerate(families)
    ]


def _episode(*, trace=..., sequence=_SEQUENCE, cross_mem=False):
    mem = []
    if cross_mem:
        mem = [{"analogical_source": True, "retrieval_metrics": {
            "retrieved_same_scenario_count": 1,
            "retrieved_cross_scenario_count": 1,
        }}]
    episode = {
        "episode_id": "ep-thermal",
        "scenario_metadata": {"scenario_name": "thermal_homeostasis"},
        "closure_profile": "baseline_fixed",
        "context": {"retrieved_memory": mem},
        "result": {"reasoning_sequence": list(sequence), "relation_kind": "support"},
    }
    if trace is not ...:  # `...` = clave ausente (episodio sin traza)
        episode["trace"] = trace
    return {"episode": episode}


# ── 1. La verificación real ──────────────────────────────────────────────────


def test_traza_integra_es_integra():
    result = assess_trace_integrity(_episode(trace=_steps(_SEQUENCE))["episode"])
    assert result.integral is True
    assert result.reason == "ok"
    assert result.step_count == 6
    # Los cinco chequeos corrieron: nada quedó "aprobado por defecto".
    assert result.checks_applied == (
        "present", "non_empty", "well_formed", "monotonic_ts", "sequence_match",
    )


def test_traza_ausente_no_es_integra():
    """Antes devolvía True (lo peor posible): ausencia de evidencia != integridad."""
    result = assess_trace_integrity(_episode(trace=...)["episode"])
    assert result.integral is False
    assert result.reason == TRACE_MISSING


def test_traza_vacia_no_es_integra():
    result = assess_trace_integrity(_episode(trace=[])["episode"])
    assert result.integral is False
    assert result.reason == TRACE_EMPTY


def test_traza_no_lista_no_es_integra():
    result = assess_trace_integrity(_episode(trace={"family": "ABD"})["episode"])
    assert result.integral is False
    assert result.reason == TRACE_MALFORMED


def test_paso_malformado_no_es_integro():
    trace = _steps(_SEQUENCE)
    del trace[2]["family"]
    result = assess_trace_integrity(_episode(trace=trace)["episode"])
    assert result.integral is False
    assert result.reason == STEP_MALFORMED
    assert result.details["step_index"] == 2

    trace = _steps(_SEQUENCE)
    trace[1]["status"] = ""
    result = assess_trace_integrity(_episode(trace=trace)["episode"])
    assert result.integral is False
    assert result.reason == STEP_MALFORMED


def test_discontinuidad_por_paso_faltante():
    """Falta un paso: la cadena de razonamiento está rota respecto de lo ejecutado."""
    trace = _steps([f for f in _SEQUENCE if f != "CAU"])  # falta CAU
    result = assess_trace_integrity(_episode(trace=trace)["episode"])
    assert result.integral is False
    assert result.reason == SEQUENCE_MISMATCH
    assert result.details["reasoning_sequence"] == _SEQUENCE


def test_discontinuidad_por_reordenamiento():
    reordered = ["ABD", "CAU", "ANA", "CTF", "DED", "PROB"]
    result = assess_trace_integrity(_episode(trace=_steps(reordered))["episode"])
    assert result.integral is False
    assert result.reason == SEQUENCE_MISMATCH


def test_discontinuidad_por_timestamp_que_retrocede():
    trace = _steps(_SEQUENCE)
    trace[3]["timestamp"] = 900.0  # retrocede: pasos de otra corrida mezclados
    result = assess_trace_integrity(_episode(trace=trace)["episode"])
    assert result.integral is False
    assert result.reason == TIMESTAMP_REGRESSION


def test_sin_secuencia_registrada_el_chequeo_se_abstiene_y_lo_declara():
    """No verificable != verificado ok: `sequence_match` no corre y se ve."""
    result = assess_trace_integrity(_episode(trace=_steps(_SEQUENCE), sequence=[])["episode"])
    assert result.integral is True
    assert "sequence_match" not in result.checks_applied
    assert "well_formed" in result.checks_applied


# ── 2. No queda la tautología en el código ───────────────────────────────────


def test_transfer_assessment_no_reintroduce_la_tautologia():
    """Tripwire: ninguna asignación de `trace_integrity` con un literal constante."""
    source = Path("runtime/certification/transfer_assessment.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "trace_integrity" not in targets:
            continue
        # Un literal (True/False) o un IfExp con literales en ambas ramas es una mentira.
        if isinstance(node.value, ast.Constant):
            offenders.append(node.lineno)
        if isinstance(node.value, ast.IfExp) and isinstance(node.value.orelse, ast.Constant):
            if node.value.orelse.value is True:
                offenders.append(node.lineno)
    assert not offenders, f"trace_integrity vuelve a ser constante en las líneas {offenders}"


# ── 3. assess_transfer propaga la integridad real ────────────────────────────


def test_assess_transfer_reporta_integridad_real():
    intact = assess_transfer(episode_result=_episode(trace=_steps(_SEQUENCE)))
    assert intact.trace_integrity is True
    assert intact.trace_integrity_reason == "ok"

    broken = assess_transfer(episode_result=_episode(trace=...))
    assert broken.trace_integrity is False
    assert broken.trace_integrity_reason == TRACE_MISSING


# ── 4. `trace_discontinuity` es ALCANZABLE (antes, imposible) ────────────────


def _compat():
    return CompatibilityAssessment(
        source_scenario="thermal_homeostasis",
        target_scenario="resource_management",
        compatibility_class="compatible",
        topology_score=0.9,
        objective_score=0.9,
        intervention_score=0.9,
        counterfactual_score=0.9,
        overall_score=0.85,
        penalty_multiplier=1.0,
        transfer_allowed=True,
        certification_allowed=True,
    )


def _vec():
    return TransitionContinuityVector(
        source_scenario="thermal_homeostasis",
        target_scenario="resource_management",
        semantic_retention=0.9,
        trace_stability=0.9,
        causal_stability=0.9,
        intervention_policy_stability=0.9,
        structural_compatibility=0.85,
        memory_purity=0.95,
        composite_score=0.88,
        transition_type="compatible",
    )


def test_trace_discontinuity_se_alcanza_con_traza_rota():
    """El failure mode existía en el código pero era inalcanzable."""
    broken_trace = _steps([f for f in _SEQUENCE if f != "CAU"])
    episode = _episode(trace=broken_trace, cross_mem=True)["episode"]
    integrity = assess_trace_integrity(episode)
    assert integrity.integral is False

    modes = detect_failure_modes(
        morphism_score=0.85,
        memory_purity=0.95,
        trace_integrity=integrity.integral,
        polarity_inversion=False,
        policy_confidence=0.8,
        causal_support=0.8,
        belief_shift_kl=0.05,
    )
    assert "trace_discontinuity" in [m.mode for m in modes.detected_modes]


def test_posterior_baja_con_traza_no_integra():
    """La likelihood del posterior deja de estar inflada por el True constante."""
    common = dict(
        source_scenario="thermal_homeostasis",
        target_scenario="resource_management",
        morphism_class="homomorphic",
        morphism_score=0.85,
        memory_purity=0.95,
        transfer_stability=0.88,
        policy_confidence=0.8,
        causal_support=0.8,
    )
    intact = compute_transfer_posterior(trace_integrity=True, **common)
    broken = compute_transfer_posterior(trace_integrity=False, **common)
    assert broken.transfer_posterior < intact.transfer_posterior
    assert "trace_discontinuity" not in [m.mode for m in intact.failure_modes.detected_modes]
    assert "trace_discontinuity" in [m.mode for m in broken.failure_modes.detected_modes]


def test_assess_transfer_penaliza_episodio_con_traza_rota():
    """Mismo episodio, misma compatibilidad: solo cambia la traza."""
    intact = assess_transfer(
        episode_result=_episode(trace=_steps(_SEQUENCE), cross_mem=True),
        compatibility=_compat(),
        transition_vector=_vec(),
    )
    broken = assess_transfer(
        episode_result=_episode(trace=_steps(_SEQUENCE[:3]), cross_mem=True),
        compatibility=_compat(),
        transition_vector=_vec(),
    )
    assert intact.trace_integrity is True
    assert broken.trace_integrity is False
    assert broken.transfer_posterior < intact.transfer_posterior
    assert broken.failure_mode_count > intact.failure_mode_count


# ── 5. El chequeo real, encadenado al IoC* ──────────────────────────────────


def test_ioc_star_baja_cuando_la_traza_no_es_integra():
    """El chequeo REAL de integridad, encadenado al IoC*, distingue traza rota de íntegra.

    HONESTIDAD SOBRE LO QUE ESTE TEST PRUEBA (y sobre lo que NO):
    esto es una composición **sintética** de `assess_trace_integrity` + `IoCProxy`. NO
    demuestra que "antes el IoC* no podía bajar": en producción el IoC* **ya** podía bajar,
    porque su único llamador (`promotion_gate.py:76-82`) le pasa el chequeo real del
    evaluator (`runtime/reality/evaluator.py:314`), no el bool tautológico de
    `transfer_assessment`.

    Lo que la tautología SÍ rompía —y esto es lo que el paquete arregla— era el otro
    camino: `transfer_assessment` -> posterior de transferencia (`transfer_posterior.py:128`,
    `trace_val` 1.0 en vez de 0.3) y `trace_discontinuity` **inalcanzable por construcción**
    (`failure_modes.py:136`). Ese es el daño real; decirlo de más sería reintroducir en el
    test la misma clase de mentira que P9 vino a matar.
    """
    proxy = IoCProxy()
    intact_episode = _episode(trace=_steps(_SEQUENCE))["episode"]
    broken_episode = _episode(trace=...)["episode"]  # sin traza

    common = dict(
        continuity_score=0.9,
        closure_passed=True,
        collapse_detected=False,
        uncertainty=0.2,
    )
    ioc_intact = proxy.compute(
        trace_integrity=assess_trace_integrity(intact_episode).integral, **common
    )
    ioc_broken = proxy.compute(
        trace_integrity=assess_trace_integrity(broken_episode).integral, **common
    )

    assert ioc_intact > ioc_broken
    # El término de traza pesa 0.20 en el IoC*.
    assert round(ioc_intact - ioc_broken, 4) == 0.2
