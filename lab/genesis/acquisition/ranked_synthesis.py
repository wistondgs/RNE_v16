"""Versioned, rank-correct TRAIN-only synthesis semantics for M7-H1.

M7-v1 remains in :mod:`synthesis` as historical evidence.  This module is a
separate search engine: it completes a node/MDL level before selecting from
it, and its behavior deduplication retains the ranking-minimal representative
rather than the first expression emitted by a traversal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from time import monotonic
from typing import Any, Iterable, Mapping

from lab.genesis.acquisition.benchmark import LearnerTrainingView
from lab.genesis.acquisition.dsl import (
    DSLSpecification,
    _evaluate_canonical_expression,
    expression_metrics,
)
from lab.genesis.acquisition.synthesis import _expressions
from lab.genesis.contracts.serialization import canonical_sha256, freeze
from lab.genesis.evidence.artifacts import is_artifact_hash


SEARCH_SEMANTICS_V2_ID = "RANK_CANONICAL_BEHAVIOR_REPRESENTATIVE-v2"
RANKED_SYNTHESIZER_IMPLEMENTATION_HASH = canonical_sha256(
    {"synthesizer": "genesis-m7-rank-canonical-enumerative-synthesizer-v2"}
)
_POLICY_SCHEMA = "genesis-m7-ranked-search-policy-v2"
_RECEIPT_SCHEMA = "genesis-m7-ranked-synthesis-receipt-v2"


class RankedSearchTermination(str, Enum):
    EXACT_CANDIDATE_AFTER_COMPLETE_LEVEL = "EXACT_CANDIDATE_AFTER_COMPLETE_LEVEL"
    FRONTIER_EXHAUSTED_NO_CANDIDATE = "FRONTIER_EXHAUSTED_NO_CANDIDATE"
    RESOURCE_EXHAUSTED_INCOMPLETE_LEVEL = "RESOURCE_EXHAUSTED_INCOMPLETE_LEVEL"
    INVALID_SEARCH_STATE = "INVALID_SEARCH_STATE"


BehaviorAtom = tuple[str, int | str]
BehaviorKey = tuple[BehaviorAtom, ...]


def _require_hash(value: str, reason: str) -> None:
    if not isinstance(value, str) or not is_artifact_hash(value):
        raise ValueError(reason)


@dataclass(frozen=True, slots=True)
class RankedSearchPolicy:
    """Immutable frontier and safety policy for the H1 search implementation.

    ``max_ast_nodes`` is the scientific frontier.  The optional caps are not:
    hitting one before a level completes makes the result explicitly
    ``RESOURCE_EXHAUSTED_INCOMPLETE_LEVEL``.
    """

    schema_version: str
    policy_id: str
    dsl_hash: str
    max_ast_nodes: int
    max_ast_depth: int
    max_raw_ast_evaluations: int | None = None
    max_distinct_behaviors: int | None = None
    wall_time_limit_seconds: int | None = None
    policy_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != _POLICY_SCHEMA or not self.policy_id:
            raise ValueError("genesis_ranked_search_policy_identity_invalid")
        _require_hash(self.dsl_hash, "genesis_ranked_search_policy_dsl_invalid")
        for value, reason in (
            (self.max_ast_nodes, "genesis_ranked_search_policy_nodes_invalid"),
            (self.max_ast_depth, "genesis_ranked_search_policy_depth_invalid"),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(reason)
        for value, reason in (
            (self.max_raw_ast_evaluations, "genesis_ranked_search_policy_raw_cap_invalid"),
            (self.max_distinct_behaviors, "genesis_ranked_search_policy_behavior_cap_invalid"),
            (self.wall_time_limit_seconds, "genesis_ranked_search_policy_wall_cap_invalid"),
        ):
            if value is not None and (
                not isinstance(value, int) or isinstance(value, bool) or value <= 0
            ):
                raise ValueError(reason)
        object.__setattr__(self, "policy_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "policy_id": self.policy_id,
            "dsl_hash": self.dsl_hash,
            "max_ast_nodes": self.max_ast_nodes,
            "max_ast_depth": self.max_ast_depth,
            "max_raw_ast_evaluations": self.max_raw_ast_evaluations,
            "max_distinct_behaviors": self.max_distinct_behaviors,
            "wall_time_limit_seconds": self.wall_time_limit_seconds,
        }

    def validate(self) -> bool:
        try:
            return RankedSearchPolicy(**self.canonical_payload()).policy_hash == self.policy_hash
        except (TypeError, ValueError):
            return False


def ranked_search_policy(
    *,
    specification: DSLSpecification,
    policy_id: str,
    max_ast_nodes: int,
    max_ast_depth: int | None = None,
    max_raw_ast_evaluations: int | None = None,
    max_distinct_behaviors: int | None = None,
    wall_time_limit_seconds: int | None = None,
) -> RankedSearchPolicy:
    """Create a policy that cannot widen the immutable DSL limits."""

    if (
        not specification.validate()
        or max_ast_nodes > specification.max_ast_nodes
        or (max_ast_depth is not None and max_ast_depth > specification.max_ast_depth)
    ):
        raise ValueError("genesis_ranked_search_policy_dsl_frontier_invalid")
    return RankedSearchPolicy(
        _POLICY_SCHEMA,
        policy_id,
        specification.dsl_hash,
        max_ast_nodes,
        specification.max_ast_depth if max_ast_depth is None else max_ast_depth,
        max_raw_ast_evaluations,
        max_distinct_behaviors,
        wall_time_limit_seconds,
    )


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    """A TRAIN-only candidate selected by the declared lexicographic rank."""

    program_ast: Mapping[str, Any]
    program_hash: str
    mdl: int
    ast_depth: int
    behavior_key: BehaviorKey
    training_error: int | None

    def __post_init__(self) -> None:
        if (
            not is_artifact_hash(self.program_hash)
            or not isinstance(self.mdl, int)
            or not isinstance(self.ast_depth, int)
            or self.mdl <= 0
            or self.ast_depth <= 0
            or self.training_error is not None and self.training_error < 0
        ):
            raise ValueError("genesis_ranked_candidate_invalid")
        object.__setattr__(self, "program_ast", freeze(self.program_ast))
        object.__setattr__(self, "behavior_key", tuple(self.behavior_key))
        if self.program_hash != canonical_sha256(self.program_ast):
            raise ValueError("genesis_ranked_candidate_program_hash_invalid")

    @property
    def rank(self) -> tuple[int, int, str]:
        if self.training_error is None:
            raise ValueError("genesis_ranked_candidate_failure_not_rankable")
        return (self.training_error, self.mdl, self.program_hash)


@dataclass(frozen=True, slots=True)
class RankedSearchReceipt:
    """Immutable H1 frontier state; no M7-v1 receipt is reinterpreted."""

    schema_version: str
    search_semantics_id: str
    synthesizer_implementation_hash: str
    policy_hash: str
    dsl_hash: str
    training_commitment_hash: str
    completed_levels: tuple[int, ...]
    current_level: int | None
    current_level_complete: bool
    raw_ast_count: int
    canonical_ast_count: int
    behavior_class_count: int
    deduplicated_count: int
    candidate_found: bool
    candidate_level: int | None
    candidate_hash: str | None
    termination_reason: RankedSearchTermination
    elapsed_milliseconds: int
    receipt_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            self.schema_version != _RECEIPT_SCHEMA
            or self.search_semantics_id != SEARCH_SEMANTICS_V2_ID
        ):
            raise ValueError("genesis_ranked_receipt_version_invalid")
        for value, reason in (
            (self.synthesizer_implementation_hash, "genesis_ranked_receipt_implementation_invalid"),
            (self.policy_hash, "genesis_ranked_receipt_policy_invalid"),
            (self.dsl_hash, "genesis_ranked_receipt_dsl_invalid"),
            (self.training_commitment_hash, "genesis_ranked_receipt_training_invalid"),
        ):
            _require_hash(value, reason)
        if self.synthesizer_implementation_hash != RANKED_SYNTHESIZER_IMPLEMENTATION_HASH:
            raise ValueError("genesis_ranked_receipt_implementation_mismatch")
        levels = tuple(sorted(set(self.completed_levels)))
        if levels != self.completed_levels or any(level <= 0 for level in levels):
            raise ValueError("genesis_ranked_receipt_levels_invalid")
        for value, reason in (
            (self.raw_ast_count, "genesis_ranked_receipt_raw_count_invalid"),
            (self.canonical_ast_count, "genesis_ranked_receipt_canonical_count_invalid"),
            (self.behavior_class_count, "genesis_ranked_receipt_behavior_count_invalid"),
            (self.deduplicated_count, "genesis_ranked_receipt_dedup_count_invalid"),
            (self.elapsed_milliseconds, "genesis_ranked_receipt_elapsed_invalid"),
        ):
            if not isinstance(value, int) or value < 0:
                raise ValueError(reason)
        if (
            self.canonical_ast_count > self.raw_ast_count
            or self.behavior_class_count > self.canonical_ast_count
            or self.deduplicated_count
            != self.canonical_ast_count - self.behavior_class_count
        ):
            raise ValueError("genesis_ranked_receipt_counts_inconsistent")
        object.__setattr__(self, "termination_reason", RankedSearchTermination(self.termination_reason))
        if self.current_level is not None and self.current_level <= 0:
            raise ValueError("genesis_ranked_receipt_current_level_invalid")
        candidate_fields = (self.candidate_level, self.candidate_hash)
        if self.candidate_found:
            if (
                any(value is None for value in candidate_fields)
                or not is_artifact_hash(self.candidate_hash or "")
                or self.candidate_level not in levels
                or self.current_level != self.candidate_level
                or not levels
                or self.candidate_level != levels[-1]
                or not self.current_level_complete
                or self.termination_reason
                is not RankedSearchTermination.EXACT_CANDIDATE_AFTER_COMPLETE_LEVEL
            ):
                raise ValueError("genesis_ranked_receipt_candidate_invalid")
        elif any(value is not None for value in candidate_fields):
            raise ValueError("genesis_ranked_receipt_absent_candidate_invalid")
        elif self.termination_reason is RankedSearchTermination.EXACT_CANDIDATE_AFTER_COMPLETE_LEVEL:
            raise ValueError("genesis_ranked_receipt_missing_exact_candidate")
        if (
            self.termination_reason
            is RankedSearchTermination.FRONTIER_EXHAUSTED_NO_CANDIDATE
            and not self.current_level_complete
        ):
            raise ValueError("genesis_ranked_receipt_frontier_incomplete")
        if (
            self.termination_reason
            is RankedSearchTermination.RESOURCE_EXHAUSTED_INCOMPLETE_LEVEL
            and self.current_level_complete
        ):
            raise ValueError("genesis_ranked_receipt_partial_level_invalid")
        object.__setattr__(self, "receipt_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "search_semantics_id": self.search_semantics_id,
            "synthesizer_implementation_hash": self.synthesizer_implementation_hash,
            "policy_hash": self.policy_hash,
            "dsl_hash": self.dsl_hash,
            "training_commitment_hash": self.training_commitment_hash,
            "completed_levels": self.completed_levels,
            "current_level": self.current_level,
            "current_level_complete": self.current_level_complete,
            "raw_ast_count": self.raw_ast_count,
            "canonical_ast_count": self.canonical_ast_count,
            "behavior_class_count": self.behavior_class_count,
            "deduplicated_count": self.deduplicated_count,
            "candidate_found": self.candidate_found,
            "candidate_level": self.candidate_level,
            "candidate_hash": self.candidate_hash,
            "termination_reason": self.termination_reason.value,
            "elapsed_milliseconds": self.elapsed_milliseconds,
        }

    def validate(self) -> bool:
        try:
            return RankedSearchReceipt(**self.canonical_payload()).receipt_hash == self.receipt_hash
        except (TypeError, ValueError):
            return False

    def semantic_payload(self) -> dict[str, Any]:
        """Fields that must reproduce across a replay despite elapsed time."""

        payload = self.canonical_payload()
        del payload["elapsed_milliseconds"]
        return payload


@dataclass(frozen=True, slots=True)
class RankedSearchOutcome:
    receipt: RankedSearchReceipt
    selected_candidate: RankedCandidate | None


def _behavior_key(
    expression: Mapping[str, Any],
    specification: DSLSpecification,
    training: LearnerTrainingView,
) -> tuple[BehaviorKey, int | None]:
    """Commit ordered TRAIN values *and* deterministic failures to one key."""

    behavior: list[BehaviorAtom] = []
    correct = 0
    failed = False
    for example in training.training_examples:
        try:
            output = _evaluate_canonical_expression(
                expression, example.input_value, specification,
            )
        except ValueError as error:
            failed = True
            behavior.append(("FAILURE", f"{type(error).__name__}:{error}"))
        else:
            behavior.append(("VALUE", output))
            correct += output == example.output_value
    return tuple(behavior), None if failed else len(training.training_examples) - correct


def _ordered_expressions(
    specification: DSLSpecification,
    policy: RankedSearchPolicy,
    *,
    enumeration_order: str,
) -> Iterable[Mapping[str, Any]]:
    """Yield the immutable grammar's canonical ASTs, optionally reversed.

    The non-canonical orders are test-only metamorphic inputs.  They never
    change the DSL, its limits, or the rank definition; they only prove that
    AST insertion order, operator order, and constant order have no authority
    over the v2 result.
    """

    values = _expressions(specification, policy.max_ast_nodes)
    if enumeration_order == "CANONICAL":
        for expression in values:
            if expression_metrics(expression, specification)["ast_depth"] <= policy.max_ast_depth:
                yield expression
        return
    if enumeration_order not in {
        "REVERSED", "OPERATOR_REVERSED", "CONSTANT_REVERSED",
    }:
        raise ValueError("genesis_ranked_search_enumeration_order_invalid")

    def constants(expression: Mapping[str, Any]) -> tuple[int, ...]:
        values = () if "value" not in expression else (int(expression["value"]),)
        return tuple(sorted((*values, *(value for child in expression["args"] for value in constants(child)))))

    def reorder(level: list[Mapping[str, Any]]) -> Iterable[Mapping[str, Any]]:
        if enumeration_order == "REVERSED":
            return reversed(level)
        if enumeration_order == "OPERATOR_REVERSED":
            return iter(sorted(
                level,
                key=lambda expression: (str(expression["op"]), canonical_sha256(expression)),
                reverse=True,
            ))
        return iter(sorted(
            level,
            key=lambda expression: (constants(expression), canonical_sha256(expression)),
            reverse=True,
        ))

    level: list[Mapping[str, Any]] = []
    current_nodes: int | None = None
    for expression in values:
        nodes = int(expression_metrics(expression, specification)["node_count"])
        if current_nodes is not None and nodes != current_nodes:
            yield from reorder(level)
            level = []
        current_nodes = nodes
        if expression_metrics(expression, specification)["ast_depth"] <= policy.max_ast_depth:
            level.append(expression)
    yield from reorder(level)


class RankCanonicalProgramSynthesizer:
    """Complete each MDL level, then choose its ranking-minimal exact member."""

    implementation_id = "genesis-m7-rank-canonical-enumerative-synthesizer-v2"
    search_semantics_id = SEARCH_SEMANTICS_V2_ID
    implementation_hash = RANKED_SYNTHESIZER_IMPLEMENTATION_HASH

    def synthesize(
        self,
        *,
        specification: DSLSpecification,
        training: LearnerTrainingView,
        policy: RankedSearchPolicy,
        test_enumeration_order: str = "CANONICAL",
    ) -> RankedSearchOutcome:
        if (
            not specification.validate()
            or not policy.validate()
            or policy.dsl_hash != specification.dsl_hash
            or policy.max_ast_nodes > specification.max_ast_nodes
            or policy.max_ast_depth > specification.max_ast_depth
            or not training.training_examples
        ):
            raise ValueError("genesis_ranked_search_input_invalid")

        started = monotonic()
        raw_count = canonical_count = 0
        all_behavior_representatives: dict[BehaviorKey, RankedCandidate] = {}
        level_representatives: dict[BehaviorKey, RankedCandidate] = {}
        completed_levels: list[int] = []
        current_level: int | None = None

        def elapsed() -> int:
            return int((monotonic() - started) * 1_000)

        def outcome(
            *,
            level_complete: bool,
            candidate: RankedCandidate | None,
            reason: RankedSearchTermination,
        ) -> RankedSearchOutcome:
            receipt = RankedSearchReceipt(
                _RECEIPT_SCHEMA,
                SEARCH_SEMANTICS_V2_ID,
                RANKED_SYNTHESIZER_IMPLEMENTATION_HASH,
                policy.policy_hash,
                specification.dsl_hash,
                training.training_commitment_hash,
                tuple(completed_levels),
                current_level,
                level_complete,
                raw_count,
                canonical_count,
                len(all_behavior_representatives),
                canonical_count - len(all_behavior_representatives),
                candidate is not None,
                None if candidate is None else candidate.mdl,
                None if candidate is None else candidate.program_hash,
                reason,
                elapsed(),
            )
            return RankedSearchOutcome(receipt, candidate)

        def close_level() -> RankedSearchOutcome | None:
            if current_level is None:
                return None
            exact = [
                candidate for candidate in level_representatives.values()
                if candidate.training_error == 0
            ]
            completed_levels.append(current_level)
            if exact:
                # The entire level is now known.  MDL is fixed, so hash is the
                # exact remaining declared tie-break.
                selected = min(exact, key=lambda candidate: candidate.program_hash)
                return outcome(
                    level_complete=True,
                    candidate=selected,
                    reason=RankedSearchTermination.EXACT_CANDIDATE_AFTER_COMPLETE_LEVEL,
                )
            return None

        for expression in _ordered_expressions(
            specification, policy, enumeration_order=test_enumeration_order,
        ):
            metrics = expression_metrics(expression, specification)
            node_count = int(metrics["node_count"])
            if current_level is None:
                current_level = node_count
            elif node_count != current_level:
                result = close_level()
                if result is not None:
                    return result
                current_level = node_count
                level_representatives = {}
            if (
                policy.wall_time_limit_seconds is not None
                and elapsed() >= policy.wall_time_limit_seconds * 1_000
            ):
                return outcome(
                    level_complete=False,
                    candidate=None,
                    reason=RankedSearchTermination.RESOURCE_EXHAUSTED_INCOMPLETE_LEVEL,
                )
            if (
                policy.max_raw_ast_evaluations is not None
                and raw_count >= policy.max_raw_ast_evaluations
            ):
                return outcome(
                    level_complete=False,
                    candidate=None,
                    reason=RankedSearchTermination.RESOURCE_EXHAUSTED_INCOMPLETE_LEVEL,
                )
            raw_count += 1
            canonical_count += 1
            behavior, training_error = _behavior_key(expression, specification, training)
            if (
                behavior not in all_behavior_representatives
                and policy.max_distinct_behaviors is not None
                and len(all_behavior_representatives) >= policy.max_distinct_behaviors
            ):
                return outcome(
                    level_complete=False,
                    candidate=None,
                    reason=RankedSearchTermination.RESOURCE_EXHAUSTED_INCOMPLETE_LEVEL,
                )
            candidate = RankedCandidate(
                expression,
                canonical_sha256(expression),
                node_count,
                int(metrics["ast_depth"]),
                behavior,
                training_error,
            )
            # All members of one behavior class have the same TRAIN error
            # whenever they evaluate successfully.  Failed evaluations are
            # also keyed together, so representative choice is precisely the
            # required (MDL, canonical-hash) order and never traversal order.
            representative_rank = (candidate.mdl, candidate.program_hash)
            previous = all_behavior_representatives.get(behavior)
            if previous is None or representative_rank < (
                previous.mdl, previous.program_hash
            ):
                all_behavior_representatives[behavior] = candidate
            previous_level = level_representatives.get(behavior)
            if previous_level is None or representative_rank < (
                previous_level.mdl, previous_level.program_hash
            ):
                level_representatives[behavior] = candidate

        result = close_level()
        if result is not None:
            return result
        return outcome(
            level_complete=True,
            candidate=None,
            reason=RankedSearchTermination.FRONTIER_EXHAUSTED_NO_CANDIDATE,
        )


def exhaustive_reference_search(
    *,
    specification: DSLSpecification,
    training: LearnerTrainingView,
    policy: RankedSearchPolicy,
    test_enumeration_order: str = "CANONICAL",
) -> RankedSearchOutcome:
    """Tiny test oracle: exhaustive, no behavior deduplication in selection.

    It exists solely for bounded test spaces.  Production campaigns must use
    :class:`RankCanonicalProgramSynthesizer`, never this deliberately costly
    reference implementation.
    """

    if policy.max_distinct_behaviors is not None:
        raise ValueError("genesis_reference_oracle_distinct_behavior_cap_unsupported")
    # Reuse the exact policy validation and level/cap semantics, but keep every
    # expression by giving it a unique semantic key until level completion.
    if not specification.validate() or not policy.validate() or not training.training_examples:
        raise ValueError("genesis_reference_oracle_input_invalid")
    started = monotonic()
    raw_count = canonical_count = 0
    behavior_classes: set[BehaviorKey] = set()
    current_level: int | None = None
    completed_levels: list[int] = []
    exact_candidates: list[RankedCandidate] = []

    def elapsed() -> int:
        return int((monotonic() - started) * 1_000)

    def build(
        *, level_complete: bool, candidate: RankedCandidate | None,
        reason: RankedSearchTermination,
    ) -> RankedSearchOutcome:
        receipt = RankedSearchReceipt(
            _RECEIPT_SCHEMA, SEARCH_SEMANTICS_V2_ID,
            RANKED_SYNTHESIZER_IMPLEMENTATION_HASH, policy.policy_hash,
            specification.dsl_hash, training.training_commitment_hash,
            tuple(completed_levels), current_level, level_complete, raw_count,
            canonical_count, len(behavior_classes),
            canonical_count - len(behavior_classes), candidate is not None,
            None if candidate is None else candidate.mdl,
            None if candidate is None else candidate.program_hash, reason, elapsed(),
        )
        return RankedSearchOutcome(receipt, candidate)

    def finish_level() -> RankedSearchOutcome | None:
        if current_level is None:
            return None
        completed_levels.append(current_level)
        if exact_candidates:
            return build(
                level_complete=True,
                candidate=min(exact_candidates, key=lambda candidate: candidate.program_hash),
                reason=RankedSearchTermination.EXACT_CANDIDATE_AFTER_COMPLETE_LEVEL,
            )
        return None

    for expression in _ordered_expressions(
        specification, policy, enumeration_order=test_enumeration_order,
    ):
        metrics = expression_metrics(expression, specification)
        node_count = int(metrics["node_count"])
        if current_level is None:
            current_level = node_count
        elif node_count != current_level:
            result = finish_level()
            if result is not None:
                return result
            current_level = node_count
            exact_candidates = []
        if (
            policy.wall_time_limit_seconds is not None
            and elapsed() >= policy.wall_time_limit_seconds * 1_000
        ) or (
            policy.max_raw_ast_evaluations is not None
            and raw_count >= policy.max_raw_ast_evaluations
        ):
            return build(
                level_complete=False, candidate=None,
                reason=RankedSearchTermination.RESOURCE_EXHAUSTED_INCOMPLETE_LEVEL,
            )
        raw_count += 1
        canonical_count += 1
        behavior, training_error = _behavior_key(expression, specification, training)
        behavior_classes.add(behavior)
        candidate = RankedCandidate(
            expression, canonical_sha256(expression), node_count,
            int(metrics["ast_depth"]), behavior, training_error,
        )
        if candidate.training_error == 0:
            exact_candidates.append(candidate)
    result = finish_level()
    if result is not None:
        return result
    return build(
        level_complete=True, candidate=None,
        reason=RankedSearchTermination.FRONTIER_EXHAUSTED_NO_CANDIDATE,
    )


def replay_ranked_synthesis(
    *,
    specification: DSLSpecification,
    training: LearnerTrainingView,
    policy: RankedSearchPolicy,
    receipt: RankedSearchReceipt,
) -> RankedSearchOutcome:
    """Replay only a v2 ranked receipt; cross-version laundering is rejected."""

    if (
        not isinstance(receipt, RankedSearchReceipt)
        or receipt.search_semantics_id != SEARCH_SEMANTICS_V2_ID
        or receipt.synthesizer_implementation_hash
        != RANKED_SYNTHESIZER_IMPLEMENTATION_HASH
        or receipt.policy_hash != policy.policy_hash
    ):
        raise ValueError("genesis_ranked_synthesis_replay_version_mismatch")
    outcome = RankCanonicalProgramSynthesizer().synthesize(
        specification=specification, training=training, policy=policy,
    )
    if outcome.receipt.semantic_payload() != receipt.semantic_payload():
        raise ValueError("genesis_ranked_synthesis_replay_mismatch")
    return outcome
