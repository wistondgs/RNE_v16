"""B26.2 — un cruce no renormalizable NO puede puntuar como renormalización perfecta.

EL BUG (main): si alguno de los dos escenarios de un cruce no tenía régimen latente,
court_runtime salteaba el bloque de renormalización en silencio y `renorm_residual`
se quedaba en 0.0. Y 0.0 es el valor MÁS FAVORABLE:
  - risk_process: `+ 0.12 * max(0.0, renorm_residual)` -> cero aporte al riesgo.
  - failure_atlas: `if renorm_residual > 0.55` -> `renorm_residual_spike` inalcanzable.

Doctrina aplicada (ya vigente en el repo): NO MEDIDO != bueno. Abstenerse, declararlo,
y que ningún consumidor lo lea como salud.
"""

from __future__ import annotations

import pytest

from runtime.organism.failure_atlas import detect_failure_atlas
from runtime.organism.risk_process import ConstitutionalRiskProcess


# ── failure_atlas: el detector se ABSTIENE, no dispara falsa alarma ──────────

def _atlas(renorm_residual):
    return detect_failure_atlas(
        drift_identity=0.0,
        drift_policy=0.0,
        delta_viability=0.0,
        memory_purity=1.0,
        modification_impact=0.0,
        erosion=0.0,
        renorm_residual=renorm_residual,
    )


def test_residual_no_medido_no_dispara_renorm_residual_spike():
    """FALSO PÁNICO NO. `None` no es "la renormalización falló catastróficamente"."""
    atlas = _atlas(None)
    triggers = [e.signature.trigger for e in atlas.events]
    assert "renorm_residual_spike" not in triggers
    assert atlas.critical_count == 0


def test_residual_no_medido_queda_declarado_como_agujero():
    """FALSA SALUD NO. El atlas sin eventos pero con agujero NO es salud."""
    atlas = _atlas(None)
    assert atlas.unmeasured_axes == ("renorm_residual",)
    assert atlas.is_complete is False


def test_residual_medido_y_alto_sigue_disparando_la_falla():
    """La abstención no desarma el detector cuando SÍ hay evidencia."""
    atlas = _atlas(0.90)
    triggers = [e.signature.trigger for e in atlas.events]
    assert "renorm_residual_spike" in triggers
    assert atlas.critical_count == 1
    assert atlas.is_complete is True


def test_residual_medido_y_bajo_no_dispara_y_no_tiene_agujeros():
    atlas = _atlas(0.10)
    assert atlas.events == ()
    assert atlas.unmeasured_axes == ()
    assert atlas.is_complete is True


# ── risk_process: `None` no se suma como 0.0 disfrazado de medición ─────────

def _update(risk: ConstitutionalRiskProcess, renorm_residual):
    return risk.update(
        scope_type="edge",
        scope_key="a->b",
        drift_identity=0.0,
        drift_policy=0.0,
        delta_viability=0.0,
        delta_purity=0.0,
        delta_modification=0.0,
        erosion=0.0,
        renorm_residual=renorm_residual,
    )


def test_riesgo_con_residual_no_medido_declara_el_agujero():
    update = _update(ConstitutionalRiskProcess(), None)
    assert update.failure_atlas.unmeasured_axes == ("renorm_residual",)
    assert update.failure_atlas.is_complete is False


def test_un_residual_real_pesa_mas_que_uno_no_medido():
    """El cruce medido y malo DEBE puntuar peor que el no medido.

    (El no medido no se castiga numéricamente — se abstiene — pero el veredicto
    T5 lo manda a cuarentena igual: ver los tests de scope más abajo.)
    """
    sin_medir = _update(ConstitutionalRiskProcess(), None).updated_risk
    medido_malo = _update(ConstitutionalRiskProcess(), 0.90).updated_risk
    assert medido_malo > sin_medir


# ── court: el veredicto NO puede certificar transferencia sin evidencia ─────

@pytest.fixture()
def court():
    from runtime.organism.court_runtime import ConstitutionalCourtRuntime

    return ConstitutionalCourtRuntime(storage=None)  # _scope_from_risk no toca storage


SANO = dict(
    modification_pending=False,
    flow_valid=True,
    rollback=False,
    viability_score=0.95,
    organism_risk=0.10,
    edge_risk=0.10,
    modification_risk=0.10,
    inheritance_risk=0.10,
)


def test_cruce_no_renormalizable_no_certifica_transferencia(court):
    """EL NÚCLEO DE B26.2.

    Organismo perfectamente sano en todos los ejes medidos + un cruce que NO sabe
    renormalizar => la corte se ABSTIENE de certificar. No certifica transfer_safe
    ni inheritance_safe: certificar exige evidencia, y de ese cruce no hay ninguna.
    """
    scope, advice = court._scope_from_risk(
        cross_regime=True, renorm_unmeasured=True, **SANO
    )
    assert scope == "quarantine_only"
    assert advice == "analogical_hint"


def test_cruce_no_renormalizable_no_es_blocked(court):
    """LA TRAMPA (b): abstenerse NO es entrar en pánico.

    "No sé renormalizar esto" no es "la renormalización falló catastróficamente".
    """
    scope, _ = court._scope_from_risk(cross_regime=True, renorm_unmeasured=True, **SANO)
    assert scope != "blocked"


def test_cruce_no_renormalizable_no_puede_cobrar_local_safe(court):
    """La regresión exacta de main.

    Antes `cross_regime` era `renorm_result is not None`, así que un cruce no mapeado
    se le presentaba a la corte como "no hubo cruce" y caía en la rama final:
    `if organism_risk < 0.55: return "local_safe"`. El cruce MÁS incierto que existe
    cobraba el scope MÁS favorable.
    """
    scope, _ = court._scope_from_risk(
        cross_regime=True, renorm_unmeasured=True, **SANO
    )
    assert scope != "local_safe"

    # Y el bug tal cual era: si el cruce se reporta como "no hubo cruce", da local_safe.
    scope_bug, _ = court._scope_from_risk(
        cross_regime=False, renorm_unmeasured=False, **SANO
    )
    assert scope_bug == "local_safe"


