"""Controlador principal MSRC (Multi-Scale Resolution Controller)."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, Optional

from runtime.storage.records import utc_now_iso

from .contracts import (
    ProbeResult,
    ScaleDecisionRecord,
    ScalePolicyState,
)
from .cross_scale_memory_guard import CrossScaleMemoryGuard
from .scale_audit_logger import ScaleAuditLogger
from .scale_catalog import ScaleCatalog
from .scale_estimator import ScaleEstimator
from .scale_policy_engine import ScalePolicyEngine
from .scale_transition_manager import ScaleTransitionManager
from .vram_sampler import NvidiaVRAMSampler


class MSRCController:
    """Orquesta estimación, política, transición y auditoría de escala."""

    def __init__(
        self,
        *,
        storage,
        output_dir=None,
        catalog: Optional[ScaleCatalog] = None,
        estimator: Optional[ScaleEstimator] = None,
        policy_engine: Optional[ScalePolicyEngine] = None,
        transition_manager: Optional[ScaleTransitionManager] = None,
        memory_guard: Optional[CrossScaleMemoryGuard] = None,
        vram_sampler: Optional[NvidiaVRAMSampler] = None,
        audit_logger: Optional[ScaleAuditLogger] = None,
    ):
        self.storage = storage
        self.catalog = catalog or ScaleCatalog.default()
        self.estimator = estimator or ScaleEstimator(catalog=self.catalog)
        self.policy_engine = policy_engine or ScalePolicyEngine()
        self.transition_manager = transition_manager or ScaleTransitionManager(catalog=self.catalog)
        self.memory_guard = memory_guard or CrossScaleMemoryGuard()
        self.vram_sampler = vram_sampler or NvidiaVRAMSampler()
        self.audit_logger = audit_logger or ScaleAuditLogger(
            storage=storage,
            output_dir=output_dir,
        )

    def ensure_state(self, state: Optional[ScalePolicyState], *, default_scale_id: str) -> ScalePolicyState:
        if state is not None:
            return state
        return ScalePolicyState(current_scale_id=default_scale_id)

    def step(
        self,
        *,
        run_id: str,
        episode_id: str,
        state: ScalePolicyState,
        observation: Dict[str, Any],
        viability_margin: Optional[float],
        certification_verdict: Optional[str],
        metrics: Optional[Dict[str, Any]] = None,
        alarm_threshold: float = 0.85,
        probe_result: Optional[ProbeResult] = None,
        probe_executor=None,
        trace_group_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        # SSOT del commit de escala (CANON §3.1.6, atomicidad).
        #
        # `source_scale_id` se captura ANTES de decidir y es la única verdad sobre
        # dónde estaba el organismo en este step. El commit de la escala nueva
        # ocurre en UN SOLO lugar —más abajo, con lo que devuelve el transition
        # manager— y solo en el camino de éxito; si la transición aborta, el
        # manager devuelve el origen y la escala queda intacta.
        #
        # No leemos `state.current_scale_id` después de `decide()` para eso: el
        # policy engine es un decisor, no un aplicador. Si alguna vez volviera a
        # escribir la escala en el state, este capture evita que un abort deje
        # pegada una escala que nunca se aplicó (era exactamente el bug: el abort
        # registraba `rollback_applied=True` y se quedaba en la escala nueva).
        source_scale_id = state.current_scale_id

        vram_snapshot = self.vram_sampler.sample()
        estimate = self.estimator.estimate(
            current_scale_id=source_scale_id,
            observation=observation,
            viability_margin=viability_margin,
            certification_verdict=certification_verdict,
            metrics=metrics,
            vram_snapshot=vram_snapshot,
            alarm_threshold=alarm_threshold,
        )

        action = self.policy_engine.decide(
            catalog=self.catalog,
            state=state,
            estimate=estimate,
            probe_result=probe_result,
        )

        if action.action_type == "fork_probe":
            self.audit_logger.log_probe_started(
                run_id=run_id,
                payload={
                    "episode_id": episode_id,
                    "source_scale_id": source_scale_id,
                    "target_scale_id": action.target_scale_id,
                    "reason": action.reason,
                    "estimate": estimate.to_dict(),
                    "trace_group_id": trace_group_id,
                },
            )

        transition_result = self.transition_manager.execute_action(
            run_id=run_id,
            episode_id=episode_id,
            current_scale_id=source_scale_id,
            action=action,
            estimate=estimate,
            probe_executor=probe_executor,
            # El ProbeResult pendiente (medido en el fork_probe de un step previo)
            # llega hasta acá para que `commit_probe_result` commitee LO QUE EL
            # PROBE MIDIÓ y no la estimación del catálogo.
            probe_result=probe_result,
        )

        selected_scale_id = transition_result["selected_scale_id"]
        transition_record = transition_result["transition_record"]
        if trace_group_id:
            transition_record = replace(
                transition_record,
                metadata={
                    **dict(transition_record.metadata or {}),
                    "trace_group_id": trace_group_id,
                },
            )
        maybe_probe = transition_result.get("probe_result")

        if maybe_probe is not None:
            self.audit_logger.log_probe_completed(
                run_id=run_id,
                payload={
                    "episode_id": episode_id,
                    "target_scale_id": maybe_probe.target_scale_id,
                    "probe_result": maybe_probe.to_dict(),
                    "trace_group_id": trace_group_id,
                },
            )

        if action.action_type == "commit_probe_result":
            self.audit_logger.log_probe_committed(
                run_id=run_id,
                payload={
                    "episode_id": episode_id,
                    "target_scale_id": action.target_scale_id,
                    "metadata": action.metadata,
                    # Qué se commiteó realmente: medición del probe o nada medido.
                    "cost_measurement_source": transition_record.cost_measurement_source,
                    "unmeasured_costs": list(transition_record.unmeasured_costs),
                    "trace_group_id": trace_group_id,
                },
            )
        if action.action_type == "discard_probe_result":
            self.audit_logger.log_probe_discarded(
                run_id=run_id,
                payload={
                    "episode_id": episode_id,
                    "target_scale_id": action.target_scale_id,
                    "metadata": action.metadata,
                    "trace_group_id": trace_group_id,
                },
            )

        # ÚNICO punto de commit de la escala en todo MSRC (ver docstring del
        # transition manager). En el abort, `selected_scale_id` es el origen: la
        # escala queda como estaba y la atomicidad de CANON §3.1.6 se cumple.
        state.current_scale_id = selected_scale_id

        decision_record = ScaleDecisionRecord(
            run_id=run_id,
            episode_id=episode_id,
            step_index=state.step_index,
            current_scale_id=state.current_scale_id,
            action=action,
            estimate=estimate,
            selected_scale_id=selected_scale_id,
            timestamp=utc_now_iso(),
            metadata={
                "vram_snapshot": vram_snapshot,
                "policy_state": state.to_dict(),
                "trace_group_id": trace_group_id,
            },
        )

        self.audit_logger.log_decision(decision_record)
        self.audit_logger.log_transition(transition_record)

        if state.oscillation_events > 0 and state.oscillation_events % 3 == 0:
            self.audit_logger.log_oscillation(
                run_id=run_id,
                payload={
                    "episode_id": episode_id,
                    "oscillation_events": state.oscillation_events,
                    "last_actions": list(state.last_actions),
                    "trace_group_id": trace_group_id,
                },
            )

        if state.upgrade_regret > 0 or state.downgrade_regret > 0:
            self.audit_logger.log_regret(
                run_id=run_id,
                payload={
                    "episode_id": episode_id,
                    "upgrade_regret": state.upgrade_regret,
                    "downgrade_regret": state.downgrade_regret,
                    "trace_group_id": trace_group_id,
                },
            )

        return {
            "state": state,
            "estimate": estimate,
            "action": action,
            "decision_record": decision_record,
            "selected_scale_id": selected_scale_id,
            "transition_record": transition_record,
            "probe_result": maybe_probe,
            "vram_snapshot": vram_snapshot,
            "trace_group_id": trace_group_id,
        }

    def sanitize_cross_scale_memory(
        self,
        *,
        source_scale_id: str,
        target_scale_id: str,
        payload: Dict[str, Any],
    ):
        return self.memory_guard.sanitize_for_cross_scale(
            source_scale_id=source_scale_id,
            target_scale_id=target_scale_id,
            payload=payload,
        )
