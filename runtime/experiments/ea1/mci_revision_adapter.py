"""Canonical F1A evidence barrier and preregistered EA1 belief revision."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from runtime.organism.experience import ExperienceIntegrityError, outcome_witness_from_event
from runtime.organism.life_transition import LifeTransition
from runtime.storage import StorageFacade
from runtime.symbolic.mci import TransitionCompiler, TransitionEvidence

from .canonical import digest, stable_id
from .contracts import (
    BeliefRevision,
    CanonicalOutcomeReference,
    ContractError,
    DivergentPredictionSet,
    ExperimentSelectionReceipt,
    OrdinalState,
    TheoryState,
)
from .mci_adapter import MCIWorkingSet


@dataclass(frozen=True, slots=True)
class _ValidatedCanonicalEvidence:
    reference_id: str
    selection_receipt_id: str
    action_id: str
    outcome: int
    witness_id: str
    outcome_hash: str
    bridge_identity: object

    @property
    def evidence_id(self) -> str:
        return stable_id(
            "mci-canonical-evidence",
            {
                "reference_id": self.reference_id,
                "witness_id": self.witness_id,
                "outcome_hash": self.outcome_hash,
            },
        )


class CanonicalEvidenceBridge:
    """Revalidates a reference against a persisted F1A transition; owns no authority."""

    def __init__(self, storage: StorageFacade, *, factual_field: str = "ea1_binary_outcome") -> None:
        self._storage = storage
        self._factual_field = factual_field
        self._identity = object()
        self._validated: dict[str, _ValidatedCanonicalEvidence] = {}

    def validate(
        self,
        reference: CanonicalOutcomeReference,
        receipt: ExperimentSelectionReceipt,
    ) -> _ValidatedCanonicalEvidence:
        if not isinstance(reference, CanonicalOutcomeReference):
            raise ExperienceIntegrityError("canonical_outcome_reference_required")
        if (
            reference.selection_receipt_id != receipt.receipt_id
            or reference.committed_intervention != receipt.action_id
        ):
            raise ExperienceIntegrityError("canonical_reference_selection_mismatch")
        matches: list[tuple[Any, Any]] = []
        for event in self._storage.list_events(
            run_id=receipt.run_id,
            event_types=[reference.source_event_type],
            limit=10000,
        ):
            try:
                witness = outcome_witness_from_event(event)
            except ExperienceIntegrityError:
                continue
            if witness.source_record_id == reference.source_record_id:
                matches.append((event, witness))
        if len(matches) != 1:
            raise ExperienceIntegrityError("canonical_reference_does_not_resolve_uniquely")
        event, witness = matches[0]
        if (
            witness.witness_id != reference.witness_id
            or witness.outcome_hash != reference.outcome_hash
            or witness.committed_intervention != reference.committed_intervention
        ):
            raise ExperienceIntegrityError("canonical_reference_witness_mismatch")
        transition = LifeTransition.from_dict(event.payload)
        raw = transition.factual_outcome.get(self._factual_field)
        if isinstance(raw, bool):
            outcome = int(raw)
        elif isinstance(raw, int) and raw in {0, 1}:
            outcome = raw
        else:
            raise ExperienceIntegrityError("canonical_binary_outcome_missing")
        candidate = _ValidatedCanonicalEvidence(
            reference.reference_id,
            receipt.receipt_id,
            receipt.action_id,
            outcome,
            witness.witness_id,
            witness.outcome_hash,
            self._identity,
        )
        previous = self._validated.get(reference.reference_id)
        if previous is not None and previous != candidate:
            raise ExperienceIntegrityError("divergent_canonical_evidence_replay")
        self._validated[reference.reference_id] = candidate
        return previous or candidate

    def owns(self, evidence: object) -> bool:
        return (
            isinstance(evidence, _ValidatedCanonicalEvidence)
            and evidence.bridge_identity is self._identity
            and self._validated.get(evidence.reference_id) == evidence
        )


class MCIOutcomeAdapter:
    def __init__(self, bridge: CanonicalEvidenceBridge) -> None:
        self._bridge = bridge
        self._revisions: dict[str, tuple[str, BeliefRevision]] = {}

    def revise(
        self,
        theory: TheoryState,
        working: MCIWorkingSet,
        prediction_set: DivergentPredictionSet,
        receipt: ExperimentSelectionReceipt,
        reference: CanonicalOutcomeReference,
        *,
        epoch: int,
        logical_time: int,
    ) -> BeliefRevision:
        evidence = self._bridge.validate(reference, receipt)
        if not self._bridge.owns(evidence):
            raise ExperienceIntegrityError("untrusted_canonical_evidence")
        input_hash = digest(
            {
                "theory": theory,
                "prediction_set_id": prediction_set.prediction_set_id,
                "receipt_id": receipt.receipt_id,
                "reference_id": reference.reference_id,
                "outcome": evidence.outcome,
                "epoch": epoch,
                "logical_time": logical_time,
            }
        )
        previous = self._revisions.get(reference.reference_id)
        if previous is not None:
            if previous[0] != input_hash:
                raise ContractError("divergent_belief_revision_replay")
            return previous[1]

        working.assert_consistent(theory)
        if prediction_set.theory_state_id != theory.state_id:
            raise ContractError("revision_prediction_theory_mismatch")
        predictions = {
            item.hypothesis_id: item
            for item in prediction_set.predictions
            if item.action_id == receipt.action_id
        }
        if set(predictions) != set(theory.rival_hypothesis_ids):
            raise ContractError("revision_likelihoods_unavailable")
        probabilities = tuple(
            predictions[item].success_probability for item in theory.rival_hypothesis_ids
        )
        if any(item is None for item in probabilities):
            raise ContractError("revision_likelihoods_unavailable")

        likelihoods = tuple(
            max(float(probability) if evidence.outcome else 1.0 - float(probability), 1e-12)
            for probability in probabilities
        )
        unknown_likelihood = 0.5
        unnormalized = (
            theory.posterior_h1 * likelihoods[0],
            theory.posterior_h2 * likelihoods[1],
            theory.posterior_unknown * unknown_likelihood,
        )
        total = sum(unnormalized)
        posterior = tuple(value / total for value in unnormalized)
        best_likelihood = max(likelihoods)
        statuses: list[tuple[str, str]] = []
        retracted: list[str] = []
        for index, hypothesis_id in enumerate(theory.rival_hypothesis_ids):
            ratio = likelihoods[index] / best_likelihood
            status = "refuted" if posterior[index] <= 0.05 and ratio <= 0.10 else "active"
            statuses.append((hypothesis_id, status))
            if status == "refuted":
                retracted.append(hypothesis_id)
        preferred_index = 0 if posterior[0] >= posterior[1] else 1
        preferred = theory.rival_hypothesis_ids[preferred_index]
        ordinal = OrdinalState.HIGH if posterior[preferred_index] >= 0.80 else OrdinalState.MID
        state_payload = {
            "epoch": epoch + 1,
            "posterior_h1": posterior[0],
            "posterior_h2": posterior[1],
            "posterior_unknown": posterior[2],
            "preferred_hypothesis_id": preferred,
            "evidence_ids": theory.evidence_ids + (reference.reference_id,),
            "rival_hypothesis_ids": theory.rival_hypothesis_ids,
            "ordinal_state": ordinal,
            "predecessor_state_id": theory.state_id,
            "version": theory.version + 1,
            "logical_time": logical_time,
        }
        successor = TheoryState(stable_id("theory", state_payload), **state_payload)

        for item in working.hypotheses:
            predicted = TransitionCompiler(item.runtime.learner.active_spec).execute(
                {"outcome_probability": 0.0, "alarm": False},
                action=receipt.action_id,
                external_input=0.0,
            )
            observed = {
                "outcome_probability": float(evidence.outcome),
                "alarm": bool(evidence.outcome),
            }
            item.runtime.learner.observe(
                TransitionEvidence(
                    {"outcome_probability": 0.0, "alarm": False},
                    receipt.action_id,
                    0.0,
                    observed,
                    predicted,
                    replay_unit_id=reference.reference_id,
                    logical_time=logical_time,
                )
            )
        working.rebind(successor)
        snapshot = working.snapshot()
        overlay_refs = tuple(
            (
                item.candidate.hypothesis_id,
                item.runtime.learner.active_overlay.overlay_id
                if item.runtime.learner.active_overlay is not None
                else None,
            )
            for item in working.hypotheses
        )
        revision_payload = {
            "epoch": epoch,
            "theory_before_id": theory.state_id,
            "theory_after_id": successor.state_id,
            "outcome_reference_id": reference.reference_id,
            "likelihoods": tuple(zip(theory.rival_hypothesis_ids, likelihoods, strict=True)),
            "posterior": posterior,
            "mci_state_hash": digest(snapshot),
        }
        revision = BeliefRevision(
            stable_id("mci-revision", revision_payload),
            epoch,
            theory.state_id,
            successor,
            reference.reference_id,
            "EA1-C-v1 Bernoulli Bayes update from revalidated F1A evidence",
            tuple(zip(theory.rival_hypothesis_ids, likelihoods, strict=True)),
            (
                (theory.rival_hypothesis_ids[0], posterior[0]),
                (theory.rival_hypothesis_ids[1], posterior[1]),
                ("unknown", posterior[2]),
            ),
            tuple(statuses),
            tuple(retracted),
            (),
            "canonical_f1a_evidence",
            overlay_refs,
            digest(snapshot),
        )
        self._revisions[reference.reference_id] = (input_hash, revision)
        return revision

    def reject_unvalidated(self, value: object) -> None:
        if not self._bridge.owns(value):
            raise ExperienceIntegrityError("validated_canonical_evidence_required")
