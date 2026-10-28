"""B26.1 — cobertura de regímenes sobre el registry vivo de escenarios.

Criterio: canon/normative/SCENARIO_CONTRACTS_v1.md §6 (los 4 escenarios oficiales).
"""

from __future__ import annotations

import pytest

from runtime.organism.regime_model import (
    DEFERRED_LOAD_REGIME,
    GRID_THERMAL_REGIME,
    REGIME_REGISTRY,
    SCENARIO_TO_REGIME,
    compare_regimes,
    get_regime_for_scenario,
    is_scenario_mapped,
)
from runtime.world.registry import SCENARIO_REGISTRY


def test_todos_los_escenarios_del_registry_vivo_tienen_regimen():
    """CANARIO. Si alguien registra un escenario nuevo sin régimen, esto grita.

    No es una prohibición: un escenario sin régimen es legal (B26.2 lo maneja con
    abstención explícita). Es un recordatorio de que la omisión tiene que ser una
    DECISIÓN, no un olvido.
    """
    sin_regimen = [name for name in SCENARIO_REGISTRY if not is_scenario_mapped(name)]
    assert sin_regimen == [], (
        f"Escenarios del registry vivo sin régimen latente: {sin_regimen}. "
        "Asignales un régimen (canon SCENARIO_CONTRACTS_v1 §6) o declará "
        "explícitamente por qué no se puede."
    )


def test_los_cuatro_escenarios_canonicos_estan_mapeados():
    assert set(SCENARIO_TO_REGIME) == {
        "thermal_homeostasis",
        "resource_management",
        "grid_thermal_5x5",
        "deferred_load_trap",
    }
    for regime_id in SCENARIO_TO_REGIME.values():
        assert regime_id in REGIME_REGISTRY


def test_escenario_desconocido_sigue_devolviendo_none():
    """`None` = NO SÉ RENORMALIZAR. Sigue siendo posible, y debe seguir siéndolo."""
    assert get_regime_for_scenario("escenario_que_no_existe") is None
    assert is_scenario_mapped("escenario_que_no_existe") is False


# ── Los regímenes nuevos respetan el canon ───────────────────────────────────

def test_grid_thermal_respeta_canon_6_3():
    r = GRID_THERMAL_REGIME
    assert r.optimization_geometry == "minimize"        # canon §6.3
    assert r.causal_polarity == "lower_is_better"       # canon §6.3
    assert r.counterfactual_law == "perturbation"       # opposite_intervention
    assert "grid_thermal_5x5" in r.scenario_instances
    # la topología canónica exacta no se pierde aunque el enum no la represente
    assert r.metadata["canonical_control_topology"] == "threshold_single_loop_spatial"


def test_deferred_load_respeta_canon_6_4():
    r = DEFERRED_LOAD_REGIME
    assert r.control_topology == "single_loop"          # canon §6.4
    assert r.optimization_geometry == "minimize"        # canon §6.4
    assert r.causal_polarity == "lower_is_better"       # canon §6.4
    # LA estructura del escenario-trampa: la deuda rebota => no es estable.
    assert r.equilibrium_class == "metastable"
    assert r.recovery_profile == "slow"
    # el campo no determinado por el canon está DECLARADO como tal
    assert r.metadata["response_sensitivity_basis"] == "canon_undetermined_neutral_default"


def test_grid_thermal_es_compatible_con_thermal_no_identico():
    """El grid es la extensión espacial del thermal: compatible, no el mismo régimen."""
    comp = compare_regimes(
        get_regime_for_scenario("thermal_homeostasis"),
        get_regime_for_scenario("grid_thermal_5x5"),
    )
    assert comp.compatibility == "compatible_regime"
    assert comp.topology_match is False   # single_loop vs distributed
    assert comp.geometry_match is True
    assert comp.polarity_match is True


def test_cruce_thermal_resource_es_polaridad_invertida():
    """canon §7.5: minimize <-> maximize es el cruce peligroso (adversarial)."""
    comp = compare_regimes(
        get_regime_for_scenario("thermal_homeostasis"),
        get_regime_for_scenario("resource_management"),
    )
    assert comp.polarity_match is False
    assert comp.geometry_match is False


@pytest.mark.parametrize("source", sorted(SCENARIO_TO_REGIME))
@pytest.mark.parametrize("target", sorted(SCENARIO_TO_REGIME))
def test_ningun_cruce_mapeado_dispara_renorm_residual_spike(source, target):
    """LA TRAMPA (a): extender el mapeo NO puede desatar una tormenta de fallas críticas.

    Mide el residual REAL de cada cruce con el motor real. El umbral de
    `renorm_residual_spike` (failure_atlas.py) es > 0.55.
    """
    if source == target:
        pytest.skip("no es un cruce")

    from runtime.organism.regime_renormalization import RegimeRenormalizationEngine
    from runtime.organism.snapshot import OrganismSnapshot
    from runtime.organism.state import PolicyState

    engine = RegimeRenormalizationEngine()
    for sensitivity in (0.1, 0.3, 0.5, 0.7, 0.9):
        result = engine.renormalize(
            source_regime=get_regime_for_scenario(source),
            target_regime=get_regime_for_scenario(target),
            snapshot=OrganismSnapshot(policy=PolicyState(sensitivity=sensitivity)),
        )
        residual = result.regime_residual.residual_error
        assert 0.0 <= residual <= 1.0
        assert residual <= 0.55, (
            f"{source}->{target} @sensitivity={sensitivity} da residual={residual} "
            "=> dispararía renorm_residual_spike (severidad high/critical)."
        )


def test_los_cruces_mapeados_dan_residual_estrictamente_positivo():
    """Ningún cruce REAL es una renormalización perfecta. 0.0 sería la mentira vieja."""
    from runtime.organism.regime_renormalization import RegimeRenormalizationEngine
    from runtime.organism.snapshot import OrganismSnapshot

    engine = RegimeRenormalizationEngine()
    for source in SCENARIO_TO_REGIME:
        for target in SCENARIO_TO_REGIME:
            if source == target:
                continue
            result = engine.renormalize(
                source_regime=get_regime_for_scenario(source),
                target_regime=get_regime_for_scenario(target),
                snapshot=OrganismSnapshot(),
            )
            assert result.regime_residual.residual_error > 0.0, (
                f"{source}->{target} puntúa como renormalización PERFECTA (0.0)."
            )
