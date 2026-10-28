from runtime.control.msrc import ProbeResult, ScaleCatalog, ScaleEstimate, ScalePolicyEngine, ScalePolicyState


def _estimate(
    *,
    required: float,
    heterogeneity: float = 0.5,
    epistemic: float = 0.5,
    risk: float = 0.5,
    operational: float = 0.3,
    candidates=None,
    vram_pressure: float = 0.5,
    vram_opportunity: float = 0.7,
    signals=None,
):
    return ScaleEstimate(
        required_resolution_score=required,
        heterogeneity_score=heterogeneity,
        epistemic_insufficiency_score=epistemic,
        risk_score=risk,
        operational_pressure_score=operational,
        vram_headroom=max(0.0, 1.0 - vram_pressure),
        vram_pressure=vram_pressure,
        vram_fragmentation_risk=0.2,
        vram_opportunity_score=vram_opportunity,
        recommended_scale_candidates=candidates or ["5x5"],
        signals=signals or {},
    )


def test_policy_requires_accumulated_evidence_before_upgrade_probe():
    engine = ScalePolicyEngine()
    catalog = ScaleCatalog.default()
    state = ScalePolicyState(current_scale_id="1x1")

    action1 = engine.decide(catalog=catalog, state=state, estimate=_estimate(required=0.85, epistemic=0.8))
    action2 = engine.decide(catalog=catalog, state=state, estimate=_estimate(required=0.85, epistemic=0.8))
    action3 = engine.decide(catalog=catalog, state=state, estimate=_estimate(required=0.85, epistemic=0.8))

    assert action1.action_type == "keep_scale"
    assert action2.action_type == "keep_scale"
    assert action3.action_type == "fork_probe"
    assert action3.target_scale_id == "5x5"


def test_policy_commits_positive_probe():
    engine = ScalePolicyEngine()
    catalog = ScaleCatalog.default()
    state = ScalePolicyState(current_scale_id="1x1", probe_inflight_target="5x5")
    probe = ProbeResult(
        target_scale_id="5x5",
        cognitive_gain_delta=0.12,
        viability_preserved=True,
        evidence_score=0.8,
        outcome="positive",
    )

    action = engine.decide(catalog=catalog, state=state, estimate=_estimate(required=0.8), probe_result=probe)
    assert action.action_type == "commit_probe_result"
    # La escala destino viaja en la ACCION. El motor NO la aplica: el commit es del
    # controller y solo ocurre si la transicion no aborta (SSOT / CANON 3.1.6).
    assert action.target_scale_id == "5x5"
    assert state.current_scale_id == "1x1"


def test_policy_discards_negative_probe():
    engine = ScalePolicyEngine()
    catalog = ScaleCatalog.default()
    state = ScalePolicyState(current_scale_id="1x1", probe_inflight_target="5x5")
    probe = ProbeResult(
        target_scale_id="5x5",
        cognitive_gain_delta=-0.04,
        viability_preserved=False,
        evidence_score=0.2,
        outcome="negative",
    )

    action = engine.decide(catalog=catalog, state=state, estimate=_estimate(required=0.8), probe_result=probe)
    assert action.action_type == "discard_probe_result"
    assert state.current_scale_id == "1x1"


def test_policy_downgrade_requires_persistent_evidence():
    engine = ScalePolicyEngine()
    catalog = ScaleCatalog.default()
    state = ScalePolicyState(current_scale_id="5x5")
    actions = []
    for _ in range(5):
        actions.append(
            engine.decide(
                catalog=catalog,
                state=state,
                estimate=_estimate(required=0.15, candidates=["1x1"], operational=0.8, vram_pressure=0.9, vram_opportunity=0.1),
            )
        )

    assert actions[-1].action_type == "downgrade_scale"
    assert actions[-1].target_scale_id == "1x1"
    # El motor decide; no aplica. La escala del state sigue siendo la de origen
    # hasta que el controller commitee la transicion (SSOT / CANON 3.1.6).
    assert state.current_scale_id == "5x5"


def test_aggressive_policy_scales_before_baseline_under_warning_signal():
    baseline = ScalePolicyEngine.baseline()
    aggressive = ScalePolicyEngine.aggressive()
    catalog = ScaleCatalog.default()

    state_b = ScalePolicyState(current_scale_id="1x1")
    state_a = ScalePolicyState(current_scale_id="1x1")
    estimate = _estimate(required=0.33, heterogeneity=0.24, epistemic=0.18, risk=0.42, vram_opportunity=0.72)

    b1 = baseline.decide(catalog=catalog, state=state_b, estimate=estimate)
    b2 = baseline.decide(catalog=catalog, state=state_b, estimate=estimate)
    a1 = aggressive.decide(catalog=catalog, state=state_a, estimate=estimate)
    a2 = aggressive.decide(catalog=catalog, state=state_a, estimate=estimate)

    assert b1.action_type == "keep_scale"
    assert b2.action_type == "keep_scale"
    assert a1.action_type == "keep_scale"
    assert a2.action_type in {"upgrade_scale", "fork_probe"}


