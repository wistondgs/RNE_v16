"""P9.6 — el organismo mide sus evidencias en vez de fabricarlas.

Desarma la familia "ausencia de dato = evidencia favorable". Antes, `assess_transfer`
rellenaba toda evidencia ausente con su valor MÁS FAVORABLE (`purity=1.0`, `stability=1.0`,
`kl=0.0`, `policy=0.5`) y los detectores leían esos mismos números: la falta de datos se
convertía en prueba de salud. Y encima los detectores solo corrían `if is_cross:`, así que
en un episodio intra-escenario —donde el organismo VIVE— no se evaluaba ninguna patología.

Estos tests fijan las dos mitades:
  - AUSENCIA: un dato que no está se declara ausente y el detector se ABSTIENE (no dispara).
  - PRESENCIA: un dato que sí está se mide, y la patología se detecta AUNQUE SEA LOCAL.
"""

from runtime.certification.transfer_assessment import assess_transfer

_SEQUENCE = ["ABD", "ANA", "CAU", "CTF", "DED", "PROB"]


def _trace():
    return [
        {"family": f, "status": "ok", "detail": {}, "timestamp": 1000.0 + i}
        for i, f in enumerate(_SEQUENCE)
    ]


def _episode(*, memory=None, belief=None, relation_kind="support"):
    """Episodio INTRA-escenario (el caso donde el organismo vive: sin transferencia)."""
    result = {
        "episode": {
            "trace": _trace(),
            "episode_id": "ep-local",
            "scenario_metadata": {
                "scenario_name": "thermal_homeostasis",
                "main_variable": "temperature",
            },
            "closure_profile": "adaptive_min",
            "context": {
                "observation": {"temperature": 0.8, "alarm": True},
                "retrieved_memory": memory or [],
            },
            "result": {
                "updated_world": {"temperature": 0.78},
                "relation_kind": relation_kind,
                "reasoning_sequence": list(_SEQUENCE),
            },
        },
    }
    if belief is not None:
        result["belief_state"] = {"prior": None, "posterior": belief}
    return result


def _clean_memory(n: int):
    """Hits de memoria del MISMO escenario: hubo oportunidad de contaminarse y no pasó."""
    return [
        {
            "structure": {"relation_kind": "support"},
            "retrieval_metrics": {
                "retrieved_same_scenario_count": n,
                "retrieved_cross_scenario_count": 0,
            },
        }
        for _ in range(n)
    ]


def _contaminated_memory(*, same: int, cross: int):
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


# ── AUSENCIA: lo que no se midió se declara, y nadie lo lee como salud ───────────

def test_absent_evidence_is_declared_not_invented():
    """Sin prior ni transición: la ausencia se NOMBRA en vez de rellenarse con lo favorable."""
    result = assess_transfer(episode_result=_episode())

    assert result.transition_stability_score is None, "sin episodio previo NO hay estabilidad"
    assert "transition_stability" in result.unmeasured_fields
    assert "belief_shift_kl" in result.unmeasured_fields


def test_unmeasured_evidence_makes_the_detector_abstain_not_fire():
    """La abstención es simétrica: la ausencia tampoco es evidencia de ENFERMEDAD.

    `belief_collapse` no puede correr sin belief shift ⇒ no corre, y NO dispara. Antes leía
    el `kl = 0.0` fabricado, que además era el valor más favorable posible.
    """
    result = assess_transfer(episode_result=_episode())

    assert "belief_collapse" not in result.detector_checks_applied
    assert "belief_collapse" not in [m.mode for m in result.failure_modes]


# ── PRESENCIA: se mide, y la patología LOCAL se detecta ──────────────────────────

