"""Replay shadow puro de ventanas vitales con adaptadores candidatos."""

from __future__ import annotations

from typing import Any

from runtime.neural.contracts import (
    CausalContextView,
    InferenceScope,
    NeuralInferenceRequest,
    ResourceSnapshot,
)
from runtime.neural.integration.adapters import canonical_adapter_registry
from runtime.neural.integration.adapters import N4Adapter
from runtime.neural.integration.contracts import SymbiosisIdentity, canonical_sha256

from .trajectory_window import DynamicTrajectoryWindow


REPLAY_SCHEMA_VERSION = "organism-trajectory-replay-v1"


class ShadowTrajectoryReplay:
    """No recibe storage ni autoridades vivas; sólo compara propuestas."""

    def replay(self, window: DynamicTrajectoryWindow, *, organ_id: str) -> dict[str, Any]:
        adapter = canonical_adapter_registry()[organ_id]
        rows = []
        for transition in window.transitions:
            replay_context = dict(transition.neural_state_delta.get("replay_context") or {})
            historical = next(
                (
                    item for item in transition.action_proposals
                    if item.get("organ") == organ_id
                ),
                None,
            )
            if not replay_context or historical is None:
                rows.append({
                    "transition_id": transition.transition_id,
                    "status": "insufficient_evidence",
                    "uncertainty_difference": None,
                    "uncertainty_measurement_status": "unmeasured",
                    "uncertainty_reason": "historical_replay_context_or_candidate_missing",
                    "cost_difference": None,
                    "cost_measurement_status": "unmeasured",
                    "cost_reason": "historical_replay_context_or_candidate_missing",
                    "causal_agreement": None,
                    "causal_measurement_status": "unmeasured",
                    "historical_reward": transition.reward.get("reward"),
                    "historical_reward_measurement_status": (
                        "measured" if transition.reward.get("reward") is not None else "unmeasured"
                    ),
                    "evidence_insufficient": True,
                    "contract_errors": ["historical_replay_context_or_candidate_missing"],
                })
                continue
            if historical.get("backend_id") != adapter.reference_id:
                rows.append({
                    "transition_id": transition.transition_id,
                    "status": "incompatible_contract",
                    "uncertainty_difference": None,
                    "uncertainty_measurement_status": "unmeasured",
                    "uncertainty_reason": "backend_identity_mismatch",
                    "cost_difference": None,
                    "cost_measurement_status": "unmeasured",
                    "cost_reason": "backend_identity_mismatch",
                    "causal_agreement": None,
                    "causal_measurement_status": "unmeasured",
                    "historical_reward": transition.reward.get("reward"),
                    "historical_reward_measurement_status": (
                        "measured" if transition.reward.get("reward") is not None else "unmeasured"
                    ),
                    "evidence_insufficient": True,
                    "contract_errors": ["backend_identity_mismatch"],
                })
                continue
            identity = SymbiosisIdentity(
                trace_group_id=transition.trace_group_id,
                organism_id=window.organism_id,
                lineage_id=window.lineage_id,
                run_id=transition.state_after.run_id,
                episode_id=transition.state_after.episode_id,
                scenario_id=str(replay_context.get("scenario_id") or "unknown"),
            )
            request = NeuralInferenceRequest(
                inference_id=f"replay-{transition.transition_id}-{organ_id.lower()}",
                run_id=identity.run_id,
                organ=organ_id,
                capability=adapter.capability,
                payload={"identity": identity.to_dict(), "inputs": replay_context.get("inputs") or {}},
                scope=InferenceScope.LAB,
                resources=ResourceSnapshot.from_mapping(replay_context.get("resources")),
                causal_context=CausalContextView(
                    organism_id=identity.organism_id,
                    episode_id=identity.episode_id,
                    trace_id=identity.trace_group_id,
                ),
            )
            context = {
                "identity": identity,
                "inputs": replay_context.get("inputs") or {},
                "n3_temporal": replay_context.get("n3_temporal") or {},
                "reasoning_state": replay_context.get("reasoning_state") or {},
                "lotf_valid": replay_context.get("lotf_valid"),
                "viability": replay_context.get("viability") or {},
                "reasoning": replay_context.get("reasoning") or {},
            }
            try:
                output = adapter.infer(request, context)
                candidate_hash = canonical_sha256(output.candidate_output)
                replay_input_hash = canonical_sha256(request.payload)
                historical_uncertainty = _finite_number(
                    historical.get("historical_uncertainty")
                )
                uncertainty_difference = (
                    output.uncertainty - historical_uncertainty
                    if historical_uncertainty is not None
                    else None
                )
                cost_difference = _cost_difference(
                    historical.get("historical_cost"), output.cost
                )
                historical_causal = historical.get("historical_causal_comparison")
                causal_agreement = None
                if organ_id == "N4" and isinstance(historical_causal, dict) and isinstance(
                    historical_causal.get("agreement"), bool
                ):
                    causal_agreement = N4Adapter.compare(
                        output.candidate_output, context["reasoning_state"]
                    ).get("agreement")
                diverged = candidate_hash != historical.get("candidate_hash")
                rows.append({
                    "transition_id": transition.transition_id,
                    "status": "diverged" if diverged else "reproduced",
                    "historical_candidate_hash": historical.get("candidate_hash"),
                    "replay_input_hash": replay_input_hash,
                    "replay_candidate_hash": candidate_hash,
                    "proposal_diverged": diverged,
                    "uncertainty_difference": uncertainty_difference,
                    "uncertainty_measurement_status": (
                        "measured" if uncertainty_difference is not None else "unmeasured"
                    ),
                    "uncertainty_reason": (
                        None if uncertainty_difference is not None else "historical_uncertainty_missing"
                    ),
                    "cost_difference": cost_difference or None,
                    "cost_measurement_status": "measured" if cost_difference else "unmeasured",
                    "cost_reason": None if cost_difference else "no_comparable_numeric_cost_metrics",
                    "causal_agreement": causal_agreement,
                    "causal_measurement_status": (
                        "measured" if causal_agreement is not None else "not_applicable" if organ_id != "N4" else "unmeasured"
                    ),
                    "historical_reward": transition.reward.get("reward"),
                    "historical_reward_measurement_status": (
                        "measured" if transition.reward.get("reward") is not None else "unmeasured"
                    ),
                    "contract_errors": [],
                    "regime_compatibility": transition.regime_after.get(
                        "compatibility_with_previous_regime"
                    ),
                    "evidence_insufficient": False,
                    "estimated_impact_only": True,
                })
            except Exception as exc:
                rows.append({
                    "transition_id": transition.transition_id,
                    "status": "incompatible_contract",
                    "uncertainty_difference": None,
                    "uncertainty_measurement_status": "unmeasured",
                    "cost_difference": None,
                    "cost_measurement_status": "unmeasured",
                    "causal_agreement": None,
                    "causal_measurement_status": "unmeasured",
                    "historical_reward": transition.reward.get("reward"),
                    "historical_reward_measurement_status": (
                        "measured" if transition.reward.get("reward") is not None else "unmeasured"
                    ),
                    "evidence_insufficient": True,
                    "contract_errors": [f"{type(exc).__name__}:{exc}"],
                })
        return {
            "schema_version": REPLAY_SCHEMA_VERSION,
            "window_id": window.window_id,
            "adapter": organ_id,
            "authority_effect": "none",
            "writes_performed": False,
            "original_chain_untouched": True,
            "results": rows,
        }


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if number == number and abs(number) != float("inf") else None


def _cost_difference(historical: Any, replay: Any) -> dict[str, float]:
    if not isinstance(historical, dict) or not isinstance(replay, dict):
        return {}
    differences = {}
    for key in sorted(set(historical).intersection(replay)):
        before = _finite_number(historical.get(key))
        after = _finite_number(replay.get(key))
        if before is not None and after is not None:
            differences[key] = after - before
    return differences
