"""B32 — tests unitarios del controlador MSRC (antes: cero).

Cubre lo que exige CANON §3.1.6 para la transicion de escala —atomico, auditable
y probado— y la doctrina de medicion del repo: lo que no se midio NO se llama
`real_*` ni se rellena con la estimacion del catalogo.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from runtime.control.msrc import (
    MSRCController,
    ProbeResult,
    ScaleAction,
    ScaleCatalog,
    ScaleEstimate,
    ScalePolicyState,
)
from runtime.control.msrc.vram_sampler import NullVRAMSampler


class FakeStorage:
    """Storage minimo: solo captura los eventos emitidos."""

    def __init__(self) -> None:
        self.events: List[Dict[str, Any]] = []

    def append_event(self, **kwargs: Any) -> None:
        self.events.append(kwargs)


class StubPolicyEngine:
    """Motor de politica que devuelve una accion fija.

    Permite ejercitar cada `action_type` del controller sin depender de los
    umbrales/hysteresis del motor real (eso ya lo cubre test_scale_policy_engine).
    """

    def __init__(self, action: ScaleAction, *, mutate_scale_to: Optional[str] = None) -> None:
        self.action = action
        #: Simula un motor que ademas APLICA la escala (el bug historico). Sirve
        #: para probar que el controller no depende de eso.
        self.mutate_scale_to = mutate_scale_to
        self.seen_probe_result: Optional[ProbeResult] = None

    def decide(self, *, catalog, state, estimate, probe_result=None) -> ScaleAction:
        state.step_index += 1
        self.seen_probe_result = probe_result
        if self.mutate_scale_to is not None:
            state.current_scale_id = self.mutate_scale_to
        return self.action


class _CatalogDenyingTarget:
    """Delegador que finge que ninguna escala destino existe."""

    def __init__(self, inner: ScaleCatalog) -> None:
        self.inner = inner

    def has_scale(self, scale_id: str) -> bool:
        return False

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


def _estimate() -> ScaleEstimate:
    return ScaleEstimate(
        required_resolution_score=0.7,
        heterogeneity_score=0.5,
        epistemic_insufficiency_score=0.6,
        risk_score=0.4,
        operational_pressure_score=0.3,
        vram_headroom=0.5,
        vram_pressure=0.4,
        vram_fragmentation_risk=0.1,
        vram_opportunity_score=0.7,
        recommended_scale_candidates=["5x5"],
        signals={},
    )


def _controller(action: ScaleAction, **kwargs: Any) -> tuple[MSRCController, FakeStorage, StubPolicyEngine]:
    storage = FakeStorage()
    engine = StubPolicyEngine(action, **kwargs)
    controller = MSRCController(
        storage=storage,
        policy_engine=engine,
        vram_sampler=NullVRAMSampler(),
    )
    # El estimador real necesita una observacion; lo dejamos, pero el motor es stub.
    return controller, storage, engine


def _step(controller: MSRCController, state: ScalePolicyState, **kwargs: Any) -> Dict[str, Any]:
    return controller.step(
        run_id="run-1",
        episode_id="ep-1",
        state=state,
        observation={"cell_states": [{"temperature": t} for t in (0.1, 0.9, 0.3, 0.8)]},
        viability_margin=0.8,
        certification_verdict="pass",
        metrics={"cognitive_quality": 0.5, "risk_score": 0.4},
        **kwargs,
    )


def _probe(target: str = "5x5", **overrides: Any) -> ProbeResult:
    payload: Dict[str, Any] = dict(
        target_scale_id=target,
        cognitive_gain_delta=0.11,
        viability_preserved=True,
        evidence_score=0.9,
        outcome="positive",
    )
    payload.update(overrides)
    return ProbeResult(**payload)


# --------------------------------------------------------------------------
# Un test por action_type
# --------------------------------------------------------------------------


def test_keep_scale_does_not_move_the_organism():
    action = ScaleAction(action_type="keep_scale", target_scale_id="1x1", reason="estable")
    controller, _, _ = _controller(action)
    state = ScalePolicyState(current_scale_id="1x1")

    out = _step(controller, state)

    assert out["selected_scale_id"] == "1x1"
    assert state.current_scale_id == "1x1"
    assert out["transition_record"].transition_aborted is False


def test_trace_group_links_decision_transition_and_audit_events():
    action = ScaleAction(action_type="keep_scale", target_scale_id="1x1", reason="estable")
    controller, storage, _ = _controller(action)
    out = _step(
        controller,
        ScalePolicyState(current_scale_id="1x1"),
        trace_group_id="trace-msrc-neural-1",
    )

    assert out["trace_group_id"] == "trace-msrc-neural-1"
    assert out["decision_record"].metadata["trace_group_id"] == "trace-msrc-neural-1"
    assert out["transition_record"].metadata["trace_group_id"] == "trace-msrc-neural-1"
    linked = [event for event in storage.events if event["event_type"] in {"msrc.decision", "msrc.transition"}]
    assert len(linked) == 2
    assert all(event["payload"]["metadata"]["trace_group_id"] == "trace-msrc-neural-1" for event in linked)


def test_lock_scale_for_n_steps_does_not_move_the_organism():
    action = ScaleAction(action_type="lock_scale_for_n_steps", target_scale_id="1x1", reason="lock", lock_steps=3)
    controller, _, _ = _controller(action)
    state = ScalePolicyState(current_scale_id="1x1")

    out = _step(controller, state)

    assert out["selected_scale_id"] == "1x1"
    assert state.current_scale_id == "1x1"


def test_upgrade_scale_commits_the_new_scale():
    action = ScaleAction(action_type="upgrade_scale", target_scale_id="5x5", reason="mas detalle")
    controller, _, _ = _controller(action)
    state = ScalePolicyState(current_scale_id="1x1")

    out = _step(controller, state)

    assert out["selected_scale_id"] == "5x5"
    assert state.current_scale_id == "5x5"
    record = out["transition_record"]
    # El origen del registro es la escala REAL de origen, no el destino.
    assert record.source_scale_id == "1x1"
    assert record.target_scale_id == "5x5"


def test_downgrade_scale_commits_the_new_scale():
    action = ScaleAction(action_type="downgrade_scale", target_scale_id="1x1", reason="sobra resolucion")
    controller, _, _ = _controller(action)
    state = ScalePolicyState(current_scale_id="5x5")

    out = _step(controller, state)

    assert out["selected_scale_id"] == "1x1"
    assert state.current_scale_id == "1x1"
    assert out["transition_record"].source_scale_id == "5x5"


def test_fork_probe_runs_the_probe_without_moving_the_organism():
    action = ScaleAction(action_type="fork_probe", target_scale_id="5x5", reason="sondear")
    controller, _, _ = _controller(action)
    state = ScalePolicyState(current_scale_id="1x1")
    calls: List[str] = []

    def executor(target_scale_id: str) -> ProbeResult:
        calls.append(target_scale_id)
        return _probe(target_scale_id)

    out = _step(controller, state, probe_executor=executor)

    assert calls == ["5x5"]
    # El probe mide, pero NO mueve al organismo.
    assert out["selected_scale_id"] == "1x1"
    assert state.current_scale_id == "1x1"
    assert out["probe_result"] is not None


def test_discard_probe_result_keeps_the_current_scale():
    action = ScaleAction(action_type="discard_probe_result", target_scale_id="1x1", reason="probe flojo")
    controller, _, _ = _controller(action)
    state = ScalePolicyState(current_scale_id="1x1")

    out = _step(controller, state, probe_result=_probe(outcome="negative"))

    assert out["selected_scale_id"] == "1x1"
    assert state.current_scale_id == "1x1"


def test_commit_probe_result_commits_the_probed_scale():
    action = ScaleAction(action_type="commit_probe_result", target_scale_id="5x5", reason="probe ok")
    controller, _, _ = _controller(action)
    state = ScalePolicyState(current_scale_id="1x1")

    out = _step(controller, state, probe_result=_probe("5x5", measured_time_cost_ms=1234.5))

    assert out["selected_scale_id"] == "5x5"
    assert state.current_scale_id == "5x5"


# --------------------------------------------------------------------------
# CANON 3.1.6 — atomicidad: el abort NO deja la escala nueva aplicada
# --------------------------------------------------------------------------


def test_aborted_transition_leaves_the_scale_untouched():
    """El corazon de A3: si la transicion falla, la escala NO cambia."""
    action = ScaleAction(action_type="upgrade_scale", target_scale_id="5x5", reason="mas detalle")
    controller, _, _ = _controller(action)
    state = ScalePolicyState(current_scale_id="1x1")
    controller.transition_manager.catalog = _CatalogDenyingTarget(controller.catalog)

    out = _step(controller, state)

    record = out["transition_record"]
    assert record.transition_aborted is True
    assert record.abort_reason is not None
    # ATOMICIDAD: la escala quedo donde estaba.
    assert out["selected_scale_id"] == "1x1"
    assert state.current_scale_id == "1x1"
    assert record.source_scale_id == "1x1"


def test_abort_is_atomic_even_if_the_policy_engine_applied_the_scale_itself():
    """Regresion del bug real: el motor escribia state.current_scale_id al decidir.

    El controller pasaba ese state YA MUTADO al transition manager, asi que el
    abort devolvia "la escala actual"... que ya era la NUEVA. La transicion
    fallida quedaba aplicada igual. El controller ahora captura el origen ANTES
    de decidir, asi que ni un motor que aplique por su cuenta rompe la atomicidad.
    """
    action = ScaleAction(action_type="upgrade_scale", target_scale_id="5x5", reason="mas detalle")
    controller, _, _ = _controller(action, mutate_scale_to="5x5")
    state = ScalePolicyState(current_scale_id="1x1")
    controller.transition_manager.catalog = _CatalogDenyingTarget(controller.catalog)

    out = _step(controller, state)

    assert out["transition_record"].transition_aborted is True
    assert state.current_scale_id == "1x1", "un abort no puede dejar aplicada la escala nueva"
    assert out["transition_record"].source_scale_id == "1x1"


def test_abort_emits_the_legacy_rollback_event_for_existing_consumers():
    action = ScaleAction(action_type="upgrade_scale", target_scale_id="5x5", reason="mas detalle")
    controller, storage, _ = _controller(action)
    state = ScalePolicyState(current_scale_id="1x1")
    controller.transition_manager.catalog = _CatalogDenyingTarget(controller.catalog)

    _step(controller, state)

    event_types = [e["event_type"] for e in storage.events]
    assert "msrc.rollback" in event_types
    payload = next(e["payload"] for e in storage.events if e["event_type"] == "msrc.rollback")
    # Alias legacy: los consumidores vivos (benchmark) siguen leyendo esta clave.
    assert payload["rollback_applied"] is True
    assert payload["transition_aborted"] is True


# --------------------------------------------------------------------------
# Auditabilidad: real_* solo si se midio (el test que HOY fallaba)
# --------------------------------------------------------------------------


def test_commit_probe_result_commits_what_the_probe_measured():
    """El test que fallaba antes del fix.

    `commit_probe_result` escribia `target.expected_artifact_cost -
    source.expected_artifact_cost` en `real_artifact_cost`: la ESTIMACION del
    catalogo con el nombre `real_`. Tenia la medicion del probe y la tiraba justo
    al commitear.
    """
    action = ScaleAction(action_type="commit_probe_result", target_scale_id="5x5", reason="probe ok")
    controller, _, _ = _controller(action)
    state = ScalePolicyState(current_scale_id="1x1")
    probe = _probe("5x5", cognitive_gain_delta=0.42, measured_time_cost_ms=1234.5, measured_artifact_cost=7.0)

    out = _step(controller, state, probe_result=probe)

    record = out["transition_record"]
    assert record.real_time_cost == 1234.5
    assert record.real_artifact_cost == 7.0
    assert record.cost_measurement_source == "probe_execution"
    assert record.unmeasured_costs == []
    # El ioc_delta committeado es el que MIDIO el probe.
    assert record.ioc_delta == 0.42
    # Y no es una copia de la estimacion del catalogo.
    catalog = ScaleCatalog.default()
    assert record.real_time_cost != record.estimated_time_cost
    assert record.estimated_artifact_cost == catalog.get("5x5").expected_artifact_cost


def test_commit_probe_result_never_fills_real_cost_with_the_catalog_estimate():
    """Sin mediciones del probe, real_* queda NO MEDIDO. No se inventa."""
    action = ScaleAction(action_type="commit_probe_result", target_scale_id="5x5", reason="probe ok")
    controller, _, _ = _controller(action)
    state = ScalePolicyState(current_scale_id="1x1")
    # ProbeResult sin mediciones (measured_* = None), como los que producen hoy el
    # kernel y el benchmark.
    probe = _probe("5x5")

    out = _step(controller, state, probe_result=probe)

    record = out["transition_record"]
    assert record.real_time_cost is None
    assert record.real_artifact_cost is None
    assert set(record.unmeasured_costs) == {"real_time_cost", "real_artifact_cost"}
    assert record.cost_measurement_source == "none"
    # La estimacion del catalogo vive en estimated_*, y SOLO ahi.
    assert record.estimated_time_cost == ScaleCatalog.default().get("5x5").expected_time_cost


def test_upgrade_without_probe_declares_its_costs_unmeasured():
    """Un upgrade sin probe no midio el coste de correr en la escala nueva.

    Ese real_* es NO MEDIDO, no "igual al estimado".
    """
    action = ScaleAction(action_type="upgrade_scale", target_scale_id="5x5", reason="mas detalle")
    controller, _, _ = _controller(action)
    state = ScalePolicyState(current_scale_id="1x1")

    record = _step(controller, state)["transition_record"]

    assert record.real_time_cost is None
    assert record.real_artifact_cost is None
    assert set(record.unmeasured_costs) == {"real_time_cost", "real_artifact_cost"}
    assert record.cost_measurement_source == "none"
    # El delta de la estimacion NO se cuela como medicion.
    catalog = ScaleCatalog.default()
    estimate_delta = catalog.get("5x5").expected_artifact_cost - catalog.get("1x1").expected_artifact_cost
    assert record.real_artifact_cost != estimate_delta


@pytest.mark.parametrize("action_type", ["keep_scale", "lock_scale_for_n_steps", "discard_probe_result"])
def test_non_executing_actions_do_not_time_the_managers_own_dict_lookups(action_type):
    """El viejo real_time_cost cronometraba los lookups del manager (microsegundos).

    Eso no es el coste de la transicion: es una medicion del objeto equivocado
    haciendose pasar por la buena. Ahora se declara no medido.
    """
    action = ScaleAction(action_type=action_type, target_scale_id="1x1", reason="x")
    controller, _, _ = _controller(action)
    state = ScalePolicyState(current_scale_id="1x1")

    record = _step(controller, state)["transition_record"]

    assert record.real_time_cost is None
    assert record.real_artifact_cost is None
    assert set(record.unmeasured_costs) == {"real_time_cost", "real_artifact_cost"}


def test_fork_probe_measures_the_probe_wall_time_not_the_manager_overhead():
    action = ScaleAction(action_type="fork_probe", target_scale_id="5x5", reason="sondear")
    controller, _, _ = _controller(action)
    state = ScalePolicyState(current_scale_id="1x1")

    def slow_executor(target_scale_id: str) -> ProbeResult:
        # El probe real corre un episodio entero en la escala destino.
        import time

        time.sleep(0.02)
        return _probe(target_scale_id)

    out = _step(controller, state, probe_executor=slow_executor)
    record = out["transition_record"]

    # Se midio el probe (>=20ms), no los lookups de dict del manager (microsegundos).
    assert record.real_time_cost is not None
    assert record.real_time_cost >= 20.0
    assert record.cost_measurement_source == "probe_execution"
    assert "real_time_cost" not in record.unmeasured_costs
    # Artefactos: el productor no los instrumenta => NO MEDIDO, no 0.0.
    assert record.real_artifact_cost is None
    assert "real_artifact_cost" in record.unmeasured_costs
    # El registro habla de la escala PROBADA, para que estimated_* y real_* sean comparables.
    assert record.target_scale_id == "5x5"


def test_fork_probe_attaches_the_measurement_to_the_probe_result():
    """La medicion tiene que sobrevivir hasta el commit (que ocurre en otro step)."""
    action = ScaleAction(action_type="fork_probe", target_scale_id="5x5", reason="sondear")
    controller, _, _ = _controller(action)
    state = ScalePolicyState(current_scale_id="1x1")

    out = _step(controller, state, probe_executor=lambda target: _probe(target))
    measured = out["probe_result"]

    assert measured.measured_time_cost_ms is not None
    assert measured.measured_time_cost_ms > 0.0


def test_probe_measurement_survives_fork_then_commit_round_trip():
    """Cadena completa: fork_probe mide -> el llamador guarda -> commit commitea eso."""
    fork = ScaleAction(action_type="fork_probe", target_scale_id="5x5", reason="sondear")
    controller, _, _ = _controller(fork)
    state = ScalePolicyState(current_scale_id="1x1")

    forked = _step(controller, state, probe_executor=lambda target: _probe(target))
    pending = forked["probe_result"]
    assert state.current_scale_id == "1x1"  # el probe no movio nada

    # Step siguiente: el llamador devuelve el ProbeResult pendiente y la politica commitea.
    controller.policy_engine = StubPolicyEngine(
        ScaleAction(action_type="commit_probe_result", target_scale_id="5x5", reason="probe ok")
    )
    committed = _step(controller, state, probe_result=pending)["transition_record"]

    assert state.current_scale_id == "5x5"
    assert committed.real_time_cost == pending.measured_time_cost_ms
    assert committed.cost_measurement_source == "probe_execution"


def test_commit_ignores_a_probe_measured_on_a_different_scale():
    """Commitear la medicion de OTRA escala seria peor que no medir."""
    action = ScaleAction(action_type="commit_probe_result", target_scale_id="5x5", reason="probe ok")
    controller, _, _ = _controller(action)
    state = ScalePolicyState(current_scale_id="1x1")
    foreign = _probe("30x30", measured_time_cost_ms=999.0)

    record = _step(controller, state, probe_result=foreign)["transition_record"]

    assert record.real_time_cost is None
    assert record.cost_measurement_source == "none"
    assert "real_time_cost" in record.unmeasured_costs


def test_transition_record_declares_that_estimated_and_real_use_different_units():
    action = ScaleAction(action_type="upgrade_scale", target_scale_id="5x5", reason="mas detalle")
    controller, _, _ = _controller(action)
    state = ScalePolicyState(current_scale_id="1x1")

    record = _step(controller, state)["transition_record"]

    units = record.metadata["cost_units"]
    assert units["estimated_time_cost"] == "catalog_relative"
    assert units["real_time_cost"] == "milliseconds"


def test_the_pending_probe_result_reaches_the_policy_engine():
    """El controller le pasa el ProbeResult al motor para que pueda decidir el commit."""
    action = ScaleAction(action_type="discard_probe_result", target_scale_id="1x1", reason="x")
    controller, _, engine = _controller(action)
    state = ScalePolicyState(current_scale_id="1x1")
    probe = _probe("5x5")

    _step(controller, state, probe_result=probe)

    assert engine.seen_probe_result is probe
