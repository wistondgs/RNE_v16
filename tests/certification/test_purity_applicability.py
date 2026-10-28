"""B85 — la pureza vacua es NO APLICABLE, no una medición de 1.0.

La compuerta `memory_purity >= 0.85` de `is_restorable` existe para UNA cosa: impedir que el
organismo se refugie en un estado con memoria CONTAMINADA. Si el retrieval no devolvió ningún
hit, no hay memoria que pueda estar contaminada. Ese eje no es "desconocido" (eso es
`unmeasured`) ni es "pureza verificada en 1.0": **no aplica**.

Por eso el fix NO cambia el comportamiento —pasar la compuerta con cero memoria era y sigue
siendo correcto— sino la AFIRMACIÓN. Antes, `_measure_memory_purity` devolvía `1.0` y el
certificado lo publicaba como `memory_purity_score`, indistinguible de una pureza ganada sobre
50 hits limpios: **una medición que nunca se hizo**, consumida por la compuerta como evidencia.

Tres estados, y este archivo los separa:
  MEASURED       hubo hits ⇒ hubo oportunidad de contaminarse ⇒ el número es evidencia ganada.
  NOT_APPLICABLE cero hits ⇒ no hay nada que contaminar ⇒ el eje no aplica (y NO bloquea).
  UNMEASURED     hubo hits pero faltan las métricas ⇒ ausencia real ⇒ el eje se abstiene.
"""

from runtime.certification.transfer_assessment import (
    PURITY_MEASURED,
    PURITY_NOT_APPLICABLE,
    PURITY_UNMEASURED,
    assess_transfer,
    purity_not_applicable,
)

_SEQUENCE = ["ABD", "ANA", "CAU", "CTF", "DED", "PROB"]


def _trace():
    return [
        {"family": f, "status": "ok", "detail": {}, "timestamp": 1000.0 + i}
        for i, f in enumerate(_SEQUENCE)
    ]


def _episode(*, memory=None):
    return {
        "episode": {
            "trace": _trace(),
            "episode_id": "ep-b85",
            "scenario_metadata": {
                "scenario_name": "thermal_homeostasis",
                "main_variable": "temperature",
            },
            "closure_profile": "adaptive_min",
            "context": {
                "observation": {"temperature": 0.8, "alarm": True},
                "retrieved_memory": memory if memory is not None else [],
            },
            "result": {
                "updated_world": {"temperature": 0.78},
                "relation_kind": "support",
                "reasoning_sequence": list(_SEQUENCE),
            },
        },
    }


def _hits(*, same: int, cross: int):
    """Hits CON métricas: el retriever dejó sus conteos ⇒ la pureza es medible."""
    return [
        {
            "structure": {"relation_kind": "support"},
            "retrieval_metrics": {
                "retrieved_same_scenario_count": same,
                "retrieved_cross_scenario_count": cross,
            },
        }
        for _ in range(same + cross)
    ]


def _hits_without_metrics(n: int):
    """Hits SIN métricas: hubo oportunidad de contaminarse y NO sabemos si pasó."""
    return [{"structure": {"relation_kind": "support"}} for _ in range(n)]


# ── EL ESTADO QUE FALTABA: NO APLICABLE ─────────────────────────────────────────

def test_zero_hits_is_not_applicable_not_a_measurement():
    """EL BUG, DESNUDO: sin memoria recuperada, el 1.0 NO es una medición.

    El número no cambia (bajarlo sería fabricar en el otro sentido y mataría el refugio).
    Lo que cambia es que deja de venderse como evidencia ganada.
    """
    result = assess_transfer(episode_result=_episode(memory=[]))

    assert result.memory_purity_score == 1.0, "el número NO se toca: pasar es correcto"
    assert result.memory_purity_basis["status"] == PURITY_NOT_APPLICABLE
    assert result.memory_purity_basis["contamination_opportunity"] is False
    assert "memory_purity" in result.not_applicable_fields

    # Y NO es un agujero: no hay nada que medir, así que no puede estar "no medido".
    assert "memory_purity" not in result.unmeasured_fields


def test_measured_purity_is_not_declared_not_applicable():
    """Con hits limpios, el 1.0 se GANÓ: hubo memoria que pudo contaminar y no contaminó."""
    result = assess_transfer(episode_result=_episode(memory=_hits(same=3, cross=0)))

    assert result.memory_purity_score == 1.0
    assert result.memory_purity_basis["status"] == PURITY_MEASURED
    assert result.memory_purity_basis["contamination_opportunity"] is True
    assert "memory_purity" not in result.not_applicable_fields
    assert "memory_purity" not in result.unmeasured_fields


def test_contaminated_purity_is_measured_evidence():
    """El eje APLICA y la evidencia es en contra: 1 - 2/3 = 0.33."""
    result = assess_transfer(episode_result=_episode(memory=_hits(same=1, cross=2)))

    assert result.memory_purity_basis["status"] == PURITY_MEASURED
    assert result.memory_purity_score is not None
    assert result.memory_purity_score < 0.70
    assert "memory_purity" not in result.not_applicable_fields


def test_hits_without_metrics_is_unmeasured_not_not_applicable():
    """LA DISTINCIÓN QUE SALVA LA COMPUERTA: hubo memoria, faltan las métricas.

    Acá SÍ hubo oportunidad de contaminarse y no sabemos si pasó. Eso es ausencia REAL
    (patrón P9.5): el eje se abstiene y la compuerta se cierra. Confundirlo con "no aplica"
    sería exactamente la mentira original con otro nombre.
    """
    result = assess_transfer(episode_result=_episode(memory=_hits_without_metrics(4)))

    assert result.memory_purity_score is None, "no se rellena con un 1.0 favorable"
    assert result.memory_purity_basis["status"] == PURITY_UNMEASURED
    assert result.memory_purity_basis["contamination_opportunity"] is True
    assert "memory_purity" in result.unmeasured_fields
    assert "memory_purity" not in result.not_applicable_fields


def test_the_three_states_are_mutually_exclusive():
    """Un eje no puede estar a la vez medido, ausente y sin sujeto."""
    for memory in ([], _hits(same=2, cross=1), _hits_without_metrics(2)):
        result = assess_transfer(episode_result=_episode(memory=memory))
        overlap = set(result.unmeasured_fields) & set(result.not_applicable_fields)
        assert not overlap, f"un eje en dos estados a la vez: {overlap}"
        assert result.memory_purity_basis["status"] in (
            PURITY_MEASURED,
            PURITY_NOT_APPLICABLE,
            PURITY_UNMEASURED,
        )


# ── EL PREDICADO QUE LEEN LAS COMPUERTAS ────────────────────────────────────────

def test_purity_not_applicable_reads_the_basis():
    assert purity_not_applicable({"status": PURITY_NOT_APPLICABLE}) is True
    assert purity_not_applicable({"status": PURITY_MEASURED}) is False
    assert purity_not_applicable({"status": PURITY_UNMEASURED}) is False
    assert purity_not_applicable({}) is False
    assert purity_not_applicable(None) is False


def test_purity_not_applicable_is_backward_compatible():
    """Certificados anteriores a B85 no traen `status`, pero sí la misma afirmación."""
    assert purity_not_applicable({"contamination_opportunity": False}) is True
    assert purity_not_applicable({"contamination_opportunity": True}) is False