def _contradicting_memory(n: int):
    """Memoria del MISMO escenario que CONTRADICE la política.

    Ojo: memoria contaminada (cross-scenario) NO sirve para probar la rama local, porque un
    hit cross activa `cross_evidence` y el episodio pasa a ser `is_cross`. La patología
    genuinamente local es esta: memorias del propio escenario diciendo que la intervención
    NO produce el efecto esperado. Eso es deriva de política, y ocurre en casa.
    """
    return [
        {
            "structure": {"relation_kind": "contradiction"},
            "retrieval_metrics": {
                "retrieved_same_scenario_count": n,
                "retrieved_cross_scenario_count": 0,
            },
        }
        for _ in range(n)
    ]


def _local_episode_with_drift():
    """Episodio intra-escenario, memoria LIMPIA (0 cross) y política a la deriva.

    Cadena REAL productor→detector: `build_belief_state` mide la confianza en la política a
    partir de la memoria, y `assess_transfer` la lee del belief_state del episodio.
    """
    from runtime.reality.belief_state import build_belief_state
    from dataclasses import asdict

    episode = _episode(memory=_contradicting_memory(2), relation_kind="contradiction")
    belief = build_belief_state(episode_result=episode)
    episode["belief_state"] = {"prior": None, "posterior": asdict(belief)}
    return episode, belief


def test_local_pathology_is_detected_in_an_intra_scenario_episode():
    """LA CABECERA DE P9.6: patología detectada SIN transferencia, con memoria LIMPIA.

    Antes esto era imposible: `detect_failure_modes` solo se alcanzaba dentro de
    `if is_cross:`, y un episodio intra-escenario con memoria limpia —donde el organismo
    VIVE— se salteaba la rama entera. La política podía estar a la deriva y el certificado
    salía impecable.
    """
    episode, belief = _local_episode_with_drift()
    result = assess_transfer(episode_result=episode)

    # Es LOCAL de verdad: sin transferencia, sin contaminación cruzada.
    assert result.cross_scenario_evidence_used is False
    assert result.failure_mode_scope == "local"
    assert result.memory_purity_score == 1.0, "la memoria está limpia: la pureza es real"

    # Y aun así el organismo se ve la patología.
    assert belief.policy_confidence < 0.50, "el productor puede bajar del umbral (paso 3)"
    detected = {m.mode for m in result.failure_modes}
    assert "policy_drift" in detected

    # NO se inventan patologías de transferencia donde no hay transferencia.
    assert "morphism_failure" not in detected
    assert "causal_inversion" not in detected
    assert "morphism_failure" not in result.detector_checks_applied


def test_failure_modes_do_not_gate_the_local_verdict():
    """Decisión conservadora explícita: revivirlos NO los convierte en compuerta.

    Las patologías entran al certificado como METADATA. Que sean alcanzables no debe frenar
    la promoción — eso es otra decisión, y no es esta.
    """
    episode, _ = _local_episode_with_drift()
    result = assess_transfer(episode_result=episode)

    assert result.failure_modes, "hay patología detectada"
    assert result.transfer_verdict == "certified_local", "y aun así el veredicto local no cambia"


def test_contaminated_memory_is_measured_and_flagged():
    """Memoria contaminada: la pureza se MIDE (no se fabrica en 1.0) y la patología aparece.

    Este episodio NO es local: un hit cross-scenario activa `cross_evidence` — que es
    justamente lo correcto, la contaminación ES evidencia de cruce.
    """
    episode = _episode(memory=_contaminated_memory(same=1, cross=2))
    result = assess_transfer(episode_result=episode)

    assert result.cross_scenario_evidence_used is True
    assert result.memory_purity_score is not None
    assert result.memory_purity_score < 0.70, "1 - 2/3 = 0.33: memoria contaminada"
    assert "memory_contamination" in {m.mode for m in result.failure_modes}


# ── PROCEDENCIA: un 1.0 no es un 1.0 ────────────────────────────────────────────

