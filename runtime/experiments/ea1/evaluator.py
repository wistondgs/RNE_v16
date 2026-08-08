from __future__ import annotations

from dataclasses import dataclass

from .canonical import stable_id
from .contracts import AcquisitionStatus, Arm, CensorReason, ScenarioFamily, SourceAcquisitionReceipt, TheoryState
from .canonical import digest

POSTERIOR_THRESHOLD = 0.80
ODDS_THRESHOLD = 4.0
UNKNOWN_MAX = 0.10
HELDOUT_DELTA_MIN_NATS = 0.05
FUNCTIONAL_GAIN_MIN = 0.25


class EvaluationPhaseError(RuntimeError):
    pass


class FirstCrossingTracker:
    """Immutable first threshold crossing; later states cannot move it."""

    def __init__(self) -> None:
        self._crossing: TheoryState | None = None
        self._seen: dict[str, str] = {}
        self._regressed_after_crossing = False

    def observe(self, state: TheoryState) -> TheoryState | None:
        fingerprint = stable_id("theory", state.to_payload())
        prior = self._seen.get(state.state_id)
        if prior and prior != fingerprint:
            raise ValueError("divergent_theory_state_replay")
        self._seen[state.state_id] = fingerprint
        meets = state.preferred_posterior >= POSTERIOR_THRESHOLD and state.rival_odds >= ODDS_THRESHOLD and state.posterior_unknown <= UNKNOWN_MAX
        if self._crossing is None and meets:
            self._crossing = state
        elif self._crossing is not None and state.epoch > self._crossing.epoch and not meets:
            self._regressed_after_crossing = True
        return self._crossing

    @property
    def crossing(self) -> TheoryState | None:
        return self._crossing

    @property
    def regressed_after_crossing(self) -> bool:
        return self._regressed_after_crossing


@dataclass(frozen=True, slots=True)
class EvaluationEvidence:
    correct_structural_class: bool | None
    heldout_initial_log_loss: float | None
    heldout_acquired_log_loss: float | None
    persistence_opportunities: int
    persistence_passed: bool | None
    functional_gain: float | None
    canonical_evidence: bool | None
    prohibited_information: bool
    censor_reason: CensorReason = CensorReason.NONE
    evaluation_count: int = 1
    candidate_canonical_signature: str | None = None
    ground_truth_canonical_signature: str | None = None
    heldout_interventional_mae: float | None = None
    heldout_probe_count: int = 0
    required_persistence_opportunities: int = 2
    functional_probe_count: int = 0
    functional_invariant_breaches: int = 0
    ground_truth_opening_ref: str | None = None


