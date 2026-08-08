"""Frozen EA1-C MCI value-of-information policy."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .canonical import digest, stable_id
from .contracts import (
    DivergentPredictionSet,
    ExperimentProposal,
    Producer,
    PublicAction,
    TheoryState,
    artifact_hash,
)


LAMBDA_DECISION = 0.5
LAMBDA_RISK = 2.0
MIN_SAFE_EIG_NATS = 0.05
POLICY_ID = "ea1-c3-mci-voi-v1"
DECISION_DESIGN_ID = "DECISION_DESIGN_DISTRIBUTION_V1"


@dataclass(frozen=True, slots=True)
class VOITerms:
    expected_information_gain: float
    expected_decision_value: float
    cost: float
    risk: float
    denominator: float
    final_score: float

    def as_pairs(self) -> tuple[tuple[str, float], ...]:
        return (
            ("expected_information_gain", self.expected_information_gain),
            ("expected_decision_value", self.expected_decision_value),
            ("lambda_decision", LAMBDA_DECISION),
            ("cost", self.cost),
            ("risk", self.risk),
            ("lambda_risk", LAMBDA_RISK),
            ("denominator", self.denominator),
            ("final_score", self.final_score),
        )


@dataclass(frozen=True, slots=True)
class MCISelectionDecision:
    selected: ExperimentProposal | None
    considered: tuple[ExperimentProposal, ...]
    canonical_hash_order: tuple[str, ...]
    tie_break_result: str
    abstention_reason: str = ""


def _entropy(weights: tuple[float, ...]) -> float:
    return -sum(value * math.log(value) for value in weights if value > 0.0)


def _weights(theory: TheoryState) -> tuple[float, float, float]:
    return theory.posterior_h1, theory.posterior_h2, theory.posterior_unknown


def _posterior(
    weights: tuple[float, float, float],
    likelihoods: tuple[float, float, float],
    outcome: int,
) -> tuple[float, float, float]:
    masses = tuple(
        weight * max(probability if outcome else 1.0 - probability, 1e-12)
        for weight, probability in zip(weights, likelihoods, strict=True)
    )
    total = sum(masses)
    return tuple(value / total for value in masses)  # type: ignore[return-value]


def _decision_design_value(weights: tuple[float, float, float]) -> float:
    """Expected value over two class roles and two recovery roles, all equiprobable."""

    h1, h2, unknown = weights
    class_role = max(h1 + 0.5 * unknown, h2 + 0.5 * unknown, 0.60)
    recovery_role = 1.0
    return 0.5 * class_role + 0.5 * recovery_role


class MCI_VOI_Policy:
    """Uses only current public theory and model-based prediction probabilities."""

    policy_id = POLICY_ID

    def score(
        self,
        theory: TheoryState,
        prediction_set: DivergentPredictionSet,
        action: PublicAction,
    ) -> VOITerms:
        if prediction_set.theory_state_id != theory.state_id:
            raise ValueError("prediction_theory_state_mismatch")
        by_hypothesis = {
            item.hypothesis_id: item
            for item in prediction_set.predictions
            if item.action_id == action.action_id
        }
        if set(by_hypothesis) != set(theory.rival_hypothesis_ids):
            return VOITerms(0.0, 0.0, float(action.cost), action.risk, 1.0 + action.cost + LAMBDA_RISK * action.risk, 0.0)
        probabilities = tuple(
            by_hypothesis[hypothesis_id].success_probability
            for hypothesis_id in theory.rival_hypothesis_ids
        )
        if any(value is None for value in probabilities):
            return VOITerms(0.0, 0.0, float(action.cost), action.risk, 1.0 + action.cost + LAMBDA_RISK * action.risk, 0.0)
        likelihoods = (float(probabilities[0]), float(probabilities[1]), 0.5)
        weights = _weights(theory)
        probability_one = sum(
            weight * probability
            for weight, probability in zip(weights, likelihoods, strict=True)
        )
        posterior_one = _posterior(weights, likelihoods, 1)
        posterior_zero = _posterior(weights, likelihoods, 0)
        expected_entropy = (
            probability_one * _entropy(posterior_one)
            + (1.0 - probability_one) * _entropy(posterior_zero)
        )
        eig = max(0.0, _entropy(weights) - expected_entropy)
        current_value = _decision_design_value(weights)
        expected_value = (
            probability_one * _decision_design_value(posterior_one)
            + (1.0 - probability_one) * _decision_design_value(posterior_zero)
        )
        edv = max(0.0, expected_value - current_value)
        denominator = 1.0 + float(action.cost) + LAMBDA_RISK * action.risk
        score = (eig + LAMBDA_DECISION * edv) / denominator
        return VOITerms(eig, edv, float(action.cost), action.risk, denominator, score)

    def proposals(
        self,
        theory: TheoryState,
        prediction_set: DivergentPredictionSet,
        actions: tuple[PublicAction, ...],
        *,
        epoch: int,
    ) -> tuple[ExperimentProposal, ...]:
        proposals: list[ExperimentProposal] = []
        for action in actions:
            terms = self.score(theory, prediction_set, action)
            cells = {
                item.hypothesis_id: item.success_probability
                for item in prediction_set.predictions
                if item.action_id == action.action_id
            }
            available = all(cells.get(item) is not None for item in theory.rival_hypothesis_ids)
            discrimination = (
                abs(float(cells[theory.rival_hypothesis_ids[0]]) - float(cells[theory.rival_hypothesis_ids[1]]))
                if available
                else 0.0
            )
            identity = {
                "policy_id": POLICY_ID,
                "theory_state_id": theory.state_id,
                "prediction_set_id": prediction_set.prediction_set_id,
                "action_id": action.action_id,
                "epoch": epoch,
                "voi_terms": terms.as_pairs(),
            }
            proposals.append(
                ExperimentProposal(
                    stable_id("mci-proposal", identity),
                    epoch,
                    action.action_id,
                    prediction_set.prediction_set_id,
                    terms.expected_information_gain,
                    0.0,
                    Producer.MCI,
                    hypotheses_discriminated=theory.rival_hypothesis_ids,
                    discrimination_estimate=discrimination,
                    cost=action.cost,
                    risk=action.risk,
                    reversible=action.reversible,
                    required_state="available",
                    expected_decision_value=terms.expected_decision_value,
                    voi_score=terms.final_score,
                    voi_terms=terms.as_pairs(),
                    admissibility_status="admissible" if available else "unavailable",
                    admissibility_reasons=() if available else ("prediction_unavailable",),
                )
            )
        return tuple(proposals)

    def select(
        self,
        theory: TheoryState,
        proposals: tuple[ExperimentProposal, ...],
        *,
        governance: tuple[tuple[str, str], ...] = (),
    ) -> MCISelectionDecision:
        statuses = dict(governance)
        non_refuted = sum(
            statuses.get(hypothesis_id, "active") != "refuted"
            for hypothesis_id in theory.rival_hypothesis_ids
        )
        admissible = tuple(item for item in proposals if item.admissibility_status == "admissible")
        canonical = tuple(sorted(admissible, key=artifact_hash))
        hash_order = tuple(artifact_hash(item) for item in canonical)
        if non_refuted < 2:
            return MCISelectionDecision(None, proposals, hash_order, "abstain", "fewer_than_two_non_refuted_rivals")
        if theory.posterior_unknown >= 0.25:
            return MCISelectionDecision(None, proposals, hash_order, "abstain", "unknown_mass_threshold")
        informative = tuple(
            item for item in canonical if item.expected_information_gain >= MIN_SAFE_EIG_NATS
        )
        if not informative:
            return MCISelectionDecision(None, proposals, hash_order, "abstain", "no_safe_proposal_meets_eig_threshold")
        best_score = max(float(item.voi_score or 0.0) for item in informative)
        tied = tuple(
            item
            for item in informative
            if math.isclose(float(item.voi_score or 0.0), best_score, rel_tol=0.0, abs_tol=1e-15)
        )
        selected = min(tied, key=artifact_hash)
        tie_result = (
            f"canonical_hash:{artifact_hash(selected)}"
            if len(tied) > 1
            else f"unique_score:{digest(selected.to_payload())}"
        )
        return MCISelectionDecision(selected, proposals, hash_order, tie_result)
