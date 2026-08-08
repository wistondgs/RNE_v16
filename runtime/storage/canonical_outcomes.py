"""Authority boundary for cognitive outcome anchors.

This module establishes architectural producer authority inside one RNFE process.
It is not a cryptographic trust system and does not defend against hostile code
introspection or an administrator rewriting every source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import TYPE_CHECKING, Any, Mapping

from .records import StoredEvent

if TYPE_CHECKING:
    from runtime.life.contracts import AutonomyDecision, VitalSignsSnapshot
    from runtime.organism.life_transition import LifeTransition
    from .facade import StorageFacade


ACTING_OUTCOME_EVENT = "organism.life_transition.committed"
NONACTING_OUTCOME_EVENTS = frozenset(
    {"life.shutdown", "life.sleep", "life.quarantine", "life.rollback"}
)
RESERVED_CANONICAL_OUTCOME_EVENTS = frozenset(
    {ACTING_OUTCOME_EVENT, *NONACTING_OUTCOME_EVENTS}
)

ACTING_OWNER = "scenario_episode_runner"
NONACTING_OWNER = "life_kernel"
CANONICAL_OUTCOME_AUTHORITY_VERSION = "canonical-outcome-authority-v1"


class CanonicalOutcomeAuthorityError(ValueError):
    """A canonical outcome write lacked producer authority or continuity."""


class ReservedCanonicalOutcomeError(CanonicalOutcomeAuthorityError):
    """A generic writer attempted to persist a reserved cognitive anchor."""


class CanonicalOutcomeDivergenceError(CanonicalOutcomeAuthorityError):
    """One canonical identity resolved to divergent content."""


class CanonicalOutcomeUnavailableError(CanonicalOutcomeAuthorityError):
    """The persisted predecessor required to prove continuity was unavailable."""


# Opaque, process-local objects. They are deliberately neither serializable nor
# caller-supplied metadata. Leading-underscore access is part of the frozen failure
# model: ordinary runtime APIs do not expose them; hostile introspection is out of scope.
_ISSUER_CAPABILITY = object()
_BACKEND_WRITE_CAPABILITY = object()
_WRITE_LOCK = RLock()


def reject_reserved_canonical_event(event_type: str) -> None:
    if str(event_type) in RESERVED_CANONICAL_OUTCOME_EVENTS:
        raise ReservedCanonicalOutcomeError(
            f"reserved_canonical_outcome_requires_authority:{event_type}"
        )


def _require_backend_write_capability(capability: object, event_type: str) -> None:
    if capability is not _BACKEND_WRITE_CAPABILITY:
        raise ReservedCanonicalOutcomeError(
            f"canonical_backend_capability_required:{event_type}"
        )
    if event_type not in RESERVED_CANONICAL_OUTCOME_EVENTS:
        raise CanonicalOutcomeAuthorityError(
            f"canonical_channel_requires_reserved_event:{event_type}"
        )


@dataclass(frozen=True, slots=True)
class CanonicalOutcomeWriteResult:
    event: StoredEvent
    status: str


class CanonicalOutcomeAuthority:
    """Typed capability held only by factual world/life owners."""

    __slots__ = ("_storage", "_owner", "_issuer", "observations")

    def __init__(
        self,
        *,
        storage: "StorageFacade",
        owner: str,
        issuer: object,
    ) -> None:
        if issuer is not _ISSUER_CAPABILITY:
            raise CanonicalOutcomeAuthorityError("canonical_authority_issuer_required")
        if owner not in {ACTING_OWNER, NONACTING_OWNER}:
            raise CanonicalOutcomeAuthorityError("canonical_authority_owner_invalid")
        self._storage = storage
        self._owner = owner
        self._issuer = issuer
        self.observations: dict[str, int] = {
            "accepted": 0,
            "duplicate_exact": 0,
            "duplicate_divergent": 0,
            "authority_unavailable": 0,
        }

    def commit_acting_transition(
        self, transition: "LifeTransition"
    ) -> CanonicalOutcomeWriteResult:
        if self._owner != ACTING_OWNER:
            raise CanonicalOutcomeAuthorityError("acting_owner_authority_required")
        from runtime.organism.life_transition import LifeTransition

        if type(transition) is not LifeTransition:
            raise TypeError("canonical_acting_transition_type_required")
        if transition.status != "committed":
            raise CanonicalOutcomeAuthorityError("canonical_transition_must_be_committed")
        if transition.state_before.organism_id != transition.state_after.organism_id:
            raise CanonicalOutcomeAuthorityError("canonical_transition_organism_mismatch")
        if transition.state_before.lineage_id != transition.state_after.lineage_id:
            raise CanonicalOutcomeAuthorityError("canonical_transition_lineage_mismatch")
        if transition.state_before.run_id != transition.state_after.run_id:
            raise CanonicalOutcomeAuthorityError("canonical_transition_run_mismatch")

        event = StoredEvent(
            event_type=ACTING_OUTCOME_EVENT,
            run_id=transition.state_after.run_id,
            source=ACTING_OWNER,
            payload=transition.to_dict(),
        )
        with _WRITE_LOCK:
            existing, saturated = self._acting_anchors()
            by_id = [
                item for item in existing
                if item[0].transition_id == transition.transition_id
            ]
            if by_id:
                hashes = {item[0].transition_hash for item in by_id}
                hashes.add(transition.transition_hash)
                if len(hashes) != 1:
                    self.observations["duplicate_divergent"] += 1
                    raise CanonicalOutcomeDivergenceError(
                        "canonical_transition_identity_divergent"
                    )
                self.observations["duplicate_exact"] += 1
                return CanonicalOutcomeWriteResult(by_id[0][1], "duplicate_exact")

            if saturated:
                self.observations["authority_unavailable"] += 1
                raise CanonicalOutcomeUnavailableError(
                    "canonical_transition_lookup_window_saturated"
                )
            self._validate_acting_continuity(transition, existing)
            persisted = self._storage._append_canonical_outcome(
                event, _BACKEND_WRITE_CAPABILITY
            )
            self.observations["accepted"] += 1
            return CanonicalOutcomeWriteResult(persisted, "accepted")

    def commit_nonacting_decision(
        self,
        *,
        decision: "AutonomyDecision",
        vitals: "VitalSignsSnapshot",
        checkpoint_artifact_id: str,
        organism_id: str,
        run_id: str,
        episode_id: str,
        step_index: int,
        scenario: str,
        main_variable: str,
        operational_conjunction: Mapping[str, Any] | None = None,
        causal_context: Mapping[str, Any] | None = None,
    ) -> CanonicalOutcomeWriteResult:
        if self._owner != NONACTING_OWNER:
            raise CanonicalOutcomeAuthorityError("nonacting_owner_authority_required")
        from runtime.life.contracts import AutonomyDecision, VitalSignsSnapshot

        if type(decision) is not AutonomyDecision:
            raise TypeError("canonical_life_decision_type_required")
        if type(vitals) is not VitalSignsSnapshot:
            raise TypeError("canonical_vitals_type_required")
        action = str(decision.action)
        event_type = f"life.{action}"
        if event_type not in NONACTING_OUTCOME_EVENTS:
            raise CanonicalOutcomeAuthorityError("canonical_nonacting_action_invalid")
        if not all(
            str(item or "").strip()
            for item in (checkpoint_artifact_id, organism_id, run_id, episode_id)
        ):
            raise CanonicalOutcomeAuthorityError("canonical_nonacting_identity_required")

        facts = {
            "organism_id": organism_id,
            "run_id": run_id,
            "episode_id": episode_id,
            "scenario": str(scenario),
            "regime": "distress" if action in {"quarantine", "rollback"} else "rest",
            "main_variable": str(main_variable),
            "causal_status": "",
            "intervention": "",
            "viability_margin": vitals.viability_margin,
            "ioc": vitals.ioc_proxy,
            "risk": vitals.risk_score,
            "reward": 0.0,
            "action": action,
            "certified": bool(vitals.certified),
            "closure_passed": False,
            "viability_delta": 0.0,
        }
        payload: dict[str, Any] = {
            "episode_id": episode_id,
            "organism_id": organism_id,
            "step_index": int(step_index),
            "decision": decision.to_dict(),
            "vital_signs": vitals.to_dict(),
            "checkpoint_artifact_id": checkpoint_artifact_id,
            "operational_conjunction": dict(operational_conjunction or {}),
            "experience_facts": facts,
        }
        if causal_context:
            payload["causal_context"] = dict(causal_context)
        event = StoredEvent(
            event_type=event_type,
            run_id=run_id,
            source=NONACTING_OWNER,
            payload=payload,
        )

        from runtime.organism.experience import outcome_witness_from_event

        candidate_witness = outcome_witness_from_event(event)
        with _WRITE_LOCK:
            events = self._storage.list_events(
                run_id=run_id, event_types=[event_type], limit=5000
            )
            matches = []
            for item in events:
                try:
                    witness = outcome_witness_from_event(item)
                except (TypeError, ValueError):
                    continue
                if witness.source_record_id == candidate_witness.source_record_id:
                    matches.append((witness, item))
            if matches:
                witness_ids = {item[0].witness_id for item in matches}
                witness_ids.add(candidate_witness.witness_id)
                if len(witness_ids) != 1:
                    self.observations["duplicate_divergent"] += 1
                    raise CanonicalOutcomeDivergenceError(
                        "canonical_nonacting_identity_divergent"
                    )
                self.observations["duplicate_exact"] += 1
                return CanonicalOutcomeWriteResult(matches[0][1], "duplicate_exact")
            if len(events) >= 5000:
                self.observations["authority_unavailable"] += 1
                raise CanonicalOutcomeUnavailableError(
                    "canonical_nonacting_lookup_window_saturated"
                )
            persisted = self._storage._append_canonical_outcome(
                event, _BACKEND_WRITE_CAPABILITY
            )
            self.observations["accepted"] += 1
            return CanonicalOutcomeWriteResult(persisted, "accepted")

    def _acting_anchors(
        self,
    ) -> tuple[list[tuple["LifeTransition", StoredEvent]], bool]:
        from runtime.organism.life_transition import LifeTransition

        anchors: list[tuple[LifeTransition, StoredEvent]] = []
        events = self._storage.list_events(
            event_types=[ACTING_OUTCOME_EVENT], limit=5000
        )
        for event in events:
            if event.source != ACTING_OWNER:
                continue
            try:
                anchors.append((LifeTransition.from_dict(event.payload), event))
            except (TypeError, ValueError):
                continue
        return anchors, len(events) >= 5000

    def _validate_acting_continuity(
        self,
        transition: "LifeTransition",
        existing: list[tuple["LifeTransition", StoredEvent]],
    ) -> None:
        from runtime.organism.dynamic_state import canonical_hash

        organism_id = transition.state_after.organism_id
        lineage_id = transition.state_after.lineage_id
        run_id = transition.state_after.run_id
        same_run = [
            item for item, event in existing
            if event.run_id == run_id and item.state_after.organism_id == organism_id
        ]
        if transition.transition_index == 1:
            expected_genesis = canonical_hash(
                {"genesis": True, "organism_id": organism_id, "lineage_id": lineage_id}
            )
            if (
                same_run
                or transition.previous_transition_id is not None
                or transition.previous_transition_hash != expected_genesis
            ):
                self.observations["authority_unavailable"] += 1
                raise CanonicalOutcomeUnavailableError(
                    "canonical_genesis_not_available"
                )
            return

        predecessors = [
            item for item, _event in existing
            if item.transition_id == transition.previous_transition_id
        ]
        valid = [
            item for item in predecessors
            if item.transition_hash == transition.previous_transition_hash
            and item.transition_index + 1 == transition.transition_index
            and item.state_after.organism_id == organism_id
            and item.state_after.lineage_id == lineage_id
            and transition.state_before.previous_state_hash == item.state_after.state_hash
        ]
        if len(valid) != 1:
            self.observations["authority_unavailable"] += 1
            raise CanonicalOutcomeUnavailableError(
                "canonical_transition_predecessor_unavailable"
            )


def _issue_canonical_outcome_authority(
    *, storage: "StorageFacade", owner: str
) -> CanonicalOutcomeAuthority:
    """Composition-only issuer used by the two factual owner constructors."""

    return CanonicalOutcomeAuthority(
        storage=storage, owner=owner, issuer=_ISSUER_CAPABILITY
    )