def test_aggressive_probe_commit_threshold_is_less_timid_than_baseline():
    baseline = ScalePolicyEngine.baseline()
    aggressive = ScalePolicyEngine.aggressive()
    catalog = ScaleCatalog.default()
    estimate = _estimate(required=0.7, heterogeneity=0.3, epistemic=0.3, risk=0.5, vram_opportunity=0.7)

    probe = ProbeResult(
        target_scale_id="5x5",
        cognitive_gain_delta=0.04,
        viability_preserved=True,
        evidence_score=0.51,
        outcome="positive",
    )
    state_b = ScalePolicyState(current_scale_id="1x1", probe_inflight_target="5x5")
    state_a = ScalePolicyState(current_scale_id="1x1", probe_inflight_target="5x5")

    action_b = baseline.decide(catalog=catalog, state=state_b, estimate=estimate, probe_result=probe)
    action_a = aggressive.decide(catalog=catalog, state=state_a, estimate=estimate, probe_result=probe)

    assert action_b.action_type == "discard_probe_result"
    assert action_a.action_type == "commit_probe_result"


def test_aggressive_policy_does_not_overscale_in_safe_homogeneous_case():
    aggressive = ScalePolicyEngine.aggressive()
    catalog = ScaleCatalog.default()
    state = ScalePolicyState(current_scale_id="1x1")
    estimate = _estimate(required=0.12, heterogeneity=0.05, epistemic=0.05, risk=0.10, vram_opportunity=0.92)

    actions = [
        aggressive.decide(catalog=catalog, state=state, estimate=estimate)
        for _ in range(3)
    ]
    assert all(action.action_type == "keep_scale" for action in actions)


def test_regime_v3_prefers_probe_or_upgrade_in_heterogeneous_regime():
    v3 = ScalePolicyEngine.regime_v3()
    aggressive = ScalePolicyEngine.aggressive()
    catalog = ScaleCatalog.default()
    state_v3 = ScalePolicyState(current_scale_id="1x1")
    state_aggr = ScalePolicyState(current_scale_id="1x1")
    estimate = _estimate(
        required=0.40,
        heterogeneity=0.34,
        epistemic=0.24,
        risk=0.28,
        vram_opportunity=0.76,
        signals={
            "risk_detail": {"low_margin": 0.20, "proximity_to_threshold": 0.28, "world_level": 0.79},
            "heterogeneity_detail": {"expected_spatial_complexity": 0.84, "scale_blindspot_bonus": 0.60},
        },
    )

    action_v3 = v3.decide(catalog=catalog, state=state_v3, estimate=estimate)
    action_aggr = aggressive.decide(catalog=catalog, state=state_aggr, estimate=estimate)

    assert action_aggr.action_type == "keep_scale"
    assert action_v3.action_type in {"fork_probe", "upgrade_scale"}


def test_regime_v3_avoids_overscaling_in_homogeneous_safe():
    v3 = ScalePolicyEngine.regime_v3()
    catalog = ScaleCatalog.default()
    state = ScalePolicyState(current_scale_id="1x1")
    estimate = _estimate(
        required=0.14,
        heterogeneity=0.04,
        epistemic=0.08,
        risk=0.14,
        vram_opportunity=0.85,
        signals={
            "risk_detail": {"low_margin": 0.05, "proximity_to_threshold": 0.10, "world_level": 0.62},
            "heterogeneity_detail": {"expected_spatial_complexity": 0.10, "scale_blindspot_bonus": 0.0},
        },
    )

    actions = [v3.decide(catalog=catalog, state=state, estimate=estimate) for _ in range(4)]
    assert all(action.action_type == "keep_scale" for action in actions)


def test_regime_v3_uses_vram_opportunity_at_viability_edge():
    v3 = ScalePolicyEngine.regime_v3()
    catalog = ScaleCatalog.default()
    state = ScalePolicyState(current_scale_id="1x1")
    estimate = _estimate(
        required=0.60,
        heterogeneity=0.18,
        epistemic=0.30,
        risk=0.72,
        vram_pressure=0.58,
        vram_opportunity=0.84,
        signals={
            "risk_detail": {"low_margin": 0.70, "proximity_to_threshold": 0.75, "world_level": 0.92},
            "heterogeneity_detail": {"expected_spatial_complexity": 0.42, "scale_blindspot_bonus": 0.20},
        },
    )

    first = v3.decide(catalog=catalog, state=state, estimate=estimate)
    second = v3.decide(catalog=catalog, state=state, estimate=estimate)
    assert first.action_type == "keep_scale"
    assert second.action_type in {"fork_probe", "upgrade_scale"}
