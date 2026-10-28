"""Tests del lazo de autoevolución ρₜ (R2): trigger → sandbox → aplicar → monitor → rollback."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from runtime.organism.autoevolution import AutoEvolutionController
from runtime.organism.lineage import LineageState
from runtime.organism.state import (
    OrganismBeliefState,
    OrganismState,
    PolicyState,
    ViabilityState,
)
from runtime.storage import StorageConfig, StorageFactory


def _storage(tmp_path: Path):
    config = StorageConfig(
        mode="sqlite",
        sqlite_db_path=str(tmp_path / "evo.db"),
        postgres_dsn=None,
        artifact_root=tmp_path / "artifacts",
        prefer_postgres_reads=True,
        strict_dual_write=False,
    )
    return StorageFactory.create_facade(config)


def _state(*, margin: float = 1.0, drift: float = 0.0, episode: int = 1) -> OrganismState:
    # Creencias realistas post-episodio (como las produce el runner real);
    # con las default el invariante hard triadic_closure no se satisface.
    return OrganismState(
        state_id=f"state-{episode}",
        timestamp="2026-06-10T00:00:00Z",
        episode_count=episode,
        belief=OrganismBeliefState(
            intervention_efficacy=0.9,
            causal_support_confidence=0.9,
            memory_purity_estimate=0.95,
            trace_integrity_confidence=0.8,
        ),
        policy=PolicyState(accumulated_drift=drift),
        viability=ViabilityState(viability_margin=margin),
    )


def _with_evidence(ctrl: AutoEvolutionController, n: int = 20, ok: int = 19):
    """Pre-siembra evidencia histórica (episodios certificados) del run."""
    ctrl._evidence = {"n": n, "ok": ok}
    return ctrl


def _episode_result(
    *,
    margin: float = 1.0,
    rollback_required: bool = False,
    verdict: str = "valid",
    retrieved: int = 0,
) -> dict:
    return {
        "episode": {"context": {"retrieved_memory": [{"m": i} for i in range(retrieved)]}},
        "viability_assessment": {
            "is_viable": True,
            "viability_margin": margin,
            "distance_to_edge": margin,
            "rollback_required": rollback_required,
        },
        "constitutional_validation": {"verdict": verdict, "hard_violation_count": 0},
    }


class _Knobs:
    def __init__(self, limit=3, mode="cross_scenario_analogical"):
        self.values = {"memory_retrieval_limit": limit, "memory_filter_mode": mode}

    def read(self):
        return dict(self.values)

    def write(self, changes, context=None):  # el contexto lo pone el lazo (§XLII)
        self.values.update(changes)


def _controller(knobs: _Knobs, *, storage=None, **kw) -> AutoEvolutionController:
    defaults = dict(patience=2, post_window=2, cooldown=2, enabled=True)
    defaults.update(kw)
    return AutoEvolutionController(
        run_id="run-evo",
        storage=storage,
        knob_reader=knobs.read,
        knob_writer=knobs.write,
        **defaults,
    )


class TestTriggerAndApply:
    def test_healthy_episodes_do_nothing(self):
        knobs = _Knobs()
        ctrl = _controller(knobs)
        for i in range(5):
            out = ctrl.observe_episode(
                organism_state=_state(margin=0.9, episode=i),
                episode_result=_episode_result(margin=0.9),
                certificate_metadata={},
            )
        assert out["action"] == "none"
        assert knobs.values["memory_retrieval_limit"] == 3
        assert ctrl.lineage.generation == 0

    def test_sustained_degradation_applies_modification(self):
        knobs = _Knobs(limit=3)
        ctrl = _with_evidence(_controller(knobs))
        # 2 episodios degradados con presión de memoria alta (3 hits / 5).
        for i in range(2):
            out = ctrl.observe_episode(
                organism_state=_state(margin=0.30, episode=i),
                episode_result=_episode_result(margin=0.30, retrieved=3),
                certificate_metadata={"risk_plus": {"hard_violation_count": 0}},
            )
        assert out["action"] == "applied"
        assert out["target"] == "memory_scoring_secondary_weights"
        assert knobs.values["memory_retrieval_limit"] == 2
        assert ctrl.lineage.generation == 1
        json.dumps(out)

    def test_filter_mode_candidate_when_no_memory_pressure(self):
        knobs = _Knobs(limit=3, mode="cross_scenario_analogical")
        ctrl = _with_evidence(_controller(knobs))
        for i in range(2):
            out = ctrl.observe_episode(
                organism_state=_state(margin=0.30, episode=i),
                episode_result=_episode_result(margin=0.30, retrieved=0),
                certificate_metadata={},
            )
        assert out["action"] == "applied"
        assert out["target"] == "selection_policy"
        assert knobs.values["memory_filter_mode"] == "strict_same_scenario"

    def test_patience_required_before_applying(self):
        knobs = _Knobs()
        ctrl = _controller(knobs, patience=3)
        out = ctrl.observe_episode(
            organism_state=_state(margin=0.30),
            episode_result=_episode_result(margin=0.30, retrieved=3),
            certificate_metadata={},
        )
        assert out["action"] == "none"
        assert knobs.values["memory_retrieval_limit"] == 3

    def test_sie_safety_gate_blocks_modification(self):
        knobs = _Knobs()
        ctrl = _controller(knobs)
        for i in range(2):
            out = ctrl.observe_episode(
                organism_state=_state(margin=0.30, episode=i),
                episode_result=_episode_result(margin=0.30, retrieved=3),
                certificate_metadata={"risk_plus": {"hard_violation_count": 1}},
            )
        assert out["action"] == "blocked"
        assert knobs.values["memory_retrieval_limit"] == 3
        assert ctrl.lineage.generation == 0

    def test_no_candidate_when_knobs_exhausted(self):
        knobs = _Knobs(limit=1, mode="strict_same_scenario")
        ctrl = _controller(knobs)
        for i in range(2):
            out = ctrl.observe_episode(
                organism_state=_state(margin=0.30, episode=i),
                episode_result=_episode_result(margin=0.30, retrieved=0),
                certificate_metadata={},
            )
        assert out["action"] == "no_candidate"

    def test_disabled_controller_is_inert(self):
        knobs = _Knobs()
        ctrl = _controller(knobs, enabled=False)
        out = ctrl.observe_episode(
            organism_state=_state(margin=0.1),
            episode_result=_episode_result(margin=0.1, rollback_required=True),
            certificate_metadata={},
        )
        assert out["action"] == "disabled"


class TestR1RiskEnforcement:
    """R1 — freno de riesgo de cola S-I-E: de sombra a enforcement (gate falsable).

    Bloquea lo inseguro (CVaR>τ con evidencia) SIN falsos positivos (no bloquea por
    historial insuficiente). Default OFF ⇒ conducta byte-idéntica (solo sombra).
    """

    def _drive_to_gate(self, ctrl, risk_plus):
        out = None
        for i in range(2):  # patience=2 ⇒ el 2º episodio degradado llega al gate S-I-E
            out = ctrl.observe_episode(
                organism_state=_state(margin=0.30, episode=i),
                episode_result=_episode_result(margin=0.30, retrieved=3),
                certificate_metadata={"risk_plus": risk_plus},
            )
        return out

    def test_tail_risk_buffer_does_not_block_in_shadow(self, monkeypatch):
        monkeypatch.delenv("RNFE_RISK_ENFORCEMENT", raising=False)  # default OFF
        knobs = _Knobs()
        ctrl = _with_evidence(_controller(knobs))
        out = self._drive_to_gate(
            ctrl,
            {"sie_verdict": "BUFFER", "cvar_neg_delta_ioc": 0.5,
             "sie_reason": "CVaR=0.5 > 0.1", "hard_violation_count": 0},
        )
        assert out["action"] == "applied"  # sombra: el freno de cola NO muerde

    def test_tail_risk_buffer_blocks_under_enforcement(self, monkeypatch):
        monkeypatch.setenv("RNFE_RISK_ENFORCEMENT", "1")
        knobs = _Knobs()
        ctrl = _with_evidence(_controller(knobs))
        out = self._drive_to_gate(
            ctrl,
            {"sie_verdict": "BUFFER", "cvar_neg_delta_ioc": 0.5,
             "sie_reason": "CVaR=0.5 > 0.1", "hard_violation_count": 0},
        )
        assert out["action"] == "blocked"
        assert out["risk_enforced"] is True
        assert knobs.values["memory_retrieval_limit"] == 3  # no se mutó
        assert ctrl.lineage.generation == 0

    def test_insufficient_history_buffer_is_not_false_positive(self, monkeypatch):
        # BUFFER por historial insuficiente (cvar None) NO debe bloquear (falso positivo).
        monkeypatch.setenv("RNFE_RISK_ENFORCEMENT", "1")
        knobs = _Knobs()
        ctrl = _with_evidence(_controller(knobs))
        out = self._drive_to_gate(
            ctrl,
            {"sie_verdict": "BUFFER", "cvar_neg_delta_ioc": None,
             "sie_reason": "historial insuficiente (2 < 4)", "hard_violation_count": 0},
        )
        assert out["action"] == "applied"

    def test_accept_verdict_never_blocks(self, monkeypatch):
        monkeypatch.setenv("RNFE_RISK_ENFORCEMENT", "1")
        knobs = _Knobs()
        ctrl = _with_evidence(_controller(knobs))
        out = self._drive_to_gate(
            ctrl,
            {"sie_verdict": "ACEPTAR", "cvar_neg_delta_ioc": 0.05, "hard_violation_count": 0},
        )
        assert out["action"] == "applied"

    def test_hard_violation_blocks_regardless_of_flag(self, monkeypatch):
        monkeypatch.delenv("RNFE_RISK_ENFORCEMENT", raising=False)
        knobs = _Knobs()
        ctrl = _controller(knobs)
        out = self._drive_to_gate(ctrl, {"hard_violation_count": 1})
        assert out["action"] == "blocked"
        assert out.get("risk_enforced") is False  # bloqueo hard, no enforcement de cola


class TestPostMonitor:
    def _apply(self, knobs, ctrl):
        _with_evidence(ctrl)
        for i in range(2):
            out = ctrl.observe_episode(
                organism_state=_state(margin=0.30, episode=i),
                episode_result=_episode_result(margin=0.30, retrieved=3),
                certificate_metadata={},
            )
        assert out["action"] == "applied"

    def test_commit_when_deltas_improve(self):
        knobs = _Knobs()
        ctrl = _controller(knobs, post_window=2)
        self._apply(knobs, ctrl)
        out = ctrl.observe_episode(
            organism_state=_state(margin=0.35, episode=3),
            episode_result=_episode_result(margin=0.35),
            certificate_metadata={"risk_plus": {"delta_ioc": 0.02}},
        )
        assert out["action"] == "monitoring"
        out = ctrl.observe_episode(
            organism_state=_state(margin=0.40, episode=4),
            episode_result=_episode_result(margin=0.40),
            certificate_metadata={"risk_plus": {"delta_ioc": 0.03}},
        )
        assert out["action"] == "committed"
        assert knobs.values["memory_retrieval_limit"] == 2  # se mantiene
        assert ctrl.lineage.generation == 1

    def test_revert_when_deltas_worsen(self):
        knobs = _Knobs()
        ctrl = _controller(knobs, post_window=2)
        self._apply(knobs, ctrl)
        ctrl.observe_episode(
            organism_state=_state(margin=0.25, episode=3),
            episode_result=_episode_result(margin=0.25),
            certificate_metadata={"risk_plus": {"delta_ioc": -0.05}},
        )
        out = ctrl.observe_episode(
            organism_state=_state(margin=0.20, episode=4),
            episode_result=_episode_result(margin=0.20),
            certificate_metadata={"risk_plus": {"delta_ioc": -0.04}},
        )
        assert out["action"] == "reverted"
        assert knobs.values["memory_retrieval_limit"] == 3  # mando revertido
        assert out["restored_state"].state_id == "state-1"  # checkpoint pre-aplicación
        assert len(ctrl.lineage.rollback_ancestry) == 1


class TestRollback:
    def test_rollback_restores_last_healthy_checkpoint(self):
        knobs = _Knobs(limit=3)
        ctrl = _controller(knobs)
        # Episodio sano fija el checkpoint.
        ctrl.observe_episode(
            organism_state=_state(margin=0.90, episode=1),
            episode_result=_episode_result(margin=0.90),
            certificate_metadata={},
        )
        knobs.values["memory_retrieval_limit"] = 1  # deriva externa de mandos
        out = ctrl.observe_episode(
            organism_state=_state(margin=0.05, episode=2),
            episode_result=_episode_result(margin=0.05, rollback_required=True),
            certificate_metadata={},
        )
        assert out["action"] == "rollback"
        assert out["restored_state"].state_id == "state-1"
        assert knobs.values["memory_retrieval_limit"] == 3  # mandos del checkpoint
        assert len(ctrl.lineage.rollback_ancestry) == 1

    def test_rollback_without_checkpoint_still_records_lineage(self):
        knobs = _Knobs()
        ctrl = _controller(knobs)
        out = ctrl.observe_episode(
            organism_state=_state(margin=0.05),
            episode_result=_episode_result(margin=0.05, rollback_required=True),
            certificate_metadata={},
        )
        assert out["action"] == "rollback"
        assert "restored_state" not in out
        assert len(ctrl.lineage.rollback_ancestry) == 1


class TestRunnerIntegration:
    def test_healthy_run_has_inert_evolution_and_active_lineage(self, tmp_path):
        from runtime.world import ScenarioEpisodeRunner

        runner = ScenarioEpisodeRunner(
            storage=_storage(tmp_path), scenario="thermal_homeostasis"
        )
        result = runner.run_episode()
        assert result["autoevolution"]["action"] in {"none", "disabled"}
        assert result["lineage"]["generation"] == 0
        assert runner.lineage.history[0].entry_type == "genesis"

    def test_forced_degradation_triggers_real_modification(self, tmp_path):
        from runtime.world import ScenarioEpisodeRunner

        runner = ScenarioEpisodeRunner(
            storage=_storage(tmp_path),
            scenario="thermal_homeostasis",
            memory_filter_mode="cross_scenario_analogical",
        )
        # Forzar percepción de degradación: todo margen cuenta como degradado.
        # La evidencia se acumula orgánicamente: las primeras propuestas caen
        # en cuarentena (LCB bajo con poca evidencia) hasta que el run se gana
        # el derecho a mutar con episodios certificados.
        runner._autoevolution.viability_trigger = 1.1
        runner._autoevolution.patience = 2
        runner._autoevolution.cooldown = 2

        actions = []
        applied = None
        for _ in range(10):
            result = runner.run_episode()
            evo = result["autoevolution"]
            actions.append(evo["action"])
            if evo["action"] == "applied":
                applied = evo
                break

        assert applied is not None, f"sin modificación aplicada: {actions}"
        # La modificación tomó efecto sobre el mando REAL correspondiente.
        changes = applied["changes"]
        if "memory_retrieval_limit" in changes:
            assert runner.memory_retrieval_limit == changes["memory_retrieval_limit"]
        if "memory_filter_mode" in changes:
            assert runner.memory_filter_mode == changes["memory_filter_mode"]
        assert runner.lineage.generation == 1
        # El evento quedó persistido en storage.
        events = runner.storage.list_events(
            run_id=runner.run_id, event_types=["autoevolution.applied"]
        )
        assert len(events) == 1

    def test_organism_continuity_across_runners(self, tmp_path):
        from runtime.world import ScenarioEpisodeRunner

        storage = _storage(tmp_path)
        r1 = ScenarioEpisodeRunner(
            storage=storage, run_id="life-x", scenario="thermal_homeostasis"
        )
        for _ in range(2):
            r1.run_episode()
        # El mismo organismo continúa en otro régimen.
        r2 = ScenarioEpisodeRunner(
            storage=storage,
            run_id="life-x",
            scenario="resource_management",
            organism_state=r1.organism_state,
            lineage=r1.lineage,
        )
        result = r2.run_episode()
        assert r2.organism_state.episode_count == 3
        assert result["lineage"]["lineage_id"] == r1.lineage.lineage_id


class TestCriterioDeRetencion:
    """El criterio que decide conservar o revertir una automodificación.

    El histórico es ΔIoC. Medido en este árbol, IoC converge a un único valor
    hacia el paso ~50 de una vida y desde ahí todo ΔIoC vale exactamente 0.0,
    con lo que `mean < 0.0` nunca se cumple y el lazo conserva TODA modificación
    — incluida una que hunda la variable esencial. Estos tests fijan el caso en
    que las dos cantidades DISCREPAN, que es el único donde el criterio importa.
    """

    def _aplicar(self, ctrl, margen=0.30):
        _with_evidence(ctrl)
        for i in range(2):
            out = ctrl.observe_episode(
                organism_state=_state(margin=margen, episode=i),
                episode_result=_episode_result(margin=margen, retrieved=3),
                certificate_metadata={},
            )
        assert out["action"] == "applied", out
        return out

    def _ventana(self, ctrl, margenes, delta_ioc):
        """Cierra la ventana post-aplicación con margen que cae y ΔIoC plano."""
        out = None
        for i, m in enumerate(margenes):
            out = ctrl.observe_episode(
                organism_state=_state(margin=m, episode=3 + i),
                episode_result=_episode_result(margin=m),
                certificate_metadata={"risk_plus": {"delta_ioc": delta_ioc}},
            )
        return out

    def test_senal_desconocida_no_arranca(self):
        try:
            _controller(_Knobs(), retention_signal="viabilidad")
        except ValueError as exc:
            assert "RETENTION_SIGNAL_UNKNOWN" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("una señal inexistente debe fallar al construir")

    def test_ioc_plano_conserva_aunque_la_viabilidad_caiga(self):
        """El default histórico: ΔIoC==0 ⇒ commit, con el margen desplomándose."""
        knobs = _Knobs()
        ctrl = _controller(knobs, post_window=2)  # retention_signal="ioc" por default
        assert ctrl.retention_signal == "ioc"
        self._aplicar(ctrl, margen=0.30)
        out = self._ventana(ctrl, [0.20, 0.10], delta_ioc=0.0)
        assert out["action"] == "committed"
        assert out["retention_decided_by"] == "delta_ioc"
        assert out["mean_delta_ioc"] == 0.0
        # La medida que NO decidió igual se reporta: el margen cayó 0.15 de media.
        assert out["mean_delta_viability"] == -0.15
        assert knobs.values["memory_retrieval_limit"] == 2  # el cambio se quedó

    def test_viabilidad_revierte_el_mismo_caso(self):
        """Mismo episodio, misma ΔIoC plana: con la variable esencial, revierte."""
        knobs = _Knobs()
        ctrl = _controller(knobs, post_window=2, retention_signal="viability")
        self._aplicar(ctrl, margen=0.30)
        out = self._ventana(ctrl, [0.20, 0.10], delta_ioc=0.0)
        assert out["action"] == "reverted"
        assert out["retention_decided_by"] == "delta_viability"
        assert out["mean_delta_viability"] == -0.15
        assert knobs.values["memory_retrieval_limit"] == 3  # mando devuelto
        assert out["restored_state"].state_id == "state-1"
        assert len(ctrl.lineage.rollback_ancestry) == 1

    def test_viabilidad_conserva_lo_que_mejora_el_margen(self):
        """No es un revertidor universal: si el margen sube, se conserva."""
        knobs = _Knobs()
        ctrl = _controller(knobs, post_window=2, retention_signal="viability")
        self._aplicar(ctrl, margen=0.30)
        out = self._ventana(ctrl, [0.40, 0.50], delta_ioc=0.0)
        assert out["action"] == "committed"
        assert out["mean_delta_viability"] == 0.15
        assert knobs.values["memory_retrieval_limit"] == 2

    def test_both_revierte_si_cualquiera_de_las_dos_se_daña(self):
        knobs = _Knobs()
        ctrl = _controller(knobs, post_window=2, retention_signal="both")
        self._aplicar(ctrl, margen=0.30)
        out = self._ventana(ctrl, [0.20, 0.10], delta_ioc=0.02)  # IoC mejora
        assert out["action"] == "reverted"
        assert out["retention_decided_by"] == "delta_viability"
        assert out["mean_delta_ioc"] == 0.02

    def test_ioc_sigue_revirtiendo_cuando_el_cierre_empeora(self):
        """Ninguna de las pruebas históricas cambia: el default queda intacto."""
        knobs = _Knobs()
        ctrl = _controller(knobs, post_window=2)
        self._aplicar(ctrl, margen=0.30)
        out = self._ventana(ctrl, [0.25, 0.20], delta_ioc=-0.05)
        assert out["action"] == "reverted"
        assert out["retention_decided_by"] == "delta_ioc"
        assert knobs.values["memory_retrieval_limit"] == 3