def test_cruce_renormalizado_y_sano_si_certifica(court):
    """La abstención no rompe el camino feliz: con evidencia, la corte certifica."""
    scope, _ = court._scope_from_risk(
        cross_regime=True, renorm_unmeasured=False, **SANO
    )
    assert scope in {"inheritance_safe", "transfer_safe"}


def test_sin_cruce_sigue_siendo_local_safe(court):
    """Episodio intra-escenario: no hay renormalización que medir. Eje sin sujeto."""
    scope, _ = court._scope_from_risk(
        cross_regime=False, renorm_unmeasured=False, **SANO
    )
    assert scope == "local_safe"


# ── END-TO-END: la corte real, ingiriendo episodios reales ──────────────────

def _episode(episode_id: str, scenario_name: str) -> dict:
    return {
        "episode": {
            "episode_id": episode_id,
            "scenario_metadata": {"scenario_name": scenario_name},
            "timestamp": "2026-07-11T00:00:00Z",
        }
    }


@pytest.fixture()
def real_court(tmp_path, monkeypatch):
    from runtime.organism.court_runtime import ConstitutionalCourtRuntime
    from runtime.storage import get_storage

    monkeypatch.setenv("RNFE_T5_MODE", "on")
    monkeypatch.setenv("RNFE_STORAGE_MODE", "sqlite")
    monkeypatch.setenv("AEON_EVENT_DB", str(tmp_path / "t5.db"))
    monkeypatch.setenv("RNFE_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    storage = get_storage(refresh=True)
    yield ConstitutionalCourtRuntime(storage=storage)
    storage.close()
    get_storage(refresh=True).close()  # no dejar el singleton apuntando al tmp_path


def test_e2e_cruce_hacia_escenario_sin_regimen_queda_no_medido(real_court):
    """EL BUG, end-to-end. Un cruce hacia un régimen que el organismo NO CONOCE.

    En main esto devolvía renormalization_residual == 0.0 (renormalización PERFECTA).
    """
    run_id = "run-b26-e2e"
    real_court.ingest_episode(
        run_id=run_id, episode_result=_episode("ep-1", "thermal_homeostasis")
    )
    result = real_court.ingest_episode(
        run_id=run_id,
        episode_result=_episode("ep-2", "escenario_del_futuro_sin_regimen"),
    )

    assert result is not None
    # LO CENTRAL: ya no puntúa 0.0.
    assert result.renormalization_residual is None
    assert result.renormalization_residual != 0.0
    assert result.renormalization_status == "unmeasured"

    # La omisión está DECLARADA POR NOMBRE, no callada.
    assert result.unrenormalizable_edge == (
        "thermal_homeostasis",
        "escenario_del_futuro_sin_regimen",
    )
    assert "renorm_residual" in result.unmeasured_axes

    # El veredicto NO lo cuenta como riesgo cero: no certifica transferencia.
    assert result.canonical_scope == "quarantine_only"
    assert result.canonical_scope not in {"local_safe", "transfer_safe", "inheritance_safe"}

    # Y NO entra en pánico: no hay falla crítica fabricada.
    assert result.canonical_scope != "blocked"


def test_e2e_cruce_entre_los_4_escenarios_si_se_mide(real_court):
    """B26.1: los cruces del registry vivo AHORA renormalizan de verdad.

    grid_thermal_5x5 no tenía régimen en main: este cruce se salteaba en silencio.
    """
    run_id = "run-b26-e2e-mapeado"
    real_court.ingest_episode(
        run_id=run_id, episode_result=_episode("ep-1", "thermal_homeostasis")
    )
    result = real_court.ingest_episode(
        run_id=run_id, episode_result=_episode("ep-2", "grid_thermal_5x5")
    )

    assert result is not None
    assert result.renormalization_status == "measured"
    assert result.renormalization_residual is not None
    assert result.renormalization_residual > 0.0   # ningún cruce real es perfecto
    assert result.unmeasured_axes == ()
    assert result.unrenormalizable_edge == ()
    # LA TRAMPA (a): medir de verdad no desató una falla crítica.
    assert result.renormalization_residual <= 0.55


def test_e2e_episodio_intra_escenario_es_not_applicable(real_court):
    """Sin cruce no hay renormalización que medir: eje SIN SUJETO (no un agujero)."""
    run_id = "run-b26-e2e-mismo"
    real_court.ingest_episode(
        run_id=run_id, episode_result=_episode("ep-1", "thermal_homeostasis")
    )
    result = real_court.ingest_episode(
        run_id=run_id, episode_result=_episode("ep-2", "thermal_homeostasis")
    )

    assert result is not None
    assert result.renormalization_status == "not_applicable"
    assert result.renormalization_residual is None
    assert result.unrenormalizable_edge == ()
    # B85 — Y ESTO ES LO QUE FALTABA: un eje SIN SUJETO no es un agujero.
    #
    # Sin la distinción, el episodio intra-escenario (el 99% de todos) marcaba el atlas
    # como INCOMPLETO para siempre — y entonces "atlas incompleto" dejaba de significar
    # nada, porque era la norma permanente. Peor: un agujero REAL (un cruce que no se pudo
    # renormalizar) quedaba indistinguible del caso trivial donde no había NADA que
    # renormalizar.
    #
    # "No medí" y "no había nada que medir" son cosas distintas. Confundirlas destruye
    # exactamente la señal que este paquete vino a crear.
    assert result.unmeasured_axes == ()
