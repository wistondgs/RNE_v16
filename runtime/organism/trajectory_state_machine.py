"""Maquina de estado trayectorial para RNFE-T5.

La transicion nativa del organismo vive aqui y opera sobre trayectoria.
`transition_organism_state` se mantiene como adapter legacy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .snapshot import OrganismSnapshot
from .state import OrganismBeliefState, OrganismState, PolicyState, ViabilityState
from .trajectory import OrganismTrajectory


@dataclass
class TrajectoryStateMachine:
    """Transicion nativa T_{t+1} = Psi(T_t, r_t, o_t, u_t, cf_t, m_t)."""

    def advance_state(
        self,
        *,
        current: OrganismState,
        episode_result: Mapping[str, Any],
        regime: str,
        new_state_id: str,
        timestamp: str,
    ) -> OrganismState:
        episode = dict(episode_result.get("episode", {}))
        result = dict(episode.get("result", {}))
        context = dict(episode.get("context", {}))
        observation = dict(context.get("observation", {}))
        cert = dict(episode_result.get("certification", {}))

        alarm = bool(observation.get("alarm", False))
        relation_kind = str(result.get("relation_kind", "unknown"))
        belief_data = dict(episode_result.get("belief_state", {}))
        posterior_data = dict(belief_data.get("posterior", {})) if belief_data else {}
        retrieved_memory = list(context.get("retrieved_memory", []) or [])
        memory_pressure = min(1.0, len(retrieved_memory) / 5.0)

        factual_delta = float(result.get("factual_delta", 0.0) or 0.0)
        counterfactual_delta = float(result.get("counterfactual_delta", 0.0) or 0.0)
        transition_gap = abs(factual_delta - counterfactual_delta)
        trajectory_factor = max(
            0.6,
            min(1.4, 1.0 - transition_gap + (0.15 * (1.0 - memory_pressure))),
        )
        uncertainty_decay = max(0.80, min(0.99, 0.92 + 0.04 * trajectory_factor))

        new_belief = OrganismBeliefState(
            alarm_probability=0.9 if alarm else 0.1,
            intervention_efficacy=float(
                posterior_data.get("policy_confidence", current.belief.intervention_efficacy)
            ),
            causal_support_confidence=float(
                posterior_data.get(
                    "causal_support_confidence",
                    0.9
                    if relation_kind == "support"
                    else (0.2 if relation_kind == "contradiction" else 0.5),
                )
            ),
            memory_purity_estimate=max(
                0.0,
                min(
                    1.0,
                    float(
                        posterior_data.get(
                            "memory_purity_confidence",
                            current.belief.memory_purity_estimate,
                        )
                    )
                    - 0.05 * memory_pressure,
                ),
            ),
            trace_integrity_confidence=float(
                posterior_data.get("trace_confidence", current.belief.trace_integrity_confidence)
            ),
            regime_uncertainty=max(0.0, current.belief.regime_uncertainty * uncertainty_decay),
        )

        drift_delta = abs(new_belief.intervention_efficacy - current.belief.intervention_efficacy) * trajectory_factor
        new_drift = min(1.0, current.policy.accumulated_drift + drift_delta * 0.1)
        new_policy = PolicyState(
            control_class=current.policy.control_class,
            sensitivity=current.policy.sensitivity,
            perturbation_tolerance=current.policy.perturbation_tolerance,
            recovery_capacity=max(
                0.0,
                min(
                    1.0,
                    current.policy.recovery_capacity - drift_delta * 0.05 + 0.01 * trajectory_factor,
                ),
            ),
            accumulated_drift=round(new_drift, 4),
        )

        is_certified = cert.get("verdict") == "certified"
        margin_delta = (0.01 if is_certified else -0.03) * trajectory_factor
        deg_delta = (0.0 if is_certified else 0.02) + (0.01 * memory_pressure if not is_certified else 0.0)
        new_viability = ViabilityState(
            viability_margin=max(0.0, min(1.0, current.viability.viability_margin + margin_delta)),
            reserve_stability=max(
                0.0,
                min(
                    1.0,
                    current.viability.reserve_stability
                    + ((0.01 * trajectory_factor) if is_certified else (-0.02 - 0.01 * memory_pressure)),
                ),
            ),
            accumulated_degradation=max(
                0.0,
                min(1.0, current.viability.accumulated_degradation + deg_delta),
            ),
            rollback_readiness=current.viability.rollback_readiness,
            recovery_debt=max(
                0.0,
                current.viability.recovery_debt
                + ((-0.01 * trajectory_factor) if is_certified else (0.02 + 0.01 * memory_pressure)),
            ),
        )

        return OrganismState(
            state_id=new_state_id,
            timestamp=timestamp,
            active_regime=regime,
            episode_count=current.episode_count + 1,
            belief=new_belief,
            policy=new_policy,
            identity=current.identity,
            viability=new_viability,
            modification=current.modification,
        )

    def observe(
        self,
        *,
        trajectory: OrganismTrajectory,
        regime: str,
        episode_result: Mapping[str, Any],
        authoritative_state: OrganismState,
    ) -> OrganismSnapshot:
        """Registra la transición que YA HIZO la autoridad. No deriva fisiología.

        D-047 — autoridad única de transición. `advance()` DERIVA un estado nuevo
        llamando a `advance_state`; eso está bien cuando quien llama es la única
        autoridad sobre el organismo (el camino del episodio mínimo, que no tiene
        `OrganismState` propio). En el life-loop **sí hay** autoridad —
        `Kernel → ScenarioEpisodeRunner → transition_organism_state`— y derivar
        otra vez producía una SEGUNDA transición fisiológica por paso lógico:
        medido, `N_advance_state = 2` en 40/40 pasos y 40 `OrganismState`
        huérfanos que nadie adoptaba (H-045).

        `observe` toma el estado autoritativo y solo lo ASIENTA en la trayectoria
        del tribunal, que la necesita para `window`, `digest` y el motor de flujo.
        El snapshot hereda el `state_id` de la autoridad (`from_state`), así que
        la identidad es continua y no hay huérfanos.
        """
        snapshot = OrganismSnapshot.from_state(authoritative_state)
        self._asentar(trajectory=trajectory, snapshot=snapshot, regime=regime,
                      episode_result=episode_result)
        return snapshot

    @staticmethod
    def _asentar(
        *,
        trajectory: OrganismTrajectory,
        snapshot: OrganismSnapshot,
        regime: str,
        episode_result: Mapping[str, Any],
    ) -> None:
        """Añade un punto a la trayectoria. Compartido por `advance` y `observe`."""
        episode = dict(episode_result.get("episode", {}))
        context = dict(episode.get("context", {}))
        trajectory.append(
            snapshot=snapshot,
            regime=regime,
            observation=dict(context.get("observation", {})),
            intervention={"label": context.get("intervention")},
            counterfactual=dict(context.get("counterfactual", {})),
            memory_context={"retrieved_memory_count": len(context.get("retrieved_memory", []) or [])},
        )

    def advance(
        self,
        *,
        trajectory: OrganismTrajectory,
        regime: str,
        episode_result: Mapping[str, Any],
        new_snapshot_id: str,
        timestamp: str,
    ) -> OrganismSnapshot:
        """Deriva un estado nuevo. Solo legítimo cuando el llamador ES la autoridad."""
        if trajectory.points:
            current_state = trajectory.points[-1].snapshot.to_state()
        else:
            current_state = OrganismState()

        next_state = self.advance_state(
            current=current_state,
            episode_result=episode_result,
            regime=regime,
            new_state_id=new_snapshot_id,
            timestamp=timestamp,
        )
        snapshot = OrganismSnapshot.from_state(next_state)
        self._asentar(trajectory=trajectory, snapshot=snapshot, regime=regime,
                      episode_result=episode_result)
        return snapshot

