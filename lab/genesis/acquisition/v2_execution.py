"""M7-H2B0: version-strict V2 execution and replay substrate.

This module deliberately owns no confirmatory campaign runner.  It accepts
only a non-canonical, toy integration binding and runs the rank-canonical V2
search in a separately supervised process group.  The worker never imports or
instantiates the historical V1 synthesizer.  Its level transcripts are compact
streaming commitments; replay regenerates them rather than trusting counters
or a re-sealed receipt.

The cgroup-v2 hierarchy available in the development environment does not
delegate the memory controller to a child scope.  Consequently this module
uses an external process-group RSS watchdog.  It is intentionally described as
an observed/enforced watchdog, *not* as a kernel-hard memory limit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import multiprocessing
import os
from pathlib import Path
import signal
import time
from typing import Any, Mapping, Sequence

from lab.genesis.acquisition.benchmark import Example, LearnerTrainingView
from lab.genesis.acquisition.confirmation import CANONICAL_CONFIRMATORY_TASK_IDS
from lab.genesis.acquisition.dsl import DSLSpecification, canonical_expression, expression_metrics
from lab.genesis.acquisition.ranked_synthesis import (
    RANKED_SYNTHESIZER_IMPLEMENTATION_HASH,
    SEARCH_SEMANTICS_V2_ID,
    BehaviorKey,
    RankedCandidate,
    RankedSearchPolicy,
    _behavior_key,
    _ordered_expressions,
)
from lab.genesis.contracts.serialization import canonical_sha256, freeze
from lab.genesis.evidence.artifacts import is_artifact_hash


V2_EXECUTION_ADAPTER_IMPLEMENTATION_ID = "genesis-m7-v2-execution-adapter-h2b0"
V2_EXECUTION_ADAPTER_IMPLEMENTATION_HASH = canonical_sha256({
    "implementation": V2_EXECUTION_ADAPTER_IMPLEMENTATION_ID,
    "semantics": SEARCH_SEMANTICS_V2_ID,
    "transcript": "per-level-streaming-digest-v1",
})
_BINDING_SCHEMA = "genesis-m7-v2-execution-binding-h2b0"
_H2B1_BINDING_SCHEMA = "genesis-m7-v2-execution-binding-h2b1"
_H2B1_FIXTURE_BINDING_SCHEMA = "genesis-m7-v2-execution-binding-h2b1-fixture"
_TRANSCRIPT_SCHEMA = "genesis-m7-v2-level-transcript-h2b0"
_RECEIPT_SCHEMA = "genesis-m7-v2-synthesis-execution-receipt-h2b0"
_RESOURCE_SCHEMA = "genesis-m7-v2-resource-envelope-receipt-h2b0"
_STREAM_SCHEMA = "genesis-m7-v2-level-stream-v1"
_WATCHDOG = "PROCESS_GROUP_RSS_WATCHDOG-v1"
_MEMORY_ENFORCEMENT = "EXTERNAL_PROCESS_GROUP_RSS_WATCHDOG_NOT_KERNEL_HARD-v1"
_TIME_ENFORCEMENT = "PARENT_MONOTONIC_WALL_CLOCK_SIGNAL-v1"
_AST_ENFORCEMENT = "V2_WORKER_DISTINCT_RAW_AND_BEHAVIOR_CAPS-v1"


def _require_hash(value: str, reason: str) -> None:
    if not isinstance(value, str) or not is_artifact_hash(value):
        raise ValueError(reason)


def _plain(value: Any) -> Any:
    """Make immutable contract material safe for a multiprocessing pipe."""

    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_plain(item) for item in value)
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def _stream_seed(name: str, level: int) -> str:
    return canonical_sha256({"schema": _STREAM_SCHEMA, "stream": name, "level": level})


def _stream_add(previous: str, value: Any) -> str:
    return canonical_sha256({"previous": previous, "value": value})


def _transcript_root(transcripts: Sequence["V2LevelTranscript"]) -> str:
    return canonical_sha256({
        "schema": _STREAM_SCHEMA,
        "root": tuple(item.transcript_hash for item in transcripts),
    })


class V2ExecutionTermination(str, Enum):
    SELECTED_AFTER_COMPLETE_LEVEL = "SELECTED_AFTER_COMPLETE_LEVEL"
    FRONTIER_EXHAUSTED_NO_CANDIDATE = "FRONTIER_EXHAUSTED_NO_CANDIDATE"
    NOT_PROVEN_RESOURCE_EXHAUSTION = "NOT_PROVEN_RESOURCE_EXHAUSTION"


class ResourceTerminationCause(str, Enum):
    COMPLETED = "COMPLETED"
    RAW_AST_CAP_REACHED = "RAW_AST_CAP_REACHED"
    BEHAVIOR_CAP_REACHED = "BEHAVIOR_CAP_REACHED"
    WALL_TIME_CAP_REACHED = "WALL_TIME_CAP_REACHED"
    MEMORY_CAP_REACHED = "MEMORY_CAP_REACHED"
    WORKER_TERMINATED_WITHOUT_RECEIPT = "WORKER_TERMINATED_WITHOUT_RECEIPT"


@dataclass(frozen=True, slots=True)
class V2ExecutionBinding:
    """All identities that a V2 execution must bind before enumeration."""

    schema_version: str
    campaign_id: str
    task_id: str
    campaign_hash: str
    task_binding_hash: str
    acceptance_policy_hash: str
    battery_manifest_hash: str
    search_policy_hash: str
    ranked_engine_policy: RankedSearchPolicy
    dsl_hash: str
    search_semantics_id: str
    search_implementation_id: str
    search_implementation_hash: str
    max_mdl: int
    max_depth: int
    max_nodes: int
    max_raw_ast_evaluations: int
    max_distinct_behaviors: int
    max_wall_time_seconds: int
    max_peak_memory_mib: int
    integration_scope: str = "H2B0_TOY_ONLY"
    binding_hash: str = field(init=False)

    def __post_init__(self) -> None:
        h2b0_scope = self.schema_version == _BINDING_SCHEMA and self.integration_scope == "H2B0_TOY_ONLY"
        h2b1_scope = self.schema_version == _H2B1_BINDING_SCHEMA and self.integration_scope == "H2B1_CONFIRMATORY_FROZEN"
        fixture_scope = self.schema_version == _H2B1_FIXTURE_BINDING_SCHEMA and self.integration_scope == "H2B1_NONCANONICAL_FIXTURE"
        if (
            not (h2b0_scope or h2b1_scope or fixture_scope)
            or not self.campaign_id
            or not self.task_id
            or self.search_semantics_id != SEARCH_SEMANTICS_V2_ID
            or self.search_implementation_id
            != "genesis-m7-rank-canonical-enumerative-synthesizer-v2"
            or self.search_implementation_hash != RANKED_SYNTHESIZER_IMPLEMENTATION_HASH
        ):
            raise ValueError("genesis_v2_execution_binding_identity_invalid")
        if h2b0_scope and (
            self.campaign_id in CANONICAL_CONFIRMATORY_TASK_IDS
            or self.campaign_id.startswith("m7h2-confirmatory-")
        ):
            raise ValueError("genesis_v2_execution_binding_identity_invalid")
        if h2b1_scope and (
            self.task_id not in CANONICAL_CONFIRMATORY_TASK_IDS
            or self.campaign_id != f"m7h2-confirmatory-{self.task_id}"
        ):
            raise ValueError("genesis_v2_execution_binding_identity_invalid")
        if fixture_scope and self.campaign_id.startswith("m7h2-confirmatory-"):
            raise ValueError("genesis_v2_execution_binding_identity_invalid")
        for value in (
            self.campaign_hash, self.task_binding_hash, self.acceptance_policy_hash,
            self.battery_manifest_hash, self.search_policy_hash, self.dsl_hash,
        ):
            _require_hash(value, "genesis_v2_execution_binding_hash_invalid")
        if not self.ranked_engine_policy.validate() or self.ranked_engine_policy.dsl_hash != self.dsl_hash:
            raise ValueError("genesis_v2_execution_binding_engine_policy_invalid")
        for value in (
            self.max_mdl, self.max_depth, self.max_nodes,
            self.max_raw_ast_evaluations, self.max_distinct_behaviors,
            self.max_wall_time_seconds, self.max_peak_memory_mib,
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError("genesis_v2_execution_binding_limit_invalid")
        policy = self.ranked_engine_policy
        if (
            self.max_mdl != self.max_nodes
            or policy.max_ast_nodes != self.max_nodes
            or policy.max_ast_depth != self.max_depth
            or policy.max_raw_ast_evaluations != self.max_raw_ast_evaluations
            or policy.max_distinct_behaviors != self.max_distinct_behaviors
            or policy.wall_time_limit_seconds != self.max_wall_time_seconds
        ):
            raise ValueError("genesis_v2_execution_binding_policy_limits_invalid")
        object.__setattr__(self, "binding_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "campaign_id": self.campaign_id,
            "task_id": self.task_id,
            "campaign_hash": self.campaign_hash,
            "task_binding_hash": self.task_binding_hash,
            "acceptance_policy_hash": self.acceptance_policy_hash,
            "battery_manifest_hash": self.battery_manifest_hash,
            "search_policy_hash": self.search_policy_hash,
            "ranked_engine_policy": self.ranked_engine_policy.canonical_payload(),
            "dsl_hash": self.dsl_hash,
            "search_semantics_id": self.search_semantics_id,
            "search_implementation_id": self.search_implementation_id,
            "search_implementation_hash": self.search_implementation_hash,
            "max_mdl": self.max_mdl,
            "max_depth": self.max_depth,
            "max_nodes": self.max_nodes,
            "max_raw_ast_evaluations": self.max_raw_ast_evaluations,
            "max_distinct_behaviors": self.max_distinct_behaviors,
            "max_wall_time_seconds": self.max_wall_time_seconds,
            "max_peak_memory_mib": self.max_peak_memory_mib,
            "integration_scope": self.integration_scope,
        }

    def validate(self) -> bool:
        try:
            payload = self.canonical_payload()
            payload["ranked_engine_policy"] = RankedSearchPolicy(**payload["ranked_engine_policy"])
            return V2ExecutionBinding(**payload).binding_hash == self.binding_hash
        except (TypeError, ValueError):
            return False

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "V2ExecutionBinding":
        values = dict(payload)
        values["ranked_engine_policy"] = RankedSearchPolicy(**values["ranked_engine_policy"])
        return cls(**values)


@dataclass(frozen=True, slots=True)
class V2LevelTranscript:
    """One compact, rederivable MDL-level account of native V2 search."""

    schema_version: str
    campaign_hash: str
    task_binding_hash: str
    search_semantics_id: str
    search_policy_hash: str
    ranked_engine_policy_hash: str
    mdl_level: int
    level_started: bool
    level_complete: bool
    raw_ast_count_delta: int
    raw_ast_count_cumulative: int
    behavior_classes_delta: int
    behavior_classes_cumulative: int
    dedup_count_delta: int
    dedup_count_cumulative: int
    exact_candidate_count: int
    selected_candidate_hash: str | None
    enumeration_digest: str
    representative_set_digest: str
    exact_candidate_set_digest: str
    event_status: str
    transcript_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            self.schema_version != _TRANSCRIPT_SCHEMA
            or self.search_semantics_id != SEARCH_SEMANTICS_V2_ID
            or not self.level_started
            or not isinstance(self.mdl_level, int)
            or self.mdl_level <= 0
        ):
            raise ValueError("genesis_v2_level_transcript_identity_invalid")
        for value in (
            self.campaign_hash, self.task_binding_hash, self.search_policy_hash,
            self.ranked_engine_policy_hash, self.enumeration_digest,
            self.representative_set_digest, self.exact_candidate_set_digest,
        ):
            _require_hash(value, "genesis_v2_level_transcript_hash_invalid")
        for value in (
            self.raw_ast_count_delta, self.raw_ast_count_cumulative,
            self.behavior_classes_delta, self.behavior_classes_cumulative,
            self.dedup_count_delta, self.dedup_count_cumulative,
            self.exact_candidate_count,
        ):
            if not isinstance(value, int) or value < 0:
                raise ValueError("genesis_v2_level_transcript_counter_invalid")
        if (
            self.raw_ast_count_delta < self.behavior_classes_delta
            or self.dedup_count_delta != self.raw_ast_count_delta - self.behavior_classes_delta
            or self.dedup_count_cumulative
            != self.raw_ast_count_cumulative - self.behavior_classes_cumulative
            or self.behavior_classes_cumulative > self.raw_ast_count_cumulative
            or self.event_status not in {
                "LEVEL_COMPLETED_NO_EXACT",
                "EXACT_CANDIDATE_AFTER_COMPLETE_LEVEL",
                "RESOURCE_EXHAUSTED_INCOMPLETE_LEVEL",
            }
            or (self.level_complete and self.event_status == "RESOURCE_EXHAUSTED_INCOMPLETE_LEVEL")
            or (not self.level_complete and self.event_status != "RESOURCE_EXHAUSTED_INCOMPLETE_LEVEL")
        ):
            raise ValueError("genesis_v2_level_transcript_semantics_invalid")
        if self.selected_candidate_hash is not None:
            _require_hash(self.selected_candidate_hash, "genesis_v2_level_transcript_candidate_invalid")
            if not self.level_complete or self.event_status != "EXACT_CANDIDATE_AFTER_COMPLETE_LEVEL":
                raise ValueError("genesis_v2_level_transcript_selection_invalid")
        elif self.event_status == "EXACT_CANDIDATE_AFTER_COMPLETE_LEVEL":
            raise ValueError("genesis_v2_level_transcript_selection_missing")
        object.__setattr__(self, "transcript_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "campaign_hash": self.campaign_hash,
            "task_binding_hash": self.task_binding_hash,
            "search_semantics_id": self.search_semantics_id,
            "search_policy_hash": self.search_policy_hash,
            "ranked_engine_policy_hash": self.ranked_engine_policy_hash,
            "mdl_level": self.mdl_level,
            "level_started": self.level_started,
            "level_complete": self.level_complete,
            "raw_ast_count_delta": self.raw_ast_count_delta,
            "raw_ast_count_cumulative": self.raw_ast_count_cumulative,
            "behavior_classes_delta": self.behavior_classes_delta,
            "behavior_classes_cumulative": self.behavior_classes_cumulative,
            "dedup_count_delta": self.dedup_count_delta,
            "dedup_count_cumulative": self.dedup_count_cumulative,
            "exact_candidate_count": self.exact_candidate_count,
            "selected_candidate_hash": self.selected_candidate_hash,
            "enumeration_digest": self.enumeration_digest,
            "representative_set_digest": self.representative_set_digest,
            "exact_candidate_set_digest": self.exact_candidate_set_digest,
            "event_status": self.event_status,
        }

    def validate(self) -> bool:
        try:
            return V2LevelTranscript(**self.canonical_payload()).transcript_hash == self.transcript_hash
        except (TypeError, ValueError):
            return False


@dataclass(frozen=True, slots=True)
class V2ResourceReceipt:
    """Observed external envelope data; timing/RSS are not replay-equality data."""

    schema_version: str
    execution_binding_hash: str
    enforcement_mechanism: str
    memory_enforcement: str
    time_enforcement: str
    ast_cap_enforcement: str
    configured_raw_ast_cap: int
    configured_behavior_cap: int
    configured_wall_time_seconds: int
    configured_peak_memory_mib: int
    search_pid: int | None
    process_group_id: int | None
    wall_elapsed_milliseconds: int
    peak_observed_memory_bytes: int
    raw_ast_count: int
    behavior_class_count: int
    termination_cause: ResourceTerminationCause
    receipt_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            self.schema_version != _RESOURCE_SCHEMA
            or self.enforcement_mechanism != _WATCHDOG
            or self.memory_enforcement != _MEMORY_ENFORCEMENT
            or self.time_enforcement != _TIME_ENFORCEMENT
            or self.ast_cap_enforcement != _AST_ENFORCEMENT
        ):
            raise ValueError("genesis_v2_resource_receipt_identity_invalid")
        _require_hash(self.execution_binding_hash, "genesis_v2_resource_receipt_binding_invalid")
        for value in (
            self.configured_raw_ast_cap, self.configured_behavior_cap,
            self.configured_wall_time_seconds, self.configured_peak_memory_mib,
            self.wall_elapsed_milliseconds, self.peak_observed_memory_bytes,
            self.raw_ast_count, self.behavior_class_count,
        ):
            if not isinstance(value, int) or value < 0:
                raise ValueError("genesis_v2_resource_receipt_counter_invalid")
        if not all(value > 0 for value in (
            self.configured_raw_ast_cap, self.configured_behavior_cap,
            self.configured_wall_time_seconds, self.configured_peak_memory_mib,
        )) or self.behavior_class_count > self.raw_ast_count:
            raise ValueError("genesis_v2_resource_receipt_cap_invalid")
        for value in (self.search_pid, self.process_group_id):
            if value is not None and (not isinstance(value, int) or value <= 0):
                raise ValueError("genesis_v2_resource_receipt_process_invalid")
        object.__setattr__(self, "termination_cause", ResourceTerminationCause(self.termination_cause))
        object.__setattr__(self, "receipt_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "execution_binding_hash": self.execution_binding_hash,
            "enforcement_mechanism": self.enforcement_mechanism,
            "memory_enforcement": self.memory_enforcement,
            "time_enforcement": self.time_enforcement,
            "ast_cap_enforcement": self.ast_cap_enforcement,
            "configured_raw_ast_cap": self.configured_raw_ast_cap,
            "configured_behavior_cap": self.configured_behavior_cap,
            "configured_wall_time_seconds": self.configured_wall_time_seconds,
            "configured_peak_memory_mib": self.configured_peak_memory_mib,
            "search_pid": self.search_pid,
            "process_group_id": self.process_group_id,
            "wall_elapsed_milliseconds": self.wall_elapsed_milliseconds,
            "peak_observed_memory_bytes": self.peak_observed_memory_bytes,
            "raw_ast_count": self.raw_ast_count,
            "behavior_class_count": self.behavior_class_count,
            "termination_cause": self.termination_cause.value,
        }

    def validate(self) -> bool:
        try:
            return V2ResourceReceipt(**self.canonical_payload()).receipt_hash == self.receipt_hash
        except (TypeError, ValueError):
            return False


@dataclass(frozen=True, slots=True)
class V2SynthesisReceipt:
    """V2-only result receipt, structurally distinct from historical V1 receipts."""

    schema_version: str
    execution_binding_hash: str
    campaign_hash: str
    task_binding_hash: str
    search_semantics_id: str
    search_implementation_id: str
    search_implementation_hash: str
    search_policy_hash: str
    ranked_engine_policy_hash: str
    acceptance_policy_hash: str
    battery_manifest_hash: str
    dsl_hash: str
    max_mdl: int
    max_depth: int
    max_nodes: int
    completed_levels: tuple[int, ...]
    current_level: int | None
    current_level_complete: bool
    raw_ast_count: int
    behavior_class_count: int
    dedup_count: int
    selected_candidate_ast: Mapping[str, Any] | None
    selected_candidate_hash: str | None
    selected_candidate_mdl: int | None
    termination_reason: V2ExecutionTermination
    level_transcript_root: str
    resource_receipt_hash: str
    receipt_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            self.schema_version != _RECEIPT_SCHEMA
            or self.search_semantics_id != SEARCH_SEMANTICS_V2_ID
            or self.search_implementation_id
            != "genesis-m7-rank-canonical-enumerative-synthesizer-v2"
            or self.search_implementation_hash != RANKED_SYNTHESIZER_IMPLEMENTATION_HASH
        ):
            raise ValueError("genesis_v2_synthesis_receipt_identity_invalid")
        for value in (
            self.execution_binding_hash, self.campaign_hash, self.task_binding_hash,
            self.search_policy_hash, self.ranked_engine_policy_hash,
            self.acceptance_policy_hash, self.battery_manifest_hash, self.dsl_hash,
            self.level_transcript_root, self.resource_receipt_hash,
        ):
            _require_hash(value, "genesis_v2_synthesis_receipt_hash_invalid")
        levels = tuple(sorted(set(self.completed_levels)))
        if levels != self.completed_levels or any(level <= 0 for level in levels):
            raise ValueError("genesis_v2_synthesis_receipt_levels_invalid")
        for value in (self.max_mdl, self.max_depth, self.max_nodes, self.raw_ast_count, self.behavior_class_count, self.dedup_count):
            if not isinstance(value, int) or value < 0:
                raise ValueError("genesis_v2_synthesis_receipt_counter_invalid")
        if (
            self.max_mdl <= 0 or self.max_depth <= 0 or self.max_nodes <= 0
            or self.max_mdl != self.max_nodes
            or self.behavior_class_count > self.raw_ast_count
            or self.dedup_count != self.raw_ast_count - self.behavior_class_count
            or (self.current_level is not None and self.current_level <= 0)
        ):
            raise ValueError("genesis_v2_synthesis_receipt_semantics_invalid")
        object.__setattr__(self, "termination_reason", V2ExecutionTermination(self.termination_reason))
        candidate_fields = (
            self.selected_candidate_ast, self.selected_candidate_hash, self.selected_candidate_mdl,
        )
        if self.termination_reason is V2ExecutionTermination.SELECTED_AFTER_COMPLETE_LEVEL:
            if (
                any(value is None for value in candidate_fields)
                or self.current_level != self.selected_candidate_mdl
                or self.selected_candidate_mdl not in levels
                or not self.current_level_complete
                or self.selected_candidate_mdl != levels[-1]
            ):
                raise ValueError("genesis_v2_synthesis_receipt_candidate_invalid")
            ast = freeze(self.selected_candidate_ast)
            object.__setattr__(self, "selected_candidate_ast", ast)
            if self.selected_candidate_hash != canonical_sha256(ast):
                raise ValueError("genesis_v2_synthesis_receipt_candidate_hash_invalid")
        elif any(value is not None for value in candidate_fields):
            raise ValueError("genesis_v2_synthesis_receipt_absent_candidate_invalid")
        if (
            self.termination_reason is V2ExecutionTermination.NOT_PROVEN_RESOURCE_EXHAUSTION
            and self.current_level_complete
        ):
            raise ValueError("genesis_v2_synthesis_receipt_partial_level_invalid")
        object.__setattr__(self, "receipt_hash", canonical_sha256(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "execution_binding_hash": self.execution_binding_hash,
            "campaign_hash": self.campaign_hash,
            "task_binding_hash": self.task_binding_hash,
            "search_semantics_id": self.search_semantics_id,
            "search_implementation_id": self.search_implementation_id,
            "search_implementation_hash": self.search_implementation_hash,
            "search_policy_hash": self.search_policy_hash,
            "ranked_engine_policy_hash": self.ranked_engine_policy_hash,
            "acceptance_policy_hash": self.acceptance_policy_hash,
            "battery_manifest_hash": self.battery_manifest_hash,
            "dsl_hash": self.dsl_hash,
            "max_mdl": self.max_mdl,
            "max_depth": self.max_depth,
            "max_nodes": self.max_nodes,
            "completed_levels": self.completed_levels,
            "current_level": self.current_level,
            "current_level_complete": self.current_level_complete,
            "raw_ast_count": self.raw_ast_count,
            "behavior_class_count": self.behavior_class_count,
            "dedup_count": self.dedup_count,
            "selected_candidate_ast": self.selected_candidate_ast,
            "selected_candidate_hash": self.selected_candidate_hash,
            "selected_candidate_mdl": self.selected_candidate_mdl,
            "termination_reason": self.termination_reason.value,
            "level_transcript_root": self.level_transcript_root,
            "resource_receipt_hash": self.resource_receipt_hash,
        }

    def semantic_payload(self) -> dict[str, Any]:
        payload = self.canonical_payload()
        del payload["resource_receipt_hash"]
        return payload

    def validate(self) -> bool:
        try:
            return V2SynthesisReceipt(**self.canonical_payload()).receipt_hash == self.receipt_hash
        except (TypeError, ValueError):
            return False


@dataclass(frozen=True, slots=True)
class V2ExecutionOutcome:
    receipt: V2SynthesisReceipt
    resource_receipt: V2ResourceReceipt
    level_transcripts: tuple[V2LevelTranscript, ...]
    selected_candidate: RankedCandidate | None


class _ExternalLimitReached(Exception):
    def __init__(self, cause: ResourceTerminationCause) -> None:
        self.cause = cause


@dataclass(slots=True)
class _NativeSearchResult:
    transcripts: list[V2LevelTranscript]
    selected_candidate: RankedCandidate | None
    completed_levels: list[int]
    current_level: int | None
    current_level_complete: bool
    raw_ast_count: int
    behavior_class_count: int
    termination: V2ExecutionTermination
    cause: ResourceTerminationCause


def _transcript(
    *, binding: V2ExecutionBinding, level: int, level_complete: bool,
    raw_before: int, raw_count: int, behaviors_before: int,
    representatives: Mapping[BehaviorKey, RankedCandidate], exact: Sequence[RankedCandidate],
    enumeration_digest: str, selected: RankedCandidate | None,
) -> V2LevelTranscript:
    behavior_count = len(representatives)
    raw_delta = raw_count - raw_before
    behavior_delta = behavior_count - behaviors_before
    exact_hashes = tuple(sorted(candidate.program_hash for candidate in exact))
    representative_payload = tuple(sorted(
        (
            canonical_sha256({"behavior": behavior}),
            candidate.mdl,
            candidate.program_hash,
        )
        for behavior, candidate in representatives.items()
    ))
    event = (
        "EXACT_CANDIDATE_AFTER_COMPLETE_LEVEL" if selected is not None
        else "LEVEL_COMPLETED_NO_EXACT" if level_complete
        else "RESOURCE_EXHAUSTED_INCOMPLETE_LEVEL"
    )
    return V2LevelTranscript(
        _TRANSCRIPT_SCHEMA, binding.campaign_hash, binding.task_binding_hash,
        SEARCH_SEMANTICS_V2_ID, binding.search_policy_hash,
        binding.ranked_engine_policy.policy_hash, level, True, level_complete,
        raw_delta, raw_count, behavior_delta, behavior_count,
        raw_delta - behavior_delta, raw_count - behavior_count, len(exact_hashes),
        None if selected is None else selected.program_hash, enumeration_digest,
        canonical_sha256({"representatives": representative_payload}),
        canonical_sha256({"exact_candidate_hashes": exact_hashes}), event,
    )


def _run_native_v2_search(
    *, binding: V2ExecutionBinding, specification: DSLSpecification,
    training: LearnerTrainingView, stop_after_raw: int | None = None,
    step_delay_seconds: float = 0.0,
) -> _NativeSearchResult:
    """Run the H1 rank-canonical algorithm while committing every MDL level.

    This is intentionally V2-native rather than a wrapper around the V1
    campaign pipeline.  Its representative update rule is the same declared
    ``(MDL, canonical_hash)`` argmin used by the frozen H1 search semantics.
    """

    if not (
        binding.validate() and specification.validate()
        and specification.dsl_hash == binding.dsl_hash
        and training.task_id == binding.task_id
        and training.training_examples
    ):
        raise ValueError("genesis_v2_execution_native_input_invalid")
    policy = binding.ranked_engine_policy
    all_representatives: dict[BehaviorKey, RankedCandidate] = {}
    level_representatives: dict[BehaviorKey, RankedCandidate] = {}
    level_exact: list[RankedCandidate] = []
    transcripts: list[V2LevelTranscript] = []
    completed_levels: list[int] = []
    raw_count = 0
    current_level: int | None = None
    level_raw_before = 0
    level_behaviors_before = 0
    enumeration_digest = ""

    def partial(cause: ResourceTerminationCause) -> _NativeSearchResult:
        if current_level is not None:
            transcripts.append(_transcript(
                binding=binding, level=current_level, level_complete=False,
                raw_before=level_raw_before, raw_count=raw_count,
                behaviors_before=level_behaviors_before,
                representatives=all_representatives, exact=level_exact,
                enumeration_digest=enumeration_digest, selected=None,
            ))
        return _NativeSearchResult(
            transcripts, None, completed_levels, current_level, False, raw_count,
            len(all_representatives), V2ExecutionTermination.NOT_PROVEN_RESOURCE_EXHAUSTION,
            cause,
        )

    def close_level() -> _NativeSearchResult | None:
        if current_level is None:
            return None
        selected = None
        if level_exact:
            selected = min(level_exact, key=lambda candidate: candidate.program_hash)
        transcripts.append(_transcript(
            binding=binding, level=current_level, level_complete=True,
            raw_before=level_raw_before, raw_count=raw_count,
            behaviors_before=level_behaviors_before,
            representatives=all_representatives, exact=level_exact,
            enumeration_digest=enumeration_digest, selected=selected,
        ))
        completed_levels.append(current_level)
        if selected is not None:
            return _NativeSearchResult(
                transcripts, selected, completed_levels, current_level, True, raw_count,
                len(all_representatives), V2ExecutionTermination.SELECTED_AFTER_COMPLETE_LEVEL,
                ResourceTerminationCause.COMPLETED,
            )
        return None

    try:
        for expression in _ordered_expressions(specification, policy, enumeration_order="CANONICAL"):
            metrics = expression_metrics(expression, specification)
            node_count = int(metrics["node_count"])
            if current_level is None:
                current_level = node_count
                level_raw_before = raw_count
                level_behaviors_before = len(all_representatives)
                enumeration_digest = _stream_seed("enumeration", current_level)
            elif node_count != current_level:
                closed = close_level()
                if closed is not None:
                    return closed
                current_level = node_count
                level_raw_before = raw_count
                level_behaviors_before = len(all_representatives)
                level_representatives = {}
                level_exact = []
                enumeration_digest = _stream_seed("enumeration", current_level)
            if stop_after_raw is not None and raw_count >= stop_after_raw:
                return partial(ResourceTerminationCause.WALL_TIME_CAP_REACHED)
            if raw_count >= binding.max_raw_ast_evaluations:
                return partial(ResourceTerminationCause.RAW_AST_CAP_REACHED)
            if step_delay_seconds:
                time.sleep(step_delay_seconds)
            raw_count += 1
            program_hash = canonical_sha256(expression)
            enumeration_digest = _stream_add(enumeration_digest, program_hash)
            behavior, training_error = _behavior_key(expression, specification, training)
            if (
                behavior not in all_representatives
                and len(all_representatives) >= binding.max_distinct_behaviors
            ):
                return partial(ResourceTerminationCause.BEHAVIOR_CAP_REACHED)
            candidate = RankedCandidate(
                expression, program_hash, node_count, int(metrics["ast_depth"]),
                behavior, training_error,
            )
            rank = (candidate.mdl, candidate.program_hash)
            previous = all_representatives.get(behavior)
            if previous is None or rank < (previous.mdl, previous.program_hash):
                all_representatives[behavior] = candidate
            previous_level = level_representatives.get(behavior)
            if previous_level is None or rank < (previous_level.mdl, previous_level.program_hash):
                level_representatives[behavior] = candidate
            if candidate.training_error == 0:
                level_exact.append(candidate)
    except _ExternalLimitReached as interruption:
        return partial(interruption.cause)

    closed = close_level()
    if closed is not None:
        return closed
    return _NativeSearchResult(
        transcripts, None, completed_levels, current_level, True, raw_count,
        len(all_representatives), V2ExecutionTermination.FRONTIER_EXHAUSTED_NO_CANDIDATE,
        ResourceTerminationCause.COMPLETED,
    )


def _worker(payload: Mapping[str, Any], connection: Any) -> None:
    """Child worker.  The only search implementation imported here is V2."""

    try:
        os.setsid()

        # This is an H2B0 test-only instrument.  It is deliberately absent
        # from normal execution, where this module never imports V1.  With a
        # spawned worker it proves that an accidental V1 dispatch would fail
        # inside the actual child process rather than merely in its parent.
        if payload.get("test_v1_synthesis_tripwire"):
            from lab.genesis.acquisition.synthesis import DeterministicProgramSynthesizer

            def v1_must_not_run(*_args: Any, **_kwargs: Any) -> None:
                raise AssertionError("genesis_v2_execution_v1_path_touched")

            DeterministicProgramSynthesizer.synthesize = v1_must_not_run

        def interrupt(signum: int, _frame: Any) -> None:
            cause = (
                ResourceTerminationCause.WALL_TIME_CAP_REACHED
                if signum == signal.SIGUSR1
                else ResourceTerminationCause.MEMORY_CAP_REACHED
            )
            raise _ExternalLimitReached(cause)

        signal.signal(signal.SIGUSR1, interrupt)
        signal.signal(signal.SIGUSR2, interrupt)
        binding = V2ExecutionBinding.from_payload(payload["binding"])
        specification = DSLSpecification.from_payload(payload["specification"])
        training = LearnerTrainingView(
            payload["training"]["task_id"],
            tuple(Example(**item) for item in payload["training"]["examples"]),
            payload["training"]["commitment_hash"],
        )
        # The supervisor starts the committed search-only wall clock only
        # after reconstruction is complete and immediately before enumeration.
        connection.send({"kind": "ready"})
        result = _run_native_v2_search(
            binding=binding, specification=specification, training=training,
            step_delay_seconds=float(payload.get("test_step_delay_seconds", 0.0)),
        )
        connection.send({
            "kind": "result",
            "transcripts": tuple(_plain(item.canonical_payload()) for item in result.transcripts),
            "selected": None if result.selected_candidate is None else {
                "program_ast": _plain(result.selected_candidate.program_ast),
                "program_hash": result.selected_candidate.program_hash,
                "mdl": result.selected_candidate.mdl,
                "ast_depth": result.selected_candidate.ast_depth,
                "behavior_key": result.selected_candidate.behavior_key,
                "training_error": result.selected_candidate.training_error,
            },
            "completed_levels": tuple(result.completed_levels),
            "current_level": result.current_level,
            "current_level_complete": result.current_level_complete,
            "raw_ast_count": result.raw_ast_count,
            "behavior_class_count": result.behavior_class_count,
            "termination": result.termination.value,
            "cause": result.cause.value,
        })
    except BaseException as error:  # pragma: no cover - tested from supervisor boundary
        connection.send({"kind": "error", "type": type(error).__name__, "message": str(error)})
    finally:
        connection.close()


def _process_group_rss_bytes(process_group_id: int) -> int:
    """Best-effort RSS over the child process group, including descendants."""

    total = 0
    page_size = os.sysconf("SC_PAGE_SIZE")
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat_fields = (entry / "stat").read_text().split()
            if len(stat_fields) < 5 or int(stat_fields[4]) != process_group_id:
                continue
            resident = int((entry / "statm").read_text().split()[1])
        except (FileNotFoundError, PermissionError, IndexError, ValueError):
            continue
        total += resident * page_size
    # A very short-lived child can finish before ``setsid`` becomes visible to
    # the first parent poll.  Its leader PID is still the process-group ID we
    # assigned, so retain a direct-leader sample instead of falsely recording
    # zero observed RSS.
    if total == 0:
        try:
            total = int((Path("/proc") / str(process_group_id) / "statm").read_text().split()[1]) * page_size
        except (FileNotFoundError, PermissionError, IndexError, ValueError):
            pass
    return total


def _resource_receipt(
    *, binding: V2ExecutionBinding, pid: int | None, elapsed_ms: int,
    peak_memory: int, raw_count: int, behavior_count: int,
    cause: ResourceTerminationCause,
) -> V2ResourceReceipt:
    return V2ResourceReceipt(
        _RESOURCE_SCHEMA, binding.binding_hash, _WATCHDOG, _MEMORY_ENFORCEMENT,
        _TIME_ENFORCEMENT, _AST_ENFORCEMENT, binding.max_raw_ast_evaluations,
        binding.max_distinct_behaviors, binding.max_wall_time_seconds,
        binding.max_peak_memory_mib, pid, pid, elapsed_ms, peak_memory, raw_count,
        behavior_count, cause,
    )


def _signal_worker(process: multiprocessing.Process, pid: int, sig: int) -> None:
    """Signal the isolated group, with a narrow pre-``setsid`` fallback."""

    try:
        os.killpg(pid, sig)
    except ProcessLookupError:
        if process.is_alive():
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass


def _make_receipt(
    *, binding: V2ExecutionBinding, resource: V2ResourceReceipt,
    transcripts: Sequence[V2LevelTranscript], selected: RankedCandidate | None,
    completed_levels: Sequence[int], current_level: int | None,
    current_level_complete: bool, raw_count: int, behavior_count: int,
    termination: V2ExecutionTermination,
) -> V2SynthesisReceipt:
    return V2SynthesisReceipt(
        _RECEIPT_SCHEMA, binding.binding_hash, binding.campaign_hash,
        binding.task_binding_hash, SEARCH_SEMANTICS_V2_ID,
        "genesis-m7-rank-canonical-enumerative-synthesizer-v2",
        RANKED_SYNTHESIZER_IMPLEMENTATION_HASH, binding.search_policy_hash,
        binding.ranked_engine_policy.policy_hash, binding.acceptance_policy_hash,
        binding.battery_manifest_hash, binding.dsl_hash, binding.max_mdl,
        binding.max_depth, binding.max_nodes, tuple(completed_levels), current_level,
        current_level_complete, raw_count, behavior_count, raw_count - behavior_count,
        None if selected is None else selected.program_ast,
        None if selected is None else selected.program_hash,
        None if selected is None else selected.mdl, termination,
        _transcript_root(transcripts), resource.receipt_hash,
    )


def _outcome_from_worker(
    *, binding: V2ExecutionBinding, message: Mapping[str, Any], resource: V2ResourceReceipt,
) -> V2ExecutionOutcome:
    if message.get("kind") != "result":
        raise ValueError("genesis_v2_execution_worker_failed")
    transcripts = tuple(V2LevelTranscript(**item) for item in message["transcripts"])
    selected_payload = message["selected"]
    selected = None if selected_payload is None else RankedCandidate(**selected_payload)
    receipt = _make_receipt(
        binding=binding, resource=resource, transcripts=transcripts, selected=selected,
        completed_levels=tuple(message["completed_levels"]), current_level=message["current_level"],
        current_level_complete=bool(message["current_level_complete"]),
        raw_count=int(message["raw_ast_count"]), behavior_count=int(message["behavior_class_count"]),
        termination=V2ExecutionTermination(message["termination"]),
    )
    outcome = V2ExecutionOutcome(receipt, resource, transcripts, selected)
    if not validate_v2_execution_outcome(binding=binding, outcome=outcome):
        raise ValueError("genesis_v2_execution_worker_outcome_invalid")
    return outcome


def run_v2_execution(
    *, binding: V2ExecutionBinding, specification: DSLSpecification,
    training: LearnerTrainingView, test_step_delay_seconds: float = 0.0,
    test_v1_synthesis_tripwire: bool = False,
) -> V2ExecutionOutcome:
    """Execute a version-valid native V2 binding under the H2B0 supervisor."""

    if (
        not binding.validate() or not specification.validate()
        or binding.dsl_hash != specification.dsl_hash or training.task_id != binding.task_id
        or test_step_delay_seconds < 0
    ):
        raise ValueError("genesis_v2_execution_adapter_input_invalid")
    # ``spawn`` avoids inheriting unrelated threads/allocations from a host
    # process and gives the resource watchdog a clean child boundary.
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    payload = {
        "binding": _plain(binding.canonical_payload()),
        "specification": _plain(specification.canonical_payload()),
        "training": {
            "task_id": training.task_id,
            "examples": tuple(item.canonical_payload() for item in training.training_examples),
            "commitment_hash": training.training_commitment_hash,
        },
        "test_step_delay_seconds": test_step_delay_seconds,
        "test_v1_synthesis_tripwire": test_v1_synthesis_tripwire,
    }
    process = context.Process(target=_worker, args=(payload, child), daemon=True)
    spawned = time.monotonic()
    started: float | None = None
    process.start()
    child.close()
    pid = process.pid
    if pid is None:
        raise RuntimeError("genesis_v2_execution_worker_pid_missing")
    memory_cap = binding.max_peak_memory_mib * 1024 * 1024
    peak_memory = 0
    forced_cause: ResourceTerminationCause | None = None
    message: Mapping[str, Any] | None = None
    signal_deadline: float | None = None
    try:
        while True:
            now = time.monotonic()
            peak_memory = max(peak_memory, _process_group_rss_bytes(pid))
            if parent.poll(0.01):
                message = parent.recv()
                if message.get("kind") == "ready":
                    started = time.monotonic()
                    message = None
                    continue
                break
            if not process.is_alive():
                break
            if forced_cause is None and started is not None:
                if peak_memory > memory_cap:
                    forced_cause = ResourceTerminationCause.MEMORY_CAP_REACHED
                    _signal_worker(process, pid, signal.SIGUSR2)
                    signal_deadline = now + 1.0
                elif now - started >= binding.max_wall_time_seconds:
                    forced_cause = ResourceTerminationCause.WALL_TIME_CAP_REACHED
                    _signal_worker(process, pid, signal.SIGUSR1)
                    signal_deadline = now + 1.0
            elif signal_deadline is not None and now >= signal_deadline:
                _signal_worker(process, pid, signal.SIGKILL)
                break
        process.join(timeout=1.0)
    finally:
        if process.is_alive():
            _signal_worker(process, pid, signal.SIGKILL)
            process.join(timeout=1.0)
        parent.close()
    elapsed_ms = int((time.monotonic() - (started or spawned)) * 1_000)
    if message is not None and message.get("kind") == "result":
        cause = ResourceTerminationCause(message["cause"])
        resource = _resource_receipt(
            binding=binding, pid=pid, elapsed_ms=elapsed_ms, peak_memory=peak_memory,
            raw_count=int(message["raw_ast_count"]),
            behavior_count=int(message["behavior_class_count"]), cause=cause,
        )
        return _outcome_from_worker(binding=binding, message=message, resource=resource)
    cause = forced_cause or ResourceTerminationCause.WORKER_TERMINATED_WITHOUT_RECEIPT
    resource = _resource_receipt(
        binding=binding, pid=pid, elapsed_ms=elapsed_ms, peak_memory=peak_memory,
        raw_count=0, behavior_count=0, cause=cause,
    )
    receipt = _make_receipt(
        binding=binding, resource=resource, transcripts=(), selected=None,
        completed_levels=(), current_level=None, current_level_complete=False,
        raw_count=0, behavior_count=0,
        termination=V2ExecutionTermination.NOT_PROVEN_RESOURCE_EXHAUSTION,
    )
    return V2ExecutionOutcome(receipt, resource, (), None)


def run_v2_toy_execution(
    *, binding: V2ExecutionBinding, specification: DSLSpecification,
    training: LearnerTrainingView, test_step_delay_seconds: float = 0.0,
    test_v1_synthesis_tripwire: bool = False,
) -> V2ExecutionOutcome:
    """H2B0-only compatibility entrypoint; canonical slots remain rejected."""

    if binding.integration_scope != "H2B0_TOY_ONLY":
        raise ValueError("genesis_v2_execution_toy_scope_invalid")
    return run_v2_execution(
        binding=binding, specification=specification, training=training,
        test_step_delay_seconds=test_step_delay_seconds,
        test_v1_synthesis_tripwire=test_v1_synthesis_tripwire,
    )


def run_v2_confirmatory_execution(
    *, binding: V2ExecutionBinding, specification: DSLSpecification,
    training: LearnerTrainingView, test_v1_synthesis_tripwire: bool = False,
) -> V2ExecutionOutcome:
    """H2B1 entrypoint for a predeclared canonical V2 campaign only."""

    if binding.integration_scope != "H2B1_CONFIRMATORY_FROZEN":
        raise ValueError("genesis_v2_execution_confirmatory_scope_invalid")
    return run_v2_execution(
        binding=binding, specification=specification, training=training,
        test_v1_synthesis_tripwire=test_v1_synthesis_tripwire,
    )


def run_v2_fixture_execution(
    *, binding: V2ExecutionBinding, specification: DSLSpecification,
    training: LearnerTrainingView, test_v1_synthesis_tripwire: bool = False,
) -> V2ExecutionOutcome:
    """Noncanonical H2B1 fixture entrypoint; it cannot consume a real slot."""

    if binding.integration_scope != "H2B1_NONCANONICAL_FIXTURE":
        raise ValueError("genesis_v2_execution_fixture_scope_invalid")
    return run_v2_execution(
        binding=binding, specification=specification, training=training,
        test_v1_synthesis_tripwire=test_v1_synthesis_tripwire,
    )


def validate_v2_execution_outcome(
    *, binding: V2ExecutionBinding, outcome: V2ExecutionOutcome,
) -> bool:
    """Validate the non-replayable structural/resource links of one outcome."""

    if not isinstance(binding, V2ExecutionBinding) or not isinstance(outcome, V2ExecutionOutcome):
        return False
    receipt = outcome.receipt
    resource = outcome.resource_receipt
    transcripts = outcome.level_transcripts
    if not (
        binding.validate() and receipt.validate() and resource.validate()
        and receipt.execution_binding_hash == binding.binding_hash
        and receipt.campaign_hash == binding.campaign_hash
        and receipt.task_binding_hash == binding.task_binding_hash
        and receipt.search_policy_hash == binding.search_policy_hash
        and receipt.ranked_engine_policy_hash == binding.ranked_engine_policy.policy_hash
        and receipt.acceptance_policy_hash == binding.acceptance_policy_hash
        and receipt.battery_manifest_hash == binding.battery_manifest_hash
        and receipt.dsl_hash == binding.dsl_hash
        and receipt.resource_receipt_hash == resource.receipt_hash
        and resource.execution_binding_hash == binding.binding_hash
        and resource.configured_raw_ast_cap == binding.max_raw_ast_evaluations
        and resource.configured_behavior_cap == binding.max_distinct_behaviors
        and resource.configured_wall_time_seconds == binding.max_wall_time_seconds
        and resource.configured_peak_memory_mib == binding.max_peak_memory_mib
        and resource.raw_ast_count == receipt.raw_ast_count
        and resource.behavior_class_count == receipt.behavior_class_count
        and all(item.validate() for item in transcripts)
        and receipt.level_transcript_root == _transcript_root(transcripts)
    ):
        return False
    previous_raw = previous_behaviors = 0
    previous_level = 0
    for index, transcript in enumerate(transcripts):
        if not (
            transcript.campaign_hash == binding.campaign_hash
            and transcript.task_binding_hash == binding.task_binding_hash
            and transcript.search_policy_hash == binding.search_policy_hash
            and transcript.ranked_engine_policy_hash == binding.ranked_engine_policy.policy_hash
            and transcript.mdl_level > previous_level
            and transcript.raw_ast_count_cumulative == previous_raw + transcript.raw_ast_count_delta
            and transcript.behavior_classes_cumulative == previous_behaviors + transcript.behavior_classes_delta
        ):
            return False
        if index < len(transcripts) - 1 and not transcript.level_complete:
            return False
        previous_raw = transcript.raw_ast_count_cumulative
        previous_behaviors = transcript.behavior_classes_cumulative
        previous_level = transcript.mdl_level
    if transcripts:
        last = transcripts[-1]
        if (
            receipt.current_level != last.mdl_level
            or receipt.current_level_complete != last.level_complete
            or receipt.raw_ast_count != last.raw_ast_count_cumulative
            or receipt.behavior_class_count != last.behavior_classes_cumulative
        ):
            return False
    elif receipt.current_level is not None or receipt.raw_ast_count or receipt.behavior_class_count:
        return False
    if receipt.termination_reason is V2ExecutionTermination.SELECTED_AFTER_COMPLETE_LEVEL:
        return (
            outcome.selected_candidate is not None
            and outcome.selected_candidate.program_hash == receipt.selected_candidate_hash
            and outcome.selected_candidate.program_ast == receipt.selected_candidate_ast
            and transcripts[-1].selected_candidate_hash == receipt.selected_candidate_hash
            and resource.termination_cause is ResourceTerminationCause.COMPLETED
        )
    return outcome.selected_candidate is None and receipt.selected_candidate_hash is None


def replay_v2_execution(
    *, binding: V2ExecutionBinding, specification: DSLSpecification,
    training: LearnerTrainingView, outcome: V2ExecutionOutcome,
) -> V2ExecutionOutcome:
    """Re-enumerate native V2 semantics and reject any altered receipt/state.

    RSS and elapsed time are observational; for a resource-interrupted run the
    replay stops after the committed number of raw ASTs and proves the stored
    incomplete-level transcript/counters.  It never treats that cutoff as a
    resumable checkpoint or promotes a partial-level candidate.
    """

    if not isinstance(outcome, V2ExecutionOutcome):
        raise ValueError("genesis_v2_execution_replay_version_mismatch")
    if not validate_v2_execution_outcome(binding=binding, outcome=outcome):
        raise ValueError("genesis_v2_execution_replay_receipt_invalid")
    receipt = outcome.receipt
    resource = outcome.resource_receipt
    if not (
        specification.validate() and specification.dsl_hash == binding.dsl_hash
        and training.task_id == binding.task_id
        and receipt.search_semantics_id == SEARCH_SEMANTICS_V2_ID
        and receipt.search_implementation_hash == RANKED_SYNTHESIZER_IMPLEMENTATION_HASH
    ):
        raise ValueError("genesis_v2_execution_replay_version_mismatch")
    cutoff = (
        receipt.raw_ast_count
        if receipt.termination_reason is V2ExecutionTermination.NOT_PROVEN_RESOURCE_EXHAUSTION
        else None
    )
    regenerated = _run_native_v2_search(
        binding=binding, specification=specification, training=training,
        stop_after_raw=cutoff,
    )
    replay_resource = _resource_receipt(
        binding=binding, pid=None, elapsed_ms=0, peak_memory=0,
        raw_count=regenerated.raw_ast_count,
        behavior_count=regenerated.behavior_class_count, cause=resource.termination_cause,
    )
    replayed = V2ExecutionOutcome(
        _make_receipt(
            binding=binding, resource=replay_resource, transcripts=regenerated.transcripts,
            selected=regenerated.selected_candidate, completed_levels=regenerated.completed_levels,
            current_level=regenerated.current_level,
            current_level_complete=regenerated.current_level_complete,
            raw_count=regenerated.raw_ast_count,
            behavior_count=regenerated.behavior_class_count,
            termination=regenerated.termination,
        ),
        replay_resource, tuple(regenerated.transcripts), regenerated.selected_candidate,
    )
    if (
        replayed.receipt.semantic_payload() != receipt.semantic_payload()
        or tuple(item.canonical_payload() for item in replayed.level_transcripts)
        != tuple(item.canonical_payload() for item in outcome.level_transcripts)
        or replayed.resource_receipt.configured_raw_ast_cap != resource.configured_raw_ast_cap
        or replayed.resource_receipt.configured_behavior_cap != resource.configured_behavior_cap
        or replayed.resource_receipt.configured_wall_time_seconds != resource.configured_wall_time_seconds
        or replayed.resource_receipt.configured_peak_memory_mib != resource.configured_peak_memory_mib
    ):
        raise ValueError("genesis_v2_execution_replay_mismatch")
    return replayed


def replay_v2_toy_execution(
    *, binding: V2ExecutionBinding, specification: DSLSpecification,
    training: LearnerTrainingView, outcome: V2ExecutionOutcome,
) -> V2ExecutionOutcome:
    """H2B0-only replay compatibility entrypoint."""

    if binding.integration_scope != "H2B0_TOY_ONLY":
        raise ValueError("genesis_v2_execution_toy_scope_invalid")
    return replay_v2_execution(
        binding=binding, specification=specification, training=training, outcome=outcome,
    )


def replay_v2_confirmatory_execution(
    *, binding: V2ExecutionBinding, specification: DSLSpecification,
    training: LearnerTrainingView, outcome: V2ExecutionOutcome,
) -> V2ExecutionOutcome:
    """H2B1 replay entrypoint, never a second acquisition attempt."""

    if binding.integration_scope != "H2B1_CONFIRMATORY_FROZEN":
        raise ValueError("genesis_v2_execution_confirmatory_scope_invalid")
    return replay_v2_execution(
        binding=binding, specification=specification, training=training, outcome=outcome,
    )


def replay_v2_fixture_execution(
    *, binding: V2ExecutionBinding, specification: DSLSpecification,
    training: LearnerTrainingView, outcome: V2ExecutionOutcome,
) -> V2ExecutionOutcome:
    """Replay only a noncanonical H2B1 integration fixture."""

    if binding.integration_scope != "H2B1_NONCANONICAL_FIXTURE":
        raise ValueError("genesis_v2_execution_fixture_scope_invalid")
    return replay_v2_execution(
        binding=binding, specification=specification, training=training, outcome=outcome,
    )
