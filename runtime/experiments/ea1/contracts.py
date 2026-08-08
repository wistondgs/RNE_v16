from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from .canonical import digest, stable_id


def frozen_map(value: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
    return MappingProxyType(dict(value or {}))


class ContractError(ValueError):
    pass


class Producer(str, Enum):
    ORGANISM = "organism"
    CONTROL = "control"


class PredictionMode(str, Enum):
    OBSERVATIONAL = "observational"
    INTERVENTIONAL = "interventional"


class OrdinalState(str, Enum):
    LOW = "low"
    MID = "mid"
    HIGH = "high"


class Arm(str, Enum):
    EXPERIMENTAL = "experimental"
    C0_PASSIVE = "c0_passive"
    C1_GREEDY = "c1_greedy"
    C2_RANDOM = "c2_random"
    C5_ORACLE = "c5_oracle"


class ScenarioFamily(str, Enum):
    S1 = "s1"
    S2 = "s2"
    S3 = "s3"
    S4 = "s4"
    S5 = "s5"


class AcquisitionStatus(str, Enum):
    CANDIDATE_SEALED = "candidate_sealed"
    VALID = "valid"
    INVALID = "invalid"
    INCOMPLETE = "incomplete"


class CensorReason(str, Enum):
    NONE = "none"
    CRASH = "crash"
    ZERO_EVALUATIONS = "zero_evaluations"
    MISSING_OUTCOME = "missing_outcome"
    PROTOCOL_BREACH = "protocol_breach"
    MISSING_REQUIRED_DATA = "missing_required_data"
    MISSING_REQUIRED_PROBE = "missing_required_probe"
    EXHAUSTED_BUDGET = "exhausted_budget"
    INCOMPLETE_PERSISTENCE = "incomplete_persistence"
    MISSING_F1A_OUTCOME = "missing_f1a_outcome"


@dataclass(frozen=True, slots=True)
class HypothesisCandidate:
    hypothesis_id: str
    structural_class: str
    executable_description: str
    provenance: str
    prior: float = 0.49
    producer: Producer = Producer.ORGANISM
    proposition: str = ""
    scope: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    predicted_effects: tuple[str, ...] = ()
    refutation_condition: str = ""

    def __post_init__(self) -> None:
        if not self.hypothesis_id or not self.structural_class or not self.executable_description:
            raise ContractError("hypothesis_identity_required")
        if not 0.0 <= self.prior <= 1.0:
            raise ContractError("invalid_prior")

    def to_payload(self) -> dict[str, Any]:
        return {"hypothesis_id": self.hypothesis_id, "structural_class": self.structural_class, "executable_description": self.executable_description, "provenance": self.provenance, "prior": self.prior, "producer": self.producer, "proposition": self.proposition, "scope": self.scope, "assumptions": self.assumptions, "predicted_effects": self.predicted_effects, "refutation_condition": self.refutation_condition}


@dataclass(frozen=True, slots=True)
class TheoryState:
    state_id: str
    epoch: int
    posterior_h1: float
    posterior_h2: float
    posterior_unknown: float
    preferred_hypothesis_id: str
    evidence_ids: tuple[str, ...] = ()
    rival_hypothesis_ids: tuple[str, ...] = ("h1", "h2")
    ordinal_state: OrdinalState = OrdinalState.MID
    predecessor_state_id: str | None = None
    version: int = 1
    logical_time: int = 0

    def __post_init__(self) -> None:
        values = (self.posterior_h1, self.posterior_h2, self.posterior_unknown)
        if self.epoch < 0 or self.version < 1 or self.logical_time < 0 or len(set(self.rival_hypothesis_ids)) < 2 or any(not 0.0 <= x <= 1.0 for x in values) or abs(sum(values) - 1.0) > 1e-9:
            raise ContractError("invalid_theory_distribution")

    @property
    def preferred_posterior(self) -> float:
        return max(self.posterior_h1, self.posterior_h2)

    @property
    def rival_odds(self) -> float:
        lo = min(self.posterior_h1, self.posterior_h2)
        return float("inf") if lo == 0.0 else max(self.posterior_h1, self.posterior_h2) / lo

    def to_payload(self) -> dict[str, Any]:
        return {"state_id": self.state_id, "epoch": self.epoch, "posterior_h1": self.posterior_h1, "posterior_h2": self.posterior_h2, "posterior_unknown": self.posterior_unknown, "preferred_hypothesis_id": self.preferred_hypothesis_id, "evidence_ids": self.evidence_ids, "rival_hypothesis_ids": self.rival_hypothesis_ids, "ordinal_state": self.ordinal_state, "predecessor_state_id": self.predecessor_state_id, "version": self.version, "logical_time": self.logical_time}


@dataclass(frozen=True, slots=True)
class DivergentPrediction:
    hypothesis_id: str
    action_id: str
    mode: PredictionMode
    predicted_state: OrdinalState
    horizon: int
    predictor_provenance: str = "preregistered"

    def to_payload(self) -> dict[str, Any]:
        return {"hypothesis_id": self.hypothesis_id, "action_id": self.action_id, "mode": self.mode, "predicted_state": self.predicted_state, "horizon": self.horizon, "predictor_provenance": self.predictor_provenance}


@dataclass(frozen=True, slots=True)
class DivergentPredictionSet:
    prediction_set_id: str
    predictions: tuple[DivergentPrediction, ...]

    def __post_init__(self) -> None:
        if len(self.predictions) < 2 or len({p.predicted_state for p in self.predictions}) < 2:
            raise ContractError("predictions_must_diverge")

    def to_payload(self) -> dict[str, Any]:
        return {"prediction_set_id": self.prediction_set_id, "predictions": self.predictions}


@dataclass(frozen=True, slots=True)
class PublicAction:
    action_id: str
    label: str
    parameters: Mapping[str, Any]
    cost: int = 1
    risk: float = 0.25
    reversible: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", frozen_map(self.parameters))
        if self.cost != 1 or self.risk != 0.25 or not self.reversible:
            raise ContractError("ea1_action_constraints_violated")

    def to_payload(self) -> dict[str, Any]:
        return {"action_id": self.action_id, "label": self.label, "parameters": self.parameters, "cost": self.cost, "risk": self.risk, "reversible": self.reversible}


@dataclass(frozen=True, slots=True)
class ExperimentProposal:
    proposal_id: str
    epoch: int
    action_id: str
    prediction_set_id: str
    expected_information_gain: float
    immediate_reward: float
    producer: Producer
    comparator_action_id: str = "passive"
    hypotheses_discriminated: tuple[str, ...] = ("h1", "h2")
    discrimination_estimate: float = 0.0
    cost: int = 1
    risk: float = 0.25
    reversible: bool = True
    required_state: str = "available"

    def __post_init__(self) -> None:
        if self.cost != 1 or self.risk != 0.25 or not self.reversible or len(set(self.hypotheses_discriminated)) < 2:
            raise ContractError("invalid_ea1_proposal_envelope")

    def to_payload(self) -> dict[str, Any]:
        return {"proposal_id": self.proposal_id, "epoch": self.epoch, "action_id": self.action_id, "prediction_set_id": self.prediction_set_id, "expected_information_gain": self.expected_information_gain, "immediate_reward": self.immediate_reward, "producer": self.producer, "comparator_action_id": self.comparator_action_id, "hypotheses_discriminated": self.hypotheses_discriminated, "discrimination_estimate": self.discrimination_estimate, "cost": self.cost, "risk": self.risk, "reversible": self.reversible, "required_state": self.required_state}


@dataclass(frozen=True, slots=True)
class BudgetSnapshot:
    epoch: int
    tokens_used: int
    cost_used: int
    risk_used: float
    max_epochs: int = 4
    max_tokens: int = 4
    max_cost: int = 4
    max_risk: float = 1.0

    def to_payload(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in ("epoch", "tokens_used", "cost_used", "risk_used", "max_epochs", "max_tokens", "max_cost", "max_risk")}


@dataclass(frozen=True, slots=True)
class ExperimentSelectionReceipt:
    receipt_id: str
    run_id: str
    arm: Arm
    epoch: int
    proposal_id: str
    action_id: str
    selector: str
    random_seed: int | None
    random_draw_index: int | None
    budget_before: BudgetSnapshot
    budget_after: BudgetSnapshot
    proposal_set_hash: str
    block_id: str = "block-unknown"
    scenario_family: ScenarioFamily = ScenarioFamily.S1
    candidate_proposal_ids: tuple[str, ...] = ()
    scores_available: tuple[tuple[str, float], ...] = ()
    logical_time: int = 0

    @property
    def receipt_hash(self) -> str:
        return digest(self._unsigned_payload())

    def _unsigned_payload(self) -> dict[str, Any]:
        return {"receipt_id": self.receipt_id, "run_id": self.run_id, "arm": self.arm, "epoch": self.epoch, "proposal_id": self.proposal_id, "action_id": self.action_id, "selector": self.selector, "random_seed": self.random_seed, "random_draw_index": self.random_draw_index, "budget_before": self.budget_before, "budget_after": self.budget_after, "proposal_set_hash": self.proposal_set_hash, "block_id": self.block_id, "scenario_family": self.scenario_family, "candidate_proposal_ids": self.candidate_proposal_ids, "scores_available": self.scores_available, "logical_time": self.logical_time}

    def to_payload(self) -> dict[str, Any]:
        return {**self._unsigned_payload(), "tokens_before": self.budget_before.tokens_used, "tokens_consumed": self.budget_after.tokens_used - self.budget_before.tokens_used, "tokens_after": self.budget_after.tokens_used, "tokens_remaining": self.budget_after.max_tokens - self.budget_after.tokens_used, "receipt_hash": self.receipt_hash}


@dataclass(frozen=True, slots=True)
class CanonicalOutcomeReference:
    reference_id: str
    selection_receipt_id: str
    source_event_type: str
    source_record_id: str
    witness_id: str
    committed_intervention: str
    outcome_hash: str

    def to_payload(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in ("reference_id", "selection_receipt_id", "source_event_type", "source_record_id", "witness_id", "committed_intervention", "outcome_hash")}


@dataclass(frozen=True, slots=True)
class BeliefRevision:
    revision_id: str
    epoch: int
    theory_before_id: str
    theory_after: TheoryState
    outcome_reference_id: str
    rationale: str
    likelihood_support: tuple[tuple[str, float], ...] = ()
    posterior_weights: tuple[tuple[str, float], ...] = ()
    ordinal_transitions: tuple[tuple[str, str], ...] = ()
    retracted_hypothesis_ids: tuple[str, ...] = ()
    unresolved_hypothesis_ids: tuple[str, ...] = ()
    provenance: str = "canonical_f1a_evidence"

    def to_payload(self) -> dict[str, Any]:
        return {"revision_id": self.revision_id, "epoch": self.epoch, "theory_before_id": self.theory_before_id, "theory_after": self.theory_after, "outcome_reference_id": self.outcome_reference_id, "rationale": self.rationale, "likelihood_support": self.likelihood_support, "posterior_weights": self.posterior_weights, "unknown_mass": self.theory_after.posterior_unknown, "ordinal_transitions": self.ordinal_transitions, "retracted_hypothesis_ids": self.retracted_hypothesis_ids, "unresolved_hypothesis_ids": self.unresolved_hypothesis_ids, "provenance": self.provenance, "successor_theory_state_id": self.theory_after.state_id}


@dataclass(frozen=True, slots=True)
class ExperimentMemoryRecord:
    memory_id: str
    run_id: str
    arm: Arm
    epoch: int
    revision_id: str
    content: Mapping[str, Any]
    theory_state_id: str | None = None
    proposal_set_id: str | None = None
    selection_receipt_id: str | None = None
    outcome_reference_id: str | None = None
    discrimination_observed: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "content", frozen_map(self.content))

    def to_payload(self) -> dict[str, Any]:
        return {"memory_id": self.memory_id, "run_id": self.run_id, "arm": self.arm, "epoch": self.epoch, "revision_id": self.revision_id, "content": self.content, "theory_state_id": self.theory_state_id, "proposal_set_id": self.proposal_set_id, "selection_receipt_id": self.selection_receipt_id, "outcome_reference_id": self.outcome_reference_id, "discrimination_observed": self.discrimination_observed}