class SourceAcquisitionEvaluator:
    """Post-run evaluator. It has no arm-facing API and fails closed before finalization."""

    def __init__(self, run_id: str, arm: Arm, tracker: FirstCrossingTracker, *, block_id: str = "block-dev", scenario_family: ScenarioFamily = ScenarioFamily.S1, token_count: int = 0) -> None:
        self.run_id, self.arm, self.tracker = run_id, arm, tracker
        self.block_id, self.scenario_family = block_id, scenario_family
        self.token_count = token_count
        self._arms_finalized = False
        self._candidate: SourceAcquisitionReceipt | None = None

    def mark_arms_finalized(self) -> None:
        self._arms_finalized = True

    def seal_candidate(self) -> SourceAcquisitionReceipt:
        if not self._arms_finalized:
            raise EvaluationPhaseError("candidate_only_after_all_arms_finalize")
        crossing = self.tracker.crossing
        payload = {"run_id": self.run_id, "arm": self.arm.value, "first_crossing": crossing.state_id if crossing else None}
        candidate_values = {
            "selected_structural_class": crossing.preferred_hypothesis_id if crossing else None,
            "theory_state_hash": digest(crossing.to_payload()) if crossing else None,
            "posterior_weight": crossing.preferred_posterior if crossing else None,
            "runner_up_odds": ("infinite" if crossing and crossing.rival_odds == float("inf") else crossing.rival_odds) if crossing else None,
            "unknown_weight": crossing.posterior_unknown if crossing else None,
            "token_count": self.token_count,
            "acquisition_logical_time": crossing.logical_time if crossing else None,
        }
        candidate_seal_hash = digest({**payload, **candidate_values})
        self._candidate = SourceAcquisitionReceipt(
            acquisition_id=stable_id("acq", payload), run_id=self.run_id, arm=self.arm,
            first_crossing_epoch=crossing.epoch if crossing else None,
            theory_state_id=crossing.state_id if crossing else None,
            status=AcquisitionStatus.CANDIDATE_SEALED,
            correct_structural_class=None, heldout_delta_nats=None, persistent=None,
            functional_gain=None, canonical_evidence=None, prohibited_information=None,
            block_id=self.block_id, scenario_family=self.scenario_family,
            regressed_after_crossing=self.tracker.regressed_after_crossing,
            **candidate_values, candidate_seal_hash=candidate_seal_hash,
        )
        return self._candidate

    def finalize(self, evidence: EvaluationEvidence) -> SourceAcquisitionReceipt:
        if self._candidate is None:
            raise EvaluationPhaseError("candidate_must_be_sealed_first")
        delta = None
        if evidence.heldout_initial_log_loss is not None and evidence.heldout_acquired_log_loss is not None:
            # Decimal protocol thresholds must not be changed by binary-float dust.
            delta = round(evidence.heldout_initial_log_loss - evidence.heldout_acquired_log_loss, 12)
        incomplete = (
            evidence.censor_reason is not CensorReason.NONE
            or evidence.evaluation_count == 0
            or evidence.correct_structural_class is None
            or delta is None
            or evidence.persistence_passed is None
            or evidence.functional_gain is None
            or evidence.canonical_evidence is None
            or evidence.candidate_canonical_signature is None
            or evidence.ground_truth_canonical_signature is None
            or evidence.heldout_interventional_mae is None
            or evidence.heldout_probe_count != 8
            or evidence.functional_probe_count != 4
            or evidence.ground_truth_opening_ref is None
        )
        signature_match = evidence.candidate_canonical_signature == evidence.ground_truth_canonical_signature
        valid = (
            not incomplete
            and self._candidate.theory_state_id is not None
            and evidence.correct_structural_class is True
            and delta is not None and delta >= HELDOUT_DELTA_MIN_NATS
            and signature_match and evidence.heldout_interventional_mae is not None and evidence.heldout_interventional_mae <= 0.10
            and evidence.required_persistence_opportunities == 2 and evidence.persistence_opportunities >= 2 and evidence.persistence_passed is True
            and evidence.functional_gain is not None and evidence.functional_gain >= FUNCTIONAL_GAIN_MIN
            and evidence.functional_invariant_breaches == 0
            and evidence.canonical_evidence is True
            and evidence.prohibited_information is False
        )
        status = AcquisitionStatus.INCOMPLETE if incomplete else AcquisitionStatus.VALID if valid else AcquisitionStatus.INVALID
        invalid_reasons: list[str] = []
        if status is not AcquisitionStatus.VALID:
            if incomplete: invalid_reasons.append("missing_required_evaluation")
            if self._candidate.theory_state_id is None: invalid_reasons.append("acquisition_threshold_not_crossed")
            if not signature_match: invalid_reasons.append("structural_signature_mismatch")
            if evidence.heldout_interventional_mae is not None and evidence.heldout_interventional_mae > 0.10: invalid_reasons.append("heldout_mae_gate_failed")
            if evidence.persistence_opportunities < 2: invalid_reasons.append("persistence_opportunities_missing")
            if evidence.functional_invariant_breaches: invalid_reasons.append("functional_invariant_breach")
        return SourceAcquisitionReceipt(
            acquisition_id=self._candidate.acquisition_id, run_id=self.run_id, arm=self.arm,
            first_crossing_epoch=self._candidate.first_crossing_epoch, theory_state_id=self._candidate.theory_state_id,
            status=status, correct_structural_class=evidence.correct_structural_class,
            heldout_delta_nats=delta, persistent=evidence.persistence_passed,
            functional_gain=evidence.functional_gain, canonical_evidence=evidence.canonical_evidence,
            prohibited_information=evidence.prohibited_information,
            censor_reason=CensorReason.ZERO_EVALUATIONS if evidence.evaluation_count == 0 else evidence.censor_reason,
            block_id=self.block_id, scenario_family=self.scenario_family,
            regressed_after_crossing=self.tracker.regressed_after_crossing,
            selected_structural_class=self._candidate.selected_structural_class,
            theory_state_hash=self._candidate.theory_state_hash,
            posterior_weight=self._candidate.posterior_weight,
            runner_up_odds=self._candidate.runner_up_odds,
            unknown_weight=self._candidate.unknown_weight,
            token_count=self._candidate.token_count,
            acquisition_logical_time=self._candidate.acquisition_logical_time,
            candidate_seal_hash=self._candidate.candidate_seal_hash,
            invalid_reasons=tuple(invalid_reasons),
        )
