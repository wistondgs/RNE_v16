from runtime.control.msrc import ProbeResult, ScaleAction, ScaleCatalog, ScaleEstimate, ScaleTransitionManager


def _estimate():
    return ScaleEstimate(
        required_resolution_score=0.7,
        heterogeneity_score=0.5,
        epistemic_insufficiency_score=0.6,
        risk_score=0.5,
        operational_pressure_score=0.4,
        vram_headroom=0.4,
        vram_pressure=0.6,
        vram_fragmentation_risk=0.2,
        vram_opportunity_score=0.7,
        recommended_scale_candidates=["5x5"],
        signals={},
    )


def test_transition_manager_keep_scale_returns_same_target():
    manager = ScaleTransitionManager(catalog=ScaleCatalog.default())
    out = manager.execute_action(
        run_id="run-x",
        episode_id="ep-1",
        current_scale_id="1x1",
        action=ScaleAction(action_type="keep_scale", target_scale_id="1x1", reason="stable"),
        estimate=_estimate(),
    )
    assert out["selected_scale_id"] == "1x1"
    assert out["transition_record"].transition_aborted is False
    assert out["transition_record"].rollback_applied is False  # alias legacy


def test_transition_manager_upgrade_to_non_executable_uses_nearest_executable():
    manager = ScaleTransitionManager(catalog=ScaleCatalog.default())
    out = manager.execute_action(
        run_id="run-x",
        episode_id="ep-2",
        current_scale_id="1x1",
        action=ScaleAction(action_type="upgrade_scale", target_scale_id="10x10", reason="need detail"),
        estimate=_estimate(),
    )
    assert out["selected_scale_id"] == "5x5"


def test_transition_manager_fork_probe_uses_executor():
    manager = ScaleTransitionManager(catalog=ScaleCatalog.default())

    def _probe(target_scale_id: str) -> ProbeResult:
        return ProbeResult(
            target_scale_id=target_scale_id,
            cognitive_gain_delta=0.08,
            viability_preserved=True,
            evidence_score=0.75,
            outcome="positive",
        )

    out = manager.execute_action(
        run_id="run-x",
        episode_id="ep-3",
        current_scale_id="1x1",
        action=ScaleAction(action_type="fork_probe", target_scale_id="5x5", reason="probe"),
        estimate=_estimate(),
        probe_executor=_probe,
    )
    assert out["probe_result"] is not None
    assert out["probe_result"].target_scale_id == "5x5"


def test_transition_manager_aborts_when_probe_executor_missing():
    manager = ScaleTransitionManager(catalog=ScaleCatalog.default())
    out = manager.execute_action(
        run_id="run-x",
        episode_id="ep-4",
        current_scale_id="1x1",
        action=ScaleAction(action_type="fork_probe", target_scale_id="5x5", reason="probe"),
        estimate=_estimate(),
    )
    record = out["transition_record"]
    # Abort, no rollback: la escala nunca se aplico, asi que no hay nada que revertir.
    assert out["selected_scale_id"] == "1x1"
    assert record.transition_aborted is True
    assert record.rollback_applied is True  # alias legacy
    assert "probe_executor requerido" in record.abort_reason
    # Un abort no midio nada: no se inventan costes.
    assert record.real_time_cost is None
    assert record.real_artifact_cost is None
    assert set(record.unmeasured_costs) == {"real_time_cost", "real_artifact_cost"}
