"""Corte constitucional T5: trayectoria + flujo + renormalizacion + riesgo."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any, Dict, Literal
from uuid import uuid4

from runtime.storage import StorageFacade

from .constitution_flow import ConstitutionalFlowEngine
from .regime_model import get_regime_for_scenario
from .regime_renormalization import RegimeRenormalizationEngine, RenormalizationResult
from .risk_process import ConstitutionalRiskProcess, RiskState
from .t5_mode import get_t5_mode
from .trajectory import OrganismTrajectory
from .state import OrganismState
from .trajectory_state_machine import TrajectoryStateMachine
from .viability_kernel import TrajectoryViabilityKernel


logger = logging.getLogger(__name__)


# B26.2 — estado del eje de renormalización en este episodio.
#   not_applicable: no hubo cruce de régimen (mismo escenario, o primer episodio).
#                   No hay renormalización que medir: es un eje SIN SUJETO.
#   measured:       hubo cruce y ambos escenarios tienen régimen latente conocido.
#                   El residual es una MEDICIÓN.
#   unmeasured:     hubo cruce y al menos uno de los dos escenarios NO tiene régimen.
#                   El organismo NO SABE renormalizar este cruce. El residual es
#                   AUSENCIA DE EVIDENCIA, no evidencia de perfección.
RenormalizationStatus = Literal["not_applicable", "measured", "unmeasured"]


@dataclass(frozen=True)
class CourtEpisodeResult:
    trajectory_id: str
    canonical_scope: str
    legacy_scope: str
    transfer_advice: str
    flow_validity: bool
    erosion: float
    phase_drift: float
    rollback_obligation: bool
    viability_score: float
    organism_risk: float
    edge_risk: float
    modification_risk: float
    inheritance_risk: float
    failure_mode_count: int

    # B26.2 — antes eran `float` y valían 0.0 cuando el cruce no era renormalizable.
    # 0.0 es el valor MÁS FAVORABLE: cero aporte al riesgo (risk_process) y
    # `renorm_residual_spike` inalcanzable (failure_atlas). Ahora `None` = NO MEDIDO.
    # Quien los consuma DEBE mirar `renormalization_status` antes de leerlos como salud.
    renormalization_residual: float | None
    renormalization_uncertainty: float | None
    expected_recovery_cost: float | None
    renormalization_status: RenormalizationStatus = "not_applicable"

    # Cruce de régimen que ocurrió pero NO se pudo renormalizar (escenarios sin
    # régimen latente). Vacío cuando no hay omisión. Declarado por nombre.
    unrenormalizable_edge: tuple[str, ...] = ()
    unmeasured_axes: tuple[str, ...] = ()

    @property
    def renormalization_measured(self) -> bool:
        return self.renormalization_status == "measured"


class ConstitutionalCourtRuntime:
    """Orquesta el dictamen constitucional primario del organismo."""

    def __init__(self, *, storage: StorageFacade):
        self.storage = storage
        self.flow_engine = ConstitutionalFlowEngine()
        self.renorm_engine = RegimeRenormalizationEngine()
        self.risk_process = ConstitutionalRiskProcess()
        self.viability_kernel = TrajectoryViabilityKernel()
        self.state_machine = TrajectoryStateMachine()
        self._trajectory_by_run: Dict[str, OrganismTrajectory] = {}
        self._last_regime_by_run: Dict[str, str] = {}

    def _legacy_scope_from_canonical(self, canonical_scope: str) -> str:
        mapping = {
            "local_safe": "local_only",
            "transfer_safe": "compatible_transfer",
            "modification_safe": "compatible_transfer",
            "inheritance_safe": "compatible_transfer",
            "quarantine_only": "analogical_hint_only",
            "blocked": "blocked",
        }
        return mapping.get(canonical_scope, "blocked")

    def _scope_from_risk(
        self,
        *,
        cross_regime: bool,
        renorm_unmeasured: bool,
        modification_pending: bool,
        flow_valid: bool,
        rollback: bool,
        viability_score: float,
        organism_risk: float,
        edge_risk: float,
        modification_risk: float,
        inheritance_risk: float,
    ) -> tuple[str, str]:
        """Deriva el scope constitucional.

        B26.2 — ``renorm_unmeasured``: hubo cruce de régimen y NO se pudo
        renormalizar. La corte **no puede certificar transferencia ni herencia**
        sobre un cruce cuyo residual nunca midió: certificar exige evidencia, y acá
        no hay. Cae a ``quarantine_only`` / ``analogical_hint``, que es exactamente
        el estado que el canon prescribe para transferencia no certificada
        (SCENARIO_CONTRACTS_v1 §7.3) y para el cruce peligroso (§7.5).

        Ojo con la simetría: esto NO es ``blocked``. "No sé renormalizar esto" no es
        "la renormalización falló catastróficamente". La corte se ABSTIENE de
        certificar; no declara una falla crítica.
        """
        aggregate = max(organism_risk, edge_risk, modification_risk, inheritance_risk)
        if rollback or viability_score < 0.20 or aggregate >= 0.85:
            return "blocked", ""
        if not flow_valid or viability_score < 0.35 or aggregate >= 0.65:
            return "quarantine_only", "analogical_hint"

        if modification_pending:
            if modification_risk < 0.45 and organism_risk < 0.55:
                return "modification_safe", ""
            return "quarantine_only", "analogical_hint"

        if cross_regime:
            # El cruce ocurrió pero el residual NO se midió: sin evidencia no hay
            # certificado. Antes este caso ni siquiera llegaba acá (cross_regime era
            # False porque renorm_result era None) y podía terminar en `local_safe`:
            # el cruce más incierto que existe cobraba el scope MÁS favorable.
            if renorm_unmeasured:
                return "quarantine_only", "analogical_hint"
            if inheritance_risk < 0.30 and edge_risk < 0.35 and organism_risk < 0.40:
                return "inheritance_safe", ""
            if edge_risk < 0.50 and organism_risk < 0.55:
                return "transfer_safe", ""
            return "quarantine_only", "analogical_hint"

        if organism_risk < 0.55:
            return "local_safe", ""
        return "quarantine_only", "analogical_hint"

    def _seed_risk_from_storage(
        self,
        *,
        run_id: str,
        trajectory_id: str,
        scope_type: str,
        scope_key: str,
    ) -> None:
        if self.risk_process.get(scope_type=scope_type, scope_key=scope_key) is not None:
            return
        previous = self.storage.list_constitutional_risk_states(
            run_id=run_id,
            trajectory_id=trajectory_id,
            scope_type=scope_type,
            scope_key=scope_key,
            limit=1,
        )
        if previous:
            self.risk_process.seed_score(
                scope_type=scope_type,  # type: ignore[arg-type]
                scope_key=scope_key,
                risk_score=previous[0].risk_score,
            )

    def _persist_risk_scope(
        self,
        *,
        run_id: str,
        trajectory_id: str,
        window_end_episode: int,
        scope_type: str,
        scope_key: str,
        update_payload: Dict[str, Any],
        state: RiskState,
        mode: str,
    ) -> None:
        previous = self.storage.list_constitutional_risk_states(
            run_id=run_id,
            trajectory_id=trajectory_id,
            scope_type=scope_type,
            scope_key=scope_key,
            limit=1,
        )
        prev_state_id = previous[0].state_id if previous else None
        step_index = (previous[0].step_index + 1) if previous else 0
        state_id = f"risk-{trajectory_id}-{scope_type}-{window_end_episode}-{step_index}"

        failure_events = [
            {
                "name": f.name,
                "severity": f.severity,
                "reversible": f.reversible,
                "recovery_protocol": f.recovery_protocol,
                "trigger": f.signature.trigger,
                "metrics": f.signature.metrics,
            }
            for f in state.failure_atlas.events
        ]

        self.storage.write_constitutional_risk_state(
            state_id=state_id,
            run_id=run_id,
            trajectory_id=trajectory_id,
            scope_type=scope_type,
            scope_key=scope_key,
            risk_score=state.risk_score,
            prev_state_id=prev_state_id,
            step_index=step_index,
            risk_json={
                "update": update_payload,
                "state": {
                    "scope_type": state.scope_type,
                    "scope_key": state.scope_key,
                    "risk_score": state.risk_score,
                    "drift_identity": state.drift_identity,
                    "drift_policy": state.drift_policy,
                    "delta_viability": state.delta_viability,
                    "delta_purity": state.delta_purity,
                    "delta_modification": state.delta_modification,
                    "failure_modes": [f["name"] for f in failure_events],
                    "failure_events": failure_events,
                    # B26.2: los ejes que el atlas NO pudo evaluar viajan al ledger.
                    # Un `failure_events` vacío con `unmeasured_axes` no vacío NO es
                    # un certificado de salud: es un certificado con agujeros.
                    "unmeasured_axes": list(state.failure_atlas.unmeasured_axes),
                    "atlas_complete": state.failure_atlas.is_complete,
                },
                "chain": {
                    "prev_state_id": prev_state_id,
                    "step_index": step_index,
                },
            },
            metadata={"mode": mode},
        )
        for index, failure in enumerate(failure_events):
            self.storage.write_failure_atlas_event(
                event_id=f"failure-{trajectory_id}-{scope_type}-{window_end_episode}-{step_index}-{index}",
                run_id=run_id,
                trajectory_id=trajectory_id,
                scope_type=scope_type,
                scope_key=scope_key,
                failure_class=str(failure["name"]),
                severity=str(failure["severity"]),
                reversible=bool(failure["reversible"]),
                recovery_protocol=str(failure["recovery_protocol"]),
                signature_json={
                    "trigger": failure["trigger"],
                    "metrics": failure["metrics"],
                },
                metadata={"mode": mode, "step_index": step_index},
            )

    def ingest_episode(
        self,
        *,
        run_id: str,
        episode_result: Dict[str, Any],
        organism_state: OrganismState | None = None,
    ) -> CourtEpisodeResult | None:
        """Evalúa un episodio cerrado.

        D-047 — `organism_state` es el estado POST-transición que produjo la
        autoridad (`Kernel → Runner → transition_organism_state`). Cuando llega,
        el tribunal lo OBSERVA y no acuña fisiología propia. Cuando no llega —el
        camino del episodio mínimo, que no tiene `OrganismState`— el tribunal ES
        la única autoridad y deriva como siempre.
        """
        mode = get_t5_mode()
        if mode == "off":
            return None

        episode = episode_result.get("episode", {})
        episode_id = str(episode.get("episode_id", f"episode-{uuid4().hex[:8]}"))
        scenario_metadata = episode.get("scenario_metadata", {})
        scenario_name = str(scenario_metadata.get("scenario_name", episode.get("scenario", "unknown")))
        timestamp = str(episode.get("timestamp", ""))

        trajectory = self._trajectory_by_run.get(run_id)
        if trajectory is None:
            trajectory = OrganismTrajectory(trajectory_id=f"traj-{run_id}")
            self._trajectory_by_run[run_id] = trajectory

        if organism_state is not None:
            snapshot = self.state_machine.observe(
                trajectory=trajectory,
                regime=scenario_name,
                episode_result=episode_result,
                authoritative_state=organism_state,
            )
        else:
            snapshot = self.state_machine.advance(
                trajectory=trajectory,
                regime=scenario_name,
                episode_result=episode_result,
                new_snapshot_id=f"snap-{uuid4().hex[:12]}",
                timestamp=timestamp,
            )

        window = trajectory.window(8)
        digest = trajectory.digest(window_size=8)
        window_id = f"window-{trajectory.trajectory_id}-{window.end_episode}"
        self.storage.write_organism_snapshot(
            snapshot_id=snapshot.snapshot_id,
            run_id=run_id,
            episode_id=episode_id,
            trajectory_id=trajectory.trajectory_id,
            regime=scenario_name,
            snapshot_json=snapshot.to_dict(),
            metadata={"mode": mode},
        )
        self.storage.write_trajectory_window(
            window_id=window_id,
            run_id=run_id,
            trajectory_id=trajectory.trajectory_id,
            start_episode=window.start_episode,
            end_episode=window.end_episode,
            snapshots_json={"snapshots": [point.snapshot.to_dict() for point in window.points]},
            digest_json=asdict(digest),
            metadata={"window_size": len(window.points)},
        )

        flow_result = self.flow_engine.evaluate(trajectory, window_size=8)
        flow_report = self.flow_engine.to_report(trajectory=trajectory, result=flow_result, window_size=8)
        self.storage.write_trajectory_flow_report(
            report_id=f"flow-{trajectory.trajectory_id}-{window.end_episode}",
            run_id=run_id,
            trajectory_id=trajectory.trajectory_id,
            window_id=window_id,
            flow_validity=flow_result.flow_validity,
            erosion=flow_result.erosion,
            phase_drift=flow_result.phase_drift,
            rollback_obligation=flow_result.rollback_obligation,
            report_json=asdict(flow_report),
            metadata={
                "mode": mode,
                "point_violations": list(flow_result.point_violations),
                "flow_violations": list(flow_result.flow_violations),
                "thresholds": flow_result.thresholds,
            },
        )

        viability = self.viability_kernel.assess(
            trajectory=trajectory,
            flow_result=flow_result,
            window_size=8,
        )

        # ── B26.2 — el cruce de régimen y su renormalización ──────────────────
        # ANTES: si CUALQUIERA de los dos escenarios no tenía régimen latente, el
        # bloque entero se salteaba en silencio — sin else, sin log, sin flag — y
        # `renorm_residual` se quedaba en 0.0. Y 0.0 es el valor MÁS FAVORABLE:
        #   - risk_process: `+ 0.12 * max(0.0, renorm_residual)` => CERO riesgo.
        #   - failure_atlas: `if renorm_residual > 0.55` => `renorm_residual_spike`
        #     INALCANZABLE.
        # Es decir: el cruce más incierto que existe —uno hacia un régimen que el
        # organismo NO CONOCE— se puntuaba como si la renormalización hubiera sido
        # PERFECTA. Ausencia de dato = evidencia favorable, en la corte constitucional.
        #
        # AHORA: un cruce no renormalizable queda NO MEDIDO (None) y DECLARADO.
        prev_regime_name = self._last_regime_by_run.get(run_id)
        renorm_result: RenormalizationResult | None = None
        renorm_residual: float | None = None
        renorm_uncertainty: float | None = None
        renorm_recovery_cost: float | None = None
        renorm_status: RenormalizationStatus = "not_applicable"
        unrenormalizable_edge: tuple[str, ...] = ()

        cross_regime = bool(prev_regime_name) and prev_regime_name != scenario_name
        if cross_regime:
            source_regime = get_regime_for_scenario(prev_regime_name)
            target_regime = get_regime_for_scenario(scenario_name)

            if source_regime is None or target_regime is None:
                # NO MEDIDO. El organismo no sabe renormalizar este cruce.
                # No se fabrica 0.0 (falsa salud) ni 1.0 (falso pánico): se declara.
                renorm_status = "unmeasured"
                unmapped = tuple(
                    name
                    for name, regime in (
                        (prev_regime_name, source_regime),
                        (scenario_name, target_regime),
                    )
                    if regime is None
                )
                unrenormalizable_edge = (str(prev_regime_name), str(scenario_name))
                logger.warning(
                    "B26.2: cruce de régimen NO renormalizable %s -> %s "
                    "(sin régimen latente: %s). residual = NO MEDIDO (no 0.0). "
                    "La corte no certifica transferencia sobre este cruce.",
                    prev_regime_name,
                    scenario_name,
                    ", ".join(unmapped),
                )
            else:
                renorm_status = "measured"
                renorm_result = self.renorm_engine.renormalize(
                    source_regime=source_regime,
                    target_regime=target_regime,
                    snapshot=snapshot,
                )
                renorm_residual = renorm_result.regime_residual.residual_error
                renorm_uncertainty = renorm_result.uncertainty.transport_uncertainty
                renorm_recovery_cost = renorm_result.regime_residual.expected_recovery_cost
                self.storage.write_renormalization_event(
                    event_id=f"renorm-{trajectory.trajectory_id}-{window.end_episode}",
                    run_id=run_id,
                    trajectory_id=trajectory.trajectory_id,
                    source_regime=renorm_result.renormalization_map.source_regime,
                    target_regime=renorm_result.renormalization_map.target_regime,
                    residual_error=renorm_residual,
                    transport_uncertainty=renorm_uncertainty,
                    expected_recovery_cost=renorm_recovery_cost,
                    map_json=asdict(renorm_result),
                    metadata={"mode": mode},
                )

        previous_snapshot = window.points[-2].snapshot if len(window.points) > 1 else snapshot
        d_viability = snapshot.viability.viability_margin - previous_snapshot.viability.viability_margin
        d_purity = max(0.0, previous_snapshot.belief.memory_purity_estimate - snapshot.belief.memory_purity_estimate)
        d_modification = 1.0 if snapshot.modification.lineage_delta_pending else 0.0

        scope_defs = [
            ("organism", run_id),
            ("modification", snapshot.modification.active_proposals[0].proposal_id if snapshot.modification.active_proposals else f"{run_id}:mod"),
            # B41: el scope de HERENCIA (μ_t) se keya por el linaje del GENOMA, no por la
            # corrida efímera. El fallback a run_id se reemplaza por el centinela de linaje
            # de génesis (IdentityState.lineage_id default), que es estable por-organismo.
            ("inheritance", snapshot.identity.lineage_id or "genesis"),
        ]
        if renorm_result is not None:
            scope_defs.append(
                (
                    "edge",
                    f"{renorm_result.renormalization_map.source_regime}->{renorm_result.renormalization_map.target_regime}",
                )
            )
        elif renorm_status == "unmeasured":
            # B26.2: el borde EXISTE aunque no sepamos renormalizarlo. Antes no se
            # abría scope de edge y el cruce desaparecía del ledger de riesgo.
            # Se keya por nombre de escenario (no hay regime_id que usar).
            scope_defs.append(("edge", f"{prev_regime_name}->{scenario_name}"))

        updates: Dict[str, RiskState] = {}
        for scope_type, scope_key in scope_defs:
            self._seed_risk_from_storage(
                run_id=run_id,
                trajectory_id=trajectory.trajectory_id,
                scope_type=scope_type,
                scope_key=scope_key,
            )
            update = self.risk_process.update(
                scope_type=scope_type,  # type: ignore[arg-type]
                scope_key=scope_key,
                drift_identity=digest.identity_curvature,
                drift_policy=digest.policy_phase_drift,
                delta_viability=d_viability,
                delta_purity=d_purity,
                delta_modification=d_modification,
                erosion=flow_result.erosion,
                renorm_residual=renorm_residual,
                # B85 — el status ya distingue los tres casos acá arriba; hay que PROPAGARLO.
                # Sin esto, un episodio intra-escenario (donde no hubo cruce y por lo tanto
                # NO HABÍA NADA que renormalizar) marcaba el atlas como incompleto, igual que
                # un cruce real que no se pudo medir. Un agujero de verdad quedaba
                # indistinguible del caso trivial, y "atlas incompleto" pasaba a ser la norma
                # permanente — o sea, dejaba de significar algo.
                renorm_not_applicable=(renorm_status == "not_applicable"),
            )
            state = self.risk_process.get(scope_type=scope_type, scope_key=scope_key)
            assert state is not None
            updates[scope_type] = state
            self._persist_risk_scope(
                run_id=run_id,
                trajectory_id=trajectory.trajectory_id,
                window_end_episode=window.end_episode,
                scope_type=scope_type,
                scope_key=scope_key,
                update_payload=asdict(update),
                state=state,
                mode=mode,
            )

        organism_state = updates["organism"]
        edge_state = updates.get("edge")
        mod_state = updates["modification"]
        inheritance_state = updates["inheritance"]
        edge_risk = edge_state.risk_score if edge_state is not None else 0.0

        canonical_scope, transfer_advice = self._scope_from_risk(
            # B26.2: el cruce cuenta como cruce AUNQUE no se haya podido renormalizar.
            # Antes era `renorm_result is not None`, así que un cruce no mapeado se le
            # presentaba a la corte como "no hubo cruce" y podía cobrar `local_safe`.
            cross_regime=cross_regime,
            renorm_unmeasured=(renorm_status == "unmeasured"),
            modification_pending=snapshot.modification.lineage_delta_pending,
            flow_valid=flow_result.flow_validity,
            rollback=flow_result.rollback_obligation or viability.rollback_required,
            viability_score=viability.viability_score,
            organism_risk=organism_state.risk_score,
            edge_risk=edge_risk,
            modification_risk=mod_state.risk_score,
            inheritance_risk=inheritance_state.risk_score,
        )
        legacy_scope = self._legacy_scope_from_canonical(canonical_scope)

        self._last_regime_by_run[run_id] = scenario_name
        return CourtEpisodeResult(
            trajectory_id=trajectory.trajectory_id,
            canonical_scope=canonical_scope,
            legacy_scope=legacy_scope,
            transfer_advice=transfer_advice,
            flow_validity=flow_result.flow_validity,
            erosion=flow_result.erosion,
            phase_drift=flow_result.phase_drift,
            rollback_obligation=flow_result.rollback_obligation or viability.rollback_required,
            viability_score=viability.viability_score,
            organism_risk=organism_state.risk_score,
            edge_risk=round(edge_risk, 4),
            modification_risk=mod_state.risk_score,
            inheritance_risk=inheritance_state.risk_score,
            failure_mode_count=len(organism_state.failure_atlas.events),
            renormalization_residual=renorm_residual,
            renormalization_uncertainty=renorm_uncertainty,
            expected_recovery_cost=renorm_recovery_cost,
            renormalization_status=renorm_status,
            unrenormalizable_edge=unrenormalizable_edge,
            unmeasured_axes=tuple(organism_state.failure_atlas.unmeasured_axes),
        )