@dataclass(frozen=True, slots=True)
class SourceAcquisitionReceipt:
    acquisition_id: str
    run_id: str
    arm: Arm
    first_crossing_epoch: int | None
    theory_state_id: str | None
    status: AcquisitionStatus
    correct_structural_class: bool | None
    heldout_delta_nats: float | None
    persistent: bool | None
    functional_gain: float | None
    canonical_evidence: bool | None
    prohibited_information: bool | None
    censor_reason: CensorReason = CensorReason.NONE
    block_id: str = "block-unknown"
    scenario_family: ScenarioFamily = ScenarioFamily.S1
    regressed_after_crossing: bool = False
    selected_structural_class: str | None = None
    theory_state_hash: str | None = None
    posterior_weight: float | None = None
    runner_up_odds: float | str | None = None
    unknown_weight: float | None = None
    token_count: int | None = None
    acquisition_logical_time: int | None = None
    candidate_seal_hash: str | None = None
    invalid_reasons: tuple[str, ...] = ()
    evaluator_version: str = "ea1-source-acquisition-evaluator-v1"

    def to_payload(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in ("acquisition_id", "run_id", "arm", "first_crossing_epoch", "theory_state_id", "status", "correct_structural_class", "heldout_delta_nats", "persistent", "functional_gain", "canonical_evidence", "prohibited_information", "censor_reason", "block_id", "scenario_family", "regressed_after_crossing", "selected_structural_class", "theory_state_hash", "posterior_weight", "runner_up_odds", "unknown_weight", "token_count", "acquisition_logical_time", "candidate_seal_hash", "invalid_reasons", "evaluator_version")}


def artifact_id(prefix: str, payload: Mapping[str, Any]) -> str:
    return stable_id(prefix, payload)


def artifact_hash(value: Any) -> str:
    return digest(value)