def test_vacuous_purity_declares_that_nothing_could_contaminate_it():
    """Pureza 1.0 sobre CERO hits: el número no cambia, pero deja de mentir sobre su sustento.

    Es *ausencia de oportunidad de contaminarse*, no pureza verificada. Sin la base, un 1.0
    vacuo se lee igual que uno ganado sobre 50 hits limpios.
    """
    result = assess_transfer(episode_result=_episode(memory=[]))

    assert result.memory_purity_score == 1.0  # el número NO se toca
    basis = result.memory_purity_basis
    assert basis["hits"] == 0
    assert basis["contamination_opportunity"] is False


def test_earned_purity_is_distinguishable_from_vacuous_purity():
    """El mismo 1.0, pero GANADO: hubo memoria que pudo contaminar y no contaminó."""
    result = assess_transfer(episode_result=_episode(memory=_clean_memory(3)))

    assert result.memory_purity_score == 1.0
    basis = result.memory_purity_basis
    assert basis["hits"] == 3
    assert basis["cross_scenario_hits"] == 0
    assert basis["contamination_opportunity"] is True, "hubo oportunidad y se verificó"


# ─────────────────────────────────────────────────────────────────────────────
# TRIPWIRE: el certificado no puede declarar que chequeó lo que confiesa no medir.
# ─────────────────────────────────────────────────────────────────────────────

# Qué evidencia necesita cada detector para poder correr.
_MODE_EVIDENCE = {
    "memory_contamination": "memory_purity",
    "policy_drift": "policy_confidence",
    "belief_collapse": "belief_shift_kl",
    "causal_inversion": "causal_support",
    "morphism_failure": "morphism_score",
    "trace_discontinuity": "trace_integrity",
}


def _assert_certificate_does_not_contradict_itself(result) -> None:
    """La invariante central del vocabulario de honestidad de P9/P9.6.

    `detector_checks_applied` (qué se verificó) y `unmeasured_fields` (qué no se midió) son
    dos campos del MISMO certificado. Si un detector aparece en el primero mientras su
    evidencia aparece en el segundo, el certificado se autocontradice: afirma haber
    chequeado algo que confiesa no haber medido.

    Ese era el bug: en la rama cross, los detectores corrían sobre los PRIORES NEUTROS (que
    el posterior necesita para su aritmética) y después el certificado declaraba esos
    chequeos como si se hubieran hecho sobre evidencia. Es exactamente la mentira que el
    paquete vino a matar, reintroducida en el vocabulario inventado para matarla.
    """
    unmeasured = set(result.unmeasured_fields)
    for mode in result.detector_checks_applied:
        evidence = _MODE_EVIDENCE[mode]
        assert evidence not in unmeasured, (
            f"El certificado dice haber chequeado '{mode}' pero declara que su evidencia "
            f"('{evidence}') NO se midió. checks_applied={result.detector_checks_applied} "
            f"unmeasured_fields={result.unmeasured_fields}"
        )


def test_certificate_never_claims_to_have_checked_what_it_did_not_measure():
    """Sobre el episodio local (sin memoria: varias evidencias ausentes)."""
    _assert_certificate_does_not_contradict_itself(
        assess_transfer(episode_result=_episode())
    )


def test_cross_branch_certificate_does_not_contradict_itself_either():
    """LA RAMA DEL BUG: cross, donde el posterior corre sobre priores neutros.

    Un episodio con evidencia cross (memoria contaminada) abre `is_cross`, y ahí el
    posterior rellena las evidencias ausentes con neutros para poder hacer su aritmética.
    Los DETECTORES no deben heredar esos rellenos, y el certificado no debe declararlos
    como chequeos hechos.
    """
    result = assess_transfer(
        episode_result=_episode(memory=_contaminated_memory(same=3, cross=2))
    )
    _assert_certificate_does_not_contradict_itself(result)
    # Y sin morfismo, los modos de TRANSFERENCIA no pueden darse por chequeados.
    if result.morphism_score is None:
        assert "morphism_failure" not in result.detector_checks_applied
        assert "causal_inversion" not in result.detector_checks_applied
