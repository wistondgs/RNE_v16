"""Authority-preserving adapter from EA1 theories to historical MCI models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from runtime.symbolic.mci import MCIRuntime, NeuralHypothesis, TransitionCompiler, TransitionSpec
from runtime.symbolic.mci.contracts import ActionSpec, EffectSpec, EquationSpec, VariableSpec

from .canonical import digest, stable_id
from .contracts import (
    ContractError,
    DivergentPrediction,
    DivergentPredictionSet,
    HypothesisCandidate,
    OrdinalState,
    PredictionMode,
    PublicAction,
    TheoryState,
)


PREDICTOR_ID = "ea1-mci-transition-compiler-v1"


@dataclass(slots=True)
class MCIWorkingHypothesis:
    candidate: HypothesisCandidate
    runtime: MCIRuntime
    official_weight: float
    unavailable_action_ids: tuple[str, ...] = ()

    @property
    def spec(self) -> TransitionSpec:
        return self.runtime.learner.active_spec


@dataclass(slots=True)
class MCIWorkingSet:
    theory_state_id: str
    theory_state_version: int
    theory_state_hash: str
    hypotheses: tuple[MCIWorkingHypothesis, ...]
    unknown_weight: float

    def rebind(self, theory: TheoryState) -> None:
        weights = {
            theory.rival_hypothesis_ids[0]: theory.posterior_h1,
            theory.rival_hypothesis_ids[1]: theory.posterior_h2,
        }
        if set(weights) != {item.candidate.hypothesis_id for item in self.hypotheses}:
            raise ContractError("mci_rebind_rival_mismatch")
        for item in self.hypotheses:
            item.official_weight = weights[item.candidate.hypothesis_id]
        self.theory_state_id = theory.state_id
        self.theory_state_version = theory.version
        self.theory_state_hash = digest(theory)
        self.unknown_weight = theory.posterior_unknown
        self.assert_consistent(theory)

    def assert_consistent(self, theory: TheoryState) -> None:
        expected = {
            theory.rival_hypothesis_ids[0]: theory.posterior_h1,
            theory.rival_hypothesis_ids[1]: theory.posterior_h2,
        }
        actual = {item.candidate.hypothesis_id: item.official_weight for item in self.hypotheses}
        if (
            theory.state_id != self.theory_state_id
            or theory.version != self.theory_state_version
            or digest(theory) != self.theory_state_hash
            or actual != expected
            or self.unknown_weight != theory.posterior_unknown
        ):
            raise ContractError("ea1_mci_authority_disagreement")

    def snapshot(self) -> dict[str, Any]:
        return {
            "theory_state_id": self.theory_state_id,
            "theory_state_version": self.theory_state_version,
            "theory_state_hash": self.theory_state_hash,
            "unknown_weight": self.unknown_weight,
            "hypotheses": tuple(
                {
                    "hypothesis_id": item.candidate.hypothesis_id,
                    "structural_class": item.candidate.structural_class,
                    "model_spec_hash": item.spec.sha256,
                    "model_spec_version": item.spec.version,
                    "official_weight": item.official_weight,
                    "overlay": (
                        item.runtime.learner.active_overlay.to_dict()
                        if item.runtime.learner.active_overlay is not None
                        else None
                    ),
                    "hypothesis_ledger": item.runtime.learner.hypothesis_ledger.snapshot(),
                }
                for item in self.hypotheses
            ),
        }


class MCITheoryAdapter:
    """Builds a derived MCI working set; EA1 TheoryState remains authoritative."""

    def adapt(
        self,
        theory: TheoryState,
        hypotheses: tuple[HypothesisCandidate, ...],
        actions: tuple[PublicAction, ...],
    ) -> MCIWorkingSet:
        if len(hypotheses) != 2 or len({item.hypothesis_id for item in hypotheses}) != 2:
            raise ContractError("mci_requires_exactly_two_supplied_rivals")
        supplied = {item.hypothesis_id: item for item in hypotheses}
        if set(supplied) != set(theory.rival_hypothesis_ids):
            raise ContractError("theory_and_mci_rival_identity_mismatch")
        action_ids = {action.action_id for action in actions}
        if len(actions) != 6 or len(action_ids) != 6:
            raise ContractError("mci_requires_six_action_substrate")
        weights = {
            theory.rival_hypothesis_ids[0]: theory.posterior_h1,
            theory.rival_hypothesis_ids[1]: theory.posterior_h2,
        }
        working: list[MCIWorkingHypothesis] = []
        for hypothesis_id in theory.rival_hypothesis_ids:
            candidate = supplied[hypothesis_id]
            probabilities = dict(candidate.intervention_probabilities or {})
            if not probabilities or not set(probabilities) <= action_ids:
                raise ContractError("invalid_public_intervention_model")
            available_actions = tuple(
                action for action in actions if action.action_id in probabilities
            )
            spec = self._compile_spec(candidate, available_actions, probabilities)
            runtime = MCIRuntime(spec)
            runtime.learner.hypothesis_ledger.submit(
                NeuralHypothesis(
                    hypothesis_id=candidate.hypothesis_id,
                    kind="regime",
                    target_id=candidate.structural_class,
                    expression=None,
                    proposed_value=None,
                    confidence=weights[hypothesis_id],
                    evidence_refs=(),
                    provider="ea1-mci-theory-adapter-v1",
                    model_ref=spec.sha256,
                    logical_time=theory.logical_time,
                )
            )
            working.append(
                MCIWorkingHypothesis(
                    candidate,
                    runtime,
                    weights[hypothesis_id],
                    tuple(sorted(action_ids - set(probabilities))),
                )
            )
        result = MCIWorkingSet(
            theory.state_id,
            theory.version,
            digest(theory),
            tuple(working),
            theory.posterior_unknown,
        )
        result.assert_consistent(theory)
        return result

    def restore(
        self,
        theory: TheoryState,
        hypotheses: tuple[HypothesisCandidate, ...],
        actions: tuple[PublicAction, ...],
        snapshot: Mapping[str, Any],
    ) -> MCIWorkingSet:
        working = self.adapt(theory, hypotheses, actions)
        if (
            str(snapshot.get("theory_state_id")) != theory.state_id
            or int(snapshot.get("theory_state_version", -1)) != theory.version
            or str(snapshot.get("theory_state_hash")) != digest(theory)
        ):
            raise ContractError("mci_snapshot_theory_mismatch")
        rows = snapshot.get("hypotheses")
        if not isinstance(rows, (tuple, list)):
            raise ContractError("mci_snapshot_hypotheses_required")
        by_id = {
            str(row["hypothesis_id"]): row
            for row in rows
            if isinstance(row, Mapping)
        }
        if set(by_id) != {item.candidate.hypothesis_id for item in working.hypotheses}:
            raise ContractError("mci_snapshot_rival_mismatch")
        for item in working.hypotheses:
            row = by_id[item.candidate.hypothesis_id]
            if str(row["structural_class"]) != item.candidate.structural_class:
                raise ContractError("mci_snapshot_structure_mismatch")
            overlay = row.get("overlay")
            if overlay is not None:
                if not isinstance(overlay, Mapping):
                    raise ContractError("mci_snapshot_overlay_invalid")
                item.runtime.restore_overlay(overlay)
            ledger = row.get("hypothesis_ledger")
            if not isinstance(ledger, (tuple, list)):
                raise ContractError("mci_snapshot_ledger_invalid")
            item.runtime.restore_hypothesis_ledger(tuple(ledger))
            if item.spec.sha256 != str(row["model_spec_hash"]):
                raise ContractError("mci_snapshot_effective_model_mismatch")
        return working

    @staticmethod
    def _compile_spec(
        candidate: HypothesisCandidate,
        actions: tuple[PublicAction, ...],
        probabilities: Mapping[str, float],
    ) -> TransitionSpec:
        ordered = sorted(actions, key=lambda item: item.action_id)
        parameters: dict[str, float] = {"decision_threshold": 0.5}
        effects: list[EffectSpec] = []
        action_specs: list[ActionSpec] = []
        for index, action in enumerate(ordered):
            parameter = f"outcome_probability_{index}"
            parameters[parameter] = float(probabilities[action.action_id])
            action_specs.append(ActionSpec(action.action_id, {}))
            effects.append(
                EffectSpec(
                    stable_id(
                        "mci-effect",
                        {"hypothesis_id": candidate.hypothesis_id, "action_id": action.action_id},
                    ),
                    action.action_id,
                    1.0,
                    parameter,
                )
            )
        return TransitionSpec(
            spec_id=stable_id("mci-spec", candidate.to_payload()),
            version=candidate.model_version,
            scenario="ea1_public_rival_model",
            variables=(VariableSpec("outcome_probability", "real"), VariableSpec("alarm", "bool")),
            parameters=parameters,
            actions=tuple(action_specs),
            equations=(EquationSpec("outcome_probability", (), tuple(effects)),),
            alarm_variable="alarm",
            alarm_source="outcome_probability",
            alarm_operator=">=",
            alarm_threshold_parameter="decision_threshold",
            main_variable="outcome_probability",
            optimization_direction="maximize",
            safe_action=ordered[0].action_id,
            invariants=(),
        )


class MCIPredictionAdapter:
    def predict(
        self,
        working: MCIWorkingSet,
        theory: TheoryState,
        actions: tuple[PublicAction, ...],
        *,
        public_state: Mapping[str, Any],
        horizon: int,
        logical_time: int,
    ) -> DivergentPredictionSet:
        working.assert_consistent(theory)
        probabilities: dict[tuple[str, str], float] = {}
        unavailable: list[tuple[str, str]] = []
        for item in working.hypotheses:
            for action in sorted(actions, key=lambda value: value.action_id):
                if action.action_id in item.unavailable_action_ids:
                    unavailable.append((item.candidate.hypothesis_id, action.action_id))
                    continue
                outcome = TransitionCompiler(item.runtime.learner.active_spec).execute(
                    {"outcome_probability": 0.0, "alarm": False},
                    action=action.action_id,
                    external_input=0.0,
                )
                probabilities[(item.candidate.hypothesis_id, action.action_id)] = float(
                    outcome["outcome_probability"]
                )
        predictions: list[DivergentPrediction] = []
        for action in sorted(actions, key=lambda value: value.action_id):
            cells = [
                (item, probabilities[(item.candidate.hypothesis_id, action.action_id)])
                for item in working.hypotheses
                if (item.candidate.hypothesis_id, action.action_id) in probabilities
            ]
            if not cells:
                continue
            low, high = min(value for _, value in cells), max(value for _, value in cells)
            for item, probability in cells:
                state = (
                    OrdinalState.MID
                    if low == high
                    else OrdinalState.LOW
                    if probability == low
                    else OrdinalState.HIGH
                )
                overlay = item.runtime.learner.active_overlay
                predictions.append(
                    DivergentPrediction(
                        item.candidate.hypothesis_id,
                        action.action_id,
                        PredictionMode.INTERVENTIONAL,
                        state,
                        horizon,
                        predictor_provenance="mci_transition_spec_compiler",
                        success_probability=probability,
                        model_spec_version=item.spec.version,
                        model_spec_hash=item.spec.sha256,
                        overlay_id=overlay.overlay_id if overlay else None,
                        predictor_identity=PREDICTOR_ID,
                        theory_state_version=theory.version,
                        logical_time=logical_time,
                    )
                )
        payload = {
            "theory_state_id": theory.state_id,
            "public_state_hash": digest(public_state),
            "predictions": tuple(item.to_payload() for item in predictions),
        }
        return DivergentPredictionSet(
            stable_id("mci-predictions", payload),
            tuple(predictions),
            theory.state_id,
            digest(public_state),
            tuple(sorted(unavailable)),
        )


class MCIStateRestorer:
    """Rebuilds the official EA1 state and its derived MCI state from the EA1 ledger."""

    def __init__(self, theory_adapter: MCITheoryAdapter | None = None) -> None:
        self.theory_adapter = theory_adapter or MCITheoryAdapter()

    def restore(
        self,
        ledger: Any,
        run_id: str,
        hypotheses: tuple[HypothesisCandidate, ...],
        actions: tuple[PublicAction, ...],
    ) -> tuple[TheoryState, MCIWorkingSet]:
        entries = ledger.entries(run_id)
        revisions = [entry for entry in entries if entry.kind == "revision"]
        memories = [entry for entry in entries if entry.kind == "experiment_memory"]
        if not revisions or not memories:
            raise ContractError("mci_reload_requires_revision_and_memory")
        raw = revisions[-1].payload.get("theory_after")
        if not isinstance(raw, Mapping):
            raise ContractError("mci_reload_theory_payload_invalid")
        theory = TheoryState(
            state_id=str(raw["state_id"]),
            epoch=int(raw["epoch"]),
            posterior_h1=float(raw["posterior_h1"]),
            posterior_h2=float(raw["posterior_h2"]),
            posterior_unknown=float(raw["posterior_unknown"]),
            preferred_hypothesis_id=str(raw["preferred_hypothesis_id"]),
            evidence_ids=tuple(raw.get("evidence_ids") or ()),
            rival_hypothesis_ids=tuple(raw.get("rival_hypothesis_ids") or ()),
            ordinal_state=OrdinalState(str(raw["ordinal_state"])),
            predecessor_state_id=(
                str(raw["predecessor_state_id"])
                if raw.get("predecessor_state_id") is not None
                else None
            ),
            version=int(raw["version"]),
            logical_time=int(raw["logical_time"]),
        )
        content = memories[-1].payload.get("content")
        snapshot = content.get("mci_snapshot") if isinstance(content, Mapping) else None
        if not isinstance(snapshot, Mapping):
            raise ContractError("mci_reload_snapshot_missing")
        return theory, self.theory_adapter.restore(theory, hypotheses, actions, snapshot)
