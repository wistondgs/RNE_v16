"""Estado adaptativo longitudinal y planner limitado a obtener evidencia."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from .dynamic_state import canonical_hash
from .life_transition import LifeTransition


ADAPTIVE_STATE_SCHEMA_VERSION = "organ-adaptive-state-v1"
ADAPTATION_PRIORITY_SCHEMA_VERSION = "adaptation-priority-v1"
ALLOWED_ADAPTATION_ACTIONS = frozenset(
    {"collect_more_evidence", "replay_candidate", "hold", "quarantine_candidate"}
)


@dataclass(slots=True)
class OrganAdaptiveState:
    organism_id: str
    lineage_id: str
    regime_id: str
    organ_id: str
    backend_id: str
    participation_count: int = 0
    abstention_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    receipt_abstained_count: int = 0
    observed_count: int = 0
    compared_count: int = 0
    unavailable_count: int = 0
    persistence_degraded_count: int = 0
    delayed_reward_count: int = 0
    delayed_reward_mean: float | None = None
    certificate_outcomes: dict[str, int] = field(default_factory=dict)
    calibration_residual_mean: float | None = None
    causal_disagreement_count: int = 0
    causal_observation_count: int = 0
    latency_mean_ms: float | None = None
    latency_m2: float = 0.0
    latency_tail_ms: tuple[float, ...] = ()
    resource_cost_mean: float | None = None
    fallback_count: int = 0
    regime_dwell_time: int = 0
    change_point_indicators: tuple[str, ...] = ()
    last_update_transition_id: str | None = None
    schema_version: str = ADAPTIVE_STATE_SCHEMA_VERSION

    @property
    def consumer_acceptance_rate(self) -> float | None:
        denominator = self.acceptance_denominator
        return self.accepted_count / denominator if denominator else None

    @property
    def acceptance_denominator(self) -> int:
        return self.accepted_count + self.rejected_count

    @property
    def causal_disagreement_rate(self) -> float | None:
        return (
            self.causal_disagreement_count / self.causal_observation_count
            if self.causal_observation_count
            else None
        )

    @property
    def fallback_rate(self) -> float | None:
        return self.fallback_count / self.participation_count if self.participation_count else None

    @property
    def state_hash(self) -> str:
        return canonical_hash(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "consumer_acceptance_rate": self.consumer_acceptance_rate,
            "acceptance_denominator": self.acceptance_denominator,
            "causal_disagreement_rate": self.causal_disagreement_rate,
            "fallback_rate": self.fallback_rate,
        }


class AdaptiveStateStore:
    def __init__(self, *, organism_id: str, lineage_id: str):
        self.organism_id = organism_id
        self.lineage_id = lineage_id
        self.states: dict[tuple[str, str, str], OrganAdaptiveState] = {}

    def update(self, transition: LifeTransition, symbiosis_trace: Mapping[str, Any]) -> list[OrganAdaptiveState]:
        from runtime.neural.integration.contracts import ConsumerVerdictClass

        if transition.status != "committed":
            return []
        regime_id = str(transition.regime_after.get("regime_id") or "unmapped")
        receipts = list(symbiosis_trace.get("consumer_receipts") or ())
        reward_value = transition.reward.get("reward")
        certificate_verdict = transition.certificate.get("verdict")
        updated = []
        for organ in symbiosis_trace.get("organs") or ():
            organ_id = str(organ.get("organ") or "")
            backend_id = str(
                (symbiosis_trace.get("backend_identities") or {}).get(organ_id)
                or organ.get("capability")
                or "unknown"
            )
            key = (regime_id, organ_id, backend_id)
            state = self.states.setdefault(
                key,
                OrganAdaptiveState(
                    organism_id=self.organism_id,
                    lineage_id=self.lineage_id,
                    regime_id=regime_id,
                    organ_id=organ_id,
                    backend_id=backend_id,
                ),
            )
            state.participation_count += 1
            state.regime_dwell_time += 1
            if organ.get("abstained"):
                state.abstention_count += 1
            organ_receipts = [item for item in receipts if item.get("organ") == organ_id]
            for receipt in organ_receipts:
                try:
                    verdict = ConsumerVerdictClass(str(receipt.get("verdict_class") or "invalid"))
                except ValueError:
                    verdict = ConsumerVerdictClass.INVALID
                if verdict is ConsumerVerdictClass.ACCEPTED:
                    state.accepted_count += 1
                elif verdict in {ConsumerVerdictClass.REJECTED, ConsumerVerdictClass.INVALID}:
                    state.rejected_count += 1
                elif verdict is ConsumerVerdictClass.ABSTAINED:
                    state.receipt_abstained_count += 1
                elif verdict is ConsumerVerdictClass.OBSERVED:
                    state.observed_count += 1
                elif verdict is ConsumerVerdictClass.COMPARED:
                    state.compared_count += 1
                elif verdict is ConsumerVerdictClass.UNAVAILABLE:
                    state.unavailable_count += 1
                elif verdict is ConsumerVerdictClass.PERSISTENCE_DEGRADED:
                    state.persistence_degraded_count += 1
                if not bool(receipt.get("persisted")) and bool(
                    symbiosis_trace.get("persistence_degraded")
                ):
                    state.persistence_degraded_count += 1
            if reward_value is not None:
                reward = float(reward_value)
                state.delayed_reward_count += 1
                state.delayed_reward_mean = _online_mean(
                    state.delayed_reward_mean, reward, state.delayed_reward_count
                )
            if certificate_verdict is not None:
                label = str(certificate_verdict)
                state.certificate_outcomes[label] = state.certificate_outcomes.get(label, 0) + 1
            comparison = (organ.get("candidate") or {}).get("canonical_comparison") or {}
            if organ_id == "N4" and comparison:
                state.causal_observation_count += 1
                if comparison.get("agreement") is False:
                    state.causal_disagreement_count += 1
            latency = organ.get("latency")
            if latency is not None:
                value = float(latency)
                count = state.participation_count
                previous = state.latency_mean_ms
                state.latency_mean_ms = _online_mean(previous, value, count)
                if previous is not None:
                    state.latency_m2 += (value - previous) * (value - state.latency_mean_ms)
                state.latency_tail_ms = tuple(sorted((*state.latency_tail_ms, value))[-32:])
            ram = organ.get("RAM")
            if ram is not None:
                state.resource_cost_mean = _ema(state.resource_cost_mean, float(ram))
            if organ.get("fallback_reason"):
                state.fallback_count += 1
            indicators = []
            if state.causal_disagreement_rate is not None and state.causal_disagreement_rate > 0.5:
                indicators.append("causal_disagreement_shift")
            if state.fallback_rate is not None and state.fallback_rate > 0.5:
                indicators.append("fallback_shift")
            state.change_point_indicators = tuple(indicators)
            state.last_update_transition_id = transition.transition_id
            updated.append(state)
        return updated

    @property
    def state_hash(self) -> str | None:
        return canonical_hash(self.export_checkpoint()) if self.states else None

    def export_checkpoint(self) -> dict[str, Any]:
        return {
            "schema_version": "organ-adaptive-state-checkpoint-v1",
            "organism_id": self.organism_id,
            "lineage_id": self.lineage_id,
            "states": [state.to_dict() for _, state in sorted(self.states.items())],
        }

    def restore_checkpoint(self, raw: Mapping[str, Any] | None) -> int:
        data = dict(raw or {})
        if data.get("schema_version") != "organ-adaptive-state-checkpoint-v1":
            return 0
        if str(data.get("organism_id")) != self.organism_id:
            raise ValueError("adaptive_checkpoint_organism_mismatch")
        if str(data.get("lineage_id")) != self.lineage_id:
            raise ValueError("adaptive_checkpoint_lineage_mismatch")
        self.states.clear()
        for raw_state in data.get("states") or ():
            known = {
                name: raw_state[name]
                for name in OrganAdaptiveState.__dataclass_fields__
                if name in raw_state and name not in {"schema_version"}
            }
            known["latency_tail_ms"] = tuple(known.get("latency_tail_ms") or ())
            known["change_point_indicators"] = tuple(known.get("change_point_indicators") or ())
            if "accepted_count" not in known and "accepted_receipts" in raw_state:
                # El checkpoint legado usó heurística textual optimista: no se hereda
                # como aceptación verificable.
                known["accepted_count"] = 0
                known["observed_count"] = int(raw_state.get("observed_receipts", 0) or 0)
            state = OrganAdaptiveState(**known)
            self.states[(state.regime_id, state.organ_id, state.backend_id)] = state
        return len(self.states)


class AdaptationPlanner:
    def plan(self, states: list[OrganAdaptiveState]) -> list[dict[str, Any]]:
        plans = []
        for state in states:
            action = "hold"
            blocker = None
            reasons = []
            required = max(0, 3 - state.participation_count)
            if state.causal_disagreement_rate is not None and state.causal_disagreement_rate > 0.5:
                action, blocker = "quarantine_candidate", "causal_disagreement_rate"
                reasons.append("canonical causal disagreement exceeds shadow tolerance")
            elif state.fallback_rate is not None and state.fallback_rate > 0.5:
                action, blocker = "replay_candidate", "fallback_rate"
                reasons.append("fallback dominates observations")
            elif required:
                action = "collect_more_evidence"
                reasons.append("longitudinal sample is insufficient")
            plan = {
                "schema_version": ADAPTATION_PRIORITY_SCHEMA_VERSION,
                "organism_id": state.organism_id,
                "lineage_id": state.lineage_id,
                "organ_id": state.organ_id,
                "regime_id": state.regime_id,
                "backend_id": state.backend_id,
                "reason": reasons or ["bounded evidence is currently stable"],
                "confidence": min(1.0, state.participation_count / 10.0),
                "required_observations": required,
                "blocker": blocker,
                "allowed_action": action,
            }
            if plan["allowed_action"] not in ALLOWED_ADAPTATION_ACTIONS:
                raise RuntimeError("adaptation_planner_forbidden_action")
            plans.append(plan)
        return plans


def _online_mean(previous: float | None, value: float, count: int) -> float:
    return value if previous is None else previous + (value - previous) / max(1, count)


def _ema(previous: float | None, value: float, alpha: float = 0.2) -> float:
    return value if previous is None else alpha * value + (1.0 - alpha) * previous
